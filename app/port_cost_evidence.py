import json,re
from hashlib import sha256
from typing import Literal
from app.config import WEB_DIR
from app.harness.contracts import StrictModel
class Args(StrictModel):
    case:Literal["budget2024","budget2025","bridge2025","history"]
def read_receipt(args):
    from app.port_cost_pin import SHA
    b=(WEB_DIR/"policy-evidence/port-cost/evidence.json").read_bytes()
    if sha256(b).hexdigest()!=SHA:raise ValueError("成本清单校验失败")
    return json.loads(b)[args.case]
def menu(text):
    if re.search("下发|操控|付款|转账",text):return []
    return ["finance.port_cost"] if "洛杉矶" in text and re.search("运营费用|财年成本|成本对账|财年预算|预算执行",text) else []

def boundary_issues(answer,case):
    if case not in ("budget2024","budget2025"):return []
    for sentence in re.split(r"[。！？!?；;\n]",answer):
        if not re.search(r"差额|少支|低于预算|预算差异|结余",sentence):continue
        for clause in re.split(r"[，,](?!\d{3})|但(?=是|属于)|而(?=是|属于)",sentence):
            for m in re.finditer(r"(?:是|属于|计入|构成|等于|代表|意味着|可以算作|可算作|算作)\s*(?:本项目|项目|该项目|本次)?(?:[该本]?年度?最终支出(?:的(?:一部分|组成部分))?|(?:RL|强化学习|项目|策略)\s*(?:的)?(?:节省|节费|收益)|已实现的?节费)",clause,re.I):
                if re.search(r"(?:不|并不|不是|不能|不能被|非|未|不应|并非|无法|难以|不得|不可以|不等于|不代表)(?:(?:将|把)(?:这笔|该|此|上述)?(?:预算)?(?:差额|少支金额|其))?(?:直接)?\s*$",clause[:m.start()]):continue
                return ["初步预算差额是预算减初步支出，既不是年度最终支出的一部分，也不能认作 RL 节费。请删除错误归因，保留数值。"]
    return []
