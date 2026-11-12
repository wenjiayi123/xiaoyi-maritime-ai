"""Preserve data v1; balance training answer positions before any model run.

No candidate evidence, goals, rewards or sealed test cases are changed. Only
training candidate display order and the corresponding loss-event index move.
"""

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prepare_agent_expert_tasks as core  # noqa: E402


def balanced_cases(split, rows, *, builder=core.build_cases):
    cases, labels = builder(split, rows)
    if split != "train":
        return cases, labels
    single_choice_index = 0
    for case, label in zip(cases, labels):
        allowed = label["allowed_recommendation_indices"]
        if len(allowed) != 1:
            continue
        desired = single_choice_index % 2
        single_choice_index += 1
        if allowed[0] == desired:
            continue
        case["task"]["candidate_green_preferences"] = list(reversed(case["task"]["candidate_green_preferences"]))
        case["receipt_files"] = list(reversed(case["receipt_files"]))
        case["task"]["lose_response_candidates"] = [1 - i for i in case["task"]["lose_response_candidates"]]
        label["allowed_recommendation_indices"] = [desired]
    return cases, labels


def main():
    output = Path(sys.argv[sys.argv.index("--output") + 1])
    core.build_cases = balanced_cases
    core.main()
    path = Path(__file__)
    source_copy = output / "sources" / path.relative_to(ROOT)
    source_copy.write_bytes(path.read_bytes())
    parent = output.parent / "tasks-001"
    note = {
        "supersedes": str(parent.resolve()),
        "reason": "pre-model data audit found imbalanced training recommendation positions6/14 including ties",
        "correction": "alternate unique feasible answer position by reversing training candidate display order; same physical receipts and goals",
        "old_data_preserved": True,
        "model_runs_before_correction": 0,
        "sealed_test_tasks_byte_identical_to_v1": (output / "sealed-test/tasks.json").read_bytes()
        == (parent / "sealed-test/tasks.json").read_bytes(),
        "sealed_test_gold_byte_identical_to_v1": (output / "sealed-test/oracle-labels.json").read_bytes()
        == (parent / "sealed-test/oracle-labels.json").read_bytes(),
    }
    assert note["sealed_test_tasks_byte_identical_to_v1"] and note["sealed_test_gold_byte_identical_to_v1"]
    core.save(output / "PRETRAIN_DATA_CORRECTION.json", note)
    lock = json.loads((output / "DATA_LOCK.json").read_text())
    for p in [path, source_copy, output / "PRETRAIN_DATA_CORRECTION.json"]:
        lock["files"][str(p.resolve())] = hashlib.sha256(p.read_bytes()).hexdigest()
    core.save(output / "DATA_LOCK.json", lock)
    core.save(
        output / "READY.json",
        {
            "data_lock_sha256": hashlib.sha256((output / "DATA_LOCK.json").read_bytes()).hexdigest(),
            "data_frozen": True,
            "training_protocol_frozen": False,
        },
    )


if __name__ == "__main__":
    main()
