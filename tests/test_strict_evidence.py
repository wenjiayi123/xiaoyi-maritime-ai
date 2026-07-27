import hashlib
from datetime import date

from app.models import ChatRequest
from app.retrieval import KnowledgeBase
from app.xiaoyi import XiaoyiAI


def test_strict_mode_refuses_when_index_evidence_is_insufficient() -> None:
    result = XiaoyiAI().ask("港口有没有量子传送门？")

    assert result.strict_evidence is True
    assert result.grounded is False
    assert result.coverage == 0.0
    assert result.evidence == []
    assert result.refusal_reason == "insufficient_index_evidence"
    assert "无法在严格证据模式下回答" in result.answer


def test_strict_mode_returns_auditable_index_evidence() -> None:
    result = XiaoyiAI().ask("集装箱码头 TOS 负责什么？")

    assert result.grounded is True
    assert result.refusal_reason is None
    assert result.coverage > 0
    assert result.source_quality == "internal_curated"
    assert result.evidence
    assert "仅摘录当前检索索引" in result.answer

    first = result.evidence[0]
    assert first.provenance_type == "internal_curated"
    assert first.official is False
    assert first.verification_status == "not_independently_verified"
    assert first.institution == "小懿AI项目内部资料整理"
    assert first.source_url is None
    assert first.version in {"unversioned", "internal-2026-07-11"}
    assert first.checksum_sha256 and len(first.checksum_sha256) == 64
    assert first.chunk_checksum_sha256 and len(first.chunk_checksum_sha256) == 64


def test_index_records_match_content_hashes() -> None:
    chunks = KnowledgeBase().chunks
    assert chunks
    for chunk in chunks:
        expected = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        assert chunk.content_hash == expected
        assert len(chunk.document_hash) == 64


def test_legacy_request_payload_remains_compatible() -> None:
    request = ChatRequest.model_validate({"question": "TOS 是什么？"})

    assert request.mode == "expert"
    assert request.top_k == 5
    assert request.strict_evidence is True


def test_smalltalk_remains_available_in_strict_mode() -> None:
    result = XiaoyiAI().ask("你好")

    assert result.intent == "greeting"
    assert result.refusal_reason is None
    assert result.source_quality == "not_applicable"
    assert "你好" in result.answer


def test_regulatory_question_requires_official_source() -> None:
    result = XiaoyiAI().ask("MARPOL 的具体油类排放限值是什么？")

    assert result.grounded is False
    assert result.refusal_reason == "official_full_text_required"
    assert result.evidence
    assert all(item.citation_role == "locator_only" for item in result.evidence)
    assert all(item.content_scope != "official_full_text" for item in result.evidence)


def test_official_maritime_single_window_source_can_ground_answer() -> None:
    result = XiaoyiAI().ask("IMO 海事单一窗口从哪一年起强制实施？", top_k=8)

    assert result.grounded is True
    assert result.source_quality == "official_verified"
    assert result.evidence
    assert all(item.official for item in result.evidence)
    assert all(item.source_url for item in result.evidence)


def test_shore_power_safety_procedure_uses_new_official_regulation_index() -> None:
    result = XiaoyiAI().ask("岸电安全操作规程有哪些？", top_k=10)

    assert result.grounded is True
    assert any(item.source == "64_cn_port_ship_shore_power_rules.md" for item in result.evidence)
    assert any(item.official for item in result.evidence)
    assert "接电前" in result.answer
    assert "异常" in result.answer


def test_identity_uses_live_knowledge_inventory_and_end_to_end_positioning() -> None:
    result = XiaoyiAI().ask("你是谁，你能干什么？")

    assert "129 份港航专业文档" in result.answer
    assert "882 个可检索知识片段" in result.answer
    assert "68 份" in result.answer
    assert "不自动等同于法规或标准全文" in result.answer
    assert "结果回写" in result.answer


def test_identity_recognizes_origin_wording() -> None:
    result = XiaoyiAI().ask("你来自哪里？")

    assert result.intent == "identity"
    assert result.refusal_reason is None
    assert "我是小懿" in result.answer
    assert "我是小懿AI" not in result.answer
    assert "由AI博士温家懿研发" in result.answer
    assert "独立研发" not in result.answer
    assert "随时可交流的港航数字同事" in result.answer


def test_identity_recognizes_developer_wording_without_hallucination() -> None:
    for question in ("谁研发的？", "谁研制了小懿？", "小懿是谁设计的？"):
        result = XiaoyiAI().ask(question)

        assert result.intent == "identity"
        assert result.refusal_reason is None
        assert "由AI博士温家懿研发" in result.answer
        assert "独立研发" not in result.answer
        assert "海贼王" not in result.answer
        assert "One Piece" not in result.answer


def test_high_risk_evidence_policy_cannot_be_disabled_by_request_flag() -> None:
    result = XiaoyiAI().ask(
        "新加坡港危险品申报时限是多少？",
        strict_evidence=False,
    )

    assert result.grounded is False
    assert result.refusal_reason == "official_full_text_required"
    assert result.evidence_requirement == "official_full_text"
    assert all(item.citation_role == "locator_only" for item in result.evidence)


def test_jurisdiction_locator_question_uses_local_official_source() -> None:
    result = XiaoyiAI().ask("新加坡船舶到港官方程序入口在哪里？", top_k=8)

    assert result.grounded is True
    assert result.jurisdictions == ["SG"]
    assert any(
        item.source == "101_sg_vessel_arrival_departure_procedures.md"
        for item in result.evidence
    )


def test_specific_exemption_condition_requires_full_official_text() -> None:
    result = XiaoyiAI().ask("新加坡港引航强制豁免的具体条件是什么？")

    assert result.grounded is False
    assert result.jurisdictions == ["SG"]
    assert result.refusal_reason == "official_full_text_required"
    assert all(item.citation_role == "locator_only" for item in result.evidence)


def test_effective_date_routes_transition_to_the_correct_chinese_law_source() -> None:
    before = XiaoyiAI().ask(
        "中国生态环境法典在2026年7月是否已经生效？",
        as_of_date=date(2026, 7, 15),
        top_k=8,
    )
    effective = XiaoyiAI().ask(
        "中国生态环境法典在2026年8月15日是否生效？",
        as_of_date=date(2026, 8, 15),
        top_k=8,
    )

    assert any(
        item.source == "107_china_marine_environment_law_current.md"
        for item in before.evidence
    )
    assert any(
        item.source == "106_china_ecology_environment_code_transition.md"
        for item in effective.evidence
    )
