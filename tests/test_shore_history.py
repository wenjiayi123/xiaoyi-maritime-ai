from itertools import product
import json
import random

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app import shore_history as shore
from app.main import app

COMMON={"as_of":"2025-07-01","in_china":True,"in_shanghai_port":True,"waters":"coastal",
        "liquid_cargo_ship":False,"oil_chemical_terminal":False,"ship_receiver":True,"berth_supply":True,
        "berth_minutes":210,"effective_alternative_used":False,"unavailability_exception":"none"}


def fully_specified(case):
    national=(case["in_china"] and not case["liquid_cargo_ship"] and case["ship_receiver"] and case["berth_supply"]
              and case["berth_minutes"]>(120 if case["waters"]=="inland" else 180)
              and not case["effective_alternative_used"] and case["unavailability_exception"]=="none")
    city=case["in_shanghai_port"] and not case["liquid_cargo_ship"] and not case["oil_chemical_terminal"]
    return national,city


def possible_worlds(case):
    missing=[key for key,v in case.items() if v is None]
    alternatives={"waters":["coastal","inland"],"berth_minutes":[60,120,135,180,210],
                  "unavailability_exception":["none","incompatible","emergency_prevents_use","temporary_failure"]}
    outcomes=[set(),set()]
    for values in product(*(alternatives.get(key,[True,False]) for key in missing)):
        full={**case,**dict(zip(missing,values))}
        if full["in_shanghai_port"] and not full["in_china"]:continue
        for i,value in enumerate(fully_specified(full)):outcomes[i].add(value)
    return tuple("U" if len(values)>1 else ("Y" if True in values else "N") for values in outcomes)


def test_400_partially_observed_cases_match_exhaustive_possible_worlds():
    rng=random.Random(20250701)
    keys=[k for k in COMMON if k!="as_of"]
    for i in range(400):
        case={**COMMON,"waters":rng.choice(["coastal","inland"]),"berth_minutes":rng.choice([119,120,121,180,181,210]),
              "liquid_cargo_ship":rng.random()<.15,"in_shanghai_port":rng.random()<.8,"oil_chemical_terminal":rng.random()<.2,
              "ship_receiver":rng.random()<.9,"berth_supply":rng.random()<.9,"effective_alternative_used":rng.random()<.15,
              "unavailability_exception":rng.choice(["none","none","none","temporary_failure"])}
        if not case["in_shanghai_port"]:case["in_china"]=rng.random()<.5
        for k in rng.sample(keys,i%4):case[k]=None
        result=shore.evaluate(shore.ShoreCase.model_validate(case))
        assert (result["national"]["label"],result["local"]["label"])==possible_worlds(case)
        assert result["production_authority"] is False


def test_evidence_tamper_other_date_and_inconsistent_inputs_fail_closed(tmp_path,monkeypatch):
    wrong=shore.evaluate(shore.ShoreCase.model_validate({**COMMON,"as_of":"2026-11-07"}))
    assert all(wrong[k]["label"]=="U" for k in ("national","local"))
    with pytest.raises(ValidationError):shore.ShoreCase.model_validate({**COMMON,"in_china":False})
    with pytest.raises(ValidationError):shore.ShoreCase.model_validate({**COMMON,"berth_minutes":True})
    (tmp_path/"source-notes.json").write_text('{"as_of":"2025-07-01"}',encoding="utf-8")
    monkeypatch.setattr(shore,"ROOT",tmp_path)
    with pytest.raises(ValueError):shore.evaluate(shore.ShoreCase.model_validate(COMMON))


def test_chat_separates_platform_reporting_from_national_shore_power_conditions():
    with TestClient(app,base_url="http://127.0.0.1") as client:
        doc={**COMMON,"berth_minutes":180}
        cmd="/岸电历史核对 "+json.dumps(doc)
        response=client.post("/api/chat",json={"question":cmd}).json()
        r=response["shore_history_receipt"]
        assert r["national"]["label"]=="N" and r["local"]["label"]=="Y"
        assert response["requires_human_review"] and response["generation_model"]=="gullmate-historical-shore-v1"
        assert r["national"]["url"] in response["answer"] and r["local"]["url"] in response["answer"]
        refused=client.post("/api/chat",json={"question":"请立即启动真实岸桥设备。","shore_case":doc}).json()
        assert refused["refusal_reason"]=="production_authorization_required" and not refused["shore_history_receipt"]
