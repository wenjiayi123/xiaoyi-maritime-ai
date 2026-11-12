"""Match explicit policy selection and compare carbon deltas within their reporting period."""
import re

def requested(task):
    patterns={"guarded":r"(?:风险)?约束(?:型)?深度\s*(?:Q|强化学习)|风险价值网络",
              "single":r"单步","multi":r"多步"}
    for text in [v["text"] for v in reversed(task.get("inputs",[]))]+[task["goal"]]:
        arms=set()
        for arm,pattern in patterns.items():
            for m in re.finditer(pattern,text,re.I):
                if not re.search(r"不(?:要|用|选|跑|使用)|排除",text[max(0,m.start()-4):m.start()]):arms.add(arm)
        if arms:return sorted(arms)
    return []

def arguments_for(task,args):
    arms=requested(task)
    arm=args.get("arm")
    if not arms:return args
    if arm is None and len(arms)==1:return {**args,"arm":arms[0]}
    if arm not in arms:raise ValueError("本次工单已指定算法，请选择 "+" 或 ".join(arms))
    return args

def presentation(receipt):
    f=receipt["summary"]
    if "策略全天碳排减MPC_kg" not in f:return f
    def difference(value,positive,negative,unit):
        if value==0:return "持平（差额 0 "+unit+"）"
        return (positive if value>0 else negative)+f" {abs(value):,.2f} "+unit
    q={"时刻UTC":f["小时UTC"],"选中的动作":f["本小时动作"],"请求比例":f["本小时电池指令比例"],
       "仿真计量":f["查询小时实际方向"]+f" {f['查询小时实际充放电量_kWh']:,.2f} kWh","五个动作的回报估值":f["本小时五个动作Q值"]}
    if "本小时风险估计均越限" in f:
        row=receipt["steps"][f["小时UTC"]]
        q["五个动作的风险估值"]=f["本小时五个动作风险估值"]
        q["选择依据"]="五项风险预测全为正，选择预估风险最低的动作" if row["fallback"] else "只在预测风险非正的动作中取最高回报"
    daily={"仿真成本元":{k:f[v] for k,v in (("深度策略","深度策略全天成本元"),("固定限峰","固定限峰全天成本元"),("MPC","MPC全天成本元"))},
           "成本相对MPC":difference(f["相对MPC少花元"],"少花","多花","元"),"成本相对固定限峰":difference(f["相对固定限峰少花元"],"少花","多花","元"),
           "日峰相对MPC":difference(f["策略日峰减MPC日峰_kW"],"高出","低于","kW"),
           "全天碳排相对MPC":difference(f["策略全天碳排减MPC_kg"],"净增碳","净减碳","kg"),
           "不满足的检查":f["相对MPC未通过的约束"],"自动结论":f["结论"]}
    return {"日期UTC":f["日期UTC"],"负荷百分比":f["负荷百分比"],"方法":f["方法"],"用户指定小时的观测":q,
            "全天对照与工单结论":daily,"人工签署记录":None,"范围":"本机港区仿真"}

def claim_issues(text,row):
    facts=row["summary"]
    issues=[]
    # The only actor certified in this tool is the simulator and model; there is no human signature.
    for clause in re.split(r"[，,。；;！？\n]",text):
        if re.search(r"(?:人工|人工复核|人工审核|人工审批)(?:已|已经|业已)?(?:复核|核验|审核|审批)?(?:确认|通过|完成|批准|签字)|(?:经|经过)人工(?:审核|复核|批准)(?:后)?(?:确认|认定|已)",clause):
            if not re.search(r"尚未|未经|未完成|仍需|待|须|需要|应由|建议|可提交|尚需|不能|无法",clause):
                issues.append("本工单仅有模型和仿真证据。请报告自动结论「"+facts["结论"]+"」，没有人工签名或已完成复核的记录。")
    if re.search(r"(?:^|[，,。；;！？\s])(?:本次|本工单的)?人工(?:复核|审核|审批)(?:的)?(?:最终)?结论(?:为|是|[：:])",text):
        issues.append("工件没有人工签名。「人工复核结论」会把自动核验误说成人员结论。请直接写「工单建议"+facts["结论"]+"，人工尚未签署」。")
    att=row.get("attribution")
    if not att:return issues
    daily=att["carbon_difference_kg"]
    for sentence in re.split(r"[。；;！？\n]",text):
        for m in re.finditer(r"([+\-−]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:kg|千克|公斤)",sentence,re.I):
            context=sentence[:m.start()]
            if not re.search(r"碳|排放",context):continue
            clause=re.split(r"[，,](?!\d{3})",context)[-1]
            indicators=re.findall(r"净增碳|净减碳|净增|净减|增碳|减碳|多排|少排|增加|减少|降低|升高|上升|下降|高出|高于|低于|净差|碳差|多|少",clause)
            if not indicators:continue
            local=re.search(r"(\d{1,2})\s*(?:点|时)(?:段|内|UTC)?",clause)
            scope=daily
            if local and not re.search("全天|全日|当日",clause):
                h=int(local[1]);scope=att["hourly_carbon_difference_kg"][h] if h<24 else daily
            elif re.search(r"该小时|本小时|此小时|这一小时|这一个小时",clause):
                match=re.findall(r"(\d{1,2})\s*(?:时|点)",context)
                if match and int(match[-1])<24:scope=att["hourly_carbon_difference_kg"][int(match[-1])]
                else:scope=att["hourly_carbon_difference_kg"][row["args"]["hour"]]
            indicator=indicators[-1]
            if indicator in ("净减碳","净减","减碳","少排","减少","降低","下降","低于","少"):scope=-scope
            literal=m[1].replace(",","").replace("−","-");precision=len(literal.partition(".")[2])
            if abs(float(literal)-round(scope,precision))>1e-6:
                issues.append(f"请改正碳排方向和时段。全天相对MPC为{'净增碳' if daily>=0 else '净减碳'} {abs(daily):,.2f} kg。单小时差必须注明具体小时。")
    return list(dict.fromkeys(issues))
