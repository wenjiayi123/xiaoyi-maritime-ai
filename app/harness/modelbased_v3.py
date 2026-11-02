"""Offline empirical-model RL with sealed policies and independently tuned MPC baselines."""

import argparse
import csv
import gzip
import json
import statistics
import time
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.harness import crossport_v2 as c
from app.harness import learning_v3 as learning

OUT = c.BASE_DIR / ".runtime/modelbased-v3-20261030"
QUEUE = np.arange(0, 12.00001, .05)
DEMAND = np.arange(.4, 2.00001, .1)
VOLATILITY = np.asarray([.05, .15, .3, .5, .8])
HORIZONS = list(range(1, 15)) + [28, 90]
FACTORS = np.asarray(c.old.FACTORS)


@lru_cache(maxsize=4096)
def deterministic_q(demand_bin, availability, remaining, horizon, robust_bin):
    demand = (demand_bin + robust_bin) / 20
    values = np.zeros((len(c.GRID), 5))
    for depth in range(1, min(horizon, remaining) + 1):
        q = np.empty((len(c.GRID), 5, 5))
        for a in range(5):
            end = np.maximum(0, c.GRID + demand - FACTORS[a] * availability)
            cost = end + .5 * FACTORS[a] ** 2 + np.maximum(0, end - 4) * 5
            if depth == 1 and remaining <= horizon:
                cost += 2 * end
            continuation = np.interp(np.minimum(end, c.GRID[-1]), c.GRID, values[:, a])
            continuation += np.maximum(0, end - c.GRID[-1]) * 6 * (depth - 1)
            q[:, :, a] = cost[:, None] + continuation[:, None] + .05 * np.abs(FACTORS - FACTORS[a])[None, :]
            if availability < .75 and a > 2:
                q[:, :, a] = 1e12
        values = q.min(axis=2)
    return q


class MPC:
    def __init__(self, horizon, robust, gains):
        self.horizon, self.robust, self.gains = horizon, robust, gains
        self.seed = 0
        self.name = f"mpc{horizon}_r{robust}"

    def action(self, env):
        history, _, demand, _, _, _, availability, _ = env.context()
        q = deterministic_q(round(demand / env.scale * 20), availability,
                            90 - (env.index - 42), self.horizon,
                            round(self.robust * c.uncertainty_scale(history) / env.scale * 20))
        return int(np.argmin([np.interp(min(env.backlog / env.scale, 40), c.GRID,
                                      q[:, env.previous_action, a]) for a in range(5)]))


class EmpiricalPolicy:
    def __init__(self, name, values, gains):
        self.name, self.values, self.gains, self.seed = name, values, gains, 0

    def action(self, env):
        history, _, demand, _, _, _, availability, mask = env.context()
        # Pure interpolation of a frozen learned table; no online planning/teacher call.
        di = np.clip((demand / env.scale - .4) / .1, 0, len(DEMAND) - 1)
        lo = int(di)
        hi = min(lo + 1, len(DEMAND) - 1)
        vi = int(np.argmin(abs(VOLATILITY - c.uncertainty_scale(history) / env.scale)))
        ai = int(availability >= .75)
        remaining = 90 - (env.index - 42)
        horizon = remaining if remaining <= 14 else (28 if remaining <= 28 else 90)
        qi = np.clip(env.backlog / env.scale / .05, 0, len(QUEUE) - 1)
        qlo = int(qi)
        qhi = min(qlo + 1, len(QUEUE) - 1)
        ix = (vi, ai, HORIZONS.index(horizon))
        q = sum(weight * self.values[(d, *ix, b, env.previous_action)]
                for d, dw in [(lo, 1 - (di - lo)), (hi, di - lo)]
                for b, bw in [(qlo, 1 - (qi - qlo)), (qhi, qi - qlo)]
                for weight in [dw * bw])
        if env.backlog / env.scale > QUEUE[-1]:
            return max(a for a in range(5) if mask[a])
        return int(np.argmin(np.where(mask, q, 1e12)))


def train_table(quantiles, noise_scale):
    """Bellman backups over known queue mechanics and a training-only empirical arrival model."""
    table = np.empty((len(DEMAND), len(VOLATILITY), 2, len(HORIZONS), len(QUEUE), 5, 5), dtype=np.float32)
    for di, demand in enumerate(DEMAND):
        for vi, vol in enumerate(VOLATILITY):
            arrivals = np.maximum(0, demand + noise_scale * vol * quantiles)
            for ai, availability in enumerate([.5, 1.]):
                endings = [np.maximum(0, QUEUE[:, None] + arrivals - FACTORS[a] * availability) for a in range(5)]
                positions = [np.clip(e / .05, 0, len(QUEUE) - 1) for e in endings]
                indices = [p.astype(int) for p in positions]
                weights = [p - i for p, i in zip(positions, indices)]
                immediate = [e + .5 * FACTORS[a] ** 2 + np.maximum(0, e - 4) * 5 for a, e in enumerate(endings)]
                values = np.zeros((len(QUEUE), 5))
                for depth in range(1, 91):
                    q = np.empty((len(QUEUE), 5, 5))
                    for a in range(5):
                        ix, w = indices[a], weights[a]
                        continuation = (1 - w) * values[ix, a] + w * values[np.minimum(ix + 1, len(QUEUE) - 1), a]
                        continuation += np.maximum(0, endings[a] - QUEUE[-1]) * 6 * (depth - 1)
                        cost = immediate[a] + continuation + (2 * endings[a] if depth == 1 else 0)
                        q[:, :, a] = cost.mean(axis=1)[:, None] + .05 * np.abs(FACTORS - FACTORS[a])[None, :]
                        if availability < .75 and a > 2:
                            q[:, :, a] = 1e9
                    values = q.min(axis=2)
                    if depth in HORIZONS:
                        # Action advantages remove a large common value and retain float32 resolution.
                        table[di, vi, ai, HORIZONS.index(depth)] = q - q.min(axis=2, keepdims=True)
        print("BELLMAN", noise_scale, round(float(demand), 2), flush=True)
    return table


