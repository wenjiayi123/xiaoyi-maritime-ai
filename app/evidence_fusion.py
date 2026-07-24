from __future__ import annotations

from dataclasses import replace
from datetime import date
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.domain_context import DomainContext
from app.knowledge_policy import (
    build_query_policy,
    requires_official_evidence,
    source_is_applicable,
)
from app.retrieval import SearchHit, get_shared_knowledge_base


router = APIRouter(prefix="/api/evidence", tags=["知识与系统证据融合"])

EvidenceType = Literal["knowledge", "system_result", "simulation_result", "capability_contract"]


class ExternalEvidenceInput(BaseModel):
    source_type: Literal["system_result", "simulation_result", "capability_contract"]
    source_id: str = Field(..., min_length=2, max_length=160)
    system_id: str = Field(..., min_length=2, max_length=80)
    capability_id: Optional[str] = None
    title: str
    payload: dict[str, Any] = Field(default_factory=dict)
    fetched_at: Optional[datetime] = None
    verification_status: str = "client_supplied"
    correlation_id: Optional[str] = None


class EvidenceEnvelope(BaseModel):
    id: str
    source_type: EvidenceType
    source_id: str
    title: str
    summary: str
    score: float = 0.0
    coverage: float = 0.0
    official: bool = False
    verification_status: str
    source_quality: str
    source_url: Optional[str] = None
    institution: Optional[str] = None
    version: Optional[str] = None
    document_checksum_sha256: Optional[str] = None
    chunk_checksum_sha256: Optional[str] = None
    system_id: Optional[str] = None
    capability_id: Optional[str] = None
    fetched_at: datetime
    correlation_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    citation_role: Literal["supporting", "locator_only"] = "supporting"


class EvidenceFusionRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000)
    context: DomainContext = Field(default_factory=DomainContext)
    include_knowledge: bool = True
    top_k: int = Field(6, ge=1, le=20)
    official_only: bool = False
    external_evidence: list[ExternalEvidenceInput] = Field(default_factory=list)


class EvidenceFusionResponse(BaseModel):
    trace_id: str
    query: str
    context: DomainContext
    grounded: bool
    knowledge_count: int
    system_result_count: int
    simulation_result_count: int
    evidence: list[EvidenceEnvelope]
    evidence_summary: str
    boundary_notice: str
    evidence_requirement: str = "registered_index"
    jurisdictions: list[str] = Field(default_factory=list)
    as_of_date: date = Field(default_factory=date.today)


def _knowledge_envelope(
    hit: SearchHit,
    *,
    citation_role: Literal["supporting", "locator_only"] = "supporting",
) -> EvidenceEnvelope:
    provenance = hit.chunk.provenance
    return EvidenceEnvelope(
        id=hit.chunk.id, source_type="knowledge", source_id=hit.chunk.source,
        title=hit.chunk.title, summary=hit.snippet, score=hit.score, coverage=hit.coverage,
        official=provenance.official, verification_status=provenance.verification_status,
        source_quality=provenance.source_quality, source_url=provenance.source_url,
        institution=provenance.institution, version=provenance.version,
        document_checksum_sha256=hit.chunk.document_hash or None,
        chunk_checksum_sha256=hit.chunk.content_hash or None,
        fetched_at=datetime.now(timezone.utc),
        payload={"matched_terms": hit.matched_terms, "retrieval_method": getattr(hit, "retrieval_method", "lexical")},
        citation_role=citation_role,
    )


def _external_envelope(
    item: ExternalEvidenceInput,
    *,
    trusted_live_read: bool = False,
) -> EvidenceEnvelope:
    safe_summary = str(item.payload.get("summary") or item.payload.get("status") or item.title)[:600]
    verified_live_read = bool(
        trusted_live_read
        and item.verification_status == "live_read"
        and item.source_type in {"system_result", "simulation_result"}
        and item.correlation_id
        and item.fetched_at
    )
    effective_status = "live_read" if verified_live_read else (
        "preview_only"
        if item.verification_status == "preview_only"
        else "client_supplied"
    )
    return EvidenceEnvelope(
        id=f"external-{uuid4().hex}", source_type=item.source_type, source_id=item.source_id,
        title=item.title, summary=safe_summary, verification_status=effective_status,
        source_quality="live_system" if verified_live_read else "unverified_external",
        system_id=item.system_id, capability_id=item.capability_id,
        fetched_at=item.fetched_at or datetime.now(timezone.utc), correlation_id=item.correlation_id,
        payload=item.payload,
    )


