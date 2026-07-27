from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.answer_verification import verify_response
from app.config import BASE_DIR
from app.question_universe import question_domains
from app.xiaoyi import XiaoyiAI


BENCHMARK_PATH = (
    BASE_DIR / "data" / "evaluation" / "maritime_question_universe_benchmark_v6.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contains_all(text: str, terms: list[str]) -> bool:
    folded = text.casefold()
    return all(term.casefold() in folded for term in terms)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    passed = sum(row["passed"] for row in rows)
    return {
        "case_count": count,
        "passed_count": passed,
        "pass_rate": round(passed / max(1, count), 4),
        "failed_ids": [row["id"] for row in rows if not row["passed"]],
    }


def run_question_universe_benchmark(
    path: Path = BENCHMARK_PATH,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    engine = XiaoyiAI()
    rows: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in payload["cases"]:
        result = engine.ask(case["question"], mode="ops", top_k=8)
        verification = verify_response(result)
        sources = {item.source for item in result.evidence}
        detected_domains = question_domains(case["question"])
        checks = {
            "grounded": result.grounded,
            "source": case["expected_source"] in sources,
            "domain": case["domain"] in detected_domains,
            "required_terms": _contains_all(
                result.answer,
                case.get("required_answer_terms", []),
            ),
            "citation_gate": verification.status == "passed",
        }
        row = {
            "id": case["id"],
            "domain": case["domain"],
            "detected_domains": detected_domains,
            "grounded": result.grounded,
            "refusal_reason": result.refusal_reason,
            "citation_status": verification.status,
            "sources": sorted(sources),
            "checks": checks,
            "passed": all(checks.values()),
        }
        rows.append(row)
        grouped[case["domain"]].append(row)

    boundary_rows: list[dict[str, Any]] = []
    for case in payload["boundary_cases"]:
        result = engine.ask(case["question"], mode="expert", top_k=8)
        verification = verify_response(result)
        checks = {
            "not_grounded": not result.grounded,
            "refusal": result.refusal_reason == case["expected_refusal_reason"],
            "required_terms": _contains_all(
                result.answer,
                case.get("required_answer_terms", []),
            ),
            "citation_gate": verification.status == "not_applicable",
        }
        row = {
            "id": case["id"],
            "grounded": result.grounded,
            "refusal_reason": result.refusal_reason,
            "citation_status": verification.status,
            "checks": checks,
            "passed": all(checks.values()),
        }
        boundary_rows.append(row)

    operational = _summary(rows)
    boundary = _summary(boundary_rows)
    overall = _summary([*rows, *boundary_rows])
    return {
        "benchmark_id": payload["benchmark_id"],
        "benchmark_sha256": _sha256(path),
        "operational_case_count": len(rows),
        "boundary_case_count": len(boundary_rows),
        "combined_fixed_case_count": int(payload["base_case_count"]) + len(rows),
        "domains": {
            domain: _summary(grouped[domain]) for domain in sorted(grouped)
        },
        "operational": {"summary": operational, "rows": rows},
        "boundary": {"summary": boundary, "rows": boundary_rows},
        "overall": overall,
        "passed": overall["pass_rate"] == 1.0,
        "scope": payload["scope"],
    }
