"""Compact model-facing evidence. Exact full receipts remain in the harness artifact store."""

def policy_digest(name,result):
    if name=="policy.vessel_schedule":
        baseline=result["baseline"];candidate=result["metrics"]
        def compact(m):
            return {"目标成本_元":format(m["objective_cny"],".2f"),"总等待_船时":m["wait_vessel_hours"],
                    "总逾期_船时":m["late_vessel_hours"],"完成量_TEU":m["processed_teu"],
                    "岸电_kWh":m["shore_kwh"],"岸桥_台时":m["crane_hours"]}
        return {"日期":result["day"],"工况":result["scenario"],"方法":result["method"],"沙盘基线":compact(baseline),
                "当前方案":compact(candidate),"本日达到严格改进门槛":result["eligible_improvement"],
                "未过条件":[k for k,v in result["checks"].items() if not v],
                "基线在求解器下界容差内":result.get("native_at_solver_bound"),
                "船次列":["工程船次","泊位编号_从1起","开工时","完工时"],
                "逐船分配":[[v["job_id"],v["berth"]+1,v["start_hour"],v["end_hour"]] for v in result["schedule"]],
                "适用范围":result["scope"],"现场控制权限":False,"回执":result["receipt_sha256"]}
    capacity=result["dr_capacity_review"]
    meanings={"no_event":"当日无响应事件","delivered":"达到最低交付",
              "shortfall_undetermined":"交付不足，该上界未能判定物理可行性",
              "incompatible_with_service":"最低交付超出保持充电与冷链服务时的物理上界"}
    from app.harness.service_facts import service_facts
    checks=result["checks"]
    return {**service_facts(result),"日期与对照":result["selection"],"响应目标_kWh":result["dr_contract_kwh"],
            "该方案实际充电服务达标":checks["agv_delivered"] and checks["agv_departures"],
            "该方案实际冷链服务达标":checks["cold_chain"] and checks["terminal_thermal_debt"],
            "该方案实际响应交付达标":checks["dr_delivery"],
            "最低交付_kWh":format(capacity["required_kwh"],".2f"),"实交_kWh":format(capacity["delivered_kwh"],".2f"),
            "事后乐观上界_kWh":format(capacity["upper_kwh"],".2f"),"响应结论":meanings[capacity["status"]],
            "可供离线复核":not result["failed"],"未过条件":result["failed"],"日成本变化_百分比":format(result["cost_change_pct"],".2f"),
            "候选原单位指标":result["candidate_metrics"],"基线原单位指标":result["baseline_metrics"],
            "范围":capacity["scope"]+result["scope"],"现场控制权限":False,"回执":result["receipt_sha256"]}


def conflicting_service_claim(text,result):
    import re
    checks=result["checks"]
    if not all(checks[k] for k in ("agv_delivered","agv_departures","cold_chain","terminal_thermal_debt")):return False
    # These two services were delivered. A statement about joint infeasibility
    # must include the third obligation, or explicitly be conditional on it.
    for sentence in re.split(r"[。！？；;\n]",text):
        denied=re.search(r"(?:无法|不能|不可|未能|难以)(?:同时|一并|兼顾)(?:保持|维持|保障|保住|满足|确保)?[^。；]{0,16}(?:充电.{0,10}冷链|冷链.{0,10}充电)",sentence)
        if not denied:continue
        if re.search(r"(?:并非|不是|并不意味着|不代表)\s*$",sentence[:denied.start()]):continue
        tail=sentence[denied.end():]
        conditional=bool(re.search(r"(?:若|如需|要|在|当).{0,18}(?:达到|交足|满足|兑现|完成).{0,12}(?:响应|最低交付|合同)",sentence[:denied.start()]))
        third=bool(re.search(r"(?:响应目标|响应门槛|响应交付|最低交付|需量响应|需求响应|响应承诺|三项)",denied.group()+tail))
        if not conditional and not third:return True
    return False
