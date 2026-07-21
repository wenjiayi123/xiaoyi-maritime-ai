from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.domain_context import DomainContext
from app.runtime_store import runtime_store
from app.security import bind_claimed_identity


router = APIRouter(prefix="/api/hub", tags=["小懿跨系统能力中枢"])

SystemMode = Literal["offline", "demo", "live"]
RiskLevel = Literal["low", "medium", "high"]


class CapabilityDefinition(BaseModel):
    id: str
    system_id: str
    name: str
    english_name: str
    description: str
    method: Literal["GET", "POST", "NAVIGATE"]
    path: str
    risk_level: RiskLevel = "low"
    read_only: bool = True
    required_context: list[str] = Field(default_factory=list)
    output_type: str = "system_result"
    ui_anchor: Optional[str] = None


class SystemDefinition(BaseModel):
    id: str
    name: str
    english_name: str
    role: str
    mode: SystemMode
    base_url: Optional[str]
    ui_url: Optional[str]
    health_path: str
    configured: bool
    isolation_notice: str
    capabilities: list[CapabilityDefinition]


class CapabilityInvokeRequest(BaseModel):
    context: DomainContext = Field(default_factory=DomainContext)
    parameters: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True
    actor_id: str = Field("local-admin", min_length=2, max_length=100)
    actor_role: Literal["viewer", "analyst", "operator", "admin"] = "admin"
    correlation_id: Optional[str] = None


class CapabilityInvokeResponse(BaseModel):
    invocation_id: str
    correlation_id: str
    capability_id: str
    system_id: str
    mode: SystemMode
    status: str
    dry_run: bool
    external_request_performed: bool
    requested_at: datetime
    source_url: Optional[str]
    ui_url: Optional[str]
    data: dict[str, Any]
    evidence: dict[str, Any]
    notice: str


_SYSTEM_SPECS = (
    {
        "id": "port-dt-multi", "name": "港口数字孪生与AI平台", "english": "Port Digital Twin & AI Platform",
        "role": "感知、预测、孪生、RL、执行、回滚与审计", "prefix": "PORT_DT", "default_url": "http://127.0.0.1:8000",
        "health": "/health", "ui": "http://127.0.0.1:8000/",
        "capabilities": (
            ("portviz_snapshot", "港区态势快照", "Port Status Snapshot", "读取港区几何、泊位、设备与车辆态势", "GET", "/api/portviz/bootstrap", ["port_code"]),
            ("portviz_stream", "港区实时帧", "Port Live Frame", "读取港区动态流的当前帧", "GET", "/api/portviz/stream", ["port_code"]),
            ("rl_training_status", "RL训练状态", "RL Training Status", "读取策略训练进度、指标与产物状态", "GET", "/api/rl/train/status", []),
            ("ops_guard_health", "策略守护栏状态", "Ops Guardrail Health", "读取执行守护栏、质量门和回滚就绪状态", "GET", "/api/opsx/health", []),
            ("open_twin_workspace", "打开数字孪生平台", "Open Twin Workspace", "跳转到完整数字孪生与RL工作台", "NAVIGATE", "/", []),
        ),
    },
    {
        "id": "energy-cockpit", "name": "能碳驾驶舱", "english": "Energy & Carbon Cockpit",
        "role": "能耗、碳排、岸电与MARL业务决策表达", "prefix": "ENERGY_COCKPIT", "default_url": "http://127.0.0.1:8808",
        "health": "/api/linkage/health", "ui": "http://127.0.0.1:5173/",
        "capabilities": (
            ("energy_linkage_health", "能碳联动状态", "Energy Linkage Health", "读取训练、仿真、航行和小懿联动状态", "GET", "/api/linkage/health", []),
            ("energy_training_status", "能碳策略训练状态", "Energy Policy Training", "读取MARL长时训练进度和剩余时间", "GET", "/api/rl/train/status", []),
            ("open_energy_cockpit", "打开能碳驾驶舱", "Open Energy Cockpit", "跳转到能碳业务驾驶舱", "NAVIGATE", "/", []),
        ),
    },
    {
        "id": "malacca-sandbox", "name": "马六甲沙盘港口推演", "english": "Malacca Port Sandbox",
        "role": "场景推演、策略训练、目标选择与训练后测试", "prefix": "MALACCA", "default_url": "http://127.0.0.1:4173",
        "health": "/", "ui": "http://127.0.0.1:4173/",
        "capabilities": (
            ("open_malacca_sandbox", "打开马六甲推演", "Open Malacca Sandbox", "跳转到场景推演和策略测试工作台", "NAVIGATE", "/", []),
            ("malacca_policy_test", "策略测试交接", "Policy Test Handoff", "生成策略测试所需上下文并交接到沙盘，不在小懿内重复执行", "NAVIGATE", "/", ["scenario_id", "policy_id"]),
        ),
    },
    {
        "id": "sailing-simulator", "name": "航行模拟器", "english": "Sailing Simulator",
        "role": "船舶航行、气象扰动与操纵场景演示", "prefix": "SAILING", "default_url": "",
        "health": "/", "ui": "",
        "capabilities": (
            ("sailing_scenario_handoff", "航行场景交接", "Sailing Scenario Handoff", "生成航行场景参数和本地启动指引，不自动启动Godot", "NAVIGATE", "/", ["scenario_id"]),
        ),
    },
)


