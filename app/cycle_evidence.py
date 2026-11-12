import re
from pathlib import Path
from pydantic import Field
from app.harness.contracts import StrictModel
from app.cycle_reader import read_case
from app.cycle_pin import SHA

DIRECTORY = Path(__file__).resolve().parents[1] / "data/decision-cycle-v1"
CASE_ID = re.compile(r"(?<![A-Za-z0-9-])CYCLE-[A-Z0-9]+(?:-[A-Z0-9]+)+(?![A-Za-z0-9-])", re.I)


class Args(StrictModel):
    case_id: str = Field(min_length=8,max_length=72,description="用户所给的完整 CYCLE 工单编号")


def lookup(args, task=None):
    case_id = args.case_id.upper()
    receipt = read_case(DIRECTORY, SHA, case_id)
    goal = (task or {}).get("goal","")
    if not goal:
        return receipt
    if case_id not in ids_in(goal):
        raise ValueError("工具编号不在本工单请求中")
    from app.cycle_english import english_goal, project
    if english_goal(goal):
        return project(receipt,goal)
    references = {"待机":"相对待机每工况周均减少","固定电价识别":"相对固定电价识别每工况周均减少",
                  "原训练策略":"相对固定原训练策略每工况周均减少"}
    named = [ref for token, ref in references.items() if token in goal and ref in receipt]
    equipment = "设备岗" in goal or "执行阶段" in goal
    if not named and not equipment:
        return receipt
    fields = ["工单编号","主题","来源","历史数据提供方","模型提供方","模型版本 SHA256","业务原件 SHA256",
              "本次从原件取证时刻 UTC","处置","审批记录","现场执行记录"]
    if named:
        fields += named
    if equipment:
        fields += ["原训练种子","目标周","官方目标周实绩"]
    return {key:receipt[key] for key in fields if key in receipt}


def ids_in(text):
    return {s.upper() for s in CASE_ID.findall(text)}


def menu(text):
    return ["cycle.evidence"] if ids_in(text) else []


def check_refs(task, action):
    goal = task.get("goal", "")
    requested = ids_in(goal)
    if not requested:
        return []
    cited = {r["arguments"]["case_id"].upper() for r in task["results"]
             if r["id"] in action.evidence_ids and r["ok"] and r["tool"] == "cycle.evidence"}
    if cited != requested:
        return ["请引用提问中的完整工单编号。当前已引用工单与所查工单不匹配。"]
    from app.cycle_english import english_goal,scope_issue
    if english_goal(goal):
        return scope_issue(goal,action.text)
    if "CYCLE-BESS-7COST" in requested and "固定电价识别" in goal and "增益" in goal:
        if not explicit_fixed_gain(action.text):
            return ["请仅对照题目指定的固定电价识别策略列出三项增益。费用 0 元、碳排 0 kg、峰值 0 kW，通用控制替换门槛未通过。"]
    if "设备岗" in goal and "CYCLE-BESS-7COST" in requested:
        if not re.search(r"沙箱.{0,5}复算",action.text) or "执行阶段为费用优先" in action.text:
            return ["执行阶段是可提交沙箱复算。费用优先是偏好，不是执行阶段。请根据处置字段报告可进入的阶段。"]
    if "设备岗" in goal and "CYCLE-US-20261120" in requested:
        if not re.search(r"(?:不能|不得|不可|无法|不应|不支持|不具备|暂缓|不宜).{0,16}(?:调配|调度|联动|执行|下发)",action.text):
            return ["处置是等待官方实绩，本工单当前不能用于设备调配。请明确回答能否调配并报出审批、执行记录状态。"]
    if "设备岗" in goal and "审批" in goal and "执行" in goal:
        if "审批" not in action.text or "执行" not in action.text:
            return ["请分别说明审批记录与现场执行记录。当前这两栏均为空。"]
    return []


def explicit_fixed_gain(text):
    if "固定电价识别" not in text:
        return False
    pieces = re.split("[。；;！!？?\n]", text)
    for i, piece in enumerate(pieces):
        if "固定电价识别" not in piece:
            continue
        excerpt = " ".join(pieces[i:i+4])
        excerpt = re.split(r"(?:相对|相比|较)(?:于)?(?:待机|固定原训练策略|原训练策略)",excerpt)[0]
        group = re.search(r"(?:三项|三者|三种|三方面|费用.{0,12}碳.{0,12}峰).{0,22}(?:均|都|全部|全)(?:为|是|为数值|等于)?\s*(?:零|0(?:\.0+)?(?![.\d]))",excerpt)
        zeros = [re.search(r"(?<![.\d])0(?:\.0+)?\s*"+u,excerpt,re.I) for u in (r"元",r"(?:kg|千克|公斤)",r"(?:kW(?!h)|千瓦)")]
        gate = re.search(r"未(?:达到|通过|满足|达)|不(?:能|建议|可|满足|符合|通过|达标)|暂缓",text)
        if (group or all(zeros)) and gate:
            return True
    return False