def develop():
    if (OUT / "selection-before-test.json").exists():
        raise ValueError("selection already sealed")
    OUT.mkdir(parents=True, exist_ok=True)
    original = json.loads((c.OUT / "selection-before-test.json").read_text())
    _, series = c.load()
    plan = json.loads((learning.DATA / "protocol.json").read_text())
    train, _ = c.windows(series, plan["train_ports"], plan["training_years"], [1, 4, 7, 10])
    validation, _ = c.windows(series, plan["train_ports"], [2025], [1, 4, 7, 10])
    forecast, gains = original["forecast"]["selected"], tuple(original["gains"])
    residuals = []
    for window in train:
        env = c.Episode(window["records"], forecast, gains=gains)
        for _ in range(90):
            history, _, demand, *_ = env.context()
            actual = env.records[env.index][1]
            residuals.append((actual - demand) / c.uncertainty_scale(history))
            env.step(2)
    quantiles = np.quantile(residuals, [.05, .2, .35, .5, .65, .8, .95])
    c.write(OUT / "empirical-transition-model.json", {"training_residuals": len(residuals),
            "standardized_error_quantiles": quantiles.tolist(), "training_ports": plan["train_ports"],
            "years": plan["training_years"], "physics_prior": "declared queue/service/cost model, not learned terminal equipment physics"})
    models, rows = [], []
    for noise in [.5, 1., 1.5]:
        table = train_table(quantiles, noise)
        name = f"empirical_model_rl_s{noise}"
        path = OUT / f"{name}.npz"
        np.savez_compressed(path, advantages=table)
        models.append({"name": name, "path": str(path.relative_to(c.BASE_DIR)), "sha256": c.sha(path)})
        policy = EmpiricalPolicy(name, table, gains)
        rows.extend(c.evaluate(policy, w, forecast) for w in validation)
        print("MODEL_VALIDATION", name, statistics.mean(r["score"] for r in rows if r["algorithm"] == name), flush=True)
        del table
    for horizon in [7, 14, 28]:
        for robust in [0., .5]:
            p = MPC(horizon, robust, gains)
            rows.extend(c.evaluate(p, w, forecast) for w in validation)
    ablation = json.loads((learning.OUT / "ablation-development.json").read_text())
    means = {name: statistics.mean(r["score"] for r in rows if r["algorithm"] == name)
             for name in sorted({r["algorithm"] for r in rows})}
    rl_scores = {**{k: v for k, v in means.items() if k.startswith("empirical_")},
                 **{k: v for k, v in ablation["validation_means"].items() if k != "td_off"}}
    selection = {"schema": "xiaoyi-learning-selection.v3", "frozen_before_test_at": time.time(),
        "source_sha256": c.sha(Path(__file__)), "ablation_source_sha256": c.sha(Path(learning.__file__)),
        "base_source_hashes": c.sources(), "protocol_sha256": c.sha(learning.DATA / "protocol.json"),
        "ablation_report_sha256": c.sha(learning.OUT / "ablation-development.json"), "models": models,
        "validation_rows": rows, "validation_means": means, "rl_validation_means": rl_scores,
        "selected_rl": max(rl_scores, key=rl_scores.get),
        "selected_baseline": max((k for k in means if k.startswith("mpc")), key=means.get),
        "forecast": forecast, "gains": gains, "test_labels_used": False,
        "notice": "Empirical model-based offline RL is separately labeled, not model-free DQN. Queue physics is declared; transition uncertainty learned only from2019-2024 four-port indicators. Direct table lookup at evaluation, no online MPC fallback. Long remaining horizons use nearest precomputed28/90 bucket; five volatility bins and clipped demand grid are approximation assumptions. No actor trained on held-out ports.",
        "production_authority": False}
    c.write(OUT / "selection-before-test.json", selection)
    print("SELECTION_FROZEN", selection["selected_rl"], selection["selected_baseline"], means, flush=True)


