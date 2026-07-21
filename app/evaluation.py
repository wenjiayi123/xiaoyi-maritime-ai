from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.knowledge_api import get_knowledge_status
from app.knowledge_policy import detect_jurisdictions
from app.knowledge_intake import KnowledgeIntakeRequest, submit_knowledge_intake
from app.retrieval import get_shared_knowledge_base
from app.runtime_store import runtime_store
from app.security import request_identity
from app.xiaoyi import XiaoyiAI


router = APIRouter(prefix="/api/evaluation", tags=["RAG评测与知识反馈闭环"])


_RETRIEVAL_BENCHMARKS = (
    ("集装箱码头 TOS 负责什么？", ("03_container_terminal.md", "06_tos_and_digital.md"), False),
    ("岸电安全操作规程有哪些？", ("64_cn_port_ship_shore_power_rules.md",), True),
    ("IMO 海事单一窗口从哪一年起强制实施？", ("45_imo_maritime_single_window.md", "46_imo_fal_guidance.md"), True),
    ("船舶晚到导致泊位冲突怎么处理？", ("14_terminal_planning_dispatch.md", "55_vessel_schedule_port_call_qa.md", "33_vessel_navigation_incident_playbooks.md"), False),
    ("台风红色预警下港区要启动哪些流程？", ("08_safety_emergency.md", "37_port_qa_form_taxonomy.md"), False),
    ("DCSA 港口靠泊标准解决什么问题？", ("48_dcsa_port_call_standard.md",), True),
    ("SOLAS 公约主要覆盖哪些船舶安全事项？", ("81_imo_solas_public_summary.md",), True),
    ("STCW 对船员培训和值班有什么作用？", ("83_imo_stcw_public_summary.md",), True),
    ("ISPS Code 管理什么港口设施保安问题？", ("84_imo_isps_code_public_summary.md",), True),
    ("压载水管理公约解决什么环境风险？", ("85_imo_ballast_water_management_summary.md",), True),
    ("IMSBC Code 适用于哪些固体散装货物风险？", ("86_imo_imsbc_code_public_summary.md",), True),
    ("WHO IHR 对指定港口公共卫生能力有什么要求？", ("92_who_ihr_ports_summary.md",), True),
    ("新加坡现行港口条例从哪里核验？", ("99_sg_port_regulations_current.md", "98_sg_maritime_legislation_directory.md"), True),
    ("马来西亚2026年仍有效的航运通告目录在哪里？", ("103_my_active_shipping_notices_2026.md",), True),
    ("中国生态环境法典何时生效？", ("106_china_ecology_environment_code_transition.md",), True),
    ("COLREG 是什么国际规则？", ("110_imo_colreg_public_summary.md",), True),
)

_POLICY_BENCHMARKS = (
    {
        "question": "《港口危险货物安全管理规定》第三十五条原文是什么？",
        "grounded": False,
        "refusal_reason": "official_full_text_required",
    },
    {
        "question": "新加坡港2026年危险品申报时限是多少？",
        "grounded": False,
        "refusal_reason": "official_full_text_required",
    },
    {
        "question": "VGM允许误差是多少？",
        "grounded": False,
        "refusal_reason": "official_full_text_required",
    },
    {
        "question": "新加坡船舶到港官方程序入口在哪里？",
        "grounded": True,
        "expected_source": "101_sg_vessel_arrival_departure_procedures.md",
    },
    {
        "question": "马来西亚2026年仍有效航运通告目录在哪里？",
        "grounded": True,
        "expected_source": "103_my_active_shipping_notices_2026.md",
    },
    {
        "question": "中国生态环境法典在2026年7月是否已经生效？",
        "grounded": True,
        "expected_source": "107_china_marine_environment_law_current.md",
        "as_of_date": date(2026, 7, 15),
    },
    {
        "question": "中国生态环境法典在2026年8月15日是否生效？",
        "grounded": True,
        "expected_source": "106_china_ecology_environment_code_transition.md",
        "as_of_date": date(2026, 8, 15),
    },
    {
        "question": "MARPOL 的具体油类排放限值是什么？",
        "grounded": False,
        "refusal_reason": "official_full_text_required",
    },
    {
        "question": "新加坡港危险品申报时限是多少？",
        "grounded": False,
        "refusal_reason": "official_full_text_required",
        "strict_evidence": False,
    },
)

_LATEST_BENCHMARK: Optional[dict[str, Any]] = None


class EvaluationRunRequest(BaseModel):
    top_k: int = Field(8, ge=1, le=20)


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


