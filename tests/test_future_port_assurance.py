"""Business invariants and adversarial acceptance for public historical port studies."""

import copy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.harness import policy_assurance as pa, portcall, public_port, twin_validation as tv
from app.main import app

AT = datetime(2024, 12, 25, tzinfo=timezone.utc)


def request(**updates):
    data = {
        "site_id": "test-port",
        "as_of": AT,
        "calls": [{"call_id": "A"}, {"call_id": "B"}],
        "events": [
            {
                "event_id": x + ".eta",
                "call_id": x,
                "classifier": "ESTIMATED",
                "revision": 1,
                "event_time": AT,
                "received_at": AT,
                "source_party": "carrier",
                "source_reference": "test",
            }
            for x in ["A", "B"]
        ],
    }
    data.update(updates)
    return portcall.PlanRequest(**data)


def test_arrival_uncertainty_and_independent_capacity_checker():
    req = request(capacities={**portcall.CAPACITIES, "berth": 1})
    result = portcall.plan(req)
    schedule = result["selected"]["schedule"]
    assert min(r["start_minutes"] for r in schedule) >= 15
    a, b = sorted(schedule, key=lambda r: r["start_minutes"])
    assert a["end_minutes"] <= b["start_minutes"]
    forged = copy.deepcopy(schedule)
    forged[1]["start_minutes"] = forged[0]["start_minutes"]
    assert not portcall.verify_schedule(req, forged, {"A": 15, "B": 15})["feasible"]
    assert result["operational_release"] is False


@pytest.mark.parametrize("resource", ["berth", "channel", "crane", "power_kw"])
def test_no_complete_schedule_means_withhold(resource):
    req = request(
        closures=[
            {"resource": resource, "start_minutes": 0, "end_minutes": 720, "unavailable": portcall.CAPACITIES[resource]}
        ]
    )
    result = portcall.plan(req)
    assert result["selected"] is None and result["recommendation_status"] == "withheld"
    assert all(not c["validation"]["feasible"] for c in result["candidates"])


def test_revision_received_after_decision_cannot_change_historical_plan():
    base = request()
    first = portcall.plan(base)
    data = base.model_dump()
    new = copy.deepcopy(data["events"][0])
    new.update(revision=2, event_time=AT + timedelta(hours=5), received_at=AT + timedelta(minutes=1))
    data["events"].append(new)
    second = portcall.plan(portcall.PlanRequest(**data))
    assert second["selected"] == first["selected"]
    assert second["future_updates_excluded"] == 1


def test_conflicting_sources_are_exposed_without_silently_picking_latest():
    data = request().model_dump()
    other = copy.deepcopy(data["events"][0])
    other.update(event_id="another-source", source_party="terminal", event_time=AT + timedelta(minutes=30))
    data["events"].append(other)
    assert portcall.plan(portcall.PlanRequest(**data))["recommendation_status"] == "withheld"


@pytest.mark.parametrize("classifier,delay", [("ACTUAL", 1), ("ESTIMATED", -121), ("REQUESTED", 0)])
def test_future_actual_stale_or_only_requested_arrivals_cannot_be_released(classifier, delay):
    data = request().model_dump()
    for e in data["events"]:
        e["classifier"] = classifier
        if classifier == "ACTUAL":
            e["event_time"] += timedelta(minutes=delay)
        else:
            e["received_at"] += timedelta(minutes=delay)
    assert portcall.plan(portcall.PlanRequest(**data))["selected"] is None


def test_infeasible_frozen_commitment_is_never_silently_moved():
    data = request().model_dump()
    data["calls"][0]["frozen_start_minutes"] = 0
    assert portcall.plan(portcall.PlanRequest(**data))["selected"] is None


@pytest.mark.parametrize("mutation", ["timezone", "duplicate", "changed_identity", "negative_capacity"])
def test_portcall_contract_rejects_unreliable_inputs(mutation):
    data = request().model_dump()
    if mutation == "timezone":
        data["as_of"] = AT.replace(tzinfo=None)
    if mutation == "duplicate":
        data["events"].append(copy.deepcopy(data["events"][0]))
    if mutation == "changed_identity":
        new = copy.deepcopy(data["events"][0])
        new.update(revision=2, classifier="ACTUAL")
        data["events"].append(new)
    if mutation == "negative_capacity":
        data["capacities"]["power_kw"] = -1
    with pytest.raises(ValidationError):
        portcall.PlanRequest(**data)


def validation_request():
    rows = []
    for i in range(80):
        rows.append(
            {
                "issued_at": AT + timedelta(minutes=i * 6),
                "target_at": AT + timedelta(minutes=(i + 1) * 6),
                "predicted": 1.0,
                "actual": 1.01,
                "baseline": 0.8,
                "lower": 0.95,
                "upper": 1.05,
                "source_row": str(i),
            }
        )
    return {
        "site_id": "test",
        "variable": "water_level",
        "unit": "m MLLW",
        "model_version": "test.v1",
        "source_sha256": "a" * 64,
        "frozen_at": rows[39]["target_at"],
        "maximum_mae": 0.1,
        "maximum_interval_width": 0.2,
        "calibration": rows[:40],
        "holdout": rows[40:],
    }


