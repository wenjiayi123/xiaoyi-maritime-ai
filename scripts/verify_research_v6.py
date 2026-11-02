"""Independent arithmetic/source readback of frozen research, not scientific peer review."""

import csv
import gzip
import io
import json
import math
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

from app.harness.physical_v2 import sha, write

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".codex_artifacts/research-v6-20261030"
FACTORS = [0.65, 0.85, 1.0, 1.15, 1.35]


def main():
    target = OUT / "independent-readback.json"
    if target.exists():
        raise ValueError("never overwrite a completed readback")
    learning = json.loads((ROOT / ".runtime/rl-v6-20261030/report.json").read_text())
    physical = json.loads((ROOT / "data/public/long_twin_v6_20261030/report.json").read_text())
    source = {}
    for e in learning["sources"]["entries"]:
        with (ROOT / e["path"]).open() as handle:
            source[e["id"]] = {date.fromisoformat(r["date"]): float(r["portcalls"]) for r in csv.DictReader(handle)}
    count, frames, maximum_error, mismatches = 0, 0, 0.0, []
    paired_actions = {}
    with gzip.open(ROOT / learning["trace_path"], "rt") as handle:
        for line in handle:
            row = json.loads(line)
            start = date.fromisoformat(row["start"])
            lag = 14 if row["scenario"] == "publication_delay" else 7
            cutoff = start - timedelta(days=lag)
            scale = max(1.0, statistics.mean(source[row["port_id"]][cutoff - timedelta(days=i)] for i in range(28)))
            backlog, previous, cost, violations = 0.0, 2, 0.0, 0
            for i, f in enumerate(row["frames"]):
                at = start + timedelta(days=i)
                arrival = source[row["port_id"]][at] * (
                    1.5 if row["scenario"] == "demand_surge" and 20 <= i < 50 else 1
                )
                avail = 0.5 if row["scenario"] == "resource_outage" and 30 <= i < 44 else 1.0
                a = f["action"]
                end = max(0, backlog + arrival - scale * FACTORS[a] * avail)
                ratio = end / scale
                step_cost = (
                    ratio
                    + 0.5 * FACTORS[a] ** 2
                    + 0.05 * abs(FACTORS[a] - FACTORS[previous])
                    + 5 * max(0, ratio - 4)
                    + (2 * ratio if i == 89 else 0)
                )
                maximum_error = max(
                    maximum_error,
                    abs(end - f["backlog_proxy"]),
                    abs(step_cost - f["cost_proxy"]),
                    abs(arrival - f["arrival_indicator"]),
                )
                if (
                    a not in range(5)
                    or (avail < 0.75 and a > 2)
                    or f["public_latest_day"] != (at - timedelta(days=lag)).isoformat()
                    or f["capacity_scale_input_latest_day"] != cutoff.isoformat()
                ):
                    mismatches.append(
                        {"algorithm": row["algorithm"], "window": row["window"], "i": i, "kind": "action_mask_or_clock"}
                    )
                violations += ratio > 4
                backlog, previous, cost = end, a, cost + step_cost
                frames += 1
            maximum_error = max(maximum_error, abs(row["score"] + cost / 90))
            if len(row["frames"]) != 90 or violations != row["constraint_violations"]:
                mismatches.append({"window": row["window"], "kind": "length_or_violations"})
            paired_actions[row["algorithm"], row["seed"], row["window"], row["scenario"]] = [
                f["action"] for f in row["frames"]
            ]
            count += 1
    # The maximum-capacity comparator supplies a lower bound for queue violations,
    # not proof that real-world capacity cannot be augmented.
    raw_filtered_differences = sum(
        sum(a != b for a, b in zip(actions, paired_actions["offline_rl90.none", seed, window, scenario]))
        for (name, seed, window, scenario), actions in paired_actions.items()
        if name == learning["selection"]["selected_rl"]
    )
    stochastic_differences = sum(
        sum(a != b for a, b in zip(actions, paired_actions["stochastic_mpc28.old_reserve", seed, window, scenario]))
        for (name, seed, window, scenario), actions in paired_actions.items()
        if name == learning["selection"]["selected_rl"]
    )
    truth = {}
    for e in physical["sources"]["test"]["entries"]:
        raw = gzip.decompress((ROOT / e["path"]).read_bytes()).decode(e["encoding"])
        if raw.startswith("Error {") or e["provider_error"]:
            continue
        noaa = e["provider"] == "noaa"
        if noaa:
            records = json.loads(raw)["data"]
        else:
            reader = csv.DictReader(io.StringIO(raw))
            next(reader)
            records = reader
        for r in records:
            try:
                value = float(r["v"]) if noaa else float(r["sea_level"]) / 1000
                ok = (
                    all(v == "0" for v in r["f"].split(",")) and r.get("q", "v") == "v"
                    if noaa
                    else int(r["quality"]) >= 3
                )
            except (ValueError, TypeError):
                continue
            if not ok or not math.isfinite(value) or value <= -32:
                continue
            stamp = (
                datetime.strptime(r["t"], "%Y-%m-%d %H:%M").isoformat() + "+00:00"
                if noaa
                else r["time"].replace("Z", "+00:00")
            )
            truth[e["station_id"], stamp] = value
    tide_points, tide_mismatches, observation_counts, missing_counts = 0, [], {}, {}
    with gzip.open(ROOT / physical["trace_path"], "rt") as handle:
        for line in handle:
            p = json.loads(line)
            actual = truth.get((p["station_id"], p["at"]))
            if p["actual_m"] != actual or p["test_observation_used_as_input"]:
                tide_mismatches.append({"station_id": p["station_id"], "at": p["at"], "kind": "truth_or_test_input"})
            if p["predicted_m"] is not None and (
                not p["forecast_origin"]
                or datetime.fromisoformat(p["at"]) < datetime.fromisoformat(p["forecast_origin"].replace("Z", "+00:00"))
            ):
                tide_mismatches.append({"station_id": p["station_id"], "at": p["at"], "kind": "origin"})
            observation_counts[p["station_id"]] = observation_counts.get(p["station_id"], 0) + (actual is not None)
            missing_counts[p["station_id"]] = missing_counts.get(p["station_id"], 0) + (actual is None)
            tide_points += 1
    checks = {
        "rl_complete_runs": count == len(learning["runs"]),
        "rl_physical_cost_and_flow_arithmetic": maximum_error < 1e-8,
        "rl_clocks_and_masks": not mismatches,
        "tide_primary_truth_units_quality": not tide_mismatches,
        "all_expected_hours_explicit_including_missing": tide_points == 8 * 8760 + 8 * (24 + 23) * 24,
    }
    write(
        target,
        {
            "schema": "xiaoyi-independent-research-readback.v6",
            "passed": all(checks.values()),
            "checks": checks,
            "rl_runs": count,
            "rl_frames": frames,
            "rl_maximum_numeric_error": maximum_error,
            "rl_mismatches": mismatches,
            "rl_filtered_vs_raw_action_differences": raw_filtered_differences,
            "rl_vs_stochastic_mpc_action_differences": stochastic_differences,
            "physical_expected_points": tide_points,
            "physical_valid_observations_by_station": observation_counts,
            "physical_missing_by_station": missing_counts,
            "tide_mismatches": tide_mismatches,
            "source_reports": [
                {
                    "path": ".runtime/rl-v6-20261030/report.json",
                    "sha256": sha(ROOT / ".runtime/rl-v6-20261030/report.json"),
                },
                {
                    "path": "data/public/long_twin_v6_20261030/report.json",
                    "sha256": sha(ROOT / "data/public/long_twin_v6_20261030/report.json"),
                },
            ],
            "notice": "Separate raw decoding and arithmetic reconstructs the stored physical cost, truth, missing hours, clocks and masks without invoking the training or simulation step implementation. This is local internal readback, not external peer review or evidence that the declared service proxy is real terminal physics. Model-blocked cells may still contain valid observations; n is scored points, not raw truth availability.",
            "production_authority": False,
        },
    )
    print(
        json.dumps(
            {
                "passed": all(checks.values()),
                "checks": checks,
                "runs": count,
                "frames": frames,
                "tide_expected": tide_points,
            }
        ),
        flush=True,
    )
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
