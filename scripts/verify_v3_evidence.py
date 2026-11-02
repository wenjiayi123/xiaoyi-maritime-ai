"""Independent raw-row cost/flow and astronomical/assimilation reconstruction."""

import argparse
import csv
import gzip
import json
import math
import statistics
import sys
from bisect import bisect_left, bisect_right
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
        if "array" in value:
            return np.asarray(decode(value["array"]), dtype=value["dtype"])
        if "complex" in value:
            return complex(*value["complex"])
        return Bunch({k: decode(v) for k, v in value.items()})
    return value


def verify():
    study = json.loads((ROOT / ".runtime/modelbased-v3-20261030/report.json").read_text())
    raw = {}
    for entry in study["sources"]["entries"]:
        path = ROOT / entry["path"]
        assert c.sha(path) == entry["sha256"]
        with path.open() as handle:
            raw[entry["id"]] = {date.fromisoformat(r["date"]): float(r["portcalls"]) for r in csv.DictReader(handle)}
    networks = {}
    for meta in study["ablation"]["models"]:
        path = ROOT / meta["path"]
        assert c.sha(path) == meta["sha256"]
        networks[(meta["condition"], meta["seed"])] = json.loads(path.read_text())
    for meta in study["selection"]["models"] + study["ablation"]["replays"]:
        assert c.sha(ROOT / meta["path"]) == meta["sha256"]
    rollouts = frames = decisions = 0
    max_input = max_cost = max_flow = max_action = 0.
    sampled = set()
    for line in gzip.open(ROOT / study["trace_path"], "rt"):
        run = json.loads(line)
        first = date.fromisoformat(run["start"])
        values = raw[run["port_id"]]
        scale = max(1., statistics.mean(values[first - timedelta(days=i)] for i in range(7, 35)))
        backlog = total = 0.
        previous = 1.
        key = (run["algorithm"], run["seed"])
        neural = key in networks and (*key, run["scenario"]) not in sampled and run["scenario"] in ["normal", "publication_delay"]
        if neural:
            sampled.add((*key, run["scenario"]))
            payload = networks[key]
            params = [np.asarray(p) for p in payload["params"]]
            env = c.Episode([(first + timedelta(days=i), values[first + timedelta(days=i)]) for i in range(-42, 90)],
                            study["selection"]["forecast"], run["scenario"], tuple(payload["gains"]))
        assert len(run["frames"]) == 90
        for index, frame in enumerate(run["frames"]):
            day = first + timedelta(days=index)
            arrival = values[day] * (1.5 if run["scenario"] == "demand_surge" and 20 <= index < 50 else 1.)
            availability = .5 if run["scenario"] == "resource_outage" and 30 <= index < 44 else 1.
            factor = [.65, .85, 1., 1.15, 1.35][frame["action"]]
            assert availability == 1. or frame["action"] <= 2
            served = min(backlog + arrival, scale * factor * availability)
            backlog = backlog + arrival - served
            ratio = backlog / scale
            cost = ratio + .5 * factor**2 + .05 * abs(factor - previous) + max(0, ratio - 4) * 5 + (2 * ratio if index == 89 else 0)
            total += cost
            lag = 14 if run["scenario"] == "publication_delay" else 7
            assert frame["public_latest_day"] == (day - timedelta(days=lag)).isoformat()
            max_input = max(max_input, abs(arrival - frame["arrival_indicator"]), abs(served - frame["service_proxy"]))
            max_flow = max(max_flow, abs(backlog - frame["backlog_proxy"]))
            max_cost = max(max_cost, abs(cost - frame["cost_proxy"]))
            if neural:
                f, mask, _ = env.features()
                w, b, a, ac, v, vc = params
                h = np.maximum(0, np.asarray(f) @ w + b)
                advantage = h @ a + ac
                q = h @ v + vc + advantage - advantage.mean()
                action = max((i for i in range(5) if mask[i]), key=lambda i: q[i])
                max_action = max(max_action, abs(action - frame["action"]))
                env.step(action)
                decisions += 1
            previous = factor
            frames += 1
        assert abs(-total / 90 - run["score"]) < 1e-9
        rollouts += 1
    assert rollouts == len(study["runs"]) and frames == 90 * rollouts

    physical = json.loads((ROOT / "data/public/physical_twin_v3_20261030/report.json").read_text())
    observed = {}
    utc = timezone.utc
    for entry in physical["sources"]["entries"]:
        path = ROOT / entry["path"]
        assert c.sha(path) == entry["sha256"]
        if entry["provider_error"]:
            continue
        noaa = entry["provider"] == "noaa"
        if noaa:
            records = json.loads(path.read_text())["data"]
        else:
            with path.open() as handle:
                reader = csv.DictReader(handle)
                next(reader)
                records = list(reader)
        own = observed.setdefault(entry["station_id"], {})
        for row in records:
            try:
                value = float(row["v"]) if noaa else float(row["sea_level"]) / 1000
                valid = row.get("q", "v") == "v" and all(x == "0" for x in row["f"].split(",")) if noaa else int(row["quality"]) >= 3
            except (TypeError, ValueError):
                continue
            if not valid or not math.isfinite(value) or value <= -32:
                continue
            at = datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=utc) if noaa else datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            if at.year == 2026:
                if at in own:
                    assert abs(own[at] - value) <= .001001
                else:
                    own[at] = value
    predictions, error_history = {}, {}
    models = {m["station_id"]: m for m in physical["selection"]["models"]}
    for sid, model in models.items():
        chosen = model["selected"]
        coef = decode(json.loads((ROOT / chosen["coefficient_path"]).read_text()))
        times = sorted(observed[sid])
        base = utide.reconstruct(np.asarray([t.replace(tzinfo=None) for t in times], dtype="datetime64[ns]"), coef,
                                 min_SNR=0, verbose=False).h
        corrections = chosen["correction_coefficients"]
        tide = {}
        for t, value in zip(times, base):
            phase = (t.timetuple().tm_yday - 1) / 365.25 * 2 * math.pi
            vector = [0.] if chosen["correction"] == "none" else ([1.] if chosen["correction"] == "intercept" else [1., math.sin(phase), math.cos(phase)])
            tide[t] = float(value + sum(a * b for a, b in zip(vector, corrections)))
        predictions[(sid, None)] = tide
        for choice in model["short_choices"]:
            horizon, resolution = choice["horizon"], choice["resolution"]
            own = {}
            errors = {}
            for at in times:
                if at.minute % resolution:
                    continue
                cutoff = at - timedelta(minutes=horizon)
                past = [cutoff - timedelta(minutes=resolution * i) for i in range(choice["memory"])]
                if any(t not in tide for t in past):
                    continue
                predicted = tide[at] + statistics.mean(observed[sid][t] - tide[t] for t in past)
                own[at] = predicted
                errors[at] = predicted - observed[sid][at]
            predictions[(sid, horizon)] = own
            error_history[(sid, horizon)] = (sorted(errors), errors)
    points = 0
    max_tide = max_radius = 0.
    for line in gzip.open(ROOT / physical["trace_path"], "rt"):
        row = json.loads(line)
        sid = row["station_id"]
        at = datetime.fromisoformat(row["at"])
        horizon = row.get("horizon_minutes")
        assert row["actual_m"] == observed[sid][at]
        predicted = predictions[(sid, horizon)][at]
        max_tide = max(max_tide, abs(predicted - row["predicted_m"]))
        model = models[sid]
        if horizon is None:
            radius = model["quarter_radii_m"][str((at.month - 1) // 3 + 1)]
        else:
            cutoff = at - timedelta(minutes=horizon)
            assert datetime.fromisoformat(row["input_cutoff"]) == cutoff
            assert datetime.fromisoformat(row["interval_latest_label"]) <= cutoff
            choice = next(c for c in model["short_choices"] if c["horizon"] == horizon)
            ordered, errors = error_history[(sid, horizon)]
            lo, hi = bisect_left(ordered, cutoff - timedelta(days=14)), bisect_right(ordered, cutoff)
            calibration = sorted(abs(errors[t]) for t in ordered[lo:hi])
            radius = choice["radius_m"]
            if len(calibration) >= 50:
                ix = min(len(calibration) - 1, math.ceil((len(calibration) + 1) * physical["protocol"]["interval_quantile"]) - 1)
                radius = max(radius, calibration[ix] * physical["protocol"]["interval_margin"])
        max_radius = max(max_radius, abs(radius - row["radius_m"]))
        points += 1
    checks = {"all_rollouts_and_frames": rollouts == len(study["runs"]), "primary_input_flow_cost": max(max_input, max_flow, max_cost) < 1e-9,
              "all_saved_network_hashes": len(networks) == 35, "independent_neural_actions": max_action == 0 and decisions == 2700,
              "all_tide_points_and_causal_intervals": max_tide < 1e-10 and max_radius < 1e-10,
              "all_physical_cells_including_missing": len(physical["results"]) == 75}
    return {"schema": "xiaoyi-independent-v3-readback", "passed": all(checks.values()), "checks": checks,
            "rollouts": rollouts, "frames": frames, "saved_networks_hash_checked": len(networks), "neural_action_decisions": decisions,
            "physical_points": points, "maximum_input_error": max_input, "maximum_flow_error": max_flow,
            "maximum_cost_error": max_cost, "maximum_neural_action_error": max_action,
            "maximum_tide_prediction_error": max_tide, "maximum_interval_radius_error": max_radius,
            "notice": "Raw CSV/JSON values, costs and conservation reconstructed independently. Sampled complete neural traces use independent arithmetic; astronomical coefficients decoded from JSON. This checks execution, not successful field performance or all model-based policy table decisions.",
            "production_authority": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.out and args.out.exists():
        raise ValueError("refuse to overwrite accepted evidence")
    result = verify()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if not result["passed"]:
        sys.exit(1)
