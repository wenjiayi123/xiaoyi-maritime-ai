from dataclasses import replace
import math

from app.agent_training.environment import FAMILIES, reference_action
from app.agent_training.environment_v2 import ProgressEnvironment, counterfactuals, make_task_v2


def test_all_families_reference_completes_and_shaping_telescopes():
    for family in FAMILIES:
        env = ProgressEnvironment(make_task_v2("train", family, 0))
        while not env.done:
            env.step(reference_action(env))
        assert env.success
        assert math.isclose(sum(s["reward_components"]["potential_shaping"] for s in env.steps), 0, abs_tol=1e-12)
        assert env.steps[-1]["after"]["remaining_steps"] == env.task.max_steps - len(env.steps)


def test_partial_joint_reads_receive_progress_but_repeats_do_not():
    env = ProgressEnvironment(make_task_v2("train", "joint", 0))
    first, repeated = env.step("A"), env.step("A")
    assert first["reward"] > 0 and repeated["reward"] < 0
    assert first["reward_components"]["potential_shaping"] > 0
    assert repeated["reward_components"]["potential_shaping"] == 0


def test_two_step_return_credits_necessary_timeout_and_retry():
    env = ProgressEnvironment(make_task_v2("train", "read_recovery", 0))
    branches = counterfactuals(env)
    assert branches["B"]["first"]["reward"] < 0
    assert max(branches, key=lambda k: branches[k]["two_step_return"]) == "B"
    assert branches["B"]["following"]["B"]["ok"]
    assert not env.steps and not env.fault_triggered
    assert not branches["B"]["first"]["model_action"]


def test_all_terminal_failures_zero_potential():
    env = ProgressEnvironment(replace(make_task_v2("train", "joint", 0), max_steps=2))
    env.step("A")
    terminal = env.step("B")
    assert env.done and not env.success and terminal["potential_after"] == 0
    assert math.isclose(sum(s["reward_components"]["potential_shaping"] for s in env.steps), 0, abs_tol=1e-12)


def test_menu_distractors_have_both_directions_and_one_matching_candidate():
    offsets = set()
    for i in range(30):
        env = ProgressEnvironment(make_task_v2("train", "energy_compare", i))
        options = [a["arguments"] for a in env.actions.values() if a["tool"] == "energy.compare"]
        assert (
            sum(
                p["green_preference"] == env.task.green and p["carbon_price_cny_per_ton"] == env.task.carbon
                for p in options
            )
            == 1
        )
        offsets.update(
            1 if p["green_preference"] > env.task.green else -1
            for p in options
            if p["green_preference"] != env.task.green
        )
    assert offsets == {-1, 1}


def test_pending_feedback_is_factual_without_action_answer():
    env = ProgressEnvironment(make_task_v2("train", "joint", 0))
    env.step("A")
    assert "港口状态尚未读取" not in env.prompt()
    assert "能源状态尚未读取" in env.prompt()
    assert "正确动作" not in env.prompt()
