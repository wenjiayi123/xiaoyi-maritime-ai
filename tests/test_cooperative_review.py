"""The signed device release distinguishes passed and withheld days and rejects replacement bytes."""
import json

import pytest
from pydantic import ValidationError
from app import cooperative_review as review


def test_all_published_day_and_treatment_decisions():
    directory=review.DIRECTORY
    index=review.checked(directory/"index.json",review.INDEX_SHA256,1_000_000)
    seen=set();reads=0
    for group,scope in index["groups"].items():
        anchor,demand=group.split("-")
        for record in scope["days"]:
            for method in scope["summary"]:
                answer=review.inspect_day(review.DeviceReview(day=record["day"],baseline=anchor,demand=demand,method=method))
                assert answer["receipt_sha256"]==record["sha256"] and len(answer["checks"])==15
                assert answer["production_authority"] is False
                assert answer["decision"]==("withhold_candidate" if answer["failed"] else "eligible_for_offline_review")
                seen.add(answer["decision"]);reads+=1
    assert reads==480 and seen=={"eligible_for_offline_review","withhold_candidate"}


def test_unknown_day_and_path_are_not_resolved():
    with pytest.raises(ValueError,match="没有冻结"):
        review.inspect_day(review.DeviceReview(day="1900-01-01",baseline="fixed",demand="normal"))
    with pytest.raises(ValidationError):
        review.DeviceReview(day="../index.json",baseline="fixed",demand="normal")


def test_daily_receipt_tampering_is_refused(tmp_path,monkeypatch):
    origin=review.DIRECTORY;data=(origin/"index.json").read_bytes()
    (tmp_path/"index.json").write_bytes(data)
    name=json.loads(data)["groups"]["fixed-normal"]["days"][0]["day"]
    (tmp_path/("fixed-normal-"+name+".json")).write_bytes(b"{}")
    monkeypatch.setattr(review,"DIRECTORY",tmp_path)
    with pytest.raises(ValueError,match="版本"):review.inspect_day(review.DeviceReview(day=name,baseline="fixed",demand="normal"))


def test_tool_is_read_only_role_scoped_and_typed():
    from app.harness import tools
    item=tools.REGISTRY["policy.multidevice"]
    assert item[0] is review.DeviceReview and item[2] is False
    args={"day":"2024-01-01","baseline":"fixed","demand":"normal"}
    with pytest.raises(PermissionError):
        tools.validate("policy.multidevice",args,{"allowed_tools":[],"actor_role":"viewer"})
    arg=tools.validate("policy.multidevice",args,{"allowed_tools":["policy.multidevice"],"actor_role":"viewer"})
    assert arg.day.isoformat()=="2024-01-01"
    receipt=tools.execute("policy.multidevice",args,{"allowed_tools":["policy.multidevice"],"actor_role":"viewer"},None)
    assert receipt==review.inspect_day(arg)
