"""Measure complete local answers; append evidence without replacing old runs."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--output-tag", required=True)
    parser.add_argument("--include-linkage", action="store_true", help="Read local adapter receipts and recompute the offline energy scenario; never auto-start targets")
    args = parser.parse_args()
    url = args.base_url.rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password:
        parser.error("audit supports only explicit local HTTP services")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.output_tag):
        parser.error("output tag must be 1-80 letters, digits, underscores or hyphens")
    destination = ROOT / "reports" / f"assistant_runtime_audit_{args.output_tag}.json"
    if destination.exists():
        parser.error("report already exists; choose a new output tag")

    def request(path, payload=None):
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        req = Request(url + path, data=body, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=150) as response:
            return json.load(response)

    model = request("/api/models")
    # Do not send the audit questions through a remote model endpoint.
    if model.get("external_request_enabled"):
        parser.error("runtime model is remote; this audit requires a local model or local rules")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Local complete-answer observations, not a throughput SLA, blind quality test or field production acceptance.",
        "model": {key: model.get(key) for key in ["provider", "model", "local_generation_enabled", "answer_strategy"]},
        "cases": [],
    }
    session = f"runtime-audit-{uuid4().hex}"
    cases = [
        ("clarification", "那这个要求呢？", "missing"),
        ("lookup", "新加坡船舶到港报告的官方入口在哪里？", "lookup"),
        ("handover", "港口交班要交什么？", "handover"),
        ("handover_repeat", "港口交班要交什么？", "repeat"),
        ("definition", "TOS 是什么？", "definition"),
        ("scope_cn", "中国船舶到港报告的官方入口在哪里？", "scope"),
        ("scope_sg", "那在新加坡呢？", "scope"),
        ("scope_my", "那在马来西亚呢？", "scope"),
    ]
    for case_id, question, conversation in cases:
        started = time.perf_counter()
        result = request("/api/chat", {"question": question, "session_id": f"{session}-{conversation}"})
        row = {"id": case_id, "question": question, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}
        row.update({key: result.get(key) for key in ["answer", "intent", "timing", "query_analysis", "generation_provider", "generation_fallback", "generation_notice", "grounded", "refusal_reason", "answer_verification", "decision_readiness"]})
        row["evidence_ids"] = [item["id"] for item in result.get("evidence", [])]
        report["cases"].append(row)
        print(f'{case_id}: {row["elapsed_ms"] / 1000:.3f}s, provider={row["generation_provider"]}, fallback={row["generation_fallback"]}', flush=True)
    dense = request("/api/models").get("dense_retrieval", {})
    report["retrieval"] = {key: value for key, value in dense.items() if key != "index_path"}
    if args.include_linkage:
        result = request("/api/system-linkage/command", {"target": "all", "command": "打开强化学习面板，重算能碳策略并读取沙盘能力，核验航行模拟器隔离状态", "auto_start": False})
        report["linkage"] = {key: result[key] for key in ["correlation_id", "succeeded", "total", "all_succeeded", "production_write_enabled", "completed_at"]}
        report["linkage"]["results"] = [{key: value for key, value in row.items() if key != "runtime"} for row in result["results"]]
    report["code_sha256"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ["app/main.py", "app/models.py", "app/query_intelligence.py", "app/xiaoyi.py", "app/model_gateway.py", "app/vector_retrieval.py", "app/retrieval.py", "app/settings.py", "app/system_linkage.py", "web/app.js"]}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(destination.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
