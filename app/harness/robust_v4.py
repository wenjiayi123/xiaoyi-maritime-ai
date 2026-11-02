"""Causal queue innovations, shared safety filters and broader offline model RL."""

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

from app.harness import crossport_v2 as c, modelbased_v3 as previous

DATA = c.BASE_DIR / "data/public/portwatch_v4_20261030"
OUT = c.BASE_DIR / ".runtime/robust-v4-20261030"
QUEUE = np.arange(0, 12.00001, .025)
DEMAND = np.arange(.4, 3.00001, .05)
VOL = np.asarray([.025, .05, .1, .2, .3, .5, .8, 1.2])
HORIZONS = list(range(1, 15)) + [28, 90]
FACTORS = np.asarray(c.old.FACTORS)
PROBS = [.02, .1, .25, .5, .75, .9, .98]
WEIGHTS = np.asarray([.06, .115, .2, .25, .2, .115, .06])


class Episode(c.Episode):
    def __init__(self, records, forecast, scenario="normal", gains=(.2, .02, .02), alpha=.5):
        super().__init__(records, forecast, scenario, gains)
        self.alpha = alpha
        self.arrival_estimate = None
        self.memory_cache = None
        self.innovation_kind = "none"
        self.pending_note = {}

    def context(self):
        if self.memory_cache is not None:
            return self.memory_cache
        history, lag, public, _, _, _, availability, mask = super().context()
        demand = public if self.arrival_estimate is None or self.alpha == 0 else max(public, self.arrival_estimate)
        error = self.backlog / self.scale - .2 + (demand / self.scale - 1) * .5
        integral = max(-4., min(4., self.integral + error))
        kp, ki, kd = self.gains
        command = max(.65, min(1.35, 1 + kp * error + ki * integral + kd * (error - self.previous_error)))
        pid = min((a for a in range(5) if mask[a]), key=lambda a: abs(FACTORS[a] - command))
        self.memory_cache = history, lag, demand, error, integral, pid, availability, mask
        return self.memory_cache

    def step(self, action):
        history, _, demand, _, _, _, availability, _ = self.context()
        public = c.forecasting.predict(self.forecast, history, self.records[self.index][0])
        before, index, kind = self.backlog, self.index, self.innovation_kind
        capacity = self.scale * FACTORS[action] * availability
        prior = public if self.arrival_estimate is None else self.arrival_estimate
        note = dict(self.pending_note)
        result = super().step(action)
        # Only q_before/q_after and own capacity are read here, never actual source arrival.
        if self.backlog > 1e-9:
            inferred = max(0., self.backlog - before + capacity)
            self.innovation_kind = "previous_saturated_service_queue_identity"
        else:
            # Empty queue gives an upper bound, not an exact arrival measurement.
            inferred = public
            self.innovation_kind = "empty_queue_bound_not_used_as_point_measurement"
        self.arrival_estimate = ((1 - self.alpha) * prior + self.alpha * inferred) if self.backlog > 1e-9 else public
        self.frames[-1].update(public_forecast_proxy=public, causal_nowcast_proxy=demand,
            nowcast_input_kind=kind, nowcast_latest_queue_day=self.records[index - 1][0].isoformat() if index > 42 else None,
            **note)
        self.memory_cache = None
        self.pending_note = {}
        return result


