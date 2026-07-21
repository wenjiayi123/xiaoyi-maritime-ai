from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional, Union

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from app.config import (
    AUTHORITY_COVERAGE_PATH,
    INDEX_PATH,
    KB_DIR,
    KNOWLEDGE_CATALOG_PATH,
    SOURCE_REGISTRY_PATH,
)
from app.provenance import SourceProvenance, load_source_registry
from app.knowledge_policy import detect_jurisdictions
from app.retrieval import KnowledgeBase, KnowledgeChunk, get_shared_knowledge_base, load_index


router = APIRouter(prefix="/api/knowledge", tags=["可审计知识库"])


class KnowledgeStatus(BaseModel):
    status: str
    document_count: int
    chunk_count: int
    official_verified_documents: int
    official_verified_chunks: int
    official_summary_documents: int
    official_full_text_documents: int
    official_locator_documents: int
    internal_curated_documents: int
    unregistered_documents: int
    review_current_documents: int
    review_due_documents: int
    review_date_missing_documents: int
    jurisdiction_documents: dict[str, int]
    completeness_claim: str = "partial_auditable_coverage"
    registry_version: str
    index_sha256: str
    index_built_at: datetime
    strict_evidence_default: bool = True
    notice: str


class KnowledgeSourceItem(BaseModel):
    source_id: str
    display_name: str
    institution: Optional[str]
    source_url: Optional[str]
    version: Optional[str]
    provenance_type: str
    official: bool
    verification_status: str
    source_quality: str
    license: Optional[str]
    notes: Optional[str]
    jurisdictions: list[str]
    content_scope: str
    legal_force: str
    effective_from: Optional[str]
    effective_to: Optional[str]
    last_verified_at: Optional[str]
    review_due_at: Optional[str]
    review_status: str
    update_frequency: Optional[str]
    chunk_count: int
    document_checksum_sha256: Optional[str]


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=300)
    top_k: int = Field(8, ge=1, le=30)
    official_only: bool = False
    source_quality: Optional[str] = None
    institution: Optional[str] = None
    jurisdiction: Optional[str] = Field(None, max_length=40)
    content_scope: Optional[str] = Field(None, max_length=80)
    current_only: bool = False
    min_coverage: float = Field(0.30, ge=0.0, le=1.0)


class KnowledgeSearchHit(BaseModel):
    id: str
    source: str
    title: str
    snippet: str
    score: float
    lexical_score: float = 0.0
    semantic_score: float = 0.0
    rerank_score: float = 0.0
    retrieval_method: str = "hybrid_sparse_v2"
    coverage: float
    matched_terms: list[str]
    qualified: bool
    qualification_reason: str
    source_url: Optional[str]
    institution: Optional[str]
    version: Optional[str]
    official: bool
    verification_status: str
    source_quality: str
    jurisdictions: list[str]
    content_scope: str
    legal_force: str
    effective_from: Optional[str]
    effective_to: Optional[str]
    last_verified_at: Optional[str]
    review_due_at: Optional[str]
    review_status: str
    document_checksum_sha256: Optional[str]
    chunk_checksum_sha256: Optional[str]


class KnowledgeSearchResponse(BaseModel):
    query: str
    grounded: bool
    result_count: int
    official_result_count: int
    min_coverage: float
    retrieval_method: str = "hybrid_sparse_v2"
    notice: str
    hits: list[KnowledgeSearchHit]


class KnowledgeCatalogCoverageCounts(BaseModel):
    indexed: int = Field(ge=0)
    partial: int = Field(ge=0)
    planned: int = Field(ge=0)


class KnowledgeCatalogCoverageSummary(BaseModel):
    categories: KnowledgeCatalogCoverageCounts
    topics: KnowledgeCatalogCoverageCounts


