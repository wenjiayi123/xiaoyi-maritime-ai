"""Independent tiny optimum, unsafe schedules, receipts and actual tool orchestration."""

import copy
import hashlib
import itertools
import json
import time

import pytest

from app.access_control import IdentityContext
from app.harness import model, operations_v5 as ops, proof_v5
from app.harness import tools
from app.harness.contracts import CreateTask
from app.harness.runner import Harness
from app.harness.store import Conflict, HarnessStore
from app.runtime_store import RuntimeStore


@pytest.fixture
def tiny(monkeypatch):
    monkeypatch.setattr(ops, "SLOTS", 12)
    return {
        "jobs": [
            {
                "id": "SYN-1",
                "release": 0,
                "duration": 3,
                "length_m": 310,
                "cranes": 2,
                "shore_kw": 350,
                "priority": 1,
                "due": 4,
            },
            {
                "id": "SYN-2",
                "release": 0,
                "duration": 2,
                "length_m": 310,
                "cranes": 1,
                "shore_kw": 200,
                "priority": 4,
                "due": 4,
            },
        ],
        "caps": {r: [v] * 12 for r, v in ops.RESOURCES.items()},
        "grid_limit_kw": [2600] * 12,
        "tariff_weight": [0.5] * 4 + [1.5] * 4 + [0.7] * 4,
        "base_kw": 200,
        "weights": {
            "deferred_call": 5000,
            "grid_kwh_to_points": 0.01,
            "waiting_priority_per_hour": 2.0,
            "late_priority_per_hour": 8.0,
        },
    }


def test_joint_solver_matches_exhaustive_feasible_tiny_optimum(tiny):
    # Enumerate independent complete schedules and defer choices, not the MILP matrix.
    choices = [
        [None, *[{"job": i, "start": s, "berth": 1} for s in range(1, 12 - j["duration"])]]
        for i, j in enumerate(tiny["jobs"])
    ]
    feasible = []
    for rows in itertools.product(*choices):
        value = ops.schedule_check(tiny, [r for r in rows if r is not None])
        if value["passed"]:
            feasible.append(value["objective_points"])
    result = ops.solve(tiny)
    assert result["solver"]["optimality_proven"]
    assert result["selected"]["objective_points"] == pytest.approx(min(feasible), abs=1e-7)
    assert result["solver"]["dual_bound_points"] == pytest.approx(min(feasible), abs=1e-7)


def test_independent_schedule_checker_rejects_overlap_and_wrong_berth(tiny):
    overlapping = [{"job": 0, "start": 1, "berth": 1}, {"job": 1, "start": 1, "berth": 1}]
    assert not ops.schedule_check(tiny, overlapping)["checks"]["all_resource_bounds"]
    wrong = [{"job": 0, "start": 1, "berth": 0}]
    assert not ops.schedule_check(tiny, wrong)["passed"]


def test_no_firm_energy_defers_whole_calls_without_claiming_completion(tiny):
    tiny["grid_limit_kw"] = [200] * 12
    result = ops.solve(tiny)
    assert result["selected"]["completed_calls"] == 0
    assert result["selected"]["deferred_calls"] == 2
    assert result["selected"]["passed"]
    assert not result["selected"]["all_calls_completed"]


def test_changed_public_file_is_rejected(tmp_path):
    file = tmp_path / "public.csv"
    file.write_text("original")
    sha = hashlib.sha256(file.read_bytes()).hexdigest()
    file.write_text("modified")
    with pytest.raises(ValueError, match="变化"):
        ops.checked(str(file), sha)


