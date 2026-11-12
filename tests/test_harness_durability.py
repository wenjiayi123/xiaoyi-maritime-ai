"""Regression tests with isolated SQLite databases and injected process/I/O faults."""

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from app.access_control import IdentityContext
from app.harness import model, tools
from app.harness.contracts import Action, CreateTask, digest
from app.harness.runner import Harness
from app.harness.store import Conflict, HarnessStore
from app.harness.trajectory import export_trajectory


def make_task(harness, request_id="durability-test", actor="tester"):
    return harness.create(
        CreateTask(goal="计算 6*7", request_id=request_id,
                   driver="rules", allowed_tools=["calculate"]),
        IdentityContext(actor, "operator", True, "test"), schedule=False,
    )


@pytest.fixture
def harness(tmp_path):
    runtime = Harness(HarnessStore(tmp_path / "tasks.db"), workers=1)
    yield runtime
    runtime.close()


def test_pending_task_is_visible_beyond_200_newer_records(harness):
    queued = make_task(harness)
    for index in range(205):
        task = make_task(harness, f"history-{index:04}")
        harness.store.mutate(task["id"], lambda t: t.update(status="completed"), "fixture")
    seen = threading.Event()
    original = harness.schedule

    def record(task_id):
        if task_id == queued["id"]:
            seen.set()
        original(task_id)

    harness.schedule = record
    harness.start()
    assert seen.wait(2), "old queued task was hidden behind newer finished tasks"


