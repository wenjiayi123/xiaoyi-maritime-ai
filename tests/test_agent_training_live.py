import json
from dataclasses import replace

import pytest

from app.agent_training.environment import TaskEnvironment, make_task, reference_action
from app.agent_training.live import ACCEPTANCE_GOAL, NativeBackend, native_step, parse_goal


def test_acceptance_instruction_resolves_explicit_constraints():
    task = parse_goal(ACCEPTANCE_GOAL, inject_read_fault=True)
    assert task.family == "joint"
    assert (task.baseline, task.green, task.carbon) == (0.5, 0.82, 85)
    assert task.scenario == "high_density_berthing" and task.fault == "transient_read"


def test_native_error_does_not_advance_synthetic_success_state(tmp_path):
    env = TaskEnvironment(make_task("acceptance", "port_read", 0))

    class BrokenBackend:
        def execute(self, *args):
            raise TimeoutError("native offline")

    result = native_step(env, BrokenBackend(), "A")
    assert not result["ok"] and not env.reads and not env.success


def test_injected_failure_does_not_claim_a_native_call():
    task = replace(make_task("acceptance", "joint", 0), fault="transient_read")
    env = TaskEnvironment(task)
    result = native_step(env, None, "B")
    assert result["fault_injection"] and not result["native_executed"] and not env.reads


def test_native_report_rejects_missing_real_receipts(tmp_path):
    env = TaskEnvironment(make_task("acceptance", "joint", 0))
    while not env.done:
        env.step(reference_action(env))
    assert env.success
    with pytest.raises(ValueError):
        NativeBackend(tmp_path).verify(env)


def test_native_record_tamper_rejected(tmp_path):
    env = TaskEnvironment(make_task("acceptance", "port_read", 0))
    backend = NativeBackend(tmp_path)
    row = backend.record({"tool": "port.read", "arguments": {}}, {"production_authority": False})
    path = tmp_path / row["file"]
    data = json.loads(path.read_text())
    data["response"]["changed"] = True
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        backend.verify(env)


def test_observation_preserves_zero_and_distinguishes_simulation_time(tmp_path, monkeypatch):
    backend = NativeBackend(tmp_path)
    raw = {
        "production_authority": False,
        "data_mode": "public_data_calibrated_realtime_simulation",
        "site_id": "test-sim",
        "generated_at": "2026-11-01T00:00:00Z",
        "virtual_event_time": "2026-08-01T00:00:00Z",
        "signals": {},
        "kpis": {"current": {"safety_violations": 0}},
    }
    monkeypatch.setattr(backend, "request", lambda *args: raw)
    backend.read("energy")
    summary = backend.summaries["energy"]
    assert summary["observed_at"] != summary["event_time"]
    assert summary["metrics"][0]["value"] is None
    assert summary["metrics"][2]["value"] == 0


def test_unavailable_port_state_cannot_be_recorded_as_success(tmp_path, monkeypatch):
    backend = NativeBackend(tmp_path)
    monkeypatch.setattr(backend, "request", lambda *args: {"production_authority": False, "available": False})
    with pytest.raises(ValueError, match="unavailable"):
        backend.read("port")


def test_local_verification_and_report_are_not_labeled_as_remote_api_responses(tmp_path, monkeypatch):
    env = TaskEnvironment(make_task("acceptance", "port_read", 0))
    backend = NativeBackend(tmp_path)
    calls = []

    def request(*args):
        calls.append(args)
        return {"production_authority": False, "available": True, "aggregate_kw": 0}

    monkeypatch.setattr(backend, "request", request)
    read = native_step(env, backend, "A")
    check = native_step(env, backend, "I")
    report = native_step(env, backend, "J")
    assert env.success and len(calls) == 1
    assert read["execution_origin"] == "actual_local_system_api"
    assert check["execution_origin"] == report["execution_origin"] == "local_runtime_tool"
    evidence = json.loads((tmp_path / report["native_evidence"]["file"]).read_text())
    assert evidence["source"] == "local_runtime_tool"


@pytest.mark.parametrize("goal", ["下发真实设备控制", "暂停能碳时钟", "做任意代码运行", "写一首诗"])
def test_unsupported_instructions_not_silently_claimed(goal):
    with pytest.raises(ValueError):
        parse_goal(goal)


@pytest.mark.parametrize("goal", ["只查询港口并评估靠泊情景", "只读能源绿色偏好0.8", "读取港口，不要评估靠泊情景"])
def test_keyword_parser_cannot_override_read_only_or_negative_constraints(goal):
    with pytest.raises(ValueError):
        parse_goal(goal)


def test_explicit_read_only_port_query_remains_supported():
    assert parse_goal("只读取港口当前状态并给我报告").family == "port_read"
