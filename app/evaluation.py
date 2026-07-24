from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import statistics
import time
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.config import EVALUATION_BENCHMARK_PATH
from app.knowledge_api import get_knowledge_status
from app.knowledge_intake import KnowledgeIntakeRequest, submit_knowledge_intake
from app.knowledge_policy import detect_jurisdictions
from app.retrieval import SearchHit, get_shared_knowledge_base
from app.runtime_store import runtime_store
from app.security import request_identity
from app.xiaoyi import XiaoyiAI


router = APIRouter(prefix="/api/evaluation", tags=["RAG评测与知识反馈闭环"])
_LATEST_BENCHMARK: Optional[dict[str, Any]] = None


class EvaluationRunRequest(BaseModel):
    top_k: int = Field(5, ge=1, le=20)


class FeedbackRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=1000)
    answer_id: Optional[str] = Field(None, max_length=160)
    rating: int = Field(..., ge=1, le=5)
    correction: Optional[str] = Field(None, max_length=5000)
    evidence_ids: list[str] = Field(default_factory=list)
    submitted_by: str = Field("local-admin", min_length=2, max_length=100)


class FeedbackReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reviewed_by: str = Field(..., min_length=2, max_length=100)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_benchmark(path: Path = EVALUATION_BENCHMARK_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    retrieval_cases = payload.get("retrieval_cases")
    policy_cases = payload.get("policy_cases")
    if not isinstance(retrieval_cases, list) or not isinstance(policy_cases, list):
        raise ValueError("Benchmark must contain retrieval_cases and policy_cases lists")
    identifiers = [
        str(item.get("id") or "")
        for item in [*retrieval_cases, *policy_cases]
    ]
    if not identifiers or any(not value for value in identifiers):
        raise ValueError("Every benchmark case requires a stable id")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Benchmark case ids must be unique")
    if any(item.get("split") not in {"validation", "test"} for item in [*retrieval_cases, *policy_cases]):
        raise ValueError("Benchmark split must be validation or test")
    return payload


def _source_rank(hits: list[SearchHit], expected_sources: set[str]) -> int | None:
    for rank, hit in enumerate(hits, start=1):
        if hit.chunk.source in expected_sources:
            return rank
    return None


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction))))
    return round(ordered[index], 3)


def _latency_summary(values: list[float]) -> dict[str, float]:
    return {
        "mean_ms": round(statistics.fmean(values), 3) if values else 0.0,
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "max_ms": round(max(values), 3) if values else 0.0,
    }


def _retrieval_summary(rows: list[dict[str, Any]], rank_field: str) -> dict[str, Any]:
    total = len(rows)
    official_rows = [row for row in rows if row["official_required"]]
    jurisdiction_rows = [
        row
        for row in rows
        if row["expected_jurisdictions"]
        and set(row["expected_jurisdictions"]) != {"GLOBAL"}
    ]
    global_rows = [
        row
        for row in rows
        if set(row["expected_jurisdictions"]) == {"GLOBAL"}
    ]
    category_totals: dict[str, list[bool]] = {}
    reciprocal_ranks: list[float] = []
    for row in rows:
        rank = row[rank_field]
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        category_totals.setdefault(row["category"], []).append(bool(rank and rank <= 5))
    return {
        "case_count": total,
        "hit_at_1": round(
            sum(bool(row[rank_field] and row[rank_field] <= 1) for row in rows) / max(1, total),
            4,
        ),
        "hit_at_3": round(
            sum(bool(row[rank_field] and row[rank_field] <= 3) for row in rows) / max(1, total),
            4,
        ),
        "hit_at_5": round(
            sum(bool(row[rank_field] and row[rank_field] <= 5) for row in rows) / max(1, total),
            4,
        ),
        "mrr": round(statistics.fmean(reciprocal_ranks), 4) if reciprocal_ranks else 0.0,
        "official_requirement_pass_rate": round(
            sum(row["official_pass"] for row in official_rows) / max(1, len(official_rows)),
            4,
        ),
        "official_top_k_precision": round(
            statistics.fmean(row["official_top_k_precision"] for row in official_rows),
            4,
        )
        if official_rows
        else None,
        "evidence_hash_completeness_rate": round(
            sum(row["top_k_hash_complete"] for row in rows) / max(1, total),
            4,
        ),
        "jurisdiction_routing_case_count": len(jurisdiction_rows),
        "jurisdiction_routing_accuracy": round(
            sum(row["jurisdiction_pass"] for row in jurisdiction_rows)
            / max(1, len(jurisdiction_rows)),
            4,
        ),
        "global_scope_case_count": len(global_rows),
        "global_scope_neutrality_accuracy": round(
            sum(row["jurisdiction_pass"] for row in global_rows)
            / max(1, len(global_rows)),
            4,
        ),
        "category_hit_at_5": {
            category: round(sum(values) / len(values), 4)
            for category, values in sorted(category_totals.items())
        },
    }


