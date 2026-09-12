import copy
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import linked_agent as agent
from app.linked_agent_catalog import parse_command
from app.main import app
from app.runtime_store import RuntimeStore


@pytest.fixture
def local(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "runtime_store", RuntimeStore(tmp_path / "jobs.sqlite3"))
    state = {"scenario": "normal", "running": True, "run_id": "test-run"}
    writes = []

    def observe(target):
        return {"observed_at": agent.now(), "source_time": "engineering-clock", "config": copy.deepcopy(state), "metrics": {"queue": 10 if state["scenario"] == "normal" else 20}, "payload_sha256": agent.digest(state), "production_authority": False, "source": "test-contract"}

    def request(target, method, path, payload=None):
        writes.append((path, payload))
        if path.endswith("scenarios"):
            state["scenario"] = payload["scenario"]
        elif path.endswith("control"):
            state["running"] = payload["action"] == "start"
        return copy.deepcopy(state)

    monkeypatch.setattr(agent, "_observe", observe)
    monkeypatch.setattr(agent, "_request", request)
    with TestClient(app) as client:
        yield client, state, writes
    deadline = time.monotonic() + 5
    while agent._active and time.monotonic() < deadline:
        time.sleep(.02)
    assert not agent._active


def prepare(client, **overrides):
    body = {"action_id": "malacca.scenario", "parameters": {"scenario": "peak-arrivals"}, "samples": 1, **overrides}
    return client.post("/api/linked-agent/plans", json=body)


def start(client, plan, request_id=None):
    return client.post(f"/api/linked-agent/plans/{plan['id']}/execute", json={"plan_sha256": plan["plan_sha256"], "request_id": request_id or uuid4().hex})


def finish(client, run_id):
    for _ in range(150):
        result = client.get(f"/api/linked-agent/runs/{run_id}").json()
        if result["status"] != "running":
            # Final receipt is committed just before releasing the target lock.
            for _ in range(100):
                if result["plan"]["target"] not in agent._active:
                    return result
                time.sleep(.01)
        time.sleep(.02)
    raise AssertionError("job did not terminate")


def test_scenario_adjust_observe_and_restore_are_real_calls(local):
    client, state, writes = local
    plan = prepare(client).json()
    assert not writes
    result = finish(client, start(client, plan).json()["id"])
    assert result["status"] == "completed"
    assert result["applied"] and result["restored"]
    assert result["observations"][0]["config"]["scenario"] == "peak-arrivals"
    assert result["changes"][0]["change"] == 10
    assert state["scenario"] == "normal"
    assert len(writes) == 2
    previous = "0" * 64
    for event in result["events"]:
        assert event["previous_sha256"] == previous
        assert agent.digest({k:v for k,v in event.items() if k != "sha256"}) == event["sha256"]
        previous = event["sha256"]


def test_repeated_requests_and_new_keys_cannot_repeat_prepared_plan(local):
    client, _, writes = local
    plan = prepare(client).json()
    first = start(client, plan, "request-12345678").json()
    finish(client, first["id"])
    assert start(client, plan, "request-12345678").json()["id"] == first["id"]
    assert start(client, plan).json()["id"] == first["id"]
    assert len(writes) == 2
    another = prepare(client).json()
    assert start(client, another, "request-12345678").status_code == 409


@pytest.mark.parametrize("params", [{"scenario":"unknown"},{"scenario":"normal","shell":"anything"}])
def test_invalid_parameters_are_rejected_before_io(local, params):
    client, _, writes = local
    assert prepare(client, parameters=params).status_code == 422
    assert not writes


@pytest.mark.parametrize("params", [{"green_preference":-1},{"green_preference":1.01},{"carbon_price_cny_per_ton":5001},{"base_url":"http://example.test"}])
def test_energy_bounds_and_extra_fields(local, params):
    client, _, _ = local
    assert prepare(client, action_id="energy.compare", parameters=params).status_code == 422


