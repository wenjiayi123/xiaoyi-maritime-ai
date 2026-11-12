from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.agent_training.expert_environment import ExpertTask, RecordedEnergyProvider, ExpertEnvironment, reference_action
from app.agent_training.expert_observation_v2 import ObservedFactsEnvironment
from app.agent_training.registered_receipts import read_receipt

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / '.codex_artifacts/agent-rl-expert-expansion-20261102/continuation-002/tasks-003/train/tasks.json'


def cases():
    return json.loads(TRAIN.read_text())


def environment(cls, case):
    return cls(ExpertTask(**case['task']), RecordedEnergyProvider([read_receipt(p) for p in case['receipt_files']]))


@pytest.mark.parametrize('index', [0, 1, 2, 3])
def test_prompt_has_all_actions_no_case_id(index):
    c = cases()[index]
    env = environment(ObservedFactsEnvironment, c)
    prompt = env.prompt()
    assert c['task']['case_id'] not in prompt
    assert all(letter + '=' + name in prompt for letter, name in env.menu().items())
    assert '最近三个已执行工具=' in prompt


def test_future_events_and_labels_cannot_leak():
    c = cases()[0]
    changed = deepcopy(c)
    changed['task']['case_id'] = 'SECRET_FUTURE_ID'
    changed['task']['changed_requirements'] = {'min_carbon_reduction_pct': 99.123456}
    changed['task']['lose_response_candidates'] = [0, 1]
    assert environment(ObservedFactsEnvironment, c).prompt() == environment(ObservedFactsEnvironment, changed).prompt()


def test_all24_training_transitions_rewards_and_outcomes_unchanged():
    for c in cases():
        original, updated = environment(ExpertEnvironment, c), environment(ObservedFactsEnvironment, c)
        while not original.done:
            # Reference is only used in this engineering parity test, never by runner.
            action = reference_action(original)
            assert original.step(action) == updated.step(action)
            assert original.observation() == updated.observation()
        assert original.report == updated.report and original.success == updated.success


def test_wrong_model_action_not_overridden():
    env = environment(ObservedFactsEnvironment, cases()[0])
    transition = env.step('J')
    assert transition['label'] == 'J' and not env.success
