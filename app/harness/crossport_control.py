"""Small CPU Double-DQN and causal service proxy. No equipment dispatch."""

from __future__ import annotations

import copy
import math
import statistics
from dataclasses import dataclass

from app.harness.crossport_forecast import predict

FACTORS = (0.65, 0.85, 1.0, 1.15, 1.35)
FEATURES = 25
HISTORY_DAYS = 42


class ServiceEpisode:
    def __init__(self, records, forecast, *, days=90, scenario="normal"):
        if len(records) != days + HISTORY_DAYS:
            raise ValueError("episode requires contiguous observed history and exact horizon")
        self.records = records
        self.forecast = forecast
        self.days = days
        self.scenario = scenario
        self.scale = max(1.0, statistics.mean(v for _, v in records[8:36]))
        self.index = HISTORY_DAYS
        self.backlog = 0.0
        self.previous_action = 2
        self.integral = 0.0
        self.previous_error = 0.0
        self.total_cost = 0.0
        self.violations = 0
        self.mass_error = 0.0
        self.frames = []

    def history(self):
        lag = 14 if self.scenario == "publication_delay" else 7
        # Initial history is 35 days; under 14-day lag the first observation has 22 days.
        history = self.records[: self.index - lag + 1]
        return history, lag

    def context(self):
        history, lag = self.history()
        day = self.records[self.index][0]
        demand = predict(self.forecast, history, day)
        error = self.backlog / self.scale - 0.2 + (demand / self.scale - 1.0) * 0.5
        integral = max(-4.0, min(4.0, self.integral + error))
        derivative = error - self.previous_error
        command = 0.85 * error + 0.06 * integral + 0.12 * derivative
        pid = min(range(5), key=lambda a: abs(FACTORS[a] - max(0.65, min(1.35, 1.0 + 0.22 * command))))
        availability = 0.5 if self.scenario == "resource_outage" and 30 <= self.index - HISTORY_DAYS < 44 else 1.0
        mask = [a <= 2 or availability >= 0.75 for a in range(5)]
        if not mask[pid]:
            pid = 2
        return history, lag, demand, error, integral, pid, availability, mask

    def features(self):
        history, lag, demand, error, integral, pid, availability, mask = self.context()
        past = [v / self.scale for _, v in history[-7:]]
        day = self.records[self.index][0]
        vector = [
            self.backlog / self.scale,
            *past,
            demand / self.scale,
            statistics.pstdev(v for _, v in history[-min(28, len(history)) :]) / self.scale,
            math.sin(day.weekday() * 2 * math.pi / 7),
            math.cos(day.weekday() * 2 * math.pi / 7),
            integral / 4,
            self.previous_error,
            *[float(self.previous_action == a) for a in range(5)],
            (self.days - (self.index - HISTORY_DAYS)) / self.days,
            availability,
            lag / 14,
            pid / 4,
            error,
            self.scale / 150,
        ]
        if len(vector) != FEATURES:
            raise ValueError("Markov feature contract mismatch")
        return [max(-8.0, min(8.0, v)) for v in vector], mask, pid

    def step(self, action):
        _, lag, forecast, error, integral, pid, availability, mask = self.context()
        if action not in range(5) or not mask[action]:
            raise ValueError("unsafe or unregistered capacity action")
        day, actual = self.records[self.index]
        if self.scenario == "demand_surge" and 20 <= self.index - HISTORY_DAYS < 50:
            actual *= 1.5
        before = self.backlog
        capacity = self.scale * FACTORS[action] * availability
        served = min(before + actual, capacity)
        self.backlog = before + actual - served
        mass_error = abs(before + actual - served - self.backlog)
        backlog_ratio = self.backlog / self.scale
        overflow = max(0.0, backlog_ratio - 4.0)
        resource_cost = 0.5 * FACTORS[action] ** 2
        change_cost = 0.05 * abs(FACTORS[action] - FACTORS[self.previous_action])
        terminal = 2.0 * backlog_ratio if self.index - HISTORY_DAYS + 1 == self.days else 0.0
        cost = backlog_ratio + resource_cost + change_cost + overflow * 5.0 + terminal
        violations = int(overflow > 0)
        self.violations += violations
        self.total_cost += cost
        self.mass_error = max(self.mass_error, mass_error)
        self.integral = integral
        self.previous_error = error
        self.previous_action = action
        self.frames.append(
            {
                "date": day.isoformat(),
                "public_latest_day": self.records[self.index - lag][0].isoformat(),
                "action": action,
                "pid_action": pid,
                "arrival_indicator": actual,
                "service_proxy": served,
                "backlog_proxy": self.backlog,
                "cost_proxy": cost,
                "resource_cost_proxy": resource_cost,
                "flow_balance_error": mass_error,
                "declared_availability": availability,
                "constraint_violation": violations > 0,
            }
        )
        self.index += 1
        done = self.index >= len(self.records)
        return -cost, done


