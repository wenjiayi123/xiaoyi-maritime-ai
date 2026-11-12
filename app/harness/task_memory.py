"""Select explicit user memories within the remaining task context budget."""
import math
import json
import ast
import re
import unicodedata
from collections import Counter
from decimal import Decimal, InvalidOperation

from app.harness.contracts import digest, encoded


def memory_request(task):
    text = " ".join([task["goal"], *[r["text"] for r in task.get("inputs", []) if r.get("text")]])
    requested = bool(re.search(r"(?:保存|记下|留存)(?:过)?的|(?:先前|之前|以前|已经|已)(?:保存|记下|留存)的?|我的记忆|my saved|previously saved|saved note", text, re.I))
    names = re.findall(r'(?:项目|记忆|记录|档案)\s*(?:名为|名称为|[：:])?\s*[“"《]([^”"》]{1,80})[”"》]', text)
    return requested, names


def terms(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    tokens = set(re.findall(r"[a-z0-9]+(?:[-_/][a-z0-9]+)*", text))
    for segment in re.findall(r"[\u3400-\u9fff]+", text):
        tokens.update(segment[i:i + 2] for i in range(len(segment) - 1))
    return tokens


def ranked_memories(task, memories):
    """Use task terms and the latest steering input. Preserve recency on ties."""
    newest = next((row["text"] for row in reversed(task.get("inputs", [])) if row.get("text")), "")
    goal_terms = terms(task["goal"])
    steering_terms = terms(newest)
    records = [(row, terms(row["label"]), terms(row["text"])) for row in memories]
    frequency = Counter(term for _, labels, content in records for term in labels | content)
    query = goal_terms | steering_terms
    weights = {term: math.log1p(len(records) / count) * (2 if term in steering_terms else 1)
               for term, count in frequency.items() if term in query}

    def score(record):
        _, labels, content = record
        return sum(weights[t] * (2 if t in labels else 1) for t in sorted(query & (labels | content)))

    return [row for row, _, _ in sorted(records, key=score, reverse=True)]


def add_task_memories(task, memories, packet, max_chars):
    """Fit complete notes after mandatory goals and observations have been encoded."""
    requested, names = memory_request(task)
    if requested:
        if not task.get("use_memory"):
            packet = {**packet, "memory_status":"disabled"}
        elif not memories:
            packet = {**packet, "memory_status":"empty"}
    if names and task.get("use_memory"):
        def included(row):
            content = unicodedata.normalize("NFKC", row["label"] + "\n" + row["text"]).casefold()
            return any(unicodedata.normalize("NFKC", name).casefold() in content for name in names)
        memories = [row for row in memories if included(row)]
        if not memories:
            packet = {**packet, "memory_status":"named_record_missing"}
    base = encoded(packet)
    if not memories or not task.get("use_memory"):
        return base
    selected = []
    for row in ranked_memories(task, memories):
        note = {"label": row["label"], "text": row["text"]}
        if row.get("id"):
            note["id"] = row["id"]
        candidate = encoded({**packet, "memory": [*selected, note]})
        if len(candidate) <= max_chars:
            selected.append(note)
            base = candidate
        if len(selected) == 6:
            break
    return base


def used_memory_refs(messages):
    """Keep identities and content digests in task events without copying note text."""
    rows = json.loads(messages[-1]["content"]).get("memory", [])
    return [{"id":r["id"], "sha256":digest({"label":r["label"],"text":r["text"]})}
            for r in rows if r.get("id")]


_DECIMAL = re.compile(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\d.])", re.ASCII)


def memory_cost_issue(task, action, messages, current_notes):
    """Check the numeric inputs of a cost calculation expressly based on saved notes.

    Other tasks retain their tool contracts. This checks input provenance, not
    the choice of formula, the unit of each operand, or production authority.
    """
    if action.kind != "tool" or action.tool != "calculate" or set(task["allowed_tools"]) != {"calculate"}:
        return None
    request = " ".join([task["goal"], *[r["text"] for r in task["inputs"]]])
    if not memory_request(task)[0] or not re.search(r"费|成本|租金|价款|cost|charge|fee",request,re.I):
        return None
    shown = json.loads(messages[-1]["content"]).get("memory", [])
    current = {r["id"]:r for r in current_notes}
    notes = [s for s in shown if s.get("id") in current and
             all(s[k] == current[s["id"]][k] for k in ("text","label"))]
    # A named job's tariff cannot be sourced from another job in the same account.
    named_ids = {s.get("id") for s in shown if len(s["label"].strip()) >= 2 and s["label"].casefold() in request.casefold()}
    if named_ids:
        notes = [s for s in notes if s["id"] in named_ids]
    text = " ".join([request, *[s["text"] for s in notes]])
    quantities = re.sub(r"\b[A-Za-z]+[A-Za-z0-9]*(?:[-_/][A-Za-z0-9]+)+\b|\d{4}[-/]\d{1,2}[-/]\d{1,2}", " ", text, flags=re.ASCII)
    available = {Decimal(m[0].replace(",","")) for m in _DECIMAL.finditer(quantities)}
    if not available:
        return "missing_inputs"
    expression = action.arguments.get("expression")
    if not isinstance(expression,str) or len(expression)>200:
        return "unverified_operands"
    try:
        literals = {Decimal(str(n.value)) for n in ast.walk(ast.parse(expression,mode="eval"))
                    if isinstance(n, ast.Constant) and type(n.value) in (int,float)}
    except (SyntaxError, ValueError, InvalidOperation, RecursionError):
        return "unverified_operands"
    # A conversion constant is eligible only alongside an observed operand and
    # an explicitly stated unit conversion. The calculator still checks its AST.
    constants = {Decimal(0),Decimal(1)}
    if re.search(r"%|百分",text):
        constants.add(Decimal(100))
    if ("小时" in text and "分钟" in text) or ("分钟" in text and "秒" in text):
        constants.add(Decimal(60))
    if any(a in text and b in text for a,b in (("千瓦","兆瓦"),("千克","吨"),("kW","MW"),("kg","tonne"))):
        constants.add(Decimal(1000))
    if not literals.intersection(available) or literals - available - constants:
        return "unverified_operands"
    return None
