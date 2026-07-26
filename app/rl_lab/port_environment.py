from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Optional

from app.rl_lab.datasets import EnergyRecord, infer_step_minutes
from app.rl_lab.environment import percentile


PORT_ACTION_CAPACITY_FACTORS = (0.65, 0.82, 1.0, 1.15, 1.30)
PORT_ACTION_LABELS = ("安全降载", "稳态保守", "平衡运行", "增派资源", "高峰恢复")


def _present(value: Optional[float], default: float) -> float:
    return default if value is None else value


@dataclass(frozen=True)
class PortOperationsParameters:
    step_hours: float
    base_service_rate_per_hour: float
    maximum_backlog: float
    traffic_bins: tuple[float, ...]
    queue_bins: tuple[float, ...]
    speed_bins: tuple[float, ...]
    calibration_notice: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "environment_type": "port_operations",
            "step_hours": round(self.step_hours, 6),
            "base_service_rate_per_hour": round(self.base_service_rate_per_hour, 6),
            "maximum_backlog": round(self.maximum_backlog, 6),
            "traffic_bins": [round(value, 6) for value in self.traffic_bins],
            "queue_bins": [round(value, 6) for value in self.queue_bins],
            "speed_bins": [round(value, 6) for value in self.speed_bins],
            "action_capacity_factors": list(PORT_ACTION_CAPACITY_FACTORS),
            "calibration_notice": self.calibration_notice,
        }


def derive_port_parameters(records: list[EnergyRecord]) -> PortOperationsParameters:
    step_hours = infer_step_minutes(records) / 60
    traffic = [max(0.0, item.vessel_count or 0.0) for item in records]
    queues = [
        max(0.0, item.anchored_vessels or 0.0) + max(0.0, item.slow_vessels or 0.0)
        for item in records
    ]
    speeds = [max(0.0, item.avg_sog_knots or 0.0) for item in records]
    changes = [max(0.0, current - previous) for previous, current in zip(traffic, traffic[1:])]
    demand_per_step = max(0.25, percentile(changes or [0.0], 0.75) + percentile(queues, 0.5) * 0.04)
    return PortOperationsParameters(
        step_hours=step_hours,
        base_service_rate_per_hour=demand_per_step / max(step_hours, 1 / 60),
        maximum_backlog=max(8.0, percentile(queues, 0.95) * 2.5),
        traffic_bins=tuple(percentile(traffic, ratio) for ratio in (0.2, 0.4, 0.6, 0.8)),
        queue_bins=tuple(percentile(queues, ratio) for ratio in (0.2, 0.4, 0.6, 0.8)),
        speed_bins=tuple(percentile(speeds, ratio) for ratio in (0.2, 0.4, 0.6, 0.8)),
        calibration_notice=(
            "服务能力由训练段交通变化与排队代理量标定，不代表码头实测装卸能力；"
            "生产部署必须用泊位、工班和设备实绩重新标定。"
        ),
    )


