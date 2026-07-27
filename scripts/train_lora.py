from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data" / "model_registry.json"
DEFAULT_DATASET = ROOT / ".runtime" / "finetuning" / "xiaoyi-maritime-sft-v1"
DEFAULT_OUTPUT = ROOT / "artifacts" / "lora" / "xiaoyi-maritime-1.7b"
DEFAULT_BASE_MODEL = ROOT / ".runtime" / "models" / "maritime-training-1.7b"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _physical_memory_bytes() -> int | None:
    if platform.system() == "Darwin":
        try:
            return int(
                subprocess.check_output(
                    ["sysctl", "-n", "hw.memsize"],
                    text=True,
                ).strip()
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
    return None


def preflight() -> dict[str, Any]:
    contract = _training_contract()
    intel_mac = platform.system() == "Darwin" and platform.machine() == "x86_64"
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "physical_memory_bytes": _physical_memory_bytes(),
        "base_model": contract,
        "recommended_dependency_file": (
            "requirements-lora-intel-mac.lock"
            if intel_mac
            else "requirements-lora.txt"
        ),
        "default_run_scope": (
            "local_engineering_smoke"
            if intel_mac
            else "recorded_lora_experiment"
        ),
        "boundary": (
            "This Intel 16GB Mac can attempt a very short 1.7B CPU LoRA "
            "engineering run. Use Linux/NVIDIA QLoRA for a full experiment; "
            "never report a smoke loss as domain-model quality."
            if intel_mac
            else "Verify accelerator memory and dependency compatibility before training."
        ),
    }


