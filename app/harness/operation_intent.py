"""Recognize explicit work-order instructions and check scope claims against cited receipts."""
import re

READ=r"检查|核对|核验|读取|查阅|查询|复算|试算|重算|比较|对比|出具|汇报|列出"
IDEA=r"是什么|什么是|怎么实现|如何实现|能否|能不能|可以吗|原理"
MODEL_TOOLS=("forecast.port_load","dispatch.tariff_week","evidence.match_scope")


def request_kind(text):
    forecast=bool(re.search(r"日前.{0,8}(?:预测|日峰)|独立日峰|日峰(?:值)?(?:预测|估计)|(?:上海|丰沙尔|工业混合).{0,12}(?:日峰|负荷预测)",text))
    dispatch=bool(re.search(r"电价.{0,12}(?:工况|识别|错位|偏移|延后|提前|未知|变化)|(?:工况|储能|策略).{0,12}(?:账单|节省|电价)",text))
    return forecast,dispatch


def operational(text):
    from app.deep_storage_trial import menu as deep_menu
    if deep_menu(text):return True
    prior_action=re.search(r"查看|检查|读取|比较|对比|试算|暂停|恢复|切换|验证|核验|回放|执行|帮我|请",text)
    relevant=bool(re.search(r"能碳|马六甲|数字孪生|航行模拟器|强化学习|RL|策略|Harness|harness",text) or any(request_kind(text)))
    from app.portcall_evidence import menu as portcall_menu
    from app.equipment_evidence import menu as equipment_menu
    from app.port_carbon_evidence import menu as carbon_menu
    from app.port_cost_evidence import menu as cost_menu
    from app.queue_evidence import menu as queue_menu
    from app.cycle_evidence import ids_in
    if ids_in(text):return True
    if not relevant and not portcall_menu(text) and not equipment_menu(text) and not carbon_menu(text) and not cost_menu(text) and not queue_menu(text):return False
    if not re.search(IDEA,text):
        return bool(prior_action or re.search(READ,text))
    for clause in re.split(r"[，,。；;！？!?\n]",text):
        if re.search(READ,clause) and not re.search(IDEA+r"|是否可以|是否支持|如何|怎样|请问为什么",clause):return True
    return False


def menu(text):
    from app.deep_storage_trial import menu as deep_menu
    if deep_menu(text):return deep_menu(text)
    from app.portcall_evidence import menu as portcall_menu
    from app.equipment_evidence import menu as equipment_menu
    from app.port_carbon_evidence import menu as carbon_menu
    from app.port_cost_evidence import menu as cost_menu
    from app.queue_evidence import menu as queue_menu
    from app.cycle_evidence import menu as cycle_menu
    if cycle_menu(text):return cycle_menu(text)
    queue=queue_menu(text)
    if queue:return queue
    cost=cost_menu(text)
    if cost:return cost
    carbon=carbon_menu(text)
    if carbon:return carbon
    equipment=equipment_menu(text)
    if equipment:return equipment
    portcalls=portcall_menu(text)
    if portcalls:return portcalls
    if not any(request_kind(text)):return []
    if re.search(r"启动系统|暂停系统|恢复模拟|下发(?:生产|现场)指令|切换模拟配置",text):return []
    return [*MODEL_TOOLS,"systems.inspect","calculate","policy.shore_storage"]


def inspection(r):
    d=r.get("data",{});key=(r.get("target"),r.get("resource"))
    if not isinstance(d,dict):return None
    if key==("port-dt-multi","coverage") and {"total","runtime_covered","scenarios"}<=d.keys():
        count=d["runtime_covered"];total=d["total"]
        fraction=format(100*count/total,".2f")+"%" if type(count) is int and type(total) is int and total>0 else "未知"
        return {"系统":"数字孪生","已经覆盖的场景数":count,"登记场景总数":total,"覆盖占比":fraction,
                "统计口径":f"已覆盖 {count} 个，登记总数 {total} 个，比例 {fraction}。",
                "场景":[[v.get("name"),v.get("state")] for v in d["scenarios"]],"范围":d.get("claim_boundary"),"现场权限":False}
    if key==("energy-cockpit","forecast") and {"points","model","input_snapshot_sha256"}<=d.keys():
        horizons=[]
        for p in d["points"]:
            y=p.get("predictions",{});band=p.get("prediction_interval_approx_95pct",{}).get("terminal_load_kw",{})
            if "terminal_load_kw" not in y or not {"lower","upper"}<=band.keys():return None
            horizons.append({"时距_小时":p["horizon_hours"],"码头负荷_kW":format(y["terminal_load_kw"],".2f"),
                "区间下界_kW":format(band["lower"],".2f"),"区间上界_kW":format(band["upper"],".2f")})
        return {"系统":"能碳","类型":d.get("data_mode"),"原生推理":d.get("true_model_inference"),"模型":d["model"].get("model_id"),
                "预测点数":len(horizons),"逐时距预测":horizons,"快照指纹":d["input_snapshot_sha256"],"现场权限":False}
    return None


