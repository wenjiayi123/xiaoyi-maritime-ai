from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import linked_system_launcher, sailing_simulator_launcher
from app.domain_context import DomainContext
from app.runtime_store import runtime_store


router = APIRouter(prefix="/api/system-linkage", tags=["小懿四系统联动网关"])

SystemTarget = Literal[
    "port-dt-multi",
    "energy-cockpit",
    "malacca-sandbox",
    "sailing-simulator",
]
CommandTarget = Literal[
    "all",
    "port-dt-multi",
    "energy-cockpit",
    "malacca-sandbox",
    "sailing-simulator",
]

_XIAOYI_ROOT = Path(__file__).resolve().parents[1]
_BRIDGE_DIR = Path(
    os.getenv(
        "XIAOYI_SAILING_BRIDGE_DIR",
        str(_XIAOYI_ROOT / ".runtime" / "sailing-bridge"),
    )
).expanduser()
_BRIDGE_REQUEST = _BRIDGE_DIR / "malacca_validation_request.json"
_BRIDGE_RESULT = _BRIDGE_DIR / "malacca_validation_result.json"
_ENERGY_API = os.getenv("XIAOYI_ENERGY_API_URL", "http://127.0.0.1:8808").rstrip("/")

_last_results: dict[str, dict[str, Any]] = {}


class LinkageCommandRequest(BaseModel):
    target: CommandTarget
    command: str = Field(
        "读取当前业务态势并给出可追溯摘要",
        min_length=2,
        max_length=1000,
    )
    session_id: str = Field("default", min_length=1, max_length=120)
    context: DomainContext = Field(default_factory=DomainContext)
    parameters: dict[str, Any] = Field(default_factory=dict)
    auto_start: bool = True
    wait_seconds: float = Field(20.0, ge=1.0, le=45.0)


