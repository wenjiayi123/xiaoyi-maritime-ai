"""Diagnose constrained decision headroom and improve a learned policy by rollout.

The clairvoyant MILP is a diagnostic lower bound, never an executable controller.
Rollout uses only currently published history, the inherited learned residual
model and policy. A longer-horizon same-information rollout is a strong baseline.
"""

import math

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from app.harness import rl_v7 as old

FACTORS = old.FACTORS


def feasible(queue, mean, sigma, availability):
    maximum = 2 if availability < 0.75 else 4
    choices = [a for a in range(maximum + 1) if queue + mean + sigma <= FACTORS[a] * availability + 1e-12]
    return choices or [maximum]


def raw_actions(table, mean, sigma, queues, previous, remaining, availability):
    outside = (mean > old.MEAN[-1]) | (queues > old.QUEUE[-1])
    di = float(np.interp(mean, old.MEAN, np.arange(len(old.MEAN))))
    vi = float(np.interp(sigma, old.VOL, np.arange(len(old.VOL))))
    bounds = np.zeros((*queues.shape, 4))
    for d, dw in [(int(di), 1 - di % 1), (min(int(di) + 1, len(old.MEAN) - 1), di % 1)]:
        for v, vw in [(int(vi), 1 - vi % 1), (min(int(vi) + 1, len(old.VOL) - 1), vi % 1)]:
            bounds += dw * vw * table[d, v, int(availability >= 0.75), remaining - 1, previous]
    maximum = 2 if availability < 0.75 else 4
    return np.where(outside, maximum, np.minimum(maximum, np.sum(queues[..., None] + 1e-10 >= bounds, axis=-1)))


class Rollout:
    def __init__(self, table, centroids, horizon, seed=0):
        self.table, self.centroids, self.horizon, self.seed = table, np.asarray(centroids), horizon, seed
        self.name = "rl_rollout7" if horizon == 7 else "matched_rollout28"

    def action(self, env):
        history, lag, mean, _, _, _, avail, _ = env.context()
        scale = env.scale
        sigma = old.c.uncertainty_scale(history) / scale
        mean, queue = mean / scale, env.backlog / scale
        allowed = feasible(queue, mean, sigma, avail)
        if len(allowed) == 1:
            return allowed[0]
        remaining = 90 - (env.index - 42)
        horizon = min(remaining, self.horizon)
        # Same learned centroids as offline RL; 7 deterministic common scenarios.
        vi = int(np.argmin(abs(old.VOL - sigma)))
        noises = self.centroids[int(lag == 14), vi]
        weights = old.WEIGHTS
        queues = np.full((len(allowed), 7), queue)
        previous = np.full(queues.shape, env.previous_action, dtype=int)
        costs = np.zeros(queues.shape)
        table = self.table[int(lag == 14)]
        from datetime import timedelta

        now = env.records[env.index][0]
        for depth in range(horizon):
            day = now + timedelta(days=depth)
            m = old.c.forecasting.predict(env.forecast, history, day) / scale
            if depth == 0:
                actions = np.broadcast_to(np.asarray(allowed)[:, None], queues.shape)
            else:
                actions = raw_actions(table, m, sigma, queues, previous, remaining - depth, avail)
                required = queues + m + sigma
                maximum = 2 if avail < 0.75 else 4
                minimum = np.minimum(maximum, np.sum(required[..., None] > FACTORS[:maximum] * avail + 1e-12, axis=-1))
                actions = np.maximum(actions, minimum)
            # A common rank path represents persistent residual uncertainty;
            # assumptions are explicit and tested, not future observed arrivals.
            actual = np.maximum(0.0, m + sigma * noises)
            queues = np.maximum(0, queues + actual - FACTORS[actions] * avail)
            costs += (
                queues
                + 0.5 * FACTORS[actions] ** 2
                + 0.05 * abs(FACTORS[actions] - FACTORS[previous])
                + 5 * np.maximum(0, queues - 4)
            )
            if depth + 1 == remaining:
                costs += 2 * queues
            previous = actions
        values = costs @ weights
        return allowed[int(np.argmin(values))]


