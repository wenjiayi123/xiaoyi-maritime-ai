from __future__ import annotations

import re

import pytest

from app.xiaoyi import SMALLTALK_INTENTS, XiaoyiAI


SMALLTALK_CASES = [
    "你好",
    "嗨，小懿",
    "谢谢你",
    "你是谁？",
    "你能做什么？",
]


GROUNDED_DAILY_KNOWLEDGE_CASES = [
    "ETA、ETB、ETD 分别是什么意思？",
    "VGM 是什么？",
    "提单是什么？",
    "舱单是什么？",
    "提单、舱单和 VGM 有什么区别？",
    "岸桥是做什么的？",
    "AGV 在集装箱码头负责什么？",
    "TOS 是什么？",
    "船舶靠泊的一般流程是什么？",
    "集装箱从卸船到提箱要经过哪些流程？",
    "集卡进港过闸的一般流程是什么？",
    "闸口排队常见原因有哪些？",
    "港口交接班要交接哪些内容？",
    "码头发现异常后一般怎么上报？",
    "箱子在码头通常有哪些状态？",
    "What is ETA?",
    "What does VGM mean?",
    "What does a TOS do?",
    "How do I report a terminal incident?",
]


REALTIME_BOUNDARY_CASES = [
    ("今天港口忙吗？", ("TOS", "PCS", "生产系统", "港口系统")),
    ("今天有多少条船在港？", ("TOS", "PCS", "AIS", "VTS", "生产系统")),
    ("海盛轮什么时候靠泊？", ("TOS", "AIS", "VTS", "泊位计划", "船期系统")),
    ("这条船的 ETA 是几点？", ("TOS", "AIS", "VTS", "船期系统")),
    ("我的箱子现在到哪了？", ("TOS", "PCS", "箱号", "集装箱跟踪")),
    ("箱号 MSKU1234567 到哪了？", ("TOS", "PCS", "箱号", "集装箱跟踪")),
    ("现在闸口排队多久？", ("闸口系统", "预约系统", "TOS", "生产系统")),
    ("今天吞吐量是多少？", ("TOS", "统计系统", "生产系统")),
    ("AGV-023 现在在线吗？", ("TOS", "EAM", "设备系统", "车队系统")),
    ("3号泊位岸桥现在能耗多少？", ("EMS", "能源系统", "计量系统")),
    ("Where is my container now?", ("TOS", "PCS", "container tracking", "container number")),
    ("When will this vessel berth?", ("TOS", "AIS", "VTS", "berth plan", "schedule system")),
]


SPECIFIC_REGULATION_CASES = [
    "MARPOL 的具体油类排放限值是什么？",
    "SOLAS 关于 VGM 的具体条款原文是什么？",
    "ISPS Code 要求港口设施必须执行哪一条？",
]


KNOWN_OFFICIAL_CASES = [
    "IMO 海事单一窗口从哪一年起强制实施？",
]


_DIRECT_LIVE_BOUNDARY_TERMS = (
    "无实时数据",
    "没有实时数据",
    "暂无实时数据",
    "未接入实时",
    "未连接实时",
    "无法获取当前",
    "无法查询当前",
    "无法确认当前",
    "不能查询当前",
    "当前数据不可用",
    "no real-time data",
    "no realtime data",
    "not connected to live",
    "cannot access current",
    "can't access current",
)


_CONNECTION_TERMS = (
    "需要连接",
    "需连接",
    "需要接入",
    "需接入",
    "连接港口",
    "接入港口",
    "connect to",
    "requires a connection",
)


_SYSTEM_TERMS = (
    "系统",
    "TOS",
    "PCS",
    "AIS",
    "VTS",
    "EMS",
    "EAM",
    "live system",
    "operational system",
)


_KNOWN_DEMO_SNAPSHOT_VALUES = (
    "32 艘",
    "48,256 TEU",
    "78.5%",
    "92.3%",
    "1,235.6 MWh",
    "356.7 tCO",
)


@pytest.fixture(scope="module")
def engine() -> XiaoyiAI:
    return XiaoyiAI()


