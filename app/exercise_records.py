"""Read-only checks for explicitly declared exercises. All fields point to the supplied text."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import re
from typing import Literal

from app import batch_emissions, berth_clock, maintenance_hours, monthly_energy_rule

from pydantic import BaseModel, ConfigDict, Field


class ExerciseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
    facts: str = Field(min_length=2, max_length=2400)
    kind: Literal["power", "version", "permit", "flow", "unit_cost", "maintenance", "batch_emissions", "energy_monthly", "berth_clock", "general"]
    scope: Literal["exercise"]


class Unresolved(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def applicable(facts, question):
    if berth_clock.applicable(facts, question):
        return "berth_clock"
    if monthly_energy_rule.applicable(facts, question):
        return "energy_monthly"
    if batch_emissions.applicable(facts, question):
        return "batch_emissions"
    if maintenance_hours.applicable(facts, question):
        return "maintenance"
    if re.search(r"速率|通过能力|吞吐能力",question) and re.search(r"串联|串行|依次经过",facts):
        return "flow"
    if re.search(r"单位成本|每(?:标准箱|箱|TEU).*成本",question,re.I) and re.search(r"成本",facts):
        return "unit_cost"
    if re.search(r"并网|购电功率|网侧|电网取电",question) and re.search(r"(?:[kM]W|千瓦|兆瓦)",facts,re.I):
        return "power"
    if re.search(r"上限|限值|适用限额",question) and re.search(r"旧版|新版|版本|生效|有效期",facts):
        return "version"
    if re.search(r"有效|剩余.*分钟",question) and re.search(r"签字|会签|签批|批准|审批|签名",facts):
        return "permit"
    return None


def from_command(text):
    prefix=re.match(r"^\s*(/演练核验|/演练推理|/分步复算)(?:\s|$)",text)
    if not prefix:
        return None
    marker=prefix[1]
    match=re.fullmatch(re.escape(marker)+r"[ \t]+(?P<id>[^\s]{1,100})\s*\n事实[：:](?P<facts>.+?)\n问题[：:](?P<question>[^\n]+)\s*",text.strip(),re.S)
    if not match:
        raise ValueError(f"{marker} 用法：第一行写命令与记录编号，第二行以“事实：”开头，第三行以“问题：”开头")
    facts=match["facts"].strip()
    question=match["question"].strip()
    kind=applicable(facts,question)
    if kind is None and marker=="/演练核验":raise ValueError("当前演练核验支持靠泊时限、功率、串联能力、单位成本、批次净减排、具名能耗月报条款、维保工时、版本限额和签批有效期问题")
    if kind is None:kind="general"
    return ExerciseRecord(source=match["id"],facts=facts,kind=kind,scope="exercise")


NUMBER = r"[+-]?\d+(?:\.\d+)?"
DAY = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}(?=\s*日))"
REGIONS = re.compile(r"辖区(?:不符|不明|不同|未知)|不同辖区|不含|不包括当日|失效日期未明|撤销条款|优先适用|除外")
ROLE = {"loads":r"负荷|用电|充电|耗用|消耗", "generation":r"放电|光伏|发电|风电出力",
        "caps":r"上限|限额|不得超过|不超过|最大允许|最大购电|限制"}


def span(text, offset, match, group, role):
    a,b=match.span(group)
    return {"role":role,"start":offset+a,"end":offset+b,"text":text[a:b]}


COUNT=r"(?:[1-9]\d?|[一二两三四五六七八九十]{1,3})"


def count_units(raw):
    if raw.isdigit():return int(raw)
    digits={"一":1,"二":2,"两":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}
    if raw in digits:return digits[raw]
    if raw.count("十")==1:
        a,b=raw.split("十")
        if (not a or a in digits) and (not b or b in digits):return 10*(digits[a] if a else 1)+digits.get(b,0)
    raise Unresolved("flow_count","并行设备数量不明确")


def parse_flow(text):
    if re.search(r"分流|回流|返工|共享|互斥|故障|检修|停机|利用率|小计|其中|合计",text):
        raise Unresolved("flow_topology","含共享、未去重或不可用设备，需区分实际可用能力")
    rate=re.compile(rf"(?P<value>{NUMBER})\s*(?P<unit>箱|TEU)\s*(?:/|每)\s*(?P<period>小时|分钟)",re.I)
    references=[];capacities=[];targets=[];units=set()
    prior=0
    for hit in rate.finditer(text):
        left=text[prior:hit.start()]
        # Keep the full fragment for counts, but not an earlier goal or machine description.
        prefix=re.split(r"[。；;、，,]",left)[-1]
        per_hour=Decimal(hit["value"])*(60 if hit["period"]=="分钟" else 1)
        units.add(hit["unit"].upper())
        if per_hour<0:raise Unresolved("flow_rate","速率不能为负")
        is_target=re.search(r"计划速率|最低目标|目标速率|需求速率|计划最低|目标至少|要求至少",prefix)
        pointers=[span(text,0,hit,0,"计划速率" if is_target else "环节速率")]
        if is_target:targets.append(per_hour)
        else:
            multiplier=1
            multiplicity=re.search(rf"(?P<count>{COUNT})\s*台[^。；、，（）()]*?(?:各|每台)(?:为|可达|约)?\s*$",left)
            if multiplicity:
                multiplier=count_units(multiplicity["count"])
                pointers.append(span(left,prior,multiplicity,"count","并行台数"))
            elif re.search(r"(?:各|每台)\s*$",left) or re.search(rf"{COUNT}\s*台",prefix):
                raise Unresolved("flow_count","单机或合计能力及设备数未明确")
            capacities.append(per_hour*multiplier)
        references.extend(pointers);prior=hit.end()
    if len(units)!=1:raise Unresolved("flow_unit","各环节与目标须统一箱或 TEU 口径")
    if len(capacities)<2 or len(targets)!=1:raise Unresolved("flow_missing","至少两个有速率的环节和唯一目标才可核验")
    if re.search(r"速率未知|能力未知|速率待补|能力未提供|能力缺失|尚未测定|瓶颈未查明|超过而不含|严格超过",text):
        raise Unresolved("flow_missing","存在未说明的环节能力或特殊目标边界")
    bottleneck=min(capacities)
    return bottleneck,bottleneck>=targets[0],references,{"stage_rates_per_hour":list(map(float,capacities)),
        "target_per_hour":float(targets[0]),"unit":next(iter(units))+"/小时"}


def parse_unit_cost(text):
    if re.search(r"美元|港元|港币|欧元|汇率|含税换算|另计|未计入|未含|未知|待核实",text):
        raise Unresolved("cost_scope","币种、成本边界或分母尚未统一")
    if not re.search(r"先四舍五入(?:到|至|保留)?(?:小数点后)?(?:两|二|2)位",text):
        raise Unresolved("cost_rounding","演练需明确先四舍五入到两位再比较的口径")
    patterns={
        "cost":rf"(?:班次成本|总成本|本次成本|成本)(?:为|是|：)?\s*(?P<v>{NUMBER})\s*(?P<unit>万元|元)(?!\s*/)",
        "volume":rf"(?:服务量|实际作业量|完成量|处理量)(?:为|是|：)?\s*(?P<v>{NUMBER})\s*(?P<unit>万?TEU|万?箱)",
        "limit":rf"(?P<v>{NUMBER})\s*(?P<unit>元\s*/\s*(?:TEU|箱))\s*(?:的)?(?:上限|限额|限值)"}
    hits={};pointers=[]
    for key,pattern in patterns.items():
        group=list(re.finditer(pattern,text,re.I))
        if len(group)!=1:raise Unresolved("cost_roles","须分别给出唯一成本、完成量和同口径单位成本上限")
        hits[key]=group[0];pointers.append(span(text,0,group[0],0,key))
    cost=Decimal(hits["cost"]["v"])*(10000 if hits["cost"]["unit"]=="万元" else 1)
    unit=hits["volume"]["unit"].upper()
    volume=Decimal(hits["volume"]["v"])*(10000 if unit.startswith("万") else 1)
    limit=Decimal(hits["limit"]["v"])
    if volume<=0 or cost<0 or limit<0:raise Unresolved("cost_volume","成本或上限为负，或服务量不是正数")
    unit=unit.removeprefix("万")
    if hits["limit"]["unit"].split("/")[-1].strip().upper()!=unit:
        raise Unresolved("cost_unit","箱与 TEU 的口径不同，不能直接比较")
    value=(cost/volume).quantize(Decimal(".01"),rounding=ROUND_HALF_UP)
    return value,value<=limit,pointers,{"cost_cny":float(cost),"volume":float(volume),"unit":"元/"+unit,"limit":float(limit),
                                       "rounding":"ROUND_HALF_UP before limit comparison"}


def parse_power(text):
    if re.search(r"可能|尚待确认|约为|拟议|或许|未经测量|二选一|最大值未知",text):
        raise Unresolved("power_uncertain","记录中含候选值或未确认的功率，不能认定唯一结果")
    if re.search(r"其中|已包含|包含.*分项|已计入|合计负荷|负荷合计|小计",text):
        raise Unresolved("grouping","负荷含小计或包含关系，须先明确分项边界")
    powers=re.compile(rf"(?P<number>{NUMBER})\s*(?P<unit>MW|kW|兆瓦|千瓦)(?![A-Za-z时])",re.I)
    groups={name:[] for name in ROLE}
    pointers=[]
    for clause in re.finditer(r"[^，,；;。]+",text):
        phrase=clause.group()
        hits=list(powers.finditer(phrase))
        if not hits:
            if re.search(r"负荷|并网限额|出力|充电功率|放电功率",phrase) and not re.search(r"kWh|MWh|千瓦时|兆瓦时",phrase,re.I):
                raise Unresolved("power_missing","功率分项缺数值或单位")
            continue
        if len(hits)!=1:
            raise Unresolved("power_role","一个分项含多个功率值，无法唯一绑定")
        hit=hits[0]
        roles=[name for name,pattern in ROLE.items() if re.search(pattern,phrase)]
        if len(roles)!=1:
            raise Unresolved("power_role","功率分项的作用不唯一")
        value=Decimal(hit["number"])
        if value < 0:raise Unresolved("power_sign","功率方向与正值分项约定不符")
        value*=1000 if hit["unit"].lower() in {"mw","兆瓦"} else 1
        groups[roles[0]].append(value)
        pointers.append(span(phrase,clause.start(),hit,0,roles[0]))
    if not groups["loads"] or not groups["caps"]:
        raise Unresolved("power_missing","缺少负荷或并网限额")
    net=sum(groups["loads"])-sum(groups["generation"])
    cap=min(groups["caps"])
    if net<0:raise Unresolved("export","存在反送电，需补充上网及计量边界")
    return net, net<=cap, pointers, {"loads_kw":list(map(float,groups["loads"])),
        "generation_kw":list(map(float,groups["generation"])),"cap_kw":float(cap),"unit":"kW"}


def single(pattern,text,role,offset=0):
    hits=list(re.finditer(pattern,text))
    if len(hits)!=1:raise Unresolved("role_missing",f"{role} 需要唯一且明确的原文记录")
    return hits[0]["v"], span(text,offset,hits[0],"v",role)


def temporal_value(raw):
    if "-" in raw:
        try:return date.fromisoformat(raw).toordinal(), "iso"
        except ValueError:raise Unresolved("date","日期无效")
    if not 1<=int(raw)<=31:raise Unresolved("date","月内日期无效")
    return int(raw), "day"


def parse_versions(text):
    if REGIONS.search(text) or re.search(r"另有规定|另行适用|豁免|例外|替代条款|条件生效",text):
        raise Unresolved("scope","记录存在不适用辖区、特殊边界或优先条款，需补充来源")
    review,p1=single(rf"(?:审查|审核|核验|复核)(?:日期|日|时间)?(?:为|是|在)?\s*(?P<v>{DAY})",text,"审核日期")
    declared,p2=single(rf"(?:申报|报送|申请|送审|提交)(?:数量|值|量)?(?:为|是)?\s*(?P<v>{NUMBER})",text,"申报值")
    today,basis=temporal_value(review)
    pointers=[p1,p2]
    matched=[]
    versions=[]
    for clause in re.finditer(r"[^；;。]+",text):
        phrase=clause.group()
        if not re.search(r"版本|旧版|新版|末版|首版",phrase):
            if re.search(r"限额|限值|上限|不超过",phrase):
                raise Unresolved("role_missing","存在没有版本归属的限额")
            continue
        limit,ptr=single(rf"(?:上限|限额|限值|额度|不超过)(?:为|是|=|：)?\s*(?P<v>{NUMBER})",phrase,"版本限额",clause.start())
        pointers.append(ptr)
        edges={}
        for key,label in (("start",r"(?:自|从|起始日为)"),("end",r"(?:截至|至|到)")):
            seek=rf"{label}\s*(?:本月)?\s*(?P<v>{DAY})"
            fields=list(re.finditer(seek,phrase))
            if len(fields)>1:raise Unresolved("date","版本边界不唯一")
            if fields:
                val,scale=temporal_value(fields[0]["v"])
                if scale!=basis:raise Unresolved("date","日期基准不一致")
                edges[key]=val
                pointers.append(span(phrase,clause.start(),fields[0],"v",key))
        lo,hi=edges.get("start"),edges.get("end")
        if not edges or lo is not None and hi is not None and hi<lo:
            raise Unresolved("date","版本区间未定义或倒置")
        # Fail closed if another date or quantity in this clause has no assigned role.
        assigned={(p["start"],p["end"]) for p in pointers}
        for observed in re.finditer(rf"{DAY}|{NUMBER}",phrase):
            if (clause.start()+observed.start(),clause.start()+observed.end()) not in assigned:
                raise Unresolved("date","版本记录含无归属的日期或数量")
        versions.append({"start":lo,"end":hi,"limit":limit})
        if (lo is None or lo<=today) and (hi is None or today<=hi):matched.append(Decimal(limit))
    if not versions:raise Unresolved("role_missing","无可追溯的版本条款")
    if len(matched)!=1:raise Unresolved("version_count","审核日期匹配零个或多个有效版本，需补充版本依据")
    return matched[0], Decimal(declared)<=matched[0], pointers, {"review":review,"declared":declared,"versions":versions,"basis":basis}


NEG=r"尚未签(?:字|批|名)?|未签(?:字|批|名)?|未批准|未授权|没有签字|未会签|签字撤销|审批撤销|撤销签字"
POS=r"已经签字|已签字|已签批|已签名|完成会签|签字齐全|已获批准|已批准|签批齐全"


def parse_permit(text):
    if re.search(r"跨日|次日|不含|不包括当时|时区不同",text):
        raise Unresolved("scope","时间基准或端点超出同日含端点的演练约定")
    readings={};pointers=[]
    for name,label in (("start",r"检测(?:完成|开始|起点)?|核验开始"),
                       ("expiry",r"有效至|有效到|到期|截止"),("clock",r"现在|当前|核验时刻|观察时刻")):
        value,ptr=single(rf"(?:{label})(?:时刻|时间)?(?:在|为|是)?\s*(?:第\s*)?(?P<v>\d+)\s*分钟",text,name)
        readings[name]=int(value)
        pointers.append(ptr)
    if readings["expiry"]<readings["start"]:raise Unresolved("scope","有效期早于检测")
    signed=list(re.finditer(POS,text)); denied=list(re.finditer(NEG,text))
    if signed and denied:raise Unresolved("sign_conflict","签批记录同时含肯定与否定，需核对")
    if not signed and not denied:raise Unresolved("sign_missing","签批证据不明确")
    match=(denied or signed)[0]
    status_clause=re.split(r"[；;，,。]",text[:match.start()])[-1]
    if (re.search(r"若|假如|如果|须待|须由|必须|应当|声称|谎称|尚待核实|无法确认|没有证据证明|不能证明|并非|不是",status_clause)
            or re.search(r"存疑|未核实|待核验",text[match.end():].split("。",1)[0])):
        raise Unresolved("sign_missing","条件性签批表述无法证明已登记状态")
    pointers.append(span(text,0,match,0,"签批状态"))
    left=max(0,readings["expiry"]-readings["clock"])
    allowed=bool(signed) and readings["start"]<=readings["clock"]<=readings["expiry"]
    return left,allowed,pointers,{**readings,"signed":bool(signed),"unit":"min"}


def verify(record, question=None):
    if record.kind=="energy_monthly":
        return monthly_energy_rule.verify(record,question)
    if record.kind=="general":
        raise ValueError("通用演练必须通过有界模型推理并标明核验程度")
    base={"schema":"gullmate.exercise.v1","source":record.source,"kind":record.kind,"scope":record.scope,
          "facts_sha256":hashlib.sha256(record.facts.encode()).hexdigest(),"production_authority":False}
    try:
        if re.search(r"\d{15,}",record.facts):
            raise Unresolved("numeric_range","记录含超过本工具精度范围的数量")
        if record.kind=="berth_clock":
            value,ok,pointers,proof=berth_clock.verify(record.facts,question)
        elif record.kind=="batch_emissions":
            value,ok,pointers,proof=batch_emissions.verify(record.facts,question)
        elif record.kind=="maintenance":
            value,ok,pointers,proof=maintenance_hours.verify(record.facts,question)
        else:
            value,ok,pointers,proof={"power":parse_power,"version":parse_versions,"permit":parse_permit,
                                "flow":parse_flow,"unit_cost":parse_unit_cost}[record.kind](record.facts)
    except Unresolved as exc:
        return {**base,"decision":"UNKNOWN","value":None,"reason":exc.code,"detail":str(exc)}
    except ArithmeticError:
        return {**base,"decision":"UNKNOWN","value":None,"reason":"numeric_range","detail":"数值超出可核验精度"}
    if any(record.facts[p["start"]:p["end"]] != p["text"] for p in pointers):raise ValueError("来源定位错误")
    return {**base,"decision":"ALLOW" if ok else "HOLD","value":float(value),"references":pointers,"proof":proof}


def summary(receipt):
    if receipt["kind"]=="energy_monthly":
        return monthly_energy_rule.summary(receipt)
    if receipt["decision"]=="UNKNOWN":
        return "本次演练暂缓判定。"+receipt["detail"]+"。"
    if receipt.get("verification")=="registered_portwatch_series":
        source=receipt["source_receipt"]
        result="满足" if receipt["decision"]=="ALLOW" else "未满足"
        return (f"按 {source['port']} 的登记挂靠记录核算，结果为 {receipt['value']:g} {receipt['proof']['unit']}，"
                f"{result}题给练习条件。模型选择了核算项目，计算依据和对应日期保存在回执中。")
    if receipt["kind"]=="batch_emissions":
        return batch_emissions.summary(receipt)
    if receipt["kind"]=="maintenance":
        return maintenance_hours.summary(receipt)
    if receipt["kind"]=="berth_clock":
        minute=int(receipt["value"])
        label="满足" if receipt["decision"]=="ALLOW" else "未满足"
        return (f"按演练记录 {receipt['source']}，后船最早可在 {minute//60:02d}:{minute%60:02d} 靠泊"
                f"（本作业日第 {minute} 分钟），{label}所给时限。回执附离泊、间隔、到港和截止时间。")
    if receipt["kind"]=="general":
        label="满足所给条件" if receipt["decision"]=="ALLOW" else "未满足所给条件"
        return f"本机模型按演练记录 {receipt['source']} 试算为 {receipt['value']:g}，{label}。这是模型试算值，使用前请核对单位、算法与约束。"
    unit=" "+receipt["proof"]["unit"] if receipt["kind"] in {"flow","unit_cost"} else {"power":" kW","permit":" 分钟","version":"（记录限额单位）"}[receipt["kind"]]
    decision="满足所给演练条件" if receipt["decision"]=="ALLOW" else "未满足所给演练条件"
    return f"按记录 {receipt['source']} 核验，结果为 {receipt['value']:g}{unit}，{decision}。此判断仅用于演练。"
