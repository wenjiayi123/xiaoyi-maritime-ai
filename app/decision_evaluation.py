from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.answer_verification import verify_response
from app.config import BASE_DIR
from app.decision_assurance import assess_response
from app.models import ChatResponse, Evidence
from app.query_intelligence import build_query_analysis
from app.xiaoyi import XiaoyiAI


BENCHMARK_PATH = (
    BASE_DIR
    / "data"
    / "evaluation"
    / "maritime_decision_readiness_benchmark_v3.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(
    identifier: str,
    snippet: str,
    *,
    title: str = "某海事规则生效状态",
    source: str = "official-rule.md",
    jurisdiction: str = "CN",
    version: str = "v1",
    checksum: str = "a" * 64,
    official: bool = True,
    review_status: str = "current",
) -> Evidence:
    return Evidence(
        id=identifier,
        source=source,
        title=title,
        score=100.0,
        snippet=snippet,
        official=official,
        verification_status="verified" if official else "internal_curated",
        source_quality="official_verified" if official else "internal_curated",
        jurisdictions=[jurisdiction],
        content_scope="official_summary" if official else "internal_curated",
        legal_force="law" if official else "guidance",
        version=version,
        checksum_sha256=checksum,
        chunk_checksum_sha256=(identifier[-1] * 64),
        review_status=review_status,
    )


def _response(
    evidence: list[Evidence],
    *,
    grounded: bool = True,
    source_quality: str = "official_verified",
    requires_human_review: bool = True,
    refusal_reason: str | None = None,
    completion_status: str = "complete",
) -> ChatResponse:
    return ChatResponse(
        app="小懿",
        mode="expert",
        intent="policy",
        question="该结论是否可采用？",
        answer="当前结论见已登记证据。[E1]" if grounded else "当前证据不足，已停止形成结论。",
        evidence=evidence,
        confidence="high" if grounded else "low",
        next_questions=[],
        grounded=grounded,
        source_quality=source_quality,
        requires_human_review=requires_human_review,
        refusal_reason=refusal_reason,
        completion_status=completion_status,
    )


def _scenario(name: str) -> ChatResponse:
    positive = _evidence("rule:1", "主管机关说明：该规则已经生效。")
    negative = _evidence("rule:2", "主管机关说明：该规则尚未生效。")
    if name == "polarity_conflict":
        return _response([positive, negative])
    if name == "version_divergence":
        return _response(
            [
                _evidence("rule:1", "规则适用于港航业务。", version="v1"),
                _evidence(
                    "rule:2",
                    "规则适用于港航业务。",
                    version="v2",
                    checksum="b" * 64,
                ),
            ]
        )
    if name == "cross_jurisdiction_opposite":
        return _response(
            [
                positive,
                _evidence(
                    "rule:2",
                    "主管机关说明：该规则尚未生效。",
                    jurisdiction="SG",
                ),
            ]
        )
    if name == "different_topic_opposite":
        return _response(
            [
                positive,
                _evidence(
                    "rule:2",
                    "主管机关说明：该规则尚未生效。",
                    title="另一危险品申报制度",
                ),
            ]
        )
    if name == "citation_failure":
        response = _response([positive])
        return response.model_copy(
            update={
                "answer": "该规则已经生效，但回答没有提供证据编号。",
                "answer_verification": verify_response(
                    response.model_copy(
                        update={
                            "answer": "该规则已经生效，但回答没有提供证据编号。"
                        }
                    )
                ),
            }
        )
    if name in {"review_due", "review_invalid"}:
        review_status = "review_due" if name == "review_due" else "review_date_invalid"
        return _response(
            [
                _evidence(
                    "rule:1",
                    "主管机关说明：该规则已经生效。",
                    review_status=review_status,
                )
            ],
            requires_human_review=False,
        )
    if name == "official_freshness_missing":
        return _response(
            [
                _evidence(
                    "rule:1",
                    "主管机关说明：该规则已经生效。",
                    review_status="review_date_missing",
                )
            ],
            requires_human_review=False,
        )
    if name == "official_current":
        return _response([positive])
    if name == "internal_current":
        return _response(
            [
                _evidence(
                    "guide:1",
                    "泊位计划用于协调船舶靠离泊。",
                    title="泊位计划",
                    source="internal-guide.md",
                    official=False,
                )
            ],
            source_quality="internal_curated",
            requires_human_review=False,
        )
    if name == "insufficient_evidence":
        return _response(
            [],
            grounded=False,
            source_quality="unverified",
            requires_human_review=False,
            refusal_reason="insufficient_index_evidence",
            completion_status="refused",
        )
    if name == "partial_answer":
        return _response(
            [positive],
            completion_status="partial",
            requires_human_review=False,
        )
    if name == "sandbox":
        return _response(
            [
                _evidence(
                    "sandbox:1",
                    "动态沙箱事件，不是生产实绩。",
                    title="运营沙箱",
                    source="XIAOYI-PORT-SANDBOX",
                    official=False,
                    review_status="unknown",
                )
            ],
            source_quality="public_data_calibrated_simulation",
            requires_human_review=False,
            refusal_reason="sandbox_not_production",
        )
    refusal_map = {
        "live_refusal": "live_data_connection_required",
        "full_text_refusal": "official_full_text_required",
        "business_object_refusal": "business_object_required",
    }
    if name in refusal_map:
        return _response(
            [],
            grounded=False,
            source_quality="unverified",
            requires_human_review=False,
            refusal_reason=refusal_map[name],
            completion_status="refused",
        )
    raise ValueError(f"unknown decision benchmark scenario: {name}")


