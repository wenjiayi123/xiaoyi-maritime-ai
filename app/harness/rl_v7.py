"""Lag-conditional normal-data offline RL, risk ablation and fair raw baselines."""

import argparse
import csv
import gzip
import json
import statistics
import time
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

from app.harness import rl_v6 as old, mpc_exact_v7 as mpc

c = old.c
DATA = c.BASE_DIR / "data/public/rl_v7_20261031"
OUT = c.BASE_DIR / ".runtime/rl-v7-20261031"
MEAN = np.arange(0, 4.00001, 0.1)
VOL = np.asarray([0.025, 0.1, 0.3, 0.6, 1.2, 2.4])
QUEUE = np.arange(0, 16.00001, 0.05)
WEIGHTS = old.WEIGHTS
FACTORS = old.FACTORS


def load_development():
    series, sources = old.load_development()
    path = c.BASE_DIR / "data/public/rl_v6_20261030/manifest.json"
    manifest = json.loads(path.read_text())
    for e in manifest["entries"]:
        p = c.BASE_DIR / e["path"]
        if c.sha(p) != e["sha256"]:
            raise ValueError("viewed development source changed")
        with p.open() as f:
            series[e["id"]] = [(date.fromisoformat(r["date"]), float(r["portcalls"])) for r in csv.DictReader(f)]
    return series, [*sources, {"path": str(path.relative_to(c.BASE_DIR)), "sha256": c.sha(path)}]


def sources():
    paths = [Path(__file__), Path(mpc.__file__), Path(old.__file__), DATA / "protocol.json"]
    return {str(p.relative_to(c.BASE_DIR)): c.sha(p) for p in paths}


class Actor:
    def __init__(self, table, name, seed=0, horizon=90):
        self.table, self.seed, self.horizon = table, seed, horizon
        self.name = name if horizon == 90 else name + ".stochastic28"
        self.outside = False

    def action(self, env):
        h, lag, mean, _, _, _, avail, mask = env.context()
        mean, queue = mean / env.scale, env.backlog / env.scale
        self.outside = mean > MEAN[-1] or queue > QUEUE[-1]
        if self.outside:
            return max(a for a in range(5) if mask[a])
        di = float(np.interp(mean, MEAN, np.arange(len(MEAN))))
        vi = float(np.interp(c.uncertainty_scale(h) / env.scale, VOL, np.arange(len(VOL))))
        remaining = 90 - (env.index - 42)
        depth = remaining - 1 if self.horizon == 90 or remaining <= 28 else 90
        bounds = np.zeros(4)
        for d, dw in [(int(di), 1 - di % 1), (min(int(di) + 1, len(MEAN) - 1), di % 1)]:
            for v, vw in [(int(vi), 1 - vi % 1), (min(int(vi) + 1, len(VOL) - 1), vi % 1)]:
                bounds += dw * vw * self.table[int(lag == 14), d, v, int(avail >= 0.75), depth, env.previous_action]
        return min(int(np.sum(queue + 1e-10 >= bounds)), max(a for a in range(5) if mask[a]))


class Controller(old.Controller):
    def __init__(self, raw, guard, gains):
        super().__init__(raw, guard, gains, 0, 0)

    def action(self, env):
        a = super().action(env)
        h, _, mean, _, _, _, avail, mask = env.context()
        upper = mean + self.guard["sigma"] * c.uncertainty_scale(h)
        allowed = [
            i
            for i in range(5)
            if mask[i]
            and max(0, env.backlog + upper - env.scale * FACTORS[i] * avail) <= self.guard["queue_budget"] * env.scale
        ]
        env.pending_note.update(
            capacity_scale_proxy=env.scale,
            feasible_filter_action_count=len(allowed),
            learned_grid_extrapolation=bool(getattr(self.raw, "outside", False)),
        )
        return a


def evaluate(policy, window, forecast, scenario="normal", keep=False):
    return old.evaluate(policy, window, forecast, scenario, keep)


