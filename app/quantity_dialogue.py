"""Read-only two-part numerical exercise for an explicitly requested deep review."""
import json
import math
import re

SYSTEM = "你是港航记录复算助手。只核对所给演练事实，保留单位和约束，不执行现场操作。"


def split_question(question):
    text = question.strip()
    if "？" in text[:-1] or "?" in text[:-1]:
        pieces = re.split(r"[？?]", text, maxsplit=1)
    else:
        pieces = re.split(r"(?:[，,；;]|以及|及)(?=\s*(?:能否|是否|可否|承诺是否|安排是否|申请是否))", text, maxsplit=1)
    if len(pieces) != 2:
        return None
    number, decision = (part.strip() for part in pieces)
    if not re.search(r"多少|第几|几(?:个|次|分钟|班)|[数量额率值]$", number):
        return None
    if not re.search(r"能否|是否|可否|吗|可行|合规|达标", decision):
        return None
    return number + "？", decision


def decode(choice, field, source):
    if choice.get("finish_reason") != "stop":
        return None
    content = choice["message"].get("content") or ""
    # Local engines can place reasoning in a separate message field or embed closed tags.
    if "</think>" in content:
        content = content.rsplit("</think>", 1)[1]
    elif "<think>" in content:
        return None
    content = content.strip()
    if content.startswith("```") and content.endswith("```"):
        content = re.sub(r"^`{3}(?:json)?\s*", "", content[:-3]).strip()
    try:
        obj = json.loads(content)
    except ValueError:
        return None
    if not isinstance(obj, dict) or set(obj) != {field, "source"} or obj["source"] != source:
        return None
    value = obj[field]
    if field == "value":
        if type(value) not in (float, int) or abs(value)>10**15 or not math.isfinite(value):
            return None
    elif value not in ("ALLOW", "HOLD", "UNKNOWN"):
        return None
    return value


def review(record, question, model, complete):
    split = split_question(question)
    receipt = {"model_role": "separate_quantity_decision", "calls": [],
               "decision": "UNKNOWN", "value": None, "completion_tokens": 0}
    if not split:
        return {**receipt, "reason": "ambiguous_questions", "detail": "请分别写出询问数值和判断条件的两个问题"}
    num_q, decision_q = split
    prefix = f"记录编号 {record.source}。演练事实：{record.facts}\n"
    first = prefix+"只回答这个数量问题："+num_q+" 按问题的单位和取整约定，只返回 JSON 对象 value（所问数值）、source（记录编号）。"

    def generate(field, prompt, cap):
        body = {"model": model, "messages": [{"role":"system","content":SYSTEM},{"role":"user","content":prompt}],
                "chat_template_kwargs":{"enable_thinking":True}, "seed":20261106,
                "temperature":.6, "top_p":.95, "top_k":20, "min_p":0, "max_tokens":cap}
        choice, tokens = complete(body)
        receipt["model"] = model
        finish = choice["finish_reason"]
        receipt["calls"].append({"field":field, "max_tokens":cap, "finish":finish, "completion_tokens":tokens})
        receipt["completion_tokens"] += tokens
        return decode(choice, field, record.source), finish

    for cap in (1024, 2048):
        value, num_finish = generate("value", first, cap)
        reading = (f"第一次数值回答为 {value}，对应“{num_q}”。请自行复核。" if value is not None
                   else "第一次没有得到可核验的数值。")
        second = prefix+reading+"\n现在独立判断："+decision_q+" 只返回 JSON 对象 decision（条件满足 ALLOW、不满足 HOLD、资料不足 UNKNOWN）、source（记录编号）。"
        verdict, decision_finish = generate("decision", second, cap)
        if cap == 1024 and "length" in (num_finish, decision_finish):
            continue
        if value is None or verdict is None:
            return {**receipt, "reason":"incomplete_or_invalid", "detail":"模型没有在生成预算内交付带同一来源编号的完整数值和判断"}
        if verdict == "UNKNOWN":
            return {**receipt, "reason":"model_requires_evidence", "detail":"模型表示给定记录不足以判断所问条件"}
        return {**receipt, "value":value, "decision":verdict, "finish":"stop"}
