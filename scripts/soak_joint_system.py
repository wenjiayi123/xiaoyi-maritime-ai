"""Bounded wall-clock soak of local registered services, original assessment and policies.

Never acknowledges a mission on behalf of Flutter and never changes native controls.
Each run has a fresh evidence directory; failures and concurrent-busy skips are retained.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SERVICES = {
    "xiaoyi": ("http://127.0.0.1:8010/api/harness/joint/capabilities", "xiaoyi-joint-capabilities.v1"),
    "twin": ("http://127.0.0.1:8000/health/live", None),
    "energy": ("http://127.0.0.1:8808/api/health", None),
    "energy_web": ("http://127.0.0.1:5173/", "<!doctype html"),
    "malacca": ("http://127.0.0.1:5174/api/rl/health", "malacca-reference-rl"),
    "mobile_web": ("http://127.0.0.1:7357/", "PortAI"),
    "policy": ("http://127.0.0.1:11839/health", "xiaoyi-policy-runtime.v1"),
    "generation": ("http://127.0.0.1:11435/health", "ok"),
    "embedding": ("http://127.0.0.1:11436/health", "ok"),
}


def fetch(url, body=None, timeout=8):
    raw = None if body is None else json.dumps(body, allow_nan=False).encode()
    request = urllib.request.Request(url, data=raw, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read(2_000_001)


def api(path, body=None):
    return json.loads(fetch("http://127.0.0.1:8010/api/harness/joint" + path, body, 35)[1])


def probe(item):
    name, (url, marker) = item
    start = time.monotonic()
    try:
        status, body = fetch(url)
        value = body.decode("utf-8")
        if len(body) > 2_000_000 or (marker and marker.lower() not in value.lower()):
            raise ValueError("service identity marker mismatch or oversized response")
        return name, {
            "ok": status == 200,
            "seconds": time.monotonic() - start,
            "status": status,
            "response_sha256": hashlib.sha256(body).hexdigest(),
        }
    except Exception as exc:
        return name, {"ok": False, "seconds": time.monotonic() - start, "error": str(exc)[:500]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=7200)
    parser.add_argument("--interval", type=float, default=15)
    parser.add_argument("--assessment-cadence", type=float, default=600)
    parser.add_argument("--assessment-delay", type=float, default=45)
    parser.add_argument("--policy-cadence", type=float, default=120)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.seconds < 30 or args.interval < 1:
        parser.error("duration must be >=30 seconds; interval >=1 second")
    if min(args.assessment_cadence, args.policy_cadence) < 30 or args.assessment_delay < 0:
        parser.error("workload cadences must be >=30 seconds; assessment delay >=0")
    args.out.mkdir(parents=True, exist_ok=False)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    began = time.monotonic()
    epoch = time.time()
    protocol = {
        "schema": "xiaoyi-joint-soak.v2",
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "pid": os.getpid(),
        "planned_wall_seconds": args.seconds,
        "interval_seconds": args.interval,
        "services": SERVICES,
        "policy_cadence_seconds": args.policy_cadence,
        "assessment_cadence_seconds": args.assessment_cadence,
        "assessment_scope": "original short assessment; require_mobile=False, mutate_sandbox=False",
        "native_gui_included": False,
        "production_authority": False,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (args.out / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2))
    samples = []
    workloads = []
    pending = None
    next_policy = began
    next_assessment = began + args.assessment_delay
    with (
        concurrent.futures.ThreadPoolExecutor(max_workers=len(SERVICES)) as pool,
        (args.out / "samples.ndjson").open("w") as stream,
        (args.out / "workloads.ndjson").open("w") as work,
    ):
        while not stopping and time.monotonic() - began <= args.seconds:
            tick = time.monotonic()
            health = dict(pool.map(probe, SERVICES.items()))
            ps = subprocess.check_output(["ps", "-axo", "pid=,ppid=,rss=,pcpu=,stat=,command="], text=True)
            processes = [
                line.strip()
                for line in ps.splitlines()
                if any(
                    s in line
                    for s in [
                        "uvicorn app.",
                        "Virtualization.VirtualMachine",
                        "Godot --headless",
                        "llama-server",
                        "http.server 7357",
                        "node_modules/.bin/vite",
                        "malacca-port-sandbox",
                    ]
                )
            ]
            sample = {
                "epoch": time.time(),
                "elapsed_seconds": time.monotonic() - began,
                "health": health,
                "processes": processes,
                "load_average": os.getloadavg(),
            }
            samples.append(sample)
            stream.write(json.dumps(sample) + "\n")
            stream.flush()
            try:
                jobs = api("/missions")["items"]
                other_active = any(
                    j["status"] in ["running", "waiting_business_approval"] and j["id"] != pending for j in jobs
                )
                if pending:
                    job = api("/missions/" + pending)
                    if job["status"] != "running":
                        exported = api("/missions/" + pending + "/export")
                        (args.out / (pending + ".json")).write_text(json.dumps(exported, ensure_ascii=False, indent=2))
                        result = {
                            "kind": "legacy_assessment",
                            "id": pending,
                            "status": job["status"],
                            "integrity": exported["integrity"],
                            "elapsed_seconds": time.monotonic() - began,
                        }
                        if job["status"] == "partial":
                            assert job["request_id"].startswith("soak-") and not job["config"]["require_mobile"]
                            assert all(
                                exported["integrity"][k]
                                for k in ["event_chain_valid", "result_hashes_valid", "business_operation_hashes_valid"]
                            )
                            ended = api("/missions/" + pending + "/control/cancel", {})
                            assert ended["status"] == "cancelled"
                            result["test_cleanup_status"] = ended["status"]
                            (args.out / (pending + "-closed.json")).write_text(
                                json.dumps(api("/missions/" + pending + "/export"), ensure_ascii=False, indent=2)
                            )
                        workloads.append(result)
                        work.write(json.dumps(result) + "\n")
                        work.flush()
                        pending = None
                if time.monotonic() >= next_policy:
                    if other_active or pending:
                        result = {
                            "kind": "policy",
                            "status": "skipped_busy",
                            "elapsed_seconds": time.monotonic() - began,
                        }
                    else:
                        from app.harness.transport import compare, fixture

                        seed = 55000 + len(workloads)
                        case = fixture(seed, 30, bool(seed % 2)).model_copy(update={"allow_refill": bool(seed % 2)})
                        result = {
                            "kind": "policy",
                            "status": "completed",
                            "elapsed_seconds": time.monotonic() - began,
                            "comparison": compare(case),
                        }
                    workloads.append(result)
                    work.write(json.dumps(result, ensure_ascii=False) + "\n")
                    work.flush()
                    next_policy = time.monotonic() + args.policy_cadence
                if time.monotonic() >= next_assessment:
                    if other_active or pending:
                        result = {"kind": "legacy_assessment_start", "status": "skipped_busy"}
                    else:
                        job = api(
                            "/missions",
                            {
                                "request_id": "soak-" + uuid.uuid4().hex,
                                "goal": "稳定性验收：复核原有联合评估，不修改沙盘、不代替移动端签收。",
                                "require_mobile": False,
                                "mutate_sandbox": False,
                                "max_seconds": 180,
                            },
                        )
                        pending = job["id"]
                        try:
                            api("/missions/" + pending + "/approval", {"plan_sha256": job["plan_sha256"]})
                            result = {"kind": "legacy_assessment_start", "status": "started", "id": pending}
                        except urllib.error.HTTPError as exc:
                            if exc.code != 409:
                                raise
                            detail = exc.read().decode()
                            api("/missions/" + pending + "/control/cancel", {})
                            result = {
                                "kind": "legacy_assessment_start",
                                "status": "busy_rejected",
                                "id": pending,
                                "response": detail,
                                "test_cleanup_status": "cancelled",
                            }
                            pending = None
                    result["elapsed_seconds"] = time.monotonic() - began
                    workloads.append(result)
                    work.write(json.dumps(result) + "\n")
                    work.flush()
                    next_assessment = time.monotonic() + args.assessment_cadence
            except Exception as exc:
                result = {
                    "kind": "workload_error",
                    "elapsed_seconds": time.monotonic() - began,
                    "error": str(exc)[:1000],
                }
                workloads.append(result)
                work.write(json.dumps(result) + "\n")
                work.flush()
            (args.out / "progress.json").write_text(
                json.dumps(
                    {
                        "elapsed_seconds": time.monotonic() - began,
                        "samples": len(samples),
                        "pending_mission": pending,
                        "failed_probes": {k: sum(not s["health"][k]["ok"] for s in samples) for k in SERVICES},
                    },
                    indent=2,
                )
            )
            remaining = min(args.interval - (time.monotonic() - tick), args.seconds - (time.monotonic() - began))
            if remaining <= 0 and time.monotonic() - began >= args.seconds:
                break
            if remaining > 0:
                time.sleep(remaining)
        final_health = dict(pool.map(probe, SERVICES.items()))
        last = {
            "epoch": time.time(),
            "elapsed_seconds": time.monotonic() - began,
            "health": final_health,
            "processes": [],
            "load_average": os.getloadavg(),
        }
        stream.write(json.dumps(last) + "\n")
        samples.append(last)
    summary = {
        "schema": "xiaoyi-joint-soak-result.v1",
        "planned_wall_seconds": args.seconds,
        "actual_wall_seconds": time.time() - epoch,
        "monotonic_seconds": time.monotonic() - began,
        "duration_complete": not stopping and time.monotonic() - began >= args.seconds,
        "samples": len(samples),
        "workloads": len(workloads),
        "pending_mission": pending,
        "health": {},
        "production_authority": False,
        "native_gui_verified": False,
    }
    for name in SERVICES:
        values = sorted(s["health"][name]["seconds"] for s in samples if s["health"][name]["ok"])
        summary["health"][name] = {
            "probes": len(samples),
            "failed": sum(not s["health"][name]["ok"] for s in samples),
            "p95_seconds": values[max(0, int(len(values) * 0.95) - 1)] if values else None,
            "max_seconds": max(values) if values else None,
        }
    summary["workload_errors"] = [w for w in workloads if w["kind"] == "workload_error"]
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
