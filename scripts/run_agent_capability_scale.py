"""Frozen 24+6 native capability rehearsal, reusing the single existing worker."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import fcntl
except ImportError:  # Windows uses the project's non-blocking file lease.
    from app import windows_flock as fcntl
from scripts import run_agent_capability_demo as core  # noqa: E402
from scripts import run_agent_capability_demo_v2 as wording  # noqa: E402

ACCEPTED = core.BASE
BASE = ROOT / ".codex_artifacts/agent-rl-capability-scale-20261102"
core.prompt_for = wording.prompt_for
# Only this new process uses this pause path; accepted scripts remain unchanged.
core.BASE = BASE


def prepare(out):
    if out.exists():
        raise ValueError("Output already exists; do not overwrite a frozen experiment")
    prior = core.verify(ACCEPTED / "round-004")
    accepted = core.read(ACCEPTED / "ACCEPTANCE.json")
    if accepted.get("passed") is not True:
        raise ValueError("Accepted baseline is not passed")
    catalog = core.read(BASE / "TASK_CATALOG.json")
    cases = catalog["cases"]
    if (len(cases) != 30 or len({c["semantic_contract_sha256"] for c in cases}) != 30
            or sum(c["stage"] == "core24" for c in cases) != 24
            or sum(c["stage"] == "extension6" for c in cases) != 6):
        raise ValueError("Invalid 24+6 task catalog")
    p = {
        "time": core.now(), "purpose": "Finite engineering expansion and repeatability, not independent algorithm superiority testing",
        "groups": prior["groups"], "models": prior["models"], "source_experiment": prior["source_experiment"],
        "RL_method": prior["RL_method"], "prompt_mode": wording.MODE,
        "wording_change": prior["wording_change"], "cases": cases, "repetitions": 2, "max_steps": 18,
        "schedule": ["core24-r1", "extension6-r1", "core24-r2", "extension6-r2"],
        "gate": "Each entire stage must pass before the next starts. Complete both groups for all cases in that stage; keep every failure. On a failed stage, stop for diagnosis, do not repeat it or silently omit it.",
        "infrastructure_error": "An exception in execution or audit stops the run after preserving the attempt; no automatic reattempt.",
        "success": prior["success"],
        "acceptance": "All 30 distinct contracts, both models, two executions each, with successful offline replay: 60/60 each, 120/120 total. Finite engineering repeatability only.",
        "scope": prior["scope"], "new_training": False, "production_authority": False,
        "preservation": {"accepted_root": str(ACCEPTED), "accepted_zip_sha256": core.sha(ACCEPTED / "专家展示包-最终版.zip"),
                         "old_final_test_must_remain_closed": True},
        "compute": {"new_base_models": 0, "parallel_decisions": 1, "max_executions": 120, "max_model_calls": 2160,
                    "worker": "http://127.0.0.1:18781", "reuse_existing_cached_worker": True},
        "counting": "30 distinct task instances, not 30 new business abilities, training examples or independent tests; six prior accepted anchor instances are marked. Report all success/failure and unattempted counts.",
    }
    draft = out.with_name(out.name + ".preparing")
    draft.mkdir(parents=True, exist_ok=False)
    source_files = list(dict.fromkeys([*core.SOURCE_FILES, "scripts/run_agent_capability_demo_v2.py",
                                     "scripts/run_agent_capability_scale.py",
                                     str((BASE / "TASK_CATALOG.json").relative_to(ROOT))]))
    sources = {}
    for rel in source_files:
        src = ROOT / rel
        sources[rel] = core.sha(src)
        dst = draft / "source" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    core.live.save(draft / "PROTOCOL.json", p)
    core.live.save(draft / "SOURCES.json", sources)
    core.live.save(draft / "LOCK.json", {n: core.sha(draft / n) for n in ["PROTOCOL.json", "SOURCES.json"]})
    core.live.save(draft / "STATUS.json", {"time": core.now(), "phase": "registered", "total": 120, "model_calls": 0})
    draft.rename(out)
    print(json.dumps({"registered": str(out), "cases": 30, "planned_executions": 120, "new_training": False}))


def counts(p, results):
    return {g: {"successes": sum(r["success"] for r in results if r["group"] == g),
                "attempted": sum(r["group"] == g for r in results),
                "registered": len(p["cases"]) * p["repetitions"],
                "not_attempted": len(p["cases"]) * p["repetitions"] - sum(r["group"] == g for r in results)}
            for g in p["groups"]}


def save_progress(out, p, results, phase, **extra):
    current = {"time": core.now(), "phase": phase, "pid": os.getpid(), "completed": len(results), "total": 120,
               "counts": counts(p, results), "model_calls": sum(r["steps"] for r in results), **extra}
    core.live.save(out / "STATUS.json", current)
    core.live.save(out / "PROGRESS.json", {**current, "results": results})


def run(out):
    p = core.verify(out)
    if core.sha(ACCEPTED / "专家展示包-最终版.zip") != p["preservation"]["accepted_zip_sha256"]:
        raise ValueError("Accepted package changed")
    with (BASE / "execution.lock").open("a") as lock, (ACCEPTED / "execution.lock").open("a") as shared_lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # The accepted live UI uses the same lock. No interleaved native jobs.
        fcntl.flock(shared_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        health = core.live.local_request("http://127.0.0.1:18781", "/health", timeout=8)
        if any(health["weights"].get(g) != p["models"][g]["parameter_fingerprint"] for g in p["groups"]):
            raise ValueError("Worker model identity mismatch")
        core.live.save(out / "WORKER_START.json", {"time": core.now(), "health": health, "runner_pid": os.getpid()})
        results = []
        for stage in p["schedule"]:
            kind, rep_text = stage.rsplit("-r", 1)
            repetition = int(rep_text)
            stage_rows = []
            for case in [c for c in p["cases"] if c["stage"] == kind]:
                for group in p["groups"]:
                    if (BASE / "PAUSE").exists():
                        raise RuntimeError("Expansion pause requested")
                    ident = f"{case['id']}-{group}-r{repetition}"
                    folder = out / "runs" / ident
                    save_progress(out, p, results, "running", stage=stage, active=ident)
                    if (folder / "AUDIT.json").exists():
                        job = core.read(folder / "job.json")
                        audit = core.audit_job(job, folder, p)
                    else:
                        if folder.exists():
                            raise RuntimeError("Partial attempt preserved; explicit audit/recovery needed: " + ident)
                        folder.mkdir(parents=True)
                        job = {"id": ident, "goal": case["goal"], "task": case["task"], "group": group,
                               "status": "queued", "success": False, "steps": [], "evidence": [],
                               "experiment": "experiment-004", "environment": core.REVISION,
                               "expected_adapter_sha256": p["models"][group]["parameter_fingerprint"],
                               "production_authority": False, "fault_injection_requested": case["inject_read_fault"]}
                        job = core.execute(job, folder, p)
                        audit = core.audit_job(job, folder, p)
                        core.live.save(folder / "AUDIT.json", audit)
                    row = {"id": ident, "case": case["id"], "group": group, "stage": stage,
                           "repetition": repetition, "status": job["status"], "success": job["success"],
                           "steps": len(job["steps"]), "seconds": job["elapsed_seconds"], "audit": audit,
                           "folder": str(folder), "previously_accepted_anchor": case["previously_accepted_anchor"]}
                    results.append(row)
                    stage_rows.append(row)
                    save_progress(out, p, results, "running", stage=stage, last_completed=ident)
                    print(json.dumps(row, ensure_ascii=False), flush=True)
                    if job.get("error"):
                        raise RuntimeError("Execution exception preserved in " + ident + ": " + job["error"])
            passed = all(r["success"] for r in stage_rows)
            core.live.save(out / "stages" / (stage + ".json"), {"time": core.now(), "passed": passed, "results": stage_rows})
            if not passed:
                save_progress(out, p, results, "needs_diagnosis", stage=stage, stage_passed=False)
                core.live.save(out / "RESULTS.json", {"time": core.now(), "counts": counts(p, results), "results": results,
                                                      "suite_passed": False, "new_training": False, "rl_superiority_claimed": False,
                                                      "stop_reason": "Registered stage gate failed; unattempted tasks are not successes."})
                return 2
        # Revalidate all source/adapter identities and the accepted archive after execution.
        core.verify(out)
        if core.sha(ACCEPTED / "专家展示包-最终版.zip") != p["preservation"]["accepted_zip_sha256"]:
            raise ValueError("Accepted package changed during expansion")
        core.live.save(out / "RESULTS.json", {"time": core.now(), "counts": counts(p, results), "results": results,
                                              "suite_passed": True, "new_training": False, "rl_superiority_claimed": False,
                                              "scope": p["purpose"]})
        save_progress(out, p, results, "complete", suite_passed=True)
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if args.command == "prepare":
        prepare(out)
        return
    code = 1
    try:
        code = run(out)
    except Exception as exc:
        prior = core.read(out / "STATUS.json") if (out / "STATUS.json").exists() else {}
        core.live.save(out / "STATUS.json", {**prior, "time": core.now(), "phase": "stopped_for_review", "error": str(exc)})
        raise
    finally:
        core.live.save(out / "process-exit.json", {"time": core.now(), "pid": os.getpid(), "exit_code": code})
    raise SystemExit(code)


if __name__ == "__main__":
    main()
