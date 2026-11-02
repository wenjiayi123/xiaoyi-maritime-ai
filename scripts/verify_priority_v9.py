"""Independent trace arithmetic and freeze/chronology checks, without model helpers."""

import csv
import gzip
import hashlib
import json
import statistics as stats
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".codex_artifacts/priority-v9-20261031"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    return json.loads((ROOT / p).read_text())


def close(a, b):
    assert abs(a - b) < 1e-9, (a, b)


def main():
    frozen = [
        "data/public/interval_v9_20261031/selection-before-test.json",
        "data/public/annual_v9_20261031/selection-before-test.json",
        ".runtime/rl-v9-20261031/selection-before-test.json",
    ]
    for path in frozen:
        for source, checksum in read(path)["source_sha256"].items():
            assert sha(ROOT / source) == checksum, source
    annual_selection = read(frozen[1])
    manifest = read("data/public/annual_v9_20261031/test-manifest.json")
    assert all(e["retrieved_at"] > annual_selection["frozen_at"] for e in manifest["entries"])
    raw_truth = {}
    for entry in manifest["entries"]:
        path = ROOT / entry["path"]
        assert sha(path) == entry["sha256"]
        body = json.loads(gzip.decompress(path.read_bytes()))
        raw_truth[entry["station_id"]] = {
            r["t"]: float(r["v"]) for r in body.get("data", []) if r.get("q", "v") == "v" and r.get("f") == "0,0"
        }

    f = read("data/public/interval_v9_20261031/report.json")
    forecasts = 0
    trace_path = f["trace"]["path"]
    assert sha(ROOT / trace_path) == f["trace"]["sha256"]
    with gzip.open(ROOT / trace_path, "rt") as handle:
        for cell in map(json.loads, handle):
            records = [r for r in cell["rows"] if r.get("prediction") and r.get("actual") is not None]
            covered, normalized_wis, widths = [], [], []
            for row in records:
                origin, cutoff = date.fromisoformat(row["origin"]), date.fromisoformat(row["publication_cutoff"])
                assert cutoff == origin - timedelta(days=7)
                assert date.fromisoformat(row["target"]) == origin + timedelta(days=cell["horizon_days"])
                assert date.fromisoformat(row["calibration_latest_day"]) <= cutoff
                if row["last_feedback_target"]:
                    assert date.fromisoformat(row["last_feedback_target"]) <= cutoff
                y, point, intervals = row["actual"], row["prediction"]["point"], row["prediction"]["intervals"]
                total = 0.5 * abs(y - point)
                for level, (lower, upper) in intervals.items():
                    alpha = 1 - float(level)
                    assert lower <= point <= upper
                    score = upper - lower + 2 / alpha * (max(0, lower - y) + max(0, y - upper))
                    total += alpha / 2 * score
                wis = total / (len(intervals) + 0.5)
                close(wis, row["wis"])
                lower, upper = intervals["0.9"]
                covered.append(lower <= y <= upper)
                normalized_wis.append(wis / row["scale"])
                widths.append((upper - lower) / row["scale"])
                forecasts += 1
            summary = cell["summary"]
            close(stats.mean(covered), summary["coverage90"])
            close(stats.mean(normalized_wis), summary["normalized_wis"])
            close(stats.mean(widths), summary["mean_width90_normalized"])
            assert len(records) / summary["expected"] >= 0.95

    annual = read("data/public/annual_v9_20261031/report.json")
    assert sha(ROOT / annual["trace_path"]) == annual["trace_sha256"]
    annual_rows = 0
    with gzip.open(ROOT / annual["trace_path"], "rt") as handle:
        for cell in map(json.loads, handle):
            assert len(cell["rows"]) == 8760
            assert len({r["time"] for r in cell["rows"]}) == 8760
            for row in cell["rows"]:
                key = datetime.fromisoformat(row["time"]).strftime("%Y-%m-%d %H:%M")
                assert row["actual"] == raw_truth[cell["station_id"]].get(key)
                annual_rows += 1
            for quarter in [None, "1", "2", "3", "4"]:
                rows = [r for r in cell["rows"] if quarter is None or r["quarter"] == quarter]
                summary = cell["annual"] if quarter is None else cell["quarters"][quarter]
                known = [r for r in rows if r["prediction"] is not None and r["actual"] is not None]
                close(len(known) / len(rows), summary["availability"])
                if known:
                    close(stats.mean(abs(r["prediction"] - r["actual"]) for r in known), summary["mae_m"])
                    close(stats.mean(r["lower"] <= r["actual"] <= r["upper"] for r in known), summary["coverage90"])
                    close(max(r["upper"] - r["lower"] for r in known), summary["max_width90_m"])

    rl = read(".runtime/rl-v9-20261031/report.json")
    assert sha(ROOT / rl["trace_path"]) == rl["trace_sha256"]
    steps, runs, action_changes = 0, 0, 0
    signatures = {}
    with gzip.open(ROOT / rl["trace_path"], "rt") as handle:
        for run in map(json.loads, handle):
            assert len(run["frames"]) == 90
            assert run["maximum_flow_error"] < 1e-7 and run["production_authority"] is False
            close(-sum(r["cost_proxy"] for r in run["frames"]) / 90, run["score"])
            assert sum(r["constraint_violation"] for r in run["frames"]) == run["constraint_violations"]
            for frame in run["frames"]:
                assert date.fromisoformat(frame["public_latest_day"]) <= date.fromisoformat(frame["date"]) - timedelta(
                    days=7
                )
            runs += 1
            steps += len(run["frames"])
            close(stats.mean(bool(r["safety_override"]) for r in run["frames"]), run["safety_override_fraction"])
            # Read the actual executed trajectory, not a label or expected counter.
            signatures[run["algorithm"], run["seed"], run["window"], run["scenario"]] = [
                r["action"] for r in run["frames"]
            ]
    candidate = next(r for r in rl["aggregate"] if r["algorithm"] == "constrained.reserve")
    for key, acts in signatures.items():
        name, seed, window, scenario = key
        if name == "constrained.reserve":
            base = signatures[candidate["matched_baseline"], 0, window, scenario]
            action_changes += sum(a != b for a, b in zip(acts, base))
    for row in rl["aggregate"]:
        assert row["research_admission"] == all(row["checks"].values())
    result = {
        "passed": True,
        "frozen_sources_unchanged": True,
        "test_acquisition_after_model_freeze": True,
        "forecast_rows_all_three_methods": forecasts,
        "annual_rows_both_methods_including_missing": annual_rows,
        "rl_runs": runs,
        "rl_steps": steps,
        "rl_executed_action_differences_from_selected_baseline": action_changes,
        "annual_actual_truth_availability": {sid: len(values) / 8760 for sid, values in raw_truth.items()},
        "production_authority": False,
    }
    (OUT / "independent-readback.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
