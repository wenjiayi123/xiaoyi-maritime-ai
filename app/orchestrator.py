from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.capability_hub import CapabilityInvokeRequest, capabilities, get_capability, invoke_capability
from app.domain_context import ContextResolveResponse, DomainContext, resolve_context
from app.evidence_fusion import EvidenceFusionRequest, ExternalEvidenceInput, fuse_evidence
from app.access_control import has_permission
from app.runtime_store import runtime_store
from app.security import bind_claimed_identity


router = APIRouter(prefix="/api/orchestrator", tags=["小懿跨系统自然语言编排"])


class OrchestrationRequest(BaseModel):
    command: str = Field(..., min_length=2, max_length=1000)
    session_id: str = Field("default", min_length=1, max_length=120)
    context: DomainContext = Field(default_factory=DomainContext)
    actor_id: str = Field("local-admin", min_length=2, max_length=100)
    actor_role: Literal["viewer", "analyst", "operator", "admin"] = "admin"
    execute_read_only: bool = False
    max_capabilities: int = Field(3, ge=1, le=6)


class OrchestrationStep(BaseModel):
    order: int
    phase: str
    action: str
    capability_id: Optional[str] = None
    system_id: Optional[str] = None
    status: str
    risk_level: str = "low"
    requires_confirmation: bool = False
    detail: str = ""


class OrchestrationResponse(BaseModel):
    id: str
    correlation_id: str
    command: str
    intent: str
    context_resolution: ContextResolveResponse
    selected_capabilities: list[str]
    steps: list[OrchestrationStep]
    evidence_trace_id: str
    evidence_summary: str
    grounded: bool
    handoff_links: list[dict[str, str]]
    result_summary: str
    execution_boundary: str
    created_at: datetime


_CAPABILITY_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (("岸电", "能耗", "碳排", "需量", "能碳"), ("energy_linkage_health",), "energy_carbon_analysis"),
    (("能碳训练", "marl", "能耗策略"), ("energy_training_status",), "energy_policy_training"),
    (("港区", "泊位", "岸桥", "设备", "实时态势"), ("portviz_snapshot",), "port_status_analysis"),
    (("实时帧", "动态流", "车辆态势"), ("portviz_stream",), "port_live_stream"),
    (("rl", "训练", "策略状态"), ("rl_training_status",), "rl_status_analysis"),
    (("守护栏", "回滚", "质量门"), ("ops_guard_health",), "guardrail_analysis"),
    (("马六甲", "沙盘", "策略测试", "场景推演"), ("malacca_policy_test",), "simulation_handoff"),
    (("航行", "操船", "航线", "气象扰动"), ("sailing_scenario_handoff",), "sailing_handoff"),
)


def _select(command: str, limit: int) -> tuple[str, list[str]]:
    lower = command.lower()
    selected: list[str] = []
    intents: list[str] = []
    for keywords, capability_ids, intent in _CAPABILITY_RULES:
        if any(keyword.lower() in lower for keyword in keywords):
            intents.append(intent)
            selected.extend(capability_ids)
    selected = list(dict.fromkeys(selected))[:limit]
    return ("+".join(dict.fromkeys(intents)) if intents else "knowledge_only", selected)


