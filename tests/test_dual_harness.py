from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
import time
import subprocess
import sys

import pytest

from app.access_control import IdentityContext
from app.harness import joint, research
from app.harness.contracts import CreateTask, digest
from app.harness.runner import Harness
from app.harness.store import Conflict, HarnessStore
from app.rl_lab.datasets import EnergyRecord
from app.rl_lab.environment import EnergySchedulingEnvironment, derive_parameters
from app.rl_lab.port_environment import PortOperationsEnvironment, derive_port_parameters
from app.runtime_store import RuntimeStore

OPERATOR = IdentityContext("dual-test-operator", "operator", True, "test")
OTHER = IdentityContext("other-operator", "operator", True, "test")
VIEWER = IdentityContext("viewer", "viewer", True, "test")


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    store = RuntimeStore(tmp_path / "runtime.db")
    monkeypatch.setattr(joint, "runtime_store", store)
    monkeypatch.setattr(research, "runtime_store", store)
    monkeypatch.setattr(research, "BASE_DIR", tmp_path)
    monkeypatch.setattr(research, "ROOT", tmp_path / "research")
    class DeferredThread:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            pass
    monkeypatch.setattr(joint, "_thread_factory", DeferredThread)
    monkeypatch.setattr(joint, "_executor_lease", None)
    monkeypatch.setattr(research, "_executor_lease", None)
    joint._active.clear()
    joint._controls.clear()
    yield store
    for service in [joint, research]:
        if service._executor_lease is not None:
            service._executor_lease.release()
    joint._active.clear()
    joint._controls.clear()


def mission(**kwargs):
    return joint.create(joint.MissionCreate(request_id="dual-mission-001", **kwargs), OPERATOR)


def approve(job):
    return joint.approve(job["id"], joint.MissionApproval(plan_sha256=job["plan_sha256"]), OPERATOR)


def test_creation_is_idempotent_and_bound_to_parameters(isolated):
    first = mission()
    assert mission()["id"] == first["id"]
    with pytest.raises(Conflict):
        mission(scenario="peak-arrivals")
    assert first["status"] == "waiting_approval"
    assert first["results"] == {}


def test_preview_never_invokes_downstream(isolated, monkeypatch):
    monkeypatch.setattr(joint, "_request", lambda *_a, **_kw: pytest.fail("preview called a target"))
    assert mission()["status"] == "waiting_approval"


def test_model_cannot_drop_readonly_goal_or_change_fixed_parameters(isolated):
    from app.harness import tools
    task = {"id": "goal-binding-test", "goal": "只读联合评估，不修改", "mode": "enterprise",
            "actor_id": OPERATOR.actor_id, "actor_role": OPERATOR.role,
            "allowed_tools": ["joint.preview"], "joint_context": {"mutate_sandbox": True}}
    with pytest.raises(ValueError, match="只读目标"):
        tools.execute("joint.preview", {}, task, None)
    with pytest.raises(ValueError, match="不能改写"):
        tools.validate("joint.preview", {"goal": "联合评估"}, task)
    with pytest.raises(ValueError, match="不能改写"):
        tools.validate("joint.preview", {"mutate_sandbox": False}, task)


def test_viewer_cannot_create_or_approve(isolated):
    with pytest.raises(PermissionError):
        joint.create(joint.MissionCreate(request_id="dual-viewer-001"), VIEWER)
    job = mission()
    with pytest.raises(PermissionError):
        joint.approve(job["id"], joint.MissionApproval(plan_sha256=job["plan_sha256"]), VIEWER)


def test_owner_is_enforced_for_read_and_control(isolated):
    job = mission()
    with pytest.raises(PermissionError):
        joint.get(job["id"], OTHER.actor_id)
    with pytest.raises(PermissionError):
        joint.control(job["id"], "cancel", OTHER)


def test_approval_rejects_changed_hash_and_expiry(isolated):
    job = mission()
    with pytest.raises(Conflict):
        joint.approve(job["id"], joint.MissionApproval(plan_sha256="0" * 64), OPERATOR)
    job["expires_epoch"] = time.time() - 1
    joint._save(job, "test.expired")
    with pytest.raises(Conflict):
        approve(job)


