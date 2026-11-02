"""Independent arithmetic, causal noninterference, and enumerated robust optima."""

import copy
import itertools
from datetime import date, timedelta

import pytest

from app.harness import predictive_v8 as f, robust_schedule_v8 as r


def calibration():
    return {
        "horizons": {
            str(h): {
                "selected": "blend",
                "baseline": "mean7",
                "radii": {k: {str(v): 0.2 for v in f.LEVELS} for k in f.MODELS},
            }
            for h in f.HORIZONS
        }
    }


def mapping():
    return {date(2024, 1, 1) + timedelta(days=i): 10.0 for i in range(800)}


def test_wis_independent_arithmetic_and_width_penalty():
    # IS for [8,12], y=15, alpha=.2 is 4 + 10*3 = 34.
    assert f.interval_score(15, 8, 12, 0.2) == pytest.approx(34)
    assert f.weighted_interval_score(15, 10, {0.8: (8, 12)}) == pytest.approx((2.5 + 3.4) / 1.5)
    assert f.weighted_interval_score(10, 10, {0.8: (0, 20)}) > f.weighted_interval_score(10, 10, {0.8: (8, 12)})


@pytest.mark.parametrize("low,high,alpha", [(2, 1, 0.1), (0, 1, 0), (0, float("inf"), 0.1)])
def test_invalid_probability_inputs_fail_closed(low, high, alpha):
    with pytest.raises(ValueError):
        f.interval_score(1, low, high, alpha)


@pytest.mark.parametrize("horizon", f.HORIZONS)
def test_forecast_and_monitor_cannot_observe_unpublished_truth(horizon):
    values = mapping()
    origin = date(2025, 6, 1)
    before = f.forecast(values, calibration(), origin, horizon)
    poisoned = {d: v if d <= origin - timedelta(days=f.LAG) else 1000000 for d, v in values.items()}
    assert f.forecast(poisoned, calibration(), origin, horizon) == before
    assert before["status"] == "candidate"
    assert before["monitor"]["latest_realized_target"] == "2025-05-25"
    assert before["production_authority"] is False


def test_missing_and_stale_observations_do_not_get_imputed():
    values = mapping()
    del values[date(2025, 5, 25)]
    outcome = f.forecast(values, calibration(), date(2025, 6, 1), 7)
    assert outcome["status"] == "hold" and outcome["prediction"] is None


def test_unqualified_baseline_is_never_used_as_fallback(monkeypatch):
    monitoring = {
        "latest_realized_target": "2025-05-25",
        "models": {"blend": {"n": 28, "coverage90": 0.95, "mae": 2}, "mean7": {"n": 28, "coverage90": 0.50, "mae": 1}},
    }
    monkeypatch.setattr(f, "monitor", lambda *args: monitoring)
    outcome = f.forecast(mapping(), calibration(), date(2025, 6, 1), 7)
    assert outcome["status"] == "hold" and "no_qualified_baseline" in outcome["reasons"]
    monitoring["models"]["mean7"]["coverage90"] = 0.95
    outcome = f.forecast(mapping(), calibration(), date(2025, 6, 1), 7)
    assert outcome["status"] == "baseline"
    assert outcome["prediction"]["model"] == "mean7"


def test_drift_and_bad_intervals_hold_without_silent_baseline_release():
    values = mapping()
    for d in list(values):
        if date(2025, 5, 12) <= d <= date(2025, 5, 25):
            values[d] = 1000
    result = f.forecast(values, calibration(), date(2025, 6, 1), 1)
    assert result["status"] == "hold" and not result["research_plan_allowed"]
    assert "observed_demand_shift" in result["reasons"]
    cal = calibration()
    for m in cal["horizons"].values():
        for radii in m["radii"].values():
            radii["0.9"] = 20
    assert f.forecast(mapping(), cal, date(2025, 6, 1), 1)["status"] == "hold"


@pytest.mark.parametrize("calls", [-1, float("nan"), float("inf"), True])
def test_bad_source_values_are_rejected(calls):
    with pytest.raises(ValueError):
        f.validated([{"date": "2025-01-01", "calls": calls}])


