"""Causal censored-observation belief and offline stochastic Bellman control."""

import argparse
import csv
import gzip
import json
import math
import statistics
import time
from datetime import date
from pathlib import Path

import numpy as np
from scipy.special import ndtr

from app.harness import crossport_v2 as c
from app.harness import robust_v4 as legacy
from app.harness import modelbased_v3 as planners

DATA = c.BASE_DIR / "data/public/rl_v6_20261030"
OUT = c.BASE_DIR / ".runtime/rl-v6-20261030"
PUB = np.array([0.0, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0])
INNOVATION = np.array([-1.0, -0.5, -0.2, 0.0, 0.2, 0.5, 1.0, 2.0])
VOL = np.array([0.025, 0.1, 0.3, 0.7, 1.5])
QUEUE = np.arange(0, 16.00001, 0.1)
FACTORS = np.asarray(c.old.FACTORS)
EDGES = np.array([0.0, 0.025, 0.10, 0.25, 0.75, 0.90, 0.975, 1.0])
WEIGHTS = np.diff(EDGES)


def censored_mean(mean, sigma, upper):
    """E[D | 0<=D<=upper] under the explicitly assumed normal observation model."""
    mean, sigma, upper = np.broadcast_arrays(np.asarray(mean), np.maximum(1e-9, sigma), np.maximum(0.0, upper))
    a, b = -mean / sigma, (upper - mean) / sigma
    z = ndtr(b) - ndtr(a)
    pa, pb = np.exp(-0.5 * a * a) / math.sqrt(2 * math.pi), np.exp(-0.5 * b * b) / math.sqrt(2 * math.pi)
    value = mean + sigma * (pa - pb) / np.maximum(1e-12, z)
    rare = (z < 1e-10) & (upper > 1e-9)
    if np.any(rare):
        from scipy.stats import truncnorm

        value = np.array(value, copy=True)
        value[rare] = truncnorm.mean(a[rare], b[rare], loc=mean[rare], scale=sigma[rare])
    return np.minimum(upper, np.maximum(0.0, np.where(upper <= 1e-9, 0.0, value)))


class Episode(c.Episode):
    def __init__(self, records, forecast, scenario="normal", gains=(0.2, 0.02, 0.02), alpha=0.5, phi=0.5):
        super().__init__(records, forecast, scenario, gains)
        history, _ = self.history()
        self.scale = max(1.0, statistics.mean(v for _, v in history[-28:]))
        self.scale_latest_day = history[-1][0]
        self.alpha, self.phi, self.innovation = alpha, phi, 0.0
        self.pending_note = {}
        self.public_forecast = None

    def context(self):
        if self.cache is not None:
            return self.cache
        history, lag = self.history()
        public = c.forecasting.predict(self.forecast, history, self.records[self.index][0])
        demand = max(0.0, public + self.phi * self.innovation)
        error = self.backlog / self.scale - 0.2 + (demand / self.scale - 1) * 0.5
        integral = max(-4.0, min(4.0, self.integral + error))
        kp, ki, kd = self.gains
        command = np.clip(1 + kp * error + ki * integral + kd * (error - self.previous_error), 0.65, 1.35)
        availability = 0.5 if self.scenario == "resource_outage" and 30 <= self.index - 42 < 44 else 1.0
        mask = [a <= 2 or availability >= 0.75 for a in range(5)]
        pid = min((a for a in range(5) if mask[a]), key=lambda a: abs(FACTORS[a] - command))
        self.public_forecast = public
        self.cache = history, lag, demand, error, integral, pid, availability, mask
        return self.cache

    def step(self, action):
        history, _, mean, _, _, _, availability, _ = self.context()
        public = self.public_forecast
        before, day, innovation = self.backlog, self.records[self.index][0], self.innovation
        sigma = c.uncertainty_scale(history)
        capacity = self.scale * FACTORS[action] * availability
        note = dict(self.pending_note)
        result = super().step(action)
        if self.backlog > 1e-9:
            posterior = max(0.0, self.backlog - before + capacity)
            kind = "saturated_queue_flow_identity"
            upper = None
        else:
            upper = max(0.0, capacity - before)
            posterior = float(censored_mean(mean, sigma, upper))
            kind = "censored_normal_posterior_not_a_point_observation"
        self.innovation = (1 - self.alpha) * innovation + self.alpha * (posterior - public)
        self.frames[-1].update(
            public_forecast_proxy=public,
            causal_belief_proxy=mean,
            belief_input_innovation=innovation,
            posterior_arrival_estimate=posterior,
            posterior_empty_queue_upper_bound=upper,
            posterior_kind=kind,
            capacity_scale_input_latest_day=self.scale_latest_day.isoformat(),
            latest_queue_observation_day=day.isoformat(),
            local_queue_observation_assumed=True,
            **note,
        )
        self.pending_note = {}
        return result