def test_rejected_mission_cannot_execute(isolated):
    job = mission()
    result = joint.approve(job["id"], joint.MissionApproval(plan_sha256=job["plan_sha256"], approve=False), OPERATOR)
    assert result["status"] == "rejected"
    with pytest.raises(Conflict):
        approve(job)


def test_duplicate_approval_does_not_start_another_execution(isolated):
    job = mission()
    first = approve(job)
    second = approve(job)
    assert first["started_epoch"] == second["started_epoch"]
    assert list(joint._active) == [job["id"]]


def test_dependency_order_and_real_mobile_receipt_required(isolated, monkeypatch):
    seen = []
    def perform(step, job, stop):
        seen.append(step)
        assert not stop()
        return {"source": step, "production_authority": False}
    monkeypatch.setattr(joint, "_perform", perform)
    job = mission()
    approve(job)
    joint._run(job["id"])
    job = joint.get(job["id"])
    assert seen == ["services", "traffic", "sailing", "port", "energy"]
    assert job["status"] == "waiting_mobile"
    assert "mobile" not in job["results"]
    with pytest.raises(Conflict):
        joint.acknowledge(job["id"], joint.MobileAck(receipt_sha256="0" * 64, client="flutter-web"), OPERATOR)
    done = joint.acknowledge(job["id"], joint.MobileAck(receipt_sha256=job["delivery_sha256"], client="flutter-web"), OPERATOR)
    assert done["status"] == "completed"
    receipt = joint.export(done)
    assert receipt["integrity"]["event_chain_valid"]
    assert receipt["integrity"]["result_hashes_valid"]


def test_failure_stops_dependent_steps(isolated, monkeypatch):
    seen = []
    def perform(step, *_):
        seen.append(step)
        if step == "sailing":
            raise ValueError("sample collision")
        return {"step": step}
    monkeypatch.setattr(joint, "_perform", perform)
    job = mission()
    approve(job)
    joint._run(job["id"])
    assert seen == ["services", "traffic", "sailing"]
    assert joint.get(job["id"])["status"] == "blocked"


def test_unknown_write_result_is_not_replayed(isolated, monkeypatch):
    def perform(step, *_):
        if step == "traffic":
            raise TimeoutError("target receipt lost")
        return {"step": step}
    monkeypatch.setattr(joint, "_perform", perform)
    job = mission(mutate_sandbox=True)
    approve(job)
    joint._run(job["id"])
    assert joint.get(job["id"])["status"] == "needs_review"
    with pytest.raises(Conflict):
        joint.control(job["id"], "resume", OPERATOR)


def test_write_intent_survives_lost_receipt_and_reconciliation_is_read_only(isolated, monkeypatch):
    from app import linked_agent
    observation = {"config": {"scenario": "normal"}, "production_authority": False}
    monkeypatch.setattr(linked_agent, "_observe", lambda *_: observation)
    job = mission(mutate_sandbox=True, scenario="peak-arrivals")
    writes = []
    def request(_target, method, _path, *_args, **_kwargs):
        if method == "GET":
            return {"source": "test"}
        assert joint.get(job["id"])["write_intents"]["traffic"]["before"] == observation
        writes.append(method)
        raise TimeoutError("remote receipt was lost")
    monkeypatch.setattr(joint, "_request", request)
    with pytest.raises(TimeoutError):
        joint._perform("traffic", job, lambda: False)
    saved = joint.get(job["id"])
    saved["status"] = "needs_review"
    joint._save(saved, "test.unknown_write")
    reviewed = joint.reconcile(job["id"], OPERATOR)
    assert reviewed["status"] == "needs_review"
    assert reviewed["reconciliation"]["observed"] == observation
    assert reviewed["reconciliation"]["write_intents"]["traffic"]["requested_scenario"] == "peak-arrivals"
    assert writes == ["POST"]


