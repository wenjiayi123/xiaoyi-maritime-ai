"""Bind historical-case amendments to literal observations. Keep ambiguous or unbound changes unknown."""
from decimal import Decimal
import hashlib
import json
import re

ABSENT=object()
ROLE={"in_china":r"中国|境内|境外","in_shanghai_port":r"上海|外省|辖区","waters":r"沿海|内河|水域|航区",
      "liquid_cargo_ship":r"船型|液货|集装箱船","oil_chemical_terminal":r"油气化工|码头类别|码头分类",
      "ship_receiver":r"受电","berth_supply":r"泊位.*供电|码头.*供电","effective_alternative_used":r"替代",
      "unavailability_exception":r"故障|事故|气候|天气|妨碍|匹配|紧急|无法接电","berth_minutes":r"靠泊|停靠|在泊|时长|分钟|小时"}
UNSURE=re.compile(r"不详|未知|未查明|不知|不能确定|不确定|无法确定|尚不清楚|无从判定|待确认|未证实|无法判断|无法确认|描述含糊|没有可信记录|没有可靠记录|是否.{0,12}(?:没有|无|缺少).{0,4}证据|能否.{0,10}(?:无|没有)证据|尚未核实|没有记录|未记录|没有证据判断")


def proposal_request(baseline,story,model_name):
    patch={"type":"object","properties":{"field":{"type":"string","enum":list(ROLE)},"value":{"type":"string"},
           "quote":{"type":"string"}},"required":["field","value","quote"],"additionalProperties":False}
    schema={"type":"object","properties":{"changes":{"type":"array","items":patch,"maxItems":8}},
            "required":["changes"],"additionalProperties":False}
    instruction=("你为历史演练提取用户陈述的变化，不判断法律任务。未改动的事实不重述。"
        "quote 逐字引用变更句的实际文字。true/false 表示确认状态，unknown 表示证据不足。waters 用 coastal/inland。"
        "故障类型用 none/temporary_failure/incompatible/emergency_prevents_use。"
        "若时长只知上限或下限，value 写原文字面范围，勿虚构精确分钟。")
    return {"model":model_name,"messages":[{"role":"system","content":instruction},
        {"role":"user","content":"原登记事实："+json.dumps(baseline.model_dump(mode="json"),ensure_ascii=False)+"\n变更句："+story}],
        "temperature":0,"seed":7147,"max_tokens":320,"chat_template_kwargs":{"enable_thinking":False},
        "response_format":{"type":"json_object","schema":schema}}
QUANTITY=r"(?:\d+(?:\.\d+)?|[零一二两三四五六七八九十百]{1,5})"
DIGITS={ch:v for ch,v in zip("零一二两三四五六七八九",(0,1,2,2,3,4,5,6,7,8,9))}


def quantity(n):
    if re.fullmatch(r"\d+(?:\.\d+)?",n):return Decimal(n)
    if n in DIGITS:return Decimal(DIGITS[n])
    if n.count("十")==1 and "百" not in n:
        a,b=n.split("十")
        if (not a or a in DIGITS) and (not b or b in DIGITS):
            return Decimal(10*(DIGITS[a] if a else 1)+DIGITS.get(b,0))
    raise ValueError("时长文字不在已验证范围")


def duration_change(clause):
    if not re.search(r"靠泊|停靠|在泊|时长|停了|靠了",clause) and not re.fullmatch(
            rf"\s*(?:恰好|恰满|不足|不超过|最多|至少|超过|只知|只有)?\s*{QUANTITY}\s*(?:小时|分钟)\s*",clause):
        return ABSENT
    interval=re.search(rf"({QUANTITY})\s*(小时|分钟)?\s*(?:至|到|～|~)\s*({QUANTITY})\s*(小时|分钟)",clause)
    if interval:
        a,u,b,v=interval.groups()
        if re.search(r"不含|不包括端点",clause):return None
        return {"lower":float(quantity(a)*(60 if (u or v)=="小时" else 1)),
                "upper":float(quantity(b)*(60 if v=="小时" else 1))}
    seen=list(re.finditer(rf"({QUANTITY})\s*(小时|分钟)",clause))
    if not seen:return None if UNSURE.search(clause) else ABSENT
    # This contract deliberately refuses disjoint alternatives and compound clock formats it cannot prove.
    if len(seen)!=1:return None
    hit=seen[0];amount=float(quantity(hit[1])*(60 if hit[2]=="小时" else 1))
    preceding=clause[:hit.start()].rstrip()
    if re.search(r"不超过|至多|最多|不多于",preceding):return {"upper":amount,"upper_inclusive":True}
    if re.search(r"至少|不少于|不短于|不低于",preceding):return {"lower":amount,"lower_inclusive":True}
    if re.search(r"不足|少于|小于|不到",preceding):return {"upper":amount,"upper_inclusive":False}
    if re.search(r"超过|多于|长于",preceding):return {"lower":amount,"lower_inclusive":False}
    if UNSURE.search(clause):return None
    return amount


