"""Information boundaries, learned updates, complete cohorts and physical split invariants."""

import copy
import math
import random
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest
from pydantic import ValidationError

from app.harness import (
    crossport_control as c,
    crossport_forecast as f,
    crossport_benchmark as b,
    portwatch_data as d,
    multisite_twin,
)
from app.rl_lab import algorithms as old


def records():
    first = date(2020, 1, 1)
    return [(first + timedelta(days=i - 42), 100.0 + 10 * math.sin(i)) for i in range(132)]


def test_legacy_double_q_behavior_uses_both_estimators_and_preserves_old_artifact_version():
    state = (1,)
    key = old._state_key(state)
    primary = {key: [3.0, 0.0, 0.0, 0.0, 0.0]}
    secondary = {key: [0.0, 0.0, 0.0, 0.0, 8.0]}
    assert old.epsilon_greedy(old._behavior_values(primary, secondary, state), (True,) * 5, 0.0, random.Random(1)) == 4
    p = old.TrainedPolicy("q_learning", primary, None, 1, {})
    payload = p.public_dict()
    payload.pop("implementation_version")
    assert old.TrainedPolicy.from_dict(payload).implementation_version.startswith("tabular.v1")


def test_current_or_future_public_demand_cannot_change_current_observation():
    a = records()
    modified = copy.deepcopy(a)
    for i in range(36, len(modified)):
        modified[i] = (modified[i][0], 10000.0)
    one = c.ServiceEpisode(a, {"kind": "mean7"})
    two = c.ServiceEpisode(modified, {"kind": "mean7"})
    assert one.features() == two.features()  # days newer than t-7 are unavailable public inputs
    assert one.step(2)[0] != two.step(2)[0]  # actual outcome becomes available to the simulator after acting


def test_markov_contract_exposes_previous_action_time_and_controller_memory():
    env = c.ServiceEpisode(records(), {"kind": "mean7"})
    base = env.features()[0]
    env.previous_action = 4
    assert env.features()[0] != base
    env.previous_action = 2
    env.integral = 1.0
    assert env.features()[0] != base
    assert len(env.features()[0]) == 25


@pytest.mark.parametrize("scenario", ["normal", "demand_surge", "resource_outage", "publication_delay"])
def test_source_lag_flow_conservation_and_actual_masks_are_enforced(scenario):
    result = c.evaluate(c.Policy("pid"), records(), {"kind": "mean7"}, scenario)
    backlog = 0.0
    for frame in result["frames"]:
        expected = backlog + frame["arrival_indicator"] - frame["service_proxy"]
        assert frame["backlog_proxy"] == pytest.approx(expected)
        backlog = frame["backlog_proxy"]
        lag = (date.fromisoformat(frame["date"]) - date.fromisoformat(frame["public_latest_day"])).days
        assert lag == (14 if scenario == "publication_delay" else 7)
        if frame["declared_availability"] < 0.75:
            assert frame["action"] <= 2
    assert result["score"] == pytest.approx(-sum(r["cost_proxy"] for r in result["frames"]) / 90)


def test_invalid_capacity_action_is_rejected_before_state_advances():
    env = c.ServiceEpisode(records(), {"kind": "mean7"}, scenario="resource_outage")
    env.index += 30
    before = env.backlog
    with pytest.raises(ValueError):
        env.step(4)
    assert env.backlog == before


def test_residual_fallback_is_explicit_and_not_counted_as_learning():
    policy = c.Policy("residual_double_dqn", c.Network(np.random.default_rng(1), True), True, 1)
    result = c.evaluate(policy, records(), {"kind": "mean7"}, "publication_delay")
    assert result["fallback_fraction"] == 1 and result["learned_action_fraction"] == 0
    assert result["action_differs_from_pid_fraction"] == 0


def test_actual_double_dqn_training_changes_weights_and_finishes_real_episodes():
    model, curve = c.train_policy("double_dqn", [records()], {"kind": "mean7"}, 11, steps=400)
    original = c.Network(np.random.default_rng(11))
    assert curve and curve[-1]["step"] >= 360
    assert any(not np.array_equal(a, b) for a, b in zip(original.params, model.network.params))
    assert all(np.isfinite(p).all() for p in model.network.params)


