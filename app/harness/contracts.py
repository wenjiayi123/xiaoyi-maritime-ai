from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSION = "xiaoyi-harness.v1"
TERMINAL = {"completed", "partial", "failed", "cancelled", "budget_exceeded", "blocked", "needs_review"}
WAITING = {"paused", "waiting_input", "waiting_approval"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def completed_tools(task: dict) -> set[str]:
    return {
        name
        for result in task.get("results", [])
        if result["ok"]
        for name in result.get("executed_tools", [result["tool"]])
    }


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Budget(StrictModel):
    max_steps: int = Field(12, ge=1, le=40)
    max_tool_calls: int = Field(16, ge=1, le=64)
    max_active_seconds: float = Field(180, ge=5, le=1800)
    max_tokens: int = Field(16000, ge=512, le=100000)
    context_chars: int = Field(18000, ge=4000, le=64000)
    max_output_chars: int = Field(8000, ge=1000, le=20000)


class JointContext(StrictModel):
    scenario: Literal["normal", "peak-arrivals", "extreme-weather"] = "normal"
    mutate_sandbox: bool = False
    require_mobile: bool = True
    max_seconds: int = Field(360, ge=30, le=7200)
    workflow: Literal["assessment", "full_business"] = "assessment"
    voyage_scenario: Literal[
        "open_water",
        "harbor",
        "auto_berthing",
        "auto_unberthing",
        "narrow_channel_head_on",
        "crossing_starboard",
        "narrow_channel_overtaking",
    ] = "open_water"
    overtaking_agreement_confirmed: bool = False
    business_approval: Literal["human", "role_rehearsal"] = "human"
    experiment_id: str | None = Field(None, pattern=r"^hr-[a-f0-9]{32}$")


class CreateTask(StrictModel):
    goal: str = Field(min_length=2, max_length=4000)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")
    driver: Literal["auto", "model", "rules"] = "auto"
    planning_mode: Literal["contract", "adaptive"] = "contract"
    mode: Literal["enterprise", "research"] = "enterprise"
    model_profile: Literal["existing", "open_agent"] = "existing"
    joint_context: JointContext | None = None
    operations_context: dict[str, Any] | None = Field(None, max_length=5)
    skills: list[str] = Field(default_factory=lambda: ["maritime-evidence"], max_length=5)
    allowed_tools: list[str] | None = Field(None, max_length=40)
    required_tools: list[str] | None = Field(None, max_length=40)
    budget: Budget = Field(default_factory=Budget)
    use_memory: bool = False
    template_id: (
        Literal[
            "port-briefing",
            "port-query",
            "twin-study",
            "port-future-study",
            "strategy-research",
            "joint-preview",
            "crossport-review",
            "remediation-review",
            "operations-study",
        ]
        | None
    ) = None


    @model_validator(mode="after")
    def validate_operations_context(self):
        if self.planning_mode == "adaptive" and (self.template_id or self.driver == "rules"):
            raise ValueError("自主任务使用真实模型，不能绑定固定模板或规则驱动")
        if self.operations_context is not None:
            from app.harness.operations_v5 import OptimizeArgs

            self.operations_context = OptimizeArgs.model_validate(self.operations_context).model_dump(mode="json")
        return self


class Action(StrictModel):
    kind: Literal["tool", "plan", "ask", "final"]
    tool: str | None = Field(None, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)
    text: str = Field("", max_length=12000)
    steps: list[str] = Field(default_factory=list, max_length=12)
    evidence_ids: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def coherent(self):
        if self.kind == "tool" and not self.tool:
            raise ValueError("工具动作必须指定登记工具")
        if self.kind in {"ask", "final"} and not self.text.strip():
            raise ValueError("追问和交付必须包含正文")
        if self.kind == "plan" and (not self.steps or any(not s.strip() or len(s) > 300 for s in self.steps)):
            raise ValueError("计划需要1至12个非空步骤，每步不超过300字符")
        return self


class InputRequest(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")


class ApprovalRequest(StrictModel):
    approval_id: str = Field(min_length=8, max_length=100)
    action_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    approve: bool


class MemoryRequest(StrictModel):
    text: str = Field(min_length=1, max_length=1000)
    label: str = Field("用户显式保存", max_length=80)


DUAL_TEMPLATES = [
    {
        "id": "operations-study",
        "name": "公开数据驱动的联合排程实证",
        "mode": "research",
        "goal": "在默认登记新港、2026-05-18公开指标驱动的合成工单上，真实求解泊位、引航、岸桥、集卡、堆场与供电联合优化，比较四个启发式并核对求解界限；列清来源、合成假设和未改善结果，不执行现场调度。",
        "required_tools": ["operations.optimize"],
        "seconds": 300,
        "max_tokens": 24000,
    },
    {
        "id": "remediation-review",
        "name": "八项整改与2026独立留出审阅",
        "mode": "research",
        "goal": "审阅最新八项整改与2026独立留出：核对RL与强MPC、纯模仿快照、新国际港口、需求区间、物理标定失败和当前全仓发布证据。保留缺测、失败与现场缺项；只读审阅，不启动训练或现场控制。",
        "required_tools": ["crossport.diagnosis", "remediation.review"],
        "seconds": 420,
        "max_tokens": 24000,
    },
    {
        "id": "crossport-review",
        "name": "跨港RL诊断与孪生标定审阅",
        "mode": "research",
        "goal": "审阅已完成的跨港跨时段RL研究，核对旧RL落后PID的实证原因、整港和未来期留出、压力失败以及多站点孪生标定边界；保留不利结果，不启动训练或现场控制。",
        "required_tools": ["crossport.diagnosis", "crossport.compare"],
        "seconds": 420,
        "max_tokens": 24000,
    },
    {
        "id": "strategy-research",
        "name": "RL策略与基线研究",
        "mode": "research",
        "goal": "核对最新完成的业务RL研究实验，比较基线与候选，报告验证集选型、测试结果及失败条件，不执行生产调度。",
        "required_tools": ["strategy.compare", "strategy.replay"],
        "seconds": 300,
        "max_tokens": 16000,
    },
    {
        "id": "joint-preview",
        "name": "六系统联合任务计划",
        "mode": "enterprise",
        "goal": "为交通、航行样本、港区负荷、能碳和移动端生成联合任务计划，先预览参数与审批，不直接执行。",
        "required_tools": ["joint.preview"],
        "seconds": 300,
        "max_tokens": 16000,
    },
]