class ThresholdPolicy:
    def __init__(self, name, thresholds):
        self.name, self.thresholds = name, thresholds

    def action(self, env):
        history, _, demand, _, _, _, availability, mask = env.context()
        mean = demand / env.scale
        backlog = env.backlog / env.scale
        if mean > DEMAND[-1] or backlog > QUEUE[-1]:
            return max(a for a in range(5) if mask[a])
        di = float(np.clip((mean - .4) / .05, 0, len(DEMAND) - 1))
        volatility = c.uncertainty_scale(history) / env.scale
        vi = float(np.clip(np.interp(volatility, VOL, np.arange(len(VOL))), 0, len(VOL) - 1))
        remaining = 90 - (env.index - 42)
        horizon = remaining if remaining <= 14 else (28 if remaining <= 28 else 90)
        boundaries = np.zeros(4)
        for d, dw in [(int(di), 1 - di % 1), (min(int(di) + 1, len(DEMAND) - 1), di % 1)]:
            for v, vw in [(int(vi), 1 - vi % 1), (min(int(vi) + 1, len(VOL) - 1), vi % 1)]:
                boundaries += dw * vw * self.thresholds[d, v, int(availability >= .75), HORIZONS.index(horizon), env.previous_action]
        action = int(np.sum(backlog + 1e-10 >= boundaries))
        return min(action, max(a for a in range(5) if mask[a]))


class Policy:
    def __init__(self, raw, guard, gains, alpha):
        self.raw, self.guard, self.gains, self.alpha = raw, guard, gains, alpha
        self.name = raw.name + "." + guard["name"]
        self.seed = 0

    def action(self, env):
        raw = self.raw.action(env)
        action = raw
        if self.guard["name"] != "none":
            history, _, demand, _, _, _, availability, mask = env.context()
            upper = demand / env.scale + self.guard["sigma"] * c.uncertainty_scale(history) / env.scale
            allowed = [a for a in range(5) if mask[a] and max(0., env.backlog / env.scale + upper - FACTORS[a] * availability) <= self.guard["queue_budget"]]
            action = max(raw, min(allowed)) if allowed else max(a for a in range(5) if mask[a])
        env.pending_note = {"raw_learned_or_baseline_action": int(raw), "safety_override": bool(action != raw),
                            "safety_filter": self.guard["name"],
                            "learned_table_extrapolation": bool(isinstance(self.raw, ThresholdPolicy) and (
                                env.context()[2] / env.scale > DEMAND[-1] or env.backlog / env.scale > QUEUE[-1]))}
        return int(action)


def evaluate(policy, window, forecast, scenario="normal", keep=False):
    env = Episode(window["records"], forecast, scenario, policy.gains, policy.alpha)
    done = False
    while not done:
        _, done = env.step(policy.action(env))
    result = {"algorithm": policy.name, "seed": 0, "port_id": window["port_id"], "window": window["id"],
              "start": window["start"], "scenario": scenario, "score": -env.total_cost / 90,
              "constraint_violations": env.violations, "maximum_flow_error": env.mass_error,
              "safety_override_fraction": statistics.mean(r["safety_override"] for r in env.frames),
              "evaluation_mpc_fallback": False}
    if keep:
        result["frames"] = env.frames
    return result


def load_development():
    _, series = c.load()
    manifest = json.loads((c.BASE_DIR / "data/public/portwatch_v3_20261030/manifest.json").read_text())
    for entry in manifest["entries"]:
        path = c.BASE_DIR / entry["path"]
        assert c.sha(path) == entry["sha256"]
        with path.open() as handle:
            series[entry["id"]] = [(date.fromisoformat(r["date"]), float(r["portcalls"])) for r in csv.DictReader(handle)]
    return series


