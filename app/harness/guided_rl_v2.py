"""Additional validation-only dueling critic study; imitation and RL are distinct artifacts."""

import copy
import json
import statistics
import time
from pathlib import Path

import numpy as np

from app.config import BASE_DIR
from app.harness import crossport_v2 as c

OUT = BASE_DIR / ".runtime/guided-rl-v2-20261030"


class Network:
    def __init__(self, seed):
        rng = np.random.default_rng(seed)
        self.params = [
            rng.normal(0, 0.1, (25, 64)),
            np.zeros(64),
            rng.normal(0, 0.05, (64, 5)),
            np.zeros(5),
            np.zeros((64, 1)),
            np.zeros(1),
        ]
        self.m = [np.zeros_like(p) for p in self.params]
        self.v = [np.zeros_like(p) for p in self.params]
        self.updates = 0

    def forward(self, x):
        w, b, a, ac, v, vc = self.params
        h = np.maximum(0, x @ w + b)
        adv = h @ a + ac
        return h @ v + vc + adv - adv.mean(axis=-1, keepdims=True)

    def fit(self, x, actions, targets=None, expert=None, imitation_weight=0):
        w, b, a, ac, v, vc = self.params
        z = x @ w + b
        h = np.maximum(0, z)
        adv = h @ a + ac
        dq = np.zeros((len(x), 5))
        if targets is not None:
            q = h @ v + vc + adv - adv.mean(axis=1, keepdims=True)
            dq[np.arange(len(x)), actions] = np.clip(q[np.arange(len(x)), actions] - targets, -1, 1) / len(x)
        da = dq - dq.mean(axis=1, keepdims=True)
        dv = dq.sum(axis=1, keepdims=True)
        if expert is not None:
            logits = adv - adv.max(axis=1, keepdims=True)
            probabilities = np.exp(logits)
            probabilities /= probabilities.sum(axis=1, keepdims=True)
            probabilities[np.arange(len(x)), expert] -= 1
            da += imitation_weight * probabilities / len(x)
        dh = (da @ a.T + dv @ v.T) * (z > 0)
        gradients = [x.T @ dh, dh.sum(axis=0), h.T @ da, da.sum(axis=0), h.T @ dv, dv.sum(axis=0)]
        norm = np.sqrt(sum(float((g * g).sum()) for g in gradients))
        self.updates += 1
        for i, gradient in enumerate(gradients):
            gradient *= min(1, 5 / max(1e-9, norm))
            self.m[i] = 0.9 * self.m[i] + 0.1 * gradient
            self.v[i] = 0.999 * self.v[i] + 0.001 * gradient * gradient
            self.params[i] -= (
                0.0003 * (self.m[i] / (1 - 0.9**self.updates)) / (np.sqrt(self.v[i] / (1 - 0.999**self.updates)) + 1e-8)
            )


