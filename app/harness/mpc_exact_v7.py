"""Compress the exact interpolated five-action MPC lower envelope, without imitation."""

from functools import lru_cache

import numpy as np

from app.harness import crossport_v2 as c

FACTORS = np.asarray(c.old.FACTORS)


def envelope(costs):
    """Exact argmin envelope of linearly interpolated grid costs; no action projection."""
    chosen = costs.argmin(axis=1)
    starts, actions = [0.0], [int(chosen[0])]
    for i in np.flatnonzero(chosen[1:] != chosen[:-1]):
        lo, hi = costs[i], costs[i + 1]
        crossings = [0.0, 1.0]
        for a in range(5):
            for b in range(a):
                slope = (hi[a] - lo[a]) - (hi[b] - lo[b])
                if abs(slope) > 1e-12:
                    point = (lo[b] - lo[a]) / slope
                    if 0 < point < 1:
                        crossings.append(float(point))
        crossings = sorted(set(crossings))
        for left, right in zip(crossings[:-1], crossings[1:]):
            fraction = (left + right) / 2
            action = int(np.argmin(lo + fraction * (hi - lo)))
            at = float(c.GRID[i] + left * 0.1)
            if action != actions[-1]:
                starts.append(at)
                actions.append(action)
        if int(chosen[i + 1]) != actions[-1]:
            starts.append(float(c.GRID[i + 1]))
            actions.append(int(chosen[i + 1]))
    return np.asarray(starts), np.asarray(actions)


@lru_cache(maxsize=512)
def policies(mean_bin, availability):
    """Same recurrence, reward, terminal cost, grid and tail as V3's deterministic MPC."""
    mean = mean_bin / 20
    endings = [np.maximum(0, c.GRID + mean - factor * availability) for factor in FACTORS]
    immediate = [e + 0.5 * FACTORS[a] ** 2 + 5 * np.maximum(0, e - 4) for a, e in enumerate(endings)]
    result = {}
    for terminal, maximum in [(True, 90), (False, 28)]:
        values = np.zeros((len(c.GRID), 5))
        for depth in range(1, maximum + 1):
            q = np.empty((len(c.GRID), 5, 5))
            for a, end in enumerate(endings):
                cont = np.interp(np.minimum(end, c.GRID[-1]), c.GRID, values[:, a]) + np.maximum(
                    0, end - c.GRID[-1]
                ) * 6 * (depth - 1)
                costs = immediate[a] + cont + (2 * end if terminal and depth == 1 else 0)
                q[:, :, a] = costs[:, None] + 0.05 * abs(FACTORS - FACTORS[a])[None, :]
                if availability < 0.75 and a > 2:
                    q[:, :, a] = 1e12
            values = q.min(axis=2)
            if terminal or depth == 28:
                result[terminal, depth] = [envelope(q[:, prev, :]) for prev in range(5)]
    return result


def action(mean_bin, availability, remaining, horizon, backlog, previous):
    terminal = remaining <= horizon
    depth = min(remaining, horizon)
    starts, choices = policies(mean_bin, availability)[terminal, depth][previous]
    q = min(backlog, 40)
    position = int(np.searchsorted(starts, q, side="right") - 1)
    if position and abs(starts[position] - q) < 1e-9:
        return int(min(choices[position - 1], choices[position]))
    return int(choices[position])


class MPC:
    def __init__(self, horizon, risk, gains, means=None, name=None):
        self.horizon, self.risk, self.gains, self.means = horizon, risk, gains, means
        self.name, self.seed = name or f"mpc{horizon}_r{risk}", 0

    def action(self, env):
        history, lag, mean, _, _, _, avail, _ = env.context()
        sigma = c.uncertainty_scale(history) / env.scale
        model_mean = 0.0
        if self.means is not None:
            from app.harness.rl_v7 import VOL

            vi = int(np.argmin(abs(VOL - sigma)))
            model_mean = sigma * self.means[int(lag == 14), vi]
        mean_bin = round(max(0, mean / env.scale + model_mean) * 20) + round(self.risk * sigma * 20)
        return action(
            mean_bin, avail, 90 - (env.index - 42), self.horizon, env.backlog / env.scale, env.previous_action
        )
