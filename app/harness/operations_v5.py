"""Public-activity anchored, bounded joint scheduling; no field dispatch."""

import csv
import hashlib
import json
import math
import time
from datetime import date, timedelta
from typing import Literal

import numpy as np
from pydantic import Field
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_matrix

from app.config import BASE_DIR
from app.harness.contracts import StrictModel, digest

FOLDER = BASE_DIR / "data/public/operations_v5_20261030"
SCENARIOS = ["normal", "arrival_peak", "crane_outage", "grid_derating"]
RESOURCES = {"berth0": 1, "berth1": 1, "pilot": 2, "tug": 2, "crane": 4, "transport": 6, "yard": 6}
SLOTS = 48
HOURS = 0.5
NOTICE = "IMF公开活动指标驱动的合成工单；设备、工期、优先级、电价权重与供电均为显式假设。整数优化由HiGHS完成，大模型负责选工具和解释。不是RL收益、现场节能或生产调度。"


class OptimizeArgs(StrictModel):
    port_id: str | None = Field(None, max_length=40)
    source_day: date = date(2026, 5, 18)
    scenario: Literal["normal", "arrival_peak", "crane_outage", "grid_derating"] = "normal"
    grid_kw: int = Field(2600, ge=1200, le=5000)
    objective: Literal["balanced", "turnaround"] = "balanced"


def checked(path, expected):
    path = BASE_DIR / path
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("公开输入文件缺失或已变化")
    return path


def catalog():
    manifest = json.loads((FOLDER / "manifest.json").read_text())
    checked(str((FOLDER / "protocol.json").relative_to(BASE_DIR)), manifest["protocol_sha256"])
    return manifest


def problem(args, *, manifest=None):
    manifest = manifest or catalog()
    entry = next((e for e in manifest["entries"] if e["id"] == (args.port_id or manifest["entries"][0]["id"])), None)
    if entry is None:
        raise ValueError("请选择登记的公开港口")
    with checked(entry["path"], entry["sha256"]).open() as handle:
        row = next((r for r in csv.DictReader(handle) if r["date"] == args.source_day.isoformat()), None)
    if row is None:
        raise ValueError("该港口在所选日期没有登记数据，未填补")
    activity = float(row["portcalls"])
    if not math.isfinite(activity) or activity < 0:
        raise ValueError("公开活动指标无效")
    count = min(10, max(4, math.ceil(activity / 10 * (1.5 if args.scenario == "arrival_peak" else 1))))
    seed = int(digest({"port": entry["id"], "date": row["date"]})[:8], 16)
    jobs = []
    for i in range(count):
        variation = (seed >> (i % 8)) % 3
        jobs.append(
            {
                "id": f"SYN-{i + 1:02}",
                "release": i // 2 + variation,
                "duration": 3 + (i + variation) % 4,
                "length_m": 310 if i % 3 == 1 else 220,
                "cranes": 2 if i % 3 == 0 else 1,
                "shore_kw": 200 if i % 2 else 350,
                "priority": 1 + (i + variation) % 4,
                "due": 12 + i * 2,
            }
        )
    caps = {r: [v] * SLOTS for r, v in RESOURCES.items()}
    if args.scenario == "crane_outage":
        caps["crane"][8:20] = [2] * 12
    grid = [args.grid_kw] * SLOTS
    if args.scenario == "grid_derating":
        grid[8:24] = [max(1200, args.grid_kw - 1000)] * 16
    tariff = [0.65 if t < 12 or t >= 40 else 1.5 if 18 <= t < 32 else 1.0 for t in range(SLOTS)]
    return {
        "jobs": jobs,
        "caps": caps,
        "grid_limit_kw": grid,
        "tariff_weight": tariff,
        "base_kw": 200,
        "horizon_slots": SLOTS,
        "slot_hours": HOURS,
        "weights": {
            "deferred_call": 5000.0,
            "waiting_priority_per_hour": 2.0,
            "late_priority_per_hour": 8.0,
            "grid_kwh_to_points": 0.01 if args.objective == "balanced" else 0.0,
        },
        "input": args.model_dump(mode="json"),
        "source": {
            "entry": entry,
            "raw_row": row,
            "decision_day_assumed": (args.source_day + timedelta(days=7)).isoformat(),
            "publication_delay_assumed_days": 7,
            "actual_historical_publication_time_verified": False,
            "portcalls": activity,
            "synthetic_call_count": count,
            "manifest_content_sha256": digest(manifest),
        },
        "assumptions": [
            "一时隙30分钟，24小时计划；每10个公开AIS活动计数映射约1个合成工单，最低4个最高10个，非真实船期",
            "两个泊位长度260/400m，船长、引航拖轮时长、岸桥/集卡需求和交付期限均为生成假设",
            "电网基本负荷200kW，岸桥每台450kW，岸电200/350kW，引航80kW、堆场60kW为假设",
            "电价只是无货币单位的时段权重；碳因子、航速油耗和真实电表未知，不计算实测减排或财务收益",
            "不使用测试结果调整目标权重；全部方法共享相同工单、容量和完整假定日电价信息",
            "未接入船舶吃水、海图深度或潮汐基准，本计划不能作为海务放行；未知UKC继续暂缓",
        ],
        "production_authority": False,
    }


