"""Business regression tests for declared offers and the two deployed chat paths."""
import copy
import json
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.harness.contracts import CreateTask, digest
from app.harness.runner import Harness
from app.harness.store import Conflict, HarnessStore
from app.access_control import IdentityContext
from app.main import app
from app.offer_comparison import OfferSheet, compare
from app.offer_language import from_question


def catalog():
    return {"profile":"berth","required":"12","requirement_ref":"DR-1","offers":[
        {"id":"A","price":"830","quote_ref":"P1","limit":"11.5","check_ref":"B1","assessment":"pass"},
        {"id":"B","price":"910","quote_ref":"P2","limit":"12","check_ref":"B2"},
        {"id":"C","price":"940","quote_ref":"P3","limit":"13","check_ref":"B3"}]}


def decide(data):
    return compare(OfferSheet.model_validate(data))


def test_numbers_take_precedence_over_a_verbal_pass_and_round_trip():
    result = decide(catalog())
    assert result["winners"] == ["B"] and result["minimum"] == "910"
    assert result["rows"][0]["eligibility"] == "ineligible"
    assert result["result_sha256"] == digest({k:v for k,v in result.items() if k!="result_sha256"})
    assert result == decide(result["input"])
    assert result["production_authority"] is False


@pytest.mark.parametrize(("price","expect"),[("0","needs_evidence"),("910","needs_evidence"),("910.000001","selected"),(None,"needs_evidence")])
def test_pending_constraint_can_block_the_minimum_or_tie(price,expect):
    data=catalog()
    data["offers"][0].update(price=price,check_ref=None)
    result=decide(data)
    assert result["status"]==expect
    assert result["known_leaders"]==["B"]
    assert result["winners"]==(["B"] if expect=="selected" else [])


def test_rejection_with_missing_price_does_not_block_others():
    data=catalog(); data["offers"][0].update(price=None,quote_ref=None)
    assert decide(data)["winners"]==["B"]


def test_expired_negative_cannot_rule_out_an_offer():
    data=catalog();data["as_of"]="2026-11-06T00:00:00+08:00"
    data["offers"][0]["valid_until"]="2026-11-05T16:00:00Z"
    r=decide(data)
    assert r["status"]=="needs_evidence" and r["blocking_ids"]==["A"]
    del data["as_of"]
    with pytest.raises(ValidationError):OfferSheet.model_validate(data)


def test_tie_zero_and_order_independence():
    data=catalog()
    for row in data["offers"][1:]:row["price"]="0.000000"
    for order in [data["offers"],list(reversed(data["offers"]))]:
        r=decide({**data,"offers":order})
        assert r["winners"]==["B","C"] and r["minimum"]=="0" and r["status"]=="tie"


def test_missing_requirement_source_and_all_rejected():
    data=catalog();data["requirement_ref"]=None
    assert decide(data)["status"]=="needs_evidence"
    for row in data["offers"]:row["assessment"]="fail"
    assert decide(data)["status"]=="no_feasible"


@pytest.mark.parametrize("bad",["-1","NaN","Infinity",True,"1000000000001","0.00000001"])
def test_invalid_prices(bad):
    d=catalog();d["offers"][0]["price"]=bad
    with pytest.raises(ValidationError): OfferSheet.model_validate(d)


def test_duplicate_id_and_currency_rejected():
    d=catalog();d["offers"][0]["id"]="b"
    with pytest.raises(ValidationError):OfferSheet.model_validate(d)
    d=catalog();d["offers"][1]["currency"]="USD"
    with pytest.raises(ValidationError):OfferSheet.model_validate(d)


BERTH="候选 D2：A 成本 830 元但违反吃水约束；B 成本 910 元可行；C 成本 940 元可行。问可采用候选中的最低成本，单位 CNY。"
POWER="计划 Q1：0.31、0.28、0.41 元/kWh 分别为候选甲乙丙报价。核验 Q2：乙未满足供电容量；甲和丙均满足。问最低可行报价，单位 CNY/kWh。"


@pytest.mark.parametrize(("q","who","price"),[(BERTH,"B","910"),(POWER,"甲","0.31"),
    (BERTH.replace("违反吃水约束","满足吃水约束").replace("830","913.56").replace("910","955"),"A","913.56"),
    (POWER.replace("乙未满足供电容量；甲和丙均满足","甲未满足供电容量；乙和丙均满足"),"乙","0.28")])
def test_declared_language_families(q,who,price):
    matched,sheet=from_question(q)
    assert matched and sheet
    assert compare(sheet)["winners"]==[who] and compare(sheet)["minimum"]==price


@pytest.mark.parametrize("q",[BERTH.replace("830 元","830 美元"),BERTH.replace("B 成本","另有闭港通知；B 成本"),
                           POWER.replace("甲和丙均满足","甲和乙均满足"),POWER.replace("甲乙丙","甲乙"),
                           BERTH.replace("单位 CNY","单位 CNY/kWh"),POWER.replace("问最低可行报价","仅考虑乙；问最低可行报价")])
def test_unbound_prose_requires_clarification(q):
    assert from_question(q)==(True,None)


def test_general_knowledge_question_uses_original_route():
    assert from_question("什么是船舶吃水？")== (False,None)


@pytest.mark.parametrize("stream",[False,True])
def test_chat_and_stream_use_the_same_verified_result(stream):
    client=TestClient(app,base_url="http://127.0.0.1")
    response=client.post("/api/chat"+("/stream" if stream else ""),json={"question":POWER,"session_id":"offers-test"})
    assert response.status_code==200
    if stream:
        events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        final=events[-1]
        assert events[0]["generation_provider"]=="local_rules"
        if "response" in final:final=final["response"]
    else:
        final=response.json()
    assert final["offer_comparison"]["winners"]==["甲"]
    assert final["generation_model"]=="offer-comparison-v1"
    assert final["decision_readiness"]["status"]=="sandbox_only"


def test_locked_harness_uses_real_artifact_and_rejects_changed_retry(tmp_path):
    harness=Harness(HarnessStore(tmp_path/"offer.sqlite"))
    identity=IdentityContext("comparison-user","analyst",True,"test")
    payload=CreateTask(goal="比较候选方案",request_id="offers-retry-01",driver="rules",offer_context=catalog())
    try:
        first=harness.create(payload,identity)
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            stored=harness.store.get(first["id"])
            if stored["status"] not in {"running","queued"}:break
            time.sleep(.05)
        assert stored["status"]=="completed",stored
        assert stored["allowed_tools"]==["offers.compare"]
        record=stored["results"][0]
        receipt=json.loads(harness.store.artifact(first["id"],record["artifact"])["content"])
        assert receipt==decide(catalog())
        assert harness.create(payload,identity)["id"]==first["id"]
        altered=catalog();altered["offers"][1]["price"]="700"
        with pytest.raises(Conflict):
            harness.create(CreateTask(goal=payload.goal,request_id=payload.request_id,driver="rules",offer_context=altered),identity)
    finally:
        harness.close()


def test_locked_offer_task_rejects_mixed_tools():
    with pytest.raises(ValidationError):
        CreateTask(goal="比较报价",request_id="offers-mixed-01",offer_context=catalog(),allowed_tools=["offers.compare","linked.action"])
