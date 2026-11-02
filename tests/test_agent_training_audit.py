import json
from dataclasses import asdict

import pytest

from app.agent_training.environment import TaskEnvironment, digest, make_task, reference_action, run_reference
from scripts.audit_agent_rl_results import audit


@pytest.fixture
def experiment(tmp_path):
    tasks = [make_task("test", family, 0) for family in ["port_read", "read_recovery"]]
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks/test.json").write_text(json.dumps([asdict(t) for t in tasks]))
    groups = {}
    for name in ["A_rules", "B_base", "C_sft", "D_rl"]:
        folder = tmp_path / "trajectories" / name
        folder.mkdir(parents=True)
        cases = []
        for task in tasks:
            decisions = []
            if name == "A_rules":
                env = run_reference(task)
            else:
                env = TaskEnvironment(task)
                while not env.done:
                    label = "I" if name == "B_base" else reference_action(env)
                    decisions.append({"label": label, "old_logp": -0.1})
                    env.step(label)
            outcome = env.outcome()
            cases.append(outcome)
            (folder / f"{task.case_id}.json").write_text(
                json.dumps({"task": asdict(task), "steps": env.steps, "decisions": decisions})
            )
        rate = sum(c["success"] for c in cases) / len(cases)
        groups[name] = {
            "cases": cases,
            "n": len(cases),
            "success_rate": rate,
            "macro_success_rate": rate,
            "mean_steps": sum(c["steps"] for c in cases) / len(cases),
            "by_family": {
                c["family"]: {"n": 1, "successes": int(c["success"]), "success_rate": float(c["success"])}
                for c in cases
            },
        }
    (tmp_path / "summary.json").write_text(json.dumps({"groups": groups, "rl_increment": 0.0}))
    (tmp_path / "training.jsonl").write_text("")
    return tmp_path


def test_replay_audits_all_groups_and_uses_all_assigned_fault_cases(experiment):
    original = (experiment / "summary.json").read_bytes()
    result = audit(experiment)
    assert result["trajectories"] == 8
    assert (experiment / "summary.json").read_bytes() == original
    audited = json.loads((experiment / "audited-summary.json").read_text())
    base = audited["groups"]["B_base"]
    assert base["parameter_accuracy"] is None
    assert base["fault_cases"] == 1
    assert base["fault_exposed_cases"] == 0
    assert base["recovery_rate"] == 0
    assert base["recovery_rate_among_exposed"] is None


def test_rejects_inflated_aggregate_score(experiment):
    path = experiment / "summary.json"
    data = json.loads(path.read_text())
    data["groups"]["B_base"]["success_rate"] = 1.0
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="aggregate metric mismatch"):
        audit(experiment)


def test_float_sum_roundoff_allowed_but_changed_reward_rejected(experiment):
    path = experiment / "summary.json"
    data = json.loads(path.read_text())
    data["groups"]["D_rl"]["cases"][0]["reward"] += 1e-15
    path.write_text(json.dumps(data))
    audit(experiment)
    data["groups"]["D_rl"]["cases"][0]["reward"] += 0.001
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="reported outcome mismatch: reward"):
        audit(experiment)


def test_correct_arguments_with_missing_precondition_are_separate_metrics(experiment):
    task = make_task("test", "read_recovery", 0)
    env = TaskEnvironment(task)
    correct = next(
        k
        for k, a in env.actions.items()
        if a["tool"] == "energy.compare"
        and a["arguments"]["green_preference"] == task.green
        and a["arguments"]["carbon_price_cny_per_ton"] == task.carbon
    )
    env.step(correct)  # Correct arguments, but energy has not been read yet.
    while not env.done:
        env.step(reference_action(env))
    trace = {
        "task": asdict(task),
        "steps": env.steps,
        "decisions": [{"label": row["choice"], "old_logp": -0.1} for row in env.steps],
    }
    (experiment / "trajectories/C_sft" / f"{task.case_id}.json").write_text(json.dumps(trace))
    path = experiment / "summary.json"
    summary = json.loads(path.read_text())
    group = summary["groups"]["C_sft"]
    group["cases"][1] = env.outcome()
    group["mean_steps"] = sum(c["steps"] for c in group["cases"]) / 2
    path.write_text(json.dumps(summary))
    audit(experiment)
    group = json.loads((experiment / "audited-summary.json").read_text())["groups"]["C_sft"]
    assert group["parameter_accuracy"] == 1
    assert group["parameter_execution_success_rate"] == 0.5


def test_rejects_changed_action_even_if_trajectory_digest_updated(experiment):
    path = experiment / "trajectories/D_rl/test-port_read-000.json"
    trace = json.loads(path.read_text())
    trace["steps"][0]["action"]["tool"] = "energy.read"
    path.write_text(json.dumps(trace))
    summary_path = experiment / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["groups"]["D_rl"]["cases"][0]["trajectory_sha256"] = digest(trace["steps"])
    summary_path.write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="candidate/action expansion mismatch"):
        audit(experiment)
