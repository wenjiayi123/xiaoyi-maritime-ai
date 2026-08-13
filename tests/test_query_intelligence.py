from uuid import uuid4

from fastapi.testclient import TestClient

from app.answer_verification import verify_answer, verify_response
from app.knowledge_policy import detect_jurisdictions
from app.main import _generation_history, app
from app.models import Evidence
from app.query_intelligence import build_query_analysis
from app.xiaoyi import XiaoyiAI


client = TestClient(app)


def test_independent_question_is_not_rewritten() -> None:
    plan = build_query_analysis("TOS 是什么？")

    assert plan.resolution == "independent"
    assert plan.standalone_question == "TOS 是什么？"
    assert plan.subquestions == ["TOS 是什么？"]


def test_independent_generation_omits_unrelated_chat_history() -> None:
    history = [
        {"id": "answer-new", "question": "上一题", "response": {"answer": "上一答"}},
        {"id": "answer-old", "question": "更早题", "response": {"answer": "更早答"}},
    ]
    plan = build_query_analysis("TOS 是什么？", history=history)

    assert plan.resolution == "independent"
    assert _generation_history(history, plan) == []


def test_followup_inherits_topic_but_replaces_old_jurisdiction() -> None:
    history = [
        {
            "id": "answer-previous",
            "question": "中国船舶到港报告应从哪里核验？",
            "response": {},
        }
    ]

    plan = build_query_analysis("那在新加坡呢？", history=history)

    assert plan.resolution == "history_resolved"
    assert plan.inherited_from_answer_id == "answer-previous"
    assert "船舶到港报告" in plan.standalone_question
    assert "新加坡" in plan.standalone_question
    assert "中国" not in plan.standalone_question


def test_followup_generation_keeps_only_latest_relevant_turn() -> None:
    history = [
        {
            "id": "answer-previous",
            "question": "中国船舶到港报告应从哪里核验？",
            "response": {"answer": "上一轮回答"},
        },
        {
            "id": "answer-older",
            "question": "更早的问题",
            "response": {"answer": "更早回答"},
        },
    ]
    plan = build_query_analysis("那在新加坡呢？", history=history)

    assert plan.resolution == "history_resolved"
    assert _generation_history(history, plan) == history[:1]


def test_unresolved_followup_is_marked_for_clarification() -> None:
    plan = build_query_analysis("那这个要求呢？")

    assert plan.resolution == "clarification_required"
    assert plan.requires_clarification is True
    assert plan.clarification_reason


def test_complex_question_is_decomposed_and_classified() -> None:
    plan = build_query_analysis(
        "比较欧盟和英国的港口国监督入口，同时说明2026年应核对哪个版本"
    )

    assert len(plan.subquestions) == 2
    assert {"comparison", "temporal", "regulatory", "multi_part"}.issubset(
        plan.dimensions
    )
    assert plan.complexity >= 4


def test_new_priority_jurisdictions_are_detected() -> None:
    assert detect_jurisdictions("美国 eCFR 港口规则入口") == ("US",)
    assert detect_jurisdictions("澳大利亚 AMSA Marine Orders") == ("AU",)
    assert detect_jurisdictions("鹿特丹港规定") == ("NL",)


def test_multi_part_retrieval_balances_evidence_coverage() -> None:
    plan = build_query_analysis("TOS 是什么，同时 AGV 在码头负责什么？")
    result = XiaoyiAI().ask_compound(
        plan.standalone_question,
        plan.subquestions,
        top_k=8,
    )

    assert result.grounded is True
    assert result.evidence_coverage == 1.0
    assert len(result.subquestion_support) == 2
    assert all(item.covered for item in result.subquestion_support)
    assert "TOS" in result.answer
    assert "AGV" in result.answer