class LinkageStartRequest(BaseModel):
    targets: list[SystemTarget] = Field(..., min_length=1, max_length=4)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _local_json(
    method: Literal["GET", "POST"],
    url: str,
    *,
    payload: Optional[dict[str, Any]] = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("联动网关只允许访问登记的本机 HTTP 服务")
    raw_body = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    headers = {"Accept": "application/json"}
    if raw_body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, method=method, headers=headers, data=raw_body)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_000)
            parsed_body = json.loads(raw)
            if not isinstance(parsed_body, dict):
                return {"items": parsed_body}
            return parsed_body
    except HTTPError as exc:
        detail = exc.read(4_000).decode("utf-8", "replace")
        raise RuntimeError(f"目标系统返回 HTTP {exc.code}：{detail[:500]}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"目标系统请求失败：{exc}") from exc


def _web_runtime(target: str) -> dict[str, Any]:
    payload = linked_system_launcher.linked_systems_status(targets=target)
    runtime = payload.systems[target]
    return runtime.model_dump(mode="json")


def _sailing_runtime() -> dict[str, Any]:
    runtime = sailing_simulator_launcher.sailing_simulator_status()
    return runtime.model_dump(mode="json")


def _runtime(target: SystemTarget) -> dict[str, Any]:
    if target == "sailing-simulator":
        return _sailing_runtime()
    return _web_runtime(target)


def _ensure_running(target: SystemTarget, wait_seconds: float) -> dict[str, Any]:
    runtime = _runtime(target)
    if runtime.get("running"):
        return runtime

    if target == "sailing-simulator":
        sailing_simulator_launcher.launch_sailing_simulator(
            sailing_simulator_launcher.SailingSimulatorLaunchRequest()
        )
    else:
        linked_system_launcher.launch_linked_systems(
            linked_system_launcher.LinkedSystemsLaunchRequest(targets=[target])
        )

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        runtime = _runtime(target)
        if runtime.get("running"):
            return runtime
        if runtime.get("state") in {"error", "port_conflict", "unavailable"}:
            break
        time.sleep(0.35)
    raise RuntimeError(runtime.get("message") or f"{target} 未在限定时间内就绪")


def _compact_port(
    action_payload: dict[str, Any],
    health: dict[str, Any],
) -> dict[str, Any]:
    action = (
        action_payload.get("action")
        if isinstance(action_payload.get("action"), dict)
        else {}
    )
    execution = (
        action_payload.get("execution")
        if isinstance(action_payload.get("execution"), dict)
        else {}
    )
    systems = health.get("systems") if isinstance(health.get("systems"), dict) else {}
    return {
        "matched": action_payload.get("matched"),
        "action_id": action.get("id"),
        "action_label": action.get("label") or action.get("button_label"),
        "route": action.get("route"),
        "execution_status": execution.get("status") or action_payload.get("status"),
        "dry_run": True,
        "requires_human_confirm": action.get("requires_human_confirm", False),
        "integration_ready": health.get("ok"),
        "online_systems": sum(
            bool(item.get("online"))
            for item in systems.values()
            if isinstance(item, dict)
        ),
        "registered_systems": len(systems),
        "desktop_integrations_enabled": health.get("desktop_integrations_enabled"),
        "production_write_enabled": False,
    }


def _compact_energy(payload: dict[str, Any]) -> dict[str, Any]:
    kpis = payload.get("kpis") if isinstance(payload.get("kpis"), list) else []
    strategies = payload.get("strategies") if isinstance(payload.get("strategies"), list) else []
    carbon_market = (
        payload.get("carbon_market")
        if isinstance(payload.get("carbon_market"), dict)
        else {}
    )
    environment = (
        payload.get("rl_environment")
        if isinstance(payload.get("rl_environment"), dict)
        else {}
    )
    return {
        "scenario_id": payload.get("scenario_id"),
        "green_preference": payload.get("green_preference"),
        "kpis": [
            {
                "label": item.get("label"),
                "value": item.get("value"),
                "unit": item.get("unit"),
                "delta": item.get("delta"),
            }
            for item in kpis[:6]
            if isinstance(item, dict)
        ],
        "strategies": [item.get("strategy") for item in strategies[:3] if isinstance(item, dict)],
        "total_cost_saving_cny": carbon_market.get("total_cost_saving_cny"),
        "abatement_ton": carbon_market.get("abatement_ton"),
        "dataset_id": environment.get("dataset_id"),
        "dataset_sha256": environment.get("dataset_sha256"),
        "production_dispatch_enabled": (
            payload.get("governance", {}).get("production_dispatch_enabled")
            if isinstance(payload.get("governance"), dict)
            else None
        ),
    }


def _compact_malacca(
    health: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    scenario = snapshot.get("scenario") if isinstance(snapshot.get("scenario"), dict) else {}
    overview = (
        scenario.get("overview")
        if isinstance(scenario.get("overview"), dict)
        else {}
    )
    evidence = (
        snapshot.get("evidence")
        if isinstance(snapshot.get("evidence"), dict)
        else {}
    )
    mpa = evidence.get("mpa") if isinstance(evidence.get("mpa"), dict) else {}
    telemetry = (
        snapshot.get("telemetry")
        if isinstance(snapshot.get("telemetry"), dict)
        else {}
    )
    weather = (
        telemetry.get("weather")
        if isinstance(telemetry.get("weather"), dict)
        else {}
    )
    return {
        "service_status": health.get("status"),
        "engine": health.get("engine"),
        "algorithms": health.get("algorithms", []),
        "training_rendering": health.get("trainingRendering"),
        "evaluation_rendering": health.get("evaluationRendering"),
        "dataset": {
            "source": snapshot.get("source"),
            "agency": mpa.get("agency"),
            "collection_id": mpa.get("collectionId"),
            "dataset_ids": mpa.get("datasetIds", []),
            "period": mpa.get("period"),
        },
        "scenario": {
            "id": scenario.get("id"),
            "name": scenario.get("name"),
            "port_count": overview.get("portCount"),
            "channel_count": overview.get("channelCount"),
            "monitored_vessels": overview.get("monitoredVesselCount"),
        },
        "weather": {
            "wind_speed_ms": weather.get("windSpeedMs"),
            "wave_height_m": weather.get("waveHeightM"),
            "visibility_km": weather.get("visibilityKm"),
        },
        "production_write_enabled": False,
    }


def _sailing_request(
    trace_id: str,
    request: LinkageCommandRequest,
) -> dict[str, Any]:
    params = request.parameters
    risk_events = params.get("riskEvents")
    if not isinstance(risk_events, list):
        risk_events = [
            {
                "id": "xiaoyi-demo-collision-risk",
                "type": "collision-risk",
                "label": "小懿联动碰撞风险验证",
                "affectedArea": "验证航段",
                "severity": "warning",
                "resolved": False,
            }
        ]
    vessel_id = (
        request.context.mmsi
        or request.context.imo_number
        or str(params.get("vesselId") or "xiaoyi-linked-vessel")
    )
    return {
        "requestId": trace_id,
        "source": "xiaoyi-ai-system-linkage",
        "sessionId": request.session_id,
        "instruction": request.command,
        "vesselId": vessel_id,
        "origin": params.get(
            "origin",
            {"portName": "马六甲验证起点", "latitude": 1.26, "longitude": 103.62},
        ),
        "destination": params.get(
            "destination",
            {"portName": "马六甲验证终点", "latitude": 1.38, "longitude": 103.88},
        ),
        "progressPercent": float(params.get("progressPercent", 0.0)),
        "headingDeg": float(params.get("headingDeg", 68.0)),
        "speedProfile": {
            "initialKnots": float(params.get("initialKnots", 8.0)),
            "targetKnots": float(params.get("targetKnots", 10.0)),
            "maxSafeKnots": float(params.get("maxSafeKnots", 14.0)),
        },
        "riskEvents": risk_events,
        "context": request.context.model_dump(exclude_none=True),
        "createdAt": _utc_now(),
    }


def _write_sailing_request(payload: dict[str, Any]) -> None:
    _BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    _BRIDGE_RESULT.unlink(missing_ok=True)
    temporary = _BRIDGE_REQUEST.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(_BRIDGE_REQUEST)


def _wait_sailing_result(request_id: str, wait_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _BRIDGE_RESULT.is_file():
            try:
                payload = json.loads(_BRIDGE_RESULT.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            if isinstance(payload, dict) and payload.get("requestId") == request_id:
                if payload.get("status") != "running":
                    return payload
        time.sleep(0.25)
    raise RuntimeError("航行模拟器已收到指令，但未在限定时间内写回最终验证结果")


def _execute_target(
    target: SystemTarget,
    request: LinkageCommandRequest,
    trace_id: str,
) -> dict[str, Any]:
    started_at = time.monotonic()
    runtime = (
        _ensure_running(target, request.wait_seconds)
        if request.auto_start
        else _runtime(target)
    )
    if not runtime.get("running"):
        raise RuntimeError(runtime.get("message") or "目标系统不在线")

    if target == "port-dt-multi":
        base_url = str(runtime["url"]).rstrip("/") + "/"
        action_payload = _local_json(
            "POST",
            urljoin(base_url, "api/assistant/actions/execute"),
            payload={
                "instruction": request.command,
                "intent": "xiaoyi_system_linkage",
                "dry_run": True,
                "source": "xiaoyi-ai",
                "context": request.context.model_dump(exclude_none=True),
            },
            timeout=8.0,
        )
        health = _local_json(
            "GET",
            urljoin(base_url, "api/rl/integration/health"),
            timeout=8.0,
        )
        payload = {"action": action_payload, "integration_health": health}
        summary = _compact_port(action_payload, health)
        action = "自然语言动作映射与联动健康核验"
        boundary = "真实调用数字孪生动作网关与联动健康接口；只生成 dry-run 动作包，不下发生产控制。"
    elif target == "energy-cockpit":
        payload = _local_json(
            "POST",
            f"{_ENERGY_API}/api/optimization/recompute",
            payload={
                "scenario_id": str(
                    request.parameters.get(
                        "scenario_id",
                        "port_la_2025_public_benchmark",
                    )
                ),
                "green_preference": float(request.parameters.get("green_preference", 0.68)),
                "carbon_price_cny_per_ton": float(
                    request.parameters.get("carbon_price_cny_per_ton", 85.0)
                ),
            },
            timeout=12.0,
        )
        summary = _compact_energy(payload)
        action = "能碳策略重算"
        boundary = "调用能碳后端执行离线策略重算；数据来自登记数据集，不写入生产调度。"
    elif target == "malacca-sandbox":
        base_url = str(runtime["url"]).rstrip("/")
        health = _local_json("GET", f"{base_url}/api/rl/health", timeout=8.0)
        snapshot = _local_json("GET", f"{base_url}/api/public-data/snapshot", timeout=12.0)
        payload = {"health": health, "snapshot": snapshot}
        summary = _compact_malacca(health, snapshot)
        action = "沙盘数据与RL能力读取"
        boundary = "读取沙盘公开数据快照和RL引擎状态；不启动训练、不提交生产动作。"
    else:
        sailing_payload = _sailing_request(trace_id, request)
        _write_sailing_request(sailing_payload)
        sailing_simulator_launcher.focus_sailing_simulator(
            sailing_simulator_launcher.SailingSimulatorLaunchRequest()
        )
        payload = _wait_sailing_result(trace_id, request.wait_seconds)
        summary = {
            key: payload.get(key)
            for key in (
                "status",
                "safePass",
                "riskLevel",
                "recommendedSpeedKnots",
                "estimatedTravelMinutes",
                "minClearanceMeters",
                "collisionCount",
                "groundingCount",
                "delayDeltaMinutes",
                "carbonDeltaTons",
                "loadedScene",
                "summary",
            )
        }
        action = "Godot航行场景验证"
        boundary = "通过本地文件桥加载航线、船舶和风险事件；结果由Godot运行场景回写，不控制实船。"

    result = {
        "trace_id": trace_id,
        "target": target,
        "name": runtime.get("name"),
        "status": "completed",
        "action": action,
        "runtime": runtime,
        "summary": summary,
        "payload_sha256": _sha256(payload),
        "duration_ms": round((time.monotonic() - started_at) * 1000),
        "completed_at": _utc_now(),
        "boundary": boundary,
    }
    _last_results[target] = result
    return result


@router.get("/overview")
def linkage_overview() -> dict[str, Any]:
    systems: dict[str, Any] = {}
    for target in (
        "port-dt-multi",
        "energy-cockpit",
        "malacca-sandbox",
        "sailing-simulator",
    ):
        try:
            runtime = _runtime(target)  # type: ignore[arg-type]
            error = None
        except Exception as exc:  # status aggregation must be best-effort
            runtime = {
                "target": target,
                "state": "error",
                "running": False,
                "message": str(exc),
            }
            error = str(exc)
        systems[target] = {
            "runtime": runtime,
            "last_result": _last_results.get(target),
            "error": error,
        }
    online_count = sum(bool(item["runtime"].get("running")) for item in systems.values())
    return {
        "systems": systems,
        "online_count": online_count,
        "total": len(systems),
        "all_ready": online_count == len(systems),
        "bridge": {
            "request_file": str(_BRIDGE_REQUEST),
            "result_file": str(_BRIDGE_RESULT),
            "request_exists": _BRIDGE_REQUEST.is_file(),
            "result_exists": _BRIDGE_RESULT.is_file(),
        },
        "generated_at": _utc_now(),
        "execution_boundary": "本机联动只面向离线数据、仿真和策略预演；所有生产写入保持关闭。",
    }


@router.post("/start")
def start_linked_targets(payload: LinkageStartRequest) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for target in list(dict.fromkeys(payload.targets)):
        try:
            results[target] = _ensure_running(target, 30.0)
        except Exception as exc:
            results[target] = {
                **_runtime(target),
                "state": "error",
                "running": False,
                "message": str(exc),
            }
    return {
        "systems": results,
        "all_ready": all(item.get("running") for item in results.values()),
        "production_write_enabled": False,
    }


@router.post("/command")
def execute_linkage_command(payload: LinkageCommandRequest) -> dict[str, Any]:
    targets: list[SystemTarget] = (
        [
            "port-dt-multi",
            "energy-cockpit",
            "malacca-sandbox",
            "sailing-simulator",
        ]
        if payload.target == "all"
        else [payload.target]
    )
    correlation_id = f"link-{uuid4().hex}"
    results: list[dict[str, Any]] = []
    for index, target in enumerate(targets, start=1):
        trace_id = f"{correlation_id}-{index}"
        try:
            results.append(_execute_target(target, payload, trace_id))
        except Exception as exc:
            results.append(
                {
                    "trace_id": trace_id,
                    "target": target,
                    "name": _runtime(target).get("name"),
                    "status": "failed",
                    "error": str(exc),
                    "completed_at": _utc_now(),
                }
            )
    succeeded = sum(item["status"] == "completed" for item in results)
    response = {
        "correlation_id": correlation_id,
        "command": payload.command,
        "results": results,
        "succeeded": succeeded,
        "total": len(results),
        "all_succeeded": succeeded == len(results),
        "production_write_enabled": False,
        "execution_boundary": "联动结果来自本机系统API或Godot场景桥；不代表港口生产实时状态，也不下发真实设备或船舶指令。",
        "completed_at": _utc_now(),
    }
    runtime_store.add_audit(
        correlation_id=correlation_id,
        actor_id="local-admin",
        actor_role="admin",
        action="system_linkage.command",
        resource=",".join(targets),
        risk_level="medium",
        outcome="success" if response["all_succeeded"] else "failed",
        request=payload.model_dump(mode="json"),
        response=response,
        detail=f"四系统联动完成 {succeeded}/{len(results)} 项。",
    )
    return response
