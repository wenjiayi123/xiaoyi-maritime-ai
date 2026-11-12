"""Freeze task data only; do not train or open a language-model final evaluation.

New parameter/constraint combinations are held out. Physical trajectory overlap
is disclosed: the existing native solver exposes one known 24-hour window.
"""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.expert_contracts import assess_energy_option  # noqa: E402
from app.agent_training.expert_energy import check_receipt, digest  # noqa: E402
from app.agent_training.expert_environment import (  # noqa: E402
    ExpertTask,
    ExpertEnvironment,
    RecordedEnergyProvider,
    reference_action,
)

FAMILIES = ("clarification", "multiple_constraints", "unknown_receipt", "changed_goal")


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def build_cases(split, rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["config_index"], []).append(row)
    cases, labels = [], []
    for config_index, group in sorted(grouped.items()):
        group.sort(key=lambda r: r["candidate_index"])
        if len(group) != 2:
            raise ValueError("two candidate receipts required")
        receipts = [json.loads(Path(row["receipt_file"]).read_text())["receipt"] for row in group]
        all_facts = [check_receipt(receipt, receipt["parameters"]) for receipt in receipts]
        baseline, carbon = (
            group[0]["parameters"]["baseline_green_preference"],
            group[0]["parameters"]["carbon_price_cny_per_ton"],
        )
        costs = [facts[1]["cost_cny"] for facts in all_facts]
        reductions = [
            (facts[0]["carbon_kg"] - facts[1]["carbon_kg"]) / facts[0]["carbon_kg"] * 100 for facts in all_facts
        ]
        # Modest achievable goals are constructed from native evidence, not
        # a fabricated10% target. These are declared curriculum task goals,
        # never measurements of gains caused by the language model.
        primary = {"max_cost_cny": round(max(costs) + 1000 + config_index * 25, 3), "min_service_pct": 98.0}
        if max(reductions) > 0:
            primary["min_carbon_reduction_pct"] = round(max(reductions) * (0.4 if split == "train" else 0.6), 6)
        cost_only = {
            "max_cost_cny": round((sum(costs) / 2 if config_index % 2 else min(costs) - 200), 3),
            "min_service_pct": 98.0,
        }
        for family_index, family in enumerate(FAMILIES):
            order = [0, 1] if (config_index + family_index) % 2 == 0 else [1, 0]
            ordered = [group[i] for i in order]
            goal = (
                "比较登记的两个能碳方案，按当前碳排、成本和作业完成率约束给出建议。缺少关键参数先询问；结果不明先查回执。"
                if split == "train"
                else "请核对这两个能碳候选能否满足我当前的要求，给出有依据的选择。条件不全请补问，调用没返回结果时先确认是否已完成。"
            )
            values = {
                "case_id": f"expert-{split}-{config_index:02d}-{family}",
                "goal": goal,
                "candidate_green_preferences": tuple(r["parameters"]["green_preference"] for r in ordered),
                "baseline_green_preference": baseline,
                "carbon_price_cny_per_ton": carbon,
                "requirements": primary,
                "max_steps": 18,
            }
            if family == "clarification":
                key = ("baseline_green_preference", "carbon_price_cny_per_ton", "requirements")[config_index % 3]
                values["scripted_replies"] = {key: values[key]}
                values[key] = None
            elif family == "multiple_constraints":
                values["requirements"] = cost_only
            elif family == "unknown_receipt":
                values["lose_response_candidates"] = (config_index % 2,)
            elif family == "changed_goal":
                values["changed_requirements"] = cost_only
                values["change_after_calculations"] = 2
            task = ExpertTask(**values)
            final_requirements = task.changed_requirements or task.requirements or task.scripted_replies["requirements"]
            statuses = [assess_energy_option(*all_facts[i], final_requirements)["status"] for i in order]
            valid = [i for i, status in enumerate(statuses) if status == "meets_registered_requirements"]
            expected = "verified_candidate_recommended" if valid else "no_registered_candidate_meets_requirements"
            if any(status == "needs_evidence" for status in statuses):
                raise ValueError("curriculum cannot hide missing evidence")
            cases.append(
                {
                    "task": asdict(task),
                    "family": family,
                    "configuration_index": config_index,
                    "receipt_files": [r["receipt_file"] for r in ordered],
                    "parameters_are_explicit_structured_input": True,
                }
            )
            labels.append(
                {
                    "case_id": task.case_id,
                    "expected_outcome": expected,
                    "allowed_recommendation_indices": valid,
                    "physical_window_id": group[0]["window_id"],
                }
            )
    return cases, labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    corpus = json.loads((args.corpus / "COLLECTION_COMPLETE.json").read_text())
    if corpus["failures"] or len(corpus["rows"]) != 18:
        raise ValueError("complete native corpus required")
    train_rows = [r for r in corpus["rows"] if r["split"] == "train"]
    test_rows = [r for r in corpus["rows"] if r["split"] == "sealed_test"]
    train, train_labels = build_cases("train", train_rows)
    test, test_labels = build_cases("sealed_test", test_rows)
    assert len(train) == 24 and len(test) == 12
    # Exact parameter tuples are disjoint; do not misrepresent that as novel
    # physics when multiple solver requests yield identical trajectories/KPIs.
    def keys(rows):
        names = ("baseline_green_preference", "green_preference", "carbon_price_cny_per_ton")
        return {tuple(r["parameters"][k] for k in names) for r in rows}
    assert not keys(train_rows) & keys(test_rows)
    demonstrations, train_checks = [], []
    for case, gold in zip(train, train_labels):
        task = ExpertTask(**case["task"])
        receipts = [json.loads(Path(p).read_text())["receipt"] for p in case["receipt_files"]]
        environment = ExpertEnvironment(task, RecordedEnergyProvider(receipts))
        history = []
        while not environment.done:
            label = reference_action(environment)
            demonstrations.append(
                {
                    "case_id": task.case_id,
                    "history": history.copy(),
                    "prompt": environment.prompt(),
                    "target": label,
                    "producer": "declared engineering reference policy for SFT demonstrations",
                }
            )
            environment.step(label)
            history.append(label)
        passed = environment.outcome == gold["expected_outcome"] and environment.success
        train_checks.append(
            {
                "case_id": task.case_id,
                "expected_decision_observed": passed,
                "outcome": environment.outcome,
                "business_complete": environment.business_complete,
                "steps": len(history),
            }
        )
        if not passed:
            save(args.output / "FAILED_TRAIN_ENVIRONMENT.json", train_checks)
            raise ValueError("training environment reference audit failed")
    save(args.output / "train/tasks.json", train)
    save(args.output / "train/oracle-labels.json", train_labels)
    save(args.output / "train/demonstrations.json", demonstrations)
    save(args.output / "train/ENVIRONMENT_AUDIT.json", train_checks)
    save(args.output / "sealed-test/tasks.json", test)
    save(args.output / "sealed-test/oracle-labels.json", test_labels)
    def unit(row):
        return digest(row["candidate"])
    unique_train = {unit(r) for r in train_rows}
    unique_test = {unit(r) for r in test_rows}
    audit = {
        "time": datetime.now(timezone.utc).isoformat(),
        "train_tasks": len(train),
        "sealed_test_tasks": len(test),
        "train_configurations": 6,
        "heldout_configurations": 3,
        "families": list(FAMILIES),
        "sft_step_demonstrations": len(demonstrations),
        "native_comparisons": 18,
        "physical_windows": len(corpus["physical_windows"]),
        "unique_candidate_business_metric_vectors": len(unique_train | unique_test),
        "metric_vectors_shared_across_splits": len(unique_train & unique_test),
        "parameter_tuple_overlap": 0,
        "train_outcome_distribution": dict(Counter(r["expected_outcome"] for r in train_labels)),
        "sealed_test_outcome_distribution": dict(Counter(r["expected_outcome"] for r in test_labels)),
        "valid_choice_positions": {
            split: dict(Counter(str(i) for row in labels for i in row["allowed_recommendation_indices"]))
            for split, labels in [("train", train_labels), ("sealed_test", test_labels)]
        },
        "training_reference_checks_passed": all(row["expected_decision_observed"] for row in train_checks),
        "sealed_test_environment_rollouts": 0,
        "model_calls": 0,
        "training_updates": 0,
        "holdout_claim": "new parameter/constraint and tool-decision configurations on one known offline physical window; not independent ports, unseen trajectories or unseen task families",
        "explicit_limitations": [
            f"{len(corpus['rows'])}comparisons collapse to{len(unique_train | unique_test)}business metric vectors",
            "carbon price affects separate settlement but is not part of the selected dispatch-cost metric",
            "structured input and numerical assessment are deterministic; model chooses tools",
            "scripted clarification replies and goal changes are controlled task conditions",
            "no model generalization result yet",
        ],
        "acceptance_categories": [
            "correct recommendation with verified goal satisfaction",
            "correct explanation that no registered candidate meets requirements",
            "awaiting clarification or evidence gap counted separately, never as completed operations",
        ],
    }
    save(args.output / "DATA_AUDIT.json", audit)
    sources = [
        Path(__file__),
        ROOT / "app/agent_training/expert_environment.py",
        ROOT / "app/agent_training/expert_energy.py",
        ROOT / "app/agent_training/expert_contracts.py",
    ]
    for p in sources:
        target = args.output / "sources" / p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(p.read_bytes())
    files = [p for p in args.output.rglob("*") if p.is_file()]
    external = (
        [Path(r["receipt_file"]) for r in corpus["rows"]]
        + [args.corpus / "COLLECTION_PLAN.json", args.corpus / "COLLECTION_COMPLETE.json"]
        + sources
    )
    manifest = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in files + external}
    save(
        args.output / "DATA_LOCK.json",
        {
            "time": audit["time"],
            "files": manifest,
            "data_frozen": True,
            "training_protocol_frozen": False,
            "instruction": "Do not alter data or use sealed tasks to train/tune; learning algorithm, trainer source and budget must be separately frozen before any model loading/training.",
        },
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
