from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Optional

from app.rl_lab.datasets import EnergyRecord, infer_step_minutes


ACTIONS = (-1.0, -0.5, 0.0, 0.5, 1.0)
ACTION_LABELS = (
    "全功率放电",
    "半功率放电",
    "保持",
    "半功率充电",
    "全功率充电",
)


def percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    position = (len(ordered) - 1) * min(1.0, max(0.0, ratio))
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


@dataclass(frozen=True)
class EnvironmentParameters:
    capacity_kwh: float
    max_power_kw: float
    minimum_soc: float
    maximum_soc: float
    initial_soc: float
    round_trip_efficiency: float
    step_hours: float
    peak_target_kw: float
    mean_load_kw: float
    load_bins: tuple[float, ...]

    def public_dict(self) -> dict[str, Any]:
        return {
            "capacity_kwh": round(self.capacity_kwh, 6),
            "max_power_kw": round(self.max_power_kw, 6),
            "minimum_soc": self.minimum_soc,
            "maximum_soc": self.maximum_soc,
            "initial_soc": self.initial_soc,
            "round_trip_efficiency": self.round_trip_efficiency,
            "step_hours": round(self.step_hours, 6),
            "peak_target_kw": round(self.peak_target_kw, 6),
            "mean_load_kw": round(self.mean_load_kw, 6),
            "load_bins": [round(value, 6) for value in self.load_bins],
            "action_factors": list(ACTIONS),
        }


def derive_parameters(records: list[EnergyRecord]) -> EnvironmentParameters:
    loads = [item.load_kw for item in records]
    p95 = max(0.01, percentile(loads, 0.95))
    mean_load = max(0.01, sum(loads) / len(loads))
    step_hours = infer_step_minutes(records) / 60
    return EnvironmentParameters(
        capacity_kwh=max(p95 * 3.0, mean_load * 4.0),
        max_power_kw=max(p95 * 0.55, mean_load * 0.7),
        minimum_soc=0.10,
        maximum_soc=0.95,
        initial_soc=0.55,
        round_trip_efficiency=0.90,
        step_hours=step_hours,
        peak_target_kw=percentile(loads, 0.75),
        mean_load_kw=mean_load,
        load_bins=(
            percentile(loads, 0.20),
            percentile(loads, 0.40),
            percentile(loads, 0.60),
            percentile(loads, 0.80),
        ),
    )


def tariff_for(record: EnergyRecord) -> float:
    if record.price_per_kwh is not None:
        return record.price_per_kwh
    hour = record.timestamp.hour
    if 0 <= hour < 7:
        return 0.10
    if 17 <= hour < 21:
        return 0.32
    return 0.18


def carbon_for(record: EnergyRecord) -> float:
    return record.carbon_kg_per_kwh if record.carbon_kg_per_kwh is not None else 0.45


