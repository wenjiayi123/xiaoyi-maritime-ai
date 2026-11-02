"""Small independent outcome graders; reports rules/model evidence separately."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from app.access_control import IdentityContext
from app.harness.contracts import CreateTask, digest, now
from app.harness.runner import Harness
from app.harness.store import HarnessStore

CASES = [
    {"id": "calc-01", "goal": "计算 6*7", "tool": "calculate", "value": 42},
    {"id": "calc-02", "goal": "计算 (120+80)/4", "tool": "calculate", "value": 50},
    {"id": "calc-03", "goal": "计算 0*5", "tool": "calculate", "value": 0},
    {"id": "knowledge-01", "goal": "解释岸电接入前应核验哪些事项", "tool": "knowledge.search"},
]


def run_evaluation() -> dict:
    from app.harness.business_evaluation import run as business_evaluation
    rows = []
    with tempfile.TemporaryDirectory(prefix="xiaoyi-harness-eval-") as folder:
        runtime = Harness(HarnessStore(Path(folder) / "evaluation.db"))
        try:
            for case in CASES:
                started = time.monotonic()
                task = runtime.create(
                    CreateTask(
                        goal=case["goal"],
                        request_id="eval-" + uuid4().hex,
                        driver="rules",
                        allowed_tools=[case["tool"]],
                    ),
                    IdentityContext("isolated-evaluation", "operator", True, "evaluation"),
                )
                while time.monotonic() - started < 15:
                    task = runtime.store.get(task["id"])
                    if task["status"] not in {"queued", "running"} and task["id"] not in runtime.active:
                        break
                    time.sleep(0.02)
                checks = {
                    "completed": task["status"] == "completed",
                    "driver_disclosed": task["driver"] == "rules",
                    "registered_tool": len(task["results"]) == 1 and task["results"][0]["tool"] == case["tool"],
                    "production_disabled": task["production_authority"] is False,
                    "valid_reference": bool((task.get("final") or {}).get("verification", {}).get("references_valid")),
                }
                if checks["registered_tool"]:
                    result = json.loads(runtime.store.artifact(task["id"], "T1.json")["content"])
                    if "value" in case:
                        checks["outcome_value"] = result.get("value") == case["value"]
                    else:
                        checks["source_fields"] = bool(result.get("evidence")) and bool(result.get("source_quality"))
                rows.append(
                    {
                        "id": case["id"],
                        "passed": all(checks.values()),
                        "checks": checks,
                        "status": task["status"],
                        "usage": task["usage"],
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                    }
                )
        finally:
            runtime.close()
    business = business_evaluation()
    return {
        "schema": "xiaoyi-harness.evaluation.v1",
        "at": now(),
        "case_set_sha256": digest(CASES),
        "driver": "rules",
        "case_count": len(rows),
        "passed": all(row["passed"] for row in rows) and business["passed"],
        "pass_rate": sum(row["passed"] for row in rows) / len(rows),
        "rows": rows,
        "business_assurance": business,
        "scope": "规则任务机制与公开港口业务门禁分别计数；不是模型自主规划、多引擎性能排名、第三方盲测或生产SLA",
    }