def test_worker_limit_does_not_claim_jobs_waiting_in_threadpool(harness, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def hold(task_id):
        started.set()
        release.wait(4)
        harness.store.release(task_id, harness.instance)
        with harness.lock:
            harness.active.discard(task_id)

    monkeypatch.setattr(harness, "_work", hold)
    first, second = make_task(harness, "first-worker"), make_task(harness, "second-worker")
    try:
        harness.schedule(first["id"])
        assert started.wait(2)
        harness.schedule(second["id"])
        assert harness.store.get(second["id"])["status"] == "queued"
    finally:
        release.set()


def test_expired_worker_cannot_overwrite_replacement_result(harness, monkeypatch):
    task = make_task(harness)
    assert harness.store.claim(task["id"], harness.instance)
    replacement = Harness(HarnessStore(harness.store.path))
    original_execute = tools.execute
    first = True
    action = Action(kind="tool", tool="calculate", arguments={"expression": "6*7"})

    def delayed(*args, **kwargs):
        nonlocal first
        if not first:
            return original_execute(*args, **kwargs)
        first = False
        with harness.store.connect() as db:
            db.execute("UPDATE harness_tasks SET lease_until=0 WHERE id=?", (task["id"],))
        assert harness.store.recover() == 1
        harness.store.mutate(task["id"], lambda t: t.update(status="queued"), "fixture.resume")
        assert replacement.store.claim(task["id"], replacement.instance)
        replacement._invoke(replacement.store.get(task["id"]), action)
        return {"value": 41, "unit": ""}

    monkeypatch.setattr(tools, "execute", delayed)
    try:
        with pytest.raises(Conflict):
            harness._invoke(harness.store.get(task["id"]), action)
        current = harness.store.get(task["id"])
        artifact = harness.store.artifact(task["id"], "T1.json")
        assert json.loads(artifact["content"])["value"] == 42
        assert digest(artifact["content"]) == current["results"][0]["sha256"]
    finally:
        replacement.close()


def test_tool_result_and_event_rollback_together(harness, monkeypatch):
    task = make_task(harness)
    harness.store.claim(task["id"], harness.instance)
    original_event = harness.store._event

    def interrupted(db, value, event, detail=None):
        if event == "tool.completed":
            raise sqlite3.OperationalError("injected interrupted transaction")
        return original_event(db, value, event, detail)

    monkeypatch.setattr(harness.store, "_event", interrupted)
    with pytest.raises(sqlite3.OperationalError):
        harness._invoke(harness.store.get(task["id"]),
                        Action(kind="tool", tool="calculate", arguments={"expression": "6*7"}))
    assert harness.store.get(task["id"])["results"] == []
    assert harness.store.artifact(task["id"], "T1.json") is None


def test_failed_report_write_cannot_leave_completed_status(harness):
    task = make_task(harness)
    harness.store.claim(task["id"], harness.instance)
    harness._invoke(harness.store.get(task["id"]),
                    Action(kind="tool", tool="calculate", arguments={"expression": "6*7"}))
    with harness.store.connect() as db:
        db.execute("""CREATE TRIGGER reject_report BEFORE INSERT ON harness_artifacts
            WHEN NEW.name='report.md' BEGIN SELECT RAISE(ABORT,'injected full disk'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        harness._finalize(harness.store.get(task["id"]),
                          Action(kind="final", text="结果为42 [T1]", evidence_ids=["T1"]))
    assert harness.store.get(task["id"])["status"] == "running"
    assert harness.store.get(task["id"])["final"] is None
    assert harness.store.artifact(task["id"], "report.md") is None


def test_draft_artifact_rejects_stale_owner(harness):
    task = make_task(harness)
    harness.store.claim(task["id"], "current")
    with pytest.raises(Conflict):
        harness.store.artifact(task["id"], "draft.md", "stale output", owner="old")
    assert harness.store.artifact(task["id"], "draft.md") is None
    harness.store.artifact(task["id"], "draft.md", "current output", owner="current")
    assert harness.store.artifact(task["id"], "draft.md")["content"] == "current output"


def test_trace_detects_deleted_tail_and_uses_current_snapshot(harness):
    task = make_task(harness)
    harness.store.mutate(task["id"], lambda t: t.update(stop_reason="checkpoint"), "fixture")
    exported = export_trajectory(task, harness.store)
    assert exported["snapshot_version"] == 2
    assert exported["integrity"]["event_chain"]
    with harness.store.connect() as db:
        db.execute("DELETE FROM harness_events WHERE task_id=? AND seq=2", (task["id"],))
    assert not export_trajectory(task, harness.store)["integrity"]["event_chain"]


def test_trace_detects_report_corruption(harness):
    task = make_task(harness)
    harness.schedule(task["id"])
    deadline = time.monotonic() + 3
    while task["id"] in harness.active and time.monotonic() < deadline:
        time.sleep(.01)
    assert export_trajectory(task, harness.store)["integrity"]["final_report"]
    harness.store.artifact(task["id"], "report.md", "modified")
    assert not export_trajectory(task, harness.store)["integrity"]["final_report"]


def test_submission_failure_returns_claim_to_queue(harness, monkeypatch):
    def fail(*args):
        raise RuntimeError("injected submission failure")

    monkeypatch.setattr(harness.pool, "submit", fail)
    task = make_task(harness)
    with pytest.raises(RuntimeError):
        harness.schedule(task["id"])
    assert harness.store.get(task["id"])["status"] == "queued"
    assert task["id"] not in harness.active
    assert harness.store.claim(task["id"], "replacement")


def test_process_exit_during_result_commit_recovers_consistent_task(harness):
    task = make_task(harness)
    child = r'''
import os, sys
from app.harness.store import HarnessStore
from app.harness.runner import Harness
from app.harness.contracts import Action
store = HarnessStore(sys.argv[1])
h = Harness(store)
task_id = sys.argv[2]
assert store.claim(task_id, h.instance)
original = store._event
def fail(db, task, event, detail=None):
    if event == "tool.completed":
        os._exit(73)
    original(db, task, event, detail)
store._event = fail
h._invoke(store.get(task_id), Action(kind="tool", tool="calculate", arguments={"expression":"6*7"}))
'''
    process = subprocess.run(
        [sys.executable, "-c", child, str(harness.store.path), task["id"]],
        timeout=20, capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert process.returncode == 73, process.stderr.decode(errors="replace")
    assert harness.store.artifact(task["id"], "T1.json") is None
    assert not harness.store.get(task["id"])["results"]
    with harness.store.connect() as db:
        db.execute("UPDATE harness_tasks SET lease_until=0 WHERE id=?", (task["id"],))
    assert harness.store.recover() == 1
    assert harness.store.get(task["id"])["status"] == "paused"
    harness.control(task["id"], "resume", "operator")
    deadline = time.monotonic() + 5
    while task["id"] in harness.active and time.monotonic() < deadline:
        time.sleep(.01)
    current = harness.store.get(task["id"])
    assert current["status"] == "completed"
    assert len(current["results"]) == 1
    assert export_trajectory(current, harness.store)["integrity"]["event_chain"]


def test_parallel_schema_exposes_only_authorized_typed_children(harness):
    task = make_task(harness)
    task.update(allowed_tools=["research.parallel", "linked.observe"], required_tools=["research.parallel"])
    schema = model.wire_schema(task)
    parallel = next(option for option in schema["properties"]["action"]["anyOf"]
                    if option["properties"]["tool"].get("const") == "research.parallel")
    branches = parallel["properties"]["arguments"]["properties"]["branches"]
    assert branches["minItems"] == 1 and branches["maxItems"] == 3
    children = branches["items"]["anyOf"]
    assert len(children) == 1
    assert children[0]["properties"]["tool"] == {"const": "linked.observe"}
    assert children[0]["properties"]["arguments"]["required"] == ["target"]
    assert "energy-cockpit" in children[0]["properties"]["arguments"]["properties"]["target"]["enum"]
    offered = next(tool for tool in tools.catalog("operator", task["allowed_tools"]) if tool["name"] == "research.parallel")
    assert len(offered["parameters"]["properties"]["branches"]["items"]["anyOf"]) == 1


def test_parallel_without_child_permission_is_not_offered(harness):
    task = make_task(harness)
    task.update(allowed_tools=["research.parallel"], required_tools=["research.parallel"])
    schema = model.wire_schema(task)
    assert all(option["properties"]["tool"].get("const") != "research.parallel"
               for option in schema["properties"]["action"]["anyOf"])


def test_parallel_summary_keeps_every_branch_and_failed_target():
    result = {"branches": [
        {"tool":"knowledge.search", "arguments":{"question":"岸电核验"}, "ok":True,
         "result":{"answer":"长资料"*3000, "evidence":[], "source_quality":{}}},
        {"tool":"linked.observe", "arguments":{"target":"malacca-sandbox"}, "ok":False,
         "error":"injected timeout"},
    ]}
    summary = json.loads(Harness._summary("research.parallel", result))
    assert len(summary["branches"]) == 2
    assert "malacca-sandbox" in summary["branches"][1]["arguments"]
    assert summary["branches"][1]["ok"] is False
    assert "timeout" in summary["branches"][1]["summary"]
