"""Paired, fixed-replay learning ablations; new holdouts are a separate phase."""

import argparse
import copy
import gzip
import json
import math
import statistics
import time
from pathlib import Path

import numpy as np

from app.config import BASE_DIR
from app.harness import crossport_v2 as c
from app.harness.guided_rl_v2 import Network

OUT = BASE_DIR / ".runtime/learning-v3-20261030"
DATA = BASE_DIR / "data/public/portwatch_v3_20261030"
CONDITIONS = {
    "reference_td": {},
    "td_off": {"td": False},
    "imitation_off": {"imitation": 0.0},
    "gamma_one": {"gamma": 1.0},
    "encoder_frozen": {"freeze_encoder": True},
    "monte_carlo_target": {"mc": True},
    "learning_rate_tenth": {"lr": 0.00003},
}


def fit(net, x, actions, targets, experts, *, td=True, imitation=0.1, freeze_encoder=False, lr=0.0003, **_):
    w, b, a, ac, v, vc = net.params
    z = x @ w + b
    h = np.maximum(0, z)
    adv = h @ a + ac
    dq = np.zeros((len(x), 5))
    if td:
        q = h @ v + vc + adv - adv.mean(axis=1, keepdims=True)
        dq[np.arange(len(x)), actions] = np.clip(q[np.arange(len(x)), actions] - targets, -1, 1) / len(x)
    da = dq - dq.mean(axis=1, keepdims=True)
    dv = dq.sum(axis=1, keepdims=True)
    logits = adv - adv.max(axis=1, keepdims=True)
    probabilities = np.exp(logits)
    probabilities /= probabilities.sum(axis=1, keepdims=True)
    probabilities[np.arange(len(x)), experts] -= 1
    da += imitation * probabilities / len(x)
    dh = (da @ a.T + dv @ v.T) * (z > 0)
    gradients = [x.T @ dh, dh.sum(axis=0), h.T @ da, da.sum(axis=0), h.T @ dv, dv.sum(axis=0)]
    if freeze_encoder:
        gradients[:2] = [np.zeros_like(w), np.zeros_like(b)]
    norm = math.sqrt(sum(float((g * g).sum()) for g in gradients))
    net.updates += 1
    for i, grad in enumerate(gradients):
        grad *= min(1, 5 / max(1e-9, norm))
        net.m[i] = 0.9 * net.m[i] + 0.1 * grad
        net.v[i] = 0.999 * net.v[i] + 0.001 * grad * grad
        net.params[i] -= lr * (net.m[i] / (1 - 0.9**net.updates)) / (
            np.sqrt(net.v[i] / (1 - 0.999**net.updates)) + 1e-8
        )


def reset_net(seed):
    path = BASE_DIR / f".runtime/guided-rl-v2-20261030/models/dueling_imitation_only-{seed}.json"
    payload = json.loads(path.read_text())
    net = Network(seed)
    net.params = [np.asarray(p) for p in payload["params"]]
    return net, c.sha(path)


def replay(seed, windows, forecast, gains):
    """Identical fixed behavior, transitions and minibatch indices within each seed."""
    rng = np.random.default_rng(seed + 90000)
    teacher, initial_hash = reset_net(seed)
    rows = []
    while len(rows) < 12000:
        env = c.Episode(windows[int(rng.integers(len(windows)))]["records"], forecast,
                        c.SCENARIOS[int(rng.integers(4))], gains)
        episode = []
        done = False
        while not done:
            f, mask, _ = env.features()
            expert = int(c.mpc_q(env).argmin())
            allowed = np.flatnonzero(mask)
            action = int(rng.choice(allowed)) if rng.random() < 0.2 else int(
                allowed[np.argmax(teacher.forward(np.asarray(f))[allowed])])
            reward, done = env.step(action)
            nf, nm = ([0.] * 25, [True] * 5) if done else env.features()[:2]
            episode.append([f, action, reward / 10, nf, done, nm, expert])
        value = 0
        for row in reversed(episode):
            value = row[2] + 0.97 * value
            row.append(value)
        rows.extend(episode)
    arrays = {key: np.asarray([r[i] for r in rows]) for i, key in enumerate(
        ["x", "action", "reward", "nx", "done", "mask", "expert", "behavior_mc"])}
    arrays["batch_indices"] = rng.integers(len(rows), size=(3000, 64))
    path = OUT / f"fixed-replay-{seed}.npz"
    np.savez_compressed(path, **arrays)
    return arrays, {"path": str(path.relative_to(BASE_DIR)), "sha256": c.sha(path),
                    "initial_weight_sha256": initial_hash, "transitions": len(rows)}