def test_specific_thdi_alarm_prefers_procedure_over_generated_catalog_queries() -> None:
    result = XiaoyiAI().ask(
        "岸电 THDi 超标告警应该先检查什么？",
        mode="sop",
        top_k=5,
        strict_evidence=True,
        retrieval_queries=["岸电 THDi 超标告警应该先检查什么？"],
    )

    evidence_ids = [item.id for item in result.evidence]
    assert result.grounded is True
    assert result.evidence_coverage == 1.0
    assert len(result.subquestion_support) == 1
    assert evidence_ids[0].startswith("07_energy_carbon_shore_power:")
    assert any(
        item.startswith("35_energy_equipment_incident_playbooks:")
        for item in evidence_ids
    )
    assert not any(
        item.startswith(("00_knowledge_catalog:", "37_port_qa_form_taxonomy:"))
        for item in evidence_ids
    )
    assert "确认 THDi 数值、持续时间、船舶负载和告警等级" in result.answer


def test_official_locator_prefers_requested_directory_over_newer_documents() -> None:
    singapore = XiaoyiAI().ask(
        "新加坡船舶到港官方程序入口在哪里？",
        top_k=5,
        strict_evidence=True,
    )
    malaysia = XiaoyiAI().ask(
        "马来西亚海事立法应从哪个官方目录开始核验？",
        top_k=5,
        strict_evidence=True,
    )

    assert singapore.grounded is True
    assert singapore.evidence[0].source == (
        "101_sg_vessel_arrival_departure_procedures.md"
    )
    assert malaysia.grounded is True
    assert malaysia.evidence[0].source == "102_my_marine_legislation_directory.md"


def test_compound_question_answers_supported_part_and_refuses_clause_part() -> None:
    plan = build_query_analysis(
        "VGM 的制度目的是什么，同时 SOLAS VI/2 的条款原文是什么？"
    )
    result = XiaoyiAI().ask_compound(
        plan.standalone_question,
        plan.subquestions,
        top_k=8,
    )

    assert result.completion_status == "partial"
    assert result.refusal_reason == "partial_evidence"
    assert result.evidence_coverage == 0.5
    assert result.subquestion_support[0].covered is True
    assert result.subquestion_support[1].covered is False
    assert "不能回答具体条款" in result.answer


def test_grounded_local_answer_passes_citation_integrity_gate() -> None:
    result = XiaoyiAI().ask("TOS 是什么？")
    verification = verify_response(result)

    assert verification.status == "passed"
    assert verification.citation_coverage == 1.0
    assert verification.citation_validity == 1.0


def test_invalid_or_missing_citation_is_detected() -> None:
    evidence = [
        Evidence(
            id="chunk-1",
            source="source.md",
            title="source",
            score=1.0,
            snippet="TOS supports terminal planning.",
        )
    ]

    verification = verify_answer(
        "TOS 负责码头计划与执行协调。\n另一个结论。[E9]",
        evidence,
        grounded=True,
    )

    assert verification.status == "needs_review"
    assert verification.citation_coverage == 0.0
    assert verification.citation_validity == 0.0


def test_chat_api_resolves_followup_with_actor_scoped_history() -> None:
    session_id = f"dialogue-{uuid4().hex}"
    headers = {"X-Xiaoyi-Actor": "dialogue-tester", "X-Xiaoyi-Role": "analyst"}
    first = client.post(
        "/api/chat",
        headers=headers,
        json={
            "question": "中国船舶到港报告的官方入口在哪里？",
            "session_id": session_id,
            "top_k": 8,
        },
    )
    second = client.post(
        "/api/chat",
        headers=headers,
        json={
            "question": "那在新加坡呢？",
            "session_id": session_id,
            "top_k": 8,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    payload = second.json()
    assert payload["query_analysis"]["resolution"] == "history_resolved"
    assert "新加坡" in payload["query_analysis"]["standalone_question"]
    assert payload["jurisdictions"] == ["SG"]
    assert payload["answer_verification"]["status"] in {
        "passed",
        "not_applicable",
    }