def mpc_action(env):
    _, _, forecast, _, _, _, availability, mask = env.context()

    # Three-step deterministic search uses only the current causal forecast, never future actual rows.
    def search(backlog, previous, depth):
        best = (float("inf"), 2)
        for a, allowed in enumerate(mask):
            if not allowed:
                continue
            end = max(0.0, backlog + forecast - env.scale * FACTORS[a] * availability)
            ratio = end / env.scale
            cost = (
                ratio + 0.5 * FACTORS[a] ** 2 + 0.05 * abs(FACTORS[a] - FACTORS[previous]) + max(0.0, ratio - 4.0) * 5
            )
            if depth > 1:
                cost += 0.97 * search(end, a, depth - 1)[0]
            if cost < best[0]:
                best = (cost, a)
        return best

    return search(env.backlog, env.previous_action, 3)[1]


class Network:
    def __init__(self, rng, residual=False):
        import numpy as np

        self.params = [rng.normal(0, 0.12, (FEATURES, 32)), np.zeros(32), rng.normal(0, 0.05, (32, 5)), np.zeros(5)]
        if residual:
            self.params[3][2] = 0.2
        self.m = [np.zeros_like(p) for p in self.params]
        self.v = [np.zeros_like(p) for p in self.params]
        self.updates = 0

    def forward(self, x):
        import numpy as np

        w, b, v, c = self.params
        return np.maximum(0, x @ w + b) @ v + c

    def fit(self, x, actions, targets):
        import numpy as np

        w, b, v, c = self.params
        z = x @ w + b
        h = np.maximum(0, z)
        q = h @ v + c
        grad = np.zeros_like(q)
        grad[np.arange(len(x)), actions] = np.clip(q[np.arange(len(x)), actions] - targets, -1, 1) / len(x)
        dz = (grad @ v.T) * (z > 0)
        gradients = [x.T @ dz, dz.sum(axis=0), h.T @ grad, grad.sum(axis=0)]
        norm = math.sqrt(sum(float((g * g).sum()) for g in gradients))
        self.updates += 1
        for i, g in enumerate(gradients):
            g = g * min(1.0, 5.0 / max(1e-9, norm))
            self.m[i] = 0.9 * self.m[i] + 0.1 * g
            self.v[i] = 0.999 * self.v[i] + 0.001 * g * g
            self.params[i] -= (
                0.0008 * (self.m[i] / (1 - 0.9**self.updates)) / (np.sqrt(self.v[i] / (1 - 0.999**self.updates)) + 1e-8)
            )

    def payload(self):
        return [p.tolist() for p in self.params]


@dataclass
class Policy:
    name: str
    network: object = None
    residual: bool = False
    seed: int = 0

    def action(self, env):
        import numpy as np

        f, mask, pid = env.features()
        if self.name == "pid":
            return pid, False
        if self.name == "mpc":
            return mpc_action(env), False
        if self.name == "balanced":
            return 2, False
        if self.name == "max_capacity":
            return max(a for a, ok in enumerate(mask) if ok), False
        # Read-only shadow fallback is disclosed; it is not counted as a learned action.
        if self.residual and (env.context()[1] != 7 or max(abs(v) for v in f[:10]) > 4.0):
            return pid, True
        q = self.network.forward(np.asarray(f))
        actions = [max(0, min(4, pid + a - 2)) if self.residual else a for a in range(5)]
        allowed = [i for i, a in enumerate(actions) if mask[a]]
        chosen = max(allowed, key=lambda i: q[i])
        return actions[chosen], False