def test_stale_configuration_is_not_overwritten(local):
    client, state, writes = local
    plan = prepare(client).json()
    state["scenario"] = "channel-closure"
    result = finish(client, start(client, plan).json()["id"])
    assert result["status"] == "failed" and not writes


def test_manual_restore_refuses_to_overwrite_another_change(local):
    client, state, writes = local
    plan = prepare(client, restore_after_observation=False).json()
    result = finish(client, start(client, plan).json()["id"])
    assert result["applied"] and not result["restored"]
    state["scenario"] = "channel-closure"
    assert client.post(f"/api/linked-agent/runs/{result['id']}/rollback",json={}).status_code == 409
    assert len(writes) == 1
    state["scenario"] = "peak-arrivals"
    restored = client.post(f"/api/linked-agent/runs/{result['id']}/rollback",json={})
    assert restored.json()["restored"]
    assert state["scenario"] == "normal"


def test_cancel_observation_restores_applied_configuration(local):
    client, state, _ = local
    plan = prepare(client, samples=12, interval_seconds=2).json()
    run = start(client, plan).json()
    for _ in range(100):
        if state["scenario"] == "peak-arrivals":
            break
        time.sleep(.01)
    assert client.post(f"/api/linked-agent/runs/{run['id']}/cancel",json={}).json()["cancellation_requested"]
    result = finish(client, run["id"])
    assert result["status"] == "cancelled" and result["restored"]
    assert len(result["observations"]) < 12


def test_target_busy_blocks_second_operation(local):
    client, _, _ = local
    first = prepare(client, samples=12, interval_seconds=2).json()
    second = prepare(client).json()
    run = start(client, first).json()
    assert start(client, second).status_code == 409
    client.post(f"/api/linked-agent/runs/{run['id']}/cancel",json={})
    finish(client, run["id"])


def test_expired_or_mismatched_plan_cannot_execute(local):
    client, _, writes = local
    plan = prepare(client).json()
    wrong = copy.deepcopy(plan)
    wrong["plan_sha256"] = "0"*64
    assert start(client, wrong).status_code == 409
    plan["expires_at_epoch"] = 0
    agent.runtime_store.save_artifact(agent._PLAN_KIND,plan["id"],plan)
    assert start(client, plan).status_code == 409
    assert not writes


def test_uncertain_write_is_not_retried_or_falsely_completed(local, monkeypatch):
    client, _, writes = local
    def timeout(*args, **kwargs):
        writes.append("attempt")
        raise TimeoutError("sensitive adapter details")
    monkeypatch.setattr(agent,"_request",timeout)
    plan=prepare(client).json()
    result=finish(client,start(client,plan).json()["id"])
    assert result["status"] == "needs_review" and len(writes) == 1
    assert "sensitive" not in str(result)


def test_viewer_cannot_operate_and_operator_cannot_read_another_user(local):
    client, _, _ = local
    body={"action_id":"malacca.observe","samples":1}
    assert client.post("/api/linked-agent/plans",json=body,headers={"X-Xiaoyi-Role":"viewer"}).status_code == 403
    plan=client.post("/api/linked-agent/plans",json=body,headers={"X-Xiaoyi-Actor":"alice","X-Xiaoyi-Role":"operator"}).json()
    response=client.post(f"/api/linked-agent/plans/{plan['id']}/execute",json={"plan_sha256":plan["plan_sha256"],"request_id":uuid4().hex},headers={"X-Xiaoyi-Actor":"bob","X-Xiaoyi-Role":"operator"})
    assert response.status_code == 403


@pytest.mark.parametrize("text,action", [("能碳绿色偏好调到80%，碳价100，进行对比试算","energy.compare"),("马六甲切换集中到港并观测","malacca.scenario"),("暂停马六甲模拟时钟并观测","malacca.clock"),("观测数字孪生","port.observe")])
def test_natural_commands_map_only_to_registered_actions(text,action):
    assert parse_command(text)["action_id"] == action


