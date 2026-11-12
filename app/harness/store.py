"""Transactional task state, bounded artifacts, leases and append-only event chain."""

from __future__ import annotations

import copy
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from app.harness.contracts import TERMINAL, digest, encoded, now


class Conflict(RuntimeError):
    pass


class HarnessStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS harness_tasks (
                    id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    status TEXT NOT NULL, version INTEGER NOT NULL, updated REAL NOT NULL,
                    lease_owner TEXT, lease_until REAL NOT NULL DEFAULT 0, payload TEXT NOT NULL,
                    UNIQUE(actor_id, request_id));
                CREATE INDEX IF NOT EXISTS harness_tasks_status ON harness_tasks(status, updated);
                CREATE TABLE IF NOT EXISTS harness_events (
                    task_id TEXT NOT NULL, seq INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(task_id, seq));
                CREATE TABLE IF NOT EXISTS harness_artifacts (
                    task_id TEXT NOT NULL, name TEXT NOT NULL, content TEXT NOT NULL,
                    sha256 TEXT NOT NULL, media_type TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(task_id, name));
                CREATE TABLE IF NOT EXISTS harness_memories (
                    id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, text TEXT NOT NULL,
                    label TEXT NOT NULL, created_at TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _event(db, task: dict, event: str, detail: dict | None = None):
        old = db.execute(
            "SELECT seq,payload FROM harness_events WHERE task_id=? ORDER BY seq DESC LIMIT 1", (task["id"],)
        ).fetchone()
        row = {
            "task_id": task["id"],
            "seq": old["seq"] + 1 if old else 1,
            "at": now(),
            "event": event,
            "status": task["status"],
            "detail": detail or {},
            "state_sha256": digest(task),
            "previous_sha256": json.loads(old["payload"])["sha256"] if old else "0" * 64,
        }
        row["sha256"] = digest(row)
        db.execute("INSERT INTO harness_events VALUES (?,?,?)", (task["id"], row["seq"], encoded(row)))

    def create(self, task: dict) -> tuple[dict, bool]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT payload FROM harness_tasks WHERE actor_id=? AND request_id=?",
                (task["actor_id"], task["request_id"]),
            ).fetchone()
            if old:
                value = json.loads(old["payload"])
                if value["request_sha256"] != task["request_sha256"]:
                    raise Conflict("同一请求编号不能用于不同任务")
                return value, False
            count = db.execute(
                "SELECT COUNT(*) FROM harness_tasks WHERE actor_id=? AND status NOT IN ('completed','partial','failed','cancelled','budget_exceeded','blocked','needs_review')",
                (task["actor_id"],),
            ).fetchone()[0]
            if count >= 20:
                raise Conflict("当前用户未结束任务已达20项，请先处理历史任务")
            task["version"] = 1
            db.execute(
                "INSERT INTO harness_tasks VALUES (?,?,?,?,?,?,NULL,0,?)",
                (task["id"], task["actor_id"], task["request_id"], task["status"], 1, time.time(), encoded(task)),
            )
            self._event(db, task, "task.created")
            return copy.deepcopy(task), True

    def get(self, task_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM harness_tasks WHERE id=?", (task_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def list(self, actor_id: str | None, limit=100) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM harness_tasks "
                + ("WHERE actor_id=? " if actor_id else "")
                + "ORDER BY updated DESC LIMIT ?",
                ((actor_id, limit) if actor_id else (limit,)),
            ).fetchall()
            return [json.loads(row[0]) for row in rows]

    def queued_ids(self, limit: int) -> list[str]:
        with self.connect() as db:
            return [row[0] for row in db.execute(
                "SELECT id FROM harness_tasks WHERE status='queued' AND lease_until<=? "
                "ORDER BY updated, rowid LIMIT ?", (time.time(), limit),
            )]

    @staticmethod
    def _check_owner(db, task_id: str, owner: str):
        row = db.execute(
            "SELECT lease_owner,lease_until FROM harness_tasks WHERE id=?", (task_id,),
        ).fetchone()
        if not row or row["lease_owner"] != owner or row["lease_until"] <= time.time():
            raise Conflict("执行租约已失效")

    def mutate(
        self, task_id: str, fn: Callable[[dict], None], event: str,
        detail=None, owner=None, *, artifacts: list[dict] | None = None,
    ) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM harness_tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise KeyError(task_id)
            if owner:
                self._check_owner(db, task_id, owner)
            task = json.loads(row["payload"])
            fn(task)
            task["updated_at"] = now()
            task["version"] = row["version"] + 1
            raw = encoded(task)
            if len(raw.encode()) > 2_000_000:
                raise Conflict("任务状态超过2MB上限")
            for artifact in artifacts or []:
                self._put_artifact(db, task_id, **artifact)
            db.execute(
                "UPDATE harness_tasks SET payload=?,status=?,version=?,updated=? WHERE id=?",
                (raw, task["status"], task["version"], time.time(), task_id),
            )
            self._event(db, task, event, detail)
            return task

    def claim(self, task_id: str, owner: str) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM harness_tasks WHERE id=?", (task_id,)).fetchone()
            if not row or row["status"] != "queued" or row["lease_until"] > time.time():
                return False
            task = json.loads(row["payload"])
            task.update(status="running", version=row["version"] + 1, updated_at=now())
            db.execute(
                "UPDATE harness_tasks SET status='running',lease_owner=?,lease_until=?,payload=?,version=?,updated=? WHERE id=?",
                (owner, time.time() + 90, encoded(task), task["version"], time.time(), task_id),
            )
            self._event(db, task, "task.claimed")
            return True

    def heartbeat(self, task_id: str, owner: str) -> bool:
        with self.connect() as db:
            return (
                db.execute(
                    "UPDATE harness_tasks SET lease_until=? WHERE id=? AND lease_owner=? AND lease_until>?",
                    (time.time() + 90, task_id, owner, time.time()),
                ).rowcount
                == 1
            )

    def release(self, task_id: str, owner: str):
        with self.connect() as db:
            db.execute(
                "UPDATE harness_tasks SET lease_owner=NULL,lease_until=0 WHERE id=? AND lease_owner=?", (task_id, owner)
            )

    def recover(self) -> int:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT * FROM harness_tasks WHERE status='running' AND lease_until<?", (time.time(),)
            ).fetchall()
            for row in rows:
                task = json.loads(row["payload"])
                uncertain = task.get("inflight", {}).get("side_effect", False)
                task.update(
                    status="needs_review" if uncertain else "paused",
                    version=row["version"] + 1,
                    stop_reason="执行租约过期；未决副作用需人工核查"
                    if uncertain
                    else "执行进程中断；可从检查点继续只读工作",
                    updated_at=now(),
                )
                db.execute(
                    "UPDATE harness_tasks SET status=?,payload=?,version=?,lease_owner=NULL,lease_until=0 WHERE id=?",
                    (task["status"], encoded(task), task["version"], task["id"]),
                )
                self._event(db, task, "task.recovered")
            return len(rows)

    def events(self, task_id: str, after=0, limit=200) -> list[dict]:
        with self.connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT payload FROM harness_events WHERE task_id=? AND seq>? ORDER BY seq LIMIT ?",
                    (task_id, after, limit),
                )
            ]

    def trace_snapshot(self, task_id: str) -> tuple[dict, list[dict], dict[str, dict]]:
        """Capture task, ledger and artifacts from one SQLite read snapshot."""
        with self.connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT payload FROM harness_tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            events = [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM harness_events WHERE task_id=? ORDER BY seq", (task_id,),
            )]
            artifacts = {row["name"]: dict(row) for row in db.execute(
                "SELECT * FROM harness_artifacts WHERE task_id=?", (task_id,),
            )}
            return json.loads(row[0]), events, artifacts

    @staticmethod
    def _put_artifact(db, task_id: str, name: str, content: str, media_type="text/markdown"):
        if len(content.encode()) > 200_000:
            raise ValueError("单工件不得超过200KB")
        if (
            db.execute("SELECT COUNT(*) FROM harness_artifacts WHERE task_id=?", (task_id,)).fetchone()[0] >= 64
            and not db.execute(
                "SELECT 1 FROM harness_artifacts WHERE task_id=? AND name=?", (task_id, name)
            ).fetchone()
        ):
            raise ValueError("单任务最多64个工件")
        db.execute(
            "INSERT OR REPLACE INTO harness_artifacts VALUES (?,?,?,?,?,?)",
            (task_id, name, content, digest(content), media_type, now()),
        )

    def artifact(
        self, task_id: str, name: str, content: str | None = None,
        media_type="text/markdown", *, owner: str | None = None,
    ) -> dict | None:
        with self.connect() as db:
            if content is not None:
                db.execute("BEGIN IMMEDIATE")
                if owner:
                    self._check_owner(db, task_id, owner)
                self._put_artifact(db, task_id, name, content, media_type)
            row = db.execute("SELECT * FROM harness_artifacts WHERE task_id=? AND name=?", (task_id, name)).fetchone()
            return dict(row) if row else None

    def artifacts(self, task_id: str) -> list[dict]:
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT name,sha256,media_type,updated_at,length(content) AS chars FROM harness_artifacts WHERE task_id=?",
                    (task_id,),
                )
            ]

    def memories(self, actor_id: str) -> list[dict]:
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM harness_memories WHERE actor_id=? ORDER BY created_at DESC LIMIT 30", (actor_id,)
                )
            ]

    def save_memory(self, actor_id: str, memory_id: str, text: str, label: str):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM harness_memories WHERE actor_id=?", (actor_id,)).fetchone()[0] >= 30:
                raise Conflict("最多保存30条记忆，请先删除旧条目")
            db.execute("INSERT INTO harness_memories VALUES (?,?,?,?,?)", (memory_id, actor_id, text, label, now()))

    def delete_memory(self, actor_id: str, memory_id: str) -> bool:
        with self.connect() as db:
            return (
                db.execute("DELETE FROM harness_memories WHERE id=? AND actor_id=?", (memory_id, actor_id)).rowcount
                == 1
            )