def train_thresholds(quantiles_by_vol, penalty):
    thresholds = np.empty((len(DEMAND), len(VOL), 2, len(HORIZONS), 5, 4), dtype=np.float32)
    projected = decisions = 0
    for di, demand in enumerate(DEMAND):
        for vi, volatility in enumerate(VOL):
            arrivals = np.maximum(0, demand + volatility * quantiles_by_vol[vi])
            for ai, availability in enumerate([.5, 1.]):
                end = [np.maximum(0, QUEUE[:, None] + arrivals - FACTORS[a] * availability) for a in range(5)]
                positions = [np.clip(e / .025, 0, len(QUEUE) - 1) for e in end]
                indices = [p.astype(int) for p in positions]
                weights = [p - ix for p, ix in zip(positions, indices)]
                reward_cost = [e + .5 * FACTORS[a] ** 2 + np.maximum(0, e - 4) * 5 + penalty * (e > 4) for a, e in enumerate(end)]
                value = np.zeros((len(QUEUE), 5))
                for depth in range(1, 91):
                    q = np.empty((len(QUEUE), 5, 5))
                    for a in range(5):
                        ix, w = indices[a], weights[a]
                        continuation = (1 - w) * value[ix, a] + w * value[np.minimum(ix + 1, len(QUEUE) - 1), a]
                        continuation += np.maximum(0, end[a] - QUEUE[-1]) * 6 * (depth - 1)
                        cost = reward_cost[a] + continuation + (2 * end[a] if depth == 1 else 0)
                        q[:, :, a] = (cost @ WEIGHTS)[:, None] + .05 * np.abs(FACTORS - FACTORS[a])[None, :]
                        if availability < .75 and a > 2:
                            q[:, :, a] = 1e10
                    value = q.min(axis=2)
                    if depth in HORIZONS:
                        actions = q.argmin(axis=2).T
                        monotone = np.maximum.accumulate(actions, axis=1)
                        projected += int(np.sum(monotone != actions))
                        decisions += actions.size
                        for prev in range(5):
                            for boundary in range(1, 5):
                                found = np.flatnonzero(monotone[prev] >= boundary)
                                thresholds[di, vi, ai, HORIZONS.index(depth), prev, boundary - 1] = QUEUE[found[0]] if len(found) else 999.
        if di % 4 == 0:
            print("V4_BELLMAN", penalty, round(float(demand), 2), flush=True)
    return thresholds, {"monotone_projection_changed_decisions": projected, "grid_decisions": decisions,
                         "notice": "Threshold compression uses an explicit monotone conservative projection, not a neural critic; all costs evaluated with the original external reward."}


