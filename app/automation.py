from __future__ import annotations

import re
from collections import OrderedDict
from datetime import datetime, timezone
from threading import RLock
from typing import Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.security import request_identity
from app.runtime_store import runtime_store


router = APIRouter(prefix="/api/automation", tags=["小懿智能操作"])

ActionKind = Literal[
    "navigate",
    "set_range",
    "set_mode",
    "open_panel",
    "create_task",
    "ask",
    "filter_knowledge",
    "inspect_knowledge",
    "verify_sources",
    "validate_answer",
    "present_result",
    "inspect_metrics",
    "inspect_decision",
    "advance_task",
    "inspect_task_result",
    "validate_report",
    "present_report",
    "verify_view",
    "inspect_connectors",
    "generate_report",
    "new_chat",
    "show_history",
    "show_favorites",
    "show_alerts",
    "show_settings",
    "switch_avatar",
    "propose_live_action",
    "open_rl_mission",
    "check_rl_systems",
    "build_rl_scenario",
    "replay_rl_training",
    "run_rl_competition",
    "verify_rl_policy",
    "dispatch_rl_dry_run",
    "present_rl_mission",
    "open_weather_mission",
    "check_weather_systems",
    "build_weather_scenario",
    "infer_weather_policy",
    "benchmark_weather_policy",
    "replay_weather_twin",
    "verify_weather_policy",
    "dispatch_weather_dry_run",
    "present_weather_mission",
    "open_marl_mission",
    "check_marl_systems",
    "build_marl_cmdp",
    "coordinate_marl_agents",
    "inspect_marl_reward",
    "verify_marl_policy",
    "dispatch_marl_dry_run",
    "present_marl_mission",
    "check_simulator_runtime",
    "launch_simulator",
    "verify_simulator_runtime",
    "open_simulator",
    "check_linked_system_runtime",
    "launch_linked_system_runtime",
    "verify_linked_system_runtime",
    "open_linked_system_runtime",
]
ActionStatus = Literal["pending", "running", "completed", "failed", "skipped"]
PlanStatus = Literal["ready", "running", "awaiting_confirmation", "completed", "failed", "cancelled"]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class AutomationPlanRequest(BaseModel):
    command: str = Field(..., min_length=2, max_length=500)
    execution_mode: Literal["guided", "automatic"] = "automatic"


class AutomationAction(BaseModel):
    id: str
    order: int
    kind: ActionKind
    label: str
    phase: Literal["理解", "准备", "检索", "分析", "执行", "核验", "交付"] = "执行"
    visual_target: str
    parameters: dict[str, str] = Field(default_factory=dict)
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_confirmation: bool = False
    status: ActionStatus = "pending"
    result: Optional[str] = None


class AutomationAuditEvent(BaseModel):
    timestamp: datetime
    event: str
    detail: str


class AutomationPlan(BaseModel):
    id: str
    command: str
    intent: str
    summary: str
    confidence: float
    actionable: bool
    execution_mode: Literal["guided", "automatic"]
    data_notice: str
    status: PlanStatus
    current_action_id: Optional[str]
    confirmed_action_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    actions: list[AutomationAction]
    audit_trail: list[AutomationAuditEvent]


class AutomationStepResult(BaseModel):
    outcome: Literal["success", "failed", "skipped"] = "success"
    detail: str = Field(default="界面动作已完成。", max_length=500)


class AutomationConfirmRequest(BaseModel):
    action_id: str = Field(..., min_length=3, max_length=120)
    confirmed: bool
    operator: str = Field(default="管理员", min_length=2, max_length=80)


class AutomationAdvanceResponse(BaseModel):
    plan: AutomationPlan
    completed_action_id: Optional[str]
    next_action: Optional[AutomationAction]
    assistant_message: str


