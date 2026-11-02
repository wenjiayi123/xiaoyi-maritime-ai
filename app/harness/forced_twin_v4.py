"""Individual archived weather runs as external forcing; no stitched future runs."""

import argparse
import gzip
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import utide

from app.harness import physical_v3 as prior
from app.harness.crossport_v2 import BASE_DIR, sha, write

FOLDER = BASE_DIR / "data/public/forecast_forcing_v4_20261030"
UTC = timezone.utc


def load():
    plan = json.loads((FOLDER / "protocol.json").read_text())
    manifest = json.loads((FOLDER / "manifest.json").read_text())
    assert manifest["protocol_sha256"] == sha(FOLDER / "protocol.json")
    for field in ["water_history_manifest", "tide_selection"]:
        assert sha(BASE_DIR / manifest[field]["path"]) == manifest[field]["sha256"]
    _, _, groups = prior.load()
    weather = {}
    for entry in manifest["entries"]:
        path = BASE_DIR / entry["path"]
        assert sha(path) == entry["sha256"]
        if entry["http_status"] != 200 or entry["provider_error"]:
            continue
        raw = json.loads(path.read_text())
        if entry["kind"] == "weather":
            if not isinstance(raw, list) or len(raw) != len(entry["stations_in_request_order"]):
                raise ValueError("weather station order mismatch")
            for sid, payload in zip(entry["stations_in_request_order"], raw):
                assert payload["utc_offset_seconds"] == 0
                assert payload["hourly_units"]["pressure_msl"] == "hPa"
                assert payload["hourly_units"]["wind_speed_10m"] == "m/s"
                hourly = payload["hourly"]
                values = {}
                for i, at in enumerate(hourly["time"]):
                    row = [hourly[k][i] for k in plan["weather_variables"]]
                    if all(v is not None and math.isfinite(v) for v in row):
                        values[datetime.fromisoformat(at).replace(tzinfo=UTC)] = row
                weather[(sid, entry["id"])] = {"values": values,
                    "initialization": datetime.fromisoformat(entry["initialization_utc"].replace("Z", "+00:00")),
                    "assumed_available": datetime.fromisoformat(entry["assumed_available_utc"].replace("Z", "+00:00")),
                    "grid_coordinates": [payload["latitude"], payload["longitude"]], "receipt": entry}
        else:
            group = groups[entry["id"]]
            for row in raw["data"]:
                try:
                    value = float(row["v"])
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(value) or row.get("q", "v") != "v" or any(f != "0" for f in row["f"].split(",")):
                    continue
                at = datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
                if at in group["observed"] and abs(group["observed"][at] - value) > .001001:
                    raise ValueError("observed station product conflict")
                group["observed"][at] = value
    return plan, manifest, groups, weather


def features(at, weather, pressure_mean):
    pressure, speed, direction = weather
    angle = math.radians(direction)
    u, v = -speed * math.sin(angle), -speed * math.cos(angle)
    phase = (at.timetuple().tm_yday - 1) / 365.25 * 2 * math.pi
    return [1., math.sin(phase), math.cos(phase), (pressure_mean - pressure) / 100, u * abs(u) / 100, v * abs(v) / 100]


def run_predictions(sid, run, model, observed, weather, tide):
    source = weather.get((sid, run))
    if source is None:
        return []
    issue = source["assumed_available"]
    assert issue >= source["initialization"] + timedelta(hours=8)
    coefficient = np.asarray(model["coefficients"])
    initial_delta = 0.
    if model["mode"] == "causal_initial_water_then_open_loop_7d":
        if issue not in observed or issue not in source["values"] or issue not in tide:
            return []
        initial_estimate = tide[issue] + np.dot(features(issue, source["values"][issue], model["pressure_mean"]), coefficient)
        initial_delta = observed[issue] - initial_estimate
    predictions = []
    for lead in range(1, 169):
        at = issue + timedelta(hours=lead)
        if at not in source["values"] or at not in tide:
            continue
        value = tide[at] + np.dot(features(at, source["values"][at], model["pressure_mean"]), coefficient)
        if model["decay_hours"]:
            value += initial_delta * math.exp(-lead / model["decay_hours"])
        predictions.append({"at": at, "lead_hours": lead, "predicted_m": float(value), "issue": issue,
                            "weather_initialization": source["initialization"], "initial_water_used": model["mode"] != "no_test_water_initialization"})
    return predictions


