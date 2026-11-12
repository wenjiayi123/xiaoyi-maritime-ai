"""Bind a requested TwinLab readback and distinguish live receipts from archived replay data."""
import re


def shore_fields(task):
    """Bind an explicitly named registered input, keeping mixed/comparative requests open."""
    fixed={}
    messages=[task.get("goal",""),*(v.get("text","") for v in task.get("inputs",[]))]
    query=" ".join(messages)
    live=online_request(task)
    if not re.search(r"岸电|储能|船次电表|shore.power|BESS",query,re.I):
        return {"verify_twin":live} if live is not None else {}
    for text in reversed(messages):
        calls=set(re.findall(r"(?<![A-Za-z0-9_])SC_\d{5}(?![A-Za-z0-9_])",text))
        dates=set(re.findall(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)",text))
        if not calls and not dates:continue
        if re.search(r"(?:排除|不要查|不查|except|exclude)\s*(?:船次|日期)?\s*(?:SC_|20\d{2}-)",text,re.I):break
        explicit_week=bool(re.search(r"起始周|周起点|周回执|岸电周|周策略|168\s*小时|那一周|这一周|--week",text))
        if len(calls)==1 and not (dates and explicit_week):
            fixed={"call_id":next(iter(calls)),"week":None,"hour":None,"verify_twin":False}
        elif len(dates)==1 and not calls and explicit_week:
            fixed={"week":next(iter(dates)),"call_id":None}
            ordinal=[int(n)-1 for n in re.findall(r"第\s*(\d+)\s*(?:个)?小时",text)]
            indexes=[int(n) for n in re.findall(r"(?:小时索引|零基索引|hour\s*=)\s*[:：=]?\s*(\d+)",text,re.I)]
            named=set(ordinal+indexes)
            if len(named)==1 and 0<=min(named)<168:fixed["hour"]=named.pop()
            elif not re.search(r"第\s*[零一二三四五六七八九十百\d]+\s*(?:个)?小时|小时索引|小时明细|逐时|hour\s*[=:\d]",query,re.I):
                fixed["hour"]=None
        break
    if fixed.get("week"):fixed["verify_twin"]=live is True
    elif live is not None and fixed.get("call_id") is None:fixed["verify_twin"]=live
    return fixed


def read_policy_first(task):
    if "policy.shore_storage" not in task.get("allowed_tools",[]) or task.get("results"):return False
    fixed=shore_fields(task)
    text=" ".join([task.get("goal",""),*(v.get("text","") for v in task.get("inputs",[]))])
    return bool((fixed.get("call_id") or fixed.get("week")) and re.search(r"查|核|重放|复算|重算|多少|哪个泊位|回执",text))


def online_request(task):
    texts=[task.get("goal",""),*(v.get("text","") for v in task.get("inputs",[]))]
    for text in reversed(texts):
        twin=bool(re.search(r"TwinLab|原生孪生|官方孪生|verify_twin",text,re.I))
        if not twin and not re.search(r"在线.{0,6}(?:核验|读回|复核|重放|重算)",text):continue
        if re.search(r"verify_twin\s*[:=：]\s*(?:false|0)|(?:不要|勿|不用|无需|禁止).{0,18}(?:在线|TwinLab|verify_twin)|(?:只|仅)(?:看|查|读取)(?:冻结|归档|静态)",text,re.I):return False
        if re.search(r"在线.{0,9}(?:核验|复核|重算|重放|读回)|(?:启用|打开)\s*verify_twin|verify_twin\s*[:=：]\s*true|(?:TwinLab|孪生).{0,18}(?:重新计算|实际重算|独立复算|重新运行)",text,re.I):return True
    return None


def live_claim_problem(task,text,receipt):
    references=receipt if isinstance(receipt,list) else [receipt]
    verified=[r for r in references if r.get("twin_readback",{}).get("verified") is True]
    if online_request(task) is True and not verified:return True
    for sentence in re.split(r"[。！？;；\n]",text):
        claim=re.search(r"(?:在线|TwinLab|原生重算|重放|重算).{0,22}(?:核验通过|核对通过|复核通过|已验证|相符|一致)|(?:已|完成).{0,9}(?:在线重放|在线复核|在线核验)",sentence,re.I)
        if claim and not re.search(r"未|尚无|无法|不能|不代表|无需|不一致",sentence):
            dates=set(re.findall(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)",sentence))
            if not verified or dates and not dates.issubset({r.get("week") for r in verified}):return True
    return False


def incorrect_departure_credit(text):
    # A meter sample exactly at departure cannot create a new service interval.
    for clause in re.split(r"[。；;！？\n]",text):
        if not re.search(r"离泊(?:端点|时刻|之后|以后|后)|离港(?:时刻|之后|后)",clause):continue
        if re.search(r"(?:不|未|无须|无需|不会|不可|不能|不应).{0,6}(?:计入|计费|计算|纳入)|排除|截断|截止|为\s*0\s*kWh|计入.{0,4}(?:零|0\s*kWh)",clause,re.I):continue
        if re.search(r"(?:离泊|离港).{0,14}(?:之后|以后|后一刻钟|后的一刻钟|后的.{0,4}分钟|后续).{0,16}(?:计入|纳入|计费)",clause):return True
    return False
