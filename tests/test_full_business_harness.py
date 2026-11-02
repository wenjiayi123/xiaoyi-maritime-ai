import copy
import hashlib
import json
import time
from pathlib import Path
import pytest
from app.access_control import IdentityContext
from app.harness import joint, business, transport
from app.harness.contracts import digest
from app.runtime_store import RuntimeStore
from app.harness.store import Conflict
from integrations.policy_runtime.contracts import Stop, Vehicle, TransportCase, Route, fixture, validate_routes, sha

OWNER = IdentityContext("phase-two-owner", "operator", True, "jwt_hs256_verified")
OP = IdentityContext("phase-two-operator", "operator", True, "jwt_hs256_verified")
SAFETY = IdentityContext("phase-two-safety", "admin", True, "jwt_hs256_verified")


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(joint, "runtime_store", RuntimeStore(tmp_path / "store.db"))
    # Approval/state-machine tests use a local native-source fixture. Actual
    # cross-repository execution is covered separately by adapter acceptance.
    native_source = tmp_path / "native-source.txt"
    native_source.write_text("isolated test native implementation")
    monkeypatch.setattr(joint, "implementation", lambda: {
        "test-native-source": hashlib.sha256(native_source.read_bytes()).hexdigest()
    })

    class Thread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr(joint, "_thread_factory", Thread)
    monkeypatch.setattr(joint, "_executor_lease", None)
    joint._active.clear()
    joint._controls.clear()
    yield
    if joint._executor_lease:
        joint._executor_lease.release()
    joint._active.clear()
    joint._controls.clear()


def waiting(approval="human"):
    j = joint.create(
        joint.MissionCreate(request_id="phase-two-approval-001", workflow="full_business", business_approval=approval),
        OWNER,
    )
    j.update(status="waiting_business_approval", business_approval_sha256="a" * 64)
    data = {"prepared_epoch": time.time(), "expires_seconds": 300}
    j["results"]["business_prepare"] = {"data": data, "sha256": digest(data)}
    return joint._save(j, "test.prepared")


def test_default_workflow_stays_legacy():
    c = joint.MissionCreate(request_id="legacy-default-001")
    assert c.workflow == "assessment" and c.business_approval == "human"


def test_full_plan_covers_entire_transaction(isolated):
    j = joint.create(joint.MissionCreate(request_id="phase-two-full-plan", workflow="full_business"), OWNER)
    ids = [s["id"] for s in j["plan"]["steps"]]
    assert (
        ids.index("business_approval")
        < ids.index("port_execute")
        < ids.index("business_verify")
        < ids.index("business_rollback")
        < ids.index("mobile")
    )
    assert j["plan"]["implementation_sha256"] == joint.implementation()
    assert "24步" in next(s["label"] for s in j["plan"]["steps"] if s["id"] == "port_execute")


def test_requester_and_local_unverified_identity_cannot_self_approve(isolated):
    j = waiting()
    for who in [OWNER, IdentityContext("other-local", "admin", False, "local_unverified_header")]:
        with pytest.raises(PermissionError):
            joint.approve_business(j["id"], joint.BusinessApproval(bundle_sha256="a" * 64, slot="operator"), who)
    assert joint.get(j["id"])["status"] == "waiting_business_approval"


def test_two_independent_authenticated_roles_are_required(isolated):
    j = waiting()
    a = joint.BusinessApproval(bundle_sha256="a" * 64, slot="operator")
    j = joint.approve_business(j["id"], a, OP)
    assert j["status"] == "waiting_business_approval" and len(j["business_approvals"]) == 1
    with pytest.raises(Conflict):
        joint.approve_business(j["id"], a, OP)
    with pytest.raises(PermissionError):
        joint.approve_business(j["id"], joint.BusinessApproval(bundle_sha256="a" * 64, slot="safety_officer"), OP)
    j = joint.approve_business(j["id"], joint.BusinessApproval(bundle_sha256="a" * 64, slot="safety_officer"), SAFETY)
    assert j["status"] == "running" and not j["results"]["business_approval"]["data"]["approvals_simulated"]
    assert len(business.approved_actors(j)) == 2


