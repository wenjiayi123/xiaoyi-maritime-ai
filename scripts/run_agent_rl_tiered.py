"""Versioned three-tier experiments using the existing audited CPU objective.

Prepare the shared source SFT once, then prepare each tier with its committed
adapter. Independent tests are not evaluated by this development runner.
"""

import argparse
from dataclasses import replace
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_agent_rl_v3 as runner  # noqa: E402
from app.agent_training.environment_tiered import (  # noqa: E402
    REVISION,
    TIERS,
    TieredEnvironment,
    TieredTask,
    common_source_tasks,
    demonstrations,
    task_splits,
    teacher_action,
)


def source_splits(seed):
    training = common_source_tasks(seed)
    validation = []
    for tier in TIERS:
        for i, task in enumerate(task_splits(tier, seed=seed)["validation"][:4]):
            validation.append(replace(task, menu_seed=101 + i if tier == "future" else 0))
    return {"train": training, "validation": validation, "test": [], "retention": []}


def configure(tier, seed):
    runner.DynamicTask = TieredTask
    runner.DynamicEnvironment = TieredEnvironment
    runner.teacher_action = teacher_action
    runner.task_splits = (lambda: source_splits(seed)) if tier == "common" else lambda: task_splits(tier, seed=seed)
    runner.demonstrations = demonstrations
    runner.REVISION = REVISION
    runner.SOURCES = runner.SOURCES + [
        "app/agent_training/environment_v4.py",
        "app/agent_training/environment_tiered.py",
        "scripts/run_agent_rl_tiered.py",
        "tests/test_agent_tiered_environment.py",
    ]


def prepare(args):
    runner.prepare(args)
    out = args.output
    cfg = runner.read(out / "config.json")
    common = args.tier == "common"
    if not common:
        parent = args.common.resolve() / "warmup/step-00512/adapter/adapter_model.safetensors"
        marker = parent.parent.parent / "COMMITTED.json"
        if not marker.exists() or runner.read(marker)["adapter_sha256"] != runner.sha(parent):
            raise ValueError("committed shared SFT parent is required")
        status = runner.read(args.common / "STATUS.json")
        if status["phase"] != "pilot_complete":
            raise ValueError("shared-source SFT must have finished its feasibility gate")
        cfg.update(
            parent_adapter=str(parent),
            parent_sha256=runner.sha(parent),
            parent_choice="fixed step512 shared source SFT, selected before tier results",
        )
    cfg.update(
        schema="xiaoyi-tiered-agent.v1",
        tier=args.tier,
        seed=args.seed,
        warmup_updates=512 if common else 0,
        groups=0 if common else 48,
        max_steps=24,
        cache_limit_gib=4,
        validation_milestones=[0] if common else [0, 8, 16, 24, 32, 40, 48],
        common_source_sft=common,
        curriculum=None,
        output_scope="13 displayed candidate tool/parameter calls; not unconstrained API generation",
        new_prompt="shared factual progress plus current observable tool-contract mapping",
        initialization_source="all trajectories start at task beginning, no teacher prefix",
        evaluation="development tasks only, from task start",
        pilot_primary="complete same-start D RL and E continued-SFT contrasts within each tier",
        future_scope="adaptation after controlled menu/source-timing shifts; same target contracts in adaptation train/dev/test, disjoint task instances",
        replay_adaptations="same task historical-success replay, two passes through24 instances; zero replay remains a valid observed result",
        common_demonstrations_sha256=runner.sha(out / "common-demonstrations.json"),
        final_acceptance_claim=False,
    )
    cfg["groups_description"]["C_common_sft"] = (
        "shared step512 source SFT on72 configurations; all treatment branches start here"
    )
    order = list(range(len(runner.task_splits()["train"])))
    random.Random(args.seed).shuffle(order)
    runner.save(out / "schedule.json", [] if common else order * 2)
    runner.save(out / "config.json", cfg)
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
            "tier": args.tier,
            "final_test_opened": False,
            "interpretation": "development feasibility only, no confirmed superiority claim",
        },
    )


def develop(args):
    import fcntl

    cfg = runner.read(args.output / "config.json")
    if runner.sha(args.output / "common-demonstrations.json") != cfg["common_demonstrations_sha256"]:
        raise ValueError("demonstration file drift")
    original = runner.evaluate

    def evaluate(policy, out, config, phase, step):
        result = original(policy, out, config, phase, step)
        if args.tier == "common" and phase == "C_common_sft" and result["successes"] < 3:
            runner.log_status(
                out,
                "source_sft_gate_failed",
                successes=result["successes"],
                n=result["n"],
                reason="shared starting policy below3/12 source-development feasibility threshold",
            )
            raise RuntimeError("source SFT needs improvement before tier comparisons")
        return result

    runner.evaluate = evaluate
    with (args.output / "trainer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runner.develop(args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "develop"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tier", choices=["common", *TIERS])
    parser.add_argument("--common", type=Path)
    parser.add_argument("--seed", type=int, default=20261102)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.command == "develop":
        config = runner.read(args.output / "config.json")
        args.tier, args.seed = config["tier"], config["seed"]
    if not args.tier or args.command == "prepare" and args.tier != "common" and not args.common:
        parser.error("prepare needs a tier and dependent tiers need --common")
    configure(args.tier, args.seed)
    prepare(args) if args.command == "prepare" else develop(args)


if __name__ == "__main__":
    main()