def load_development():
    series, sources = {}, []
    for folder in [
        "portwatch_crossport_20261030",
        "portwatch_v2_20261030",
        "portwatch_v3_20261030",
        "portwatch_v4_20261030",
        "operations_v5_20261030",
    ]:
        manifest_path = c.BASE_DIR / "data/public" / folder / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest["entries"]:
            path = c.BASE_DIR / entry["path"]
            if c.sha(path) != entry["sha256"]:
                raise ValueError("development public data changed")
            with path.open() as handle:
                records = [(date.fromisoformat(r["date"]), float(r["portcalls"])) for r in csv.DictReader(handle)]
            old = dict(series.get(entry["id"], []))
            if any(day in old and abs(old[day] - value) > 1e-9 for day, value in records):
                raise ValueError("conflicting primary vintages")
            if len(records) > len(series.get(entry["id"], [])):
                series[entry["id"]] = records
        sources.append({"path": str(manifest_path.relative_to(c.BASE_DIR)), "sha256": c.sha(manifest_path)})
    return series, sources


class Controller:
    def __init__(self, raw, guard, gains, alpha=0.5, phi=0.5, noise_mean=0.0):
        self.raw, self.guard, self.gains = raw, guard, gains
        self.alpha, self.phi, self.noise_mean = alpha, phi, noise_mean
        self.seed = getattr(raw, "seed", 0)
        self.name = raw.name + "." + guard["name"]

    def action(self, env):
        raw = int(self.raw.action(env))
        _, _, mean, _, _, _, availability, mask = env.context()
        action = raw
        if self.guard["name"] != "none":
            sigma = c.uncertainty_scale(env.context()[0])
            upper = max(0.0, mean + self.guard["sigma"] * sigma)
            choices = [
                a
                for a in range(5)
                if mask[a]
                and max(0.0, env.backlog + upper - env.scale * FACTORS[a] * availability)
                <= self.guard["queue_budget"] * env.scale
            ]
            action = max(raw, min(choices)) if choices else max(a for a in range(5) if mask[a])
        env.pending_note = {
            "raw_learned_or_baseline_action": raw,
            "safety_override": bool(raw != action),
            "safety_filter": self.guard["name"],
        }
        return int(action)


def evaluate(policy, window, forecast, scenario="normal", keep=False):
    env = Episode(window["records"], forecast, scenario, policy.gains, policy.alpha, policy.phi)
    timings = []
    done = False
    while not done:
        started = time.perf_counter()
        action = policy.action(env)
        timings.append(time.perf_counter() - started)
        _, done = env.step(action)
    row = {
        "algorithm": policy.name,
        "seed": policy.seed,
        "port_id": window["port_id"],
        "window": window["id"],
        "start": window["start"],
        "scenario": scenario,
        "score": -env.total_cost / 90,
        "constraint_violations": env.violations,
        "maximum_flow_error": env.mass_error,
        "safety_override_fraction": statistics.mean(f["safety_override"] for f in env.frames),
        "policy_latency_p50_ms": float(np.quantile(timings, 0.5) * 1000),
        "policy_latency_p95_ms": float(np.quantile(timings, 0.95) * 1000),
        "evaluation_mpc_fallback": False,
        "production_authority": False,
    }
    if keep:
        row["frames"] = env.frames
    return row


