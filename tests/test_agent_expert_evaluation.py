"""Evaluator checks use training receipts and explicit rule test doubles only."""

from copy import deepcopy
from pathlib import Path

import pytest

from app.agent_training.expert_environment import reference_action
from scripts.prepare_agent_expert_training import read, environment
from scripts.evaluate_agent_expert import run_episode, summarize
from scripts.agent_expert_evaluation_support import audit_episode, validate_decision

DATA = Path(".codex_artifacts/agent-rl-expert-expansion-20261102/tasks-002/train")


def fixture(index):
    case = read(DATA / "tasks.json")[index]
    gold = next(x for x in read(DATA / "oracle-labels.json") if x["case_id"] == case["task"]["case_id"])
    return case, gold


def response(action, group="unit", fingerprint="unit-no-model"):
    return {
        "choice": action,
        "group": group,
        "adapter_sha256": fingerprint,
        "decision_mode": "causal_lm_constrained_next_token",
        "probabilities": [float(a == action) for a in "ABCDEFGHIJKLM"],
    }


def reference_double(case):
    env = environment(case)

    def decide(prompt, group):
        assert prompt == env.prompt()
        action = reference_action(env)
        env.step(action)
        return response(action, group)

    return decide


@pytest.mark.parametrize("index", [4, 5, 6, 7, 1])
def test_four_families_and_infeasible_separate_metrics(tmp_path, index):
    case, gold = fixture(index)
    row = run_episode(case, gold, "unit", "unit-no-model", tmp_path / "attempt", decide=reference_double(case))
    assert row["metrics"]["decision_correct"]
    assert row["metrics"]["business_complete"] == bool(gold["allowed_recommendation_indices"])
    assert row["audit"]["passed"]
    if case["family"] == "clarification":
        assert row["metrics"]["clarification_correct"]
    if case["family"] == "unknown_receipt":
        assert row["metrics"]["receipt_recoveries"] == 1
    if case["family"] == "changed_goal":
        assert row["metrics"]["goal_changes_observed"] == 1
        assert row["metrics"]["final_goal_version"] == row["metrics"]["report_current_goal_version"] == 2


def test_model_wrong_report_is_preserved_as_failure(tmp_path):
    case, gold = fixture(4)
    row = run_episode(case, gold, "unit", "unit-no-model", tmp_path / "failure", decide=lambda p, g: response("J", g))
    assert row["metrics"]["decision_correct"] is False
    assert row["metrics"]["business_complete"] is False
    assert row["audit"]["passed"]  # Valid evidence of a model failure.


@pytest.mark.parametrize("field,value", [("adapter_sha256", "wrong"), ("choice", "B"), ("group", "wrong")])
def test_identity_or_argmax_tampering_rejected(field, value):
    data = response("A")
    data[field] = value
    with pytest.raises(ValueError, match="mismatch"):
        validate_decision(data, "unit", "unit-no-model")


def test_corrupted_transcript_rejected_without_model_call(tmp_path):
    case, gold = fixture(4)
    run_episode(case, gold, "unit", "unit-no-model", tmp_path / "attempt", decide=reference_double(case))
    job = read(tmp_path / "attempt/trajectory.json")
    job["steps"][0]["transition"]["reward"] = 99
    with pytest.raises(ValueError, match="does not replay"):
        audit_episode(job, tmp_path / "attempt", "unit-no-model")


def test_wrong_gold_does_not_create_success(tmp_path):
    case, gold = fixture(4)
    wrong = deepcopy(gold)
    wrong["expected_outcome"] = "no_registered_candidate_meets_requirements"
    row = run_episode(case, wrong, "unit", "unit-no-model", tmp_path / "attempt", decide=reference_double(case))
    assert not row["metrics"]["decision_correct"]


def test_existing_attempt_is_never_overwritten(tmp_path):
    case, gold = fixture(4)
    folder = tmp_path / "attempt"
    folder.mkdir()
    with pytest.raises(FileExistsError):
        run_episode(case, gold, "unit", "unit-no-model", folder, decide=lambda p, g: response("A", g))


def test_unattempted_cases_are_not_successes():
    p = {"groups": ["unit"], "scope": "unit"}
    out = summarize(p, [])
    assert not out["accepted"]
    assert out["groups"]["unit"]["new_sealed"]["unattempted"] == 24
    assert out["groups"]["unit"]["legacy_native"]["unattempted"] == 60


def test_native_snapshot_audit_and_tamper_detection(tmp_path, monkeypatch):
    from app.agent_training.expert_environment import RecordedEnergyProvider
    from scripts.prepare_agent_expert_training import save
    from scripts import evaluate_agent_expert as evaluator

    case, gold = fixture(6)
    receipts = [read(p)["receipt"] for p in case["receipt_files"]]

    class SnapshotTestDouble(RecordedEnergyProvider):
        mode = "actual_local_offline_energy_api"

        def __init__(self, folder):
            super().__init__(receipts)
            self.folder = folder

        def snapshot(self):
            for index, receipt in self.receipts.items():
                save(self.folder / f"candidate-{index}/energy-journal.json", {"receipt": receipt})

        def calculate(self, *args, **kwargs):
            result = super().calculate(*args, **kwargs)
            self.snapshot()
            return result

        def recover(self, *args):
            result = super().recover(*args)
            self.snapshot()
            return result

    monkeypatch.setattr(evaluator, "NativeEnergyProvider", SnapshotTestDouble)
    folder = tmp_path / "native-test-double"
    row = run_episode(case, gold, "unit", "unit-no-model", folder, native=True, decide=reference_double(case))
    assert row["audit"]["passed"]
    snapshot = next(folder.glob("tool-evidence/*/candidate-*/energy-journal.json"))
    snapshot.write_text("{}")
    with pytest.raises(ValueError, match="Raw evidence drift"):
        audit_episode(read(folder / "trajectory.json"), folder, "unit-no-model")
