from dataclasses import replace
import io
import json

import pytest

from app import port_activity
from app.exercise_records import ExerciseRecord, summary
from app.model_gateway import ModelGateway
from app.settings import settings


FACTS = ("PortWatch 公开挂靠统计，Antwerp。自 2024-03-01 起连续 4 天。"
         "全部船舶挂靠艘次分别是 [47, 61, 59, 67]。集装箱船挂靠艘次分别是 [17, 10, 12, 16]。"
         "每艘次对应1张核对单，核对单上限为 72 张。")
QUESTION = "这些集装箱船共对应多少张核对单？是否在额度内？"


def record(facts):
    return ExerciseRecord(source="history", scope="exercise", kind="general", facts=facts)


def test_registered_port_history_validates_source_and_computes():
    receipt = port_activity.verify(record(FACTS), QUESTION, "orders", "unit-selector")
    assert (receipt["decision"], receipt["value"]) == ("ALLOW", 55)
    assert receipt["source_receipt"]["port_id"] == "port57" and len(receipt["source_receipt"]["rows"]) == 4
    assert receipt["proof"]["unreported_values_used"] is False and receipt["production_authority"] is False
    assert all(FACTS[r["start"]:r["end"]] == r["text"] for r in receipt["references"])


def test_hidden_daily_value_is_not_fetched_into_the_exercise():
    receipt = port_activity.verify(record(FACTS.replace("[17, 10, 12, 16]", "[17, null, 12, 16]")), QUESTION, "orders", "unit-selector")
    assert receipt["decision"] == "UNKNOWN" and receipt["value"] is None
    assert receipt["proof"]["interval"] == [45., 106.] and receipt["reason"] == "indeterminate_series"
    assert "暂缓" in summary(receipt)


@pytest.mark.parametrize("facts,reason", [
    (FACTS.replace("47, 61", "48, 61"), "source_mismatch"),
    (FACTS + "上述额度已被撤回。", "unverified_clause"),
    (FACTS + "只核算夜班船舶。", "unverified_clause"),
    (FACTS.replace("2024-03-01", "2034-03-01"), "source_gap"),
    (FACTS.replace("Antwerp", "Antwerp 和 Ningbo"), "port_identity"),
])
def test_unsupported_scope_and_conflicting_evidence_abstain(facts, reason):
    result = port_activity.verify(record(facts), QUESTION, "orders", "unit-selector")
    assert result["reason"] == reason and result["value"] is None and result["decision"] == "UNKNOWN"


def test_local_selector_sees_facts_and_never_supplies_the_arithmetic(monkeypatch):
    gateway = ModelGateway(replace(settings, model_provider="openai_compatible", model_name="local-test", model_base_url="http://127.0.0.1:11435/v1"))
    def completion(body, *, stream):
        assert not stream and body["chat_template_kwargs"]["enable_thinking"] is False
        assert QUESTION in body["messages"][-1]["content"] and FACTS in body["messages"][-1]["content"]
        return io.BytesIO(json.dumps({"model": "local-test", "choices": [{"finish_reason": "stop", "message": {"content": '{"operation":"orders"}'}}]}).encode())
    monkeypatch.setattr(gateway, "_send_completion", completion)
    result = gateway.reason_about_exercise(record(FACTS), QUESTION)
    assert result["model_role"] == "operation_selection" and result["value"] == 55
    assert "程序" not in result.get("model", "") and "核算项目" in summary(result)
