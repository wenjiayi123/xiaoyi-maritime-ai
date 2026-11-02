"""Focused context and data acquisition order preserve the existing gates."""
import copy
import json
from itertools import combinations

import pytest

from app.harness import model


def task(goal):
    return {"goal":goal, "inputs":[], "plan":[], "results":[], "actor_role":"operator", "required_tools":["runtime.snapshot", "knowledge.search"], "allowed_tools":["runtime.snapshot", "knowledge.search"], "skills":[], "usage":{}, "budget":{"context_chars":18000,"max_output_chars":8000}}


@pytest.mark.parametrize("goal,first", [
    ("读取当前快照，结合通用岸电SOP说明风险", "knowledge.search"),
    ("先检索岸电SOP，再读取快照", "knowledge.search"),
    ("读取当前快照，再检索岸电SOP", "runtime.snapshot"),
    ("先获取快照，然后查阅岸电SOP", "runtime.snapshot"),
    ("根据当前快照的故障检索对应SOP", "runtime.snapshot"),
])
def test_independent_lookup_precedes_snapshot_but_explicit_dependencies_win(goal, first):
    t = task(goal)
    assert model.decision_tools(t) == [first]
    choices = model.wire_schema(t)["properties"]["action"]["anyOf"]
    assert {c["properties"]["kind"]["const"] for c in choices} == {"tool"}
    assert {c["properties"]["tool"]["const"] for c in choices} == {first}
    t['results'] = [{"id":"T1", "tool":first, "ok":True}]
    assert model.decision_tools(t) == [n for n in t['required_tools'] if n != first]


def test_compact_native_prompt_excludes_unavailable_distant_workflows():
    t = task("读取快照，结合通用岸电SOP")
    t['inputs'] = [{"text":"禁止调度设备", "request_id":"steer-one"}]
    messages, _ = model.context(t, [])
    assert "joint.preview" not in messages[0]['content'] and "twin.validate_public" not in messages[0]['content']
    assert len(messages[0]['content']) < 1400
    content = json.loads(messages[1]['content'])
    assert content['goal'] == t['goal'] and content['user_inputs'] == t['inputs']
    assert content['required_tools'] == t['required_tools']


def test_compaction_never_refreshes_source_clock_or_drops_free_summary_facts():
    t = task("概括告警")
    t['required_tools'] = ['runtime.snapshot']
    t['results'] = [{"id":"T1", "tool":"runtime.snapshot", "ok":True, "summary":"large" * 2000, "artifact":"T1.json", "sha256":"hash", "source_facts":{"observed_at":"2001-01-01T00:00:00Z", "must_keep":"QC-19告警"}}]
    original = copy.deepcopy(t)
    messages, _ = model.context(t, [])
    content = json.loads(messages[1]['content'])
    assert content['source_facts']['T1'] == original['results'][0]['source_facts']
    assert t == original


def test_tool_transport_omits_unused_prose_and_never_relaxes_risk_clock():
    t = task("核查风险")
    t['required_tools'] = ['runtime.snapshot', 'maritime.risk']
    t['allowed_tools'] = list(t['required_tools'])
    t['results'] = [{'id':'T1', 'tool':'runtime.snapshot', 'ok':True}]
    choices = model.wire_schema(t)['properties']['action']['anyOf']
    tool = next(c['properties'] for c in choices if c['properties']['kind']['const'] == 'tool')
    assert tool['text'] == {'const':''}
    assert tool['arguments']['properties']['max_age_seconds']['maximum'] == 120


def test_metric_query_context_retains_semantics_after_compaction():
    t = task("核对电网需量和闸口排队")
    t['required_tools'] = ['maritime.query']
    t['allowed_tools'] = list(t['required_tools'])
    messages, _ = model.context(t, [])
    assert 'dataset=metrics' in messages[0]['content']
    assert 'gate_queue=闸口排队' in messages[0]['content']
    assert 'grid_demand=电网需量' in messages[0]['content']


