from dataclasses import replace
from datetime import date

import pytest

from app.answer_verification import verify_answer
from app.knowledge_api import KnowledgeSearchRequest, search_knowledge
from app.models import Evidence
from app.model_gateway import ModelGateway
from app.models import ChatResponse
from app.provenance import SourceProvenance
from app.retrieval import KnowledgeBase, KnowledgeChunk
from app.xiaoyi import XiaoyiAI


@pytest.mark.parametrize('cited,claim,expected', [
    ('12 kW', '12 kWh', False), ('20 MWh', '20 MW', False),
    ('−18 °C', '+18 °C', False), ('-3.5 米', '3.5 米', False),
    ('不超过 6 MW', '不低于 6 MW', False), ('小于 6 MW', '不超过 6 MW', False),
    ('08:30', '30:08', False), ('0.50 元/kWh', '0.50 元/吨', False),
    ('8 mW', '8 MW', False), ('12 kWh', '12 千瓦时', True),
    ('2.50 MW', '2.5 兆瓦', True), ('至多 6 kW', '≤6 千瓦', True),
    ('−18 °C', '-18 摄氏度', True), ('08:30', '8:30', True),
    ('1,200 kWh', '1200 千瓦时', True), ('25 吨', '25 吨', True),
    ('2e3 kW', '2e4 kW', False), ('2e3 kW', '2000 千瓦', True),
    ('8 kW/s', '8 kW', False), ('5 kvar', '5 kvarh', False),
])
def test_measurement_in_cited_evidence(cited, claim, expected):
    evidence = Evidence(id='m1', source='fixture.md', title='设备运行记录', score=100,
                        snippet=f'本次设备记录的核验读数为{cited}。')
    result = verify_answer(f'本次设备记录的核验读数为{claim}。[E1]', [evidence], grounded=True)
    assert (result.status == 'passed') is expected, result.model_dump()


def source(name, start, end=None, due='2030-06-01'):
    return SourceProvenance(name, name, provenance_type='official', official=True,
                            source_quality='official_verified', verification_status='verified',
                            content_scope='official_excerpt', jurisdictions=('CN',),
                            effective_from=start, effective_to=end, review_due_at=due)


def chunk(name, provenance, text, title='岸电容量核验规定'):
    return KnowledgeChunk(name, name, title, text, ['岸电','容量','核验'], 'a'*64, 'b'*64, provenance)


@pytest.fixture
def crowded_kb():
    old = source('old', '2020-01-01', '2022-12-31')
    new = source('new', '2023-01-01', due='2024-01-01')
    rows = [chunk(f'old-{i}', old, '岸电容量核验规定。'*10 + '按旧版核验。') for i in range(35)]
    rows.append(chunk('new', new, '岸电容量核验规定，按新版进行核验。', '岸电核验'))
    rows.append(chunk('unknown', replace(new, effective_from=None, effective_to=None), '岸电容量核验规定。'))
    return KnowledgeBase(rows)


@pytest.mark.parametrize('day, expected, forbidden', [
    ('2022-12-31', 'old-0', 'new'), ('2023-01-01', 'new', 'old-0'),
    ('2023-12-31', 'new', 'old-0'),
])
def test_search_respects_day_before_result_limit(monkeypatch, crowded_kb, day, expected, forbidden):
    monkeypatch.setattr('app.knowledge_api.get_shared_knowledge_base', lambda: crowded_kb)
    request = KnowledgeSearchRequest(query='岸电容量核验规定', top_k=10, official_only=True, as_of_date=day)
    result = search_knowledge(request)
    assert any(hit.id == expected and hit.qualified for hit in result.hits)
    assert not any(hit.id == forbidden for hit in result.hits)
    assert not any(hit.id == 'unknown' and hit.qualified for hit in result.hits)
    assert result.as_of_date == date.fromisoformat(day)


def test_current_review_uses_requested_day(monkeypatch, crowded_kb):
    monkeypatch.setattr('app.knowledge_api.get_shared_knowledge_base', lambda: crowded_kb)
    def search(day):
        return search_knowledge(KnowledgeSearchRequest(query='岸电容量核验规定', top_k=10, current_only=True, as_of_date=day))
    assert any(hit.id == 'new' and hit.review_status == 'current' for hit in search('2024-01-01').hits)
    assert all(hit.id != 'new' for hit in search('2024-01-02').hits)


def test_chat_can_retrieve_valid_version_behind_35_obsolete_matches(crowded_kb):
    ai = XiaoyiAI(kb=crowded_kb)
    response = ai.ask('中国岸电容量核验规定是什么？', as_of_date=date(2023, 1, 1), top_k=1)
    assert response.grounded
    assert [item.id for item in response.evidence] == ['new']


def test_citation_does_not_borrow_quantity_from_adjacent_sentence():
    def reading(source, value):
        return Evidence(id=source, source=source, title='岸电测量记录', score=100,
                        snippet=f'{source}泊位的岸电测量为{value} kW。')
    refs = [reading('甲', 10), reading('乙', 30)]
    result = verify_answer('甲泊位的岸电测量为30 kW[E1]。乙泊位的岸电测量为10 kW[E2]。', refs, grounded=True)
    assert result.status == 'needs_review' and result.claim_count == 2
    assert all(not item.numeric_integrity for item in result.claims)


@pytest.mark.parametrize('observed,claim', [('08:30 到港。', '09:30 到港。[E1]'),
                                           ('18 摄氏度为记录温度。', '-18 摄氏度为记录温度。[E1]')])
def test_leading_clock_and_sign_are_not_list_markers(observed, claim):
    ref = Evidence(id='x',source='x',title='原始记录',score=100,snippet=observed)
    assert verify_answer(claim,[ref],grounded=True).status == 'needs_review'


def test_automatic_citation_preserves_numeric_sign_and_source_role():
    ref = Evidence(id='x',source='x',title='设备记录',score=100,snippet='本次冷藏箱实际温度为-18摄氏度。')
    response = ChatResponse(app='舷鸥',mode='expert',intent='port_knowledge',question='温度是多少？',
                            answer='',evidence=[ref],confidence='medium',next_questions=[],grounded=True)
    mismatch = '本次冷藏箱实际温度为18摄氏度。'
    assert ModelGateway._attach_exact_evidence_citation(response, mismatch) == mismatch
    assert ModelGateway._attach_exact_evidence_citation(response, ref.snippet).endswith('[E1]')
    locator = response.model_copy(update={'evidence':[ref.model_copy(update={'citation_role':'locator'})]})
    assert ModelGateway._attach_exact_evidence_citation(locator, ref.snippet) == ref.snippet
