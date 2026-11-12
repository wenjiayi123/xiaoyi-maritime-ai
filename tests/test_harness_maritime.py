"""Business outcome, evidence lineage, reproducibility and non-interference tests."""

import copy
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.access_control import IdentityContext
from app.harness import maritime, model, tools
from app.harness.contracts import Action, Budget, CreateTask, InputRequest, digest, encoded, completed_tools
from app.harness.verification import verify
from app.harness.runner import Harness
from app.harness.store import Conflict, HarnessStore
from app.realtime_port_simulator import PortRealtimeSimulator


@pytest.fixture
def h(tmp_path):
    runtime = Harness(HarnessStore(tmp_path / "business.db"))
    yield runtime
    runtime.close()


@pytest.fixture
def snapshot():
    sim = PortRealtimeSimulator()
    return jsonable_encoder(sim.snapshot_at(sequence=10, observed_at=datetime.now(timezone.utc).replace(microsecond=0)))


def task(h, **kwargs):
    return h.create(
        CreateTask(goal="港区分析", driver="rules", request_id="test-" + str(time.time_ns()), **kwargs),
        IdentityContext("alice", "operator", True, "test"),
        schedule=False,
    )


def attach(h, t, name, content):
    ref = "T" + str(len(t["results"]) + 1)
    text = encoded(content)
    h.store.artifact(t["id"], ref + ".json", text)

    def update(row):
        row["results"].append(
            {
                "id": ref,
                "tool": name,
                "ok": True,
                "artifact": ref + ".json",
                "sha256": digest(text),
                "summary": text[:2000],
            }
        )

    t = h.store.mutate(t["id"], update, "test.evidence")
    return t, ref


def captured(h, snapshot):
    return attach(
        h, task(h), "runtime.snapshot", {"snapshot": snapshot, "simulator_source_sha256": maritime.simulator_digest()}
    )


def settle(h, task_id):
    for _ in range(500):
        t = h.store.get(task_id)
        if t["status"] not in {"queued", "running"} and task_id not in h.active:
            return t
        time.sleep(0.01)
    raise AssertionError(t)


@pytest.mark.parametrize("template", [t["id"] for t in maritime.TEMPLATES])
def test_business_template_executes_real_tools_to_verified_completion(h, template):
    t = task(h, template_id=template)
    h.schedule(t["id"])
    t = settle(h, t["id"])
    assert t["status"] == "completed", t["stop_reason"]
    assert set(t["required_tools"]).issubset({r["tool"] for r in t["results"] if r["ok"]})
    assert t["final"]["verification"]["passed"]
    if template == "port-briefing":
        assert "港航交接简报" in t["final"]["text"] and "当班责任人" in t["final"]["text"]


@pytest.mark.parametrize("value", ["2000-01-01T00:00:00Z", "2099-01-01T00:00:00Z", "bad", "2026-10-29T10:00:00"])
def test_stale_future_invalid_or_naive_time_withholds_recommendations(h, snapshot, value):
    snapshot["metadata"]["observed_at"] = value
    t, ref = captured(h, snapshot)
    report = tools.execute("maritime.risk", {"source_ref": ref}, t, h.store)
    assert not report["readiness"]["analysis_usable"] and report["recommendation_status"] == "withheld"
    assert report["readiness"]["operational_release"] is False


def test_fresh_envelope_does_not_hide_stale_sensor(snapshot):
    snapshot["energy"]["observed_at"] = "2000-01-01T00:00:00Z"
    gate = maritime.readiness(snapshot)
    assert gate["checks"]["fresh"] and not gate["analysis_usable"] and "energy" in gate["stale_components"]


def test_missing_domain_is_unknown_not_zero(snapshot):
    snapshot.pop("equipment")
    assert maritime.metric_values(snapshot)["low_soc_agv"] is None
    assert not maritime.readiness(snapshot)["analysis_usable"]


