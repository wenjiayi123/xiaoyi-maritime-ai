"""Identify checked display values and literal source metadata in calculation summaries."""
import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import io
import json
import re

from integrations.shanghai_lab_v1.data import FOLDER

PRECISION = re.compile(r"(?:保留|取到|四舍五入[到至])\s*([零一二两三四五六0-6])\s*位")
DIGITS = {"零":0,"一":1,"二":2,"两":2,"三":3,"四":4,"五":5,"六":6}
SOURCE = re.compile(r"资料编号\s*[:：]?\s*([a-zA-Z][a-zA-Z0-9_-]{1,79})[，,\s]+摘要\s*[:：]?\s*([0-9a-f]{12,64})(?![0-9a-f])")
DAY = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")


def remove_rounded_value(text, goal, receipt):
    precision = PRECISION.search(goal)
    unit = receipt.get("unit")
    raw = receipt.get("value")
    if not precision or not isinstance(unit,str) or not unit.strip() or type(raw) not in (int,float):
        return text
    digit = precision[1]
    places = int(digit) if digit.isascii() else DIGITS[digit]
    try:
        rounded = Decimal(str(raw)).quantize(Decimal(1).scaleb(-places),rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return text
    unit_pattern = "[%％]" if unit.strip() in {"%","％"} else re.escape(unit.strip())
    # Chinese prose may directly precede the number; only Latin identifiers or numeric prefixes are excluded.
    pattern = r"(?<![A-Za-z0-9_.])([+-]?\d+(?:\.\d+)?)\s*" + unit_pattern + r"(?![a-zA-Z0-9/%])"
    return re.sub(pattern,lambda m: " " if Decimal(m[1])==rounded else m[0],text)


def remove_registered_metadata(text, goal):
    bindings = SOURCE.findall(goal)
    if not bindings:
        return text
    try:
        manifest = json.loads((FOLDER/"manifest.json").read_bytes())
        if manifest.get("schema")!="shanghai-public-lab-dataset.v1":
            return text
        sources = {row["id"]:row for row in manifest["sources"]}
        for source_id,claimed in bindings:
            source=sources.get(source_id)
            if not source or not source["sha256"].startswith(claimed):
                continue
            filename=source["path"]
            if manifest["files"].get(filename,{}).get("sha256")!=source["sha256"]:
                continue
            path=(FOLDER/filename).resolve()
            if not path.is_relative_to(FOLDER.resolve()):
                continue
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=source["sha256"]:
                continue
            text=re.sub(r"(?<![A-Za-z0-9_-])"+re.escape(source_id)+r"(?![A-Za-z0-9_-])"," ",text)
            requested_days=set(DAY.findall(goal)) & set(DAY.findall(text))
            if requested_days and filename.lower().endswith(".csv"):
                days=set()
                for row in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
                    for key in ("date","time","timestamp"):
                        day=(row.get(key) or "")[:10]
                        if day in requested_days:days.add(day)
                text=DAY.sub(lambda m:" " if m[0] in days else m[0],text)
    except (OSError,UnicodeError,ValueError,KeyError,csv.Error):
        return text
    return text


def historical_dispatch_issue(goal, answer):
    """A historical calculation cannot authorize equipment deployment when the user asks that question."""
    if not re.search(r"历史|historical",goal,re.I):
        return None
    asks_live = re.search(r"(?:能否|是否|可否|能不能|可不可以).{0,10}直接.{0,26}(?:现场|下发|实船|岸桥|港机|调度)",
                          goal,re.I) or re.search(r"(?:can|may|should).{0,50}directly.{0,45}(?:dispatch|deploy|control)",goal,re.I)
    if not asks_live:
        return None
    issue = "历史统计只可供分析，不能单凭本次计算直接投放设备或下发调度；结论应说明还需当前作业计划、资源状态和有权调度人员确认。"
    denial = re.compile(r"(?:不能|不可|无法|不得|不应|不足以|不具备|不可以).{0,28}(?:现场|直接|投放|调度|下发|执行|依据)|"
                        r"仅(?:供|作|可作|能作为).{0,8}参考|(?:cannot|can.t|should not|must not|insufficient|no authority).{0,56}(?:dispatch|deploy|use|basis|control)",re.I)
    allowed = re.compile(r"(?:可以|能够|足以|应当|可)(?:直接|据此|用于|用来|作为依据|安排|下发).{0,18}(?:现场|投放|岸桥|港机|调度)|"
                         r"\b(?:can|may|should)\s+(?:be\s+used\s+)?directly.{0,30}(?:dispatch|deploy|control)",re.I)
    for clause in re.split(r"[，,。！？!?；;\n]",answer):
        for hit in allowed.finditer(clause):
            if not re.search(r"(?:不|未|非|并不|不能|并非)$",clause[:hit.start()]) and not denial.search(clause[:hit.end()]):
                return issue
    return None if denial.search(answer) else issue
