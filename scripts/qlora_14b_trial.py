"""Bounded one-GPU, offline Qwen3-14B QLoRA pilot. Default action is preflight."""
import argparse
import hashlib
import json
import random
import re
import time
from pathlib import Path

DATASET_MANIFEST = "5022e30fd0dcb06d789312128c2c5d121b1377f3b942c25cd7ea36d3e9301594"


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_data(folder):
    manifest = folder/"manifest.json"
    if file_hash(manifest) != DATASET_MANIFEST:
        raise ValueError("Dataset version differs from the audited GullMate v5 dataset")
    metadata = json.loads(manifest.read_bytes())
    digests = {Path(k).name:v for k,v in metadata["artifact_sha256"].items()}
    for split in ("train", "validation", "test"):
        name = split+".jsonl"
        if file_hash(folder/name) != digests[name]:
            raise ValueError(f"Partition integrity failure: {split}")
    return metadata, digests


def checked_rows(folder,name,digests):
    raw=(folder/name).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=digests[name]:
        raise ValueError(f"Partition changed while reading: {name}")
    return [json.loads(line) for line in raw.splitlines() if line]


def inspect_model(folder):
    if folder is None:
        return ["Provide a local, pinned Qwen3-14B Hugging Face snapshot"]
    config=json.loads((folder/"config.json").read_bytes())
    if (config.get("model_type"),config.get("hidden_size"),config.get("num_hidden_layers"))!=("qwen3",5120,40):
        return ["The supplied snapshot does not match the official Qwen3-14B configuration"]
    index=json.loads((folder/"model.safetensors.index.json").read_bytes())
    shards=set(index["weight_map"].values())
    if any(Path(k).name!=k or not (folder/k).is_file() for k in shards):
        return ["Missing or invalid model shard"]
    if not re.fullmatch(r"[a-f0-9]{40}",folder.resolve().name):
        return ["Use the pinned 40-character Hugging Face snapshot directory"]
    return []


def encode(row,tokenizer,torch,device):
    messages=row["messages"]
    if messages[-1]["role"]!="assistant":
        raise ValueError("Final answer required")
    prompt=tokenizer.apply_chat_template(messages[:-1],tokenize=True,add_generation_prompt=True,enable_thinking=False)
    answer=tokenizer.encode(messages[-1]["content"],add_special_tokens=False)[:255]+[tokenizer.eos_token_id]
    prefix=prompt[-(512-len(answer)):]
    return {"input_ids":torch.tensor([prefix+answer],device=device),
            "labels":torch.tensor([[-100]*len(prefix)+answer],device=device)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data",type=Path,required=True)
    p.add_argument("--model",type=Path)
    p.add_argument("--output",type=Path)
    p.add_argument("--train",action="store_true")
    args=p.parse_args()
    start=time.monotonic()
    metadata,digests=check_data(args.data)
    blockers=inspect_model(args.model)
    import importlib.util
    for package in ("bitsandbytes","torch","peft","accelerate","transformers"):
        if importlib.util.find_spec(package) is None:
            blockers.append("Missing "+package)
    if importlib.util.find_spec("torch"):
        import torch
        if not torch.cuda.is_available():
            blockers.append("CUDA unavailable")
        elif torch.cuda.mem_get_info()[0] < 20*(1024**3):
            blockers.append("Pilot requires 20 GiB free GPU memory under this job's resource budget")
    protocol={"dataset":metadata["dataset_id"],"split_counts":metadata["split_counts"],"seq_len":512,
              "step_limit":40,"grad_accumulation":4,"seed":17,"wall_budget_minutes":60,"pilot_blockers":blockers}
    print(json.dumps(protocol,indent=2),flush=True)
    if not args.train:return
    if blockers or not args.output:
        raise SystemExit("Training requires successful preflight and a new output path")
    args.output.mkdir(parents=True,exist_ok=False)
    protocol["base_revision"]=args.model.resolve().name
    protocol["base_file_sha256"]={s.name:file_hash(s) for s in sorted(args.model.iterdir())
                                  if s.is_file() and s.suffix in {".safetensors",".json",".txt"}}
    (args.output/"protocol.json").write_text(json.dumps(protocol,indent=2),encoding="utf-8")
    from transformers import AutoTokenizer,AutoModelForCausalLM,BitsAndBytesConfig
    from peft import LoraConfig,get_peft_model,prepare_model_for_kbit_training
    torch.manual_seed(17)
    torch.cuda.manual_seed_all(17)
    rng=random.Random(17)
    dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    quant=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type="nf4",bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=dtype)
    tokenizer=AutoTokenizer.from_pretrained(args.model,local_files_only=True)
    model=AutoModelForCausalLM.from_pretrained(args.model,local_files_only=True,quantization_config=quant,
        torch_dtype=dtype,device_map={"":0})
    model.config.use_cache=False
    model=prepare_model_for_kbit_training(model,use_gradient_checkpointing=True)
    model=get_peft_model(model,LoraConfig(r=8,lora_alpha=16,target_modules=["q_proj","v_proj"],task_type="CAUSAL_LM"))
    optimizer=torch.optim.AdamW([v for v in model.parameters() if v.requires_grad],lr=1e-4)
    train=checked_rows(args.data,"train.jsonl",digests)
    valid=checked_rows(args.data,"validation.jsonl",digests)
    def loss(rows):
        model.eval()
        with torch.no_grad():
            return sum(float(model(**encode(row,tokenizer,torch,"cuda")).loss) for row in rows[:8])/min(len(rows),8)
    before=loss(valid)
    model.train()
    curve=[]
    for step in range(40):
        if time.monotonic()-start>=3300:break
        optimizer.zero_grad()
        total=0.0
        for row in rng.sample(train,4):
            l=model(**encode(row,tokenizer,torch,"cuda")).loss
            if not torch.isfinite(l):raise ValueError("Nonfinite loss")
            (l/4).backward()
            total+=l.detach().item()/4
        torch.nn.utils.clip_grad_norm_(model.parameters(),1.0,error_if_nonfinite=True)
        optimizer.step()
        curve.append(total)
        print(step+1,round(total,5),flush=True)
    if not curve:raise RuntimeError("No optimizer steps within budget")
    model.save_pretrained(args.output/"adapter",safe_serialization=True)
    report={"validation_before":before,"validation_after":loss(valid),"train_losses":curve,
            "peak_cuda_bytes":torch.cuda.max_memory_allocated(),
            "adapter_sha256":file_hash(args.output/"adapter/adapter_model.safetensors"),
            "actual_steps":len(curve),"full_budget_completed":len(curve)==40,
            "elapsed_seconds":time.monotonic()-start,"production_promotion":False}
    (args.output/"result.json").write_text(json.dumps(report,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()
