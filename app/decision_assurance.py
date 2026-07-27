from __future__ import annotations

import re
from itertools import combinations

from app.models import (
    ChatResponse,
    DecisionReadiness,
    Evidence,
    EvidenceConflict,
    EvidenceHealth,
    QueryAnalysis,
)


_POSITIVE_STATUS = (
    "已经生效",
    "已生效",
    "现行有效",
    "仍然有效",
    "currently in force",
    "is in force",
)
_NEGATIVE_STATUS = (
    "尚未生效",
    "未生效",
    "已经废止",
    "已废止",
    "不再有效",
    "not yet in force",
    "repealed",
)
_TOPIC_NOISE = {
    "官方",
    "来源",
    "摘要",
    "目录",
    "现行",
    "生效",
    "废止",
    "规定",
    "规则",
    "法律",
    "法规",
    "信息",
    "入口",
    "summary",
    "official",
    "directory",
}


def _topic_terms(title: str) -> set[str]:
    terms = {
        value.casefold()
        for value in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", title)
        if value.casefold() not in _TOPIC_NOISE
    }
    for block in re.findall(r"[\u4e00-\u9fff]{2,20}", title):
        for size in (2, 3, 4):
            terms.update(
                block[index : index + size]
                for index in range(max(0, len(block) - size + 1))
            )
    return {term for term in terms if term not in _TOPIC_NOISE}


def _same_topic(left: Evidence, right: Evidence) -> bool:
    left_title = re.sub(r"\W+", "", left.title).casefold()
    right_title = re.sub(r"\W+", "", right.title).casefold()
    if left_title and left_title == right_title:
        return True
    left_terms = _topic_terms(left.title)
    right_terms = _topic_terms(right.title)
    if not left_terms or not right_terms:
        return False
    overlap = len(left_terms & right_terms) / min(len(left_terms), len(right_terms))
    return overlap >= 0.55


def _same_scope(left: Evidence, right: Evidence) -> bool:
    left_scopes = set(left.jurisdictions or ["GLOBAL"])
    right_scopes = set(right.jurisdictions or ["GLOBAL"])
    return bool(
        "GLOBAL" in left_scopes
        or "GLOBAL" in right_scopes
        or left_scopes.intersection(right_scopes)
    )


def _polarity(evidence: Evidence) -> str | None:
    text = f"{evidence.title}\n{evidence.snippet}".casefold()
    positive = any(term in text for term in _POSITIVE_STATUS)
    negative = any(term in text for term in _NEGATIVE_STATUS)
    if positive == negative:
        return None
    return "positive" if positive else "negative"


def _conflicts(evidence: list[Evidence]) -> list[EvidenceConflict]:
    rows: list[EvidenceConflict] = []
    for left, right in combinations(evidence, 2):
        if not _same_scope(left, right) or not _same_topic(left, right):
            continue
        left_polarity = _polarity(left)
        right_polarity = _polarity(right)
        if left_polarity and right_polarity and left_polarity != right_polarity:
            rows.append(
                EvidenceConflict(
                    left_evidence_id=left.id,
                    right_evidence_id=right.id,
                    conflict_type="status_polarity",
                    detail="同主题、同辖区证据对生效或有效状态给出相反表述",
                )
            )
            continue
        if (
            left.source == right.source
            and left.version
            and right.version
            and left.version != right.version
            and left.checksum_sha256
            and right.checksum_sha256
            and left.checksum_sha256 != right.checksum_sha256
        ):
            rows.append(
                EvidenceConflict(
                    left_evidence_id=left.id,
                    right_evidence_id=right.id,
                    conflict_type="version_divergence",
                    detail="同一登记来源出现不同版本和不同文档哈希",
                )
            )
    return rows


def assess_evidence_health(response: ChatResponse) -> EvidenceHealth:
    supporting = [
        item for item in response.evidence if item.citation_role == "supporting"
    ]
    if not response.grounded or not supporting:
        return EvidenceHealth(status="not_applicable", freshness="not_applicable")
    due = [
        item.id
        for item in supporting
        if item.review_status in {"review_due", "review_date_invalid"}
    ]
    unknown = [
        item.id
        for item in supporting
        if item.review_status in {"unknown", "review_date_missing"}
    ]
    conflicts = _conflicts(supporting)
    if due and unknown:
        freshness = "mixed"
    elif due:
        freshness = "review_due"
    elif unknown:
        freshness = "unknown"
    elif all(item.review_status in {"current", "not_applicable"} for item in supporting):
        freshness = "current"
    else:
        freshness = "mixed"
    issues: list[str] = []
    if due:
        issues.append("存在已到复核期或复核日期异常的支持证据")
    if unknown:
        issues.append("部分支持证据缺少可判断的新鲜度元数据")
    if conflicts:
        issues.append("支持证据之间存在需人工消解的强冲突信号")
    status = "conflict" if conflicts else "degraded" if due else "healthy"
    return EvidenceHealth(
        status=status,
        freshness=freshness,
        supporting_evidence_count=len(supporting),
        official_evidence_count=sum(item.official for item in supporting),
        review_due_evidence_ids=due,
        freshness_unknown_evidence_ids=unknown,
        conflicts=conflicts,
        issues=issues,
    )


