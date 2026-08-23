from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.question_universe import DOMAINS, FORMS, question_domains  # noqa: E402


OUTPUT_JSON = ROOT / "data" / "evaluation" / "port_question_universe_v1.json"
OUTPUT_MARKDOWN = ROOT / "docs" / "PORT_QUESTION_UNIVERSE.md"
KB_DIR = ROOT / "data" / "kb"


SUBJECTS = {
    "port_basics": "港口类型、功能分区与参与方",
    "shipping": "航线、船期、舱位与船公司运营",
    "vessel_port_call": "船舶到离港、泊位、引航与航道",
    "container_terminal": "集装箱装卸、堆场、闸口与水平运输",
    "special_cargo": "散杂货、液体散货、冷链、滚装与大件货",
    "customs_documents": "订舱、单证、报关、查验与放行",
    "intermodal": "海铁、公路、驳船与腹地集疏运",
    "equipment_engineering": "港口设备维护、工程、疏浚与结构设施",
    "energy_environment": "能源、碳排、岸电、环保与绿色港口",
    "safety_security": "安全、危险品、保安、消防与应急",
    "smart_port_data": "TOS、PCS、数据、接口、人工智能与网络安全",
    "commercial_legal": "港口费用、合同、客户、保险、索赔与投资",
    "people_management": "岗位、班组、交接班、培训与运营管理",
    "planning_kpi": "港口计划、调度、经营指标、预测与产能",
    "live_operations": "港口实时状态、自动动作、权限与审计边界",
}


FORM_TEMPLATES = {
    "definition": ("请解释{subject}的核心概念、适用场景与边界。", "{subject}到底是啥、有什么用？"),
    "abbreviation": ("请列出{subject}常用缩写、全称及业务含义。", "{subject}那些英文简称都啥意思？"),
    "process": ("请按时间顺序说明{subject}的标准业务流程、参与方和关键节点。", "{subject}这事具体怎么走？"),
    "role": ("请说明{subject}各参与岗位的职责边界、协同关系与确认权限。", "{subject}到底谁负责、该找谁？"),
    "comparison": ("请从对象、主体、触发条件和数据来源比较{subject}中的相近概念。", "{subject}这几个到底有啥区别？"),
    "metric": ("请解释{subject}相关指标的定义、口径和业务含义。", "{subject}这些数该怎么看？"),
    "calculation": ("请给出{subject}相关指标的计算口径、输入数据、单位和限制。", "{subject}这个数怎么算？"),
    "cause": ("请按人、机、料、法、环、数分析{subject}异常的直接原因和根因。", "{subject}怎么会这样、先查哪？"),
    "impact": ("请评估{subject}异常对安全、生产、客户、合规和成本的影响。", "{subject}出问题会牵连啥？"),
    "risk": ("请给出{subject}的风险判断条件、等级、升级阈值和人工确认边界。", "{subject}严重不、要不要停？"),
    "handling": ("请按确认、隔离、处置、恢复和复盘说明{subject}异常的处理方法。", "{subject}出问题咋办？"),
    "sop": ("请生成{subject}的适用范围、启动条件、步骤、责任人与恢复条件。", "给我一份{subject}能照着做的SOP。"),
    "decision": ("请说明是否调整{subject}方案的前置条件、收益、风险和备选方案。", "{subject}现在到底要不要调整？"),
    "priority": ("请按安全、合规、时间窗和全局影响排列{subject}事项优先级。", "{subject}这么多事先干哪个？"),
    "checklist": ("请生成{subject}在对象、数据、设备、人员、单证和记录方面的检查清单。", "{subject}要核对啥，给个清单。"),
    "evidence": ("请列出判断{subject}所需的系统数据、人工记录、外部证据和版本要求。", "判断{subject}得看哪些数据才靠谱？"),
    "interface": ("请说明{subject}涉及系统的输入输出、同步频率、权限和异常处理。", "{subject}几个系统怎么连、怎么同步？"),
    "data_quality": ("请说明{subject}数据缺失、重复、冲突或延迟时的排查和对账方法。", "{subject}数据对不上咋整？"),
    "compliance": ("请按辖区、适用日期、官方证据和审批边界分析{subject}的合规要求。", "{subject}这样干合规不、要谁批？"),
    "commercial": ("请说明{subject}相关费用的计费对象、触发条件、合同证据和争议流程。", "{subject}这钱咋算、收费对不对？"),
    "communication": ("请生成{subject}面向客户的事实、影响、动作、里程碑和更新时间说明。", "{subject}这事怎么跟客户说？"),
    "briefing": ("请将{subject}整理为包含状态、风险、动作、责任人和截止时间的简报。", "把{subject}给我说成一分钟汇报。"),
    "review": ("请基于计划与实际、偏差、根因、动作和验证指标复盘{subject}。", "{subject}事后怎么复盘、下次咋改？"),
    "forecast": ("请说明预测{subject}所需数据窗口、假设、上下界和预警触发条件。", "{subject}接下来会咋样、能提前预警不？"),
    "training": ("请为{subject}设计包含对象、目标、案例、测试和记录的培训内容。", "新人怎么学{subject}，给个培训提纲。"),
    "template": ("请生成{subject}所需字段、责任人、时间、状态和证据引用模板。", "把{subject}整理成能直接填的模板。"),
}


