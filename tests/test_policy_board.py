from copy import deepcopy
from pathlib import Path
import json

import pytest
from pydantic import ValidationError

from app import policy_board, policy_release
from app.harness import tools
from app.harness.contracts import CreateTask


def request(**changes):
    return policy_board.PolicyBoard.model_validate({
        "scenario":"evaluate","window":0,"candidates":["fixed","mpc2"],"limits":{"delay_minutes":100},
        "objective":"cost",**changes})


@pytest.fixture
def native(monkeypatch):
    raw=(Path(__file__).resolve().parents[2]/"carbon/frontend/public/gullmate-policy-release.json").read_bytes()
    assert policy_release.hashlib.sha256(raw).hexdigest()==policy_release.EXPECTED_SHA256
    data=json.loads(raw)
    monkeypatch.setattr(policy_board,"load_verified_release",lambda:(data,policy_release.EXPECTED_SHA256))
    return data


def test_missing_candidate_or_window_mismatch_rejects_incomplete_comparison(native):
    with pytest.raises(ValueError,match="候选"):
        policy_board.select(request(candidates=["fixed","unregistered"]))
    native["scenarios"]["evaluate"]["policies"]["mpc2"]["windows"][0]["start"]+=1
    with pytest.raises(ValueError,match="对齐"):
        policy_board.select(request())


def test_tie_and_display_precision_do_not_bypass_safety(native):
    window=native["scenarios"]["evaluate"]["policies"]["fixed"]["windows"][0]
    twin=deepcopy(window)
    native["scenarios"]["evaluate"]["policies"]["mpc2"]["windows"][0]=twin
    for item in (window,twin):
        item["metrics"].update(cost=10,delay_minutes=2,safety_violations=0)
    result=policy_board.select(request(precision="one_decimal",candidates=["mpc2","fixed"]))
    assert result["ties"]==["mpc2","fixed"] and result["selected"]=="mpc2" and not result["production_authority"]
    twin["metrics"]["safety_violations"]=1
    assert policy_board.select(request())["selected"]=="fixed"
    for invalid in (-1,.01):
        twin["metrics"]["safety_violations"]=invalid
        with pytest.raises(ValueError,match="非负整数"):policy_board.select(request(precision="one_decimal"))


def test_duplicate_candidates_or_model_supplied_new_constraints_are_rejected():
    with pytest.raises(ValidationError):request(candidates=["fixed","fixed"])
    base={"request_id":"board-check-123","goal":"核验策略","planning_mode":"adaptive"}
    with pytest.raises(ValidationError):CreateTask(**base,allowed_tools=["policy.select"])
    with pytest.raises(ValidationError):CreateTask(**base,policy_board_context=request().model_dump(),allowed_tools=["calculate"])
    with pytest.raises(ValidationError):tools.validate("policy.select",{"limits":{"cost":300}},
        {"actor_role":"admin","allowed_tools":["policy.select"]})
    assert not any(t["name"]=="policy.select" for t in tools.catalog("admin"))
    spec=CreateTask(**base,policy_board_context=request().model_dump())
    assert spec.allowed_tools==spec.required_tools==["policy.select"]
