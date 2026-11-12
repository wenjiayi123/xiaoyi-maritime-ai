"""Guarded one-model warm-start, independent audit and nine-alias restoration."""

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import file_lease as fcntl
from scripts.freeze_agent_expert_recovery import verify  # noqa: E402
from scripts.agent_expert_recovery_support import read, save, sha, now, resource_check, REGISTRY  # noqa: E402
from scripts.run_agent_expert_continuation_queue import health, listener, process_alive  # noqa: E402


def status(out, phase, **extra):
    value = dict(time=now(), phase=phase, queue_pid=os.getpid(), **extra)
    save(out / "QUEUE_STATUS.json", value)
    with (out / "QUEUE_EVENTS.jsonl").open("a") as f:
        f.write(json.dumps(value, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def stop_worker(out, cfg):
    guard = resource_check(out, require_model=True)
    pid = listener()
    current = health()
    if (
        pid is None
        or current.get("registry_sha256") != cfg["original_registry_sha256"]
        or current.get("base_model_instances") != 1
    ):
        raise RuntimeError("Expected single registered worker not present")
    owned = guard["model_processes"][0]
    if owned["pid"] != pid or owned["cwd"] != str(ROOT):
        raise RuntimeError("Guard identity mismatch")
    command = subprocess.check_output(["ps", "-p", str(pid), "-o", "args="], text=True).strip()
    args = shlex.split(command)
    if "serve_agent_expert_registry.py" not in command or "--registry" not in args:
        raise RuntimeError("Listener identity mismatch")
    registry = Path(args[args.index("--registry") + 1])
    registry = registry if registry.is_absolute() else ROOT / registry
    if registry.resolve() != REGISTRY.resolve() or command != owned["command"]:
        raise RuntimeError("Listener registry/command changed")
    save(out / "WORKER_STOP_REQUEST.json", dict(time=now(), pid=pid, command=command, health=current))
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 30
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.5)
    if process_alive(pid) or listener() is not None:
        raise RuntimeError("Worker did not exit; training not started")
    save(out / "WORKER_STOPPED.json", dict(time=now(), pid=pid, confirmed_gone=True))


def registry_contents(original, complete):
    cfg = deepcopy(original)
    # Runtime random initialization is part of B_base identity, NOT training seed.
    cfg["experiment"] = "expert-continuation003-common-supervised-recovery"
    for name in ["E_expert_sft2", "D_expert_rl2"]:
        cfg["acceptance_status"][name] = "continuation002_evaluation_complete_not_accepted"
    cfg["groups"]["C_expert_warm3"] = {
        k: complete[k] for k in ["adapter", "file_sha256", "parameter_fingerprint", "parent_fingerprint"]
    }
    cfg["groups"]["C_expert_warm3"]["additional_updates"] = complete["updates"]
    cfg["acceptance_status"]["C_expert_warm3"] = (
        "training_readiness_passed_not_final_acceptance"
        if complete["warm_ready"]
        else "warm_training_budget_complete_not_ready"
    )
    return cfg


def make_registry(out):
    if not read(out / "PARAMETER_AND_OBJECTIVE_AUDIT.json")["passed"]:
        raise ValueError("Parameter audit required")
    cfg = registry_contents(read(REGISTRY), read(out / "TRAINING_COMPLETE.json"))
    folder = out / "live-registration-004"
    folder.mkdir(exist_ok=False)
    save(folder / "REGISTRY.json", cfg)
    save(
        folder / "LOCK.json",
        dict(
            registry_sha256=sha(folder / "REGISTRY.json"),
            prior_registry_sha256=sha(REGISTRY),
            audit_sha256=sha(out / "PARAMETER_AND_OBJECTIVE_AUDIT.json"),
            runtime_seed=cfg["seed"],
            training_seed=read(out / "CONFIG.json")["seed"],
            old_aliases_preserved=list(read(REGISTRY)["groups"]),
        ),
    )
    return folder / "REGISTRY.json"


def restore(out, registry):
    resource_check(out)
    if listener() is not None:
        raise RuntimeError("Model listener already exists; do not load a second base")
    status(out, "restoring_one_worker", registry=str(registry))
    with (out / "registry-console.log").open("x") as log:
        worker = subprocess.Popen(
            [
                str(ROOT / ".venv-lora/bin/python"),
                str(ROOT / "scripts/serve_agent_expert_registry.py"),
                "--registry",
                str(registry),
                "--port",
                "18781",
            ],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    save(out / "RESTORE_STARTED.json", dict(time=now(), pid=worker.pid, registry=str(registry)))
    deadline = time.monotonic() + 300
    expected = read(registry)
    while time.monotonic() < deadline:
        resource_check(out)
        if worker.poll() is not None:
            raise RuntimeError("Restored worker exited; inspect retained console")
        try:
            value = health()
        except (OSError, ValueError):
            time.sleep(2)
            continue
        if (
            value.get("registry_sha256") != sha(registry)
            or value.get("base_model_instances") != 1
            or value.get("weights") != {g: r["parameter_fingerprint"] for g, r in expected["groups"].items()}
        ):
            raise RuntimeError("Restored adapter identity mismatch")
        save(out / "REGISTRY_RESTORED.json", dict(time=now(), pid=worker.pid, health=value))
        return worker.pid
    raise RuntimeError("Worker not yet healthy; preserve startup process for diagnosis")


def run(out):
    cfg = verify(out)
    resource_check(out, require_model=True)
    lock = (out / "QUEUE.lock").open("a+")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (out / "QUEUE_START.json").exists() or (out / "TRAINING_START.json").exists():
        raise RuntimeError("Previous attempt preserved; no automatic restart")
    save(out / "QUEUE_START.json", dict(time=now(), pid=os.getpid(), lock_sha256=sha(out / "LOCK.json")))
    child = None
    audited = False
    failure = None
    try:
        stop_worker(out, cfg)
        with (out / "training-console.log").open("x") as log:
            child = subprocess.Popen(
                [
                    str(ROOT / ".venv-lora/bin/python"),
                    str(ROOT / "scripts/train_agent_expert_recovery.py"),
                    "--experiment",
                    str(out),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            status(out, "common_recovery_training", training_pid=child.pid, max_updates=512)
            code = child.wait()
        save(
            out / "process-exit.json",
            dict(
                time=now(),
                pid=child.pid,
                returncode=code,
                meaning="0 ready;2 budget complete not ready;other interrupted/failure",
            ),
        )
        if code not in (0, 2) or not (out / "TRAINING_COMPLETE.json").exists():
            raise RuntimeError("Training interrupted; retain all evidence")
        status(out, "independent_warm_training_audit")
        with (out / "audit-console.log").open("x") as log:
            subprocess.run(
                [
                    str(ROOT / ".venv/bin/python"),
                    str(ROOT / "scripts/audit_agent_expert_recovery_training.py"),
                    "--experiment",
                    str(out),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
        audited = True
    except BaseException as exc:
        failure = dict(time=now(), error=repr(exc), traceback=traceback.format_exc())
        save(out / "QUEUE_FAILURE.json", failure)
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=30)
    finally:
        if (out / "WORKER_STOPPED.json").exists() and (child is None or child.poll() is not None):
            try:
                resource_check(out)
                registry = make_registry(out) if audited else REGISTRY
                pid = restore(out, registry)
                status(
                    out,
                    "warm_training_audited_registry_restored"
                    if audited
                    else "failure_preserved_prior_registry_restored",
                    worker_pid=pid,
                    training_audited=audited,
                    warm_ready=read(out / "TRAINING_COMPLETE.json")["warm_ready"] if audited else False,
                    failure=failure,
                )
            except BaseException as exc:
                save(out / "RESTORE_FAILURE.json", dict(time=now(), error=repr(exc), traceback=traceback.format_exc()))
                status(out, "restoration_needs_attention", training_audited=audited, error=repr(exc))
                raise
        else:
            status(out, "stopped_before_handoff", failure=failure)
    if failure:
        raise RuntimeError(failure["error"])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--experiment", type=Path, required=True)
    run(p.parse_args().experiment.resolve())