def test_duplicate_dates_and_premature_model_use_rejected():
    with pytest.raises(ValueError):
        f.validated([{"date": "2025-01-01", "calls": 1}] * 2)
    with pytest.raises(ValueError):
        f.forecast(mapping(), calibration(), date(2024, 1, 1), 7)
    with pytest.raises(ValueError):
        f.forecast(mapping(), calibration(), date(2025, 1, 7), 14)


def test_monitor_excludes_predictions_before_model_was_available():
    for horizon in f.HORIZONS:
        result = f.forecast(mapping(), calibration(), f.MODEL_AVAILABLE_FROM, horizon)
        assert result["status"] == "hold"
        assert all(m["n"] == 0 for m in result["monitor"]["models"].values())


def test_selection_and_calibration_ignore_audit_years_and_ports():
    start = date(2022, 1, 1)
    values = [{"date": start + timedelta(days=i), "calls": 10 + i % 7} for i in range(1461)]
    original = f.fit({"dev": values}, ["dev"])
    changed = [{**row, "calls": row["calls"] if row["date"].year <= 2024 else 100000} for row in values]
    assert f.fit({"dev": changed, "not_used": [{"not_validated": True}]}, ["dev"]) == original


@pytest.fixture
def tiny(monkeypatch):
    monkeypatch.setattr(r.ops, "SLOTS", 8)
    base = {
        "jobs": [
            {
                "id": "A",
                "release": 0,
                "duration": 2,
                "length_m": 310,
                "cranes": 1,
                "shore_kw": 100,
                "priority": 1,
                "due": 4,
            },
            {
                "id": "B",
                "release": 0,
                "duration": 2,
                "length_m": 310,
                "cranes": 1,
                "shore_kw": 100,
                "priority": 2,
                "due": 5,
            },
        ],
        "caps": {k: [v] * 8 for k, v in r.ops.RESOURCES.items()},
        "grid_limit_kw": [1500] * 8,
        "tariff_weight": [1] * 8,
        "base_kw": 200,
        "weights": {
            "deferred_call": 5000,
            "grid_kwh_to_points": 0.01,
            "waiting_priority_per_hour": 2,
            "late_priority_per_hour": 8,
        },
    }
    slow = copy.deepcopy(base)
    slow["jobs"][0]["duration"] = 3
    late = copy.deepcopy(base)
    late["jobs"][1]["release"] = 2
    return [{"name": "base", "problem": base}, {"name": "slow", "problem": slow}, {"name": "late", "problem": late}]


def test_shared_plan_matches_independent_exhaustive_minmax(tiny):
    # All starts, including infeasible choices; no use of the solver's options/matrix.
    choices = [[None, *[{"job": j, "start": s, "berth": 1} for s in range(1, 8)]] for j in range(2)]
    costs = []
    for candidate in itertools.product(*choices):
        schedule = [c for c in candidate if c is not None]
        checks = [r.ops.schedule_check(c["problem"], schedule) for c in tiny]
        if all(c["passed"] for c in checks):
            costs.append(max(c["objective_points"] for c in checks))
    answer = r.solve(tiny)
    assert answer["solver"]["optimality_proven"]
    assert answer["worst_objective_points"] == pytest.approx(min(costs))
    assert answer["solver"]["dual_bound"] == pytest.approx(min(costs))
    assert answer["all_declared_scenarios_feasible"]
    assert answer["production_authority"] is False


def test_infeasible_base_load_and_mismatched_job_identity_are_rejected(tiny):
    changed = copy.deepcopy(tiny)
    changed[1]["problem"]["jobs"][0]["id"] = "different ship"
    with pytest.raises(ValueError):
        r.solve(changed)
    tiny[0]["problem"]["grid_limit_kw"][0] = 199
    with pytest.raises(ValueError):
        r.solve(tiny)


def test_complete_deferral_remains_explicit_under_resource_exhaustion(tiny):
    for case in tiny:
        case["problem"]["caps"]["crane"] = [0] * 8
    answer = r.solve(tiny)
    assert answer["schedule"] == []
    assert all(c["deferred_calls"] == 2 and c["completed_calls"] == 0 for c in answer["scenarios"])
    assert answer["all_declared_scenarios_feasible"]
