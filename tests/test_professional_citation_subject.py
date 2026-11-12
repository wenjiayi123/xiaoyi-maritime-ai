from types import SimpleNamespace
from app.model_gateway import ModelGateway
from app.query_intelligence import build_query_analysis, citation_subject


def test_citation_format_does_not_change_the_search_subject():
    subject="同一货量的 TEU 如何折算？"
    for suffix in [" 请用港航知识库回答并指出依据。"," 请注明出处。"]:
        raw=subject+suffix
        assert citation_subject(raw)==(subject,True)
        plan=build_query_analysis(raw)
        assert plan.original_question==raw and plan.subquestions==[subject]
    material=subject+" 请根据2025年适用的中国法规给出结论。"
    assert citation_subject(material)==(material,False)
    claim="Which port is listed? Please cite your sources."
    assert citation_subject(claim)==("Which port is listed?",True)


def test_citation_request_preserves_missing_evidence_response():
    common={"refusal_reason":"insufficient_index_evidence","intent":"decision_priority","subquestion_support":[]}
    strict=SimpleNamespace(**common,question="现场复工依据是什么？ 请提供来源。")
    plain=SimpleNamespace(**common,question="AGV 如何工作？")
    assert ModelGateway._should_use_policy_boundary(strict)
    assert not ModelGateway._should_use_policy_boundary(plain)


def test_dependent_clause_stays_with_safety_subject():
    q="码头巡检发现刺激性气味，申请复工前还要核实哪些记录？"
    assert build_query_analysis(q).subquestions==[q]
    q="梳理岸桥的主要职责，还要说明闸口的放行条件。"
    assert len(build_query_analysis(q).subquestions)==2