def test_receipt_idempotency_identity_and_tamper_detection(tmp_path, monkeypatch):
    store = RuntimeStore(tmp_path / "proof.db")
    monkeypatch.setattr(proof_v5, "runtime_store", store)
    calls = []
    monkeypatch.setattr(
        proof_v5, "calculate", lambda kind, params: calls.append(kind) or {"value": 7, "production_authority": False}
    )
    request = proof_v5.RunRequest(request_id="idempotency-proof", kind="facts")
    first = proof_v5.run(request, "alice")
    assert proof_v5.run(request, "alice")["id"] == first["id"] and calls == ["facts"]
    with pytest.raises(ValueError):
        proof_v5.get(first["id"], "bob")
    with pytest.raises(Conflict):
        proof_v5.run(proof_v5.RunRequest(request_id=request.request_id, kind="runtime"), "alice")
    raw = store.get_artifact(proof_v5.KIND, first["id"])
    raw["result"]["value"] = 8
    store.save_artifact(proof_v5.KIND, first["id"], raw)
    assert not proof_v5.get(first["id"], "alice")["integrity"]["result_hash_valid"]


def test_invalid_analysis_is_retained_as_failed_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(proof_v5, "runtime_store", RuntimeStore(tmp_path / "proof.db"))
    request = proof_v5.RunRequest(request_id="invalid-proof-input", kind="optimization", parameters={"grid_kw": 1})
    receipt = proof_v5.run(request, "alice")
    assert receipt["status"] == "failed" and receipt["result"]["error"]
    assert receipt["integrity"]["event_chain_valid"] and not receipt["production_authority"]


def test_faults_block_and_restore_private_snapshot():
    report = proof_v5.faults()
    assert report["passed"] and len(report["cases"]) == 4
    assert report["unknown_ukc"]["status"] == "withheld"
    assert all(row["failed_checks"] and row["restored_hash_matches"] for row in report["cases"])


def test_live_facts_share_one_snapshot_without_mutation():
    report = proof_v5.facts()
    assert all(report["checks"].values())
    assert len(report["branches"]["branches"]) >= 3
    assert not report["production_authority"]