class KnowledgeCatalogTopic(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    priority: Literal["P0", "P1", "P2"]
    coverage_status: Literal["indexed", "partial", "planned"]
    must_use_official_sources: bool
    subtopics: list[str]


class KnowledgeCatalogCategory(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    priority: Literal["P0", "P1", "P2"]
    coverage_status: Literal["indexed", "partial", "planned"]
    must_use_official_sources: bool
    current_kb_files: list[str]
    recommended_authorities: list[str]
    recommended_material_families: list[str]
    topics: list[KnowledgeCatalogTopic]


class KnowledgeCatalogResponse(BaseModel):
    catalog_version: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    category_count: int = Field(ge=0)
    topic_count: int = Field(ge=0)
    coverage_basis: dict[str, Union[str, int]]
    coverage_summary: KnowledgeCatalogCoverageSummary
    disclaimer: str = Field(min_length=1)
    roadmap_notice: str = Field(min_length=1)
    categories: list[KnowledgeCatalogCategory]


CATALOG_ROADMAP_NOTICE = (
    "本目录是港航知识采集、核验与持续扩充的覆盖路线图，不代表目录所列资料已经全部入库。"
    "indexed 仅表示当前存在可检索资料；涉及法规、安全、海关、航海与生产控制的结论仍须核对"
    "适用辖区的现行官方文本和现场批准程序。"
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _index_time(path: Path) -> datetime:
    timestamp = path.stat().st_mtime if path.exists() else 0
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _load_knowledge_catalog(path: Path) -> KnowledgeCatalogResponse:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("catalog root must be an object")
    payload = KnowledgeCatalogResponse.model_validate(
        {**raw, "roadmap_notice": CATALOG_ROADMAP_NOTICE}
    )
    actual_category_count = len(payload.categories)
    actual_topic_count = sum(len(category.topics) for category in payload.categories)
    if payload.category_count != actual_category_count:
        raise ValueError("category count does not match catalog contents")
    if payload.topic_count != actual_topic_count:
        raise ValueError("topic count does not match catalog contents")
    summary = payload.coverage_summary
    if (
        summary.categories.indexed
        + summary.categories.partial
        + summary.categories.planned
        != actual_category_count
    ):
        raise ValueError("category coverage summary does not match catalog contents")
    if (
        summary.topics.indexed
        + summary.topics.partial
        + summary.topics.planned
        != actual_topic_count
    ):
        raise ValueError("topic coverage summary does not match catalog contents")
    return payload


def _chunks_by_source(chunks: list[KnowledgeChunk]) -> dict[str, list[KnowledgeChunk]]:
    grouped: dict[str, list[KnowledgeChunk]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.source, []).append(chunk)
    return grouped


def get_knowledge_status(chunks: Optional[list[KnowledgeChunk]] = None) -> KnowledgeStatus:
    loaded = chunks if chunks is not None else load_index()
    grouped = _chunks_by_source(loaded)
    registry = load_source_registry(SOURCE_REGISTRY_PATH)
    qualities = Counter(
        registry.get(source_id).source_quality
        for source_id in grouped
    )
    official_sources = {
        source_id
        for source_id in grouped
        if registry.get(source_id).official
        and registry.get(source_id).source_quality == "official_verified"
    }
    unregistered = sum(
        registry.get(source_id).provenance_type == "unregistered"
        for source_id in grouped
    )
    scopes = Counter(registry.get(source_id).content_scope for source_id in grouped)
    review_statuses = Counter(
        registry.get(source_id).review_status
        for source_id in official_sources
    )
    jurisdiction_documents: Counter[str] = Counter()
    for source_id in grouped:
        jurisdiction_documents.update(registry.get(source_id).jurisdictions)
    return KnowledgeStatus(
        status="ready" if loaded and not unregistered else "attention",
        document_count=len(grouped),
        chunk_count=len(loaded),
        official_verified_documents=len(official_sources),
        official_verified_chunks=sum(
            len(grouped[source_id]) for source_id in official_sources
        ),
        official_summary_documents=(
            scopes.get("official_summary", 0)
            + scopes.get("publisher_guidance", 0)
        ),
        official_full_text_documents=(
            scopes.get("official_full_text", 0)
            + scopes.get("official_excerpt", 0)
        ),
        official_locator_documents=(
            scopes.get("official_directory", 0)
            + scopes.get("standard_catalog_metadata", 0)
            + scopes.get("publisher_catalog_metadata", 0)
        ),
        internal_curated_documents=qualities.get("internal_curated", 0),
        unregistered_documents=unregistered,
        review_current_documents=review_statuses.get("current", 0),
        review_due_documents=review_statuses.get("review_due", 0),
        review_date_missing_documents=review_statuses.get("review_date_missing", 0),
        jurisdiction_documents=dict(sorted(jurisdiction_documents.items())),
        registry_version=registry.registry_version,
        index_sha256=_sha256_file(INDEX_PATH),
        index_built_at=_index_time(INDEX_PATH),
        notice=(
            "专业模式默认严格证据检索。官方摘要、目录定位、授权全文/摘录与内部整理资料分级展示；"
            "官方发布页摘要不等于法规全文，证据不足时拒绝生成专业事实。"
        ),
    )


@router.get("/status", response_model=KnowledgeStatus)
def knowledge_status() -> KnowledgeStatus:
    return get_knowledge_status()


@router.get("/catalog", response_model=KnowledgeCatalogResponse)
def knowledge_catalog() -> KnowledgeCatalogResponse:
    try:
        return _load_knowledge_catalog(KNOWLEDGE_CATALOG_PATH)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="港航专业目录暂不可用：目录文件尚未部署。",
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail="港航专业目录暂不可用：目录数据未通过完整性校验。",
        ) from exc


@router.get("/authority-coverage", response_model=dict[str, Any])
def authority_coverage() -> dict[str, Any]:
    try:
        payload = json.loads(AUTHORITY_COVERAGE_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("authority coverage root must be an object")
        return payload
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="权威来源覆盖矩阵尚未部署。") from exc
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="权威来源覆盖矩阵未通过完整性校验。") from exc


@router.get("/sources", response_model=list[KnowledgeSourceItem])
def knowledge_sources(
    official_only: bool = Query(False),
    verification_status: Optional[str] = Query(None),
) -> list[KnowledgeSourceItem]:
    chunks = load_index()
    grouped = _chunks_by_source(chunks)
    registry = load_source_registry(SOURCE_REGISTRY_PATH)
    items: list[KnowledgeSourceItem] = []
    for source_id in sorted(grouped):
        provenance: SourceProvenance = registry.get(source_id)
        if official_only and not provenance.official:
            continue
        if verification_status and provenance.verification_status != verification_status:
            continue
        source_chunks = grouped[source_id]
        items.append(
            KnowledgeSourceItem(
                source_id=source_id,
                display_name=provenance.display_name,
                institution=provenance.institution,
                source_url=provenance.source_url,
                version=provenance.version,
                provenance_type=provenance.provenance_type,
                official=provenance.official,
                verification_status=provenance.verification_status,
                source_quality=provenance.source_quality,
                license=provenance.license,
                notes=provenance.notes,
                jurisdictions=list(provenance.jurisdictions),
                content_scope=provenance.content_scope,
                legal_force=provenance.legal_force,
                effective_from=provenance.effective_from,
                effective_to=provenance.effective_to,
                last_verified_at=provenance.last_verified_at,
                review_due_at=provenance.review_due_at,
                review_status=provenance.review_status,
                update_frequency=provenance.update_frequency,
                chunk_count=len(source_chunks),
                document_checksum_sha256=source_chunks[0].document_hash or None,
            )
        )
    return items


@router.post("/search", response_model=KnowledgeSearchResponse)
def search_knowledge(payload: KnowledgeSearchRequest) -> KnowledgeSearchResponse:
    knowledge_base = get_shared_knowledge_base()
    inferred_jurisdictions = detect_jurisdictions(payload.query)
    raw_hits = knowledge_base.search(
        payload.query,
        top_k=min(payload.top_k * 4, 100),
        official_only=payload.official_only,
        source_quality=payload.source_quality,
        institution=payload.institution,
        jurisdictions=(
            (payload.jurisdiction,)
            if payload.jurisdiction
            else inferred_jurisdictions or None
        ),
        content_scopes=(payload.content_scope,) if payload.content_scope else None,
        current_only=payload.current_only,
    )
    raw_hits = raw_hits[: payload.top_k]
    hits: list[KnowledgeSearchHit] = []
    for hit in raw_hits:
        provenance = hit.chunk.provenance
        if hit.coverage < payload.min_coverage:
            qualified = False
            qualification_reason = "coverage_below_threshold"
        elif provenance.provenance_type == "unregistered" or provenance.verification_status == "unregistered":
            qualified = False
            qualification_reason = "source_unregistered"
        elif not hit.chunk.content_hash or not hit.chunk.document_hash:
            qualified = False
            qualification_reason = "checksum_missing"
        elif payload.official_only and not (
            provenance.official and provenance.source_quality == "official_verified"
        ):
            qualified = False
            qualification_reason = "official_source_required"
        elif payload.current_only and provenance.review_status in {"review_due", "review_date_invalid"}:
            qualified = False
            qualification_reason = "source_review_due"
        else:
            qualified = True
            qualification_reason = "qualified"
        hits.append(KnowledgeSearchHit(
            id=hit.chunk.id,
            source=hit.chunk.source,
            title=hit.chunk.title,
            snippet=hit.snippet,
            score=hit.score,
            lexical_score=hit.lexical_score,
            semantic_score=hit.semantic_score,
            rerank_score=hit.rerank_score,
            retrieval_method=hit.retrieval_method,
            coverage=hit.coverage,
            matched_terms=hit.matched_terms,
            qualified=qualified,
            qualification_reason=qualification_reason,
            source_url=hit.chunk.provenance.source_url,
            institution=hit.chunk.provenance.institution,
            version=hit.chunk.provenance.version,
            official=hit.chunk.provenance.official,
            verification_status=hit.chunk.provenance.verification_status,
            source_quality=hit.chunk.provenance.source_quality,
            jurisdictions=list(provenance.jurisdictions),
            content_scope=provenance.content_scope,
            legal_force=provenance.legal_force,
            effective_from=provenance.effective_from,
            effective_to=provenance.effective_to,
            last_verified_at=provenance.last_verified_at,
            review_due_at=provenance.review_due_at,
            review_status=provenance.review_status,
            document_checksum_sha256=hit.chunk.document_hash or None,
            chunk_checksum_sha256=hit.chunk.content_hash or None,
        ))
    grounded = any(hit.qualified for hit in hits)
    return KnowledgeSearchResponse(
        query=payload.query,
        grounded=grounded,
        result_count=len(hits),
        official_result_count=sum(hit.official for hit in hits),
        min_coverage=payload.min_coverage,
        notice=(
            "仅返回已建立哈希和来源登记的索引命中；摘要/目录不能替代正式全文，"
            "grounded=false 表示没有达到当前覆盖与来源条件。"
        ),
        hits=hits,
    )
