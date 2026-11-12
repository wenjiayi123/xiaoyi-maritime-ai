from types import SimpleNamespace
import copy
import pytest
from app.harness.contracts import digest,encoded
from app.harness.operation_intent import operational,domain_issues,inspection
from app.operation_evidence import ForecastRequest,DispatchRequest,MatchRequest,forecast,dispatch,reconcile,compact


def test_explicit_inspection_survives_a_conceptual_followup():
    assert operational("核对数字孪生和能碳的证据，并说明能否用于现场调度")
    assert not operational("请问数字孪生能否读取现场数据？")
    assert not operational("数字孪生的原理是什么")


def test_reconciliation_is_task_scoped_and_rejects_bad_artifact():
    f=forecast(ForecastRequest(site="shanghai",day="2026-07-01"))
    d=dispatch(DispatchRequest(scenario="industrial_mix_price_shift",week="2026-06-29"))
    items={};results=[]
    for i,(name,v) in enumerate((("forecast.port_load",f),("dispatch.tariff_week",d)),1):
        body=encoded(v);k=f"T{i}.json";items[k]={"content":body,"sha256":digest(body)};results.append({"id":f"T{i}","tool":name,"ok":True,"artifact":k,"sha256":digest(body)})
    task={"id":"owned","results":results,"goal":"对账，给出日前独立日峰和电价识别较原策略节省的金额，两项均用冻结回执。","allowed_tools":[r["tool"] for r in results]}
    store=SimpleNamespace(artifact=lambda owner,k:items[k] if owner=="owned" else None)
    refs=MatchRequest(forecast_ref="T1",dispatch_ref="T2");j=reconcile(refs,task,store)
    assert j["within_week"] and not j["same_load"] and not j["scope_matches"] and len(j["parent_sha256"])==2
    assert compact(d)["工况说明"].endswith("4 小时")
    text=f'独立日峰 {j["peak_kw"]:.2f} kW，较原策略节省 {j["saved_vs_original_cny"]:.2f} 元，二者负荷口径不同。'
    assert not domain_issues(task,text,[j])
    assert domain_issues(task,text.replace("负荷口径不同","口径一致"),[j])
    assert domain_issues(task,text.replace("节省","多花"),[j])
    assert domain_issues(task,text,[{**j,"dispatch_source":"twin"}])
    with pytest.raises(ValueError):reconcile(MatchRequest(forecast_ref="T2",dispatch_ref="T1"),task,store)
    items["T1.json"]["content"]+=" "
    with pytest.raises(ValueError):reconcile(refs,task,store)


def test_inspect_rounded_point_bound_to_actual_forecast():
    r={"target":"energy-cockpit","resource":"forecast","data":{"points":[{"horizon_hours":1,"predictions":{"terminal_load_kw":11857.287872},
        "prediction_interval_approx_95pct":{"terminal_load_kw":{"lower":10853.753643,"upper":12860.8221}}}],"model":{"model_id":"measured"},"input_snapshot_sha256":"abc"}}
    assert inspection(r)["逐时距预测"][0]["码头负荷_kW"]=="11857.29"
    assert inspection({**r,"data":None}) is None


def test_scope_binding_deduplication_and_steering():
    from app.harness.operation_intent import pinned_inputs,satisfied_read,menu
    t={"goal":"上海 2026-08-04 的冻结日前独立日峰。让 TwinLab 在线重算 2026-08-03 起始周工业混合负荷电价延后4小时的识别版账单。"}
    fields=pinned_inputs(t)
    f=fields["forecast.port_load"];d=fields["dispatch.tariff_week"]
    assert f=={"day":"2026-08-04","site":"shanghai","source":"archive"}
    assert d=={"week":"2026-08-03","scenario":"industrial_mix_price_shift","source":"twin"}
    r={"ok":True,"tool":"forecast.port_load","arguments":f}
    assert satisfied_read({**t,"results":[r]},r["tool"],f)
    assert not satisfied_read({**t,"results":[{**r,"ok":False}]},r["tool"],f)
    new=pinned_inputs({**t,"inputs":[{"text":"改为 2026-08-11 的日前独立日峰。"}]})
    assert new["forecast.port_load"]["day"]=="2026-08-11" and new["dispatch.tariff_week"]["week"]=="2026-08-03"
    assert "day" not in pinned_inputs({**t,"inputs":[{"text":"改到 2026-08-11"}]})["forecast.port_load"]
    assert not menu("读取日前预测，再恢复模拟配置")


def test_existence_question_does_not_replace_online_mode_or_count():
    from app.harness.operation_intent import explicit_modes,wrong_coverage
    q="两项都请 TwinLab 在线重算：上海日前独立日峰和原电价工况周账单。请说明是否存在同日起点冻结周回执。"
    assert explicit_modes(q)=={"forecast":"twin","dispatch":"twin"}
    r={"target":"port-dt-multi","resource":"coverage","data":{"total":10,"runtime_covered":9,"scenarios":[]}}
    assert wrong_coverage("运行覆盖率为9，包含场景。",r)
    assert not wrong_coverage("覆盖了9个场景，共10个，覆盖率为90%。",r)
    assert not wrong_coverage("覆盖率为9/10。",r)

def test_missing_and_present_archive_are_distinguished_in_chinese():
    from app.harness.operation_intent import domain_issues
    task={"goal":"请查日前日峰和电价识别工况并对账，是否存在同日起点冻结周回执？","allowed_tools":["forecast.port_load","dispatch.tariff_week","evidence.match_scope"]}
    joined={"schema":"operations.match.v1","scope_matches":True,"day":"2026-09-24","week":"2026-09-22","forecast_site":"shanghai","scenario":"shanghai","dispatch_archive_exists":False,"forecast_source":"twin","dispatch_source":"twin"}
    for sentence in ("该周不存在同日起点冻结周回执。","该周没有同日起点冻结周回执。","该日起点冻结周回执未登记。"):
        assert not domain_issues(task,sentence,[joined])
    assert domain_issues(task,"该周存在同日起点冻结周回执。",[joined])
