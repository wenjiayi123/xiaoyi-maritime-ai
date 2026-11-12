from collections import Counter
from copy import deepcopy
import json

import pytest

from scripts import agent_expert_recovery_support as support
from scripts.freeze_agent_expert_recovery import holdout
from scripts.run_agent_expert_recovery_queue import registry_contents


@pytest.fixture
def states():
    return support.read(support.DATA / "STATES.json")


def test_balanced_order_preserves_both_strata_and_all_records(states):
    schedule = support.balanced_order(states, 20261105)
    assert schedule == support.balanced_order(states, 20261105)
    by_id = {s["state_id"]: s for s in states}
    counts = Counter()
    for row in schedule:
        selected = [by_id[s] for s in row["states"]]
        assert len(selected) == 12 and sum(s["origin"] == "legacy_retention" for s in selected) == 4
        counts.update(s["target"] for s in selected if s["origin"] != "legacy_retention")
    assert len(schedule) == 512 and max(counts.values()) - min(counts.values()) <= 1
    assert {s for r in schedule for s in r["states"]} == set(by_id)


def test_schedule_endpoints_and_no_budget_overrun():
    cfg = dict(max_updates=512, lr_initial=2e-4, lr_final=2e-5)
    assert support.learning_rate(1, cfg) == cfg["lr_initial"]
    assert support.learning_rate(512, cfg) == cfg["lr_final"]
    values = [support.learning_rate(s, cfg) for s in range(1, 513)]
    assert all(a >= b for a, b in zip(values, values[1:]))
    with pytest.raises(ValueError):
        support.learning_rate(513, cfg)


@pytest.mark.parametrize(
    "gates,expected",
    [
        ([], False),
        ([dict(step=64, passed=True)], False),
        ([dict(step=64, passed=True), dict(step=128, passed=True)], True),
        ([dict(step=64, passed=True), dict(step=192, passed=True)], False),
        ([dict(step=64, passed=False), dict(step=128, passed=True)], False),
        ([dict(step=64, passed=True), dict(step=128, passed=False)], False),
    ],
)
def test_training_readiness_requires_consecutive_complete_gates(gates, expected):
    assert support.ready(gates) == expected


def test_actual_choice_cannot_be_substituted():
    with pytest.raises(ValueError):
        support.validate_choice("A", dict(probabilities=[0.0, 0.0, 0.0, 1.0] + [0.0] * 9))
    support.validate_choice("D", dict(probabilities=[0.0, 0.0, 0.0, 1.0] + [0.0] * 9))


def test_gate_retains_failed_loop_and_independently_replays(tmp_path, monkeypatch):
    monkeypatch.setattr(support, "resource_check", lambda out: None)
    case = support.read(support.DATA / "CASES.json")[0]
    gold = next(g for g in support.read(support.DATA / "TRAIN_GOLD.json") if g["case_id"] == case["task"]["case_id"])
    item = dict(kind="expert", case_id=case["task"]["case_id"], case=case, gold=gold)

    class WrongPolicy:
        def fingerprint(self):
            return "test-only-identity"

        def choose(self, prompt, **kwargs):
            return "D", dict(probabilities=[0.0, 0.0, 0.0, 1.0] + [0.0] * 9)

    result = support.training_gate(WrongPolicy(), [item], tmp_path, 64)
    assert not result["passed"] and result["rows"][0]["decisions"] == 18
    job = json.loads((tmp_path / "training-gates/step-00064" / f"{item['case_id']}.json").read_text())
    assert [s["choice"] for s in job["steps"]] == ["D"] * 18
    assert support.replay_gate(item, job)
    bad = deepcopy(job)
    bad["metrics"]["decision_correct"] = True
    with pytest.raises(ValueError):
        support.replay_gate(item, bad)


def test_holdout_labels_use_receipts_and_new_combinations_only():
    cases = support.read(support.DATA / "CASES.json")
    before = deepcopy(cases)
    rows, labels = holdout(cases)
    assert cases == before and len(rows) == 12 and len({r["task"]["case_id"] for r in rows}) == 12
    assert sum(g["expected_outcome"] == "verified_candidate_recommended" for g in labels) == 8
    assert {r["source_training_configuration"] for r in rows} == {1, 3, 5}
    for row in rows:
        for train in cases:
            assert (
                row["task"]["requirements"],
                row["task"]["changed_requirements"],
                row["task"]["scripted_replies"],
            ) != (
                train["task"]["requirements"],
                train["task"]["changed_requirements"],
                train["task"]["scripted_replies"],
            )


def test_registry_preserves_random_baseline_seed_and_all_old_aliases():
    original = support.read(support.REGISTRY)
    before = deepcopy(original)
    complete = dict(
        adapter="/new.safetensors",
        file_sha256="file",
        parameter_fingerprint="fp",
        parent_fingerprint="parent",
        updates=128,
        warm_ready=True,
    )
    new = registry_contents(original, complete)
    assert original == before and new["seed"] == original["seed"] == 20261102
    assert all(new["groups"][g] == value for g, value in original["groups"].items())
    assert len(new["groups"]) == 10 and "not_final_acceptance" in new["acceptance_status"]["C_expert_warm3"]