SOURCE_DOMAIN_PREFIXES = {
    "port_basics": {0, 1, 10, 11, 20, 37, 38, 43},
    "shipping": {2, 21, 22, 23, 55},
    "vessel_port_call": {12, 24, 33, 48, 53, 73, 101, 104, 110, 120, 127},
    "container_terminal": {3, 14, 34, 51, 52, 54, 56, 121},
    "special_cargo": {4, 28, 29, 86, 125},
    "customs_documents": {13, 30, 45, 46, 47, 57, 71, 76, 78, 93, 94, 95},
    "intermodal": {15},
    "equipment_engineering": {5, 19, 25, 58},
    "energy_environment": {7, 16, 35, 64, 65, 82, 85, 87, 106, 107, 119, 123},
    "safety_security": {8, 32, 36, 40, 44, 62, 63, 72, 77, 79, 80, 81, 83, 84, 88, 90, 91, 92, 124},
    "smart_port_data": {6, 18, 27, 41, 49, 75},
    "commercial_legal": {17, 26, 31, 42, 66, 67, 69, 74, 96, 97, 125},
    "people_management": {32, 54, 58, 59, 122, 126},
    "planning_kpi": {14, 17, 39, 43, 54, 74, 96, 97, 120, 121, 126},
    "live_operations": {41, 54, 58, 122},
}


def _source_prefix(path: Path) -> int:
    match = re.match(r"(\d+)", path.name)
    return int(match.group(1)) if match else -1


def _source_domains(path: Path, title: str) -> list[str]:
    found = question_domains(f"{path.stem} {title}")
    prefix = _source_prefix(path)
    for domain, prefixes in SOURCE_DOMAIN_PREFIXES.items():
        if prefix in prefixes and domain not in found:
            found.append(domain)
    return found or ["port_basics"]


def _split_aliases(value: str) -> list[str]:
    return [
        item.strip(" 。？?")
        for item in re.split(r"[；;]", value)
        if item.strip(" 。？?")
    ]