def develop():
    if (OUT / "selection-before-test.json").exists():
        raise ValueError("selection is immutable")
    OUT.mkdir(parents=True, exist_ok=True)
    plan = json.loads((DATA / "protocol.json").read_text())
    series = load_development()
    forecast = c.fit_forecast(series, plan["train_ports"])
    gains = tuple(json.loads((c.OUT / "selection-before-test.json").read_text())["gains"])
    train, excluded = c.windows(series, plan["train_ports"], plan["fit_years"], [1, 4, 7, 10])
    validation, _ = c.windows(series, plan["train_ports"], [2025], [1, 4, 7, 10])
    guards = plan["safety_filters"]
    alpha_rows = []
    for alpha in plan["nowcast_alpha_candidates"]:
        p = Policy(previous.MPC(14, 0., gains), guards[0], gains, alpha)
        result = [evaluate(p, w, forecast["selected"], s) for w in validation for s in c.SCENARIOS]
        alpha_rows.append({"alpha": alpha, "score": statistics.mean(r["score"] for r in result),
                           "normal_score": statistics.mean(r["score"] for r in result if r["scenario"] == "normal")})
    alpha = max(alpha_rows, key=lambda r: r["score"])["alpha"]
    print("V4_SHARED_ALPHA", alpha_rows, "selected", alpha, flush=True)
    residuals = [[] for _ in VOL]
    rng = np.random.default_rng(432101)
    interactions = 0
    for window in train:
        for scenario in c.SCENARIOS:
            env = Episode(window["records"], forecast["selected"], scenario, gains, alpha)
            for _ in range(90):
                history, _, demand, _, _, _, _, mask = env.context()
                sigma = c.uncertainty_scale(history)
                actual = env.records[env.index][1]
                if scenario == "demand_surge" and 20 <= env.index - 42 < 50:
                    actual *= 1.5
                vi = int(np.argmin(abs(VOL - sigma / env.scale)))
                residuals[vi].append((actual - demand) / sigma)
                env.step(int(rng.choice(np.flatnonzero(mask))))
                interactions += 1
    global_residuals = [v for group in residuals for v in group]
    quantiles = np.asarray([np.quantile(group if len(group) >= 500 else global_residuals, PROBS) for group in residuals])
    c.write(OUT / "empirical-transition-model.json", {"interactions": interactions, "by_volatility_n": [len(g) for g in residuals],
            "quantile_probabilities": PROBS, "weights": WEIGHTS.tolist(), "standardized_error_quantiles": quantiles.tolist(),
            "alpha": alpha, "training_ports": plan["train_ports"], "training_years": plan["fit_years"],
            "all_four_training_scenarios": True, "no_test_labels": True})
    policies, models = [], []
    for penalty in plan["learned_risk_penalties"]:
        thresholds, info = train_thresholds(quantiles, penalty)
        name = f"risk_model_rl_p{penalty}"
        path = OUT / f"{name}.npz"
        np.savez_compressed(path, thresholds=thresholds)
        models.append({"name": name, "path": str(path.relative_to(c.BASE_DIR)), "sha256": c.sha(path), "penalty": penalty, **info})
        policies.extend(Policy(ThresholdPolicy(name, thresholds), g, gains, alpha) for g in guards)
    for horizon in [14, 28]:
        for robust in [0., .5]:
            policies.extend(Policy(previous.MPC(horizon, robust, gains), g, gains, alpha) for g in guards)
    maximum = Policy(c.Policy("max_capacity", gains=gains), guards[0], gains, alpha)
    feasibility = {(w["id"], scenario): evaluate(maximum, w, forecast["selected"], scenario)["constraint_violations"]
                   for w in validation for scenario in c.SCENARIOS}
    rows = []
    for policy in policies:
        rows.extend(evaluate(policy, w, forecast["selected"], scenario) for w in validation for scenario in c.SCENARIOS)
        print("V4_VALIDATION", policy.name, flush=True)
    summary = []
    for policy in policies:
        own = [r for r in rows if r["algorithm"] == policy.name]
        summary.append({"algorithm": policy.name, "normal_score": statistics.mean(r["score"] for r in own if r["scenario"] == "normal"),
            "avoidable_violations": sum(r["constraint_violations"] for r in own if feasibility[(r["window"], r["scenario"])] == 0),
            "override_fraction": statistics.mean(r["safety_override_fraction"] for r in own)})
    mpcs = [r for r in summary if r["algorithm"].startswith("mpc")]
    cost_baseline = max(mpcs, key=lambda r: r["normal_score"])["algorithm"]
    safe_baseline = min(mpcs, key=lambda r: (r["avoidable_violations"], -r["normal_score"]))["algorithm"]
    baseline = {(r["window"], r["scenario"]): r for r in rows if r["algorithm"] == cost_baseline}
    rl_rows = []
    for row in summary:
        if not row["algorithm"].startswith("risk_"):
            continue
        per_port = [statistics.mean(r["score"] - baseline[(r["window"], r["scenario"])]["score"]
                    for r in rows if r["algorithm"] == row["algorithm"] and r["port_id"] == port and r["scenario"] == "normal")
                    for port in plan["train_ports"]]
        rl_rows.append({**row, "worst_port_delta": min(per_port), "port_balanced_delta": statistics.mean(per_port)})
    chosen = max(rl_rows, key=lambda r: (-r["avoidable_violations"], r["worst_port_delta"], r["port_balanced_delta"]))
    c.write(OUT / "selection-before-test.json", {"schema": "xiaoyi-risk-selection.v4", "frozen_before_test_at": time.time(),
        "source_sha256": c.sha(Path(__file__)), "base_source_hashes": c.sources(),
        "previous_mpc_implementation_sha256": c.sha(Path(previous.__file__)), "protocol_sha256": c.sha(DATA / "protocol.json"),
        "forecast": forecast, "gains": gains, "alpha": alpha, "alpha_candidates": alpha_rows, "models": models,
        "validation_rows": rows, "validation_summary": summary, "rl_validation_summary": rl_rows,
        "selected_rl": chosen["algorithm"], "selected_cost_mpc": cost_baseline, "selected_safe_mpc": safe_baseline,
        "training_windows": len(train), "excluded_training_windows": excluded,
        "empirical_model_sha256": c.sha(OUT / "empirical-transition-model.json"), "test_labels_used": False,
        "production_authority": False})
    print("V4_SELECTION_FROZEN", chosen, cost_baseline, safe_baseline, flush=True)


