from __future__ import annotations

import re
import unicodedata

from app.models import AnswerVerification, ChatResponse, ClaimSupport, Evidence


_CITATION = re.compile(r"\[E(\d+)\]")
_LIST_PREFIX = re.compile(
    r"^\s*(?:"
    r"[-*•]+\s*|"
    r"(?:\(?\d{1,3}\)?|[一二三四五六七八九十]+)"
    r"(?:[、:：)）]\s*|\.\s+)"
    r")"
)
_ENGLISH_TOKEN = re.compile(r"[a-z][a-z0-9_/-]{1,}")
_CJK_BLOCK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]{2,}")
_DATE_TOKEN = re.compile(
    r"(?<!\d)((?:19|20)\d{2})\s*(?:年|[-/.])\s*"
    r"(\d{1,2})\s*(?:月|[-/.])\s*(\d{1,2})\s*日?"
)
_NUMBER_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(\d+(?:,\d{3})*(?:\.\d+)?)"
    r"\s*"
    r"(%|％|小时|分钟|秒|天|日|吨|千克|公斤|kg|米|公里|海里|节|"
    r"teu|kw|mw|元|美元|usd|tco2e|艘|名|条|项|次|个)?",
    re.IGNORECASE,
)
_ALIGNMENT_THRESHOLD = 0.30
_NON_FACTUAL_FOLLOWUP = re.compile(
    r"^(?:若|如|如果)(?:还)?需(?:要)?进一步"
    r"(?:细化|确认|分析|查询|协助|说明)?"
    r"[，,:：]?(?:请|可|需)?(?:补充|提供)"
)
_TERM_NOISE = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "into",
    "current",
    "official",
    "source",
    "evidence",
    "answer",
    "information",
    "根据",
    "当前",
    "索引",
    "可以",
    "需要",
    "必须",
    "进行",
    "相关",
    "具体",
    "回答",
    "证据",
    "来源",
    "官方",
    "规则",
    "规定",
    "要求",
    "信息",
    "内容",
    "结论",
    "本地",
    "适用",
}
_SKIP_PREFIXES = (
    "身份信息：",
    "能力说明：",
    "日常建议：",
    "港航岗位影响与安排：",
    "证据边界：",
    "核验与处置建议：",
    "证据锁定结论：",
    "生成式综合分析：",
    "生成式综合分析（关键事实以索引结论为准）：",
    "模型综合建议（需人工复核）：",
    "生成安全说明：",
    "来源状态：",
    "适用日期：",
    "根据当前索引，我能确认的重点是：",
    "我核对的索引依据",
    "当前证据没有覆盖",
    "上述片段没有覆盖",
    "请补充",
    "下方证据仅用于定位",
    "当前索引未找到",
    "当前只找到",
    "当前知识问答没有",
    "要回答这个问题",
    "在真实接口返回前",
)


def _claim_text(claim: str) -> str:
    text = _CITATION.sub("", claim)
    text = _LIST_PREFIX.sub("", text)
    return text.strip()


def _normalized(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^a-z0-9\u3400-\u4dbf\u4e00-\u9fff]+", "", value)


