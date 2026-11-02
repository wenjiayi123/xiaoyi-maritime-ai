"""Research information contracts and strengthened planner/learner invariants."""

import math
from datetime import date, timedelta

import numpy as np
import pytest

from app.harness import crossport_v2 as c, physical_v2 as p


def records():
    origin = date(2020, 1, 1)
    return [(origin + timedelta(days=i - 42), 100.0 + math.sin(i) * 10) for i in range(132)]


def test_synthetic_shock_enters_public_observation_only_after_publication_lag():
    env = c.Episode(records(), {"kind": "mean7"}, "demand_surge")
    for _ in range(27):
        before = env.index - 42
        history, lag = env.history()
        first_shock = env.records[62][0]
        seen = dict(history).get(first_shock)
        if before < 27:
            assert seen is None
        env.step(4)
    assert env.history()[0][-1][1] == pytest.approx(env.records[62][1] * 1.5)
    assert lag == 7


def test_observation_is_unchanged_by_unreleased_or_future_target_values():
    a = records()
    b = [(d, v if i < 36 else 99999.0) for i, (d, v) in enumerate(a)]
    assert c.Episode(a, {"kind": "mean7"}).features() == c.Episode(b, {"kind": "mean7"}).features()


def test_context_cache_is_invalidated_and_large_queue_remains_visible():
    env = c.Episode(records(), {"kind": "mean7"})
    first = env.context()
    env.step(4)
    assert env.context() is not first
    env.backlog = env.scale * 10
    one = env.features()[0][0]
    env.backlog = env.scale * 20
    assert env.features()[0][0] > one


def test_last_step_mpc_has_actual_terminal_and_switch_cost_and_outage_mask():
    table = c.planner_values(20, 1.0, 1)
    index = 10  # backlog ratio one
    for action, factor in enumerate(c.old.FACTORS):
        q = max(0, 1 + 1 - factor)
        expected = 3 * q + 0.5 * factor**2 + 0.05 * abs(factor - 1)
        assert table[index, 2, action] == pytest.approx(expected)
    assert np.all(c.planner_values(20, 0.5, 1)[:, :, 3:] > 1e10)


def test_rl_updates_real_weights_without_changing_imitation_snapshot():
    windows = [{"records": records()}]
    teacher = (np.zeros((32, 25)), np.tile(np.arange(5) * -0.1, (32, 1)))
    rl, imitation, curve = c.train(
        "mpc_guided_double_dqn", windows, {"kind": "mean7"}, (0.2, 0.02, 0.02), 77, teacher, steps=400
    )
    assert rl.network.updates > 1500
    assert imitation.network.updates == 0
    assert curve and any(not np.array_equal(a, b) for a, b in zip(rl.network.params, imitation.network.params))


def test_physical_no_evaluable_observations_are_a_failure_and_not_omitted():
    r = p.metrics([], 0.1, 168, {"mae_m": 0.2, "coverage": 0.8, "width_m": 0.75}, [])
    assert r["passed"] is False and r["n"] == 0 and r["expected"] == 168


def test_wide_intervals_cannot_make_physical_acceptance_pass():
    r = p.metrics([0.01] * 168, 1.0, 168, {"mae_m": 0.2, "coverage": 0.8, "width_m": 0.75}, [0.1] * 168)
    assert r["coverage"] == 1 and r["blockers"] == ["interval_width"]


def test_new_physical_assimilation_cannot_see_target_or_future_values():
    from datetime import datetime, timezone

    target = datetime(2026, 2, 2, tzinfo=timezone.utc)
    observed = {target - timedelta(hours=i): float(i) for i in range(10)}
    tide = {at: 0.1 for at in observed}
    before = p.prediction(target, observed, tide, 60, 3, 60)
    observed[target] = 999999.0
    observed[target + timedelta(hours=1)] = -999999.0
    assert p.prediction(target, observed, tide, 60, 3, 60) == before