class _PlanStore:
    def __init__(self, max_items: int = 100) -> None:
        self._items: OrderedDict[str, AutomationPlan] = OrderedDict()
        self._max_items = max_items
        self._lock = RLock()
        for payload in reversed(runtime_store.list_artifacts("automation_plan", limit=max_items)):
            try:
                plan = AutomationPlan.model_validate(payload)
            except ValueError:
                continue
            if plan.status in {"running", "awaiting_confirmation"}:
                now = _now()
                for action in plan.actions:
                    if action.status == "running":
                        action.status = "failed"
                        action.result = "服务进程重启，未自动续执行。"
                plan.status = "failed"
                plan.current_action_id = None
                plan.updated_at = now
                plan.audit_trail.append(AutomationAuditEvent(
                    timestamp=now,
                    event="process-restart",
                    detail="服务进程重启；为防止重复执行，未完成计划已安全停止。",
                ))
                runtime_store.save_artifact("automation_plan", plan.id, plan.model_dump(mode="json"), max_items=max_items)
            self._items[plan.id] = plan

    def _persist(self, plan: AutomationPlan) -> None:
        runtime_store.save_artifact(
            "automation_plan",
            plan.id,
            plan.model_dump(mode="json"),
            max_items=self._max_items,
        )

    def save(self, plan: AutomationPlan) -> AutomationPlan:
        with self._lock:
            while len(self._items) >= self._max_items:
                self._items.popitem(last=False)
            self._items[plan.id] = plan
            self._persist(plan)
            return plan.model_copy(deep=True)

    def list(self) -> list[AutomationPlan]:
        with self._lock:
            return [item.model_copy(deep=True) for item in reversed(self._items.values())]

    def get(self, plan_id: str) -> Optional[AutomationPlan]:
        with self._lock:
            plan = self._items.get(plan_id)
            return plan.model_copy(deep=True) if plan else None

    def confirm(self, plan_id: str, payload: AutomationConfirmRequest) -> Optional[AutomationPlan]:
        with self._lock:
            plan = self._items.get(plan_id)
            if plan is None:
                return None
            action = next((item for item in plan.actions if item.id == payload.action_id), None)
            if action is None:
                raise HTTPException(status_code=404, detail="操作步骤不存在")
            if not action.requires_confirmation:
                raise HTTPException(status_code=409, detail="该步骤不需要人工确认")
            now = _now()
            if payload.confirmed:
                if action.id not in plan.confirmed_action_ids:
                    plan.confirmed_action_ids.append(action.id)
                plan.status = "running"
                detail = f"{payload.operator} 已确认步骤“{action.label}”。"
            else:
                action.status = "skipped"
                action.result = "操作员拒绝执行。"
                plan.status = "cancelled"
                plan.current_action_id = None
                detail = f"{payload.operator} 已拒绝步骤“{action.label}”，计划取消。"
            plan.updated_at = now
            plan.audit_trail.append(AutomationAuditEvent(timestamp=now, event="human-confirmation", detail=detail))
            self._persist(plan)
            return plan.model_copy(deep=True)

    def advance(
        self, plan_id: str, payload: AutomationStepResult
    ) -> Optional[AutomationAdvanceResponse]:
        with self._lock:
            plan = self._items.get(plan_id)
            if plan is None:
                return None
            if plan.status in {"completed", "failed", "cancelled"}:
                return AutomationAdvanceResponse(
                    plan=plan.model_copy(deep=True),
                    completed_action_id=None,
                    next_action=None,
                    assistant_message="计划已结束，无需继续推进。",
                )
            current = next((item for item in plan.actions if item.status == "running"), None)
            if current is None:
                current = next((item for item in plan.actions if item.status == "pending"), None)
                if current:
                    current.status = "running"
                    plan.current_action_id = current.id
            if current is None:
                plan.status = "completed"
                plan.current_action_id = None
                plan.updated_at = _now()
                self._persist(plan)
                return AutomationAdvanceResponse(
                    plan=plan.model_copy(deep=True),
                    completed_action_id=None,
                    next_action=None,
                    assistant_message="全部界面操作已完成。",
                )
            if current.requires_confirmation and current.id not in plan.confirmed_action_ids:
                plan.status = "awaiting_confirmation"
                plan.current_action_id = current.id
                plan.updated_at = _now()
                self._persist(plan)
                raise HTTPException(status_code=409, detail="当前步骤需要人工确认后才能执行")

            now = _now()
            current.status = {"success": "completed", "failed": "failed", "skipped": "skipped"}[payload.outcome]
            current.result = payload.detail
            plan.audit_trail.append(
                AutomationAuditEvent(
                    timestamp=now,
                    event="action-finished",
                    detail=f"第 {current.order} 步“{current.label}”：{payload.detail}",
                )
            )
            if payload.outcome == "failed":
                plan.status = "failed"
                plan.current_action_id = None
                message = f"“{current.label}”执行失败，计划已停止。"
                next_action = None
            else:
                next_action = next((item for item in plan.actions if item.status == "pending"), None)
                if next_action is None:
                    plan.status = "completed"
                    plan.current_action_id = None
                    message = "全部界面操作已完成，操作轨迹已经保存。"
                else:
                    next_action.status = "running"
                    plan.current_action_id = next_action.id
                    if next_action.requires_confirmation and next_action.id not in plan.confirmed_action_ids:
                        plan.status = "awaiting_confirmation"
                        message = f"下一步“{next_action.label}”需要人工确认。"
                    else:
                        plan.status = "running"
                        message = f"“{current.label}”已完成，开始“{next_action.label}”。"
            plan.updated_at = now
            self._persist(plan)
            return AutomationAdvanceResponse(
                plan=plan.model_copy(deep=True),
                completed_action_id=current.id,
                next_action=next_action.model_copy(deep=True) if next_action else None,
                assistant_message=message,
            )


