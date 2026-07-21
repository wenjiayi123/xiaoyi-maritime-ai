from __future__ import annotations

import json
import hashlib
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import INDEX_PATH, KB_DIR, SOURCE_REGISTRY_PATH
from app.provenance import SourceProvenance, load_source_registry


DOMAIN_TERMS = [
    "港口",
    "港航",
    "港航圈",
    "知识体系",
    "知识目录",
    "知识全景",
    "航运",
    "码头",
    "泊位",
    "靠泊",
    "离泊",
    "锚地",
    "堆场",
    "闸口",
    "集装箱",
    "TEU",
    "FEU",
    "TOS",
    "EDI",
    "OCR",
    "VGM",
    "提单",
    "舱单",
    "岸桥",
    "桥吊",
    "场桥",
    "RTG",
    "RMG",
    "AGV",
    "ASC",
    "正面吊",
    "岸电",
    "冷链",
    "冷藏箱",
    "THDi",
    "碳排",
    "能耗",
    "台风",
    "危险品",
    "IMDG",
    "SOLAS",
    "MARPOL",
    "ISPS",
    "海关",
    "海事",
    "船代",
    "货代",
    "班轮",
    "干散货",
    "液体散货",
    "油轮",
    "LNG",
    "RoRo",
    "吞吐量",
    "船时效率",
    "桥吊效率",
    "泊位利用率",
    "ETA",
    "ETB",
    "ETD",
    "ATA",
    "ATB",
    "ATD",
    "VTS",
    "AIS",
    "引航",
    "拖轮",
    "靠泊",
    "离泊",
    "系泊",
    "清关",
    "报关",
    "查验",
    "放行",
    "提单",
    "舱单",
    "D/O",
    "B/L",
    "Manifest",
    "CY",
    "CFS",
    "OOG",
    "Reefer",
    "DG",
    "多式联运",
    "海铁联运",
    "驳船",
    "内陆港",
    "无水港",
    "腹地",
    "Dwell time",
    "滞港",
    "拥堵",
    "绿色港口",
    "MARPOL",
    "ECA",
    "OPS",
    "替代燃料",
    "粉尘",
    "噪声",
    "污水",
    "自动化码头",
    "数字孪生",
    "数据治理",
    "网络安全",
    "预测性维护",
    "预防性维护",
    "MTBF",
    "MTTR",
    "备件",
    "航线网络",
    "班轮运营",
    "舱位管理",
    "空箱调拨",
    "船期可靠性",
    "运价",
    "THC",
    "滞箱费",
    "滞港费",
    "租船",
    "航次租船",
    "期租",
    "光租",
    "滞期费",
    "速遣费",
    "配载",
    "稳性",
    "货损",
    "货差",
    "航海气象",
    "潮汐",
    "水深",
    "能见度",
    "航道",
    "疏浚",
    "防波堤",
    "护岸",
    "海商法",
    "租船合同",
    "共同海损",
    "海上保险",
    "P&I",
    "PCS",
    "单一窗口",
    "港口社区系统",
    "特种货",
    "超限货",
    "高价值货",
    "邮轮",
    "客运",
    "渡运",
    "保税",
    "自由贸易区",
    "综合保税区",
    "跨境电商",
    "港口费率",
    "SLA",
    "客户服务",
    "费用争议",
    "HSE",
    "作业许可",
    "交接班",
    "运营复盘",
    "船舶晚到",
    "泊位冲突",
    "船舶走锚",
    "缆绳断裂",
    "碰撞",
    "触碰码头",
    "大雾封航",
    "强风停工",
    "雷暴",
    "堆场拥堵",
    "闸口排队",
    "翻箱率",
    "岸桥故障",
    "场桥故障",
    "AGV故障",
    "OCR误识别",
    "TOS宕机",
    "TOS降级",
    "EDI异常",
    "消息队列",
    "数据不同步",
    "箱号不符",
    "封号不符",
    "VGM不符",
    "海关查验滞留",
    "放行异常",
    "退关",
    "冷藏箱高温",
    "冷藏箱断电",
    "岸电跳闸",
    "THDi超标",
    "停电",
    "储能故障",
    "火灾",
    "失火",
    "着火",
    "起火",
    "火情",
    "烟雾",
    "冒烟",
    "浓烟",
    "爆燃",
    "消防",
    "疏散",
    "油污泄漏",
    "漏油",
    "溢油",
    "水域污染",
    "围油栏",
    "危险品泄漏",
    "人员受伤",
    "有人受伤",
    "工伤",
    "急救",
    "夹伤",
    "触电",
    "摔伤",
    "车辆事故",
    "交通事故",
    "粉尘超标",
    "污水超排",
    "网络攻击",
    "账号异常",
    "接口异常",
    "问答形式",
    "概念定义",
    "术语缩写",
    "流程说明",
    "角色职责",
    "对比辨析",
    "指标解释",
    "指标计算",
    "原因分析",
    "影响评估",
    "风险判断",
    "异常处置",
    "SOP生成",
    "决策建议",
    "优先级排序",
    "检查清单",
    "数据源",
    "证据链",
    "系统接口",
    "数据质量",
    "合规审计",
    "商务费用",
    "客户沟通",
    "汇报摘要",
    "复盘改进",
    "预测预警",
    "培训说明",
    "模板生成",
    "运行简报",
    "交接班记录",
    "异常处置记录",
]

