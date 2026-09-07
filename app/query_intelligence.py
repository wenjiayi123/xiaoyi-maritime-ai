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
    # Discourse markers alone do not make a new, explicitly named subject
    # dependent on the previous conversation (e.g. "另外，TOS 是什么？").
    without_transition = re.sub(r"^(?:另外|还有|那么|然后|具体|那)[，,\s]*", "", compact)
    if without_transition != compact and re.search(
        r"(?:\b[A-Za-z][A-Za-z0-9/-]{1,}\b|岸电|岸桥|场桥|闸口|堆场|集装箱|"
        r"船舶|交接班|泊位|海关|碳排|设备|船员|引航)", without_transition,
    ) and re.search(r"是什么|做什么|怎么|如何|作用|流程|区别|原因|what|how", without_transition, re.IGNORECASE) and not re.search(r"这个|该|它|上述|刚才|上面|这[艘条项]", without_transition):
        return False
    return (
        compact.startswith(_FOLLOWUP_PREFIXES)
        or any(reference in compact for reference in _FOLLOWUP_REFERENCES)
        or compact.rstrip("？?。！! ") in {"呢", "为什么", "怎么做", "怎么办", "说明一下", "同时说明一下", "详细说说", "继续"}
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


def _scope_only_followup(question: str) -> bool:
    if not detect_jurisdictions(question) and not re.search(r"20\d{2}", question):
        return False
    remaining = _strip_old_scope(question, question)
    remaining = re.sub(r"那么|如果|换成|截至|对应|入口|要求|规定|怎么样|如何|[那在呢的到时年？?。\s]", "", remaining)
    return not remaining


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
    context_topic = original

    if followup and previous:
        prior_response = previous.get("response") or {}
        prior_plan = prior_response.get("query_analysis") or {}
        # Prefer the resolved topic saved with the answer, not the raw last
        # question, which may itself only say "那在新加坡呢？".
        prior_topic = str(
            prior_plan.get("context_topic")
            or prior_plan.get("standalone_question")
            or previous["question"]
        )
        if prior_plan.get("requires_clarification"):
            prior_topic = ""
        prior_topic = _strip_old_scope(prior_topic, original)
        if prior_topic:
            standalone = f"{prior_topic}；追问：{original}"
            scopes = detect_jurisdictions(original)
            dates = re.findall(r"20\d{2}(?:年(?:\d{1,2}月(?:\d{1,2}日)?)?|-\d{2}-\d{2})?", original)
            scope_context = "、".join([*(_JURISDICTION_NAMES.get(scope, scope) for scope in scopes), *dates])
            context_topic = f"{prior_topic} {scope_context}".strip()
            if _scope_only_followup(original):
                # Replace the scope in the actual question. Appending a vague
                # "那在新加坡呢" used to dilute ranking with unrelated directory
                # chunks even though the business subject was already known.
                standalone = f"{scope_context}{prior_topic}？"
                context_topic = standalone.rstrip("？?")
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

    if requires_clarification:
        context_topic = ""
    if resolution == "history_resolved":
        # The separator we inserted is context, not a second user question.
        parts = _decompose(original)
        subquestions = [standalone] if len(parts) == 1 else [f"{prior_topic}；追问：{part}" for part in parts]
    else:
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
        context_topic=context_topic,
        resolution=resolution,
        inherited_from_answer_id=inherited_answer_id,
        subquestions=subquestions,
        dimensions=dimensions,
        complexity=complexity,
        requires_clarification=requires_clarification,
        clarification_reason=clarification_reason,
    )