def footprint(job, start, berth):
    end = start + job["duration"]
    cells = [("pilot", start - 1, 1), ("tug", start - 1, 1), ("yard", end, 2), ("transport", end, 1)]
    power = {start - 1: 80.0, end: 60.0}
    for tick in range(start, end):
        cells.extend(
            [(f"berth{berth}", tick, 1), ("crane", tick, job["cranes"]), ("transport", tick, 2 * job["cranes"])]
        )
        power[tick] = 450.0 * job["cranes"] + job["shore_kw"]
    return cells, power


def option_cost(p, job, start, power):
    waiting = (start - 1 - job["release"]) * HOURS
    late = max(0, start + job["duration"] + 1 - job["due"]) * HOURS
    w = p["weights"]
    return (
        waiting * job["priority"] * w["waiting_priority_per_hour"]
        + late * job["priority"] * w["late_priority_per_hour"]
        + sum(kw * HOURS * p["tariff_weight"][t] * w["grid_kwh_to_points"] for t, kw in power.items())
    )


def options(p):
    result = []
    for i, job in enumerate(p["jobs"]):
        for berth, length in enumerate([260, 400]):
            if job["length_m"] > length:
                continue
            for start in range(job["release"] + 1, SLOTS - job["duration"]):
                cells, power = footprint(job, start, berth)
                if any(v > p["caps"][r][t] for r, t, v in cells):
                    continue
                if any(v + p["base_kw"] > p["grid_limit_kw"][t] for t, v in power.items()):
                    continue
                result.append(
                    {
                        "job": i,
                        "start": start,
                        "berth": berth,
                        "cells": cells,
                        "power": power,
                        "cost": option_cost(p, job, start, power),
                    }
                )
    return result


def schedule_check(p, schedule):
    """Rebuild physics from jobs/start/berth, not solver coefficients or cached costs."""
    use = {k: [0] * SLOTS for k in RESOURCES}
    load = [float(p["base_kw"])] * SLOTS
    seen, errors, delay, late, penalty = set(), [], 0.0, 0.0, 0.0
    for row in schedule:
        i, start, berth = row["job"], row["start"], row["berth"]
        if i in seen or not 0 <= i < len(p["jobs"]) or berth not in [0, 1]:
            errors.append("duplicate_or_invalid_job")
            continue
        seen.add(i)
        j = p["jobs"][i]
        end = start + j["duration"]
        if start - 1 < j["release"] or end >= SLOTS or j["length_m"] > [260, 400][berth]:
            errors.append("release_length_or_horizon")
            continue
        use["pilot"][start - 1] += 1
        use["tug"][start - 1] += 1
        load[start - 1] += 80.0
        use["yard"][end] += 2
        use["transport"][end] += 1
        load[end] += 60.0
        for t in range(start, end):
            use[f"berth{berth}"][t] += 1
            use["crane"][t] += j["cranes"]
            use["transport"][t] += 2 * j["cranes"]
            load[t] += 450.0 * j["cranes"] + j["shore_kw"]
        d = (start - 1 - j["release"]) * HOURS
        late_hours = max(0, end + 1 - j["due"]) * HOURS
        delay += d
        late += late_hours
        penalty += j["priority"] * (d * 2 + late_hours * 8)
    deferred = len(p["jobs"]) - len(seen)
    energy = sum(load) * HOURS
    energy_points = sum(
        v * p["tariff_weight"][t] * HOURS * p["weights"]["grid_kwh_to_points"] for t, v in enumerate(load)
    )
    checks = {
        "unique_atomic_calls": not errors,
        "all_resource_bounds": all(v <= p["caps"][r][t] for r, a in use.items() for t, v in enumerate(a)),
        "firm_power_bounds": all(v <= p["grid_limit_kw"][t] + 1e-7 for t, v in enumerate(load)),
        "deferred_calls_conserved": len(seen) + deferred == len(p["jobs"]),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "completed_calls": len(seen),
        "deferred_calls": deferred,
        "total_waiting_hours": delay,
        "late_call_hours": late,
        "grid_energy_kwh": energy,
        "peak_grid_kw": max(load),
        "objective_points": penalty + energy_points + deferred * p["weights"]["deferred_call"],
        "grid_kw": load,
        "resource_usage": use,
        "violations": errors,
        "carbon_kg": None,
        "all_calls_completed": deferred == 0,
        "production_authority": False,
    }


