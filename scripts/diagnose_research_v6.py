"""Post-test diagnostic raw-to-raw comparisons; never used for model admission."""

import csv
import gzip
import json
import statistics
from datetime import date
from pathlib import Path

import numpy as np

from app.harness import rl_v6 as study

ROOT = study.c.BASE_DIR
OUT = ROOT / ".codex_artifacts/research-v6-20261030"


def main():
    target = OUT / "diagnostics.json"
    if target.exists():
        raise ValueError("post-test diagnostics immutable")
    report = json.loads((study.OUT / "report.json").read_text())
    selection = report["selection"]
    sources = report["sources"]
    series = {}
    for e in sources["entries"]:
        with (ROOT / e["path"]).open() as handle:
            series[e["id"]] = [(date.fromisoformat(r["date"]), float(r["portcalls"])) for r in csv.DictReader(handle)]
    windows, _ = study.c.windows(series, list(series), [2026], [1, 4])
    gains = tuple(selection["gains"])
    guard = {"name": "none", "sigma": 0, "queue_budget": 4}
    policies = []
    for m in selection["models"]:
        table = np.load(ROOT / m["path"])["thresholds"]
        policies.append(study.Controller(study.FrozenPolicy(table, m["seed"], 28), guard, gains, 0, 0))
    empirical = json.loads((study.OUT / "empirical-transition-model.json").read_text())
    policies.append(
        study.Controller(
            study.CorrectedMPC(28, gains, np.asarray(empirical["pooled_centroids"]) @ study.WEIGHTS), guard, gains, 0, 0
        )
    )
    rows, actions = [], {}
    trace = OUT / "posthoc-raw-trajectories.jsonl.gz"
    with gzip.open(trace, "wt") as handle:
        for policy in policies:
            for w in windows:
                for scenario in study.c.SCENARIOS:
                    row = study.evaluate(policy, w, selection["forecast"]["selected"], scenario, True)
                    actions[policy.name, policy.seed, w["id"], scenario] = [f["action"] for f in row["frames"]]
                    handle.write(json.dumps(row) + "\n")
                    rows.append({k: v for k, v in row.items() if k != "frames"})
    raw_runs = [r for r in report["runs"] if r["algorithm"] == "offline_rl90.none"]
    comparisons = []
    for name in sorted({r["algorithm"] for r in rows}):
        own = [r for r in rows if r["algorithm"] == name]
        b = {
            (w["id"], s): statistics.mean(r["score"] for r in own if r["window"] == w["id"] and r["scenario"] == s)
            for w in windows
            for s in study.c.SCENARIOS
        }
        per_port = {
            p: [
                (
                    statistics.mean(
                        r["score"] for r in raw_runs if r["window"] == w["id"] and r["scenario"] == "normal"
                    )
                    - b[w["id"], "normal"]
                )
                / abs(b[w["id"], "normal"])
                for w in windows
                if w["port_id"] == p
            ]
            for p in series
        }
        comparisons.append(
            {
                "raw_baseline": name,
                "rl_relative_cost_interval": study.c.clustered_interval(per_port),
                "baseline_all_violations": sum(r["constraint_violations"] for r in own),
                "baseline_run_count": len(own),
                "notice": "Same absent safety filter and same information contract. Newly added after viewing the held-out results: diagnostic only, no model selection or admission credit.",
            }
        )
    action_differences = 0
    with gzip.open(ROOT / report["trace_path"], "rt") as handle:
        for line in handle:
            row = json.loads(line)
            if row["algorithm"] == "offline_rl90.none":
                other = actions["stochastic_mpc28.none", row["seed"], row["window"], row["scenario"]]
                action_differences += sum(a != b for a, b in zip([f["action"] for f in row["frames"]], other))
    selected = next(r for r in report["aggregate"] if r["algorithm"] == selection["selected_rl"])
    raw = next(r for r in report["aggregate"] if r["algorithm"] == "offline_rl90.none")
    safe_runs = [r for r in report["runs"] if r["algorithm"] == selection["selected_rl"]]
    maximum = [r for r in report["runs"] if r["algorithm"] == "max_capacity.old_reserve"]
    floor = {(r["window"], r["scenario"]): r["constraint_violations"] for r in maximum}
    seed_totals = [
        {"seed": seed, "violations": sum(r["constraint_violations"] for r in safe_runs if r["seed"] == seed)}
        for seed in report["protocol"]["seeds"]
    ]
    readback = json.loads((OUT / "independent-readback.json").read_text())
    study.c.write(
        target,
        {
            "schema": "xiaoyi-research-diagnostics.v6",
            "posthoc_new_comparison": True,
            "admission_used": False,
            "raw_to_raw_comparisons": comparisons,
            "raw_rl_vs_raw_stochastic_mpc_action_differences": action_differences,
            "compared_raw_actions": len(raw_runs) * 90,
            "raw_to_guarded_unfair_comparison": {
                "apparent_relative_improvement_pct": raw["new_port_relative_cost_interval"]["mean_delta"] * 100,
                "extra_violations_across_five_fits": raw["excess_over_max_capacity"],
                "regressing_ports": [p for p in raw["per_port"] if p["relative_cost_improvement_pct"] < 0],
                "stress": raw["stress"],
                "notice": "This apparent improvement compares absent versus present filtering; it is not an RL algorithm gain. It still fails stress, per-port and excess-violation checks.",
            },
            "safe_results": {
                "relative_cost_improvement_pct": selected["new_port_relative_cost_interval"]["mean_delta"] * 100,
                "seed_violation_totals": seed_totals,
                "maximum_capacity_unique_window_violations": sum(floor.values()),
                "feasible_windows_of64": sum(n == 0 for n in floor.values()),
                "feasible_window_violations": selected["feasible_constraint_violations"],
                "excess_over_maximum": selected["excess_over_max_capacity"],
                "filtered_vs_raw_action_differences": readback["rl_filtered_vs_raw_action_differences"],
                "filtered_vs_raw_action_count": len(safe_runs) * 90,
            },
            "source_reports": [
                {"path": ".runtime/rl-v6-20261030/report.json", "sha256": study.c.sha(study.OUT / "report.json")},
                {
                    "path": ".codex_artifacts/research-v6-20261030/independent-readback.json",
                    "sha256": study.c.sha(OUT / "independent-readback.json"),
                },
            ],
            "posthoc_trace": {"path": str(trace.relative_to(ROOT)), "sha256": study.c.sha(trace)},
            "implementation": {"path": str(Path(__file__).relative_to(ROOT)), "sha256": study.c.sha(Path(__file__))},
            "notice": "The original pre-registered new-port report and all old failures remain immutable. Post-test raw baseline checks diagnose whether the filter alone explains equality; they do not create a new independent test, select a better model or count as additional admission evidence. Repeated fits are not independent port trials. Intrinsic overflow is relative to declared proxy capacity only, not proof of real port impossibility.",
            "production_authority": False,
        },
    )
    print(
        json.dumps(
            {
                "raw_action_differences": action_differences,
                "comparisons": comparisons,
                "seed_violation_totals": seed_totals,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
