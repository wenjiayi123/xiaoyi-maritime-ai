"""Return a frozen evaluation only. No equipment connection or command."""
from hashlib import sha256
import json,re
from typing import Literal
from app.config import WEB_DIR
from app.harness.contracts import StrictModel

class StateArgs(StrictModel):
    case:Literal["thermal","pose10","pose30"]
def read_receipt(args):
    from app.equipment_evidence_pin import EVIDENCE_SHA
    raw=(WEB_DIR/"policy-evidence/equipment/evidence.json").read_bytes()
    if sha256(raw).hexdigest()!=EVIDENCE_SHA:raise ValueError("设备留出试验回执校验失败")
    return json.loads(raw)[args.case]
def menu(text):
    if re.search("下发|操控|切换配置|启动系统|暂停系统|设定阈值",text):return []
    return ["equipment.state"] if re.search(r"(?:吊具.{0,24}(?:帧|留出|位置预测)|跨运车.{0,24}(?:过热|告警|留出)|(?:10|30)\s*帧.{0,12}吊具)",text) else []
