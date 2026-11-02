"""Tampered scores and action evidence must not pass the retention audit."""

import copy
import json

import pytest

from scripts.audit_agent_rl_v2 import audit_independent_retention, sha


@pytest.fixture
def retention_evidence(tmp_path):
    def put(name, value):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value))

    questions = [{"id": "probe-1", "prompt": "Synthetic test fixture", "expected": "B", "category": "fixture"}]
    put("retention-holdout-questions.json", questions)
    put("checkpoint-selection.json", {"fixture": True})
    put("test-opened.json", {"at": "2026-11-02T10:01:00+08:00"})
    manifest = {
        "at": "2026-11-02T10:00:00+08:00",
        "count": 1,
        "questions_sha256": sha(tmp_path / "retention-holdout-questions.json"),
        "used_for_training": False,
        "used_for_checkpoint_selection": False,
    }
    put("retention-holdout-manifest.json", manifest)
    put(
        "retention-holdout-opened.json",
        {
            "manifest_sha256": sha(tmp_path / "retention-holdout-manifest.json"),
            "selection_sha256": sha(tmp_path / "checkpoint-selection.json"),
        },
    )
    data = {
        "questions_sha256": manifest["questions_sha256"],
        "selection_sha256": sha(tmp_path / "checkpoint-selection.json"),
        "groups": {},
    }
    result, decisions = {"weights": {}}, []
    for group, key in [("B_base", "initial"), ("C_sft", "sft"), ("D_rl", "rl"), ("E_more_sft", "more_sft")]:
        result["weights"][key] = key + "-fixture"
        row = {
            **questions[0],
            "group": group,
            "choice": "A",
            "correct": False,
            "parameter_sha256": result["weights"][key],
            "probabilities": [1.0] + [0.0] * 12,
        }
        recorded = {"rows": [row], "n": 1, "correct": 0, "accuracy": 0}
        data["groups"][group] = recorded
        put("retention-independent/" + group + ".json", recorded)
        decisions.append(row)
    put("retention-independent-summary.json", data)
    (tmp_path / "retention-holdout-decisions.jsonl").write_text("\n".join(map(json.dumps, decisions)))
    return tmp_path, result, data, decisions, put


def test_recomputed_retention_keeps_negative_results(retention_evidence):
    folder, result, data, _, _ = retention_evidence
    assert audit_independent_retention(folder, result) == data


def test_rejects_inflated_retention_even_when_all_summary_copies_agree(retention_evidence):
    folder, result, data, _, put = retention_evidence
    data["groups"]["D_rl"].update(correct=1, accuracy=1)
    put("retention-independent/D_rl.json", data["groups"]["D_rl"])
    put("retention-independent-summary.json", data)
    with pytest.raises(ValueError, match="score mismatch"):
        audit_independent_retention(folder, result)


def test_rejects_claimed_correct_answer_that_disagrees_with_model_probabilities(retention_evidence):
    folder, result, data, decisions, put = retention_evidence
    decisions = copy.deepcopy(decisions)
    decisions[2].update(choice="B", correct=True)
    data["groups"]["D_rl"] = {"rows": [decisions[2]], "n": 1, "correct": 1, "accuracy": 1}
    put("retention-independent/D_rl.json", data["groups"]["D_rl"])
    put("retention-independent-summary.json", data)
    (folder / "retention-holdout-decisions.jsonl").write_text("\n".join(map(json.dumps, decisions)))
    with pytest.raises(ValueError, match="action/answer mismatch"):
        audit_independent_retention(folder, result)