def _training_contract() -> dict[str, Any]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    training_id = registry["local_training_model_id"]
    model = next(item for item in registry["models"] if item["model_id"] == training_id)
    source_env = str(model.get("training_source_env") or "XIAOYI_LORA_BASE_MODEL")
    revision_env = str(
        model.get("training_revision_env") or "XIAOYI_LORA_BASE_REVISION"
    )
    source = os.getenv(source_env, "").strip() or str(DEFAULT_BASE_MODEL)
    revision = os.getenv(revision_env, "").strip() or None
    return {
        "model_id": source,
        "revision": revision,
        "artifact_profile": model["upstream_model"],
        "inference_model_id": model["model_id"],
        "license": model["license"],
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _require_dependencies() -> tuple[Any, ...]:
    try:
        import torch
        from peft import LoraConfig, get_peft_model
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise SystemExit(
            "LoRA依赖未安装。先创建独立环境并运行：\n"
            "python3 -m venv .venv-lora\n"
            ".venv-lora/bin/python -m pip install -r requirements-lora-intel-mac.lock"
        ) from exc
    return torch, LoraConfig, get_peft_model, AutoModelForCausalLM, AutoTokenizer


def _encode_example(tokenizer: Any, item: dict[str, Any], max_length: int) -> dict[str, Any]:
    messages = item["messages"]
    prompt_ids = tokenizer.apply_chat_template(
        messages[:-1],
        tokenize=True,
        add_generation_prompt=True,
    )
    full_ids = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=False,
    )
    assistant_ids = full_ids[len(prompt_ids) :]
    if not assistant_ids:
        raise ValueError("聊天模板没有产生可训练的assistant token")

    # 长样本不能简单从尾部截断，否则可能只剩prompt、全部label均为-100，
    # 产生NaN损失。保留问题末尾和至少一部分答案，确保每条样本都有监督信号。
    assistant_budget = min(len(assistant_ids), max(1, max_length // 2))
    prompt_budget = max_length - assistant_budget
    selected_prompt = prompt_ids[-prompt_budget:] if prompt_budget else []
    selected_assistant = assistant_ids[:assistant_budget]
    input_ids = selected_prompt + selected_assistant
    labels = [-100] * len(selected_prompt) + selected_assistant
    return {"input_ids": input_ids, "labels": labels}


def _collate(torch: Any, tokenizer: Any, items: list[dict[str, Any]]) -> dict[str, Any]:
    max_length = max(len(item["input_ids"]) for item in items)
    pad_id = tokenizer.pad_token_id
    input_ids: list[list[int]] = []
    attention_mask: list[list[int]] = []
    labels: list[list[int]] = []
    for item in items:
        padding = max_length - len(item["input_ids"])
        input_ids.append(item["input_ids"] + [pad_id] * padding)
        attention_mask.append([1] * len(item["input_ids"]) + [0] * padding)
        labels.append(item["labels"] + [-100] * padding)
    return {
        "input_ids": torch.tensor(input_ids, dtype=torch.long),
        "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
        "labels": torch.tensor(labels, dtype=torch.long),
    }


def _mean_loss(
    model: Any,
    batches: list[dict[str, Any]],
    torch: Any,
    device: Any,
    limit: int,
) -> float | None:
    if not batches:
        return None
    model.eval()
    losses: list[float] = []
    with torch.no_grad():
        for batch in batches[:limit]:
            prepared = {key: value.to(device) for key, value in batch.items()}
            losses.append(float(model(**prepared).loss.detach().cpu()))
    model.train()
    return sum(losses) / len(losses)


def train(args: argparse.Namespace) -> dict[str, Any]:
    torch, LoraConfig, get_peft_model, AutoModelForCausalLM, AutoTokenizer = (
        _require_dependencies()
    )
    contract = _training_contract()
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device(args.device)
    if args.device == "mps" and not torch.backends.mps.is_available():
        raise SystemExit("当前PyTorch环境没有可用MPS后端")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("当前PyTorch环境没有可用CUDA后端")

    train_path = args.dataset_dir / "train.jsonl"
    validation_path = args.dataset_dir / "validation.jsonl"
    test_path = args.dataset_dir / "test.jsonl"
    if (
        not train_path.is_file()
        or not validation_path.is_file()
        or not test_path.is_file()
    ):
        raise SystemExit("LoRA数据集不存在；先运行 scripts/build_lora_dataset.py")
    train_items = _load_jsonl(train_path)
    validation_items = _load_jsonl(validation_path)
    test_items = _load_jsonl(test_path)
    if not train_items:
        raise SystemExit("训练分区为空")

    tokenizer = AutoTokenizer.from_pretrained(
        contract["model_id"],
        revision=contract["revision"],
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    encoded_train = [
        _encode_example(tokenizer, item, args.max_length) for item in train_items
    ]
    encoded_validation = [
        _encode_example(tokenizer, item, args.max_length) for item in validation_items
    ]
    encoded_test = [
        _encode_example(tokenizer, item, args.max_length) for item in test_items
    ]
    train_batches = [
        _collate(torch, tokenizer, [item]) for item in encoded_train
    ]
    validation_batches = [
        _collate(torch, tokenizer, [item]) for item in encoded_validation
    ]
    test_batches = [
        _collate(torch, tokenizer, [item]) for item in encoded_test
    ]

    dtype = torch.float32 if args.device == "cpu" else torch.float16
    model = AutoModelForCausalLM.from_pretrained(
        contract["model_id"],
        revision=contract["revision"],
        torch_dtype=dtype,
        low_cpu_mem_usage=True,
    )
    model.config.use_cache = False
    model.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False}
    )
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()
    lora_config = LoraConfig(
        r=args.rank,
        lora_alpha=args.alpha,
        lora_dropout=args.dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    )
    model = get_peft_model(model, lora_config)
    model.to(device)
    trainable_parameters = sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )
    all_parameters = sum(parameter.numel() for parameter in model.parameters())
    optimizer = torch.optim.AdamW(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=args.learning_rate,
    )

    started_at = datetime.now(timezone.utc)
    started = time.monotonic()
    before_validation_loss = _mean_loss(
        model,
        validation_batches,
        torch,
        device,
        args.validation_cases,
    )
    before_test_loss = _mean_loss(
        model,
        test_batches,
        torch,
        device,
        args.test_cases,
    )
    losses: list[float] = []
    model.train()
    optimizer.zero_grad(set_to_none=True)
    order = list(range(len(train_batches)))
    random.shuffle(order)
    for step in range(args.max_steps):
        batch = train_batches[order[step % len(order)]]
        prepared = {key: value.to(device) for key, value in batch.items()}
        loss = model(**prepared).loss
        loss.backward()
        torch.nn.utils.clip_grad_norm_(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            args.max_grad_norm,
        )
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        value = float(loss.detach().cpu())
        losses.append(value)
        print(f"step={step + 1}/{args.max_steps} loss={value:.6f}", flush=True)

    after_validation_loss = _mean_loss(
        model,
        validation_batches,
        torch,
        device,
        args.validation_cases,
    )
    after_test_loss = _mean_loss(
        model,
        test_batches,
        torch,
        device,
        args.test_cases,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.output_dir, safe_serialization=True)
    tokenizer.save_pretrained(args.output_dir)
    adapter_path = args.output_dir / "adapter_model.safetensors"
    finished_at = datetime.now(timezone.utc)
    report = {
        "schema_version": "1.0",
        "run_id": f"lora-{started_at.strftime('%Y%m%dT%H%M%SZ')}",
        "status": "completed",
        "base_model": contract,
        "adapter_compatible_inference_model": contract["inference_model_id"],
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "device": args.device,
        },
        "dataset": {
            "directory": str(args.dataset_dir),
            "train_examples": len(train_items),
            "validation_examples": len(validation_items),
            "test_examples": len(test_items),
            "train_sha256": _sha256_file(train_path),
            "validation_sha256": _sha256_file(validation_path),
            "test_sha256": _sha256_file(test_path),
        },
        "lora": {
            "rank": args.rank,
            "alpha": args.alpha,
            "dropout": args.dropout,
            "trainable_parameters": trainable_parameters,
            "all_parameters": all_parameters,
            "trainable_percent": round(
                100.0 * trainable_parameters / all_parameters,
                6,
            ),
        },
        "training": {
            "seed": args.seed,
            "max_steps": args.max_steps,
            "max_length": args.max_length,
            "learning_rate": args.learning_rate,
            "losses": losses,
            "initial_validation_loss": before_validation_loss,
            "final_validation_loss": after_validation_loss,
            "initial_test_loss": before_test_loss,
            "final_test_loss": after_test_loss,
            "validation_cases": min(args.validation_cases, len(validation_batches)),
            "test_cases": min(args.test_cases, len(test_batches)),
            "duration_seconds": round(time.monotonic() - started, 3),
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
        },
        "artifacts": {
            "adapter_path": str(adapter_path),
            "adapter_sha256": _sha256_file(adapter_path),
        },
        "claim_boundary": (
            "This is a local SFT/LoRA engineering run. Loss is an optimization "
            "signal, not proof of answer accuracy, field performance, or legal correctness."
        ),
    }
    (args.output_dir / "training_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="在与本地推理同架构的1.7B本地权重上执行可审计LoRA训练"
    )
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", choices=["cpu", "mps", "cuda"], default="cpu")
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument("--max-length", type=int, default=96)
    parser.add_argument("--validation-cases", type=int, default=1)
    parser.add_argument("--test-cases", type=int, default=1)
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--alpha", type=int, default=16)
    parser.add_argument("--dropout", type=float, default=0.05)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--max-grad-norm", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="只输出本机训练边界，不导入PyTorch或下载训练权重",
    )
    args = parser.parse_args()
    if args.preflight:
        print(json.dumps(preflight(), ensure_ascii=False, indent=2))
        return
    if args.max_steps < 1 or args.max_length < 32:
        raise SystemExit("max-steps必须大于0，max-length必须至少32")
    train(args)


if __name__ == "__main__":
    main()
