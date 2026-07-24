from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Optional
from uuid import uuid4

from app.config import RUNTIME_DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


class RuntimeStore:
    """Small persistent control-plane store; never stores connector secrets."""

    def __init__(self, path: Path | str | None = None) -> None:
        configured = os.getenv("XIAOYI_RUNTIME_DB")
        self.path = Path(path or configured or RUNTIME_DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS contexts (
                    session_id TEXT PRIMARY KEY,
                    context_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    correlation_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    response_hash TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit_events(correlation_id);
                CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    answer_id TEXT,
                    rating INTEGER NOT NULL,
                    correction TEXT,
                    evidence_ids_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    submitted_by TEXT NOT NULL,
                    reviewed_by TEXT,
                    intake_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chat_session_created
                  ON chat_turns(session_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_chat_actor_session
                  ON chat_turns(actor_id, session_id);
                CREATE TABLE IF NOT EXISTS runtime_artifacts (
                    kind TEXT NOT NULL,
                    id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(kind, id)
                );
                CREATE INDEX IF NOT EXISTS idx_runtime_artifacts_updated
                  ON runtime_artifacts(kind, updated_at DESC);
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    namespace TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    response_headers_json TEXT NOT NULL,
                    response_body BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY(namespace, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_idempotency_expires
                  ON idempotency_records(expires_at);
                """
            )

    def health_check(self) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                result = connection.execute("SELECT 1").fetchone()[0]
                integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            return {
                "ok": result == 1 and integrity == "ok",
                "backend": "sqlite",
                "integrity": integrity,
                "path_configured": True,
            }
        except sqlite3.Error as exc:
            return {"ok": False, "backend": "sqlite", "error": str(exc)[:300]}

    def save_context(self, session_id: str, context: dict[str, Any]) -> dict[str, Any]:
        updated_at = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO contexts(session_id, context_json, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  context_json=excluded.context_json, updated_at=excluded.updated_at""",
                (session_id, _json(context), updated_at),
            )
        return {"session_id": session_id, "context": context, "updated_at": updated_at}

    def get_context(self, session_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT context_json, updated_at FROM contexts WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "session_id": session_id,
            "context": json.loads(row["context_json"]),
            "updated_at": row["updated_at"],
        }

    def add_audit(
        self,
        *,
        correlation_id: str,
        actor_id: str,
        actor_role: str,
        action: str,
        resource: str,
        risk_level: str,
        outcome: str,
        request: Any = None,
        response: Any = None,
        detail: str = "",
    ) -> dict[str, Any]:
        event = {
            "id": f"audit-{uuid4().hex}",
            "correlation_id": correlation_id,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "action": action,
            "resource": resource,
            "risk_level": risk_level,
            "outcome": outcome,
            "request_hash": _hash(request),
            "response_hash": _hash(response),
            "detail": detail[:1000],
            "created_at": _now(),
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO audit_events VALUES(
                  :id,:correlation_id,:actor_id,:actor_role,:action,:resource,
                  :risk_level,:outcome,:request_hash,:response_hash,:detail,:created_at
                )""",
                event,
            )
        return event

    def list_audit(self, limit: int = 50, correlation_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM audit_events"
        params: list[Any] = []
        if correlation_id:
            sql += " WHERE correlation_id=?"
            params.append(correlation_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def create_feedback(
        self,
        *,
        question: str,
        answer_id: str | None,
        rating: int,
        correction: str | None,
        evidence_ids: list[str],
        submitted_by: str,
    ) -> dict[str, Any]:
        now = _now()
        item = {
            "id": f"feedback-{uuid4().hex}",
            "question": question,
            "answer_id": answer_id,
            "rating": rating,
            "correction": correction,
            "evidence_ids_json": _json(evidence_ids),
            "status": "pending_review",
            "submitted_by": submitted_by,
            "reviewed_by": None,
            "intake_id": None,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO feedback VALUES(
                  :id,:question,:answer_id,:rating,:correction,:evidence_ids_json,
                  :status,:submitted_by,:reviewed_by,:intake_id,:created_at,:updated_at
                )""",
                item,
            )
        return self._public_feedback(item)

    def update_feedback(
        self,
        feedback_id: str,
        *,
        status: str,
        reviewed_by: str,
        intake_id: str | None = None,
    ) -> Optional[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            result = connection.execute(
                """UPDATE feedback SET status=?, reviewed_by=?, intake_id=?, updated_at=?
                WHERE id=?""",
                (status, reviewed_by, intake_id, _now(), feedback_id),
            )
            if result.rowcount == 0:
                return None
            row = connection.execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone()
        return self._public_feedback(dict(row))

    def get_feedback(self, feedback_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone()
        return self._public_feedback(dict(row)) if row else None

    def list_feedback(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [self._public_feedback(dict(row)) for row in rows]

    def save_chat_turn(
        self,
        *,
        session_id: str,
        actor_id: str,
        question: str,
        response: dict[str, Any],
        retention_days: int,
    ) -> dict[str, Any]:
        item = {
            "id": str(response.get("answer_id") or f"answer-{uuid4().hex}"),
            "session_id": session_id,
            "actor_id": actor_id,
            "question": question,
            "response_json": _json(response),
            "created_at": _now(),
        }
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))).isoformat().replace("+00:00", "Z")
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM chat_turns WHERE created_at < ?", (cutoff,))
            connection.execute(
                """INSERT OR REPLACE INTO chat_turns(
                  id,session_id,actor_id,question,response_json,created_at
                ) VALUES(:id,:session_id,:actor_id,:question,:response_json,:created_at)""",
                item,
            )
        return self._public_chat_turn(item)

    def list_chat_turns(
        self,
        session_id: str,
        *,
        actor_id: str,
        allow_all: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM chat_turns WHERE session_id=?"
        params: list[Any] = [session_id]
        if not allow_all:
            sql += " AND actor_id=?"
            params.append(actor_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 200)))
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._public_chat_turn(dict(row)) for row in rows]

    def delete_chat_turns(self, session_id: str, *, actor_id: str, allow_all: bool = False) -> int:
        sql = "DELETE FROM chat_turns WHERE session_id=?"
        params: list[Any] = [session_id]
        if not allow_all:
            sql += " AND actor_id=?"
            params.append(actor_id)
        with self._lock, self._connect() as connection:
            result = connection.execute(sql, params)
        return int(result.rowcount)

    def save_artifact(self, kind: str, artifact_id: str, payload: dict[str, Any], *, max_items: int = 100) -> None:
        now = _now()
        created_at = str(payload.get("created_at") or payload.get("generated_at") or now)
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO runtime_artifacts(kind,id,payload_json,created_at,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(kind,id) DO UPDATE SET
                  payload_json=excluded.payload_json, updated_at=excluded.updated_at""",
                (kind, artifact_id, _json(payload), created_at, now),
            )
            stale = connection.execute(
                "SELECT id FROM runtime_artifacts WHERE kind=? ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
                (kind, max(1, max_items)),
            ).fetchall()
            if stale:
                connection.executemany(
                    "DELETE FROM runtime_artifacts WHERE kind=? AND id=?",
                    [(kind, row["id"]) for row in stale],
                )

    def get_artifact(self, kind: str, artifact_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM runtime_artifacts WHERE kind=? AND id=?",
                (kind, artifact_id),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list_artifacts(self, kind: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM runtime_artifacts WHERE kind=? ORDER BY updated_at DESC LIMIT ?",
                (kind, max(1, min(limit, 500))),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def get_idempotency(self, namespace: str, key: str) -> Optional[dict[str, Any]]:
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM idempotency_records WHERE expires_at <= ?", (now,))
            row = connection.execute(
                "SELECT * FROM idempotency_records WHERE namespace=? AND idempotency_key=?",
                (namespace, key),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["response_headers"] = json.loads(item.pop("response_headers_json"))
        return item

    def save_idempotency(
        self,
        *,
        namespace: str,
        key: str,
        method: str,
        path: str,
        request_hash: str,
        status_code: int,
        response_headers: list[tuple[str, str]],
        response_body: bytes,
        ttl_seconds: int,
    ) -> None:
        created = datetime.now(timezone.utc)
        item = {
            "namespace": namespace,
            "idempotency_key": key,
            "method": method,
            "path": path,
            "request_hash": request_hash,
            "status_code": status_code,
            "response_headers_json": _json(response_headers),
            "response_body": response_body,
            "created_at": created.isoformat().replace("+00:00", "Z"),
            "expires_at": (created + timedelta(seconds=max(60, ttl_seconds))).isoformat().replace("+00:00", "Z"),
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO idempotency_records VALUES(
                  :namespace,:idempotency_key,:method,:path,:request_hash,:status_code,
                  :response_headers_json,:response_body,:created_at,:expires_at
                )""",
                item,
            )

    def metrics(self) -> dict[str, Any]:
        with self._connect() as connection:
            audit_total = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
            feedback_total = connection.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
            pending = connection.execute(
                "SELECT COUNT(*) FROM feedback WHERE status='pending_review'"
            ).fetchone()[0]
            successes = connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE outcome='success'"
            ).fetchone()[0]
            chat_turns = connection.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0]
            artifacts = connection.execute("SELECT COUNT(*) FROM runtime_artifacts").fetchone()[0]
        return {
            "audit_events": audit_total,
            "successful_actions": successes,
            "feedback_total": feedback_total,
            "feedback_pending_review": pending,
            "chat_turns": chat_turns,
            "runtime_artifacts": artifacts,
        }

    @staticmethod
    def _public_feedback(item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        raw = result.pop("evidence_ids_json", "[]")
        result["evidence_ids"] = json.loads(raw)
        return result

    @staticmethod
    def _public_chat_turn(item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        raw = result.pop("response_json", "{}")
        result["response"] = json.loads(raw)
        return result


runtime_store = RuntimeStore()