def test_simulation_roles_are_explicit_and_never_human(isolated):
    j = waiting("role_rehearsal")
    j = joint.approve_business(j["id"], joint.BusinessApproval(bundle_sha256="a" * 64, slot="role_rehearsal"), OWNER)
    assert j["results"]["business_approval"]["data"]["approvals_simulated"]
    assert all(a["simulated"] and a["actor_id"].startswith("simulation:") for a in j["business_approvals"])


def test_rehearsal_cannot_bypass_real_approval(isolated):
    j = waiting()
    with pytest.raises(PermissionError):
        joint.approve_business(j["id"], joint.BusinessApproval(bundle_sha256="a" * 64, slot="role_rehearsal"), OWNER)


@pytest.mark.parametrize("change", ["bundle", "expired", "source"])
def test_business_rejects_wrong_expired_or_changed_plan(isolated, monkeypatch, change):
    j = waiting("role_rehearsal")
    key = "a" * 64
    if change == "bundle":
        key = "b" * 64
    if change == "expired":
        j["results"]["business_prepare"]["data"]["prepared_epoch"] -= 301
        joint._save(j, "test.expired")
    if change == "source":
        monkeypatch.setattr(joint, "implementation", lambda: {"drift": "x"})
    with pytest.raises(Conflict):
        joint.approve_business(j["id"], joint.BusinessApproval(bundle_sha256=key, slot="role_rehearsal"), OWNER)


def test_unknown_write_is_not_replayed(isolated):
    j = waiting()
    calls = []

    def unknown():
        calls.append(1)
        raise TimeoutError("lost acknowledgment")

    with pytest.raises(TimeoutError):
        business.operation(j, "traffic.execute", unknown)
    with pytest.raises(Conflict):
        business.operation(j, "traffic.execute", unknown)
    assert calls == [1]


def test_confirmed_operation_is_idempotent(isolated):
    j = waiting()
    calls = []

    def apply():
        calls.append(1)
        return {"receipt": "native-123"}

    assert business.operation(j, "test.execute", apply) == business.operation(j, "test.execute", apply)
    assert calls == [1]


def test_transport_rejects_repeated_or_missing_cargo():
    c = fixture(size=2)
    routes = [Route(vehicle_id=c.vehicles[0].id, stops=["DEPOT", c.jobs[0].id, c.jobs[0].id, "DEPOT"])]
    assert "each_job_exactly_once" in validate_routes(c, routes)["violations"]


def test_contract_hash_survives_transport_json_roundtrip():
    c = fixture()
    assert sha(c.model_dump()) == sha(TransportCase.model_validate(json.loads(c.model_dump_json())).model_dump())


@pytest.mark.parametrize("kind", ["capacity", "time_window", "vehicle_energy", "forbidden_edge", "refill_not_allowed"])
def test_independent_checker_blocks_constraints(kind):
    c = fixture(size=2)
    v = c.vehicles[0]
    order = ["DEPOT", *[j.id for j in c.jobs], "DEPOT"]
    if kind == "capacity":
        c = c.model_copy(update={"vehicles": [v.model_copy(update={"capacity": 1})]})
    if kind == "time_window":
        c = c.model_copy(update={"jobs": [c.jobs[0].model_copy(update={"window_end_seconds": 0.001}), c.jobs[1]]})
    if kind == "vehicle_energy":
        c = c.model_copy(update={"vehicles": [v.model_copy(update={"energy_budget_kwh": 0.0001})]})
    if kind == "forbidden_edge":
        c = c.model_copy(update={"forbidden_edges": [("DEPOT", c.jobs[0].id)]})
    if kind == "refill_not_allowed":
        order.insert(2, "DEPOT")
    result = validate_routes(c, [Route(vehicle_id=v.id, stops=order)])
    assert kind in result["violations"] and not result["feasible"]


