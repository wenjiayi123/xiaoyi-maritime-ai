from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.rl_lab.datasets import EnergyRecord
from app.rl_lab.environment import (
    ACTIONS,
    EnergySchedulingEnvironment,
    EnvironmentParameters,
    tariff_for,
)
from app.rl_lab.port_environment import (
    PORT_ACTION_CAPACITY_FACTORS,
    PortOperationsEnvironment,
    PortOperationsParameters,
)


ALGORITHM_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "q_learning",
        "label": "Q-learning",
        "family": "reinforcement_learning",
        "type": "off_policy_td_control",
        "trainable": True,
        "description": "离策略时序差分控制，更新目标使用下一状态最大动作价值。",
        "update_equation": "Q(s,a) <- Q(s,a) + alpha[r + gamma max_a' Q(s',a') - Q(s,a)]",
        "compatible_environments": ["energy_storage", "port_operations"],
    },
    {
        "id": "sarsa",
        "label": "SARSA",
        "family": "reinforcement_learning",
        "type": "on_policy_td_control",
        "trainable": True,
        "description": "同策略时序差分控制，训练目标跟随实际探索动作。",
        "update_equation": "Q(s,a) <- Q(s,a) + alpha[r + gamma Q(s',a') - Q(s,a)]",
        "compatible_environments": ["energy_storage", "port_operations"],
    },
    {
        "id": "expected_sarsa",
        "label": "Expected SARSA",
        "family": "reinforcement_learning",
        "type": "expected_on_policy_td_control",
        "trainable": True,
        "description": "用 epsilon-greedy 策略下的期望动作价值降低更新方差。",
        "update_equation": "Q(s,a) <- Q(s,a) + alpha[r + gamma E_pi Q(s',a') - Q(s,a)]",
        "compatible_environments": ["energy_storage", "port_operations"],
    },
    {
        "id": "double_q_learning",
        "label": "Double Q-learning",
        "family": "reinforcement_learning",
        "type": "double_estimator_off_policy_td",
        "trainable": True,
        "description": "双价值表解耦动作选择与评估，缓解最大化偏差。",
        "update_equation": "随机更新Q_A或Q_B；动作选择与目标评估使用不同价值表",
        "compatible_environments": ["energy_storage", "port_operations"],
    },
    {
        "id": "pid",
        "label": "PID 控制基线",
        "family": "control_theory",
        "type": "proportional_integral_derivative_controller",
        "trainable": False,
        "description": "控制理论基线：能源环境跟踪峰值与SOC，港口环境跟踪队列与积压，并遵守相同动作约束。",
        "update_equation": "u_t = Kp*e_t + Ki*sum(e_t) + Kd*(e_t-e_t-1)",
        "compatible_environments": ["energy_storage", "port_operations"],
    },
    {
        "id": "sop_rule",
        "label": "现场 SOP 固定规则基线",
        "family": "operations_rule",
        "type": "deterministic_site_sop_proxy",
        "trainable": False,
        "description": "能源环境按电价、负荷和SOC执行固定充放电规则；港口环境按积压、锚泊代理和安全动作掩码选择能力档位。规则不读取测试未来值。",
        "update_equation": "if/then SOP rules over current observation; no learned parameters",
        "compatible_environments": ["energy_storage", "port_operations"],
    },
)

RL_ALGORITHM_IDS = tuple(item["id"] for item in ALGORITHM_SPECS if item["trainable"])
ALL_ALGORITHM_IDS = tuple(item["id"] for item in ALGORITHM_SPECS)


def algorithm_catalog() -> list[dict[str, Any]]:
    return [dict(item) for item in ALGORITHM_SPECS]


def _state_key(state: tuple[int, ...]) -> str:
    return ",".join(str(value) for value in state)


def _new_values() -> list[float]:
    return [0.0 for _ in ACTIONS]


def _values(table: dict[str, list[float]], state: tuple[int, ...]) -> list[float]:
    return table.setdefault(_state_key(state), _new_values())


