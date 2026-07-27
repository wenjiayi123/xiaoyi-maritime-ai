from app.answer_verification import verify_response
from app.daily_query import daily_query_categories, expand_daily_queries
from app.xiaoyi import XiaoyiAI


def test_peak_shaving_short_query_expands_to_port_operations_context() -> None:
    expanded = expand_daily_queries("如何削峰")
    assert daily_query_categories("如何削峰") == ["energy_peak"]
    assert any("岸桥" in query and "储能" in query for query in expanded)


def test_peak_shaving_returns_actionable_grounded_answer() -> None:
    result = XiaoyiAI().ask("如何削峰", mode="ops", top_k=8)
    verification = verify_response(result)
    assert result.grounded is True
    assert result.refusal_reason is None
    assert result.evidence[0].source == "119_port_energy_peak_management_daily_qa.md"
    assert "建议执行顺序" in result.answer
    assert "不可中断" in result.answer
    assert "没有实时负荷曲线" in result.answer
    assert verification.status == "passed"


def test_colloquial_daily_questions_route_to_matching_playbooks() -> None:
    expected = {
        "今天用电峰值太高怎么办？": "119_port_energy_peak_management_daily_qa.md",
        "堆场快满了怎么办？": "121_yard_gate_equipment_flow_daily_qa.md",
        "闸口排队太长怎么处理？": "121_yard_gate_equipment_flow_daily_qa.md",
        "TOS卡顿怎么办？": "122_shift_customer_system_coordination_daily_qa.md",
    }
    engine = XiaoyiAI()
    for question, source in expected.items():
        result = engine.ask(question, mode="ops", top_k=8)
        assert result.grounded is True
        assert result.evidence[0].source == source
        assert verify_response(result).status == "passed"


def test_vague_action_question_requests_business_object() -> None:
    result = XiaoyiAI().ask("怎么办？", mode="ops")
    assert result.grounded is False
    assert result.refusal_reason == "business_object_required"
    assert "业务对象" in result.answer


def test_peak_shaving_followups_are_domain_specific() -> None:
    result = XiaoyiAI().ask("今天用电峰值太高怎么办？", mode="ops")
    assert any("EMS" in item and "TOS" in item for item in result.next_questions)
    assert any("削峰" in item for item in result.next_questions)