def run_orchestration(payload: OrchestrationRequest) -> OrchestrationResponse:
    if payload.execute_read_only and not has_permission(payload.actor_role, "capability.invoke_read"):
        raise HTTPException(status_code=403, detail="当前角色没有跨系统只读调用权限")
    orchestration_id = f"orchestration-{uuid4().hex}"
    correlation_id = f"corr-{uuid4().hex}"
    context_resolution = resolve_context(
        payload.command, session_id=payload.session_id, explicit=payload.context, persist=True
    )
    intent, selected = _select(payload.command, payload.max_capabilities)
    steps: list[OrchestrationStep] = [
        OrchestrationStep(order=1, phase="理解", action="解析港航业务对象与时间范围", status="completed", detail=f"识别字段：{', '.join(context_resolution.detected_fields) or '无显式字段'}"),
        OrchestrationStep(order=2, phase="检索", action="检索港航知识与适用规则", status="completed", detail="采用 hybrid_sparse_v2 混合稀疏召回和二次排序"),
    ]
    external: list[ExternalEvidenceInput] = []
    handoffs: list[dict[str, str]] = []
    for capability_id in selected:
        system, capability = get_capability(capability_id)
        invoke_payload = CapabilityInvokeRequest(
            context=context_resolution.context,
            dry_run=not payload.execute_read_only,
            actor_id=payload.actor_id,
            actor_role=payload.actor_role,
            correlation_id=correlation_id,
        )
        try:
            invocation = invoke_capability(capability_id, invoke_payload)
            step_status = "completed" if invocation.status in {"success", "preview", "handoff_ready"} else "failed"
            external.append(
                ExternalEvidenceInput(
                    source_type="system_result" if invocation.external_request_performed else "capability_contract",
                    source_id=invocation.invocation_id, system_id=system.id, capability_id=capability.id,
                    title=f"{system.name} · {capability.name}", payload=invocation.data,
                    fetched_at=invocation.requested_at,
                    verification_status="live_read" if invocation.external_request_performed else "preview_only",
                    correlation_id=correlation_id,
                )
            )
            if invocation.ui_url:
                handoffs.append({"system_id": system.id, "label": f"打开{system.name}", "url": invocation.ui_url})
            detail = invocation.notice
        except HTTPException as exc:
            step_status = "blocked"
            detail = str(exc.detail)
        steps.append(
            OrchestrationStep(
                order=len(steps) + 1, phase="调用" if capability.method != "NAVIGATE" else "交接",
                action=capability.name, capability_id=capability.id, system_id=system.id,
                status=step_status, risk_level=capability.risk_level, detail=detail,
            )
        )
    fusion = fuse_evidence(
        EvidenceFusionRequest(
            query=payload.command, context=context_resolution.context, top_k=6,
            include_knowledge=True, external_evidence=external,
        ),
        trusted_external=True,
    )
    steps.extend(
        [
            OrchestrationStep(order=len(steps) + 1, phase="核验", action="区分知识、系统与推演证据", status="completed", detail=fusion.evidence_summary),
            OrchestrationStep(order=len(steps) + 2, phase="交付", action="生成解释与原系统跳转", status="completed", detail="小懿只呈现摘要、来源和交接入口"),
        ]
    )
    if selected:
        result_summary = f"已选择 {len(selected)} 项外部系统能力并完成{('只读调用' if payload.execute_read_only else '隔离预览')}；融合 {fusion.evidence_summary}。"
    else:
        result_summary = f"当前问题无需调用其他系统，已完成知识检索；融合 {fusion.evidence_summary}。"
    result = OrchestrationResponse(
        id=orchestration_id, correlation_id=correlation_id, command=payload.command,
        intent=intent, context_resolution=context_resolution, selected_capabilities=selected,
        steps=steps, evidence_trace_id=fusion.trace_id, evidence_summary=fusion.evidence_summary,
        grounded=fusion.grounded, handoff_links=list({item['url']: item for item in handoffs}.values()),
        result_summary=result_summary,
        execution_boundary="默认仅生成跨系统调用预览；execute_read_only=true 也只允许已显式配置 live 的 GET 接口，绝不执行写操作。",
        created_at=datetime.now(timezone.utc),
    )
    runtime_store.add_audit(
        correlation_id=correlation_id, actor_id=payload.actor_id, actor_role=payload.actor_role,
        action="orchestrator.run", resource="xiaoyi-system-hub", risk_level="low", outcome="success",
        request=payload.model_dump(mode="json"), response=result.model_dump(mode="json"), detail=result_summary,
    )
    return result


@router.post("/run", response_model=OrchestrationResponse)
def run_orchestration_api(payload: OrchestrationRequest, request: Request) -> OrchestrationResponse:
    actor_id, actor_role = bind_claimed_identity(request, payload.actor_id, payload.actor_role)
    return run_orchestration(payload.model_copy(update={"actor_id": actor_id, "actor_role": actor_role}))


@router.get("/examples")
def orchestration_examples() -> dict[str, Any]:
    return {
        "items": [
            "分析 CNYTN 未来3小时岸电风险，并告诉我应该去哪个系统看详情",
            "查看港区实时态势和RL训练状态",
            "把场景 SCN-01 和策略 POLICY-PPO 交接到马六甲沙盘测试",
            "检索台风红色预警SOP，不调用其他系统",
        ]
    }