def pilot():
    """Development only. Inspect shared belief/filter effects before new-port scoring."""
    OUT.mkdir(exist_ok=True)
    target = OUT / "pilot.json"
    if target.exists():
        raise ValueError("pilot results immutable")
    series, sources = load_development()
    selection = json.loads((legacy.OUT / "selection-before-test.json").read_text())
    forecast, gains = selection["forecast"]["selected"], tuple(selection["gains"])
    ports = ["port1201", "port1114", "port664", "port729", "port1160", "port1417", "port776", "port220"]
    windows, excluded = c.windows(series, ports, [2025], [1, 7])
    guards = [
        {"name": "none", "sigma": 0.0, "queue_budget": 4.0},
        {"name": "old_reserve", "sigma": 1.0, "queue_budget": 0.0},
        {"name": "budget0.5", "sigma": 1.0, "queue_budget": 0.5},
        {"name": "budget1", "sigma": 1.0, "queue_budget": 1.0},
        {"name": "budget2", "sigma": 2.0, "queue_budget": 2.0},
    ]
    rows, aggregates = [], []
    maximum = Controller(c.Policy("max_capacity", gains=gains), guards[0], gains)
    floor = {
        (w["id"], s): evaluate(maximum, w, forecast, s)["constraint_violations"] for w in windows for s in c.SCENARIOS
    }
    for alpha, phi in [(0.0, 0.0), (0.5, 0.5), (0.5, 0.9), (1.0, 0.9)]:
        for guard in guards:
            policy = Controller(planners.MPC(14, 0.0, gains), guard, gains, alpha, phi)
            result = [evaluate(policy, w, forecast, s) for w in windows for s in c.SCENARIOS]
            aggregate = {
                "alpha": alpha,
                "phi": phi,
                "guard": guard,
                "normal_score": statistics.mean(r["score"] for r in result if r["scenario"] == "normal"),
                "feasible_window_violations": sum(
                    r["constraint_violations"] for r in result if floor[r["window"], r["scenario"]] == 0
                ),
                "excess_violations_over_max_capacity": sum(
                    r["constraint_violations"] - floor[r["window"], r["scenario"]] for r in result
                ),
            }
            aggregates.append(aggregate)
            rows.extend({**r, "alpha": alpha, "phi": phi} for r in result)
            print("V6_PILOT", aggregate, flush=True)
    c.write(
        target,
        {
            "sources": sources,
            "development_ports": ports,
            "year": 2025,
            "aggregates": aggregates,
            "runs": rows,
            "excluded": excluded,
            "fresh_test_labels_used": False,
            "notice": "Shared MPC development pilot, not a new held-out result or trained RL advantage. All methods will share the selected observation and filter contract.",
        },
    )


class FrozenPolicy:
    """Frozen model-based RL actor; no teacher or planner is called here."""

    def __init__(self, thresholds, seed, horizon=90):
        self.thresholds, self.seed, self.horizon = thresholds, seed, horizon
        self.name = "offline_rl90" if horizon == 90 else "stochastic_mpc28"

    def action(self, env):
        history, _, demand, _, _, _, availability, mask = env.context()
        q, mean = env.backlog / env.scale, demand / env.scale
        if mean > legacy.DEMAND[-1] or q > legacy.QUEUE[-1]:
            return max(a for a in range(5) if mask[a])
        di = float(np.clip((mean - 0.4) / 0.05, 0, len(legacy.DEMAND) - 1))
        vi = float(np.interp(c.uncertainty_scale(history) / env.scale, legacy.VOL, np.arange(len(legacy.VOL))))
        remaining = 90 - (env.index - 42)
        depth = remaining - 1 if self.horizon == 90 or remaining <= 28 else 90
        boundaries = np.zeros(4)
        for d, dw in [(int(di), 1 - di % 1), (min(int(di) + 1, len(legacy.DEMAND) - 1), di % 1)]:
            for v, vw in [(int(vi), 1 - vi % 1), (min(int(vi) + 1, len(legacy.VOL) - 1), vi % 1)]:
                boundaries += dw * vw * self.thresholds[d, v, int(availability >= 0.75), depth, env.previous_action]
        return min(int(np.sum(q + 1e-10 >= boundaries)), max(a for a in range(5) if mask[a]))


class CorrectedMPC(planners.MPC):
    def __init__(self, horizon, gains, noise):
        super().__init__(horizon, 0.0, gains)
        self.name = f"mean_corrected_mpc{horizon}"
        self.noise = noise

    def action(self, env):
        h, _, mean, _, _, _, avail, _ = env.context()
        sigma = c.uncertainty_scale(h)
        vi = int(np.argmin(abs(legacy.VOL - sigma / env.scale)))
        corrected = max(0.0, mean + sigma * self.noise[vi])
        q = planners.deterministic_q(round(corrected / env.scale * 20), avail, 90 - (env.index - 42), self.horizon, 0)
        return int(
            np.argmin(
                [np.interp(min(env.backlog / env.scale, 40), c.GRID, q[:, env.previous_action, a]) for a in range(5)]
            )
        )