def _greedy_index(values: list[float], valid_mask: tuple[bool, ...], rng: random.Random) -> int:
    candidates = [index for index, valid in enumerate(valid_mask) if valid]
    if not candidates:
        return len(ACTIONS) // 2
    best = max(values[index] for index in candidates)
    ties = [index for index in candidates if abs(values[index] - best) < 1e-12]
    return rng.choice(ties)


def epsilon_greedy(
    values: list[float],
    valid_mask: tuple[bool, ...],
    epsilon: float,
    rng: random.Random,
) -> int:
    valid = [index for index, allowed in enumerate(valid_mask) if allowed]
    if not valid:
        return len(ACTIONS) // 2
    if rng.random() < epsilon:
        return rng.choice(valid)
    return _greedy_index(values, valid_mask, rng)


@dataclass
class TrainedPolicy:
    algorithm_id: str
    q_table: dict[str, list[float]]
    secondary_q_table: Optional[dict[str, list[float]]]
    seed: int
    hyperparameters: dict[str, float]

    def action(self, state: tuple[int, ...], valid_mask: tuple[bool, ...], rng: random.Random) -> int:
        primary = self.q_table.get(_state_key(state), _new_values())
        if self.secondary_q_table is None:
            combined = primary
        else:
            secondary = self.secondary_q_table.get(_state_key(state), _new_values())
            combined = [left + right for left, right in zip(primary, secondary)]
        return _greedy_index(combined, valid_mask, rng)

    def public_dict(self) -> dict[str, Any]:
        payload = {
            "algorithm_id": self.algorithm_id,
            "seed": self.seed,
            "hyperparameters": self.hyperparameters,
            "state_count": len(set(self.q_table) | set(self.secondary_q_table or {})),
            "action_count": len(ACTIONS),
            "q_table": self.q_table,
        }
        if self.secondary_q_table is not None:
            payload["secondary_q_table"] = self.secondary_q_table
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TrainedPolicy":
        return cls(
            algorithm_id=str(payload["algorithm_id"]),
            q_table={str(key): [float(value) for value in values] for key, values in payload["q_table"].items()},
            secondary_q_table={str(key): [float(value) for value in values] for key, values in payload.get("secondary_q_table", {}).items()} or None,
            seed=int(payload["seed"]),
            hyperparameters={str(key): float(value) for key, value in payload.get("hyperparameters", {}).items()},
        )


@dataclass(frozen=True)
class PIDPolicy:
    kp: float = 0.85
    ki: float = 0.06
    kd: float = 0.12
    soc_gain: float = 0.35

    def public_dict(self) -> dict[str, Any]:
        return {
            "algorithm_id": "pid",
            "controller": "PID",
            "hyperparameters": {"kp": self.kp, "ki": self.ki, "kd": self.kd, "soc_gain": self.soc_gain},
            "trained": False,
        }


@dataclass(frozen=True)
class ConfiguredBaselinePolicy:
    algorithm_id: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "algorithm_id": self.algorithm_id,
            "controller": "deterministic_site_sop_proxy",
            "trained": False,
            "future_test_rows_used": False,
        }


def _episode_epsilon(episode: int, episodes: int, start: float, end: float) -> float:
    if episodes <= 1:
        return end
    fraction = episode / (episodes - 1)
    return start * math.pow(end / start, fraction)


