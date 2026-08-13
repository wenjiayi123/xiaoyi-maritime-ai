from __future__ import annotations

import math
import os
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Protocol
from urllib import request

from app.realtime_port_simulator import SIMULATION_NOTICE, realtime_port_simulator
from app.site_admission import evaluate_live_metadata


DataMode = Literal["operations_sandbox", "live"]


SANDBOX_NOTICE = SIMULATION_NOTICE


class PortOperationsDataSource(Protocol):
    """Production swap boundary for TOS/PCS/EMS/EAM/VTS adapters."""

    mode: DataMode

    def metadata(self, observed_at: datetime) -> dict[str, Any]: ...

    def overview(self, observed_at: datetime) -> dict[str, Any]: ...

    def energy(self, period: str, observed_at: datetime) -> dict[str, Any]: ...

    def alerts(self, observed_at: datetime) -> list[dict[str, Any]]: ...

    def runtime_snapshot(self, observed_at: datetime) -> dict[str, Any]: ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


@dataclass(frozen=True)
class SandboxPortDataSource:
    """Deterministic, time-varying port sandbox with production-shaped payloads.

    Values change on a five-minute event-time bucket.  The generator is repeatable
    for the same bucket, which makes tests and interview demonstrations stable while
    still behaving like a continuously updating operational feed.
    """

    mode: DataMode = "operations_sandbox"
    source_system: str = "XIAOYI-PORT-SANDBOX"
    port_code: str = "XPS01"
    port_name: str = "公开数据校准样板港区"

    @staticmethod
    def _is_runtime_request(observed_at: datetime) -> bool:
        return abs((utc_now() - observed_at).total_seconds()) <= 30

    def _runtime(self, observed_at: datetime) -> dict[str, Any] | None:
        if not self._is_runtime_request(observed_at):
            return None
        return realtime_port_simulator.snapshot()

    def _bucket(self, observed_at: datetime) -> int:
        return int(observed_at.timestamp()) // 300

    def _wave(self, observed_at: datetime, offset: float = 0.0) -> float:
        bucket = self._bucket(observed_at)
        return math.sin(bucket * 0.73 + offset) * 0.55 + math.sin(bucket * 0.19 + offset) * 0.45

    def metadata(self, observed_at: datetime) -> dict[str, Any]:
        runtime = self._runtime(observed_at)
        if runtime is not None:
            return runtime["metadata"]
        event_at = observed_at.replace(second=(observed_at.second // 5) * 5)
        return {
            "data_mode": self.mode,
            "data_notice": SANDBOX_NOTICE,
            "source_system": self.source_system,
            "source_type": "synthetic_event_stream",
            "source_adapter": "SandboxPortDataSource",
            "schema_version": "port-ops.v1",
            "port_code": self.port_code,
            "observed_at": event_at,
            "generated_at": utc_now(),
            "quality_code": "SYNTHETIC_VALIDATED",
            "quality_score": 0.99,
            "latency_ms": 35 + self._bucket(observed_at) % 41,
            # A schema-compatible sandbox is not a production-ready data source.
            # Site admission remains fail-closed until a verified live adapter is
            # calibrated, shadowed and approved.
            "production_ready": False,
            "live_data_verified": False,
            "write_enabled": False,
        }

    def overview(self, observed_at: datetime) -> dict[str, Any]:
        runtime = self._runtime(observed_at)
        if runtime is not None:
            return runtime["overview"]
        local_hour = (observed_at.hour + 8) % 24
        minute = (observed_at.minute // 5) * 5
        day_progress = (local_hour * 60 + minute) / 1440
        wave = self._wave(observed_at)
        vessels = max(11, round(17 + wave * 2.2))
        throughput = round(1800 + day_progress * 46800 + wave * 360)
        qc_util = round(76.8 + wave * 4.6, 1)
        agv_online = round(95.1 + self._wave(observed_at, 1.7) * 1.8, 1)
        yard_occupancy = round(67.2 + self._wave(observed_at, 2.4) * 3.2, 1)
        gate_queue = max(4, round(16 + self._wave(observed_at, 3.1) * 8))
        return {
            "port_name": self.port_name,
            "operational_date": date.today(),
            "metrics": [
                self._metric("vessels-in-port", "当前在港船舶", vessels, "艘", 1.8 + wave, "normal"),
                self._metric("teu-throughput", "今日累计吞吐量", throughput, "TEU", 4.1 + wave * 1.2, "normal"),
                self._metric("berth-utilization", "岸桥作业利用率", qc_util, "%", 2.7 + wave, "normal"),
                self._metric("agv-online-rate", "AGV 在线率", agv_online, "%", 0.9 + wave * 0.4, "normal"),
            ],
            "secondary_metrics": {
                "yard_occupancy_percent": yard_occupancy,
                "gate_queue_vehicles": gate_queue,
                "working_berths": 5,
                "active_quay_cranes": max(12, round(15 + wave)),
            },
        }

    @staticmethod
    def _metric(
        metric_id: str,
        label: str,
        value: float,
        unit: str,
        trend_percent: float,
        status: str,
    ) -> dict[str, Any]:
        if unit == "%":
            display = f"{value:.1f}%"
        elif unit == "TEU":
            display = f"{int(value):,} TEU"
        else:
            display = f"{int(value)} {unit}"
        return {
            "id": metric_id,
            "label": label,
            "value": value,
            "unit": unit,
            "display_value": display,
            "trend_percent": round(trend_percent, 1),
            "trend": "up" if trend_percent > 0.15 else "down" if trend_percent < -0.15 else "flat",
            "status": status,
        }

    def energy(self, period: str, observed_at: datetime) -> dict[str, Any]:
        if self._is_runtime_request(observed_at):
            return realtime_port_simulator.period_energy(period)
        wave = self._wave(observed_at, 0.8)
        if period == "today":
            # Twelve non-overlapping two-hour intervals.  "24:00" is not emitted
            # because it belongs to the following operating day.
            labels = [f"{hour:02d}:00" for hour in range(0, 24, 2)]
            base_values = [74, 68, 72, 81, 99, 118, 130, 126, 113, 105, 102, 100]
            raw_values = [
                value
                * (1 + wave * 0.018 + math.sin(i + self._bucket(observed_at)) * 0.012)
                for i, value in enumerate(base_values)
            ]
            multiplier = 1
            interval_minutes = 120
        else:
            days = 7 if period == "7d" else 30
            labels = [(date.today() - timedelta(days=days - index - 1)).isoformat() for index in range(days)]
            raw_values = [1120 + ((index * 137) % 310) - (index % 3) * 75 + wave * 24 for index in range(days)]
            multiplier = days
            interval_minutes = 1440
        total = round((1188.4 + wave * 28.0) * multiplier * (0.96 if multiplier > 1 else 1), 1)
        scale = total / max(sum(raw_values), 1e-9)
        values = [round(value * scale, 1) for value in raw_values]
        # Keep the public API invariant exact at its declared 0.1 MWh precision.
        values[-1] = round(values[-1] + total - sum(values), 1)
        carbon = round(total * 0.284, 1)
        return {
            "summary": {
                "total_energy_mwh": total,
                "carbon_emissions_tco2e": carbon,
                "carbon_intensity_kgco2e_per_teu": round(14.8 + wave * 0.35, 1),
                "shore_power_utilization_percent": round(72.6 + wave * 2.4, 1),
                "energy_change_percent": round(-5.8 + wave * 0.8, 1),
                "carbon_change_percent": round(-5.1 + wave * 0.7, 1),
                "intensity_change_percent": round(-4.3 + wave * 0.6, 1),
                "shore_power_change_percent": round(8.6 + wave * 1.2, 1),
            },
            "series": [
                {
                    "timestamp": label,
                    "energy_mwh": float(value),
                    "carbon_emissions_tco2e": round(value * 0.284, 1),
                    "baseline_mwh": round(value * 1.061, 1),
                }
                for label, value in zip(labels, values)
            ],
            "series_semantics": "non_overlapping_interval_energy",
            "interval_minutes": interval_minutes,
            "insights": [
                "岸桥与冷藏箱区构成当前主要用能负荷，能耗曲线与作业量变化一致。",
                "12:00—16:00 为预计高负荷窗口，建议结合船舶作业计划复核峰值。",
                "岸电接入率保持上升；涉及现场处置时仍须由值班人员核对 EMS 与计量点实绩。",
            ],
        }

    def alerts(self, observed_at: datetime) -> list[dict[str, Any]]:
        runtime = self._runtime(observed_at)
        if runtime is not None:
            return list(runtime["alerts"])
        wave = self._wave(observed_at, 1.2)
        battery = round(22 + wave * 4)
        return [
            {
                "id": f"OPS-QC03-{self._bucket(observed_at)}",
                "level": "critical",
                "category": "equipment_energy",
                "title": "岸桥单位作业能耗偏高",
                "message": f"QC-03 最近 30 分钟单位作业能耗高于同工况基线 {round(13.8 + abs(wave) * 3.1, 1)}%。",
                "source": "EMS/EAM 沙箱事件流",
                "occurred_at": observed_at - timedelta(minutes=8),
                "status": "active",
                "recommended_actions": ["核对 QC-03 当前作业量和待机时长", "检查起升与小车机构状态", "由设备主管确认是否转检修工单"],
            },
            {
                "id": f"OPS-BERTH05-{self._bucket(observed_at)}",
                "level": "warning",
                "category": "berth",
                "title": "泊位衔接窗口收窄",
                "message": "B05 前船预计完工时间与后船引航窗口间隔缩短至 42 分钟。",
                "source": "TOS/PCS 沙箱事件流",
                "occurred_at": observed_at - timedelta(minutes=16),
                "status": "active",
                "recommended_actions": ["复核前船剩余箱量", "确认拖轮与引航资源", "准备备选靠泊时窗"],
            },
            {
                "id": f"OPS-AGV023-{self._bucket(observed_at)}",
                "level": "warning",
                "category": "equipment",
                "title": "AGV 续航不足",
                "message": f"AGV-023 电量 {battery}%，当前任务完成后预计剩余 12%—15%。",
                "source": "EAM/车队沙箱事件流",
                "occurred_at": observed_at - timedelta(minutes=31),
                "status": "active",
                "recommended_actions": ["锁定当前任务后不再派新任务", "安排 AGV-041 接替", "引导 AGV-023 前往 C2 充电位"],
            },
            {
                "id": f"OPS-GATE-{self._bucket(observed_at)}",
                "level": "info",
                "category": "gate",
                "title": "南闸口到车波峰提醒",
                "message": "预约到车量将在未来 30 分钟进入波峰，建议提前开放 1 条备用车道。",
                "source": "闸口预约沙箱事件流",
                "occurred_at": observed_at - timedelta(minutes=43),
                "status": "active",
                "recommended_actions": ["复核预约到车曲线", "确认备用车道人员", "监视场外排队长度"],
            },
        ]

    def runtime_snapshot(self, observed_at: datetime) -> dict[str, Any]:
        runtime = self._runtime(observed_at)
        if runtime is not None:
            fleet = runtime["fleet_summary"]
            return {
                **runtime,
                "berth_calls": runtime["port_calls"],
                "equipment_summary": fleet,
                "equipment": {
                    "quay_cranes": {
                        "total": fleet["quay_cranes"]["total"],
                        "working": fleet["quay_cranes"]["working"],
                        "standby": fleet["quay_cranes"]["total"] - fleet["quay_cranes"]["working"] - fleet["quay_cranes"]["fault"],
                        "maintenance": fleet["quay_cranes"]["fault"],
                    },
                    "agv": {
                        "total": fleet["agv"]["total"],
                        "online": fleet["agv"]["total"] - fleet["agv"]["low_soc"],
                        "working": fleet["agv"]["working"],
                        "charging": fleet["agv"]["charging"],
                    },
                    "yard_cranes": {
                        "total": fleet["yard_cranes"]["total"],
                        "working": fleet["yard_cranes"]["working"],
                        "maintenance": 0,
                    },
                },
                "equipment_assets": runtime["equipment"],
                "yard": {
                    "occupancy_percent": round(sum(item["occupancy_percent"] for item in runtime["yard_blocks"]) / len(runtime["yard_blocks"]), 1),
                    "reefer_slots_used": sum(item["reefer_slots_used"] for item in runtime["yard_blocks"]),
                    "dangerous_goods_zone_percent": round(100 * sum(item["dangerous_goods_teu"] for item in runtime["yard_blocks"]) / max(sum(item["occupied_teu"] for item in runtime["yard_blocks"]), 1), 1),
                },
                "gate": {
                    "queue_vehicles": sum(item["queue_vehicles"] for item in runtime["gates"]),
                    "open_lanes": sum(item["lanes_open"] for item in runtime["gates"]),
                    "average_turn_time_minutes": round(sum(item["turn_time_minutes"] for item in runtime["gates"]) / len(runtime["gates"]), 1),
                },
            }
        wave = self._wave(observed_at)
        return {
            "metadata": self.metadata(observed_at),
            "port": {"code": self.port_code, "name": self.port_name, "timezone": "Asia/Shanghai"},
            "berth_calls": [
                {"berth_id": "B03", "vessel_id": "IMO9387421", "vessel_name": "HAI XING 18", "status": "working", "eta": None, "etd": (observed_at + timedelta(hours=3, minutes=20)).isoformat(), "remaining_moves": max(180, round(760 + wave * 95))},
                {"berth_id": "B05", "vessel_id": "IMO9712456", "vessel_name": "OCEAN BRIDGE", "status": "working", "eta": None, "etd": (observed_at + timedelta(hours=1, minutes=5)).isoformat(), "remaining_moves": max(90, round(320 + wave * 60))},
                {"berth_id": "B07", "vessel_id": "IMO9458127", "vessel_name": "PACIFIC LOTUS", "status": "alongside", "eta": None, "etd": (observed_at + timedelta(hours=6, minutes=10)).isoformat(), "remaining_moves": max(420, round(1260 + wave * 120))},
                {"berth_id": "ANCH-02", "vessel_id": "IMO9893315", "vessel_name": "EASTERN HORIZON", "status": "awaiting_pilot", "eta": (observed_at + timedelta(minutes=48)).isoformat(), "etd": None, "remaining_moves": 1480},
            ],
            "equipment": {
                "quay_cranes": {"total": 18, "working": max(12, round(15 + wave)), "standby": 2, "maintenance": 1},
                "agv": {"total": 96, "online": max(88, round(92 + wave * 2)), "working": max(66, round(72 + wave * 3)), "charging": 14},
                "yard_cranes": {"total": 54, "working": max(39, round(43 + wave * 2)), "maintenance": 2},
            },
            "yard": {"occupancy_percent": round(67.2 + wave * 3.2, 1), "reefer_slots_used": max(640, round(712 + wave * 34)), "dangerous_goods_zone_percent": round(51.4 + wave * 2.1, 1)},
            "gate": {"queue_vehicles": max(4, round(16 + wave * 8)), "open_lanes": 8, "average_turn_time_minutes": round(21.8 + abs(wave) * 3.2, 1)},
        }


class HttpPortDataSource:
    """Read-only adapter for a production integration gateway.

    The gateway is expected to normalize site-specific TOS/PCS/EMS/EAM/VTS data to
    the same port-ops.v1 resources used by the sandbox.  No write endpoint is called.
    """

    mode: DataMode = "live"

    def __init__(self) -> None:
        self.base_url = os.getenv("XIAOYI_PORT_BASE_URL", "").strip().rstrip("/")
        self.token = os.getenv("XIAOYI_PORT_API_TOKEN", "").strip()
        self.timeout_seconds = float(os.getenv("XIAOYI_PORT_TIMEOUT_SECONDS", "5"))
        if not self.base_url:
            raise RuntimeError(
                "XIAOYI_PORT_DATA_MODE=live 已启用，但未配置 XIAOYI_PORT_BASE_URL；系统已安全拒绝启动。"
            )

    def _get(self, path: str) -> dict[str, Any]:
        headers = {"Accept": "application/json", "User-Agent": "Xiaoyi-Port-Adapter/1.0"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = request.Request(f"{self.base_url}{path}", headers=headers, method="GET")
        with request.urlopen(req, timeout=self.timeout_seconds) as response:  # nosec B310 - deployment-configured gateway
            if response.status != 200:
                raise RuntimeError(f"生产数据网关返回 HTTP {response.status}")
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("生产数据网关返回的不是 JSON 对象")
        return payload

    def metadata(self, observed_at: datetime) -> dict[str, Any]:
        payload = self._get("/runtime/status")
        admission = evaluate_live_metadata(payload)
        if not admission["read_only_admission_passed"]:
            reasons = ", ".join(admission["blockers"][:8])
            raise RuntimeError(f"生产数据网关未通过只读现场准入，已失败关闭：{reasons}")
        payload["write_enabled"] = False
        payload["site_admission"] = admission
        return payload

    def overview(self, observed_at: datetime) -> dict[str, Any]:
        return self._get("/operations/overview")

    def energy(self, period: str, observed_at: datetime) -> dict[str, Any]:
        return self._get(f"/energy?range={period}")

    def alerts(self, observed_at: datetime) -> list[dict[str, Any]]:
        payload = self._get("/alerts?status=active&limit=100")
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise RuntimeError("生产数据网关 alerts.items 格式无效")
        return items

    def runtime_snapshot(self, observed_at: datetime) -> dict[str, Any]:
        return self._get("/runtime/snapshot")


def create_port_data_source() -> PortOperationsDataSource:
    mode = os.getenv("XIAOYI_PORT_DATA_MODE", "operations_sandbox").strip().lower()
    if mode == "operations_sandbox":
        return SandboxPortDataSource()
    if mode == "live":
        return HttpPortDataSource()
    raise RuntimeError("XIAOYI_PORT_DATA_MODE 仅允许 operations_sandbox 或 live")


port_data_source = create_port_data_source()