def _mode(prefix: str) -> SystemMode:
    value = os.getenv(f"XIAOYI_SYSTEM_{prefix}_MODE", "offline").strip().lower()
    return value if value in {"offline", "demo", "live"} else "offline"  # type: ignore[return-value]


def _system_from_spec(spec: dict[str, Any]) -> SystemDefinition:
    prefix = spec["prefix"]
    mode = _mode(prefix)
    configured_url = os.getenv(f"XIAOYI_SYSTEM_{prefix}_BASE_URL")
    base_url = (configured_url if configured_url is not None else spec["default_url"]).strip() or None
    ui_url = (os.getenv(f"XIAOYI_SYSTEM_{prefix}_UI_URL") or spec["ui"]).strip() or None
    capabilities = [
        CapabilityDefinition(
            id=item[0], system_id=spec["id"], name=item[1], english_name=item[2],
            description=item[3], method=item[4], path=item[5], required_context=item[6],
            read_only=True, risk_level="low", ui_anchor=item[5] if item[4] == "NAVIGATE" else None,
        )
        for item in spec["capabilities"]
    ]
    return SystemDefinition(
        id=spec["id"], name=spec["name"], english_name=spec["english"], role=spec["role"],
        mode=mode, base_url=base_url, ui_url=ui_url, health_path=spec["health"],
        configured=bool(base_url), capabilities=capabilities,
        isolation_notice="默认 offline 不访问其他系统；dry_run 可检查调用契约，只有显式配置 live 才执行登记的GET只读调用。",
    )


def systems() -> list[SystemDefinition]:
    return [_system_from_spec(spec) for spec in _SYSTEM_SPECS]


def capabilities() -> list[CapabilityDefinition]:
    return [capability for system in systems() for capability in system.capabilities]


def get_capability(capability_id: str) -> tuple[SystemDefinition, CapabilityDefinition]:
    for system in systems():
        for capability in system.capabilities:
            if capability.id == capability_id:
                return system, capability
    raise KeyError(capability_id)


def _request_url(system: SystemDefinition, capability: CapabilityDefinition, payload: CapabilityInvokeRequest) -> str | None:
    if capability.method == "NAVIGATE":
        return system.ui_url
    if not system.base_url:
        return None
    url = urljoin(system.base_url.rstrip("/") + "/", capability.path.lstrip("/"))
    params = {**payload.context.model_dump(exclude_none=True), **payload.parameters}
    if params and capability.method == "GET":
        url += ("&" if "?" in url else "?") + urlencode({key: str(value) for key, value in params.items() if value not in ({}, "")})
    return url


