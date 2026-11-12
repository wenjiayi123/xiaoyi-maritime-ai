from app.shore_online_intent import live_claim_problem,online_request
from app.harness.tools import validate
import pytest


def test_only_actual_twin_readback_supports_online_agreement():
    t={"goal":"请让正在运行的 TwinLab 在线重放指定周","allowed_tools":["policy.shore_storage"],"actor_role":"operator"}
    assert online_request(t) is True
    assert validate("policy.shore_storage",{"week":"2026-01-01"},t).verify_twin
    with pytest.raises(ValueError):validate("policy.shore_storage",{"week":"2026-01-01","verify_twin":False},t)
    static={"schema":"gullmate.shore-week-review.v1"}
    assert live_claim_problem(t,"T1是工程数据",static)
    assert live_claim_problem({},"重放与冻结结果一致",static)
    assert not live_claim_problem({},"尚未取得在线复核",static)
    assert not live_claim_problem(t,"重放一致",{**static,"twin_readback":{"verified":True}})
    assert online_request({**t,"inputs":[{"text":"不用在线复核，只查冻结回执"}]}) is False
    assert online_request({"goal":"读取 2026-01-01 的岸电周回执"}) is None


def test_requested_call_or_entire_week_is_preserved():
    from app.shore_online_intent import shore_fields,read_policy_first
    c={"goal":"上海独立岸电电表中，工程船次 SC_00001 在哪个泊位，计入多少电量？","allowed_tools":["policy.shore_storage"],"actor_role":"viewer"}
    assert read_policy_first(c) and shore_fields(c)=={"call_id":"SC_00001","week":None,"hour":None,"verify_twin":False}
    assert validate("policy.shore_storage",{},c).call_id=="SC_00001"
    w={**c,"goal":"查上海岸电储能 2025-08-01 起始的168 小时回执，给出账单变化"}
    assert shore_fields(w)=={"week":"2025-08-01","call_id":None,"hour":None,"verify_twin":False}
    with pytest.raises(ValueError):validate("policy.shore_storage",{"week":"2025-08-01","hour":167},w)
    assert shore_fields({**w,"goal":w["goal"]+"以及第 11 小时的明细"})["hour"]==10
    assert "hour" not in shore_fields({**w,"goal":w["goal"]+"比较第 11 小时和第 13 小时"})
    assert not shore_fields({**w,"goal":"比较岸电船次 SC_00001 和 SC_00002"})


def test_departure_credit_and_failed_policy_summaries():
    from app.shore_online_intent import incorrect_departure_credit
    from app.harness.runner import Harness
    assert incorrect_departure_credit("离泊端点之后的一刻钟计入电量，依据是计量说明。")
    assert not incorrect_departure_credit("离泊端点之后的一刻钟不计入电量。")
    for tool in ("policy.shore_storage","policy.vessel_schedule","policy.multidevice"):
        assert "无法连接" in Harness._summary(tool,{"error":"无法连接"})
