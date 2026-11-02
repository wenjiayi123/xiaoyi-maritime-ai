"""Storage control with causal rolling optimization and a separately labelled oracle.

Exact dynamic programming applies to the declared SOC lattice only. All dispatch
rows are independently reconciled by the physical/accounting ledger.
"""

from __future__ import annotations

import math
from .protocol import energy_ledger, validate_plan


def optimize_lattice(case, loads, solar, start, stored, *, step_kwh=300):
    b, e = case["battery"], case["energy"]
    low = math.ceil(b["min_soc"] * b["capacity_kwh"] / step_kwh)
    high = math.floor(b["max_soc"] * b["capacity_kwh"] / step_kwh)
    target = round(b["initial_soc"] * b["capacity_kwh"] / step_kwh)
    initial = round(stored / step_kwh)
    if abs(initial * step_kwh - stored) > 1e-5:
        raise ValueError("storage state is not on declared lattice")
    values = {target: 0.0}
    policies = {}
    for hour in range(23, start - 1, -1):
        next_values = {}
        for state in range(low, high + 1):
            best = None
            for nxt, tail in values.items():
                delta = (nxt - state) * step_kwh
                ac = delta / b["efficiency"] if delta >= 0 else delta * b["efficiency"]
                if abs(ac) > b["power_kw"] + 1e-8:
                    continue
                grid = max(0.0, loads[hour] - solar[hour] + ac)
                if grid > e["grid_limit_kw"][hour] + 1e-8:
                    continue
                cost = grid * e["price_cny_kwh"][hour] + abs(ac) * b["wear_cny_kwh"] + tail
                candidate = (cost, abs(ac), nxt, ac)
                if best is None or candidate < best:
                    best = candidate
            if best is not None:
                next_values[state] = best[0]
                policies[(hour, state)] = (best[2], best[3])
        values = next_values
    if initial not in values:
        raise ValueError("storage optimization has no physically feasible completion")
    state, actions = initial, []
    for hour in range(start, 24):
        state, action = policies[(hour, state)]
        actions.append(action)
    return actions


def causal_actions(case, plan, step_kwh=300):
    operations = validate_plan(case, plan)
    b = case["battery"]
    stored = b["initial_soc"] * b["capacity_kwh"]
    actions, traces = [], []
    for hour in range(24):
        # Planned crane/shore service and tariffs are declared known commitments.
        # Future realized reanalysis/base-load rows are intentionally not indexed.
        loads = [0.0] * 24
        solar = [0.0] * 24
        theoretical_now = max(0.0, math.sin(math.pi * (hour - 6) / 12)) * 2550
        attenuation = min(1.0, case["energy"]["pv_kw"][hour] / theoretical_now) if theoretical_now > 100 else 0.65
        for h in range(hour, 24):
            loads[h] = (
                case["energy"]["base_kw"][hour]
                + operations["shore_kw"][h]
                + operations["cranes"][h] * case["energy"]["crane_kw"]
            )
            solar[h] = (
                case["energy"]["pv_kw"][hour]
                if h == hour
                else max(0.0, math.sin(math.pi * (h - 6) / 12)) * 2550 * attenuation
            )
        action = optimize_lattice(case, loads, solar, hour, stored, step_kwh=step_kwh)[0]
        actions.append(action)
        stored += max(0.0, action) * b["efficiency"] - max(0.0, -action) / b["efficiency"]
        traces.append(
            {
                "hour": hour,
                "latest_observed_hour": hour,
                "forecast": "current-load persistence plus declared solar shape; no future reanalysis",
                "stored_kwh": stored,
                "action_ac_kw": action,
            }
        )
    return actions, traces


def evaluate(case, plan, *, step_kwh=300):
    baseline = energy_ledger(case, plan)
    actions, trace = causal_actions(case, plan, step_kwh)
    candidate = energy_ledger(case, plan, actions)
    oracle_actions = optimize_lattice(
        case,
        baseline["operations"]["load_kw"],
        case["energy"]["pv_kw"],
        0,
        case["battery"]["initial_soc"] * case["battery"]["capacity_kwh"],
        step_kwh=step_kwh,
    )
    oracle = energy_ledger(case, plan, oracle_actions)
    gains = {
        "cost_saving_cny": baseline["totals"]["total_cny"] - candidate["totals"]["total_cny"],
        "cost_saving_pct": (baseline["totals"]["total_cny"] - candidate["totals"]["total_cny"])
        / baseline["totals"]["total_cny"]
        * 100,
        "carbon_change_kg": candidate["totals"]["carbon_kg"] - baseline["totals"]["carbon_kg"],
        "grid_energy_change_kwh": candidate["totals"]["grid_kwh"] - baseline["totals"]["grid_kwh"],
        "regret_to_hindsight_cny": candidate["totals"]["total_cny"] - oracle["totals"]["total_cny"],
    }
    candidate.update(
        method="causal_storage_mpc_lattice_v1",
        comparison={
            "no_storage": baseline["totals"],
            "hindsight_lattice_lower_bound": oracle["totals"],
            "deltas": gains,
        },
        controller_trace=trace,
        lattice_step_kwh=step_kwh,
        selection="Fixed causal controller; not selected after seeing test costs; original V7 champion remains active in its original system",
        tradeoff="Cost arbitrage can increase grid energy and carbon because of round-trip losses; all changes retained",
        scope="Storage subproblem with fixed berth/crane service; not an RL gain or a globally optimal whole-port schedule",
        benchmark_information="Oracle reads future realized inputs only for a labelled lower-bound diagnostic; causal controller does not.",
    )
    return candidate
