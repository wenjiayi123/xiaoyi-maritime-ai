from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from time import perf_counter
from typing import Any, Literal, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request as FastAPIRequest
from pydantic import BaseModel, Field

from app.security import request_identity


ConnectorMode = Literal["demo", "live", "offline"]
ConnectorHealthStatus = Literal[
    "offline",
    "demo",
    "unchecked",
    "online",
    "degraded",
    "misconfigured",
]
AuthType = Literal["none", "api_key", "bearer", "basic", "oauth2", "mtls"]
MappingDirection = Literal["read", "write", "bidirectional"]


router = APIRouter(prefix="/api/connectors", tags=["港口系统连接器"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class FieldMapping(BaseModel):
    canonical_field: str
    external_field: str
    direction: MappingDirection
    data_type: str
    required: bool = False
    description: str


class ConnectorCapabilities(BaseModel):
    read: list[str]
    write: list[str]
    read_only: bool


class ConnectorInfo(BaseModel):
    id: str
    code: str
    name: str
    english_name: str
    system_type: str
    description: str
    mode: ConnectorMode
    health_status: ConnectorHealthStatus
    configured: bool
    base_url: Optional[str]
    auth_type: AuthType
    supported_auth_types: list[AuthType]
    credential_configured: bool
    capabilities: ConnectorCapabilities
    write_enabled: bool
    requires_human_confirmation: bool
    integration_patterns: list[str]
    health_path: str
    mapping_version: str
    field_mappings: list[FieldMapping]
    configuration_errors: list[str]
    configuration_notice: str
    environment_prefix: str


class ConnectorCatalogResponse(BaseModel):
    generated_at: datetime
    total: int
    online: int
    demo: int
    offline: int
    notice: str
    items: list[ConnectorInfo]


class ConnectorHealthResponse(BaseModel):
    connector_id: str
    mode: ConnectorMode
    status: ConnectorHealthStatus
    checked_at: datetime
    reachable: bool
    http_status: Optional[int] = None
    latency_ms: Optional[int] = None
    detail: str
    live_data_verified: bool


class HumanConfirmation(BaseModel):
    confirmed: bool = False
    operator_id: str = Field(..., min_length=2, max_length=100)
    reason: str = Field(..., min_length=4, max_length=300)
    reference: str = Field(..., min_length=4, max_length=120)


class WritePreflightRequest(BaseModel):
    operation: str = Field(..., min_length=2, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)
    confirmation: Optional[HumanConfirmation] = None


class WritePreflightResponse(BaseModel):
    connector_id: str
    operation: str
    authorization_id: str
    authorized: Literal[False] = False
    preflight_recorded: Literal[True] = True
    dispatch_performed: Literal[False] = False
    human_confirmation_recorded: Literal[True] = True
    dual_approval_verified: Literal[False] = False
    production_authority: Literal[False] = False
    authorized_at: datetime
    expires_in_seconds: int
    message: str


@dataclass(frozen=True)
class _ConnectorDefinition:
    id: str
    code: str
    name: str
    english_name: str
    system_type: str
    description: str
    env_key: str
    supported_auth_types: tuple[AuthType, ...]
    read_capabilities: tuple[str, ...]
    write_capabilities: tuple[str, ...]
    integration_patterns: tuple[str, ...]
    field_mappings: tuple[FieldMapping, ...]


@dataclass(frozen=True)
class _RuntimeConfig:
    mode: ConnectorMode
    base_url: Optional[str]
    auth_type: AuthType
    credential: Optional[str]
    write_enabled: bool
    health_path: str
    timeout_seconds: float
    errors: tuple[str, ...]


def _mapping(
    canonical_field: str,
    external_field: str,
    direction: MappingDirection,
    data_type: str,
    description: str,
    required: bool = False,
) -> FieldMapping:
    return FieldMapping(
        canonical_field=canonical_field,
        external_field=external_field,
        direction=direction,
        data_type=data_type,
        required=required,
        description=description,
    )


_DEFINITIONS: tuple[_ConnectorDefinition, ...] = (
    _ConnectorDefinition(
        id="tos",
        code="TOS",
        name="码头操作系统",
        english_name="Terminal Operating System",
        system_type="terminal_operating_system",
        description="衔接船舶计划、泊位、堆场、岸桥、水平运输与作业指令。",
        env_key="TOS",
        supported_auth_types=("api_key", "bearer", "basic", "oauth2", "mtls"),
        read_capabilities=(
            "vessel_calls",
            "berth_plan",
            "yard_inventory",
            "equipment_jobs",
            "work_instructions",
        ),
        write_capabilities=("berth_plan_update", "crane_plan_update", "dispatch_order"),
        integration_patterns=("REST/OpenAPI", "SOAP", "MQ/Kafka", "EDIFACT CODECO/COARRI"),
        field_mappings=(
            _mapping("vessel_call_id", "vesselVisitId", "bidirectional", "string", "船舶挂靠唯一标识", True),
            _mapping("imo_number", "imoNumber", "read", "string", "IMO 船舶编号"),
            _mapping("eta", "estimatedTimeOfArrival", "read", "datetime", "预计到港时间"),
            _mapping("berth_id", "berthId", "bidirectional", "string", "泊位标识"),
            _mapping("container_number", "equipmentNumber", "read", "string", "集装箱箱号"),
        ),
    ),
    _ConnectorDefinition(
        id="pcs",
        code="PCS",
        name="港口社区系统",
        english_name="Port Community System",
        system_type="port_community_system",
        description="衔接港口、船公司、货代、码头、海关及物流参与方的信息交换。",
        env_key="PCS",
        supported_auth_types=("api_key", "bearer", "oauth2", "mtls"),
        read_capabilities=("port_calls", "cargo_status", "party_directory", "document_status"),
        write_capabilities=("community_message", "service_request", "document_exchange"),
        integration_patterns=("REST/OpenAPI", "AS4", "MQ/Kafka", "UN/EDIFACT"),
        field_mappings=(
            _mapping("port_call_id", "portCallReference", "bidirectional", "string", "港口挂靠引用", True),
            _mapping("organization_id", "partyId", "bidirectional", "string", "参与方统一标识"),
            _mapping("document_type", "messageFunction", "bidirectional", "string", "业务报文类型"),
            _mapping("cargo_status", "consignmentStatus", "read", "string", "货物/托运状态"),
            _mapping("event_time", "eventDateTime", "read", "datetime", "业务事件时间"),
        ),
    ),
    _ConnectorDefinition(
        id="ems",
        code="EMS",
        name="能源管理系统",
        english_name="Energy Management System",
        system_type="energy_management_system",
        description="读取电、水、油、气、岸电、设备负荷及碳核算相关数据。",
        env_key="EMS",
        supported_auth_types=("api_key", "bearer", "basic", "oauth2", "mtls"),
        read_capabilities=("meter_readings", "energy_baselines", "shore_power", "carbon_metrics", "energy_alerts"),
        write_capabilities=("alert_threshold_update", "demand_response_plan"),
        integration_patterns=("REST/OpenAPI", "OPC UA Gateway", "MQTT", "Modbus Gateway"),
        field_mappings=(
            _mapping("meter_id", "pointId", "read", "string", "计量点标识", True),
            _mapping("reading_time", "timestamp", "read", "datetime", "采集时间", True),
            _mapping("active_energy_kwh", "activeEnergy", "read", "decimal", "有功电量 kWh"),
            _mapping("shore_power_kwh", "shorePowerEnergy", "read", "decimal", "岸电用电量 kWh"),
            _mapping("carbon_emissions_tco2e", "co2Equivalent", "read", "decimal", "二氧化碳当量 tCO2e"),
        ),
    ),
    _ConnectorDefinition(
        id="eam",
        code="EAM",
        name="企业资产管理系统",
        english_name="Enterprise Asset Management",
        system_type="enterprise_asset_management",
        description="衔接设备台账、状态、点检、故障、备件与维修工单。",
        env_key="EAM",
        supported_auth_types=("api_key", "bearer", "basic", "oauth2", "mtls"),
        read_capabilities=("asset_registry", "asset_status", "fault_events", "maintenance_orders", "spare_parts"),
        write_capabilities=("maintenance_order_create", "maintenance_order_update", "inspection_assignment"),
        integration_patterns=("REST/OpenAPI", "SOAP", "MQ/Kafka"),
        field_mappings=(
            _mapping("asset_id", "assetNumber", "bidirectional", "string", "资产唯一编号", True),
            _mapping("asset_status", "operatingStatus", "read", "string", "设备运行状态"),
            _mapping("fault_code", "failureCode", "read", "string", "故障代码"),
            _mapping("work_order_id", "workOrderNumber", "bidirectional", "string", "维修工单编号"),
            _mapping("planned_start", "scheduledStart", "bidirectional", "datetime", "计划开工时间"),
        ),
    ),
    _ConnectorDefinition(
        id="vts",
        code="VTS",
        name="船舶交通管理系统",
        english_name="Vessel Traffic Service",
        system_type="vessel_traffic_service",
        description="读取监管水域交通态势、航行计划、交通组织与安全信息。",
        env_key="VTS",
        supported_auth_types=("bearer", "oauth2", "mtls"),
        read_capabilities=("traffic_picture", "vessel_movements", "navigation_warnings", "traffic_plan"),
        write_capabilities=("safety_message_draft", "traffic_plan_proposal"),
        integration_patterns=("REST/OpenAPI", "Secure MQ", "IALA data exchange"),
        field_mappings=(
            _mapping("mmsi", "mmsi", "read", "string", "海上移动业务标识", True),
            _mapping("vessel_name", "shipName", "read", "string", "船名"),
            _mapping("position", "position", "read", "geojson", "经纬度位置"),
            _mapping("course_over_ground", "cog", "read", "decimal", "对地航向"),
            _mapping("traffic_event_id", "eventId", "bidirectional", "string", "交通事件标识"),
        ),
    ),
    _ConnectorDefinition(
        id="ais",
        code="AIS",
        name="船舶自动识别系统",
        english_name="Automatic Identification System",
        system_type="automatic_identification_system",
        description="读取 AIS 动态、静态与航次数据；该连接器按只读方式设计。",
        env_key="AIS",
        supported_auth_types=("none", "api_key", "bearer", "oauth2"),
        read_capabilities=("positions", "static_vessel_data", "voyage_data", "tracks"),
        write_capabilities=(),
        integration_patterns=("NMEA 0183/AIS", "IEC 61162 Gateway", "REST/OpenAPI", "Stream/MQ"),
        field_mappings=(
            _mapping("mmsi", "mmsi", "read", "string", "海上移动业务标识", True),
            _mapping("imo_number", "imo", "read", "string", "IMO 船舶编号"),
            _mapping("latitude", "lat", "read", "decimal", "WGS-84 纬度"),
            _mapping("longitude", "lon", "read", "decimal", "WGS-84 经度"),
            _mapping("navigation_status", "navStatus", "read", "integer", "AIS 航行状态码"),
        ),
    ),
    _ConnectorDefinition(
        id="weather",
        code="METOC",
        name="港区气象与海洋环境服务",
        english_name="Marine Weather and Ocean Service",
        system_type="marine_weather_service",
        description="读取港区实况、预报、预警及风浪流等海洋环境数据。",
        env_key="WEATHER",
        supported_auth_types=("none", "api_key", "bearer", "oauth2"),
        read_capabilities=("observations", "forecast", "warnings", "wind_wave_current", "visibility"),
        write_capabilities=(),
        integration_patterns=("REST/OpenAPI", "CAP warning feed", "GRIB/NetCDF", "MQTT"),
        field_mappings=(
            _mapping("station_id", "stationId", "read", "string", "气象站/海洋站标识", True),
            _mapping("observation_time", "observationTime", "read", "datetime", "观测时间", True),
            _mapping("wind_speed_ms", "windSpeed", "read", "decimal", "风速 m/s"),
            _mapping("visibility_m", "visibility", "read", "decimal", "能见度 m"),
            _mapping("warning_code", "warningCode", "read", "string", "预警代码"),
        ),
    ),
    _ConnectorDefinition(
        id="single-window",
        code="SW",
        name="国际贸易单一窗口",
        english_name="International Trade Single Window",
        system_type="trade_single_window",
        description="衔接申报、舱单、运输工具、查验与放行状态；正式接入须遵循主管部门规范。",
        env_key="SINGLE_WINDOW",
        supported_auth_types=("api_key", "bearer", "oauth2", "mtls"),
        read_capabilities=("declaration_status", "manifest_status", "inspection_status", "release_status"),
        write_capabilities=("declaration_submit", "manifest_submit", "declaration_correction"),
        integration_patterns=("Authority API", "AS4", "XML message", "MQ"),
        field_mappings=(
            _mapping("declaration_id", "declarationNo", "bidirectional", "string", "申报单号", True),
            _mapping("transport_id", "transportId", "bidirectional", "string", "运输工具标识"),
            _mapping("manifest_id", "manifestNo", "bidirectional", "string", "舱单编号"),
            _mapping("customs_status", "clearanceStatus", "read", "string", "通关状态"),
            _mapping("release_time", "releaseTime", "read", "datetime", "放行时间"),
        ),
    ),
)


_MODE_VALUES: tuple[ConnectorMode, ...] = ("demo", "live", "offline")
_AUTH_VALUES: tuple[AuthType, ...] = ("none", "api_key", "bearer", "basic", "oauth2", "mtls")
_NOTICE = (
    "连接器目录仅描述未来接入契约；默认未配置真实地址和凭据，"
    "offline/demo 均不代表生产系统在线。"
)


class ConnectorRegistry:
    """Fail-closed connector registry with secret-safe public metadata."""

    def __init__(self, environment: Optional[Mapping[str, str]] = None) -> None:
        self._environment = dict(os.environ if environment is None else environment)
        self._definitions = {item.id: item for item in _DEFINITIONS}
        self._runtime = {
            item.id: self._load_runtime(item)
            for item in _DEFINITIONS
        }
        self._last_health: dict[str, ConnectorHealthResponse] = {}
        self._lock = RLock()

    @staticmethod
    def _prefix(definition: _ConnectorDefinition) -> str:
        return f"XIAOYI_CONNECTOR_{definition.env_key}"

    def _load_runtime(self, definition: _ConnectorDefinition) -> _RuntimeConfig:
        prefix = self._prefix(definition)
        errors: list[str] = []

        raw_mode = self._environment.get(f"{prefix}_MODE", "offline").strip().lower()
        if raw_mode not in _MODE_VALUES:
            errors.append(f"{prefix}_MODE 必须是 demo、live 或 offline")
            mode: ConnectorMode = "offline"
        else:
            mode = raw_mode  # type: ignore[assignment]

        raw_auth = self._environment.get(f"{prefix}_AUTH_TYPE", "none").strip().lower()
        if raw_auth not in _AUTH_VALUES:
            errors.append(f"{prefix}_AUTH_TYPE 不受支持")
            auth_type: AuthType = "none"
        else:
            auth_type = raw_auth  # type: ignore[assignment]
        if mode == "live" and auth_type not in definition.supported_auth_types:
            errors.append(f"{definition.code} 不支持 auth_type={auth_type}")

        raw_url = self._environment.get(f"{prefix}_BASE_URL", "").strip()
        base_url = self._validate_base_url(raw_url, prefix, errors)
        credential = self._environment.get(f"{prefix}_CREDENTIAL") or None
        health_path = self._environment.get(f"{prefix}_HEALTH_PATH", "/health").strip() or "/health"
        if not health_path.startswith("/"):
            errors.append(f"{prefix}_HEALTH_PATH 必须以 / 开头")
            health_path = "/health"

        raw_timeout = self._environment.get(f"{prefix}_TIMEOUT_SECONDS", "3").strip()
        try:
            timeout_seconds = float(raw_timeout)
            if not 0.2 <= timeout_seconds <= 15:
                raise ValueError
        except ValueError:
            errors.append(f"{prefix}_TIMEOUT_SECONDS 必须在 0.2 到 15 秒之间")
            timeout_seconds = 3.0

        write_enabled = self._environment.get(f"{prefix}_ALLOW_WRITE", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if write_enabled and not definition.write_capabilities:
            errors.append(f"{definition.code} 是只读连接器，不能启用写操作")
            write_enabled = False
        if mode != "live" and write_enabled:
            errors.append("只有 live 模式可以启用写操作")
            write_enabled = False
        if mode == "live" and not base_url:
            errors.append("live 模式必须配置 BASE_URL")
        if mode == "live" and auth_type != "none" and not credential:
            errors.append("live 模式所选认证方式需要配置 CREDENTIAL")

        return _RuntimeConfig(
            mode=mode,
            base_url=base_url,
            auth_type=auth_type,
            credential=credential,
            write_enabled=write_enabled,
            health_path=health_path,
            timeout_seconds=timeout_seconds,
            errors=tuple(errors),
        )

    @staticmethod
    def _validate_base_url(raw_url: str, prefix: str, errors: list[str]) -> Optional[str]:
        if not raw_url:
            return None
        parsed = urlsplit(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"{prefix}_BASE_URL 必须是有效的 http/https 地址")
            return None
        if parsed.username or parsed.password:
            errors.append(f"{prefix}_BASE_URL 禁止内嵌用户名或密码")
            return None
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))

    def _get(self, connector_id: str) -> tuple[_ConnectorDefinition, _RuntimeConfig]:
        definition = self._definitions.get(connector_id)
        if definition is None:
            raise KeyError(connector_id)
        return definition, self._runtime[connector_id]

    def _configured(self, runtime: _RuntimeConfig) -> bool:
        if runtime.mode == "offline" or runtime.errors:
            return False
        if runtime.mode == "demo":
            return True
        return bool(runtime.base_url and (runtime.auth_type == "none" or runtime.credential))

    def _status(self, connector_id: str, runtime: _RuntimeConfig) -> ConnectorHealthStatus:
        if runtime.errors:
            return "misconfigured"
        if runtime.mode == "offline":
            return "offline"
        if runtime.mode == "demo":
            return "demo"
        cached = self._last_health.get(connector_id)
        return cached.status if cached else "unchecked"

    def get_info(self, connector_id: str) -> ConnectorInfo:
        definition, runtime = self._get(connector_id)
        prefix = self._prefix(definition)
        return ConnectorInfo(
            id=definition.id,
            code=definition.code,
            name=definition.name,
            english_name=definition.english_name,
            system_type=definition.system_type,
            description=definition.description,
            mode=runtime.mode,
            health_status=self._status(connector_id, runtime),
            configured=self._configured(runtime),
            base_url=runtime.base_url,
            auth_type=runtime.auth_type,
            supported_auth_types=list(definition.supported_auth_types),
            credential_configured=bool(runtime.credential),
            capabilities=ConnectorCapabilities(
                read=list(definition.read_capabilities),
                write=list(definition.write_capabilities),
                read_only=not definition.write_capabilities,
            ),
            write_enabled=runtime.write_enabled,
            requires_human_confirmation=bool(definition.write_capabilities),
            integration_patterns=list(definition.integration_patterns),
            health_path=runtime.health_path,
            mapping_version="draft-1",
            field_mappings=[item.model_copy(deep=True) for item in definition.field_mappings],
            configuration_errors=list(runtime.errors),
            configuration_notice=(
                "字段映射是站点接入模板，必须以真实系统数据字典、接口规范和联调结果为准；"
                "认证凭据只从服务端环境变量读取且不会通过 API 返回。"
            ),
            environment_prefix=prefix,
        )

    def list_info(self) -> list[ConnectorInfo]:
        return [self.get_info(item.id) for item in _DEFINITIONS]

    @staticmethod
    def _auth_headers(runtime: _RuntimeConfig) -> dict[str, str]:
        if not runtime.credential or runtime.auth_type in {"none", "mtls"}:
            return {}
        if runtime.auth_type == "api_key":
            return {"X-API-Key": runtime.credential}
        if runtime.auth_type in {"bearer", "oauth2"}:
            return {"Authorization": f"Bearer {runtime.credential}"}
        if runtime.auth_type == "basic":
            encoded = base64.b64encode(runtime.credential.encode("utf-8")).decode("ascii")
            return {"Authorization": f"Basic {encoded}"}
        return {}

    def check_health(self, connector_id: str) -> ConnectorHealthResponse:
        definition, runtime = self._get(connector_id)
        checked_at = _now()

        if runtime.errors:
            response = ConnectorHealthResponse(
                connector_id=connector_id,
                mode=runtime.mode,
                status="misconfigured",
                checked_at=checked_at,
                reachable=False,
                detail="；".join(runtime.errors),
                live_data_verified=False,
            )
            return self._cache_health(response)
        if runtime.mode == "offline":
            response = ConnectorHealthResponse(
                connector_id=connector_id,
                mode="offline",
                status="offline",
                checked_at=checked_at,
                reachable=False,
                detail="连接器未启用；没有探测任何外部系统。",
                live_data_verified=False,
            )
            return self._cache_health(response)
        if runtime.mode == "demo":
            response = ConnectorHealthResponse(
                connector_id=connector_id,
                mode="demo",
                status="demo",
                checked_at=checked_at,
                reachable=False,
                detail="演示模式不访问生产系统，不能视为真实在线。",
                live_data_verified=False,
            )
            return self._cache_health(response)

        assert runtime.base_url is not None
        url = urljoin(f"{runtime.base_url.rstrip('/')}/", runtime.health_path.lstrip("/"))
        headers = {"Accept": "application/json", "User-Agent": "Xiaoyi-Port-Connector/0.1"}
        headers.update(self._auth_headers(runtime))
        request = Request(url, headers=headers, method="GET")
        started = perf_counter()
        try:
            with urlopen(request, timeout=runtime.timeout_seconds) as response:  # noqa: S310
                status_code = int(response.status)
            latency_ms = round((perf_counter() - started) * 1000)
            if 200 <= status_code < 400:
                result = ConnectorHealthResponse(
                    connector_id=connector_id,
                    mode="live",
                    status="online",
                    checked_at=checked_at,
                    reachable=True,
                    http_status=status_code,
                    latency_ms=latency_ms,
                    detail=f"真实健康检查成功（HTTP {status_code}）。",
                    live_data_verified=True,
                )
            else:
                result = ConnectorHealthResponse(
                    connector_id=connector_id,
                    mode="live",
                    status="degraded",
                    checked_at=checked_at,
                    reachable=True,
                    http_status=status_code,
                    latency_ms=latency_ms,
                    detail=f"目标可达但健康检查异常（HTTP {status_code}）。",
                    live_data_verified=False,
                )
        except HTTPError as exc:
            result = ConnectorHealthResponse(
                connector_id=connector_id,
                mode="live",
                status="degraded",
                checked_at=checked_at,
                reachable=True,
                http_status=exc.code,
                latency_ms=round((perf_counter() - started) * 1000),
                detail=f"目标返回 HTTP {exc.code}，未验证为在线。",
                live_data_verified=False,
            )
        except (URLError, TimeoutError, OSError) as exc:
            result = ConnectorHealthResponse(
                connector_id=connector_id,
                mode="live",
                status="offline",
                checked_at=checked_at,
                reachable=False,
                latency_ms=round((perf_counter() - started) * 1000),
                detail=f"健康检查失败：{type(exc).__name__}。",
                live_data_verified=False,
            )
        return self._cache_health(result)

    def _cache_health(self, response: ConnectorHealthResponse) -> ConnectorHealthResponse:
        with self._lock:
            self._last_health[response.connector_id] = response
        return response.model_copy(deep=True)

    def authorize_write(self, connector_id: str, payload: WritePreflightRequest) -> WritePreflightResponse:
        definition, runtime = self._get(connector_id)
        if payload.operation not in definition.write_capabilities:
            raise ValueError("该连接器不支持此写操作")
        confirmation = payload.confirmation
        if confirmation is None or not confirmation.confirmed:
            raise PermissionError("写操作必须由人工明确确认，并提供操作人、原因和审批引用")
        if runtime.mode != "live":
            raise RuntimeError("仅 live 模式允许进入写操作预检")
        if runtime.errors:
            raise RuntimeError("连接器配置不完整，禁止写操作")
        if not runtime.write_enabled:
            raise PermissionError("服务端未显式启用该连接器写权限")
        with self._lock:
            last_health = self._last_health.get(connector_id)
        if last_health is None or last_health.status != "online" or not last_health.live_data_verified:
            raise RuntimeError("写操作前必须通过真实在线健康检查")
        return WritePreflightResponse(
            connector_id=connector_id,
            operation=payload.operation,
            authorization_id=f"authz-{uuid4().hex[:16]}",
            authorized_at=_now(),
            expires_in_seconds=60,
            message=(
                "单人写操作预检已记录，但不构成生产授权，本端点不会下发生产指令。"
                "后续站点适配器必须验证相互独立的短时双人审批、范围和撤销状态。"
            ),
        )


registry = ConnectorRegistry()


def _not_found(connector_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"未知连接器：{connector_id}")


@router.get("", response_model=ConnectorCatalogResponse)
def list_connectors() -> ConnectorCatalogResponse:
    items = registry.list_info()
    return ConnectorCatalogResponse(
        generated_at=_now(),
        total=len(items),
        online=sum(item.health_status == "online" for item in items),
        demo=sum(item.mode == "demo" for item in items),
        offline=sum(item.mode == "offline" for item in items),
        notice=_NOTICE,
        items=items,
    )


@router.get("/{connector_id}", response_model=ConnectorInfo)
def get_connector(connector_id: str) -> ConnectorInfo:
    try:
        return registry.get_info(connector_id)
    except KeyError as exc:
        raise _not_found(connector_id) from exc


@router.get("/{connector_id}/field-mappings", response_model=list[FieldMapping])
def get_field_mappings(connector_id: str) -> list[FieldMapping]:
    try:
        return registry.get_info(connector_id).field_mappings
    except KeyError as exc:
        raise _not_found(connector_id) from exc


@router.get("/{connector_id}/health", response_model=ConnectorHealthResponse)
@router.post("/{connector_id}/health-check", response_model=ConnectorHealthResponse)
def check_connector_health(connector_id: str) -> ConnectorHealthResponse:
    try:
        return registry.check_health(connector_id)
    except KeyError as exc:
        raise _not_found(connector_id) from exc


@router.post("/{connector_id}/write-preflight", response_model=WritePreflightResponse)
def write_preflight(connector_id: str, payload: WritePreflightRequest, request: FastAPIRequest) -> WritePreflightResponse:
    identity = request_identity(request)
    if identity.authenticated and payload.confirmation:
        payload = payload.model_copy(
            update={
                "confirmation": payload.confirmation.model_copy(update={"operator_id": identity.actor_id})
            }
        )
    try:
        return registry.authorize_write(connector_id, payload)
    except KeyError as exc:
        raise _not_found(connector_id) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
