"""Reconstruct causal queue memory, filters, costs and frozen-run tide predictions."""

import argparse
import csv
import gzip
import json
import math
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import utide
from utide.utilities import Bunch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.harness.crossport_forecast import predict  # noqa: E402


def decode(v):
    if isinstance(v, list):
        return [decode(x) for x in v]
    if isinstance(v, dict):
        if "array" in v:
            return np.asarray(decode(v["array"]), dtype=v["dtype"])
        if "complex" in v:
            return complex(*v["complex"])
        return Bunch({k: decode(x) for k, x in v.items()})
    return v


def threshold_action(table, queue, demand, volatility, availability, remaining, previous):
    if queue > 12 or demand > 3:
        return 4 if availability == 1 else 2
    di = float(np.clip((demand - .4) / .05, 0, 52))
    vi = float(np.clip(np.interp(volatility, [.025, .05, .1, .2, .3, .5, .8, 1.2], range(8)), 0, 7))
    horizons = list(range(1, 15)) + [28, 90]
    h = remaining if remaining <= 14 else (28 if remaining <= 28 else 90)
    boundary = np.zeros(4)
    for d, dw in [(int(di), 1 - di % 1), (min(int(di) + 1, 52), di % 1)]:
        for v, vw in [(int(vi), 1 - vi % 1), (min(int(vi) + 1, 7), vi % 1)]:
            boundary += dw * vw * table[d, v, int(availability >= .75), horizons.index(h), previous]
    return min(int(np.sum(queue + 1e-10 >= boundary)), 4 if availability == 1 else 2)


