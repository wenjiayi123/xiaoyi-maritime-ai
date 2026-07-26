from __future__ import annotations

from copy import deepcopy
from typing import Any


ENERGY_STORAGE_CONTRACT: dict[str, Any] = {
    "id": "energy_storage",
    "label": "港口能源与储能调度",
    "decision_scope": "在给定负荷、电价、碳强度和储能约束下选择充放电功率档位。",
    "observation": [
        {"id": "hour_bin", "source": "timestamp", "evidence": "measured"},
        {"id": "load_bin", "source": "load_kw", "evidence": "measured"},
        {"id": "soc_bin", "source": "environment_state", "evidence": "simulated_state"},
        {"id": "tariff_bin", "source": "price_per_kwh", "evidence": "measured_or_documented_default"},
        {"id": "load_trend_bin", "source": "load_kw(t+1)-load_kw(t)", "evidence": "derived"},
    ],
    "actions": [
        {"index": 0, "id": "full_discharge", "label": "全功率放电", "factor": -1.0},
        {"index": 1, "id": "half_discharge", "label": "半功率放电", "factor": -0.5},
        {"index": 2, "id": "hold", "label": "保持", "factor": 0.0},
        {"index": 3, "id": "half_charge", "label": "半功率充电", "factor": 0.5},
        {"index": 4, "id": "full_charge", "label": "全功率充电", "factor": 1.0},
    ],
    "objective": {
        "direction": "maximize",
        "formula": "-energy_cost - 1.4*peak_excess - 1.5*constraint_violation - 12*terminal_reserve_shortfall",
        "components": [
            "energy_cost",
            "peak_excess",
            "soc_constraint_violation",
            "terminal_reserve_shortfall",
        ],
    },
    "hard_constraints": [
        "minimum_soc <= soc <= maximum_soc",
        "abs(storage_power_kw) <= max_power_kw",
        "training render_mode is None",
        "test rows are unavailable before training completes",
    ],
}


PORT_OPERATIONS_CONTRACT: dict[str, Any] = {
    "id": "port_operations",
    "label": "AIS驱动的港口交通—服务能力协同",
    "decision_scope": "依据真实交通观测和站点约束选择服务能力档位；输出只作为规划沙箱建议。",
    "observation": [
        {"id": "hour_bin", "source": "timestamp", "evidence": "measured"},
        {"id": "traffic_bin", "source": "vessel_count", "evidence": "measured"},
        {"id": "queue_bin", "source": "anchored_vessels+slow_vessels", "evidence": "measured_proxy"},
        {"id": "speed_bin", "source": "avg_sog_knots", "evidence": "measured"},
        {"id": "backlog_bin", "source": "environment_state", "evidence": "simulated_state"},
        {"id": "berth_bin", "source": "berth_occupancy_ratio", "evidence": "site_or_proxy"},
        {"id": "yard_bin", "source": "yard_occupancy_ratio", "evidence": "site_or_proxy"},
        {"id": "equipment_bin", "source": "equipment_availability_ratio", "evidence": "site_or_default"},
        {"id": "weather_risk_bin", "source": "wind_speed_mps+visibility_km", "evidence": "site_or_default"},
        {"id": "tide_window", "source": "tide_window_open", "evidence": "site_or_default"},
        {"id": "traffic_trend_bin", "source": "vessel_count(t+1)-vessel_count(t)", "evidence": "derived"},
    ],
    "actions": [
        {"index": 0, "id": "safety_downshift", "label": "安全降载", "capacity_factor": 0.65},
        {"index": 1, "id": "conservative", "label": "稳态保守", "capacity_factor": 0.82},
        {"index": 2, "id": "balanced", "label": "平衡运行", "capacity_factor": 1.0},
        {"index": 3, "id": "resource_boost", "label": "增派资源", "capacity_factor": 1.15},
        {"index": 4, "id": "peak_recovery", "label": "高峰恢复", "capacity_factor": 1.30},
    ],
    "objective": {
        "direction": "maximize",
        "formula": (
            "+1.8*served_units - backlog - 12*safety_violation "
            "- 8*yard_overflow - 0.6*action_change - 0.5*resource_boost"
        ),
        "components": [
            "served_units",
            "backlog",
            "safety_violation",
            "yard_overflow",
            "action_change",
            "resource_boost",
            "measured_energy_and_carbon_when_available",
        ],
    },
    "hard_constraints": [
        "unsafe high-capacity actions are masked during severe weather, closed tide windows, or low equipment availability",
        "production systems are never written by the RL laboratory",
        "training render_mode is None",
        "test rows are unavailable before training completes",
    ],
    "international_port_factors": [
        {"id": "port_identity", "fields": ["unlocode", "terminal_id", "timezone"], "standard": "UN/LOCODE"},
        {"id": "port_call", "fields": ["ETA/RTA/PTA/ATA", "ETD/RTD/PTD/ATD", "move_forecast"], "standard": "DCSA Port Call"},
        {"id": "nautical", "fields": ["berth", "fairway", "pilot", "tug", "linesmen", "draft", "tide", "current"]},
        {"id": "traffic", "fields": ["AIS vessel count", "SOG", "navigation status", "vessel type"]},
        {"id": "terminal", "fields": ["berth occupancy", "crane availability", "yard occupancy", "reefer", "dangerous goods"]},
        {"id": "hinterland", "fields": ["gate queue", "truck appointments", "rail window"]},
        {"id": "environment", "fields": ["wind", "visibility", "wave", "water level", "emissions"]},
        {"id": "governance", "fields": ["data quality", "freshness", "authorization", "human confirmation"]},
    ],
}


ENVIRONMENT_CONTRACTS = {
    ENERGY_STORAGE_CONTRACT["id"]: ENERGY_STORAGE_CONTRACT,
    PORT_OPERATIONS_CONTRACT["id"]: PORT_OPERATIONS_CONTRACT,
}


def environment_contract(environment_type: str) -> dict[str, Any]:
    contract = ENVIRONMENT_CONTRACTS.get(environment_type)
    if contract is None:
        raise ValueError(f"unsupported RL environment_type: {environment_type}")
    return deepcopy(contract)


def environment_contract_catalog() -> list[dict[str, Any]]:
    return [deepcopy(item) for item in ENVIRONMENT_CONTRACTS.values()]
