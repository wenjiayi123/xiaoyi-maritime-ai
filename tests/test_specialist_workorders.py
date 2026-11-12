"""Port work-order contracts, independent verification and recoverable evidence handoffs."""

import json
from types import SimpleNamespace

import pytest

from app.harness import tools, workorders_api
from app.harness.contracts import CreateTask
from app.policy_release import PolicySelection
from app.specialist_orders import (
    EvidenceError,
    adjudicate,
    drive,
    evidence_view,
    journal,
    register,
    summarize,
)
from app.specialist_planner import check_plan


def step(role, tool, *parents):
    return dict(role=role, tool=tool, needs=list(parents), assignment="复核原始资料")


def test_plan_sorts_and_keeps_independent_vetoes():
    plan = [
        step("management", "review", "energy"),
        step("carbon", "policy.energy", "energy"),
        step("energy", "policy.energy"),
    ]
    result = check_plan({"steps": plan}, {s["role"]: [s["tool"]] for s in plan})
    assert [s["role"] for s in result] == ["energy", "carbon", "management"]
    assert set(result[-1]["needs"]) == {"energy", "carbon"}


def test_plan_rejects_cycles_and_unauthorized_tools():
    c = {"energy": ["policy.energy"], "carbon": ["policy.energy"]}
    with pytest.raises(ValueError, match="循环"):
        check_plan(
            {
                "steps": [
                    step("energy", "policy.energy", "carbon"),
                    step("carbon", "policy.energy", "energy"),
                ]
            },
            c,
        )
    with pytest.raises(ValueError, match="授权"):
        check_plan({"steps": [step("energy", "policy.safety")]}, c)


def test_user_order_key_isolation_and_replay(tmp_path):
    path = journal(tmp_path, "alice", "case-one")
    assert path != journal(tmp_path, "bob", "case-one")
    order = register(path, "alice", "case-one", "查询岸桥点检资料", None, False)
    from app.harness.local_lock import ProcessLease

    lease = ProcessLease(path.with_suffix(".create.lock")).acquire()
    try:
        assert (
            register(path, "alice", "case-one", "查询岸桥点检资料", None, False)
            == order
        )
    finally:
        lease.release()
    with pytest.raises(ValueError, match="不同输入"):
        register(path, "alice", "case-one", "别的目标", None, False)
    for invalid in ("../x", "cataLog", "COM1"):
        with pytest.raises(ValueError):
            journal(tmp_path, "alice", invalid)


def test_policy_selection_is_bound_before_execution():
    sel = PolicySelection(scenario="stress", window=0).model_dump()
    task = dict(
        allowed_tools=["policy.operations"], actor_role="operator", policy_context=sel
    )
    assert tools.validate("policy.operations", {}, task).model_dump() == sel
    with pytest.raises(ValueError, match="锁定"):
        tools.validate("policy.operations", {"scenario": "evaluate"}, task)
    assert (
        CreateTask(
            goal="查看回执", request_id="policy-locked", policy_context=sel
        ).policy_context.window
        == 0
    )


def test_locator_alone_cannot_complete_a_knowledge_order():
    raw = {
        "grounded": True,
        "answer": "没有实际条款",
        "evidence": [{"citation_role": "locator_only", "chunk_checksum_sha256": "123"}],
    }
    with pytest.raises(EvidenceError):
        evidence_view("knowledge.search", raw, None, "maintenance")


def test_maintenance_requires_the_equipment_component_and_subject_in_one_excerpt():
    raw = {
        "grounded": True,
        "answer": "AGV在岸桥交接区运输。",
        "evidence": [
            {
                "id": "a",
                "citation_role": "supporting",
                "title": "AGV职责",
                "snippet": "AGV 在岸桥交接区运输。",
                "chunk_checksum_sha256": "abc",
            }
        ],
    }
    with pytest.raises(EvidenceError):
        evidence_view(
            "knowledge.search", raw, None, "maintenance", "核实岸桥吊具锁销报警点检依据"
        )
    raw["evidence"].append(
        {
            "id": "b",
            "citation_role": "supporting",
            "title": "岸桥吊具日检",
            "snippet": "锁销报警列入点检要求。",
            "chunk_checksum_sha256": "def",
        }
    )
    assert evidence_view(
        "knowledge.search", raw, None, "maintenance", "核实岸桥吊具锁销报警点检依据"
    )["sources"] == [{"id": "b", "sha256": "def"}]


@pytest.mark.parametrize("window", [None, 0])
def test_arbiter_verifies_values_dataset_and_veto(window):
    sel = PolicySelection(scenario="stress", window=window).model_dump()
    values = {"fixed": 48, "joint-17-8192": 110}
    facts = {
        "metric": "delay_minutes",
        "dataset_sha256": "dataset",
        "means": values,
        "window": {"values": values},
    }
    g = {
        "decision": "veto",
        "dataset_sha256": "dataset",
        "policy_metrics": {"delay_minutes": 110},
        "baseline_metrics": {"delay_minutes": 48},
    }
    rows = {
        "analytics": dict(role="analytics", tool="knowledge.figures", facts=facts),
        "dispatch": dict(role="dispatch", tool="policy.operations", facts=g),
    }
    decision = adjudicate(rows, sel)
    assert (
        decision["decision"] == "retain_baseline"
        and decision["comparisons"][0]["agrees"]
    )
    assert not decision["production_authority"]
    g["dataset_sha256"] = "different"
    assert adjudicate(rows, sel)["decision"] == "needs_review"
    g["dataset_sha256"] = "dataset"
    g["baseline_metrics"]["delay_minutes"] = 47
    assert adjudicate(rows, sel)["decision"] == "needs_review"


