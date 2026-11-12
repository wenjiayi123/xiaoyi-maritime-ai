from app.workforce_daily import is_general_workforce_question, workforce_daily_answer
from app.xiaoyi import XiaoyiAI


def test_technical_pressure_does_not_route_to_workforce():
    question = "压力试验中，负荷增大后延误多少分钟？"
    assert workforce_daily_answer(question) is None
    assert not is_general_workforce_question(question)
    assert workforce_daily_answer("压力测试时我感到焦虑总走神") is not None


def test_cost_result_uses_the_study_originally_requested():
    answer = XiaoyiAI().ask("常规负荷留出评测中固定调度的平均成本为多少？", top_k=3)
    assert answer.grounded and "639563.03" in answer.answer
    assert "适用SLA" not in answer.answer
    assert answer.evidence[0].source == "18_smart_port_ai_data.md"