def _ask_strict(engine: XiaoyiAI, question: str):
    return engine.ask(
        question,
        mode="expert",
        top_k=8,
        strict_evidence=True,
    )


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in terms)


def _has_useful_live_data_boundary(answer: str) -> bool:
    if _contains_any(answer, _DIRECT_LIVE_BOUNDARY_TERMS):
        return True
    return _contains_any(answer, _CONNECTION_TERMS) and _contains_any(
        answer, _SYSTEM_TERMS
    )


@pytest.mark.parametrize("question", SMALLTALK_CASES)
def test_daily_smalltalk_remains_natural_in_strict_mode(
    engine: XiaoyiAI, question: str
) -> None:
    result = _ask_strict(engine, question)

    assert result.intent in SMALLTALK_INTENTS
    assert result.refusal_reason is None
    assert result.grounded is False
    assert result.source_quality == "not_applicable"
    assert result.answer.strip()


@pytest.mark.parametrize("question", GROUNDED_DAILY_KNOWLEDGE_CASES)
def test_common_terms_and_workflows_are_grounded(
    engine: XiaoyiAI, question: str
) -> None:
    result = _ask_strict(engine, question)

    assert result.strict_evidence is True
    assert result.grounded is True
    assert result.refusal_reason is None
    assert result.coverage > 0
    assert result.evidence
    assert all(item.checksum_sha256 for item in result.evidence)
    assert all(item.chunk_checksum_sha256 for item in result.evidence)
    assert result.answer.strip()


@pytest.mark.parametrize("question,system_hints", REALTIME_BOUNDARY_CASES)
def test_realtime_questions_explain_the_data_boundary_without_fabrication(
    engine: XiaoyiAI,
    question: str,
    system_hints: tuple[str, ...],
) -> None:
    result = _ask_strict(engine, question)

    assert result.strict_evidence is True
    assert _has_useful_live_data_boundary(result.answer), (
        "实时问题应明确说明当前没有实时数据，或需要连接真实港口系统"
    )
    assert _contains_any(result.answer, system_hints), (
        "边界回答还应指出需要查询的系统、业务对象或标识"
    )
    assert not any(value in result.answer for value in _KNOWN_DEMO_SNAPSHOT_VALUES), (
        "严格问答不得把驾驶舱演示快照当成实时生产数据"
    )


@pytest.mark.parametrize("question", SPECIFIC_REGULATION_CASES)
def test_specific_regulatory_clauses_require_official_sources(
    engine: XiaoyiAI, question: str
) -> None:
    result = _ask_strict(engine, question)

    if result.grounded:
        assert result.refusal_reason is None
        assert result.source_quality == "official_verified"
        assert result.evidence
        assert all(item.official for item in result.evidence)
        assert all(item.source_url for item in result.evidence)
        assert all(
            item.verification_status in {"verified", "verified_official_url"}
            for item in result.evidence
        )
        assert all(
            item.content_scope in {"official_full_text", "official_excerpt"}
            for item in result.evidence
        )
    else:
        assert result.refusal_reason == "official_full_text_required"
        assert result.evidence
        assert all(item.citation_role == "locator_only" for item in result.evidence)


@pytest.mark.parametrize("question", KNOWN_OFFICIAL_CASES)
def test_known_official_facts_are_grounded_by_official_sources(
    engine: XiaoyiAI, question: str
) -> None:
    result = _ask_strict(engine, question)

    assert result.grounded is True
    assert result.refusal_reason is None
    assert result.source_quality == "official_verified"
    assert result.evidence
    assert all(item.official for item in result.evidence)
    assert all(item.source_url for item in result.evidence)


def test_benchmark_has_broad_daily_dialogue_coverage() -> None:
    all_questions = (
        SMALLTALK_CASES
        + GROUNDED_DAILY_KNOWLEDGE_CASES
        + [question for question, _ in REALTIME_BOUNDARY_CASES]
        + SPECIFIC_REGULATION_CASES
        + KNOWN_OFFICIAL_CASES
    )

    assert len(all_questions) >= 30
    assert len(all_questions) == len(set(all_questions))
    assert any(re.search(r"[A-Za-z]{3,}", question) for question in all_questions)
