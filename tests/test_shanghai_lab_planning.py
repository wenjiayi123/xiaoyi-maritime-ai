import copy
import pytest
from integrations.shanghai_lab_v1.data import digest, make_case, verified_dataset
from integrations.shanghai_lab_v1.planning import compare_and_select, objective, strong_reference
from integrations.shanghai_lab_v1.protocol import validate_plan
from test_shanghai_lab_protocol import node_plan


@pytest.fixture(scope="module")
def dataset():
    return verified_dataset()


@pytest.mark.parametrize("scenario", ["normal", "arrival_surge", "berth_outage", "grid_derating", "weather_closure"])
def test_strong_reference_no_worse_on_same_information(scenario, dataset):
    c = make_case(scenario=scenario, dataset=dataset)
    native = node_plan(c)
    result = compare_and_select(c, native)
    assert validate_plan(c, result)["feasible"]
    assert objective(c, result) <= objective(c, native) + 1e-6
    original = validate_plan(c, native)
    selected = validate_plan(c, result)
    assert selected["wait_vessel_hours"] <= original["wait_vessel_hours"]
    assert selected["late_vessel_hours"] <= original["late_vessel_hours"]
    assert result["comparison"]["strong_reference"]["solver"]["gap"] >= 0


def test_committed_jobs_are_frozen(dataset):
    c = make_case(dataset=dataset)
    p = strong_reference(c)
    row = p["scheduled"][0]
    freeze = {row["job_id"]: {"start_hour": row["start_hour"], "berth": row["berth"]}}
    q = strong_reference(c, frozen=freeze)
    assert next(r for r in q["scheduled"] if r["job_id"] == row["job_id"]) == row
    impossible = {row["job_id"]: {"start_hour": 24, "berth": row["berth"]}}
    with pytest.raises(ValueError, match="frozen"):
        strong_reference(c, frozen=impossible)


def test_solver_cannot_hide_unserviceable_work(dataset):
    c = make_case(dataset=dataset)
    c["resources"]["channel_open"] = [False] * 24
    c["snapshot_sha256"] = digest({k: v for k, v in c.items() if k != "snapshot_sha256"})
    with pytest.raises(ValueError, match="feasible"):
        strong_reference(c)
