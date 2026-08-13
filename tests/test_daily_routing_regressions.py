from app.answer_verification import verify_response
from app.xiaoyi import XiaoyiAI


def test_short_daily_questions_rank_the_matching_operational_section() -> None:
    engine = XiaoyiAI()
    cases = (
        ("闸口排队太长怎么处理", "121_yard_gate_equipment_flow_daily_qa.md", ("预约波峰", "场内拥堵")),
        ("滚装船车辆怎么排", "125_port_commercial_intermodal_special_cargo_daily_qa.md", ("预排区", "系固")),
        ("海铁联运怎么组织", "125_port_commercial_intermodal_special_cargo_daily_qa.md", ("班列", "业务主键")),
        ("火车没按时到怎么办", "125_port_commercial_intermodal_special_cargo_daily_qa.md", ("替代运力", "冷链")),
        ("储能算减碳吗", "123_port_carbon_reduction_daily_qa.md", ("不必然减碳", "循环损耗")),
        ("接口消息晚到了怎么办", "126_port_management_kpi_system_daily_qa.md", ("幂等", "积压")),
    )
    for question, expected_source, required_terms in cases:
        result = engine.ask(question, mode="ops", top_k=8)
        assert result.grounded is True
        assert expected_source in {item.source for item in result.evidence}
        assert all(term in result.answer for term in required_terms)
        assert verify_response(result).status == "passed"
