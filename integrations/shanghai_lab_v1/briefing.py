"""Bounded, source-linked briefing. This compiler is not a language-model eval."""

from __future__ import annotations

import json
import math

from .data import FOLDER, digest, verified_dataset
from .protocol import energy_ledger, validate_plan, verify_energy


def verify_result(result):
    if digest({k: v for k, v in result.items() if k not in {"result_sha256", "mobile_ack"}}) != result["result_sha256"]:
        raise ValueError("trial integrity mismatch")
    if result.get("production_authority") is not False:
        raise ValueError("unexpected production authority")
    if result["status"] != "completed_simulation_pending_mobile":
        raise ValueError("incomplete trial cannot support a completed-work briefing")
    case, plan, energy, receipt = (result[k] for k in ("snapshot", "plan", "energy", "execution"))
    verify_energy(case, plan, energy)
    baseline = energy_ledger(case, plan)["totals"]
    expected = {
        "cost_saving_cny": baseline["total_cny"] - energy["totals"]["total_cny"],
        "carbon_change_kg": energy["totals"]["carbon_kg"] - baseline["carbon_kg"],
    }
    if any(abs(energy["comparison"]["deltas"][key] - value) > 1e-6 for key, value in expected.items()):
        raise ValueError("comparison arithmetic mismatch")
    if digest({k: v for k, v in receipt.items() if k != "receipt_sha256"}) != receipt["receipt_sha256"]:
        raise ValueError("execution integrity mismatch")
    if receipt["source_snapshot_sha256"] != case["snapshot_sha256"] or not receipt["restore_verified"]:
        raise ValueError("execution source/restoration mismatch")


def compile_briefing(result):
    verify_result(result)
    manifest, _, _, _ = verified_dataset()
    case, plan, energy = (result[k] for k in ("snapshot", "plan", "energy"))
    if digest(manifest) != case["dataset_sha256"]:
        raise ValueError("briefing source dataset mismatch")
    sources = {s["id"]: s for s in manifest["sources"]}
    facts = []
    for anchor in json.loads((FOLDER / "official_anchors.json").read_text()):
        source = sources[anchor["source_id"]]
        facts.append(
            {
                "id": anchor["id"],
                "value": anchor["value"],
                "unit": anchor["unit"],
                "scope": anchor["scope"],
                "time_basis": str(anchor["year"]),
                "source_sha256": source["sha256"],
                "source_url": source["url"],
                "evidence_class": "official_aggregate",
                "usage": anchor["use"],
                "published_at": source["published_at"],
            }
        )
    metrics = validate_plan(case, plan)
    for name, value, unit, origin in [
        ("processed_teu", metrics["processed_teu"], "TEU", "plan"),
        ("wait_vessel_hours", metrics["wait_vessel_hours"], "vessel_hours", "plan"),
        ("late_vessel_hours", metrics["late_vessel_hours"], "vessel_hours", "plan"),
        ("total_cost", energy["totals"]["total_cny"], "CNY", "energy"),
        ("storage_saving", energy["comparison"]["deltas"]["cost_saving_cny"], "CNY", "energy"),
        ("storage_carbon_change", energy["comparison"]["deltas"]["carbon_change_kg"], "kgCO2e", "energy"),
    ]:
        facts.append(
            {
                "id": name,
                "value": value,
                "unit": unit,
                "scope": case["site_id"],
                "time_basis": case["event_time"] + "/24h",
                "source_sha256": digest(result[origin]),
                "source_url": "/api/harness/shanghai/trials/" + result["id"],
                "evidence_class": "simulation_output",
                "usage": "this_trial_only",
            }
        )
    delta = energy["comparison"]["deltas"]
    carbon_word = "增加" if delta["carbon_change_kg"] >= 0 else "减少"
    cost_word = "减少" if delta["cost_saving_cny"] >= 0 else "增加"
    text = (
        f"上海港公开数据校准试验 {case['event_time'][:10]}，完成 {len(case['jobs'])} 项工程工单、"
        f"{metrics['processed_teu']} TEU；总等待 {metrics['wait_vessel_hours']} 船时，逾期 {metrics['late_vessel_hours']} 船时。"
        f"同一排程下储能相对无储能方案费用{cost_word} {abs(delta['cost_saving_cny']):.2f} 元，"
        f"碳排{carbon_word} {abs(delta['carbon_change_kg']):.2f} kgCO₂e。"
        "费用含能损、循环折耗和逾期成本，未计项目投资与全部港区经营成本。"
        "排程已独立复核，执行回执已读回，隔离试验状态已恢复。"
        "这是历史公开资料与工程补足驱动的模拟，年度统计只作背景；不代表上港集团现场联合验证。"
    )
    briefing = {
        "schema": "shanghai-evidence-briefing.v1",
        "trial_id": result["id"],
        "result_sha256": result["result_sha256"],
        "text": text,
        "facts": facts,
        "authorship": "deterministic_verified_artifact_compiler",
        "sources": list(sources.values()),
        "baseline": "same schedule, no storage; hindsight comparator is diagnostic, not a deployable policy",
        "uncertainties": [
            "工程工单、资源能力、电价、碳因子须由落地港区校准",
            "仅小时粒度排程，不含船舶动力学或现场放行",
            "旧 RL 冠军与新优化模块分开留证，不能相加宣传收益",
            "尚无港区现场联合验证及生产授权",
        ],
        "production_authority": False,
    }
    briefing["briefing_sha256"] = digest(briefing)
    return briefing


def check_claims(briefing, claims):
    """Exact structured claim guard; does not claim unrestricted prose verification."""
    known = {fact["id"]: fact for fact in briefing["facts"]}
    checks = []
    fields = ("unit", "scope", "time_basis", "source_sha256", "evidence_class")
    for claim in claims:
        fact = known.get(claim.get("id"))
        errors = []
        if fact is None:
            errors.append("unsupported_fact")
        else:
            value = claim.get("value")
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value - fact["value"]) > 1e-6:
                errors.append("value")
            errors.extend(field for field in fields if claim.get(field) != fact[field])
        checks.append({"id": claim.get("id"), "accepted": not errors, "mismatches": errors})
    return {
        "accepted": bool(claims) and all(c["accepted"] for c in checks),
        "claims": checks,
        "scope": "structured facts only; not an unrestricted LLM hallucination benchmark",
    }