def test_bad_or_poor_model_does_not_override_feasible_baseline(monkeypatch):
    c = fixture(size=2)

    def solve(case, model, *a, **kw):
        return {
            "model": model,
            "validation": {"feasible": model != "routefinder", "objective_value": 3 if model == "ortools" else 5},
        }

    monkeypatch.setattr(transport, "solve", solve)
    result = transport.compare(c)
    assert result["selected"]["model"] == "ortools" and len(result["candidates"]) == 3


def test_parco_native_wait_is_not_a_second_service():
    from integrations.policy_runtime.action_codec import parco_stops

    stops, waits = parco_stops(0, [0, 2, 2, 3, 0], "DEPOT", ["A", "B"], 2)
    assert stops == ["DEPOT", "A", "B", "DEPOT"] and [w["tick"] for w in waits] == [0, 2]


def test_parco_nonconsecutive_revisit_is_preserved_and_rejected():
    from integrations.policy_runtime.action_codec import parco_stops

    stops, waits = parco_stops(0, [2, 3, 2, 0], "DEPOT", ["A", "B"], 2)
    assert stops == ["DEPOT", "A", "B", "A", "DEPOT"] and not waits
    with pytest.raises(ValueError):
        parco_stops(0, [1], "DEPOT", ["A", "B"], 2)


def test_rollback_tolerates_unexecuted_native_history(isolated, monkeypatch):
    j = waiting()
    j["results"]["business_prepare"]["data"]["energy"] = {"decision_id": "energy-own"}
    j["business_operations"] = {
        "energy.execute": {
            "status": "confirmed",
            "result": {"execution_receipt": {"executed_at": "2026-10-29T00:01:00Z"}},
        }
    }
    joint._save(j, "test.native_executed")

    def invoke(job, target, method, path, body=None, key=None):
        if method == "GET":
            return {"items": [{"decision_id": "pending", "execution_receipt": None}]}
        return {"status": "rolled_back_simulation"}

    monkeypatch.setattr(business, "_call", invoke)
    assert business.rollback(j)["results"]["energy"]["status"] == "rolled_back_simulation"


def test_rollback_refuses_to_overwrite_newer_native_execution(isolated, monkeypatch):
    j = waiting()
    j["results"]["business_prepare"]["data"]["energy"] = {"decision_id": "energy-own"}
    j["business_operations"] = {
        "energy.execute": {
            "status": "confirmed",
            "result": {"execution_receipt": {"executed_at": "2026-10-29T00:01:00Z"}},
        }
    }
    joint._save(j, "test.native_executed")

    def invoke(job, target, method, path, body=None, key=None):
        assert method == "GET"
        return {"items": [{"decision_id": "other", "execution_receipt": {"executed_at": "2026-10-29T00:02:00Z"}}]}

    monkeypatch.setattr(business, "_call", invoke)
    with pytest.raises(Conflict):
        business.rollback(j)


def test_unknown_write_cannot_be_compensated_blindly(isolated):
    j = waiting()
    j["status"] = "needs_review"
    j["business_operations"] = {"energy.execute": {"status": "intent"}}
    joint._save(j, "test.unknown")
    with pytest.raises(Conflict):
        joint.compensate(j["id"], OWNER)