def test_cancel_before_dispatch_has_no_downstream_effect(isolated, monkeypatch):
    monkeypatch.setattr(joint, "_perform", lambda *_: pytest.fail("cancelled mission executed"))
    job = mission()
    approve(job)
    joint.control(job["id"], "cancel", OPERATOR)
    joint._run(job["id"])
    assert joint.get(job["id"])["status"] == "cancelled"


def test_pause_during_readonly_sample_can_resume_without_replaying_received_steps(isolated, monkeypatch):
    seen = []
    def perform(step, job, stop):
        seen.append(step)
        if step == "sailing" and seen.count("sailing") == 1:
            joint._controls[job["id"]]["pause"] = True
            assert stop()
            raise InterruptedError("sample stopped at pause boundary")
        return {"source": step}
    monkeypatch.setattr(joint, "_perform", perform)
    job = mission()
    approve(job)
    joint._run(job["id"])
    assert joint.get(job["id"])["status"] == "paused"
    joint.control(job["id"], "resume", OPERATOR)
    joint._run(job["id"])
    assert joint.get(job["id"])["status"] == "waiting_mobile"
    assert seen == ["services", "traffic", "sailing", "sailing", "port", "energy"]


def test_budget_exhaustion_is_not_completion(isolated, monkeypatch):
    monkeypatch.setattr(joint, "_perform", lambda *_: pytest.fail("budget-exhausted mission executed"))
    job = mission()
    approve(job)
    job = joint.get(job["id"])
    job["active_seconds"] = 1000
    joint._save(job, "test.budget")
    joint._run(job["id"])
    assert joint.get(job["id"])["status"] == "budget_exceeded"


def test_restart_marks_inflight_mission_for_review(isolated):
    job = mission()
    approve(job)
    joint._active.clear()
    joint.recover()
    assert joint.get(job["id"])["status"] == "needs_review"


