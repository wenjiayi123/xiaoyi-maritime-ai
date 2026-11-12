"""Display fixed role evidence in its recorded units and verify the selected role disposition."""
from __future__ import annotations

import json

from app.policy_release import ROLE_CHECKS, CHECK_METRICS

LABELS = {
    "cost": ("成本", "元"), "carbon": ("碳排放", "kg"), "service": ("处理量", "TEU"),
    "delay": ("延误", "分钟"), "peak": ("峰值功率", "kW"), "safety": ("安全违规", "次"),
    "terminal_soc": ("期末荷电比例", ""),
}
ROLES = {"energy":"能碳","operations":"运营","safety":"安全"}

def render_choices(role, policy, baseline, checks):
    """The model selects the conclusion. Each option displays identical source measurements."""
    details = []
    for key in ROLE_CHECKS[role]:
        metric = CHECK_METRICS[key]
        label, unit = LABELS[key]
        left = format(float(policy[metric]), ".2f")
        right = format(float(baseline[metric]), ".2f")
        suffix = " " + unit if unit else ""
        status = "达标" if checks[key] else "未达标"
        details.append(f"{label} {left} / {right}{suffix}（{status}）")
    figures = "。".join(details)
    return {decision: f"历史仿真，{ROLES[role]}岗位{title}。策略 / 基线。{figures}。"
            for decision, title in (("pass", "通过"), ("veto", "否决"))}

def report_choices(task):
    if not task.get("council_role_review") or task.get("inputs"):
        return None
    results = task.get("results", [])
    if len(results) != 1 or not results[0]["ok"]:
        return None
    role = results[0]["tool"].removeprefix("policy.")
    if role not in ROLE_CHECKS:
        return None
    summary = json.loads(results[0]["summary"])
    display = summary["display"]
    return list(render_choices(role, display["policy_metrics"], display["baseline_metrics"], summary["checks"]).values())

def verified_text(receipt):
    options = render_choices(receipt["role"], receipt["policy_metrics"], receipt["baseline_metrics"], receipt["checks"])
    verdict = "pass" if all(receipt["checks"][k] for k in ROLE_CHECKS[receipt["role"]]) else "veto"
    if receipt["decision"] != verdict:
        return None
    return options[verdict]
