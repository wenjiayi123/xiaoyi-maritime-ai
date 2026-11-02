"""Read-only latest research evidence, preserving all previous failed experiments."""

import copy
import gzip
import json

from app.config import BASE_DIR
from app.harness import remediation_v4 as prior
from app.harness.physical_v2 import sha

REGISTRY = BASE_DIR / "config/research_v6_evidence_registry.json"


def checked(path, expected):
    p = BASE_DIR / path
    if not p.resolve().is_relative_to(BASE_DIR.resolve()) or not p.is_file() or sha(p) != expected:
        raise ValueError("新研究证据摘要不符或文件缺失，停止采信：" + path)
    return p


def bindings():
    registry = json.loads(REGISTRY.read_text())
    return [
        *registry["reports"].values(),
        *({"path": p, "sha256": h} for p, h in registry["scientific_sources"].items()),
    ]


def source(study, item):
    d = report()
    if study == "rl":
        entries = d["learning"]["sources"]["entries"]
    elif study in {"history", "test"}:
        entries = d["physical"]["sources"][study]["entries"]
    else:
        raise ValueError("未登记的公开研究来源")
    if not 0 <= item < len(entries):
        raise ValueError("来源编号超出已登记范围")
    entry = entries[item]
    return entry, checked(entry["path"], entry["sha256"])


def report():
    registry = json.loads(REGISTRY.read_text())
    if registry.get("schema") != "xiaoyi-research-evidence.v6":
        raise ValueError("不支持的新研究证据登记版本")
    values = {k: json.loads(checked(v["path"], v["sha256"]).read_text()) for k, v in registry["reports"].items()}
    learning, physical = values["learning"], values["physical"]
    files = dict(registry["scientific_sources"])
    files[learning["trace_path"]] = learning["trace_sha256"]
    files[physical["trace_path"]] = physical["trace_sha256"]
    if values.get("diagnostics"):
        for key in ["posthoc_trace", "implementation"]:
            entry = values["diagnostics"][key]
            files[entry["path"]] = entry["sha256"]
    for model in learning["selection"]["models"]:
        files[model["path"]] = model["sha256"]
    for model in physical["selection"]["models"]:
        for m in model.get("models", {}).values():
            files[m["path"]] = m["sha256"]
    for manifest in [learning["sources"], *physical["sources"].values()]:
        for e in manifest["entries"]:
            files[e["path"]] = e["sha256"]
    issues = [p for p, h in files.items() if not (BASE_DIR / p).is_file() or sha(BASE_DIR / p) != h]
    previous = prior.report()
    return {
        "schema": "xiaoyi-research-assurance.v6",
        **values,
        "current": not issues and previous["current"],
        "scientific_evidence_current": not issues,
        "validation_issues": issues,
        "previous": {
            "annual": {
                "passed": previous["legacy_summary"]["long_passed"],
                "total": previous["legacy_summary"]["long_total"],
            },
            "short": {
                "passed": previous["legacy_summary"]["short_passed"],
                "total": previous["legacy_summary"]["short_total"],
            },
            "forced": previous["physical"]["modes"],
        },
        "notice": "新八港与完整年度研究单独评价；旧失败继续保留。拟合更多历史、通过软件检查或图表更丰富，都不自动构成相对强MPC收益、现场孪生标定或超级智能认证。",
        "production_authority": False,
    }


def compact():
    d = report()
    learning, physical = d["learning"], d["physical"]
    selected = next(r for r in learning["aggregate"] if r["algorithm"] == learning["selection"]["selected_rl"])
    return {
        "current": d["current"],
        "scientific_evidence_current": d["scientific_evidence_current"],
        "selected_rl": selected,
        "selected_cost_baseline": learning["selection"]["selected_cost_baseline"],
        "selected_safe_baseline": learning["selection"]["selected_safe_baseline"],
        "annual": physical["annual"],
        "quarters": physical["quarters"],
        "new_periods": physical["new_periods"],
        "pilot": d["pilot"]["aggregates"],
        "learning_sources": learning["sources"],
        "physical_sources": physical["sources"],
        "notice": d["notice"],
        "production_authority": False,
    }


def review_summary():
    d = report()
    learning, physical = d["learning"], d["physical"]
    selected = next(r for r in learning["aggregate"] if r["algorithm"] == learning["selection"]["selected_rl"])
    return {
        "schema": d["schema"],
        "current": d["current"],
        "selected_rl": selected,
        "selected_cost_baseline": learning["selection"]["selected_cost_baseline"],
        "selected_safe_baseline": learning["selection"]["selected_safe_baseline"],
        "annual": physical["annual"],
        "quarters": physical["quarters"],
        "new_periods": physical["new_periods"],
        "failed_twin_cells": [
            {"site": r["site"], "period": r["period"], "blockers": r["blockers"]}
            for r in physical["results"]
            if not r["passed"]
        ],
        "posthoc_diagnosis": {
            k: d["diagnostics"][k]
            for k in [
                "admission_used",
                "raw_to_raw_comparisons",
                "raw_rl_vs_raw_stochastic_mpc_action_differences",
                "compared_raw_actions",
                "safe_results",
            ]
        }
        if d.get("diagnostics")
        else None,
        "source_manifests": [
            "data/public/rl_v6_20261030/manifest.json",
            "data/public/long_twin_v6_20261030/history-manifest.json",
            "data/public/long_twin_v6_20261030/test-manifest.json",
        ],
        "notice": d["notice"],
        "production_authority": False,
    }