_plans = _PlanStore()


def _normalize(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:；;（）()]", "", text.lower())


def _action(
    kind: ActionKind,
    label: str,
    visual_target: str,
    parameters: Optional[dict[str, str]] = None,
    phase: Literal["理解", "准备", "检索", "分析", "执行", "核验", "交付"] = "执行",
    risk_level: Literal["low", "medium", "high"] = "low",
    requires_confirmation: bool = False,
) -> dict[str, object]:
    return {
        "kind": kind,
        "label": label,
        "visual_target": visual_target,
        "parameters": parameters or {},
        "phase": phase,
        "risk_level": risk_level,
        "requires_confirmation": requires_confirmation,
    }


def _extract_range(text: str) -> str:
    if any(word in text for word in ["30日", "30天", "一个月", "月度"]):
        return "30d"
    if any(word in text for word in ["7日", "7天", "一周", "本周", "周度"]):
        return "7d"
    return "today"


def _looks_like_question(command: str, normalized: str) -> bool:
    if "?" in command or "？" in command:
        return True
    question_phrases = (
        "是什么", "为什么", "什么", "怎么", "如何", "哪些", "哪个", "是否", "能否",
        "应该", "先检查", "请解释", "介绍一下", "有什么区别", "有什么作用",
    )
    return any(phrase in normalized for phrase in question_phrases)