def _checks(
    case: dict[str, Any],
    *,
    status: str,
    risk: str,
    blockers: list[str],
    health: str,
    freshness: str,
    conflict_types: list[str],
) -> dict[str, bool]:
    checks = {
        "status": status == case["expected_status"],
        "risk": risk == case.get("expected_risk", risk),
        "health": health == case.get("expected_health", health),
        "freshness": freshness == case.get("expected_freshness", freshness),
    }
    if "expected_blocker" in case:
        checks["blocker"] = case["expected_blocker"] in blockers
    if "expected_conflict_type" in case:
        checks["conflict_type"] = case["expected_conflict_type"] in conflict_types
    return checks


def _evaluate_query_cases(
    cases: list[dict[str, Any]],
    engine: XiaoyiAI,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        analysis = build_query_analysis(case["question"])
        if len(analysis.subquestions) > 1:
            response = engine.ask_compound(
                analysis.standalone_question,
                analysis.subquestions,
                mode=case.get("mode", "expert"),
                top_k=8,
            )
        else:
            response = engine.ask(
                analysis.standalone_question,
                mode=case.get("mode", "expert"),
                top_k=8,
                retrieval_queries=analysis.subquestions,
            )
        response = response.model_copy(
            update={"answer_verification": verify_response(response)}
        )
        health, readiness = assess_response(response, analysis)
        conflict_types = [item.conflict_type for item in health.conflicts]
        checks = _checks(
            case,
            status=readiness.status,
            risk=readiness.risk_level,
            blockers=readiness.blockers,
            health=health.status,
            freshness=health.freshness,
            conflict_types=conflict_types,
        )
        rows.append(
            {
                "id": case["id"],
                "status": readiness.status,
                "risk_level": readiness.risk_level,
                "blockers": readiness.blockers,
                "evidence_health": health.status,
                "freshness": health.freshness,
                "conflict_types": conflict_types,
                "checks": checks,
                "passed": all(checks.values()),
            }
        )
    return rows


def _evaluate_assurance_cases(
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        response = _scenario(case["scenario"])
        health, readiness = assess_response(response)
        conflict_types = [item.conflict_type for item in health.conflicts]
        checks = _checks(
            case,
            status=readiness.status,
            risk=readiness.risk_level,
            blockers=readiness.blockers,
            health=health.status,
            freshness=health.freshness,
            conflict_types=conflict_types,
        )
        rows.append(
            {
                "id": case["id"],
                "scenario": case["scenario"],
                "status": readiness.status,
                "risk_level": readiness.risk_level,
                "blockers": readiness.blockers,
                "evidence_health": health.status,
                "freshness": health.freshness,
                "conflict_types": conflict_types,
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


def run_decision_benchmark(
    path: Path = BENCHMARK_PATH,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    engine = XiaoyiAI()
    query_rows = _evaluate_query_cases(payload["query_cases"], engine)
    assurance_rows = _evaluate_assurance_cases(payload["assurance_cases"])
    all_rows = [*query_rows, *assurance_rows]
    base = payload["base_benchmarks"]
    overall = _summary(all_rows)
    return {
        "benchmark_id": payload["benchmark_id"],
        "benchmark_sha256": _sha256(path),
        "case_count": len(all_rows),
        "combined_case_count": int(base["v1_case_count"])
        + int(base["v2_case_count"])
        + len(all_rows),
        "query": {"summary": _summary(query_rows), "rows": query_rows},
        "assurance": {
            "summary": _summary(assurance_rows),
            "rows": assurance_rows,
        },
        "overall": overall,
        "passed": overall["pass_rate"] == 1.0,
        "scope": payload["scope"],
    }
