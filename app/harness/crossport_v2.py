"""New port/year holdouts, stronger planners and separately disclosed MPC-guided RL."""

import csv
import gzip
import hashlib
import json
import math
import random
import statistics
import time
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.config import BASE_DIR
from app.harness import crossport_control as old, crossport_forecast as forecasting
from app.harness.crossport_benchmark import clustered_interval

FOLDER = BASE_DIR / "data/public/portwatch_v2_20261030"
OUT = BASE_DIR / ".runtime/crossport-v2-20261030"
SCENARIOS = ["normal", "demand_surge", "resource_outage", "publication_delay"]
SEEDS = [32101, 32102, 32103, 32104, 32105]
STEPS = 40000


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def sources():
    paths = [
        Path(__file__),
        Path(old.__file__),
        Path(forecasting.__file__),
        BASE_DIR / "app/harness/crossport_benchmark.py",
        FOLDER / "protocol.json",
        FOLDER / "manifest.json",
    ]
    return {str(p.relative_to(BASE_DIR)): sha(p) for p in paths}


def load():
    manifest = json.loads((FOLDER / "manifest.json").read_text())
    if manifest["protocol_sha256"] != sha(FOLDER / "protocol.json"):
        raise ValueError("new cohort protocol changed")
    if sha(BASE_DIR / manifest["primary_export"]["path"]) != manifest["primary_export"]["sha256"]:
        raise ValueError("primary published CSV changed")
    series = {}
    for entry in manifest["entries"]:
        path = BASE_DIR / entry["path"]
        if sha(path) != entry["sha256"]:
            raise ValueError("new cohort CSV changed")
        with path.open() as handle:
            rows = list(csv.DictReader(handle))
        values = [(date.fromisoformat(r["date"]), float(r["portcalls"])) for r in rows]
        if len(set(d for d, v in values)) != len(values) or any(
            not math.isfinite(v) or v < 0 or v != int(v) for d, v in values
        ):
            raise ValueError("invalid source dates/counts")
        series[entry["id"]] = values
    return manifest, series


def windows(series, ports, years, months):
    included, excluded = [], []
    for port in ports:
        mapping = dict(series[port])
        for year in years:
            for month in months:
                start = date(year, month, 1)
                dates = [start + timedelta(days=i) for i in range(-42, 90)]
                identity = {"port_id": port, "start": start.isoformat(), "id": f"{port}.{year}.{month:02}"}
                if any(d not in mapping for d in dates):
                    excluded.append({**identity, "reason": "source period unavailable; no fabricated filling"})
                else:
                    included.append({**identity, "records": [(d, mapping[d]) for d in dates]})
    return included, excluded


def uncertainty_scale(history):
    values = [v for d, v in history[-28:]]
    return max(1.0, statistics.pstdev(values), math.sqrt(max(1.0, statistics.mean(values))))


def fit_forecast(series, train_ports):
    rows = {p: [{"date": d, "calls": v} for d, v in r] for p, r in series.items()}
    train = [e for p in train_ports for e in forecasting.examples(rows[p], 2019, 2024)]
    validation = [e for p in train_ports for e in forecasting.examples(rows[p], 2025, 2025)]
    features, targets = zip(*[(forecasting.vector(h, d)[0], a / forecasting.vector(h, d)[1]) for h, d, a in train])
    x, y = np.asarray(features), np.asarray(targets)
    penalty = np.eye(x.shape[1]) * 0.1
    penalty[0, 0] = 0
    coef = np.linalg.solve(x.T @ x + penalty, x.T @ y).tolist()
    models = [{"kind": k} for k in ["lagged_persistence", "weekday_mean", "mean7"]] + [
        {"kind": "ridge_ar7", "coefficients": coef}
    ]
    metrics = [
        {
            "kind": m["kind"],
            "validation_mae": statistics.mean(abs(forecasting.predict(m, h, d) - a) for h, d, a in validation),
        }
        for m in models
    ]
    selected = min(models, key=lambda m: next(r["validation_mae"] for r in metrics if r["kind"] == m["kind"]))
    residuals = sorted(abs(forecasting.predict(selected, h, d) - a) / uncertainty_scale(h) for h, d, a in validation)
    radius = residuals[min(len(residuals) - 1, math.ceil((len(residuals) + 1) * 0.95) - 1)]
    return {
        "selected": selected,
        "candidates": metrics,
        "interval_multiplier": radius,
        "fit_ports": train_ports,
        "fit_years": [2019, 2024],
        "validation_year": 2025,
        "interval": "95% validation residual quantile scaled by causal trailing variability/Poisson floor; no test-port labels used; serial dependence limits coverage guarantees",
    }