def develop():
    if (OUT / "selection-before-test.json").exists():
        raise ValueError("additional selection is immutable")
    original = json.loads((c.OUT / "selection-before-test.json").read_text())
    if original["source_hashes"] != c.sources():
        raise ValueError("base development implementation drift")
    _, series = c.load()
    plan = json.loads((c.FOLDER / "protocol.json").read_text())
    windows, _ = c.windows(series, plan["train_ports"], plan["training_years"], [1, 4, 7, 10])
    validation, _ = c.windows(series, plan["train_ports"], [2025], [1, 4, 7, 10])
    gains = tuple(original["gains"])
    forecast = original["forecast"]["selected"]
    x, y = c.teacher_data(windows, forecast, gains, samples=6000)
    expert = y.argmax(axis=1)
    metadata, validation_rows = [], []
    for seed in c.SEEDS:
        print("dueling warmstart", seed, flush=True)
        rng = np.random.default_rng(seed)
        net = Network(seed)
        for _ in range(6000):
            indices = rng.integers(len(x), size=64)
            net.fit(x[indices], None, expert=expert[indices], imitation_weight=1)
        clone = copy.deepcopy(net)
        agreement = float(np.mean(clone.forward(x).argmax(axis=1) == expert))
        target = copy.deepcopy(net)
        replay = [None] * 30000
        position, size = 0, 0
        env = None
        for step in range(40000):
            if env is None:
                env = c.Episode(
                    windows[int(rng.integers(len(windows)))]["records"],
                    forecast,
                    c.SCENARIOS[int(rng.integers(4))],
                    gains,
                )
            f, mask, _ = env.features()
            oracle = int(np.argmin(c.mpc_q(env)))  # training-only guidance, not an evaluation fallback
            epsilon = max(0.05, 0.25 * (1 - step / 32000))
            allowed = [a for a in range(5) if mask[a]]
            action = (
                int(rng.choice(allowed))
                if rng.random() < epsilon
                else max(allowed, key=lambda a: net.forward(np.asarray(f))[a])
            )
            reward, done = env.step(action)
            nf, nm = ([0.0] * 25, [True] * 5) if done else env.features()[:2]
            replay[position] = (f, action, reward / 10, nf, done, nm, oracle)
            position = (position + 1) % len(replay)
            size = min(size + 1, len(replay))
            if size >= 256 and step % 4 == 0:
                batch = [replay[i] for i in rng.integers(size, size=64)]
                nx = np.asarray([r[3] for r in batch])
                valid = np.asarray([r[5] for r in batch])
                greedy = np.argmax(np.where(valid, net.forward(nx), -1e12), axis=1)
                targets = (
                    np.asarray([r[2] for r in batch])
                    + 0.97
                    * (1 - np.asarray([r[4] for r in batch], dtype=float))
                    * target.forward(nx)[np.arange(64), greedy]
                )
                net.fit(
                    np.asarray([r[0] for r in batch]),
                    np.asarray([r[1] for r in batch]),
                    targets,
                    np.asarray([r[6] for r in batch]),
                    imitation_weight=0.1,
                )
            if step % 250 == 0:
                target.params = [p.copy() for p in net.params]
            if done:
                env = None
        for name, model, rl_steps in [("dueling_guided_ddqn", net, 40000), ("dueling_imitation_only", clone, 0)]:
            p = c.Policy(name, model, seed, gains)
            path = OUT / "models" / f"{name}-{seed}.json"
            c.write(
                path,
                {
                    "name": name,
                    "seed": seed,
                    "params": [v.tolist() for v in model.params],
                    "gains": gains,
                    "rl_steps": rl_steps,
                    "imitation_updates": 6000,
                    "teacher_agreement_on_training": agreement,
                    "network_updates": model.updates,
                    "evaluation_mpc_fallback": False,
                },
            )
            metadata.append(
                {"name": name, "seed": seed, "path": str(path.relative_to(BASE_DIR)), "sha256": c.sha(path)}
            )
            validation_rows.extend(c.evaluate(p, w, forecast) for w in validation)
        print("dueling trained", seed, "teacher agreement", agreement, flush=True)
    means = {
        name: statistics.mean(r["score"] for r in validation_rows if r["algorithm"] == name)
        for name in ["dueling_guided_ddqn", "dueling_imitation_only"]
    }
    candidates = {
        **{
            k: v
            for k, v in original["validation_means"].items()
            if k in ["balanced_double_dqn", "mpc_guided_double_dqn"]
        },
        "dueling_guided_ddqn": means["dueling_guided_ddqn"],
    }
    result = {
        "source_sha256": c.sha(Path(__file__)),
        "base_source_hashes": c.sources(),
        "base_selection_sha256": c.sha(c.OUT / "selection-before-test.json"),
        "frozen_before_test_at": time.time(),
        "models": metadata,
        "validation_rows": validation_rows,
        "validation_means": means,
        "global_selected_rl": max(candidates, key=candidates.get),
        "all_rl_validation_scores": candidates,
        "hypothesis": "Separate value/advantage heads, valid expert action classification and joint RL/imitation loss can prevent invalid-action regression targets dominating the warmstart. Full original reward retained in evaluation; gamma .97 explicitly differs from previous gamma1 ablation.",
        "test_labels_used": False,
        "production_authority": False,
    }
    c.write(OUT / "selection-before-test.json", result)
    print("SUPPLEMENT_FROZEN", means, result["global_selected_rl"], flush=True)
    return result


