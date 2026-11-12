"""Trace capture and offline audit for expert tasks; never chooses model actions."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
from urllib.error import HTTPError, URLError

from app.agent_training.expert_energy import check_context, check_receipt, digest
from app.agent_training.expert_environment import ExpertEnvironment, ExpertTask, RecordedEnergyProvider
from scripts.prepare_agent_expert_training import read, save, sha


def canonical(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def validate_decision(response, group, fingerprint):
    p = response.get("probabilities", [])
    if (
        response.get("group") != group
        or response.get("adapter_sha256") != fingerprint
        or len(p) != 13
        or any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in p)
        or not math.isclose(sum(p), 1.0, abs_tol=2e-6)
        or response.get("choice") != "ABCDEFGHIJKLM"[max(range(13), key=lambda i: p[i])]
        or response.get("decision_mode") != "causal_lm_constrained_next_token"
    ):
        raise ValueError("Decision identity/probability/argmax mismatch")


class CaptureProvider:
    def __init__(self, inner, folder):
        self.inner, self.folder = inner, Path(folder)
        self.mode = inner.mode
        self.events = []

    def pending_index(self):
        return self.inner.pending_index()

    def call(self, method, *args, **kwargs):
        event = {"method": method, "args": canonical(args), "kwargs": canonical(kwargs)}
        result = None
        try:
            result = getattr(self.inner, method)(*args, **kwargs)
            event["result"] = canonical(result)
            return result
        except Exception as exc:
            try:
                args_record = canonical(exc.args)
            except (TypeError, ValueError):
                args_record = [str(value) for value in exc.args]
            event["error"] = {"type": type(exc).__name__, "message": str(exc), "args": args_record}
            if isinstance(exc, HTTPError):
                event["error"].update(code=exc.code, url=exc.url, msg=exc.msg)
            elif isinstance(exc, URLError):
                event["error"]["reason"] = str(exc.reason)
            raise
        finally:
            event["pending_after"] = self.inner.pending_index()
            event["snapshots"] = []
            native_folder = getattr(self.inner, "folder", None)
            if native_folder is not None:
                for p in sorted(Path(native_folder).rglob("energy-journal.json")):
                    rel = Path("tool-evidence") / f"event-{len(self.events):03d}" / p.relative_to(native_folder)
                    target = self.folder / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(p.read_bytes())
                    event["snapshots"].append({"file": str(rel), "sha256": sha(target)})
            self.events.append(event)
            save(self.folder / "tool-events.json", self.events)

    def read_context(self):
        return self.call("read_context")

    def calculate(self, *args, **kwargs):
        return self.call("calculate", *args, **kwargs)

    def recover(self, *args):
        return self.call("recover", *args)

    def verify(self, *args):
        return self.call("verify", *args)


class ReplayProvider:
    def __init__(self, events, mode):
        self.events, self.mode, self.position, self.pending = events, mode, 0, None

    def pending_index(self):
        return self.pending

    def call(self, method, *args, **kwargs):
        if self.position >= len(self.events):
            raise AssertionError("Missing recorded provider call")
        event = self.events[self.position]
        self.position += 1
        if event["method"] != method or event["args"] != canonical(args) or event["kwargs"] != canonical(kwargs):
            raise AssertionError("Provider call differs from frozen environment")
        self.pending = event["pending_after"]
        if "error" in event:
            error = event["error"]
            if error["type"] == "HTTPError":
                raise HTTPError(error["url"], error["code"], error["msg"], None, None)
            if error["type"] == "URLError":
                raise URLError(error["reason"])
            kinds = {"ValueError": ValueError, "RuntimeError": RuntimeError, "KeyError": KeyError, "OSError": OSError}
            if error["type"] not in kinds:
                raise AssertionError("Unsupported recorded exception")
            raise kinds[error["type"]](*error["args"])
        return deepcopy(event["result"])

    read_context = CaptureProvider.read_context
    calculate = CaptureProvider.calculate
    recover = CaptureProvider.recover
    verify = CaptureProvider.verify


def outcome_metrics(env, gold):
    recommendation = (env.report or {}).get("recommendation_index")
    expected = gold["expected_outcome"]
    correct = bool(env.success and env.outcome == expected)
    if expected == "verified_candidate_recommended":
        correct = correct and recommendation in gold["allowed_recommendation_indices"]
    return {
        "decision_correct": correct,
        "expected_outcome": expected,
        "outcome": env.outcome,
        "business_complete": bool(env.business_complete and correct),
        "feasible_case": expected == "verified_candidate_recommended",
        "correct_no_registered_candidate": bool(correct and expected == "no_registered_candidate_meets_requirements"),
        "clarification_correct": env.clarification_correct,
        "receipt_recoveries": sum(s["label"] == "G" and not s["error"] for s in env.steps),
        "goal_changes_observed": sum((s.get("event") or {}).get("kind") == "scripted_goal_change" for s in env.steps),
        "final_goal_version": env.goal_version,
        "report_current_goal_version": (env.report or {}).get("goal_version"),
        "candidate_scope": "two registered alternatives only",
    }


def audit_episode(job, folder, expected_fingerprint):
    """Rebuild every prompt/state using recorded tool results; no model/API calls."""
    folder = Path(folder)
    events = read(folder / "tool-events.json") if (folder / "tool-events.json").exists() else []
    provider = ReplayProvider(events, job["provider_mode"])
    env = ExpertEnvironment(ExpertTask(**job["task"]), provider)
    for step in job["steps"]:
        if env.prompt() != step["prompt"]:
            raise ValueError("Saved model input mismatch")
        validate_decision(step["model"], job["group"], expected_fingerprint)
        actual = env.step(step["model"]["choice"])
        if canonical(actual) != step["transition"]:
            raise ValueError("Recorded transition does not replay")
    if provider.position != len(events) or canonical(env.report) != job["report"]:
        raise ValueError("Tool/report transcript mismatch")
    if outcome_metrics(env, job["gold"]) != job["metrics"]:
        raise ValueError("Unsupported outcome metrics")
    if job["provider_mode"] == "recorded_native_evidence_replay":
        original = RecordedEnergyProvider([read(path)["receipt"] for path in job["source_receipt_files"]])
        independent = ExpertEnvironment(ExpertTask(**job["task"]), original)
        for step in job["steps"]:
            if (
                independent.prompt() != step["prompt"]
                or canonical(independent.step(step["model"]["choice"])) != step["transition"]
            ):
                raise ValueError("Recorded result differs from frozen source receipts")
    for event in events:
        if event["method"] == "read_context" and "result" in event:
            check_context(event["result"])
        receipts = {}
        for item in event["snapshots"]:
            path = folder / item["file"]
            if sha(path) != item["sha256"]:
                raise ValueError("Raw evidence drift")
            state = read(path)
            receipt = state.get("receipt")
            if receipt:
                check_receipt(receipt, receipt["parameters"])
                receipts[path.parent.name] = receipt
        if (
            event["method"] == "verify"
            and "result" in event
            and job["provider_mode"] == "actual_local_offline_energy_api"
        ):
            index, requirements = event["args"]
            receipt = receipts.get(f"candidate-{index}")
            if receipt is None:
                raise ValueError("Missing native calculation receipt")
            checker = RecordedEnergyProvider([receipt])
            checker.receipts[index] = receipt
            expected = checker.verify(index, requirements)
            for key in ("assessment", "alternatives", "receipt_sha256"):
                if expected[key] != event["result"][key]:
                    raise ValueError("Business assessment not supported by native receipt")
    return {
        "passed": True,
        "decision_correct": job["metrics"]["decision_correct"],
        "model_decisions": len(job["steps"]),
        "tool_calls": len(events),
        "trajectory_digest": digest(job),
        "new_model_calls": 0,
        "new_native_calls": 0,
    }
