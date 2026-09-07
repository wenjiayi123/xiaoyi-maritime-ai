from __future__ import annotations

import json
import hashlib
import logging
import math
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
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
    if not vector or not all(math.isfinite(float(value)) for value in vector):
        raise ValueError("embedding向量为空或包含非有限数值")
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
        ordered = sorted(items, key=lambda item: int(item["index"]))
        if [int(item["index"]) for item in ordered] != list(range(len(texts))):
            raise ValueError("embedding接口返回索引无效")
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
        self._lock = threading.RLock()
        self._query_cache: OrderedDict[str, tuple[float, tuple[float, ...]]] = OrderedDict()
        self._pending: dict[str, Future] = {}
        self._circuit_open_until = 0.0
        self._cache_hits = 0
        self._upstream_requests = 0
        self._fallbacks = 0
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
            if any(not record.vector or not all(math.isfinite(value) for value in record.vector)
                   for record in self.records.values()):
                raise ValueError("稠密索引包含无效向量")
            self.manifest = dict(payload.get("manifest") or {})
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            logger.exception("Dense vector index load failed")
            self.records = {}
            self.last_error = "dense_index_load_failed"

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.records)

    def _query_vector(self, query: str) -> tuple[float, ...] | None:
        # Cache embeddings, never answers or mutable operational snapshots.
        # Each index instance owns its cache, so rebuilding the index invalidates it.
        key = hashlib.sha256(query.encode("utf-8")).hexdigest()
        with self._lock:
            now = time.monotonic()
            cached = self._query_cache.get(key)
            if cached and now - cached[0] < 300:
                self._query_cache.move_to_end(key)
                self._cache_hits += 1
                return cached[1]
            if now < self._circuit_open_until:
                self._fallbacks += 1
                return None
            pending = self._pending.get(key)
            owner = pending is None
            if owner:
                if len(self._pending) >= 4:
                    self._fallbacks += 1
                    return None
                pending = Future()
                self._pending[key] = pending
                self._upstream_requests += 1
        if not owner:
            try:
                return pending.result(timeout=self.timeout_seconds)
            except TimeoutError:
                with self._lock:
                    self._fallbacks += 1
                return None
        vector = None
        try:
            client = EmbeddingClient(self.base_url, self.model, timeout_seconds=self.timeout_seconds)
            vector = tuple(client.embed([query], query=True)[0])
            if not vector or not all(math.isfinite(value) for value in vector):
                raise ValueError("embedding向量无效")
            dimensions = {len(record.vector) for record in self.records.values()}
            if dimensions != {len(vector)}:
                raise ValueError("embedding维度与索引不一致")
            with self._lock:
                self._query_cache[key] = (time.monotonic(), vector)
                self._query_cache.move_to_end(key)
                while len(self._query_cache) > 128:
                    self._query_cache.popitem(last=False)
                self.last_error = None
                self._circuit_open_until = 0.0
        except (OSError, TimeoutError, ValueError, TypeError, KeyError, IndexError):
            vector = None
            with self._lock:
                self.last_error = "embedding_upstream_unavailable"
                self._circuit_open_until = time.monotonic() + 30.0
                self._fallbacks += 1
        finally:
            with self._lock:
                self._pending.pop(key, None)
                pending.set_result(vector)
        return vector

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
        query_vector = self._query_vector(query)
        if query_vector is None:
            return {}
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
        with self._lock:
            diagnostics = {
                "circuit_open": time.monotonic() < self._circuit_open_until,
                "query_cache_hits": self._cache_hits,
                "query_cache_entries": len(self._query_cache),
                "upstream_requests": self._upstream_requests,
                "fallbacks": self._fallbacks,
                "query_timeout_seconds": self.timeout_seconds,
            }
        return {
            **diagnostics,
            "configured": bool(self.base_url),
            "enabled": self.enabled,
            "model": self.model,
            "index_path": str(self.path),
            "record_count": len(self.records),
            "dimensions": self.manifest.get("dimensions"),
            "last_error": self.last_error,
            "notice": (
                "真实稠密向量召回已启用；Sparse/BM25仍作为可审计对照与回退。"
                if self.enabled and not diagnostics["circuit_open"]
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