def assess():
    if (OUT / "report.json").exists():
        raise ValueError("never overwrite an inspected holdout")
    selection = json.loads((OUT / "selection-before-test.json").read_text())
    assert selection["source_sha256"] == c.sha(Path(__file__))
    assert selection["base_source_hashes"] == c.sources()
    plan = json.loads((DATA / "protocol.json").read_text())
    assert selection["protocol_sha256"] == c.sha(DATA / "protocol.json")
    manifest = json.loads((DATA / "manifest.json").read_text())
    assert manifest["protocol_sha256"] == selection["protocol_sha256"]
    series = {}
    for entry in manifest["entries"]:
        path = c.BASE_DIR / entry["path"]
        assert c.sha(path) == entry["sha256"]
        with path.open() as handle:
            series[entry["id"]] = [(date.fromisoformat(r["date"]), float(r["portcalls"])) for r in csv.DictReader(handle)]
    windows, excluded = c.windows(series, list(series), [2026], plan["test_months"])
    gains, alpha = tuple(selection["gains"]), selection["alpha"]
    guards = plan["safety_filters"]
    policies = []
    for meta in selection["models"]:
        path = c.BASE_DIR / meta["path"]
        assert c.sha(path) == meta["sha256"]
        thresholds = np.load(path)["thresholds"]
        policies.extend(Policy(ThresholdPolicy(meta["name"], thresholds), g, gains, alpha) for g in guards)
    for h in [14, 28]:
        for robust in [0., .5]:
            policies.extend(Policy(previous.MPC(h, robust, gains), g, gains, alpha) for g in guards)
    policies += [Policy(c.Policy(n, gains=gains), guards[0], gains, alpha) for n in ["max_capacity", "pid_tuned"]]
    rows = []
    trace = OUT / "trajectories.jsonl.gz"
    with gzip.open(trace, "wt") as handle:
        for policy in policies:
            for window in windows:
                for scenario in c.SCENARIOS:
                    row = evaluate(policy, window, selection["forecast"]["selected"], scenario, True)
                    handle.write(json.dumps(row) + "\n")
                    row.pop("frames")
                    rows.append(row)
            print("V4_UNSEEN_EVALUATED", policy.name, flush=True)
    maximum_name = "max_capacity.none"
    maximum = {(r["window"], r["scenario"]): r for r in rows if r["algorithm"] == maximum_name}
    aggregate = []
    for name in sorted({r["algorithm"] for r in rows}):
        own = [r for r in rows if r["algorithm"] == name]
        comparisons = []
        for comparator in dict.fromkeys([selection["selected_cost_mpc"], selection["selected_safe_mpc"]]):
            baseline = {(r["window"], r["scenario"]): r for r in rows if r["algorithm"] == comparator}
            paired, relative = {}, {}
            for window in windows:
                key = (window["id"], "normal")
                score = next(r["score"] for r in own if r["window"] == window["id"] and r["scenario"] == "normal")
                delta = score - baseline[key]["score"]
                paired.setdefault(window["port_id"], []).append(delta)
                relative.setdefault(window["port_id"], []).append(delta / abs(baseline[key]["score"]))
            absolute_ci = c.clustered_interval(paired)
            relative_ci = c.clustered_interval(relative)
            changes = list(absolute_ci["per_port_mean_delta"].values())
            positive = [max(0., v) for v in changes]
            concentration = max(positive) / sum(positive) if sum(positive) > 0 else None
            stress = [{"scenario": s, "mean_delta": statistics.mean(r["score"] - baseline[(r["window"], s)]["score"]
                        for r in own if r["scenario"] == s)} for s in c.SCENARIOS[1:]]
            comparisons.append({"baseline": comparator, "absolute_port_interval": absolute_ci,
                "relative_port_interval": relative_ci, "largest_positive_gain_share": concentration,
                "mean_without_best_port": (sum(changes) - max(changes)) / max(1, len(changes) - 1), "stress": stress})
        feasible = [r for r in own if maximum[(r["window"], r["scenario"])]["constraint_violations"] == 0]
        checks = {"selected_rl": name == selection["selected_rl"],
            "beats_cost_and_safe_mpc_absolute_ci": all(r["absolute_port_interval"]["port_cluster_ci95"][0] > 0 for r in comparisons),
            "beats_cost_and_safe_mpc_relative_ci": all(r["relative_port_interval"]["port_cluster_ci95"][0] > 0 for r in comparisons),
            "no_new_port_mean_regression": all(r["absolute_port_interval"]["worst_port_mean_delta"] >= 0 for r in comparisons),
            "gain_not_concentrated": all(r["largest_positive_gain_share"] is not None and r["largest_positive_gain_share"] <= .5 and r["mean_without_best_port"] > 0 for r in comparisons),
            "stress_noninferiority": all(s["mean_delta"] >= 0 for r in comparisons for s in r["stress"]),
            "no_feasible_window_violation": all(r["constraint_violations"] == 0 for r in feasible)}
        aggregate.append({"algorithm": name, "test_score": statistics.mean(r["score"] for r in own if r["scenario"] == "normal"),
            "comparisons": comparisons, "checks": checks, "research_admission": all(checks.values()),
            "feasible_constraint_violations": sum(r["constraint_violations"] for r in feasible),
            "all_constraint_violations": sum(r["constraint_violations"] for r in own),
            "safety_override_fraction": statistics.mean(r["safety_override_fraction"] for r in own), "production_admission": False})
    # Previously inspected v3 windows are a diagnostic shadow replay, not a new holdout.
    development = load_development()
    old_windows, _ = c.windows(development, ["port1417", "port395"], [2026], [1])
    chosen = next(p for p in policies if p.name == selection["selected_rl"])
    shadow = [evaluate(chosen, w, selection["forecast"]["selected"], "demand_surge", True) for w in old_windows]
    c.write(OUT / "historical-four-step-shadow.json", {"prior_v3_violations": 4, "new_violations": sum(r["constraint_violations"] for r in shadow),
        "runs": shadow, "notice": "Viewed v3 windows, new queue-memory contract, forecast and20-port training; changes are joint, not a single-factor causal attribution or independent acceptance.", "production_authority": False})
    c.write(OUT / "report.json", {"schema": "xiaoyi-risk-generalization-study.v4", "sources": manifest, "protocol": plan,
        "selection": selection, "selection_sha256": c.sha(OUT / "selection-before-test.json"),
        "windows": [{k: v for k, v in w.items() if k != "records"} for w in windows], "excluded_windows": excluded,
        "aggregate": aggregate, "runs": rows, "trace_path": str(trace.relative_to(c.BASE_DIR)), "trace_sha256": c.sha(trace),
        "historical_shadow_path": str((OUT / "historical-four-step-shadow.json").relative_to(c.BASE_DIR)),
        "historical_shadow_sha256": c.sha(OUT / "historical-four-step-shadow.json"), "production_authority": False,
        "notice": "Broader20-port development, causal censored queue innovation and explicitly shared safety filters. New8-port outcome gate uses absolute and port-relative paired intervals, concentration, regressions and avoidable safety violations. All raw/filtered candidates and both cost/safe MPC baselines retained. No live-port or hardware authority."})
    print("V4_FRESH_DONE", [(r["algorithm"], r["test_score"], r["feasible_constraint_violations"], r["research_admission"]) for r in aggregate], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["develop", "assess"])
    args = parser.parse_args()
    {"develop": develop, "assess": assess}[args.phase]()