def twin(cell):
    d = report()["physical"]
    if not 0 <= cell < len(d["results"]):
        raise ValueError("请选择已封存的年度或新时期单元")
    selected = d["results"][cell]
    points = []
    with gzip.open(checked(d["trace_path"], d["trace_sha256"]), "rt") as handle:
        for line in handle:
            p = json.loads(line)
            if p["station_id"] != selected["station_id"]:
                continue
            at = p["at"]
            period = selected["period"]
            matches = (
                period.startswith("annual")
                or ("Q" in period and (int(at[5:7]) - 1) // 3 + 1 == int(period[-1]))
                or at.startswith(period[:7])
            )
            if matches:
                points.append(p)
    return {
        "cell": selected,
        "cell_index": cell,
        "cells": d["results"],
        "points": points,
        "observed_points": sum(p["actual_m"] is not None for p in points),
        "truth_availability": sum(p["actual_m"] is not None for p in points) / len(points) if points else 0,
        "summary": {k: d[k] for k in ["annual", "quarters", "new_periods"]},
        "source_trace": {"path": d["trace_path"], "sha256": d["trace_sha256"]},
        "evidence_bindings": bindings(),
        "sources": d["sources"],
        "assumptions": d["protocol"],
        "selection": next(m for m in d["selection"]["models"] if m["station_id"] == selected["station_id"]),
        "notice": d["notice"],
        "production_authority": False,
    }


def rl(port_id, quarter, scenario, seed):
    data = report()
    d = data["learning"]
    window = f"{port_id}.2026.{quarter}"
    if window not in {w["id"] for w in d["windows"]} or seed not in d["protocol"]["seeds"]:
        raise ValueError("请选择新研究中已封存的港口、窗口和种子")
    names = {
        d["selection"]["selected_rl"],
        d["selection"]["selected_cost_baseline"],
        d["selection"]["selected_safe_baseline"],
        "stochastic_mpc28.old_reserve",
        "offline_rl90.none",
        "max_capacity.old_reserve",
        "pid_tuned.old_reserve",
    }
    runs = []
    with gzip.open(checked(d["trace_path"], d["trace_sha256"]), "rt") as handle:
        for line in handle:
            row = json.loads(line)
            if (
                row["window"] == window
                and row["scenario"] == scenario
                and row["algorithm"] in names
                and row["seed"] in [0, seed]
            ):
                runs.append(row)
    return {
        "runs": runs,
        "ports": d["sources"]["entries"],
        "seeds": d["protocol"]["seeds"],
        "aggregate": d["aggregate"],
        "selection_summary": {
            k: d["selection"][k] for k in ["selected_rl", "selected_cost_baseline", "selected_safe_baseline"]
        },
        "pilot": data["pilot"],
        "readback": data.get("readback"),
        "diagnostics": data.get("diagnostics"),
        "source_trace": {"path": d["trace_path"], "sha256": d["trace_sha256"]},
        "evidence_bindings": bindings(),
        "frozen_models": [{"path": m["path"], "sha256": m["sha256"]} for m in d["selection"]["models"]],
        "sources": d["sources"],
        "assumptions": d["protocol"],
        "notice": d["notice"],
        "production_authority": False,
    }


def enrich(base):
    if not REGISTRY.is_file():
        return base
    d = report()
    result = copy.deepcopy(base)
    rows = {r["id"]: r for r in result["criteria"]}
    learning, physical = d["learning"], d["physical"]
    chosen = next(r for r in learning["aggregate"] if r["algorithm"] == learning["selection"]["selected_rl"])
    current = d["current"]
    rows["P01"]["evidence"] += (
        " V6再增8个不同港口；新NOAA8站两段2026晚期时段及UHSLC8站完整2025年，原始错误、质量与基准逐条保留。"
    )
    rows["P02"]["evidence"] = (
        "40个已查看港口只作开发，8个未使用港口留出；5次港口年度块自助拟合，先冻结再提取测试。孪生模型先冻结再下载真值。"
    )
    rows["P03"].update(
        passed=current and chosen["research_admission"],
        evidence=f"V6五次拟合、新八港16窗口；可行窗口违规{chosen['feasible_constraint_violations']}，额外违规{chosen['excess_over_max_capacity']}，相对成本均值{chosen['new_port_relative_cost_interval']['mean_delta'] * 100:.4f}%。",
        remaining="未通过项："
        + "、".join(chosen["blockers"])
        + "。共同过滤器、随机MPC同源求解器与代理成本范围公开；旧失败保留。",
    )
    a, q, n = [physical[k] for k in ["annual", "quarters", "new_periods"]]
    rows["P06"].update(
        passed=current and a["all_passed"] and q["all_passed"] and n["all_passed"],
        evidence=f"固定起点完整365天{a['passed']}/{a['total']}，季度{q['passed']}/{q['total']}；晚期新时段{n['passed']}/{n['total']}。不拼接后来的预报、不用测试水位初始化。",
        remaining="逐单元的误差、覆盖、区间宽度、可用率和强基线检查均保留。Newlyn等缺测/历史覆盖不足不填成真值；原年度5/21和七日失败仍可查。",
    )
    for row in rows.values():
        row["passed"] = bool(row["passed"] and current)
        row["status"] = "所列研究检查通过" if row["passed"] else "未通过或待证明"
    result.update(
        schema="xiaoyi-leading-port-gap-assessment.v6",
        passed_items=sum(r["passed"] for r in rows.values()),
        top_port_full_acceptance=all(r["passed"] for r in rows.values()),
        research_admission=current and chosen["research_admission"],
        production_authority=False,
        latest_research=compact(),
    )
    return result
