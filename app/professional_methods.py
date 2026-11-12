"""Read-only educational method lookup, anchored to a specific section of a verified reference note."""
import hashlib
import json
import re

from app.config import APP_NAME, DATA_DIR
from app.models import ChatResponse, Evidence, Mode
from app.retrieval import load_chunks

METHODS = {
    "电表的功率与累计电量":("gullmate_energy_measurement.md",
        (r"电表|电能表|电量|耗电|kwh|千瓦时",r"功率|负荷|kw(?!h)|千瓦(?!时)|计量|平均|每段|每一刻钟")),
    "削峰、移峰与节能的区分":("gullmate_energy_measurement.md",
        (r"削峰|移峰|错峰|峰值|需量|负荷曲线",r"节能|节电|能耗|电量|基线|产量|工时")),
    "分时电价与储能方案":("gullmate_energy_measurement.md",
        (r"分时|错峰|电价|电费|费率",r"储能|期末|峰谷|结转|计费")),
    "闸口等待的平均数、中位数和 P95":("gullmate_service_metrics.md",
        (r"闸口|过闸|卡车|等待|慢车|班次|交班|全天",r"平均|均值|中位|分位|p95|百分位|尾部|长尾")),
    "多班次完成率和人均等待":("gullmate_service_metrics.md",
        (r"集团|合并|汇总|两班|多班次|两组|规模不同",r"完成率|完成比例|比例|加权|计划量|人均")),
    "港区范围与码头范围":("gullmate_service_metrics.md",
        (r"港区|全港|挂靠|码头间",r"统计口径|范围|样本范围|可比|数据边界")),
    "旋转设备的振动、温度与状态基线":("gullmate_condition_monitoring.md",
        (r"电机|轴承|驱动|桥吊|岸桥|场桥|设备",r"振动|转速|传感器|测点|负载|温升",r"趋势|基线|工况|状态|磨损|历史|沿用")),
    "设备可用时间与维修恢复时间":("gullmate_condition_monitoring.md",
        (r"检修|维修|故障|停机|备件",r"等待|恢复|时长|工时|mttr|mtbf")),
}
EXCLUDE=re.compile(r"当前真实|现在.{0,18}(?:实际|真实|多少)|此刻|现场实测|批准.{0,12}(?:停机|复工|放行)|强制力|具体条款|法定|替我.{0,8}下发|直接执行|出具.{0,10}执法|查询.{0,12}实时",re.I)


def select_section(question: str) -> tuple[str, str] | None:
    asks_for_method = re.search(r"如何|怎样|怎么|为何|为什么|区别|能否|还能|是否可比|解释|what is|how |why ", question, re.I)
    if EXCLUDE.search(question) or not asks_for_method:
        return None
    found = []
    for title, (filename, groups) in METHODS.items():
        hits = [re.findall(pattern, question, re.I) for pattern in groups]
        if any(not matches for matches in hits):
            continue
        weight = sum(len({word.casefold() for word in matches}) for matches in hits)
        found.append((weight, title, filename))
    if not found:
        return None
    found.sort(reverse=True)
    if len(found) > 1 and found[0][0] == found[1][0] and found[0][2] != found[1][2]:
        return None
    _, title, filename = found[0]
    return title, filename


def method_answer(question: str, mode: Mode, strict_evidence: bool) -> ChatResponse | None:
    selected = select_section(question)
    if selected is None:
        return None
    title, filename = selected
    folder = DATA_DIR / "professional_methods"
    try:
        manifest = json.loads((folder / "manifest.json").read_bytes())
        if manifest.get("schema") != "gullmate-professional-methods.v1":
            return None
        hashes = manifest["files"]
        registry = folder / "registry.json"
        if hashlib.sha256(registry.read_bytes()).hexdigest() != hashes["registry.json"]:
            return None
        chunks = load_chunks(folder / "notes", registry)
        matches = [c for c in chunks if c.source == filename and c.title == title]
        if len(matches) != 1:
            return None
        chunk = matches[0]
        if (chunk.document_hash != hashes["notes/" + filename] or chunk.provenance.official
                or chunk.provenance.content_scope != "internal_curated"):
            return None
    except (OSError, ValueError, KeyError):
        return None
    provenance = chunk.provenance
    # Different sections have different primary sources. Some are internal derivations.
    reference = re.search(r"https://[^\s<>]+", chunk.text)
    evidence = Evidence(id=chunk.id, source=chunk.source, title=chunk.title, score=1.0, snippet=chunk.text,
                        source_url=reference[0].rstrip("。；，)") if reference else None,
                        institution=provenance.institution, version=provenance.version,
                        checksum_sha256=chunk.document_hash, chunk_checksum_sha256=chunk.content_hash,
                        provenance_type=provenance.provenance_type, official=False, verification_status=provenance.verification_status,
                        source_quality=provenance.source_quality, jurisdictions=list(provenance.jurisdictions),
                        legal_force=provenance.legal_force, content_scope=provenance.content_scope,
                        last_verified_at=provenance.last_verified_at, citation_role="supporting")
    return ChatResponse(app=APP_NAME, mode=mode, intent="professional_method", question=question,
                        answer=chunk.text + " [E1]", evidence=[evidence], confidence="medium", next_questions=[],
                        strict_evidence=strict_evidence, grounded=True, coverage=1.0, source_quality=provenance.source_quality,
                        evidence_requirement="registered_professional_method", completion_status="complete")