def assess():
    if (OUT / "report.json").exists():
        raise ValueError("never overwrite viewed holdout")
    selection = json.loads((OUT / "selection-before-test.json").read_text())
    assert selection["source_sha256"] == c.sha(Path(__file__))
    assert selection["ablation_source_sha256"] == c.sha(Path(learning.__file__))
    plan = json.loads((learning.DATA / "protocol.json").read_text())
    manifest = json.loads((learning.DATA / "manifest.json").read_text())
    assert manifest["protocol_sha256"] == c.sha(learning.DATA / "protocol.json")
    series = {}
    for entry in manifest["entries"]:
        path = c.BASE_DIR / entry["path"]
        assert c.sha(path) == entry["sha256"]
        with path.open() as handle:
            series[entry["id"]] = [(date.fromisoformat(r["date"]), float(r["portcalls"])) for r in csv.DictReader(handle)]
    windows, excluded = c.windows(series, list(series), [2026], plan["test_months"])
    gains = tuple(selection["gains"])
    policies = [MPC(h, r, gains) for h in [7, 14, 28] for r in [0., .5]]
    policies += [c.Policy("pid_tuned", gains=gains), c.Policy("max_capacity", gains=gains)]
    for meta in selection["models"]:
        path = c.BASE_DIR / meta["path"]
        assert c.sha(path) == meta["sha256"]
        policies.append(EmpiricalPolicy(meta["name"], np.load(path)["advantages"], gains))
    ablation = json.loads((learning.OUT / "ablation-development.json").read_text())
    best_neural = max((k for k in ablation["validation_means"] if k != "td_off"), key=ablation["validation_means"].get)
    for meta in ablation["models"]:
        if meta["condition"] not in [best_neural, "reference_td", "td_off"]:
            continue
        payload = json.loads((c.BASE_DIR / meta["path"]).read_text())
        net = learning.Network(meta["seed"])
        net.params = [np.asarray(p) for p in payload["params"]]
        policies.append(c.Policy(meta["condition"], net, meta["seed"], gains))
    rows = []
    trace = OUT / "trajectories.jsonl.gz"
    with gzip.open(trace, "wt") as handle:
        for policy in policies:
            for window in windows:
                for scenario in c.SCENARIOS:
                    row = c.evaluate(policy, window, selection["forecast"], scenario, True)
                    handle.write(json.dumps(row) + "\n")
                    row.pop("frames")
                    rows.append(row)
            print("NEW_PORT_EVALUATED", policy.name, policy.seed, flush=True)
    baseline = {(r["window"], r["scenario"]): r for r in rows if r["algorithm"] == selection["selected_baseline"]}
    maximum = {(r["window"], r["scenario"]): r for r in rows if r["algorithm"] == "max_capacity"}
    aggregate = []
    for name in sorted({r["algorithm"] for r in rows}):
        own = [r for r in rows if r["algorithm"] == name]
        paired = {}
        for window in windows:
            paired.setdefault(window["port_id"], []).append(statistics.mean(
                r["score"] for r in own if r["window"] == window["id"] and r["scenario"] == "normal")
                - baseline[(window["id"], "normal")]["score"])
        interval = c.clustered_interval(paired)
        stress = [{"scenario": scenario, "mean_delta": statistics.mean(
            r["score"] - baseline[(r["window"], scenario)]["score"] for r in own if r["scenario"] == scenario)} for scenario in c.SCENARIOS[1:]]
        feasible = [r for r in own if maximum[(r["window"], r["scenario"])]["constraint_violations"] == 0]
        checks = {"selected_rl": name == selection["selected_rl"], "positive_port_cluster_ci": interval["port_cluster_ci95"][0] > 0,
                  "no_mean_port_regression": interval["worst_port_mean_delta"] >= 0,
                  "stress_noninferiority": all(r["mean_delta"] >= 0 for r in stress),
                  "no_feasible_window_violation": all(r["constraint_violations"] == 0 for r in feasible)}
        aggregate.append({"algorithm": name, "validation_score": selection["rl_validation_means"].get(name, selection["validation_means"].get(name)),
                          "test_score": statistics.mean(r["score"] for r in own if r["scenario"] == "normal"),
                          "new_port_interval": interval, "stress": stress, "checks": checks,
                          "all_constraint_violations": sum(r["constraint_violations"] for r in own),
                          "feasible_constraint_violations": sum(r["constraint_violations"] for r in feasible),
                          "research_admission": all(checks.values()), "production_admission": False})
    c.write(OUT / "report.json", {"schema": "xiaoyi-new-port-learning.v3", "sources": manifest, "protocol": plan,
        "selection": selection, "selection_sha256": c.sha(OUT / "selection-before-test.json"),
        "ablation": ablation, "windows": [{k: v for k, v in w.items() if k != "records"} for w in windows],
        "excluded_windows": excluded, "aggregate": aggregate, "runs": rows, "trace_path": str(trace.relative_to(c.BASE_DIR)),
        "trace_sha256": c.sha(trace), "production_authority": False, "notice": selection["notice"]})
    print("FRESH_HOLDOUT_DONE", [(a["algorithm"], round(a["test_score"], 6), a["research_admission"]) for a in aggregate], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["develop", "assess"])
    args = parser.parse_args()
    {"develop": develop, "assess": assess}[args.phase]()