def train_tabular_policy(
    algorithm_id: str,
    records: list[EnergyRecord],
    parameters: EnvironmentParameters | PortOperationsParameters,
    *,
    episodes: int,
    horizon_steps: int,
    seed: int,
    learning_rate: float,
    discount_factor: float,
    epsilon_start: float,
    epsilon_end: float,
    progress: Callable[[int, dict[str, Any]], None],
    cancelled: Callable[[], bool],
    environment_type: str = "energy_storage",
) -> tuple[TrainedPolicy, list[dict[str, Any]]]:
    if algorithm_id not in RL_ALGORITHM_IDS:
        raise ValueError(f"unsupported trainable algorithm: {algorithm_id}")
    rng = random.Random(seed)
    if environment_type == "port_operations":
        if not isinstance(parameters, PortOperationsParameters):
            raise TypeError("port_operations requires PortOperationsParameters")
        environment: EnergySchedulingEnvironment | PortOperationsEnvironment = PortOperationsEnvironment(
            records,
            parameters,
            horizon_steps=horizon_steps,
            seed=seed,
            split_name="train",
            render_mode=None,
        )
    else:
        if not isinstance(parameters, EnvironmentParameters):
            raise TypeError("energy_storage requires EnvironmentParameters")
        environment = EnergySchedulingEnvironment(
            records,
            parameters,
            horizon_steps=horizon_steps,
            seed=seed,
            split_name="train",
            render_mode=None,
        )
    q_table: dict[str, list[float]] = {}
    secondary: Optional[dict[str, list[float]]] = {} if algorithm_id == "double_q_learning" else None
    curve: list[dict[str, Any]] = []
    reward_ema: Optional[float] = None
    for episode in range(episodes):
        if cancelled():
            raise InterruptedError("training cancelled")
        state = environment.reset()
        epsilon = _episode_epsilon(episode, episodes, epsilon_start, epsilon_end)
        action = epsilon_greedy(_values(q_table, state), environment.valid_action_mask(), epsilon, rng)
        total_reward = 0.0
        done = False
        while not done:
            next_state, reward, done, _ = environment.step(action)
            total_reward += reward
            next_mask = environment.valid_action_mask() if not done else tuple(True for _ in ACTIONS)
            next_action = 0 if done else epsilon_greedy(_values(q_table, next_state), next_mask, epsilon, rng)
            values = _values(q_table, state)
            if algorithm_id == "q_learning":
                target = reward if done else reward + discount_factor * max(
                    value for value, valid in zip(_values(q_table, next_state), next_mask) if valid
                )
                values[action] += learning_rate * (target - values[action])
            elif algorithm_id == "sarsa":
                target = reward if done else reward + discount_factor * _values(q_table, next_state)[next_action]
                values[action] += learning_rate * (target - values[action])
            elif algorithm_id == "expected_sarsa":
                if done:
                    target = reward
                else:
                    next_values = _values(q_table, next_state)
                    valid_indices = [index for index, valid in enumerate(next_mask) if valid]
                    greedy = _greedy_index(next_values, next_mask, rng)
                    expected = 0.0
                    for index in valid_indices:
                        probability = epsilon / len(valid_indices) + (1 - epsilon if index == greedy else 0.0)
                        expected += probability * next_values[index]
                    target = reward + discount_factor * expected
                values[action] += learning_rate * (target - values[action])
            else:
                assert secondary is not None
                if rng.random() < 0.5:
                    primary_values = _values(q_table, state)
                    next_primary = _values(q_table, next_state)
                    best = _greedy_index(next_primary, next_mask, rng)
                    estimate = _values(secondary, next_state)[best]
                    target = reward if done else reward + discount_factor * estimate
                    primary_values[action] += learning_rate * (target - primary_values[action])
                else:
                    secondary_values = _values(secondary, state)
                    next_secondary = _values(secondary, next_state)
                    best = _greedy_index(next_secondary, next_mask, rng)
                    estimate = _values(q_table, next_state)[best]
                    target = reward if done else reward + discount_factor * estimate
                    secondary_values[action] += learning_rate * (target - secondary_values[action])
            state = next_state
            action = next_action
        reward_ema = total_reward if reward_ema is None else reward_ema * 0.92 + total_reward * 0.08
        point = {
            "episode": episode + 1,
            "reward": round(total_reward, 6),
            "reward_ema": round(reward_ema, 6),
            "epsilon": round(epsilon, 6),
            "constraint_violations": environment.constraint_violations,
        }
        curve.append(point)
        progress(episode + 1, point)
    policy = TrainedPolicy(
        algorithm_id=algorithm_id,
        q_table=q_table,
        secondary_q_table=secondary,
        seed=seed,
        hyperparameters={
            "learning_rate": learning_rate,
            "discount_factor": discount_factor,
            "epsilon_start": epsilon_start,
            "epsilon_end": epsilon_end,
            "episodes": float(episodes),
            "horizon_steps": float(horizon_steps),
        },
    )
    return policy, curve


