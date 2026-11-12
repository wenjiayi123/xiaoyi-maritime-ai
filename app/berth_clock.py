"""Earliest berth time for an expressly declared single-day, single-berth exercise."""
import re

STAMP = r"(?:\d{1,2}[:：]\d{2}|(?:当天|当日|本作业日)?第\s*\d{1,4}\s*分钟)"
PREVIOUS = r"(?:前船|前一艘船|上一艘船|前序船)"
NEXT = r"(?:后船|本船|下一艘船)"
LINK = r"\s*(?:(?:时间|时刻)\s*)?(?:为|是|在|于|[：:])?\s*"
RULES = (
    ("departure",re.compile(rf"{PREVIOUS}(?:离泊|离开泊位){LINK}(?P<v>{STAMP})")),
    ("departure",re.compile(rf"{PREVIOUS}\s*(?:于|在)?\s*(?P<v>{STAMP})\s*(?:离泊|离开泊位)")),
    ("arrival",re.compile(rf"{NEXT}(?:到港|抵港|就绪){LINK}(?P<v>{STAMP})")),
    ("clearance",re.compile(r"(?:泊位清空间隔|最小安全间隔|安全间隔|清空间隔|必须再留|需再留)\s*(?:为|是|[：:])?\s*(?P<v>\d{1,4})\s*分钟")),
    ("deadline",re.compile(rf"(?:承诺靠泊(?:时限|期限)|最晚靠泊(?:时刻|时间)?){LINK}(?P<v>{STAMP})")),
    ("deadline",re.compile(rf"(?:承诺靠泊(?:时间|时刻)?|靠泊时间)\s*(?P<op>不得晚于|不晚于|不得迟于|不迟于|必须早于|严格早于|早于)\s*(?P<v>{STAMP})")),
)
SCOPE = re.compile(r"单泊位(?:演练)?|(?:各时刻均为|均为|时间均为)?同一\s*(?:UTC\s*)?(?:作业日|自然日)|统一使用\s*UTC",re.I)


def applicable(facts,question):
    return bool(re.search(r"最早.{0,12}(?:靠泊|靠上泊位)",question)
                and re.search(r"时限|承诺|最迟|截止",question)
                and re.search(r"离泊|清空间隔|安全间隔",facts))


def minute(raw):
    from app.exercise_records import Unresolved
    if ":" in raw or "：" in raw:
        h,m=map(int,re.split("[:：]",raw))
        if h>=24 or m>=60:
            raise Unresolved("invalid_clock","记录中的时钟超出 00:00 至 23:59")
        return h*60+m
    value=int(re.search(r"\d+",raw)[0])
    if value>=1440:
        raise Unresolved("invalid_clock","当日分钟必须在 0 至 1439 之内")
    return value


def verify(facts,question):
    from app.exercise_records import Unresolved,span
    prompt=re.split(r"\n问题[：:]",question or "")[-1].strip()
    if (not applicable(facts,prompt) or not re.search(r"第几分钟|多少分钟|几点|何时|什么时刻",prompt)
            or re.search(r"下发|安排拖轮|现场操作|执行|直接调度|离泊时限|等待时长|等了多久",prompt)):
        raise Unresolved("question_scope","需明确询问本作业日的最早靠泊时间和承诺时限")
    values={}
    pointers=[]
    exclusive=False
    day_known=False
    for piece in re.finditer(r"[^，,；;。\n]+",facts):
        clause=piece[0].strip()
        if not clause:
            continue
        offset=piece.start()+len(piece[0])-len(piece[0].lstrip())
        if SCOPE.fullmatch(clause):
            day_known|="同一" in clause
            continue
        for role,pattern in RULES:
            match=pattern.fullmatch(clause)
            if match:
                break
        else:
            raise Unresolved("unresolved_berth_constraint","有未绑定的时间、作业条件或附加限制，需先补齐或澄清")
        if role in values:
            raise Unresolved("duplicate_berth_field","同一作业字段出现多个值，请确认有效版本")
        raw=match["v"]
        day_known|=any(s in raw for s in ("当天","当日","本作业日"))
        pointers.append(span(clause,offset,match,"v",role))
        values[role]=int(raw) if role=="clearance" else minute(raw)
        if match.groupdict().get("op"):
            exclusive=match["op"] in {"必须早于","严格早于","早于"}
            pointers.append(span(clause,offset,match,"op","comparison"))
    if set(values)!={"arrival","departure","clearance","deadline"} or not day_known:
        raise Unresolved("missing_berth_field","需确认同一作业日、前船离泊、最小间隔、后船到港与承诺时限")
    available=values["departure"]+values["clearance"]
    if available>=1440:
        raise Unresolved("outside_service_day","最早可用时刻已跨日，请提供完整日期与跨日条件")
    first=max(available,values["arrival"])
    ok=first<values["deadline"] if exclusive else first<=values["deadline"]
    return first,ok,pointers,{**values,"berth_available_minute":available,"operator":"<" if exclusive else "<=",
        "unit":"分钟（从本作业日零点起）","formula":"max(arrival, departure + clearance)",
        "scope":"用户声明的单泊位演练，仅核验所给时间条件"}
