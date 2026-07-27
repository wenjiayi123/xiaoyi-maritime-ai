from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.answer_verification import verify_answer
from app.config import BASE_DIR
from app.models import Evidence


BENCHMARK_PATH = (
    BASE_DIR
    / "data"
    / "evaluation"
    / "maritime_claim_alignment_benchmark_v4.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(rows: list[dict[str, Any]]) -> list[Evidence]:
    return [
        Evidence(
            id=row["id"],
            source=row.get("source", "benchmark-fixture.md"),
            title=row["title"],
            score=100.0,
            snippet=row["snippet"],
            citation_role=row.get("citation_role", "supporting"),
            official=bool(row.get("official", False)),
            verification_status="verified",
            source_quality="official_verified"
            if row.get("official")
            else "internal_curated",
        )
        for row in rows
    ]


def _evaluate(case: dict[str, Any]) -> dict[str, Any]:
    verification = verify_answer(
        case["answer"],
        _evidence(case["evidence"]),
        grounded=bool(case.get("grounded", True)),
    )
    checks = {
        "status": verification.status == case["expected_status"],
        "supported_claims": verification.supported_claim_count
        == int(case["expected_supported_claims"]),
    }
    if "expected_citation_validity" in case:
        checks["citation_validity"] = (
            verification.citation_validity
            == float(case["expected_citation_validity"])
        )
    if "expected_alignment_min" in case:
        checks["alignment_min"] = (
            verification.evidence_alignment
            >= float(case["expected_alignment_min"])
        )
    if "expected_alignment_max" in case:
        checks["alignment_max"] = (
            verification.evidence_alignment
            <= float(case["expected_alignment_max"])
        )
    if "expected_numeric_integrity" in case:
        checks["numeric_integrity"] = (
            verification.numeric_integrity
            == float(case["expected_numeric_integrity"])
        )
    if "expected_unsupported_numeric" in case:
        unsupported = [
            token
            for claim in verification.claims
            for token in claim.unsupported_numeric_tokens
        ]
        checks["unsupported_numeric"] = (
            unsupported == case["expected_unsupported_numeric"]
        )
    if "expected_issue" in case:
        checks["issue"] = any(
            case["expected_issue"] in issue for issue in verification.issues
        )
    return {
        "id": case["id"],
        "category": case["category"],
        "status": verification.status,
        "supported_claims": verification.supported_claim_count,
        "citation_validity": verification.citation_validity,
        "evidence_alignment": verification.evidence_alignment,
        "numeric_integrity": verification.numeric_integrity,
        "unsupported_numeric_tokens": [
            token
            for claim in verification.claims
            for token in claim.unsupported_numeric_tokens
        ],
        "issues": verification.issues,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    passed = sum(row["passed"] for row in rows)
    return {
        "case_count": count,
        "passed_count": passed,
        "pass_rate": round(passed / max(1, count), 4),
        "failed_ids": [row["id"] for row in rows if not row["passed"]],
    }


def run_alignment_benchmark(
    path: Path = BENCHMARK_PATH,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = [_evaluate(case) for case in payload["cases"]]
    categories = {
        category: {
            "summary": _summary(
                [row for row in rows if row["category"] == category]
            ),
            "rows": [row for row in rows if row["category"] == category],
        }
        for category in ("citation", "alignment", "numeric")
    }
    overall = _summary(rows)
    base = payload["base_benchmarks"]
    return {
        "benchmark_id": payload["benchmark_id"],
        "benchmark_sha256": _sha256(path),
        "case_count": len(rows),
        "combined_case_count": sum(int(value) for value in base.values())
        + len(rows),
        "categories": categories,
        "overall": overall,
        "passed": overall["pass_rate"] == 1.0,
        "scope": payload["scope"],
    }
