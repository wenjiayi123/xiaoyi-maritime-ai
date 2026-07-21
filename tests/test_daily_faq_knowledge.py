from pathlib import Path

import pytest

from app.config import KB_DIR, SOURCE_REGISTRY_PATH
from app.provenance import load_source_registry
from app.retrieval import KnowledgeBase, _split_markdown
from app.xiaoyi import XiaoyiAI


DAILY_FAQ_SOURCES = (
    "54_daily_port_operations_shift_qa.md",
    "55_vessel_schedule_port_call_qa.md",
    "56_container_yard_gate_handling_qa.md",
    "57_booking_document_release_qa.md",
    "58_equipment_team_handover_alert_qa.md",
    "59_bilingual_port_spoken_abbreviations_qa.md",
)


BENCHMARK_CASES = (
    ("如何做班前会简报", DAILY_FAQ_SOURCES[0], "当班目标"),
    ("值班接班先看什么", DAILY_FAQ_SOURCES[0], "上一班未闭环事项"),
    ("泊位冲突怎么协调", DAILY_FAQ_SOURCES[0], "有权计划与调度人员"),
    ("堆场拥堵先看哪些数据", DAILY_FAQ_SOURCES[0], "各箱区占用率"),
    ("客户问作业进度怎么回复", DAILY_FAQ_SOURCES[0], "标明数据时点"),
    ("多系统数据不一致怎么办", DAILY_FAQ_SOURCES[0], "统一业务对象、统计口径"),
    ("如何判断一项任务已闭环", DAILY_FAQ_SOURCES[0], "已完成动作不等于已闭环"),
    ("ETA 是什么", DAILY_FAQ_SOURCES[1], "Estimated Time of Arrival"),
    ("ETB 是什么", DAILY_FAQ_SOURCES[1], "Estimated Time of Berthing"),
    ("ETD 是什么", DAILY_FAQ_SOURCES[1], "Estimated Time of Departure"),
    ("ETA 和 ETB 有什么区别", DAILY_FAQ_SOURCES[1], "到达后可能因泊位"),
    ("船期 ETA 变了怎么更新", DAILY_FAQ_SOURCES[1], "保留原 ETA"),
    ("引航是做什么的", DAILY_FAQ_SOURCES[1], "当地航道"),
    ("拖轮数量怎么确定", DAILY_FAQ_SOURCES[1], "不能由问答系统直接决定减配"),
    ("进口箱和出口箱有什么区别", DAILY_FAQ_SOURCES[2], "由船舶卸下后"),
    ("空箱和重箱怎么区分", DAILY_FAQ_SOURCES[2], "未装载货物"),
    ("怎么查一个箱在哪里", DAILY_FAQ_SOURCES[2], "完整箱号"),
    ("什么是堆场翻箱", DAILY_FAQ_SOURCES[2], "额外移箱"),
    ("闸口预约是什么", DAILY_FAQ_SOURCES[2], "时间窗口"),
    ("OCR 箱号识别不一致怎么办", DAILY_FAQ_SOURCES[2], "暂停该车箱的自动放行"),
    ("冷藏箱进堆场要关注什么", DAILY_FAQ_SOURCES[2], "设定温度与模式"),
    ("订舱是什么", DAILY_FAQ_SOURCES[3], "获取舱位与操作安排"),
    ("提单是什么", DAILY_FAQ_SOURCES[3], "重要的运输单证"),
    ("舱单是什么", DAILY_FAQ_SOURCES[3], "货物与运输信息清单"),
    ("VGM 是什么", DAILY_FAQ_SOURCES[3], "经核实的总重量"),
    ("单证数据对账用哪些关键字段", DAILY_FAQ_SOURCES[3], "航次、订舱号、提单号"),
    ("EDI 报文在单证流程里做什么", DAILY_FAQ_SOURCES[3], "交换结构化"),
    ("单证交接班要交代什么", DAILY_FAQ_SOURCES[3], "未回执或错误报文"),
    ("设备班前检查要看什么", DAILY_FAQ_SOURCES[4], "现场点检表"),
    ("岸桥出现告警怎么办", DAILY_FAQ_SOURCES[4], "不应反复复位"),
    ("AGV 离线怎么处理", DAILY_FAQ_SOURCES[4], "确认 AGV 实际位置"),
    ("OCR 设备故障怎么降级运行", DAILY_FAQ_SOURCES[4], "转人工录入与复核"),
    ("急停按钮动作后怎么办", DAILY_FAQ_SOURCES[4], "未查明原因前不得盲目复位"),
    ("ETR 预计恢复时间怎么说", DAILY_FAQ_SOURCES[4], "未经维修负责人确认不做硬承诺"),
    ("Port 和 Terminal 有什么区别", DAILY_FAQ_SOURCES[5], "更广的港口水陆区域"),
    ("QC STS RTG RMG 分别是什么", DAILY_FAQ_SOURCES[5], "Ship-to-Shore crane"),
    ("AGV ASC 是什么", DAILY_FAQ_SOURCES[5], "Automated Guided Vehicle"),
    ("ETA ETB ETD 英文全称是什么", DAILY_FAQ_SOURCES[5], "Estimated Time of Arrival"),
    ("Vessel alongside 和 All fast 是什么意思", DAILY_FAQ_SOURCES[5], "不应自动等同于已具备开工条件"),
    ("Roger Wilco Please confirm 分别怎么用", DAILY_FAQ_SOURCES[5], "关键作业指令应复读"),
)


