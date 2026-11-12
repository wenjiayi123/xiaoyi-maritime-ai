"""Finite, serial, preregistered RL versus continued-SFT comparison.

One shared source SFT, three paired training seeds, two treatment branches.
No learned held-out evaluation occurs before all six branches are committed.
"""

import argparse
from dataclasses import asdict
import datetime
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import file_lease as fcntl
from scripts import run_agent_rl_formal_core as core  # noqa: E402
from scripts import run_agent_rl_tiered_queue as lifecycle  # noqa: E402
from app.agent_training.environment_tiered import (  # noqa: E402
    TieredEnvironment, TieredTask, task_splits, demonstrations, teacher_action,
)

DEFAULT = ROOT / ".codex_artifacts/agent-rl-confirmatory-20261102"
COMMON = ROOT / ".codex_artifacts/agent-rl-tiered-20261102/common-001"
GROUPS = ("D_drgrpo", "E_more_sft")
SEEDS = (20261102, 20261103, 20261104)
TIERS = ("simple", "complex", "future")


def configure():
    core.DynamicTask = TieredTask
    core.DynamicEnvironment = TieredEnvironment
    core.teacher_action = teacher_action


def now():
    return datetime.datetime.now().astimezone().isoformat()


def status(base, phase, **fields):
    value = {"time": now(), "phase": phase, **fields}
    core.save(base / "QUEUE_STATUS.json", value)
    print(json.dumps(value, ensure_ascii=False), flush=True)


def schedule(seed):
    a, b = list(range(24)), list(range(24, 48))
    rng = random.Random(seed)
    rng.shuffle(a)
    rng.shuffle(b)
    return [i for pair in zip(a, b) for i in pair]


def prepare(base):
    if base.exists():
        raise ValueError("formal output must be new")
    base.mkdir(parents=True)
    # Same still-unopened benchmark as the prior registered tier design.
    splits = {tier: task_splits(tier, seed=20261102) for tier in TIERS}
    train = splits["complex"]["train"] + splits["future"]["train"]
    core.save(base / "tasks/train.json", [asdict(t) for t in train])
    for tier in TIERS:
        core.save(base / "tasks" / (tier + ".json"), [asdict(t) for t in splits[tier]["test"]])
    core.save(base / "tasks/retention.json", [asdict(t) for t in splits["simple"]["retention"]])
    core.save(base / "common-demonstrations.json", demonstrations(train))
    protocol = {
        "schema": "xiaoyi-formal-paired.v1", "created_at": now(),
        "reason": "user requested direct formal comparison and conserving local compute",
        "supersedes": "unstarted simple/complex/future development pilots; all prior evidence preserved",
        "common": str(COMMON), "common_lock_sha256": core.sha(COMMON / "protocol-lock.json"),
        "common_selector": "fixed warmup step512, source gate >=3/12, never best checkpoint",
        "common_parent_disclosure": "old004 E384 chosen using historical results; new tests remain unopened",
        "training_seeds": list(SEEDS), "training_groups": list(GROUPS),
        "train_instances": {"complex": 24, "future": 24}, "updates_per_group": 48,
        "schedule": "one pass, alternating shuffled complex and future cases; equal exposure at24 and48",
        "group_size": 4, "max_steps": 24, "temperature": 1.4,
        "learning_rate": 0.0001, "kl_coefficient": 0.02, "clip": 0.2,
        "checkpoint_selection": "fixed final step48 for both groups, no best-of-seed selection",
        "evaluation_nodes": [0, 24, 48], "training_validation": "none; log training only",
        "test_counts": {"simple": 24, "complex": 24, "future": 24, "retention": 16},
        "evaluation": "greedy from task start; all training and audits frozen before first test",
        "rules_and_common": "evaluate once; reuse identical baseline records for every paired seed",
        "primary_complex": {"minimum_mean_lift": 0.10, "interval_lower_bound": 0},
        "primary_future": {"minimum_normalized_auc_lift": 0.10, "interval_lower_bound": 0,
                           "minimum_final_success_rate": 0.80, "nodes": [0, 24, 48]},
        "statistics": {
            "method": "paired crossed bootstrap over training seeds and scenario clusters",
            "replicates": 20000, "seed": 9072026, "two_sided_confidence": 0.975,
            "multiple_comparisons": "Bonferroni for two predeclared alternative primary endpoints",
            "cluster": "shocks + require_restore + menu_seed + switch_step + timed_revisions",
            "within_cluster": "average all parameter variants before resampling; not independent replicates",
            "scope": "three seeds and a small synthetic scenario set; limited precision and external validity",
        },
        "retention_max_drop": 0.05,
        "acceptance": "at least one primary route, retention, audits, and native model closed loop",
        "native_candidate": "D_drgrpo seed20261102 step48 fixed in advance, no rule fallback",
        "fairness": "same parent, optimizer steps, gradient action positions; E receives oracle corrections on D states",
        "resource_accounting": "report oracle labels, calls, action positions, wall time separately; not equal wall time",
        "future_scope": "known target contracts601/602 after exposure; not zero-shot arbitrary API generation",
        "output_scope": "13 candidate tool/parameter calls; 11 tool types; simulated harness environment",
        "tests_reused_from_prior_design": True, "prior_model_test_access": False,
        "failure_policy": "preserve negative results; no post-test tuning or passing by changing thresholds",
        "production_authority": False,
    }
    core.save(base / "PROTOCOL.json", protocol)
    sources = list(core.read(COMMON / "source-manifest.json")) + [
        "scripts/run_agent_rl_formal_core.py", "scripts/run_agent_rl_confirmatory.py",
        "scripts/analyze_agent_rl_confirmatory.py", "scripts/run_agent_rl_tiered_queue.py",
        "scripts/audit_agent_rl_v3.py", "scripts/audit_agent_rl_tiered.py",
        "tests/test_agent_confirmatory.py", "tests/test_agent_tiered_queue.py",
    ]
    for source in dict.fromkeys(sources):
        target = base / "source" / source
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / source, target)
    core.save(base / "source-manifest.json", {s: core.sha(ROOT / s) for s in dict.fromkeys(sources)})
    files = ["PROTOCOL.json", "source-manifest.json", "common-demonstrations.json"]
    files += [str(p.relative_to(base)) for p in sorted((base / "tasks").glob("*.json"))]
    core.save(base / "LOCK.json", {p: core.sha(base / p) for p in files})
    status(base, "prepared", final_test_opened=False, acceptance_passed=False)


