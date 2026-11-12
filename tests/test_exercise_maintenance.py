import pytest
from app.exercise_records import applicable, from_command, summary, verify

BEFORE = "距维保限值尚有多少小时？接下该班次是否合规？"
AFTER = "班后带符号余量是多少小时？能否承接本班？"


def check(facts, question=BEFORE):
    command=f"/演练推理 PM-1\n事实：{facts}\n问题：{question}"
    record=from_command(command)
    assert record.kind=="maintenance"
    result=verify(record,command)
    assert result["production_authority"] is False
    for ref in result.get("references",[]):
        assert facts[ref["start"]:ref["end"]]==ref["text"]
    return result


@pytest.mark.parametrize(("q","value"),[(BEFORE,8),(AFTER,1)])
def test_maintenance_requested_quantity(q,value):
    r=check("预防性维保到 1000 小时必须执行，当前 992 小时，下一班任务需连续运行 7 小时，不允许途中超限。",q)
    assert (r["value"],r["decision"])==(value,"ALLOW")
    assert r["proof"]["remaining"]==8 and r["proof"]["margin"]==1


def test_shift_too_long_and_mixed_units():
    r=check("当前 60840 分钟；保养限值为 1020 小时；本班需连续运行 11 小时。")
    assert (r["value"],r["decision"])==(6,"HOLD")
    assert "超出维保限值 5 小时" in summary(r)


@pytest.mark.parametrize(("clause","label"),[("，班末可恰好到限","ALLOW"),("，必须在到限前结束","HOLD"),("","UNKNOWN")])
def test_shift_ending_at_deadline(clause,label):
    assert check("维保限值 800 小时，当前 794 小时，本班需连续运行 6 小时"+clause)["decision"]==label


def test_unassigned_exception_and_mixed_questions():
    facts="维保限值 800 小时，当前 794 小时，本班需连续运行 3 小时"
    assert check(facts+"；另有2小时预热")["decision"]=="UNKNOWN"
    assert check(facts,"班前还可运行多少小时？还要扣除两小时，能否承接本班？")["decision"]=="UNKNOWN"


def test_existing_roles_when_maintenance_is_only_background():
    assert applicable("维护岗位已经签字。检测开始第 10 分钟，有效至第 30 分钟，当前第 15 分钟。","还有多少剩余有效分钟？")=="permit"
    assert applicable("设备维护统计为两个独立故障样本；本周仍有 4 个工单。","剩余工单有几个？") is None
    assert applicable("检修前的并网上限为 200 kW，负荷 80 kW。","可用并网功率还剩多少 kW？")=="power"