def assess():
    if (OUT / "report.json").exists():
        raise ValueError("new test result cannot be overwritten")
    selected = json.loads((OUT / "selection-before-test.json").read_text())
    if selected["source_sha256"] != c.sha(Path(__file__)) or selected["base_source_hashes"] != c.sources():
        raise ValueError("supplement implementation changed after selection")
    original = c.report()
    _, series = c.load()
    plan = original["protocol"]
    windows, _ = c.windows(series, list(series), [2026], plan["test_quarters"])
    baseline = {
        (r["window"], r["scenario"]): r
        for r in original["runs"]
        if r["algorithm"] == original["selection"]["selected_baseline"]
    }
    maximum = {(r["window"], r["scenario"]): r for r in original["runs"] if r["algorithm"] == "max_capacity"}
    rows = []
    import gzip

    trace = OUT / "trajectories.jsonl.gz"
    with gzip.open(trace, "wt") as handle:
        for meta in selected["models"]:
            payload = json.loads((BASE_DIR / meta["path"]).read_text())
            net = Network(payload["seed"])
            net.params = [np.asarray(p) for p in payload["params"]]
            p = c.Policy(payload["name"], net, payload["seed"], tuple(payload["gains"]))
            for w in windows:
                for scenario in c.SCENARIOS:
                    row = c.evaluate(p, w, original["selection"]["forecast"]["selected"], scenario, True)
                    frames = row.pop("frames")
                    handle.write(json.dumps({**row, "frames": frames}) + "\n")
                    rows.append(row)
    aggregates = []
    for name in selected["validation_means"]:
        own = [r for r in rows if r["algorithm"] == name]
        contexts = {}
        for role, ports in [("temporal_holdout", plan["train_ports"]), ("new_whole_port_holdout", plan["fresh_ports"])]:
            paired = {}
            for w in windows:
                if w["port_id"] in ports:
                    scores = [r["score"] for r in own if r["window"] == w["id"] and r["scenario"] == "normal"]
                    paired.setdefault(w["port_id"], []).append(
                        statistics.mean(scores) - baseline[(w["id"], "normal")]["score"]
                    )
            contexts[role] = c.clustered_interval(paired)
        stress = [
            {
                "scenario": scenario,
                "mean_delta": statistics.mean(
                    r["score"] - baseline[(r["window"], scenario)]["score"] for r in own if r["scenario"] == scenario
                ),
            }
            for scenario in c.SCENARIOS[1:]
        ]
        feasible = [r for r in own if maximum[(r["window"], r["scenario"])]["constraint_violations"] == 0]
        checks = {
            "rl_candidate": name == "dueling_guided_ddqn",
            "selected_on_validation": name == selected["global_selected_rl"],
            "both_holdouts_improve": all(v["port_cluster_ci95"][0] > 0 for v in contexts.values()),
            "no_port_regression": all(v["worst_port_mean_delta"] >= 0 for v in contexts.values()),
            "no_feasible_window_violation": all(r["constraint_violations"] == 0 for r in feasible),
            "stress_noninferiority": all(r["mean_delta"] >= 0 for r in stress),
        }
        aggregates.append(
            {
                "algorithm": name,
                "validation_score": selected["validation_means"][name],
                "test_score": statistics.mean(r["score"] for r in own if r["scenario"] == "normal"),
                "contexts": contexts,
                "stress": stress,
                "checks": checks,
                "blockers": [k for k, v in checks.items() if not v],
                "research_admission": all(checks.values()),
                "all_constraint_violations": sum(r["constraint_violations"] for r in own),
                "feasible_constraint_violations": sum(r["constraint_violations"] for r in feasible),
                "production_admission": False,
            }
        )
    result = {
        "schema": "xiaoyi-dueling-guided-rl.v1",
        "selection": selected,
        "selection_sha256": c.sha(OUT / "selection-before-test.json"),
        "aggregate": aggregates,
        "runs": rows,
        "trace_path": str(trace.relative_to(BASE_DIR)),
        "trace_sha256": c.sha(trace),
        "production_authority": False,
        "notice": "模仿快照与真实TD更新后的RL分别留出比较。运行时没有MPC回退；训练时的MPC教师、联合损失和修改的折扣因子明示，失败结果全部保留。",
    }
    c.write(OUT / "report.json", result)
    return result


def report():
    value = json.loads((OUT / "report.json").read_text())
    expected = value["selection"]
    issues = []
    if expected["source_sha256"] != c.sha(Path(__file__)) or expected["base_source_hashes"] != c.sources():
        issues.append("supplement implementation/source drift")
    for meta in expected["models"]:
        if c.sha(BASE_DIR / meta["path"]) != meta["sha256"]:
            issues.append("supplement model drift")
    if (
        c.sha(OUT / "selection-before-test.json") != value["selection_sha256"]
        or c.sha(BASE_DIR / value["trace_path"]) != value["trace_sha256"]
    ):
        issues.append("supplement result provenance drift")
    value["historical_only"] = bool(issues)
    value["current_validation_issues"] = issues
    return value
