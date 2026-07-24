from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.provenance import SourceProvenance


JURISDICTION_LABELS = {
    "GLOBAL": "国际通用框架",
    "CN": "中国",
    "SG": "新加坡",
    "MY": "马来西亚",
}

JURISDICTION_TERMS = {
    "CN": (
        "中国",
        "中华人民共和国",
        "中国港口",
        "中国海事",
        "中国海关",
        "港口危险货物安全管理规定",
        "港口和船舶岸电管理办法",
        "船舶安全监督规则",
    ),
    "SG": ("新加坡", "新加坡港", "MPA", "PSA Singapore", "Singapore"),
    "MY": (
        "马来西亚",
        "巴生港",
        "丹戎帕拉帕斯",
        "Port Klang",
        "Tanjung Pelepas",
        "Malaysia",
    ),
    "GLOBAL": ("国际规则", "国际公约", "全球", "IMO", "ILO", "IHO", "WCO", "WTO"),
}

OFFICIAL_QUERY_TERMS = (
    "法规", "标准", "规范", "强制", "合规", "海关", "海事", "监管", "公约",
    "法律", "条例", "办法", "规定", "处罚", "罚款", "危险品", "危险货物",
    "消防", "火灾", "边检", "检疫", "环保", "污染", "排放", "职业安全",
    "停航", "封航", "MARPOL", "SOLAS", "ISPS", "IMO", "IHO", "国标", "GB/", "GB ",
    "原文", "全文", "条款", "申报时限", "允许误差", "法定限值", "豁免条件",
    "官方", "法典", "通告", "规程", "生效日期", "是否生效",
)

CLAUSE_LEVEL_TERMS = (
    "原文",
    "全文",
    "逐字",
    "具体条款",
    "强制条款",
    "哪一条",
    "哪条",
    "第几条",
    "哪项条款",
    "罚款金额",
    "罚多少",
    "处罚幅度",
    "具体限值",
    "法定限值",
    "豁免条件",
    "具体条件",
    "例外条件",
    "法律责任",
    "责任上限",
    "诉讼时效",
    "申报时限",
    "允许误差",
    "误差是多少",
    "时限是多少",
    "期限是多少",
    "数值上限",
    "数值下限",
)

HUMAN_REVIEW_TERMS = (
    "合规",
    "法规",
    "标准",
    "强制",
    "处罚",
    "危险品",
    "停航",
    "停工",
    "消防",
    "应急",
    "下发",
    "执行",
    "许可",
    "失火",
    "着火",
    "起火",
    "冒烟",
    "漏油",
    "溢油",
    "人员受伤",
    "车辆事故",
)

LOCATOR_FACT_TERMS = (
    "是什么",
    "哪个版本",
    "最新版本",
    "是否现行",
    "何时发布",
    "发布时间",
    "目录",
    "入口",
    "从哪一年",
    "是否生效",
    "生效日期",
    "核验入口",
    "核对哪部",
    "应核对",
)

FULL_TEXT_SCOPES = {"official_full_text", "official_excerpt"}
SUMMARY_SCOPES = FULL_TEXT_SCOPES | {"official_summary", "publisher_guidance"}
LOCATOR_SCOPES = SUMMARY_SCOPES | {
    "official_directory",
    "standard_catalog_metadata",
    "publisher_catalog_metadata",
}


@dataclass(frozen=True)
class QueryEvidencePolicy:
    jurisdictions: tuple[str, ...]
    explicit_jurisdiction: bool
    evidence_requirement: str
    official_required: bool
    full_text_required: bool
    locator_facts_allowed: bool
    requires_human_review: bool
    as_of_date: date

    @property
    def allowed_content_scopes(self) -> set[str] | None:
        if self.full_text_required:
            return FULL_TEXT_SCOPES
        if self.official_required:
            return LOCATOR_SCOPES if self.locator_facts_allowed else SUMMARY_SCOPES
        return None

    @property
    def jurisdiction_notice(self) -> str:
        if not self.jurisdictions:
            return "未指定辖区；回答只说明证据自身适用范围，不自动外推到其他国家或港口。"
        labels = "、".join(JURISDICTION_LABELS.get(item, item) for item in self.jurisdictions)
        return f"本次按{labels}筛选证据；国际框架仍须通过当地实施法和港口制度确认。"