def test_good_accuracy_never_grants_physical_twin_or_site_authority():
    result = tv.validate(tv.ValidationRequest(**validation_request()))
    assert result["validation_passed"] and not result["operational_release"]
    assert result["evidence_origin"].startswith("caller_supplied")


@pytest.mark.parametrize("mutation", ["leak", "same_time", "duplicate", "nonfinite", "timezone", "future"])
def test_forecast_contract_rejects_lookahead_leakage_and_invalid_actuals(mutation):
    data = validation_request()
    if mutation == "leak":
        data["calibration"][0]["target_at"] = AT + timedelta(days=2)
    if mutation == "same_time":
        data["holdout"][0]["issued_at"] = data["holdout"][0]["target_at"]
    if mutation == "duplicate":
        data["holdout"].append(copy.deepcopy(data["calibration"][0]))
    if mutation == "nonfinite":
        data["holdout"][0]["actual"] = float("nan")
    if mutation == "timezone":
        data["holdout"][0]["issued_at"] = AT.replace(tzinfo=None)
    if mutation == "future":
        data["holdout"][-1]["target_at"] = datetime.now(timezone.utc) + timedelta(days=1)
    with pytest.raises(ValidationError):
        tv.ValidationRequest(**data)


def test_wide_intervals_bad_holdout_and_tiny_sample_are_visible_blockers():
    data = validation_request()
    for r in data["holdout"]:
        r.update(actual=2.0, lower=-100.0, upper=100.0)
    data["holdout"] = data["holdout"][:2]
    result = tv.validate(tv.ValidationRequest(**data))
    assert not result["validation_passed"]
    assert {"holdout_sample_count", "mae_within_tolerance", "interval_width", "residual_drift"} <= set(
        result["blockers"]
    )


def policy_rows(deltas, *, violation=False):
    rows, stress = [], []
    for i, delta in enumerate(deltas):
        for name, score, validation in [("sop_rule", 10, 5), ("pid", 100, 4), ("q_learning", 10 + delta, 8)]:
            episodes = [{"constraint_violations": int(violation and name == "q_learning" and j == 0)} for j in range(3)]
            rows.append(
                {
                    "algorithm": name,
                    "seed": i,
                    "validation_metrics": {"score": validation},
                    "test_metrics": {"score": score, "constraint_violations": 0},
                    "test_episodes": episodes,
                }
            )
            for scenario in ["demand_surge", "equipment_outage", "severe_weather"]:
                stress.append(
                    {
                        "algorithm": name,
                        "seed": i,
                        "scenario": scenario,
                        "metrics": {"score": score},
                        "episodes": episodes,
                    }
                )
    return rows, stress


def decision(deltas, **kwargs):
    rows, stress = policy_rows(deltas, **kwargs)
    result = pa.assess(rows, ["q_learning"], stress)
    return result, next(d for d in result["decisions"] if d["algorithm"] == "q_learning")


def test_validation_comparator_is_not_selected_from_test_scores():
    report, d = decision([1, 1, 1, 1, 1])
    assert report["comparator_algorithm"] == "sop_rule"
    assert d["statistics"]["paired_mean_delta"] == 1
    assert d["research_admission"] and d["enterprise_admission"] is False
    assert d["zero_failure_seed_rate_upper95"] > 0.4  # five successes do not prove rare-event safety


@pytest.mark.parametrize("deltas", [[5], [5, 5, 5, 5], [-1, 10, 10, 10, 10], [1, 1, 1, 1, -3]])
def test_small_sample_worst_seed_or_uncertain_improvement_is_blocked(deltas):
    _, d = decision(deltas)
    assert d["research_admission"] is False


def test_single_observed_violation_cannot_be_hidden_by_aggregate_rounding():
    _, d = decision([10] * 5, violation=True)
    assert not d["research_admission"] and not d["checks"]["no_observed_violations"]


def test_missing_stress_results_and_regressions_block_admission():
    rows, stress = policy_rows([5] * 5)
    stress = [r for r in stress if not (r["algorithm"] == "q_learning" and r["seed"] == 0)]
    result = pa.assess(rows, ["q_learning"], stress)
    d = next(d for d in result["decisions"] if d["algorithm"] == "q_learning")
    assert not d["checks"]["stress_complete_and_noninferior"]


def test_public_evidence_is_verified_and_missing_fields_are_not_zero_filled():
    catalog = public_port.catalog()
    assert len(catalog["entries"]) == 6 and all(e["integrity_valid"] for e in catalog["entries"])
    entry, rows = public_port.load("noaa_la_lb_ais_weather_2024_12_25")
    assert len(rows) == 710 and any(r["wind_speed_mps"] == "" for r in rows)
    assert entry["joined_nonmissing_counts"]["pressure_hpa"] == 710
    assert not any("equipment_availability_ratio" in r for r in rows)


