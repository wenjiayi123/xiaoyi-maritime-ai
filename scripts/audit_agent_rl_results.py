"""Independently replay held-out action logs and derive comparable metrics.

Original training/evaluation records remain immutable. This audit does not make
model calls or change checkpoints, rewards, cases, or success outcomes.
"""

from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.environment import TaskEnvironment, TaskSpec, digest, reference_action  # noqa: E402


def audit(folder):
    original = folder / "summary.json"
    raw = json.loads(original.read_text())
    result = copy.deepcopy(raw)
    tasks = json.loads((folder / "tasks/test.json").read_text())
    expected = {t["case_id"]: t for t in tasks}
    if not expected or len(expected) != len(tasks):
        raise ValueError("test cases must be nonempty and unique")
    if set(result["groups"]) != {"A_rules", "B_base", "C_sft", "D_rl"}:
        raise ValueError("all four comparison groups are required")
    checks = []
    for name, group in result["groups"].items():
        if len(group["cases"]) != len(expected) or {r["case_id"] for r in group["cases"]} != set(expected):
            raise ValueError("groups do not use the same test cases")
        for case in group["cases"]:
            path = folder / "trajectories" / name / (case["case_id"] + ".json")
            trace = json.loads(path.read_text())
            if trace["task"] != expected[case["case_id"]]:
                raise ValueError("test task altered")
            if digest(trace["steps"]) != case["trajectory_sha256"]:
                raise ValueError("trajectory hash mismatch")
            env = TaskEnvironment(TaskSpec(**trace["task"]))
            for row in trace["steps"]:
                if name == "A_rules" and reference_action(env) != row["choice"]:
                    raise ValueError("rule baseline not reproduced")
                if env.actions[row["choice"]] != row["action"]:
                    raise ValueError("candidate/action expansion mismatch")
                rebuilt = env.step(row["choice"])
                for key in ["ok", "feedback", "reward"]:
                    if rebuilt[key] != row[key]:
                        raise ValueError("environment outcome mismatch: " + key)
            outcome = env.outcome()
            for key in [
                "success",
                "steps",
                "reward",
                "errors",
                "parameter_attempts",
                "parameter_correct",
                "fault_injected",
                "recovered",
                "checks",
            ]:
                matches = (
                    math.isclose(outcome[key], case[key], abs_tol=1e-12, rel_tol=0)
                    if key == "reward"
                    else outcome[key] == case[key]
                )
                if not matches:
                    raise ValueError("reported outcome mismatch: " + key)
            if name != "A_rules":
                if len(trace["decisions"]) != len(trace["steps"]):
                    raise ValueError("missing model decisions")
                for d, s in zip(trace["decisions"], trace["steps"]):
                    if d["label"] != s["choice"] or not math.isfinite(d["old_logp"]) or d["old_logp"] > 1e-6:
                        raise ValueError("invalid recorded model decision")
            task = trace["task"]
            case["parameter_matches"] = sum(
                row["action"]["tool"] == "energy.compare"
                and row["action"]["arguments"]
                == {
                    "baseline_green_preference": task["baseline"],
                    "green_preference": task["green"],
                    "carbon_price_cny_per_ton": task["carbon"],
                }
                for row in trace["steps"]
            )
            checks.append({"group": name, "case_id": case["case_id"], "reproduced": True})
        families = {
            f: [c for c in group["cases"] if c["family"] == f] for f in dict.fromkeys(t["family"] for t in tasks)
        }
        reconstructed = {
            "n": len(expected),
            "success_rate": sum(c["success"] for c in group["cases"]) / len(expected),
            "macro_success_rate": sum(sum(c["success"] for c in cases) / len(cases) for cases in families.values())
            / len(families),
            "mean_steps": sum(c["steps"] for c in group["cases"]) / len(expected),
            "by_family": {
                f: {
                    "n": len(cases),
                    "successes": sum(c["success"] for c in cases),
                    "success_rate": sum(c["success"] for c in cases) / len(cases),
                }
                for f, cases in families.items()
            },
        }
        for key, value in reconstructed.items():
            matches = (
                math.isclose(group[key], value, abs_tol=1e-12, rel_tol=0)
                if isinstance(value, float)
                else group[key] == value
            )
            if not matches:
                raise ValueError("aggregate metric mismatch: " + key)
        attempts = sum(c["parameter_attempts"] for c in group["cases"])
        group["parameter_attempts"] = attempts
        group["parameter_accuracy"] = (
            sum(c["parameter_matches"] for c in group["cases"]) / attempts if attempts else None
        )
        group["parameter_execution_success_rate"] = (
            sum(c["parameter_correct"] for c in group["cases"]) / attempts if attempts else None
        )
        assigned = [c for c in group["cases"] if c["family"] in {"read_recovery", "write_recovery"}]
        exposed = [c for c in assigned if c["fault_injected"]]
        group["fault_cases"] = len(assigned)
        group["fault_exposed_cases"] = len(exposed)
        group["recovery_rate"] = sum(c["recovered"] for c in assigned) / len(assigned) if assigned else None
        group["recovery_rate_among_exposed"] = sum(c["recovered"] for c in exposed) / len(exposed) if exposed else None
    c = {row["case_id"]: row for row in result["groups"]["C_sft"]["cases"]}
    d = {row["case_id"]: row for row in result["groups"]["D_rl"]["cases"]}
    result["paired_rl_effect"] = {
        "failure_to_success": sum(not c[k]["success"] and d[k]["success"] for k in c),
        "success_to_failure": sum(c[k]["success"] and not d[k]["success"] for k in c),
        "same_cases": len(c),
    }
    increment = result["groups"]["D_rl"]["success_rate"] - result["groups"]["C_sft"]["success_rate"]
    if result["rl_increment"] != increment:
        raise ValueError("RL improvement does not match verified cases")
    result["audit"] = {
        "schema": "xiaoyi-agent-result-audit.v1",
        "all_replayed": True,
        "trajectories": len(checks),
        "source_summary_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "source": "summary.json and per-case raw decision/action logs",
        "metrics": {
            "recovery_rate": "all assigned fault cases, including failures before reaching the fault",
            "parameter_accuracy": "exact match of all three requested parameters / all parameter attempts, regardless of other execution preconditions; null if none",
            "parameter_execution_success_rate": "parameter attempts accepted with their execution preconditions / all attempts",
        },
        "model_calls_made_during_audit": 0,
        "outcomes_modified": False,
        "floating_aggregate_absolute_tolerance": 1e-12,
        "tolerance_reason": "training uses Python 3.9 and audit uses Python 3.12; float-sum algorithms can differ at machine precision; individual step rewards remain exact",
    }
    training = [json.loads(line) for line in (folder / "training.jsonl").read_text().splitlines() if line.strip()]
    sft = [r for r in training if r["stage"] == "sft"]
    rl = [r for r in training if r["stage"] == "rl"]
    sampled_tasks = {
        json.loads(path.read_text())["task"]["case_id"] for path in (folder / "rollouts").glob("group-*.json")
    }
    result["training_counts"] = {
        "sft_steps": len(sft),
        "rl_sampling_groups": len(rl),
        "rl_optimizer_updates": sum(bool(r["updated"]) for r in rl),
        "rl_rollouts": sum(len(r["scores"]) for r in rl),
        "rl_unique_training_cases": len(sampled_tasks),
        "sft_step_seconds": sum(r["seconds"] for r in sft),
    }
    (folder / "evaluation-audit.json").write_text(
        json.dumps({"audit": result["audit"], "checks": checks}, ensure_ascii=False, indent=2) + "\n"
    )
    (folder / "audited-summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result["audit"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    print(json.dumps(audit(parser.parse_args().experiment), ensure_ascii=False))
