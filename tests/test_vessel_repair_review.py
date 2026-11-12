from pathlib import Path
import json
import pytest
from app import vessel_review as reader


def test_repair_read_all_frozen_schedules_and_retained_actions():
    folder=reader.DIRECTORY.parent/"shanghai-vessel-repair"
    index=json.loads((folder/"index.json").read_bytes())
    passed=at_bound=count=0
    for key in index["receipts"]:
        scene,date=key.split("/")
        for method in index["summary"]:
            row=reader.review_plan(reader.VesselQuery(day=date,scenario=scene,method=method))
            assert row["receipt_sha256"]==index["receipts"][key] and not row["production_authority"]
            assert len(row["schedule"])==len(row["jobs"])
            if method=="repair":
                passed+=row["eligible_improvement"];at_bound+=row["native_at_solver_bound"]
                assert row["method_weight_sha256"]==index["weight_sha256"]
                assert row["metrics"]["objective_cny"]<=row["baseline"]["objective_cny"]+1e-6
                assert row["retained_step"]<=len(row["repair_steps"])<=5
            count+=1
    assert (count,passed,at_bound)==(540,52,34)


def test_wrong_study_method_is_refused():
    old=json.loads((reader.DIRECTORY/"index.json").read_bytes())["dates"][0]
    new=json.loads((reader.DIRECTORY.parent/"shanghai-vessel-repair/index.json").read_bytes())["dates"][0]
    with pytest.raises(ValueError,match="没有评测此方法"):reader.review_plan(reader.VesselQuery(day=old,method="repair"))
    with pytest.raises(ValueError,match="没有评测此方法"):reader.review_plan(reader.VesselQuery(day=new,method="immediate_cost"))


def test_registered_tool_returns_repair_and_bound():
    from app.harness import tools
    q={"day":"2025-11-04","scenario":"normal","method":"repair"}
    data=tools.execute("policy.vessel_schedule",q,{"actor_role":"viewer","allowed_tools":["policy.vessel_schedule"]},None)
    assert data["eligible_improvement"] and data["repair_steps"] and not data["native_at_solver_bound"]
