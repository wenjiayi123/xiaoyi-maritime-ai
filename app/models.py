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
