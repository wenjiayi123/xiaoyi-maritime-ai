"""Read-only arithmetic audit without importing either new forecast/solver module."""

import copy
import csv
import hashlib
import json
import statistics as stats
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".codex_artifacts/capability-review-v8-20261031"
EXPERIMENT = OUT / "experiment-qualified"


def main():
    report = json.loads((EXPERIMENT / "forecast.json").read_text())
    summary = json.loads((EXPERIMENT / "summary.json").read_text())
    for name, checksum in summary["source_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == checksum, name
    manifest = json.loads((ROOT / "data/public/operations_v5_20261030/manifest.json").read_text())
    series = {}
    for entry in manifest["entries"]:
        with (ROOT / entry["path"]).open() as handle:
            series[entry["id"]] = {date.fromisoformat(r["date"]): float(r["portcalls"]) for r in csv.DictReader(handle)}
    errors, groups = [], {}
    for row in report["traces"]:
        origin, target = date.fromisoformat(row["origin"]), date.fromisoformat(row["target"])
        cutoff = origin - timedelta(days=7)
        assert origin >= date(2025, 1, 8)
        assert (target - origin).days == row["horizon_days"]
        assert row["publication_cutoff"] == row["monitor"]["latest_realized_target"] == cutoff.isoformat()
        available_monitors = sum(
            cutoff - timedelta(days=i + row["horizon_days"]) >= date(2025, 1, 8) for i in range(28)
        )
        assert all(m["n"] == available_monitors for m in row["monitor"]["models"].values())
        mapping = series[row["port_id"]]
        days = [cutoff - timedelta(days=i) for i in reversed(range(84))]
        values = [mapping[d] for d in days]
        scale = max(1.0, stats.mean(values[-28:]))
        model = report["frozen"]["model"]["horizons"][str(row["horizon_days"])]
        checks = {}
        for name in ["candidate", "baseline"]:
            pred = row[name]
            week28 = stats.mean(mapping[d] for d in days[-28:] if d.weekday() == target.weekday())
            expected = {
                "persistence": values[-1],
                "mean7": stats.mean(values[-7:]),
                "weekday28": week28,
                "weekday84": stats.mean(mapping[d] for d in days if d.weekday() == target.weekday()),
                "blend": 0.5 * week28 + 0.5 * stats.mean(values[-7:]),
            }[pred["model"]]
            errors.append(abs(pred["point"] - expected))
            actual = mapping[target]
            wis = 0.5 * abs(expected - actual)
            for level in (0.5, 0.8, 0.9):
                radius = model["radii"][pred["model"]][str(level)] * scale
                low, high = max(0.0, expected - radius), expected + radius
                errors.extend(
                    [abs(pred["intervals"][str(level)][0] - low), abs(pred["intervals"][str(level)][1] - high)]
                )
                alpha = 1 - level
                wis += alpha / 2 * (high - low + 2 / alpha * (max(low - actual, 0) + max(actual - high, 0)))
            low, high = pred["intervals"]["0.9"]
            checks[name] = {
                "mae": abs(expected - actual),
                "wis": wis / 3.5,
                "coverage90": float(low <= actual <= high),
                "width90_normalized": (high - low) / scale,
            }
        groups.setdefault((row["port_id"], target.year, row["horizon_days"]), []).append(checks)
        assert row["actual"] == mapping[target]
        assert not row["production_authority"]
        if row["research_plan_allowed"]:
            assert row["status"] in ["candidate", "baseline"]
            assert available_monitors == 28
    for cell in report["cells"]:
        rows = groups[(cell["port_id"], cell["year"], cell["horizon_days"])]
        for name, key in [("candidate", "all_candidate"), ("baseline", "all_strong_baseline")]:
            for metric in ["mae", "wis", "coverage90", "width90_normalized"]:
                errors.append(abs(cell[key][metric] - stats.mean(r[name][metric] for r in rows)))
    scheduling = json.loads((EXPERIMENT / "scheduling.json").read_text())["cases"]
    physical_checks = 0
    for case in scheduling:
        for scenario_index, name in enumerate(["nominal", "late_arrival", "long_service", "resource_loss", "combined"]):
            p = copy.deepcopy(case["problem"])
            if name in ["late_arrival", "combined"]:
                for job in p["jobs"]:
                    job["release"] += 2
            if name in ["long_service", "combined"]:
                for job in p["jobs"]:
                    job["duration"] += 2
            if name in ["resource_loss", "combined"]:
                p["grid_limit_kw"] = [v * 0.8 for v in p["grid_limit_kw"]]
                p["caps"]["crane"] = [max(0, v - 1) for v in p["caps"]["crane"]]
            loads = [p["base_kw"]] * 48
            uses = {k: [0] * 48 for k in p["caps"]}
            seen = set()
            for action in case["robust"]["schedule"]:
                j, start, berth = p["jobs"][action["job"]], action["start"], action["berth"]
                assert action["job"] not in seen
                seen.add(action["job"])
                end = start + j["duration"]
                assert start - 1 >= j["release"] and end < 48 and j["length_m"] <= [260, 400][berth]
                uses["pilot"][start - 1] += 1
                uses["tug"][start - 1] += 1
                loads[start - 1] += 80
                uses["yard"][end] += 2
                uses["transport"][end] += 1
                loads[end] += 60
                for tick in range(start, end):
                    uses["berth" + str(berth)][tick] += 1
                    uses["crane"][tick] += j["cranes"]
                    uses["transport"][tick] += 2 * j["cranes"]
                    loads[tick] += 450 * j["cranes"] + j["shore_kw"]
            assert all(v <= p["grid_limit_kw"][i] + 1e-8 for i, v in enumerate(loads))
            assert all(v <= p["caps"][k][i] for k, a in uses.items() for i, v in enumerate(a))
            result = case["robust"]["scenarios"][scenario_index]
            assert loads == result["grid_kw"] and uses == result["resource_usage"]
            assert result["completed_calls"] == len(seen)
            assert result["deferred_calls"] == len(p["jobs"]) - len(seen)
            physical_checks += 1
    assert max(errors) < 1e-9
    result = {
        "schema": "xiaoyi-upgrade-independent-readback.v8",
        "passed": True,
        "forecast_traces": len(report["traces"]),
        "forecast_cells": len(report["cells"]),
        "maximum_arithmetic_error": max(errors),
        "scenario_physics_reconstructed": physical_checks,
        "forecast_statuses": dict(Counter(r["status"] for r in report["traces"])),
        "clock_checks": "model availability, publication cutoff, monitor origins, and target lead all passed",
        "boundary": "execution and arithmetic consistency; not physical calibration or independent field validation",
        "production_authority": False,
    }
    with (OUT / "independent-readback.json").open("x") as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
