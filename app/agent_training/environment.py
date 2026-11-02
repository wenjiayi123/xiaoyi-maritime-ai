"""Resettable, bounded tool environment shared by all four comparison groups.

This is an explicit synthetic training environment, not a live-port simulator.
The live executor uses the same model-selected action contracts separately.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import random
from typing import Any


FAMILIES = (
    "port_read",
    "energy_compare",
    "port_scenario",
    "traffic_read",
    "joint",
    "read_recovery",
    "write_recovery",
    "clock_restore",
)
FAMILY_NAMES = dict(
    zip(
        FAMILIES,
        (
            "港口查询",
            "能碳参数比较",
            "港口情景",
            "交通查询",
            "跨系统联合",
            "读取故障恢复",
            "回执丢失恢复",
            "模拟状态恢复",
        ),
    )
)
REVISION = "xiaoyi-agent-env.v2-readable-state"
LETTERS = "ABCDEFGHIJKLM"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@dataclass(frozen=True)
class TaskSpec:
    case_id: str
    split: str
    family: str
    seed: int
    green: float = 0.82
    carbon: float = 85.0
    baseline: float = 0.5
    scenario: str = "high_density_berthing"
    fault: str = "none"
    max_steps: int = 14

    def public(self):
        return asdict(self)

    def goal(self):
        goals = {
            "port_read": "读取港口状态，核验后交付报告。",
            "traffic_read": "读取交通状态，核验后交付报告。",
            "energy_compare": "读取能源状态并比较能碳方案，核验后交付报告。",
            "port_scenario": "读取港口状态并评估靠泊情景，核验后交付报告。",
            "joint": "读取港口、能源、交通，完成港口情景与能碳比较，核验后交付联合报告。",
            "read_recovery": "读取能源并完成能碳比较；读取失败后恢复继续，核验后交付报告。",
            "write_recovery": "读取能源并完成能碳比较；响应丢失时先读回回执，核验后交付报告。",
            "clock_restore": "读取能源，暂停模拟时钟，恢复原状态，核验后交付报告。",
        }
        extra = ""
        if self.family in {"energy_compare", "joint", "read_recovery", "write_recovery"}:
            extra += f" 基准={self.baseline:g}，绿色偏好={self.green:g}，碳价={self.carbon:g}。"
        if self.family in {"port_scenario", "joint"}:
            extra += f" 情景={self.scenario}。"
        return goals[self.family] + extra


def make_task(split, family, index):
    offsets = {"train": 110000, "validation": 220000, "test": 330000, "acceptance": 440000}
    seed = offsets[split] + FAMILIES.index(family) * 1000 + index
    rng = random.Random(seed)
    grids = {
        "train": [0.55, 0.65, 0.75, 0.85],
        "validation": [0.60, 0.70, 0.80],
        "test": [0.57, 0.67, 0.77, 0.87],
        "acceptance": [0.82],
    }
    return TaskSpec(
        f"{split}-{family}-{index:03d}",
        split,
        family,
        seed,
        green=rng.choice(grids[split]),
        carbon=rng.choice([60, 85, 110, 135]) + (3 if split == "test" else 0),
        scenario=rng.choice(["high_density_berthing", "channel_congestion", "equipment_degradation"]),
        fault={"read_recovery": "transient_read", "write_recovery": "lost_response"}.get(family, "none"),
    )


def requirements(task):
    f = task.family
    reads = {
        "port_read": ["port"],
        "traffic_read": ["traffic"],
        "energy_compare": ["energy"],
        "port_scenario": ["port"],
        "joint": ["port", "energy", "traffic"],
        "read_recovery": ["energy"],
        "write_recovery": ["energy"],
        "clock_restore": ["energy"],
    }[f]
    return {
        "reads": reads,
        "energy": f in {"energy_compare", "joint", "read_recovery", "write_recovery"},
        "port": f in {"port_scenario", "joint"},
        "restore": f == "clock_restore",
    }


class TaskEnvironment:
    """No action is auto-selected. Preconditions and the final grader are deterministic."""

    def __init__(self, task: TaskSpec):
        self.task = task
        self.required = requirements(task)
        self.reads = set()
        self.receipts = {}
        self.verified = False
        self.paused = False
        self.ever_paused = False
        self.restored = False
        self.uncertain = False
        self.diagnosed = False
        self.fault_triggered = False
        self.last = "none"
        self.steps = []
        self.done = False
        self.success = False
        self.report = None
        self.params_attempts = 0
        self.params_correct = 0
        self.rng = random.Random(task.seed)
        self.actions = self._actions()

    def _actions(self):
        t = self.task
        wrong_green = round(max(0.05, min(0.95, t.green - 0.20)), 2)
        correct = {
            "tool": "energy.compare",
            "arguments": {
                "baseline_green_preference": t.baseline,
                "green_preference": t.green,
                "carbon_price_cny_per_ton": t.carbon,
            },
        }
        wrong = {"tool": "energy.compare", "arguments": {**correct["arguments"], "green_preference": wrong_green}}
        pair = [correct, wrong]
        self.rng.shuffle(pair)
        return {
            "A": {"tool": "port.read", "arguments": {}},
            "B": {"tool": "energy.read", "arguments": {}},
            "C": {"tool": "traffic.read", "arguments": {}},
            "D": {"tool": "port.evaluate", "arguments": {"scenario": t.scenario, "horizon_min": 60, "step_min": 15}},
            "E": pair[0],
            "F": pair[1],
            "G": {"tool": "energy.pause", "arguments": {}},
            "H": {"tool": "energy.restore", "arguments": {}},
            "I": {"tool": "execution.verify", "arguments": {}},
            "J": {"tool": "artifact.report", "arguments": {}},
            "K": {"tool": "execution.diagnose", "arguments": {}},
            "L": {
                "tool": "energy.compare",
                "arguments": {**correct["arguments"], "carbon_price_cny_per_ton": t.carbon + 25},
            },
            "M": {"tool": "task.ask", "arguments": {}},
        }

    def observation(self):
        return {
            "goal": self.task.goal(),
            "reads": sorted(self.reads),
            "completed": sorted(self.receipts),
            "verified": self.verified,
            "clock": "paused" if self.paused else "running",
            "ever_paused": self.ever_paused,
            "restored": self.restored,
            "uncertain_write": self.uncertain,
            "last": self.last,
            "remaining_steps": self.task.max_steps - len(self.steps),
        }

    def prompt(self):
        labels = []
        names = {
            "port.read": "读取港口",
            "energy.read": "读取能源",
            "traffic.read": "读取交通",
            "energy.pause": "暂停模拟时钟",
            "energy.restore": "恢复原时钟",
            "execution.verify": "核验全部结果",
            "artifact.report": "交付报告",
            "execution.diagnose": "诊断接口",
            "task.ask": "询问用户",
        }
        for label, a in self.actions.items():
            args = a["arguments"]
            if a["tool"] == "energy.compare":
                text = f"能碳比较(偏好{args['green_preference']:g},碳价{args['carbon_price_cny_per_ton']:g})"
            elif a["tool"] == "port.evaluate":
                text = f"港口评估({args['scenario']})"
            else:
                text = names[a["tool"]]
            labels.append(label + "=" + text)
        done = [{"port": "港口读取", "energy": "能源读取", "traffic": "交通读取"}[r] for r in sorted(self.reads)]
        done += [{"port": "港口情景评估", "energy": "能碳参数比较"}[r] for r in sorted(self.receipts)]
        if self.ever_paused:
            done.append("暂停模拟时钟")
        if self.restored:
            done.append("恢复原时钟")
        if self.verified:
            done.append("全部结果核验")
        state = "已完成：" + ("、".join(done) or "无") + "。"
        state += "当前时钟：" + ("暂停" if self.paused else "运行") + "。"
        state += "结果核验：" + ("已通过" if self.verified else "尚未通过") + "。"
        state += "执行结果不明：" + ("是，需读回回执" if self.uncertain else "否") + "。"
        state += f"最近反馈：{self.last}。剩余步数{self.task.max_steps - len(self.steps)}。"
        return "任务：" + self.task.goal() + "\n" + state + "\n工具：" + ";".join(labels) + "\n下一步只输出一个字母："

    def checks(self):
        r = self.required
        e = self.receipts.get("energy", {})
        p = self.receipts.get("port", {})
        return {
            "required_observations": set(r["reads"]) <= self.reads,
            "energy_parameters": not r["energy"]
            or (e.get("green") == self.task.green and e.get("carbon") == self.task.carbon),
            "port_scenario": not r["port"] or p.get("scenario") == self.task.scenario,
            "restoration": not r["restore"] or (self.ever_paused and self.restored and not self.paused),
            "no_uncertain_write": not self.uncertain,
            "verified": self.verified,
        }

    def _potential(self):
        checks = self.checks()
        return sum(float(checks[k]) for k in checks) / len(checks)

    def step(self, label):
        if self.done:
            raise RuntimeError("episode already ended")
        if label not in self.actions:
            raise ValueError("unknown action")
        before = self.observation()
        previous = self._potential()
        a = self.actions[label]
        tool, params = a["tool"], a["arguments"]
        ok = True
        result = {}
        previous_facts = (
            tuple(sorted(self.reads)),
            digest(self.receipts),
            self.verified,
            self.paused,
            self.restored,
            self.uncertain,
        )
        if tool.endswith(".read"):
            target = tool.split(".")[0]
            if target == "energy" and self.task.fault == "transient_read" and not self.fault_triggered:
                self.fault_triggered = True
                self.last = "read_timeout: safe to retry read; diagnose also available"
                ok = False
            else:
                self.reads.add(target)
                result = {
                    "source": "synthetic_resettable_environment",
                    "target": target,
                    "case": self.task.case_id,
                    "production_authority": False,
                    "source_hash": digest({"seed": self.task.seed, "target": target}),
                }
                self.last = "read_ok:" + target
        elif tool == "energy.compare":
            self.params_attempts += 1
            valid = (
                params["green_preference"] == self.task.green and params["carbon_price_cny_per_ton"] == self.task.carbon
            )
            if "energy" not in self.reads:
                self.last = "missing_energy_observation"
                ok = False
            elif self.uncertain:
                self.last = "previous_write_unknown: verify receipt before retry"
                ok = False
            elif not valid:
                self.last = "parameter_mismatch: use requested green and carbon"
                ok = False
            else:
                self.params_correct += 1
                result = {
                    "green": params["green_preference"],
                    "carbon": params["carbon_price_cny_per_ton"],
                    "baseline": self.task.baseline,
                    "source": "synthetic_parameter_receipt",
                    "request_id": self.task.case_id + "-energy",
                }
                self.receipts["energy"] = result
                self.verified = False
                if self.task.fault == "lost_response" and not self.fault_triggered:
                    self.fault_triggered = True
                    self.uncertain = True
                    self.last = "response_lost: result unknown; read back receipt with execution.verify"
                    result = {"response_received": False}
                    ok = False
                else:
                    self.last = "energy_compare_ok"
        elif tool == "port.evaluate":
            if "port" not in self.reads:
                self.last = "missing_port_observation"
                ok = False
            else:
                result = {"scenario": params["scenario"], "source": "synthetic_parameter_receipt"}
                self.receipts["port"] = result
                self.verified = False
                self.last = "port_evaluate_ok"
        elif tool == "energy.pause":
            if "energy" not in self.reads:
                self.last = "missing_energy_observation"
                ok = False
            elif not self.required["restore"]:
                self.last = "pause_not_requested"
                ok = False
            elif self.paused:
                self.last = "already_paused"
                ok = False
            else:
                self.paused = True
                self.ever_paused = True
                self.restored = False
                self.verified = False
                self.last = "paused_restore_required"
        elif tool == "energy.restore":
            if not self.paused:
                self.last = "no_owned_change_to_restore"
                ok = False
            else:
                self.paused = False
                self.restored = True
                self.verified = False
                self.last = "restored_readback_required"
        elif tool == "execution.verify":
            self.uncertain = False
            self.verified = True
            if not all(self.checks().values()):
                self.verified = False
                self.last = "verification_incomplete"
                ok = False
            else:
                self.last = "all_receipts_verified"
                result = {"checks": self.checks()}
        elif tool == "execution.diagnose":
            self.diagnosed = True
            self.last = "diagnosis: reads may retry; unknown writes require receipt verification"
            result = {"read_retry_allowed": True, "write_retry_without_verification": False}
        elif tool == "task.ask":
            self.last = "user: parameters already supplied; continue within simulation"
            result = {"answer": "already_specified"}
        elif tool == "artifact.report":
            if all(self.checks().values()):
                self.success = True
                self.done = True
                self.last = "completed"
                self.report = {
                    "case_id": self.task.case_id,
                    "goal": self.task.goal(),
                    "receipts": self.receipts,
                    "checks": self.checks(),
                    "environment": "synthetic_training",
                    "production_authority": False,
                }
                result = {"report_sha256": digest(self.report)}
            else:
                self.last = "report_rejected: missing evidence, verification or restoration"
                ok = False
        facts = (
            tuple(sorted(self.reads)),
            digest(self.receipts),
            self.verified,
            self.paused,
            self.restored,
            self.uncertain,
        )
        reward = 2 * (self._potential() - previous) - 0.02
        if not ok:
            reward -= 0.15
        if facts == previous_facts:
            reward -= 0.05
        if self.success:
            reward += 3
        if len(self.steps) + 1 >= self.task.max_steps and not self.done:
            self.done = True
            reward -= 1
        transition = {
            "step": len(self.steps) + 1,
            "observation": before,
            "choice": label,
            "action": a,
            "ok": ok,
            "result": result,
            "feedback": self.last,
            "reward": round(reward, 6),
            "after": self.observation(),
            "model_action": True,
            "environment_revision": REVISION,
        }
        self.steps.append(transition)
        return transition

    def outcome(self):
        return {
            "case_id": self.task.case_id,
            "family": self.task.family,
            "split": self.task.split,
            "success": self.success,
            "steps": len(self.steps),
            "reward": sum(s["reward"] for s in self.steps),
            "parameter_attempts": self.params_attempts,
            "parameter_correct": self.params_correct,
            "errors": sum(not s["ok"] for s in self.steps),
            "fault_injected": self.fault_triggered,
            "recovered": self.fault_triggered and self.success,
            "checks": self.checks(),
            "trajectory_sha256": digest(self.steps),
            "source": "synthetic_training_environment",
        }


def reference_action(env):
    """Competent deterministic baseline and SFT demonstrator, not used by learned policies."""
    if env.uncertain:
        return "I"
    for target in env.required["reads"]:
        if target not in env.reads:
            return {"port": "A", "energy": "B", "traffic": "C"}[target]
    if env.required["port"] and "port" not in env.receipts:
        return "D"
    if env.required["energy"] and "energy" not in env.receipts:
        return next(
            k
            for k, a in env.actions.items()
            if a["tool"] == "energy.compare"
            and a["arguments"]["green_preference"] == env.task.green
            and a["arguments"]["carbon_price_cny_per_ton"] == env.task.carbon
        )
    if env.required["restore"]:
        if not env.ever_paused:
            return "G"
        if env.paused:
            return "H"
    if not env.verified:
        return "I"
    return "J"


def run_reference(task):
    env = TaskEnvironment(task)
    while not env.done:
        transition = env.step(reference_action(env))
        transition["model_action"] = False
        transition["origin"] = "deterministic_reference"
    return env
