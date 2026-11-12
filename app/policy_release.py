"""Read the fixed CarbonOps experiment through the local business system."""
import hashlib
import json
import re
from typing import Literal
from urllib.error import URLError
from urllib.request import urlopen

from pydantic import BaseModel, ConfigDict, Field

SOURCE = "http://127.0.0.1:5173/gullmate-policy-release.json"
EXPECTED_SHA256 = "8a3ba464bb95b28f20fb4a9ef1becc83528567c3fe0bbdc66376f46e3c0eb7bb"


class PolicySelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["evaluate", "stress"] = "evaluate"
    strategy: Literal["joint", "storage", "cost_only"] = "joint"
    seed: Literal[17, 37, 59] = 17
    baseline: Literal["fixed", "mpc2"] = "fixed"
    window: int | None = Field(None, ge=0, le=11)


class ReleaseUnavailable(ValueError):
    pass


def from_command(question: str) -> tuple[bool, PolicySelection | None]:
    """Explicit evidence commands never intercept ordinary policy or training questions."""
    match = re.fullmatch(r"\s*(?:小鸥[，, ]*|GullMate[, ]*)?/(?:策略复验|policy-review)(?:\s+(.*?))?\s*", question, flags=re.I)
    if not match:
        return False, None
    fields = {}
    try:
        for token in (match[1] or "").split():
            key, value = token.split("=", 1)
            if key in fields:
                raise ValueError("重复参数")
            fields[key] = int(value) if key in {"seed", "window"} else value
        return True, PolicySelection.model_validate(fields)
    except (TypeError, ValueError):
        return True, None


def summarize(receipt: dict) -> str:
    a,b=receipt["policy_metrics"],receipt["baseline_metrics"]
    failed=[key for key,value in receipt["checks"].items() if not value]
    reason={"cost":"成本","carbon":"碳排","service":"处理量","delay":"延误","peak":"峰值功率","safety":"违规","terminal_soc":"期末电量"}
    verdict="保留基线，未通过项目为"+"、".join(reason[k] for k in failed) if failed else "可提交人工复核"
    return (f"能碳历史仿真 · {receipt['strategy']} 对比 {receipt['baseline']} · {receipt['period']}。\n"
            f"模拟成本 {a['cost']:,.2f} 对 {b['cost']:,.2f}，碳排 {a['carbon_kg']:,.2f} 对 {b['carbon_kg']:,.2f} kg，"
            f"处理量 {a['processed_teu']:,.2f} 对 {b['processed_teu']:,.2f} TEU，延误 {a['delay_minutes']:.2f} 对 {b['delay_minutes']:.2f} 分钟。\n"
            f"{verdict}。数据来自 CarbonOps 冻结回执 {receipt['release_sha256'][:12]}；生产权限关闭。")


ROLE_CHECKS = {"energy": ("cost", "carbon"), "operations": ("service", "delay"), "safety": ("peak", "safety", "terminal_soc")}
CHECK_METRICS = {"cost": "cost", "carbon": "carbon_kg", "service": "processed_teu", "delay": "delay_minutes",
                 "peak": "peak_kw", "safety": "safety_violations", "terminal_soc": "ending_battery_soc"}


def review_role(role: str, selection: PolicySelection) -> dict:
    record = compare(selection)
    checks = {key: record["checks"][key] for key in ROLE_CHECKS[role]}
    metrics = [CHECK_METRICS[key] for key in checks]
    return {
        **{key: record[key] for key in ("release_sha256", "dataset_sha256", "policy_sha256", "period", "production_authority")},
        "role": role, "selection": selection.model_dump(), "checks": checks,
        "policy_metrics": {key: record["policy_metrics"][key] for key in metrics},
        "baseline_metrics": {key: record["baseline_metrics"][key] for key in metrics},
        "decision": "pass" if all(checks.values()) else "veto",
    }


def load_verified_release() -> tuple[dict, str]:
    try:
        with urlopen(SOURCE, timeout=4) as response:
            if response.geturl() != SOURCE:
                raise ReleaseUnavailable("能碳回执位置不符")
            raw = response.read(1024 * 1024 + 1)
    except (URLError, OSError) as exc:
        raise ReleaseUnavailable("能碳服务未返回可核验的运行回执") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if len(raw) > 1024 * 1024 or actual != EXPECTED_SHA256:
        raise ReleaseUnavailable("能碳策略发布版本或回执哈希不匹配")
    release = json.loads(raw)
    if release.get("production_authority") is not False:
        raise ReleaseUnavailable("能碳策略回执缺少仿真权限边界")
    return release, actual


def compare(selection: PolicySelection) -> dict:
    release, actual = load_verified_release()
    scene = release["scenarios"][selection.scenario]
    key = f"{selection.strategy}-{selection.seed}-8192"
    policies = scene["policies"]
    if selection.window is None:
        a, b = policies[key]["mean"], policies[selection.baseline]["mean"]
        period = "12 paired windows"
    else:
        left = policies[key]["windows"][selection.window]
        right = policies[selection.baseline]["windows"][selection.window]
        if left["start"] != right["start"]:
            raise ReleaseUnavailable("对照窗口不一致")
        a, b = left["metrics"], right["metrics"]
        period = f"{left['period']} / {left['start']}"
    checks = {
        "cost": a["cost"] < b["cost"], "carbon": a["carbon_kg"] <= b["carbon_kg"] + 1e-6,
        "service": a["processed_teu"] >= b["processed_teu"] - 1e-6,
        "delay": a["delay_minutes"] <= b["delay_minutes"] + 1e-6,
        "safety": a["safety_violations"] == 0,
        "peak": a["peak_kw"] <= b["peak_kw"] + 1e-6,
        "terminal_soc": a["ending_battery_soc"] >= b["ending_battery_soc"] - 1e-6,
    }
    return {
        "schema": "gullmate.policy-comparison.v1", "source": "CarbonOps", "source_url": SOURCE,
        "release_sha256": actual, "dataset_sha256": release["dataset_sha256"], "policy_sha256": release["weights"][key],
        "strategy": key, "baseline": selection.baseline, "scenario": selection.scenario, "window": selection.window,
        "period": period, "policy_metrics": a, "baseline_metrics": b, "checks": checks,
        "decision": "human_review" if all(checks.values()) else "retain_baseline",
        "scope": "saved historical simulation", "production_authority": False,
    }
