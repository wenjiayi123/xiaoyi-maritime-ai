"""Dated check of the Chinese domestic seagoing-ship monthly energy reporting option."""
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]/"data/monthly_energy_20250208"
AS_OF="2025-02-08"
DOC="海危防〔2022〕164号"
HASHES={"msa":"6548df222af018a5965f78805406d3b3b4cdbd6aefff0df24323eeb9ee4cafc0","service":"19d47a42459255c0e9585fd049e54b0658eb81371a322f0d961be95c23b57f14"}
FIELD_NAMES={"chinese_flag":"国籍","gt":"总吨","service":"航行类别","use":"船舶用途","fixed_waters":"固定水域",
             "fixed_route":"固定航线","minutes":"单航次最长航时"}
EMPTY=("待补","未知","未提供","未记录")
TYPES={"中国籍":("chinese_flag",True),"外国籍":("chinese_flag",False),"中国":("chinese_flag",True),"外国":("chinese_flag",False),
       "国内海船":("service","domestic_sea"),"国内航行海船":("service","domestic_sea"),"国际航行海船":("service","international"),
       "内河船舶":("service","inland"),"普通商用货运":("use","ordinary"),"普通商船":("use","ordinary"),"军事船舶":("use","military"),
       "渔业船舶":("use","fishery"),"体育运动船艇":("use","sports")}
KEYS={"国籍":"chinese_flag","登记国籍":"chinese_flag","船籍":"chinese_flag","总吨":"gt","登记总吨":"gt","航行类别":"service",
      "船舶及航行类别":"service","用途":"use","船舶用途":"use","登记船舶用途":"use","固定水域":"fixed_waters","固定航线":"fixed_route",
      "单航次最长航时":"minutes","该模式下各单航次最长航时":"minutes","该运营模式下各单航次的最长航行":"minutes"}
FIELDS=re.compile("("+ "|".join(re.escape(k) for k in sorted(KEYS,key=len,reverse=True)) +r")(?:为|是|=|：|:)\s*(.+)")
YESNO={"确认符合":True,"确认不符合":False,"是":True,"否":False}
DURATION=re.compile(r"(?:(\d{1,7}(?:\.\d{1,3})?)\s*(?:小时|h)\s*)?(?:(\d{1,8})\s*(?:分钟|min))?",re.I)
SOURCES={"msa":"https://www.sh.msa.gov.cn/hsfg/content.jspx?cid=5ab557553ba54c84ba2d81f69877c1d0&key=",
         "service":"https://www.js.msa.gov.cn/art/2025/2/8/art_4571_481.html"}


def applicable(facts,q):
    return bool(re.search(r"月报|按月.{0,3}报告|月度报告",q) and "能耗" in q and (DOC in q or "船舶能耗数据和碳强度管理办法" in q))


def sources():
    lock=json.loads((ROOT/"source-lock.json").read_bytes())
    if lock["historical_date"]!=AS_OF or lock["rule"]!=DOC or set(lock["sources"])!=set(SOURCES):
        raise ValueError("历史条款登记不匹配")
    for key,url in SOURCES.items():
        meta=lock["sources"][key]
        if meta["url"]!=url or meta["sha256"]!=HASHES[key] or hashlib.sha256((ROOT/(key+".html")).read_bytes()).hexdigest()!=HASHES[key]:
            raise ValueError("官方来源快照未通过校验")
    return [{"publisher":"中华人民共和国上海海事局法规库","document":DOC,"articles":[2,6,23],"url":SOURCES["msa"],"sha256":HASHES["msa"]},
            {"publisher":"江苏海事局政务服务指南","document":"船舶能耗数据报告","url":SOURCES["service"],"sha256":HASHES["service"]}]


def typed(key,value):
    if value in EMPTY:return None
    if key in ("chinese_flag","service","use"):
        pair=TYPES.get(value)
        if pair and pair[0]==key:return pair[1]
    elif key=="gt":
        m=re.fullmatch(r"([1-9]\d{0,8})\s*(?:GT|总吨)?",value,re.I)
        if m:return int(m[1])
    elif key.startswith("fixed_") and value in YESNO:
        return YESNO[value]
    elif key=="minutes":
        m=DURATION.fullmatch(value)
        if m and any(m.groups()):
            if m[1] and m[2] and ("." in m[1] or int(m[2])>=60):
                raise ValueError("复合时长记录需核对")
            minutes=Decimal(m[1] or 0)*60+int(m[2] or 0)
            if 0<minutes<=10000000 and minutes==minutes.to_integral_value():return int(minutes)
    raise ValueError(FIELD_NAMES[key]+"的口径或取值无法确认")


