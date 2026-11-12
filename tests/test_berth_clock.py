from app.exercise_records import verify
from app.models import ChatRequest


QUESTION="最早靠泊是当天第几分钟？能否满足时限？"
FACTS="前船 08:00 离泊，必须再留 20 分钟。后船到港是当天第 490 分钟，承诺靠泊时限为第 500 分钟。"


def record(facts):
    old={"source":"berth-qa","kind":"general","scope":"exercise","facts":facts}
    req=ChatRequest(question=QUESTION,exercise_record=old)
    assert req.exercise_record.kind=="berth_clock"
    assert old["kind"]=="general"
    return verify(req.exercise_record,QUESTION)


def test_legacy_general_record_binds_departure_clearance_and_inclusive_limit():
    out=record(FACTS)
    assert (out["value"],out["decision"],out["production_authority"])==(500,"ALLOW",False)
    assert {p["role"] for p in out["references"]}=={"departure","clearance","arrival","deadline"}
    assert all(FACTS[p["start"]:p["end"]]==p["text"] for p in out["references"])
    strict=record(FACTS.replace("承诺靠泊时限为","承诺靠泊时间必须早于"))
    assert strict["value"]==500 and strict["decision"]=="HOLD" and strict["proof"]["operator"]=="<"


def test_unknown_conditions_do_not_produce_a_berth_time():
    for bad in (FACTS+"引航时间未知。", FACTS+"前船 08:01 离泊。",
                FACTS.replace("08:00","23:56"), FACTS.replace("20 分钟","-20 分钟"),
                FACTS.replace("第 490","第 1490")):
        out=record(bad)
        assert out["decision"]=="UNKNOWN" and out["value"] is None and out["reason"]
