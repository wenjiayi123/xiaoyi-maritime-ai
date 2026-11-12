"""Freeze and execute the single post-training evaluation via the existing worker."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import html
import os
from pathlib import Path
import shutil
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import file_lease as fcntl
from scripts.freeze_agent_expert_continuation import read, save, sha, verify as verify_training, EXPERT  # noqa: E402
from scripts.prepare_agent_expert_training import OLD  # noqa: E402
from scripts.agent_expert_evaluation_support import (  # noqa: E402
    CaptureProvider,
    validate_decision,
    outcome_metrics,
    audit_episode,
    canonical,
)
from app.agent_training.expert_environment import (  # noqa: E402
    ExpertTask,
    ExpertEnvironment,
    RecordedEnergyProvider,
    NativeEnergyProvider,
)
from app.agent_training.live import local_request  # noqa: E402
from scripts import run_agent_capability_scale as legacy  # noqa: E402

TRAINING = EXPERT / "continuation-002"
DATA = TRAINING / "tasks-003"
REGISTRY = TRAINING / "live-registration-003/REGISTRY.json"
GROUPS = {"E_expert_sft2": "E_sft", "D_expert_rl2": "D_rl"}


def now():
    return datetime.now(timezone.utc).isoformat()


def paused(out):
    if any((p / "PAUSE").exists() for p in (EXPERT, out)):
        raise RuntimeError("Evaluation paused; partial attempt preserved")


def prepare(out):
    cfg = verify_training(TRAINING)
    complete = read(TRAINING / "TRAINING_COMPLETE.json")
    if not read(TRAINING / "PARAMETER_AND_OBJECTIVE_AUDIT.json")["passed"]:
        raise ValueError("Training audit required")
    out.mkdir(parents=True, exist_ok=False)
    # Only training cases are read here. Held-out content stays unopened until run().
    train = read(DATA / "train/tasks.json")
    native = [case for case in train if case["configuration_index"] == 1]
    if len(native) != 4 or len({c["family"] for c in native}) != 4:
        raise ValueError("Expected fixed four native demonstration families")
    train_gold = {g["case_id"]: g for g in read(DATA / "train/oracle-labels.json")}
    models = {group: complete["routes"][route] for group, route in GROUPS.items()}
    old = deepcopy(legacy.core.verify(OLD / "round-003"))
    old.update(groups=list(GROUPS), models=models)
    protocol = {
        "time": now(),
        "groups": list(GROUPS),
        "models": models,
        "training_lock_sha256": sha(TRAINING / "LOCK.json"),
        "training_audit_sha256": sha(TRAINING / "PARAMETER_AND_OBJECTIVE_AUDIT.json"),
        "data_lock_sha256": sha(DATA / "DATA_LOCK.json"),
        "registry_sha256": sha(REGISTRY),
        "worker": "http://127.0.0.1:18781",
        "new_base_models": 0,
        "new_cases": 12,
        "new_repetitions": 2,
        "legacy_cases": 30,
        "legacy_repetitions": 2,
        "native_cases": 4,
        "native_repetitions": 1,
        "planned_total_attempts": 176,
        "schedule": ["new_sealed", "legacy_native", "new_native_demo"],
        "case_order": "file order; repetition outer, case next, groups E then D; all registered semantic failures retained and continue",
        "error_policy": "Transport, identity or audit exception stops with partial evidence; never automatic rerun. Model-selected wrong tool/report is a task failure and does not stop other registered tasks.",
        "pause": "Check experiment/global PAUSE before each expert decision and each legacy attempt; legacy also checks global pause each decision",
        "selection": cfg["selection"],
        "acceptance": cfg["evaluation"]["acceptance"],
        "thresholds": {"new_correct_per_group": 24, "legacy_correct_per_group": 60, "native_correct_per_group": 4},
        "closed_test_rule": "Open once after this evaluator/protocol is frozen. No tuning, checkpoint changes, repeated attempts or training after results.",
        "counting": "12heldout parameter/constraint cases repeated twice; repetitions are not independent cases. Four native demonstrations are fixed training configurations, not additional holdout evidence.",
        "scope": cfg["evaluation"]["generalization_limit"],
        "model_scope": "13candidate tool letters; structured parameters, numerical assessment and reports deterministic; scripted replies/goalchanges in controlled episodes",
        "production_authority": False,
        "superiority_claimed": False,
        "primary_delivery_group": "D_expert_rl2",
        "delivery_reporting": "Report per-route original gates and RL priority separately; original joint accepted flag unchanged.",
        "initializer_seed_note": "Runtime seed20261102 preserves B_base identity; training seed20261104 unchanged. All trained adapter fingerprints fixed.",
    }
    save(out / "PROTOCOL.json", protocol)
    save(out / "NATIVE_CASES.json", native)
    save(out / "NATIVE_GOLD.json", {c["task"]["case_id"]: train_gold[c["task"]["case_id"]] for c in native})
    save(out / "LEGACY_PROTOCOL.json", old)
    sources = {}
    for p in [
        Path(__file__),
        ROOT / "scripts/agent_expert_evaluation_support.py",
        ROOT / "tests/test_agent_expert_continuation_evaluation.py",
    ]:
        sources[str(p)] = sha(p)
        dst = out / "sources" / p.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
    save(out / "SOURCES.json", sources)
    save(
        out / "LOCK.json",
        {
            n: sha(out / n)
            for n in ["PROTOCOL.json", "NATIVE_CASES.json", "NATIVE_GOLD.json", "LEGACY_PROTOCOL.json", "SOURCES.json"]
        },
    )
    save(out / "STATUS.json", {"time": now(), "phase": "frozen_ready", "sealed_tests_opened": False})


def verify(out):
    verify_training(TRAINING)
    for name, expected in read(out / "LOCK.json").items():
        if sha(out / name) != expected:
            raise ValueError("Evaluation protocol drift: " + name)
    for path, expected in read(out / "SOURCES.json").items():
        if sha(path) != expected or sha(out / "sources" / Path(path).relative_to(ROOT)) != expected:
            raise ValueError("Evaluator source drift")
    p = read(out / "PROTOCOL.json")
    for source, key in [
        (TRAINING / "LOCK.json", "training_lock_sha256"),
        (TRAINING / "PARAMETER_AND_OBJECTIVE_AUDIT.json", "training_audit_sha256"),
        (DATA / "DATA_LOCK.json", "data_lock_sha256"),
        (REGISTRY, "registry_sha256"),
    ]:
        if sha(source) != p[key]:
            raise ValueError("Evaluation prerequisite drift")
    if not read(TRAINING / "PARAMETER_AND_OBJECTIVE_AUDIT.json")["passed"]:
        raise ValueError("Training audit failed")
    legacy.core.verify(OLD / "round-003")
    return p


def worker_health(p):
    health = local_request(p["worker"], "/health", timeout=8)
    if (
        health.get("base_model_instances") != 1
        or health.get("registry_sha256") != p["registry_sha256"]
        or any(health["weights"].get(g) != p["models"][g]["parameter_fingerprint"] for g in p["groups"])
    ):
        raise ValueError("Worker identity differs from frozen final adapters")
    return health


def run_episode(case, gold, group, fingerprint, folder, *, native=False, decide=None, pause_check=None):
    folder.mkdir(parents=True, exist_ok=False)
    inner = (
        NativeEnergyProvider(folder / "native")
        if native
        else RecordedEnergyProvider([read(p)["receipt"] for p in case["receipt_files"]])
    )
    provider = CaptureProvider(inner, folder)
    env = ExpertEnvironment(ExpertTask(**case["task"]), provider)
    job = {
        "task": case["task"],
        "gold": gold,
        "family": case["family"],
        "group": group,
        "source_receipt_files": [] if native else case["receipt_files"],
        "provider_mode": provider.mode,
        "expected_fingerprint": fingerprint,
        "steps": [],
        "started_at": now(),
        "status": "running",
    }
    save(folder / "trajectory.json", job)
    try:
        while not env.done:
            if pause_check:
                pause_check()
            prompt = env.prompt()
            response = (
                decide(prompt, group)
                if decide
                else local_request("http://127.0.0.1:18781", "/decide", {"prompt": prompt, "group": group}, timeout=120)
            )
            job["pending_decision"] = {"prompt": prompt, "model": response}
            save(folder / "trajectory.json", job)
            validate_decision(response, group, fingerprint)
            transition = env.step(response["choice"])
            job["steps"].append({"prompt": prompt, "model": response, "transition": canonical(transition)})
            job.pop("pending_decision")
            save(folder / "trajectory.json", job)
        job.update(
            status="completed", metrics=outcome_metrics(env, gold), report=canonical(env.report), finished_at=now()
        )
        save(folder / "trajectory.json", job)
        audit = audit_episode(job, folder, fingerprint)
        save(folder / "AUDIT.json", audit)
        save(folder / "report.json", {"metrics": job["metrics"], "report": job["report"], "source": provider.mode})
        (folder / "report.html").write_text(
            '<meta charset="utf-8"><title>舷鸥任务回执</title><h1>舷鸥任务回执</h1><p>本机离线模拟；程序依据核验事实生成报告。</p><pre>'
            + html.escape((folder / "report.json").read_text())
            + "</pre>"
        )
        return {
            "case_id": env.task.case_id,
            "family": case["family"],
            "group": group,
            "metrics": job["metrics"],
            "steps": len(job["steps"]),
            "audit": audit,
            "folder": str(folder),
        }
    except Exception as exc:
        job.update(status="exception", error=repr(exc), traceback=traceback.format_exc(), finished_at=now())
        save(folder / "trajectory.json", job)
        raise


def summarize(p, results):
    summary = {}
    for group in p["groups"]:
        own = [r for r in results if r["group"] == group]
        summary[group] = {}
        for split, total in [("new_sealed", 24), ("legacy_native", 60), ("new_native_demo", 4)]:
            rows = [r for r in own if r["split"] == split]
            summary[group][split] = {
                "correct": sum(r["success"] for r in rows),
                "attempted": len(rows),
                "registered": total,
                "unattempted": total - len(rows),
            }
        rows = [r for r in own if r["split"] == "new_sealed"]
        summary[group]["new_business"] = {
            "verified_complete": sum(r["metrics"]["business_complete"] for r in rows),
            "registered_feasible_attempts": 16,
            "correct_none_of_two": sum(r["metrics"]["correct_no_registered_candidate"] for r in rows),
            "registered_infeasible_attempts": 8,
            "clarification_correct": sum(r["metrics"]["clarification_correct"] for r in rows),
            "receipt_recoveries": sum(r["metrics"]["receipt_recoveries"] for r in rows),
        }
    route_accepted = {
        g: all(
            summary[g][s]["correct"] == n and summary[g][s]["attempted"] == n
            for s, n in [("new_sealed", 24), ("legacy_native", 60), ("new_native_demo", 4)]
        )
        for g in p["groups"]
    }
    passed = all(route_accepted.values())
    primary = p.get("primary_delivery_group", "D_expert_rl2")
    return {
        "groups": summary,
        "accepted": passed,
        "registered_joint_accepted": passed,
        "route_accepted": route_accepted,
        "primary_delivery_group": primary,
        "primary_delivery_accepted": route_accepted.get(primary, False),
        "completed_attempts": len(results),
        "registered_attempts": 176,
        "scope": p["scope"],
        "superiority_claimed": False,
    }


def run(out):
    p = verify(out)
    paused(out)
    if (out / "STARTED.json").exists():
        raise ValueError("Evaluation already started; preserve attempts, no automatic rerun")
    with ExitStack() as stack:
        for directory in [EXPERT, legacy.BASE, legacy.ACCEPTED]:
            lock = stack.enter_context((directory / "execution.lock").open("a"))
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        save(out / "WORKER_START.json", worker_health(p))
        save(out / "STARTED.json", {"time": now(), "pid": os.getpid(), "protocol_lock_sha256": sha(out / "LOCK.json")})
        # Both final weights and the evaluator are frozen before this first parse.
        save(
            out / "SEALED_TEST_OPENED.json",
            {"time": now(), "data_lock_sha256": p["data_lock_sha256"], "purpose": "one final evaluation"},
        )
        tests = read(DATA / "sealed-test/tasks.json")
        gold = {g["case_id"]: g for g in read(DATA / "sealed-test/oracle-labels.json")}
        if len(tests) != 12 or len(gold) != 12:
            raise ValueError("Held-out task count mismatch")
        results = []

        def progress(active=None):
            summary = summarize(p, results)
            save(
                out / "STATUS.json",
                {"time": now(), "phase": "running", "pid": os.getpid(), "active": active, **summary},
            )
            save(out / "PROGRESS.json", {**summary, "results": results})

        def expert_cases(split, cases, gold_by_id, repetitions, native):
            for repetition in range(1, repetitions + 1):
                for case in cases:
                    for group in p["groups"]:
                        paused(out)
                        ident = f"{case['task']['case_id']}-{group}-r{repetition}"
                        progress(split + "/" + ident)
                        row = run_episode(
                            case,
                            gold_by_id[case["task"]["case_id"]],
                            group,
                            p["models"][group]["parameter_fingerprint"],
                            out / split / ident,
                            native=native,
                            pause_check=lambda: paused(out),
                        )
                        row.update(split=split, repetition=repetition, success=row["metrics"]["decision_correct"])
                        results.append(row)
                        progress()

        expert_cases("new_sealed", tests, gold, 2, False)
        old = read(out / "LEGACY_PROTOCOL.json")
        # Same legacy prompt, execution and audit. Only pause-file location is
        # adapted in this process; accepted source files remain byte-identical.
        legacy.core.BASE = EXPERT
        for repetition in range(1, 3):
            for case in old["cases"]:
                for group in p["groups"]:
                    paused(out)
                    ident = f"{case['id']}-{group}-r{repetition}"
                    folder = out / "legacy_native" / ident
                    folder.mkdir(parents=True, exist_ok=False)
                    progress("legacy_native/" + ident)
                    job = {
                        "id": ident,
                        "goal": case["goal"],
                        "task": case["task"],
                        "group": group,
                        "status": "queued",
                        "success": False,
                        "steps": [],
                        "evidence": [],
                        "experiment": "expert-continuation002-fixed-final64",
                        "environment": legacy.core.REVISION,
                        "expected_adapter_sha256": p["models"][group]["parameter_fingerprint"],
                        "production_authority": False,
                        "fault_injection_requested": case["inject_read_fault"],
                    }
                    job = legacy.core.execute(job, folder, old)
                    audit = legacy.core.audit_job(job, folder, old)
                    save(folder / "AUDIT.json", audit)
                    results.append(
                        {
                            "split": "legacy_native",
                            "case_id": case["id"],
                            "group": group,
                            "repetition": repetition,
                            "success": job["success"],
                            "steps": len(job["steps"]),
                            "folder": str(folder),
                            "audit": audit,
                        }
                    )
                    progress()
                    if job.get("error"):
                        raise RuntimeError("Legacy infrastructure exception preserved: " + job["error"])
        expert_cases("new_native_demo", read(out / "NATIVE_CASES.json"), read(out / "NATIVE_GOLD.json"), 1, True)
        verify(out)
        save(out / "WORKER_END.json", worker_health(p))
        summary = summarize(p, results)
        save(out / "RESULTS.json", {"time": now(), **summary, "results": results})
        save(
            out / "ACCEPTANCE.json",
            {
                "time": now(),
                **summary,
                "all_attempts_audited": True,
                "final_test_reused_for_tuning": False,
                "frozen_training_unchanged": True,
            },
        )
        save(out / "STATUS.json", {"time": now(), "phase": "complete", **summary})
        return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "verify", "run"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if args.command != "run":
        {"prepare": prepare, "verify": verify}[args.command](out)
    else:
        code = 1
        try:
            code = run(out)
        except Exception as exc:
            save(
                out / ("FAILURE-" + str(os.getpid()) + ".json"),
                {"time": now(), "error": repr(exc), "traceback": traceback.format_exc()},
            )
            prior = read(out / "STATUS.json") if (out / "STATUS.json").exists() else {}
            save(out / "STATUS.json", {**prior, "time": now(), "phase": "stopped_with_exception", "error": repr(exc)})
            raise
        finally:
            save(out / "process-exit.json", {"time": now(), "pid": os.getpid(), "returncode": code})
        raise SystemExit(code)
