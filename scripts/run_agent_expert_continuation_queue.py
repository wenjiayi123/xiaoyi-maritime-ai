"""One frozen serial training attempt, audit, then restore one model registry."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import file_lease as fcntl
from scripts.freeze_agent_expert_continuation import EXPERT, read, save, sha, verify  # noqa: E402

ORIGINAL = EXPERT / "live-registration-001/REGISTRY.json"
ORIGINAL_SHA = "67aeaf1a46c3380c20b7a95085e2934081cc709603d15a76015ada6c24017040"


def now():
    return datetime.now(timezone.utc).isoformat()


def health():
    with urlopen("http://127.0.0.1:18781/health", timeout=3) as response:
        return json.load(response)


def listener():
    result = subprocess.run(
        ["/usr/sbin/lsof", "-nP", "-iTCP:18781", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
        check=False,
    )
    pids = {int(line) for line in result.stdout.splitlines() if line.strip()}
    if len(pids) > 1:
        raise RuntimeError("Multiple listeners; preserve current services")
    if result.returncode not in (0, 1):
        raise RuntimeError("Could not inspect model listener")
    return next(iter(pids), None)


def process_alive(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


def status(out, phase, **extra):
    value = {"time": now(), "phase": phase, "queue_pid": os.getpid(), **extra}
    save(out / "QUEUE_STATUS.json", value)
    with (out / "QUEUE_EVENTS.jsonl").open("a") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def stop_verified_worker(out):
    pid = listener()
    if pid is None:
        raise RuntimeError("Expected registered worker absent; diagnose before starting")
    current = health()
    if current.get("registry_sha256") != ORIGINAL_SHA or current.get("base_model_instances") != 1:
        raise RuntimeError("Unexpected model service; do not stop it")
    command = subprocess.check_output(["ps", "-p", str(pid), "-o", "args="], text=True).strip()
    if "serve_agent_expert_registry.py" not in command or "--port 18781" not in command:
        raise RuntimeError("Listener process identity mismatch")
    save(out / "WORKER_STOP_REQUEST.json", {"time": now(), "pid": pid, "command": command, "health": current})
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 30
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.5)
    if process_alive(pid) or listener() is not None:
        raise RuntimeError("Worker did not exit cleanly; no training was launched")
    save(out / "WORKER_STOPPED.json", {"time": now(), "pid": pid, "confirmed_gone": True})


def make_registry(out):
    complete = read(out / "TRAINING_COMPLETE.json")
    if not read(out / "PARAMETER_AND_OBJECTIVE_AUDIT.json")["passed"]:
        raise RuntimeError("No passed training audit")
    cfg = read(ORIGINAL)
    cfg["experiment"] = "expert-continuation002-common-parent-fixed-final64"
    cfg["seed"] = read(out / "CONFIG.json")["seed"]
    for group in ("E_expert_sft", "D_expert_rl"):
        cfg["acceptance_status"][group] = "training001_audited_evaluation001_not_accepted"
    for route, group in (("E_sft", "E_expert_sft2"), ("D_rl", "D_expert_rl2")):
        cfg["groups"][group] = complete["routes"][route]
        cfg["acceptance_status"][group] = "continuation002_training_audited_capability_evaluation_pending"
    folder = out / "live-registration-002"
    folder.mkdir(exist_ok=False)
    registry = folder / "REGISTRY.json"
    save(registry, cfg)
    save(
        folder / "LOCK.json",
        {
            "registry_sha256": sha(registry),
            "prior_registry_sha256": ORIGINAL_SHA,
            "server_source_sha256": sha(ROOT / "scripts/serve_agent_expert_registry.py"),
            "training_audit_sha256": sha(out / "PARAMETER_AND_OBJECTIVE_AUDIT.json"),
            "old_aliases_preserved": list(read(ORIGINAL)["groups"]),
            "base_model_instances": 1,
        },
    )
    return registry


def restore_worker(out, registry):
    if listener() is not None:
        raise RuntimeError("Listener already present; do not load another model")
    status(out, "restoring_one_inference_worker", registry=str(registry))
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
    save(out / "RESTORE_STARTED.json", {"time": now(), "pid": worker.pid, "registry": str(registry)})
    deadline = time.monotonic() + 240
    expected = read(registry)
    while time.monotonic() < deadline:
        if worker.poll() is not None:
            raise RuntimeError("Restored worker exited; inspect registry-console.log")
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
            raise RuntimeError("Restored model identity mismatch")
        save(out / "REGISTRY_RESTORED.json", {"time": now(), "pid": worker.pid, "health": value})
        return worker.pid
    raise RuntimeError("Worker startup has not reached healthy state; keep existing process and diagnose")


def run(out):
    verify(out)
    if sha(ORIGINAL) != ORIGINAL_SHA:
        raise ValueError("Original registry drift")
    if any((p / "PAUSE").exists() for p in (EXPERT, out)):
        raise RuntimeError("Paused; no new action")
    lock = (out / "QUEUE.lock").open("a+")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (out / "QUEUE_START.json").exists() or (out / "TRAINING_START.json").exists():
        raise RuntimeError("Prior attempt preserved; no automatic restart")
    save(out / "QUEUE_START.json", {"time": now(), "pid": os.getpid(), "lock_sha256": sha(out / "LOCK.json")})
    child, failure, audited = None, None, False
    try:
        status(out, "stopping_verified_inference_worker")
        stop_verified_worker(out)
        with (out / "training-console.log").open("x") as log:
            child = subprocess.Popen(
                [
                    str(ROOT / ".venv-lora/bin/python"),
                    str(ROOT / "scripts/train_agent_expert_continuation.py"),
                    "--experiment",
                    str(out),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            status(out, "serial_training", training_pid=child.pid, routes=["E_sft", "D_rl"], update_cap=128)
            exit_code = child.wait()
        save(out / "process-exit.json", {"time": now(), "pid": child.pid, "returncode": exit_code})
        if exit_code != 0:
            raise RuntimeError(f"Training exited {exit_code}; all partial artifacts retained")
        status(out, "independent_parameter_and_objective_audit")
        with (out / "audit-console.log").open("x") as log:
            subprocess.run(
                [
                    str(ROOT / ".venv/bin/python"),
                    str(ROOT / "scripts/audit_agent_expert_continuation.py"),
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
        failure = {"time": now(), "error": repr(exc), "traceback": traceback.format_exc()}
        save(out / "QUEUE_FAILURE.json", failure)
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=30)
    finally:
        # Only restore after proving the training child is gone. No parallel model.
        if (out / "WORKER_STOPPED.json").exists() and (child is None or child.poll() is not None):
            try:
                registry = make_registry(out) if audited else ORIGINAL
                restored = restore_worker(out, registry)
                status(
                    out,
                    "training_audited_registry_restored_pending_evaluation"
                    if audited
                    else "stopped_failure_original_registry_restored",
                    worker_pid=restored,
                    training_audited=audited,
                    final_tests_opened=False,
                    failure=failure,
                )
            except BaseException as exc:
                save(
                    out / "RESTORE_FAILURE.json",
                    {"time": now(), "error": repr(exc), "traceback": traceback.format_exc()},
                )
                status(out, "restoration_needs_attention", training_audited=audited, error=repr(exc))
                raise
        else:
            status(out, "stopped_before_model_handoff", failure=failure)
    if failure:
        raise RuntimeError(failure["error"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=Path, required=True)
    args = parser.parse_args()
    run(args.experiment.resolve())
