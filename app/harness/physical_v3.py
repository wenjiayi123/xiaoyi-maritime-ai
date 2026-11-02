"""Disjoint residual development/calibration and new tide periods, without gap filling."""

import argparse
from bisect import bisect_left, bisect_right
import csv
import gzip
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import utide
from utide.utilities import Bunch

from app.harness import physical_v2 as old

FOLDER = old.BASE_DIR / "data/public/physical_twin_v3_20261030"
UTC = timezone.utc


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


def load():
    plan = json.loads((FOLDER / "protocol.json").read_text())
    manifest = json.loads((FOLDER / "manifest.json").read_text())
    assert manifest["protocol_sha256"] == old.sha(FOLDER / "protocol.json")
    groups = {}
    for entry in manifest["entries"]:
        path = old.BASE_DIR / entry["path"]
        assert old.sha(path) == entry["sha256"]
        group = groups.setdefault(entry["station_id"], {"site": entry["site"], "provider": entry["provider"],
            "observed": {}, "rejected": Counter(), "quality_counts": Counter(), "datums": set(),
            "record_ids": set(), "duplicate_agreements": 0, "provider_errors": []})
        if entry["provider_error"]:
            group["provider_errors"].append(entry)
            continue
        if entry["provider"] == "noaa":
            raw = json.loads(path.read_text())
            group["lat"] = float(raw["metadata"]["lat"])
            group["datums"].add("MLLW")
            records = raw["data"]
        else:
            with path.open() as handle:
                reader = csv.DictReader(handle)
                next(reader)
                records = list(reader)
        for row in records:
            noaa = entry["provider"] == "noaa"
            at = (datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC) if noaa
                  else datetime.fromisoformat(row["time"].replace("Z", "+00:00")))
            try:
                value = float(row["v"]) if noaa else float(row["sea_level"]) / 1000
                valid = (row.get("q", "v") == "v" and all(f == "0" for f in row["f"].split(","))) if noaa else int(row["quality"]) >= 3
            except (ValueError, TypeError):
                value, valid = float("nan"), False
            if not valid or not math.isfinite(value) or value <= -32:
                group["rejected"][str(at.year)] += 1
                continue
            if at in group["observed"]:
                if abs(group["observed"][at] - value) > .001001:
                    raise ValueError("primary product conflict, no error-based source selection: " + entry["station_id"])
                group["duplicate_agreements"] += 1
                continue
            group["observed"][at] = value
            group["quality_counts"][row.get("q", "verified_hourly") if noaa else row["quality"]] += 1
            if not noaa:
                group["lat"] = float(row["latitude"])
                group["datums"].add(row["reference_datum"])
                group["record_ids"].add(row["record_id"])
        if len(group["datums"]) > 1 or len(group["record_ids"]) > 1:
            raise ValueError("datum or record change requires explicit reconciliation")
    return plan, manifest, groups


def annual_vector(times, kind):
    phase = np.asarray([(t.timetuple().tm_yday - 1) / 365.25 * 2 * math.pi for t in times])
    if kind == "none":
        return np.zeros((len(times), 1))
    if kind == "intercept":
        return np.ones((len(times), 1))
    return np.column_stack([np.ones(len(times)), np.sin(phase), np.cos(phase)])


def reconstruct(times, coef):
    naive = [t.replace(tzinfo=None) for t in times]
    return utide.reconstruct(np.asarray(naive, dtype="datetime64[ns]"), coef, min_SNR=0, verbose=False).h


def short_predictions(observed, tide, horizon, memory, resolution):
    result = {}
    for at in sorted(tide):
        if at.minute % resolution:
            continue
        prediction = old.prediction(at, observed, tide, horizon, memory, resolution)
        if prediction:
            result[at] = prediction
    return result


def evaluate(errors, radii, expected, limits, baseline):
    if not errors:
        return {"passed": False, "n": 0, "expected": expected, "blockers": ["no_evaluable_observations"]}
    mae = float(np.mean(np.abs(errors)))
    coverage = float(np.mean(np.abs(errors) <= radii))
    max_width = float(max(radii) * 2)
    checks = {"mae": mae <= limits["mae_m"], "coverage": coverage >= limits["coverage"],
              "interval_width": max_width <= limits["width_m"], "availability": len(errors) / expected >= .95,
              "matches_or_beats_baseline": mae <= float(np.mean(baseline)) + 1e-9}
    return {"n": len(errors), "expected": expected, "mae_m": mae, "bias_m": float(np.mean(errors)),
            "rmse_m": float(np.sqrt(np.mean(np.asarray(errors) ** 2))), "baseline_mae_m": float(np.mean(baseline)),
            "coverage": coverage, "interval_width_m": max_width, "mean_interval_width_m": float(np.mean(radii) * 2),
            "availability": len(errors) / expected, "checks": checks,
            "blockers": [k for k, v in checks.items() if not v], "passed": all(checks.values())}


