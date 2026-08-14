from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPT = "船舶预计晚到但没有最新ETA时，值班员应该怎么处理？"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        relative = path.relative_to(ROOT).as_posix()
    except ValueError:
        relative = str(path)
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _training_summary(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    dataset = dict(payload.get("dataset") or {})
    directory = dataset.get("directory")
    if directory:
        try:
            dataset["directory"] = Path(directory).relative_to(ROOT).as_posix()
        except ValueError:
            dataset["directory"] = str(directory)
    return {
        "run_id": payload.get("run_id"),
        "status": payload.get("status"),
        "base_model": payload.get("base_model"),
        "dataset": dataset,
        "lora": payload.get("lora"),
        "training": payload.get("training"),
        "adapter_sha256": (payload.get("artifacts") or {}).get("adapter_sha256"),
        "claim_boundary": payload.get("claim_boundary"),
    }


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是港航专业助手小懿。自然、简洁、专业地回答；"
                    "不得编造实时数据。/no_think"
                ),
            },
            {"role": "user", "content": args.prompt},
        ],
        "temperature": 0.2,
        "max_tokens": args.max_tokens,
    }
    request = Request(
        f"{args.base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    started_at = datetime.now(timezone.utc)
    started = time.monotonic()
    with urlopen(request, timeout=args.timeout_seconds) as response:
        body = json.loads(response.read(10_000_000))
    elapsed = time.monotonic() - started
    choice = body["choices"][0]
    training_report_path = (
        ROOT
        / "artifacts"
        / "lora"
        / "xiaoyi-maritime-1.7b-r96-v3"
        / "training_report.json"
    )
    report = {
        "schema_version": "1.0",
        "probe_id": f"local-generation-{uuid4().hex[:12]}",
        "status": "completed",
        "profile": args.profile,
        "started_at": started_at.isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "request": {
            "model": args.model,
            "prompt": args.prompt,
            "temperature": 0.2,
            "max_tokens": args.max_tokens,
        },
        "response": {
            "model": body.get("model"),
            "system_fingerprint": body.get("system_fingerprint"),
            "finish_reason": choice.get("finish_reason"),
            "content": choice.get("message", {}).get("content"),
            "usage": body.get("usage"),
            "timings": body.get("timings"),
        },
        "evidence": {
            "model_registry": _artifact(ROOT / "data" / "model_registry.json"),
            "dataset_manifest": _artifact(
                ROOT
                / ".runtime"
                / "finetuning"
                / "xiaoyi-maritime-sft-v3"
                / "manifest.json"
            ),
            "training_report": _artifact(
                training_report_path
            ),
            "lora_gguf": _artifact(
                ROOT
                / "artifacts"
                / "lora"
                / "xiaoyi-maritime-1.7b-r96-v3"
                / "xiaoyi-maritime-1.7b-r96-v3-f16.gguf"
            ),
        },
        "training_summary": _training_summary(training_report_path),
        "claim_boundary": (
            "This probe proves that a pinned local model profile produced tokens through "
            "the OpenAI-compatible runtime. It is not an accuracy, independently validated quality, "
            "production-port, or legal-correctness benchmark."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = args.output.with_name(f".{args.output.name}.{uuid4().hex}.tmp")
    temp_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(args.output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="记录本地open-weight生成或LoRA加载的可复核推理探针"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:11435/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--profile", choices=["base", "lora"], required=True)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--max-tokens", type=int, default=160)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_probe(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
