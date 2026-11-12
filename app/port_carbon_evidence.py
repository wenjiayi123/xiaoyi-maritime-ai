import json,re
from hashlib import sha256
from typing import Literal
from app.config import WEB_DIR
from app.harness.contracts import StrictModel
class CarbonArgs(StrictModel):
    case:Literal["compare","forward","2021","2022","2023","2024","2025"]
def read_receipt(args):
    from app.port_carbon_pin import SHA
    b=(WEB_DIR/"policy-evidence/port-carbon/evidence.json").read_bytes()
    if sha256(b).hexdigest()!=SHA:raise ValueError("排放清单归档校验失败")
    return json.loads(b)[args.case]
def menu(text):
    if re.search("下发|操控|切换配置|启动系统|暂停系统",text):return []
    if re.search("洛杉矶",text) and re.search("碳排放|温室气体|碳当量|排放清单",text) and re.search("年度|年初|留出|封存|预测|清单",text):return ["emissions.port_year"]
    return []