class PortOperationsEnvironment:
    def __init__(
        self,
        records: list[EnergyRecord],
        parameters: PortOperationsParameters,
        *,
        horizon_steps: int,
        seed: int,
        split_name: str,
        render_mode: Optional[str] = None,
    ) -> None:
        if len(records) < horizon_steps + 1:
            raise ValueError("dataset split is shorter than horizon_steps + 1")
        if render_mode is not None and split_name != "test":
            raise ValueError("render output is allowed only on the untouched test split")
        self.records = records
        self.parameters = parameters
        self.horizon_steps = horizon_steps
        self.rng = random.Random(seed)
        self.split_name = split_name
        self.render_mode = render_mode
        self.start_index = 0
        self.index = 0
        self.steps = 0
        self.backlog = 0.0
        self.previous_action_factor = 1.0
        self.total_reward = 0.0
        self.total_served = 0.0
        self.total_backlog = 0.0
        self.total_service_capacity = 0.0
        self.total_wait_proxy_hours = 0.0
        self.constraint_violations = 0
        self.measured_energy_kwh = 0.0
        self.measured_carbon_kg = 0.0
        self.energy_observation_count = 0
        self.frames: list[dict[str, Any]] = []

    @staticmethod
    def _bin(value: float, boundaries: tuple[float, ...]) -> int:
        return sum(value > boundary for boundary in boundaries)

    @staticmethod
    def _ratio_bin(value: float) -> int:
        return min(4, max(0, int(value * 5)))

    @staticmethod
    def weather_risk(record: EnergyRecord) -> float:
        wind = _present(record.wind_speed_mps, 0.0)
        visibility = _present(record.visibility_km, 10.0)
        wind_risk = min(1.0, max(0.0, (wind - 8.0) / 17.0))
        visibility_risk = min(1.0, max(0.0, (5.0 - visibility) / 5.0))
        return max(wind_risk, visibility_risk)

    def reset(self, *, start_index: Optional[int] = None) -> tuple[int, ...]:
        last_start = len(self.records) - self.horizon_steps - 1
        if start_index is None:
            start_index = self.rng.randint(0, max(0, last_start))
        self.start_index = min(max(0, start_index), max(0, last_start))
        self.index = self.start_index
        self.steps = 0
        initial = self.records[self.index]
        self.backlog = max(0.0, initial.anchored_vessels or 0.0) + max(0.0, initial.slow_vessels or 0.0)
        self.previous_action_factor = 1.0
        self.total_reward = 0.0
        self.total_served = 0.0
        self.total_backlog = 0.0
        self.total_service_capacity = 0.0
        self.total_wait_proxy_hours = 0.0
        self.constraint_violations = 0
        self.measured_energy_kwh = 0.0
        self.measured_carbon_kg = 0.0
        self.energy_observation_count = 0
        self.frames = []
        return self.state()

    def state(self) -> tuple[int, ...]:
        current = self.records[self.index]
        following = self.records[min(self.index + 1, len(self.records) - 1)]
        queue = max(0.0, current.anchored_vessels or 0.0) + max(0.0, current.slow_vessels or 0.0)
        traffic = max(0.0, current.vessel_count or 0.0)
        speed = max(0.0, current.avg_sog_knots or 0.0)
        equipment = _present(current.equipment_availability_ratio, 1.0)
        berth = _present(current.berth_occupancy_ratio, min(1.0, queue / max(1.0, traffic)))
        yard = _present(current.yard_occupancy_ratio, 0.65)
        tide_open = 1 if _present(current.tide_window_open, 1.0) >= 0.5 else 0
        trend = max(0.0, following.vessel_count or 0.0) - traffic
        tolerance = max(1.0, percentile(list(self.parameters.traffic_bins), 0.5) * 0.04)
        trend_bin = 0 if trend < -tolerance else 2 if trend > tolerance else 1
        return (
            current.timestamp.hour // 4,
            self._bin(traffic, self.parameters.traffic_bins),
            self._bin(queue, self.parameters.queue_bins),
            self._bin(speed, self.parameters.speed_bins),
            min(5, int(self.backlog / max(1.0, self.parameters.maximum_backlog) * 6)),
            self._ratio_bin(berth),
            self._ratio_bin(yard),
            self._ratio_bin(equipment),
            min(3, int(self.weather_risk(current) * 4)),
            tide_open,
            trend_bin,
        )

    def valid_action_mask(self) -> tuple[bool, ...]:
        record = self.records[self.index]
        risk = self.weather_risk(record)
        equipment = _present(record.equipment_availability_ratio, 1.0)
        tide_open = _present(record.tide_window_open, 1.0) >= 0.5
        return tuple(
            not (index >= 3 and (risk >= 0.72 or equipment < 0.50 or not tide_open))
            for index in range(len(PORT_ACTION_CAPACITY_FACTORS))
        )

    def step(self, action_index: int) -> tuple[tuple[int, ...], float, bool, dict[str, Any]]:
        if not 0 <= action_index < len(PORT_ACTION_CAPACITY_FACTORS):
            raise ValueError(f"invalid action index {action_index}")
        record = self.records[self.index]
        previous = self.records[max(self.start_index, self.index - 1)]
        traffic = max(0.0, record.vessel_count or 0.0)
        queue_observed = max(0.0, record.anchored_vessels or 0.0) + max(0.0, record.slow_vessels or 0.0)
        arrivals = max(0.0, traffic - max(0.0, previous.vessel_count or 0.0))
        demand_units = arrivals + queue_observed * 0.04
        self.backlog += demand_units

        factor = PORT_ACTION_CAPACITY_FACTORS[action_index]
        risk = self.weather_risk(record)
        equipment = min(1.0, max(0.0, _present(record.equipment_availability_ratio, 1.0)))
        berth = min(1.0, max(0.0, _present(record.berth_occupancy_ratio, queue_observed / max(1.0, traffic))))
        yard = min(1.0, max(0.0, _present(record.yard_occupancy_ratio, 0.65)))
        tide_open = _present(record.tide_window_open, 1.0) >= 0.5
        weather_capacity = max(0.25, 1.0 - risk * 0.75)
        tide_capacity = 1.0 if tide_open else 0.45
        berth_capacity = max(0.35, 1.0 - berth * 0.45)
        service_capacity = (
            self.parameters.base_service_rate_per_hour
            * self.parameters.step_hours
            * factor
            * weather_capacity
            * tide_capacity
            * max(0.2, equipment)
            * berth_capacity
        )
        served = min(self.backlog, max(0.0, service_capacity))
        self.backlog = max(0.0, self.backlog - served)

        safety_violation = bool(
            (action_index >= 3 and risk >= 0.72)
            or (action_index >= 3 and equipment < 0.50)
            or (action_index >= 3 and not tide_open)
        )
        yard_overflow = max(0.0, yard - 0.85)
        backlog_overflow = self.backlog > self.parameters.maximum_backlog
        violations = int(safety_violation) + int(backlog_overflow)
        self.constraint_violations += violations

        throughput_reward = served * 1.8
        backlog_penalty = self.backlog
        safety_penalty = violations * 12.0
        yard_penalty = yard_overflow * 8.0
        action_change_penalty = abs(factor - self.previous_action_factor) * 0.6
        resource_penalty = max(0.0, factor - 1.0) * 0.5
        reward = (
            throughput_reward
            - backlog_penalty
            - safety_penalty
            - yard_penalty
            - action_change_penalty
            - resource_penalty
        )
        self.previous_action_factor = factor
        self.total_reward += reward
        self.total_served += served
        self.total_backlog += self.backlog
        self.total_service_capacity += service_capacity
        self.total_wait_proxy_hours += self.backlog * self.parameters.step_hours
        if record.load_kw is not None:
            energy_kwh = record.load_kw * self.parameters.step_hours
            self.measured_energy_kwh += energy_kwh
            self.measured_carbon_kg += energy_kwh * _present(record.carbon_kg_per_kwh, 0.45)
            self.energy_observation_count += 1

        self.steps += 1
        done = self.steps >= self.horizon_steps
        frame = {
            "step": self.steps,
            "timestamp": record.timestamp.isoformat(),
            "vessel_count": round(traffic, 6),
            "anchored_vessels": round(max(0.0, record.anchored_vessels or 0.0), 6),
            "slow_vessels": round(max(0.0, record.slow_vessels or 0.0), 6),
            "avg_sog_knots": round(max(0.0, record.avg_sog_knots or 0.0), 6),
            "action": action_index,
            "action_label": PORT_ACTION_LABELS[action_index],
            "capacity_factor": factor,
            "service_capacity": round(service_capacity, 6),
            "served_units": round(served, 6),
            "backlog_units": round(self.backlog, 6),
            "weather_risk": round(risk, 6),
            "berth_occupancy_ratio": round(berth, 6),
            "yard_occupancy_ratio": round(yard, 6),
            "equipment_availability_ratio": round(equipment, 6),
            "tide_window_open": tide_open,
            "reward": round(reward, 8),
            "constraint_violation": bool(violations),
            "split": self.split_name,
            "evidence_level": "measured_ais_plus_calibrated_operations_proxy",
        }
        if self.render_mode == "trace":
            self.frames.append(frame)
        self.index += 1
        next_state = self.state() if not done else tuple(0 for _ in range(11))
        return next_state, reward, done, frame

    def episode_metrics(self, total_reward: float) -> dict[str, Any]:
        average_backlog = self.total_backlog / max(1, self.steps)
        capacity_utilization = self.total_served / max(1e-9, self.total_service_capacity) * 100
        return {
            "total_reward": round(total_reward, 6),
            "served_units": round(self.total_served, 6),
            "average_backlog_units": round(average_backlog, 6),
            "wait_proxy_hours": round(self.total_wait_proxy_hours, 6),
            "capacity_utilization_percent": round(capacity_utilization, 6),
            "constraint_violations": self.constraint_violations,
            "measured_energy_kwh": (
                round(self.measured_energy_kwh, 6) if self.energy_observation_count else None
            ),
            "measured_carbon_kg": (
                round(self.measured_carbon_kg, 6) if self.energy_observation_count else None
            ),
            "terminal_backlog_units": round(self.backlog, 6),
            "steps": self.steps,
            "split": self.split_name,
            "metric_boundary": (
                "AIS traffic fields are measured; served, backlog and waiting metrics are calibrated scenario outputs, "
                "not observed terminal production results."
            ),
        }
