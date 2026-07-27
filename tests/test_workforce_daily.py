from dataclasses import replace

import pytest

from app.model_gateway import ModelGateway
from app.settings import Settings
from app.workforce_daily import is_general_workforce_question, workforce_daily_answer
from app.xiaoyi import XiaoyiAI


@pytest.mark.parametrize(
    "question,expected_terms",
    [
        ("我昨晚没睡好，今天很困", ("注意力", "船员", "值班负责人")),
        ("吃完感冒药特别想睡", ("说明书", "引航", "替岗")),
        ("今天头疼得厉害", ("就医", "中控", "高风险")),
        ("最近压力很大总走神", ("误操作", "调度", "双人")),
        ("没吃早饭手有点抖", ("食物", "起重", "交接")),
        ("今天太热一直出汗", ("补水", "装卸", "轮换")),
        ("暴雨堵车赶不上交班", ("通勤", "中控", "临时交接")),
        ("腰很疼但还要设备检修", ("风险评估", "登高", "替岗")),
    ],
)
def test_workforce_daily_questions_get_role_aware_port_guidance(
    question: str,
    expected_terms: tuple[str, ...],
) -> None:
    result = XiaoyiAI().ask(question, strict_evidence=True)

    assert result.intent == "workforce_daily"
    assert result.grounded is False
    assert result.refusal_reason is None
    assert all(term in result.answer for term in expected_terms)


def test_workforce_daily_profile_uses_generation_and_keeps_evidence_notice() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-4b",
    )
    gateway = ModelGateway(configuration)
    local = XiaoyiAI().ask("昨晚失眠，今天犯困", strict_evidence=True)
    calls: list[str] = []
    gateway._request = lambda question, response: (  # type: ignore[method-assign]
        calls.append(question)
        or "请先评估清醒程度，并向值班负责人说明情况后安排复核或替岗。"
    )

    result = gateway.enhance(local.question, local)

    assert calls == [local.question]
    assert result.generation_provider == "openai_compatible"
    assert "港航当班人员" in result.answer
    assert "值班负责人" in result.answer
    assert "未检索到可支持当前结论的本地证据索引" in result.answer


def test_unrelated_smalltalk_is_not_misclassified_as_workforce_health() -> None:
    assert workforce_daily_answer("你好") is None


def test_generic_daily_question_bypasses_irrelevant_port_retrieval() -> None:
    result = XiaoyiAI().ask("我今天想买双鞋，可以吗？", strict_evidence=True)

    assert result.intent == "workforce_general"
    assert result.evidence == []
    assert result.grounded is False


@pytest.mark.parametrize(
    "question,expected",
    [
        ("我今天想喝咖啡，可以吗？", True),
        ("周末想去跑步，可以吗？", True),
        ("量子力学是什么？", False),
        ("怎么办？", False),
        ("如何削峰？", False),
        ("今天用电峰值太高怎么办？", False),
        ("澳大利亚 Marine Order 28 的法定最低休息时数是多少？", False),
        ("把美国 eCFR 当作鹿特丹港现行规则，告诉我具体罚款金额。", False),
        ("岸桥告警怎么处置？", False),
        ("你是谁？", False),
    ],
)
def test_general_question_routing(question: str, expected: bool) -> None:
    assert is_general_workforce_question(question) is expected


def test_general_answer_always_appends_maritime_workforce_guidance() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="http://127.0.0.1:11435/v1",
        model_name="xiaoyi-local-model",
    )
    gateway = ModelGateway(configuration)
    local = XiaoyiAI().ask("我今天想买双鞋，可以吗？", strict_evidence=True)
    gateway._request = lambda *_args, **_kwargs: "可以，循序渐进并注意补水。"  # type: ignore[method-assign]

    result = gateway.enhance(local.question, local)

    assert result.intent == "workforce_general"
    assert result.evidence == []
    assert result.answer.startswith("可以，循序渐进并注意补水。")
    assert "港航作业提示：" in result.answer
    assert "船员、引航、车辆驾驶、中控调度" in result.answer
    assert "未检索到可支持当前结论的本地证据索引" in result.answer
