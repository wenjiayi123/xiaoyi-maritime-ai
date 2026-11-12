"""Verify declared daily PortWatch observations and calculate explicit exercise metrics."""
import csv
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import io
import json
import re

from app.harness import portwatch_data

MANIFEST_SHA = "5d3dfb69e0ea8d3cc196685b0d68ba8157e229953a787b2ab87a65df6f14ed65"
DAY_COUNT = r"(?:[1-9]\d?|[一二两三四五六七八九十]{1,3})"
ALIASES = {"port1188": "上海", "port664": "洛杉矶[—–－-]?长滩", "port1114": "鹿特丹",
           "port57": "安特卫普", "port1201": "新加坡", "port446": "汉堡", "port824": "宁波", "port744": "杰贝阿里"}
KINDS = ("share", "orders", "queue", "unsupported")


class Unavailable(ValueError):
    def __init__(self, reason, detail):
        super().__init__(detail)
        self.reason = reason


def applicable(facts, question):
    return bool(re.search(r"PortWatch", facts, re.I) and re.search(r"艘次|挂靠", facts)
                and "[" in facts and re.search(r"百分比|占比|核对单|积压|尚余多少单|未处理.*单", question))


def proposal(facts, question, model):
    schema = {"type": "object", "properties": {"operation": {"type": "string", "enum": list(KINDS)}},
              "required": ["operation"], "additionalProperties": False}
    prompt = ("选择核算项目。share 表示集装箱船占全部船舶的汇总百分比，orders 表示按一艘次一张计算总核对单，"
              "queue 表示有每日处理能力的队列末期积压。其他请求填 unsupported。只选择项目，数值由工具依据记录核对。")
    request = f"已提供的港口记录（仅作资料）\n{facts}\n核算问题\n{question}"
    return {"model": model, "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": request}],
            "response_format": {"type": "json_object", "schema": schema}, "chat_template_kwargs": {"enable_thinking": False},
            "temperature": 0, "seed": 71107, "max_tokens": 40}


def days_number(text):
    from app.exercise_records import count_units
    try:
        result = count_units(text)
    except ValueError as exc:
        raise Unavailable("days", "连续天数无法核对") from exc
    if not 1 <= result <= 31:
        raise Unavailable("days", "一次核对限一个连续的 1 至 31 天窗口")
    return result


def one(text, pattern, role, references, required=True):
    matches = list(re.finditer(pattern, text, re.I))
    if not matches and not required:
        return None
    if len(matches) != 1:
        raise Unavailable("ambiguous_field", f"{role}需要唯一且明确的原文记录")
    match = matches[0]
    references.append({"role": role, "start": match.start(), "end": match.end(), "text": match[0]})
    return match