def fuse_evidence(
    payload: EvidenceFusionRequest,
    *,
    trusted_external: bool = False,
) -> EvidenceFusionResponse:
    items: list[EvidenceEnvelope] = []
    policy = build_query_policy(
        payload.query,
        official_required=(
            payload.official_only or requires_official_evidence(payload.query)
        ),
    )
    supporting_knowledge_ids: set[str] = set()
    if payload.include_knowledge:
        raw_hits = get_shared_knowledge_base().search(
            payload.query,
            top_k=min(payload.top_k * 3, 60),
            official_only=policy.official_required,
            jurisdictions=policy.jurisdictions or None,
        )
        auditable = [
            hit for hit in raw_hits
            if hit.coverage >= 0.08
            and hit.chunk.provenance.provenance_type != "unregistered"
            and bool(hit.chunk.content_hash)
            and bool(hit.chunk.document_hash)
        ]
        supporting = [
            hit
            for hit in auditable
            if hit.coverage >= 0.30
            and source_is_applicable(hit.chunk.provenance, policy)
        ][: payload.top_k]
        supporting_knowledge_ids = {hit.chunk.id for hit in supporting}
        locator_policy = replace(
            policy,
            evidence_requirement="official_summary",
            full_text_required=False,
            locator_facts_allowed=True,
        )
        display = (
            [
                hit
                for hit in auditable
                if source_is_applicable(hit.chunk.provenance, locator_policy)
            ][: payload.top_k]
            if policy.official_required
            else auditable[: payload.top_k]
        )
        items.extend(
            _knowledge_envelope(
                hit,
                citation_role=(
                    "supporting"
                    if hit.chunk.id in supporting_knowledge_ids
                    else "locator_only"
                ),
            )
            for hit in display
        )
    items.extend(
        _external_envelope(item, trusted_live_read=trusted_external)
        for item in payload.external_evidence
    )
    knowledge_count = sum(item.source_type == "knowledge" for item in items)
    system_count = sum(item.source_type == "system_result" for item in items)
    simulation_count = sum(item.source_type == "simulation_result" for item in items)
    grounded = bool(supporting_knowledge_ids) or (
        not policy.official_required
        and any(
            item.source_type in {"system_result", "simulation_result"}
            and item.verification_status == "live_read"
            for item in items
        )
    )
    parts = []
    if knowledge_count:
        supporting_count = sum(
            item.source_type == "knowledge" and item.citation_role == "supporting"
            for item in items
        )
        locator_count = knowledge_count - supporting_count
        if supporting_count:
            parts.append(f"{supporting_count} 条可用于回答的知识证据")
        if locator_count:
            parts.append(f"{locator_count} 条仅定位知识来源")
    if system_count:
        parts.append(f"{system_count} 条系统结果")
    if simulation_count:
        parts.append(f"{simulation_count} 条推演结果")
    return EvidenceFusionResponse(
        trace_id=f"evidence-{uuid4().hex}", query=payload.query, context=payload.context,
        grounded=grounded, knowledge_count=knowledge_count, system_result_count=system_count,
        simulation_result_count=simulation_count, evidence=items,
        evidence_summary="、".join(parts) if parts else "没有可用证据",
        boundary_notice=(
            "知识、实时系统数据和模型推演结果分层展示；client_supplied 或 preview_only 只表示调用契约，"
            "不能作为已验证生产事实；官方摘要或目录不能替代条款级全文证据。"
        ),
        evidence_requirement=policy.evidence_requirement,
        jurisdictions=list(policy.jurisdictions),
        as_of_date=policy.as_of_date,
    )


@router.post("/fuse", response_model=EvidenceFusionResponse)
def fuse_evidence_api(payload: EvidenceFusionRequest) -> EvidenceFusionResponse:
    return fuse_evidence(payload)
