import json
from types import SimpleNamespace
import pytest
from app.cooperative_review import DeviceReview,inspect_day
from app.vessel_review import VesselQuery,review_plan
from app.harness.contracts import Action,digest,encoded
from app.harness.explicit_policy import vessel_method
from app.harness.tools import validate
from app.harness.verification import verify


def receipt(tool,result,claim,mutate=False):
    raw=encoded(result);checksum=digest(raw)
    r={"id":"T1","tool":tool,"ok":True,"artifact":"T1.json","sha256":checksum,"summary":"forged value 998877.66"}
    task={"id":"test-policy","goal":"复核工程模拟回执","inputs":[],"results":[r],"required_tools":[]}
    store=SimpleNamespace(artifact=lambda *_:{"content":raw+" " if mutate else raw,"sha256":checksum})
    return verify(task,Action(kind="final",text=claim,evidence_ids=["T1"]),store)


def test_policy_numbers_require_integrity_and_exclude_forged_summary():
    v=review_plan(VesselQuery(day="2025-11-04",method="repair"))
    tool="policy.vessel_schedule";claim="2025-11-04 工程模拟，基线 13 船时、受训 12 船时。"
    assert receipt(tool,v,claim)["passed"]
    assert not receipt(tool,v,claim,True)["artifact_integrity"]
    assert not receipt(tool,v,claim+"花费 998877.66 元。")["numeric_support"]
    d=inspect_day(DeviceReview(day="2024-03-20",baseline="fixed",demand="normal"))
    assert receipt("policy.multidevice",d,"2024-03-20 工程模拟最低交付 4312.00 kWh，事后上界 4296.575 kWh。")["passed"]
    bound=d["dr_capacity_review"]["upper_kwh"]
    assert receipt("policy.multidevice",d,f"事后物理上界为 {bound:.2f} kWh。")["passed"]
    assert not receipt("policy.multidevice",d,"上界 4296.579 kWh。")["numeric_support"]


def test_explicit_method_binding_and_steering_preserve_comparisons():
    task={"goal":"查受训换位策略（repair），按回执交付","allowed_tools":["policy.vessel_schedule"],"actor_role":"viewer"}
    assert vessel_method(task)=="repair"
    with pytest.raises(ValueError,match="方法"):validate("policy.vessel_schedule",{"day":"2025-11-04","method":"repair_greedy"},task)
    assert validate("policy.vessel_schedule",{"day":"2025-11-04"},task).method=="repair"
    assert vessel_method({**task,"inputs":[{"text":"使用方法 milp"}]})=="milp"
    assert vessel_method({**task,"goal":"比较方法 repair 和 milp"}) is None
    assert vessel_method({**task,"goal":"不要用方法 repair"}) is None