def train_policy(name, segments, forecast, seed, steps=20000, cancelled=lambda: False):
    import numpy as np

    rng = np.random.default_rng(seed)
    residual = name == "residual_double_dqn"
    online = Network(rng, residual)
    target = copy.deepcopy(online)
    replay = []
    curve = []
    env = None
    episode_reward = 0.0
    episode_count = 0
    for step in range(steps):
        if step % 128 == 0 and cancelled():
            raise InterruptedError("cross-port training cancelled or budget exceeded")
        if env is None:
            env = ServiceEpisode(segments[int(rng.integers(len(segments)))], forecast)
            episode_reward = 0.0
        f, mask, pid = env.features()
        mapped = [max(0, min(4, pid + a - 2)) if residual else a for a in range(5)]
        allowed = [i for i, a in enumerate(mapped) if mask[a]]
        epsilon = max(0.05, 1.0 - step / (steps * 0.8))
        action = (
            int(rng.choice(allowed))
            if rng.random() < epsilon
            else max(allowed, key=lambda a: online.forward(np.asarray(f))[a])
        )
        reward, done = env.step(mapped[action])
        episode_reward += reward
        if done:
            f2 = [0.0] * FEATURES
            mask2 = [True] * 5
        else:
            f2, actual_mask, pid2 = env.features()
            mapped2 = [max(0, min(4, pid2 + a - 2)) if residual else a for a in range(5)]
            mask2 = [actual_mask[a] for a in mapped2]
        replay.append((f, action, max(-40.0, reward), f2, done, mask2))
        if len(replay) > 20000:
            replay.pop(0)
        if len(replay) >= 256 and step % 4 == 0:
            batch = [replay[i] for i in rng.integers(len(replay), size=64)]
            x = np.asarray([r[0] for r in batch])
            nx = np.asarray([r[3] for r in batch])
            valid = np.asarray([r[5] for r in batch])
            greedy = np.argmax(np.where(valid, online.forward(nx), -1e9), axis=1)
            boot = target.forward(nx)[np.arange(64), greedy]
            targets = (
                np.asarray([r[2] for r in batch]) + 0.97 * (1 - np.asarray([r[4] for r in batch], dtype=float)) * boot
            )
            online.fit(x, np.asarray([r[1] for r in batch]), np.clip(targets, -300, 20))
        if step % 250 == 0:
            target = copy.deepcopy(online)
        if done:
            episode_count += 1
            curve.append({"episode": episode_count, "step": step + 1, "reward": episode_reward, "epsilon": epsilon})
            env = None
    return Policy(name, online, residual, seed), curve


def evaluate(policy, records, forecast, scenario="normal"):
    env = ServiceEpisode(records, forecast, scenario=scenario)
    fallback = 0
    for _ in range(env.days):
        action, abstained = policy.action(env)
        fallback += abstained
        env.step(action)
    return {
        "score": -env.total_cost / env.days,
        "mean_cost_proxy": env.total_cost / env.days,
        "constraint_violations": env.violations,
        "maximum_flow_balance_error": env.mass_error,
        "fallback_fraction": fallback / env.days,
        "learned_action_fraction": 1 - fallback / env.days if policy.network else 0.0,
        "mean_backlog_proxy": statistics.mean(f["backlog_proxy"] / env.scale for f in env.frames),
        "mean_resource_cost_proxy": statistics.mean(f["resource_cost_proxy"] for f in env.frames),
        "action_differs_from_pid_fraction": statistics.mean(f["action"] != f["pid_action"] for f in env.frames),
        "frames": env.frames,
    }