def tides(groups, runs):
    result = {}
    original = json.loads((prior.FOLDER / "selection-before-test.json").read_text())
    for sid in groups:
        all_times = sorted({datetime.fromisoformat(run).replace(tzinfo=UTC) + timedelta(hours=i) for run in runs for i in range(8, 177)})
        for basis in [0, 1]:
            coef_path = prior.FOLDER / f"coefficients-{sid}-{basis}.json"
            source = next(m for m in original["models"] if m["station_id"] == sid)
            expected = next(m["coefficient_sha256"] for m in source["candidates"] if m["basis"] == basis)
            assert sha(coef_path) == expected
            coef = prior.decode(json.loads(coef_path.read_text()))
            values = utide.reconstruct(np.asarray([t.replace(tzinfo=None) for t in all_times], dtype="datetime64[ns]"), coef,
                                       min_SNR=0, verbose=False).h
            result[(sid, basis)] = dict(zip(all_times, values.tolist()))
    return result


def radius(errors):
    values = sorted(abs(v) for v in errors)
    if not values:
        return None
    return values[min(len(values) - 1, math.ceil((len(values) + 1) * .95) - 1)]


def develop():
    if (FOLDER / "selection-before-test.json").exists():
        raise ValueError("selection immutable")
    plan, manifest, groups, weather = load()
    runs = plan["fit_runs"] + plan["selection_runs"] + plan["calibration_runs"]
    tide = tides(groups, runs)
    models = []
    for sid, group in groups.items():
        observed = group["observed"]
        pressures = [row[0] for run in plan["fit_runs"] for row in weather[(sid, run)]["values"].values()]
        pressure_mean = float(np.mean(pressures))
        fitted = []
        for basis in [0, 1]:
            x, y = [], []
            for run in plan["fit_runs"]:
                source = weather[(sid, run)]
                issue = source["assumed_available"]
                for lead in range(1, 169):
                    at = issue + timedelta(hours=lead)
                    if at in observed and at in source["values"]:
                        x.append(features(at, source["values"][at], pressure_mean))
                        y.append(observed[at] - tide[(sid, basis)][at])
            x, y = np.asarray(x), np.asarray(y)
            if len(y) < 500:
                raise ValueError("insufficient weather/tide development labels: " + sid)
            for penalty in plan["ridge_penalties"]:
                coefficients = np.linalg.solve(x.T @ x + np.eye(6) * penalty, x.T @ y)
                fitted.append({"name": f"harmonic{8 if basis == 0 else 20}_weather_ridge{penalty}", "basis": basis,
                    "coefficients": coefficients.tolist(), "pressure_mean": pressure_mean, "fit_n": len(y), "penalty": penalty})
            if basis == 0:
                fixed = np.asarray([0., 0., 0., 1., 0., 0.])  # inverse barometer:1cm/hPa
                fixed[0] = float(np.mean(y - x @ fixed))
                fitted.append({"name": "harmonic8_fixed_inverse_barometer", "basis": 0,
                    "coefficients": fixed.tolist(), "pressure_mean": pressure_mean, "fit_n": len(y), "penalty": None})
        for mode in plan["report_modes"]:
            options = []
            for fit in fitted:
                for decay in ([0] if mode == "no_test_water_initialization" else [24, 72, 168]):
                    model = {**fit, "mode": mode, "decay_hours": decay}
                    errors = []
                    for run in plan["selection_runs"]:
                        predictions = run_predictions(sid, run, model, observed, weather, tide[(sid, model["basis"])])
                        errors.extend(p["predicted_m"] - observed[p["at"]] for p in predictions if p["at"] in observed)
                    if errors:
                        options.append({**model, "validation_mae_m": float(np.mean(np.abs(errors))), "validation_n": len(errors)})
            selected = min(options, key=lambda m: m["validation_mae_m"])
            baseline = min((m for m in options if m["name"] == "harmonic8_fixed_inverse_barometer"), key=lambda m: m["validation_mae_m"])
            calibration = {"1-24": [], "25-72": [], "73-168": []}
            for run in plan["calibration_runs"]:
                predictions = run_predictions(sid, run, selected, observed, weather, tide[(sid, selected["basis"])])
                for p in predictions:
                    if p["at"] in observed:
                        bucket = "1-24" if p["lead_hours"] <= 24 else ("25-72" if p["lead_hours"] <= 72 else "73-168")
                        calibration[bucket].append(p["predicted_m"] - observed[p["at"]])
            radii = {k: radius(v) for k, v in calibration.items()}
            assert all(v is not None for v in radii.values())
            models.append({"station_id": sid, "site": group["site"], "mode": mode,
                "selected": selected, "strong_baseline": baseline, "candidates": options,
                "interval_radii_m": radii, "calibration_n": {k: len(v) for k, v in calibration.items()},
                "datum": sorted(group["datums"]), "record_ids": sorted(group["record_ids"]),
                "weather_grid": weather[(sid, plan["fit_runs"][0])]["grid_coordinates"]})
            print("FORCING_SELECTED", sid, mode, selected["name"], selected["decay_hours"], selected["validation_mae_m"], flush=True)
    write(FOLDER / "selection-before-test.json", {"schema": "xiaoyi-forced-twin-selection.v4",
        "frozen_before_test_at": datetime.now(UTC).isoformat(), "source_sha256": sha(Path(__file__)),
        "prior_implementation_sha256": sha(Path(prior.__file__)), "manifest_sha256": sha(FOLDER / "manifest.json"),
        "protocol_sha256": sha(FOLDER / "protocol.json"), "models": models, "test_labels_used": False,
        "production_authority": False})


