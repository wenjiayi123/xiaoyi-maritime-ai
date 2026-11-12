"""Release one verified worker, run one bounded adaptation, restore accepted demo."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import file_lease as fcntl
from scripts import run_agent_capability_scale as scale  # noqa: E402

c = scale.core


def health():
    try:
        return c.live.local_request("http://127.0.0.1:18781", "/health", timeout=2)
    except Exception:
        return None


def main(out, evaluation):
    from scripts.adapt_agent_capability_scale import verify
    cfg = verify(out)
    if (out / "LAUNCH.json").exists():
        raise ValueError("Launcher already started; inspect existing evidence instead")
    if (scale.BASE / "PAUSE").exists():
        raise ValueError("Expansion paused")
    expected = {g: m["parameter_fingerprint"] for g, m in cfg["source_models"].items()}
    h = health()
    if not h or h.get("experiment") != "experiment-004" or any(h["weights"].get(g) != v for g, v in expected.items()):
        raise ValueError("Existing worker is not the verified accepted version")
    pids = subprocess.check_output(["lsof", "-nP", "-iTCP:18781", "-sTCP:LISTEN", "-t"], text=True).split()
    if len(pids) != 1:
        raise ValueError("Ambiguous model worker ownership")
    pid = int(pids[0])
    command = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True)
    if "serve_agent_rl_v1.py" not in command or "experiment-004" not in command:
        raise ValueError("PID command differs from accepted worker")
    state = {"time": c.now(), "launcher_pid": os.getpid(), "worker_to_stop": pid, "worker_command": command,
             "worker_health": h, "new_model_loads_concurrently": 0, "phase": "releasing_worker"}
    code = 1
    stopped = False
    child = None
    with (scale.BASE / "adaptation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with (scale.ACCEPTED / "execution.lock").open("a") as native_lock:
                fcntl.flock(native_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                c.live.save(out / "LAUNCH.json", state)
                os.kill(pid, signal.SIGTERM)
                stopped = True
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    check = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
                    if check.returncode or not check.stdout.strip() or check.stdout.strip().startswith("Z"):
                        break
                    time.sleep(.25)
                else:
                    raise RuntimeError("Old worker did not exit; no new model loaded")
                if health() is not None:
                    raise RuntimeError("Model endpoint still occupied; no new model loaded")
            with (out / "run.log").open("xb") as log:
                child = subprocess.Popen([str(ROOT / ".venv-lora/bin/python"), "-u", str(ROOT / "scripts/adapt_agent_capability_scale.py"),
                                          "run", "--output", str(out), "--evaluation", str(evaluation)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                state.update(time=c.now(), phase="adaptation_and_native_evaluation", child_pid=child.pid, old_worker_exited=True)
                c.live.save(out / "LAUNCH.json", state)
                print(json.dumps(state, ensure_ascii=False), flush=True)
                code = child.wait()
                state.update(child_exit_code=code, child_finished_at=c.now())
        finally:
            # Child has exited before restoring the accepted 1.7B worker.
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                state["interrupted_child_exit_code"] = child.returncode
            if stopped and health() is None:
                with (out / "restore.log").open("ab") as log:
                    restorer = subprocess.Popen([str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/start_agent_rl_v1.py"),
                                                 "--experiment", str(c.OLD)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                                start_new_session=True)
                state.update(restore_launcher_pid=restorer.pid, phase="restoring_accepted_worker")
                c.live.save(out / "LAUNCH.json", state)
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    h = health()
                    if h and all(h["weights"].get(g) == v for g, v in expected.items()):
                        state.update(accepted_worker_restored=True, restored_health=h)
                        break
                    if restorer.poll() is not None:
                        break
                    time.sleep(1)
                if not state.get("accepted_worker_restored"):
                    state["restore_error"] = "Accepted worker not verified ready; inspect restore.log"
            state.update(time=c.now(), phase="finished" if state.get("accepted_worker_restored") else "needs_review", child_exit_code=code)
            c.live.save(out / "LAUNCH.json", state)
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(main(args.output.resolve(), args.evaluation.resolve()))