class Episode(old.ServiceEpisode):
    def __init__(self, records, forecast, scenario="normal", gains=(0.2, 0.02, 0.02)):
        super().__init__(records, forecast, scenario=scenario)
        self.gains = gains
        self.cache = None

    def history(self):
        history, lag = super().history()
        # Synthetic demand shock becomes observable only after the same public lag.
        if self.scenario == "demand_surge":
            first = self.records[42][0]
            history = [(d, v * (1.5 if 20 <= (d - first).days < 50 else 1)) for d, v in history]
        return history, lag

    def context(self):
        if self.cache is not None:
            return self.cache
        history, lag, demand, error, integral, _, availability, mask = super().context()
        kp, ki, kd = self.gains
        command = max(0.65, min(1.35, 1 + kp * error + ki * integral + kd * (error - self.previous_error)))
        pid = min((a for a in range(5) if mask[a]), key=lambda a: abs(old.FACTORS[a] - command))
        self.cache = history, lag, demand, error, integral, pid, availability, mask
        return self.cache

    def features(self):
        values, mask, pid = super().features()
        values[0] = math.log1p(self.backlog / self.scale) / 3
        values[13] = math.atan(self.previous_error) / math.pi
        values[23] = math.atan(self.context()[3]) / math.pi
        return values, mask, pid

    def step(self, action):
        result = super().step(action)
        self.cache = None
        return result


GRID = np.arange(0, 40.0001, 0.1)


@lru_cache(maxsize=2048)
def planner_values(demand_bin, availability, remaining, robust_bin=0):
    """Vectorized deterministic DP MPC; five actions and previous-action switching cost."""
    demand = demand_bin / 20 + robust_bin / 20
    factors = np.asarray(old.FACTORS)
    values = np.zeros((len(GRID), 5))
    horizon = min(14, remaining)
    q = None
    for depth in range(1, horizon + 1):
        q = np.empty((len(GRID), 5, 5))
        for a in range(5):
            end = np.maximum(0, GRID + demand - factors[a] * availability)
            immediate = end + 0.5 * factors[a] ** 2 + np.maximum(0, end - 4) * 5
            if depth == 1 and remaining <= 14:
                immediate = immediate + 2 * end
            continuation = np.interp(np.minimum(end, GRID[-1]), GRID, values[:, a])
            # Positive tail slope prevents clipping a very large queue into a cheap state.
            continuation += np.maximum(0, end - GRID[-1]) * 6 * (depth - 1)
            q[:, :, a] = immediate[:, None] + continuation[:, None] + 0.05 * np.abs(factors - factors[a])[None, :]
            if availability < 0.75 and a > 2:
                q[:, :, a] = 1e12
        values = q.min(axis=2)
    return q


def mpc_q(env, robust=0):
    h, _, demand, _, _, _, availability, _ = env.context()
    uncertainty = uncertainty_scale(h) / env.scale
    q = planner_values(
        round(demand / env.scale * 20),
        availability,
        min(14, env.days - (env.index - 42)),
        round(robust * uncertainty * 20),
    )
    return np.asarray(
        [np.interp(min(env.backlog / env.scale, 40), GRID, q[:, env.previous_action, a]) for a in range(5)]
    )