def run_benchmark(top_k: int = 8) -> dict[str, Any]:
    kb = get_shared_knowledge_base()
    rows = []
    hit_count = 0
    official_hit_count = 0
    coverage_sum = 0.0
    for question, expected_sources, official_required in _RETRIEVAL_BENCHMARKS:
        hits = kb.search(
            question,
            top_k=top_k,
            jurisdictions=detect_jurisdictions(question) or None,
        )
        matched = next((hit for hit in hits if hit.chunk.source in expected_sources), None)
        hit = matched is not None
        official_hit = bool(matched and matched.chunk.provenance.official) if official_required else True
        hit_count += int(hit)
        official_hit_count += int(official_hit)
        coverage = max((item.coverage for item in hits), default=0.0)
        coverage_sum += coverage
        rows.append(
            {
                "question": question, "expected_sources": list(expected_sources), "hit_at_k": hit,
                "official_required": official_required, "official_hit": official_hit,
                "best_coverage": round(coverage, 4),
                "top_source": hits[0].chunk.source if hits else None,
            }
        )
    retrieval_total = len(rows)
    engine = XiaoyiAI()
    policy_rows: list[dict[str, Any]] = []
    policy_pass_count = 0
    for case in _POLICY_BENCHMARKS:
        result = engine.ask(
            case["question"],
            top_k=top_k,
            strict_evidence=case.get("strict_evidence", True),
            as_of_date=case.get("as_of_date"),
        )
        evidence_sources = {item.source for item in result.evidence}
        passed = (
            result.grounded is case["grounded"]
            and (
                "refusal_reason" not in case
                or result.refusal_reason == case["refusal_reason"]
            )
            and (
                "expected_source" not in case
                or case["expected_source"] in evidence_sources
            )
        )
        policy_pass_count += int(passed)
        policy_rows.append(
            {
                "question": case["question"],
                "expected_grounded": case["grounded"],
                "actual_grounded": result.grounded,
                "expected_refusal_reason": case.get("refusal_reason"),
                "actual_refusal_reason": result.refusal_reason,
                "expected_source": case.get("expected_source"),
                "evidence_sources": sorted(evidence_sources),
                "passed": passed,
            }
        )
    policy_total = len(policy_rows)
    total = retrieval_total + policy_total
    return {
        "retrieval_method": "hybrid_sparse_v2",
        "benchmark_count": total,
        "retrieval_benchmark_count": retrieval_total,
        "policy_benchmark_count": policy_total,
        "hit_at_k": round(hit_count / retrieval_total, 4),
        "official_requirement_pass_rate": round(official_hit_count / retrieval_total, 4),
        "average_best_coverage": round(coverage_sum / retrieval_total, 4),
        "policy_safety_pass_rate": round(policy_pass_count / policy_total, 4),
        "passed": (
            hit_count == retrieval_total
            and official_hit_count == retrieval_total
            and policy_pass_count == policy_total
        ),
        "items": rows,
        "policy_items": policy_rows,
    }


@router.get("/summary")
def evaluation_summary() -> dict[str, Any]:
    status = get_knowledge_status()
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
            "documents": status.document_count, "chunks": status.chunk_count,
            "official_documents": status.official_verified_documents,
            "index_sha256": status.index_sha256,
        },
        "runtime": runtime_store.metrics(),
        "latest_benchmark": _LATEST_BENCHMARK or {
            "retrieval_method": "hybrid_sparse_v2",
            "benchmark_count": len(_RETRIEVAL_BENCHMARKS) + len(_POLICY_BENCHMARKS),
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
        correlation_id="evaluation-benchmark", actor_id="system", actor_role="admin",
        action="evaluation.run", resource="rag-benchmark", risk_level="low",
        outcome="success" if result["passed"] else "failed", request=payload.model_dump(), response=result,
        detail=f"完成 {result['benchmark_count']} 条固定问答评测",
    )
    return result


@router.post("/feedback", status_code=201)
def create_feedback(payload: FeedbackRequest, request: Request) -> dict[str, Any]:
    identity = request_identity(request)
    submitted_by = identity.actor_id if identity.authenticated else payload.submitted_by
    item = runtime_store.create_feedback(
        question=payload.question, answer_id=payload.answer_id, rating=payload.rating,
        correction=payload.correction, evidence_ids=payload.evidence_ids,
        submitted_by=submitted_by,
    )
    runtime_store.add_audit(
        correlation_id=item["id"], actor_id=submitted_by, actor_role=identity.role,
        action="feedback.submit", resource="knowledge-feedback", risk_level="low", outcome="success",
        request=payload.model_dump(), response={"feedback_id": item["id"]}, detail="反馈已进入人工审核队列",
    )
    return item


@router.get("/feedback")
def list_feedback(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    items = runtime_store.list_feedback(limit)
    return {"total": len(items), "items": items}


@router.post("/feedback/{feedback_id}/review")
def review_feedback(feedback_id: str, payload: FeedbackReviewRequest, request: Request) -> dict[str, Any]:
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
                filename=f"{feedback_id}.md", content=content,
                institution="小懿AI反馈闭环", version="pending-review", official_claim=False,
            )
        )
        intake_id = intake.id
        status = "submitted_to_knowledge_intake"
    else:
        status = "rejected"
    updated = runtime_store.update_feedback(
        feedback_id, status=status, reviewed_by=reviewed_by, intake_id=intake_id
    )
    runtime_store.add_audit(
        correlation_id=feedback_id, actor_id=reviewed_by, actor_role=identity.role,
        action="feedback.review", resource="knowledge-feedback", risk_level="medium", outcome="success",
        request=payload.model_dump(), response=updated, detail=f"反馈审核结果：{status}",
    )
    return updated or {}