def _terms(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKC", text).casefold()
    terms = {
        token
        for token in _ENGLISH_TOKEN.findall(folded)
        if token not in _TERM_NOISE
    }
    for block in _CJK_BLOCK.findall(folded):
        for size in (2, 3, 4):
            terms.update(
                block[index : index + size]
                for index in range(max(0, len(block) - size + 1))
                if block[index : index + size] not in _TERM_NOISE
            )
    return terms


def _numeric_tokens(text: str) -> list[str]:
    value = unicodedata.normalize("NFKC", text).casefold()
    tokens: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for match in _DATE_TOKEN.finditer(value):
        year, month, day = match.groups()
        tokens.append(
            (
                match.start(),
                match.end(),
                f"date:{int(year):04d}-{int(month):02d}-{int(day):02d}",
            )
        )
        occupied.append(match.span())
    for match in _NUMBER_TOKEN.finditer(value):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        number, unit = match.groups()
        canonical_unit = (unit or "").replace("％", "%").casefold()
        tokens.append(
            (
                match.start(),
                match.end(),
                f"{number.replace(',', '')}{canonical_unit}",
            )
        )
    return list(dict.fromkeys(token for _, _, token in sorted(tokens)))


def _alignment(claim: str, cited: list[Evidence]) -> tuple[float, str]:
    if not cited:
        return 0.0, "none"
    claim_text = _claim_text(claim)
    evidence_text = "\n".join(
        f"{item.title}\n{item.snippet}" for item in cited
    )
    compact_claim = _normalized(claim_text)
    compact_evidence = _normalized(evidence_text)
    if compact_claim and compact_claim in compact_evidence:
        return 1.0, "exact"
    claim_terms = _terms(claim_text)
    evidence_terms = _terms(evidence_text)
    if not claim_terms:
        return 0.0, "none"
    score = len(claim_terms.intersection(evidence_terms)) / len(claim_terms)
    return round(score, 4), "lexical" if score >= _ALIGNMENT_THRESHOLD else "none"


def _claims(answer: str) -> list[str]:
    claims: list[str] = []
    in_model_advisory = False
    for raw_line in answer.splitlines():
        line = raw_line.strip().lstrip("-").strip()
        if not line or line.startswith("#") or len(line) < 8:
            continue
        if line.startswith("模型综合建议（需人工复核）："):
            in_model_advisory = True
            continue
        if in_model_advisory and not _CITATION.search(line):
            continue
        if line.startswith(_SKIP_PREFIXES) or _NON_FACTUAL_FOLLOWUP.match(line):
            continue
        claims.append(line)
    return claims


def verify_answer(
    answer: str,
    evidence: list[Evidence],
    *,
    grounded: bool,
) -> AnswerVerification:
    if not grounded:
        return AnswerVerification(status="not_applicable")
    supporting = {
        index: item
        for index, item in enumerate(evidence, start=1)
        if item.citation_role == "supporting"
    }
    rows: list[ClaimSupport] = []
    valid_citation_count = 0
    citation_count = 0
    numeric_token_count = 0
    supported_numeric_token_count = 0
    for claim in _claims(answer):
        indices = [int(value) for value in _CITATION.findall(claim)]
        citation_count += len(indices)
        valid = [index for index in indices if index in supporting]
        valid_citation_count += len(valid)
        cited = [supporting[index] for index in dict.fromkeys(valid)]
        alignment_score, alignment_basis = _alignment(claim, cited)
        numeric_tokens = _numeric_tokens(_claim_text(claim))
        cited_numeric_tokens = set(
            _numeric_tokens(
                "\n".join(
                    f"{item.title}\n{item.snippet}" for item in cited
                )
            )
        )
        unsupported_numeric_tokens = [
            token for token in numeric_tokens if token not in cited_numeric_tokens
        ]
        numeric_token_count += len(numeric_tokens)
        supported_numeric_token_count += (
            len(numeric_tokens) - len(unsupported_numeric_tokens)
        )
        citation_valid = bool(indices) and len(valid) == len(indices)
        numeric_integrity = not unsupported_numeric_tokens
        aligned = alignment_score >= _ALIGNMENT_THRESHOLD
        rows.append(
            ClaimSupport(
                claim=claim,
                citation_indices=indices,
                evidence_ids=[supporting[index].id for index in valid],
                citation_valid=citation_valid,
                alignment_score=alignment_score,
                alignment_basis=alignment_basis,
                numeric_tokens=numeric_tokens,
                unsupported_numeric_tokens=unsupported_numeric_tokens,
                numeric_integrity=numeric_integrity,
                supported=citation_valid and aligned and numeric_integrity,
            )
        )
    supported_count = sum(item.supported for item in rows)
    claim_count = len(rows)
    coverage = supported_count / claim_count if claim_count else 1.0
    validity = valid_citation_count / citation_count if citation_count else 0.0
    alignment = (
        sum(item.alignment_score for item in rows) / claim_count
        if claim_count
        else 1.0
    )
    numeric_integrity = (
        supported_numeric_token_count / numeric_token_count
        if numeric_token_count
        else 1.0
    )
    issues: list[str] = []
    if claim_count and coverage < 1.0:
        issues.append("存在未同时通过引用、词面对齐和数字完整性门禁的事实性陈述")
    if citation_count and validity < 1.0:
        issues.append("存在越界、定位型或不存在的证据编号")
    if not citation_count:
        issues.append("有依据回答缺少逐项证据编号")
    if any(
        item.citation_valid
        and item.alignment_score < _ALIGNMENT_THRESHOLD
        for item in rows
    ):
        issues.append("引用存在，但事实性陈述与所引证据的词面主题对齐不足")
    if any(item.unsupported_numeric_tokens for item in rows):
        issues.append("回答新增的数字、日期或量值未在所引证据中出现")
    return AnswerVerification(
        status=(
            "passed"
            if (
                coverage == 1.0
                and validity == 1.0
                and alignment >= _ALIGNMENT_THRESHOLD
                and numeric_integrity == 1.0
            )
            else "needs_review"
        ),
        claim_count=claim_count,
        supported_claim_count=supported_count,
        citation_coverage=round(coverage, 4),
        citation_validity=round(validity, 4),
        evidence_alignment=round(alignment, 4),
        numeric_integrity=round(numeric_integrity, 4),
        claims=rows,
        issues=issues,
        scope_notice=(
            "该校验确定性检查引用编号、主张与证据的词面对齐，以及数字、日期和量值"
            "是否出现在所引证据中；不把词面对齐冒充为语义蕴含、事实正确性或法律判断。"
            + (
                " 标注为“模型综合建议（需人工复核）”且未附证据编号的内容不计入"
                "证据支持率，不得作为已核验事实或直接生产指令。"
                if "模型综合建议（需人工复核）：" in answer
                else ""
            )
        ),
    )


def verify_response(response: ChatResponse) -> AnswerVerification:
    if response.source_quality in {"not_applicable", "sandbox_runtime"}:
        return AnswerVerification(status="not_applicable")
    return verify_answer(
        response.answer,
        response.evidence,
        grounded=response.grounded,
    )