def verify():
    report = json.loads((ROOT / ".runtime/robust-v4-20261030/report.json").read_text())
    selection = report["selection"]
    values = {}
    for entry in report["sources"]["entries"]:
        with (ROOT / entry["path"]).open() as handle:
            values[entry["id"]] = {date.fromisoformat(r["date"]): float(r["portcalls"]) for r in csv.DictReader(handle)}
    tables = {m["name"]: np.load(ROOT / m["path"])["thresholds"] for m in selection["models"]}
    guards = {g["name"]: g for g in report["protocol"]["safety_filters"]}
    factors = [.65, .85, 1., 1.15, 1.35]
    frames = rollouts = decisions = action_errors = clock_errors = 0
    max_cost = max_flow = max_nowcast = max_source = 0.
    paired_actions = {}
    for line in gzip.open(ROOT / report["trace_path"], "rt"):
        run = json.loads(line)
        first = date.fromisoformat(run["start"])
        source = values[run["port_id"]]
        scale = max(1., statistics.mean(source[first - timedelta(days=i)] for i in range(7, 35)))
        queue = total = 0.
        previous = 2
        estimate = None
        action_series = []
        for i, frame in enumerate(run["frames"]):
            day = first + timedelta(days=i)
            lag = 14 if run["scenario"] == "publication_delay" else 7
            history = [(first + timedelta(days=j), source[first + timedelta(days=j)] * (
                1.5 if run["scenario"] == "demand_surge" and 20 <= j < 50 else 1.)) for j in range(-42, i - lag + 1)]
            public = predict(selection["forecast"]["selected"], history, day)
            demand = public if estimate is None or selection["alpha"] == 0 else max(public, estimate)
            past = [v for _, v in history[-28:]]
            sigma = max(1., statistics.pstdev(past), math.sqrt(max(1., statistics.mean(past))))
            availability = .5 if run["scenario"] == "resource_outage" and 30 <= i < 44 else 1.
            raw = frame["raw_learned_or_baseline_action"]
            if run["algorithm"].startswith("risk_"):
                expected = threshold_action(tables[run["algorithm"].rsplit(".", 1)[0]], queue / scale,
                    demand / scale, sigma / scale, availability, 90 - i, previous)
                action_errors += int(raw != expected)
                decisions += 1
            guard = guards[frame["safety_filter"]]
            expected_action = raw
            if guard["name"] != "none":
                upper = demand / scale + guard["sigma"] * sigma / scale
                allowed = [a for a in range(5) if (a <= 2 or availability == 1) and max(0., queue / scale + upper - factors[a] * availability) <= guard["queue_budget"]]
                expected_action = max(raw, min(allowed)) if allowed else (4 if availability == 1 else 2)
            action_errors += int(frame["action"] != expected_action)
            action = frame["action"]
            actual = source[day] * (1.5 if run["scenario"] == "demand_surge" and 20 <= i < 50 else 1.)
            capacity = scale * factors[action] * availability
            before = queue
            served = min(queue + actual, capacity)
            queue += actual - served
            ratio = queue / scale
            cost = ratio + .5 * factors[action] ** 2 + .05 * abs(factors[action] - factors[previous]) + max(0., ratio - 4) * 5 + (2 * ratio if i == 89 else 0)
            total += cost
            max_cost = max(max_cost, abs(cost - frame["cost_proxy"]))
            max_source = max(max_source, abs(actual - frame["arrival_indicator"]), abs(served - frame["service_proxy"]))
            max_flow = max(max_flow, abs(queue - frame["backlog_proxy"]))
            max_nowcast = max(max_nowcast, abs(public - frame["public_forecast_proxy"]), abs(demand - frame["causal_nowcast_proxy"]))
            clock_errors += int(frame["public_latest_day"] != (day - timedelta(days=lag)).isoformat())
            clock_errors += int(frame["nowcast_latest_queue_day"] != ((day - timedelta(days=1)).isoformat() if i else None))
            prior_estimate = public if estimate is None else estimate
            estimate = (1 - selection["alpha"]) * prior_estimate + selection["alpha"] * max(0., queue - before + capacity) if queue > 1e-9 else public
            previous = action
            action_series.append(action)
            frames += 1
        assert abs(-total / 90 - run["score"]) < 1e-9
        if run["algorithm"] in [selection["selected_rl"], selection["selected_safe_mpc"]]:
            paired_actions[(run["algorithm"], run["window"], run["scenario"])] = action_series
        rollouts += 1
    same_safe = all(actions == paired_actions[(selection["selected_safe_mpc"], w, scenario)]
                    for (name, w, scenario), actions in paired_actions.items() if name == selection["selected_rl"])

    physical = json.loads((ROOT / "data/public/forecast_forcing_v4_20261030/report.json").read_text())
    old_manifest = json.loads((ROOT / physical["sources"]["water_history_manifest"]["path"]).read_text())
    observed = {}
    for entry in old_manifest["entries"] + [e for e in physical["sources"]["entries"] if e["kind"] == "noaa_observed"]:
        path = ROOT / entry["path"]
        noaa = entry.get("provider", "noaa") == "noaa"
        if noaa:
            raw = json.loads(path.read_text())
            rows = raw.get("data", [])
        else:
            with path.open() as handle:
                reader = csv.DictReader(handle)
                next(reader)
                rows = list(reader)
        sid = entry.get("station_id", entry.get("id"))
        own = observed.setdefault(sid, {})
        for row in rows:
            try:
                value = float(row["v"]) if noaa else float(row["sea_level"]) / 1000
                valid = row.get("q", "v") == "v" and all(x == "0" for x in row["f"].split(",")) if noaa else int(row["quality"]) >= 3
            except (ValueError, TypeError):
                continue
            if not valid or not math.isfinite(value) or value <= -32:
                continue
            at = datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc) if noaa else datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            if at.year == 2026:
                own[at] = value
    weather = {}
    for entry in physical["sources"]["entries"]:
        if entry["kind"] != "weather" or entry["role"] != "test":
            continue
        payload = json.loads((ROOT / entry["path"]).read_text())
        for sid, data in zip(entry["stations_in_request_order"], payload):
            hourly = data["hourly"]
            weather[(sid, entry["id"])] = {datetime.fromisoformat(t).replace(tzinfo=timezone.utc):
                [hourly[k][i] for k in ["pressure_msl", "wind_speed_10m", "wind_direction_10m"]]
                for i, t in enumerate(hourly["time"])}
    models = {(m["station_id"], m["mode"]): m for m in physical["selection"]["models"]}
    trace_rows = [json.loads(line) for line in gzip.open(ROOT / physical["trace_path"], "rt")]
    tide = {}
    for sid in observed:
        times = sorted({datetime.fromisoformat(row[field]) for row in trace_rows if row["station_id"] == sid for field in ["at", "issue"]})
        if not times:
            continue
        for basis in [0, 1]:
            coef = decode(json.loads((ROOT / f"data/public/physical_twin_v3_20261030/coefficients-{sid}-{basis}.json").read_text()))
            output = utide.reconstruct(np.asarray([t.replace(tzinfo=None) for t in times], dtype="datetime64[ns]"), coef,
                                       min_SNR=0, verbose=False).h
            tide[(sid, basis)] = dict(zip(times, output.tolist()))

    def point(sid, run, model, at):
        pressure, speed, direction = weather[(sid, run)][at]
        angle = math.radians(direction)
        u, v = -speed * math.sin(angle), -speed * math.cos(angle)
        phase = (at.timetuple().tm_yday - 1) / 365.25 * 2 * math.pi
        x = [1., math.sin(phase), math.cos(phase), (model["pressure_mean"] - pressure) / 100, u * abs(u) / 100, v * abs(v) / 100]
        return tide[(sid, model["basis"])][at] + sum(a * b for a, b in zip(x, model["coefficients"]))

    max_tide = max_base = 0.
    cells = {}
    for row in trace_rows:
        sid, run, mode = row["station_id"], row["run"], row["mode"]
        model = models[(sid, mode)]
        at, issue, init = [datetime.fromisoformat(row[k]) for k in ["at", "issue", "weather_initialization"]]
        assert issue >= init + timedelta(hours=8) and at == issue + timedelta(hours=row["lead_hours"])
        assert row["actual_m"] == observed[sid][at]
        for key in ["selected", "strong_baseline"]:
            fitted = model[key]
            predicted = point(sid, run, fitted, at)
            if fitted["mode"] == "causal_initial_water_then_open_loop_7d":
                predicted += (observed[sid][issue] - point(sid, run, fitted, issue)) * math.exp(-row["lead_hours"] / fitted["decay_hours"])
            error = abs(predicted - row["predicted_m" if key == "selected" else "baseline_m"])
            if key == "selected":
                max_tide = max(max_tide, error)
            else:
                max_base = max(max_base, error)
        cells[(sid, run, mode)] = cells.get((sid, run, mode), 0) + 1
    assert all(cells.get((r["station_id"], r["run"], r["mode"]), 0) == r["n"] for r in physical["results"])
    checks = {"all1280rollouts": rollouts == len(report["runs"]) == 1280,
        "all115200frames": frames == 115200, "raw_source_cost_and_flow": max(max_cost, max_flow, max_source) < 1e-9,
        "causal_queue_nowcast_and_clocks": max_nowcast < 1e-9 and clock_errors == 0,
        "frozen_threshold_and_shared_filter_actions": action_errors == 0,
        "same_actions_as_safe_mpc": same_safe, "weather_and_initial_water_predictions": max(max_tide, max_base) < 1e-10,
        "all56physical_cells_including_missing": len(physical["results"]) == 56}
    return {"schema": "xiaoyi-independent-v4-readback", "passed": all(checks.values()), "checks": checks,
        "rollouts": rollouts, "frames": frames, "threshold_policy_decisions": decisions, "action_errors": action_errors,
        "maximum_input_error": max_source, "maximum_flow_error": max_flow, "maximum_cost_error": max_cost,
        "maximum_nowcast_error": max_nowcast, "clock_errors": clock_errors, "physical_points": len(trace_rows),
        "maximum_tide_prediction_error": max_tide, "maximum_strong_baseline_error": max_base,
        "notice": "Execution reconstruction from raw rows, frozen threshold policies and individual meteorological runs. Frozen demand forecast reference function and standard UTide reconstruction are reused; safety/filter, costs, queue memory and weather correction arithmetic are independently implemented. This does not turn failed performance/field gates into passes.",
        "production_authority": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.out and args.out.exists():
        raise ValueError("never overwrite accepted evidence")
    result = verify()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if not result["passed"]:
        raise SystemExit(1)