def test_waiting_worker_does_not_starve_peer(monkeypatch, tmp_path):
    from app import specialist_orders

    roles = [step("carbon", "policy.energy"), step("energy", "policy.energy")]
    order = {"plan": roles, "workers": {}, "selection": None}

    def advance(order, step, gw, checkpoint):
        role = step["role"]
        if role == "carbon":
            order["workers"][role] = {
                "attempts": [{"task": "ht-1"}],
                "question": "补充时段",
            }
            return "waiting_input"
        order["workers"][role] = {"output": {"facts": {}}}
        return "completed"

    monkeypatch.setattr(specialist_orders, "advance_worker", advance)
    drive(order, tmp_path / "one.json", None, None, lambda message: None)
    assert order["status"] == "waiting_input" and order["waiting_task"] == "ht-1"
    assert order["workers"]["energy"]["output"]


def test_manager_rejects_fabricated_numbers():
    output = dict(
        role="safety",
        tool="policy.safety",
        task_id="ht-source",
        result="T1",
        sha256="signed",
        facts={"checks": {"peak": False}},
    )
    decision = adjudicate({"safety": output}, None)
    answer = {
        "summary": "已节约 876543 元",
        "limitation": "仅仿真",
        "references": ["safety"],
        "decision": decision["decision"],
    }
    model = SimpleNamespace(complete=lambda *args: (answer, {}))
    with pytest.raises(EvidenceError):
        summarize(model, "复核", {"safety": output}, decision)
    answer["summary"] = "峰值检查未通过。"
    assert (
        summarize(model, "复核", {"safety": output}, decision)["interpretation"]
        == answer
    )


def test_figure_summary_preserves_selected_period_and_units():
    from app.visual_evidence import figure_summary, search_figures

    result = search_figures("24h复盘与压力测试 delay 延误", 0)
    summary = json.loads(figure_summary(result))
    assert summary and all(
        h["metric"] == "delay_minutes" and h["scope"] == "selected window"
        for h in summary
    )
    assert all(
        all(h["display"][k] == format(v, ".2f") for k, v in h["values"].items())
        for h in summary
    )


def test_inline_procedure_item_numbers_do_not_mask_real_measurements():
    from app.harness.verification import numbers

    assert numbers("步骤：1. 确认编号；2. 记录 23.5 分钟；3. 报告 6 次。") == {
        "23.5",
        "6",
    }
    assert numbers("数值：45.元。另需记录：1.5 分钟。") == {"45", "1.5"}


def test_twin_snapshot_does_not_establish_independent_forecast_accuracy():
    with pytest.raises(EvidenceError, match="留出"):
        evidence_view(
            "systems.inspect", {"simulated": True}, None, "twin", "查水位校准误差"
        )
    from app.harness.public_port import forecast_validation

    original = forecast_validation()
    facts = evidence_view(
        "twin.validate_public", original, None, "twin", "对照公开水位校准留出误差"
    )
    assert facts["holdout"]["n"] and facts["site_id"] == "NOAA.9410660"
    from app.harness.runner import Harness

    summary = json.loads(Harness._summary("twin.validate_public", original))
    assert summary["exact"]["mae"] == facts["holdout"]["mae"]
    assert summary["display"]["baseline_mae"] == format(
        facts["holdout"]["baseline_mae"], ".4f"
    )
    with pytest.raises(EvidenceError, match="不覆盖"):
        evidence_view(
            "twin.validate_public", original, None, "twin", "请给出上海港水位校准误差"
        )


def test_explicit_title_request_requires_registered_heading():
    from app.specialist_orders import verified_output

    heading = "岸桥故障导致船舶作业中断，该如何处理"
    raw = {
        "grounded": True,
        "answer": "核对岸桥编号",
        "evidence": [
            dict(
                id="ch-1",
                title=heading,
                snippet="核对岸桥编号",
                chunk_checksum_sha256="source",
            )
        ],
    }
    record = dict(
        ok=True, id="T1", tool="knowledge.search", artifact="T1.json", sha256="artifact"
    )
    task = dict(
        id="task",
        status="completed",
        driver="model",
        results=[record],
        final=dict(
            text="《岸桥故障处理流程》核对编号",
            verification={"passed": True},
            evidence_ids=["T1"],
        ),
    )
    step = dict(
        role="maintenance",
        tool="knowledge.search",
        assignment="报岸桥故障处置的章节名称",
    )
    gw = SimpleNamespace(original=lambda *args: raw)
    with pytest.raises(EvidenceError, match="逐字"):
        verified_output(gw, task, step, None)
    task["final"]["text"] = "《" + heading + "》核对岸桥编号"
    assert verified_output(gw, task, step, None)["facts"]["sources"][0]["id"] == "ch-1"


def test_api_retry_requires_rejected_evidence(monkeypatch, tmp_path):
    from fastapi import HTTPException

    identity = SimpleNamespace(actor_id="alice")
    monkeypatch.setattr(workorders_api, "root", lambda: tmp_path)
    monkeypatch.setattr(workorders_api, "principal", lambda request: identity)
    monkeypatch.setattr(
        workorders_api, "workers", lambda: SimpleNamespace(submit=lambda *args: None)
    )
    payload = workorders_api.OrderRequest(goal="复核岸桥", request_id="test-order")
    assert workorders_api.create_order(payload, None)["status"] == "planning"
    with pytest.raises(HTTPException) as caught:
        workorders_api.retry_order(
            payload.request_id, workorders_api.Revision(reason="再收集资料"), None
        )
    assert caught.value.status_code == 409
    identity.actor_id = "bob"
    with pytest.raises(HTTPException) as caught:
        workorders_api.get_order(payload.request_id, None)
    assert caught.value.status_code == 404
