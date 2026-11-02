"""Finite live API regression. Rules test execution; they do not rate an LLM."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    def api(path, body=None):
        request = Request(args.base_url + "/api/harness" + path,
                          data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    cases = []
    for index in range(10):
        cases.append({"name": f"arithmetic-{index}", "goal": f"计算 ({120 + index}+80)/4，引用工具结果。",
                      "allowed_tools": ["calculate"], "required_tools": ["calculate"], "value": (200 + index) / 4})
    for topic in ["岸电接入", "AGV低SOC", "引航窗口", "恶劣天气停工", "岸桥能耗"]:
        cases.append({"name": "knowledge-" + topic, "goal": "检索" + topic + "的SOP，保留来源。",
                      "allowed_tools": ["knowledge.search"], "required_tools": ["knowledge.search"]})
        cases.append({"name": "runtime-" + topic, "goal": "读取当前港区快照并检索" + topic + "的SOP。",
                      "allowed_tools": ["runtime.snapshot", "knowledge.search"],
                      "required_tools": ["runtime.snapshot", "knowledge.search"]})
    for template, count in [("port-query", 3), ("twin-study", 3), ("port-briefing", 4)]:
        cases.extend({"name": f"{template}-{index}", "goal": "完成港区工程模拟评估，区分数据来源与生产权限。",
                      "template_id": template} for index in range(count))
    rows = []
    for case in cases:
        started = time.monotonic()
        code, task = api("/tasks", {k: v for k, v in case.items() if k not in {"name", "value"}} |
                         {"driver": "rules", "request_id": "finite-" + uuid4().hex})
        if code not in {201, 202}:
            raise RuntimeError(f"{case['name']} creation: {code} {task}")
        while task["status"] in {"queued", "running"} and time.monotonic() - started < 180:
            time.sleep(.15)
            _, task = api("/tasks/" + task["id"])
        _, receipt = api("/tasks/" + task["id"] + "/export")
        checks = {"completed": task["status"] == "completed", "rules_disclosed": task["driver"] == "rules",
                  "event_chain": receipt["integrity"]["event_chain_valid"],
                  "artifacts": receipt["integrity"]["artifact_hashes_valid"],
                  "simulation_only": task["production_authority"] is False}
        if "value" in case:
            checks["arithmetic"] = any(json.loads(a["content"]).get("value") == case["value"]
                                       for a in receipt["artifacts"] if a["name"].startswith("T"))
        rows.append({"case": case["name"], "passed": all(checks.values()), "checks": checks,
                     "seconds": round(time.monotonic() - started, 3), "receipt": receipt})

    _, planned = api("/joint/missions", {"request_id": "negative-plan-" + uuid4().hex})
    task_base = {"goal": "检索岸电SOP", "driver": "rules"}
    negative = [
        ("unknown-mode", "/tasks", {**task_base, "mode": "omniscient"}),
        ("unknown-tool", "/tasks", {**task_base, "allowed_tools": ["shell.execute"]}),
        ("empty-tools", "/tasks", {**task_base, "allowed_tools": []}),
        ("required-outside-scope", "/tasks", {**task_base, "allowed_tools": ["calculate"], "required_tools": ["knowledge.search"]}),
        ("unknown-model", "/tasks", {**task_base, "model_profile": "arbitrary_remote"}),
        ("readonly-write-conflict", "/joint/missions", {"goal": "只读联合评估，不修改", "mutate_sandbox": True}),
        ("production-control", "/joint/missions", {"goal": "联合控制真实设备并执行"}),
        ("unsupported-goal", "/joint/missions", {"goal": "帮我购买股票"}),
        ("research-without-evidence", "/joint/missions", {"mode": "research", "experiment_id": "hr-" + "0" * 32}),
        ("changed-approval", "/joint/missions/" + planned["id"] + "/approval", {"plan_sha256": "0" * 64}),
    ]
    errors = []
    for name, path, body in negative:
        if path in {"/tasks", "/joint/missions"}:
            body["request_id"] = "negative-" + uuid4().hex
        code, result = api(path, body)
        errors.append({"case": name, "http_status": code, "passed": code in {400, 403, 409, 422}, "result": result})
    api("/joint/missions/" + planned["id"] + "/approval", {"plan_sha256": planned["plan_sha256"], "approve": False})
    report = {"scope": "30条有限执行引擎任务及10条API拒绝路径；规则驱动，不是大模型开放任务可靠率。",
              "normal_count": len(rows), "normal_passed": sum(r["passed"] for r in rows),
              "negative_count": len(errors), "negative_passed": sum(r["passed"] for r in errors),
              "passed": all(r["passed"] for r in rows + errors), "normal": rows, "negative": errors}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in {"normal", "negative"}}, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
