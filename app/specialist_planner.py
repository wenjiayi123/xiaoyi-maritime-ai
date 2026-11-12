"""Plan port work orders with the selected workstation model and a bounded role catalog."""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from app.harness.model import NoRedirect


# Each specialist is restricted to its published evidence interfaces.
ROLES = {
    "operations": (
        "港口运营",
        "吞吐、生产状态、现场或历史运营口径",
        ("runtime.snapshot", "port.study", "systems.inspect"),
    ),
    "dispatch": (
        "智能调度",
        "泊位、引航、装卸与水平运输排程；历史模拟服务和延误门槛",
        ("operations.optimize", "policy.operations", "port.study"),
    ),
    "energy": (
        "能源优化",
        "用电、储能、岸电、成本、峰值与供能约束",
        ("policy.energy", "systems.inspect", "knowledge.search"),
    ),
    "carbon": (
        "碳管理",
        "排放量、碳盘查口径、排放因子与成本之间的权衡",
        ("policy.energy", "knowledge.search", "systems.inspect"),
    ),
    "maintenance": (
        "设备维护",
        "设备点检、故障征兆、检修依据与数据缺项",
        ("knowledge.search", "runtime.snapshot"),
    ),
    "safety": (
        "安全合规",
        "作业风险、权限边界、规程和安全门禁",
        ("policy.safety", "knowledge.search", "runtime.snapshot"),
    ),
    "twin": (
        "数字孪生",
        "孪生观测、模拟场景和独立校准",
        ("twin.validate_public", "systems.inspect", "runtime.snapshot"),
    ),
    "rl": (
        "强化学习",
        "受训策略、基线、跨期检验与失败条件",
        ("policy.release", "crossport.compare", "remediation.review"),
    ),
    "analytics": (
        "数据分析",
        "原始小时数据、AIS 分钟观察、策略图表及指标来源",
        ("knowledge.figures", "knowledge.ais_minute", "evidence.public_catalog"),
    ),
    "management": (
        "管理决策",
        "综合已核实的上游证据、保留否决、解释分歧、形成待复核决议",
        ("review",),
    ),
}


def local_json(url, body=None, *, token=None, timeout=110):
    dest = urlsplit(url)
    if (
        dest.scheme != "http"
        or dest.hostname not in {"127.0.0.1", "localhost", "::1"}
        or dest.username
        or dest.password
    ):
        raise ValueError("本机工单只使用已登记的环回服务")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    raw = (
        json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        if body is not None
        else None
    )
    with build_opener(NoRedirect).open(
        Request(url, data=raw, headers=headers), timeout=timeout
    ) as response:
        data = response.read(16_000_001)
    if len(data) > 16_000_000:
        raise ValueError("工件超过本机处理上限")
    return json.loads(data)


class WorkstationModel:
    def __init__(self, base):
        self.base = base.rstrip("/")
        models = local_json(self.base + "/models")["data"]
        if len(models) != 1:
            raise ValueError("需要唯一的在役本机模型")
        self.name = models[0]["id"]

    def complete(self, name, system, data, schema, max_tokens):
        body = {
            "model": self.name,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(
                        data, ensure_ascii=False, separators=(",", ":")
                    ),
                },
            ],
            "temperature": 0,
            "seed": 20261108,
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            },
        }
        response = local_json(self.base + "/chat/completions", body, timeout=120)
        choice = response["choices"][0]
        if choice["finish_reason"] != "stop":
            raise ValueError("模型未完成结构化输出")
        return json.loads(choice["message"]["content"]), {
            "model": response["model"],
            "usage": response.get("usage"),
            "id": response.get("id"),
        }


def available_roles(tools):
    return {
        role: [tool for tool in row[2] if tool == "review" or tool in tools]
        for role, row in ROLES.items()
        if any(tool == "review" or tool in tools for tool in row[2])
    }


def water_validation_goal(text):
    return bool(
        re.search(r"水位|water[ -]?level", text, re.I)
        and re.search(r"校准|误差|留出|calibrat|holdout|error", text, re.I)
    )