def fields(text):
    values={};refs=[];date=None
    for part in re.finditer(r"[^；;，,。\n]+",text):
        segment=part[0].strip()
        if segment in ("其余字段均未提供","上海港历史演练"):continue
        segment=re.sub(r"^档案记载[：:]\s*","",segment)
        if not segment:continue
        stamp=re.fullmatch(r"(?:历史核验日|演练日期|核验日期)\s*(?:为|是|[：:=])?\s*(\d{4}-\d{2}-\d{2})",segment)
        if stamp:
            if date is not None:raise ValueError("历史日期重复或冲突")
            date=stamp[1];key="as_of"
        else:
            assignment=FIELDS.fullmatch(segment)
            if assignment:
                key=KEYS[assignment[1]];value=typed(key,assignment[2].strip())
            elif segment in TYPES:
                key,value=TYPES[segment]
            elif match:=re.fullmatch(r"总吨\s*([1-9]\d{0,8})",segment):
                key,value="gt",int(match[1])
            elif match:=re.fullmatch(r"确认(属于|不属于)(固定水域|固定航线)运行",segment):
                key,value=KEYS[match[2]],match[1]=="属于"
            else:raise ValueError("有未登记的事实、例外或冲突字段，需要核对原始记录")
            if key in values:raise ValueError(FIELD_NAMES[key]+"重复出现，需要确认唯一事实")
            values[key]=value
        pos=text.index(segment,part.start(),part.end())
        refs.append({"role":"历史核验日" if key=="as_of" else FIELD_NAMES[key],"start":pos,"end":pos+len(segment),"text":segment})
    return date,{k:values.get(k) for k in FIELD_NAMES},refs


def assess(v):
    if v["chinese_flag"] is False or v["gt"] is not None and v["gt"]<400 or v["service"] not in (None,"domestic_sea") or v["use"] not in (None,"ordinary"):
        return "OUTSIDE"
    if any(v[k] is None for k in ("chinese_flag","gt","service","use")):return "UNKNOWN"
    t=v["minutes"]
    branches=((v["fixed_waters"],240),(v["fixed_route"],1440))
    if any(f is True and t is not None and t<=limit for f,limit in branches):return "ELIGIBLE"
    if all(f is False or t is not None and t>limit for f,limit in branches):return "INELIGIBLE"
    return "UNKNOWN"


def verify(record,question):
    base={"schema":"gullmate.exercise.v1","source":record.source,"kind":"energy_monthly","scope":"exercise","production_authority":False,
          "facts_sha256":hashlib.sha256(record.facts.encode()).hexdigest(),"decision":"UNKNOWN","value":None,
          "verification":"historical_named_provision","rule":DOC,"as_of":None}
    try:
        base["sources"]=sources()
        q=re.split(r"\n问题[：:]",question or "")[-1].strip().rstrip("？?")
        if q not in (f"按{DOC}第六条，这艘船能否选择按月报告能耗",f"按{DOC}第六条，本船能否选用能耗月报",
                     "按《船舶能耗数据和碳强度管理办法》第六条，是否符合能耗月度报告选项"):
            raise ValueError("核验范围仅限具名条款的国内海船能耗月度报告选项")
        date,vals,refs=fields(record.facts)
        base.update(as_of=date,references=refs)
        if date!=AS_OF:raise ValueError("需要登记已核验的历史日期 2025-02-08")
        label=assess(vals)
        base.update(decision=label,proof={"facts":vals,"scope":"国内航行海船月度能耗报送选项","article":6,"snapshot":AS_OF})
        if label=="UNKNOWN":
            base.update(reason="incomplete_ship_evidence",detail="所给事实不足以唯一判断该款；待核字段包括"+"、".join(FIELD_NAMES[k] for k,v in vals.items() if v is None))
        return base
    except (ValueError,OSError,KeyError) as e:
        return {**base,"reason":"source_or_field_unresolved","detail":str(e)}


def summary(receipt):
    words={"ELIGIBLE":"已登记事实满足该历史条款的月度报告选择条件。","INELIGIBLE":"本船在所问条款的业务范围内，两项月度报告选择条件均不成立。",
           "OUTSIDE":"已登记事实表明本船不属于所问国内海船月度报告选项的范围。","UNKNOWN":"暂缓判断。"+receipt.get("detail","资料不足")+"。"}
    text=f"演练记录 {receipt['source']}，"+words[receipt["decision"]]
    if receipt.get("sources"):
        text+=" 核对范围为 2025-02-08 的能耗月报选择，不涉及其他报送义务。依据见海危防〔2022〕164号第二、六、二十三条。"+SOURCES["msa"]
    return text