def test_training_cancellation_never_returns_a_fabricated_model():
    with pytest.raises(InterruptedError):
        c.train_policy("double_dqn", [records()], {"kind": "mean7"}, 1, steps=400, cancelled=lambda: True)


def test_forecast_refuses_history_newer_than_publication_contract():
    history = records()[:35]
    target = history[-1][0] + timedelta(days=1)
    with pytest.raises(ValueError):
        f.predict({"kind": "mean7"}, history, target)


def test_forecast_fit_is_invariant_to_future_and_whole_port_outcomes():
    start = date(2019, 1, 1)
    series = {
        p: [{"date": start + timedelta(days=i), "calls": 100.0 + (i % 7)} for i in range(2557)]
        for p in d.TRAIN_PORTS + d.UNSEEN_PORTS
    }
    one = f.fit(series)
    changed = copy.deepcopy(series)
    for p, rows in changed.items():
        for r in rows:
            if p in d.UNSEEN_PORTS or r["date"].year >= 2024:
                r["calls"] *= 50
    assert one == f.fit(changed)


def test_frozen_actual_international_cohort_has_no_synthesized_dates():
    if not (d.FOLDER / "raw/published-daily-ports-export.csv.gz").is_file():
        pytest.skip("bulk PortWatch export is a separate Release asset; restore it for full source verification")
    manifest, series = d.load_all()
    assert len(series) == 8 and sum(map(len, series.values())) == 20456
    assert len({e["iso3"] for e in manifest["entries"]}) == 7
    train, excluded = b.windows(series, [2019, 2020, 2021, 2022], d.TRAIN_PORTS)
    validation, _ = b.windows(series, [2023], d.TRAIN_PORTS)
    test, missing = b.windows(series, [2024, 2025], list(series))
    assert len(train) == 60 and len(excluded) == 4 and len(validation) == 16
    assert len(test) == 64 and not missing
    assert not set(w["port_id"] for w in train) & set(d.UNSEEN_PORTS)


def test_window_with_a_source_gap_is_excluded_instead_of_filled():
    rows = [{"date": d, "calls": v} for d, v in records()]
    assert d.contiguous(rows, date(2020, 1, 1), 90) is not None
    del rows[50]
    assert d.contiguous(rows, date(2020, 1, 1), 90) is None


def test_port_cluster_statistics_do_not_count_duplicate_seeds_as_ports():
    result = b.clustered_interval({"A": [1, 2, 3, 4], "B": [-2, -1, 0, 1]})
    assert result["ports"] == 2 and result["quarter_cells"] == 8
    assert result["worst_port_mean_delta"] == -0.5 and result["worst_quarter_delta"] == -2


@pytest.mark.parametrize("config", [{"seeds": [1] * 5}, {"seeds": [1, 2, 3, 4]}, {"training_steps": 1}])
def test_protocol_rejects_pseudoreplication_and_unbounded_configuration(config):
    with pytest.raises(ValidationError):
        b.Config(**config)


def test_harmonic_calibration_uses_disjoint_seasons_and_does_not_grant_site_control(monkeypatch):
    def synthetic(first, n):
        return [(first + timedelta(minutes=6 * i), 1 + math.sin(i / 20) * 0.2) for i in range(n)]

    groups = {
        "fixture": {
            split: {
                "rows": synthetic(datetime(2024, month, 1, tzinfo=timezone.utc), n),
                "source": {"site": "synthetic-unit-test"},
                "rejected_rows": 0,
            }
            for split, month, n in [("training", 1, 6000), ("validation", 7, 1200), ("sealed_test", 12, 1200)]
        }
    }
    monkeypatch.setattr(multisite_twin, "load", lambda: ({"schema": "synthetic-test-only"}, groups))
    report = multisite_twin.study()
    r = report["results"][0]
    assert r["model_fitted_at_cutoff"] < r["model_selected_at_cutoff"] < r["preview"][0]["target_at"]
    assert r["operational_release"] is False and report["production_authority"] is False
    assert len(r["candidates"]) == 6 and r["blockers"]  # arbitrary wave is not a calibrated physical tide