def assess():
    if (FOLDER / "report.json").exists():
        raise ValueError("never overwrite a viewed test")
    selection = json.loads((FOLDER / "selection-before-test.json").read_text())
    assert selection["source_sha256"] == sha(Path(__file__))
    assert selection["manifest_sha256"] == sha(FOLDER / "manifest.json")
    plan, manifest, groups, weather = load()
    tide = tides(groups, plan["fresh_test_runs"])
    rows = []
    trace = FOLDER / "predictions.jsonl.gz"
    with gzip.open(trace, "wt") as handle:
        for model in selection["models"]:
            sid = model["station_id"]
            observed = groups[sid]["observed"]
            for run in plan["fresh_test_runs"]:
                own = run_predictions(sid, run, model["selected"], observed, weather, tide[(sid, model["selected"]["basis"])])
                baseline = {p["at"]: p["predicted_m"] for p in run_predictions(sid, run, model["strong_baseline"], observed, weather, tide[(sid, 0)])}
                errors, radii, base_errors, raw_errors = [], [], [], []
                for p in own:
                    at = p["at"]
                    if at not in observed or at not in baseline:
                        continue
                    bucket = "1-24" if p["lead_hours"] <= 24 else ("25-72" if p["lead_hours"] <= 72 else "73-168")
                    r = model["interval_radii_m"][bucket]
                    errors.append(p["predicted_m"] - observed[at])
                    radii.append(r)
                    base_errors.append(abs(baseline[at] - observed[at]))
                    raw_errors.append(abs(tide[(sid, 0)][at] - observed[at]))
                    handle.write(json.dumps({"station_id": sid, "run": run, "mode": model["mode"], "at": at.isoformat(),
                        "lead_hours": p["lead_hours"], "issue": p["issue"].isoformat(),
                        "weather_initialization": p["weather_initialization"].isoformat(),
                        "initial_water_used": p["initial_water_used"], "actual_m": observed[at], "predicted_m": p["predicted_m"],
                        "baseline_m": baseline[at], "radius_m": r}) + "\n")
                metrics = prior.evaluate(errors, radii, 168, plan["research_limits"]["long_open_loop"], base_errors)
                rows.append({"station_id": sid, "site": model["site"], "run": run, "mode": model["mode"],
                    "selected_model": model["selected"]["name"], "baseline_model": model["strong_baseline"]["name"],
                    "raw_harmonic8_mae_m": float(np.mean(raw_errors)) if raw_errors else None, **metrics})
    modes = {mode: {"passed": sum(r["passed"] for r in rows if r["mode"] == mode),
                    "total": sum(r["mode"] == mode for r in rows),
                    "evaluable": sum(r["mode"] == mode and r["n"] > 0 for r in rows)} for mode in plan["report_modes"]}
    write(FOLDER / "report.json", {"schema": "xiaoyi-weather-forced-twin.v4", "sources": manifest, "protocol": plan,
        "selection": selection, "selection_sha256": sha(FOLDER / "selection-before-test.json"),
        "results": rows, "modes": modes, "trace_path": str(trace.relative_to(BASE_DIR)), "trace_sha256": sha(trace),
        "production_authority": False, "notice": "NewJuly windows, frozen individual meteorological runs, explicitly assumed8h publication latency.2025IFS49R1 hindcasts and2026July50R1archive differ; no as-published operational SLA.7-day weather-forced and initial-water modes are separate from previous annual open-loop qualification. Missing station targets stay failed and are never replaced by forecasts/nearby gauges."})
    print("FORCING_FRESH_DONE", modes, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["develop", "assess"])
    args = parser.parse_args()
    {"develop": develop, "assess": assess}[args.phase]()