def verify(base):
    for p, expected in core.read(base / "LOCK.json").items():
        if core.sha(base / p) != expected:
            raise ValueError("formal protocol drift: " + p)
    for p, expected in core.read(base / "source-manifest.json").items():
        if core.sha(ROOT / p) != expected:
            raise ValueError("formal source drift: " + p)
    protocol = core.read(base / "PROTOCOL.json")
    if core.sha(COMMON / "protocol-lock.json") != protocol["common_lock_sha256"]:
        raise ValueError("shared source protocol drift")
    return protocol


def seed_dir(base, seed):
    return base / ("seed-" + str(seed))


def prepare_seed(base, seed):
    out = seed_dir(base, seed)
    if out.exists():
        core.verify_protocol(out)
        return out
    parent = COMMON / "warmup/step-00512/adapter/adapter_model.safetensors"
    marker = core.read(parent.parent.parent / "COMMITTED.json")
    if marker["adapter_sha256"] != core.sha(parent):
        raise ValueError("shared adapter integrity")
    if core.read(COMMON / "STATUS.json")["phase"] != "pilot_complete":
        raise ValueError("shared source gate has not passed")
    out.mkdir()
    cfg = core.read(COMMON / "config.json")
    cfg.update(schema="xiaoyi-formal-paired.v1", status="preregistered_formal_training", seed=seed,
               tier="mixed", warmup_updates=0, groups=48, training_groups=list(GROUPS),
               evaluate_common=False, validation_milestones=[], parent_adapter=str(parent),
               parent_sha256=core.sha(parent), parent_choice="fixed shared step512",
               common_source_sft=False, selection="fixed final step48",
               evaluation="sealed until all six branches finish; final three tiers and future step24",
               final_acceptance_claim=False)
    cfg["groups_description"] = {g: cfg["groups_description"][g] for g in GROUPS}
    core.save(out / "config.json", cfg)
    shutil.copy2(base / "source-manifest.json", out / "source-manifest.json")
    train = core.read(base / "tasks/train.json")
    core.save(out / "tasks/train.json", train)
    for split in ["validation", "test", "retention"]:
        core.save(out / "tasks" / (split + ".json"), [])
    core.save(out / "task-manifest.json", {
        split: {"count": len(rows), "sha256": core.digest(rows)}
        for split, rows in [("train", train), ("validation", []), ("test", []), ("retention", [])]
    })
    shutil.copy2(base / "common-demonstrations.json", out / "common-demonstrations.json")
    cfg["common_demonstrations_sha256"] = core.sha(out / "common-demonstrations.json")
    core.save(out / "config.json", cfg)
    core.save(out / "schedule.json", schedule(seed))
    core.save(out / "protocol-lock.json", {key: core.sha(out / file) for key, file in [
        ("config", "config.json"), ("sources", "source-manifest.json"),
        ("tasks", "task-manifest.json"), ("schedule", "schedule.json")]})
    core.save(out / "STATUS.json", {"phase": "prepared", "final_test_opened": False})
    return out


