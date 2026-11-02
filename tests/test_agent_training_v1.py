from dataclasses import replace
import pytest

from app.agent_training.environment import FAMILIES, TaskEnvironment, make_task, reference_action, run_reference


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("split", ["train", "validation", "test"])
def test_reference_reaches_actual_postconditions(family, split):
    env = run_reference(make_task(split, family, 0))
    assert env.success and all(env.checks().values())
    assert env.report and env.steps[-1]["action"]["tool"] == "artifact.report"


def test_false_completion_is_rejected():
    env = TaskEnvironment(make_task("test", "joint", 0))
    result = env.step("J")
    assert not result["ok"] and not env.success and not env.report


def test_wrong_parameters_never_satisfy_task():
    env = TaskEnvironment(make_task("test", "energy_compare", 0))
    env.step("B")
    wrong = next(k for k in ["E", "F"] if env.actions[k]["arguments"]["green_preference"] != env.task.green)
    env.step(wrong)
    env.step("I")
    env.step("J")
    assert "energy" not in env.receipts and not env.success


def test_unknown_write_requires_readback_and_does_not_repeat_effect():
    env = TaskEnvironment(make_task("test", "write_recovery", 0))
    env.step("B")
    correct = reference_action(env)
    env.step(correct)
    assert env.uncertain and env.receipts["energy"]
    first = dict(env.receipts["energy"])
    failed = env.step(correct)
    assert not failed["ok"] and env.receipts["energy"] == first
    env.step("I")
    env.step("J")
    assert env.success and env.outcome()["recovered"]


def test_pause_requires_restore_before_completion():
    env = TaskEnvironment(make_task("test", "clock_restore", 0))
    env.step("B")
    env.step("G")
    env.step("I")
    env.step("J")
    assert not env.success
    env.step("H")
    env.step("I")
    env.step("J")
    assert env.success


def test_repeated_read_cannot_farm_positive_reward():
    env = TaskEnvironment(make_task("train", "port_read", 0))
    env.step("A")
    assert env.step("A")["reward"] < 0


def test_test_parameters_and_case_ids_not_in_training():
    train = [make_task("train", f, i) for f in FAMILIES for i in range(6)]
    test = [make_task("test", f, i) for f in FAMILIES for i in range(3)]
    assert not {t.case_id for t in train} & {t.case_id for t in test}
    assert not {t.green for t in train} & {t.green for t in test}


def test_terminal_budget_is_enforced():
    env = TaskEnvironment(replace(make_task("test", "joint", 0), max_steps=2))
    env.step("M")
    env.step("M")
    assert env.done and not env.success
    with pytest.raises(RuntimeError):
        env.step("A")