@pytest.fixture(scope="module")
def daily_faq_engine() -> XiaoyiAI:
    registry = load_source_registry(SOURCE_REGISTRY_PATH)
    chunks = []
    for source in DAILY_FAQ_SOURCES:
        path = KB_DIR / source
        chunks.extend(_split_markdown(path, provenance=registry.get(source)))
    return XiaoyiAI(KnowledgeBase(chunks=chunks))


def test_daily_faq_files_have_at_least_120_extractable_answers() -> None:
    question_count = 0
    answer_count = 0
    for source in DAILY_FAQ_SOURCES:
        text = (KB_DIR / source).read_text(encoding="utf-8")
        question_count += sum(line.startswith("## ") for line in text.splitlines())
        answer_count += sum(line.startswith("直接回答：") for line in text.splitlines())
    assert question_count >= 120
    assert answer_count == question_count


def test_daily_faq_sources_are_internal_and_cannot_pass_as_official() -> None:
    registry = load_source_registry(SOURCE_REGISTRY_PATH)
    for source in DAILY_FAQ_SOURCES:
        provenance = registry.get(source)
        assert provenance.provenance_type == "internal_curated"
        assert provenance.source_quality == "internal_curated"
        assert provenance.official is False
        assert provenance.source_url is None
        assert provenance.verification_status == "not_independently_verified"

    # Existing official sources retain their higher provenance tier.
    official = registry.get("53_cn_vessel_port_reporting.md")
    assert official.official is True
    assert official.source_quality == "official_verified"
    assert official.source_url


@pytest.mark.parametrize("question,expected_source,expected_phrase", BENCHMARK_CASES)
def test_daily_question_is_grounded_in_an_exact_indexed_answer(
    daily_faq_engine: XiaoyiAI,
    question: str,
    expected_source: str,
    expected_phrase: str,
) -> None:
    result = daily_faq_engine.ask(question, strict_evidence=True)

    assert result.grounded is True
    assert result.refusal_reason is None
    assert result.source_quality == "internal_curated"
    assert result.evidence
    assert result.evidence[0].source == expected_source
    assert expected_phrase in result.answer

    evidence_id = result.evidence[0].id
    evidence_chunk = next(
        chunk for chunk in daily_faq_engine.kb.chunks if chunk.id == evidence_id
    )
    direct_answer = next(
        line for line in evidence_chunk.text.splitlines() if line.startswith("直接回答：")
    )
    assert direct_answer[len("直接回答：") :] in result.answer


def test_realtime_status_question_still_fails_closed_without_live_data(
    daily_faq_engine: XiaoyiAI,
) -> None:
    result = daily_faq_engine.ask("今天港口运行正常吗", strict_evidence=True)
    assert "实时" in result.answer
    assert any(system in result.answer for system in ("TOS", "PCS", "生产系统"))
    assert not any(value in result.answer for value in ("32 艘", "48,256", "78.5%"))


def test_customs_release_question_still_requires_official_evidence(
    daily_faq_engine: XiaoyiAI,
) -> None:
    result = daily_faq_engine.ask("海关放行和码头放行一样吗", strict_evidence=True)
    assert result.grounded is False
    assert result.refusal_reason == "official_source_required"