def explicit_modes(text):
    flags={}
    for phrase in re.split(r"[。；;！？\n]",text):
        # A question about the existence/comparison of an archive is not a
        # request to substitute it for the live computation ordered earlier.
        phrase=re.sub(r"(?:是否(?:存在|有|还有)|有没有|有无).{0,18}?(?:冻结|归档).{0,12}?(?:回执|凭证|记录)|(?:与|和)(?:同日|已有|已登记的)?(?:冻结|归档).{0,8}(?:核对|比对|比较)","",phrase)
        archive=bool(re.search(r"冻结|归档|离线",phrase))
        live=bool(re.search(r"在线|本次.{0,5}重算|让\s*TwinLab.{0,8}重算",phrase,re.I))
        if re.search(r"不(?:要|用|必|需).{0,5}在线",phrase):archive,live=True,False
        if archive==live:continue
        mode="archive" if archive else "twin"
        if re.search(r"两份|两项|都(?:要|用|需要)|均(?:取|用|要)|全程|只查冻结数据",phrase):
            flags.update(forecast=mode,dispatch=mode)
        else:
            f,d=request_kind(phrase)
            if f:flags["forecast"]=mode
            if d:flags["dispatch"]=mode
    return flags


def pinned_inputs(task):
    """Bind unambiguous user-supplied parameters; comparisons and repeat requests stay open."""
    fixed={k:{} for k in MODEL_TOOLS[:2]}
    for seq,text in enumerate([task.get("goal",""),*(i.get("text","") for i in task.get("inputs",[]))]):
        clauses=re.split(r"[。；;，,！？\n]|以及|和(?=\s*20\d\d-)|及(?=\s*20\d\d-)|去解释",text)
        dates=[set(),set()];sites=set();scenarios=set()
        for clause in clauses:
            identities=re.findall(r"(?<!\d)20\d\d-\d{2}-\d{2}(?!\d)",clause)
            is_day=bool(re.search("日前|日峰|预测日",clause))
            is_week=bool(re.search("起始周|周起点|起算周|工况|原电价|储能账单|周账单",clause))
            if is_day and not is_week:dates[0].update(identities)
            if is_week and not is_day:dates[1].update(identities)
            if is_day:
                for k,p in (("funchal","丰沙尔"),("shanghai","上海"),("industrial_mix","工业混合负荷")):
                    if p in clause:sites.add(k)
            for label,pattern in (("industrial_mix_price_shift",r"(?:延后|推迟)\s*[4四]\s*小时"),("phase_minus3",r"提前\s*[3三]\s*小时"),
                                  ("phase_plus6",r"延后\s*[6六]\s*小时"),("week_switch",r"周内.{0,4}切换"),("unlisted_tariff",r"未知电价"),
                                  ("industrial_mix",r"工业混合负荷.{0,4}原电价"),("shanghai",r"上海(?:原负荷)?原电价|原电价工况")):
                if re.search(pattern,clause):scenarios.add(label)
        for key,field,values in ((MODEL_TOOLS[0],"day",dates[0]),(MODEL_TOOLS[1],"week",dates[1]),(MODEL_TOOLS[0],"site",sites),(MODEL_TOOLS[1],"scenario",scenarios)):
            if len(values)==1:fixed[key][field]=next(iter(values))
            elif len(values)>1:fixed[key].pop(field,None)
        for role,mode in explicit_modes(text).items():
            fixed[MODEL_TOOLS[0 if role=="forecast" else 1]]["source"]=mode
        if seq and re.search(r"20\d\d-\d{2}-\d{2}",text) and not any(dates):
            fixed[MODEL_TOOLS[0]].pop("day",None);fixed[MODEL_TOOLS[1]].pop("week",None)
    return fixed


def satisfied_read(task,name,fields):
    if re.search(r"再读一次|反复|重新采样|连续两次|重复读取|再次采样",task.get("goal","")):return False
    identifiers=("site","day") if name==MODEL_TOOLS[0] else ("scenario","week")
    if not all(i in fields for i in identifiers):return False
    if "source" not in fields:return False
    return any(r["ok"] and r["tool"]==name and all(r["arguments"].get(k,"archive" if k=="source" else None)==v for k,v in fields.items()) for r in task.get("results",[]))


def close_amount(text,value):
    shown=float(text.replace(",","").replace("−","-"))
    precision=len(text.rsplit(".",1)[1]) if "." in text else 0
    return abs(shown-float(format(value,f".{precision}f")))<1e-7