def test_local_scenario_transport_rejects_repetition_without_removing_scenario_sets():
    t = task('进行情景对比')
    t['required_tools'] = ['twin.compare']
    t['allowed_tools'] = list(t['required_tools'])
    t['results'] = [{'id':'T1', 'tool':'runtime.snapshot', 'ok':True}]
    variants = model.wire_schema(t)['properties']['action']['anyOf']
    args = next(v['properties']['arguments'] for v in variants if v['properties']['kind']['const'] == 'tool')
    schema = args['properties']['scenarios']
    assert schema['minItems'] == 2 and schema['maxItems'] == 5
    options = ['normal', 'vessel_surge', 'equipment_failure', 'energy_peak', 'storm']
    expected = {frozenset(group) for n in range(2, 6) for group in combinations(options, n)}
    assert {frozenset(group) for group in schema['enum']} == expected
    assert len(schema['enum']) == 26
    assert all(len(group) == len(set(group)) for group in schema['enum'])
    assert ['normal', 'energy_peak', 'storm'] in schema['enum']
    assert ['normal', 'energy_peak', 'storm', 'storm', 'storm'] not in schema['enum']


def test_scenario_transport_cannot_drop_explicit_comparison_requirement():
    t = task('比较需量高峰、大风、常态，生成交接')
    t.update(required_tools=['twin.compare'], allowed_tools=['twin.compare'])
    variants = model.wire_schema(t)['properties']['action']['anyOf']
    args = next(v['properties']['arguments'] for v in variants if v['properties']['kind']['const'] == 'tool')
    assert 'scenarios' in args['required']
    assert all({'normal', 'energy_peak', 'storm'} <= set(group) for group in args['properties']['scenarios']['enum'])
    t['inputs'] = [{'text':'改为只比较常态和大风', 'request_id':'steer'}]
    variants = model.wire_schema(t)['properties']['action']['anyOf']
    args = next(v['properties']['arguments'] for v in variants if v['properties']['kind']['const'] == 'tool')
    assert ['normal', 'storm'] in args['properties']['scenarios']['enum']


@pytest.mark.parametrize('goal,expected', [
    ('比较常态、大风与需量高峰', {'normal','storm','energy_peak'}),
    ('读取大风告警，比较常态和需量高峰', {'normal','energy_peak'}),
    ('不要比较大风', set()),
    ('比较常态和需量高峰，不含大风', set()),
])
def test_comparison_requirements_are_bounded_to_positive_comparison_clauses(goal, expected):
    from app.harness.semantic import requested_scenarios

    assert requested_scenarios(goal) == expected


def test_closed_intermediate_context_preserves_goal_skills_and_ids_without_mutating_evidence():
    t = task('查询电网需量和闸口排队，再交接')
    t.update(template_id='port-briefing', required_tools=['runtime.snapshot','maritime.query'], allowed_tools=['runtime.snapshot','maritime.query'])
    t['skills'] = ['maritime-evidence']
    t['results'] = [{'id':'T1','tool':'runtime.snapshot','ok':True,'summary':'raw' * 2000,'artifact':'T1.json','sha256':'original-hash','source_facts':{'required_value':0}}]
    original = copy.deepcopy(t)
    messages, compacted = model.context(t, [])
    content = json.loads(messages[1]['content'])
    assert compacted and content['goal'] == t['goal']
    assert content['skills'][0]['id'] == 'maritime-evidence'
    assert content['remaining_required_tools'] == ['maritime.query']
    assert content['tool_results'] == [{'id':'T1','tool':'runtime.snapshot','ok':True}]
    assert len(messages[0]['content']) + len(messages[1]['content']) < 1300
    assert t == original
    variants = model.wire_schema(t)['properties']['action']['anyOf']
    assert {v['properties']['kind']['const'] for v in variants} == {'tool'}


@pytest.mark.parametrize('mode', ['final', 'steered', 'failure'])
def test_closed_context_optimization_never_covers_final_synthesis_steering_or_failed_tools(mode):
    t = task('概括港区名称和主要告警')
    t.update(template_id='port-query', output_policy='model_or_rules_summary', required_tools=['runtime.snapshot','maritime.query'], allowed_tools=['runtime.snapshot','maritime.query'])
    t['results'] = [{'id':'T1','tool':'runtime.snapshot','ok':True,'summary':'source','artifact':'T1.json','sha256':'hash','source_facts':{'required_value':'QC-90'}}]
    if mode == 'final':
        t['required_tools'] = ['runtime.snapshot']
    if mode == 'steered':
        t['inputs'] = [{'text':'补充岸电负荷', 'request_id':'new'}]
    if mode == 'failure':
        t['results'][0]['ok'] = False
    assert not model.closed_tool_stage(t)
    messages, _ = model.context(t, [])
    content = json.loads(messages[1]['content'])
    assert content['user_inputs'] == t['inputs'] and content['budget'] == t['budget']
    if mode != 'failure':
        assert content['source_facts']['T1'] == t['results'][0]['source_facts']