def check_plan(plan, catalog):
    steps = plan["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= len(ROLES):
        raise ValueError("计划岗位数量超出范围")
    roles = [s["role"] for s in steps]
    if len(set(roles)) != len(roles):
        raise ValueError("一个岗位应合并本次分工")
    if "management" in roles and len(roles) == 1:
        raise ValueError("管理决策需要独立来源")
    for step in steps:
        role, tool, needs = step["role"], step["tool"], step["needs"]
        if tool not in catalog.get(role, []):
            raise ValueError("岗位工具未获授权")
        if set(needs) - set(roles) or role in needs or "management" in needs:
            raise ValueError("交接指向未委派岗位、自身或尚待汇总的管理岗")
        if (
            not isinstance(step["assignment"], str)
            or not 2 <= len(step["assignment"].strip()) <= 200
        ):
            raise ValueError("分工必须包含可执行的具体问题")
    pending = [dict(s, needs=list(dict.fromkeys(s["needs"]))) for s in steps]
    for step in pending:
        if step["role"] == "management":
            # The coordinator must always include every specialist's veto.
            step["needs"] = [r for r in roles if r != "management"]
    ordered = []
    while pending:
        ready = next(
            (s for s in pending if set(s["needs"]) <= {r["role"] for r in ordered}),
            None,
        )
        if ready is None:
            raise ValueError("工单中存在循环交接")
        ordered.append(ready)
        pending.remove(ready)
    return ordered


def plan_order(model, goal, tools, selection=None):
    catalog = available_roles(tools)
    args = {
        "工单": goal,
        "已指定历史范围": selection,
        "岗位目录": {
            r: {"职责": ROLES[r][1], "可用工具": v} for r, v in catalog.items()
        },
    }
    # Ask if a single specialist's original evidence suffices before expanding
    # a team. Mentioning a model, dataset or unit does not require its own agent.
    options = [
        r + "." + t for r, tools in catalog.items() if r != "management" for t in tools
    ]
    triage_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"route": {"type": "string", "enum": [*options, "collaborate"]}},
        "required": ["route"],
    }
    triage, first = model.complete(
        "route_port_request",
        "你负责工单分诊。默认选一个可以直接提供所需证据的主责岗位.工具。"
        "只问某项状态、某份检修知识、一个模拟指标或同一回执中的多个数值时，一个岗位足以交付。"
        "按最终所问的量选岗：作业量及延误归调度，成本/电量归能源，碳排归碳管理，图像来源或AIS数据归数据分析，"
        "孪生校准归孪生，是否总体胜过强基线归强化学习。资料、基线或模型的名称不构成新的分工。"
        "只有用户要求独立岗位出意见、跨来源复核、证据交接或多目标仲裁，且一个岗位不能交付时选 collaborate。",
        args,
        triage_schema,
        80,
    )
    attempts = [{"stage": "triage", "reply": triage, "trace": first}]
    route = triage["route"]
    explicit = re.sub(
        r"(?:不需(?:要)?|无需|不要|不必)(?:组织)?(?:会审|交叉复核|交叉验证|分工)",
        "",
        goal,
    )
    joint_request = bool(
        re.search(
            r"交叉复核|交叉验证|会审|分工|各(?:自)?形成独立|分别出具|独立意见|handoff|independent reviews",
            explicit,
            re.I,
        )
    )
    if joint_request:
        route = "collaborate"
        attempts[0]["constraint"] = "explicit_collaboration"
    if route != "collaborate":
        if route not in options:
            raise ValueError("分诊返回未知工具")
        role, tool = route.split(".", 1)
        if (
            role == "twin"
            and water_validation_goal(goal)
            and "twin.validate_public" in catalog[role]
        ):
            tool = "twin.validate_public"
            attempts[0]["tool_constraint"] = "independent_water_level_validation"
        return [
            {"role": role, "tool": tool, "assignment": goal[:200], "needs": []}
        ], attempts
    roster_schema = {
        "type": "object",
        "properties": {
            "roles": {
                "type": "array",
                "items": {"type": "string", "enum": list(catalog)},
            }
        },
        "additionalProperties": False,
        "required": ["roles"],
    }
    roster, selection_trace = model.complete(
        "select_port_specialists",
        "选择用户实际要求交付独立结论的岗位。仅列必要的主责岗；不能因使用数据就附加数据分析岗，也不能因评估模拟方案就附加孪生岗。"
        "用户要求从图表和其他工件交叉取证时，需保留负责图表原始数据的岗位。明确要求管理决议或最终汇总则保留管理岗。"
        "如果明确列举了独立出意见的岗位，仅补充完成该委托不可缺少的岗位。输出 roles。",
        args,
        roster_schema,
        170,
    )
    kept = list(dict.fromkeys(roster["roles"]))
    attempts.append({"stage": "roster", "reply": roster, "trace": selection_trace})
    if len(kept) >= 2 and all(r in catalog for r in kept):
        catalog = {r: catalog[r] for r in kept}
        args["岗位目录"] = {r: args["岗位目录"][r] for r in kept}
    variants = []
    for role, options in catalog.items():
        variants.append(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "role": {"const": role},
                    "tool": {"type": "string", "enum": options},
                    "assignment": {"type": "string"},
                    "needs": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(catalog)},
                    },
                },
                "required": ["role", "tool", "assignment", "needs"],
            }
        )
    step = {"anyOf": variants}
    schema = {
        "type": "object",
        "properties": {"steps": {"type": "array", "items": step}},
        "required": ["steps"],
        "additionalProperties": False,
    }
    system = (
        "你是舷鸥港航工单总调度。按用户的实际问题自主拆出最少且充分的专业分工。"
        "每项只列一个主责岗位和该岗位目录中的一个取证工具，assignment 用一句话写明对象、需核实的事实和范围。"
        "needs 是必须先收到其证据的岗位，引用此前岗位。独立工作可以没有前置。"
        "单项取证只用业务主责岗；当需要汇总、仲裁或综合决策时，最后加 management，needs 列出所有已派岗位。"
        "成本、排放若要求两个独立意见，分别委派 energy、carbon。不要替用户指定未给的港口、数字、窗口或生产权限。"
        "历史策略用具名策略工具；设备点检依据用知识检索。全部任务限资料分析或仿真。只输出给定 JSON。"
    )
    for _ in range(2):
        reply, trace = model.complete("port_work_plan", system, args, schema, 1100)
        attempts.append({"stage": "decomposition", "reply": reply, "trace": trace})
        try:
            steps = check_plan(reply, catalog)
            if joint_request and len(steps) < 2:
                raise ValueError("用户要求独立分工，需要至少两个岗位")
            if len(kept) >= 2 and set(s["role"] for s in steps) != set(kept):
                raise ValueError("分工必须覆盖全部已选岗位：" + ", ".join(kept))
            return steps, attempts
        except (ValueError, TypeError, KeyError) as exc:
            args["上次计划的验证反馈"] = str(exc)
    raise ValueError(
        "两次计划均未满足有向依赖与工具权限：" + args["上次计划的验证反馈"]
    )
