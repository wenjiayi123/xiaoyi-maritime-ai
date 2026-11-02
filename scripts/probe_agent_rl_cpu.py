"""Bounded real CPU forward/backward probe; does not overwrite any model."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model

    torch.set_num_threads(args.threads)
    torch.manual_seed(20261101)
    base = (
        Path.home()
        / ".cache/huggingface/hub/models--Qwen--Qwen3-1.7B/snapshots/70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
    )
    report = {
        "schema": "xiaoyi-agent-rl-cpu-probe.v1",
        "platform": platform.platform(),
        "model": str(base),
        "training_claim": "performance_probe_only",
        "threads": args.threads,
    }
    started = time.monotonic()
    tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        base, local_files_only=True, torch_dtype=torch.float32, low_cpu_mem_usage=True, attn_implementation="eager"
    )
    report["load_seconds"] = round(time.monotonic() - started, 3)
    model.config.use_cache = False
    layers = list(range(model.config.num_hidden_layers - 4, model.config.num_hidden_layers))
    model = get_peft_model(
        model,
        LoraConfig(
            r=8,
            lora_alpha=16,
            lora_dropout=0.0,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=["q_proj", "v_proj"],
            layers_to_transform=layers,
        ),
    )
    params = [p for p in model.parameters() if p.requires_grad]
    report["trainable_parameters"] = sum(p.numel() for p in params)
    prompt = tokenizer.apply_chat_template(
        [
            {"role": "system", "content": "选择下一项操作，只回答选项字母。"},
            {
                "role": "user",
                "content": "任务：比较能碳方案，绿色偏好0.82。状态：尚未读取能碳数据。A:读取港口 B:读取能碳 C:试算0.82 D:完成",
            },
        ],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    batch = tokenizer(prompt, return_tensors="pt")
    report["input_tokens"] = batch["input_ids"].shape[1]
    report["choice_token_ids"] = {s: tokenizer.encode(s, add_special_tokens=False) for s in "ABCDEFGH"}
    started = time.monotonic()
    model.eval()
    with torch.no_grad():
        logits = model(**batch).logits[0, -1]
    report["forward_seconds"] = round(time.monotonic() - started, 3)
    report["choice_logits"] = {s: float(logits[ids[0]]) for s, ids in report["choice_token_ids"].items()}
    del logits

    def fingerprint():
        h = hashlib.sha256()
        for p in params:
            h.update(p.detach().numpy().tobytes())
        return h.hexdigest()

    report["adapter_before"] = fingerprint()
    optimizer = torch.optim.AdamW(params, lr=1e-4)
    model.train()
    started = time.monotonic()
    ids = [report["choice_token_ids"][s][0] for s in "ABCD"]
    logits = model(**batch).logits[0, -1, ids]
    loss = torch.nn.functional.cross_entropy(logits.unsqueeze(0), torch.tensor([1]))
    loss.backward()
    torch.nn.utils.clip_grad_norm_(params, 1.0)
    optimizer.step()
    report["forward_backward_seconds"] = round(time.monotonic() - started, 3)
    report["probe_loss"] = float(loss.detach())
    report["adapter_after"] = fingerprint()
    report["parameter_update_observed"] = report["adapter_before"] != report["adapter_after"]
    report["total_seconds"] = round(time.monotonic() - started, 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
