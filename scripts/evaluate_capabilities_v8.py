"""Append-only retrospective forecast and scenario-robust scheduling evaluation."""

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.harness import predictive_v8 as f, robust_schedule_v8 as robust, portwatch_data, operations_v5 as ops  # noqa: E402


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open("x") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def run(out):
    out.mkdir(parents=True, exist_ok=False)
    original, training = portwatch_data.load_all()
    public = ops.catalog()
    ops.checked(public["primary_export"]["path"], public["primary_export"]["sha256"])
    series = {}
    for entry in public["entries"]:
        path = ops.checked(entry["path"], entry["sha256"])
        with path.open() as handle:
            series[entry["id"]] = [
                {"date": date.fromisoformat(r["date"]), "calls": float(r["portcalls"])} for r in csv.DictReader(handle)
            ]
    model = f.fit(training, portwatch_data.TRAIN_PORTS)
    source_paths = [
        "app/harness/predictive_v8.py",
        "app/harness/robust_schedule_v8.py",
        "app/harness/operations_v5.py",
        "app/harness/portwatch_data.py",
        "scripts/evaluate_capabilities_v8.py",
        ".codex_artifacts/capability-review-v8-20261031/protocol-v2-clock-corrected.json",
        "data/public/operations_v5_20261030/manifest.json",
        "data/public/portwatch_crossport_20261030/manifest.json",
    ]
    sources = {p: sha(ROOT / p) for p in source_paths}
    sources.update({e["path"]: e["sha256"] for e in [*public["entries"], *original["entries"]]})
    frozen = {
        "model": model,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": sources,
        "independence": "retrospective_seen_archive_not_blind_holdout",
        "production_authority": False,
    }
    save(out / "selection-before-audit.json", frozen)
    cells, traces = [], []
    for entry in public["entries"]:
        port = entry["id"]
        mapping = f.validated(series[port])
        for horizon in f.HORIZONS:
            for year in (2025, 2026):
                current = date(year, 1, 22) if year == 2025 else date(year, 1, 15)
                end = min(max(mapping), date(year, 12, 31))
                rows, selected, baseline, persistence, retained = [], [], [], [], []
                statuses = Counter()
                while current <= end:
                    origin = current - timedelta(days=horizon)
                    result = f.forecast(mapping, model, origin, horizon)
                    actual = mapping.get(current)
                    if actual is not None and result.get("candidate"):
                        history = f.history_at(mapping, origin)
                        selected.append(f.scored(result["candidate"], actual, history))
                        baseline.append(f.scored(result["baseline"], actual, history))
                        dist = f.distribution(model["horizons"][str(horizon)], history, current, "persistence")
                        persistence.append(f.scored(dist, actual, history))
                        if result["research_plan_allowed"]:
                            retained.append(f.scored(result["prediction"], actual, history))
                    statuses[result["status"]] += 1
                    rows.append({"port_id": port, "actual": actual, **result})
                    current += timedelta(days=7)
                cell = {
                    "port_id": port,
                    "name": entry["name"],
                    "year": year,
                    "horizon_days": horizon,
                    "expected_samples": len(rows),
                    "all_candidate": f.metrics(selected),
                    "all_strong_baseline": f.metrics(baseline),
                    "all_persistence": f.metrics(persistence),
                    "retained_only": f.metrics(retained),
                    "statuses": dict(statuses),
                    "retained_fraction": len(retained) / len(rows),
                    "production_authority": False,
                }
                cells.append(cell)
                traces.extend(rows)
                print(f"forecast {port}/{year}/h{horizon}: {dict(statuses)}", flush=True)
    forecast_report = {
        "schema": "xiaoyi-forecast-retrospective.v8",
        "frozen": frozen,
        "ports": [{"id": e["id"], "name": e["name"]} for e in public["entries"]],
        "cells": cells,
        "traces": traces,
        "production_authority": False,
    }
    save(out / "forecast.json", forecast_report)
    scheduling = []
    for entry in public["entries"]:
        for scenario in ("normal", "arrival_peak"):
            result = robust.compare(
                ops.OptimizeArgs(port_id=entry["id"], source_day=date(2026, 6, 15), scenario=scenario)
            )
            scheduling.append(result)
            print(
                f"schedule {entry['id']}/{scenario}: nominal failed {result['nominal_failed_scenarios']}, robust {result['robust_failed_scenarios']}",
                flush=True,
            )
    save(out / "scheduling.json", {"cases": scheduling, "production_authority": False})
    summary = {
        "schema": "xiaoyi-capability-upgrade-results.v8",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": sources,
        "forecast_cells": len(cells),
        "forecast_predictions": len(traces),
        "forecast_statuses": dict(Counter(r["status"] for r in traces)),
        "candidate_beats_strong_baseline_mae_cells": sum(
            c["all_candidate"]["mae"] < c["all_strong_baseline"]["mae"] - 1e-9 for c in cells
        ),
        "candidate_ties_strong_baseline_mae_cells": sum(
            abs(c["all_candidate"]["mae"] - c["all_strong_baseline"]["mae"]) <= 1e-9 for c in cells
        ),
        "candidate_beats_persistence_mae_cells": sum(
            c["all_candidate"]["mae"] < c["all_persistence"]["mae"] for c in cells
        ),
        "candidate_90_coverage_pass_cells": sum(c["all_candidate"]["coverage90"] >= 0.8 for c in cells),
        "candidate_width_pass_cells": sum(c["all_candidate"]["width90_normalized"] <= 2 for c in cells),
        "schedule_cases": len(scheduling),
        "declared_scenario_evaluations": len(scheduling) * 5,
        "nominal_failed_scenarios": sum(c["nominal_failed_scenarios"] for c in scheduling),
        "robust_failed_scenarios": sum(c["robust_failed_scenarios"] for c in scheduling),
        "proven_robust_optima": sum(c["robust"]["solver"]["optimality_proven"] for c in scheduling),
        "additional_deferred_jobs": sum(c["additional_deferred_jobs"] for c in scheduling),
        "mean_nominal_cost_increase_points": statistics.mean(c["nominal_cost_increase_points"] for c in scheduling),
        "maximum_nominal_cost_increase_points": max(c["nominal_cost_increase_points"] for c in scheduling),
        "all_scenarios_feasible": all(c["robust"]["all_declared_scenarios_feasible"] for c in scheduling),
        "files": {
            name: {"path": str((out / name).relative_to(ROOT)), "sha256": sha(out / name)}
            for name in ["selection-before-audit.json", "forecast.json", "scheduling.json"]
        },
        "independence": "previously_seen_archive_and_synthetic_orders; no new blind qualification",
        "production_authority": False,
    }
    save(out / "summary.json", summary)
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in {"files", "source_sha256"}}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / ".codex_artifacts/capability-review-v8-20261031/experiment")
    run(parser.parse_args().out.resolve())
