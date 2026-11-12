import json,re
from typing import Literal
from hashlib import sha256
from app.config import WEB_DIR
from app.harness.contracts import StrictModel
class Args(StrictModel):
    case:Literal["savannah","lalb","other","national","forward"]
def read_receipt(args):
    from app.queue_pin import SHA
    b=(WEB_DIR/"policy-evidence/congestion/evidence.json").read_bytes()
    if sha256(b).hexdigest()!=SHA:raise ValueError("等泊证据摘要校验失败")
    return json.loads(b)[args.case]
def menu(text):
    if re.search("下发|启动预警|发送预警|操控",text):return []
    return ["congestion.queue_week"] if re.search("萨凡纳|洛杉矶|长滩|美国|全美",text) and re.search("等泊|等候泊位|船舶排队",text) else []

def boundary_issues(answer,case):
    if case!="forward":return []
    publisher=r"(?:美国)?(?:交通统计局|BTS)(?:[（(]BTS[)）])?"
    for clause in re.split(r"[。；;！!？?\n，,]",answer):
        if re.search(r"(?:不是|并非|不属于|非官方|并未|没有|未提供|不是由|并非由)",clause):continue
        if re.search(r"(?:预测|前瞻|概率)(?:结果)?(?:是)?由.{0,4}"+publisher+r".{0,5}(?:提供|发布|给出|签发)",clause,re.I) or re.search(publisher+r".{0,4}(?:给出|发布|提供|签发)(?:的)?(?:本次|该|这份)?(?:官方)?(?:预测|前瞻)",clause,re.I):
            return ["来源错误：本次预测由舷鸥项目生成，BTS 只提供签发前的历史观测。不要将预测或概率归给 BTS。"]
    return []
