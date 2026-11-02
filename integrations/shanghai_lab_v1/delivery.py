"""Transactional lab review/ack journal, isolated from existing runtime databases."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3

from .data import digest


PERMISSIONS = {"operations_review": "operations.manage", "energy_review": "rl.manage", "acknowledge": "chat.use"}


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute(
        "CREATE TABLE IF NOT EXISTS events (trial TEXT NOT NULL, seq INTEGER NOT NULL, actor TEXT NOT NULL, request_id TEXT NOT NULL, signature TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(trial,seq), UNIQUE(trial,actor,request_id))"
    )
    return db


def read_events(db, trial):
    events = [json.loads(row[0]) for row in db.execute("SELECT body FROM events WHERE trial=? ORDER BY seq", (trial,))]
    previous = "0" * 64
    for i, event in enumerate(events):
        if event["seq"] != i + 1 or event["previous_sha256"] != previous or event["trial_id"] != trial:
            raise ValueError("delivery event chain mismatch")
        if event["sha256"] != digest({k: v for k, v in event.items() if k != "sha256"}):
            raise ValueError("delivery event integrity mismatch")
        previous = event["sha256"]
    return events


def state(path, trial, result_sha256):
    db = connect(path)
    try:
        events = read_events(db, trial)
    finally:
        db.close()
    if any(e["result_sha256"] != result_sha256 for e in events):
        raise ValueError("delivery refers to a different result")
    done = {e["action"] for e in events}
    reviewers = {e["actor_id"] for e in events if e["action"].endswith("_review")}
    return {
        "trial_id": trial,
        "result_sha256": result_sha256,
        "events": events,
        "status": "acknowledged_lab"
        if "acknowledge" in done
        else "waiting_acknowledgement"
        if {"operations_review", "energy_review"} <= done
        else "waiting_reviews",
        "distinct_reviewers": len(reviewers),
        "review_mode": "distinct_actors" if len(reviewers) >= 2 else "same_actor_lab_review",
        "identity_scope": "existing application identity; client kind is self-reported, not device attestation",
        "production_authority": False,
    }


def append(path, trial, result_sha256, payload, identity, has_permission):
    action = payload["action"]
    if action not in PERMISSIONS or not has_permission(identity.role, PERMISSIONS[action]):
        raise PermissionError("role cannot perform this review action")
    if payload["result_sha256"] != result_sha256:
        raise ValueError("stale or mismatched result hash")
    signature = digest(payload)
    db = connect(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        events = read_events(db, trial)
        old = db.execute(
            "SELECT signature,body FROM events WHERE trial=? AND actor=? AND request_id=?",
            (trial, identity.actor_id, payload["request_id"]),
        ).fetchone()
        if old:
            if old[0] != signature:
                raise ValueError("idempotency key conflict")
            return json.loads(old[1])
        if any(e["result_sha256"] != result_sha256 for e in events):
            raise ValueError("prior review bound to another result")
        done = {e["action"] for e in events}
        if action == "acknowledge" and not {"operations_review", "energy_review"} <= done:
            raise ValueError("both review slots must precede acknowledgement")
        if action in done:
            raise ValueError("action already recorded; read its receipt instead of signing again")
        event = {
            "trial_id": trial,
            "seq": len(events) + 1,
            "actor_id": identity.actor_id,
            "actor_role": identity.role,
            "authentication_status": identity.authentication_status,
            "result_sha256": result_sha256,
            "action": action,
            "request_id": payload["request_id"],
            "client": payload["client"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "previous_sha256": events[-1]["sha256"] if events else "0" * 64,
            "production_authority": False,
        }
        event["sha256"] = digest(event)
        db.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?)",
            (
                trial,
                event["seq"],
                identity.actor_id,
                payload["request_id"],
                signature,
                json.dumps(event, ensure_ascii=False),
            ),
        )
        db.commit()
        return event
    finally:
        db.close()
