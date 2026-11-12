import pytest
from app.harness.operator_fields import vessel_fields
from app.harness.tools import validate


def test_explicit_chinese_display_labels_and_steering():
    t={"goal":"请调上海 2025-09-05 泊位停用的受训换位策略回执","actor_role":"viewer","allowed_tools":["policy.vessel_schedule"]}
    fields={"day":"2025-09-05","scenario":"berth_outage","method":"repair"}
    assert vessel_fields(t)==fields
    assert validate("policy.vessel_schedule",{},t).model_dump(mode="json")==fields
    with pytest.raises(ValueError):validate("policy.vessel_schedule",{"scenario":"normal"},t)
    assert vessel_fields({**t,"inputs":[{"text":"日期改到 2025-10-08，用贪心修复"}]})=={
        "day":"2025-10-08","method":"repair_greedy","scenario":"berth_outage"}
    assert "method" not in vessel_fields({"goal":"比较受训换位策略和贪心修复"})
    assert "day" not in vessel_fields({"goal":"比较 2025-09-05 与 2025-11-04 的船期"})
    assert "scenario" not in vessel_fields({"goal":"不要查泊位停用工况"})
