"""Read-only Fintraffic source-backed evidence for the installed XiaoYi task centre."""
import json
import re
from hashlib import sha256
from typing import Literal
from app.config import WEB_DIR
from app.harness.contracts import StrictModel


class BerthArgs(StrictModel):
    period:Literal["apr_aug","october"]


class EtaArgs(BerthArgs):
    port:Literal["FIHEL","FIKTK","FIHKO","FITKU"]


def read_receipt(name,args):
    raw=(WEB_DIR/"policy-evidence/port-arrivals/evidence.json").read_bytes()
    if sha256(raw).hexdigest()!="234a3643a1fbe37cd80f5c3e2ce0d6af346b8faf42d4c3dc00d7b0fae3963395":raise ValueError("芬兰到港数据归档校验失败")
    data=json.loads(raw)
    if name=="portcall.eta":return data["eta"][args.port+"|"+args.period]
    if name=="portcall.berths":return data["berth"][args.period]
    raise ValueError("未知港口回执类型")


def menu(text):
    if not re.search("芬兰|赫尔辛基|科特卡|汉科|图尔库|FIHEL|FIKTK|FIHKO|FITKU",text,re.I):return []
    if re.search("下发|修改配置|暂停系统|启动系统",text):return []
    kinds=[]
    if re.search("到港|ETA|船代申报",text,re.I):kinds.append("portcall.eta")
    if re.search("泊位|模拟等待",text):kinds.append("portcall.berths")
    if kinds and re.search("设备|能碳|储能|碳排",text):return []
    return kinds