def test_operations_task_really_calls_solver_and_compiles_qualified_report(tmp_path):
    harness = Harness(HarnessStore(tmp_path / "tasks.db"))
    try:
        task = harness.create(
            CreateTask(
                goal="核对公开数据合成工单联合优化",
                request_id="operations-real-tool",
                template_id="operations-study",
                mode="research",
                driver="rules",
            ),
            IdentityContext("alice", "admin", True, "test"),
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            task = harness.store.get(task["id"])
            if task["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert task["status"] == "completed", task.get("stop_reason")
        assert task["final"]["verification"]["passed"]
        assert task["final"]["synthesis"]["model_authored"] is False
        assert "不是RL收益" in task["final"]["text"]
        artifact = json.loads(harness.store.artifact(task["id"], task["results"][0]["artifact"])["content"])
        assert artifact["solver"]["name"] == "scipy.optimize.milp / HiGHS"
    finally:
        harness.close()


def test_operations_model_contract_must_read_before_optional_plan(tmp_path):
    harness = Harness(HarnessStore(tmp_path / "tasks.db"))
    try:
        task = harness.create(
            CreateTask(
                goal="联合优化",
                request_id="operations-contract",
                template_id="operations-study",
                mode="research",
                driver="rules",
            ),
            IdentityContext("alice", "admin", True, "test"),
            schedule=False,
        )
        variants = model.wire_schema(task)["properties"]["action"]["anyOf"]
        assert {v["properties"]["kind"]["const"] for v in variants} == {"tool"}
        assert {v["properties"]["tool"]["const"] for v in variants} == {"operations.optimize"}
    finally:
        harness.close()


def test_optimization_context_is_bound_in_wire_and_checked_at_execution(tmp_path):
    harness = Harness(HarnessStore(tmp_path / "tasks.db"))
    try:
        task = harness.create(
            CreateTask(
                goal="按锁定参数优化",
                request_id="operations-bound-context",
                template_id="operations-study",
                mode="research",
                driver="rules",
                operations_context={
                    "port_id": "port694",
                    "source_day": "2026-06-15",
                    "grid_kw": 1800,
                    "objective": "turnaround",
                    "scenario": "crane_outage",
                },
            ),
            IdentityContext("alice", "admin", True, "test"),
            schedule=False,
        )
        wire = model.wire_schema(task)["properties"]["action"]["anyOf"][0]["properties"]["arguments"]
        assert all(wire["properties"][k]["const"] == v for k, v in task["operations_context"].items())
        with pytest.raises(ValueError, match="不一致"):
            tools.execute("operations.optimize", {}, task, harness.store)
    finally:
        harness.close()


def test_official_standard_subset_runs_live_but_keeps_external_conformance_false():
    result = proof_v5.calculate("standards", {})
    assert result["passed"] and len(result["checks"]) == 13
    assert [e["timestamp"]["classifierCode"] for e in result["accepted_fixtures"]] == ["EST", "REQ", "PLN", "ACT"]
    assert not result["external_conformance_completed"] and not result["production_authority"]


def test_changed_underlying_input_keeps_receipt_integrity_but_loses_current_status(tmp_path, monkeypatch):
    raw = tmp_path / "source.json"
    raw.write_text('{"original":true}')
    sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    monkeypatch.setattr(proof_v5, "BASE_DIR", tmp_path)
    monkeypatch.setattr(proof_v5, "code_sources", lambda: {})
    monkeypatch.setattr(proof_v5, "LOADED_SOURCES", {})
    monkeypatch.setattr(proof_v5, "runtime_store", RuntimeStore(tmp_path / "proof.db"))
    monkeypatch.setattr(
        proof_v5,
        "calculate",
        lambda kind, p: {"source": {"path": "source.json", "sha256": sha}, "production_authority": False},
    )
    receipt = proof_v5.run(proof_v5.RunRequest(kind="facts", request_id="drift-test-input"), "alice")
    assert not receipt["historical_only"]
    raw.write_text('{"changed":true}')
    reread = proof_v5.get(receipt["id"], "alice")
    assert reread["historical_only"] and reread["integrity"]["result_hash_valid"]


def test_proof_api_uses_real_json_contract_and_actor_bound_receipt(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.harness import proof_api

    monkeypatch.setattr(proof_v5, "runtime_store", RuntimeStore(tmp_path / "proof.db"))
    monkeypatch.setattr(proof_api, "identity_for", lambda request: IdentityContext("alice", "operator", True, "test"))
    with TestClient(app) as client:
        response = client.post("/api/harness/proof/runs", json={"request_id": "api-proof-actor", "kind": "faults"})
        assert response.status_code == 201 and response.json()["result"]["passed"]
        run_id = response.json()["id"]
        monkeypatch.setattr(proof_api, "identity_for", lambda request: IdentityContext("bob", "operator", True, "test"))
        assert client.get("/api/harness/proof/runs/" + run_id).status_code == 422
        assert (
            client.post("/api/harness/proof/runs", json={"request_id": "bad-api-kind", "kind": "dispatch"}).status_code
            == 422
        )


def test_public_csv_download_matches_registered_digest():
    from fastapi.testclient import TestClient
    from app.main import app

    entry = ops.catalog()["entries"][0]
    with TestClient(app) as client:
        response = client.get("/api/harness/proof/public-source/" + entry["id"])
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == entry["sha256"]


def test_loaded_code_mismatch_refuses_computation_and_keeps_failed_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(proof_v5, "runtime_store", RuntimeStore(tmp_path / "proof.db"))
    monkeypatch.setattr(proof_v5, "LOADED_SOURCES", {"changed-after-load.py": "0" * 64})
    called = []
    monkeypatch.setattr(proof_v5, "calculate", lambda kind, p: called.append(kind) or {})
    receipt = proof_v5.run(proof_v5.RunRequest(kind="runtime", request_id="loaded-source-drift"), "alice")
    assert not called and receipt["status"] == "failed"
    assert "已加载版本" in receipt["result"]["error"]