def hindsight_bound(frames, *, time_limit=15):
    """Exact finite trace optimization, with the original safety set and cost."""
    n = len(frames)
    assert n == 90
    scale = frames[0]["capacity_scale_proxy"]
    arrivals = np.asarray([f["arrival_indicator"] / scale for f in frames])
    # Reconstruct the guard from observed history upstream; saved explicitly.
    upper = np.asarray([f["guard_upper_normalized"] for f in frames])
    avails = np.asarray([f["declared_availability"] for f in frames])
    width = 8 * n  # 5 one-hot actions, queue, overflow, switching distance.
    obj = np.zeros(width)
    lo = np.zeros(width)
    hi = np.full(width, np.inf)
    integrality = np.zeros(width, dtype=int)
    for t in range(n):
        obj[5 * t : 5 * t + 5] = 0.5 * FACTORS**2
        hi[5 * t : 5 * t + 5] = 1
        integrality[5 * t : 5 * t + 5] = 1
        if avails[t] < 0.75:
            hi[5 * t + 3 : 5 * t + 5] = 0
    obj[5 * n : 6 * n] = 1
    obj[6 * n : 7 * n] = 5
    obj[7 * n :] = 0.05
    obj[6 * n - 1] += 2
    rows, lower, higher = [], [], []

    def constraint(terms, low=-np.inf, high=np.inf):
        rows.append(terms)
        lower.append(low)
        higher.append(high)

    big = float(sum(arrivals) + max(upper) + 2)
    for t in range(n):
        actions = {5 * t + a: 1 for a in range(5)}
        constraint(actions, 1, 1)
        balance = {5 * n + t: 1, **{5 * t + a: FACTORS[a] * avails[t] for a in range(5)}}
        if t:
            balance[5 * n + t - 1] = -1
        constraint(balance, arrivals[t])
        constraint({6 * n + t: 1, 5 * n + t: -1}, -4)
        maximum = 2 if avails[t] < 0.75 else 4
        for a in range(maximum):
            terms = {5 * t + a: big}
            if t:
                terms[5 * n + t - 1] = 1
            constraint(terms, high=big + FACTORS[a] * avails[t] - upper[t])
        for sign in [-1, 1]:
            terms = {7 * n + t: 1, **{5 * t + a: sign * FACTORS[a] for a in range(5)}}
            if t:
                terms.update({5 * (t - 1) + a: -sign * FACTORS[a] for a in range(5)})
                constraint(terms, 0)
            else:
                constraint(terms, sign * FACTORS[2])
    matrix = lil_matrix((len(rows), width))
    for i, terms in enumerate(rows):
        for j, value in terms.items():
            matrix[i, j] = value
    result = milp(
        obj,
        integrality=integrality,
        bounds=Bounds(lo, hi),
        constraints=LinearConstraint(matrix.tocsr(), lower, higher),
        options={"time_limit": time_limit, "mip_rel_gap": 1e-8},
    )
    baseline = sum(f["cost_proxy"] for f in frames)
    if result.x is None:
        return {"status": int(result.status), "baseline_cost": baseline, "solved": False}
    actions = np.argmax(result.x[: 5 * n].reshape(n, 5), axis=1)
    queue, cost, previous, violations = 0.0, 0.0, 2, 0
    for t, a in enumerate(actions):
        assert a in feasible(queue, upper[t], 0, avails[t])
        queue = max(0.0, queue + arrivals[t] - FACTORS[a] * avails[t])
        cost += (
            queue
            + 0.5 * FACTORS[a] ** 2
            + 0.05 * abs(FACTORS[a] - FACTORS[previous])
            + 5 * max(0.0, queue - 4)
            + (2 * queue if t == n - 1 else 0)
        )
        violations += queue > 4
        previous = a
    if abs(cost - result.fun) > 1e-5:
        raise ValueError("hindsight objective failed independent replay")
    lower_bound = float(result.mip_dual_bound)
    return {
        "status": int(result.status),
        "solved": True,
        "baseline_cost": baseline,
        "oracle_cost": cost,
        "dual_lower_bound": lower_bound,
        "relative_clairvoyant_gain": (baseline - cost) / baseline,
        "maximum_gain_upper_bound": (baseline - lower_bound) / baseline,
        "constraint_violations": int(violations),
        "actions": actions.tolist(),
        "oracle_is_not_deployable": True,
    }