def test_another_live_process_is_not_mistaken_for_crash_or_double_dispatched(isolated):
    job = mission()
    approve(job)
    joint._executor_lease.release()
    joint._active.clear()
    script = ("import sys; from pathlib import Path; from app.harness.local_lock import ProcessLease; "
              "lease=ProcessLease(Path(sys.argv[1])); lease.acquire(); print('ready',flush=True); sys.stdin.read()")
    child = subprocess.Popen([sys.executable, "-c", script, str(isolated.path.with_suffix(".joint.lock"))],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        assert child.stdout.readline().strip() == "ready"
        joint.recover()
        assert joint.get(job["id"])["status"] == "running"
        other = joint.create(joint.MissionCreate(request_id="other-process-test"), OPERATOR)
        with pytest.raises(Conflict, match="另一进程"):
            approve(other)
    finally:
        child.communicate("", timeout=5)
    joint.recover()
    assert joint.get(job["id"])["status"] == "needs_review"


def test_receipt_detects_payload_and_event_tampering(isolated):
    job = mission()
    job["events"][0]["detail"]["plan_sha256"] = "tampered"
    assert not joint.export(job)["integrity"]["event_chain_valid"]
    job["results"]["fake"] = {"sha256": "0" * 64, "data": {"invented": True}}
    assert not joint.export(job)["integrity"]["result_hashes_valid"]


def test_readonly_goal_cannot_enable_mutation(isolated):
    with pytest.raises(ValueError):
        mission(goal="只读核查联合系统", mutate_sandbox=True)


def records():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [EnergyRecord(timestamp=t + timedelta(minutes=15 * i), load_kw=1. + i % 7 / 10,
        vessel_count=10. + i % 4, anchored_vessels=2., avg_sog_knots=4., wind_speed_mps=3., visibility_km=10.) for i in range(240)]


@pytest.mark.parametrize("environment_type", ["energy", "port"])
def test_future_record_cannot_change_present_observation(environment_type):
    source = records()
    altered = [*source]
    altered[6] = replace(source[6], load_kw=999999., vessel_count=999999.)
    if environment_type == "energy":
        parameters = derive_parameters(source[:100])
        def make(data):
            return EnergySchedulingEnvironment(data, parameters, horizon_steps=12, seed=1, split_name="test", render_mode=None)
    else:
        parameters = derive_port_parameters(source[:100])
        def make(data):
            return PortOperationsEnvironment(data, parameters, horizon_steps=12, seed=1, split_name="test", render_mode=None)
    left, right = make(source), make(altered)
    assert left.reset(start_index=5) == right.reset(start_index=5)


def test_research_rejects_unsupported_algorithms_and_duplicate_seeds():
    with pytest.raises(ValueError):
        research.ExperimentArgs(algorithms=["pretend_ppo"])
    with pytest.raises(ValueError):
        research.ExperimentArgs(seeds=[1, 1])


def test_experiment_separates_training_validation_and_test(isolated, tmp_path, monkeypatch):
    source = tmp_path / "dataset.csv"
    source.write_text("fixture dataset identity")
    class Dataset:
        path = source
        environment_type = "energy_storage"
    monkeypatch.setattr(research, "get_dataset", lambda _: Dataset())
    monkeypatch.setattr(research, "load_records", lambda _: records())
    report = research.compare(research.ExperimentArgs(episodes=10, seeds=[1, 2], horizon_steps=12,
                              algorithms=["q_learning"]), tmp_path / "trial")
    assert report["selection_basis"] == "validation_only"
    assert report["test_used_for_training"] is False
    assert report["observation_information"] == "current_and_past_only"
    assert len(report["models"]) == 2
    assert len(report["runs"]) == 6
    assert all(r["enterprise_admission"] is False for r in report["aggregate"])
    assert report["source_hashes"] == research.source_hashes()
    assert report["dataset_contract_sha256"] == digest(report["dataset_contract"])
    frames = report["traces"][0]["frames"]
    assert frames and all("state" in f and "reward" in f for f in frames)
    assert all(f["valid_action_mask"][f["action"]] for f in frames)
    assert (tmp_path / "trial/report.json").is_file()
    assert json.loads((tmp_path / "trial/report.json").read_text())["dataset_sha256"] == report["dataset_sha256"]


def test_feature_flag_leaves_legacy_task_creation_available(isolated, tmp_path, monkeypatch):
    monkeypatch.setenv("XIAOYI_DUAL_HARNESS_ENABLED", "false")
    harness = Harness(HarnessStore(tmp_path / "harness.db"))
    try:
        old = harness.create(CreateTask(goal="计算 1+1", request_id="legacy-still-001", driver="rules"), OPERATOR, schedule=False)
        assert old["mode"] == "enterprise"
        with pytest.raises(ValueError):
            harness.create(CreateTask(goal="开展策略研究", request_id="research-off-001", mode="research"), OPERATOR, schedule=False)
    finally:
        harness.close()


def test_unfinished_mission_limit_preserves_existing_records(isolated):
    for index in range(10):
        joint.create(joint.MissionCreate(request_id=f"bounded-preview-{index:03}"), OPERATOR)
    with pytest.raises(Conflict):
        joint.create(joint.MissionCreate(request_id="bounded-preview-overflow"), OPERATOR)
    assert len(joint.list_jobs(OPERATOR.actor_id)) == 10


def test_research_mission_requires_current_verified_experiment(isolated):
    with pytest.raises(ValueError):
        mission(mode="research")


def test_plan_parameter_tampering_blocks_approval(isolated):
    job = mission()
    job["config"]["mutate_sandbox"] = True
    isolated.save_artifact(joint.KIND, job["id"], job)
    with pytest.raises(Conflict):
        approve(job)


def test_joint_preview_is_a_verified_plan_not_an_execution(isolated, tmp_path):
    harness = Harness(HarnessStore(tmp_path / "harness.db"))
    try:
        task = harness.create(CreateTask(goal="生成五系统联合计划", request_id="joint-preview-001", template_id="joint-preview", driver="rules"), OPERATOR)
        end = time.monotonic() + 10
        while time.monotonic() < end:
            task = harness.store.get(task["id"])
            if task["status"] not in {"running", "queued"}:
                break
            time.sleep(.02)
        assert task["status"] == "completed", task.get("stop_reason")
        jobs = joint.list_jobs(OPERATOR.actor_id)
        assert jobs[0]["status"] == "waiting_approval"
        assert jobs[0]["results"] == {}
    finally:
        harness.close()