class Policy:
    def __init__(self, name, network=None, seed=0, gains=(0.2, 0.02, 0.02), robust=0):
        self.name, self.network, self.seed, self.gains, self.robust = name, network, seed, gains, robust

    def action(self, env):
        features, mask, pid = env.features()
        if self.name == "pid_tuned":
            return pid
        if self.name == "mpc3":
            return old.mpc_action(env)
        if self.name in {"mpc14", "robust_mpc14"}:
            return int(np.argmin(mpc_q(env, self.robust)))
        if self.name == "max_capacity":
            return max(a for a in range(5) if mask[a])
        if self.name == "balanced":
            return 2
        q = self.network.forward(np.asarray(features))
        return max((a for a in range(5) if mask[a]), key=lambda a: q[a])


def evaluate(policy, window, forecast, scenario="normal", keep=False):
    env = Episode(window["records"], forecast, scenario, policy.gains)
    start = time.perf_counter()
    done = False
    while not done:
        _, done = env.step(policy.action(env))
    result = {
        "algorithm": policy.name,
        "seed": policy.seed,
        "port_id": window["port_id"],
        "window": window["id"],
        "start": window["start"],
        "scenario": scenario,
        "score": -env.total_cost / 90,
        "constraint_violations": env.violations,
        "maximum_flow_error": env.mass_error,
        "inference_ms_per_step": (time.perf_counter() - start) * 1000 / 90,
        "fallback_fraction": 0.0,
    }
    if keep:
        result["frames"] = env.frames
    return result


def teacher_data(windows, forecast, gains, seed=32100, samples=3000):
    rng = np.random.default_rng(seed)
    x, y = [], []
    env = None
    for _ in range(samples):
        if env is None:
            w = windows[int(rng.integers(len(windows)))]
            env = Episode(w["records"], forecast, SCENARIOS[int(rng.integers(4))], gains)
        f, mask, _ = env.features()
        q = mpc_q(env)
        x.append(f)
        y.append((-np.minimum(q, 2000) / 10).tolist())
        action = int(rng.choice([a for a in range(5) if mask[a]])) if rng.random() < 0.2 else int(np.argmin(q))
        if env.step(action)[1]:
            env = None
    return np.asarray(x), np.asarray(y)


def train(name, windows, forecast, gains, seed, teacher, steps=STEPS):
    rng = np.random.default_rng(seed)
    net = old.Network(rng)
    guided = name == "mpc_guided_double_dqn"
    imitation = None
    if guided:
        x, y = teacher
        for _ in range(1500):
            indices = rng.integers(len(x), size=64)
            actions = rng.integers(5, size=64)
            net.fit(x[indices], actions, y[indices, actions])
        imitation = old.Network(np.random.default_rng(seed))
        imitation.params = [p.copy() for p in net.params]
    target = old.Network(np.random.default_rng(seed))
    target.params = [p.copy() for p in net.params]
    replay = [None] * 30000
    size, position = 0, 0
    env = None
    curve = []
    episode_reward = 0
    for step in range(steps):
        if env is None:
            scenario = SCENARIOS[int(rng.integers(4))] if step >= 3000 else "normal"
            env = Episode(windows[int(rng.integers(len(windows)))]["records"], forecast, scenario, gains)
            episode_reward = 0
        f, mask, _ = env.features()
        epsilon = max(0.05, (0.35 if guided else 1) * (1 - step / (steps * 0.8)))
        allowed = [a for a in range(5) if mask[a]]
        action = (
            int(rng.choice(allowed))
            if rng.random() < epsilon
            else max(allowed, key=lambda a: net.forward(np.asarray(f))[a])
        )
        reward, done = env.step(action)
        episode_reward += reward
        if done:
            next_f, next_mask = [0.0] * 25, [True] * 5
        else:
            next_f, next_mask, _ = env.features()
        replay[position] = (f, action, reward / 10, next_f, done, next_mask)
        position = (position + 1) % len(replay)
        size = min(size + 1, len(replay))
        if size >= 256 and step % 4 == 0:
            batch = [replay[i] for i in rng.integers(size, size=64)]
            x = np.asarray([r[0] for r in batch])
            nx = np.asarray([r[3] for r in batch])
            valid = np.asarray([r[5] for r in batch])
            greedy = np.argmax(np.where(valid, net.forward(nx), -1e12), axis=1)
            boot = target.forward(nx)[np.arange(64), greedy]
            targets = np.asarray([r[2] for r in batch]) + (1 - np.asarray([r[4] for r in batch], dtype=float)) * boot
            net.fit(x, np.asarray([r[1] for r in batch]), targets)  # full cost, gamma=1, no reward/target clipping
        if step % 250 == 0:
            target.params = [p.copy() for p in net.params]
        if done:
            curve.append(
                {
                    "step": step + 1,
                    "episode_reward_original_scale": episode_reward,
                    "scenario": env.scenario,
                    "epsilon": epsilon,
                }
            )
            env = None
    return (
        Policy(name, net, seed, gains),
        Policy("mpc_imitation_only", imitation, seed, gains) if guided else None,
        curve,
    )