def assess_decision_readiness(
    response: ChatResponse,
    evidence_health: EvidenceHealth,
    query_analysis: QueryAnalysis | None = None,
) -> DecisionReadiness:
    if query_analysis and query_analysis.requires_clarification:
        return DecisionReadiness(
            status="needs_clarification",
            risk_level="medium",
            blockers=["ambiguous_context"],
            next_action=query_analysis.clarification_reason
            or "补充明确的业务对象、港口、辖区或时间范围。",
            rationale="当前追问无法从本会话安全继承明确主题。",
        )
    if evidence_health.status == "conflict":
        return DecisionReadiness(
            status="evidence_conflict",
            risk_level="high",
            blockers=["conflicting_supporting_evidence"],
            next_action="暂停采用冲突结论，核对原始发布页、版本和适用日期后由专业人员裁决。",
            requires_human_confirmation=True,
            rationale="同主题支持证据出现强状态或版本冲突。",
        )
    if (
        response.grounded
        and response.answer_verification.status == "needs_review"
    ):
        return DecisionReadiness(
            status="insufficient_evidence",
            risk_level="high",
            blockers=["citation_integrity_failed"],
            next_action=(
                "修正或重新生成逐项引用，确保每个事实结论只指向存在且词面对齐的"
                "支持证据，且数字、日期和量值可在证据中逐项核对。"
            ),
            requires_human_confirmation=True,
            rationale=(
                "回答后的引用、词面对齐或数字完整性校验未通过，当前文本不可进入决策链。"
            ),
        )
    refusal_actions = {
        "live_data_connection_required": (
            "needs_live_data",
            "连接经验证的只读 TOS、PCS、AIS/VTS 或对应生产系统，并核对时间戳和对象标识。",
            "verified_live_source_missing",
        ),
        "official_full_text_required": (
            "needs_full_text",
            "打开并登记当前有效的官方全文或授权摘录，再进行条款、限值、时限或罚则判断。",
            "authorized_full_text_missing",
        ),
        "business_object_required": (
            "needs_clarification",
            "补充船名/IMO、设备号、泊位、港口、辖区或时间范围后继续。",
            "business_object_missing",
        ),
    }
    if response.refusal_reason in refusal_actions:
        status, action, blocker = refusal_actions[response.refusal_reason]
        return DecisionReadiness(
            status=status,
            risk_level="high" if status in {"needs_live_data", "needs_full_text"} else "medium",
            blockers=[blocker],
            next_action=action,
            requires_human_confirmation=status
            in {"needs_live_data", "needs_full_text"},
            rationale="当前回答已按证据或数据边界失败关闭。",
        )
    if response.source_quality == "sandbox_runtime":
        return DecisionReadiness(
            status="sandbox_only",
            risk_level="medium",
            blockers=["production_data_unverified"],
            next_action="仅用于培训或流程验证；生产判断前连接并核验现场只读数据源。",
            requires_human_confirmation=True,
            rationale="当前结果来自动态运营沙箱，不是港口生产实绩。",
        )
    if response.completion_status == "partial":
        return DecisionReadiness(
            status="partial",
            risk_level="medium",
            blockers=["partial_evidence_coverage"],
            next_action="只采用已引用的子结论；为未覆盖子问题补充辖区、日期、正式来源或实时数据。",
            requires_human_confirmation=True,
            rationale="复杂问题仅有部分子问题达到证据门槛。",
        )
    if not response.grounded:
        status = (
            "not_applicable"
            if response.source_quality == "not_applicable"
            else "insufficient_evidence"
        )
        return DecisionReadiness(
            status=status,
            risk_level="low" if status == "not_applicable" else "medium",
            blockers=[] if status == "not_applicable" else ["supporting_evidence_missing"],
            next_action=""
            if status == "not_applicable"
            else "补充业务对象、辖区、日期或经登记的适用证据。",
            rationale="当前交互不需要专业证据。"
            if status == "not_applicable"
            else "当前没有足够支持证据形成可采用结论。",
        )
    if (
        response.requires_human_review
        or evidence_health.freshness in {"review_due", "mixed"}
        or (
            evidence_health.official_evidence_count > 0
            and evidence_health.freshness == "unknown"
        )
    ):
        return DecisionReadiness(
            status="ready_with_review",
            risk_level="medium",
            blockers=(
                ["source_review_due"]
                if evidence_health.freshness in {"review_due", "mixed"}
                else []
            ),
            next_action="采用前打开原始来源核对版本、适用日期和现场制度，并由责任岗位确认。",
            requires_human_confirmation=True,
            rationale="已有支持证据，但法规、合规或来源复核状态要求人工确认。",
        )
    return DecisionReadiness(
        status="ready",
        risk_level="low",
        next_action="可在当前证据登记范围内使用，并保留证据编号与审计记录。",
        rationale="支持证据、引用完整性和当前可见的新鲜度未触发阻断条件。",
    )


def assess_response(
    response: ChatResponse,
    query_analysis: QueryAnalysis | None = None,
) -> tuple[EvidenceHealth, DecisionReadiness]:
    health = assess_evidence_health(response)
    return health, assess_decision_readiness(response, health, query_analysis)