def test_semantic_metrics_preserve_zero_and_use_capacity_weighting(h, snapshot):
    agvs = [r for r in snapshot["equipment"] if r["asset_type"] == "agv"]
    for a in agvs:
        a["soc_percent"] = 100
    agvs[0]["soc_percent"] = 0
    agvs[1]["soc_percent"] = None
    snapshot["yard_blocks"] = [{"capacity_teu": 100, "occupied_teu": 100}, {"capacity_teu": 900, "occupied_teu": 0}]
    t, ref = captured(h, snapshot)
    data = tools.execute(
        "maritime.query", {"source_ref": ref, "metrics": ["low_soc_agv", "yard_occupancy", "grid_demand"]}, t, h.store
    )
    values = {r["metric_id"]: r for r in data["rows"]}
    assert values["low_soc_agv"]["value"] == 1 and values["yard_occupancy"]["value"] == 10
    assert values["grid_demand"]["unit"] == "kW"


@pytest.mark.parametrize("dataset,passed", [("port_calls", False), ("metrics", True)])
def test_requested_metrics_cannot_be_replaced_by_entity_rows(h, snapshot, dataset, passed):
    t, source_ref = captured(h, snapshot)
    data = tools.execute("maritime.query", {"source_ref": source_ref, "dataset": dataset}, t, h.store)
    t, query_ref = attach(h, t, "maritime.query", data)
    t['template_id'] = 'port-query'
    t['goal'] = '核对电网需量、岸电负荷、低电量AGV和闸口排队'
    check = verify(t, Action(kind='final', text='工程模拟，风险待复核。', evidence_ids=[query_ref]), h.store)
    assert check['business_claims'] is passed
    assert bool(check['business_issues']) is not passed


@pytest.mark.parametrize('scenarios,passed', [(['normal','storm'],False), (['normal','energy_peak','storm'],True)])
def test_requested_comparison_branch_must_exist_in_actual_artifact(h, snapshot, scenarios, passed):
    t, source_ref = captured(h, snapshot)
    data = tools.execute('twin.compare', {'source_ref':source_ref, 'scenarios':scenarios}, t, h.store)
    t, comparison_ref = attach(h, t, 'twin.compare', data)
    t['goal'] = '比较常态、大风与需量高峰，生成交接'
    check = verify(t, Action(kind='final', text='工程模拟，风险待复核。', evidence_ids=[comparison_ref]), h.store)
    assert check['business_claims'] is passed
    assert bool(check['business_issues']) is not passed


def test_zero_soc_is_also_counted_by_original_simulator(monkeypatch):
    sim = PortRealtimeSimulator()
    original = sim._equipment

    def equipment(*args):
        items = original(*args)
        next(r for r in items if r["asset_type"] == "agv")["soc_percent"] = 0
        return items

    monkeypatch.setattr(sim, "_equipment", equipment)
    s = sim.snapshot()
    count = sum(
        r["asset_type"] == "agv" and r["soc_percent"] is not None and r["soc_percent"] < 20 for r in s["equipment"]
    )
    assert s["fleet_summary"]["agv"]["low_soc"] == count


def test_entity_lookup_is_exact_and_retains_stable_identifier(h, snapshot):
    t, ref = captured(h, snapshot)
    imo = snapshot["port_calls"][0]["imo"]
    data = tools.execute(
        "maritime.query", {"source_ref": ref, "dataset": "port_calls", "entity_id": imo.lower()}, t, h.store
    )
    assert data["matched_count"] == 1 and data["rows"][0]["imo"] == imo
    empty = tools.execute(
        "maritime.query", {"source_ref": ref, "dataset": "port_calls", "entity_id": "IMO"}, t, h.store
    )
    assert empty["matched_count"] == 0


def test_query_pagination_discloses_truncation(h, snapshot):
    t, ref = captured(h, snapshot)
    data = tools.execute("maritime.query", {"source_ref": ref, "dataset": "equipment", "limit": 1}, t, h.store)
    assert len(data["rows"]) == 1 and data["matched_count"] > 1 and data["truncated"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"source_ref": "T1", "sql": "SELECT * FROM secrets"},
        {"source_ref": "T1", "metrics": ["made_up_kpi"]},
        {"source_ref": "../T1"},
    ],
)
def test_unregistered_queries_and_paths_are_rejected(arguments):
    with pytest.raises(ValidationError):
        maritime.QueryArgs.model_validate(arguments)


def test_task_boundary_and_artifact_integrity_enforced(h, snapshot):
    t, ref = captured(h, snapshot)
    other = task(h)
    with pytest.raises(ValueError, match="当前任务"):
        tools.execute("maritime.query", {"source_ref": ref}, other, h.store)
    h.store.artifact(t["id"], ref + ".json", "{}")
    with pytest.raises(ValueError, match="摘要"):
        tools.execute("maritime.query", {"source_ref": ref}, t, h.store)