def test_tampered_evidence_stops_before_study(tmp_path):
    path = tmp_path / "not-a-registered-public-source.csv"
    path.write_text("fake")
    with pytest.raises(ValueError):
        public_port._verified(path, "a" * 64)


@pytest.mark.parametrize("site", ["los_angeles", "singapore"])
@pytest.mark.parametrize("scenario", ["historical_baseline", "peak_month_demand", "resource_outage"])
def test_public_historical_studies_exercise_complete_resource_plans(site, scenario):
    report = public_port.replay(public_port.ReplayArgs(site=site, scenario=scenario))
    assert report["plan"]["selected"]["validation"]["feasible"]
    assert report["field_lineage"][-1]["class"] == "simulation_output"
    assert all(r["call_id"].startswith("scenario-call-") for r in report["plan"]["selected"]["schedule"])
    assert report["production_authority"] is False
    assert all(month <= "2024-10" for month in report["derived_inputs"]["monthly_periods_used"])
    if site == "los_angeles":
        assert report["derived_inputs"]["last_used_ais_observation"] <= report["historical_clock"]


def test_different_port_weather_is_not_imputed():
    with pytest.raises(ValueError):
        public_port.replay(public_port.ReplayArgs(site="singapore", scenario="observed_high_wind"))


def test_public_forecast_uses_strict_holdout_and_real_rows():
    r = public_port.forecast_validation()
    assert r["holdout"]["n"] > 30 and r["source"]["rows"] == 1680
    assert all(p["issued_at"] < p["target_at"] for p in r["preview"])
    assert not r["production_authority"] and not r["operational_release"]


def test_connected_api_returns_sources_and_blocks_unsupported_cross_port_case():
    with TestClient(app) as client:
        result = client.get("/api/harness/assurance/public-data")
        assert result.status_code == 200 and len(result.json()["entries"]) == 6
        response = client.post(
            "/api/harness/assurance/historical-study", json={"site": "singapore", "scenario": "observed_high_wind"}
        )
        assert response.status_code == 422


def test_loaded_research_implementation_drift_blocks_new_experiments(tmp_path, monkeypatch):
    from app.harness import research

    changed = dict(research.source_hashes())
    changed["harness/research.py"] = "b" * 64
    monkeypatch.setattr(research, "source_hashes", lambda: changed)
    with pytest.raises(ValueError, match="旧内存代码"):
        research.compare(research.ExperimentArgs(episodes=10, seeds=[1]), tmp_path)


def test_registered_read_defaults_precede_unnecessary_model_questions(tmp_path):
    import time
    from app.access_control import IdentityContext
    from app.harness import model, maritime
    from app.harness.contracts import Action, CreateTask
    from app.harness.runner import Harness
    from app.harness.store import HarnessStore

    class QuestionThenRead:
        def __init__(self):
            self.first = True

        def next(self, task, messages):
            if self.first:
                self.first = False
                return Action(kind="ask", text="请再次提供工具已登记的参数"), {"tokens": 1}
            return model.RulesDriver().next(task, messages)

    harness = Harness(HarnessStore(tmp_path / "future.db"), model_driver=QuestionThenRead())
    try:
        template = next(t for t in maritime.TEMPLATES if t["id"] == "port-future-study")
        task = harness.create(
            CreateTask(
                goal=template["goal"],
                request_id="available-defaults-test",
                driver="model",
                template_id=template["id"],
                allowed_tools=template["required_tools"],
            ),
            IdentityContext("tester", "operator", True, "test"),
            schedule=False,
        )
        schema = model.wire_schema(task)
        kinds = {v["properties"]["kind"]["const"] for v in schema["properties"]["action"]["anyOf"]}
        assert "ask" not in kinds
        harness.schedule(task["id"])
        until = time.monotonic() + 10
        while time.monotonic() < until:
            task = harness.store.get(task["id"])
            if task["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert task["status"] == "completed"
        assert len(task["results"]) == 3
        assert any(e["event"] == "clarification.deferred" for e in harness.store.events(task["id"]))
    finally:
        harness.close()


def test_independent_schedule_checker_rejects_forged_completion_time():
    req = request()
    report = portcall.plan(req)
    forged = copy.deepcopy(report["selected"]["schedule"])
    forged[0]["end_minutes"] -= 20
    releases, _, _ = portcall.arrivals(req)
    assert portcall.verify_schedule(req, forged, releases)["feasible"] is False


@pytest.mark.parametrize(
    "text,claim",
    [
        ("实测、代理、假设与缺项已明确，不执行现场控制。", False),
        ("边界已明确不执行现场控制", False),
        ("已关闭现场控制", False),
        ("不代表已完成生产调度", False),
        ("不能声称已完成实船控制", False),
        ("已经完成现场控制", True),
        ("已下发真实设备", True),
        ("未获准，但已经完成现场控制", True),
        ("不执行生产调度，但已下发设备", True),
    ],
)
def test_production_claim_checker_preserves_negation_without_hiding_real_claims(text, claim):
    from app.harness.verification import claims_production_action

    assert claims_production_action(text) is claim
