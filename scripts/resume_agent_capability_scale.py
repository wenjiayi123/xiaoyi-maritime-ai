"""Evaluate fixed adapted weights with native Python3.12 and one separate worker."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import file_lease as fcntl
from scripts import run_agent_capability_scale as scale  # noqa: E402
from scripts.launch_agent_capability_adaptation import health  # noqa: E402

c = scale.core


def prepare(out, adaptation):
    from scripts.adapt_agent_capability_scale import verify
    cfg = verify(adaptation)
    audit = c.read(adaptation / "PARAMETER_AND_OBJECTIVE_AUDIT.json")
    complete = c.read(adaptation / "TRAINING_COMPLETE.json")
    if not audit["passed"] or audit["updates_verified"] != 64 or complete["fixed_final_step"] != 64:
        raise ValueError("Fixed adapted weights are not fully audited")
    draft = out.with_name(out.name + ".preparing")
    scale.prepare(draft)
    p = c.read(draft / "PROTOCOL.json")
    adapter = adaptation / "checkpoints/step-00064/adapter_model.safetensors"
    p["models"]["D_rl"] = {"adapter": str(adapter), "file_sha256": c.sha(adapter), "parameter_fingerprint": complete["rl_after"]}
    p.update(new_training=True, adaptation=str(adaptation), additional_rl_updates=64, additional_sft_updates=0,
             source_experiment=str(adaptation), baseline_native_round=cfg["source_native_round"],
             RL_method=cfg["method"], data_split=cfg["data_split"],
             evaluation_transport="Native API executor in original Python3.12 environment and one Python3.9 1.7B worker via localhost HTTP",
             prior_infrastructure_failure="round-002 is preserved: missing fastapi in training Python environment; no scores were changed and no retraining performed")
    registry = draft / "worker"
    weights = c.read(c.OLD / "summary.json")["weights"].copy()
    weights["rl"] = complete["rl_after"]
    for key in ["sft", "more_sft"]:
        shutil.copytree(c.OLD / "checkpoints" / key, registry / "checkpoints" / key)
    target = registry / "checkpoints/rl"
    target.mkdir(parents=True)
    for name in ["adapter_model.safetensors", "adapter_config.json"]:
        shutil.copy2(adapter.parent / name, target / name)
    c.live.save(registry / "summary.json", {"rl_parameters_changed": True, "environment": c.REVISION,
                                            "seed": cfg["seed"], "weights": weights, "source_adaptation": str(adaptation)})
    c.live.save(draft / "PROTOCOL.json", p)
    c.live.save(draft / "TRAINING_AUDIT_SNAPSHOT.json", audit)
    sources = c.read(draft / "SOURCES.json")
    for f in [Path(__file__), ROOT / "scripts/launch_agent_capability_adaptation.py",
              adaptation / "CONFIG.json", adaptation / "TRAINING_COMPLETE.json"]:
        rel = str(f.relative_to(ROOT))
        sources[rel] = c.sha(f)
        dst = draft / "source" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
    c.live.save(draft / "SOURCES.json", sources)
    names = ["PROTOCOL.json", "SOURCES.json", "TRAINING_AUDIT_SNAPSHOT.json", "worker/summary.json"]
    names += [str(f.relative_to(draft)) for f in sorted(registry.glob("checkpoints/*/*.safetensors"))]
    names += [str(f.relative_to(draft)) for f in sorted(registry.glob("checkpoints/*/adapter_config.json"))]
    c.live.save(draft / "LOCK.json", {n: c.sha(draft / n) for n in names})
    draft.rename(out)
    print(json.dumps({"registered": str(out), "reuse_final_rl_step": 64, "new_training_updates": 0}), flush=True)


def run(out):
    p = c.verify(out)
    if (out / "LAUNCH.json").exists() or (scale.BASE / "PAUSE").exists():
        raise ValueError("Already launched or currently paused")
    old = c.read(scale.ACCEPTED / "round-004/PROTOCOL.json")["models"]
    expected = {g: m["parameter_fingerprint"] for g, m in old.items()}
    h = health()
    if not h or any(h["weights"].get(g) != v for g, v in expected.items()):
        raise ValueError("Accepted model service must be verified before switching")
    owned = subprocess.check_output(["lsof", "-nP", "-iTCP:18781", "-sTCP:LISTEN", "-t"], text=True).split()
    if len(owned) != 1:
        raise ValueError("Ambiguous model process")
    pid = int(owned[0])
    cmd = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True)
    if "serve_agent_rl_v1.py" not in cmd or "experiment-004" not in cmd:
        raise ValueError("Unexpected accepted worker process")
    state = {"time": c.now(), "phase": "switching_one_worker", "pid": os.getpid(), "old_worker_pid": pid,
             "native_python": sys.executable, "concurrent_base_models_max": 1, "new_training_updates": 0}
    child = None
    stopped = False
    code = 1
    original_execute = c.execute
    with (scale.BASE / "adaptation.lock").open("a") as controller_lock:
        fcntl.flock(controller_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with (scale.ACCEPTED / "execution.lock").open("a") as native_lock:
                fcntl.flock(native_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                c.live.save(out / "LAUNCH.json", state)
                os.kill(pid, signal.SIGTERM)
                stopped = True
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    row = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
                    if row.returncode or not row.stdout.strip() or row.stdout.strip().startswith("Z"):
                        break
                    time.sleep(.25)
                else:
                    raise RuntimeError("Accepted worker did not exit; no new model loaded")
                if health() is not None:
                    raise RuntimeError("Model endpoint occupied after exit")
            with (out / "worker.log").open("xb") as log:
                child = subprocess.Popen([str(ROOT / ".venv-lora/bin/python"), "-u", str(ROOT / "scripts/serve_agent_rl_v1.py"),
                                          "--experiment", str(out / "worker")], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            state.update(worker_pid=child.pid, phase="loading_fixed_adapters")
            c.live.save(out / "LAUNCH.json", state)
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                h = health()
                if h and all(h["weights"].get(g) == m["parameter_fingerprint"] for g, m in p["models"].items()):
                    break
                if child.poll() is not None:
                    raise RuntimeError("Evaluation worker exited")
                time.sleep(1)
            else:
                raise RuntimeError("Evaluation worker did not become ready")

            def execute(job, folder, protocol):
                job["experiment"] = Path(protocol["adaptation"]).name
                return original_execute(job, folder, protocol)

            c.execute = execute
            state.update(time=c.now(), phase="native_evaluation", worker_health=h)
            c.live.save(out / "LAUNCH.json", state)
            code = scale.run(out)
            result = c.read(out / "RESULTS.json")
            result.update(new_training=True, additional_rl_updates=64, additional_sft_updates=0, retraining_for_infrastructure_repair=False)
            c.live.save(out / "RESULTS.json", result)
        except Exception as exc:
            current = c.read(out / "STATUS.json")
            c.live.save(out / "STATUS.json", {**current, "time": c.now(), "phase": "stopped_for_review", "error": str(exc)})
            raise
        finally:
            c.execute = original_execute
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            if stopped and health() is None:
                with (out / "restore.log").open("ab") as log:
                    restore = subprocess.Popen([str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/start_agent_rl_v1.py"),
                                                "--experiment", str(c.OLD)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                               start_new_session=True)
                state.update(restore_pid=restore.pid, phase="restoring_accepted_worker")
                c.live.save(out / "LAUNCH.json", state)
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    h = health()
                    if h and all(h["weights"].get(g) == v for g, v in expected.items()):
                        state["accepted_worker_restored"] = True
                        break
                    if restore.poll() is not None:
                        break
                    time.sleep(1)
            state.update(time=c.now(), phase="finished" if state.get("accepted_worker_restored") else "needs_review", exit_code=code)
            c.live.save(out / "LAUNCH.json", state)
            c.live.save(out / "process-exit.json", {"time": c.now(), "pid": os.getpid(), "exit_code": code,
                                                    "accepted_worker_restored": state.get("accepted_worker_restored", False)})
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adaptation", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output.resolve(), args.adaptation.resolve())
    else:
        raise SystemExit(run(args.output.resolve()))