@pytest.mark.parametrize("scenario", ["normal", "vessel_surge", "equipment_failure", "energy_peak", "storm"])
def test_comparison_reproduces_baseline_and_is_repeatable(h, snapshot, scenario):
    sim = PortRealtimeSimulator()
    sim._scenario_id = scenario
    snapshot = jsonable_encoder(
        sim.snapshot_at(sequence=19, observed_at=datetime.now(timezone.utc).replace(microsecond=0))
    )
    t, ref = captured(h, snapshot)
    args = {"source_ref": ref}
    before = copy.deepcopy(snapshot)
    first = tools.execute("twin.compare", args, t, h.store)
    second = tools.execute("twin.compare", args, t, h.store)
    assert first == second and snapshot == before
    assert first["branches"][0]["points"][0]["metrics"] == maritime.metric_values(snapshot)
    assert all(v == 0 for v in first["branches"][0]["delta_vs_baseline"].values() if v is not None)


def test_isolated_studies_never_change_live_simulator(h, snapshot, monkeypatch):
    from app.realtime_port_simulator import realtime_port_simulator

    original = realtime_port_simulator.status()
    events = copy.deepcopy(list(realtime_port_simulator._events))
    monkeypatch.setattr(realtime_port_simulator, "set_scenario", lambda *a: pytest.fail("live mutation"))
    t, ref = captured(h, snapshot)
    tools.execute("twin.compare", {"source_ref": ref, "horizon_minutes": 60, "samples": 12}, t, h.store)
    after = realtime_port_simulator.status()
    assert after["scenario_id"] == original["scenario_id"] and after["run_id"] == original["run_id"]
    assert list(realtime_port_simulator._events) == events


@pytest.mark.parametrize("change", ["source_hash", "calibration", "field", "live"])
def test_incompatible_or_unreproducible_baselines_are_rejected(h, snapshot, change):
    if change == "calibration":
        snapshot["lineage"]["public_ais_sha256"] = "0" * 64
    if change == "field":
        snapshot["energy"]["grid_demand_kw"] += 7
    if change == "live":
        snapshot["port"]["site_connected"] = True
    t, ref = captured(h, snapshot)
    if change == "source_hash":
        monkey = pytest.MonkeyPatch()
        monkey.setattr(maritime, "simulator_digest", lambda: "0" * 64)
    try:
        with pytest.raises(ValueError):
            tools.execute("twin.compare", {"source_ref": ref}, t, h.store)
    finally:
        if change == "source_hash":
            monkey.undo()


def test_power_imbalance_suppresses_recommendation(h, snapshot):
    snapshot["energy"]["power_balance_error_kw"] = 10
    t, ref = captured(h, snapshot)
    data = tools.execute("maritime.risk", {"source_ref": ref}, t, h.store)
    assert data["recommendation_status"] == "withheld" and any(
        f["rule_id"] == "power-balance" for f in data["findings"]
    )


def test_handover_refuses_mixed_snapshot_or_missing_specialty(h, snapshot):
    t, ref = captured(h, snapshot)
    report = tools.execute("maritime.query", {"source_ref": ref}, t, h.store)
    report["snapshot_sha256"] = "0" * 64
    t, query_ref = attach(h, t, "maritime.query", report)
    with pytest.raises(ValueError, match="同一基线"):
        tools.execute("maritime.handover", {"source_ref": ref, "result_refs": [query_ref]}, t, h.store)
    report["snapshot_sha256"] = digest(snapshot)
    t, second_ref = attach(h, t, "maritime.query", report)
    with pytest.raises(ValueError, match="三类证据"):
        tools.execute("maritime.handover", {"source_ref": ref, "result_refs": [second_ref]}, t, h.store)