def event_service():
    import importlib.util

    path = Path("/Users/apple/Desktop/模拟器/port-dt-multi/app/services/harness_event_execution.py")
    if not path.is_file():
        pytest.skip("external port event-execution implementation is not installed")
    spec = importlib.util.spec_from_file_location("harness_events_unit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def schedule_fixture():
    return {
        "epoch": "2026-10-29T00:00:00Z",
        "native_arrival_seconds": 100,
        "resources": [{"resource_id": "R1", "resource_type": "berth", "capacity": 1}],
        "candidate_plan": [
            {
                "task_id": "A",
                "stage": "port_arrival",
                "chain_id": "chain.01",
                "candidate_start": "2026-10-29T00:25:00Z",
                "candidate_end": "2026-10-29T00:30:00Z",
                "deadline": "2026-10-29T02:00:00Z",
                "predecessor_ids": [],
                "allocations": [{"resource_id": "R1", "quantity": 1}],
            },
            {
                "task_id": "B",
                "stage": "berthing",
                "chain_id": "chain.01",
                "candidate_start": "2026-10-29T00:45:00Z",
                "candidate_end": "2026-10-29T00:50:00Z",
                "deadline": "2026-10-29T02:00:00Z",
                "predecessor_ids": ["A"],
                "allocations": [{"resource_id": "R1", "quantity": 1}],
            },
        ],
    }


def test_resource_plan_actually_transitions_and_releases():
    m = event_service()
    result = m.execute_schedule(schedule_fixture())
    assert result["tasks_completed"] == 2 and result["final_resource_occupancy"] == {"R1": 0.0}
    assert [e["event"] for e in result["events"]] == ["started", "completed", "started", "completed"]
    controls = m.interval_controls(schedule_fixture(), 2, 1, [0.0] * 18)
    assert controls[0][3] > -1 and controls[1][3] == -1


@pytest.mark.parametrize("kind", ["capacity", "predecessor", "arrival", "deadline"])
def test_event_execution_rechecks_real_plan_constraints(kind):
    m = event_service()
    s = schedule_fixture()
    if kind == "capacity":
        s["candidate_plan"][0]["allocations"][0]["quantity"] = 2
    if kind == "predecessor":
        s["candidate_plan"][1]["predecessor_ids"] = ["unknown"]
    if kind == "arrival":
        s["native_arrival_seconds"] = 2000
    if kind == "deadline":
        s["candidate_plan"][0]["deadline"] = "2026-10-29T00:26:00Z"
    with pytest.raises(ValueError):
        m.execute_schedule(s)


def test_real_jwt_accounts_flow_through_api_approval_without_trusting_claimed_ids(isolated):
    from dataclasses import replace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.harness.dual_api import router
    from app.security import PlatformMiddleware, issue_access_token
    from app.settings import Settings
    from app.observability import TelemetryRegistry

    j = waiting()
    cfg = replace(
        Settings.from_env(),
        environment="staging",
        security_mode="jwt",
        jwt_secret="phase-two-test-secret-at-least-32-bytes",
        rate_limit_requests=100,
    )
    secured = FastAPI()
    secured.add_middleware(PlatformMiddleware, settings=cfg, telemetry=TelemetryRegistry())
    secured.include_router(router)

    def headers(actor, role):
        return {"Authorization": "Bearer " + issue_access_token(actor_id=actor, role=role, settings=cfg)}

    with TestClient(secured) as client:
        path = f"/api/harness/joint/missions/{j['id']}/business-approval"
        body = {"bundle_sha256": "a" * 64, "slot": "operator"}
        assert client.post(path, json=body).status_code == 401
        assert client.post(path, json=body, headers=headers(OWNER.actor_id, OWNER.role)).status_code == 403
        assert client.post(path, json=body, headers=headers("viewer", "viewer")).status_code == 403
        assert (
            client.get(f"/api/harness/joint/missions/{j['id']}", headers=headers(OP.actor_id, OP.role)).status_code
            == 200
        )
        first = client.post(
            path, json=body, headers={**headers(OP.actor_id, OP.role), "X-Xiaoyi-Actor": "forged-owner"}
        )
        assert first.status_code == 200 and first.json()["status"] == "waiting_business_approval"
        second = client.post(
            path, json={**body, "slot": "safety_officer"}, headers=headers(SAFETY.actor_id, SAFETY.role)
        )
        assert second.status_code == 200
        approvals = second.json()["results"]["business_approval"]["data"]["approvals"]
        assert {a["actor_id"] for a in approvals} == {OP.actor_id, SAFETY.actor_id}
        assert not second.json()["results"]["business_approval"]["data"]["approvals_simulated"]


def test_unused_vehicle_is_not_counted_as_a_reserved_transport_resource():
    c = fixture(size=2)
    routes = [
        Route(vehicle_id=c.vehicles[0].id, stops=["DEPOT", *[n.id for n in c.jobs], "DEPOT"]),
        Route(vehicle_id=c.vehicles[1].id, stops=["DEPOT", "DEPOT"]),
    ]
    result = validate_routes(c, routes)
    assert result["feasible"] and result["vehicles_used"] == 1


def test_paused_then_cancelled_business_compensates_confirmed_controls(isolated, monkeypatch):
    j = waiting()
    j["status"] = "paused"
    j["business_operations"] = {
        "energy.execute": {"status": "confirmed", "result": {"ack": "1"}, "result_sha256": digest({"ack": "1"})}
    }
    joint._save(j, "test.paused_after_execution")
    calls = []

    def compensate(job_id, identity):
        calls.append((job_id, identity.actor_id))
        current = joint.get(job_id)
        assert current["status"] == "cancelled"
        return current

    monkeypatch.setattr(joint, "compensate", compensate)
    result = joint.control(j["id"], "cancel", OWNER)
    assert result["status"] == "cancelled" and calls == [(j["id"], OWNER.actor_id)]


def test_failed_inactive_cancel_compensation_stays_reviewable(isolated, monkeypatch):
    j = waiting()
    j["status"] = "paused"
    j["business_operations"] = {"traffic.execute": {"status": "confirmed"}}
    joint._save(j, "test.paused")

    def failed(*_):
        raise TimeoutError("native rollback unavailable")

    monkeypatch.setattr(joint, "compensate", failed)
    result = joint.control(j["id"], "cancel", OWNER)
    assert result["status"] == "needs_review" and "native rollback unavailable" in result["compensation_error"]


def test_corrupt_business_operation_receipt_cannot_be_reused(isolated):
    j = waiting()
    business.operation(j, "demo.execute", lambda: {"ack": "original"})
    current = joint.get(j["id"])
    current["business_operations"]["demo.execute"]["result"] = {"ack": "changed"}
    joint._save(current, "test.tamper")
    assert not joint.export(current)["integrity"]["business_operation_hashes_valid"]
    with pytest.raises(Conflict):
        business.operation(current, "demo.execute", lambda: {"ack": "new"})


def test_mobile_ack_reports_local_identity_truthfully(isolated):
    j = waiting()
    j.update(status="waiting_mobile", delivery_sha256="c" * 64)
    joint._save(j, "test.ready_for_mobile")
    local = IdentityContext(OWNER.actor_id, "operator", False, "local_unverified_header")
    j = joint.acknowledge(j["id"], joint.MobileAck(receipt_sha256="c" * 64, client="flutter-web"), local)
    ack = j["results"]["mobile"]["data"]
    assert j["status"] == "completed" and ack["actor_authenticated"] is False
    assert "本地未认证身份" in ack["notice"]


def test_enterprise_keeps_pretrained_candidate_in_shadow_until_explicit_research_selection(monkeypatch):
    c = fixture(size=2)

    def solve(case, model, **kw):
        return {
            "model": model,
            "validation": {
                "feasible": True,
                "objective_value": {"nearest_neighbor": 20, "ortools": 10, "routefinder": 1}[model],
            },
        }

    monkeypatch.setattr(transport, "solve", solve)
    enterprise = transport.compare(c, allow_pretrained_selection=False)
    research = transport.compare(c, allow_pretrained_selection=True)
    assert enterprise["selected"]["model"] == "ortools" and research["selected"]["model"] == "routefinder"
    assert next(c for c in enterprise["candidates"] if c["model"] == "routefinder")["selection_eligible"] is False