def observation(key,clause):
    if not re.search(ROLE[key],clause):return ABSENT
    if key=="berth_minutes":return duration_change(clause)
    if key=="in_china" and UNSURE.search(clause):
        if re.search(r"境外|是否.{0,3}(?:在|属于)?中国|国家不详",clause):return None
        if "上海港" in clause and re.search(r"中国(?:另|其他)",clause):return True
        return ABSENT
    if key=="waters" and "上海港" in clause and "还是" in clause and "内河" not in clause:return ABSENT
    if UNSURE.search(clause):return None
    if key=="in_china":
        if re.search(r"境外|中国以外",clause):return False
        if re.search(r"中国|境内",clause):return True
    if key=="in_shanghai_port":
        if re.search(r"不在上海港|不是上海港|上海港以外|外省沿海港|上海以外",clause):return False
        if re.search(r"仍在上海|属于上海港|上海港的泊位|在上海港靠泊",clause):return True
    if key=="waters":
        coastal="沿海" in clause; inland="内河" in clause
        if coastal!=inland:return "coastal" if coastal else "inland"
    if key=="liquid_cargo_ship":
        if re.search(r"非液货船|不是液货船|不属于液货船|普通集装箱船",clause):return False
        if re.search(r"(?:改为|属于|为|系|是)液货船",clause):return True
    if key=="oil_chemical_terminal":
        if re.search(r"非油气化工码头|不是油气化工码头|不属于油气化工码头",clause):return False
        if re.search(r"(?:属于|改为|为|是)油气化工码头",clause):return True
    if key=="ship_receiver":
        if re.search(r"(?:不具备|没有|无|未配备)受电设施",clause):return False
        if re.search(r"(?:有|具备|配有)受电设施|受电设施正常",clause):return True
    if key=="berth_supply":
        if re.search(r"临时故障",clause):return ABSENT
        if re.search(r"不具备.{0,5}供电能力|没有.{0,5}供电能力",clause):return False
        if re.search(r"具备.{0,5}供电能力|正常供电",clause):return True
    if key=="effective_alternative_used":
        if re.search(r"(?:没有|未|未曾)(?:采用|使用|采取)(?:有效)?替代",clause):return False
        if re.search(r"(?:采用|使用|采取)(?:了)?有效替代|有效替代措施并已使用",clause):return True
    if key=="unavailability_exception":
        if re.search(r"没有妨碍|不妨碍|没有影响接电",clause):return "none"
        if re.search(r"接口不匹配|设施不匹配",clause):return "incompatible"
        if re.search(r"临时.{0,4}故障",clause):return "temporary_failure"
        if re.search(r"气候|天气|事故|紧急",clause) and re.search(r"无法|不能",clause):return "emergency_prevents_use"
    return ABSENT


def bind(baseline,story,proposal):
    original=baseline.model_dump(mode="json")
    facts=original.copy();proof=[];rejected=[];resolved={};pending=set()
    phrases=list(re.finditer(r"[^。；;，,但]+",story))
    for key in ROLE:
        for phrase in phrases:
            fragment=phrase.group()
            try:value=observation(key,fragment)
            except (ValueError,ArithmeticError):value=None
            if value is ABSENT:continue
            if key in resolved and value!=resolved[key]:value=None
            resolved[key]=value
            proof.append({"field":key,"value":value,"start":phrase.start(),"end":phrase.end(),"quote":fragment,"origin":"source_rule"})
    for row in proposal.get("changes",[]):
        key=row.get("field");quote=row.get("quote")
        if key not in ROLE:raise ValueError("未登记的变更字段")
        # The operator explicitly supplies the baseline. A model proposal cannot invalidate a
        # baseline field that the supplied amendment never mentions.
        mentions_field=bool(re.search(ROLE[key],story))
        if not isinstance(quote,str) or len(quote.strip())<2 or quote not in story:
            rejected.append({"field":key,"reason":"模型引文无法定位"})
            if mentions_field and key not in resolved:pending.add(key)
            continue
        if key not in resolved:
            proposed=row.get("value")
            known=original.get(key)
            same=(proposed=="unknown" and known is None or proposed=="true" and known is True or
                  proposed=="false" and known is False or isinstance(known,str) and proposed==known)
            if mentions_field and not same:pending.add(key)
            rejected.append({"field":key,"reason":"未以证据确定新值"})
        else:
            verified=resolved[key]
            word="unknown" if verified is None else str(verified).lower()
            agrees=str(row.get("value","")).lower()==word
            if not agrees:
                rejected.append({"field":key,"reason":"模型建议与来源核验值不同"})
            proof.append({"field":key,"value":resolved[key],"start":story.index(quote),"end":story.index(quote)+len(quote),
                          "quote":quote,"origin":"model_proposal_agreed" if agrees else "model_proposal_corrected"})
    if not resolved and not pending and not re.fullmatch(r"\s*(?:无其他变化|其余照旧|没有变更|沿用原记录|没有其他改动|记录保持不变|上述基础事实均不变|未作任何变更|仍按原记录)[。.]?\s*",story):
        raise ValueError("变更文字无法完整核对")
    for key in pending:resolved[key]=None
    if "in_china" in resolved and "in_shanghai_port" not in resolved and resolved["in_china"] is not True:
        resolved["in_shanghai_port"]=False if resolved["in_china"] is False else None
    for key,value in resolved.items():
        if key=="berth_minutes":
            facts["berth_minutes"]=None if isinstance(value,dict) else value
            facts["berth_range"]=value if isinstance(value,dict) else None
        else:facts[key]=value
    return type(baseline).model_validate(facts),{"text_sha256":hashlib.sha256(story.encode()).hexdigest(),
        "evidence":proof,"unverified_fields":sorted(pending),"discarded_proposals":rejected}