def test_handover_rechecks_freshness_at_publication(h, snapshot, monkeypatch):
    t, ref = captured(h, snapshot)
    refs = []
    for name in ["maritime.query", "maritime.risk", "twin.compare"]:
        data = tools.execute(name, {"source_ref": ref}, t, h.store)
        t, report_ref = attach(h, t, name, data)
        refs.append(report_ref)
    future = datetime.now(timezone.utc) + timedelta(minutes=5)

    class LaterClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return future

    monkeypatch.setattr(maritime, "datetime", LaterClock)
    report = tools.execute("maritime.handover", {"source_ref": ref, "result_refs": refs}, t, h.store)
    assert report["recommendation_status"] == "withheld"
    assert not report["readiness"]["analysis_usable"] and not report["readiness"]["operational_release"]


def test_template_completion_contract_cannot_be_weakened(h):
    with pytest.raises(ValueError, match="不可省略"):
        task(h, template_id="port-briefing", required_tools=["runtime.snapshot"])


def test_business_dependencies_are_required_and_cannot_expand_tool_permissions(h):
    with pytest.raises(ValueError, match="允许范围"):
        task(h, allowed_tools=["maritime.query"], required_tools=["maritime.query"])
    t = task(h, required_tools=["maritime.handover"])
    assert set(t["required_tools"]) == set(maritime.REQUIRED)


def test_template_budget_defaults_respect_explicit_user_limits(h):
    t = task(h, template_id="port-briefing")
    assert t["budget"]["max_tokens"] == 32000 and t["budget"]["max_active_seconds"] == 600
    explicit = task(h, template_id="port-briefing", budget=Budget(max_tokens=2048, max_active_seconds=5))
    assert explicit["budget"]["max_tokens"] == 2048 and explicit["budget"]["max_active_seconds"] == 5
    with pytest.raises(Conflict):
        h.create(
            CreateTask(
                goal="港区分析",
                driver="rules",
                request_id=t["request_id"],
                template_id="port-briefing",
                budget=Budget(max_tokens=16000),
            ),
            IdentityContext("alice", "operator", True, "test"),
            schedule=False,
        )


def test_model_receives_only_the_next_missing_business_stage(h):
    t = task(h, template_id="port-briefing")
    assert model.decision_tools(t) == ["runtime.snapshot"]
    t["results"] = [{"id": "T1", "ok": True, "tool": "runtime.snapshot"}]
    assert model.decision_tools(t) == ["maritime.query"]
    schema = model.wire_schema(t)
    variants = schema["properties"]["action"]["anyOf"]
    assert all(v["properties"]["kind"].get("const") != "final" for v in variants)


def test_closed_workflow_compaction_retains_all_ids_goal_and_risk_boundary(h):
    t = task(h, template_id="port-briefing")
    t["results"] = [
        {
            "id": f"T{i}",
            "ok": True,
            "tool": name,
            "summary": "建议状态=withheld；现场放行关闭。" + "原始数据" * 2000 + "尾部待人工签收",
            "artifact": f"T{i}.json",
            "sha256": "0" * 64,
        }
        for i, name in enumerate(maritime.REQUIRED, 1)
    ]
    messages, compacted = model.context(t, [])
    content = json.loads(messages[1]["content"])
    assert compacted and content["goal"] == t["goal"]
    assert [r["id"] for r in content["tool_results"]] == ["T1", "T2", "T3", "T4", "T5"]
    assert all("withheld" in r["summary"] for r in content["tool_results"])
    assert "尾部待人工签收" in content["tool_results"][-1]["summary"]
    assert sum(len(m["content"]) for m in messages) < 9000


def test_user_steering_disables_fixed_business_stage_compaction(h):
    t = task(h, template_id="port-briefing")
    t["inputs"] = [{"text": "请进一步核对设备约束", "request_id": "steer-001"}]
    text = "设备约束" * 300
    t["results"] = [
        {"id": "T1", "tool": "runtime.snapshot", "ok": True, "summary": text, "artifact": "T1.json", "sha256": "0" * 64}
    ]
    messages, _ = model.context(t, [])
    content = json.loads(messages[1]["content"])
    assert content["user_inputs"] == t["inputs"] and content["tool_results"][0]["summary"] == text


@pytest.mark.parametrize(
    "text,expected",
    [
        ("未发现显著差异", False),
        ("已经实现显著降低", False),
        ("获得最优方案", False),
        ("只是工程情景，未做统计检验，不证明现场收益", True),
    ],
)
def test_business_guard_rejects_unearned_statistical_and_optimality_claims(h, snapshot, text, expected):
    t, ref = captured(h, snapshot)
    comparison = tools.execute("twin.compare", {"source_ref": ref}, t, h.store)
    t, comparison_ref = attach(h, t, "twin.compare", comparison)
    check = verify(t, Action(kind="final", text=text, evidence_ids=[comparison_ref]), h.store)
    assert check["business_claims"] is expected


