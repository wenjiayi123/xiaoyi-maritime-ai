from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


Mode = Literal["expert", "ops", "sop", "brief"]


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=2000, description="用户问题")
    mode: Mode = Field("expert", description="回答模式")
    top_k: int = Field(5, ge=1, le=10, description="检索证据数量")
    strict_evidence: bool = Field(
        True,
        description="专业问答是否只允许使用达到覆盖阈值的索引证据",
    )
    jurisdiction: Optional[str] = Field(
        None,
        max_length=40,
        description="可选辖区代码或名称，例如 CN、SG、MY、GLOBAL",
    )
    as_of_date: Optional[date] = Field(
        None,
        description="按哪个日期判断来源版本、有效期和复核期限",
    )
    session_id: str = Field(
        "default",
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="持久对话会话标识；生产环境按认证主体隔离",
    )


class Evidence(BaseModel):
    id: str
    source: str
    title: str
    score: float
    snippet: str
    source_url: Optional[str] = None
    institution: Optional[str] = None
    version: Optional[str] = None
    checksum_sha256: Optional[str] = None
    chunk_checksum_sha256: Optional[str] = None
    provenance_type: str = "unregistered"
    official: bool = False
    verification_status: str = "unregistered"
    source_quality: str = "unverified"
    jurisdictions: list[str] = Field(default_factory=list)
    content_scope: str = "unregistered"
    legal_force: str = "unknown"
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    last_verified_at: Optional[str] = None
    review_due_at: Optional[str] = None
    review_status: str = "unknown"
    citation_role: Literal["supporting", "locator_only"] = "supporting"


class QueryAnalysis(BaseModel):
    original_question: str
    standalone_question: str
    resolution: Literal[
        "independent",
        "history_resolved",
        "clarification_required",
    ] = "independent"
    inherited_from_answer_id: Optional[str] = None
    subquestions: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    complexity: int = Field(1, ge=1, le=5)
    requires_clarification: bool = False
    clarification_reason: Optional[str] = None


class SubquestionSupport(BaseModel):
    question: str
    covered: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    refusal_reason: Optional[str] = None


class ClaimSupport(BaseModel):
    claim: str
    citation_indices: list[int] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    citation_valid: bool = False
    alignment_score: float = Field(0.0, ge=0.0, le=1.0)
    alignment_basis: Literal["exact", "lexical", "none"] = "none"
    numeric_tokens: list[str] = Field(default_factory=list)
    unsupported_numeric_tokens: list[str] = Field(default_factory=list)
    numeric_integrity: bool = True
    supported: bool = False


class AnswerVerification(BaseModel):
    status: Literal["passed", "needs_review", "not_applicable"] = "not_applicable"
    claim_count: int = 0
    supported_claim_count: int = 0
    citation_coverage: float = Field(0.0, ge=0.0, le=1.0)
    citation_validity: float = Field(0.0, ge=0.0, le=1.0)
    evidence_alignment: float = Field(0.0, ge=0.0, le=1.0)
    numeric_integrity: float = Field(0.0, ge=0.0, le=1.0)
    advisory_checked: bool = False
    advisory_safe: bool = True
    advisory_issues: list[str] = Field(default_factory=list)
    claims: list[ClaimSupport] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    scope_notice: str = (
        "该校验确定性检查引用编号、主张与证据的词面对齐，以及数字、日期和量值"
        "是否出现在所引证据中；不把词面对齐冒充为语义蕴含、事实正确性或法律判断。"
    )


class EvidenceConflict(BaseModel):
    left_evidence_id: str
    right_evidence_id: str
    conflict_type: Literal["status_polarity", "version_divergence"]
    detail: str


class EvidenceHealth(BaseModel):
    status: Literal["healthy", "degraded", "conflict", "not_applicable"] = (
        "not_applicable"
    )
    freshness: Literal[
        "current",
        "mixed",
        "review_due",
        "unknown",
        "not_applicable",
    ] = "not_applicable"
    supporting_evidence_count: int = 0
    official_evidence_count: int = 0
    review_due_evidence_ids: list[str] = Field(default_factory=list)
    freshness_unknown_evidence_ids: list[str] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    scope_notice: str = (
        "冲突检测只识别同主题证据中的强状态极性和版本元数据分歧；"
        "未检出冲突不等于事实或法律结论已被证明。"
    )


class DecisionReadiness(BaseModel):
    status: Literal[
        "ready",
        "ready_with_review",
        "partial",
        "needs_clarification",
        "needs_live_data",
        "needs_full_text",
        "insufficient_evidence",
        "evidence_conflict",
        "sandbox_only",
        "not_applicable",
    ] = "not_applicable"
    risk_level: Literal["low", "medium", "high"] = "low"
    blockers: list[str] = Field(default_factory=list)
    next_action: str = ""
    requires_human_confirmation: bool = False
    rationale: str = ""


class ChatResponse(BaseModel):
    app: str
    mode: Mode
    intent: str
    question: str
    answer: str
    evidence: list[Evidence]
    confidence: str
    next_questions: list[str]
    strict_evidence: bool = True
    grounded: bool = False
    coverage: float = Field(0.0, ge=0.0, le=1.0)
    source_quality: str = "unverified"
    refusal_reason: Optional[str] = None
    jurisdictions: list[str] = Field(default_factory=list)
    evidence_requirement: str = "registered_index"
    requires_human_review: bool = False
    policy_notice: Optional[str] = None
    as_of_date: date = Field(default_factory=date.today)
    session_id: str = "default"
    answer_id: Optional[str] = None
    generation_provider: str = "local_rules"
    generation_model: Optional[str] = None
    generation_fallback: bool = False
    generation_notice: Optional[str] = None
    query_analysis: Optional[QueryAnalysis] = None
    subquestion_support: list[SubquestionSupport] = Field(default_factory=list)
    evidence_coverage: float = Field(0.0, ge=0.0, le=1.0)
    answer_verification: AnswerVerification = Field(default_factory=AnswerVerification)
    evidence_health: EvidenceHealth = Field(default_factory=EvidenceHealth)
    decision_readiness: DecisionReadiness = Field(default_factory=DecisionReadiness)
    completion_status: Literal["complete", "partial", "refused", "not_applicable"] = (
        "complete"
    )
