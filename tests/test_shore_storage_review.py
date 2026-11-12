import json
import pytest
from pydantic import ValidationError
from app import shore_evidence as store
from app.harness.contracts import encoded
from app.harness.runner import Harness
from app.harness import tools


def test_week_receipts_and_optional_hour():
    idx=store.checked(store.DIRECTORY/"index.json",store.INDEX_SHA,200_000)
    assert len(idx["weeks"])==55
    for i,(week,digest) in enumerate(idx["weeks"].items()):
        q=store.ShoreQuery(week=week,hour=(i*7)%168);v=store.review_shore(q)
        assert not v["production_authority"] and v["receipt_sha256"]==digest and v["hourly"]["hour"]==q.hour
        a=v["audited"];assert abs(v["candidate"]["carbon_kg"]-v["baseline"]["carbon_kg"]-a["battery_carbon_kg"]-a["flex_carbon_kg"])<1e-6
    answer=tools.execute("policy.shore_storage",{"week":"2026-01-01"},{"actor_role":"viewer","allowed_tools":["policy.shore_storage"]},None)
    assert "电池的碳排变化_kg" in json.loads(Harness._summary("policy.shore_storage",answer))
    with pytest.raises(PermissionError):tools.validate("policy.shore_storage",{"week":"2026-01-01"},{"actor_role":"viewer","allowed_tools":[]})


def test_call_identity_and_energy_coverage():
    idx=store.checked(store.DIRECTORY/"index.json",store.INDEX_SHA,200_000)
    calls=[store.review_shore(store.ShoreQuery(call_id=k)) for k in idx["calls"]]
    assert len(calls)==285 and sum(r["terminal_readings"] for r in calls)==282
    assert abs(sum(r["in_call_kwh"] for r in calls)-10350515.675)<1e-5
    assert all(not v["production_authority"] for v in calls)


def test_invalid_scope_and_tampering(tmp_path,monkeypatch):
    for fields in ({},{"week":"2026-01-01","call_id":"SC_00001"},{"call_id":"SC_00001","hour":1},
                   {"call_id":"../SC_00001"},{"week":"2026-01-01","hour":168}):
        with pytest.raises(ValidationError):store.ShoreQuery(**fields)
    with pytest.raises(ValueError,match="不是登记"):store.review_shore(store.ShoreQuery(week="2020-01-01"))
    (tmp_path/"index.json").write_bytes((store.DIRECTORY/"index.json").read_bytes())
    (tmp_path/"calls").mkdir();(tmp_path/"calls/SC_00001.json").write_bytes(b"{}")
    monkeypatch.setattr(store,"DIRECTORY",tmp_path)
    with pytest.raises(ValueError,match="版本"):store.review_shore(store.ShoreQuery(call_id="SC_00001"))
