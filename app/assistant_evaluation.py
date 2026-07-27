from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.answer_verification import verify_response
from app.config import BASE_DIR
from app.knowledge_policy import detect_jurisdictions
from app.query_intelligence import build_query_analysis
from app.xiaoyi import XiaoyiAI


BENCHMARK_PATH = (
    BASE_DIR / "data" / "evaluation" / "maritime_assistant_benchmark_v2.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contains_all(text: str, terms: list[str]) -> bool:
    folded = text.casefold()
    return all(term.casefold() in folded for term in terms)


def _contains_none(text: str, terms: list[str]) -> bool:
    folded = text.casefold()
    return all(term.casefold() not in folded for term in terms)


def _sources(result: Any) -> set[str]:
    return {item.source for item in result.evidence}


def _history(case: dict[str, Any]) -> list[dict[str, Any]]:
    prior = case.get("prior_question")
    if not prior:
        return []
    return [
        {
            "id": f"history-{case['id']}",
            "question": prior,
            "response": {},
        }
    ]


def _evaluate_dialogue(
    cases: list[dict[str, Any]],
    engine: XiaoyiAI,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        plan = build_query_analysis(case["followup"], history=_history(case))
        detected = list(detect_jurisdictions(plan.standalone_question))
        checks = {
            "resolution": plan.resolution == case["expected_resolution"],
            "required_terms": _contains_all(
                plan.standalone_question,
                case.get("required_terms", []),
            ),
            "forbidden_terms": _contains_none(
                plan.standalone_question,
                case.get("forbidden_terms", []),
            ),
            "jurisdiction": detected == case.get("expected_jurisdictions", []),
        }
        result = None
        if any(
            key in case
            for key in (
                "expected_source_any",
                "expected_refusal_reason",
            )
        ):
            result = engine.ask(
                plan.standalone_question,
                top_k=8,
                retrieval_queries=plan.subquestions,
            )
            if "expected_source_any" in case:
                checks["source"] = bool(
                    _sources(result).intersection(case["expected_source_any"])
                )
            if "expected_refusal_reason" in case:
                checks["refusal"] = (
                    result.refusal_reason == case["expected_refusal_reason"]
                )
        rows.append(
            {
                "id": case["id"],
                "standalone_question": plan.standalone_question,
                "detected_jurisdictions": detected,
                "refusal_reason": result.refusal_reason if result else None,
                "sources": sorted(_sources(result)) if result else [],
                "checks": checks,
                "passed": all(checks.values()),
            }
        )
    return rows


def _evaluate_complex(
    cases: list[dict[str, Any]],
    engine: XiaoyiAI,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        plan = build_query_analysis(case["question"])
        result = engine.ask_compound(
            plan.standalone_question,
            plan.subquestions,
            top_k=8,
        )
        verification = verify_response(result)
        sources = _sources(result)
        checks = {
            "decomposition": len(plan.subquestions)
            >= int(case["minimum_subquestions"]),
            "dimensions": set(case.get("expected_dimensions", [])).issubset(
                plan.dimensions
            ),
            "completion": result.completion_status
            == case["expected_completion_status"],
            "evidence_coverage": result.evidence_coverage
            >= float(case["minimum_evidence_coverage"]),
            "citation_gate": (
                verification.status == "passed"
                if result.grounded
                else verification.status == "not_applicable"
            ),
        }
        if "expected_source_any" in case:
            checks["source_any"] = bool(
                sources.intersection(case["expected_source_any"])
            )
        if "expected_source_all" in case:
            checks["source_all"] = set(case["expected_source_all"]).issubset(
                sources
            )
        if "expected_refusal_reason" in case:
            checks["refusal"] = (
                result.refusal_reason == case["expected_refusal_reason"]
            )
        rows.append(
            {
                "id": case["id"],
                "subquestions": plan.subquestions,
                "dimensions": plan.dimensions,
                "completion_status": result.completion_status,
                "evidence_coverage": result.evidence_coverage,
                "refusal_reason": result.refusal_reason,
                "citation_status": verification.status,
                "sources": sorted(sources),
                "checks": checks,
                "passed": all(checks.values()),
            }
        )
    return rows


def _evaluate_adversarial(
    cases: list[dict[str, Any]],
    engine: XiaoyiAI,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        result = engine.ask(case["question"], top_k=8)
        verification = verify_response(result)
        sources = _sources(result)
        checks = {
            "grounded": result.grounded is bool(case["expected_grounded"]),
        }
        if "expected_refusal_reason" in case:
            checks["refusal"] = (
                result.refusal_reason == case["expected_refusal_reason"]
            )
        if "expected_citation_role" in case:
            checks["citation_role"] = bool(result.evidence) and all(
                item.citation_role == case["expected_citation_role"]
                for item in result.evidence
            )
        if "expected_requires_human_review" in case:
            checks["human_review"] = (
                result.requires_human_review
                is bool(case["expected_requires_human_review"])
            )
        if "expected_source_any" in case:
            checks["source"] = bool(
                sources.intersection(case["expected_source_any"])
            )
        if "required_answer_terms" in case:
            checks["required_terms"] = _contains_all(
                result.answer,
                case["required_answer_terms"],
            )
        if "forbidden_answer_terms" in case:
            checks["forbidden_terms"] = _contains_none(
                result.answer,
                case["forbidden_answer_terms"],
            )
        if result.grounded:
            checks["citation_gate"] = verification.status == "passed"
        rows.append(
            {
                "id": case["id"],
                "grounded": result.grounded,
                "refusal_reason": result.refusal_reason,
                "requires_human_review": result.requires_human_review,
                "citation_status": verification.status,
                "sources": sorted(sources),
                "checks": checks,
                "passed": all(checks.values()),
            }
        )
    return rows


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    passed = sum(row["passed"] for row in rows)
    return {
        "case_count": count,
        "passed_count": passed,
        "pass_rate": round(passed / max(1, count), 4),
        "failed_ids": [row["id"] for row in rows if not row["passed"]],
    }


def run_assistant_benchmark(
    path: Path = BENCHMARK_PATH,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    engine = XiaoyiAI()
    dialogue = _evaluate_dialogue(payload["dialogue_cases"], engine)
    complex_rows = _evaluate_complex(payload["complex_cases"], engine)
    adversarial = _evaluate_adversarial(payload["adversarial_cases"], engine)
    all_rows = [*dialogue, *complex_rows, *adversarial]
    dialogue_summary = _summary(dialogue)
    complex_summary = _summary(complex_rows)
    adversarial_summary = _summary(adversarial)
    overall = _summary(all_rows)
    base_case_count = int(payload["base_benchmark"]["case_count"])
    return {
        "benchmark_id": payload["benchmark_id"],
        "benchmark_sha256": _sha256(path),
        "case_count": len(all_rows),
        "combined_with_v1_case_count": base_case_count + len(all_rows),
        "dialogue": {"summary": dialogue_summary, "rows": dialogue},
        "complex": {"summary": complex_summary, "rows": complex_rows},
        "adversarial": {"summary": adversarial_summary, "rows": adversarial},
        "overall": overall,
        "passed": overall["pass_rate"] == 1.0,
        "scope": (
            "仓库维护的确定性困难集，验证跨轮改写、复杂问题分治、证据引用和安全拒答；"
            "不是第三方盲测、用户研究、线上SLA或法律正确率。"
        ),
    }
