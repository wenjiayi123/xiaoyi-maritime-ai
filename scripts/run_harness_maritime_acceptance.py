"""Actual port task acceptance against the running server; only isolated/read tools."""

import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--driver", choices=["rules", "model"], default="rules")
    parser.add_argument("--output", required=True)
    parser.add_argument("--template", choices=["port-query", "twin-study", "port-briefing"])
    parser.add_argument("--default-budget", action="store_true", help="使用工作台同样的模板默认token预算")
    args = parser.parse_args()

    def api(path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(
            Request(args.base_url.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"}),
            timeout=20,
        ) as response:
            return json.load(response)

    before = api("/api/port-simulator/status")
    capabilities = api("/api/harness/capabilities")
    templates = capabilities["maritime"]["templates"]
    if args.template:
        templates = [t for t in templates if t["id"] == args.template]
    elif args.driver == "model":
        templates = [t for t in templates if t["id"] == "port-query"]
    rows = []
    for template in templates:
        start = time.monotonic()
        payload = {
            "goal": template["goal"],
            "template_id": template["id"],
            "driver": args.driver,
            "request_id": "maritime-" + uuid4().hex,
            "allowed_tools": template["required_tools"],
            "budget": {"max_active_seconds": template["seconds"], "max_tokens": 32000},
        }
        if args.default_budget:
            payload["budget"].pop("max_tokens")
        t = api("/api/harness/tasks", payload)
        while t["status"] in {"queued", "running"} and time.monotonic() - start < template["seconds"] + 20:
            time.sleep(0.3)
            t = api("/api/harness/tasks/" + t["id"])
        receipt = api(f"/api/harness/tasks/{t['id']}/export")
        reports = {
            r["tool"]: json.loads(next(a["content"] for a in receipt["artifacts"] if a["name"] == r["artifact"]))
            for r in t["results"]
            if r["ok"]
        }
        business = [r for name, r in reports.items() if name != "runtime.snapshot"]
        checks = {
            "completed": t["status"] == "completed",
            "driver_disclosed": t["driver"] == args.driver,
            "required_tools": set(template["required_tools"]).issubset(reports),
            "event_chain": receipt["integrity"]["event_chain_valid"],
            "artifact_integrity": receipt["integrity"]["artifact_hashes_valid"],
            "same_snapshot": bool(business) and len({r["snapshot_sha256"] for r in business}) == 1,
            "production_disabled": t["production_authority"] is False
            and all(r["production_authority"] is False for r in business),
            "business_claims_guard": (t.get("final") or {}).get("verification", {}).get("business_claims") is True,
        }
        if "maritime.query" in reports:
            checks["query_units"] = bool(reports["maritime.query"]["rows"]) and all(
                "unit" in r and "source_path" in r for r in reports["maritime.query"]["rows"]
            )
            checks["required_metrics"] = {"grid_demand", "shore_power", "low_soc_agv", "gate_queue"}.issubset(
                {r.get("metric_id") for r in reports["maritime.query"]["rows"]}
            )
        if "twin.compare" in reports:
            checks["required_scenarios"] = {"normal", "energy_peak", "storm"}.issubset(
                {r["scenario"] for r in reports["twin.compare"]["branches"]}
            )
        if "maritime.handover" in reports:
            checks["handover_not_signed"] = (
                reports["maritime.handover"]["handover_state"] == "draft_requires_human_acceptance"
            )
        if template["id"] == "port-briefing":
            synthesis = (t.get("final") or {}).get("synthesis", {})
            checks["report_origin_disclosed"] = (
                synthesis.get("mode") == "verified_business_report" and synthesis.get("model_authored") is False
            )
        rows.append(
            {
                "template": template["id"],
                "passed": all(checks.values()),
                "checks": checks,
                "elapsed_seconds": round(time.monotonic() - start, 3),
                "receipt": receipt,
            }
        )
    after = api("/api/port-simulator/status")
    unchanged = before["scenario_id"] == after["scenario_id"] and before["run_id"] == after["run_id"]
    report = {
        "passed": unchanged and all(r["passed"] for r in rows),
        "driver": args.driver,
        "case_count": len(rows),
        "current_simulator_unchanged": unchanged,
        "output_modes": {
            r["template"]: (r["receipt"]["task"].get("final") or {}).get("synthesis", {}).get("mode") for r in rows
        },
        "rows": rows,
        "scope": "实际本机任务与登记工程模拟；规则/模型及输出来源分别记录；联合交接由已核验工件编译，不作为模型自由摘要能力证据；不是现场KPI、跨引擎盲测或生产验证",
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "driver": args.driver,
                "rows": [{k: v for k, v in r.items() if k != "receipt"} for r in rows],
            },
            ensure_ascii=False,
        )
    )
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
