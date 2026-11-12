"""Finite serial experiment queue. Never runs two 1.7B processes together."""

import datetime
import sys
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import file_lease as fcntl
BASE = ROOT / ".codex_artifacts/agent-rl-tiered-20261102"
DEPENDENCY = ROOT / ".codex_artifacts/agent-rl-v3-20261102/experiment-006-curriculum"
OLD = ROOT / ".codex_artifacts/agent-rl-v2-20261102/experiment-004"


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def status(phase, **values):
    row = {"time": datetime.datetime.now().astimezone().isoformat(), "phase": phase, **values}
    save(BASE / "QUEUE_STATUS.json", row)
    print(json.dumps(row, ensure_ascii=False), flush=True)


def health():
    try:
        with urlopen("http://127.0.0.1:18781/health", timeout=2) as response:
            return json.load(response)
    except Exception:
        return None


def windows_processes(pid=None):
    if pid is not None and (not isinstance(pid,int) or isinstance(pid,bool) or pid<=0):
        raise ValueError("invalid process ID")
    filter_ = f"ProcessId = {pid}" if pid is not None else "Name LIKE 'python%'"
    output = "$_.CommandLine" if pid is not None else "('{0} {1}' -f $_.ProcessId,$_.CommandLine)"
    script = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
              f"Get-CimInstance -ClassName Win32_Process -Filter \"{filter_}\" | "
              f"ForEach-Object {{ [Console]::WriteLine({output}) }}")
    return subprocess.check_output(["powershell.exe","-NoProfile","-NonInteractive","-Command",script],
                  encoding="utf-8",stderr=subprocess.DEVNULL,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)


def command(pid):
    if os.name=="nt":
        try:return windows_processes(pid).strip()
        except (OSError,subprocess.SubprocessError):return ""
    # macOS ps escapes Chinese path bytes under the unsupported C.UTF-8 locale.
    # Keep the exact-path ownership check by requesting its supported UTF-8 locale.
    return subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "LC_ALL": "en_US.UTF-8", "LANG": "en_US.UTF-8"},
    ).stdout.strip()


def stop_old_worker():
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        current = health()
        if current:
            if current.get("service") != "xiaoyi-language-agent-rl" or current.get("experiment") != "experiment-004":
                raise RuntimeError("inference worker identity differs; nothing terminated")
            registry = ROOT / ".runtime/agent-rl-v1/launch/processes.json"
            registered = read(registry)
            if registered.get("experiment") != str(OLD):
                raise RuntimeError("inference ownership registry differs")
            stopped = []
            for pid in registered["owned_pids"]:
                cmd = command(pid)
                if str(ROOT / "scripts/serve_agent_rl_v1.py") in cmd and str(OLD) in cmd:
                    os.kill(pid, signal.SIGTERM)
                    stopped.append(pid)
            if not stopped:
                time.sleep(1)
                continue  # Health may precede the launcher's registry update.
            save(
                BASE / "inference-transition.json",
                {
                    "health_before": current,
                    "stopped_owned_model_pids": stopped,
                    "reason": "release local memory for serial training",
                    "restore_after_queue": str(OLD),
                },
            )
            for _ in range(30):
                if not health() and all(not command(pid) for pid in stopped):
                    return
                time.sleep(1)
            raise RuntimeError("old inference worker did not stop")
        time.sleep(2)
    raise RuntimeError("previous supervisor did not restore an identifiable worker")


def ensure_no_other_trainer():
    listing=windows_processes() if os.name=="nt" else subprocess.check_output(["ps", "-axo", "pid=,command="], text=True)
    lines = listing.splitlines()
    found = []
    for line in lines:
        if re.search(
            r"scripts/run_agent_rl_(?:(?:v\d+|tiered|formal_core)\.py\s+develop|confirmatory\.py\s+(?:train-seed|evaluate-seed))",
            line,
        ):
            found.append(line.strip())
    if found:
        raise RuntimeError("another trainer is active: " + str(found))


