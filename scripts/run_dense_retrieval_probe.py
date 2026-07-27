from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="记录0.6B-Embedding稠密向量索引的本地查询探针"
    )
    parser.add_argument("--query", default="船期 ETA 变了怎么更新？")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "local_dense_retrieval_v1.json",
    )
    args = parser.parse_args()

    from app.retrieval import load_chunks
    from app.vector_retrieval import DenseVectorIndex

    chunks = load_chunks()
    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    index = DenseVectorIndex()
    started_at = datetime.now(timezone.utc)
    started = time.monotonic()
    scores = index.scores(args.query, chunks)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    index_status = index.status()
    try:
        index_status["index_path"] = (
            Path(index_status["index_path"]).relative_to(ROOT).as_posix()
        )
    except (KeyError, ValueError):
        pass
    report = {
        "schema_version": "1.0",
        "probe_id": f"dense-retrieval-{uuid4().hex[:12]}",
        "status": "completed",
        "started_at": started_at.isoformat(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "query": args.query,
        "index_status": index_status,
        "top_results": [
            {
                "rank": rank,
                "score": round(score, 6),
                "chunk_id": chunk_id,
                "title": chunks_by_id[chunk_id].title,
                "content_hash": chunks_by_id[chunk_id].content_hash,
            }
            for rank, (chunk_id, score) in enumerate(
                ranked[: max(1, args.top_k)],
                start=1,
            )
        ],
        "evidence": {
            "vector_index": _artifact(
                ROOT / "data" / "xiaoyi_vector_index.json"
            ),
            "embedding_model_receipt": _artifact(
                ROOT
                / ".runtime"
                / "models"
                / "xiaoyi-embedding-0.6b-q8-0.receipt.json"
            ),
        },
        "claim_boundary": (
            "Cosine similarity is a retrieval signal only. This single query proves "
            "that the local 1024-dimensional index and query encoder work together; "
            "it is not a retrieval-quality, entailment, or answer-accuracy benchmark."
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


if __name__ == "__main__":
    main()
