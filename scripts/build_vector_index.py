from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_CHECKPOINT_PATH = (
    ROOT / ".runtime" / "vector-index" / "xiaoyi-dense-vector-v1.jsonl"
)

from app.config import VECTOR_INDEX_PATH  # noqa: E402
from app.retrieval import load_chunks  # noqa: E402
from app.vector_retrieval import EmbeddingClient  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checkpoint_records(
    checkpoint_path: Path,
    *,
    model: str,
    content_hash_by_id: dict[str, str],
) -> dict[str, dict[str, Any]]:
    if not checkpoint_path.is_file():
        return {}
    records: dict[str, dict[str, Any]] = {}
    try:
        lines = checkpoint_path.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        if (
            header.get("schema_version") != "1.0"
            or header.get("model") != model
        ):
            return {}
        for line in lines[1:]:
            try:
                item = json.loads(line)
                chunk_id = str(item["chunk_id"])
                if content_hash_by_id.get(chunk_id) != str(item["content_hash"]):
                    continue
                vector = [float(value) for value in item["vector"]]
                if vector:
                    records[chunk_id] = {
                        "chunk_id": chunk_id,
                        "content_hash": str(item["content_hash"]),
                        "vector": vector,
                    }
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
    except (IndexError, OSError, TypeError, json.JSONDecodeError):
        return {}
    return records


def _initialize_checkpoint(checkpoint_path: Path, *, model: str) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "index_id": "xiaoyi-dense-vector-v1",
                "model": model,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _append_checkpoint(
    checkpoint_path: Path,
    records: list[dict[str, Any]],
) -> None:
    if checkpoint_path.stat().st_size:
        with checkpoint_path.open("rb") as stream:
            stream.seek(-1, 2)
            terminated = stream.read(1) == b"\n"
    else:
        terminated = True
    with checkpoint_path.open("a", encoding="utf-8") as stream:
        if not terminated:
            stream.write("\n")
        for item in records:
            stream.write(
                json.dumps(
                    item,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
        stream.flush()


def build_vector_index(
    *,
    base_url: str,
    model: str,
    output_path: Path = VECTOR_INDEX_PATH,
    checkpoint_path: Path = DEFAULT_CHECKPOINT_PATH,
    batch_size: int = 8,
    timeout_seconds: float = 120.0,
    max_new_chunks: int | None = None,
) -> dict[str, Any]:
    chunks = load_chunks()
    content_hash_by_id = {
        str(chunk.id): str(chunk.content_hash) for chunk in chunks
    }
    client = EmbeddingClient(
        base_url,
        model,
        timeout_seconds=timeout_seconds,
    )
    records_by_id = _checkpoint_records(
        checkpoint_path,
        model=model,
        content_hash_by_id=content_hash_by_id,
    )
    if not records_by_id:
        _initialize_checkpoint(checkpoint_path, model=model)
    pending = [chunk for chunk in chunks if chunk.id not in records_by_id]
    dimensions: int | None = None
    if records_by_id:
        dimensions = len(next(iter(records_by_id.values()))["vector"])
        print(
            f"vector-index: resume {len(records_by_id)}/{len(chunks)}",
            flush=True,
        )
    if max_new_chunks is not None:
        pending = pending[:max_new_chunks]
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        vectors = client.embed(
            [f"{chunk.title}\n{chunk.text}" for chunk in batch],
            query=False,
        )
        checkpoint_batch: list[dict[str, Any]] = []
        for chunk, vector in zip(batch, vectors):
            dimensions = dimensions or len(vector)
            if len(vector) != dimensions:
                raise ValueError("embedding维度在同一索引中发生变化")
            record = {
                "chunk_id": chunk.id,
                "content_hash": chunk.content_hash,
                "vector": vector,
            }
            records_by_id[chunk.id] = record
            checkpoint_batch.append(record)
        _append_checkpoint(checkpoint_path, checkpoint_batch)
        print(
            f"vector-index: {len(records_by_id)}/{len(chunks)}",
            flush=True,
        )
    if len(records_by_id) < len(chunks):
        return {
            "schema_version": "1.0",
            "index_id": "xiaoyi-dense-vector-v1",
            "status": "checkpointed",
            "model": model,
            "completed_chunk_count": len(records_by_id),
            "target_chunk_count": len(chunks),
            "dimensions": dimensions,
            "checkpoint_path": str(checkpoint_path),
        }
    records = [records_by_id[chunk.id] for chunk in chunks]
    manifest = {
        "schema_version": "1.0",
        "index_id": "xiaoyi-dense-vector-v1",
        "model": model,
        "chunk_count": len(records),
        "dimensions": dimensions,
        "normalization": "l2",
        "query_instruction": (
            "maritime evidence retrieval with jurisdiction/date/object/risk/source hints"
        ),
        "source_registry_sha256": _sha256(ROOT / "data" / "source_registry.json"),
        "boundary": (
            "Dense similarity is a retrieval signal, not proof that a passage entails "
            "an answer. Jurisdiction, date, provenance and answer verification remain mandatory."
        ),
    }
    payload = {"manifest": manifest, "records": records}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temp_path.replace(output_path)
    checkpoint_path.unlink(missing_ok=True)
    return manifest


def vector_index_is_current(output_path: Path = VECTOR_INDEX_PATH) -> bool:
    if not output_path.is_file():
        return False
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        indexed = {
            str(item["chunk_id"]): str(item["content_hash"])
            for item in payload["records"]
        }
    except (KeyError, OSError, TypeError, json.JSONDecodeError):
        return False
    current = {chunk.id: chunk.content_hash for chunk in load_chunks()}
    return indexed == current


def main() -> None:
    parser = argparse.ArgumentParser(description="构建小懿open-weight真实稠密向量索引")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:11436/v1",
    )
    parser.add_argument(
        "--model",
        default="xiaoyi-embedding-0.6b",
    )
    parser.add_argument("--output", type=Path, default=VECTOR_INDEX_PATH)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_CHECKPOINT_PATH,
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument(
        "--max-new-chunks",
        type=int,
        default=0,
        help="本次最多新增的片段数；0表示一直运行到完整索引",
    )
    parser.add_argument(
        "--ensure",
        action="store_true",
        help="索引与当前知识分块一致时跳过重建",
    )
    args = parser.parse_args()
    output_path = args.output.resolve()
    if args.ensure and vector_index_is_current(output_path):
        print(f"vector-index: current {output_path}")
        return
    manifest = build_vector_index(
        base_url=args.base_url,
        model=args.model,
        output_path=output_path,
        checkpoint_path=args.checkpoint.resolve(),
        batch_size=max(1, args.batch_size),
        max_new_chunks=max(1, args.max_new_chunks) if args.max_new_chunks else None,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
