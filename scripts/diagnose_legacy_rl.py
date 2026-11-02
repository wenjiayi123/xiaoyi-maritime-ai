"""Diagnose the already-observed legacy test; not a new confirmatory holdout."""

from __future__ import annotations

import copy
import argparse
import importlib.util
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.rl_lab.datasets import chronological_split, get_dataset, load_records  # noqa: E402
from app.rl_lab.port_environment import PortOperationsEnvironment, derive_port_parameters  # noqa: E402

LEGACY_DIR = ROOT / ".codex_artifacts/crossport-20261030/legacy-source"
spec = importlib.util.spec_from_file_location("xiaoyi_frozen_legacy_algorithms", LEGACY_DIR / "algorithms.py")
alg = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = alg
spec.loader.exec_module(alg)


class Fixed(alg.TrainedPolicy):
    def __init__(self, action):
        super().__init__(f"fixed-{action}", {}, None, 0, {})
        self.fixed_action = action

    def action(self, state, mask, rng):
        return min((a for a, valid in enumerate(mask) if valid), key=lambda a: abs(a - self.fixed_action))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=".codex_artifacts/crossport-20261030")
    args = parser.parse_args()
    folder = ROOT / args.out
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "legacy-diagnosis.json").exists():
        raise FileExistsError("preserve earlier diagnosis; choose a new --out directory")
    old = json.loads((ROOT / ".codex_artifacts/future-port-20261030/research-current-release.json").read_text())
    definition = get_dataset(old["dataset_id"])
    train, validation, test = chronological_split(load_records(definition), train_ratio=0.7, validation_ratio=0.15)
    parameters = derive_port_parameters(train)
    rows = []

    def evaluate(name, policy, seed, label, episodes=None):
        result = alg.evaluate_policy(
            name,
            policy,
            test,
            parameters,
            horizon_steps=24,
            seed=seed + 90000,
            render=True,
            environment_type="port_operations",
        )
        frames = result["frames"]
        seen = (
            [alg._state_key(tuple(f["state"])) in policy.q_table for f in frames]
            if isinstance(policy, alg.TrainedPolicy) and not isinstance(policy, Fixed)
            else []
        )
        rows.append(
            {
                "algorithm": name,
                "variant": label,
                "seed": seed,
                "episodes": episodes,
                "test_metrics": result["metrics"],
                "action_counts": {str(a): sum(f["action"] == a for f in frames) for a in range(5)},
                "training_state_count": len(policy.q_table) if seen else None,
                "test_state_coverage": statistics.mean(seen) if seen else None,
                "unique_test_states": len({tuple(f["state"]) for f in frames}),
            }
        )

    for model in old["models"]:
        data = json.loads((ROOT / model["path"]).read_text())
        evaluate(model["algorithm"], alg.TrainedPolicy.from_dict(data["policy"]), model["seed"], "original_160", 160)
    for seed in old["config"]["seeds"]:
        evaluate("pid", alg.PIDPolicy(), seed, "original_baseline")
    for action in range(5):
        evaluate(f"fixed-{action}", Fixed(action), old["config"]["seeds"][0], "objective_dominance_probe")
    for episodes in [640, 2400]:
        for name in old["config"]["algorithms"]:
            for seed in old["config"]["seeds"]:
                policy, curve = alg.train_tabular_policy(
                    name,
                    train,
                    parameters,
                    episodes=episodes,
                    horizon_steps=24,
                    seed=seed,
                    learning_rate=0.12,
                    discount_factor=0.97,
                    epsilon_start=1.0,
                    epsilon_end=0.05,
                    progress=lambda *_: None,
                    cancelled=lambda: False,
                    environment_type="port_operations",
                )
                evaluate(name, policy, seed, "budget_only_ablation", episodes)
    env = PortOperationsEnvironment(test, parameters, horizon_steps=24, seed=1, split_name="test", render_mode=None)
    env.reset(start_index=0)
    twin = copy.deepcopy(env)
    env.previous_action_factor = 0.65
    twin.previous_action_factor = 1.30
    identical_state = env.state() == twin.state()
    _, reward_a, _, _ = env.step(2)
    _, reward_b, _, _ = twin.step(2)
    _, _, before = alg._port_pid_action(twin, alg.PIDPolicy(), 0.0, 0.0)
    report = {
        "schema": "xiaoyi-legacy-rl-diagnosis.v1",
        "dataset_id": definition.id,
        "dataset_sha256": old["dataset_sha256"],
        "legacy_source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in LEGACY_DIR.glob("*.py")},
        "rows": rows,
        "markov_alias_probe": {
            "same_observed_state": identical_state,
            "action": 2,
            "previous_factors": [0.65, 1.30],
            "different_rewards": [reward_a, reward_b],
            "gap": abs(reward_a - reward_b),
        },
        "observation_findings": [
            "Legacy state omits previous capacity factor although action-change reward depends on it.",
            "Legacy state omits time remaining in finite 24-step training episodes.",
            "Unseen state uses all-zero values and random tie selection.",
            "Legacy Double-Q behavior selects from primary table only; evaluation uses sum of two tables.",
            "Missing equipment/berth/weather inputs invoke declared defaults, not field measurements.",
        ],
        "scope": "Exploratory diagnosis on the previously viewed legacy holdout; cannot be relabeled a fresh confirmatory test.",
        "production_authority": False,
    }
    (folder / "legacy-diagnosis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    for variant in sorted({(r["variant"], r["episodes"], r["algorithm"]) for r in rows}, key=str):
        group = [r for r in rows if (r["variant"], r["episodes"], r["algorithm"]) == variant]
        print(
            variant,
            round(statistics.mean(r["test_metrics"]["score"] for r in group), 4),
            [r["test_state_coverage"] for r in group],
            flush=True,
        )
    print(report["markov_alias_probe"])


if __name__ == "__main__":
    main()