def develop(steps=STEPS):
    if (OUT / "selection-before-test.json").exists():
        raise ValueError("development already frozen; preserve original selection")
    OUT.mkdir(parents=True, exist_ok=True)
    manifest, series = load()
    plan = json.loads((FOLDER / "protocol.json").read_text())
    train_windows, excluded = windows(series, plan["train_ports"], plan["training_years"], [1, 4, 7, 10])
    validation, val_excluded = windows(series, plan["train_ports"], [2025], [1, 4, 7, 10])
    forecast = fit_forecast(series, plan["train_ports"])
    write(
        OUT / "frozen-execution.json",
        {
            "source_hashes": sources(),
            "steps": steps,
            "seeds": SEEDS,
            "protocol": plan,
            "changes_from_v1": [
                "shock-adjusted public observations appear only after lag",
                "log backlog observation preserves large-queue information",
                "scenario-balanced RL training",
                "gamma=1 and positive-linear reward scaling, no clipping",
                "PID validation tuning and longer/robust MPC",
                "MPC pretraining explicitly compared to imitation-only",
            ],
            "excluded_training": excluded + val_excluded,
            "started_at": time.time(),
        },
    )
    options = []
    for kp in [0.15, 0.3, 0.6]:
        for ki in [0.01, 0.05]:
            for kd in [0.0, 0.1]:
                p = Policy("pid_tuned", gains=(kp, ki, kd))
                options.append(
                    {
                        "gains": list(p.gains),
                        "score": statistics.mean(evaluate(p, w, forecast["selected"])["score"] for w in validation),
                    }
                )
    gains = tuple(max(options, key=lambda r: r["score"])["gains"])
    policies = [
        Policy("pid_tuned", gains=gains),
        Policy("mpc3", gains=gains),
        Policy("mpc14", gains=gains),
        Policy("robust_mpc14", gains=gains, robust=0.5),
        Policy("max_capacity", gains=gains),
        Policy("balanced", gains=gains),
    ]
    teacher = teacher_data(train_windows, forecast["selected"], gains)
    models, curves = [], {}
    for name in ["balanced_double_dqn", "mpc_guided_double_dqn"]:
        for seed in SEEDS:
            print("training", name, seed, flush=True)
            p, imitation, curve = train(name, train_windows, forecast["selected"], gains, seed, teacher, steps)
            for policy in [p] + ([imitation] if imitation else []):
                path = OUT / "models" / f"{policy.name}-{seed}.json"
                write(
                    path,
                    {
                        "name": policy.name,
                        "seed": seed,
                        "params": policy.network.payload(),
                        "gains": gains,
                        "rl_steps": 0 if policy.name == "mpc_imitation_only" else steps,
                        "imitation_updates": 1500 if name == "mpc_guided_double_dqn" else 0,
                        "rl_updates": policy.network.updates - (1500 if name == "mpc_guided_double_dqn" else 0)
                        if policy.name != "mpc_imitation_only"
                        else 0,
                    },
                )
                models.append(
                    {"name": policy.name, "seed": seed, "path": str(path.relative_to(BASE_DIR)), "sha256": sha(path)}
                )
                policies.append(policy)
            curves[f"{name}.{seed}"] = curve
    validation_rows = [evaluate(p, w, forecast["selected"]) for p in policies for w in validation]
    means = {
        name: statistics.mean(r["score"] for r in validation_rows if r["algorithm"] == name)
        for name in {p.name for p in policies}
    }
    strong = max(["pid_tuned", "mpc3", "mpc14", "robust_mpc14"], key=lambda n: means[n])
    selected_rl = max(["balanced_double_dqn", "mpc_guided_double_dqn"], key=lambda n: means[n])
    selection = {
        "source_hashes": sources(),
        "frozen_before_test_at": time.time(),
        "forecast": forecast,
        "gains": gains,
        "pid_search": options,
        "models": models,
        "curves": curves,
        "validation_rows": validation_rows,
        "validation_means": means,
        "selected_baseline": strong,
        "selected_rl": selected_rl,
        "steps": steps,
        "test_labels_used_for_selection": False,
        "production_authority": False,
    }
    write(OUT / "selection-before-test.json", selection)
    print("validation selection", strong, selected_rl, means, flush=True)
    return selection