def _plan_actions(command: str) -> tuple[str, str, float, list[dict[str, object]]]:
    text = _normalize(command)
    actions: list[dict[str, object]] = []
    intent = "general_question"
    summary = "这更像一个知识问题，将继续使用证据问答。"
    confidence = 0.25

    # Safety-first intent routing: questions about a system or operation are not
    # commands to manipulate it. Explicit imperative phrases continue below.
    if _looks_like_question(command, text):
        return intent, summary, 0.92, actions

    has_launch_verb = any(word in text for word in ["启动", "打开", "运行", "进入"])
    linked_launch_specs = (
        (
            any(word in text for word in ["数字孪生", "港口ai运营中枢", "港口ai平台"]),
            "port-dt-multi",
            "港口数字孪生",
            "launch_port_digital_twin",
        ),
        (
            any(word in text for word in ["能碳驾驶舱", "能耗驾驶舱", "能源驾驶舱"]),
            "energy-cockpit",
            "能碳驾驶舱",
            "launch_energy_cockpit",
        ),
        (
            "马六甲" in text and any(word in text for word in ["推演", "沙盘", "系统"]),
            "malacca-sandbox",
            "马六甲推演",
            "launch_malacca_sandbox",
        ),
    )
    if has_launch_verb:
        for matched, target, label, linked_intent in linked_launch_specs:
            if not matched:
                continue
            parameters = {"target": target, "label": label}
            return linked_intent, f"从小懿启动{label}，等待业务健康检查后进入对应系统。", 0.99, [
                _action("check_linked_system_runtime", f"检查{label}运行状态", "linked-system-runtime", parameters, phase="理解"),
                _action("launch_linked_system_runtime", f"启动{label}", "linked-system-launch", parameters, phase="执行"),
                _action("verify_linked_system_runtime", f"核验{label}业务健康", "linked-system-health", parameters, phase="核验"),
                _action("open_linked_system_runtime", f"进入{label}", "linked-system-open", parameters, phase="交付"),
            ]

    is_simulator_launch = (
        text in {"启动模拟器", "打开模拟器", "运行模拟器", "进入模拟器"}
        or (has_launch_verb and any(word in text for word in ["航行模拟器", "无人航行模拟器"]))
    )
    if is_simulator_launch:
        return "launch_sailing_simulator", "从小懿启动桌面航行模拟器，核验 Godot 主进程后切换到仿真窗口。", 0.99, [
            _action("check_simulator_runtime", "识别航行模拟器项目与 Godot 运行环境", "simulator-runtime", phase="理解"),
            _action("launch_simulator", "启动桌面航行模拟器主场景", "simulator-launch", phase="执行"),
            _action("verify_simulator_runtime", "核验航行模拟器主进程", "simulator-health", phase="核验"),
            _action("open_simulator", "切换到航行模拟器窗口", "simulator-open", phase="交付"),
        ]

    is_agv_energy_rl = (
        any(word in text for word in ["rl实验", "rl训练", "强化学习训练", "五算法", "pid基线"])
        or (
            "agv" in text
            and any(word in text for word in ["充换电", "充电", "能耗", "能源"])
            and any(word in text for word in ["rl", "强化学习", "联合优化", "策略"])
        )
    )
    if is_agv_energy_rl:
        return "optimize_agv_energy_rl", "运行真实数据驱动的四种RL算法与PID基线训练、隔离测试和审计。", 0.98, [
            _action("open_rl_mission", "打开可复现RL训练实验室", "rl-mission-core", {"horizon_steps": "72"}, phase="理解"),
            _action("check_rl_systems", "校验公开数据、算法注册表和隔离门禁", "rl-mission-topology", phase="准备"),
            _action("build_rl_scenario", "建立数据哈希与时间顺序训练/验证/测试划分", "rl-mission-scenario", phase="准备"),
            _action("replay_rl_training", "启动真实训练并读取后台进度", "rl-mission-training", phase="分析"),
            _action("run_rl_competition", "训练完成后在保留测试集渲染五种基线", "rl-mission-race", phase="分析", risk_level="medium"),
            _action("verify_rl_policy", "核验模型哈希、测试隔离与生产写入锁", "rl-mission-guardrail", phase="核验", risk_level="medium"),
            _action(
                "dispatch_rl_dry_run",
                "确认并归档本地测试Dry-run",
                "rl-mission-confirmation",
                phase="执行",
                risk_level="high",
                requires_confirmation=True,
            ),
            _action("present_rl_mission", "回写真实训练与测试审计结果", "rl-mission-result", phase="交付"),
        ]

    dangerous_patterns = [
        ("岸电", ["启动", "开启", "停止", "关闭"], "ems", "岸电启停建议"),
        ("岸桥", ["启动", "停止", "控制"], "tos", "岸桥控制建议"),
        ("agv", ["调度", "停止", "控制", "派车"], "tos", "AGV 调度建议"),
        ("泊位", ["修改", "变更", "下发", "锁定"], "tos", "泊位计划变更建议"),
        ("预警", ["关闭", "消警", "派单"], "eam", "预警处置写操作"),
    ]
    for subject, verbs, connector, label in dangerous_patterns:
        if subject in text and any(verb in text for verb in verbs):
            intent = "live_operation_request"
            summary = f"已识别真实生产写操作请求：{label}。界面只会生成方案并等待授权确认。"
            confidence = 0.96
            actions.extend(
                [
                    _action("navigate", "打开任务中心", "nav-tasks", {"view": "tasks"}, phase="准备"),
                    _action("inspect_connectors", "核验目标生产接口状态", "connector-preflight", {"connector": connector}, phase="核验"),
                    _action("inspect_decision", "生成操作影响与回滚检查", "live-action-impact", {"command": command}, phase="分析", risk_level="medium"),
                    _action(
                        "propose_live_action",
                        label,
                        "live-action-confirmation",
                        {"connector": connector, "command": command},
                        phase="执行",
                        risk_level="high",
                        requires_confirmation=True,
                    ),
                    _action("present_result", "返回对话并交付安全预检结果", "chat-answer", {"result_type": "live_operation"}, phase="交付"),
                ]
            )
            return intent, summary, confidence, actions

    if "新建对话" in text or "重新对话" in text:
        return "new_chat", "新建一个干净对话。", 0.99, [
            _action("new_chat", "清理当前对话上下文", "new-chat", phase="执行"),
            _action("verify_view", "核验新对话工作区状态", "chat-ready", {"view": "chat"}, phase="核验"),
            _action("present_result", "提示新对话已就绪", "chat-answer", {"result_type": "navigation"}, phase="交付"),
        ]
    if "历史" in text:
        return "show_history", "打开对话历史并核验可恢复记录。", 0.98, [
            _action("show_history", "打开对话历史", "history", phase="执行"),
            _action("verify_view", "核验历史记录已加载", "history-ready", {"view": "history"}, phase="核验"),
            _action("present_result", "确认历史面板可用", "operation-result", {"result_type": "navigation"}, phase="交付"),
        ]
    if "收藏" in text:
        return "show_favorites", "打开我的收藏并核验收藏记录。", 0.97, [
            _action("show_favorites", "打开我的收藏", "favorites", phase="执行"),
            _action("verify_view", "核验收藏记录已加载", "favorites-ready", {"view": "favorites"}, phase="核验"),
            _action("present_result", "确认收藏面板可用", "operation-result", {"result_type": "navigation"}, phase="交付"),
        ]
    if "设置" in text:
        return "show_settings", "打开系统设置并核验服务状态。", 0.97, [
            _action("show_settings", "打开系统设置", "settings", phase="执行"),
            _action("verify_view", "核验知识索引与接口状态", "settings-ready", {"view": "settings"}, phase="核验"),
            _action("present_result", "确认设置面板可用", "operation-result", {"result_type": "navigation"}, phase="交付"),
        ]
    if "形象" in text or "头像" in text:
        return "switch_avatar", "打开小懿形象选择并等待用户选择。", 0.96, [
            _action("switch_avatar", "打开小懿形象选择", "avatar-switch", phase="执行"),
            _action("verify_view", "核验形象资源已加载", "avatar-ready", {"view": "avatar"}, phase="核验"),
            _action("present_result", "提示形象选择已就绪", "operation-result", {"result_type": "navigation"}, phase="交付"),
        ]

    if any(word in text for word in ["报告", "日报", "简报"]):
        intent = "generate_report"
        summary = "打开数据分析并生成结构化运营报告。"
        confidence = 0.94
        energy_report = any(word in text for word in ["能耗", "碳排", "能源", "岸电"])
        report_type = "energy" if energy_report else "management_brief"
        actions.append(_action("navigate", "打开数据分析", "nav-analytics", {"view": "analytics"}, phase="准备"))
        if energy_report:
            actions.append(
                _action(
                    "set_range",
                    "切换报告数据时间范围",
                    "analytics-range",
                    {"range": _extract_range(text)},
                    phase="准备",
                )
            )
            actions.append(_action("inspect_metrics", "读取能耗与碳排关键指标", "analytics-kpis", {"range": _extract_range(text)}, phase="分析"))
        actions.extend([
            _action(
                "generate_report",
                "生成结构化分析报告",
                "generate-report",
                {"report_type": report_type, "range": _extract_range(text) if energy_report else "today"},
                phase="执行",
            ),
            _action("validate_report", "校验报告章节与数据声明", "report-validation", phase="核验"),
            _action("present_report", "返回对话并展示报告摘要", "chat-answer", phase="交付"),
        ])
        return intent, summary, confidence, actions

    if any(word in text for word in ["泊位冲突", "泊位调度", "调度优化", "船舶调度"]):
        intent = "optimize_berth"
        summary = "进入决策建议并创建泊位调度模拟任务。"
        confidence = 0.95
        actions.extend(
            [
                _action("navigate", "打开决策建议", "nav-decisions", {"view": "decisions"}),
                _action("inspect_decision", "读取泊位冲突与约束条件", "decision-context", {"command": command}, phase="分析"),
                _action(
                    "create_task",
                    "创建泊位调度候选建议任务",
                    "task-optimize-berth",
                    {"template_id": "optimize-berth"},
                    phase="执行",
                    risk_level="medium",
                ),
                _action("advance_task", "校验船期与泊位窗口", "task-step", phase="执行"),
                _action("advance_task", "分析岸线、吃水与设备约束", "task-step", phase="执行"),
                _action("advance_task", "生成启发式候选调度顺序", "task-step", phase="分析"),
                _action("advance_task", "评估冲突、延误与作业风险", "task-step", phase="核验"),
                _action("advance_task", "归档候选建议与审计轨迹", "task-step", phase="执行"),
                _action("inspect_task_result", "核验候选建议完整性", "task-result", phase="核验"),
                _action("present_result", "返回对话并交付调度建议", "chat-answer", {"result_type": "task"}, phase="交付"),
            ]
        )
        return intent, summary, confidence, actions

    if any(word in text for word in ["能耗", "碳排", "岸电", "能源", "趋势"]) and not any(
        word in text for word in ["知识库", "智库", "知识全景", "查资料", "搜索资料"]
    ):
        intent = "analyze_energy"
        range_ = _extract_range(text)
        summary = f"打开数据分析，切换到 {range_} 范围，并创建能耗分析任务。"
        confidence = 0.93
        actions.extend(
            [
                _action("navigate", "打开数据分析", "nav-analytics", {"view": "analytics"}),
                _action("set_range", "切换能耗时间范围", "analytics-range", {"range": range_}),
                _action("inspect_metrics", "读取能耗、碳排与岸电指标", "analytics-kpis", {"range": range_}, phase="分析"),
                _action(
                    "create_task",
                    "创建能耗分析任务",
                    "task-analyze-energy",
                    {"template_id": "analyze-energy"},
                ),
                _action("advance_task", "校验能耗数据完整性", "task-step", phase="执行"),
                _action("advance_task", "建立同期与基线对比", "task-step", phase="分析"),
                _action("advance_task", "识别峰值时段与异常设备", "task-step", phase="分析"),
                _action("advance_task", "生成节能降碳建议", "task-step", phase="执行"),
                _action("advance_task", "归档分析结果与审计轨迹", "task-step", phase="核验"),
                _action("inspect_task_result", "核验分析任务完成状态", "task-result", phase="核验"),
                _action("present_result", "返回对话并交付能耗结论", "chat-answer", {"result_type": "energy"}, phase="交付"),
            ]
        )
        return intent, summary, confidence, actions

    if any(word in text for word in ["预警", "告警", "异常提醒"]):
        return "show_alerts", "打开预警、检索处置依据并生成可审计建议。", 0.91, [
            _action("show_alerts", "打开预警与提醒", "notifications", phase="准备"),
            _action("inspect_decision", "归并当前告警与影响范围", "alert-context", {"command": command}, phase="分析"),
            _action("set_mode", "切换到 SOP 回答模式", "mode-sop", {"mode": "sop"}, phase="准备"),
            _action("ask", "检索告警处置 SOP", "knowledge-reasoning", {"question": command}, phase="检索"),
            _action("verify_sources", "核验处置依据与来源等级", "evidence-check", phase="核验"),
            _action("validate_answer", "检查风险边界与人工确认点", "answer-validation", phase="核验"),
            _action("present_result", "返回对话并交付处置建议", "chat-answer", {"result_type": "knowledge"}, phase="交付"),
        ]

    if any(word in text for word in ["接口中心", "连接器", "真实港口接口", "接口状态"]):
        return "show_connectors", "打开真实港口接口中心并核验连接、字段与写操作门禁。", 0.96, [
            _action("open_panel", "打开接口中心", "connectors", {"panel": "connectors"}, phase="准备"),
            _action("inspect_connectors", "读取八类连接器在线状态", "connector-health", phase="分析"),
            _action("inspect_connectors", "核验字段映射与能力清单", "connector-mapping", {"detail": "mapping"}, phase="核验"),
            _action("inspect_connectors", "检查生产写操作安全门禁", "connector-guard", {"detail": "guard"}, phase="核验"),
            _action("present_result", "交付接口装配检查结果", "operation-result", {"result_type": "connectors"}, phase="交付"),
        ]

    if any(word in text for word in ["来源审计", "来源登记", "知识来源"]):
        return "knowledge_sources", "打开知识库来源审计。", 0.96, [
            _action("navigate", "打开港航知识库", "nav-knowledge", {"view": "knowledge"}),
            _action("open_panel", "打开来源审计", "knowledge-sources", {"panel": "knowledge_sources"}),
        ]

    if any(word in text for word in ["待审核资料", "待审核知识", "资料隔离区"]):
        return "knowledge_intake", "打开知识资料待审核隔离区。", 0.96, [
            _action("navigate", "打开港航知识库", "nav-knowledge", {"view": "knowledge"}),
            _action("open_panel", "打开待审核资料", "knowledge-intake", {"panel": "knowledge_intake"}),
        ]

    if any(word in text for word in ["知识库", "智库", "知识全景", "查资料", "搜索资料"]):
        intent = "search_knowledge"
        summary = "打开港航知识库并按指令关键词筛选已索引资料。"
        confidence = 0.90
        query = command
        for prefix in ["帮我", "请", "打开", "进入", "知识库", "智库", "查资料", "搜索资料", "查询"]:
            query = query.replace(prefix, "")
        query = query.strip(" ，。") or "港航"
        return intent, summary, confidence, [
            _action("navigate", "打开港航知识库", "nav-knowledge", {"view": "knowledge"}, phase="准备"),
            _action("inspect_knowledge", "检查索引、分类与知识版本", "knowledge-status", phase="准备"),
            _action("filter_knowledge", "检索正文索引与相关片段", "knowledge-search", {"query": query}, phase="检索"),
            _action("verify_sources", "核验官方来源、版本与校验哈希", "evidence-check", phase="核验"),
            _action("set_mode", "切换到专业严格证据模式", "mode-expert", {"mode": "expert"}, phase="准备"),
            _action("ask", "生成基于索引证据的专业回答", "knowledge-reasoning", {"question": query}, phase="分析"),
            _action("validate_answer", "校验回答覆盖率与证据边界", "answer-validation", phase="核验"),
            _action("present_result", "返回智能对话并交付完整答案", "chat-answer", {"result_type": "knowledge"}, phase="交付"),
        ]

    view_patterns = [
        ("数据分析", "analytics", "打开数据分析"),
        ("决策建议", "decisions", "打开决策建议"),
        ("任务中心", "tasks", "打开任务中心"),
        ("智能对话", "chat", "返回智能对话"),
    ]
    for keyword, view, label in view_patterns:
        if keyword in text:
            return "navigate", label, 0.95, [
                _action("navigate", label, f"nav-{view}", {"view": view}, phase="执行"),
                _action("verify_view", "核验目标工作区已加载", f"{view}-ready", {"view": view}, phase="核验"),
                _action("present_result", "确认导航操作完成", "operation-result", {"result_type": "navigation"}, phase="交付"),
            ]

    return intent, summary, confidence, actions