QUERY_SYNONYMS = {
    "失火": ["火灾", "火情", "消防", "烟雾", "人员疏散"],
    "着火": ["火灾", "火情", "消防", "烟雾", "人员疏散"],
    "起火": ["火灾", "火情", "消防", "烟雾", "人员疏散"],
    "火情": ["火灾", "消防", "烟雾", "人员疏散"],
    "冒火": ["火灾", "火情", "消防"],
    "冒烟": ["烟雾", "火灾", "消防", "危险品泄漏"],
    "浓烟": ["烟雾", "火灾", "消防", "人员疏散"],
    "烟": ["烟雾", "火灾", "消防"],
    "漏油": ["油污泄漏", "水域污染", "围油栏", "MARPOL"],
    "溢油": ["油污泄漏", "水域污染", "围油栏", "MARPOL"],
    "油泄漏": ["油污泄漏", "水域污染", "围油栏", "MARPOL"],
    "漏液": ["危险品泄漏", "油污泄漏", "泄漏"],
    "异味": ["危险品泄漏", "通风", "隔离"],
    "有人受伤": ["人员受伤", "工伤", "急救", "HSE"],
    "人受伤": ["人员受伤", "工伤", "急救", "HSE"],
    "伤人": ["人员受伤", "工伤", "急救", "HSE"],
    "摔伤": ["人员受伤", "工伤", "急救", "HSE"],
    "夹伤": ["人员受伤", "工伤", "急救", "HSE"],
    "触电": ["人员受伤", "工伤", "急救", "HSE", "停电"],
    "车撞": ["车辆事故", "交通事故", "人员受伤"],
    "撞车": ["车辆事故", "交通事故", "人员受伤"],
}

STOP_TERMS = {
    "什么",
    "怎么",
    "如何",
    "应该",
    "需要",
    "哪些",
    "这个",
    "那个",
    "是否",
    "可以",
    "进行",
    "问题",
    "回答",
    "介绍",
}


@dataclass
class KnowledgeChunk:
    id: str
    source: str
    title: str
    text: str
    keywords: list[str]
    content_hash: str = ""
    document_hash: str = ""
    provenance: SourceProvenance = field(
        default_factory=lambda: SourceProvenance(
            source_id="unregistered",
            display_name="unregistered",
        )
    )


@dataclass
class SearchHit:
    chunk: KnowledgeChunk
    score: float
    snippet: str
    matched_terms: list[str] = field(default_factory=list)
    coverage: float = 0.0
    lexical_score: float = 0.0
    semantic_score: float = 0.0
    rerank_score: float = 0.0
    retrieval_method: str = "hybrid_sparse_v2"