def test_vague_parameter_or_question_does_not_invent_an_action():
    assert parse_command("能碳调节参数").get("clarification")
    assert parse_command("如何调整马六甲参数？") is None
    assert parse_command("不要暂停马六甲时钟") is None


@pytest.mark.parametrize("text,expected", [
    ("恢复马六甲模拟时钟", {"action_id": "malacca.clock", "parameters": {"action": "start"}}),
    ("马六甲时钟恢复", {"action_id": "malacca.observe", "parameters": {}}),
    ("马六甲" + "恢复" * 10000, {"action_id": "malacca.observe", "parameters": {}}),
    ("马六甲" + "恢复" * 10000 + "时钟", {"action_id": "malacca.clock", "parameters": {"action": "start"}}),
    ("暂停马六甲时钟后恢复时钟", {"action_id": "malacca.clock", "parameters": {"action": "stop"}}),
    ("不要恢复马六甲时钟", None),
])
def test_clock_parser_handles_repeated_text_without_loosening_command_guards(text, expected):
    assert parse_command(text) == expected


def test_natural_scenario_plan_has_real_preview_and_confirmation():
    with TestClient(app) as client:
        plan=client.post("/api/automation/plans",json={"command":"马六甲切换集中到港并观测"}).json()
    assert [step["kind"] for step in plan["actions"]] == ["prepare_linked_operation","run_linked_operation","present_linked_operation"]
    assert plan["actions"][1]["requires_confirmation"] is True


@pytest.mark.parametrize('invalid', ['dataset_changed', 'missing_provenance', 'dispatch_enabled', 'ignored_price'])
def test_energy_compare_rejects_incomparable_or_unverified_results(local, monkeypatch, invalid):
    client, _, _ = local
    calls = []
    def reply(target, method, path, payload=None):
        calls.append(payload)
        raw = {'green_preference': payload['green_preference'],
               'carbon_market': {'carbon_price_cny_per_ton': payload['carbon_price_cny_per_ton']},
               'rl_environment': {'dataset_id': 'public-hourly', 'dataset_sha256': 'a' * 64},
               'governance': {'production_dispatch_enabled': False}}
        if invalid == 'dataset_changed' and len(calls) == 2:
            raw['rl_environment']['dataset_sha256'] = 'b' * 64
        elif invalid == 'missing_provenance':
            raw['rl_environment'].pop('dataset_sha256')
        elif invalid == 'dispatch_enabled':
            raw['governance']['production_dispatch_enabled'] = True
        elif invalid == 'ignored_price':
            raw['carbon_market']['carbon_price_cny_per_ton'] = 999
        return raw
    monkeypatch.setattr(agent, '_request', reply)
    plan = prepare(client, action_id='energy.compare', parameters={}).json()
    result = finish(client, start(client, plan).json()['id'])
    assert result['status'] == 'failed' and 'evaluation' not in result
    assert not result.get('write_attempted')


@pytest.mark.parametrize('target,reply', [
    ('malacca-sandbox', {'authority': {'simulation_mode': True, 'production_authority': False}}),
    ('energy-cockpit', {'production_authority': False, 'data_mode': 'live'}),
    ('port-dt-multi', {'aggregate_kw': 10}),
])
def test_observation_refuses_missing_or_live_authority(monkeypatch, target, reply):
    monkeypatch.setattr(agent, '_request', lambda *a, **kw: reply)
    with pytest.raises(ValueError):
        agent._observe(target)


def test_unsupported_parameter_request_prompts_instead_of_pretending_to_observe():
    assert parse_command('调整数字孪生设备速度').get('clarification')
    assert parse_command('观测能碳和马六甲').get('clarification')
    assert parse_command('能碳绿色偏好调整到80%，碳价-100，试算')['parameters']['carbon_price_cny_per_ton'] == -100
    with TestClient(app) as client:
        plan = client.post('/api/automation/plans', json={'command': '能碳调节参数'}).json()
    assert [a['kind'] for a in plan['actions']] == ['clarify_linked_operation']
