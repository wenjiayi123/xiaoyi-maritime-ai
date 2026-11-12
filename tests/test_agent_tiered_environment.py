from dataclasses import replace

import pytest

from app.agent_training.environment_tiered import (
    TIERS,
    TieredEnvironment,
    common_source_tasks,
    demonstrations,
    reference_path,
    task_splits,
    teacher_action,
)


def test_all_tasks_are_solvable_and_partitions_have_disjoint_instances():
    identities = set()
    for tier in TIERS:
        splits = task_splits(tier)
        assert {k: len(v) for k, v in splits.items()} == {"train": 24, "validation": 8, "test": 24, "retention": 16}
        for split, tasks in splits.items():
            for task in tasks:
                # Retention intentionally shares the same simple questions across tiers.
                if split != "retention":
                    assert task.case_id not in identities
                    identities.add(task.case_id)
                assert len(reference_path(task)) <= task.max_steps
                env = TieredEnvironment(task)
                assert not env.step(next(k for k, a in env.actions.items() if a["tool"] == "artifact.report"))["ok"]


def test_future_schedule_and_permutation_seed_are_hidden_until_change():
    task = task_splits("future")["train"][0]
    a, b = TieredEnvironment(task), TieredEnvironment(replace(task, menu_seed=999, timed_revisions=((15, "port"),)))
    assert a.prompt() == b.prompt()
    for _ in range(task.switch_step):
        row = a.step(teacher_action(a))
    assert any(e["type"] == "tool_contract_changed" for e in row["external_events"])
    assert a.actions != a.base.actions
    assert "工具接口合同：已更新" in a.prompt()
    assert str(task.menu_seed) not in a.prompt()
    for external, action in a.actions.items():
        assert external + "=" in a.prompt()
        assert action == a.base.actions[a.mapping()[external]]


def test_timed_revision_invalidates_freshness_and_shaping_telescopes():
    task = task_splits("future")["train"][0]
    env = TieredEnvironment(task)
    initial = env.progress()
    while not env.done:
        env.step(teacher_action(env))
    assert env.success
    assert sum(r["reward_components"]["potential"] for r in env.steps) == pytest.approx(-0.5 * initial)
    events = [r for r in env.steps if any(e["type"] == "source_revision" for e in r["external_events"])]
    assert len(events) == 2
    assert all(not r["after"]["verified"] for r in events)
    for row in env.steps:
        assert row["reward"] == pytest.approx(sum(row["reward_components"].values()))


def test_demonstrations_replay_the_visible_contract_without_target_leakage():
    from app.agent_training.environment_tiered import TieredTask

    source = common_source_tasks()
    assert len(source) == 72
    assert {t.menu_seed for t in source if t.tier == "future"} == {101, 102, 103, 104}
    assert not ({101, 102, 103, 104} & {t.menu_seed for t in task_splits("future")["train"]})
    for record in demonstrations(source):
        env = TieredEnvironment(TieredTask(**record["task"]))
        for choice in record["history"]:
            env.step(choice)
        assert env.prompt() == record["prompt"]
        assert teacher_action(env) == record["target"]


def test_external_choices_stay_consistent_across_interface_changes():
    for task in task_splits("future")["train"][:4]:
        env = TieredEnvironment(task)
        while not env.done:
            letter = teacher_action(env)
            intended = env.actions[letter]
            row = env.step(letter)
            assert row["choice"] == letter and row["action"] == intended
