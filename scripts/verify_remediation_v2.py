"""Independent raw-input, conservation, saved-network and astronomical reconstruction."""

import argparse
import csv
import gzip
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import utide
from utide.utilities import Bunch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.harness import crossport_v2 as c  # noqa: E402


def decode(value):
    if isinstance(value, list):
        return [decode(v) for v in value]
    if isinstance(value, dict):
        if "array" in value and "dtype" in value:
            return np.asarray(decode(value["array"]), dtype=value["dtype"])
        if "complex" in value:
            return complex(*value["complex"])
        return Bunch({k: decode(v) for k, v in value.items()})
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, help="optional new receipt path; never overwrite sealed acceptance")
    args = parser.parse_args()
    report = json.loads((c.OUT / "report.json").read_text())
    guided = json.loads((ROOT / ".runtime/guided-rl-v2-20261030/report.json").read_text())
    manifest, series = c.load()
    reference = {pid: dict(rows) for pid, rows in series.items()}
    networks = {}
    for meta in report["selection"]["models"] + guided["selection"]["models"]:
        value = json.loads((ROOT / meta["path"]).read_text())
        networks[(value["name"], value["seed"])] = value
    seen = set()
    frames = rollouts = decisions = lag_errors = action_errors = 0
    max_input = max_flow = max_cost = max_service = 0.0
    factors = [0.65, 0.85, 1, 1.15, 1.35]
    for study in [report, guided]:
        with gzip.open(ROOT / study["trace_path"], "rt") as handle:
            for line in handle:
                run = json.loads(line)
                first = date.fromisoformat(run["start"])
                values = reference[run["port_id"]]
                scale = max(1, sum(values[first - timedelta(days=i)] for i in range(7, 35)) / 28)
                backlog = cost = 0.0
                previous = 1.0
                key = (run["algorithm"], run["seed"])
                identity = (*key, run["scenario"])
                neural = key in networks and identity not in seen and run["scenario"] in {"normal", "publication_delay"}
                if neural:
                    seen.add(identity)
                    model = networks[key]
                    records = [(first + timedelta(days=i), values[first + timedelta(days=i)]) for i in range(-42, 90)]
                    env = c.Episode(
                        records, report["selection"]["forecast"]["selected"], run["scenario"], tuple(model["gains"])
                    )
                if len(run["frames"]) != 90:
                    raise ValueError("incomplete rollout")
                for i, frame in enumerate(run["frames"]):
                    actual = values[date.fromisoformat(frame["date"])] * (
                        1.5 if run["scenario"] == "demand_surge" and 20 <= i < 50 else 1
                    )
                    availability = 0.5 if run["scenario"] == "resource_outage" and 30 <= i < 44 else 1
                    action = frame["action"]
                    service = min(backlog + actual, scale * factors[action] * availability)
                    end = backlog + actual - service
                    ratio = end / scale
                    expected_cost = (
                        ratio
                        + 0.5 * factors[action] ** 2
                        + 0.05 * abs(factors[action] - previous)
                        + max(0, ratio - 4) * 5
                        + (2 * ratio if i == 89 else 0)
                    )
                    max_input = max(max_input, abs(actual - frame["arrival_indicator"]))
                    max_flow = max(max_flow, abs(end - frame["backlog_proxy"]))
                    max_service = max(max_service, abs(service - frame["service_proxy"]))
                    max_cost = max(max_cost, abs(expected_cost - frame["cost_proxy"]))
                    lag_errors += (
                        date.fromisoformat(frame["date"]) - date.fromisoformat(frame["public_latest_day"])
                    ).days != (14 if run["scenario"] == "publication_delay" else 7)
                    if neural:
                        f, mask, _ = env.features()
                        params = [np.asarray(p) for p in model.get("params", [])]
                        if len(params) == 4:
                            w, b, v, vc = params
                            q = np.maximum(0, np.asarray(f) @ w + b) @ v + vc
                        else:
                            w, b, a, ac, v, vc = params
                            h = np.maximum(0, np.asarray(f) @ w + b)
                            advantages = h @ a + ac
                            q = h @ v + vc + advantages - advantages.mean()
                        chosen = max((a for a in range(5) if mask[a]), key=lambda a: q[a])
                        action_errors += chosen != action
                        env.step(chosen)
                        decisions += 1
                    backlog, previous = end, factors[action]
                    cost += expected_cost
                    frames += 1
                if abs(run["score"] + cost / 90) > 1e-8:
                    raise ValueError("score mismatch")
                rollouts += 1
    folder = ROOT / "data/public/physical_twin_v2_20261030"
    physical = json.loads((folder / "report.json").read_text())
    observed = {}
    for entry in physical["sources"]["entries"]:
        dest = observed.setdefault(entry["station_id"], {})
        path = ROOT / entry["path"]
        if entry["provider"] == "noaa":
            for row in json.loads(path.read_text())["data"]:
                try:
                    value = float(row["v"])
                except (ValueError, TypeError):
                    continue
                if math.isfinite(value) and row.get("q", "v") == "v" and all(f == "0" for f in row["f"].split(",")):
                    dest[datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)] = value
        else:
            with path.open() as handle:
                rows = csv.DictReader(handle)
                next(rows)
                for row in rows:
                    try:
                        value = float(row["sea_level"]) / 1000
                        valid = int(row["quality"]) >= 3 and math.isfinite(value) and value > -32
                    except (ValueError, TypeError):
                        continue
                    if valid:
                        dest[datetime.fromisoformat(row["time"].replace("Z", "+00:00"))] = value
    models = {m["station_id"]: m for m in physical["selection"]["models"]}
    tides = {}
    for sid, model in models.items():
        coef = decode(json.loads((ROOT / model["coefficient_path"]).read_text()))
        times = sorted(t for t in observed[sid] if t.year == 2026)
        prediction = utide.reconstruct(
            np.asarray([t.replace(tzinfo=None) for t in times], dtype="datetime64[ns]"), coef, min_SNR=0, verbose=False
        ).h
        tides[sid] = dict(zip(times, prediction))
    points = bad_cutoff = 0
    max_actual = max_prediction = 0.0
    with gzip.open(ROOT / physical["trace_path"], "rt") as handle:
        for line in handle:
            row = json.loads(line)
            sid = row["station_id"]
            target = datetime.fromisoformat(row["at"])
            expected = tides[sid][target]
            if row["kind"] == "short_assimilation":
                horizon = row["horizon_minutes"]
                choice = next(ch for ch in models[sid]["short_choices"] if ch["horizon"] == horizon)
                cutoff = target - timedelta(minutes=horizon)
                bad_cutoff += cutoff.isoformat() != row["input_cutoff"]
                times = [
                    cutoff - timedelta(minutes=choice["resolution"] * k) for k in range(choice["selected"]["memory"])
                ]
                expected += sum(observed[sid][t] - tides[sid][t] for t in times) / len(times)
            max_actual = max(max_actual, abs(observed[sid][target] - row["actual_m"]))
            max_prediction = max(max_prediction, abs(expected - row["predicted_m"]))
            points += 1
    checks = {
        "all_expected_rollouts": rollouts == 2976,
        "all_expected_frames": frames == 267840,
        "all_saved_networks": len(networks) == 25 and len(seen) == 50 and decisions == 4500,
        "raw_source_values": max_input < 1e-8 and max_actual < 1e-8,
        "queue_service_and_cost": max(max_flow, max_service, max_cost) < 1e-8,
        "causal_public_and_sensor_clocks": lag_errors == bad_cutoff == 0,
        "independent_network_actions": action_errors == 0,
        "serialized_astronomical_coefficients_replay": max_prediction < 1e-8,
    }
    checks = {key: bool(value) for key, value in checks.items()}
    result = {
        "passed": all(checks.values()),
        "checks": checks,
        "rollouts": rollouts,
        "frames": frames,
        "neural_decisions": decisions,
        "physical_points": points,
        "maximum_source_error": max(max_input, max_actual),
        "maximum_flow_error": max_flow,
        "maximum_service_error": max_service,
        "maximum_cost_error": max_cost,
        "maximum_tide_prediction_error": max_prediction,
        "notice": "Every stored outcome reconstructed from primary rows;25 saved networks replayed through independent forward formulas; UTide coefficients loaded from JSON without pickle. This verifies execution, not all research/field performance gates.",
        "production_authority": False,
    }
    if args.out is not None:
        target = args.out if args.out.is_absolute() else ROOT / args.out
        if target.exists():
            raise ValueError("choose a new independent readback receipt path; sealed evidence cannot be overwritten")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