def restore(meta):
    payload = json.loads((BASE_DIR / meta["path"]).read_text())
    if sha(BASE_DIR / meta["path"]) != meta["sha256"]:
        raise ValueError("trained policy changed")
    net = old.Network(np.random.default_rng(payload["seed"]))
    net.params = [np.asarray(p) for p in payload["params"]]
    return Policy(payload["name"], net, payload["seed"], tuple(payload["gains"]))


def assess():
    if (OUT / "report.json").exists():
        raise ValueError("held-out evaluation already viewed; never overwrite")
    selection = json.loads((OUT / "selection-before-test.json").read_text())
    if selection["source_hashes"] != sources():
        raise ValueError("implementation changed after validation selection")
    manifest, series = load()
    plan = json.loads((FOLDER / "protocol.json").read_text())
    test, excluded = windows(series, list(series), [2026], plan["test_quarters"])
    if len(test) < 24 or len({w["port_id"] for w in test}) < 12:
        raise ValueError("fresh year/port source availability insufficient")
    gains = tuple(selection["gains"])
    policies = [
        Policy(n, gains=gains, robust=0.5 if n == "robust_mpc14" else 0)
        for n in ["pid_tuned", "mpc3", "mpc14", "robust_mpc14", "max_capacity", "balanced"]
    ]
    policies += [restore(m) for m in selection["models"]]
    results = []
    trace_path = OUT / "trajectories.jsonl.gz"
    with gzip.open(trace_path, "wt") as handle:
        for p in policies:
            print("fresh test", p.name, p.seed, flush=True)
            for w in test:
                for scenario in SCENARIOS:
                    row = evaluate(p, w, selection["forecast"]["selected"], scenario, True)
                    frames = row.pop("frames")
                    handle.write(json.dumps({**row, "frames": frames}) + "\n")
                    results.append(row)
    reference = selection["selected_baseline"]
    baseline = {(r["window"], r["scenario"]): r for r in results if r["algorithm"] == reference}
    maximum = {(r["window"], r["scenario"]): r for r in results if r["algorithm"] == "max_capacity"}
    aggregate = []
    for name in selection["validation_means"]:
        rows = [r for r in results if r["algorithm"] == name]
        contexts = {}
        for role, ports in [("temporal_holdout", plan["train_ports"]), ("new_whole_port_holdout", plan["fresh_ports"])]:
            paired = {}
            for w in test:
                if w["port_id"] in ports:
                    own = [r["score"] for r in rows if r["window"] == w["id"] and r["scenario"] == "normal"]
                    paired.setdefault(w["port_id"], []).append(
                        statistics.mean(own) - baseline[(w["id"], "normal")]["score"]
                    )
            contexts[role] = clustered_interval(paired)
        stress = [
            {
                "scenario": scenario,
                "mean_delta": statistics.mean(
                    r["score"] - baseline[(r["window"], scenario)]["score"] for r in rows if r["scenario"] == scenario
                ),
            }
            for scenario in SCENARIOS[1:]
        ]
        feasible_rows = [r for r in rows if maximum[(r["window"], r["scenario"])]["constraint_violations"] == 0]
        checks = {
            "rl_candidate": name in ["balanced_double_dqn", "mpc_guided_double_dqn"],
            "selected_on_validation": name == selection["selected_rl"],
            "both_holdouts_improve": all(c["port_cluster_ci95"][0] > 0 for c in contexts.values()),
            "no_port_regression": all(c["worst_port_mean_delta"] >= 0 for c in contexts.values()),
            "no_feasible_window_violation": all(r["constraint_violations"] == 0 for r in feasible_rows),
            "stress_noninferiority": all(r["mean_delta"] >= 0 for r in stress),
        }
        aggregate.append(
            {
                "algorithm": name,
                "validation_score": selection["validation_means"][name],
                "test_score": statistics.mean(r["score"] for r in rows if r["scenario"] == "normal"),
                "mean_inference_ms_per_step": statistics.mean(r["inference_ms_per_step"] for r in rows),
                "contexts": contexts,
                "stress": stress,
                "feasible_constraint_violations": sum(r["constraint_violations"] for r in feasible_rows),
                "all_constraint_violations": sum(r["constraint_violations"] for r in rows),
                "checks": checks,
                "blockers": [k for k, v in checks.items() if not v],
                "research_admission": all(checks.values()),
                "production_admission": False,
            }
        )
    forecast_results = []
    for pid, records in series.items():
        errors, persistence, coverage, widths = [], [], [], []
        pairs = forecasting.examples([{"date": d, "calls": v} for d, v in records], 2026, 2026)
        for history, target, actual in pairs:
            estimate = forecasting.predict(selection["forecast"]["selected"], history, target)
            radius = selection["forecast"]["interval_multiplier"] * uncertainty_scale(history)
            errors.append(abs(estimate - actual))
            persistence.append(abs(history[-1][1] - actual))
            coverage.append(max(0, estimate - radius) <= actual <= estimate + radius)
            widths.append(estimate + radius - max(0, estimate - radius))
        checks = {
            "n_at_least_180": len(errors) >= 180,
            "beats_persistence": statistics.mean(errors) <= statistics.mean(persistence),
            "coverage_at_least_80pct": statistics.mean(coverage) >= 0.8,
            "width_at_most_4_times_mean_indicator": statistics.mean(widths)
            <= 4 * statistics.mean(v for d, v in records if d.year == 2026),
        }
        forecast_results.append(
            {
                "port_id": pid,
                "n": len(errors),
                "mae": statistics.mean(errors),
                "persistence_mae": statistics.mean(persistence),
                "coverage": statistics.mean(coverage),
                "mean_width": statistics.mean(widths),
                "checks": checks,
                "passed": all(checks.values()),
            }
        )
    value = {
        "schema": "xiaoyi-independent-crossport-study.v2",
        "sources": manifest,
        "protocol": plan,
        "selection": selection,
        "selection_sha256": sha(OUT / "selection-before-test.json"),
        "test_windows": [{k: v for k, v in w.items() if k != "records"} for w in test],
        "excluded_test_windows": excluded,
        "aggregate": aggregate,
        "runs": results,
        "demand_forecast": forecast_results,
        "trace_path": str(trace_path.relative_to(BASE_DIR)),
        "trace_sha256": sha(trace_path),
        "production_authority": False,
        "notice": "2026新时期与八个新港口独立留出；公开源缺失季度排除且列明。MPC引导预训练、纯模仿及后续RL分别比较，没有在线MPC回退冒充RL。故障下不可行队列继续阻断现场准入。",
    }
    write(OUT / "report.json", value)
    return value


def report():
    load()  # all registered raw/derived source checks remain mandatory at readback
    value = json.loads((OUT / "report.json").read_text())
    issues = []
    if value["selection"]["source_hashes"] != sources():
        issues.append("source implementation/cohort drift")
    if (
        sha(OUT / "selection-before-test.json") != value["selection_sha256"]
        or sha(BASE_DIR / value["trace_path"]) != value["trace_sha256"]
    ):
        issues.append("selection/trajectory drift")
    for m in value["selection"]["models"]:
        if sha(BASE_DIR / m["path"]) != m["sha256"]:
            issues.append("model drift")
    value["historical_only"] = bool(issues)
    value["current_validation_issues"] = issues
    return value
