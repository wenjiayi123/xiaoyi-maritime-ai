"""Actual persisted HTTP study, independent trajectory readback and retained failures."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18010")
    parser.add_argument("--out", required=True)
    parser.add_argument("--steps", type=int, default=20000)
    args = parser.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=False)

    def api(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(
            Request(
                args.base_url + "/api/harness/assurance/" + path,
                data=data,
                headers={"Content-Type": "application/json"},
            ),
            timeout=60,
        ) as response:
            return json.load(response)

    def save(name, value):
        (out / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    catalog = api("crossport/catalog")
    save("sources", catalog)
    if not catalog["available"]:
        raise ValueError(catalog["error"])
    save("legacy-diagnosis", api("crossport/diagnosis"))
    payload = {"request_id": "crossport-" + uuid4().hex, "training_steps": args.steps, "max_seconds": 1800}
    job = api("crossport/runs", payload)
    save("created", job)
    duplicate = api("crossport/runs", payload)
    if duplicate["id"] != job["id"]:
        raise ValueError("idempotency failed")
    previous = None
    deadline = time.monotonic() + 1900
    probes = []
    while job["status"] in {"running", "cancelling"} and time.monotonic() < deadline:
        at = time.monotonic()
        job = api("crossport/runs/" + job["id"])
        probes.append({"seconds": time.monotonic() - at, "status": job["status"]})
        key = json.dumps(job.get("progress", {}), sort_keys=True)
        if key != previous:
            print(job["status"], job.get("progress"), flush=True)
            previous = key
        if job["status"] in {"running", "cancelling"}:
            time.sleep(2)
    save("job", job)
    save("job-status-probes", probes)
    if job["status"] != "completed":
        raise ValueError("study failed: " + str(job.get("error")))
    report = api("crossport/runs/" + job["id"] + "/report")
    save("report", report)
    # Independently reconstruct every stored queue transition and causal public clock.
    traces = ROOT / report["trace_file"]
    if hashlib.sha256(traces.read_bytes()).hexdigest() != report["trace_sha256"]:
        raise ValueError("trace ledger checksum failed")
    rollout_count = 0
    frame_count = 0
    max_error = 0.0
    bad_lag = 0
    bad_action = 0
    input_error = 0.0
    cost_error = 0.0
    service_error = 0.0
    reference = {}
    for entry in catalog["entries"]:
        with (ROOT / entry["path"]).open() as handle:
            reference[entry["id"]] = {r["date"]: float(r["portcalls"]) for r in csv.DictReader(handle)}
    factors = (0.65, 0.85, 1.0, 1.15, 1.35)
    from datetime import date, timedelta

    with gzip.open(traces, "rt", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            backlog = 0.0
            cost = 0.0
            origin = date.fromisoformat(item["start"])
            scale = max(
                1.0,
                sum(
                    reference[item["port_id"]][(origin - timedelta(days=offset)).isoformat()] for offset in range(7, 35)
                )
                / 28,
            )
            previous_factor = 1.0
            if len(item["frames"]) != 90:
                raise ValueError("partial rollout counted as complete")
            for step, frame in enumerate(item["frames"]):
                source_actual = reference[item["port_id"]][frame["date"]]
                if item["scenario"] == "demand_surge" and 20 <= step < 50:
                    source_actual *= 1.5
                input_error = max(input_error, abs(source_actual - frame["arrival_indicator"]))
                availability = 0.5 if item["scenario"] == "resource_outage" and 30 <= step < 44 else 1.0
                expected_service = min(backlog + source_actual, scale * factors[frame["action"]] * availability)
                service_error = max(service_error, abs(expected_service - frame["service_proxy"]))
                expected_backlog = backlog + source_actual - expected_service
                ratio = expected_backlog / scale
                expected_cost = (
                    ratio
                    + 0.5 * factors[frame["action"]] ** 2
                    + 0.05 * abs(factors[frame["action"]] - previous_factor)
                    + max(0.0, ratio - 4.0) * 5
                    + (2.0 * ratio if step == 89 else 0.0)
                )
                cost_error = max(cost_error, abs(expected_cost - frame["cost_proxy"]))
                previous_factor = factors[frame["action"]]
                residual = abs(backlog + frame["arrival_indicator"] - frame["service_proxy"] - frame["backlog_proxy"])
                max_error = max(max_error, residual)
                backlog = frame["backlog_proxy"]
                cost += frame["cost_proxy"]
                lag = (date.fromisoformat(frame["date"]) - date.fromisoformat(frame["public_latest_day"])).days
                bad_lag += lag != (14 if item["scenario"] == "publication_delay" else 7)
                bad_action += not (
                    0 <= frame["action"] <= 4 and (frame["declared_availability"] >= 0.75 or frame["action"] <= 2)
                )
                frame_count += 1
            if not math.isfinite(cost):
                raise ValueError("non-finite outcome")
            rollout_count += 1
    checks = {
        "completed": True,
        "current_version": not report["historical_only"],
        "idempotency": True,
        "eight_ports": len(catalog["entries"]) == 8,
        "sixty_four_future_windows": len(report["splits"]["sealed_test_windows"]) == 64,
        "whole_ports_never_fitted": not set(report["protocol"]["train_port_ids"])
        & set(report["protocol"]["whole_port_holdout_ids"]),
        "ten_real_neural_models": len(report["models"]) == 10,
        "all_3584_rollouts": rollout_count == 3584,
        "independent_flow_readback": max_error < 1e-8,
        "publication_lag_respected": bad_lag == 0,
        "valid_capacity_actions": bad_action == 0,
        "actual_primary_inputs_read_back": input_error < 1e-8,
        "independent_service_and_cost": service_error < 1e-8 and cost_error < 1e-8,
        "no_enterprise_release": all(r["enterprise_admission"] is False for r in report["aggregate"]),
    }
    summary = {
        "schema": "xiaoyi-crossport-functional-acceptance.v1",
        "passed": all(checks.values()),
        "checks": checks,
        "job_id": job["id"],
        "rollouts": rollout_count,
        "frames": frame_count,
        "max_independent_flow_error": max_error,
        "max_source_input_error": input_error,
        "max_service_error": service_error,
        "max_cost_error": cost_error,
        "selected_algorithm": report["selected_algorithm"],
        "comparator_algorithm": report["comparator_algorithm"],
        "research_admitted_algorithms": [r["algorithm"] for r in report["aggregate"] if r["research_admission"]],
        "physical_station_gates": [
            {k: r[k] for k in ["site", "calibration_passed", "blockers"]}
            for r in report["multisite_physical_calibration"]["results"]
        ],
        "functional_acceptance_is_not_all_research_or_physical_gates": True,
        "production_authority": False,
    }
    save("summary", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