def _evaluate_retrieval_cases(
    cases: list[dict[str, Any]],
    *,
    top_k: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kb = get_shared_knowledge_base()
    rows: list[dict[str, Any]] = []
    hybrid_latencies: list[float] = []
    baseline_latencies: list[float] = []
    search_depth = max(5, top_k)
    for case in cases:
        question = str(case["question"])
        expected_sources = {str(value) for value in case["expected_sources"]}
        detected_jurisdictions = detect_jurisdictions(question)
        official_required = bool(case.get("official_required", False))

        started = time.perf_counter()
        hybrid_hits = kb.search(
            question,
            top_k=search_depth,
            official_only=official_required,
            jurisdictions=detected_jurisdictions or None,
        )
        hybrid_latencies.append((time.perf_counter() - started) * 1000.0)

        started = time.perf_counter()
        baseline_hits = kb.search_bm25_baseline(
            question,
            top_k=search_depth,
            official_only=official_required,
            jurisdictions=detected_jurisdictions or None,
        )
        baseline_latencies.append((time.perf_counter() - started) * 1000.0)

        hybrid_rank = _source_rank(hybrid_hits, expected_sources)
        baseline_rank = _source_rank(baseline_hits, expected_sources)
        matched_hybrid = (
            hybrid_hits[hybrid_rank - 1]
            if hybrid_rank is not None and hybrid_rank <= len(hybrid_hits)
            else None
        )
        expected_jurisdictions = {
            str(value).upper() for value in case.get("expected_jurisdictions", [])
        }
        jurisdiction_pass = (
            not expected_jurisdictions
            or (
                expected_jurisdictions == {"GLOBAL"}
                and (
                    not detected_jurisdictions
                    or "GLOBAL" in detected_jurisdictions
                )
            )
            or expected_jurisdictions.issubset(set(detected_jurisdictions))
        )
        official_pass = bool(
            not official_required
            or (
                hybrid_rank is not None
                and hybrid_rank <= search_depth
                and matched_hybrid
                and matched_hybrid.chunk.provenance.official
            )
        )
        rows.append(
            {
                "id": case["id"],
                "split": case["split"],
                "category": case["category"],
                "question": question,
                "expected_sources": sorted(expected_sources),
                "official_required": official_required,
                "expected_jurisdictions": sorted(expected_jurisdictions),
                "detected_jurisdictions": list(detected_jurisdictions),
                "jurisdiction_pass": jurisdiction_pass,
                "hybrid_rank": hybrid_rank,
                "baseline_rank": baseline_rank,
                "official_pass": official_pass,
                "official_top_k_precision": (
                    round(
                        sum(hit.chunk.provenance.official for hit in hybrid_hits)
                        / len(hybrid_hits),
                        4,
                    )
                    if hybrid_hits
                    else 0.0
                ),
                "top_k_hash_complete": bool(
                    hybrid_hits
                    and all(
                        hit.chunk.content_hash and hit.chunk.document_hash
                        for hit in hybrid_hits
                    )
                ),
                "hybrid_top_source": hybrid_hits[0].chunk.source if hybrid_hits else None,
                "baseline_top_source": baseline_hits[0].chunk.source if baseline_hits else None,
                "best_coverage": round(
                    max((item.coverage for item in hybrid_hits), default=0.0),
                    4,
                ),
            }
        )

    validation_rows = [row for row in rows if row["split"] == "validation"]
    test_rows = [row for row in rows if row["split"] == "test"]
    validation_hybrid = _retrieval_summary(validation_rows, "hybrid_rank")
    test_hybrid = _retrieval_summary(test_rows, "hybrid_rank")
    test_baseline = _retrieval_summary(test_rows, "baseline_rank")
    return rows, {
        "method": "hybrid_sparse_v2",
        "baseline_method": "bm25_only_v1",
        "validation": {
            "hybrid": validation_hybrid,
            "baseline": _retrieval_summary(validation_rows, "baseline_rank"),
        },
        "test": {
            "hybrid": test_hybrid,
            "baseline": test_baseline,
            "hit_at_5_lift_percentage_points": round(
                (test_hybrid["hit_at_5"] - test_baseline["hit_at_5"]) * 100.0,
                2,
            ),
            "mrr_lift_percentage_points": round(
                (test_hybrid["mrr"] - test_baseline["mrr"]) * 100.0,
                2,
            ),
        },
        "overall": {
            "hybrid": _retrieval_summary(rows, "hybrid_rank"),
            "baseline": _retrieval_summary(rows, "baseline_rank"),
        },
        "latency": {
            "hybrid": _latency_summary(hybrid_latencies),
            "baseline": _latency_summary(baseline_latencies),
            "scope": "single-process local measurement; not a production SLA",
        },
    }


def _policy_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    unsafe_rows = [row for row in rows if not row["expected_grounded"]]
    jurisdiction_rows = [row for row in rows if row["expected_jurisdictions"]]
    temporal_rows = [row for row in rows if row["category"] == "temporal_applicability"]
    live_rows = [row for row in rows if row["category"] == "live_data_boundary"]
    category_rows: dict[str, list[bool]] = {}
    for row in rows:
        category_rows.setdefault(row["category"], []).append(row["passed"])
    return {
        "case_count": total,
        "policy_safety_pass_rate": round(
            sum(row["passed"] for row in rows) / max(1, total),
            4,
        ),
        "unsupported_answer_block_rate": round(
            sum(row["unsafe_answer_blocked"] for row in unsafe_rows)
            / max(1, len(unsafe_rows)),
            4,
        ),
        "jurisdiction_routing_accuracy": round(
            sum(row["jurisdiction_pass"] for row in jurisdiction_rows)
            / max(1, len(jurisdiction_rows)),
            4,
        ),
        "temporal_applicability_accuracy": round(
            sum(row["passed"] for row in temporal_rows) / max(1, len(temporal_rows)),
            4,
        )
        if temporal_rows
        else None,
        "live_data_boundary_pass_rate": round(
            sum(row["passed"] for row in live_rows) / max(1, len(live_rows)),
            4,
        )
        if live_rows
        else None,
        "category_pass_rate": {
            category: round(sum(values) / len(values), 4)
            for category, values in sorted(category_rows.items())
        },
    }


def _evaluate_policy_cases(
    cases: list[dict[str, Any]],
    *,
    top_k: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    engine = XiaoyiAI()
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    for case in cases:
        as_of_date = (
            date.fromisoformat(case["as_of_date"])
            if case.get("as_of_date")
            else None
        )
        started = time.perf_counter()
        result = engine.ask(
            str(case["question"]),
            top_k=top_k,
            strict_evidence=bool(case.get("strict_evidence", True)),
            as_of_date=as_of_date,
        )
        latencies.append((time.perf_counter() - started) * 1000.0)
        evidence_sources = {item.source for item in result.evidence}
        expected_sources = {
            str(value) for value in case.get("expected_sources", [])
        }
        expected_jurisdictions = {
            str(value).upper() for value in case.get("expected_jurisdictions", [])
        }
        source_pass = not expected_sources or bool(
            expected_sources.intersection(evidence_sources)
        )
        refusal_pass = (
            "expected_refusal_reason" not in case
            or result.refusal_reason == case["expected_refusal_reason"]
        )
        jurisdiction_pass = (
            not expected_jurisdictions
            or expected_jurisdictions.issubset(set(result.jurisdictions))
        )
        grounded_pass = result.grounded is bool(case["expected_grounded"])
        passed = grounded_pass and source_pass and refusal_pass and jurisdiction_pass
        expected_grounded = bool(case["expected_grounded"])
        rows.append(
            {
                "id": case["id"],
                "split": case["split"],
                "category": case["category"],
                "question": case["question"],
                "expected_grounded": expected_grounded,
                "actual_grounded": result.grounded,
                "expected_refusal_reason": case.get("expected_refusal_reason"),
                "actual_refusal_reason": result.refusal_reason,
                "expected_sources": sorted(expected_sources),
                "evidence_sources": sorted(evidence_sources),
                "expected_jurisdictions": sorted(expected_jurisdictions),
                "actual_jurisdictions": result.jurisdictions,
                "source_pass": source_pass,
                "refusal_pass": refusal_pass,
                "jurisdiction_pass": jurisdiction_pass,
                "grounded_pass": grounded_pass,
                "unsafe_answer_blocked": bool(
                    expected_grounded
                    or (
                        not result.grounded
                        and refusal_pass
                    )
                ),
                "passed": passed,
            }
        )
    validation_rows = [row for row in rows if row["split"] == "validation"]
    test_rows = [row for row in rows if row["split"] == "test"]
    return rows, {
        "validation": _policy_summary(validation_rows),
        "test": _policy_summary(test_rows),
        "overall": _policy_summary(rows),
        "latency": {
            **_latency_summary(latencies),
            "scope": "single-process local measurement; not a production SLA",
        },
    }


def run_benchmark(top_k: int = 5) -> dict[str, Any]:
    benchmark = _load_benchmark()
    retrieval_rows, retrieval = _evaluate_retrieval_cases(
        benchmark["retrieval_cases"],
        top_k=top_k,
    )
    policy_rows, policy = _evaluate_policy_cases(
        benchmark["policy_cases"],
        top_k=top_k,
    )
    status = get_knowledge_status()
    test_retrieval = retrieval["test"]["hybrid"]
    test_baseline = retrieval["test"]["baseline"]
    test_policy = policy["test"]
    benchmark_count = len(retrieval_rows) + len(policy_rows)
    test_case_count = test_retrieval["case_count"] + test_policy["case_count"]
    passed = bool(
        test_retrieval["hit_at_5"] >= 0.90
        and test_retrieval["official_requirement_pass_rate"] >= 0.90
        and test_retrieval["official_top_k_precision"] == 1.0
        and test_retrieval["evidence_hash_completeness_rate"] == 1.0
        and test_retrieval["jurisdiction_routing_accuracy"] == 1.0
        and test_retrieval["global_scope_neutrality_accuracy"] == 1.0
        and test_policy["policy_safety_pass_rate"] >= 0.90
        and test_policy["unsupported_answer_block_rate"] == 1.0
    )
    average_best_coverage = round(
        statistics.fmean(row["best_coverage"] for row in retrieval_rows),
        4,
    )
    return {
        "report_version": "1.0",
        "benchmark_id": benchmark["benchmark_id"],
        "benchmark_sha256": _sha256_file(EVALUATION_BENCHMARK_PATH),
        "benchmark_scope": benchmark["scope"],
        "split_policy": benchmark["split_policy"],
        "top_k": top_k,
        "knowledge_snapshot": {
            "documents": status.document_count,
            "chunks": status.chunk_count,
            "official_documents": status.official_verified_documents,
            "index_sha256": status.index_sha256,
        },
        "retrieval": retrieval,
        "policy": policy,
        "resume_safe_metrics": {
            "fixed_case_count": benchmark_count,
            "fixed_test_case_count": test_case_count,
            "test_retrieval_case_count": test_retrieval["case_count"],
            "test_policy_case_count": test_policy["case_count"],
            "hybrid_hit_at_5": test_retrieval["hit_at_5"],
            "bm25_hit_at_5": test_baseline["hit_at_5"],
            "hit_at_5_lift_percentage_points": retrieval["test"][
                "hit_at_5_lift_percentage_points"
            ],
            "hybrid_mrr": test_retrieval["mrr"],
            "bm25_mrr": test_baseline["mrr"],
            "mrr_lift_percentage_points": retrieval["test"][
                "mrr_lift_percentage_points"
            ],
            "official_requirement_pass_rate": test_retrieval[
                "official_requirement_pass_rate"
            ],
            "official_top_k_precision": test_retrieval[
                "official_top_k_precision"
            ],
            "evidence_hash_completeness_rate": test_retrieval[
                "evidence_hash_completeness_rate"
            ],
            "retrieval_jurisdiction_routing_case_count": test_retrieval[
                "jurisdiction_routing_case_count"
            ],
            "retrieval_jurisdiction_routing_accuracy": test_retrieval[
                "jurisdiction_routing_accuracy"
            ],
            "global_scope_neutrality_accuracy": test_retrieval[
                "global_scope_neutrality_accuracy"
            ],
            "policy_safety_pass_rate": test_policy["policy_safety_pass_rate"],
            "unsupported_answer_block_rate": test_policy[
                "unsupported_answer_block_rate"
            ],
            "jurisdiction_routing_accuracy": test_policy[
                "jurisdiction_routing_accuracy"
            ],
            "temporal_applicability_accuracy": test_policy[
                "temporal_applicability_accuracy"
            ],
            "live_data_boundary_pass_rate": test_policy[
                "live_data_boundary_pass_rate"
            ],
            "required_qualifier": (
                "fixed repository benchmark over registered public/curated maritime "
                "sources; test partition is release acceptance, not untouched held-out "
                "data, a field user study, production KPI, or global-coverage claim"
            ),
        },
        "retrieval_method": retrieval["method"],
        "benchmark_count": benchmark_count,
        "retrieval_benchmark_count": len(retrieval_rows),
        "policy_benchmark_count": len(policy_rows),
        "hit_at_k": retrieval["overall"]["hybrid"]["hit_at_5"],
        "official_requirement_pass_rate": retrieval["overall"]["hybrid"][
            "official_requirement_pass_rate"
        ],
        "average_best_coverage": average_best_coverage,
        "policy_safety_pass_rate": policy["overall"]["policy_safety_pass_rate"],
        "passed": passed,
        "items": retrieval_rows,
        "policy_items": policy_rows,
    }


@router.get("/summary")
def evaluation_summary() -> dict[str, Any]:
    status = get_knowledge_status()
    benchmark = _load_benchmark()
    benchmark_count = len(benchmark["retrieval_cases"]) + len(benchmark["policy_cases"])
    return {
        "seven_priorities": [
            {"id": 1, "name": "系统能力注册", "status": "ready"},
            {"id": 2, "name": "统一业务上下文", "status": "ready"},
            {"id": 3, "name": "多源证据融合", "status": "ready"},
            {"id": 4, "name": "RAG 2.0", "status": "ready"},
            {"id": 5, "name": "跨系统任务编排", "status": "ready"},
            {"id": 6, "name": "权限与持久审计", "status": "ready"},
            {"id": 7, "name": "评测与反馈闭环", "status": "ready"},
        ],
        "knowledge": {
            "documents": status.document_count,
            "chunks": status.chunk_count,
            "official_documents": status.official_verified_documents,
            "index_sha256": status.index_sha256,
        },
        "runtime": runtime_store.metrics(),
        "latest_benchmark": _LATEST_BENCHMARK
        or {
            "retrieval_method": "hybrid_sparse_v2",
            "benchmark_count": benchmark_count,
            "hit_at_k": 0.0,
            "official_requirement_pass_rate": 0.0,
            "average_best_coverage": 0.0,
            "policy_safety_pass_rate": 0.0,
            "passed": False,
            "status": "not_run_in_this_process",
        },
    }


@router.post("/run")
def evaluation_run(payload: EvaluationRunRequest) -> dict[str, Any]:
    global _LATEST_BENCHMARK
    result = run_benchmark(payload.top_k)
    _LATEST_BENCHMARK = result
    runtime_store.add_audit(
        correlation_id="evaluation-benchmark",
        actor_id="system",
        actor_role="admin",
        action="evaluation.run",
        resource="rag-benchmark",
        risk_level="low",
        outcome="success" if result["passed"] else "failed",
        request=payload.model_dump(),
        response=result,
        detail=f"完成 {result['benchmark_count']} 条固定问答评测",
    )
    return result


@router.post("/feedback", status_code=201)
def create_feedback(payload: FeedbackRequest, request: Request) -> dict[str, Any]:
    identity = request_identity(request)
    submitted_by = (
        identity.actor_id if identity.authenticated else payload.submitted_by
    )
    item = runtime_store.create_feedback(
        question=payload.question,
        answer_id=payload.answer_id,
        rating=payload.rating,
        correction=payload.correction,
        evidence_ids=payload.evidence_ids,
        submitted_by=submitted_by,
    )
    runtime_store.add_audit(
        correlation_id=item["id"],
        actor_id=submitted_by,
        actor_role=identity.role,
        action="feedback.submit",
        resource="knowledge-feedback",
        risk_level="low",
        outcome="success",
        request=payload.model_dump(),
        response={"feedback_id": item["id"]},
        detail="反馈已进入人工审核队列",
    )
    return item


@router.get("/feedback")
def list_feedback(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    items = runtime_store.list_feedback(limit)
    return {"total": len(items), "items": items}


@router.post("/feedback/{feedback_id}/review")
def review_feedback(
    feedback_id: str,
    payload: FeedbackReviewRequest,
    request: Request,
) -> dict[str, Any]:
    identity = request_identity(request)
    reviewed_by = identity.actor_id if identity.authenticated else payload.reviewed_by
    item = runtime_store.get_feedback(feedback_id)
    if item is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    intake_id = None
    if payload.decision == "approve":
        if not item.get("correction"):
            raise HTTPException(status_code=409, detail="没有修订内容，不能提交知识待审核区")
        content = (
            f"# 用户反馈知识候选\n\n## 原问题\n{item['question']}\n\n"
            f"## 建议修订\n{item['correction']}\n\n"
            f"## 关联证据\n{', '.join(item['evidence_ids']) or '未提供'}\n"
        )
        intake = submit_knowledge_intake(
            KnowledgeIntakeRequest(
                filename=f"{feedback_id}.md",
                content=content,
                institution="小懿AI反馈闭环",
                version="pending-review",
                official_claim=False,
            )
        )
        intake_id = intake.id
        status = "submitted_to_knowledge_intake"
    else:
        status = "rejected"
    updated = runtime_store.update_feedback(
        feedback_id,
        status=status,
        reviewed_by=reviewed_by,
        intake_id=intake_id,
    )
    runtime_store.add_audit(
        correlation_id=feedback_id,
        actor_id=reviewed_by,
        actor_role=identity.role,
        action="feedback.review",
        resource="knowledge-feedback",
        risk_level="medium",
        outcome="success",
        request=payload.model_dump(),
        response=updated,
        detail=f"反馈审核结果：{status}",
    )
    return updated or {}
