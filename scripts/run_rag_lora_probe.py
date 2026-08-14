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
DEFAULT_QUESTION = "船期 ETA 变了怎么更新？"


def _artifact(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": digest,
    }


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    request_payload = {
        "question": args.question,
        "mode": "expert",
        "top_k": 5,
        "strict_evidence": True,
        "session_id": f"rag-lora-probe-{uuid4().hex[:12]}",
    }
    request = Request(
        f"{args.base_url.rstrip('/')}/api/chat",
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    started_at = datetime.now(timezone.utc)
    started = time.monotonic()
    with urlopen(request, timeout=args.timeout_seconds) as response:
        body = json.loads(response.read(20_000_000))
    report = {
        "schema_version": "1.0",
        "probe_id": f"rag-lora-{uuid4().hex[:12]}",
        "status": "completed",
        "started_at": started_at.isoformat(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "request": request_payload,
        "response": body,
        "evidence": {
            "local_lora_inference": _artifact(
                ROOT / "reports" / "local_lora_inference_v3.json"
            ),
            "model_registry": _artifact(ROOT / "data" / "model_registry.json"),
            "knowledge_index": _artifact(ROOT / "data" / "xiaoyi_index.json"),
        },
        "claim_boundary": (
            "This probe verifies local RAG retrieval, LoRA-backed generation and "
            "post-answer evidence reporting on one engineering case. It is not a "
            "production-port or independently validated quality benchmark."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = args.output.with_name(f".{args.output.name}.{uuid4().hex}.tmp")
    temp_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="记录小懿RAG + 本地LoRA生成 + 回答后证据报告的端到端探针"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "local_rag_lora_e2e_v3.json",
    )
    args = parser.parse_args()
    run_probe(args)


if __name__ == "__main__":
    main()