def bellman(centroids, penalty):
    """Vectorized over lag/mean/volatility; no evaluation-time planner or teacher."""
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
        ends = [np.maximum(0, QUEUE[None, :, None] + arrivals[:, None, :] - factor * avail) for factor in FACTORS]
        positions = [np.clip(e / 0.05, 0, len(QUEUE) - 1) for e in ends]
        indices = [p.astype(int) for p in positions]
        weights = [p - ix for p, ix in zip(positions, indices)]
        immediate = [
            e + 0.5 * FACTORS[a] ** 2 + 5 * np.maximum(0, e - 4) + penalty * (e > 4) for a, e in enumerate(ends)
        ]
        for terminal, maximum in [(True, 90), (False, 28)]:
            values = np.zeros((n, len(QUEUE), 5))
            for depth in range(1, maximum + 1):
                q = np.empty((n, len(QUEUE), 5, 5))
                for a in range(5):
                    ix, w = indices[a], weights[a]
                    continuation = (1 - w) * values[ni, ix, a] + w * values[ni, np.minimum(ix + 1, len(QUEUE) - 1), a]
                    continuation += np.maximum(0, ends[a] - QUEUE[-1]) * 6 * (depth - 1)
                    cost = immediate[a] + continuation + (2 * ends[a] if terminal and depth == 1 else 0)
                    q[:, :, :, a] = (cost @ WEIGHTS)[:, :, None] + 0.05 * abs(FACTORS - FACTORS[a])[None, None, :]
                    if avail < 0.75 and a > 2:
                        q[:, :, :, a] = 1e12
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
                    print("V7_BELLMAN", penalty, avail, terminal, depth, flush=True)
    return table, {"monotone_projection_changed_decisions": changed, "grid_decisions": decisions}


def empirical(blocks, keys, composition):
    raw = [[[] for _ in VOL] for _ in range(2)]
    for key in keys:
        for mode in range(2):
            for vi in range(len(VOL)):
                raw[mode][vi].extend(blocks[key]["normal"][mode][vi])
                if composition == "mixed" and mode == 0:
                    raw[mode][vi].extend(blocks[key]["normal"][mode][vi])  # original normal+outage duplication
                    raw[mode][vi].extend(blocks[key]["surge"][mode][vi])
    if composition == "normal_pooled":
        raw = [[raw[0][v] + raw[1][v] for v in range(len(VOL))] for _ in range(2)]
    result = np.empty((2, len(VOL), 7))
    for mode in range(2):
        pooled = [x for values in raw[mode] for x in values]
        for vi in range(len(VOL)):
            result[mode, vi] = old.bin_centroids(raw[mode][vi] if len(raw[mode][vi]) >= 500 else pooled)
    return result


def summarize(rows, floor):
    result = []
    for name in sorted({r["algorithm"] for r in rows}):
        own = [r for r in rows if r["algorithm"] == name]
        replicas = len({r["seed"] for r in own})
        result.append(
            {
                "algorithm": name,
                "normal_score": statistics.mean(r["score"] for r in own if r["scenario"] == "normal"),
                "feasible_violations": sum(
                    r["constraint_violations"] for r in own if floor[r["window"], r["scenario"]] == 0
                )
                / replicas,
                "excess_over_maximum": sum(
                    max(0, r["constraint_violations"] - floor[r["window"], r["scenario"]]) for r in own
                )
                / replicas,
                "mean_override": statistics.mean(r["safety_override_fraction"] for r in own),
            }
        )
    return result


