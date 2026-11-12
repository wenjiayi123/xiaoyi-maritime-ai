from app.professional_methods import method_answer
from app.xiaoyi import XiaoyiAI


def test_public_method_excerpt_is_traceable_and_has_no_official_status():
    answer = XiaoyiAI().ask("风机测点的振动变化，如何核实轴承负载和趋势？")
    assert answer.intent == "professional_method" and answer.grounded
    ref = answer.evidence[0]
    assert ref.source == "gullmate_condition_monitoring.md"
    assert ref.source_url.startswith("https://www.energy.gov/")
    assert len(ref.checksum_sha256) == len(ref.chunk_checksum_sha256) == 64
    assert not ref.official and ref.content_scope == "internal_curated"


def test_method_cannot_substitute_for_live_or_legal_evidence():
    for question in ("电表读到的当前真实耗电量是多少？", "如何批准现场岸桥停机并根据振动趋势复工？",
                     "如何按具有强制力的条款确定卡车等待 P95 法定上限？", "直接执行分时电价对应的储能指令。"):
        assert method_answer(question,"expert",True) is None


def test_method_requires_both_business_concepts():
    assert method_answer("操作培训如何安排？","expert",True) is None
    answer = method_answer("集团如何按计划量合并多个班组的完成率？","expert",True)
    assert answer and answer.evidence[0].title == "多班次完成率和人均等待"
