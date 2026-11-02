"""Exercise the actual HTTP/task interfaces and persist all accepted evidence."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", action="store_true")
    parser.add_argument("--research", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)

    def api(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(
            Request(args.base_url + "/api/harness" + path, data=data, headers={"Content-Type": "application/json"}),
            timeout=60,
        ) as response:
            return json.load(response)

    def save(name, value):
        (out / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    caps = api("/capabilities")
    save("capabilities", caps)
    save("public-catalog", api("/assurance/public-data"))
    save("forecast-validation", api("/assurance/forecast-validation", {}))
    for site in ["los_angeles", "singapore"]:
        for scenario in ["historical_baseline", "peak_month_demand", "resource_outage"]:
            save(site + "-" + scenario, api("/assurance/historical-study", {"site": site, "scenario": scenario}))
    evaluation = api("/evaluation", {})
    save("evaluation", evaluation)
    checks = {"rule_and_business_evaluation": evaluation["passed"]}
    task_ids = {}
    for driver in ["rules", *(["model"] if args.model else [])]:
        template = next(t for t in caps["maritime"]["templates"] if t["id"] == "port-future-study")
        task = api(
            "/tasks",
            {
                "request_id": "future-" + uuid4().hex,
                "driver": driver,
                "goal": template["goal"],
                "template_id": template["id"],
                "allowed_tools": template["required_tools"],
                "budget": {"max_steps": 12, "max_active_seconds": 600, "max_tokens": 32000},
            },
        )
        deadline = time.monotonic() + 650
        while task["status"] in {"running", "queued"} and time.monotonic() < deadline:
            time.sleep(0.5)
            task = api("/tasks/" + task["id"])
        receipt = api("/tasks/" + task["id"] + "/export")
        save(driver + "-task", receipt)
        task_ids[driver] = task["id"]
        checks[driver + "_task"] = (
            task["status"] == "completed"
            and task["driver"] == driver
            and receipt["integrity"]["event_chain_valid"]
            and receipt["integrity"]["artifact_hashes_valid"]
        )
        print(driver, task["id"], task["status"], flush=True)
    if args.research:
        job = api(
            "/research/runs",
            {
                "request_id": "future-research-" + uuid4().hex,
                "dataset_id": "noaa_la_lb_ais_weather_2024_12_25",
                "seeds": [30101, 30102, 30103, 30104, 30105],
                "episodes": 160,
                "horizon_steps": 24,
                "max_seconds": 300,
            },
        )
        deadline = time.monotonic() + 330
        while job["status"] in {"running", "cancelling"} and time.monotonic() < deadline:
            time.sleep(0.5)
            job = api("/research/runs/" + job["id"])
        save("research-job", job)
        checks["research_completed"] = job["status"] == "completed"
        if job["status"] == "completed":
            report = api("/research/runs/" + job["id"] + "/report")
            save("research-report", report)
            checks["research_version_current"] = report["historical_only"] is False
            checks["all_20_nominal_runs"] = len(report["runs"]) == 20
            checks["all_60_stress_runs"] = len(report["stress_runs"]) == 60
            checks["enterprise_release_disabled"] = all(r["enterprise_admission"] is False for r in report["aggregate"])
        task_ids["research"] = job["id"]
        print("research", job["id"], job["status"], flush=True)
    summary = {
        "passed": all(checks.values()),
        "checks": checks,
        "task_ids": task_ids,
        "scope": "Actual local HTTP and task execution; model/rules distinguished. Negative policy admission is an evaluation outcome, not an acceptance-script failure.",
    }
    save("summary", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
