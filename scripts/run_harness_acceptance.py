"""Read-only acceptance against a running GullMate server; saves actual task receipts."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--driver", choices=["rules", "model"], default="rules")
    parser.add_argument("--output", required=True)
    parser.add_argument("--default-profile", action="store_true", help="验收工作台默认目标、自动模式和默认预算")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    ready_until = time.monotonic() + 10
    while True:
        try:
            with urlopen(base + "/health", timeout=2) as response:
                assert response.status == 200
            break
        except (URLError, TimeoutError):
            if time.monotonic() >= ready_until:
                raise
            time.sleep(0.15)

    def api(path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        with urlopen(
            Request(base + path, data=body, headers={"Content-Type": "application/json"}), timeout=20
        ) as response:
            return json.load(response)

    cases = [
        {
            "id": "arithmetic",
            "goal": "请使用计算工具计算 (120+80)/4，返回结果并引用工具结果。",
            "allowed_tools": ["calculate"],
            "expected_value": 50,
        },
        {
            "id": "maritime-evidence",
            "goal": "检索并解释岸电接入前的核验事项，保留来源；不要调整任何设备。",
            "allowed_tools": ["knowledge.search"],
        },
        {
            "id": "runtime-and-evidence",
            "goal": "读取当前港区运行快照，再检索岸电SOP，说明数据模式和缺失信息，不调整设备。",
            "allowed_tools": ["runtime.snapshot", "knowledge.search"],
        },
    ]
    if args.default_profile:
        cases = [
            {
                "id": "default-profile",
                "goal": "读取舷鸥当前工程模拟港区快照，结合通用岸电SOP说明风险与缺失数据，不调整设备。",
                "allowed_tools": ["runtime.snapshot", "knowledge.search"],
            }
        ]
    rows = []
    for case in cases:
        started = time.monotonic()
        payload = {
            "goal": case["goal"],
            "driver": args.driver,
            "allowed_tools": case["allowed_tools"],
            "required_tools": case["allowed_tools"],
            "request_id": "accept-" + uuid4().hex,
            "budget": {"max_active_seconds": 240, "max_steps": 10, "max_tokens": 32000},
        }
        if args.default_profile:
            payload = {"goal": case["goal"], "driver": "auto", "request_id": "default-" + uuid4().hex}
        task = api("/api/harness/tasks", payload)
        while task["status"] in {"queued", "running"} and time.monotonic() - started < 300:
            time.sleep(0.5)
            task = api("/api/harness/tasks/" + task["id"])
        receipt = api("/api/harness/tasks/" + task["id"] + "/export")
        checks = {
            "completed": task["status"] == "completed",
            "event_chain": receipt["integrity"]["event_chain_valid"],
            "artifacts": receipt["integrity"]["artifact_hashes_valid"],
            "correct_driver": task["driver"] == args.driver,
            "no_production_authority": task["production_authority"] is False,
            "tools_used": set(case["allowed_tools"]).issubset({r["tool"] for r in task["results"] if r["ok"]}),
        }
        if "expected_value" in case:
            outputs = [json.loads(a["content"]) for a in receipt["artifacts"] if a["name"].startswith("T")]
            checks["actual_value"] = any(o.get("value") == case["expected_value"] for o in outputs)
        rows.append(
            {
                "case": case["id"],
                "checks": checks,
                "passed": all(checks.values()),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "receipt": receipt,
            }
        )
        print(
            json.dumps({"case": case["id"], "status": task["status"], "checks": checks}, ensure_ascii=False), flush=True
        )
    report = {
        "driver": args.driver,
        "case_count": len(rows),
        "passed": all(r["passed"] for r in rows),
        "scope": "本机实际任务与工具；运行快照为工程模拟；不代表跨引擎排名、生产调度或第三方盲测",
        "rows": rows,
    }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
