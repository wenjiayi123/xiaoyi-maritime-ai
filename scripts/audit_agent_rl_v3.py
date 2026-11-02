"""Read-only checks of committed V3 pilot evidence; never runs held-out tasks."""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.environment import LETTERS  # noqa: E402
from app.agent_training.environment_v3 import DynamicEnvironment, DynamicTask  # noqa: E402
from scripts.run_agent_rl_v3 import read, save, sha, verify_protocol  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    args = parser.parse_args()
    out = args.experiment
    verify_protocol(out)
    cfg = read(out / "config.json")
    warmup = sorted((out / "warmup").glob("step-*/COMMITTED.json"))
    for index, marker in enumerate(warmup, 1):
        path, commit = marker.parent, read(marker)
        update = read(path / "update.json")
        assert update["step"] == index
        assert sha(path / "resume.pt") == commit["resume_sha256"]
        assert sha(path / "adapter/adapter_model.safetensors") == commit["adapter_sha256"]
        assert math.isfinite(update["loss"]) and math.isfinite(update["gradient_norm"])
        assert all(math.isfinite(p) and 0 <= p <= 1 for p in update["probabilities"])
        assert abs(sum(update["probabilities"]) - 1) < 1e-5
    rows, checked = [], 0
    for phase in ["D_drgrpo", "E_more_sft", "F_experience"]:
        previous_fingerprint = None
        for marker in sorted((out / phase).glob("step-*/COMMITTED.json")):
            path = marker.parent
            commit = read(marker)
            assert sha(path / "resume.pt") == commit["resume_sha256"]
            assert sha(path / "adapter/adapter_model.safetensors") == commit["adapter_sha256"]
            summary = read(path / "summary.json")
            trajectories = read(path / "trajectories.json")
            samples = read(path / "training-samples.json")
            arithmetic = read(path / "arithmetic.json")
            assert len(samples) == len(arithmetic) == summary["gradient_action_positions"]
            for trajectory in trajectories:
                task = DynamicTask(**trajectory["task"])
                assert task.split == "train"
                env = DynamicEnvironment(task)
                total = 0.0
                for record in trajectory["steps"]:
                    assert record["prompt"] == env.prompt()
                    action = record["choice"]
                    meta = record["policy"]
                    assert abs(sum(meta["probabilities"]) - 1) < 1e-5
                    p = meta["probabilities"][LETTERS.index(action)]
                    assert abs(math.log(p) - meta["log_probability"]) < 1e-5
                    transition = env.step(action)
                    # Python 3.12 uses improved float summation; training uses
                    # 3.9. Compare reward arithmetic within 1e-12, while all
                    # states, actions, components and source metadata stay exact.
                    actual, recorded = dict(transition), dict(record["transition"])
                    assert abs(actual.pop("reward") - recorded.pop("reward")) < 1e-12
                    assert json.dumps(actual, sort_keys=True) == json.dumps(recorded, sort_keys=True)
                    total += transition["reward"]
                    checked += 1
                assert env.done and env.success == trajectory["success"]
                assert abs(total - trajectory["return"]) < 1e-6
                assert asdict(env.task) == trajectory["task"]
            computed = 0.0
            for sample, calc in zip(samples, arithmetic):
                lp = calc["log_probs"]
                q = sample["reference_probs"]
                kl = sum(math.exp(p) * (p - math.log(max(v, 1e-30))) for p, v in zip(lp, q))
                if phase == "E_more_sft":
                    surrogate = -lp[LETTERS.index(sample["target"])]
                else:
                    assert "target" not in sample
                    adv = sample["advantage"]
                    ratio = math.exp(lp[LETTERS.index(sample["choice"])] - sample["policy"]["log_probability"])
                    assert abs(ratio - calc["ratio"]) < 1e-4 * max(1, ratio)
                    if sample["replay"]:
                        surrogate = -adv * ratio / (ratio + cfg["replay_beta"])
                    else:
                        surrogate = -min(adv * ratio, adv * max(1 - cfg["clip"], min(1 + cfg["clip"], ratio)))
                expected = surrogate + cfg["kl_coefficient"] * kl
                assert abs(expected - calc["loss"]) < 1e-4, (expected, calc)
                computed += expected
            assert abs(computed / summary["normalization"] - summary["loss"]) < 1e-4
            assert summary["before_fingerprint"] == (previous_fingerprint or summary["common_fingerprint"])
            previous_fingerprint = summary["after_fingerprint"]
            if phase == "E_more_sft":
                d = read(out / "D_drgrpo" / path.name / "summary.json")
                assert d["gradient_action_positions"] == summary["gradient_action_positions"]
                assert d["common_fingerprint"] == summary["common_fingerprint"]
            rows.append(
                {
                    "phase": phase,
                    "step": summary["step"],
                    "replayed_actions": len(samples),
                    "passed": True,
                    "parameters_changed": summary["before_fingerprint"] != summary["after_fingerprint"],
                }
            )
    result = {
        "passed": True,
        "committed_updates": len(rows),
        "audited_common_sft_updates": len(warmup),
        "parameter_changing_treatment_updates": sum(r["parameters_changed"] for r in rows),
        "checked_trajectory_actions": checked,
        "checks": rows,
        "test_evaluated": False,
        "E_reward_caveat": "E update returns/successes describe reused D training data, never E policy performance",
        "boundary": "source/checkpoint/replay/loss audit; does not prove RL superiority or validate live port outcomes",
    }
    signature = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:10]
    path = out / "audits" / f"audit-v2-warmup-{len(warmup):03d}-committed-{len(rows):03d}-{signature}.json"
    if not path.exists():
        save(path, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
