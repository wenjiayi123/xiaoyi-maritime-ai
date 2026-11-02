"""Preregistered retrospective months, stress cases and economic sensitivity."""

from datetime import datetime, timezone
import copy
import json
from pathlib import Path
import random
from statistics import mean
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.shanghai_lab_v1.data import digest, make_case, verified_dataset
from integrations.shanghai_lab_v1.protocol import packed, verify_energy
from accept_shanghai_lab_v1 import request


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    dates = [f"2025-{m:02}-{d:02}" for m in range(1, 13) for d in [1, 8, 15, 22]]
    protocol = {
        "schema": "shanghai-energy-protocol.v1",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "dates": dates,
        "stress_dates": ["2025-01-15", "2025-04-15", "2025-07-15", "2025-10-15"],
        "stress_scenarios": ["arrival_surge", "berth_outage", "grid_derating", "weather_closure"],
        "sensitivity": {"price_multiplier": [0.7, 1, 1.3], "wear_cny_kwh": [0.04, 0.08, 0.18]},
        "controller": "causal_storage_mpc_lattice_v1; fixed before all runs",
        "comparators": ["no-storage", "hindsight exact lattice bound (non-deployable)"],
        "pass_requirements": [
            "all resource and energy reconciliations",
            "same terminal SOC",
            "nonzero storage in normal cases",
            "no future-input first-action leakage test",
            "preserve carbon increase and all unfavorable results",
        ],
        "claims": "Retrospective engineering study; no new learned-policy superiority or Shanghai field KPI claim",
    }
    (out / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2))
    dataset = verified_dataset()
    results = []
    cases = [(d, "normal", 1, 0.08, "monthly") for d in dates]
    cases += [(d, s, 1, 0.08, "stress") for d in protocol["stress_dates"] for s in protocol["stress_scenarios"]]
    cases += [("2025-10-15", "normal", p, w, "economic_sensitivity") for p in [0.7, 1, 1.3] for w in [0.04, 0.08, 0.18]]
    for index, (day, scenario, price, wear, group) in enumerate(cases):
        c = make_case(day, scenario, 17, dataset=dataset)
        if group == "economic_sensitivity":
            c["energy"]["price_cny_kwh"] = [v * price for v in c["energy"]["price_cny_kwh"]]
            c["battery"]["wear_cny_kwh"] = wear
            c["recipe"]["sensitivity"] = {"price_multiplier": price, "wear_cny_kwh": wear}
            c["snapshot_sha256"] = digest({k: v for k, v in c.items() if k != "snapshot_sha256"})
        packet = packed(c, "snapshot")
        status, plan = request("http://127.0.0.1:18473/api/shanghai-lab/v1/plan", packet)
        entry = {
            "index": index,
            "day": day,
            "scenario": scenario,
            "group": group,
            "price_multiplier": price,
            "wear": wear,
            "passed": False,
        }
        raw = {"snapshot": c, "plan": plan}
        if status == 200:
            packet.update(packed(plan, "plan"))
            status, energy = request("http://127.0.0.1:18808/api/shanghai-lab/v1/evaluate", packet)
            raw["energy"] = energy
            if status == 200:
                try:
                    verify_energy(c, plan, energy)
                    assert energy["comparison"]["deltas"]["regret_to_hindsight_cny"] >= -1e-5
                    entry.update(
                        passed=True,
                        **energy["comparison"]["deltas"],
                        battery_charge_kwh=energy["totals"]["battery_charge_kwh"],
                        battery_discharge_kwh=energy["totals"]["battery_discharge_kwh"],
                        total_cny=energy["totals"]["total_cny"],
                    )
                except (ValueError, AssertionError) as exc:
                    entry["error"] = str(exc)
            else:
                entry["error"] = energy
        else:
            entry["error"] = plan
        (out / f"case-{index:03}.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2))
        results.append(entry)
        if index % 12 == 0 or not entry["passed"]:
            print(json.dumps(entry, ensure_ascii=False), flush=True)
    ordinary = [r for r in results if r["group"] == "monthly" and r["passed"]]
    blocks = [mean(r["cost_saving_cny"] for r in ordinary if r["day"][5:7] == f"{m:02}") for m in range(1, 13)]
    rng = random.Random(20261031)
    bootstrap = sorted(mean(rng.choices(blocks, k=12)) for _ in range(2000))
    summary = {
        "schema": "shanghai-energy-results.v1",
        "passed": all(r["passed"] for r in results) and all(r["battery_charge_kwh"] > 0 for r in ordinary),
        "cases": len(results),
        "monthly_cases": len(ordinary),
        "mean_cost_saving_cny": mean(r["cost_saving_cny"] for r in ordinary),
        "mean_cost_saving_pct": mean(r["cost_saving_pct"] for r in ordinary),
        "worst_cost_saving_cny": min(r["cost_saving_cny"] for r in ordinary),
        "mean_carbon_increase_kg": mean(r["carbon_change_kg"] for r in ordinary),
        "monthly_block_bootstrap_ci95_cny": [bootstrap[49], bootstrap[1949]],
        "cost_nonimproving_cases": sum(r["cost_saving_cny"] <= 0 for r in ordinary),
        "interpretation": "Storage arbitrage after wear/losses; carbon tradeoff retained. Bootstrap reflects sampled scenario months, not independent field interventions.",
        "original_v7_policy_changed": False,
        "production_authority": False,
        "results": results,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
