"""Coupled berth/crane/channel/pilot/tug/power reference, separate from old RL."""

from __future__ import annotations

import time
from .data import validate_case
from .protocol import validate_plan


def objective(case, plan):
    jobs = {j["id"]: j for j in case["jobs"]}
    total = 0.0
    for row in plan["scheduled"]:
        j = jobs[row["job_id"]]
        total += max(0, row["end_hour"] - j["deadline_hour"]) * case["delay_cny_vessel_hour"]
        total += (row["start_hour"] - j["arrival_hour"]) * 50 * j["priority"]
        total += sum(
            case["energy"]["price_cny_kwh"][h] * (j["shore_kw"] + j["cranes"] * case["energy"]["crane_kw"])
            for h in range(row["start_hour"], row["end_hour"])
        )
    return total


def strong_reference(case, *, frozen=None, service_limits=None, seconds=8):
    validate_case(case, require_usable=True)
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import csc_matrix

    frozen = frozen or {}
    if set(frozen) - {j["id"] for j in case["jobs"]}:
        raise ValueError("unknown frozen commitment")
    resources, energy = case["resources"], case["energy"]
    variables = []
    for ji, j in enumerate(case["jobs"]):
        for s in range(j["arrival_hour"], 25 - j["duration_hours"]):
            if not resources["channel_open"][s]:
                continue
            for berth in range(resources["berths"]):
                if j["id"] in frozen and frozen[j["id"]] != {"start_hour": s, "berth": berth}:
                    continue
                if any(berth >= resources["berth_capacity"][h] for h in range(s, s + j["duration_hours"])):
                    continue
                row = {"job_id": j["id"], "start_hour": s, "end_hour": s + j["duration_hours"], "berth": berth}
                variables.append((ji, j, row))
    n = len(variables)
    if not n or any(not any(ji == i for ji, _, _ in variables) for i in range(len(case["jobs"]))):
        raise ValueError("no feasible assignment for every job; frozen commitments cannot be moved")
    matrix = []
    lower = []
    upper = []

    def add(coeff, lo, hi):
        matrix.append(coeff)
        lower.append(lo)
        upper.append(hi)

    for i in range(len(case["jobs"])):
        add([1 if ji == i else 0 for ji, _, _ in variables], 1, 1)
    if service_limits is not None:
        add([r["start_hour"] - j["arrival_hour"] for _, j, r in variables], 0, service_limits["wait_vessel_hours"])
        add(
            [max(0, r["end_hour"] - j["deadline_hour"]) for _, j, r in variables],
            0,
            service_limits["late_vessel_hours"],
        )
    for h in range(24):
        for b in range(resources["berths"]):
            add([int(r["berth"] == b and r["start_hour"] <= h < r["end_hour"]) for _, _, r in variables], 0, 1)
        add(
            [j["cranes"] if r["start_hour"] <= h < r["end_hour"] else 0 for _, j, r in variables],
            0,
            resources["cranes"],
        )
        add(
            [int(r["start_hour"] == h) for _, _, r in variables],
            0,
            min(resources["channel_concurrency"], resources["pilots"], resources["tugs"] // 2),
        )
        add(
            [
                j["shore_kw"] + j["cranes"] * energy["crane_kw"] if r["start_hour"] <= h < r["end_hour"] else 0
                for _, j, r in variables
            ],
            0,
            energy["grid_limit_kw"][h] - energy["base_kw"][h] + energy["pv_kw"][h],
        )
    coeff = np.array([objective(case, {"scheduled": [r]}) for _, _, r in variables])
    started = time.monotonic()
    result = milp(
        coeff,
        integrality=np.ones(n),
        bounds=Bounds(np.zeros(n), np.ones(n)),
        constraints=LinearConstraint(
            csc_matrix(np.asarray(matrix, dtype=float)), np.asarray(lower, dtype=float), np.asarray(upper, dtype=float)
        ),
        options={"time_limit": seconds, "mip_rel_gap": 0.001},
    )
    if result.x is None:
        raise ValueError("strong reference has no complete feasible incumbent: " + str(result.message))
    scheduled = [r for (_, _, r), x in zip(variables, result.x) if x > 0.5]
    plan = {
        "schema": "shanghai-plan.v1",
        "source_snapshot_sha256": case["snapshot_sha256"],
        "trial_id": case["trial_id"],
        "port_id": case["port_id"],
        "method": "coupled_resource_milp_v1",
        "scheduled": scheduled,
        "production_authority": False,
        "evidence_class": "simulation_output",
        "solver": {
            "status": int(result.status),
            "message": str(result.message),
            "gap": float(result.mip_gap),
            "dual_bound": float(result.mip_dual_bound),
            "elapsed_seconds": time.monotonic() - started,
            "variables": n,
        },
        "frozen_commitments": frozen,
        "service_non_degradation_limits": service_limits,
        "information": "retrospective same-horizon public/engineering inputs; not an online forecast test",
        "objective_definition": "service power tariff + 50 CNY/vessel-hour * declared priority + declared deadline penalty; waiting weight is an engineering preference",
        "optimality": "MILP bound applies to hourly resource model and declared proxy objective; storage is dispatched subsequently, not a whole-port global optimum",
    }
    check = validate_plan(case, plan)
    plan["metrics"] = {k: check[k] for k in ["wait_vessel_hours", "late_vessel_hours", "processed_teu", "shore_kwh"]}
    plan["resource_objective_cny"] = objective(case, plan)
    return plan


def compare_and_select(case, native_plan):
    native_check = validate_plan(case, native_plan)
    candidates = []
    for row in native_plan.get("candidates", [native_plan]):
        if not row.get("feasible"):
            continue
        candidate = {**native_plan, **row}
        validate_plan(case, candidate)
        candidates.append(
            {"method": row["method"], "resource_objective_cny": objective(case, candidate), "metrics": row["metrics"]}
        )
    strong = strong_reference(
        case, service_limits={k: native_check[k] for k in ["wait_vessel_hours", "late_vessel_hours"]}
    )
    native_cost = objective(case, native_plan)
    selected = strong if strong["resource_objective_cny"] <= native_cost + 1e-6 else native_plan
    return {
        **selected,
        "comparison": {
            "native_candidates": candidates,
            "strong_reference": {k: v for k, v in strong.items() if k != "scheduled"},
            "native_selected_objective_cny": native_cost,
            "selected_objective_cny": objective(case, selected),
            "improvement_cny": native_cost - objective(case, selected),
        },
        "legacy_rl_champions": "preserved; no Shanghai retraining or promotion claimed",
    }