def develop():
    OUT.mkdir(exist_ok=True)
    if (OUT / "selection-before-test.json").exists():
        raise ValueError("selection immutable")
    plan = json.loads((DATA / "protocol.json").read_text())
    series, data_sources = load_development()
    forecast = c.fit_forecast(series, plan["train_ports"])
    gains = tuple(json.loads((old.OUT / "selection-before-test.json").read_text())["gains"])
    training, excluded = c.windows(series, plan["train_ports"], plan["train_years"], plan["train_months"])
    validation, _ = c.windows(series, plan["train_ports"], [2025], plan["validation_months"])
    blocks = {}
    interactions = 0
    for window in training:
        key = window["port_id"] + "." + window["start"][:4]
        block = blocks.setdefault(key, {k: [[[] for _ in VOL] for _ in range(2)] for k in ["normal", "surge"]})
        for scenario in ["normal", "publication_delay", "demand_surge"]:
            env = old.Episode(window["records"], forecast["selected"], scenario, gains, 0, 0)
            for _ in range(90):
                h, lag, mean, _, _, _, _, _ = env.context()
                sigma = c.uncertainty_scale(h)
                actual = env.records[env.index][1] * (
                    1.5 if scenario == "demand_surge" and 20 <= env.index - 42 < 50 else 1
                )
                vi = int(np.argmin(abs(VOL - sigma / env.scale)))
                block["surge" if scenario == "demand_surge" else "normal"][int(lag == 14)][vi].append(
                    (actual - mean) / sigma
                )
                env.step(2)
                interactions += 1
    keys = sorted(blocks)
    guards = [plan["raw_filter"], plan["primary_shared_filter"]]
    maxpolicy = Controller(c.Policy("max_capacity", gains=gains), guards[0], gains)
    floor = {
        (w["id"], s): evaluate(maxpolicy, w, forecast["selected"], s)["constraint_violations"]
        for w in validation
        for s in c.SCENARIOS
    }
    rows, candidates = [], []
    for config in plan["configs"]:
        centroids = empirical(blocks, keys, config["composition"])
        table, info = bellman(centroids, config["penalty"])
        path = OUT / (config["name"] + "-pooled.npz")
        np.savez_compressed(path, thresholds=table)
        candidates.append(
            {
                **config,
                "path": str(path.relative_to(c.BASE_DIR)),
                "sha256": c.sha(path),
                "centroids": centroids.tolist(),
                **info,
            }
        )
        for guard in guards:
            policy = Controller(Actor(table, config["name"]), guard, gains)
            rows.extend(evaluate(policy, w, forecast["selected"], s) for w in validation for s in c.SCENARIOS)
        print(
            "V7_CANDIDATE_VALIDATION",
            config["name"],
            summarize([r for r in rows if r["algorithm"].startswith(config["name"] + ".")], floor),
            flush=True,
        )
    candidate_summary = summarize(rows, floor)
    raw = min(
        [r for r in candidate_summary if r["algorithm"].endswith(".none")],
        key=lambda r: (r["feasible_violations"], r["excess_over_maximum"], -r["normal_score"]),
    )
    chosen_config = next(c for c in candidates if c["name"] == raw["algorithm"].split(".")[0])
    models = []
    for seed in plan["seeds"]:
        sample = np.random.default_rng(seed).choice(keys, len(keys), replace=True)
        centroids = empirical(blocks, sample, chosen_config["composition"])
        table, info = bellman(centroids, chosen_config["penalty"])
        path = OUT / f"actor-{seed}.npz"
        np.savez_compressed(path, thresholds=table)
        models.append(
            {
                "seed": seed,
                "name": chosen_config["name"],
                "path": str(path.relative_to(c.BASE_DIR)),
                "sha256": c.sha(path),
                "centroids": centroids.tolist(),
                "bootstrap_blocks": dict(Counter(sample)),
                **info,
            }
        )
    means = np.asarray(chosen_config["centroids"]) @ WEIGHTS
    baselines = [mpc.MPC(h, risk, gains) for h in [28, 90] for risk in [0.0, 0.5]]
    baselines += [mpc.MPC(h, 0, gains, means, f"mean_mpc{h}") for h in [28, 90]]
    table = np.load(c.BASE_DIR / chosen_config["path"])["thresholds"]
    baselines += [Actor(table, "model", 0, 28), c.Policy("pid_tuned", gains=gains)]
    for raw_baseline in baselines:
        for guard in guards:
            policy = Controller(raw_baseline, guard, gains)
            rows.extend(evaluate(policy, w, forecast["selected"], s) for w in validation for s in c.SCENARIOS)
        print("V7_BASELINE_VALIDATED", raw_baseline.name, flush=True)
    summary = summarize(rows, floor)
    names = {b.name for b in baselines}
    selected_base = {}
    for guard in guards:
        pool = [
            r
            for r in summary
            if r["algorithm"].rsplit(".", 1)[0] in names and r["algorithm"].endswith("." + guard["name"])
        ]
        selected_base[guard["name"]] = max(pool, key=lambda r: r["normal_score"])["algorithm"]
    c.write(
        OUT / "selection-before-test.json",
        {
            "schema": "xiaoyi-rl-selection.v7",
            "frozen_at": time.time(),
            "source_hashes": sources(),
            "protocol_sha256": c.sha(DATA / "protocol.json"),
            "development_sources": data_sources,
            "forecast": forecast,
            "gains": gains,
            "candidates": candidates,
            "models": models,
            "chosen_config": chosen_config["name"],
            "selected_raw": chosen_config["name"] + ".none",
            "selected_guarded": chosen_config["name"] + ".reserve",
            "selected_baselines": selected_base,
            "validation_summary": summary,
            "validation_rows": rows,
            "training_interactions_including_ablation": interactions,
            "normal_unique_interactions": sum(len(v) for b in blocks.values() for mode in b["normal"] for v in mode),
            "excluded_training_windows": excluded,
            "test_labels_used": False,
            "production_authority": False,
        },
    )
    print("V7_RL_FROZEN", chosen_config["name"], selected_base, flush=True)


