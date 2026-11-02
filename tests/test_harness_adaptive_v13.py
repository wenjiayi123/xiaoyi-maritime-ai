"""Mechanism tests use explicit scripted drivers, never count as model intelligence."""
import copy
import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.access_control import IdentityContext
from app.harness import api, model, tools
from app.harness.adaptive import InspectArgs, ResultArgs, completion_issues, verify_execution
from app.harness.contracts import Action, CreateTask, digest
from app.harness.runner import Harness
from app.harness.store import HarnessStore
from app.main import app

ACTOR = IdentityContext("v13-test", "admin", True, "test")


class Driver:
    def __init__(self, actions):
        self.actions = iter(actions)

    def next(self, task, messages):
        item = next(self.actions)
        if callable(item):
            item = item(task)
        return Action.model_validate(item), {"tokens": 10}


def wait(h, id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        t = h.store.get(id)
        if t["status"] not in {"queued", "running"} and id not in h.active:
            return t
        time.sleep(.01)
    raise AssertionError(h.store.get(id))


@pytest.fixture
def harness(tmp_path):
    h = Harness(HarnessStore(tmp_path / "adaptive.sqlite"))
    yield h
    h.close()


def run(h, actions, **kwargs):
    h.model_driver = Driver(actions)
    task = h.create(CreateTask(goal=kwargs.pop("goal", "完成计算"), request_id=uuid4().hex,
        driver="model", planning_mode="adaptive", **kwargs), ACTOR)
    return wait(h, task["id"])


def test_adaptive_keeps_multiple_tools_available_after_required_read():
    task = {"planning_mode": "adaptive", "allowed_tools": ["runtime.snapshot", "knowledge.search", "calculate"],
        "required_tools": ["runtime.snapshot"], "results": []}
    assert model.decision_tools(task) == task["allowed_tools"]
    task["results"] = [{"ok": True, "tool": "runtime.snapshot"}]
    assert model.decision_tools(task) == task["allowed_tools"]


def test_adaptive_cannot_masquerade_as_rules_or_template():
    for args in [{"driver": "rules"}, {"template_id": "port-query"}]:
        with pytest.raises(ValueError):
            CreateTask(goal="测试任务", request_id=uuid4().hex, planning_mode="adaptive", **args)


def test_unconfigured_model_does_not_silently_fallback(harness, monkeypatch):
    monkeypatch.setattr(model, "configuration", lambda: {"available": False, "name": "", "local": False})
    with pytest.raises(ValueError, match="模型尚未配置"):
        harness.create(CreateTask(goal="检查能碳", request_id=uuid4().hex, planning_mode="adaptive"), ACTOR)


def test_linked_schema_binds_action_to_real_parameters(harness):
    task = harness.create(CreateTask(goal="试算能碳", request_id=uuid4().hex, driver="rules", allowed_tools=["linked.action"]), ACTOR, schedule=False)
    schema = model.wire_schema(task)
    variants = schema["properties"]["action"]["anyOf"][0]["properties"]["arguments"]["anyOf"]
    energy = next(v for v in variants if v["properties"]["action_id"]["const"] == "energy.compare")
    assert energy["properties"]["parameters"]["properties"]["green_preference"]["maximum"] == 1
    assert energy["properties"]["parameters"]["additionalProperties"] is False
    clock = next(v for v in variants if v["properties"]["action_id"]["const"] == "energy.clock")
    assert clock["properties"]["parameters"]["properties"]["action"]["enum"] == ["start", "stop"]


def test_invalid_resource_can_be_repaired_before_any_io(harness, monkeypatch):
    calls = []
    monkeypatch.setattr(tools, "execute", lambda name, args, *a, **kw: calls.append(copy.deepcopy(args)) or {"target":"energy-cockpit", "resource":"scenarios", "data":{}})
    t = run(harness, [
        {"kind":"tool", "tool":"systems.inspect", "arguments":{"target":"all","resource":"forecast"}},
        {"kind":"tool", "tool":"systems.inspect", "arguments":{"target":"energy-cockpit","resource":"scenarios"}},
        {"kind":"final", "text":"已读取工程模拟情景目录 [T1]。", "evidence_ids":["T1"]},
    ], allowed_tools=["systems.inspect"], goal="查看能碳情景")
    assert t["status"] == "completed"
    assert len(calls) == 1 and t["argument_repairs"] == 1
    assert not t.get("last_model_error")


def test_read_failure_retry_preserves_failure_and_resolves(harness, monkeypatch):
    real = tools.execute
    calls = []

    def flaky(name, args, *a, **kw):
        calls.append(name)
        if len(calls) == 1:
            raise TimeoutError()
        return real(name, args, *a, **kw)

    monkeypatch.setattr(tools, "execute", flaky)
    t = run(harness, [
        {"kind":"tool","tool":"calculate","arguments":{"expression":"8*9"}},
        {"kind":"tool","tool":"calculate","arguments":{"expression":"8*9"}},
        {"kind":"final","text":"计算结果为72 [T2]。","evidence_ids":["T2"]},
    ], allowed_tools=["calculate"])
    assert t["status"] == "completed"
    assert not t["results"][0]["ok"] and t["results"][0]["resolved_by"] == "T2"
    assert harness.store.artifact(t["id"], "T1.json")


def test_blocked_tool_result_is_not_success(harness, monkeypatch):
    monkeypatch.setattr(tools, "execute", lambda *a, **kw: {"status":"blocked"})
    t = run(harness, [{"kind":"tool","tool":"calculate","arguments":{"expression":"2+2"}},
        {"kind":"ask","text":"工具被阻止，请核查。"}], allowed_tools=["calculate"])
    assert not t["results"][0]["ok"] and t["status"] == "waiting_input"


def stored_action(h):
    task = h.create(CreateTask(goal="执行模拟操作",request_id=uuid4().hex,driver="rules",allowed_tools=["linked.action"]),ACTOR,schedule=False)
    task["planning_mode"] = "adaptive"
    run = {"id":"lar-test", "status":"completed", "applied":True, "restored":False, "production_authority":False,
        "expected_config":{"running":False}, "plan":{"action_id":"malacca.clock","target":"malacca-sandbox",
        "mutates":True,"restore_after_observation":False,"before":{"config":{"running":True}}}}
    raw = json.dumps({"linked_run_id":run["id"],"receipt":run})
    h.store.artifact(task["id"],"T1.json",raw)
    task["results"]=[{"id":"T1","tool":"linked.action","ok":True,"arguments":{"action_id":"malacca.clock"},"artifact":"T1.json","sha256":digest(raw)}]
    return task,run


def test_action_cannot_finish_without_independent_readback(harness):
    task,_ = stored_action(harness)
    assert any("独立执行核验" in issue for issue in completion_issues(task,harness.store))


def test_independent_readback_detects_external_change(harness,monkeypatch):
    from app import linked_agent

    task,run = stored_action(harness)
    monkeypatch.setattr(linked_agent,"get_run",lambda *a:run)
    monkeypatch.setattr(linked_agent,"_observe",lambda *a:{"config":{"running":True}})
    result = verify_execution(ResultArgs(source_ref="T1"),task,harness.store)
    assert result["status"] == "failed" and not result["checks"]["readback_matches"]


def test_forged_or_foreign_reference_rejected(harness):
    task,_ = stored_action(harness)
    with pytest.raises(ValueError):
        verify_execution(ResultArgs(source_ref="T9"),task,harness.store)
    harness.store.artifact(task["id"],"T1.json","{}")
    with pytest.raises(ValueError,match="完整性"):
        verify_execution(ResultArgs(source_ref="T1"),task,harness.store)


def test_loaded_model_context_contains_callable_signatures(harness):
    task = harness.create(CreateTask(goal="能碳参数对比", request_id=uuid4().hex, driver="rules",
        allowed_tools=["linked.action", "systems.inspect"]), ACTOR, schedule=False)
    task["planning_mode"] = "adaptive"
    messages, _ = model.context(task, [])
    assert "baseline_green_preference" in messages[0]["content"]
    assert "carbon_price_cny_per_ton" in messages[0]["content"]
    assert '"action"' in messages[0]["content"]


def test_explicit_parameters_cannot_be_lost_to_defaults(harness, monkeypatch):
    from app import linked_agent
    from app.harness.adaptive import explicit_parameters

    task = {"goal":"能碳基准绿色偏好0.5，候选0.72，碳价120", "inputs":[],
        "planning_mode":"adaptive", "actor_role":"admin", "allowed_tools":["linked.action"]}
    expected = {"baseline_green_preference":.5,"green_preference":.72,"carbon_price_cny_per_ton":120}
    assert explicit_parameters(task,"energy.compare") == expected
    task.update(required_tools=[],results=[],plan=[])
    schema = model.wire_schema(task)
    variants = schema["properties"]["action"]["anyOf"][0]["properties"]["arguments"]["anyOf"]
    energy = next(v for v in variants if v["properties"]["action_id"]["const"] == "energy.compare")
    assert energy["properties"]["parameters"]["properties"]["carbon_price_cny_per_ton"] == {"const":120.0}
    assert set(energy["properties"]["parameters"]["required"]) == set(expected)
    monkeypatch.setattr(linked_agent, "prepare", lambda *a:pytest.fail("incorrect parameters must not reach target"))
    with pytest.raises(ValueError, match="明确指定"):
        tools.prepare_action(task, {"action_id":"energy.compare", "parameters":{"green_preference":.72}})
    task["inputs"] = [{"text":"改为候选绿色偏好80%，碳价100"}]
    assert explicit_parameters(task,"energy.compare") == {**expected,"green_preference":.8,"carbon_price_cny_per_ton":100}


def test_reconcile_restore_requires_restored_receipt_and_current_state(harness, monkeypatch):
    from app import linked_agent
    from app.harness.store import Conflict

    task, receipt = stored_action(harness)
    def uncertain(t):
        t.update(status="needs_review", inflight={"side_effect":True,"tool":"execution.restore",
            "id":"call-restore","linked_run_id":receipt["id"],"arguments":{"source_ref":"T1"}})
    task = harness.store.mutate(task["id"], uncertain, "test.uncertain")
    monkeypatch.setattr(linked_agent, "get_run", lambda *a:receipt)
    monkeypatch.setattr(linked_agent, "_observe", lambda *a:{"config":{"running":False}})
    with pytest.raises(Conflict, match="恢复"):
        harness.reconcile(task)
    receipt["restored"] = True
    with pytest.raises(Conflict, match="恢复"):
        harness.reconcile(task)
    monkeypatch.setattr(linked_agent, "_observe", lambda *a:{"config":{"running":True}})
    reconciled = harness.reconcile(task)
    assert reconciled["status"] == "paused"
    assert json.loads(harness.store.artifact(task["id"], "T1.json")["content"])["source_ref"] == "T1"


def test_trajectory_detects_tampering_and_never_claims_training(harness):
    from app.harness.trajectory import export_trajectory

    task = run(harness, [{"kind":"tool","tool":"calculate","arguments":{"expression":"9*7"}},
        {"kind":"final","text":"计算得到63 [T1]。","evidence_ids":["T1"]}], allowed_tools=["calculate"])
    exported = export_trajectory(task, harness.store)
    assert exported["integrity"] == {"event_chain":True,"artifacts":True}
    assert len(exported["transitions"]) == 2
    assert not exported["training_performed"] and not exported["reward_assigned"]
    harness.store.artifact(task["id"], "T1.json", "{}")
    assert not export_trajectory(task,harness.store)["integrity"]["artifacts"]


def test_fresh_timestamps_do_not_hide_repeated_identical_reads(harness,monkeypatch):
    monkeypatch.setattr(tools,"execute",lambda *a,**k:{"time":time.time()})
    action = {"kind":"tool","tool":"calculate","arguments":{"expression":"9*7"}}
    task = run(harness,[action,action,action],allowed_tools=["calculate"])
    assert task["status"] == "blocked" and task["usage"]["tool_calls"] == 2


def test_runtime_verifies_action_before_next_model_decision(harness,monkeypatch):
    from app.harness.contracts import ApprovalRequest

    monkeypatch.setattr(tools,"prepare_action",lambda *a:{"expires_at_epoch":time.time()+300})
    def execute(name,args,*a,**kw):
        if name == "linked.action":
            return {"status":"completed","linked_run_id":"lar-test","receipt":{"plan":{
                "target":"energy-cockpit","action_id":"energy.compare","parameters":{}}}}
        assert name == "execution.verify"
        return {"status":"completed","source_ref":"T1","checks":{"readback":True}}
    monkeypatch.setattr(tools,"execute",execute)
    task = run(harness,[{"kind":"tool","tool":"linked.action","arguments":{"action_id":"energy.compare"}},
        {"kind":"final","text":"工程模拟试算已执行并核验 [T1][T2]。","evidence_ids":["T1","T2"]}],
        allowed_tools=["linked.action","execution.verify"],goal="完成默认试算")
    pending = task["pending"]
    harness.approve(task["id"],ApprovalRequest(approval_id=pending["id"],action_sha256=pending["action_sha256"],approve=True),ACTOR)
    task = wait(harness,task["id"])
    assert task["status"] == "completed"
    assert [r["tool"] for r in task["results"]] == ["linked.action","execution.verify"]
    events = harness.store.events(task["id"],0,200)
    assert sum(e["event"] == "model.action" for e in events) == 2
    assert any(e["event"] == "verification.scheduled" for e in events)


def test_online_status_cannot_substitute_for_requested_resources(harness):
    task = harness.create(CreateTask(goal="读取能碳的情景目录、数字孪生的能力覆盖、马六甲的运行快照。只读，不调整配置。",
        request_id=uuid4().hex,driver="rules",allowed_tools=["systems.inspect"]),ACTOR,schedule=False)
    task["planning_mode"] = "adaptive"
    raw = json.dumps({"target":"all","resource":"status","data":{"systems":[{"target":t} for t in ["energy-cockpit","port-dt-multi","malacca-sandbox"]]}})
    harness.store.artifact(task["id"],"T1.json",raw)
    task["results"] = [{"id":"T1","ok":True,"tool":"systems.inspect","artifact":"T1.json","sha256":digest(raw)}]
    issues = completion_issues(task,harness.store)
    assert len(issues) == 3 and all("资源尚未读取" in issue for issue in issues)


def test_unbacked_summary_number_is_repaired_without_reexecuting(harness):
    task = run(harness,[{"kind":"tool","tool":"calculate","arguments":{"expression":"9*7"}},
        {"kind":"final","text":"结果为64 [T1]。","evidence_ids":["T1"]},
        {"kind":"final","text":"结果为63 [T1]。","evidence_ids":["T1"]}],allowed_tools=["calculate"])
    assert task["status"] == "completed" and task["numeric_repairs"] == 1
    assert task["usage"]["tool_calls"] == 1
    events = harness.store.events(task["id"],0,200)
    assert any(e["event"] == "completion.numeric_repair" and e["detail"]["unsupported_numbers"] for e in events)


def test_router_preserves_conceptual_chat_and_uses_model_for_actions(harness,monkeypatch):
    monkeypatch.setattr(api,"get_harness",lambda:harness)
    harness.model_driver = Driver([{"kind":"ask","text":"测试驱动结束"}])
    with TestClient(app) as client:
        ordinary = client.post("/api/harness/chat",json={"text":"能碳的原理是什么", "request_id":uuid4().hex}).json()
        assert ordinary["handled"] is False
        result = client.post("/api/harness/chat",json={"text":"查看能碳和马六甲状态", "request_id":uuid4().hex}).json()
        assert result["handled"] and result["task"]["planning_mode"] == "adaptive"
        assert result["task"]["required_tools"] == [] and result["task"]["template_id"] is None


def test_resource_allowlist_rejects_urls():
    with pytest.raises(ValueError):
        InspectArgs(target="http://example.com",resource="snapshot")