def bellman(centroids):
    """Exact remaining-time tables plus a28step stochastic receding-horizon baseline."""
    dg, vg, qg = legacy.DEMAND, legacy.VOL, legacy.QUEUE
    table = np.empty((len(dg), len(vg), 2, 91, 5, 4), dtype=np.float32)
    projected = decisions = 0

    def boundaries(q):
        nonlocal projected, decisions
        actions = q.argmin(axis=2).T
        monotone = np.maximum.accumulate(actions, axis=1)
        projected += int(np.sum(actions != monotone))
        decisions += actions.size
        b = np.full((5, 4), 999.0, dtype=np.float32)
        for prev in range(5):
            for action in range(1, 5):
                found = np.flatnonzero(monotone[prev] >= action)
                if len(found):
                    b[prev, action - 1] = qg[found[0]]
        return b

    for di, mean in enumerate(dg):
        for vi, vol in enumerate(vg):
            arrivals = np.maximum(0.0, mean + vol * centroids[vi])
            for ai, avail in enumerate([0.5, 1.0]):
                ends = [np.maximum(0, qg[:, None] + arrivals - FACTORS[a] * avail) for a in range(5)]
                positions = [np.clip(e / 0.025, 0, len(qg) - 1) for e in ends]
                indices = [p.astype(int) for p in positions]
                weights = [p - ix for p, ix in zip(positions, indices)]
                immediate = [e + 0.5 * FACTORS[a] ** 2 + 5 * np.maximum(0, e - 4) for a, e in enumerate(ends)]
                for terminal, maximum in [(True, 90), (False, 28)]:
                    value = np.zeros((len(qg), 5))
                    for depth in range(1, maximum + 1):
                        q = np.empty((len(qg), 5, 5))
                        for a in range(5):
                            ix, w = indices[a], weights[a]
                            cont = (1 - w) * value[ix, a] + w * value[np.minimum(ix + 1, len(qg) - 1), a]
                            cont += np.maximum(0, ends[a] - qg[-1]) * 6 * (depth - 1)
                            cost = immediate[a] + cont + (2 * ends[a] if terminal and depth == 1 else 0)
                            q[:, :, a] = (cost @ WEIGHTS)[:, None] + 0.05 * abs(FACTORS - FACTORS[a])[None, :]
                            if avail < 0.75 and a > 2:
                                q[:, :, a] = 1e12
                        value = q.min(axis=2)
                        if terminal:
                            table[di, vi, ai, depth - 1] = boundaries(q)
                        elif depth == 28:
                            table[di, vi, ai, 90] = boundaries(q)
        if di % 8 == 0:
            print("V6_BELLMAN", round(float(mean), 2), flush=True)
    return table, {"monotone_projection_changed_decisions": projected, "grid_decisions": decisions}


def bin_centroids(values):
    """Probability-bin means retain the empirical tails, not truncated point quantiles."""
    values = np.sort(np.asarray(values))
    bins = [
        values[int(a * len(values)) : max(int(a * len(values)) + 1, int(b * len(values)))]
        for a, b in zip(EDGES[:-1], EDGES[1:])
    ]
    return [float(np.mean(v)) for v in bins]