def _read_md_files(kb_dir: Path = KB_DIR) -> list[Path]:
    return sorted(kb_dir.glob("*.md"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _split_markdown(
    path: Path,
    provenance: SourceProvenance | None = None,
    document_hash: str | None = None,
) -> list[KnowledgeChunk]:
    raw = path.read_text(encoding="utf-8")
    source_provenance = provenance or SourceProvenance(
        source_id=path.name,
        display_name=path.name,
    )
    source_hash = document_hash or _sha256_file(path)
    chunks: list[KnowledgeChunk] = []
    current_title = path.stem
    current_lines: list[str] = []
    section_index = 0

    def flush() -> None:
        nonlocal section_index, current_lines
        body = "\n".join(line.strip() for line in current_lines).strip()
        if not body:
            current_lines = []
            return
        section_index += 1
        text = f"{current_title}\n{body}"
        chunks.append(
            KnowledgeChunk(
                id=f"{path.stem}:{section_index}",
                source=path.name,
                title=current_title,
                text=text,
                keywords=_extract_keywords(text),
                content_hash=_sha256_text(text),
                document_hash=source_hash,
                provenance=source_provenance,
            )
        )
        current_lines = []

    for line in raw.splitlines():
        if line.startswith("#"):
            flush()
            current_title = line.lstrip("#").strip() or path.stem
        else:
            current_lines.append(line)
    flush()
    return chunks


def _cjk_ngrams(text: str) -> set[str]:
    words: set[str] = set()
    for block in re.findall(r"[\u4e00-\u9fff]{2,12}", text):
        for size in (2, 3, 4):
            if len(block) >= size:
                words.update(block[i : i + size] for i in range(len(block) - size + 1))
    return words


def _extract_keywords(text: str) -> list[str]:
    lower = text.lower()
    terms = {term for term in DOMAIN_TERMS if term.lower() in lower}
    terms.update(re.findall(r"[a-zA-Z][a-zA-Z0-9_/-]{1,}", text))
    terms.update(term for term in _cjk_ngrams(text) if term not in STOP_TERMS)
    return sorted(terms)


def _expand_query_terms(query: str, terms: list[str]) -> list[str]:
    expanded = list(terms)
    compact = re.sub(r"[\s，。！？、,.!?]", "", query)
    for trigger, additions in QUERY_SYNONYMS.items():
        if trigger.lower() in query.lower() or trigger in compact:
            expanded.extend(additions)
    return sorted(dict.fromkeys(expanded))


def _term_weight(term: str) -> float:
    if any(term.lower() == item.lower() for item in DOMAIN_TERMS):
        return 8.0
    if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_/-]{1,}", term):
        return 6.0
    return 0.08


def _evidence_query_terms(query: str) -> list[str]:
    """Terms used to measure whether a hit actually covers the user question."""

    terms = _extract_keywords(query)
    noise = STOP_TERMS | {
        "一下",
        "一下子",
        "请问",
        "请帮",
        "帮我",
        "告诉",
        "说明",
        "分析",
        "负责",
        "是什",
        "是什么",
        "如何",
        "怎么",
    }
    meaningful = [term for term in terms if term not in noise and not term.isdigit()]
    return sorted(dict.fromkeys(meaningful))


def _coverage_weight(term: str) -> float:
    if any(term.lower() == item.lower() for item in DOMAIN_TERMS):
        return 4.0
    if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_/-]{1,}", term):
        return 3.0
    if re.fullmatch(r"[\u4e00-\u9fff]+", term):
        return 2.0 if len(term) >= 4 else 1.5 if len(term) == 3 else 1.0
    return 1.0


def _match_coverage(text: str, terms: list[str]) -> tuple[list[str], float]:
    if not terms:
        return [], 0.0
    lower = text.lower()
    matched = [term for term in terms if term.lower() in lower]
    total_weight = sum(_coverage_weight(term) for term in terms)
    matched_weight = sum(_coverage_weight(term) for term in matched)
    coverage = matched_weight / total_weight if total_weight else 0.0
    return matched, round(min(coverage, 1.0), 4)


