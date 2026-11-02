"""Causal feedback, honest missingness, constrained actions and admission gates."""

import copy
import gzip
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from app.harness import annual_v9 as tide, constrained_rl_v9 as rl, interval_v9 as interval


def model():
    return {
        "radii": {"weekday84": {str(v): 0.2 for v in interval.old.LEVELS}},
        "calibration_samples": {"weekday84": 300},
    }


@pytest.mark.parametrize("horizon", [1, 7, 14])
def test_delayed_feedback_ignores_all_unpublished_labels(horizon):
    start = date(2023, 8, 1)
    mapping = {start + timedelta(days=i): float(10 + i % 7) for i in range(1100)}
    origin = date(2026, 4, 10)
    cutoff = origin - timedelta(days=7)

    def selected(values):
        cache = interval.point_cache(values, horizon, end=origin + timedelta(days=horizon))
        rows = interval.replay(cache, model(), horizon, "aci90", 2026)["rows"]
        row = next(r for r in rows if r["origin"] == origin.isoformat())
        for k in ["actual", "covered90", "absolute_error", "wis"]:
            row.pop(k)
        return row

    before = selected(mapping)
    changed = {d: v if d <= cutoff else 100000.0 for d, v in mapping.items()}
    assert selected(changed) == before
    assert before["last_feedback_target"] <= cutoff.isoformat()
    assert before["calibration_latest_day"] <= cutoff.isoformat()


def test_missing_target_truth_does_not_suppress_issued_prediction():
    mapping = {date(2023, 8, 1) + timedelta(days=i): 10.0 + i % 3 for i in range(1100)}
    target = date(2026, 4, 17)
    before = interval.point_cache(mapping, 7, end=target)[target]
    mapping.pop(target)
    after = interval.point_cache(mapping, 7, end=target)[target]
    assert after["point"] == before["point"]
    assert after["actual"] is after["error"] is None


def test_adaptive_update_uses_each_mature_forecast_once():
    start = date(2025, 1, 1)
    cache = {
        start + timedelta(days=i): {"point": 10.0, "actual": 10.0, "error": 0.0, "scale": 10.0, "drift_z": 0.0}
        for i in range(600)
    }
    rows = interval.replay(cache, model(), 7, "aci90", 2026)["rows"]
    row = rows[0]
    assert row["origin"] == "2026-01-15" and row["alpha90"] == pytest.approx(0.1)
    row = next(r for r in rows if r["origin"] == "2026-02-01")
    assert row["alpha90"] == pytest.approx(0.111)
    assert row["monitor_samples"] == 11


def test_wide_intervals_are_not_clipped_or_hidden():
    start = date(2025, 1, 1)
    cache = {
        start + timedelta(days=i): {"point": 10.0, "actual": 10.0, "error": 20.0, "scale": 10.0, "drift_z": 0.0}
        for i in range(600)
    }
    result = interval.replay(cache, model(), 7, "rolling90", 2026)
    assert result["summary"]["retained"] == 0
    assert result["summary"]["n"] > 0
    assert result["summary"]["mean_width90_normalized"] > 2
    assert not result["summary"]["width_gate"]


@pytest.mark.parametrize("availability", [0.5, 1.0])
def test_bellman_feasible_set_matches_independent_runtime_constraint(availability):
    means, volatility, queue = np.array([0.5, 1.0, 2.0]), np.array([0.1, 0.2, 2.4]), np.array([0.0, 0.1, 5.0])
    actual = rl.allowed_actions(means, volatility, queue, availability)
    for i in range(3):
        maximum = 2 if availability < 0.75 else 4
        choices = [
            a for a in range(maximum + 1) if queue[i] + means[i] + volatility[i] <= rl.FACTORS[a] * availability + 1e-12
        ]
        expected = choices or [maximum]
        assert list(np.flatnonzero(actual[i])) == expected


def test_constrained_bellman_terminal_action_matches_brute_force(monkeypatch):
    monkeypatch.setattr(rl, "MEAN", np.array([0.8]))
    monkeypatch.setattr(rl, "VOL", np.array([0.1]))
    monkeypatch.setattr(rl, "QUEUE", np.arange(0, 0.50001, 0.05))
    noises = np.array([[[-1.0, -0.5, -0.1, 0.0, 0.1, 0.5, 1.0]]] * 2)
    table, _ = rl.bellman(noises)
    for q in [0.0, 0.1, 0.3]:
        allowed = rl.allowed_actions(np.array(0.8), np.array(0.1), np.array(q), 1.0)
        for previous in range(5):
            costs = []
            for a, factor in enumerate(rl.FACTORS):
                ending = np.maximum(0, q + 0.8 + 0.1 * noises[0, 0] - factor)
                cost = (3 * ending + 0.5 * factor**2 + 5 * np.maximum(0, ending - 4)) @ rl.WEIGHTS
                costs.append(cost + 0.05 * abs(rl.FACTORS[previous] - factor) if allowed[a] else float("inf"))
            action = int(np.sum(q + 1e-10 >= table[0, 0, 0, 1, 0, previous]))
            assert action == int(np.argmin(costs))