def develop():
    if (OUT / "selection-before-test.json").exists():
        raise ValueError("selection immutable")
    plan = json.loads((DATA / "protocol.json").read_text())
    series, sources = load_development()
    forecast = c.fit_forecast(series, plan["train_ports"])
    gains = tuple(json.loads((legacy.OUT / "selection-before-test.json").read_text())["gains"])
    train, excluded = c.windows(series, plan["train_ports"], plan["train_years"], plan["train_months"])
    validation, _ = c.windows(series, plan["train_ports"], [2025], plan["validation_months"])
    blocks = {}
    for w in train:
        block = [[] for _ in legacy.VOL]
        for scenario in c.SCENARIOS:
            env = Episode(w["records"], forecast["selected"], scenario, gains, 0, 0)
            for _ in range(90):
                h, _, mean, _, _, _, _, mask = env.context()
                sigma = c.uncertainty_scale(h)
                actual = env.records[env.index][1]
                if scenario == "demand_surge" and 20 <= env.index - 42 < 50:
                    actual *= 1.5
                vi = int(np.argmin(abs(legacy.VOL - sigma / env.scale)))
                block[vi].append((actual - mean) / sigma)
                env.step(int(np.flatnonzero(mask)[len(np.flatnonzero(mask)) // 2]))
        key = f"{w['port_id']}.{w['start'][:4]}"
        if key not in blocks:
            blocks[key] = [[] for _ in legacy.VOL]
        for i, values in enumerate(block):
            blocks[key][i].extend(values)
    keys = sorted(blocks)
    all_values = [[v for key in keys for v in blocks[key][i]] for i in range(len(legacy.VOL))]
    global_values = [v for group in all_values for v in group]
    pooled = np.asarray([bin_centroids(v if len(v) >= 500 else global_values) for v in all_values])
    empirical = {
        "interactions": len(global_values),
        "blocks": len(keys),
        "by_volatility_n": [len(v) for v in all_values],
        "bin_edges": EDGES.tolist(),
        "probability_weights": WEIGHTS.tolist(),
        "pooled_centroids": pooled.tolist(),
        "training_ports": plan["train_ports"],
        "training_years": plan["train_years"],
        "all_four_scenarios": True,
        "test_labels_used": False,
    }
    c.write(OUT / "empirical-transition-model.json", empirical)
    models, rows = [], []
    guard = plan["shared_filter"]
    for seed in plan["seeds"]:
        rng = np.random.default_rng(seed)
        sample = rng.choice(keys, len(keys), replace=True)
        vals = [[v for key in sample for v in blocks[key][i]] for i in range(len(legacy.VOL))]
        global_sample = [v for group in vals for v in group]
        centroids = np.asarray([bin_centroids(v if len(v) >= 500 else global_sample) for v in vals])
        table, info = bellman(centroids)
        path = OUT / f"actor-{seed}.npz"
        np.savez_compressed(path, thresholds=table)
        models.append(
            {
                "seed": seed,
                "path": str(path.relative_to(c.BASE_DIR)),
                "sha256": c.sha(path),
                "centroids": centroids.tolist(),
                "bootstrap_block_counts": dict(__import__("collections").Counter(sample)),
                **info,
            }
        )
        for horizon in [90, 28]:
            policy = Controller(FrozenPolicy(table, seed, horizon), guard, gains, 0, 0)
            rows.extend(evaluate(policy, w, forecast["selected"], s) for w in validation for s in c.SCENARIOS)
        print("V6_MODEL_VALIDATED", seed, flush=True)
    for h in [14, 28, 90]:
        for risk in [0.0, 0.5]:
            p = Controller(planners.MPC(h, risk, gains), guard, gains, 0, 0)
            rows.extend(evaluate(p, w, forecast["selected"], s) for w in validation for s in c.SCENARIOS)
    for h in [28, 90]:
        p = Controller(CorrectedMPC(h, gains, pooled @ WEIGHTS), guard, gains, 0, 0)
        rows.extend(evaluate(p, w, forecast["selected"], s) for w in validation for s in c.SCENARIOS)
    maximum = Controller(c.Policy("max_capacity", gains=gains), guard, gains, 0, 0)
    floors = {
        (w["id"], s): evaluate(maximum, w, forecast["selected"], s)["constraint_violations"]
        for w in validation
        for s in c.SCENARIOS
    }
    summary = []
    for name in sorted({r["algorithm"] for r in rows}):
        own = [r for r in rows if r["algorithm"] == name]
        summary.append(
            {
                "algorithm": name,
                "normal_score": statistics.mean(r["score"] for r in own if r["scenario"] == "normal"),
                "feasible_violations": sum(
                    r["constraint_violations"] for r in own if floors[r["window"], r["scenario"]] == 0
                ),
                "excess_over_maximum": sum(r["constraint_violations"] - floors[r["window"], r["scenario"]] for r in own)
                / (5 if name.startswith(("offline_rl", "stochastic")) else 1),
            }
        )
    baselines = [r for r in summary if not r["algorithm"].startswith("offline_rl")]
    cost = max(baselines, key=lambda r: r["normal_score"])
    safe = min(baselines, key=lambda r: (r["feasible_violations"], r["excess_over_maximum"], -r["normal_score"]))
    c.write(
        OUT / "selection-before-test.json",
        {
            "schema": "xiaoyi-control-selection.v6",
            "frozen_at": time.time(),
            "source_sha256": c.sha(Path(__file__)),
            "protocol_sha256": c.sha(DATA / "protocol.json"),
            "pilot_sha256": c.sha(OUT / "pilot.json"),
            "empirical_model_sha256": c.sha(OUT / "empirical-transition-model.json"),
            "sources": sources,
            "base_sources": c.sources(),
            "forecast": forecast,
            "gains": gains,
            "models": models,
            "validation_summary": summary,
            "validation_rows": rows,
            "selected_rl": "offline_rl90.old_reserve",
            "selected_cost_baseline": cost["algorithm"],
            "selected_safe_baseline": safe["algorithm"],
            "excluded_training_windows": excluded,
            "test_labels_used": False,
            "production_authority": False,
        },
    )
    print("V6_SELECTION_FROZEN", summary, flush=True)


def assess():
    if (OUT / "report.json").exists():
        raise ValueError("never overwrite a viewed holdout")
    selection = json.loads((OUT / "selection-before-test.json").read_text())
    if (
        c.sha(Path(__file__)) != selection["source_sha256"]
        or c.sha(DATA / "protocol.json") != selection["protocol_sha256"]
    ):
        raise ValueError("selection implementation/protocol changed")
    manifest = json.loads((DATA / "manifest.json").read_text())
    if manifest["protocol_sha256"] != selection["protocol_sha256"]:
        raise ValueError("source extraction not bound to registered plan")
    series = {}
    for e in manifest["entries"]:
        path = c.BASE_DIR / e["path"]
        if c.sha(path) != e["sha256"]:
            raise ValueError("public held-out data changed")
        with path.open() as handle:
            series[e["id"]] = [(date.fromisoformat(r["date"]), float(r["portcalls"])) for r in csv.DictReader(handle)]
    plan = json.loads((DATA / "protocol.json").read_text())
    windows, excluded = c.windows(series, list(series), [plan["test_year"]], plan["test_months"])
    empirical = json.loads((OUT / "empirical-transition-model.json").read_text())
    if c.sha(OUT / "empirical-transition-model.json") != selection["empirical_model_sha256"]:
        raise ValueError("training uncertainty changed")
    gains, guard = tuple(selection["gains"]), plan["shared_filter"]
    policies = []
    for meta in selection["models"]:
        path = c.BASE_DIR / meta["path"]
        if c.sha(path) != meta["sha256"]:
            raise ValueError("frozen actor changed")
        table = np.load(path)["thresholds"]
        policies += [
            Controller(FrozenPolicy(table, meta["seed"], h), g, gains, 0, 0) for h in [90, 28] for g in [guard]
        ]
        policies.append(
            Controller(FrozenPolicy(table, meta["seed"]), {"name": "none", "sigma": 0, "queue_budget": 4}, gains, 0, 0)
        )
    for h in [14, 28, 90]:
        policies += [Controller(planners.MPC(h, r, gains), guard, gains, 0, 0) for r in [0.0, 0.5]]
    for h in [28, 90]:
        policies.append(
            Controller(CorrectedMPC(h, gains, np.asarray(empirical["pooled_centroids"]) @ WEIGHTS), guard, gains, 0, 0)
        )
    policies += [Controller(c.Policy(name, gains=gains), guard, gains, 0, 0) for name in ["pid_tuned", "max_capacity"]]
    rows, trace = [], OUT / "trajectories.jsonl.gz"
    with gzip.open(trace, "wt") as handle:
        for p in policies:
            for w in windows:
                for scenario in c.SCENARIOS:
                    row = evaluate(p, w, selection["forecast"]["selected"], scenario, True)
                    handle.write(json.dumps(row, allow_nan=False) + "\n")
                    rows.append({k: v for k, v in row.items() if k != "frames"})
            print("V6_NEW_PORT_TEST", p.name, p.seed, flush=True)

    def averages(name):
        out = {}
        for r in rows:
            if r["algorithm"] == name:
                out.setdefault((r["window"], r["scenario"]), []).append(r)
        return {
            k: {
                "score": statistics.mean(r["score"] for r in rs),
                "violations": max(r["constraint_violations"] for r in rs),
            }
            for k, rs in out.items()
        }

    base = averages(selection["selected_cost_baseline"])
    safe = averages(selection["selected_safe_baseline"])
    floor = averages("max_capacity.old_reserve")
    aggregate = []
    for name in sorted({r["algorithm"] for r in rows}):
        means = averages(name)
        paired, per_port = {}, []
        for port in series:
            changes = [
                (means[w["id"], "normal"]["score"] - base[w["id"], "normal"]["score"])
                / abs(base[w["id"], "normal"]["score"])
                for w in windows
                if w["port_id"] == port
            ]
            paired[port] = changes
            per_port.append({"port_id": port, "relative_cost_improvement_pct": statistics.mean(changes) * 100})
        interval = c.clustered_interval(paired)
        positive = [max(0.0, r["relative_cost_improvement_pct"]) for r in per_port]
        concentration = max(positive) / sum(positive) if sum(positive) > 1e-12 else None
        stress = [
            {
                "scenario": s,
                "mean_relative_cost_improvement_pct": statistics.mean(
                    (means[w["id"], s]["score"] - base[w["id"], s]["score"]) / abs(base[w["id"], s]["score"])
                    for w in windows
                )
                * 100,
            }
            for s in c.SCENARIOS[1:]
        ]
        own = [r for r in rows if r["algorithm"] == name]
        feasible = [r for r in own if floor[r["window"], r["scenario"]]["violations"] == 0]
        excess = sum(max(0, r["constraint_violations"] - floor[r["window"], r["scenario"]]["violations"]) for r in own)
        checks = {
            "selected_rl": name == selection["selected_rl"],
            "positive_port_cluster_ci": interval["port_cluster_ci95"][0] > 0,
            "no_mean_port_regression": min(r["relative_cost_improvement_pct"] for r in per_port) >= -1e-9,
            "stress_noninferiority": all(r["mean_relative_cost_improvement_pct"] >= -1e-9 for r in stress),
            "no_feasible_window_violation": all(r["constraint_violations"] == 0 for r in feasible),
            "no_excess_over_max_capacity": excess == 0,
            "gain_not_concentrated": concentration is not None and concentration <= 0.5,
        }
        aggregate.append(
            {
                "algorithm": name,
                "normal_mean_score": statistics.mean(r["score"] for r in own if r["scenario"] == "normal"),
                "new_port_relative_cost_interval": interval,
                "per_port": per_port,
                "positive_gain_max_port_share": concentration,
                "stress": stress,
                "all_constraint_violations": sum(r["constraint_violations"] for r in own),
                "feasible_constraint_violations": sum(r["constraint_violations"] for r in feasible),
                "excess_over_max_capacity": excess,
                "safe_baseline_mean_score_delta": statistics.mean(
                    means[w["id"], "normal"]["score"] - safe[w["id"], "normal"]["score"] for w in windows
                ),
                "checks": checks,
                "research_admission": all(checks.values()),
                "blockers": [k for k, v in checks.items() if not v],
            }
        )
    c.write(
        OUT / "report.json",
        {
            "schema": "xiaoyi-offline-control-report.v6",
            "selection": selection,
            "selection_sha256": c.sha(OUT / "selection-before-test.json"),
            "protocol": plan,
            "sources": manifest,
            "windows": [{k: v for k, v in w.items() if k != "records"} for w in windows],
            "excluded_windows": excluded,
            "aggregate": aggregate,
            "runs": rows,
            "trace_path": str(trace.relative_to(c.BASE_DIR)),
            "trace_sha256": c.sha(trace),
            "notice": "Five port-year bootstrap fits are not five independent ports. CI clusters eight fresh ports after averaging seeds. Original physical cost and common safety filter; raw runs retained separately. Any all-port shocks, proxy physics and publication-time assumptions limit inference. No test retuning, no MPC fallback, no production authority.",
            "production_authority": False,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["pilot", "develop", "assess"])
    phase = parser.parse_args().phase
    {"pilot": pilot, "develop": develop, "assess": assess}[phase]()
