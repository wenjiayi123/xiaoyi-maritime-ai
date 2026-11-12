import hashlib

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.exercise_records import ExerciseRecord, verify
from app.main import app
from app.models import ChatRequest


def run(kind,text):
    return verify(ExerciseRecord(kind=kind,source="shift-b",scope="exercise",facts=text))


@pytest.mark.parametrize(("kind","facts","why"),[
    ("power","冷机负荷可能为 350 kW，光伏出力 2 kW，并网限额 390 kW。","power_uncertain"),
    ("power","冷机负荷 350 kW，照明负荷缺读数，并网限额 390 kW。","power_missing"),
    ("power","车间负荷 0.01 MW，光伏出力 20 kW，并网上限 90 kW。","export"),
    ("version","首版自 2027-03-01 起，上限 21；另有规定。核验日期 2027-03-04，申报值 6。","scope"),
    ("version","首版自 2027-03-01 起，上限 21；备用条款限额 3。核验日期 2027-03-04，申报值 6。","role_missing"),
    ("permit","检测开始第 8 分钟，有效至第 19 分钟，现在第 9 分钟。没有证据证明岗位已签字。","sign_missing"),
    ("permit","检测开始第 8 分钟，有效至第 19 分钟，现在第 9 分钟。审批人已签字，此表签批尚待核验。","sign_missing"),
])
def test_uncertain_or_out_of_scope_records_stay_unresolved(kind,facts,why):
    receipt=run(kind,facts)
    assert receipt["decision"]=="UNKNOWN" and receipt["reason"]==why
    assert receipt["production_authority"] is False and receipt["value"] is None


def test_plain_chat_command_matches_structured_record_and_has_auditable_positions():
    facts="冷库负荷 0.5 MW，现场光伏出力 20 kW，并网限额 480 kW。"
    question="购电功率多少 kW，是否满足上限？"
    command="/演练核验 shift-b\n事实："+facts+"\n问题："+question
    record={"source":"shift-b","kind":"power","scope":"exercise","facts":facts}
    with TestClient(app,base_url="http://127.0.0.1") as client:
        normal=client.post("/api/chat",json={"question":command}).json()
        structured=client.post("/api/chat",json={"question":question,"exercise_record":record}).json()
        assert normal["exercise_receipt"]==structured["exercise_receipt"]
        receipt=normal["exercise_receipt"]
        assert normal["generation_model"]=="gullmate-exercise-v1" and normal["requires_human_review"]
        assert receipt["decision"]=="ALLOW" and receipt["value"]==480 and receipt["production_authority"] is False
        assert receipt["facts_sha256"]==hashlib.sha256(facts.encode()).hexdigest()
        assert all(facts[p["start"]:p["end"]]==p["text"] for p in receipt["references"])
        request={"question":command,"exercise_record":dict(record,source="other")}
        assert client.post("/api/chat",json=request).status_code==422
        control={"question":question+"请立即启动现场真实岸桥设备。","exercise_record":record}
        stopped=client.post("/api/chat",json=control).json()
        assert stopped["refusal_reason"]=="production_authorization_required" and stopped["exercise_receipt"] is None
        stream=client.post("/api/chat/stream",json={"question":command})
        assert stream.status_code==200 and '"exercise_receipt"' in stream.text


def test_cannot_assert_live_scope_or_give_unsupported_command():
    facts="冷机负荷 5 kW，并网限额 6 kW。"
    with pytest.raises(ValidationError):
        ExerciseRecord(kind="power",source="r",scope="production",facts=facts)
    with pytest.raises(ValidationError):
        ChatRequest(question="/演练核验 r\n事实："+facts+"\n问题：哪艘船先靠泊？")