def test_zero_gain_or_missing_evidence_cannot_admit_rl():
    required = [
        "positive_port_cluster_ci",
        "no_mean_port_regression",
        "stress_noninferiority",
        "no_feasible_window_violation",
        "no_excess_over_max_capacity",
        "gain_not_concentrated",
    ]
    checks = dict.fromkeys(required, True)
    assert rl.admission(checks)
    for name in required:
        missing = checks.copy()
        missing.pop(name)
        failed = {**checks, name: False}
        assert not rl.admission(missing) and not rl.admission(failed)


def test_season_balanced_level_does_not_weight_missing_season_as_zero():
    times, errors = [], []
    for year, value in [(2023, 0.1), (2024, 0.2)]:
        for at in tide.old.previous.hours(year):
            if at.month in [11, 12]:
                continue
            times.append(at)
            errors.append(value)
    result = tide.balanced_residuals(times, errors)
    assert result["balanced_last_residual_m"] == pytest.approx(0.2)
    assert result["balanced_slope_m_per_year"] == pytest.approx(0.1)
    with pytest.raises(ValueError):
        tide.balanced_residuals(times[:100], errors[:100])


def test_selection_rejects_average_gain_with_bad_quarter():
    base = {"level_weight": 0, "trend_weight": 0, "objective": 0.1, "quarter_mae_m": [0.1] * 4}
    candidate = {"level_weight": 1, "trend_weight": 0.5, "objective": 0.08, "quarter_mae_m": [0.05, 0.05, 0.05, 0.104]}
    selected, baseline = tide.select([base, candidate], 0.002)
    assert selected == baseline == base


def test_missing_annual_truth_stays_in_denominator_and_width_is_not_clipped():
    row = {"actual": 1.0, "prediction": 1.0, "baseline": 1.0, "lower": 0.5, "upper": 1.5}
    rows = [row.copy() for _ in range(100)]
    for r in rows[:10]:
        r["actual"] = None
    limits = {
        "mae_m": 0.2,
        "coverage": 0.8,
        "width_m": 0.75,
        "availability": 0.95,
        "baseline_noninferiority_epsilon_m": 1e-9,
    }
    result = tide.summarize(rows, limits)
    assert result["availability"] == 0.9 and result["max_width90_m"] == 1
    assert not result["passed"] and not result["checks"]["availability"] and not result["checks"]["width"]


def test_hourly_product_schema_accepts_verified_product_and_rejects_flagged(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    protocol = data / "protocol.json"
    protocol.write_text("{}")
    raw = {
        "metadata": {"lat": "1"},
        "data": [
            {"t": "2024-01-01 00:00", "v": "1", "f": "0,0"},
            {"t": "2024-01-01 01:00", "v": "1", "f": "1,0"},
            {"t": "2024-01-01 02:00", "v": "1", "f": "0,0", "q": "p"},
        ],
    }
    path = data / "raw.gz"
    path.write_bytes(gzip.compress(json.dumps(raw).encode()))
    (data / "history-manifest.json").write_text(
        json.dumps(
            {
                "protocol_sha256": tide.files.sha(protocol),
                "entries": [
                    {
                        "station_id": "test",
                        "site": "test",
                        "path": "data/raw.gz",
                        "sha256": tide.files.sha(path),
                        "provider_error": False,
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(tide, "DATA", data)
    monkeypatch.setattr(tide, "ROOT", tmp_path)
    _, groups = tide.load("history")
    assert len(groups["test"]["observed"]) == 1 and groups["test"]["rejected"]["2024"] == 2


def test_annual_forward_prediction_never_reads_test_observations(monkeypatch):
    times = [datetime(2025, 6, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(tide, "reconstruct", lambda ts, coef: np.array([1.0] * len(ts)))
    model = {
        "coef": {},
        "balanced_last_residual_m": 0.1,
        "balanced_slope_m_per_year": 0.02,
        "last_year_midpoint": 2024.5,
    }
    selected = {"level_weight": 0.5, "trend_weight": 0.25}
    assert tide.predict(times, copy.deepcopy(model), selected)[0] == pytest.approx(
        1.05 + 0.005 * (tide.old.year_coordinate(times)[0] - 2024.5)
    )