def develop():
    if (FOLDER / "selection-before-test.json").exists():
        raise ValueError("selection immutable")
    plan, manifest, groups = load()
    models = []
    for sid, group in groups.items():
        observed = group["observed"]
        train = sorted(t for t in observed if t.year in [2023, 2024] and t.minute == 0)
        dev = sorted(t for t in observed if t.year == 2025)
        assert len(train) >= 7000, "insufficient training coverage, do not fabricate"
        fit_times = [t for t in dev if t.month % 2 and t.minute == 0]
        select_times = [t for t in dev if t.month % 2 == 0 and t.day <= 14 and t.minute == 0]
        calibration = [t for t in dev if t.month % 2 == 0 and t.day >= 15 and t.minute == 0]
        candidates, forecasts = [], []
        for basis, names in enumerate(plan["constituents"]):
            coef = utide.solve(np.asarray([t.replace(tzinfo=None) for t in train], dtype="datetime64[ns]"),
                               np.asarray([observed[t] for t in train]), lat=group["lat"], constit=names,
                               method="ols", conf_int="none", trend=False, nodal=True, verbose=False)
            tide = dict(zip(dev, reconstruct(dev, coef).tolist()))
            coefficient_path = FOLDER / f"coefficients-{sid}-{basis}.json"
            old.write(coefficient_path, old.encode(coef))
            for correction in plan["correction_candidates"]:
                x = annual_vector(fit_times, correction)
                residuals = np.asarray([observed[t] - tide[t] for t in fit_times])
                correction_coef = np.linalg.solve(x.T @ x + np.eye(x.shape[1]), x.T @ residuals)
                values = np.asarray([tide[t] for t in dev]) + annual_vector(dev, correction) @ correction_coef
                predictions = dict(zip(dev, values.tolist()))
                mae = float(np.mean([abs(predictions[t] - observed[t]) for t in select_times]))
                candidates.append({"basis": basis, "constituents": len(names), "correction": correction,
                    "correction_coefficients": correction_coef.tolist(), "selection_mae_m": mae,
                    "coefficient_path": str(coefficient_path.relative_to(old.BASE_DIR)),
                    "coefficient_sha256": old.sha(coefficient_path)})
                forecasts.append(predictions)
        best = int(np.argmin([r["selection_mae_m"] for r in candidates]))
        chosen, tide = candidates[best], forecasts[best]
        radii = {}
        for quarter in range(1, 5):
            errors = [tide[t] - observed[t] for t in calibration if (t.month - 1) // 3 + 1 == quarter]
            assert len(errors) >= 100
            radii[str(quarter)] = max(.02, old.radius(errors, plan["interval_quantile"]) * plan["interval_margin"])
        short = []
        for horizon in ([6, 60, 360] if group["provider"] == "noaa" else [60, 360]):
            resolution = 6 if horizon == 6 else 60
            options = []
            for memory in plan["short_memory"]:
                predictions = short_predictions(observed, tide, horizon, memory, resolution)
                select = [t for t in predictions if t.month % 2 == 0 and t.day <= 14 and t in observed]
                errors = [predictions[t][0] - observed[t] for t in select]
                if errors:
                    options.append({"memory": memory, "selection_mae_m": float(np.mean(np.abs(errors)))})
            choice = min(options, key=lambda r: r["selection_mae_m"])
            predictions = short_predictions(observed, tide, horizon, choice["memory"], resolution)
            cal = [t for t in predictions if t.month % 2 == 0 and t.day >= 15 and t in observed]
            errors = [predictions[t][0] - observed[t] for t in cal]
            short.append({"horizon": horizon, "resolution": resolution, "memory": choice["memory"],
                          "radius_m": max(.003, old.radius(errors, plan["interval_quantile"]) * plan["interval_margin"]),
                          "calibration_n": len(errors), "selection_candidates": options})
        models.append({"station_id": sid, "site": group["site"], "provider": group["provider"],
                       "lat": group["lat"], "training_hours": len(train), "selected": chosen,
                       "candidates": candidates, "quarter_radii_m": radii, "short_choices": short,
                       "datums": sorted(group["datums"]), "record_ids": sorted(group["record_ids"]),
                       "rejected_by_year": dict(group["rejected"]), "quality_counts": dict(group["quality_counts"]),
                       "duplicate_agreements": group["duplicate_agreements"], "provider_errors": group["provider_errors"]})
        print("TWIN_SELECTED", sid, chosen["constituents"], chosen["correction"], chosen["selection_mae_m"], flush=True)
    old.write(FOLDER / "selection-before-test.json", {"schema": "xiaoyi-physical-selection.v3",
        "frozen_at": datetime.now(UTC).isoformat(), "implementation_sha256": old.sha(Path(__file__)),
        "protocol_sha256": old.sha(FOLDER / "protocol.json"), "manifest_sha256": old.sha(FOLDER / "manifest.json"),
        "models": models, "selection_uses_test_labels": False, "production_authority": False})


def assess():
    if (FOLDER / "report.json").exists():
        raise ValueError("never overwrite an inspected holdout")
    selection = json.loads((FOLDER / "selection-before-test.json").read_text())
    assert selection["implementation_sha256"] == old.sha(Path(__file__))
    assert selection["manifest_sha256"] == old.sha(FOLDER / "manifest.json")
    plan, manifest, groups = load()
    rows = []
    trace = FOLDER / "predictions.jsonl.gz"
    with gzip.open(trace, "wt") as handle:
        for model in selection["models"]:
            sid = model["station_id"]
            observed = groups[sid]["observed"]
            times = sorted(t for t in observed if t.year == 2026)
            chosen = model["selected"]
            coef = decode(json.loads((old.BASE_DIR / chosen["coefficient_path"]).read_text()))
            baseline_coef = decode(json.loads((FOLDER / f"coefficients-{sid}-0.json").read_text()))
            values = reconstruct(times, coef) + annual_vector(times, chosen["correction"]) @ np.asarray(chosen["correction_coefficients"])
            tide = dict(zip(times, values.tolist()))
            baseline = dict(zip(times, reconstruct(times, baseline_coef).tolist()))
            for month in plan["test_months"]:
                expected = old.targets(month, 60)
                errors, radii, base_errors = [], [], []
                radius = model["quarter_radii_m"][str((int(month[-2:]) - 1) // 3 + 1)]
                for at in expected:
                    if at in observed:
                        errors.append(tide[at] - observed[at])
                        base_errors.append(abs(baseline[at] - observed[at]))
                        radii.append(radius)
                        handle.write(json.dumps({"station_id": sid, "kind": "long_open_loop", "at": at.isoformat(),
                            "actual_m": observed[at], "predicted_m": tide[at], "radius_m": radius}) + "\n")
                rows.append({"station_id": sid, "site": model["site"], "month": month, "kind": "long_open_loop",
                             **evaluate(errors, radii, len(expected), plan["research_limits"]["long_open_loop"], base_errors)})
            for choice in model["short_choices"]:
                horizon, resolution = choice["horizon"], choice["resolution"]
                predictions = short_predictions(observed, tide, horizon, choice["memory"], resolution)
                residuals = {t: p[0] - observed[t] for t, p in predictions.items() if t in observed}
                residual_times = sorted(residuals)
                residual_values = [residuals[t] for t in residual_times]
                for month in plan["test_months"]:
                    expected = old.targets(month, resolution)
                    errors, radii, base_errors = [], [], []
                    for at in expected:
                        if at not in predictions or at not in observed:
                            continue
                        predicted, persistence, cutoff = predictions[at]
                        left = bisect_left(residual_times, cutoff - timedelta(days=14))
                        right = bisect_right(residual_times, cutoff)
                        past = residual_values[left:right]
                        radius = max(choice["radius_m"], old.radius(past, plan["interval_quantile"]) * plan["interval_margin"]) if len(past) >= 50 else choice["radius_m"]
                        errors.append(predicted - observed[at])
                        radii.append(radius)
                        base_errors.append(abs(persistence - observed[at]))
                        handle.write(json.dumps({"station_id": sid, "kind": "short_assimilation", "horizon_minutes": horizon,
                            "at": at.isoformat(), "input_cutoff": cutoff.isoformat(), "interval_latest_label": cutoff.isoformat(),
                            "actual_m": observed[at], "predicted_m": predicted, "radius_m": radius}) + "\n")
                    rows.append({"station_id": sid, "site": model["site"], "month": month, "kind": "short_assimilation", "horizon_minutes": horizon,
                        **evaluate(errors, radii, len(expected), plan["research_limits"][str(horizon)], base_errors)})
            print("TWIN_FRESH_EVALUATED", sid, flush=True)
    long = [r for r in rows if r["kind"] == "long_open_loop"]
    short = [r for r in rows if r["kind"] == "short_assimilation"]
    old.write(FOLDER / "report.json", {"schema": "xiaoyi-physical-new-period.v3", "sources": manifest,
        "protocol": plan, "selection": selection, "selection_sha256": old.sha(FOLDER / "selection-before-test.json"),
        "results": rows, "long_passed": sum(r["passed"] for r in long), "long_total": len(long),
        "short_passed": sum(r["passed"] for r in short), "short_total": len(short),
        "trace_path": str(trace.relative_to(old.BASE_DIR)), "trace_sha256": old.sha(trace),
        "production_authority": False, "notice": "Old failures retained. New2026March/June/September periods; strict point/coverage/maximum-width/availability/baseline gates unchanged. Missing or rejected source observations remain failures. Annual correction and quarterly intervals use2025development only. Short interval updates use labels available by input cutoff; archive replay still assumes local sensor access."})
    print("TWIN_FRESH_DONE", sum(r["passed"] for r in long), len(long), sum(r["passed"] for r in short), len(short), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["develop", "assess"])
    args = parser.parse_args()
    {"develop": develop, "assess": assess}[args.phase]()
