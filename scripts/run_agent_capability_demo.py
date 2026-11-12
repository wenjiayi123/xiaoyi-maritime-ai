"""Registered, serial engineering rehearsal using the existing model worker."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import fcntl
except ImportError:  # Windows uses the project's non-blocking file lease.
    from app import windows_flock as fcntl
from app.agent_training import live  # noqa: E402
from app.agent_training.environment import LETTERS, digest  # noqa: E402
from app.agent_training.environment_v2 import REVISION  # noqa: E402

BASE = ROOT / ".codex_artifacts/agent-rl-capability-demo-20261102"
OLD = ROOT / ".codex_artifacts/agent-rl-v2-20261102/experiment-004"
GROUPS = ("E_more_sft", "D_rl")
SOURCE_FILES = [
    "scripts/run_agent_capability_demo.py", "scripts/serve_agent_rl_v1.py",
    "app/agent_training/live.py", "app/agent_training/environment.py",
    "app/agent_training/environment_v2.py", "app/agent_training/policy.py",
    "app/agent_training/policy_v2.py",
]


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.datetime.now().astimezone().isoformat()


def prompt_for(env, mode):
    text = env.prompt()
    if mode == "contracts":
        # Fixed tool documentation, identical for both models and every task.
        # Does not select, mask or reorder actions, or consult a teacher policy.
        text = text.replace("I=核验全部结果", "I=检查已有结果是否齐全（不会执行评估或比较）")
        text = text.replace("D=港口评估(", "D=运行港口情景评估(")
        text = text.replace("\n工具：", "\n工具职责：读取状态不会生成情景评估或方案比较结果；核验只检查已有结果。\n工具：")
    elif mode != "baseline":
        raise ValueError("Unknown prompt mode")
    return text


def cases():
    definitions = [
        ("energy-082-085", "能碳方案比较", "读取能碳系统当前状态，比较基准绿色偏好0.50、候选绿色偏好0.82、碳价85元/吨的方案，核验后交付带来源和执行记录的报告。", False),
        ("energy-072-120", "能碳参数变体", "读取能碳系统当前状态，比较基准绿色偏好0.50、候选绿色偏好0.72、碳价120元/吨的方案，核验后交付带来源和执行记录的报告。", False),
        ("port-berthing", "港口靠泊情景评估", "读取港口当前状态，评估高密度靠泊情景，核验结果后交付带来源和执行记录的报告。", False),
        ("port-congestion", "港口拥堵情景评估", "读取港口当前状态，评估港口拥堵情景，核验结果后交付带来源和执行记录的报告。", False),
        ("traffic", "航道交通态势报告", "读取马六甲交通系统当前状态，核验后交付包含排队船舶、延误时间及来源的报告。", False),
        ("joint-recovery", "跨系统联合报告与读取恢复", live.ACCEPTANCE_GOAL.removesuffix("只在本机工程模拟中操作。"), True),
    ]
    result = []
    for name, title, goal, fault in definitions:
        goal += "只在本机工程模拟中操作。"
        task = asdict(live.parse_goal(goal, inject_read_fault=fault))
        task["case_id"] = "capability-" + name
        result.append({"id": name, "title": title, "goal": goal, "fault": fault, "task": task})
    return result


def prepare(out, mode):
    out.mkdir(parents=True, exist_ok=False)
    summary = read(OLD / "audited-summary.json")
    models = {}
    for group, key in [("E_more_sft", "more_sft"), ("D_rl", "rl")]:
        path = OLD / "checkpoints" / key / "adapter_model.safetensors"
        models[group] = {"adapter": str(path), "file_sha256": sha(path), "parameter_fingerprint": summary["weights"][key]}
    protocol = {
        "time": now(), "purpose": "Engineering rehearsal and repeatability, not an independent algorithm comparison",
        "groups": list(GROUPS), "models": models, "source_experiment": str(OLD),
        "SFT_selection": "Reuse completed pure continued-SFT adapter E; earlier C remains archived. Choice made before this rehearsal.",
        "RL_method": read(OLD / "config.json")["method"],
        "prompt_mode": mode, "prompt_change_is_harness_change_not_training": mode != "baseline",
        "cases": cases(), "repetitions": 2, "max_steps": 18,
        "repeat_failure_policy": "Defer repetition 2 of a group/case after failure in repetition 1; preserve failure and count deferred explicitly, never as success.",
        "success": "All required observations and exact requested calculation results, verification and report must complete; offline replay must pass.",
        "stable_in_this_suite": "Every registered attempt succeeds for both models (12/12 each); this is a finite rehearsed suite, not universal reliability.",
        "scope": "Real localhost APIs backed by public-data-calibrated engineering simulation; 13 constrained action/parameter candidates; deterministic user parameter parsing and report rendering.",
        "new_training": False, "production_authority": False,
    }
    live.save(out / "PROTOCOL.json", protocol)
    sources = {}
    for rel in SOURCE_FILES:
        p = ROOT / rel
        sources[rel] = sha(p)
        target = out / "source" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(p.read_bytes())
    live.save(out / "SOURCES.json", sources)
    live.save(out / "LOCK.json", {n: sha(out / n) for n in ["PROTOCOL.json", "SOURCES.json"]})
    live.save(out / "STATUS.json", {"time": now(), "phase": "registered", "model_calls": 0})
    return protocol


def verify(out):
    for name, h in read(out / "LOCK.json").items():
        if sha(out / name) != h:
            raise ValueError("Protocol drift: " + name)
    for rel, h in read(out / "SOURCES.json").items():
        if sha(ROOT / rel) != h or sha(out / "source" / rel) != h:
            raise ValueError("Source drift: " + rel)
    p = read(out / "PROTOCOL.json")
    for model in p["models"].values():
        if sha(Path(model["adapter"])) != model["file_sha256"]:
            raise ValueError("Adapter file drift")
    return p


def execute(job, folder, protocol):
    env = live.environment_for_job(job)
    backend = live.NativeBackend(folder)
    started = time.monotonic()
    job.update(status="running", started_at=now())
    live.save(folder / "job.json", job)
    try:
        while not env.done:
            if (BASE / "PAUSE").exists():
                raise RuntimeError("User requested demonstration pause")
            prompt = prompt_for(env, protocol["prompt_mode"])
            response = live.local_request("http://127.0.0.1:18781", "/decide", {"prompt": prompt, "group": job["group"]}, timeout=120)
            if response.get("adapter_sha256") != job["expected_adapter_sha256"] or response.get("group") != job["group"]:
                raise ValueError("Model identity mismatch")
            transition = live.native_step(env, backend, response["choice"])
            transition.update(decision_input=prompt, model=response)
            job.update(steps=env.steps, evidence=backend.evidence, elapsed_seconds=time.monotonic() - started)
            live.save(folder / "job.json", job)
        job.update(status="completed" if env.success else "failed", success=env.success, outcome=env.outcome(), report="report.html" if env.success else None)
    except Exception as exc:
        job.update(status="failed", success=False, error=str(exc)[:500], steps=env.steps, evidence=backend.evidence)
    finally:
        if backend.clock_owned:
            try:
                result = backend.execute({"tool": "energy.restore", "arguments": {}}, env)
                job["runtime_cleanup"] = {"ok": True, "sha256": digest(result), "model_action": False}
            except Exception as exc:
                job["runtime_cleanup"] = {"ok": False, "error": str(exc)}
        job.update(finished_at=now(), elapsed_seconds=time.monotonic() - started)
        live.save(folder / "job.json", job)
    return job


def audit_job(job, folder, protocol):
    env = live.environment_for_job(job)
    if job["expected_adapter_sha256"] != protocol["models"][job["group"]]["parameter_fingerprint"]:
        raise ValueError("Unexpected model")
    for actual in job["steps"]:
        if actual["decision_input"] != prompt_for(env, protocol["prompt_mode"]):
            raise ValueError("Wrong model input")
        model = actual["model"]
        probabilities = model["probabilities"]
        if (len(probabilities) != 13 or not all(math.isfinite(x) and x >= 0 for x in probabilities)
                or not math.isclose(sum(probabilities), 1, abs_tol=2e-6)
                or actual["choice"] != LETTERS[max(range(13), key=lambda i: probabilities[i])]
                or model["choice"] != actual["choice"] or model["group"] != job["group"]
                or model["adapter_sha256"] != job["expected_adapter_sha256"] or not actual["model_action"]):
            raise ValueError("Action unsupported by model output")

        class RecordedBackend:
            def execute(self, action, state):
                if actual.get("native_result_valid") is False:
                    raise RuntimeError(actual["feedback"].removeprefix("native_error:"))
                entry = actual["native_evidence"]
                record = read(folder / entry["file"])
                if digest(record) != entry["sha256"] or record["action"] != action or record["production_authority"] is not False:
                    raise ValueError("Raw response/action mismatch")
                return record["response"]

            def record(self, action, response):
                return actual["native_evidence"]

        rebuilt = live.native_step(env, RecordedBackend(), actual["choice"])
        rebuilt.update(decision_input=actual["decision_input"], model=model)
        if rebuilt != actual:
            raise ValueError("Transcript replay mismatch")
    if env.success != job["success"] or (job.get("outcome") is not None and env.outcome() != job["outcome"]):
        raise ValueError("Unsupported outcome")
    for entry in job["evidence"]:
        record = read(folder / entry["file"])
        if digest(record) != entry["sha256"]:
            raise ValueError("Evidence checksum mismatch")
        if entry["tool"] == "energy.compare":
            rows = record["response"]["alternatives"]
            if [r["parameters"]["green"] for r in rows] != [env.task.baseline, env.task.green]:
                raise ValueError("Wrong energy comparison")
            for row in rows:
                raw = row["raw"]
                if raw["green_preference"] != row["parameters"]["green"] or raw["carbon_market"]["carbon_price_cny_per_ton"] != env.task.carbon:
                    raise ValueError("Solver parameters differ")
        if entry["tool"] == "port.evaluate" and record["response"]["raw"]["scenario"] != env.task.scenario:
            raise ValueError("Wrong port scenario")
    if env.success:
        report = read(folder / "report.json")
        final = read(folder / job["steps"][-1]["native_evidence"]["file"])["response"]
        if not (folder / "report.html").exists() or not all(report["verification"]["checks"].values()) or final["sha256"] != digest(report):
            raise ValueError("Unsupported report")
        required = {r + ".read" for r in env.required["reads"]}
        if env.required["port"]:
            required.add("port.evaluate")
        if env.required["energy"]:
            required.add("energy.compare")
        if not required <= {e["tool"] for e in job["evidence"]}:
            raise ValueError("Missing required native tool")
    return {"passed": True, "success": env.success, "steps": len(job["steps"]), "job_sha256": sha(folder / "job.json"), "model_calls_in_audit": 0}


def run(out):
    p = verify(out)
    with (BASE / "execution.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        health = live.local_request("http://127.0.0.1:18781", "/health", timeout=5)
        if any(health["weights"].get(g) != p["models"][g]["parameter_fingerprint"] for g in p["groups"]):
            raise ValueError("Wrong existing inference service")
        results = []
        for repetition in range(1, p["repetitions"] + 1):
            for case in p["cases"]:
                for group in p["groups"]:
                    ident = f"{case['id']}-{group}-r{repetition}"
                    folder = out / "runs" / ident
                    if repetition > 1 and any(r["case"] == case["id"] and r["group"] == group and r.get("success") is False for r in results):
                        results.append({"id": ident, "case": case["id"], "group": group, "repetition": repetition, "status": "deferred_after_failure"})
                        continue
                    if (BASE / "PAUSE").exists():
                        raise RuntimeError("Demonstration paused")
                    if (folder / "AUDIT.json").exists():
                        job = read(folder / "job.json")
                        checked = audit_job(job, folder, p)
                    else:
                        if folder.exists():
                            raise RuntimeError("Partial attempt retained; explicit recovery needed: " + ident)
                        folder.mkdir(parents=True)
                        job = {"id": ident, "goal": case["goal"], "task": case["task"], "group": group,
                               "status": "queued", "success": False, "steps": [], "evidence": [],
                               "experiment": "experiment-004", "environment": REVISION,
                               "expected_adapter_sha256": p["models"][group]["parameter_fingerprint"],
                               "production_authority": False, "fault_injection_requested": case["fault"]}
                        live.save(out / "STATUS.json", {"time": now(), "phase": "running", "active": ident, "completed": len(results), "total": 24})
                        job = execute(job, folder, p)
                        checked = audit_job(job, folder, p)
                        live.save(folder / "AUDIT.json", checked)
                    result = {"id": ident, "case": case["id"], "group": group, "repetition": repetition,
                              "status": job["status"], "success": job["success"], "steps": len(job["steps"]),
                              "seconds": job["elapsed_seconds"], "audit": checked, "folder": str(folder)}
                    results.append(result)
                    live.save(out / "PROGRESS.json", {"time": now(), "results": results})
                    print(json.dumps(result, ensure_ascii=False), flush=True)
        counts = {g: {"successes": sum(r.get("success", False) for r in results if r["group"] == g),
                      "attempted": sum("success" in r for r in results if r["group"] == g),
                      "registered": sum(r["group"] == g for r in results),
                      "deferred": sum(r["status"] == "deferred_after_failure" for r in results if r["group"] == g)} for g in p["groups"]}
        complete = all(v["successes"] == v["registered"] for v in counts.values())
        live.save(out / "RESULTS.json", {"time": now(), "counts": counts, "results": results, "suite_passed": complete,
                                       "scope": p["purpose"], "new_training": False, "rl_superiority_claimed": False})
        live.save(out / "STATUS.json", {"time": now(), "phase": "complete", "counts": counts, "suite_passed": complete})
        print(json.dumps({"complete": True, "counts": counts, "suite_passed": complete}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prompt-mode", choices=["baseline", "contracts"], default="contracts")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output.resolve(), args.prompt_mode)
    else:
        run(args.output.resolve())


if __name__ == "__main__":
    main()
