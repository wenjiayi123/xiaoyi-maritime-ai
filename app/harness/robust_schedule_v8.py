"""One shared schedule constrained in every explicitly declared scenario.

Finite-scenario min-max MILP, not a robust guarantee outside the scenario set.
Discharge resource use changes with duration: each scenario is constrained in
full, rather than assuming maximum duration implies all shorter cases are safe.
"""

import copy
import math
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_matrix

from app.harness import operations_v5 as ops
from app.harness.contracts import digest


def scenarios(problem):
    result = []
    for name in ("nominal", "late_arrival", "long_service", "resource_loss", "combined"):
        p = copy.deepcopy(problem)
        if name in {"late_arrival", "combined"}:
            for job in p["jobs"]:
                job["release"] += 2
        if name in {"long_service", "combined"}:
            for job in p["jobs"]:
                job["duration"] += 2
        if name in {"resource_loss", "combined"}:
            p["grid_limit_kw"] = [v * 0.8 for v in p["grid_limit_kw"]]
            p["caps"]["crane"] = [max(0, v - 1) for v in p["caps"]["crane"]]
        result.append({"name": name, "problem": p})
    return result


def solve(cases, time_limit=5.0):
    if not cases or len(cases) > 8 or not 0 < time_limit <= 10:
        raise ValueError("bounded nonempty scenario set required")
    jobs = cases[0]["problem"]["jobs"]
    ids = [j["id"] for j in jobs]
    if not jobs or len(jobs) > 10 or len(set(ids)) != len(ids):
        raise ValueError("1-10 unique atomic jobs required")
    for case in cases:
        p = case["problem"]
        if [j["id"] for j in p["jobs"]] != ids:
            raise ValueError("all scenarios must bind the same ordered jobs")
        if p["weights"]["waiting_priority_per_hour"] != 2 or p["weights"]["late_priority_per_hour"] != 8:
            raise ValueError("independent checker requires the registered 2/8 waiting/lateness contract")
        if any(not math.isfinite(v) or v < p["base_kw"] for v in p["grid_limit_kw"]):
            raise ValueError("base load itself infeasible; no executable schedule")
    started = time.monotonic()
    maps = [{(c["job"], c["start"], c["berth"]): c for c in ops.options(s["problem"])} for s in cases]
    keys = sorted(set.intersection(*(set(m) for m in maps)))
    nj, nv = len(jobs), len(keys) + len(jobs) + 1
    resource_rows = {r: i for i, r in enumerate(ops.RESOURCES)}
    block = (len(resource_rows) + 1) * ops.SLOTS + 1
    rr, cc, vv = [], [], []
    low = [1.0] * nj
    high = [1.0] * nj
    for i, key in enumerate(keys):
        rr.append(key[0])
        cc.append(i)
        vv.append(1.0)
    for j in range(nj):
        rr.append(j)
        cc.append(len(keys) + j)
        vv.append(1.0)
    for si, case in enumerate(cases):
        p = case["problem"]
        offset = nj + si * block
        for i, key in enumerate(keys):
            c = maps[si][key]
            for resource, tick, amount in c["cells"]:
                rr.append(offset + resource_rows[resource] * ops.SLOTS + tick)
                cc.append(i)
                vv.append(float(amount))
            for tick, kw in c["power"].items():
                rr.append(offset + len(resource_rows) * ops.SLOTS + tick)
                cc.append(i)
                vv.append(kw)
            rr.append(offset + block - 1)
            cc.append(i)
            vv.append(c["cost"])
        for j in range(nj):
            rr.append(offset + block - 1)
            cc.append(len(keys) + j)
            vv.append(p["weights"]["deferred_call"])
        rr.append(offset + block - 1)
        cc.append(nv - 1)
        vv.append(-1.0)
        base_cost = sum(p["base_kw"] * ops.HOURS * t * p["weights"]["grid_kwh_to_points"] for t in p["tariff_weight"])
        low.extend([-np.inf] * block)
        high.extend(
            [
                *[v for r in ops.RESOURCES for v in p["caps"][r]],
                *[v - p["base_kw"] for v in p["grid_limit_kw"]],
                -base_cost,
            ]
        )
    matrix = csc_matrix((vv, (rr, cc)), shape=(len(low), nv))
    objective = np.zeros(nv)
    objective[-1] = 1
    integrality = np.ones(nv)
    integrality[-1] = 0
    upper = np.ones(nv)
    upper[-1] = np.inf
    result = milp(
        objective,
        integrality=integrality,
        bounds=Bounds(np.zeros(nv), upper),
        constraints=LinearConstraint(matrix, np.array(low), np.array(high)),
        options={"time_limit": time_limit, "mip_rel_gap": 1e-5},
    )
    schedule = [
        {"job": k[0], "start": k[1], "berth": k[2]}
        for i, k in enumerate(keys)
        if result.x is not None and result.x[i] > 0.5
    ]
    checks = [{"name": c["name"], **ops.schedule_check(c["problem"], schedule)} for c in cases]
    fallback = result.x is None or not all(c["passed"] for c in checks)
    if fallback:
        schedule = []
        checks = [{"name": c["name"], **ops.schedule_check(c["problem"], schedule)} for c in cases]
    dual = getattr(result, "mip_dual_bound", None)
    return {
        "schema": "xiaoyi-finite-scenario-plan.v8",
        "schedule": schedule,
        "scenarios": checks,
        "all_declared_scenarios_feasible": all(c["passed"] for c in checks),
        "worst_objective_points": max(c["objective_points"] for c in checks),
        "solver": {
            "status": int(result.status),
            "optimality_proven": result.status == 0 and not fallback,
            "defer_all_fallback": fallback,
            "dual_bound": float(dual) if dual is not None and math.isfinite(dual) else None,
            "elapsed_seconds": time.monotonic() - started,
        },
        "input_sha256": digest(cases),
        "production_authority": False,
        "notice": "固定五种工程压力情景内的共享计划；合成工单，非真实船期、现场收益或情景外安全保证。",
    }


def compare(args):
    problem = ops.problem(args)
    cases = scenarios(problem)
    nominal = ops.solve(problem)
    robust = solve(cases)
    nominal_checks = [
        {"name": c["name"], **ops.schedule_check(c["problem"], nominal["selected"]["schedule"])} for c in cases
    ]
    return {
        "parameters": args.model_dump(mode="json"),
        "problem": problem,
        "nominal": nominal["selected"],
        "nominal_stress": nominal_checks,
        "robust": robust,
        "nominal_failed_scenarios": sum(not c["passed"] for c in nominal_checks),
        "robust_failed_scenarios": sum(not c["passed"] for c in robust["scenarios"]),
        "nominal_cost_increase_points": robust["scenarios"][0]["objective_points"]
        - nominal["selected"]["objective_points"],
        "additional_deferred_jobs": robust["scenarios"][0]["deferred_calls"] - nominal["selected"]["deferred_calls"],
        "production_authority": False,
    }
