"""Information boundaries, meaningful policy counterexamples and seasonal bands."""

import copy
import json
import socket
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from app.harness import root_control_v10 as control, seasonal_twin_v10 as tide
from app.harness import rl_v7


def frames(actual, upper):
    queue, cost, previous = 0.0, 0.0, 2
    result = []
    for t in range(90):
        action = control.feasible(queue, upper, 0, 1)[0]
        end = max(0, queue + actual - control.FACTORS[action])
        cost = (
            end
            + 0.5 * control.FACTORS[action] ** 2
            + 0.05 * abs(control.FACTORS[action] - control.FACTORS[previous])
            + 5 * max(0, end - 4)
            + (2 * end if t == 89 else 0)
        )
        result.append(
            {
                "capacity_scale_proxy": 1.0,
                "arrival_indicator": actual,
                "guard_upper_normalized": upper,
                "declared_availability": 1.0,
                "cost_proxy": cost,
            }
        )
        queue, previous = end, action
    return result


def test_unique_action_implies_zero_clairvoyant_headroom():
    result = control.hindsight_bound(frames(1, 1.25), time_limit=5)
    assert result["solved"] and result["status"] == 0
    assert result["maximum_gain_upper_bound"] == pytest.approx(0, abs=1e-8)
    assert result["relative_clairvoyant_gain"] == pytest.approx(0, abs=1e-8)
    assert all(a == 4 for a in result["actions"])
    assert result["oracle_is_not_deployable"]


def test_oracle_finds_counterexample_to_universal_no_improvement_claim():
    result = control.hindsight_bound(frames(1.35, 0.7), time_limit=10)
    assert result["solved"] and result["relative_clairvoyant_gain"] > 0
    assert result["dual_lower_bound"] <= result["oracle_cost"] + 1e-8
    assert result["maximum_gain_upper_bound"] + 1e-8 >= result["relative_clairvoyant_gain"]


def build_rollout():
    frozen = json.loads((rl_v7.c.BASE_DIR / ".runtime/rl-v9-20261031/selection-before-test.json").read_text())
    model = frozen["models"][0]
    policy = control.Rollout(np.load(rl_v7.c.BASE_DIR / model["path"])["thresholds"], model["centroids"], 7)
    return policy, frozen


def test_rollout_future_invariance_and_no_language_model_or_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("a numeric policy must not request a language model or network")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    try:
        import requests
    except ImportError:
        pass  # requests is optional; the socket guard covers every HTTP client.
    else:
        monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    from app.model_gateway import ModelGateway

    for name, value in vars(ModelGateway).items():
        if callable(value) and not name.startswith("__"):
            monkeypatch.setattr(ModelGateway, name, forbidden)
    policy, frozen = build_rollout()
    records = [(date(2026, 1, 1) + timedelta(days=i), 100.0 + i % 7) for i in range(132)]
    env = rl_v7.old.Episode(records, frozen["forecast"]["selected"], "normal", tuple(frozen["gains"]), 0, 0)
    h, _, mean, _, _, _, avail, _ = env.context()
    assert len(control.feasible(0, mean / env.scale, rl_v7.c.uncertainty_scale(h) / env.scale, avail)) > 1
    expected = policy.action(env)
    # All records beyond the decision's publication cutoff are poisoned.
    cutoff = env.index - 7
    changed = [(d, v if i <= cutoff else 100000.0) for i, (d, v) in enumerate(records)]
    other = rl_v7.old.Episode(changed, frozen["forecast"]["selected"], "normal", tuple(frozen["gains"]), 0, 0)
    assert policy.action(other) == expected
    h, _, mean, _, _, _, avail, _ = env.context()
    assert expected in control.feasible(
        env.backlog / env.scale, mean / env.scale, rl_v7.c.uncertainty_scale(h) / env.scale, avail
    )
    from app.harness.physical_v3 import decode

    sealed = json.loads((rl_v7.c.BASE_DIR / "data/public/annual_v9_20261031/selection-before-test.json").read_text())
    station = next(s for s in sealed["stations"] if s["status"] == "ready")
    model = station["versions"]["v9"]
    times = tide.old.old.previous.hours(2025)[:24]
    result = tide.old.predict(times, decode(model["model"]), model["choice"])
    assert len(result) == 24 and np.isfinite(result).all()


def calibration_errors():
    result = []
    for year in [2023, 2024]:
        for i in range(365 * 24):
            at = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
            error = -0.2 + (i % 11) * 0.01 if at.month <= 3 else (i % 11 - 5) * 0.2
            result.append((at, error))
    return result


def test_seasonal_signed_bounds_reduce_irrelevant_worst_season_without_clipping():
    errors = calibration_errors()
    target = datetime(2025, 2, 1, tzinfo=timezone.utc)
    global_band = tide.limits(errors, "v9_global", target)
    local = tide.limits(errors, "quarter_signed", target)
    assert local[0] < 0 and local[1] == 0
    assert local[1] - local[0] < global_band[1] - global_band[0]
    storm = tide.limits(errors, "quarter_signed", datetime(2025, 8, 1, tzinfo=timezone.utc))
    assert storm[1] - storm[0] > 0.75


def test_small_calibration_segments_are_not_fabricated():
    with pytest.raises(ValueError):
        tide.signed_quantile([1.0] * 199, 0.95)


@pytest.mark.parametrize("method", tide.METHODS)
def test_cached_bands_equal_direct_statistical_definition(method):
    errors = calibration_errors()
    bands = tide.bands_for_year(errors, method, 2025)
    for month in [1, 3, 4, 7, 9, 12]:
        at = datetime(2025, month, 15, 12, tzinfo=timezone.utc)
        assert bands[at.date().isoformat()] == list(tide.limits(errors, method, at))


def test_calibration_fits_and_scores_only_pretest_years(monkeypatch):
    times = [
        datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
        for year in [2023, 2024, 2025]
        for i in range(8760)
    ]
    observed = {t: float(t.year) for t in times}

    def fit(g, year, window, count, plan):
        assert year in [2023, 2024]
        return {"year": year}

    monkeypatch.setattr(tide.old, "fit", fit)
    monkeypatch.setattr(tide.old, "predict", lambda times, model, choice: np.full(len(times), model["year"]))
    plan = {"calibration_years": [2023, 2024]}
    choice = {"window_years": 3, "count": 20}
    before = tide.calibration({"observed": observed}, choice, plan)
    after = tide.calibration({"observed": {t: v if t.year < 2025 else 1e8 for t, v in observed.items()}}, choice, plan)
    assert before == after and max(t.year for t, e in before) == 2024


def test_unchanged_acceptance_limits():
    root = rl_v7.c.BASE_DIR
    previous = json.loads((root / "data/public/annual_v9_20261031/protocol.json").read_text())
    current = json.loads((root / "data/public/annual_v10_20261031/protocol.json").read_text())
    assert current["limits"] == previous["limits"]
    old = json.loads((root / "data/public/rl_v9_20261031/protocol.json").read_text())
    new = json.loads((root / "data/public/rl_v10_20261031/protocol.json").read_text())
    assert new["guard"] == old["guard"] and new["acceptance"] == old["acceptance"]