def assess():
    if (OUT / "report.json").exists():
        raise ValueError("never overwrite a viewed holdout")
    sealed = json.loads((OUT / "selection-before-test.json").read_text())
    plan = json.loads((DATA / "protocol.json").read_text())
    if sealed["source_hashes"] != sources():
        raise ValueError("frozen implementations/protocol changed")
    manifest = json.loads((DATA / "manifest.json").read_text())
    series = {}
    for entry in manifest["entries"]:
        p = c.BASE_DIR / entry["path"]
        if c.sha(p) != entry["sha256"]:
            raise ValueError("held-out CSV changed")
        with p.open() as f:
            series[entry["id"]] = [(date.fromisoformat(r["date"]), float(r["portcalls"])) for r in csv.DictReader(f)]
    windows, excluded = c.windows(series, list(series), [2026], plan["test_months"])
    gains = tuple(sealed["gains"])
    guards = [plan["raw_filter"], plan["primary_shared_filter"]]
    policies = []
    for model in sealed["models"]:
        path = c.BASE_DIR / model["path"]
        if c.sha(path) != model["sha256"]:
            raise ValueError("actor changed")
        table = np.load(path)["thresholds"]
        for guard in guards:
            policies += [
                Controller(Actor(table, sealed["chosen_config"], model["seed"]), guard, gains),
                Controller(Actor(table, "model", model["seed"], 28), guard, gains),
            ]
    chosen = next(m for m in sealed["candidates"] if m["name"] == sealed["chosen_config"])
    means = np.asarray(chosen["centroids"]) @ WEIGHTS
    baselines = (
        [mpc.MPC(h, r, gains) for h in [28, 90] for r in [0.0, 0.5]]
        + [mpc.MPC(h, 0.0, gains, means, f"mean_mpc{h}") for h in [28, 90]]
        + [c.Policy(k, gains=gains) for k in ["pid_tuned", "max_capacity"]]
    )
    policies += [Controller(p, g, gains) for p in baselines for g in guards]
    rows = []
    trace = OUT / "trajectories.jsonl.gz"
    with gzip.open(trace, "wt") as handle:
        for policy in policies:
            for window in windows:
                for scenario in c.SCENARIOS:
                    row = evaluate(policy, window, sealed["forecast"]["selected"], scenario, True)
                    handle.write(json.dumps(row, allow_nan=False) + "\n")
                    rows.append({k: v for k, v in row.items() if k != "frames"})
            print("V7_NEW_PORT_SCORED", policy.name, policy.seed, flush=True)

    def average(name):
        grouped = {}
        for r in rows:
            if r["algorithm"] == name:
                grouped.setdefault((r["window"], r["scenario"]), []).append(r)
        return {key: statistics.mean(r["score"] for r in group) for key, group in grouped.items()}

    maximum = {
        (r["window"], r["scenario"]): r["constraint_violations"] for r in rows if r["algorithm"] == "max_capacity.none"
    }
    aggregates = []
    for name in sorted({r["algorithm"] for r in rows}):
        guard = name.rsplit(".", 1)[1]
        base_name = sealed["selected_baselines"][guard]
        own = [r for r in rows if r["algorithm"] == name]
        own_mean, base = average(name), average(base_name)
        paired = {
            p: [
                (own_mean[w["id"], "normal"] - base[w["id"], "normal"]) / abs(base[w["id"], "normal"])
                for w in windows
                if w["port_id"] == p
            ]
            for p in series
        }
        interval = c.clustered_interval(paired)
        positive = [max(0.0, statistics.mean(v)) for v in paired.values()]
        share = max(positive) / sum(positive) if sum(positive) > 1e-12 else None
        stress = [
            {
                "scenario": s,
                "relative_gain": statistics.mean(
                    (own_mean[w["id"], s] - base[w["id"], s]) / abs(base[w["id"], s]) for w in windows
                ),
            }
            for s in c.SCENARIOS[1:]
        ]
        feasible = sum(r["constraint_violations"] for r in own if maximum[r["window"], r["scenario"]] == 0)
        excess = sum(max(0, r["constraint_violations"] - maximum[r["window"], r["scenario"]]) for r in own)
        checks = {
            "selected_candidate": name in [sealed["selected_raw"], sealed["selected_guarded"]],
            "positive_port_cluster_ci": interval["port_cluster_ci95"][0] > 0,
            "no_mean_port_regression": interval["worst_port_mean_delta"] >= -1e-9,
            "stress_noninferiority": all(v["relative_gain"] >= -1e-9 for v in stress),
            "no_feasible_window_violation": feasible == 0,
            "no_excess_over_max_capacity": excess == 0,
            "gain_not_concentrated": share is not None and share <= 0.5,
        }
        aggregates.append(
            {
                "algorithm": name,
                "matched_baseline": base_name,
                "relative_cost_interval": interval,
                "positive_gain_max_port_share": share,
                "stress": stress,
                "all_constraint_violations": sum(r["constraint_violations"] for r in own),
                "feasible_constraint_violations": feasible,
                "excess_over_max_capacity": excess,
                "checks": checks,
                "blockers": [k for k, v in checks.items() if not v],
                "research_admission": all(checks.values()),
                "normal_mean_score": statistics.mean(r["score"] for r in own if r["scenario"] == "normal"),
            }
        )
    c.write(
        OUT / "report.json",
        {
            "schema": "xiaoyi-rl-report.v7",
            "protocol": plan,
            "selection": sealed,
            "selection_sha256": c.sha(OUT / "selection-before-test.json"),
            "sources": manifest,
            "windows": [{k: v for k, v in w.items() if k != "records"} for w in windows],
            "excluded_windows": excluded,
            "aggregate": aggregates,
            "runs": rows,
            "trace_path": str(trace.relative_to(c.BASE_DIR)),
            "trace_sha256": c.sha(trace),
            "notice": "Pre-registered raw-to-raw and guarded-to-guarded comparisons, five block bootstrap fits averaged within eight port clusters. No evaluation-time MPC fallback. Expanded grids/conditional model are approximation changes, not measured port gains. All old V6failures preserved; no production authority.",
            "production_authority": False,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["develop", "assess"])
    {"develop": develop, "assess": assess}[parser.parse_args().phase]()
