"""Verify the public evidence manifest and replay all 120 final test trajectories.

No model, training dependency, network access or live business service is needed.
Full weight and training-branch audit remains audit_agent_rl_v2.py on the ZIP.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.environment import LETTERS, TaskSpec, digest, reference_action  # noqa: E402
from app.agent_training.environment_v2 import ProgressEnvironment  # noqa: E402


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(folder):
    folder = folder.resolve()
    manifest = read(folder / "manifest.json")
    entries = manifest["files"]
    paths = [r["path"] for r in entries]
    require(len(set(paths)) == len(paths), "duplicate manifest path")
    for item in entries:
        path = (folder / item["path"]).resolve()
        require(path.is_relative_to(folder), "manifest path escapes evidence directory")
        payload = path.read_bytes()
        require(len(payload) == item["bytes"], f"size mismatch: {item['path']}")
        require(hashlib.sha256(payload).hexdigest() == item["sha256"], f"hash mismatch: {item['path']}")
    summary = read(folder / "audited-summary.json")
    tasks = read(folder / "tasks/test.json")
    require(digest(tasks) == read(folder / "task-manifest.json")["partitions"]["test"]["sha256"], "test manifest mismatch")
    expected = {t["case_id"]: t for t in tasks}
    require(len(expected) == 24, "expected 24 unique held-out tasks")
    require(set(summary["groups"]) == {"A_rules", "B_base", "C_sft", "D_rl", "E_more_sft"}, "five groups required")
    count = 0
    for name, group in summary["groups"].items():
        cases = group["cases"]
        require(len(cases) == len(expected) and {c["case_id"] for c in cases} == set(expected), "case coverage mismatch")
        for case in cases:
            trace = read(folder / "trajectories" / name / (case["case_id"] + ".json"))
            require(trace["task"] == expected[case["case_id"]], "task mismatch")
            require(digest(trace["steps"]) == case["trajectory_sha256"], "trajectory hash mismatch")
            require(trace["outcome"] == case, "recorded outcome mismatch")
            require(len(trace["steps"]) == len(trace["decisions"]), "missing decision evidence")
            env = ProgressEnvironment(TaskSpec(**trace["task"]))
            for step, decision in zip(trace["steps"], trace["decisions"]):
                require(decision["prompt"] == env.prompt() and decision["label"] == step["choice"], "decision mismatch")
                if name == "A_rules":
                    require(step["choice"] == reference_action(env) and not step["model_action"], "rule mismatch")
                else:
                    probabilities = decision["probabilities"]
                    require(len(probabilities) == 13 and all(math.isfinite(p) and p >= 0 for p in probabilities), "invalid probabilities")
                    require(math.isclose(sum(probabilities), 1, abs_tol=2e-6), "probabilities do not sum to one")
                    choice = LETTERS[max(range(13), key=lambda i: probabilities[i])]
                    require(step["choice"] == choice and step["model_action"], "model argmax mismatch")
                rebuilt = env.step(step["choice"])
                for key in ["action", "ok", "feedback", "reward", "reward_components", "after", "result"]:
                    require(rebuilt[key] == step[key], f"transition mismatch: {key}")
            outcome = env.outcome()
            for key in ["success", "steps", "errors", "parameter_attempts", "parameter_correct", "fault_injected", "recovered", "checks"]:
                require(outcome[key] == case[key], f"outcome mismatch: {key}")
            require(math.isclose(outcome["reward"], case["reward"], abs_tol=1e-12, rel_tol=0), "reward mismatch")
            count += 1
        require(group["n"] == len(cases), "group denominator mismatch")
        require(group["successes"] == sum(c["success"] for c in cases), "group success count mismatch")
        require(group["success_rate"] == group["successes"] / len(cases), "success rate mismatch")
        require(group["mean_steps"] == sum(c["steps"] for c in cases) / len(cases), "mean calls mismatch")
    require(math.isclose(summary["rl_increment"], summary["groups"]["D_rl"]["success_rate"] - summary["groups"]["C_sft"]["success_rate"], abs_tol=1e-12), "RL increment mismatch")
    return {"passed": True, "manifest_files": len(entries), "trajectories_replayed": count,
            "successes": {k: v["successes"] for k, v in summary["groups"].items()},
            "model_calls": 0, "external_API_calls": 0, "weights_and_training_branches_audited": False}


if __name__ == "__main__":
    print(json.dumps(verify(ROOT / "reports/agent-rl/20261102"), ensure_ascii=False, indent=2))