def develop():
    if (OUT / "selection-before-test.json").exists():
        raise ValueError("selection is immutable")
    OUT.mkdir(parents=True, exist_ok=True)
    original = json.loads((c.OUT / "selection-before-test.json").read_text())
    _, series = c.load()
    plan = json.loads((DATA / "protocol.json").read_text())
    train, _ = c.windows(series, plan["train_ports"], list(range(2019, 2025)), [1, 4, 7, 10])
    validation, _ = c.windows(series, plan["train_ports"], [2025], [1, 4, 7, 10])
    forecast, gains = original["forecast"]["selected"], tuple(original["gains"])
    rows, curves, saved, replays = [], [], [], []
    for seed in c.SEEDS:
        data, receipt = replay(seed, train, forecast, gains)
        replays.append(receipt)
        for condition, changes in CONDITIONS.items():
            net, _ = reset_net(seed)
            target = copy.deepcopy(net)
            settings = {"gamma": 0.97, **changes}
            initial_score = None
            for update in range(3001):
                if update in [0, 500, 1500, 3000]:
                    subset = validation if update == 3000 else validation[::2]
                    evaluated = [c.evaluate(c.Policy(condition, net, seed, gains), w, forecast) for w in subset]
                    score = statistics.mean(r["score"] for r in evaluated)
                    agreement = float(np.mean(net.forward(data["x"][:2048]).argmax(axis=1) == data["expert"][:2048]))
                    curves.append({"condition": condition, "seed": seed, "updates": update,
                                   "validation_score": score, "teacher_agreement": agreement,
                                   "initial_subset_score": initial_score, "validation_windows": len(subset)})
                    if update == 0:
                        initial_score = score
                    if update == 3000:
                        rows.extend(evaluated)
                        break
                ix = data["batch_indices"][update]
                nx = data["nx"][ix]
                greedy = np.argmax(np.where(data["mask"][ix], net.forward(nx), -1e12), axis=1)
                targets = data["reward"][ix] + settings["gamma"] * (1 - data["done"][ix]) * target.forward(nx)[np.arange(64), greedy]
                if settings.get("mc"):
                    targets = data["behavior_mc"][ix]
                fit(net, data["x"][ix], data["action"][ix], targets, data["expert"][ix], **settings)
                # 250 environment steps / 4 updates per step in v2 = about62 updates.
                if update % 62 == 0:
                    target.params = [p.copy() for p in net.params]
            path = OUT / "models" / f"{condition}-{seed}.json"
            c.write(path, {"condition": condition, "seed": seed, "params": [p.tolist() for p in net.params],
                           "settings": settings, "updates": 3000, "fixed_replay": receipt,
                           "gains": gains, "evaluation_mpc_fallback": False})
            saved.append({"condition": condition, "seed": seed, "path": str(path.relative_to(BASE_DIR)), "sha256": c.sha(path)})
            print("ABLATION", seed, condition, round(score, 6), "agreement", round(agreement, 4), flush=True)
    means = {name: statistics.mean(r["score"] for r in rows if r["algorithm"] == name) for name in CONDITIONS}
    paired = []
    for name in CONDITIONS:
        deltas = []
        for seed in c.SEEDS:
            reference = statistics.mean(r["score"] for r in rows if r["algorithm"] == "reference_td" and r["seed"] == seed)
            own = statistics.mean(r["score"] for r in rows if r["algorithm"] == name and r["seed"] == seed)
            deltas.append(own - reference)
        rng = np.random.default_rng(87233)
        boot = np.mean(rng.choice(deltas, size=(5000, len(deltas))), axis=1)
        paired.append({"condition": name, "single_change": CONDITIONS[name], "paired_seed_deltas": deltas,
                       "mean_delta": statistics.mean(deltas), "seed_bootstrap_ci95": np.quantile(boot, [.025, .975]).tolist()})
    result = {"schema": "xiaoyi-fixed-replay-ablation.v3", "source_sha256": c.sha(Path(__file__)),
              "base_source_hashes": c.sources(), "protocol_sha256": c.sha(DATA / "protocol.json"),
              "frozen_at": time.time(), "conditions": CONDITIONS, "replays": replays, "models": saved,
              "validation_rows": rows, "curves": curves, "validation_means": means, "paired": paired,
              "selected": max(means, key=means.get), "test_labels_used": False,
              "notice": "Controlled mechanistic experiment on fixed offline replay, not an exact reproduction of on-policy v2 behavior. Same initial weights, optimizer reset, transitions, batch order and update count within each seed. MC predicts fixed behavior returns, not unbiased optimal-action values. Paired seeds are five computational replicates, not five independent port populations.",
              "production_authority": False}
    c.write(OUT / "ablation-development.json", result)
    print("ABLATIONS_DONE", means, flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["develop"])
    args = parser.parse_args()
    develop()
