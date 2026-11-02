import json
from datetime import date, timedelta

import numpy as np
import pytest

from app.harness import robust_v4 as r


def records(arrival=100):
    start = date(2020, 1, 1)
    return [(start + timedelta(days=i), float(arrival)) for i in range(132)]


def test_empty_queue_is_censored_not_a_hidden_arrival_measurement():
    one, two = records(), records()
    one[42] = (one[42][0], 10.)
    two[42] = (two[42][0], 50.)
    a, b = [r.Episode(rows, {"kind": "mean7"}, alpha=1) for rows in [one, two]]
    a.step(2)
    b.step(2)
    assert a.backlog == b.backlog == 0
    assert a.arrival_estimate == b.arrival_estimate == 100
    assert a.features() == b.features()


def test_saturated_queue_identity_uses_only_previous_outcome_and_own_capacity():
    one, two = records(), records()
    one[42] = two[42] = (one[42][0], 200.)
    two[43:] = [(d, 90000.) for d, _ in two[43:]]
    a, b = [r.Episode(rows, {"kind": "mean7"}, alpha=1) for rows in [one, two]]
    a.step(2)
    b.step(2)
    assert a.arrival_estimate == pytest.approx(200)
    assert a.context()[2] == b.context()[2] == pytest.approx(200)
    assert a.frames[-1]["nowcast_latest_queue_day"] is None
    assert a.features() == b.features()


def test_shared_reserve_filter_is_explicit_json_serializable_and_respects_outage():
    values = np.full((len(r.DEMAND), len(r.VOL), 2, len(r.HORIZONS), 5, 4), 999., dtype=np.float32)
    raw = r.ThresholdPolicy("fixture", values)
    guard = {"name": "reserve", "sigma": 1., "queue_budget": 0.}
    policy = r.Policy(raw, guard, (.2, .02, .02), .5)
    env = r.Episode(records(), {"kind": "mean7"}, alpha=.5)
    action = policy.action(env)
    assert action > 0
    env.step(action)
    assert env.frames[-1]["raw_learned_or_baseline_action"] == 0
    assert env.frames[-1]["safety_override"] is True
    json.dumps(env.frames)
    env.scenario = "resource_outage"
    env.index = 72
    env.cache = env.memory_cache = None
    assert policy.action(env) <= 2