@pytest.mark.parametrize(
    "text,expected", [("所有信息均符合要求", False), ("历史快照过期，当前建议暂缓，不能作为现场作业依据", True)]
)
def test_withheld_data_requires_a_clear_qualification(h, snapshot, text, expected):
    snapshot["metadata"]["observed_at"] = "2000-01-01T00:00:00Z"
    t, ref = captured(h, snapshot)
    report = tools.execute("maritime.risk", {"source_ref": ref}, t, h.store)
    t, risk_ref = attach(h, t, "maritime.risk", report)
    check = verify(t, Action(kind="final", text=text, evidence_ids=[risk_ref]), h.store)
    assert check["business_claims"] is expected


def test_custom_snapshot_task_also_checks_freshness_at_final_delivery(h, snapshot):
    t, ref = captured(h, snapshot)
    observed = datetime.fromisoformat(snapshot["metadata"]["observed_at"].replace("Z", "+00:00"))
    action = Action(kind="final", text="当前数据可用于工程分析。", evidence_ids=[ref])
    fresh = verify(t, action, h.store, at=observed + timedelta(seconds=1))
    assert fresh["passed"] and fresh["delivery_readiness"]["analysis_usable"]
    stale = verify(t, action, h.store, at=observed + timedelta(seconds=121))
    assert not stale["passed"] and not stale["delivery_readiness"]["analysis_usable"]
    action.text = "已采集的模拟快照过期，建议暂缓，需重新取数。"
    qualified = verify(t, action, h.store, at=observed + timedelta(seconds=121))
    assert qualified["passed"] and not qualified["delivery_readiness"]["operational_release"]


@pytest.mark.parametrize("text,expected", [
    ("能源指标、船舶状态及设备均正常。", False),
    ("快照已读取，没有风险。", False),
    ("未发现显著差异。", False),
    ("快照仍有未关闭告警，不能声称各项均正常。", True),
    ("当前仅为工程模拟，未做统计检验，待人工核查告警。", True),
])
def test_custom_snapshot_cannot_turn_active_alerts_into_blanket_clearance(h, snapshot, text, expected):
    snapshot["alerts"] = [{"event_id": "heldout-alert", "status": "open", "title": "设备待检查"}]
    t, ref = captured(h, snapshot)
    observed = datetime.fromisoformat(snapshot["metadata"]["observed_at"].replace("Z", "+00:00"))
    result = verify(t, Action(kind="final", text=text, evidence_ids=[ref]), h.store, at=observed + timedelta(seconds=1))
    assert result["business_claims"] is expected


def test_business_repair_uses_actual_tool_failure_feedback_before_publishing(h, monkeypatch):
    original = tools.execute

    def execute(name, *args, **kwargs):
        result = original(name, *args, **kwargs)
        if name == "runtime.snapshot":
            result["snapshot"]["metadata"]["observed_at"] = "2000-01-01T00:00:00Z"
        return result

    monkeypatch.setattr(tools, "execute", execute)

    class Driver:
        def __init__(self):
            self.actions = [
                Action(kind="tool", tool="runtime.snapshot"),
                Action(kind="tool", tool="maritime.risk", arguments={"source_ref": "T1"}),
                Action(kind="final", text="所有信息均符合要求", evidence_ids=["T2"]),
                Action(kind="final", text="工程模拟数据过期，当前建议暂缓，需更新数据后复核", evidence_ids=["T2"]),
            ]

        def next(self, task, messages):
            return self.actions.pop(0), {"tokens": 10}

    h.model_driver = Driver()
    t = h.create(
        CreateTask(
            goal="核查当前港区快照",
            request_id="business-repair-001",
            driver="model",
            allowed_tools=["runtime.snapshot", "maritime.risk"],
            required_tools=["runtime.snapshot", "maritime.risk"],
        ),
        IdentityContext("alice", "operator", True, "test"),
    )
    t = settle(h, t["id"])
    assert t["status"] == "completed" and t["business_repairs"] == 1
    assert t["final"]["verification"]["business_claims"]
    assert any(e["event"] == "completion.business_repair" for e in h.store.events(t["id"]))


