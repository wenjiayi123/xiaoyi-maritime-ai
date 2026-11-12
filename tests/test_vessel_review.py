import pytest
from pydantic import ValidationError
from app import vessel_review as reader


def test_every_registered_vessel_and_all_five_schedules():
    ix=reader.checked(reader.DIRECTORY/"index.json",reader.INDEX_SHA,100_000)
    counts=0
    for key in ix["receipts"]:
        scene,day=key.split("/")
        for method in ix["summary"]:
            row=reader.review_plan(reader.VesselQuery(day=day,scenario=scene,method=method))
            assert {j["id"] for j in row["jobs"]}=={r["job_id"] for r in row["schedule"]}
            assert not row["production_authority"] and row["metrics"]["processed_teu"]==sum(j["teu"] for j in row["jobs"])
            counts+=1
    assert counts==300


def test_unknown_or_tampered_plan_rejected(tmp_path,monkeypatch):
    ix=reader.checked(reader.DIRECTORY/"index.json",reader.INDEX_SHA,100_000)
    with pytest.raises(ValueError,match="没有留出"):reader.review_plan(reader.VesselQuery(day="1999-01-01"))
    with pytest.raises(ValidationError):reader.VesselQuery(day="2025-09-11",scenario="../normal")
    q=reader.VesselQuery(day=ix["dates"][0])
    (tmp_path/"index.json").write_bytes((reader.DIRECTORY/"index.json").read_bytes())
    (tmp_path/"normal").mkdir()
    (tmp_path/"normal"/(str(q.day)+".json")).write_bytes(b"{}")
    monkeypatch.setattr(reader,"DIRECTORY",tmp_path)
    with pytest.raises(ValueError,match="版本"):reader.review_plan(q)


def test_named_vessel_tool_is_read_only_and_checks_permissions():
    from app.harness import tools
    q={"day":"2025-09-11","scenario":"berth_outage","method":"trained"}
    task={"actor_role":"viewer","allowed_tools":["policy.vessel_schedule"]}
    assert not tools.REGISTRY["policy.vessel_schedule"][2]
    assert tools.execute("policy.vessel_schedule",q,task,None)==reader.review_plan(reader.VesselQuery(**q))
    with pytest.raises(PermissionError):tools.validate("policy.vessel_schedule",q,{**task,"allowed_tools":[]})