def load_chunks(
    kb_dir: Path = KB_DIR,
    registry_path: Path | None = None,
) -> list[KnowledgeChunk]:
    paths = _read_md_files(kb_dir)
    using_default_kb = kb_dir.resolve() == KB_DIR.resolve()
    selected_registry_path = registry_path or (SOURCE_REGISTRY_PATH if using_default_kb else None)
    registry = load_source_registry(selected_registry_path) if selected_registry_path else None
    if registry and (using_default_kb or registry_path is not None):
        registry.validate_inventory({path.name for path in paths})

    chunks: list[KnowledgeChunk] = []
    for path in paths:
        provenance = registry.get(path.name) if registry else None
        chunks.extend(
            _split_markdown(
                path,
                provenance=provenance,
                document_hash=_sha256_file(path),
            )
        )
    return chunks


def build_index(
    kb_dir: Path = KB_DIR,
    index_path: Path = INDEX_PATH,
    registry_path: Path | None = None,
) -> list[KnowledgeChunk]:
    chunks = load_chunks(kb_dir, registry_path=registry_path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        [asdict(chunk) for chunk in chunks],
        ensure_ascii=False,
        indent=2,
    )
    temp_path = index_path.with_name(f".{index_path.name}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(payload, encoding="utf-8")
        temp_path.replace(index_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return chunks


def _provenance_from_payload(payload: Any, source: str) -> SourceProvenance:
    if not isinstance(payload, dict):
        return SourceProvenance(source_id=source, display_name=source)
    return SourceProvenance(
        source_id=str(payload.get("source_id") or source),
        display_name=str(payload.get("display_name") or source),
        provenance_type=str(payload.get("provenance_type") or "unregistered"),
        institution=payload.get("institution"),
        source_url=payload.get("source_url"),
        version=payload.get("version"),
        official=bool(payload.get("official", False)),
        verification_status=str(payload.get("verification_status") or "unregistered"),
        source_quality=str(payload.get("source_quality") or "unverified"),
        license=payload.get("license"),
        notes=payload.get("notes"),
        jurisdictions=tuple(payload.get("jurisdictions") or ("GLOBAL",)),
        content_scope=str(payload.get("content_scope") or "internal_curated"),
        legal_force=str(payload.get("legal_force") or "non_binding_internal"),
        effective_from=payload.get("effective_from"),
        effective_to=payload.get("effective_to"),
        last_verified_at=payload.get("last_verified_at"),
        review_due_at=payload.get("review_due_at"),
        update_frequency=payload.get("update_frequency"),
    )


def _chunk_from_payload(payload: dict[str, Any]) -> KnowledgeChunk:
    source = str(payload["source"])
    return KnowledgeChunk(
        id=str(payload["id"]),
        source=source,
        title=str(payload["title"]),
        text=str(payload["text"]),
        keywords=list(payload.get("keywords", [])),
        content_hash=str(payload.get("content_hash") or ""),
        document_hash=str(payload.get("document_hash") or ""),
        provenance=_provenance_from_payload(payload.get("provenance"), source),
    )


def _index_needs_rebuild(items: list[dict[str, Any]]) -> bool:
    if not items:
        return True
    required = {"content_hash", "document_hash", "provenance"}
    if any(not required.issubset(item) for item in items):
        return True
    for item in items:
        if item.get("content_hash") != _sha256_text(str(item.get("text", ""))):
            return True
    source_hashes = {
        path.name: _sha256_file(path)
        for path in _read_md_files(KB_DIR)
    }
    indexed_sources = {str(item.get("source")) for item in items}
    if indexed_sources != set(source_hashes):
        return True
    if any(
        source_hashes.get(str(item.get("source"))) != item.get("document_hash")
        for item in items
    ):
        return True

    registry = load_source_registry(SOURCE_REGISTRY_PATH)
    for item in items:
        source = str(item.get("source"))
        expected = json.loads(json.dumps(asdict(registry.get(source)), ensure_ascii=False))
        if item.get("provenance") != expected:
            return True
    return False


def load_index() -> list[KnowledgeChunk]:
    if not INDEX_PATH.exists():
        return build_index(KB_DIR, INDEX_PATH, SOURCE_REGISTRY_PATH)
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("chunks", [])
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        return build_index(KB_DIR, INDEX_PATH, SOURCE_REGISTRY_PATH)
    if _index_needs_rebuild(data):
        return build_index(KB_DIR, INDEX_PATH, SOURCE_REGISTRY_PATH)
    return [_chunk_from_payload(item) for item in data]


class KnowledgeBase:
    def __init__(self, chunks: list[KnowledgeChunk] | None = None) -> None:
        self.chunks = chunks if chunks is not None else load_index()
        self._search_tokens = [self._tokenize(f"{chunk.title}\n{chunk.text}") for chunk in self.chunks]
        self._document_frequencies: Counter[str] = Counter()
        for tokens in self._search_tokens:
            self._document_frequencies.update(set(tokens))
        self._average_document_length = (
            sum(len(tokens) for tokens in self._search_tokens) / len(self._search_tokens)
            if self._search_tokens else 1.0
        )

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        lower = text.lower()
        tokens = re.findall(r"[a-z][a-z0-9_/-]{1,}", lower)
        tokens.extend(term for term in _cjk_ngrams(text) if term not in STOP_TERMS)
        tokens.extend(term.lower() for term in DOMAIN_TERMS if term.lower() in lower)
        return tokens

    def _bm25(self, query_tokens: list[str], document_tokens: list[str]) -> float:
        if not query_tokens or not document_tokens:
            return 0.0
        frequencies = Counter(document_tokens)
        document_count = max(1, len(self._search_tokens))
        length = len(document_tokens)
        k1, b = 1.5, 0.75
        score = 0.0
        for term in set(query_tokens):
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            document_frequency = self._document_frequencies.get(term, 0)
            inverse = math.log(1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))
            denominator = frequency + k1 * (1 - b + b * length / max(self._average_document_length, 1.0))
            score += inverse * frequency * (k1 + 1) / denominator
        return score

    @staticmethod
    def _semantic_similarity(query: str, text: str) -> float:
        query_features = _cjk_ngrams(query) | set(re.findall(r"[a-z][a-z0-9_/-]{1,}", query.lower()))
        text_features = _cjk_ngrams(text) | set(re.findall(r"[a-z][a-z0-9_/-]{1,}", text.lower()))
        if not query_features or not text_features:
            return 0.0
        overlap = len(query_features & text_features)
        return overlap / math.sqrt(len(query_features) * len(text_features))

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        official_only: bool = False,
        source_quality: str | None = None,
        institution: str | None = None,
        jurisdictions: tuple[str, ...] | list[str] | None = None,
        content_scopes: tuple[str, ...] | list[str] | None = None,
        current_only: bool = False,
    ) -> list[SearchHit]:
        query_terms = _expand_query_terms(query, _extract_keywords(query))
        query_tokens = self._tokenize(" ".join([query, *query_terms]))
        evidence_terms = _evidence_query_terms(query)
        query_lower = query.lower()
        acronym_terms = [term for term in query_terms if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_/-]{1,}", term)]
        requested_jurisdictions = {
            str(item).strip().upper() for item in (jurisdictions or ()) if str(item).strip()
        }
        allowed_scopes = {
            str(item).strip() for item in (content_scopes or ()) if str(item).strip()
        }
        hits: list[SearchHit] = []

        for index, chunk in enumerate(self.chunks):
            if official_only and not chunk.provenance.official:
                continue
            if source_quality and chunk.provenance.source_quality != source_quality:
                continue
            if institution and institution.lower() not in str(chunk.provenance.institution or "").lower():
                continue
            source_jurisdictions = {
                item.upper() for item in (chunk.provenance.jurisdictions or ("GLOBAL",))
            }
            if (
                requested_jurisdictions
                and "GLOBAL" not in source_jurisdictions
                and not source_jurisdictions.intersection(requested_jurisdictions)
            ):
                continue
            if allowed_scopes and chunk.provenance.content_scope not in allowed_scopes:
                continue
            if current_only:
                if chunk.provenance.review_status in {"review_due", "review_date_invalid"}:
                    continue
                try:
                    if (
                        chunk.provenance.effective_from
                        and date.fromisoformat(chunk.provenance.effective_from) > date.today()
                    ):
                        continue
                    if (
                        chunk.provenance.effective_to
                        and date.fromisoformat(chunk.provenance.effective_to) < date.today()
                    ):
                        continue
                except ValueError:
                    continue
            text_lower = chunk.text.lower()
            title_lower = chunk.title.lower()
            score = 0.0

            for term in query_terms:
                term_lower = term.lower()
                weight = _term_weight(term)
                if term_lower in text_lower:
                    score += weight
                if term_lower in title_lower:
                    score += weight * 3
                    if weight >= 8.0:
                        score += 40.0
                if term in chunk.keywords:
                    score += weight * 0.5

            for term in acronym_terms:
                term_lower = term.lower()
                if term_lower in title_lower:
                    score += 80.0
                elif term_lower in text_lower:
                    score += 45.0

            if query_lower and query_lower in text_lower:
                score += 5.0

            bm25_score = self._bm25(query_tokens, self._search_tokens[index])
            semantic_score = self._semantic_similarity(query, f"{chunk.title}\n{chunk.text}")
            lexical_score = score + bm25_score * 4.0

            if lexical_score > 0 or semantic_score >= 0.055:
                matched_terms, coverage = _match_coverage(
                    f"{chunk.title}\n{chunk.text}",
                    evidence_terms,
                )
                provenance_bonus = (
                    2.5
                    if chunk.provenance.official
                    else 0.5
                    if chunk.provenance.provenance_type != "unregistered"
                    else -4.0
                )
                if chunk.provenance.content_scope in {"official_full_text", "official_excerpt"}:
                    provenance_bonus += 3.0
                elif chunk.provenance.content_scope == "official_summary":
                    provenance_bonus += 1.5
                if requested_jurisdictions and source_jurisdictions.intersection(requested_jurisdictions):
                    provenance_bonus += 4.0
                if chunk.provenance.review_status == "current":
                    provenance_bonus += 1.0
                title_bonus = sum(1 for term in evidence_terms if term.lower() in title_lower) * 2.0
                rerank_score = lexical_score + semantic_score * 35.0 + coverage * 28.0 + provenance_bonus + title_bonus
                hits.append(
                    SearchHit(
                        chunk=chunk,
                        score=round(rerank_score, 2),
                        snippet=_snippet(chunk.text, query_terms),
                        matched_terms=matched_terms,
                        coverage=coverage,
                        lexical_score=round(lexical_score, 3),
                        semantic_score=round(semantic_score, 4),
                        rerank_score=round(rerank_score, 3),
                    )
                )

        hits.sort(key=lambda item: (item.rerank_score, item.coverage, item.lexical_score), reverse=True)
        return hits[:top_k]