def training_inventory(base):
    manifest = {}
    for seed in SEEDS:
        out = seed_dir(base, seed)
        core.verify_protocol(out)
        for group in GROUPS:
            finish = core.read(out / group / "FINISHED.json")
            if finish["groups"] != 48:
                raise ValueError("incomplete training branch")
            for step in [24, 48]:
                path = out / group / ("step-%05d" % step)
                mark = core.read(path / "COMMITTED.json")
                adapter = path / "adapter/adapter_model.safetensors"
                if core.sha(adapter) != mark["adapter_sha256"]:
                    raise ValueError("checkpoint drift")
                if step == 48 and finish["fingerprint"] != mark["fingerprint"]:
                    raise ValueError("final fingerprint mismatch")
                manifest[str(adapter.relative_to(base))] = core.sha(adapter)
        for step in range(1, 49):
            d, e = [core.read(out / group / ("step-%05d/summary.json" % step)) for group in GROUPS]
            if d["common_fingerprint"] != e["common_fingerprint"] or d["gradient_action_positions"] != e["gradient_action_positions"]:
                raise ValueError("paired training budget mismatch")
        audits = list((out / "audits").glob("*.json"))
        if not any(core.read(p).get("passed") and core.read(p).get("committed_updates") == 96 for p in audits):
            raise ValueError("completed branch audit missing")
    return manifest


def evaluate_seed(base, seed):
    verify(base)
    if training_inventory(base) != core.read(base / "TRAINING_COMPLETE.json")["checkpoint_hashes"]:
        raise ValueError("all-seed training lock mismatch")
    configure()
    from app.agent_training.policy_v2 import CachedLanguagePolicy
    policy = CachedLanguagePolicy(cache_dir=base / "prefix-cache", threads=4, seed=seed, cache_limit_gib=4)
    cfg = core.read(seed_dir(base, seed) / "config.json")
    if not (base / "FINAL_TEST_OPENED.json").exists():
        core.save(base / "FINAL_TEST_OPENED.json", {"time": now(), "training_lock": core.sha(base / "TRAINING_COMPLETE.json"),
                                                   "no_further_training_allowed": True})

    def measure(group, step, adapter, tiers, folder):
        core.load_adapter(policy, adapter)
        fingerprint = policy.fingerprint()
        for tier in tiers:
            task_file = base / "tasks" / (tier + ".json")
            result_path = folder / (group + "-%05d-%s.json" % (step, tier))
            tasks = core.read(task_file)
            if result_path.exists():
                old = core.read(result_path)
                if old["fingerprint"] != fingerprint or old["tasks_sha256"] != core.sha(task_file):
                    raise ValueError("evaluation resume identity mismatch")
                continue
            records = []
            for index, value in enumerate(tasks):
                episode = folder / "episodes" / (group + "-%05d-%s-%03d.json" % (step, tier, index))
                if episode.exists() and not core.read(episode).get("in_progress"):
                    row = core.read(episode)
                    if row["behavior_fingerprint"] != fingerprint or row["task"] != value:
                        raise ValueError("episode resume identity mismatch")
                else:
                    if episode.exists():
                        episode.rename(episode.with_suffix(".interrupted-%d.json" % time.time_ns()))
                    row = core.collect(policy, TieredTask(**value), cfg, greedy=True, path=episode)
                records.append(row)
            core.save(result_path, {"phase": group, "seed": seed, "step": step, "tier": tier,
                                   "fingerprint": fingerprint, "tasks_sha256": core.sha(task_file),
                                   "n": len(records), "successes": sum(r["success"] for r in records),
                                   "trajectories": records})

    if seed == SEEDS[0]:
        measure("C_common_sft", 0, cfg["parent_adapter"], [*TIERS, "retention"], base / "baseline")
        for tier in [*TIERS, "retention"]:
            rows = []
            for task in core.read(base / "tasks" / (tier + ".json")):
                env = TieredEnvironment(TieredTask(**task))
                while not env.done:
                    env.step(teacher_action(env))
                rows.append({"case_id": task["case_id"], "success": env.success, "steps": len(env.steps)})
            core.save(base / "baseline" / ("A_rules-00000-" + tier + ".json"),
                      {"phase": "A_rules", "n": len(rows), "successes": sum(r["success"] for r in rows),
                       "model_used": False, "tasks": rows})
    out = seed_dir(base, seed)
    for group in GROUPS:
        for step, tiers in [(24, ["future"]), (48, [*TIERS, "retention"])]:
            measure(group, step, out / group / ("step-%05d/adapter/adapter_model.safetensors" % step),
                    tiers, out / "evaluation")


