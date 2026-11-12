"""Shared audited contracts for common recovery warm-start, no model imports."""

from collections import defaultdict
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.probe_agent_expert_observation import EXPERT, make_env, read, save, sha, now  # noqa: E402
from scripts.agent_expert_evaluation_support import canonical, outcome_metrics  # noqa: E402
from scripts import run_agent_capability_scale as scale  # noqa: E402

LETTERS = "ABCDEFGHIJKLM"
DATA = EXPERT / "continuation-003/recovery-data-001"
REGISTRY = EXPERT / "continuation-002/live-registration-003/REGISTRY.json"
REGISTRY_SHA = "38070bd30f716ef96b63291a2256f0a9d82068a23b0ab6d129e400579445fabc"


def balanced_order(states, seed, updates=512):
    rng = random.Random(seed)
    pools = defaultdict(list)
    for state in states:
        key = "old" if state["origin"] == "legacy_retention" else state["target"]
        pools[key].append(state["state_id"])
    classes = sorted(k for k in pools if k != "old")
    if not classes or not pools["old"]:
        raise ValueError("Both new and retained training states are required")
    queues = defaultdict(list)

    def take(key):
        if not queues[key]:
            queues[key] = pools[key].copy()
            rng.shuffle(queues[key])
        return queues[key].pop()

    schedule, class_queue = [], []
    for step in range(1, updates + 1):
        chosen = []
        for _ in range(8):
            if not class_queue:
                class_queue = classes.copy()
                rng.shuffle(class_queue)
            chosen.append(take(class_queue.pop()))
        chosen += [take("old") for _ in range(4)]
        rng.shuffle(chosen)
        schedule.append(dict(step=step, states=chosen))
    return schedule


def learning_rate(step, cfg):
    if not 1 <= step <= cfg["max_updates"]:
        raise ValueError("Step outside registered update budget")
    phase = (step - 1) / (cfg["max_updates"] - 1)
    return cfg["lr_final"] + (cfg["lr_initial"] - cfg["lr_final"]) * (1 + math.cos(math.pi * phase)) / 2


def ready(gates):
    return (
        len(gates) >= 2
        and gates[-1]["step"] - gates[-2]["step"] == 64
        and gates[-1]["passed"] is True
        and gates[-2]["passed"] is True
    )


def resource_check(out, require_model=False):
    if (EXPERT / "PAUSE").exists() or (out / "PAUSE").exists():
        raise RuntimeError("Paused; preserve all partial results")
    status = read(EXPERT / "resource-guard-001/STATUS.json")
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(status["time"])).total_seconds()
    command = subprocess.check_output(["ps", "-p", str(status["guard_pid"]), "-o", "args="], text=True)
    if "scripts/watch_agent_expert_resources.py" not in command or age > 90 or status["decision"]["pause"]:
        raise RuntimeError("Resource protection is absent, stale or paused")
    if len(status["model_processes"]) > 1 or (require_model and len(status["model_processes"]) != 1):
        raise RuntimeError("Unexpected model process count")
    return status


def environment(case):
    return make_env(case["case"]) if case["kind"] == "expert" else scale.core.live.environment_for_job(case["job"])


def prompt_for(env, case):
    return env.prompt() if case["kind"] == "expert" else scale.core.prompt_for(env, case["prompt_mode"])


def metrics_for(env, case):
    if case["kind"] == "expert":
        return outcome_metrics(env, case["gold"])
    return dict(decision_correct=env.success, legacy_checks=env.checks(), source="synthetic_training_retention")


def validate_choice(choice, decision):
    probabilities = decision["probabilities"]
    if len(probabilities) != 13 or any(not math.isfinite(p) or p < 0 for p in probabilities):
        raise ValueError("Invalid actual policy probabilities")
    if abs(sum(probabilities) - 1) > 1e-5 or choice != LETTERS[max(range(13), key=probabilities.__getitem__)]:
        raise ValueError("Gate action is not the actual deterministic model argmax")


def replay_gate(case, job):
    env = environment(case)
    for record in job["steps"]:
        if env.done or record["prompt"] != prompt_for(env, case):
            raise ValueError("Training gate prompt/state replay mismatch")
        validate_choice(record["choice"], record["decision"])
        if canonical(env.step(record["choice"])) != record["transition"]:
            raise ValueError("Training gate action/receipt transition mismatch")
    if not env.done or canonical(metrics_for(env, case)) != job["metrics"]:
        raise ValueError("Unsupported training readiness result")
    return True


def training_gate(policy, cases, out, step):
    folder = out / "training-gates" / f"step-{step:05d}"
    folder.mkdir(parents=True, exist_ok=False)
    fingerprint, rows = policy.fingerprint(), []
    for index, case in enumerate(cases):
        resource_check(out)
        env = environment(case)
        job = dict(case_id=case["case_id"], kind=case["kind"], fingerprint=fingerprint, steps=[])
        path = folder / (case["case_id"] + ".json")
        while not env.done:
            resource_check(out)
            save(
                out / "STATUS.json",
                dict(
                    time=now(),
                    phase="training_only_full_episode_gate",
                    step=step,
                    completed_cases=index,
                    total_cases=len(cases),
                    active=case["case_id"],
                    pid=os.getpid(),
                ),
            )
            prompt = prompt_for(env, case)
            choice, decision = policy.choose(prompt, sample=False, temperature=1.0)
            validate_choice(choice, decision)
            job["pending_decision"] = dict(prompt=prompt, choice=choice, decision=decision)
            save(path, job)
            transition = canonical(env.step(choice))
            job["steps"].append(dict(prompt=prompt, choice=choice, decision=decision, transition=transition))
            job.pop("pending_decision")
            save(path, job)
        job["metrics"] = canonical(metrics_for(env, case))
        job["complete"] = True
        save(path, job)
        replay_gate(case, job)
        rows.append(
            dict(
                case_id=case["case_id"],
                kind=case["kind"],
                correct=job["metrics"]["decision_correct"],
                trajectory=str(path),
                sha256=sha(path),
                decisions=len(job["steps"]),
            )
        )
    if policy.fingerprint() != fingerprint:
        raise ValueError("Parameters changed during readiness gate")
    passed = len(rows) == 48 and all(r["correct"] for r in rows)
    report = dict(
        time=now(),
        step=step,
        passed=passed,
        groups={
            kind: dict(
                correct=sum(r["correct"] for r in rows if r["kind"] == kind),
                attempted=sum(r["kind"] == kind for r in rows),
            )
            for kind in ["expert", "legacy"]
        },
        rows=rows,
        fingerprint=fingerprint,
        training_only=True,
        final_test=False,
    )
    save(folder / "RESULTS.json", report)
    return report