def _normalize_requested_jurisdiction(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    normalized = value.strip().upper()
    if normalized in JURISDICTION_LABELS:
        return (normalized,)
    for code, aliases in JURISDICTION_TERMS.items():
        if any(normalized == alias.upper() for alias in aliases):
            return (code,)
    return ()


def detect_jurisdictions(question: str) -> tuple[str, ...]:
    lowered = question.casefold()
    found = [
        code
        for code, terms in JURISDICTION_TERMS.items()
        if any(term.casefold() in lowered for term in terms)
    ]
    return tuple(dict.fromkeys(found))


def requires_full_text_evidence(question: str) -> bool:
    compact = re.sub(r"\s+", "", question)
    if re.search(r"第[一二三四五六七八九十百千0-9]+条", compact):
        return True
    if re.search(r"(?:具体|法定).{0,12}(?:限值|时限|期限|金额|幅度|误差)", compact):
        return True
    return any(term in compact for term in CLAUSE_LEVEL_TERMS)


def requires_official_evidence(question: str, intent: str | None = None) -> bool:
    upper_question = question.upper()
    return intent == "compliance" or any(
        term.upper() in upper_question for term in OFFICIAL_QUERY_TERMS
    )


def _as_of_date_from_question(question: str) -> date | None:
    patterns = (
        r"(?P<year>20\d{2})年(?P<month>0?[1-9]|1[0-2])月(?P<day>0?[1-9]|[12]\d|3[01])日",
        r"(?P<year>20\d{2})-(?P<month>0[1-9]|1[0-2])-(?P<day>0[1-9]|[12]\d|3[01])",
    )
    for pattern in patterns:
        matched = re.search(pattern, question)
        if not matched:
            continue
        try:
            return date(
                int(matched.group("year")),
                int(matched.group("month")),
                int(matched.group("day")),
            )
        except ValueError:
            return None
    return None


def build_query_policy(
    question: str,
    *,
    official_required: bool,
    requested_jurisdiction: str | None = None,
    as_of_date: date | None = None,
) -> QueryEvidencePolicy:
    requested = _normalize_requested_jurisdiction(requested_jurisdiction)
    detected = detect_jurisdictions(question)
    jurisdictions = requested or detected
    full_text_required = official_required and requires_full_text_evidence(question)
    locator_facts_allowed = any(term in question for term in LOCATOR_FACT_TERMS)
    if full_text_required:
        requirement = "official_full_text"
    elif official_required:
        requirement = "official_summary"
    else:
        requirement = "registered_index"
    return QueryEvidencePolicy(
        jurisdictions=jurisdictions,
        explicit_jurisdiction=bool(requested or detected),
        evidence_requirement=requirement,
        official_required=official_required,
        full_text_required=full_text_required,
        locator_facts_allowed=locator_facts_allowed,
        requires_human_review=official_required
        or any(term in question for term in HUMAN_REVIEW_TERMS),
        as_of_date=as_of_date or _as_of_date_from_question(question) or date.today(),
    )


def source_is_applicable(
    provenance: SourceProvenance,
    policy: QueryEvidencePolicy,
) -> bool:
    source_jurisdictions = {item.upper() for item in provenance.jurisdictions}
    if (
        policy.jurisdictions
        and "GLOBAL" not in source_jurisdictions
        and not source_jurisdictions.intersection(policy.jurisdictions)
    ):
        return False
    if policy.official_required and not (
        provenance.official and provenance.source_quality == "official_verified"
    ):
        return False
    allowed_scopes = policy.allowed_content_scopes
    if allowed_scopes is not None and provenance.content_scope not in allowed_scopes:
        return False
    if provenance.effective_from:
        try:
            if date.fromisoformat(provenance.effective_from) > policy.as_of_date:
                return False
        except ValueError:
            return False
    if provenance.effective_to:
        try:
            if date.fromisoformat(provenance.effective_to) < policy.as_of_date:
                return False
        except ValueError:
            return False
    # review_due_at controls provenance maintenance and warning state; it is not
    # a legal effective-to date. Treating it as one incorrectly suppresses an
    # otherwise applicable source after its scheduled review date.
    return True


def source_review_status(provenance: SourceProvenance, as_of_date: date) -> str:
    if not provenance.official:
        return "not_applicable"
    if not provenance.review_due_at:
        return "review_date_missing"
    try:
        return (
            "review_due"
            if date.fromisoformat(provenance.review_due_at) < as_of_date
            else "current"
        )
    except ValueError:
        return "review_date_invalid"
