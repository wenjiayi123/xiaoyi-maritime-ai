import pytest

from app.exercise_records import ExerciseRecord,verify


@pytest.mark.parametrize(("kind","text","decision","value"),[
 ("flow","同一箱流串联经过岸桥（30 箱/小时）、两台各 11 箱/小时的场桥。计划速率 22 箱/小时。","ALLOW",22),
 ("flow","串行依次经过一号站（1 TEU/分钟）和两台各 25 TEU/小时的设备。最低目标 58 TEU/小时。","HOLD",50),
 ("flow","同一箱流串联经过岸桥（35 箱/小时）、两台各 13 TEU/小时的场桥。计划速率 26 箱/小时。","UNKNOWN",None),
 ("flow","同一箱流串联经过岸桥（35 箱/小时）、两台各 13 箱/小时的场桥。其中一台检修。计划速率 26 箱/小时。","UNKNOWN",None),
 ("unit_cost","班次成本 2.469 万元，服务量 200 箱。先四舍五入到两位，再与 123.45 元/箱上限比较。","ALLOW",123.45),
 ("unit_cost","成本 10.005 元，服务量 1 TEU。先四舍五入至两位，再与 10.00 元/TEU 上限比较。","HOLD",10.01),
 ("unit_cost","成本 1 元，服务量 0 TEU。先四舍五入到两位，再与 8 元/TEU 上限比较。","UNKNOWN",None),
 ("unit_cost","成本 30 元，完成量 3 箱。先四舍五入到两位，再与 10 元/TEU 上限比较。","UNKNOWN",None),
 ("power","负荷 999999999999999999999999 kW，并网限额 1 kW。","UNKNOWN",None),
])
def test_field_units_real_capacity_and_explicit_rounding(kind,text,decision,value):
    r=verify(ExerciseRecord(source="safety-check",scope="exercise",kind=kind,facts=text))
    assert r["decision"]==decision and r["value"]==value and r["production_authority"] is False
    assert all(text[p["start"]:p["end"]]==p["text"] for p in r.get("references",[]))
