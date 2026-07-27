from __future__ import annotations

import re
from typing import Any

from app.knowledge_policy import detect_jurisdictions
from app.models import QueryAnalysis


_FOLLOWUP_PREFIXES = (
    "那",
    "那么",
    "然后",
    "还有",
    "另外",
    "这个",
    "这条",
    "该",
    "它",
    "刚才",
    "上面",
    "前面",
    "同样",
    "具体",
)
_FOLLOWUP_REFERENCES = (
    "这条规定",
    "该规定",
    "这个要求",
    "该要求",
    "这艘船",
    "这条船",
    "该船",
    "这个港口",
    "该港",
    "刚才那个",
    "前一个",
)
_JURISDICTION_PHRASES = (
    "中华人民共和国",
    "中国港口",
    "中国海事",
    "中国海关",
    "中国",
    "新加坡港",
    "新加坡",
    "马来西亚",
    "巴生港",
    "美国",
    "欧盟",
    "英国",
    "澳大利亚",
    "日本",
    "荷兰",
    "鹿特丹港",
    "Singapore",
    "Malaysia",
    "United States",
    "United Kingdom",
    "European Union",
    "Australia",
    "Japan",
    "Netherlands",
    "Rotterdam",
)
_SPLIT_PATTERN = re.compile(
    r"(?:[；;]|(?:，|,)?(?:并且|同时|以及|另外|然后|再者|还要))"
)
_JURISDICTION_NAMES = {
    "GLOBAL": "国际",
    "CN": "中国",
    "SG": "新加坡",
    "MY": "马来西亚",
    "US": "美国",
    "EU": "欧盟",
    "GB": "英国",
    "AU": "澳大利亚",
    "JP": "日本",
    "NL": "荷兰",
    "REGIONAL": "区域港口国监督",
}


def _previous_turn(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in history:
        question = str(item.get("question") or "").strip()
        if question:
            return item
    return None


def _looks_like_followup(question: str) -> bool:
    compact = question.strip()
    lowered = compact.casefold()
    return (
        compact.startswith(_FOLLOWUP_PREFIXES)
        or any(reference in compact for reference in _FOLLOWUP_REFERENCES)
        or compact in {"呢？", "呢?", "为什么？", "为什么?", "怎么做？", "怎么做?"}
        or compact.endswith(("呢？", "呢?"))
        or lowered.startswith(
            (
                "what about",
                "how about",
                "and in ",
                "what if",
                "that rule",
                "this vessel",
                "the same",
            )
        )
    )


def _strip_old_scope(question: str, current_question: str) -> str:
    scoped = question
    if detect_jurisdictions(current_question):
        for phrase in _JURISDICTION_PHRASES:
            scoped = re.sub(re.escape(phrase), "", scoped, flags=re.IGNORECASE)
        scoped = re.sub(
            r"\b(?:eCFR|USCG|EMSA|MCA|AMSA|MLIT)\b",
            "",
            scoped,
            flags=re.IGNORECASE,
        )
    if re.search(r"20\d{2}(?:年|-\d{2}-\d{2})", current_question):
        scoped = re.sub(
            r"20\d{2}(?:年(?:\d{1,2}月(?:\d{1,2}日)?)?|-\d{2}-\d{2})",
            "",
            scoped,
        )
    return re.sub(r"\s+", " ", scoped).strip(" ；;，,。？！?")


def _decompose(question: str) -> list[str]:
    parts = [part.strip(" ，,。；;") for part in _SPLIT_PATTERN.split(question)]
    parts = [part for part in parts if len(part) >= 4]
    if 1 < len(parts) <= 5:
        enriched = [parts[0]]
        prior_scopes = list(detect_jurisdictions(parts[0]))
        for part in parts[1:]:
            current_scopes = list(detect_jurisdictions(part))
            if current_scopes:
                prior_scopes = list(dict.fromkeys([*prior_scopes, *current_scopes]))
                enriched.append(part)
                continue
            if prior_scopes:
                labels = "、".join(
                    _JURISDICTION_NAMES.get(item, item) for item in prior_scopes
                )
                if part.startswith(("这两地", "两地", "双方", "各自")):
                    enriched.append(f"{labels}；{part}")
                else:
                    topic = _strip_old_scope(parts[0], part)
                    enriched.append(f"{topic}；{part}" if topic else f"{labels}；{part}")
            else:
                enriched.append(part)
        return list(dict.fromkeys(enriched))
    return [question]


def _dimensions(question: str, subquestions: list[str]) -> list[str]:
    found: list[str] = []
    if detect_jurisdictions(question):
        found.append("jurisdiction")
    if re.search(r"20\d{2}|截至|当时|现在|现行|生效|废止|过去|未来", question):
        found.append("temporal")
    if any(
        term in question.lower()
        for term in ("实时", "当前", "现在", "今天", "今日", "today", "now", "live")
    ):
        found.append("live_data")
    if any(term in question for term in ("对比", "比较", "区别", "分别", "相比")):
        found.append("comparison")
    if any(
        term in question
        for term in (
            "法规",
            "法律",
            "条例",
            "规定",
            "规则",
            "法典",
            "公约",
            "合规",
            "条款",
            "监管",
            "监督",
            "强制",
            "限值",
            "MARPOL",
            "SOLAS",
            "MSN",
            "Marine Order",
        )
    ):
        found.append("regulatory")
    if any(
        term in question
        for term in ("流程", "程序", "步骤", "怎么办", "如何处置", "SOP")
    ):
        found.append("workflow")
    if len(subquestions) > 1:
        found.append("multi_part")
    return found


def build_query_analysis(
    question: str,
    *,
    history: list[dict[str, Any]] | None = None,
) -> QueryAnalysis:
    original = question.strip()
    previous = _previous_turn(history or [])
    followup = _looks_like_followup(original)
    standalone = original
    resolution = "independent"
    inherited_answer_id = None
    requires_clarification = False
    clarification_reason = None

    if followup and previous:
        prior_topic = _strip_old_scope(str(previous["question"]), original)
        if prior_topic:
            standalone = f"{prior_topic}；追问：{original}"
            resolution = "history_resolved"
            inherited_answer_id = str(previous.get("id") or "") or None
        else:
            resolution = "clarification_required"
            requires_clarification = True
            clarification_reason = "上一轮没有可安全继承的明确业务主题"
    elif followup:
        resolution = "clarification_required"
        requires_clarification = True
        clarification_reason = "当前问题包含指代，但本会话没有可用的上一轮上下文"

    subquestions = _decompose(standalone)
    dimensions = _dimensions(standalone, subquestions)
    complexity = min(
        5,
        1
        + (1 if len(subquestions) > 1 else 0)
        + (1 if "regulatory" in dimensions else 0)
        + (1 if "temporal" in dimensions or "jurisdiction" in dimensions else 0)
        + (1 if "comparison" in dimensions or "live_data" in dimensions else 0),
    )
    return QueryAnalysis(
        original_question=original,
        standalone_question=standalone,
        resolution=resolution,
        inherited_from_answer_id=inherited_answer_id,
        subquestions=subquestions,
        dimensions=dimensions,
        complexity=complexity,
        requires_clarification=requires_clarification,
        clarification_reason=clarification_reason,
    )
