"""Independent source-field cases: omission, false gaps and value binding."""
import copy
import json

import pytest

from app.harness import model
from app.harness.semantic import field, snapshot_view, check_summary


@pytest.fixture
def snapshot():
    return {
        "port": {"name": "青澜模拟港", "code": "QINGLAN", "site_connected": False},
        "metadata": {"observed_at": "2026-10-31T04:25:00+00:00"},
        "energy": {"shore_power_kw": 0.0, "grid_demand_kw": 7281.5},
        "port_calls": [{"vessel_name": "宁澜轮", "eta": None, "atb": "2026-10-31T03:20:00+00:00"}],
        "alerts": [{"event_id": "lock-critical", "asset_id": "QC-81", "severity": "critical", "status": "active", "title": "吊具锁销状态异常"}],
    }


@pytest.mark.parametrize("row,state,value", [({}, "absent", None), ({"x": None}, "null", None), ({"x": ""}, "empty", ""), ({"x": 0}, "present", 0), ({"x": False}, "present", False)])
def test_presence_preserves_false_zero_null_and_absent(row, state, value):
    f = field(row, "x", path="test.x", label="测试字段")
    assert f["state"] == state and f["value"] == value
    assert type(f["value"]) is type(value)


def test_view_is_source_grounded_and_does_not_modify_snapshot(snapshot):
    before = copy.deepcopy(snapshot)
    v = snapshot_view(snapshot, "港区名称和编号、主要告警、宁澜轮的ETA和ATB、岸电负荷")
    assert snapshot == before
    by_path = {x["path"]: x for x in v["fields"]}
    assert by_path["port.name"]["value"] == "青澜模拟港"
    assert by_path["energy.shore_power_kw"]["state"] == "present"
    assert by_path["port_calls/0/eta"]["state"] == "null"
    assert v["required_alert_ids"] == ["lock-critical"]
    assert v["active_alerts"][0]["entity"] == "QC-81"


@pytest.mark.parametrize("text,passed", [
    ("青澜模拟港QINGLAN，QC-81吊具锁销异常，现场未接入。", True),
    ("青澜模拟港QINGLAN，现场未接入。", False),
    ("青澜模拟港QINGLAN，QC-81岸电正常，现场未接入。", False),
    ("未提供港区名称和港区编号；QC-81锁销异常。", False),
    ("青澜模拟港QINGLAN，QC-81锁销异常；未提供真实港口身份。", True),
])
def test_identity_and_required_alert_omission(snapshot, text, passed):
    assert check_summary(snapshot, "港区名称和编号、主要告警", text)["passed"] is passed


def test_actual_missing_name_remains_a_gap(snapshot):
    snapshot["port"]["name"] = None
    r = check_summary(snapshot, "港区名称和编号、主要告警", "港区名称未提供，港区编号QINGLAN。QC-81吊具锁销异常，工程模拟。")
    assert r["passed"]


def test_known_observation_time_does_not_fill_missing_eta_date(snapshot):
    assert check_summary(snapshot, "宁澜轮的ETA", "宁澜轮ETA日期未提供，工程模拟。")['passed']


@pytest.mark.parametrize("text,passed", [
    ("宁澜轮ETA为空，ATB为03:20；岸电负荷0 kW，工程模拟。", True),
    ("宁澜轮ETA为0，ATB未提供；岸电负荷0 kW。", False),
    ("宁澜轮ETA为空，ATB为03:20；岸电负荷7281.5 kW，电网需量0 kW。", False),
    ("宁澜轮ETA为空，ATB为03:20；岸电负荷未知。", False),
])
def test_field_binding_not_merely_numbers_present(snapshot, text, passed):
    assert check_summary(snapshot, "宁澜轮的ETA、ATB和岸电负荷", text)["passed"] is passed


def test_irrelevant_alarms_do_not_force_unrequested_full_report(snapshot):
    assert check_summary(snapshot, "只说岸电负荷", "岸电负荷为0 kW，工程模拟。")['passed']


@pytest.mark.parametrize("text,passed", [
    ("岸电负荷0 kW。", False),
    ("岸电负荷0 kW，工程模拟。由于生产权限关闭，无法获取实时数据。", False),
    ("岸电负荷0 kW，工程模拟；未接入现场生产源，生产控制权限关闭。", True),
])
def test_source_scope_and_read_control_causality_are_separate(snapshot, text, passed):
    assert check_summary(snapshot, "岸电负荷", text)["passed"] is passed


def test_source_facts_survive_summary_compaction(snapshot):
    t = {"actor_role":"operator", "allowed_tools":["runtime.snapshot"], "required_tools":["runtime.snapshot"], "results":[{"id":"T1", "tool":"runtime.snapshot", "ok":True, "summary":"noise" * 5000, "artifact":"T1.json", "sha256":"source-hash", "source_facts":snapshot_view(snapshot, "主要告警")}], "goal":"主要告警", "inputs":[], "plan":[], "skills":[], "usage":{}, "budget":{"context_chars":7000, "max_output_chars":8000}}
    messages, _ = model.context(t, [])
    data = json.loads(messages[-1]["content"])
    assert data['source_facts']['T1']['active_alerts'][0]['entity'] == 'QC-81'
    assert data['source_facts']['T1']['fields'][0]['value'] == '青澜模拟港'
    t['results'][0]['source_facts']['mandatory_uncompressible'] = '原始约束' * 5000
    with pytest.raises(ValueError, match="固定目标"):
        model.context(t, [])