_SHARED_KNOWLEDGE_BASE: KnowledgeBase | None = None
_SHARED_KNOWLEDGE_SIGNATURE: tuple[tuple[str, int, int], ...] | None = None


def _knowledge_inputs_signature() -> tuple[tuple[str, int, int], ...]:
    paths = [*_read_md_files(KB_DIR), SOURCE_REGISTRY_PATH]
    signature: list[tuple[str, int, int]] = []
    for path in paths:
        if not path.exists():
            signature.append((str(path), -1, -1))
            continue
        stat = path.stat()
        signature.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def get_shared_knowledge_base() -> KnowledgeBase:
    global _SHARED_KNOWLEDGE_BASE, _SHARED_KNOWLEDGE_SIGNATURE
    current_signature = _knowledge_inputs_signature()
    if (
        _SHARED_KNOWLEDGE_BASE is None
        or _SHARED_KNOWLEDGE_SIGNATURE != current_signature
    ):
        _SHARED_KNOWLEDGE_BASE = KnowledgeBase()
        _SHARED_KNOWLEDGE_SIGNATURE = _knowledge_inputs_signature()
    return _SHARED_KNOWLEDGE_BASE


def _snippet(text: str, terms: list[str], limit: int = 180) -> str:
    clean = " ".join(text.split())
    lower = clean.lower()
    best_pos = 0
    for term in terms:
        pos = lower.find(term.lower())
        if pos >= 0:
            best_pos = max(0, pos - 40)
            break
    snippet = clean[best_pos : best_pos + limit].strip()
    return snippet + ("..." if len(clean) > best_pos + limit else "")
