"""Bounded hardware probe on ONE real Qwen decoder layer; never changes a run.

This is not a full-model training benchmark. CPU development continues separately.
"""

from __future__ import annotations
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "0"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.policy import BASE, SYSTEM  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    args = parser.parse_args()
    out = args.experiment / "mps-single-layer-probe.json"
    if out.exists():
        raise ValueError("probe result already exists")
    result = {
        "scope": "one real Qwen3 layer with inherited C LoRA; not full LLM or RL training",
        "main_run_modified": False,
        "cpu_fallback": False,
        "concurrent_cpu_training": True,
        "start": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        import numpy as np
        import torch
        from peft import LoraConfig, get_peft_model
        from safetensors import safe_open
        from safetensors.torch import load_file
        from transformers import AutoTokenizer, Qwen3Config
        from transformers.models.qwen3.modeling_qwen3 import Qwen3DecoderLayer, Qwen3RotaryEmbedding

        torch.set_num_threads(1)
        result["mps_available"] = torch.backends.mps.is_available()
        if not result["mps_available"]:
            raise RuntimeError("MPS unavailable")
        record = json.loads((args.experiment / "training-states.json").read_text())[0]
        tokenizer = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
        text = tokenizer.apply_chat_template(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": record["prompt"]}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        ids = tokenizer(text, return_tensors="pt")["input_ids"]
        token_hash = hashlib.sha256(ids.numpy().tobytes()).hexdigest()
        files = list((args.experiment.parent / "frozen-prefix-cache").glob("*/" + token_hash + ".npy"))
        if len(files) != 1:
            raise ValueError("unique existing frozen prefix needed")
        hidden = torch.from_numpy(np.load(files[0], allow_pickle=False))
        config = Qwen3Config.from_pretrained(BASE, local_files_only=True)
        config._attn_implementation = "eager"

        class SingleLayer(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.config = config
                self.layer = Qwen3DecoderLayer(config, 24)

            def forward(self, hidden_states, **kwargs):
                return self.layer(hidden_states, **kwargs)[0]

        base = SingleLayer()
        index = json.loads((BASE / "model.safetensors.index.json").read_text())["weight_map"]
        prefix = "model.layers.24."
        tensors = {}
        for shard in sorted({v for k, v in index.items() if k.startswith(prefix)}):
            with safe_open(str(BASE / shard), framework="pt", device="cpu") as file:
                for key in file.keys():
                    if key.startswith(prefix):
                        tensors[key[len(prefix) :]] = file.get_tensor(key).float()
        base.layer.load_state_dict(tensors, strict=True)
        del tensors
        gc.collect()
        model = get_peft_model(
            base, LoraConfig(r=8, lora_alpha=16, lora_dropout=0.0, target_modules=["q_proj", "v_proj"], bias="none")
        )
        adapter = load_file(str(args.experiment / "checkpoints/sft/adapter_model.safetensors"))
        with torch.no_grad():
            for projection in ["q_proj", "v_proj"]:
                module = getattr(base.layer.self_attn, projection)
                for side in ["A", "B"]:
                    suffix = f".layers.24.self_attn.{projection}.lora_{side}.weight"
                    key = next(k for k in adapter if k.endswith(suffix))
                    getattr(module, "lora_" + side)["default"].weight.copy_(adapter[key])
        del adapter
        model.eval()
        seq = hidden.shape[1]
        positions = torch.arange(seq).unsqueeze(0)
        mask = torch.full((seq, seq), torch.finfo(torch.float32).min).triu(diagonal=1)[None, None]
        cos, sin = Qwen3RotaryEmbedding(config)(hidden, positions)
        params = [p for p in model.parameters() if p.requires_grad]
        result["trainable_probe_parameters"] = sum(p.numel() for p in params)

        def run(device):
            model.to(device)
            h = hidden.to(device)
            kwargs = {
                "attention_mask": mask.to(device),
                "position_embeddings": (cos.to(device), sin.to(device)),
                "use_cache": False,
            }
            times = []
            outputs = []
            gradients = []
            for i in range(3):
                model.zero_grad(set_to_none=True)
                if device == "mps":
                    torch.mps.synchronize()
                tick = time.monotonic()
                value = model(hidden_states=h, **kwargs)
                loss = value[:, -1].square().mean()
                loss.backward()
                if device == "mps":
                    torch.mps.synchronize()
                times.append(time.monotonic() - tick)
                if i == 2:
                    outputs = value.detach().cpu()
                    gradients = [p.grad.detach().cpu().clone() for p in params]
            return times, outputs, gradients

        cpu, cpu_out, cpu_grad = run("cpu")
        mps, mps_out, mps_grad = run("mps")
        result.update(
            cpu_seconds=cpu,
            mps_seconds=mps,
            output_max_absolute_difference=float((cpu_out - mps_out).abs().max()),
            gradient_max_absolute_difference=max(float((a - b).abs().max()) for a, b in zip(cpu_grad, mps_grad)),
            output_close=bool(torch.allclose(cpu_out, mps_out, atol=1e-4, rtol=1e-3)),
            gradients_close=all(torch.allclose(a, b, atol=1e-4, rtol=1e-3) for a, b in zip(cpu_grad, mps_grad)),
            finite=bool(torch.isfinite(mps_out).all()) and all(bool(torch.isfinite(g).all()) for g in mps_grad),
            status="completed",
            input_tokens=seq,
        )
    except Exception as exc:
        result.update(status="failed", error=repr(exc))
    result["end"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