def greedy(p, candidates, method):
    usage = {r: [0] * SLOTS for r in RESOURCES}
    power = [float(p["base_kw"])] * SLOTS
    schedule = []
    jobs = list(range(len(p["jobs"])))
    if method == "due_date":
        jobs.sort(key=lambda i: p["jobs"][i]["due"])
    elif method == "priority_shortest":
        jobs.sort(key=lambda i: (p["jobs"][i]["duration"] / p["jobs"][i]["priority"], i))
    for i in jobs:
        ranked = sorted(
            (c for c in candidates if c["job"] == i),
            key=lambda c: (
                (c["cost"], c["start"], c["berth"]) if method == "energy_lookahead" else (c["start"], c["berth"])
            ),
        )
        for c in ranked:
            if any(usage[r][t] + v > p["caps"][r][t] for r, t, v in c["cells"]):
                continue
            if any(power[t] + v > p["grid_limit_kw"][t] for t, v in c["power"].items()):
                continue
            for r, t, v in c["cells"]:
                usage[r][t] += v
            for t, v in c["power"].items():
                power[t] += v
            schedule.append({k: c[k] for k in ["job", "start", "berth"]})
            break
    return {"algorithm": method, "schedule": schedule, **schedule_check(p, schedule)}


def solve(p):
    started = time.monotonic()
    candidates = options(p)
    nj = len(p["jobs"])
    resource_rows = {r: i for i, r in enumerate(RESOURCES)}
    nrows = nj + (len(RESOURCES) + 1) * SLOTS
    rr, cc, vv = [], [], []
    for i, c in enumerate(candidates):
        rr.append(c["job"])
        cc.append(i)
        vv.append(1.0)
        for r, t, value in c["cells"]:
            rr.append(nj + resource_rows[r] * SLOTS + t)
            cc.append(i)
            vv.append(float(value))
        for t, value in c["power"].items():
            rr.append(nj + len(RESOURCES) * SLOTS + t)
            cc.append(i)
            vv.append(value)
    for i in range(nj):
        rr.append(i)
        cc.append(len(candidates) + i)
        vv.append(1.0)
    matrix = csc_matrix((vv, (rr, cc)), shape=(nrows, len(candidates) + nj))
    lower = np.concatenate([np.ones(nj), np.full(nrows - nj, -np.inf)])
    upper = np.array(
        [*[1.0] * nj, *[v for r in RESOURCES for v in p["caps"][r]], *[v - p["base_kw"] for v in p["grid_limit_kw"]]]
    )
    cost = np.array([*[c["cost"] for c in candidates], *[p["weights"]["deferred_call"]] * nj])
    solution = milp(
        cost,
        integrality=np.ones(len(cost)),
        bounds=Bounds(0.0, 1.0),
        constraints=LinearConstraint(matrix, lower, upper),
        options={"time_limit": 3.0, "mip_rel_gap": 0.00001},
    )
    baselines = [
        greedy(p, candidates, method) for method in ["fifo", "due_date", "priority_shortest", "energy_lookahead"]
    ]
    best = min((b for b in baselines if b["passed"]), key=lambda b: b["objective_points"])
    schedule = [
        {k: c[k] for k in ["job", "start", "berth"]}
        for i, c in enumerate(candidates)
        if solution.x is not None and solution.x[i] > 0.5
    ]
    evaluated = schedule_check(p, schedule)
    chosen = {"algorithm": "joint_milp", "schedule": schedule, **evaluated}
    fallback = not evaluated["passed"] or evaluated["objective_points"] > best["objective_points"] + 1e-5
    if fallback:
        chosen = dict(best)
    base_points = sum(p["base_kw"] * HOURS * w * p["weights"]["grid_kwh_to_points"] for w in p["tariff_weight"])
    return {
        "schema": "xiaoyi-joint-optimization.v5",
        "problem": p,
        "input_sha256": digest(p),
        "source_sha256": hashlib.sha256(__import__("pathlib").Path(__file__).read_bytes()).hexdigest(),
        "selected": chosen,
        "baselines": baselines,
        "best_baseline": best["algorithm"],
        "objective_improvement_vs_best_baseline_pct": 100
        * (best["objective_points"] - chosen["objective_points"])
        / max(1e-9, best["objective_points"]),
        "solver": {
            "name": "scipy.optimize.milp / HiGHS",
            "status": int(solution.status),
            "message": str(solution.message),
            "optimality_proven": solution.status == 0 and not fallback,
            "mip_gap": None if getattr(solution, "mip_gap", None) is None else float(solution.mip_gap),
            "dual_bound_points": None
            if getattr(solution, "mip_dual_bound", None) is None
            else float(solution.mip_dual_bound) + base_points,
            "time_limit_seconds": 3.0,
            "variables": len(cost),
            "constraints": nrows,
            "heuristic_fallback_used": fallback,
            "elapsed_seconds": time.monotonic() - started,
        },
        "checks": {
            "selected_feasible": chosen["passed"],
            "not_worse_than_four_heuristics": chosen["objective_points"] <= best["objective_points"] + 1e-5,
        },
        "notice": NOTICE,
        "production_authority": False,
    }


def optimize(args):
    return solve(problem(args))