def analyze(out):
    for script in ["audit_agent_rl_tiered.py", "render_agent_rl_v3.py"]:
        with (out / "analysis.log").open("a") as log:
            result = subprocess.run(
                [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts" / script), "--experiment", str(out)],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        if result.returncode:
            raise RuntimeError("analysis failed: " + script)


def rules(out):
    from app.agent_training.environment_tiered import TieredTask, TieredEnvironment, teacher_action

    records = []
    for value in read(out / "tasks/validation.json"):
        env = TieredEnvironment(TieredTask(**value))
        while not env.done:
            env.step(teacher_action(env))
        records.append({"case_id": env.task.case_id, "success": env.success, "steps": len(env.steps)})
    save(
        out / "baselines/A_rules-development.json",
        {
            "phase": "A_rules",
            "step": 0,
            "n": len(records),
            "successes": sum(r["success"] for r in records),
            "tasks": records,
            "model_used": False,
        },
    )


def train(out):
    ensure_no_other_trainer()
    rules(out)
    with (out / "trainer.log").open("a", buffering=1) as log:
        child = subprocess.Popen(
            [
                str(ROOT / ".venv-lora/bin/python"),
                "-u",
                str(ROOT / "scripts/run_agent_rl_tiered.py"),
                "develop",
                "--output",
                str(out),
            ],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        save(
            out / "process.json",
            {"trainer_pid": child.pid, "started": datetime.datetime.now().astimezone().isoformat()},
        )
        status("training", experiment=str(out), trainer_pid=child.pid)
        seen = ()
        try:
            while child.poll() is None:
                if (BASE / "PAUSE").exists():
                    child.send_signal(signal.SIGINT)
                    child.wait()
                    raise RuntimeError("queue pause requested; partial update preserved")
                measured = tuple(p.name for p in sorted((out / "validation").glob("*.json")))
                if measured and measured != seen:
                    analyze(out)
                    seen = measured
                time.sleep(10)
        except BaseException:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                child.wait()
            raise
        finally:
            save(
                out / "process-exit.json",
                {"exit_code": child.poll(), "time": datetime.datetime.now().astimezone().isoformat()},
            )
    analyze(out)
    if child.returncode:
        raise RuntimeError("training stopped with exit code " + str(child.returncode))


def main():
    sys_path = str(ROOT)
    import sys

    sys.path.insert(0, sys_path)
    BASE.mkdir(parents=True, exist_ok=True)
    with (BASE / "queue.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status("waiting_for_current_comparison", dependency=str(DEPENDENCY))
        while not (DEPENDENCY / "FINALIZATION.json").exists():
            if (BASE / "PAUSE").exists():
                status("paused_before_start")
                return
            time.sleep(10)
        final = read(DEPENDENCY / "FINALIZATION.json")
        if final.get("training_exit_code") != 0 or final.get("audit") != 0:
            status("dependency_failed", detail=final)
            return
        for group in ["D_drgrpo", "E_more_sft", "F_experience"]:
            if not (DEPENDENCY / group / "FINISHED.json").exists():
                raise RuntimeError("current comparison incomplete")
        stopped = False
        try:
            ensure_no_other_trainer()
            stop_old_worker()
            stopped = True
            common = BASE / "common-001"
            train(common)
            for tier in ["simple", "complex", "future"]:
                out = BASE / (tier + "-001")
                if not out.exists():
                    subprocess.run(
                        [
                            str(ROOT / ".venv/bin/python"),
                            str(ROOT / "scripts/run_agent_rl_tiered.py"),
                            "prepare",
                            "--tier",
                            tier,
                            "--common",
                            str(common),
                            "--output",
                            str(out),
                        ],
                        cwd=ROOT,
                        check=True,
                    )
                train(out)
            status(
                "three_tier_pilot_complete",
                final_test_opened=False,
                acceptance_passed=False,
                next="review development results, preregister multi-seed confirmatory comparison before independent tests",
            )
        except Exception as exc:
            status("stopped_for_review", error=str(exc), final_test_opened=False, acceptance_passed=False)
        finally:
            if stopped or (BASE / "inference-transition.json").exists():
                with (BASE / "restore-inference.log").open("a") as log:
                    child = subprocess.Popen(
                        [
                            str(ROOT / ".venv/bin/python"),
                            str(ROOT / "scripts/start_agent_rl_v1.py"),
                            "--experiment",
                            str(OLD),
                        ],
                        cwd=ROOT,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                save(BASE / "restore-inference.json", {"launcher_pid": child.pid, "experiment": str(OLD)})


if __name__ == "__main__":
    main()
