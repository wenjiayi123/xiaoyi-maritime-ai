"""Read-only live dispatch experiment used from an operator's natural-language work order."""
import hashlib
import json
import os
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Literal
from pydantic import Field, field_validator
from app.harness.contracts import StrictModel

NAME="policy.deep_storage"
class Args(StrictModel):
    day: str = Field(pattern=r"^2025-\d{2}-\d{2}$",description="留出年份的完整 UTC 日期，格式 YYYY-MM-DD")
    demand_pct: int = Field(ge=75,le=140,description="相对历史作业需求的百分比，100 表示历史水平")
    hour: int = Field(ge=0,le=23,description="报告哪个 UTC 小时的动作；全天始终运行24步")
    arm: Literal["multi","single","guarded"] = Field(default="multi",description="multi 多步深度Q，single 单步深度Q，guarded 风险约束深度Q研究候选")
    @field_validator("day")
    @classmethod
    def real_date(cls,value):
        date.fromisoformat(value)
        return value

def menu(text):
    if re.search(r"下发|操控|启动现场|写入设备",text):return []
    asset=re.search(r"储能|电池",text)
    method=re.search(r"深度强化学习|深度\s*Q|离线强化学习|\bDRL\b|\bDQN\b",text,re.I)
    run=re.search(r"试算|复算|推演|回放|重算|跑一|跑一下|对照|运行|比较|对比",text)
    return [NAME] if asset and method and run else []

def read_receipt(args):
    from app.risk_storage_pin import BASE, PYTHON, INPUTS
    for name,expected in INPUTS.items():
        with Path(name).open("rb") as file:
            if hashlib.file_digest(file,"sha256").hexdigest()!=expected:
                raise ValueError("储能研究文件版本已变动，请复核登记版本")
    env=dict(os.environ,PYTHONIOENCODING="utf8",OPENBLAS_NUM_THREADS="1",PYTHONNOUSERSITE="1")
    env.pop("PYTHONPATH",None)
    res=subprocess.run([PYTHON,"-B","-X","utf8",str(Path(BASE)/"serve_policy.py"),args.day,str(args.demand_pct),str(args.hour),args.arm],
        cwd=BASE,env=env,capture_output=True,timeout=50,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    if res.returncode:raise ValueError("该工况未取得完整仿真回执，请检查留出日期和模型数据版本")
    record=json.loads(res.stdout)
    if (record["args"]!=args.model_dump() or record["production_authority"] or len(record["steps"])!=24
            or record["schema"]!="gullmate.deep-storage.v1"):raise ValueError("储能推演结果完整性错误")
    return record

def delivery_issues(task,text,receipts):
    if NAME not in task.get("allowed_tools",[]):return []
    goal=task["goal"]+" "+" ".join(i.get("text","") for i in task.get("inputs",[]))
    if not menu(goal):return []
    # Every explicit requested value must appear in a cited successful simulation.
    requirements={}
    for key,pattern in (("day",r"(?<!\d)(2025-\d{2}-\d{2})(?!\d)"),("demand_pct",r"(\d{2,3})\s*[%％]"),("hour",r"(?<!\d)(\d{1,2})\s*(?:时|点|:00)")):
        requirements[key]={v if key=="day" else int(v) for v in re.findall(pattern,goal)}
    if not receipts or any(not vals.issubset({r["args"][k] for r in receipts}) for k,vals in requirements.items()):
        return ["请引用符合用户指定日期、负荷与小时的实际深度策略推演工件，再提交结论。"]
    from app.storage_meter_checks import meter_issues
    from app.storage_decision_claims import requested,claim_issues
    if not set(requested(task)).issubset({r["args"]["arm"] for r in receipts}):
        return ["请按明确指定的算法再取得独立回执。"]
    if len(receipts)==1:
        r=receipts[0];facts=r["summary"]
        problems=claim_issues(text,r)+meter_issues(goal,text,r)
        if re.search(r"动作|怎么调|如何调",goal) and facts["本小时动作"] not in text:
            problems.append(f"报告漏了用户问的小时动作：{r['args']['hour']} 时「{facts['本小时动作']}」。")
        if facts["相对MPC未通过的约束"] and re.search("准入|结论|约束|人工复核|基线",goal):
            aliases={"峰值功率":r"日峰|峰值|峰荷|超峰","碳排放":r"碳排|增碳|净碳","日末电量":r"日末电量|日末荷电|终端电量|终端SOC",
                     "吞吐量":r"吞吐|作业量","延误":r"延误|延迟","安全":r"安全|违规","成本":r"成本|费用|降本"}
            if not re.search(r"(?:保留|沿用|维持|保持)基线",text) or any(not re.search(aliases.get(k,re.escape(k)),text) for k in facts["相对MPC未通过的约束"]):
                problems.append("本日未通过的检查为"+"、".join(facts["相对MPC未通过的约束"])+"，自动结论为保留基线。")
        if not facts["相对MPC未通过的约束"] and re.search("是否.*复核|复核结论|能.*复核",goal) and not re.search(r"(?:可|建议|允许|可以|应当|应|能够).{0,6}(?:提交|送交|进入|报请|转交|转入|转).{0,4}(?:人工|复核)|可送审",text):
            problems.append("该日七项通过，仿真工单建议可提交人工复核，实际人工签署尚未发生。")
        return problems
    return []
