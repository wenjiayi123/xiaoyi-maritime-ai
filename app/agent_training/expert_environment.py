"""Separate bounded environment for expert-facing tool-use research.

This revision is an engineering environment, not a frozen training protocol.
The policy chooses among 13 displayed tools. Input extraction, numerical
assessment, clarification replies in replay, and report rendering are explicit
program components. Hidden future events and reference actions never enter the
policy prompt. No model is imported or loaded by this module.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import math
from urllib.error import HTTPError

from .expert_contracts import assess_energy_option
from .expert_energy import ExpertEnergyBackend, check_receipt, digest

REVISION = "expert-energy-environment.v1-engineering"
LETTERS = tuple("ABCDEFGHIJKLM")
MISSING_FIELDS = ("baseline_green_preference", "carbon_price_cny_per_ton", "requirements")


@dataclass
class ExpertTask:
    case_id: str
    goal: str
    candidate_green_preferences: tuple[float, float]
    baseline_green_preference: float | None = None
    carbon_price_cny_per_ton: float | None = None
    requirements: dict | None = None
    # Only a replay/engineering caller supplies these. No real user response
    # may be manufactured in the live UI; it must use an actual input channel.
    scripted_replies: dict = field(default_factory=dict)
    lose_response_candidates: tuple[int, ...] = ()
    changed_requirements: dict | None = None
    change_after_calculations: int = 1
    max_steps: int = 18

    def __post_init__(self):
        if len(self.candidate_green_preferences) != 2:
            raise ValueError("exactly two registered candidates required")
        if any(
            isinstance(v, bool) or not isinstance(v, (float, int)) or not 0 <= v <= 1
            for v in self.candidate_green_preferences
        ):
            raise ValueError("invalid candidate preference")
        if self.max_steps < 1 or self.change_after_calculations < 1:
            raise ValueError("positive limits required")
        if set(self.scripted_replies) - set(MISSING_FIELDS):
            raise ValueError("unknown clarification field")
        values = {key: getattr(self, key) for key in MISSING_FIELDS}
        for source in [values, self.scripted_replies]:
            for key, value in source.items():
                if value is None:
                    continue
                if key == "requirements":
                    _validate_requirements(value)
                elif (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or not 0 <= value <= (1 if key == "baseline_green_preference" else 5000)
                ):
                    raise ValueError("invalid confirmed parameter: " + key)
        if self.changed_requirements is not None:
            _validate_requirements(self.changed_requirements)


def _validate_requirements(requirements):
    limits = {"min_carbon_reduction_pct": 100, "max_cost_cny": float("inf"), "min_service_pct": 100}
    if not isinstance(requirements, dict) or not requirements or set(requirements) - set(limits):
        raise ValueError("explicit supported requirements required")
    for key, value in requirements.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= limits[key]
        ):
            raise ValueError("invalid requirement: " + key)


class RecordedEnergyProvider:
    """Exact native-receipt replay; unrecorded parameters have no fallback.

    Reusing one physical trial under different language conditions does not
    create new independent physical scenarios. Caller must report both counts.
    """

    mode = "recorded_native_evidence_replay"

    def __init__(self, receipts):
        self.catalog = {}
        self.receipts, self.pending = {}, {}
        self.context = None
        contexts = []
        for receipt in receipts:
            check_receipt(receipt, receipt["parameters"])
            parameters = receipt["parameters"]
            key = self.key(parameters)
            contexts.append(receipt["source_context"])
            if key in self.catalog and self.catalog[key]["alternatives"] != receipt["alternatives"]:
                raise ValueError("ambiguous recorded evidence for identical parameters")
            self.catalog[key] = deepcopy(receipt)
        if not contexts or any(c != contexts[0] for c in contexts):
            raise ValueError("a replay must use one frozen source version")
        self.frozen_context = deepcopy(contexts[0])

    @staticmethod
    def key(parameters):
        return tuple(
            parameters[k] for k in ("baseline_green_preference", "green_preference", "carbon_price_cny_per_ton")
        )

    def pending_index(self):
        return next(iter(self.pending), None)

    def read_context(self):
        self.context = deepcopy(self.frozen_context)
        return deepcopy(self.context)

    def calculate(self, index, parameters, *, lose_response=False):
        if self.pending:
            raise ValueError("pending receipt requires explicit readback")
        if self.context is None:
            raise ValueError("context not read")
        if self.key(parameters) not in self.catalog:
            raise ValueError("no native evidence for these parameters")
        receipt = deepcopy(self.catalog[self.key(parameters)])
        if lose_response:
            self.pending[index] = receipt
            return {"response_received": False, "injected_response_loss": True}
        self.receipts[index] = receipt
        return {"response_received": True, "receipt_sha256": receipt["receipt_sha256"]}

    def recover(self, index):
        if index not in self.pending:
            raise ValueError("no pending receipt")
        self.receipts[index] = self.pending.pop(index)
        return {"new_calculation_performed": False, "receipt_sha256": self.receipts[index]["receipt_sha256"]}

    def verify(self, index, requirements):
        if index not in self.receipts or self.pending:
            raise ValueError("completed result required")
        receipt = self.receipts[index]
        facts = check_receipt(receipt, receipt["parameters"])
        assessment = assess_energy_option(*facts, requirements)
        issues = [issue for fact in facts for issue in fact.get("issues", [])]
        if not facts[0].get("scenario_id") or facts[0].get("scenario_id") != facts[1].get("scenario_id"):
            issues.append("scenario_identity_missing_or_inconsistent")
        if issues:
            assessment["status"] = "needs_evidence"
            assessment["issues"].extend(issues)
        return {
            "assessment": assessment,
            "alternatives": facts,
            "receipt_sha256": receipt["receipt_sha256"],
            "provider_mode": self.mode,
        }


class NativeEnergyProvider:
    """Same explicit operations backed by real API calls and durable journals."""

    mode = "actual_local_offline_energy_api"

    def __init__(self, folder, base="http://127.0.0.1:18810"):
        from pathlib import Path

        self.folder = Path(folder)
        self.master = ExpertEnergyBackend(self.folder / "context", base)
        self.trials = [ExpertEnergyBackend(self.folder / f"candidate-{i}", base) for i in range(2)]

    def read_context(self):
        return self.master.read_context()

    def pending_index(self):
        return next((i for i, tool in enumerate(self.trials) if tool.state["pending"]), None)

    def calculate(self, index, parameters, *, lose_response=False):
        if any(tool.state["pending"] for tool in self.trials):
            raise ValueError("pending receipt requires explicit readback")
        context = self.master.state["context"]
        if context is None:
            raise ValueError("context not read")
        tool = self.trials[index]
        tool.state["context"] = deepcopy(context)
        request_id = (
            "expert-env-"
            + digest(
                {"folder": str(tool.folder.resolve()), "parameters": parameters, "source": context["source_version"]}
            )[:48]
        )
        response = tool.compare(parameters, request_id, withhold_response=lose_response)
        return {
            "response_received": not lose_response,
            "injected_response_loss": lose_response,
            "receipt_sha256": response.get("receipt", {}).get("receipt_sha256"),
        }

    def recover(self, index):
        result = self.trials[index].recover()
        return {"new_calculation_performed": False, "receipt_sha256": result["receipt"]["receipt_sha256"]}

    def verify(self, index, requirements):
        return {**self.trials[index].verify(requirements), "provider_mode": self.mode}


class ExpertEnvironment:
    def __init__(self, task, provider):
        self.task, self.provider = deepcopy(task), provider
        self.known = {key: deepcopy(getattr(task, key)) for key in MISSING_FIELDS}
        self.goal_version = 1
        self.context_read = False
        self.pending = None
        self.calculated = set()
        self.verifications = {}
        self.loss_injected = set()
        self.change_delivered = False
        self.calculation_count = 0
        self.attempted_candidates = set()
        self.done = self.success = self.business_complete = False
        self.clarification_correct = False
        self.outcome = None
        self.feedback = "任务已登记；数值、单位和目标字段由明确的结构化任务提供。"
        self.steps = []
        self.report = None

    def ready(self):
        return all(self.known[k] is not None for k in MISSING_FIELDS)

    def menu(self):
        labels = [
            "user.ask(基准绿色偏好)",
            "user.ask(碳价与单位)",
            "user.ask(业务约束)",
            "energy.read_context",
            "energy.compare(候选1)",
            "energy.compare(候选2)",
            "energy.receipt_readback",
            "evidence.verify(候选1,当前目标)",
            "evidence.verify(候选2,当前目标)",
            "report.recommend(候选1)",
            "report.recommend(候选2)",
            "report.no_registered_candidate_meets_goal",
            "report.insufficient_evidence",
        ]
        return dict(zip(LETTERS, labels))

    def observation(self):
        # No case id, reference action, future reply, loss schedule or future
        # target values. Only previously observed facts are presented.
        return {
            "goal": self.task.goal,
            "known": deepcopy(self.known),
            "candidates": list(self.task.candidate_green_preferences),
            "goal_version": self.goal_version,
            "context_read": self.context_read,
            "pending_candidate": self.pending,
            "calculated": sorted(self.calculated),
            "verified": {
                i: {"goal_version": value["goal_version"], "assessment": deepcopy(value["result"]["assessment"])}
                for i, value in self.verifications.items()
            },
            "feedback": self.feedback,
        }

    def prompt(self):
        state = self.observation()
        return (
            "任务："
            + state.pop("goal")
            + "\n当前已知事实（以当前目标版本为准）："
            + json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n工具："
            + "；".join(k + "=" + v for k, v in self.menu().items())
            + "\n只选择一个工具字母。服务指标指模拟窗口箱量完成率，不是现场SLA。"
        )

    def current_verifications(self):
        return {i: row["result"] for i, row in self.verifications.items() if row["goal_version"] == self.goal_version}

    def finish(self, label):
        current = self.current_verifications()
        statuses = [current[i]["assessment"]["status"] for i in range(2)] if set(current) == {0, 1} else []
        allowed = self.ready() and self.pending is None and len(statuses) == 2
        valid, outcome = False, "incorrect_report"
        if label in {"J", "K"}:
            index = 0 if label == "J" else 1
            valid = allowed and statuses[index] == "meets_registered_requirements"
            outcome = "verified_candidate_recommended" if valid else outcome
            self.business_complete = bool(valid)
        elif label == "L":
            valid = allowed and all(s == "does_not_meet_registered_requirements" for s in statuses)
            outcome = "no_registered_candidate_meets_requirements" if valid else outcome
        else:
            valid = allowed and "needs_evidence" in statuses and "meets_registered_requirements" not in statuses
            outcome = "evidence_gap_reported" if valid else outcome
        self.done, self.success, self.outcome = True, bool(valid), outcome
        self.report = {
            "outcome": outcome,
            "decision_correct": bool(valid),
            "business_complete": self.business_complete,
            "goal_version": self.goal_version,
            "requirements": deepcopy(self.known["requirements"]),
            "recommendation_index": (0 if label == "J" else 1) if label in {"J", "K"} and valid else None,
            "verified_results": deepcopy(current),
            "candidate_count": 2,
            "infeasibility_scope": "only the two registered candidates, not all possible port plans",
            "provider_mode": self.provider.mode,
            "report_producer": "deterministic renderer of checked facts",
        }
        return 1.0 if valid else -1.0

    def step(self, label):
        if self.done:
            raise ValueError("episode already terminated")
        before = self.observation()
        reward, event, error = -0.02, None, None
        try:
            if label not in LETTERS:
                raise ValueError("unknown tool label")
            if label in {"A", "B", "C"}:
                key = MISSING_FIELDS[LETTERS.index(label)]
                if self.known[key] is not None:
                    raise ValueError("requested field already supplied")
                self.clarification_correct = True
                if key not in self.task.scripted_replies or self.task.scripted_replies[key] is None:
                    self.done, self.outcome = True, "awaiting_user_clarification"
                    reward = 0.25
                    self.feedback = "已向用户询问缺项，等待真实答复；尚未完成业务。"
                else:
                    self.known[key] = deepcopy(self.task.scripted_replies[key])
                    event = {"kind": "scripted_user_reply", "field": key, "value": deepcopy(self.known[key])}
                    self.feedback = "已收到工程回放中的用户补充：" + key
            elif label == "D":
                context = self.provider.read_context()
                self.context_read = True
                self.feedback = "已读取计算来源版本：" + context["source_version"][:12]
            elif label in {"E", "F"}:
                if not self.ready() or not self.context_read or self.pending is not None:
                    raise ValueError("missing confirmed fields/context or unresolved pending result")
                index = 0 if label == "E" else 1
                parameters = {
                    "baseline_green_preference": self.known["baseline_green_preference"],
                    "green_preference": self.task.candidate_green_preferences[index],
                    "carbon_price_cny_per_ton": self.known["carbon_price_cny_per_ton"],
                }
                lose = index in self.task.lose_response_candidates and index not in self.loss_injected
                result = self.provider.calculate(index, parameters, lose_response=lose)
                self.verifications.pop(index, None)
                self.attempted_candidates.add(index)
                self.calculation_count = len(self.attempted_candidates)
                if not result["response_received"]:
                    self.loss_injected.add(index)
                    self.pending = index
                    self.feedback = "候选" + str(index + 1) + "请求已发出，响应未收到；结果尚未确认。"
                else:
                    self.calculated.add(index)
                    self.feedback = "候选" + str(index + 1) + "已收到计算回执。"
            elif label == "G":
                if self.pending is None:
                    raise ValueError("no unresolved receipt")
                self.provider.recover(self.pending)
                self.calculated.add(self.pending)
                self.pending = None
                self.feedback = "已读回原计算回执，没有重新计算。"
            elif label in {"H", "I"}:
                index = 0 if label == "H" else 1
                if not self.ready() or index not in self.calculated or self.pending is not None:
                    raise ValueError("completed calculation and current requirements required")
                result = self.provider.verify(index, self.known["requirements"])
                self.verifications[index] = {"goal_version": self.goal_version, "result": result}
                self.feedback = "候选" + str(index + 1) + "核验：" + result["assessment"]["status"]
            else:
                reward = self.finish(label)
                self.feedback = self.outcome
        except (ValueError, RuntimeError, KeyError, OSError) as exc:
            reward = -0.2
            error = {"type": type(exc).__name__, "message": str(exc)}
            self.feedback = "工具未完成：" + str(exc)
            # Genuine transport errors can leave a durable pending intent even
            # when calculate() never returned. Expose that fact to the policy.
            self.pending = self.provider.pending_index()
            if self.pending is not None:
                self.attempted_candidates.add(self.pending)
                self.calculation_count = len(self.attempted_candidates)
            if (isinstance(exc, HTTPError) and exc.code == 409) or "source changed" in str(exc):
                self.context_read = False
                self.calculated.clear()
                self.verifications.clear()
        if (
            not self.done
            and not self.change_delivered
            and self.task.changed_requirements is not None
            and self.calculation_count >= self.task.change_after_calculations
        ):
            self.known["requirements"] = deepcopy(self.task.changed_requirements)
            self.goal_version += 1
            self.change_delivered = True
            event = {
                "kind": "scripted_goal_change",
                "requirements": deepcopy(self.known["requirements"]),
                "goal_version": self.goal_version,
            }
            self.feedback += " 用户在工程情景中更新了业务约束，请按当前目标核验。"
        if not self.done and len(self.steps) + 1 >= self.task.max_steps:
            self.done, self.outcome, reward = True, "step_limit", -1.0
        row = {
            "label": label,
            "tool": self.menu().get(label),
            "before": before,
            "after": self.observation(),
            "reward": reward,
            "event": event,
            "error": error,
            "done": self.done,
            "decision_correct": self.success,
            "business_complete": self.business_complete,
            "clarification_correct": self.clarification_correct,
            "outcome": self.outcome,
            "environment_revision": REVISION,
            "provider_mode": self.provider.mode,
        }
        self.steps.append(deepcopy(row))
        return row


def reference_action(env):
    """Engineering oracle / potential SFT demonstrator; never model fallback.

    Uses only the visible current observation, not hidden future events or the
    evidence catalog. Production callers must identify it as a rule policy.
    """
    state = env.observation()
    for label, key in zip("ABC", MISSING_FIELDS):
        if state["known"][key] is None:
            return label
    if state["pending_candidate"] is not None:
        return "G"
    if not state["context_read"]:
        return "D"
    for index, label in enumerate("EF"):
        if index not in state["calculated"]:
            return label
    for index, label in enumerate("HI"):
        entry = state["verified"].get(index)
        if not entry or entry["goal_version"] != state["goal_version"]:
            return label
    statuses = [state["verified"][i]["assessment"]["status"] for i in range(2)]
    for i, label in enumerate("JK"):
        if statuses[i] == "meets_registered_requirements":
            return label
    return "M" if "needs_evidence" in statuses else "L"
