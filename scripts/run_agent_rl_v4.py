"""Versioned curriculum configuration of the audited action-RL runner.

The V3 source and evidence remain untouched. This process explicitly supplies
V4 task/environment factories to the shared runner; checkpoints and protocol
hashes include this configuration code. No treatment gets a runtime rule fallback.
"""

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_agent_rl_v3 as runner  # noqa: E402
from app.agent_training.environment_v3 import DynamicTask, task_splits, teacher_action  # noqa: E402
from app.agent_training.environment_v4 import REVISION, ReadableEnvironment  # noqa: E402


@dataclass(frozen=True)
class CurriculumTask(DynamicTask):
    initial_history: tuple = ()


class CurriculumEnvironment(ReadableEnvironment):
    def __init__(self, task):
        super().__init__(task)
        for action in task.initial_history:
            row = self.step(action)
            row["model_action"] = False
            row["origin"] = "reference_prefix_for_training_initialization"
        if self.done:
            raise ValueError("curriculum initialization must precede task completion")


def full_task(task):
    return CurriculumTask(**asdict(task))


def reference_path(task):
    env = ReadableEnvironment(task)
    path = []
    while not env.done:
        label = teacher_action(env)
        path.append(label)
        env.step(label)
    if not env.success:
        raise ValueError("curriculum reference must solve the task")
    return path


def curriculum_splits():
    original = task_splits()
    result = {split: [full_task(t) for t in tasks] for split, tasks in original.items() if split != "train"}
    # Read timeout, port revision, lost receipt, traffic revision. The common
    # SFT demonstrations additionally cover stale cache, nominal and all toggles.
    selected = [original["train"][i] for i in [3, 7, 8, 11]]
    curriculum = []
    for distance in [2, 5, 99]:
        for task in selected:
            path = reference_path(task)
            prefix = tuple(path[:-distance]) if distance < len(path) else ()
            values = asdict(task)
            values["case_id"] += f"-tail{distance}"
            curriculum.append(CurriculumTask(**values, initial_history=prefix))
    result["train"] = curriculum
    return result


def common_demonstrations(_curriculum_tasks):
    records = []
    for original in task_splits()["train"]:
        task = full_task(original)
        env = CurriculumEnvironment(task)
        while not env.done:
            label = teacher_action(env)
            records.append(
                {
                    "task": asdict(task),
                    "prompt": env.prompt(),
                    "target": label,
                    "history": [r["choice"] for r in env.steps],
                    "origin": "common_full_training_task_reference_path",
                }
            )
            env.step(label)
    return records


def configure():
    # Explicit dependency injection is confined to this process. V3 commands
    # continue to import and use their original factories and protocol.
    runner.DynamicTask = CurriculumTask
    runner.DynamicEnvironment = CurriculumEnvironment
    runner.task_splits = curriculum_splits
    runner.demonstrations = common_demonstrations
    runner.REVISION = REVISION
    runner.SOURCES = runner.SOURCES + [
        "app/agent_training/environment_v4.py",
        "scripts/run_agent_rl_v4.py",
        "tests/test_agent_training_v4.py",
    ]


def prepare(args):
    runner.prepare(args)
    out = args.output
    cfg = runner.read(out / "config.json")
    cfg.update(
        {
            "schema": "xiaoyi-agent-rl.v4-curriculum-pilot",
            "warmup_updates": 256,
            "groups": 24,
            "cache_limit_gib": 4,
            "validation_milestones": [0, 8, 16, 24],
            "common_start_gate": "at least one of four end-to-end development tasks succeeds before RL",
            "curriculum": "4 task variants repeated twice at reference distance 2, then 5, then from task start",
            "initialization_source": "reference action prefixes initialize training states only, not counted as model execution",
            "evaluation": "always from empty initial state; no reference prefix or fallback",
            "common_demonstrations": "109 full-path training states over all 12 nominal/single-event tasks",
            "common_demonstrations_sha256": runner.sha(out / "common-demonstrations.json"),
            "rl_label_access": False,
            "new_prompt": "explicit completed/pending facts; future fault schedule absent; step budget enforced but not in model prompt",
            "adaptations": "manually scheduled reference-state curriculum, not the automatic reverse-curriculum paper algorithm",
            "feasibility_predecessor": str(out.parent / "experiment-005-pilot/feasibility-stop-decision.json"),
            "replay_adaptations": "same-query AND same-initial-history replay; fixed curriculum schedule, no difficulty buckets/retirement",
        }
    )
    cfg["groups_description"]["C_common_sft"] = (
        "prior strongest SFT + common 256-update readable dynamic-state adaptation"
    )
    runner.save(out / "config.json", cfg)
    runner.save(out / "schedule.json", [i for start in [0, 4, 8] for _ in range(2) for i in range(start, start + 4)])
    runner.save(
        out / "protocol-lock.json",
        {
            "config": runner.sha(out / "config.json"),
            "sources": runner.sha(out / "source-manifest.json"),
            "tasks": runner.sha(out / "task-manifest.json"),
            "schedule": runner.sha(out / "schedule.json"),
        },
    )
    runner.save(
        out / "STATUS.json",
        {
            "phase": "prepared",
            "final_test_opened": False,
            "schema": cfg["schema"],
            "groups_per_treatment": cfg["groups"],
        },
    )
    print("V4 configuration frozen before training", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "develop"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    configure()
    if args.command == "prepare":
        prepare(args)
        return
    cfg = runner.read(args.output / "config.json")
    if runner.sha(args.output / "common-demonstrations.json") != cfg["common_demonstrations_sha256"]:
        raise ValueError("common demonstration file changed after registration")
    original_evaluate = runner.evaluate

    def gated_evaluate(policy, out, cfg, phase, step):
        result = original_evaluate(policy, out, cfg, phase, step)
        if phase == "C_common_sft" and result["successes"] < 1:
            runner.log_status(
                out,
                "common_start_gate_failed",
                successes=0,
                n=result["n"],
                reason="common policy still cannot complete a development task; RL not started",
            )
            raise RuntimeError("common starting-policy feasibility gate failed")
        return result

    runner.evaluate = gated_evaluate
    runner.main()


if __name__ == "__main__":
    main()