def policy_json(policy: TrainedPolicy) -> str:
    return json.dumps(policy.public_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pid_action(
    record: EnergyRecord,
    soc: float,
    parameters: EnvironmentParameters,
    controller: PIDPolicy,
    integral: float,
    previous_error: float,
) -> tuple[int, float, float]:
    peak_error = parameters.peak_target_kw - record.load_kw
    soc_error = 0.55 - soc
    normalized_error = peak_error / max(0.01, parameters.max_power_kw) + soc_error * controller.soc_gain
    integral = max(-4.0, min(4.0, integral + normalized_error))
    derivative = normalized_error - previous_error
    command = controller.kp * normalized_error + controller.ki * integral + controller.kd * derivative
    action = min(range(len(ACTIONS)), key=lambda index: abs(ACTIONS[index] - command))
    return action, integral, normalized_error


def _port_pid_action(
    environment: PortOperationsEnvironment,
    controller: PIDPolicy,
    integral: float,
    previous_error: float,
) -> tuple[int, float, float]:
    record = environment.records[environment.index]
    queue = max(0.0, record.anchored_vessels or 0.0) + max(0.0, record.slow_vessels or 0.0)
    target = max(1.0, environment.parameters.maximum_backlog * 0.20)
    normalized_error = (environment.backlog + queue * 0.25 - target) / target
    risk = environment.weather_risk(record)
    normalized_error -= risk * 1.6
    integral = max(-4.0, min(4.0, integral + normalized_error))
    derivative = normalized_error - previous_error
    command = controller.kp * normalized_error + controller.ki * integral + controller.kd * derivative
    target_factor = min(1.30, max(0.65, 1.0 + command * 0.18))
    action = min(
        range(len(PORT_ACTION_CAPACITY_FACTORS)),
        key=lambda index: abs(PORT_ACTION_CAPACITY_FACTORS[index] - target_factor),
    )
    valid_mask = environment.valid_action_mask()
    if not valid_mask[action]:
        allowed = [index for index, valid in enumerate(valid_mask) if valid]
        action = min(allowed, key=lambda index: abs(PORT_ACTION_CAPACITY_FACTORS[index] - target_factor))
    return action, integral, normalized_error


def _sop_rule_action(
    environment: EnergySchedulingEnvironment | PortOperationsEnvironment,
) -> int:
    valid_mask = environment.valid_action_mask()
    allowed = [index for index, valid in enumerate(valid_mask) if valid]
    if not allowed:
        return len(ACTIONS) // 2
    if isinstance(environment, PortOperationsEnvironment):
        record = environment.records[environment.index]
        queue = max(0.0, record.anchored_vessels or 0.0) + max(
            0.0, record.slow_vessels or 0.0
        )
        pressure = (
            environment.backlog + queue * 0.25
        ) / max(1.0, environment.parameters.maximum_backlog)
        desired = 4 if pressure >= 0.75 else 3 if pressure >= 0.45 else 2 if pressure >= 0.20 else 1
        return min(allowed, key=lambda index: abs(index - desired))
    record = environment.records[environment.index]
    tariff = tariff_for(record)
    soc = environment.soc
    target = environment.parameters.terminal_soc_target
    if tariff >= 0.25 and record.load_kw >= environment.parameters.peak_target_kw:
        desired = 0 if soc >= target + 0.08 else 1
    elif tariff <= 0.12 and soc < target + 0.12:
        desired = 4
    elif soc < target - 0.03:
        desired = 3
    else:
        desired = 2
    return min(allowed, key=lambda index: abs(index - desired))


def evaluate_policy(
    algorithm_id: str,
    policy: TrainedPolicy | PIDPolicy | ConfiguredBaselinePolicy,
    records: list[EnergyRecord],
    parameters: EnvironmentParameters | PortOperationsParameters,
    *,
    horizon_steps: int,
    seed: int,
    render: bool,
    environment_type: str = "energy_storage",
) -> dict[str, Any]:
    if environment_type == "port_operations":
        if not isinstance(parameters, PortOperationsParameters):
            raise TypeError("port_operations requires PortOperationsParameters")
        environment: EnergySchedulingEnvironment | PortOperationsEnvironment = PortOperationsEnvironment(
            records,
            parameters,
            horizon_steps=horizon_steps,
            seed=seed,
            split_name="test" if render else "validation",
            render_mode="trace" if render else None,
        )
    else:
        if not isinstance(parameters, EnvironmentParameters):
            raise TypeError("energy_storage requires EnvironmentParameters")
        environment = EnergySchedulingEnvironment(
            records,
            parameters,
            horizon_steps=horizon_steps,
            seed=seed,
            split_name="test" if render else "validation",
            render_mode="trace" if render else None,
        )
    max_start = len(records) - horizon_steps - 1
    starts = [0, max(0, max_start // 2), max(0, max_start)]
    episodes: list[dict[str, Any]] = []
    all_frames: list[dict[str, Any]] = []
    for evaluation_index, start in enumerate(starts):
        state = environment.reset(start_index=start)
        rng = random.Random(seed + evaluation_index * 997)
        total_reward = 0.0
        integral = 0.0
        previous_error = 0.0
        done = False
        while not done:
            if algorithm_id == "pid":
                assert isinstance(policy, PIDPolicy)
                if isinstance(environment, PortOperationsEnvironment):
                    action, integral, previous_error = _port_pid_action(
                        environment, policy, integral, previous_error
                    )
                else:
                    assert isinstance(parameters, EnvironmentParameters)
                    action, integral, previous_error = _pid_action(
                        environment.records[environment.index],
                        environment.soc,
                        parameters,
                        policy,
                        integral,
                        previous_error,
                    )
                    valid_mask = environment.valid_action_mask()
                    if not valid_mask[action]:
                        allowed = [index for index, valid in enumerate(valid_mask) if valid]
                        action = min(
                            allowed,
                            key=lambda index: abs(ACTIONS[index] - ACTIONS[action]),
                        )
            elif algorithm_id == "sop_rule":
                assert isinstance(policy, ConfiguredBaselinePolicy)
                action = _sop_rule_action(environment)
            else:
                assert isinstance(policy, TrainedPolicy)
                action = policy.action(state, environment.valid_action_mask(), rng)
            state, reward, done, _ = environment.step(action)
            total_reward += reward
        metrics = environment.episode_metrics(total_reward)
        metrics["evaluation_episode"] = evaluation_index + 1
        episodes.append(metrics)
        if render:
            all_frames.extend({**frame, "evaluation_episode": evaluation_index + 1} for frame in environment.frames)
    numeric_keys = (
        (
            "total_reward",
            "served_units",
            "average_backlog_units",
            "wait_proxy_hours",
            "capacity_utilization_percent",
            "constraint_violations",
            "terminal_backlog_units",
        )
        if environment_type == "port_operations"
        else (
            "total_reward",
            "total_cost",
            "total_grid_energy_cost",
            "total_degradation_cost",
            "baseline_cost",
            "cost_saving_percent",
            "peak_grid_kw",
            "baseline_peak_kw",
            "peak_reduction_percent",
            "carbon_kg",
            "constraint_violations",
            "terminal_soc",
        )
    )
    aggregate = {
        key: round(sum(float(item[key]) for item in episodes) / len(episodes), 6)
        for key in numeric_keys
    }
    if environment_type == "energy_storage":
        aggregate["terminal_soc_recovery_rate"] = round(
            sum(bool(item["terminal_soc_recovered"]) for item in episodes)
            / len(episodes),
            6,
        )
    if environment_type == "port_operations":
        aggregate["score"] = round(
            aggregate["total_reward"] - aggregate["constraint_violations"] * 20,
            6,
        )
        aggregate["metric_boundary"] = (
            "AIS fields are measured observations; served, backlog, wait and score are calibrated "
            "scenario outputs and are not terminal production KPIs."
        )
    else:
        aggregate["score"] = round(
            aggregate["total_reward"]
            - aggregate["constraint_violations"] * 20
            + aggregate["cost_saving_percent"] * 0.4
            + aggregate["peak_reduction_percent"] * 0.4,
            6,
        )
    return {
        "algorithm_id": algorithm_id,
        "metrics": aggregate,
        "episodes": episodes,
        "frames": all_frames if render else [],
        "rendering_performed": render,
        "render_split": "test" if render else None,
        "validation_split": not render,
        "environment_type": environment_type,
    }
