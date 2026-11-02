from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest

from app.access_control import IdentityContext, has_permission
from integrations.shanghai_lab_v1 import delivery


def send(path, action="operations_review", actor="reviewer", role="admin", key=None, sha="a" * 64):
    return delivery.append(
        path,
        "sjt-" + "a" * 24,
        "a" * 64,
        {"request_id": key or action + "-request", "result_sha256": sha, "action": action, "client": "contract-test"},
        IdentityContext(actor, role, True, "test_identity"),
        has_permission,
    )


def test_lost_response_retry_concurrent_and_reopen(tmp_path):
    path = tmp_path / "journal.sqlite"
    first = send(path)  # assume response is lost after commit
    with ThreadPoolExecutor(8) as pool:
        retried = list(pool.map(lambda _: send(path), range(16)))
    assert all(row == first for row in retried)
    send(path, "energy_review", actor="energy-reviewer", role="analyst")
    ack = send(path, "acknowledge", role="viewer")
    state = delivery.state(path, ack["trial_id"], "a" * 64)
    assert len(state["events"]) == 3
    assert state["status"] == "acknowledged_lab"
    assert state["distinct_reviewers"] == 2
    assert state["events"][-1] == ack


def test_role_hash_order_and_conflicting_key_rejected(tmp_path):
    path = tmp_path / "journal.sqlite"
    with pytest.raises(PermissionError):
        send(path, role="viewer")
    with pytest.raises(ValueError, match="hash"):
        send(path, sha="b" * 64)
    with pytest.raises(ValueError, match="precede"):
        send(path, "acknowledge")
    send(path, key="same-request")
    with pytest.raises(ValueError, match="conflict"):
        send(path, "energy_review", key="same-request")


def test_no_false_distinct_people_and_tampering_detected(tmp_path):
    path = tmp_path / "journal.sqlite"
    first = send(path)
    send(path, "energy_review")
    state = delivery.state(path, first["trial_id"], "a" * 64)
    assert state["distinct_reviewers"] == 1 and state["review_mode"] == "same_actor_lab_review"
    with sqlite3.connect(path) as db:
        bad = {**first, "actor_id": "forged"}
        db.execute("UPDATE events SET body=? WHERE seq=1", (json.dumps(bad),))
    with pytest.raises(ValueError, match="integrity"):
        delivery.state(path, first["trial_id"], "a" * 64)