def _colloquialize(title: str) -> str:
    text = title.strip()
    replacements = (
        ("如何", "怎么"),
        ("为什么", "咋回事，为什么"),
        ("是什么", "是啥"),
        ("有哪些", "都有啥"),
        ("应该", "该"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    if not re.search(r"[？?]$", text):
        text += "？"
    return text


def _topic_inventory() -> list[dict[str, Any]]:
    topics: list[dict[str, Any]] = []
    for path in sorted(KB_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        matches = list(re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE))
        for index, match in enumerate(matches):
            title = match.group(1).strip()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            section = text[match.end():end]
            aliases: list[str] = []
            for alias_match in re.finditer(
                r"^(?:常见问法|等价问法)：(.+?)\s*$",
                section,
                re.MULTILINE,
            ):
                aliases.extend(_split_aliases(alias_match.group(1)))
            utterances = list(dict.fromkeys([title, *aliases, _colloquialize(title)]))
            topics.append(
                {
                    "id": f"{path.stem}:{index + 1}",
                    "source": path.name,
                    "title": title,
                    "domains": _source_domains(path, title),
                    "formal_question": title
                    if re.search(r"如何|什么|怎么|为何|是否|哪些|区别|影响|流程|职责|计算|判断", title)
                    else f"请说明{title}。",
                    "daily_question": aliases[0] if aliases else _colloquialize(title),
                    "utterances": utterances,
                    "direct_answer": "直接回答：" in section,
                }
            )
    return topics


def _matrix(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources_by_domain: dict[str, list[str]] = {
        domain.id: [] for domain in DOMAINS
    }
    for topic in topics:
        for domain in topic["domains"]:
            if domain not in sources_by_domain:
                continue
            source = topic["source"]
            if source not in sources_by_domain[domain]:
                sources_by_domain[domain].append(source)
    rows: list[dict[str, Any]] = []
    for domain in DOMAINS:
        subject = SUBJECTS[domain.id]
        for form in FORMS:
            formal_template, daily_template = FORM_TEMPLATES[form.id]
            canonical_query = f"{domain.canonical_query} {form.canonical_terms}"
            top_sources = sources_by_domain[domain.id][:5]
            rows.append(
                {
                    "id": f"{domain.id}:{form.id}",
                    "domain": domain.id,
                    "domain_label": domain.label,
                    "form": form.id,
                    "form_label": form.label,
                    "formal_question": formal_template.format(subject=subject),
                    "daily_question": daily_template.format(subject=subject),
                    "canonical_query": canonical_query,
                    "top_sources": top_sources,
                    "retrieval_ready": bool(top_sources),
                }
            )
    return rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _markdown(payload: dict[str, Any]) -> str:
    matrix = payload["matrix"]
    lines = [
        "# 小懿AI 港口问题全集与覆盖矩阵 v1",
        "",
        f"生成时间：{payload['generated_at']}",
        "",
        "## 口径",
        "",
        "自然语言问法无法被数学意义上穷尽。本清单用“15个港航业务域 × 26种问题形式”",
        "定义可治理的问题全集，共390个意图单元、780条正式/日常基准问法；同时扫描",
        f"本地知识库得到 {payload['topic_count']} 个主题、{payload['direct_answer_topic_count']} 个直接回答主题和",
        f"{payload['utterance_count']} 条显式或派生日常表达。它用于发现和阻断覆盖缺口，",
        "不代表全球港口制度、实时数据、法规全文或所有自由表达已经完整收齐。",
        "",
        "## 问题形式",
        "",
        "、".join(f"{index}. {form.label}" for index, form in enumerate(FORMS, 1)),
        "",
        "## 全量矩阵",
        "",
    ]
    for domain in DOMAINS:
        lines.extend(
            [
                f"### {domain.label}",
                "",
                "| 问题形式 | 正式问法 | 日常口吻 | 检索准备 |",
                "|---|---|---|---|",
            ]
        )
        for row in matrix:
            if row["domain"] != domain.id:
                continue
            ready = "已建立" if row["retrieval_ready"] else "待补齐"
            lines.append(
                f"| {row['form_label']} | {row['formal_question']} | "
                f"{row['daily_question']} | {ready} |"
            )
        lines.append("")
    lines.extend(
        [
            "## 机器可读清单",
            "",
            "完整主题、表达、来源及检索候选见",
            "`data/evaluation/port_question_universe_v1.json`。清单由脚本生成，",
            "知识库变更后必须重新构建并复测。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    topics = _topic_inventory()
    matrix = _matrix(topics)
    utterances = {
        utterance
        for topic in topics
        for utterance in topic["utterances"]
        if utterance
    }
    payload = {
        "schema_version": "1.0",
        "catalog_id": "xiaoyi-port-question-universe-v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope": (
            "15 business domains x 26 question forms, plus indexed topic utterances; "
            "a governed coverage universe rather than a claim that all possible language, "
            "port rules, live states, or authorized full texts are complete"
        ),
        "domain_count": len(DOMAINS),
        "form_count": len(FORMS),
        "matrix_case_count": len(matrix),
        "formal_daily_question_count": len(matrix) * 2,
        "topic_count": len(topics),
        "direct_answer_topic_count": sum(topic["direct_answer"] for topic in topics),
        "utterance_count": len(utterances),
        "matrix_retrieval_ready_count": sum(row["retrieval_ready"] for row in matrix),
        "matrix": matrix,
        "topics": topics,
        "source_hashes": {
            path.name: _sha256(path) for path in sorted(KB_DIR.glob("*.md"))
        },
    }
    OUTPUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    OUTPUT_MARKDOWN.write_text(_markdown(payload), encoding="utf-8")
    print(
        "question universe built: "
        f"{payload['matrix_case_count']} cells / "
        f"{payload['formal_daily_question_count']} formal+daily questions / "
        f"{payload['topic_count']} indexed topics / "
        f"{payload['utterance_count']} utterances"
    )
    print(f"json: {OUTPUT_JSON}")
    print(f"markdown: {OUTPUT_MARKDOWN}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
