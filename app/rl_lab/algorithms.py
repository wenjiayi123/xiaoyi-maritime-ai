from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from typing import Any, Callable, Optional

from app.rl_lab.datasets import EnergyRecord
from app.rl_lab.environment import ACTIONS, EnergySchedulingEnvironment, EnvironmentParameters


ALGORITHM_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "q_learning",
        "label": "Q-learning",
        "family": "reinforcement_learning",
        "type": "off_policy_td_control",
        "trainable": True,
        "description": "离策略时序差分控制，更新目标使用下一状态最大动作价值。",
    },
    {
        "id": "sarsa",
        "label": "SARSA",
        "family": "reinforcement_learning",
        "type": "on_policy_td_control",
        "trainable": True,
        "description": "同策略时序差分控制，训练目标跟随实际探索动作。",
    },
    {
        "id": "expected_sarsa",
        "label": "Expected SARSA",
        "family": "reinforcement_learning",
        "type": "expected_on_policy_td_control",
        "trainable": True,
        "description": "用 epsilon-greedy 策略下的期望动作价值降低更新方差。",
    },
    {
        "id": "double_q_learning",
        "label": "Double Q-learning",
        "family": "reinforcement_learning",
        "type": "double_estimator_off_policy_td",
        "trainable": True,
        "description": "双价值表解耦动作选择与评估，缓解最大化偏差。",
    },
    {
        "id": "pid",
        "label": "PID 控制基线",
        "family": "control_theory",
        "type": "proportional_integral_derivative_controller",
        "trainable": False,
        "description": "控制理论基线，用峰值目标、SOC误差和积分/微分项生成储能动作。",
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


def _episode_epsilon(episode: int, episodes: int, start: float, end: float) -> float:
    if episodes <= 1:
        return end
    fraction = episode / (episodes - 1)
    return start * math.pow(end / start, fraction)


def train_tabular_policy(
    algorithm_id: str,
    records: list[EnergyRecord],
    parameters: EnvironmentParameters,
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
) -> tuple[TrainedPolicy, list[dict[str, Any]]]:
    if algorithm_id not in RL_ALGORITHM_IDS:
        raise ValueError(f"unsupported trainable algorithm: {algorithm_id}")
    rng = random.Random(seed)
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


def evaluate_policy(
    algorithm_id: str,
    policy: TrainedPolicy | PIDPolicy,
    records: list[EnergyRecord],
    parameters: EnvironmentParameters,
    *,
    horizon_steps: int,
    seed: int,
    render: bool,
) -> dict[str, Any]:
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
                action, integral, previous_error = _pid_action(
                    environment.records[environment.index],
                    environment.soc,
                    parameters,
                    policy,
                    integral,
                    previous_error,
                )
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
        "total_reward",
        "total_cost",
        "baseline_cost",
        "cost_saving_percent",
        "peak_grid_kw",
        "baseline_peak_kw",
        "peak_reduction_percent",
        "carbon_kg",
        "constraint_violations",
        "terminal_soc",
    )
    aggregate = {
        key: round(sum(float(item[key]) for item in episodes) / len(episodes), 6)
        for key in numeric_keys
    }
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
    }