def invoke_capability(capability_id: str, payload: CapabilityInvokeRequest) -> CapabilityInvokeResponse:
    try:
        system, capability = get_capability(capability_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"未知系统能力：{capability_id}") from exc
    missing = [name for name in capability.required_context if not getattr(payload.context, name, None)]
    if missing and not payload.dry_run:
        raise HTTPException(status_code=422, detail=f"缺少调用上下文：{', '.join(missing)}")
    if payload.actor_role == "viewer" and not payload.dry_run:
        raise HTTPException(status_code=403, detail="viewer 角色只能查看能力目录和调用预览")
    correlation_id = payload.correlation_id or f"corr-{uuid4().hex}"
    requested_at = datetime.now(timezone.utc)
    source_url = _request_url(system, capability, payload)
    performed = False
    status = "preview"
    data: dict[str, Any] = {
        "required_context": capability.required_context,
        "missing_context": missing,
        "parameters": payload.parameters,
        "context": payload.context.model_dump(exclude_none=True),
    }
    notice = "已生成隔离的能力调用预览，未访问或改变其他系统。"
    if capability.method == "NAVIGATE":
        status = "handoff_ready"
        data["handoff_url"] = system.ui_url
        notice = "已生成原系统深度跳转，不在小懿内复制其业务功能。"
    elif not payload.dry_run:
        if system.mode != "live":
            raise HTTPException(status_code=409, detail="只有显式配置为 live 的系统才能执行真实只读调用")
        if capability.method != "GET":
            raise HTTPException(status_code=403, detail="小懿跨系统中枢当前仅允许真实 GET 只读调用")
        if not source_url:
            raise HTTPException(status_code=409, detail="目标系统未配置基础地址")
        try:
            with urlopen(Request(source_url, method="GET", headers={"Accept": "application/json"}), timeout=3.0) as response:
                raw = response.read(2_000_000)
                content_type = response.headers.get("Content-Type", "")
                parsed = json.loads(raw) if "json" in content_type or raw[:1] in {b"{", b"["} else {"text": raw.decode("utf-8", "replace")[:5000]}
                data = {"payload": parsed, "http_status": getattr(response, "status", 200)}
            performed = True
            status = "success"
            notice = "已完成经配置授权的跨系统只读调用；未执行任何写操作。"
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            status = "failed"
            data = {"error": str(exc)[:500]}
            notice = "目标系统只读调用失败，未执行任何写操作。"
    result = CapabilityInvokeResponse(
        invocation_id=f"invoke-{uuid4().hex}", correlation_id=correlation_id,
        capability_id=capability.id, system_id=system.id, mode=system.mode, status=status,
        dry_run=payload.dry_run, external_request_performed=performed, requested_at=requested_at,
        source_url=source_url, ui_url=system.ui_url, data=data,
        evidence={
            "source_type": "system_result" if performed else "capability_contract",
            "system_id": system.id, "capability_id": capability.id,
            "fetched_at": requested_at.isoformat(), "verification_status": "live_read" if performed else "preview_only",
        },
        notice=notice,
    )
    runtime_store.add_audit(
        correlation_id=correlation_id, actor_id=payload.actor_id, actor_role=payload.actor_role,
        action="capability.invoke", resource=f"{system.id}:{capability.id}", risk_level=capability.risk_level,
        outcome="success" if status in {"success", "preview", "handoff_ready"} else "failed",
        request=payload.model_dump(mode="json"), response=result.model_dump(mode="json"), detail=notice,
    )
    return result


@router.get("/systems")
def list_systems() -> dict[str, Any]:
    items = systems()
    return {"total": len(items), "isolation_mode": True, "items": [item.model_dump(mode="json") for item in items]}


@router.get("/capabilities")
def list_capabilities() -> dict[str, Any]:
    items = capabilities()
    return {"total": len(items), "read_only": all(item.read_only for item in items), "items": [item.model_dump(mode="json") for item in items]}


@router.post("/capabilities/{capability_id}/invoke", response_model=CapabilityInvokeResponse)
def invoke_capability_api(capability_id: str, payload: CapabilityInvokeRequest, request: Request) -> CapabilityInvokeResponse:
    actor_id, actor_role = bind_claimed_identity(request, payload.actor_id, payload.actor_role)
    return invoke_capability(
        capability_id,
        payload.model_copy(update={"actor_id": actor_id, "actor_role": actor_role}),
    )