class EnergySchedulingEnvironment:
    """CPU-only discrete storage scheduler driven by measured time-series rows.

    The environment never fabricates observations. Exogenous load and optional
    tariff/carbon signals come from the selected CSV. Missing tariff and carbon
    fields use the explicitly documented experimental constants above.
    """

    def __init__(
        self,
        records: list[EnergyRecord],
        parameters: EnvironmentParameters,
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
        self.soc = parameters.initial_soc
        self.peak_grid_kw = 0.0
        self.total_cost = 0.0
        self.total_carbon_kg = 0.0
        self.constraint_violations = 0
        self.frames: list[dict[str, Any]] = []

    def reset(self, *, start_index: Optional[int] = None) -> tuple[int, ...]:
        last_start = len(self.records) - self.horizon_steps - 1
        if start_index is None:
            start_index = self.rng.randint(0, max(0, last_start))
        self.start_index = min(max(0, start_index), max(0, last_start))
        self.index = self.start_index
        self.steps = 0
        self.soc = self.parameters.initial_soc
        self.peak_grid_kw = 0.0
        self.total_cost = 0.0
        self.total_carbon_kg = 0.0
        self.constraint_violations = 0
        self.frames = []
        return self.state()

    def _bin(self, value: float, boundaries: tuple[float, ...]) -> int:
        return sum(value > boundary for boundary in boundaries)

    def state(self) -> tuple[int, ...]:
        current = self.records[self.index]
        following = self.records[min(self.index + 1, len(self.records) - 1)]
        hour_bin = current.timestamp.hour // 4
        load_bin = self._bin(current.load_kw, self.parameters.load_bins)
        soc_bin = min(7, max(0, int(self.soc * 8)))
        tariff = tariff_for(current)
        tariff_bin = 0 if tariff < 0.14 else 1 if tariff < 0.25 else 2
        delta = following.load_kw - current.load_kw
        tolerance = max(0.001, self.parameters.mean_load_kw * 0.05)
        trend_bin = 0 if delta < -tolerance else 2 if delta > tolerance else 1
        return hour_bin, load_bin, soc_bin, tariff_bin, trend_bin

    def valid_action_mask(self) -> tuple[bool, ...]:
        return tuple(
            not (factor < 0 and self.soc <= self.parameters.minimum_soc + 1e-9)
            and not (factor > 0 and self.soc >= self.parameters.maximum_soc - 1e-9)
            for factor in ACTIONS
        )

    def step(self, action_index: int) -> tuple[tuple[int, ...], float, bool, dict[str, Any]]:
        if not 0 <= action_index < len(ACTIONS):
            raise ValueError(f"invalid action index {action_index}")
        record = self.records[self.index]
        factor = ACTIONS[action_index]
        requested_power_kw = factor * self.parameters.max_power_kw
        efficiency = math.sqrt(self.parameters.round_trip_efficiency)
        available_discharge_kwh = max(0.0, (self.soc - self.parameters.minimum_soc) * self.parameters.capacity_kwh)
        available_charge_kwh = max(0.0, (self.parameters.maximum_soc - self.soc) * self.parameters.capacity_kwh)
        if requested_power_kw < 0:
            actual_energy_kwh = -min(abs(requested_power_kw) * self.parameters.step_hours, available_discharge_kwh * efficiency)
            actual_power_kw = actual_energy_kwh / self.parameters.step_hours
            soc_delta = actual_energy_kwh / efficiency / self.parameters.capacity_kwh
        else:
            actual_energy_kwh = min(requested_power_kw * self.parameters.step_hours, available_charge_kwh / efficiency)
            actual_power_kw = actual_energy_kwh / self.parameters.step_hours
            soc_delta = actual_energy_kwh * efficiency / self.parameters.capacity_kwh
        constrained = abs(actual_power_kw - requested_power_kw) > max(1e-8, self.parameters.max_power_kw * 1e-6)
        self.soc = min(self.parameters.maximum_soc, max(self.parameters.minimum_soc, self.soc + soc_delta))
        grid_kw = max(0.0, record.load_kw + actual_power_kw)
        tariff = tariff_for(record)
        carbon_intensity = carbon_for(record)
        step_energy_kwh = grid_kw * self.parameters.step_hours
        step_cost = step_energy_kwh * tariff
        step_carbon_kg = step_energy_kwh * carbon_intensity
        self.peak_grid_kw = max(self.peak_grid_kw, grid_kw)
        self.total_cost += step_cost
        self.total_carbon_kg += step_carbon_kg
        if constrained:
            self.constraint_violations += 1

        cost_scale = max(0.001, self.parameters.mean_load_kw * self.parameters.step_hours * 0.18)
        peak_excess = max(0.0, grid_kw - self.parameters.peak_target_kw) / max(0.01, self.parameters.peak_target_kw)
        reward = -(step_cost / cost_scale + peak_excess * 1.4 + (1.5 if constrained else 0.0))

        self.steps += 1
        done = self.steps >= self.horizon_steps
        if done:
            reserve_shortfall = max(0.0, 0.50 - self.soc)
            reward -= reserve_shortfall * 12.0
        frame = {
            "step": self.steps,
            "timestamp": record.timestamp.isoformat(),
            "load_kw": round(record.load_kw, 6),
            "action": action_index,
            "action_label": ACTION_LABELS[action_index],
            "requested_power_kw": round(requested_power_kw, 6),
            "storage_power_kw": round(actual_power_kw, 6),
            "grid_kw": round(grid_kw, 6),
            "soc": round(self.soc, 6),
            "tariff_per_kwh": round(tariff, 6),
            "carbon_kg_per_kwh": round(carbon_intensity, 6),
            "step_cost": round(step_cost, 8),
            "step_carbon_kg": round(step_carbon_kg, 8),
            "reward": round(reward, 8),
            "constrained": constrained,
            "split": self.split_name,
        }
        if self.render_mode == "trace":
            self.frames.append(frame)
        self.index += 1
        next_state = self.state() if not done else (0, 0, 0, 0, 0)
        return next_state, reward, done, frame

    def episode_metrics(self, total_reward: float) -> dict[str, Any]:
        baseline_records = self.records[self.start_index:self.start_index + self.horizon_steps]
        baseline_energy = sum(item.load_kw * self.parameters.step_hours for item in baseline_records)
        baseline_cost = sum(item.load_kw * self.parameters.step_hours * tariff_for(item) for item in baseline_records)
        baseline_peak = max(item.load_kw for item in baseline_records)
        controlled_energy = sum(frame["grid_kw"] * self.parameters.step_hours for frame in self.frames) if self.frames else None
        return {
            "total_reward": round(total_reward, 6),
            "total_cost": round(self.total_cost, 8),
            "baseline_cost": round(baseline_cost, 8),
            "cost_saving_percent": round((baseline_cost - self.total_cost) / max(1e-9, baseline_cost) * 100, 4),
            "controlled_energy_kwh": round(controlled_energy, 8) if controlled_energy is not None else None,
            "baseline_energy_kwh": round(baseline_energy, 8),
            "peak_grid_kw": round(self.peak_grid_kw, 6),
            "baseline_peak_kw": round(baseline_peak, 6),
            "peak_reduction_percent": round((baseline_peak - self.peak_grid_kw) / max(1e-9, baseline_peak) * 100, 4),
            "carbon_kg": round(self.total_carbon_kg, 8),
            "constraint_violations": self.constraint_violations,
            "terminal_soc": round(self.soc, 6),
            "steps": self.steps,
            "split": self.split_name,
        }
