"""Empirical Bellman policy that trains with the SAME safety set used at runtime.

This is offline model-based RL, not a neural policy or an operational controller.
The 28-day stochastic MPC comparator receives the same data and safety model.
"""

import numpy as np

from app.harness import rl_v7 as prior

MEAN, VOL, QUEUE = prior.MEAN, prior.VOL, prior.QUEUE
FACTORS, WEIGHTS = prior.FACTORS, prior.WEIGHTS


def allowed_actions(means, volatility, queue, availability):
    capacity = FACTORS * availability
    allowed = queue[..., None] + means[..., None] + volatility[..., None] <= capacity + 1e-12
    maximum = 2 if availability < 0.75 else 4
    allowed[..., maximum + 1 :] = False
    # Same explicit infeasibility fallback as Controller: maximum available.
    allowed[..., maximum] |= ~allowed.any(axis=-1)
    return allowed


def bellman(centroids):
    shape = (2, len(MEAN), len(VOL))
    means = np.broadcast_to(MEAN[None, :, None], shape).reshape(-1)
    vol = np.broadcast_to(VOL[None, None, :], shape).reshape(-1)
    noises = np.broadcast_to(centroids[:, None, :, :], (*shape, 7)).reshape(-1, 7)
    arrivals = np.maximum(0, means[:, None] + vol[:, None] * noises)
    n = len(means)
    ni = np.arange(n)[:, None, None]
    table = np.empty((*shape, 2, 91, 5, 4), dtype=np.float32)
    flat = table.reshape(n, 2, 91, 5, 4)
    changed = decisions = 0
    for ai, avail in enumerate([0.5, 1.0]):
        feasible = allowed_actions(means[:, None], vol[:, None], QUEUE[None, :], avail)
        ends = [np.maximum(0, QUEUE[None, :, None] + arrivals[:, None, :] - factor * avail) for factor in FACTORS]
        positions = [np.clip(e / 0.05, 0, len(QUEUE) - 1) for e in ends]
        indices = [p.astype(int) for p in positions]
        weights = [p - ix for p, ix in zip(positions, indices)]
        immediate = [e + 0.5 * FACTORS[a] ** 2 + 5 * np.maximum(0, e - 4) for a, e in enumerate(ends)]
        for terminal, maximum in [(True, 90), (False, 28)]:
            values = np.zeros((n, len(QUEUE), 5))
            for depth in range(1, maximum + 1):
                q = np.empty((n, len(QUEUE), 5, 5))
                for a in range(5):
                    ix, w = indices[a], weights[a]
                    cont = (1 - w) * values[ni, ix, a] + w * values[ni, np.minimum(ix + 1, len(QUEUE) - 1), a]
                    cont += np.maximum(0, ends[a] - QUEUE[-1]) * 6 * (depth - 1)
                    cost = immediate[a] + cont + (2 * ends[a] if terminal and depth == 1 else 0)
                    q[:, :, :, a] = (cost @ WEIGHTS)[:, :, None] + 0.05 * abs(FACTORS - FACTORS[a])[None, None, :]
                    q[:, :, :, a] = np.where(feasible[:, :, a, None], q[:, :, :, a], 1e12)
                values = q.min(axis=3)
                if terminal or depth == 28:
                    actions = q.argmin(axis=3).transpose(0, 2, 1)
                    monotone = np.maximum.accumulate(actions, axis=2)
                    changed += int(np.sum(monotone != actions))
                    decisions += actions.size
                    for b in range(1, 5):
                        found = monotone >= b
                        flat[:, ai, depth - 1 if terminal else 90, :, b - 1] = np.where(
                            found.any(axis=2), QUEUE[found.argmax(axis=2)], 999.0
                        )
                if depth % 30 == 0:
                    print("CONSTRAINED_BELLMAN", avail, terminal, depth, flush=True)
    return table, {"monotone_projection_changed_decisions": changed, "grid_decisions": decisions}


def admission(checks):
    required = {
        "positive_port_cluster_ci",
        "no_mean_port_regression",
        "stress_noninferiority",
        "no_feasible_window_violation",
        "no_excess_over_max_capacity",
        "gain_not_concentrated",
    }
    return required.issubset(checks) and all(checks[k] is True for k in required)