def test_final_delivery_rechecks_data_after_model_wait(h, snapshot):
    t, ref = captured(h, snapshot)
    report = tools.execute("maritime.risk", {"source_ref": ref}, t, h.store)
    assert report["readiness"]["analysis_usable"]
    t, risk_ref = attach(h, t, "maritime.risk", report)
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    bad = verify(t, Action(kind="final", text="所有信息均符合要求", evidence_ids=[risk_ref]), h.store, at=future)
    assert not bad["business_claims"] and not bad["delivery_readiness"]["analysis_usable"]
    good = verify(
        t, Action(kind="final", text="快照过期，当前业务建议暂缓", evidence_ids=[risk_ref]), h.store, at=future
    )
    assert good["passed"]


def test_business_report_is_published_from_artifact_without_a_model_summary(h):
    class ToolDriver:
        calls = 0

        def next(self, task, messages):
            self.calls += 1
            assert not set(maritime.REQUIRED).issubset(completed_tools(task)), "不得请求模型自由总结"
            return h.rules_driver.next(task, messages)

    driver = ToolDriver()
    h.model_driver = driver
    t = h.create(
        CreateTask(
            goal="港航联合研判",
            request_id="compiled-report-001",
            driver="model",
            template_id="port-briefing",
            budget=Budget(max_steps=6),
        ),
        IdentityContext("alice", "operator", True, "test"),
    )
    t = settle(h, t["id"])
    assert t["status"] == "completed" and t["usage"]["steps"] == 6 and driver.calls == 6
    assert t["final"]["synthesis"]["mode"] == "verified_business_report"
    assert t["final"]["synthesis"]["model_authored"] is False
    assert "港航交接简报" in t["final"]["text"] and t["final"]["verification"]["business_claims"]


def test_prompt_schema_preserves_named_fields_literal_values_and_validation():
    literal = {"title": "draft"}
    schema = {"title": "Command", "$defs": {"title": {"type": "object"}},
              "properties": {"title": {"title": "Title", "type": "string"},
                             "mode": {"enum": [literal], "default": literal}},
              "required": ["title"], "additionalProperties": False}
    projected = model.prompt_schema(schema)
    assert projected == {**{k: v for k, v in schema.items() if k != "title"},
                         "properties": {"title": {"type": "string"}, "mode": schema["properties"]["mode"]}}
    assert schema["properties"]["title"]["title"] == "Title"


def test_late_user_instruction_disables_automatic_report_publication(h, monkeypatch):
    original = tools.execute

    def execute(name, arguments, task, store, **kwargs):
        result = original(name, arguments, task, store, **kwargs)
        if name == "maritime.handover":
            h.input(
                task["id"],
                InputRequest(text="只展示已知事实，说明工程模拟边界", request_id="steer-report-001"),
                "operator",
                actor_id="alice",
            )
        return result

    monkeypatch.setattr(tools, "execute", execute)

    class ToolDriver:
        def next(self, task, messages):
            if set(maritime.REQUIRED).issubset(completed_tools(task)):
                packet = json.loads(messages[-1]["content"])
                assert packet["user_inputs"] == task["inputs"]
                assert any(r["id"] == "T5" and r["ok"] for r in packet["tool_results"])
                assert packet["source_facts"]["T1"] == task["results"][0]["source_facts"]
                assert sum(len(message["content"]) for message in messages) <= task["budget"]["context_chars"]
                return Action(
                    kind="final", text="仅展示工程模拟事实，生产权限关闭，交接草稿需人工核验", evidence_ids=["T5"]
                ), {"tokens": 10}
            return h.rules_driver.next(task, messages)

    h.model_driver = ToolDriver()
    t = h.create(
        CreateTask(goal="港航联合研判", request_id="compiled-steer-001", driver="model", template_id="port-briefing"),
        IdentityContext("alice", "operator", True, "test"),
    )
    t = settle(h, t["id"])
    assert t["status"] == "completed" and t["inputs"]
    assert t["final"]["synthesis"]["mode"] == "model" and "仅展示工程模拟事实" in t["final"]["text"]