def domain_issues(task,answer,receipts):
    """Explicit requests for both records and a provenance comparison are delivery conditions."""
    if not set(MODEL_TOOLS)&set(task.get("allowed_tools",[])):return []
    text=" ".join([task["goal"],*(v.get("text","") for v in task.get("inputs",[]))])
    kinds=request_kind(text)
    if not any(kinds):return []
    joins=[r for r in receipts if r.get("schema")=="operations.match.v1"]
    have_f=bool(joins or any(r.get("schema")=="operations.forecast.v1" for r in receipts))
    have_d=bool(joins or any(r.get("schema")=="operations.dispatch.v1" for r in receipts))
    issues=[]
    if kinds[0] and not have_f:issues.append("所要求的日前功率尚缺引用，请取得预测回执。")
    if kinds[1] and not have_d:issues.append("所要求的调度账单尚缺引用，请取得工况周回执。")
    if all(kinds) and re.search("同口径|同一.{0,5}(?:负荷|窗口|工况)|对账|能否归因|匹配",text) and not joins:
        issues.append("尚无本工单两份原件的范围比对，请用两条实际工具编号核对并引用。")
    binding=pinned_inputs(task)
    for role,tool in zip(("forecast","dispatch"),MODEL_TOOLS[:2]):
        specified=binding[tool];records=[r for r in receipts if r.get("schema")=="operations."+role+".v1"]
        for j in joins:
            records.append({"day":j["day"],"site":j["forecast_site"],"source":j["forecast_source"]} if role=="forecast" else
                           {"week":j["week"],"scenario":j["scenario"],"source":j["dispatch_source"]})
        if records and not any(all(r.get(k)==v for k,v in specified.items()) for r in records):
            issues.append("所引业务数据的日期、负荷来源或工况不符合当前工单。")
        for j in joins:
            values=({"day":j["day"],"site":j["forecast_site"],"source":j["forecast_source"]} if role=="forecast" else
                    {"week":j["week"],"scenario":j["scenario"],"source":j["dispatch_source"]})
            if any(values.get(k)!=v for k,v in specified.items()):
                issues.append("范围对账仍指向旧数据，请用符合当前工单的父工件重新比对。")
    for role,mode in explicit_modes(text).items():
        matching=[r["source"] for r in receipts if r.get("schema")=="operations."+role+".v1"]
        matched_parents=[r[role+"_source"] for r in joins]
        if (matching or matched_parents) and (mode not in matching+matched_parents or any(x!=mode for x in matched_parents)):
            issues.append(("预测" if role=="forecast" else "调度")+"读取来源不符合要求，请使用"+("本次 TwinLab 在线回执" if mode=="twin" else "冻结回执"))
    peak=[r["peak_kw"] for r in receipts if "peak_kw" in r]
    savings=[r["saved_vs_original_cny"] for r in receipts if "saved_vs_original_cny" in r]
    if have_f and kinds[0] and re.search(r"报|给出|列出|是多少|多少",text) and re.search(r"日峰",text):
        amounts=re.findall(r"([+−-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:kW(?!h)|千瓦)",answer,re.I)
        if not any(close_amount(a,v) for a in amounts for v in peak):issues.append("请用 kW 报出所引预测的独立日峰值。")
    if have_d and kinds[1] and re.search(r"较原策略|相对原策略|较原控制",text) and re.search(r"节省|多花|金额",text):
        amounts=re.finditer(r"([+−-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:元|CNY)",answer,re.I)
        correct=False
        for m in amounts:
            prefix=re.split(r"[。；;\n]",answer[:m.start()])[-1]
            verbs=re.findall(r"多花|费用增加|增加|省下|少花|省钱|节省|省",prefix)
            increase=bool(verbs and verbs[-1] in ("多花","费用增加","增加"))
            if any(close_amount(m[1],-v if increase else v) for v in savings):correct=True
        if not correct:issues.append("请按同周原策略基准报出节省或多花的元数，并核对方向。")
    for r in joins:
        for clause in re.split(r"[，,。；;！？\n]",answer):
            if not r["scope_matches"] and re.search("口径一致|两者同源|可以直接归因|可以同口径|两份负荷相同",clause) and not re.search("不一致|不同|不匹配|不能|不得|无法|并非",clause):
                issues.append("预测日期或负荷口径与控制窗口不同，不能作同口径归因。")
            if re.search(r"已(?:经)?.{0,5}(?:在线核验|在线重算|通过线上核验)",clause) and r["forecast_source"]==r["dispatch_source"]=="archive":
                issues.append("两份回执均为归档，无法声明本次在线重算。")
        if re.search(r"(?:是否存在|有没有|有无).{0,15}(?:冻结|归档).{0,6}周回执",text) and r.get("dispatch_archive_exists") is False:
            if not re.search(r"(?:不存在|没有|查不到|未登记|未找到|无|缺少)[^，,。；;！？\n]{0,24}(?:冻结|归档)|(?:冻结|归档)[^，,。；;！？\n]{0,12}(?:缺失|不存在|未登记|没有)",answer):
                issues.append("请说明成功在线重算的该周没有同日起点冻结周回执；日期在周内是另一个判断。")
    return issues


def wrong_coverage(answer,receipt):
    facts=inspection(receipt)
    if not facts or "登记场景总数" not in facts:return False
    total=facts["登记场景总数"];count=facts["已经覆盖的场景数"]
    if type(total) is not int or type(count) is not int or total<=0:return False
    for m in re.finditer(r"覆盖(?:率|占比)(?:约为|为|是|约|达到)?\s*(\d+(?:\.\d+)?)\s*(%|％|/\s*\d+)?",answer):
        number=float(m[1]);suffix=m[2] or ""
        if "/" in suffix:
            if number!=count or float(suffix.split("/")[-1])!=total:return True
        elif suffix:
            if not close_amount(m[1],100*count/total):return True
        elif number>1 or abs(number-count/total)>.000001:return True
    return False
