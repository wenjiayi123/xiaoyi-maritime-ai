from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.operator_assistant import normalize_operator_question
from app.port_runtime import SandboxPortDataSource, create_port_data_source
from app.xiaoyi import XiaoyiAI


client = TestClient(app)


def test_sandbox_source_is_time_varying_and_repeatable_per_bucket() -> None:
    source = SandboxPortDataSource()
    first_at = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)
    next_at = first_at + timedelta(minutes=5)

    first = source.overview(first_at)
    repeated = source.overview(first_at + timedelta(minutes=2))
    changed = source.overview(next_at)

    assert first == repeated
    assert first != changed
    assert source.metadata(first_at)["live_data_verified"] is False
    assert source.metadata(first_at)["write_enabled"] is False


def test_runtime_endpoints_expose_provenance_and_operational_entities() -> None:
    status = client.get("/api/runtime/status")
    snapshot = client.get("/api/runtime/snapshot")

    assert status.status_code == 200
    assert status.json()["data_mode"] == "operations_sandbox"
    assert status.json()["source_adapter"] == "SandboxPortDataSource"
    assert "尚未连接任何港口生产源" in status.json()["data_notice"]
    assert snapshot.status_code == 200
    assert len(snapshot.json()["berth_calls"]) >= 4
    assert snapshot.json()["equipment"]["agv"]["total"] > 0
    assert snapshot.json()["gate"]["open_lanes"] > 0


def test_frontline_colloquial_question_is_normalized_and_clarified() -> None:
    assert "为什么还没有" in normalize_operator_question("这船咋还没靠")
    result = XiaoyiAI().ask("这船咋还没靠")

    assert result.intent == "operator_clarification"
    assert result.refusal_reason == "business_object_required"
    assert "船名、IMO 编号或计划泊位" in result.answer


def test_workbench_question_uses_traceable_sandbox_state() -> None:
    result = XiaoyiAI().ask("工作台里 QC-03 当前告警是什么？按先安全后恢复给处置步骤。", mode="sop")

    assert result.intent == "operator_runtime_assist"
    assert result.grounded is True
    assert result.source_quality == "sandbox_runtime"
    assert result.refusal_reason == "sandbox_not_production"
    assert "SYNTHETIC_VALIDATED" in result.answer
    assert "不是现场生产实绩" in result.answer
    assert result.evidence[0].source == "XIAOYI-PORT-SANDBOX"


def test_explicit_live_asset_query_does_not_fall_back_to_sandbox() -> None:
    result = XiaoyiAI().ask("当前 CNYTN-AGV-017 的实时电量是多少？")

    assert result.grounded is False
    assert result.refusal_reason == "live_data_connection_required"
    assert all(item.source != "XIAOYI-PORT-SANDBOX" for item in result.evidence)


def test_regulatory_shore_power_limit_does_not_fall_back_to_sandbox() -> None:
    result = XiaoyiAI().ask("中国岸电标准允许的具体谐波电流限值是多少？")

    assert result.grounded is False
    assert result.refusal_reason == "official_full_text_required"
    assert all(item.source != "XIAOYI-PORT-SANDBOX" for item in result.evidence)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("南闸口要不要增开？", "暂不立即增开"),
        ("3号桥吊怎么了？", "QC-03"),
        ("AGV-023现在还能继续派任务吗？", "停止派发新任务"),
        ("今天港口忙吗？", "当前港区处于"),
        ("今天有多少条船在港？", "在港船舶"),
        ("当前堆场情况怎么样？", "堆场占用率"),
        ("现在岸电利用率怎么样？", "岸电利用率"),
        ("帮我整理交班", "当前班次交班摘要"),
        ("本班先处理什么？", "本班建议优先级"),
    ],
)
def test_showcase_operator_questions_answer_directly_without_rag_refusal(
    question: str, expected: str
) -> None:
    result = XiaoyiAI().ask(question, mode="ops", strict_evidence=True)

    assert result.intent == "operator_runtime_assist"
    assert result.source_quality == "sandbox_runtime"
    assert result.grounded is True
    assert result.refusal_reason == "sandbox_not_production"
    assert expected in result.answer
    assert "不是现场生产实绩" in result.answer
    assert "未找到足够" not in result.answer


def test_frontline_scenarios_are_role_specific() -> None:
    response = client.get("/api/operator/scenarios")

    assert response.status_code == 200
    roles = {item["role"] for item in response.json()["items"]}
    assert {"调度员", "设备主管", "值班长", "一线操作员"} <= roles


def test_live_adapter_fails_closed_without_gateway(monkeypatch) -> None:
    monkeypatch.setenv("XIAOYI_PORT_DATA_MODE", "live")
    monkeypatch.delenv("XIAOYI_PORT_BASE_URL", raising=False)

    try:
        create_port_data_source()
    except RuntimeError as error:
        assert "XIAOYI_PORT_BASE_URL" in str(error)
    else:
        raise AssertionError("live 模式缺少生产网关时必须拒绝启动")
