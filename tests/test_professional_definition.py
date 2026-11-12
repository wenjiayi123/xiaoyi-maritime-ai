from datetime import date

from app.knowledge_policy import build_query_policy
from app.xiaoyi import XiaoyiAI


def test_definition_uses_glossary_text_and_dated_review_keeps_source_policy():
    clock=date(2026,9,7)
    engine=XiaoyiAI()
    out=engine.ask("什么是泊位计划？",strict_evidence=True,review_date=clock)
    assert out.grounded and "[E" in out.answer
    assert "靠泊" in out.answer and "离泊" in out.answer and "可能被挤压" not in out.answer
    assert engine._definition_entry("什么是泊位计划？","泊位计划：原靠泊窗口可能失效，后续船舶可能被挤压。","船期延误会影响哪些港口计划") is None
    casual=build_query_policy("什么是泊位计划？",official_required=False,review_date=clock)
    historical=build_query_policy("复核适用版本",official_required=True,as_of_date=clock)
    assert casual.as_of_date==historical.as_of_date==clock and not casual.dated_evidence_required
    assert historical.dated_evidence_required and historical.official_required
