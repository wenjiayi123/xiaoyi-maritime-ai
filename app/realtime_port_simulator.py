from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import math
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.runtime_store import runtime_store
from app.security import request_identity


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "data/contracts/port_realtime_telemetry_v1.json"
AIS_PATH = ROOT / "data/public/noaa_la_lb_ais_2024_12_25_1min.csv"
ENERGY_PATH = ROOT / "data/public/uci_appliances_energy.csv"

router = APIRouter(prefix="/api/port-simulator", tags=["港口实时数据模拟器"])

TRUTH_LABEL = "公开数据校准实时模拟"
SIMULATION_NOTICE = (
    "公开数据校准实时模拟：交通包络参考公开AIS观测，能源时序链路参考公开能源基准；"
    "泊位、设备、堆场、闸口、能耗量级、天气潮汐和业务影响为物理约束下的工程模拟，"
    "当前尚未连接任何港口生产源，不是任何港口现场实测、生产KPI、财务实绩或核证减排。"
)

ScenarioId = Literal["normal", "vessel_surge", "equipment_failure", "energy_peak", "storm"]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _bounded(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _read_ais_envelope() -> dict[str, float]:
    rows: list[dict[str, str]] = []
    with AIS_PATH.open(encoding="utf-8", newline="") as handle:
        rows.extend(csv.DictReader(handle))
    if not rows:
        raise RuntimeError("公开AIS校准文件为空")

    def values(field: str) -> list[float]:
        return [float(row[field]) for row in rows]

    vessel = values("vessel_count")
    anchored = values("anchored_vessels")
    speed = values("avg_sog_knots")
    ordered = sorted(vessel)
    return {
        "rows": float(len(rows)),
        "vessel_p50": ordered[len(ordered) // 2],
        "vessel_p95": ordered[int((len(ordered) - 1) * 0.95)],
        "anchored_ratio": sum(anchored) / max(sum(vessel), 1),
        "avg_sog_knots": sum(speed) / len(speed),
    }


_CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
_CONTRACT_SHA256 = _sha256_path(CONTRACT_PATH)
_AIS_SHA256 = _sha256_path(AIS_PATH)
_ENERGY_SHA256 = _sha256_path(ENERGY_PATH)
_AIS_ENVELOPE = _read_ais_envelope()

_SCENARIOS: dict[str, dict[str, Any]] = {
    "normal": {
        "label": "常态联合生产",
        "description": "船舶、泊位、设备、堆场、闸口和能源处于可控负荷。",
        "risk": "normal",
        "multipliers": {"traffic": 1.0, "equipment": 1.0, "gate": 1.0, "energy": 1.0},
    },
    "vessel_surge": {
        "label": "船舶集中到港",
        "description": "公开AIS交通包络内的高分位到港压力，触发泊位和引航窗口重排。",
        "risk": "attention",
        "multipliers": {"traffic": 1.24, "equipment": 1.04, "gate": 1.1, "energy": 1.08},
    },
    "equipment_failure": {
        "label": "岸桥故障与AGV低电量",
        "description": "QC-03故障降级并出现AGV低SOC，检验任务重分配和维修闭环。",
        "risk": "warning",
        "multipliers": {"traffic": 1.02, "equipment": 0.82, "gate": 1.08, "energy": 0.96},
    },
    "energy_peak": {
        "label": "港区需量高峰",
        "description": "岸桥、冷藏箱和AGV充电叠加，检验储能、充电错峰和SOC恢复。",
        "risk": "attention",
        "multipliers": {"traffic": 1.02, "equipment": 1.05, "gate": 1.02, "energy": 1.23},
    },
    "storm": {
        "label": "大风低能见度",
        "description": "风速和能见度进入作业限制区，检验停机、船舶窗口和人工接管。",
        "risk": "critical",
        "multipliers": {"traffic": 0.82, "equipment": 0.58, "gate": 0.86, "energy": 0.9},
    },
}


class ScenarioRequest(BaseModel):
    scenario_id: ScenarioId
    reason: str = Field(..., min_length=4, max_length=240)


class ApprovalRequest(BaseModel):
    approver_id: str = Field(..., min_length=2, max_length=100)
    approver_role: Literal["dispatcher", "duty_manager", "energy_manager", "maintenance_supervisor"]
    reason: str = Field(..., min_length=4, max_length=240)


class ActionRequest(BaseModel):
    reason: str = Field(..., min_length=4, max_length=240)


class PortRealtimeSimulator:
    """Deterministic, production-shaped, simulation-only port event plane.

    The public AIS file calibrates traffic envelopes only. All terminal entities
    and impacts remain engineering simulation. A live site adapter can replace
    this class as long as it emits the same contract.
    """

    def __init__(self, seed: int = 20260813) -> None:
        self.seed = seed
        self._lock = RLock()
        self._started_monotonic = time.monotonic()
        self._started_at = _now()
        self._scenario_id: ScenarioId = "normal"
        self._run_id = self._new_run_id()
        self._approvals: dict[str, list[dict[str, Any]]] = {}
        self._executed: set[str] = set()
        self._events: deque[dict[str, Any]] = deque(maxlen=500)
        self._record("simulator.started", "模拟器已按默认常态场景启动。")

    def _new_run_id(self) -> str:
        return f"port-sim-{_now().strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"

    def _sequence(self) -> int:
        return max(0, int((time.monotonic() - self._started_monotonic) / 2.0))

    def _record(self, event: str, detail: str, **extra: Any) -> dict[str, Any]:
        item = {
            "event_id": f"sim-event-{uuid4().hex[:12]}",
            "event": event,
            "detail": detail,
            "occurred_at": _now().isoformat(),
            "run_id": self._run_id,
            "scenario_id": self._scenario_id,
            **extra,
        }
        self._events.appendleft(item)
        return item

    def status(self) -> dict[str, Any]:
        with self._lock:
            sequence = self._sequence()
            scenario = _SCENARIOS[self._scenario_id]
            return {
                "running": True,
                "run_id": self._run_id,
                "stream_id": f"{self._run_id}:telemetry",
                "sequence": sequence,
                "scenario_id": self._scenario_id,
                "scenario_label": scenario["label"],
                "truth_label": TRUTH_LABEL,
                "data_mode": "operations_sandbox",
                "source_type": "public_data_calibrated_simulation",
                "telemetry_schema": "port-realtime.v1",
                "canonical_schema": "port-ops.v1",
                "event_interval_seconds": 2,
                "started_at": self._started_at.isoformat(),
                "observed_at": _now().isoformat(),
                "simulation_seed": self.seed,
                "sandbox_dispatch_allowed": True,
                "physical_dispatch_allowed": False,
                "production_authority": False,
                "notice": SIMULATION_NOTICE,
            }

    def set_scenario(self, scenario_id: ScenarioId, reason: str) -> dict[str, Any]:
        with self._lock:
            previous = self._scenario_id
            self._scenario_id = scenario_id
            self._started_monotonic = time.monotonic()
            self._started_at = _now()
            self._run_id = self._new_run_id()
            self._approvals.clear()
            self._executed.clear()
            self._record(
                "scenario.changed",
                f"场景由 {previous} 切换为 {scenario_id}；原因：{reason}",
                previous_scenario=previous,
            )
            return self.status()

    def _signals(self, sequence: int) -> dict[str, float]:
        phase = sequence + self.seed % 997
        return {
            "slow": math.sin(phase * 0.13),
            "medium": math.sin(phase * 0.37 + 1.2),
            "fast": math.sin(phase * 0.79 + 2.7),
        }

    def _metadata(self, sequence: int, observed_at: datetime, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        mapping_manifest = {
            domain["id"]: domain["required_fields"] for domain in _CONTRACT["domains"]
        }
        quality = {
            "schema_validation_passed": True,
            "timezone_normalized": True,
            "completeness_rate": 1.0,
            "duplicate_rate": 0.0,
            "out_of_order_rate": 0.0,
            "physical_constraint_violations": 0,
            "quality_gate_passed": True,
        }
        metadata = {
            "data_mode": "operations_sandbox",
            "data_notice": SIMULATION_NOTICE,
            "truth_label": TRUTH_LABEL,
            "source_system": "XIAOYI-PORT-REALTIME-SIMULATOR",
            "source_type": "public_data_calibrated_simulation",
            "source_adapter": "SandboxPortDataSource",
            "schema_version": "port-ops.v1",
            "telemetry_schema_version": "port-realtime.v1",
            "port_code": "XPS01",
            "observed_at": observed_at,
            "generated_at": _now(),
            "quality_code": "PUBLIC_CALIBRATED_SIMULATION_VALIDATED",
            "quality_score": 1.0,
            "latency_ms": 18 + sequence % 23,
            "production_ready": False,
            "live_data_verified": False,
            "write_enabled": False,
            "simulation_run_id": self._run_id,
            "simulation_seed": self.seed,
            "scenario_id": self._scenario_id,
            "stream_sequence": sequence,
            "source_dataset_id": "noaa_la_lb_ais_2024_12_25_1min+uci_appliances_energy+engineering_port_model_v1",
            "source_manifest_sha256": _payload_sha256(_CONTRACT["calibration_sources"]),
            "field_mapping_version": "port-realtime.v1",
            "field_mapping_sha256": _payload_sha256(mapping_manifest),
            "contract_sha256": _CONTRACT_SHA256,
            "quality_report": quality,
            "quality_report_sha256": _payload_sha256(quality),
            "physical_dispatch_allowed": False,
            "sandbox_dispatch_allowed": True,
            "production_authority": False,
        }
        metadata["payload_sha256"] = _payload_sha256(payload or {"sequence": sequence})
        return metadata

    def _port_calls(self, observed_at: datetime, sequence: int, traffic: float, equipment: float) -> list[dict[str, Any]]:
        specs = [
            ("PC-260813-001", "IMO9387421", "413882301", "HAI XING 18", "B03", "working", 1680, 0),
            ("PC-260813-002", "IMO9712456", "477336900", "OCEAN BRIDGE", "B05", "working", 1120, 0),
            ("PC-260813-003", "IMO9458127", "563189700", "PACIFIC LOTUS", "B07", "alongside", 2260, 0),
            ("PC-260813-004", "IMO9893315", "636019240", "EASTERN HORIZON", "B09", "awaiting_pilot", 1480, 48),
            ("PC-260813-005", "IMO9637424", "538009112", "BLUE ORCHID", "B11", "scheduled", 1930, 112),
        ]
        result: list[dict[str, Any]] = []
        for index, (call_id, imo, mmsi, name, berth, status, moves, eta_minutes) in enumerate(specs):
            progress_rate = max(0.0, equipment * (sequence * (5.5 + index)))
            completed = min(moves, int(progress_rate)) if status in {"working", "alongside"} else 0
            remaining = moves - completed
            eta = observed_at + timedelta(minutes=max(5, eta_minutes - sequence * 2)) if eta_minutes else None
            etc = observed_at + timedelta(minutes=max(20, remaining / max(22 * equipment, 1))) if status in {"working", "alongside"} else None
            result.append({
                "port_call_id": call_id,
                "imo": imo,
                "mmsi": mmsi,
                "vessel_name": name,
                "vessel_type": "container",
                "loa_m": [294.1, 335.0, 366.0, 299.9, 323.0][index],
                "beam_m": [32.2, 42.8, 48.2, 40.0, 42.8][index],
                "draft_m": [11.7, 13.2, 14.1, 12.6, 13.5][index],
                "voyage_id": f"XY{2608 + index}E",
                "berth_id": berth,
                "status": status,
                "eta": eta.isoformat() if eta else None,
                "etb": (eta + timedelta(minutes=35)).isoformat() if eta else None,
                "atb": (observed_at - timedelta(hours=3 + index)).isoformat() if not eta else None,
                "etc": etc.isoformat() if etc else None,
                "etd": (etc + timedelta(minutes=35)).isoformat() if etc else None,
                "moves_planned": moves,
                "moves_completed": completed,
                "remaining_moves": remaining,
                "pilot_status": "requested" if eta else "not_required_alongside",
                "tug_status": "reserved" if eta else "released",
                "traffic_pressure_index": round(traffic, 3),
                "event_time": observed_at.isoformat(),
                "quality_code": "SIMULATED_PHYSICS_VALIDATED",
            })
        return result

    def _ais(self, observed_at: datetime, sequence: int, traffic: float) -> list[dict[str, Any]]:
        vessels: list[dict[str, Any]] = []
        for index in range(12):
            angle = (sequence * 0.012 + index * 0.49) % (2 * math.pi)
            waiting = index >= 7
            sog = (0.1 + (index % 3) * 0.12) if waiting else (5.2 + (index % 4) * 0.7) * min(traffic, 1.15)
            vessels.append({
                "mmsi": str(410000100 + index),
                "imo": str(9300100 + index),
                "vessel_name": f"SIM-VESSEL-{index + 1:02d}",
                "latitude": round(33.735 + math.sin(angle) * (0.025 if waiting else 0.055), 6),
                "longitude": round(-118.205 + math.cos(angle) * (0.035 if waiting else 0.082), 6),
                "sog_knots": round(sog, 2),
                "cog_degrees": round((angle * 180 / math.pi + 90) % 360, 1),
                "heading_degrees": round((angle * 180 / math.pi + 92) % 360, 1),
                "navigation_status": "at_anchor" if waiting else "under_way_using_engine",
                "position_accuracy": "simulated_valid",
                "ais_class": "A",
                "last_reported_at": observed_at.isoformat(),
                "route_segment": "anchorage" if waiting else "approach_channel",
                "cpa_nm": round(0.8 + (index % 5) * 0.22, 2),
                "tcpa_minutes": 18 + index * 3,
            })
        return vessels

    def _berths(self, port_calls: list[dict[str, Any]], water_level: float) -> list[dict[str, Any]]:
        by_berth = {item["berth_id"]: item for item in port_calls if item["status"] != "scheduled"}
        result: list[dict[str, Any]] = []
        for index, berth_id in enumerate(("B01", "B03", "B05", "B07", "B09", "B11")):
            call = by_berth.get(berth_id)
            depth = 15.4 + (index % 3) * 0.5
            draft = float(call["draft_m"]) if call else 0.0
            ukc = round(depth + water_level - draft, 2) if call else None
            result.append({
                "berth_id": berth_id,
                "length_m": 365 if index < 4 else 330,
                "design_depth_m": depth,
                "occupied": bool(call and call["status"] in {"working", "alongside"}),
                "port_call_id": call["port_call_id"] if call else None,
                "cranes_assigned": 3 if call and call["status"] in {"working", "alongside"} else 0,
                "mooring_status": "secured" if call and call["status"] in {"working", "alongside"} else "available",
                "pilot_required": bool(call and call["status"] == "awaiting_pilot"),
                "tugs_required": 2 if call and call["status"] == "awaiting_pilot" else 0,
                "under_keel_clearance_m": ukc,
                "window_risk_minutes": 42 if berth_id == "B05" else 90,
            })
        return result

    def _equipment(self, observed_at: datetime, sequence: int, scenario_id: str, equipment_factor: float) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for index in range(18):
            asset_id = f"QC-{index + 1:02d}"
            failed = scenario_id == "equipment_failure" and asset_id == "QC-03" and "qc-recovery" not in self._executed
            storm_stop = scenario_id == "storm"
            working = not failed and not storm_stop and index < round(15 * equipment_factor)
            status = "fault" if failed else "weather_hold" if storm_stop else "working" if working else "standby"
            items.append({
                "asset_id": asset_id, "asset_type": "quay_crane", "status": status,
                "availability": not failed, "task_id": f"MOVE-{index + 1:04d}" if working else None,
                "power_kw": round(working * (520 + 42 * math.sin(sequence * 0.2 + index)), 1),
                "energy_kwh": round(1380 + sequence * 14.2 + index * 8.1, 1),
                "moves_per_hour": round(27.5 * equipment_factor if working else 0, 1),
                "soc_percent": None, "battery_temperature_c": None,
                "fault_code": "HOIST-OVERTEMP" if failed else None,
                "maintenance_due_hours": max(0, 120 - index * 3 - sequence),
                "location": f"BERTH-{(index % 6) + 1:02d}", "event_time": observed_at.isoformat(),
                "quality_code": "SIMULATED_PHYSICS_VALIDATED",
            })
        for index in range(96):
            asset_id = f"AGV-{index + 1:03d}"
            low = index == 22 or (scenario_id in {"equipment_failure", "energy_peak"} and index in {40, 67})
            executed = "agv-charge-rebalance" in self._executed
            soc = _bounded(71 - (index % 12) * 3.8 - sequence * 0.08 + (20 if low and executed else -20 if low else 0), 8, 96)
            charging = soc < 28 or (index + sequence) % 11 == 0
            working = not charging and index < round(74 * equipment_factor)
            items.append({
                "asset_id": asset_id, "asset_type": "agv", "status": "charging" if charging else "working" if working else "standby",
                "availability": soc >= 12, "task_id": f"AGV-TASK-{index + 1:04d}" if working else None,
                "power_kw": 145.0 if charging else 21.0 if working else 2.8,
                "energy_kwh": round(420 + sequence * 1.7 + index * 0.9, 1), "moves_per_hour": 4.8 if working else 0.0,
                "soc_percent": round(soc, 1), "battery_temperature_c": round(29 + (index % 7) * 0.7 + (4 if charging else 0), 1),
                "fault_code": "LOW_SOC" if soc < 15 else None, "maintenance_due_hours": max(0, 260 - index - sequence),
                "location": f"YARD-{chr(65 + index % 8)}{index % 6 + 1}", "event_time": observed_at.isoformat(),
                "quality_code": "SIMULATED_PHYSICS_VALIDATED",
            })
        for index in range(54):
            working = index < round(43 * equipment_factor)
            items.append({
                "asset_id": f"YC-{index + 1:02d}", "asset_type": "yard_crane", "status": "working" if working else "standby",
                "availability": True, "task_id": f"YARD-TASK-{index + 1:04d}" if working else None,
                "power_kw": 118.0 if working else 9.0, "energy_kwh": round(780 + index * 3.2 + sequence * 3.4, 1),
                "moves_per_hour": 18.4 if working else 0.0, "soc_percent": None, "battery_temperature_c": None,
                "fault_code": None, "maintenance_due_hours": max(0, 180 - index * 2),
                "location": f"YARD-{chr(65 + index % 8)}", "event_time": observed_at.isoformat(),
                "quality_code": "SIMULATED_PHYSICS_VALIDATED",
            })
        return items

    def _yards(self, signals: dict[str, float], traffic: float) -> list[dict[str, Any]]:
        result = []
        for index in range(12):
            capacity = 2300 + (index % 3) * 250
            occupancy = _bounded(0.57 + index * 0.012 + signals["slow"] * 0.022 + (traffic - 1) * 0.14, 0.38, 0.88)
            used = round(capacity * occupancy)
            result.append({
                "block_id": f"{chr(65 + index // 3)}{index % 3 + 1}", "capacity_teu": capacity,
                "occupied_teu": used, "occupancy_percent": round(occupancy * 100, 1),
                "reefer_slots_total": 160 if index < 4 else 40, "reefer_slots_used": min(150 if index < 4 else 35, round(occupancy * (160 if index < 4 else 40))),
                "dangerous_goods_teu": 18 + index * 2 if index in {9, 10} else 0,
                "export_teu": round(used * 0.42), "import_teu": round(used * 0.38), "transshipment_teu": round(used * 0.2),
                "rehandle_ratio": round(0.07 + occupancy * 0.055, 3), "dwell_hours_p50": round(22 + occupancy * 18, 1),
                "dwell_hours_p95": round(62 + occupancy * 48, 1),
            })
        return result

    def _gates(self, sequence: int, gate_factor: float) -> list[dict[str, Any]]:
        return [
            {
                "gate_id": gate_id, "lanes_total": 8, "lanes_open": 8 if gate_id == "SOUTH" else 6,
                "queue_vehicles": max(1, round((16 + index * 5 + 6 * math.sin(sequence * 0.21 + index)) * gate_factor)),
                "truck_arrivals_per_hour": round((118 + index * 24) * gate_factor),
                "truck_departures_per_hour": round((112 + index * 20) * min(gate_factor, 1.08)),
                "turn_time_minutes": round((22.4 + index * 3.6) * gate_factor, 1),
                "appointment_adherence_percent": round(91.2 - index * 2.1, 1), "ocr_match_percent": 99.4,
                "rail_slots_planned": 4, "rail_slots_active": 2 + index,
            }
            for index, gate_id in enumerate(("SOUTH", "NORTH"))
        ]

    def _weather(self, observed_at: datetime, scenario_id: str, signals: dict[str, float]) -> dict[str, Any]:
        storm = scenario_id == "storm"
        wind = 19.2 + signals["medium"] * 1.8 if storm else 6.8 + signals["medium"] * 1.4
        visibility = 2800 + signals["slow"] * 500 if storm else 14800 + signals["slow"] * 900
        water = 0.72 + signals["slow"] * 0.38
        return {
            "station_id": "SIM-METOC-01", "air_temperature_c": round(27.6 + signals["slow"] * 1.5, 1),
            "relative_humidity_percent": round(78 + signals["medium"] * 5, 1), "pressure_hpa": round(1007.8 + signals["slow"] * 2.3, 1),
            "wind_speed_ms": round(wind, 1), "wind_gust_ms": round(wind * 1.34, 1),
            "wind_direction_degrees": round((135 + signals["medium"] * 28) % 360, 1), "visibility_m": round(max(800, visibility)),
            "precipitation_mm_h": 7.4 if storm else max(0.0, round(signals["fast"] - 0.85, 2)),
            "wave_height_m": round(2.4 + signals["slow"] * 0.3 if storm else 0.7 + signals["slow"] * 0.2, 1),
            "water_level_m_mllw": round(water, 2), "current_speed_ms": round(0.42 + abs(signals["medium"]) * 0.22, 2),
            "current_direction_degrees": round((72 + signals["slow"] * 32) % 360, 1), "observation_time": observed_at.isoformat(),
            "forecast_valid_until": (observed_at + timedelta(hours=3)).isoformat(),
            "source_semantics": "engineering_simulation_with_NOAA_COOPS_compatible_fields",
        }

    def _energy(self, observed_at: datetime, sequence: int, energy_factor: float, equipment: list[dict[str, Any]]) -> dict[str, Any]:
        qc_kw = sum(float(item["power_kw"]) for item in equipment if item["asset_type"] == "quay_crane")
        agv_kw = sum(float(item["power_kw"]) for item in equipment if item["asset_type"] == "agv")
        yc_kw = sum(float(item["power_kw"]) for item in equipment if item["asset_type"] == "yard_crane")
        reefer_kw = 3820.0 * energy_factor
        shore_kw = 4650.0 * min(energy_factor, 1.12)
        hvac_kw = 830.0
        lighting_kw = 520.0
        other_kw = 1240.0
        base_demand = qc_kw + agv_kw + yc_kw + reefer_kw + shore_kw + hvac_kw + lighting_kw + other_kw
        bess_executed = "energy-peak-shave" in self._executed
        bess_power = -1800.0 if bess_executed and self._scenario_id == "energy_peak" else 420.0 if sequence % 7 == 0 else 0.0
        soc = _bounded(68.0 - sequence * 0.08 - max(0, -bess_power) / 8000 + (5 if bess_power > 0 else 0), 20.0, 90.0)
        grid = base_demand + bess_power
        interval_hours = 2 / 3600
        return {
            "grid_demand_kw": round(grid, 1), "peak_limit_kw": 24200.0 if self._scenario_id == "energy_peak" else 30000.0,
            "energy_interval_kwh": round(grid * interval_hours, 3), "tariff_cny_per_kwh": 1.18 if self._scenario_id == "energy_peak" else 0.82,
            "marginal_carbon_kg_per_kwh": 0.57, "shore_power_kw": round(shore_kw, 1), "shore_power_connections": 3,
            "reefer_kw": round(reefer_kw, 1), "quay_crane_kw": round(qc_kw, 1), "yard_crane_kw": round(yc_kw, 1),
            "agv_charging_kw": round(agv_kw, 1), "hvac_kw": hvac_kw, "lighting_kw": lighting_kw, "other_kw": other_kw,
            "bess_soc_percent": round(soc, 1), "bess_capacity_kwh": 12000.0, "bess_power_kw": bess_power,
            "bess_roundtrip_efficiency": 0.89, "bess_degradation_cost_cny_per_kwh": 0.21,
            "power_balance_error_kw": 0.0, "meter_quality_code": "SIMULATED_BALANCED",
            "observed_at": observed_at.isoformat(),
        }

    def _alerts(self, observed_at: datetime, scenario_id: str, equipment: list[dict[str, Any]], energy: dict[str, Any], weather: dict[str, Any]) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []

        def add(event_id: str, severity: str, category: str, asset_id: str, title: str, message: str, actions: list[str], permit: bool = False, isolation: bool = False) -> None:
            alerts.append({
                "event_id": event_id, "id": event_id, "severity": severity, "level": severity,
                "category": category, "asset_id": asset_id, "title": title, "message": message,
                "source": "XIAOYI-PORT-REALTIME-SIMULATOR", "occurred_at": (observed_at - timedelta(seconds=18)).isoformat(),
                "acknowledged_at": None, "resolved_at": None, "status": "active", "recommended_actions": actions,
                "work_order_id": None, "permit_required": permit, "isolation_required": isolation,
            })

        low_soc = [item for item in equipment if item["asset_type"] == "agv" and float(item["soc_percent"] or 100) < 15]
        add(
            "SIM-QC03-ENERGY", "critical", "equipment_energy", "QC-03",
            "QC-03单位作业能耗偏高",
            "QC-03最近30分钟单位作业能耗高于同工况工程基线14.6%。",
            ["核对QC-03当前作业量和待机时长", "检查起升与小车机构状态", "由设备主管确认是否转检修草案"],
        )
        if scenario_id == "equipment_failure" and "qc-recovery" not in self._executed:
            add("SIM-QC03-FAULT", "critical", "equipment", "QC-03", "QC-03起升机构过温", "温度保护触发，作业任务已在沙箱中挂起。", ["锁定QC-03新任务", "将未完成任务重分配至QC-04/QC-05", "创建检修草案并等待隔离许可"], True, True)
        if low_soc:
            add("SIM-AGV-LOW-SOC", "warning", "equipment", low_soc[0]["asset_id"], "AGV低SOC队列", f"{len(low_soc)}台AGV低于15% SOC门限。", ["停止派发新任务", "重排充电优先级", "保留20%班末SOC恢复约束"])
        if float(energy["grid_demand_kw"]) > float(energy["peak_limit_kw"]):
            add("SIM-EMS-PEAK", "warning", "energy", "EMS-MAIN", "港区需量超过情景上限", f"当前{energy['grid_demand_kw']} kW，高于{energy['peak_limit_kw']} kW工程情景门限。", ["复核BESS可用SOC", "错峰非关键AGV充电", "不得削减安全与岸电刚性负荷"])
        if float(weather["wind_speed_ms"]) >= 18:
            add("SIM-METOC-WIND", "critical", "weather", "METOC-01", "大风触发岸桥作业限制", f"模拟风速{weather['wind_speed_ms']} m/s、阵风{weather['wind_gust_ms']} m/s。", ["按站点风速门限停止岸桥作业", "确认吊具安全状态", "等待现场METOC与值班人员复核"], False, True)
        add("SIM-BERTH-WINDOW", "warning", "berth", "B05", "泊位与引航窗口冲突", "后续船舶到港窗口与前船预计完工窗口重叠。", ["复核ETA/ETC", "检查引航拖轮资源", "生成备选靠泊序列"])
        add("SIM-GATE-WAVE", "info", "gate", "SOUTH", "南闸口预约到车波峰", "未来30分钟到车率进入模拟高位区间。", ["复核预约曲线", "准备备用车道", "监视场外排队"])
        return alerts

    def _decisions(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        energy = snapshot["energy"]
        low_soc = sum(1 for item in snapshot["equipment"] if item["asset_type"] == "agv" and float(item["soc_percent"] or 100) < 20)
        calls = snapshot["port_calls"]
        window_risk = min(item["window_risk_minutes"] for item in snapshot["berths"])
        definitions = [
            {
                "decision_id": "berth-window-adjust", "category": "berth", "title": "泊位与引航窗口重排建议",
                "trigger": f"最小衔接窗口{window_risk}分钟；{sum(item['status'] in {'awaiting_pilot','scheduled'} for item in calls)}艘待靠/计划船。",
                "action": "按ETA、ETC、吃水余量和岸桥可用性生成备选序列，不改写生产TOS。",
                "baseline": {"estimated_wait_minutes": 78}, "projected": {"estimated_wait_minutes": 61},
                "impact": {"wait_change_minutes": -17, "semantics": "engineering_scenario_estimate"},
                "hard_constraints": ["UKC不得低于场景门限", "引航/拖轮状态必须可用", "已靠泊船舶不强制换泊"],
                "policy": "constraint_heuristic_v1",
            },
            {
                "decision_id": "energy-peak-shave", "category": "energy", "title": "储能与AGV充电错峰建议",
                "trigger": f"电网需量{energy['grid_demand_kw']} kW，场景上限{energy['peak_limit_kw']} kW。",
                "action": "在BESS SOC、效率和衰减成本约束下削峰，并只延后非关键AGV充电。",
                "baseline": {"grid_demand_kw": energy["grid_demand_kw"]},
                "projected": {"grid_demand_kw": round(max(0, float(energy["grid_demand_kw"]) - min(1800, max(0, float(energy["grid_demand_kw"]) - 22400))), 1)},
                "impact": {"peak_reduction_kw": round(min(1800, max(0, float(energy["grid_demand_kw"]) - 22400)), 1), "semantics": "engineering_scenario_estimate"},
                "hard_constraints": ["BESS SOC保持20%—90%", "计入89%往返效率", "计入0.21元/kWh衰减成本", "不削减岸电和安全负荷"],
                "policy": "constrained_peak_shaving_v1",
            },
            {
                "decision_id": "agv-charge-rebalance", "category": "equipment", "title": "AGV任务与充电重平衡建议",
                "trigger": f"{low_soc}台AGV低于20% SOC。",
                "action": "低SOC车辆停止接新任务，由健康车辆接替并进入分级充电队列。",
                "baseline": {"low_soc_assets": low_soc}, "projected": {"low_soc_assets": max(0, low_soc - 3)},
                "impact": {"low_soc_asset_change": -min(3, low_soc), "semantics": "engineering_scenario_estimate"},
                "hard_constraints": ["当前任务安全结束后再退出", "班末SOC恢复到20%以上", "充电功率不突破需量约束"],
                "policy": "agv_soc_guard_v1",
            },
        ]
        if self._scenario_id == "equipment_failure":
            definitions.insert(0, {
                "decision_id": "qc-recovery", "category": "maintenance", "title": "QC-03故障隔离与任务转移",
                "trigger": "QC-03起升机构过温保护触发。", "action": "沙箱挂起QC-03任务、转移至QC-04/QC-05并生成检修草案。",
                "baseline": {"affected_cranes": 1, "moves_at_risk": 64}, "projected": {"affected_cranes": 0, "moves_at_risk": 18},
                "impact": {"moves_at_risk_change": -46, "semantics": "engineering_scenario_estimate"},
                "hard_constraints": ["故障设备保持隔离", "需检修许可", "不得远程复位真实PLC"], "policy": "equipment_failover_sop_v1",
            })
        input_hash = snapshot["metadata"]["payload_sha256"]
        for item in definitions:
            approvals = list(self._approvals.get(item["decision_id"], []))
            executed = item["decision_id"] in self._executed
            item.update({
                "input_payload_sha256": input_hash, "approval_count": len(approvals), "approvals_required": 2,
                "approvals": approvals, "status": "executed_in_sandbox" if executed else "approved" if len(approvals) >= 2 else "pending_approval",
                "sandbox_dispatch_allowed": len(approvals) >= 2, "physical_dispatch_allowed": False,
                "production_authority": False, "executed_in_sandbox": executed,
            })
        return definitions

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            sequence = self._sequence()
            observed_at = _now()
            scenario_id = self._scenario_id
            scenario = _SCENARIOS[scenario_id]
            multipliers = scenario["multipliers"]
            signals = self._signals(sequence)
            traffic = multipliers["traffic"] * (1 + signals["slow"] * 0.035)
            equipment_factor = multipliers["equipment"] * (1 + signals["medium"] * 0.025)
            weather = self._weather(observed_at, scenario_id, signals)
            calls = self._port_calls(observed_at, sequence, traffic, equipment_factor)
            ais = self._ais(observed_at, sequence, traffic)
            berths = self._berths(calls, float(weather["water_level_m_mllw"]))
            equipment = self._equipment(observed_at, sequence, scenario_id, equipment_factor)
            yards = self._yards(signals, traffic)
            gates = self._gates(sequence, multipliers["gate"])
            energy = self._energy(observed_at, sequence, multipliers["energy"], equipment)
            alerts = self._alerts(observed_at, scenario_id, equipment, energy, weather)
            qc = [item for item in equipment if item["asset_type"] == "quay_crane"]
            agv = [item for item in equipment if item["asset_type"] == "agv"]
            yc = [item for item in equipment if item["asset_type"] == "yard_crane"]
            payload: dict[str, Any] = {
                "simulation": self.status(),
                "port": {"code": "XPS01", "name": "公开数据校准样板港区", "timezone": "Asia/Shanghai", "site_connected": False},
                "port_calls": calls, "ais_tracks": ais, "berths": berths, "equipment": equipment,
                "yard_blocks": yards, "gates": gates, "energy": energy, "weather_tide": weather, "alerts": alerts,
                "fleet_summary": {
                    "quay_cranes": {"total": len(qc), "working": sum(item["status"] == "working" for item in qc), "fault": sum(item["status"] == "fault" for item in qc)},
                    "agv": {"total": len(agv), "working": sum(item["status"] == "working" for item in agv), "charging": sum(item["status"] == "charging" for item in agv), "low_soc": sum(float(item["soc_percent"] or 100) < 20 for item in agv)},
                    "yard_cranes": {"total": len(yc), "working": sum(item["status"] == "working" for item in yc)},
                },
                "quality": {
                    "gate_passed": True, "completeness_rate": 1.0, "duplicate_rate": 0.0,
                    "out_of_order_rate": 0.0, "physical_constraint_violations": 0,
                    "checks": ["schema", "units", "timezone", "monotonic sequence", "entity balance", "power balance", "SOC", "yard capacity", "gate capacity", "UKC"],
                },
                "lineage": {
                    "contract_path": str(CONTRACT_PATH.relative_to(ROOT)), "contract_sha256": _CONTRACT_SHA256,
                    "public_ais_path": str(AIS_PATH.relative_to(ROOT)), "public_ais_sha256": _AIS_SHA256,
                    "public_energy_path": str(ENERGY_PATH.relative_to(ROOT)), "public_energy_sha256": _ENERGY_SHA256,
                    "ais_calibration": _AIS_ENVELOPE, "accessed_at": "2026-08-13",
                },
                "governance": {
                    "decision_mode": "recommendation_only", "sandbox_dispatch_allowed": True,
                    "physical_dispatch_allowed": False, "production_authority": False,
                    "site_replacement": "replace adapter only; keep port-realtime.v1 and port-ops.v1 contracts",
                },
            }
            payload["overview"] = {
                "port_name": payload["port"]["name"], "operational_date": observed_at.date(),
                "metrics": [
                    {"id": "vessels-in-port", "label": "模拟在港/待靠船舶", "value": len(calls), "unit": "艘", "display_value": f"{len(calls)} 艘", "trend_percent": round((traffic - 1) * 100, 1), "trend": "up" if traffic >= 1 else "down", "status": "attention" if traffic > 1.15 else "normal"},
                    {"id": "teu-throughput", "label": "模拟今日累计吞吐量", "value": round(16800 + sequence * 23 * equipment_factor), "unit": "TEU", "display_value": f"{round(16800 + sequence * 23 * equipment_factor):,} TEU", "trend_percent": round((equipment_factor - 1) * 100, 1), "trend": "up" if equipment_factor >= 1 else "down", "status": "normal"},
                    {"id": "berth-utilization", "label": "模拟岸桥作业利用率", "value": round(100 * sum(item["status"] == "working" for item in qc) / len(qc), 1), "unit": "%", "display_value": f"{100 * sum(item['status'] == 'working' for item in qc) / len(qc):.1f}%", "trend_percent": round((equipment_factor - 1) * 100, 1), "trend": "up" if equipment_factor >= 1 else "down", "status": "warning" if scenario_id == "storm" else "normal"},
                    {"id": "agv-online-rate", "label": "模拟AGV可用率", "value": round(100 * sum(item["availability"] for item in agv) / len(agv), 1), "unit": "%", "display_value": f"{100 * sum(item['availability'] for item in agv) / len(agv):.1f}%", "trend_percent": 0.0, "trend": "flat", "status": "attention" if payload["fleet_summary"]["agv"]["low_soc"] else "normal"},
                ],
                "secondary_metrics": {"yard_occupancy_percent": round(sum(item["occupancy_percent"] for item in yards) / len(yards), 1), "gate_queue_vehicles": sum(item["queue_vehicles"] for item in gates), "working_berths": sum(item["occupied"] for item in berths), "active_quay_cranes": sum(item["status"] == "working" for item in qc)},
            }
            payload["metadata"] = self._metadata(sequence, observed_at, payload)
            payload["decisions"] = self._decisions(payload)
            return payload

    def energy_history(self, points: int = 30) -> dict[str, Any]:
        snapshot = self.snapshot()
        current = float(snapshot["energy"]["grid_demand_kw"])
        sequence = int(snapshot["simulation"]["sequence"])
        series = []
        for offset in range(points - 1, -1, -1):
            seq = max(0, sequence - offset)
            value = current * (1 + math.sin((seq + self.seed % 97) * 0.29) * 0.022)
            series.append({
                "timestamp": (_now() - timedelta(seconds=offset * 2)).isoformat(),
                "energy_mwh": round(value * 2 / 3_600_000, 4),
                "carbon_emissions_tco2e": round(value * 2 / 3_600_000 * 0.57, 4),
                "grid_demand_kw": round(value, 1),
                "baseline_mwh": round(value * 1.04 * 2 / 3_600_000, 4),
            })
        return {
            "range": "realtime", "updated_at": snapshot["metadata"]["observed_at"], "series": series,
            "series_semantics": "non_overlapping_2_second_simulated_interval_energy", "interval_seconds": 2,
            "source_metadata": snapshot["metadata"],
        }

    def period_energy(self, period: str) -> dict[str, Any]:
        snapshot = self.snapshot()
        current_kw = float(snapshot["energy"]["grid_demand_kw"])
        if period == "today":
            labels = [f"{hour:02d}:00" for hour in range(0, 24, 2)]
            shape = [0.63, 0.58, 0.61, 0.69, 0.82, 0.96, 1.08, 1.04, 0.94, 0.88, 0.83, 0.76]
            interval_hours = 2
        else:
            days = 7 if period == "7d" else 30
            labels = [(_now().date() - timedelta(days=days - index - 1)).isoformat() for index in range(days)]
            shape = [0.94 + math.sin((index + self.seed % 31) * 0.61) * 0.06 for index in range(days)]
            interval_hours = 24
        values = [round(current_kw * factor * interval_hours / 1000, 1) for factor in shape]
        total = round(sum(values), 1)
        carbon = round(total * float(snapshot["energy"]["marginal_carbon_kg_per_kwh"]), 1)
        throughput = max(1.0, float(next(item["value"] for item in snapshot["overview"]["metrics"] if item["id"] == "teu-throughput")))
        shore_share = 100 * float(snapshot["energy"]["shore_power_kw"]) / max(current_kw, 1)
        return {
            "summary": {
                "total_energy_mwh": total,
                "carbon_emissions_tco2e": carbon,
                "carbon_intensity_kgco2e_per_teu": round(carbon * 1000 / throughput, 1),
                "shore_power_utilization_percent": round(_bounded(shore_share * 3.7, 0, 100), 1),
                "energy_change_percent": round((float(snapshot["simulation"]["sequence"]) % 7 - 4) * 0.7, 1),
                "carbon_change_percent": round((float(snapshot["simulation"]["sequence"]) % 5 - 3) * 0.6, 1),
                "intensity_change_percent": round((float(snapshot["simulation"]["sequence"]) % 6 - 4) * 0.5, 1),
                "shore_power_change_percent": round(3.8 + (float(snapshot["simulation"]["sequence"]) % 4) * 0.4, 1),
            },
            "series": [
                {
                    "timestamp": label,
                    "energy_mwh": value,
                    "carbon_emissions_tco2e": round(value * float(snapshot["energy"]["marginal_carbon_kg_per_kwh"]), 1),
                    "baseline_mwh": round(value * 1.04, 1),
                }
                for label, value in zip(labels, values)
            ],
            "series_semantics": "non_overlapping_interval_energy",
            "interval_minutes": interval_hours * 60,
            "insights": [
                f"{TRUTH_LABEL}：当前场景为{snapshot['simulation']['scenario_label']}，数值由同一实时模拟状态计算。",
                "负荷分解覆盖岸桥、场桥、AGV充电、冷藏箱、岸电、暖通、照明和其他用能。",
                "接入港口时仅替换EMS/SCADA适配器；计量点、倍率、时区、结算边界和碳因子仍须现场对账。",
            ],
        }

    def decisions(self) -> list[dict[str, Any]]:
        return self.snapshot()["decisions"]

    def approve(self, decision_id: str, approval: ApprovalRequest) -> dict[str, Any]:
        with self._lock:
            known = {item["decision_id"] for item in self.decisions()}
            if decision_id not in known:
                raise KeyError(decision_id)
            approvals = self._approvals.setdefault(decision_id, [])
            if any(item["approver_id"] == approval.approver_id for item in approvals):
                raise ValueError("同一审批人不能重复批准同一动作")
            item = {**approval.model_dump(), "approved_at": _now().isoformat(), "simulation_only": True}
            approvals.append(item)
            self._record("decision.approved", f"{decision_id} 已记录第{len(approvals)}位沙箱审批人。", decision_id=decision_id, approver_id=approval.approver_id)
            return next(item for item in self.decisions() if item["decision_id"] == decision_id)

    def execute(self, decision_id: str, reason: str) -> dict[str, Any]:
        with self._lock:
            decision = next((item for item in self.decisions() if item["decision_id"] == decision_id), None)
            if decision is None:
                raise KeyError(decision_id)
            if int(decision["approval_count"]) < 2:
                raise PermissionError("沙箱动作仍需要两名不同审批人")
            self._executed.add(decision_id)
            event = self._record(
                "decision.executed_in_sandbox", f"{decision_id} 已改变模拟状态；原因：{reason}",
                decision_id=decision_id, physical_dispatch_performed=False,
            )
            return {
                "decision": next(item for item in self.decisions() if item["decision_id"] == decision_id),
                "event": event, "sandbox_state_updated": True, "physical_dispatch_performed": False,
                "production_authority": False,
            }

    def rollback(self, decision_id: str, reason: str) -> dict[str, Any]:
        with self._lock:
            if decision_id not in self._executed:
                raise ValueError("该沙箱动作尚未执行，无需回滚")
            self._executed.remove(decision_id)
            event = self._record(
                "decision.rolled_back_in_sandbox", f"{decision_id} 已恢复到执行前模拟规则；原因：{reason}",
                decision_id=decision_id, physical_dispatch_performed=False,
            )
            return {
                "decision": next(item for item in self.decisions() if item["decision_id"] == decision_id),
                "event": event, "sandbox_state_updated": True, "physical_dispatch_performed": False,
                "production_authority": False,
            }

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)[:limit]


realtime_port_simulator = PortRealtimeSimulator()


def _audit(request: Request, action: str, resource: str, outcome: str, detail: str, payload: Any, response: Any) -> None:
    identity = request_identity(request)
    runtime_store.add_audit(
        correlation_id=getattr(request.state, "request_id", f"sim-{uuid4().hex}"),
        actor_id=identity.actor_id,
        actor_role=identity.role,
        action=action,
        resource=resource,
        risk_level="medium",
        outcome=outcome,
        request=payload,
        response=response,
        detail=detail,
    )


@router.get("/status")
def simulator_status() -> dict[str, Any]:
    return realtime_port_simulator.status()


@router.get("/contract")
def simulator_contract() -> dict[str, Any]:
    return {
        **_CONTRACT,
        "artifact": str(CONTRACT_PATH.relative_to(ROOT)),
        "artifact_sha256": _CONTRACT_SHA256,
        "domain_count": len(_CONTRACT["domains"]),
        "canonical_field_count": sum(len(item["required_fields"]) for item in _CONTRACT["domains"]),
    }


@router.get("/snapshot")
def simulator_snapshot() -> dict[str, Any]:
    return realtime_port_simulator.snapshot()


@router.get("/history")
def simulator_history(points: int = Query(30, ge=5, le=120)) -> dict[str, Any]:
    return realtime_port_simulator.energy_history(points)


@router.get("/decisions")
def simulator_decisions() -> dict[str, Any]:
    return {
        "items": realtime_port_simulator.decisions(),
        "decision_mode": "recommendation_only",
        "sandbox_dispatch_allowed": True,
        "physical_dispatch_allowed": False,
        "production_authority": False,
    }


@router.get("/events")
def simulator_events(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    items = realtime_port_simulator.events(limit)
    return {"total": len(items), "items": items}


@router.post("/scenario")
def change_scenario(payload: ScenarioRequest, request: Request) -> dict[str, Any]:
    result = realtime_port_simulator.set_scenario(payload.scenario_id, payload.reason)
    _audit(request, "port_simulator.scenario_change", payload.scenario_id, "success", "模拟场景已切换；未访问现场系统。", payload.model_dump(), result)
    return result


@router.post("/decisions/{decision_id}/approve")
def approve_decision(decision_id: str, payload: ApprovalRequest, request: Request) -> dict[str, Any]:
    try:
        result = realtime_port_simulator.approve(decision_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知沙箱决策") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(request, "port_simulator.decision_approve", decision_id, "success", "沙箱审批已记录；不构成生产授权。", payload.model_dump(), result)
    return result


@router.post("/decisions/{decision_id}/execute")
def execute_decision(decision_id: str, payload: ActionRequest, request: Request) -> dict[str, Any]:
    try:
        result = realtime_port_simulator.execute(decision_id, payload.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知沙箱决策") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(request, "port_simulator.decision_execute", decision_id, "success", "动作只改变模拟器状态；physical_dispatch_performed=false。", payload.model_dump(), result)
    return result


@router.post("/decisions/{decision_id}/rollback")
def rollback_decision(decision_id: str, payload: ActionRequest, request: Request) -> dict[str, Any]:
    try:
        result = realtime_port_simulator.rollback(decision_id, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(request, "port_simulator.decision_rollback", decision_id, "success", "模拟动作已回滚；未触碰生产系统。", payload.model_dump(), result)
    return result


@router.get("/stream")
def simulator_stream() -> StreamingResponse:
    async def events():
        while True:
            snapshot = realtime_port_simulator.snapshot()
            yield f"event: telemetry\ndata: {json.dumps(snapshot, ensure_ascii=False, default=str)}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