def _create_plan(payload: AutomationPlanRequest) -> AutomationPlan:
    intent, summary, confidence, raw_actions = _plan_actions(payload.command)
    now = _now()
    plan_id = f"plan-{uuid4().hex[:12]}"
    actions = [
        AutomationAction(
            id=f"{plan_id}-action-{index}",
            order=index,
            status="running" if index == 1 else "pending",
            **action,
        )
        for index, action in enumerate(raw_actions, start=1)
    ]
    actionable = bool(actions)
    return AutomationPlan(
        id=plan_id,
        command=payload.command,
        intent=intent,
        summary=summary,
        confidence=confidence,
        actionable=actionable,
        execution_mode=payload.execution_mode,
        data_notice="界面自动操作仅执行固定白名单动作；生产系统写操作必须单独授权确认。",
        status="running" if actionable else "ready",
        current_action_id=actions[0].id if actions else None,
        created_at=now,
        updated_at=now,
        actions=actions,
        audit_trail=[
            AutomationAuditEvent(
                timestamp=now,
                event="plan-created",
                detail=f"识别意图 {intent}，生成 {len(actions)} 个白名单步骤。",
            )
        ],
    )


@router.post("/plans", response_model=AutomationPlan, status_code=201)
def create_plan(payload: AutomationPlanRequest) -> AutomationPlan:
    return _plans.save(_create_plan(payload))


@router.get("/plans", response_model=list[AutomationPlan])
def list_plans() -> list[AutomationPlan]:
    return _plans.list()


@router.get("/plans/{plan_id}", response_model=AutomationPlan)
def get_plan(plan_id: str) -> AutomationPlan:
    plan = _plans.get(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="智能操作计划不存在或已过期")
    return plan


@router.post("/plans/{plan_id}/next", response_model=AutomationAdvanceResponse)
def advance_plan(plan_id: str, payload: AutomationStepResult) -> AutomationAdvanceResponse:
    result = _plans.advance(plan_id, payload)
    if result is None:
        raise HTTPException(status_code=404, detail="智能操作计划不存在或已过期")
    return result


@router.post("/plans/{plan_id}/confirm", response_model=AutomationPlan)
def confirm_plan_action(plan_id: str, payload: AutomationConfirmRequest, request: Request) -> AutomationPlan:
    identity = request_identity(request)
    if identity.authenticated:
        payload = payload.model_copy(update={"operator": identity.actor_id})
    plan = _plans.confirm(plan_id, payload)
    if plan is None:
        raise HTTPException(status_code=404, detail="智能操作计划不存在或已过期")
    return plan
