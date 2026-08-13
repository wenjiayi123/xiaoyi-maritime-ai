from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.request import Request, urlopen

from app.config import VECTOR_INDEX_PATH
from app.settings import settings


logger = logging.getLogger("xiaoyi.vector_retrieval")


QUERY_INSTRUCTION = (
    "Instruct: Retrieve authoritative or operationally useful evidence for a "
    "maritime and port question. Prefer matching jurisdiction, date, object, "
    "risk boundary and source type.\nQuery: "
)


def _normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) ** 2 for value in vector))
    if norm <= 0:
        raise ValueError("embedding向量范数为0")
    return [float(value) / norm for value in vector]


class EmbeddingClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def embed(
        self,
        texts: Sequence[str],
        *,
        query: bool = False,
    ) -> list[list[float]]:
        if not texts:
            return []
        prepared = [
            f"{QUERY_INSTRUCTION}{text}" if query else text
            for text in texts
        ]
        payload = json.dumps(
            {"model": self.model, "input": prepared},
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/embeddings",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            body = json.loads(response.read(20_000_000))
        items = body.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise ValueError("embedding接口返回数量与输入不一致")
        ordered = sorted(items, key=lambda item: int(item.get("index", 0)))
        return [_normalize(item["embedding"]) for item in ordered]


@dataclass(frozen=True)
class VectorRecord:
    chunk_id: str
    content_hash: str
    vector: tuple[float, ...]


class DenseVectorIndex:
    def __init__(
        self,
        path: Path = VECTOR_INDEX_PATH,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.path = path
        self.base_url = (
            settings.embedding_base_url if base_url is None else base_url
        ).rstrip("/")
        self.model = model or settings.embedding_model
        self.timeout_seconds = (
            settings.embedding_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        self.records: dict[str, VectorRecord] = {}
        self.manifest: dict[str, Any] = {}
        self.last_error: str | None = None
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            records = payload.get("records", [])
            self.records = {
                str(item["chunk_id"]): VectorRecord(
                    chunk_id=str(item["chunk_id"]),
                    content_hash=str(item["content_hash"]),
                    vector=tuple(float(value) for value in item["vector"]),
                )
                for item in records
            }
            self.manifest = dict(payload.get("manifest") or {})
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            logger.exception("Dense vector index load failed")
            self.records = {}
            self.last_error = "dense_index_load_failed"

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.records)

    def scores(self, query: str, chunks: Iterable[Any]) -> dict[str, float]:
        if not self.enabled:
            return {}
        valid_records: dict[str, VectorRecord] = {}
        for chunk in chunks:
            record = self.records.get(str(chunk.id))
            if record and record.content_hash == str(chunk.content_hash):
                valid_records[record.chunk_id] = record
        if not valid_records:
            return {}
        client = EmbeddingClient(
            self.base_url,
            self.model,
            timeout_seconds=self.timeout_seconds,
        )
        query_vector = client.embed([query], query=True)[0]
        scores: dict[str, float] = {}
        for chunk_id, record in valid_records.items():
            if len(record.vector) != len(query_vector):
                continue
            scores[chunk_id] = sum(
                left * right
                for left, right in zip(query_vector, record.vector)
            )
        return scores

    def status(self) -> dict[str, Any]:
        return {
            "configured": bool(self.base_url),
            "enabled": self.enabled,
            "model": self.model,
            "index_path": str(self.path),
            "record_count": len(self.records),
            "dimensions": self.manifest.get("dimensions"),
            "last_error": self.last_error,
            "notice": (
                "真实稠密向量召回已启用；Sparse/BM25仍作为可审计对照与回退。"
                if self.enabled
                else "稠密向量服务或索引未启用，当前保留Sparse/BM25检索。"
            ),
        }


_SHARED_DENSE_INDEX: DenseVectorIndex | None = None
_SHARED_DENSE_SIGNATURE: tuple[str, int, int] | None = None


def get_dense_vector_index() -> DenseVectorIndex:
    global _SHARED_DENSE_INDEX, _SHARED_DENSE_SIGNATURE
    if VECTOR_INDEX_PATH.is_file():
        stat = VECTOR_INDEX_PATH.stat()
        signature = (
            settings.embedding_base_url,
            stat.st_mtime_ns,
            stat.st_size,
        )
    else:
        signature = (settings.embedding_base_url, -1, -1)
    if _SHARED_DENSE_INDEX is None or _SHARED_DENSE_SIGNATURE != signature:
        _SHARED_DENSE_INDEX = DenseVectorIndex()
        _SHARED_DENSE_SIGNATURE = signature
    return _SHARED_DENSE_INDEX
