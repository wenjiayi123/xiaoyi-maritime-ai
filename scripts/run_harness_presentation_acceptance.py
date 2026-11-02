"""Fresh, predeclared local-model presentation checks; never fall back to rules.

This is a small integration sample, not an independent agent benchmark.
Writes the case manifest before creating any tasks, and preserves every receipt.
"""

import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4


CASES = [
    {
        "id": "fresh-arithmetic",
        "goal": "使用计算工具核算：(315+285)/6。说明结果及引用，不估算，不调用其他工具。",
        "allowed_tools": ["calculate"],
        "required_tools": ["calculate"],
        "expected_value": 100,
        "budget": {"max_active_seconds": 240, "max_steps": 10, "max_tokens": 16000},
    },
    {
        "id": "fresh-handover",
        "goal": "为本次演示新采集港区快照：查询电网需量、岸电负荷、低电量AGV和闸口队列；核验风险，比较常态、需量高峰和大风情景，交付保留单位、依据及未签收状态的交接简报。不要改变当前设备或场景。",
        "template_id": "port-briefing",
        "allowed_tools": ["runtime.snapshot", "maritime.query", "maritime.risk", "twin.compare", "maritime.handover"],
        "required_tools": ["runtime.snapshot", "maritime.query", "maritime.risk", "twin.compare", "maritime.handover"],
        "budget": {"max_active_seconds": 600, "max_steps": 12, "max_tokens": 32000},
    },
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18018")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    target = Path(args.output)
    manifest = target.with_suffix(".cases.json")
    if target.exists() or manifest.exists():
        parser.error("Choose a new output path; prior evidence must not be overwritten.")
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(CASES, ensure_ascii=False, indent=2))

    def api(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(args.base_url.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=20) as response:
            return json.load(response)

    report = {"scope": "Fresh prompts and newly acquired local simulation snapshots; not new external field data, statistical accuracy or production acceptance.", "rows": []}
    before = api("/api/port-simulator/status")
    for case in CASES:
        payload = {k: v for k, v in case.items() if k not in {"id", "expected_value"}}
        payload.update(driver="model", request_id="present-" + uuid4().hex)
        started = time.monotonic()
        task = api("/api/harness/tasks", payload)
        print(json.dumps({"case": case["id"], "task_id": task["id"], "status": task["status"]}), flush=True)
        while task["status"] in {"queued", "running"} and time.monotonic() - started < case["budget"]["max_active_seconds"] + 140:
            time.sleep(1)
            task = api("/api/harness/tasks/" + task["id"])
        receipt = api("/api/harness/tasks/" + task["id"] + "/export")
        outputs = {
            r["tool"]: json.loads(next(a["content"] for a in receipt["artifacts"] if a["name"] == r["artifact"]))
            for r in task["results"] if r["ok"]
        }
        checks = {
            "completed": task["status"] == "completed",
            "real_model": task["driver"] == "model",
            "event_chain": receipt["integrity"]["event_chain_valid"],
            "artifact_hashes": receipt["integrity"]["artifact_hashes_valid"],
            "required_tools": set(case["required_tools"]).issubset(outputs),
            "production_disabled": task["production_authority"] is False,
        }
        if "expected_value" in case:
            checks["exact_value"] = outputs.get("calculate", {}).get("value") == case["expected_value"]
            checks["value_in_final"] = str(case["expected_value"]) in (task.get("final") or {}).get("text", "")
        if case.get("template_id") == "port-briefing":
            business = [o for name, o in outputs.items() if name != "runtime.snapshot"]
            synthesis = (task.get("final") or {}).get("synthesis", {})
            query = outputs.get("maritime.query", {})
            checks.update(
                same_snapshot=len(business) == 4 and len({o["snapshot_sha256"] for o in business}) == 1,
                required_metrics={"grid_demand", "shore_power", "low_soc_agv", "gate_queue"}.issubset({r.get("metric_id") for r in query.get("rows", [])}),
                units_and_sources=bool(query.get("rows")) and all("unit" in r and "source_path" in r for r in query["rows"]),
                scenarios={"normal", "energy_peak", "storm"}.issubset({b["scenario"] for b in outputs.get("twin.compare", {}).get("branches", [])}),
                unsigned=outputs.get("maritime.handover", {}).get("handover_state") == "draft_requires_human_acceptance",
                output_origin=synthesis.get("mode") == "verified_business_report" and synthesis.get("model_authored") is False,
                business_claims=(task.get("final") or {}).get("verification", {}).get("business_claims") is True,
            )
        after = api("/api/port-simulator/status")
        checks["scenario_unchanged"] = before["scenario_id"] == after["scenario_id"] and before["run_id"] == after["run_id"]
        row = {"case": case["id"], "checks": checks, "passed": all(checks.values()), "elapsed_seconds": round(time.monotonic() - started, 3), "receipt": receipt}
        report["rows"].append(row)
        report["passed"] = all(r["passed"] for r in report["rows"])
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({k: v for k, v in row.items() if k != "receipt"}, ensure_ascii=False), flush=True)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
