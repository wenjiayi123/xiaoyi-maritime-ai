"""Exercise the new environment with declared reference rules, never a model."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.expert_environment import (  # noqa: E402
    ExpertEnvironment,
    ExpertTask,
    NativeEnergyProvider,
    RecordedEnergyProvider,
    reference_action,
)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-evidence", type=Path, required=True)
    parser.add_argument("--include-native", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    receipts, source_hashes = [], {}
    for name in ("trial-1", "trial-2"):
        path = args.native_evidence / name / "energy-journal.json"
        receipts.append(json.loads(path.read_text())["receipt"])
        source_hashes[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
    goal = "比较登记的两个能碳候选，缺少条件先补问；按当前约束核验，说明达标方案或当前候选均不满足。"
    requirements = {"min_carbon_reduction_pct": 0.0, "max_cost_cny": 1e9, "min_service_pct": 98.0}
    base = {
        "goal": goal,
        "candidate_green_preferences": (0.82, 0.5),
        "baseline_green_preference": 0.5,
        "carbon_price_cny_per_ton": 85.0,
        "requirements": requirements,
    }
    cases = [
        ("feasible", {}, "verified_candidate_recommended"),
        (
            "registered_candidates_infeasible",
            {"requirements": {**requirements, "min_carbon_reduction_pct": 10.0}},
            "no_registered_candidate_meets_requirements",
        ),
        (
            "clarify_then_continue",
            {"carbon_price_cny_per_ton": None, "scripted_replies": {"carbon_price_cny_per_ton": 85.0}},
            "verified_candidate_recommended",
        ),
        ("await_real_user_reply", {"requirements": None}, "awaiting_user_clarification"),
        ("unknown_receipt", {"lose_response_candidates": (0,)}, "verified_candidate_recommended"),
        (
            "changed_goal",
            {"changed_requirements": {**requirements, "max_cost_cny": 570000.0}, "change_after_calculations": 2},
            "no_registered_candidate_meets_requirements",
        ),
    ]
    if args.include_native:
        cases.append(
            (
                "native_loss_and_goal_change",
                {
                    "lose_response_candidates": (0,),
                    "changed_requirements": {**requirements, "max_cost_cny": 570000.0},
                    "change_after_calculations": 2,
                },
                "no_registered_candidate_meets_requirements",
            )
        )
    results = []
    for name, overrides, expected in cases:
        task = ExpertTask(case_id=name, **{**base, **overrides})
        folder = args.output / name
        provider = (
            NativeEnergyProvider(folder / "native") if name.startswith("native_") else RecordedEnergyProvider(receipts)
        )
        environment = ExpertEnvironment(task, provider)
        rows = []
        while not environment.done:
            prompt = environment.prompt()
            choice = reference_action(environment)
            row = environment.step(choice)
            rows.append(
                {
                    "prompt": prompt,
                    "choice": choice,
                    "decision_producer": "engineering_reference_rules",
                    "model_action": False,
                    "transition": row,
                }
            )
            save(folder / "trajectory.json", {"task": asdict(task), "steps": rows, "report": environment.report})
        result = {
            "case": name,
            "outcome": environment.outcome,
            "expected_outcome": expected,
            "expected_decision_observed": environment.outcome == expected,
            "business_complete": environment.business_complete,
            "clarification_correct": environment.clarification_correct,
            "model_calls": 0,
            "decision_producer": "engineering_reference_rules",
            "steps": len(rows),
            "provider_mode": provider.mode,
        }
        results.append(result)
        save(folder / "RESULT.json", result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    summary = {
        "time": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "all_expected_decisions_observed": all(r["expected_decision_observed"] for r in results),
        "model_calls": 0,
        "training_updates": 0,
        "source_receipt_files": source_hashes,
        "scope": "engineering environment verification; not model evaluation, not final test, not independent physical scenarios",
        "physical_trial_windows": 1,
        "training_protocol_frozen": False,
    }
    save(args.output / "SUMMARY.json", summary)
    if not summary["all_expected_decisions_observed"]:
        raise SystemExit("environment outcome mismatch; retain failure and inspect before training")


if __name__ == "__main__":
    main()