def child(base, command, log_name, **fields):
    if fields.get("stage") in ["formal_training", "sealed_evaluation"]:
        lifecycle.ensure_no_other_trainer()
        if lifecycle.health():
            raise RuntimeError("inference worker still active; refusing second model")
    with (base / log_name).open("a") as stream:
        proc = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        try:
            status(base, "running", child_pid=proc.pid, **fields)
            while proc.poll() is None:
                if (base / "PAUSE").exists():
                    raise RuntimeError("formal queue pause requested; partial evidence retained")
                time.sleep(5)
        except BaseException:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                proc.wait()
            raise
        core.save(base / (log_name + ".exit.json"), {"time": now(), "exit_code": proc.returncode})
        if proc.returncode:
            raise RuntimeError("stage failed: " + log_name)


def run(base):
    verify(base)
    with (base / "queue.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lifecycle.BASE = base
        stopped = False
        try:
            if (base / "PAUSE").exists():
                raise RuntimeError("formal queue paused")
            lifecycle.ensure_no_other_trainer()
            lifecycle.stop_old_worker()
            stopped = True
            common_status = core.read(COMMON / "STATUS.json")["phase"]
            if common_status != "pilot_complete":
                if (COMMON / "process-exit.json").exists() and core.read(COMMON / "process-exit.json")["exit_code"]:
                    raise RuntimeError("shared source previously failed; do not bypass gate")
                lifecycle.train(COMMON)
            if not (base / "FINAL_TEST_OPENED.json").exists():
                for seed in SEEDS:
                    out = prepare_seed(base, seed)
                    if not all((out / g / "FINISHED.json").exists() for g in GROUPS):
                        child(base, [str(ROOT / ".venv-lora/bin/python"), "-u", __file__, "train-seed",
                                     "--root", str(base), "--seed", str(seed)],
                              "train-%d.log" % seed, stage="formal_training", seed=seed)
                    child(base, [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/audit_agent_rl_tiered.py"),
                                 "--experiment", str(out)], "audit-%d.log" % seed, stage="audit", seed=seed)
                core.save(base / "TRAINING_COMPLETE.json", {"time": now(), "checkpoint_hashes": training_inventory(base),
                                                          "selection": "fixed step48, future intermediate step24"})
            for seed in SEEDS:
                child(base, [str(ROOT / ".venv-lora/bin/python"), "-u", __file__, "evaluate-seed",
                             "--root", str(base), "--seed", str(seed)],
                      "evaluate-%d.log" % seed, stage="sealed_evaluation", seed=seed)
            child(base, [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/analyze_agent_rl_confirmatory.py"),
                         "--root", str(base)], "analysis.log", stage="analysis")
            status(base, "formal_comparison_complete", final_test_opened=True, acceptance_passed=False,
                   next="read locked statistics and complete preregistered native closed-loop acceptance")
        except BaseException as exc:
            status(base, "stopped_for_review", error=str(exc), acceptance_passed=False,
                   final_test_opened=(base / "FINAL_TEST_OPENED.json").exists())
            raise
        finally:
            if stopped:
                with (base / "restore-inference.log").open("a") as stream:
                    proc = subprocess.Popen([str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/start_agent_rl_v1.py"),
                                             "--experiment", str(lifecycle.OLD)], cwd=ROOT,
                                            stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                core.save(base / "restore-inference.json", {"launcher_pid": proc.pid})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run", "train-seed", "evaluate-seed"])
    parser.add_argument("--root", type=Path, default=DEFAULT)
    parser.add_argument("--seed", type=int, choices=SEEDS)
    args = parser.parse_args()
    base = args.root.resolve()
    if args.command == "prepare":
        prepare(base)
    elif args.command == "run":
        run(base)
    else:
        verify(base)
        if args.seed is None:
            parser.error("seed is required")
        configure()
        if args.command == "train-seed":
            if (base / "FINAL_TEST_OPENED.json").exists():
                raise ValueError("training prohibited after test access")
            out = seed_dir(base, args.seed)
            cfg = core.read(out / "config.json")
            if core.sha(out / "common-demonstrations.json") != cfg["common_demonstrations_sha256"]:
                raise ValueError("demonstration drift")
            with (out / "trainer.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                core.develop(argparse.Namespace(output=out))
        else:
            evaluate_seed(base, args.seed)


if __name__ == "__main__":
    main()
