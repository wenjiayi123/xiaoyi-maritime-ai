from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.agent_training.expert_environment import (
    ExpertEnvironment,
    ExpertTask,
    RecordedEnergyProvider,
    reference_action,
)
from app.agent_training.expert_learning import GAMMA, counterfactuals, potential, shaped_step
from app.agent_training.artifact_path import artifact_path

DATA = Path(".codex_artifacts/agent-rl-expert-expansion-20261102/tasks-002/train/tasks.json")


def environment(index=0):
    case = json.loads(DATA.read_text())[index]
    receipts = [json.loads(artifact_path(p).read_bytes())["receipt"] for p in case["receipt_files"]]
    return ExpertEnvironment(ExpertTask(**case["task"]), RecordedEnergyProvider(receipts))


@pytest.mark.parametrize("index", [0, 1, 2, 3, 7, 14, 23])
@pytest.mark.parametrize("early_failure", [False, True])
def test_discounted_shaping_telescopes_without_changing_complete_return(index, early_failure):
    env = environment(index)
    initial = potential(env)
    raw = shaped = 0.0
    step = 0
    while not env.done:
        action = "J" if early_failure else reference_action(env)
        row = shaped_step(env, action)
        raw += GAMMA**step * row["raw_reward"]
        shaped += GAMMA**step * row["reward"]
        step += 1
    assert potential(env) == 0
    assert shaped == pytest.approx(raw - initial, abs=1e-12)


def test_repeated_read_has_lower_return_than_new_calculation():
    env = environment(1)
    env.step("D")
    before = deepcopy(env.observation())
    branches = counterfactuals(env)
    assert env.observation() == before
    assert max(branches[a]["two_step_return"] for a in "EF") > branches["D"]["two_step_return"]
    assert set(branches) == set("ABCDEFGHIJKLM")


def test_counterfactuals_reject_native_provider_before_any_write():
    env = environment()
    env.provider = object()
    with pytest.raises(ValueError, match="never execute native"):
        counterfactuals(env)


def test_potential_has_no_hidden_future_or_answer_access():
    env = environment(3)
    other = deepcopy(env)
    other.task.changed_requirements = {"max_cost_cny": 1}
    other.task.lose_response_candidates = (0, 1)
    other.task.scripted_replies = {"carbon_price_cny_per_ton": 999}
    assert potential(env) == potential(other)


def test_training_need_check_stops_after_first_failure_to_save_compute(tmp_path, monkeypatch):
    from scripts.train_agent_expert import preflight
    # The preflight simulation has its own experiment root and pause state.
    monkeypatch.setattr("scripts.train_agent_expert.EXPERT", tmp_path)

    class PrematureReportPolicy:
        calls = 0

        def choose(self, prompt, sample=False):
            self.calls += 1
            return "J", {"test_double": True}

        def fingerprint(self):
            return "unit-test-no-model"

    policy = PrematureReportPolicy()
    cases = json.loads(DATA.read_text())
    assert preflight(policy, cases, tmp_path / "check", tmp_path) is False
    assert policy.calls == 1
    summary = json.loads((tmp_path / "check/SUMMARY.json").read_text())
    assert summary["total"] == 1
    assert summary["correct"] == 0


def test_train_environment_rejects_sealed_evidence_before_reading_it():
    from scripts.prepare_agent_expert_training import environment as load_train

    case = json.loads(DATA.read_text())[0]
    case["receipt_files"] = ["/sealed-test/never-read.json"]
    with pytest.raises(ValueError, match="Held-out evidence"):
        load_train(case)
