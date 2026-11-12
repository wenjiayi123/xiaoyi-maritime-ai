"""Recognize complete, declared price/check records. Ambiguous prose requires a sheet."""
import re
import unicodedata

from pydantic import ValidationError

from app.offer_comparison import Offer, OfferSheet

NUMBER = r"(?:0|[1-9]\d{0,11})(?:\.\d{1,6})?"
REFERENCE = r"[A-Za-z][A-Za-z0-9_.-]{0,31}"
OFFER_ID = r"[A-Za-z0-9\u4e00-\u9fff_.-]{1,32}"
COST = r"(?:元|CNY)"
RATE = r"(?:(?:元|CNY)/(?:kWh|千瓦时))"
STATE = r"(?:不满足|未满足|满足)(?:吃水约束|吃水限制|供电容量|容量约束)?|违反(?:吃水约束|吃水限制|供电容量|容量约束)|不可行|可行|待核验"
END = re.compile(r"(?:问|请问|求)\s*(?:(?:可采用候选中|已核验方案中|可行候选中)的)?最低(?:可行)?(?:报价|成本|费用)(?:是多少)?(?:,\s*单位\s*(?:CNY(?:/kWh)?|元(?:/千瓦时)?))?[。?]?\s*$",re.I)


def outcome(word):
    if word.startswith(("违反", "不满足", "未满足", "不可行")):
        return "fail"
    return "unknown" if word == "待核验" else "pass"


def names(text):
    if re.fullmatch(r"[甲乙丙丁戊己庚辛壬癸]+", text):
        return list(text)
    return [label.strip() for label in re.split(r"、|和|及|,", text)]


def from_question(question: str) -> tuple[bool, OfferSheet | None]:
    text = unicodedata.normalize("NFKC", question).strip()
    berth = bool(re.search(r"吃水|泊位", text))
    power = bool(re.search(r"供电容量|岸电|元/(?:kWh|千瓦时)|CNY/kWh", text, re.I))
    wants_price = bool(re.search(r"最低(?:可行)?(?:价|报价|成本|费用)|最便宜|哪(?:个|项)候选.*(?:便宜|低)", text))
    if not (wants_price and (berth or power) and re.search(r"候选|报价方案|核验记录",text)):
        return False, None
    end = END.search(text)
    if berth == power or not end:
        return True, None
    profile = "berth" if berth else "shore_power"
    unit = COST if berth else RATE
    expected_units = {"CNY", "元"} if berth else {"CNY/kWh", "元/千瓦时"}
    requested_unit = re.search(r"单位\s*([^。?\s]+)",end[0])
    if requested_unit and requested_unit[1] not in expected_units:
        return True, None
    body = text[:end.start()].strip().removesuffix("。").strip()
    try:
        rows = _row_records(body,unit) or _parallel_records(body,unit)
        if rows:
            return True, OfferSheet(profile=profile, offers=rows)
    except (ValidationError,ValueError):
        pass
    return True, None


def _row_records(body, unit):
    source = re.fullmatch(rf"(?:候选|报价记录|候选记录)\s*({REFERENCE})\s*:\s*(.+)",body,re.S)
    if not source:
        return None
    rows=[]
    for declaration in source[2].split(";"):
        row=re.fullmatch(rf"\s*({OFFER_ID})\s*(?:成本|报价|费用)\s*({NUMBER})\s*({unit})\s*(?:,|但)?\s*({STATE})\s*",declaration,re.I)
        if not row:
            return None
        rows.append(Offer(id=row[1],price=row[2],quote_ref=source[1],assessment=outcome(row[4]),check_ref=source[1]))
    return rows


def _parallel_records(body, unit):
    pair = re.fullmatch(rf"(?:计划|报价|报价记录)\s*({REFERENCE})\s*:\s*(.+?)\s*({unit})\s*分别为候选(.+?)(?:的)?报价。\s*(?:核验|核验记录)\s*({REFERENCE})\s*:\s*(.+)",body,re.I|re.S)
    if not pair:
        return None
    prices=[p.strip() for p in re.split(r"、|,",pair[2])]
    ids=names(pair[4])
    if len(ids)!=len(prices) or any(not re.fullmatch(NUMBER,p) for p in prices):
        return None
    checks={}
    for clause in pair[6].split(";"):
        match=re.fullmatch(rf"\s*(.+?)(?:均|都)?\s*({STATE})\s*",clause)
        if not match:
            return None
        for key in names(match[1].strip()):
            if key not in ids or key in checks:
                return None
            checks[key]=outcome(match[2])
    return [Offer(id=k,price=p,quote_ref=pair[1],assessment=checks.get(k,"unknown"),check_ref=pair[5] if k in checks else None)
            for k,p in zip(ids,prices)]
