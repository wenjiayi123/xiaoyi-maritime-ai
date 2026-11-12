import json
import pytest
from app import cooperative_review as review


def test_daily_capacity_labels_are_bound_to_native_receipts():
    groups=review.checked(review.DIRECTORY/"index.json",review.INDEX_SHA256,1_000_000)["groups"]
    counts={}
    for group,data in groups.items():
        anchor,demand=group.split("-")
        for row in data["days"]:
            result=review.inspect_day(review.DeviceReview(day=row["day"],baseline=anchor,demand=demand))
            c=result["dr_capacity_review"]
            assert c["historical_only"] and result["production_authority"] is False
            assert result["dr_infeasibility_proven"]==(c["upper_kwh"]+1e-6<c["required_kwh"])
            assert abs(c["required_kwh"]-.98*result["dr_contract_kwh"])<1e-6
            counts[c["status"]]=counts.get(c["status"],0)+1
    assert counts["incompatible_with_service"]==6 and counts["shortfall_undetermined"]==22
    assert counts["delivered"]>0 and counts["no_event"]>0 and sum(counts.values())==96


def test_tampered_capacity_certificate_rejected(monkeypatch,tmp_path):
    src=review.DIRECTORY
    index=json.loads((src/"index.json").read_bytes())
    date=index["groups"]["fixed-normal"]["days"][0]["day"]
    for name in ["index.json","fixed-normal-"+date+".json"]:(tmp_path/name).write_bytes((src/name).read_bytes())
    (tmp_path/("capacity-"+review.CAPACITY_SHA256+".json")).write_bytes(b"{}")
    monkeypatch.setattr(review,"DIRECTORY",tmp_path)
    with pytest.raises(ValueError,match="版本"):
        review.inspect_day(review.DeviceReview(day=date,baseline="fixed",demand="normal"))