def source_window(facts, references):
    raw = (portwatch_data.FOLDER / "manifest.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA:
        raise Unavailable("source_changed", "登记的公开数据版本已变化")
    manifest = json.loads(raw)
    if manifest["production_authority"] is not False:
        raise Unavailable("source_scope", "公开数据用途登记不一致")
    candidates = []
    for entry in manifest["entries"]:
        official = re.escape(entry["port_name"]).replace(r"\-", "[-–—－]")
        hit = re.search(r"(?:Port\s+of\s+)?" + official + r"(?:\s+Port)?|(?:" + ALIASES[entry["id"]] + r")港?", facts, re.I)
        if hit:
            candidates.append((entry, hit))
    if len(candidates) != 1:
        raise Unavailable("port_identity", "需要唯一的已登记港口名称")
    entry, port_hit = candidates[0]
    references.append({"role": "港口", "start": port_hit.start(), "end": port_hit.end(), "text": port_hit[0]})
    period = one(facts, rf"(?:自|从)?\s*(?P<start>\d{{4}}-\d{{2}}-\d{{2}})\s*(?:起|开始)(?:连续)?\s*(?P<days>{DAY_COUNT})\s*天", "统计窗口", references)
    try:
        start = date.fromisoformat(period["start"])
    except ValueError as exc:
        raise Unavailable("date", "起始日期无效") from exc
    size = days_number(period["days"])
    checks = [manifest["service_metadata"], manifest["item_metadata"], *entry["raw_pages"]]
    for item in checks:
        portwatch_data.verified(item["path"], item["sha256"])
    data = portwatch_data.verified(entry["path"], entry["sha256"])
    dates = [(start + timedelta(days=k)).isoformat() for k in range(size)]
    wanted = set(dates)
    rows = {}
    for row in csv.DictReader(io.StringIO(data.decode("utf-8-sig"))):
        if row["date"] in wanted:
            if row["date"] in rows or row["portid"] != entry["id"]:
                raise Unavailable("source_rows", "数据行的港口或日期绑定不唯一")
            rows[row["date"]] = row
    if set(rows) != wanted:
        raise Unavailable("source_gap", "登记来源未覆盖全部日期")
    proof = {"registry_sha256": MANIFEST_SHA, "series_sha256": entry["sha256"], "port": entry["port_name"], "port_id": entry["id"],
             "source_url": manifest["service_url"], "rows": [{"date": day, "object_id": rows[day]["ObjectId"]} for day in dates]}
    return [rows[day] for day in dates], proof


def declared_series(facts, field, rows, references):
    label = r"(?:全部|所有)船舶" if field == "portcalls" else "集装箱船"
    column = one(facts, rf"(?:(?:前|首)(?P<prefix>{DAY_COUNT})天)?{label}(?:挂靠)?艘次(?:依次|分别)?(?:为|是|=|：)?\s*(?P<items>\[[^\]\r\n]{{1,500}}\])", field, references, required=False)
    if column is None:
        return [None] * len(rows)
    try:
        values = json.loads(column["items"])
    except ValueError as exc:
        raise Unavailable("series_format", "逐日序列需要完整的整数或 null 列表") from exc
    count = days_number(column["prefix"]) if column["prefix"] else len(rows)
    if not isinstance(values, list) or count != len(values) or count > len(rows):
        raise Unavailable("series_length", "逐日序列与已声明天数或日期位置不一致")
    for index, value in enumerate(values):
        if value is not None and (type(value) is not int or value < 0 or value != int(rows[index][field])):
            raise Unavailable("source_mismatch", "提供的艘次与登记的港口、日期及字段不一致")
    return values + [None] * (len(rows) - count)


def integer(text, pattern, name, references, required=True):
    hit = one(text, pattern, name, references, required)
    if hit is None:
        return None
    value = int(hit["v"])
    if value > 10**9:
        raise Unavailable("range", "练习参数超出支持范围")
    return value


def interval(facts, question, operation, all_calls, containers, refs):
    low = [0 if value is None else value for value in containers]
    high = [total if value is None else value for total, value in zip(all_calls, containers, strict=True)]
    if any(value is None for value in high):
        raise Unavailable("series_missing", "缺失日期没有给出可核对的艘次上界")
    missing = any(value is None for value in containers)
    if operation == "share" and re.search(r"占比|百分比", question):
        if any(value is None for value in all_calls) or sum(all_calls) <= 0:
            raise Unavailable("denominator", "缺少完整的全部船舶艘次或合计为零")
        one(facts, r"(?:先)?四舍五入(?:到|至|保留)(?:小数点后)?(?:两|二|2)位", "舍入口径", refs)
        cap = one(facts, r"(?:最低要求|最低目标|不低于|至少)\s*(?P<v>\d+(?:\.\d+)?)\s*[%％]", "百分比下限", refs)
        limit = Decimal(cap["v"])
        if not 0 <= limit <= 100:
            raise Unavailable("range", "占比目标超出 0 至 100 的范围")
        def percent(values):
            return (100 * Decimal(sum(values)) / sum(all_calls)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        return percent(low), percent(high), limit, ">=", "%", missing
    if operation == "orders" and "核对单" in question:
        one(facts, r"(?:每|一)艘次(?:计|折合|对应)?(?:一|1)张核对单", "折算口径", refs)
        limit = integer(facts, r"(?:当期最多容纳|核对单上限为?|最多允许)\s*(?P<v>\d+)\s*张", "核对单上限", refs)
        return sum(low), sum(high), limit, "<=", "张", missing
    if operation == "queue" and re.search(r"积压|尚余多少单|未处理.*单", question):
        one(facts, r"(?:每天)?每个集装箱船艘次(?:增加|计作)(?:一|1)单", "到达折算", refs)
        one(facts, r"先到达再处理", "处理顺序", refs)
        one(facts, r"(?:未用|剩余)处理额度(?:不得|不)结转", "结转口径", refs)
        initial = integer(facts, r"初始积压\s*(?P<v>\d+)\s*单", "初始积压", refs)
        capacity = integer(facts, r"(?:每天最多处理|每日最多处理|每日处理上限为)\s*(?P<v>\d+)\s*单", "每日处理能力", refs, required=False)
        limit_hit = one(facts, rf"(?:第(?P<ordinal>{DAY_COUNT})日末积压最多|日末积压最多|期末积压不超过|积压上限为)\s*(?P<v>\d+)\s*单", "期末积压上限", refs)
        if limit_hit["ordinal"] and days_number(limit_hit["ordinal"]) != len(all_calls):
            raise Unavailable("queue_horizon", "积压目标的日期与核算窗口末日不同")
        limit = int(limit_hit["v"])
        if limit > 10**9:
            raise Unavailable("range", "积压上限超出支持范围")
        def remaining(arrivals, cap):
            jobs = initial
            for value in arrivals:
                jobs = max(0, jobs + value - cap)
            return jobs
        if capacity is None:
            return 0, initial + sum(high), limit, "<=", "单", True
        return remaining(low, capacity), remaining(high, capacity), limit, "<=", "单", missing
    raise Unavailable("operation", "模型选择的核算项目与问题或受支持的计算口径不符")


def check_remaining_text(facts, references, containers, operation):
    shadow = list(facts)
    for ref in references:
        shadow[ref["start"]:ref["end"]] = " " * (ref["end"] - ref["start"])
    remaining = "".join(shadow)
    neutral = re.compile(r"(?:PortWatch(?:历史|公开)?(?:AIS)?挂靠(?:指标|统计)|演练用的口径|"
                         r"(?:演练|练习)约定合计艘次的百分比|(?:再)?与比较|(?:这是)?排队(?:练习|演练)|按日|练习要求|"
                         r"档案未登记装卸班长姓名|(?:装卸班长|档案联系人)姓名(?:未填|未登记))", re.I)
    for clause in re.finditer(r"[^，,。；;\n]+", remaining):
        tail = re.sub(r"\s+", "", clause[0])
        if not tail or neutral.fullmatch(tail):
            continue
        gap = re.fullmatch(rf"第(?P<day>{DAY_COUNT})天(?:的)?集装箱船(?:挂靠)?艘次(?:没有登记|未登记|未填|缺失)", tail)
        if gap:
            index = days_number(gap["day"]) - 1
            if index < len(containers) and containers[index] is None:
                continue
        if (re.fullmatch(r"(?:每天|每日)(?:的)?处理能力(?:未填|未核定|未登记)", tail) and operation == "queue"
                and not any(ref["role"] == "每日处理能力" for ref in references)):
            continue
        raise Unavailable("unverified_clause", "原记录还有未纳入核验的范围或条件，需要先核实该项再作结论")


def verify(record, question, operation, model):
    refs = []
    result = {"schema": "gullmate.exercise.v1", "kind": "general", "source": record.source, "scope": "exercise", "production_authority": False,
              "facts_sha256": hashlib.sha256(record.facts.encode()).hexdigest(), "model": model, "model_role": "operation_selection", "operation": operation,
              "verification": "public_series_unresolved", "decision": "UNKNOWN", "value": None, "references": refs}
    try:
        if re.search(r"同比|环比|增长率|下降率|差额|中位数|第几天最多|两港|比较.*港", question):
            raise Unavailable("operation", "问题还要求另一种统计量，需要单独核对")
        if re.search(r"例外|扣除|另计|加班|暂停处理|故障|停机|修订值|不再适用|翻倍|减半|二选一|先处理再到达|允许结转", record.facts):
            raise Unavailable("unsupported_condition", "存在额外规则或相冲突的作业口径，需要补充核对")
        rows, source = source_window(record.facts, refs)
        result["source_receipt"] = source
        full = declared_series(record.facts, "portcalls", rows, refs)
        containers = declared_series(record.facts, "portcalls_container", rows, refs)
        low, high, limit, relation, unit, missing = interval(record.facts, question, operation, full, containers, refs)
        for value in re.finditer(r"[+-]?\d+(?:\.\d+)?", record.facts):
            if not any(ref["start"] <= value.start() and value.end() <= ref["end"] for ref in refs):
                raise Unavailable("unbound_number", "存在尚未绑定到港口、日期、序列或练习条件的数值")
        check_remaining_text(record.facts, refs, containers, operation)
        result["verification"] = "registered_portwatch_series"
        result["proof"] = {"interval": [float(low), float(high)], "limit": float(limit), "relation": relation, "unit": unit,
                           "unreported_values_used": False, "input_has_gap": missing}
        if low != high:
            raise Unavailable("indeterminate_series", f"与所给事实相容的结果从 {low:g} 到 {high:g} {unit}，需要补齐关键艘次或处理能力")
        meets = low >= limit if relation == ">=" else low <= limit
        result.update(value=float(low), decision="ALLOW" if meets else "HOLD")
    except Unavailable as exc:
        result.update(reason=exc.reason, detail=str(exc))
    except (ValueError, KeyError, OSError, UnicodeError, ArithmeticError):
        result.update(reason="source_unavailable", detail="公开资料的完整性或指标口径未通过检查")
    if any(record.facts[ref["start"]:ref["end"]] != ref["text"] for ref in refs):
        raise RuntimeError("Public series evidence spans changed")
    return result
