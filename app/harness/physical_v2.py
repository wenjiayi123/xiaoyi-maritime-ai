"""Annual astronomical tide fit and independent international/year holdouts."""

import csv
import gzip
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import BASE_DIR

FOLDER = BASE_DIR / "data/public/physical_twin_v2_20261030"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def encode(value):
    import numpy as np

    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, np.ndarray):
        return {"array": encode(value.tolist()), "dtype": str(value.dtype)}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    if isinstance(value, complex):
        return {"complex": [value.real, value.imag]}
    if isinstance(value, np.generic):
        return encode(value.item())
    return value


def load():
    plan = json.loads((FOLDER / "protocol.json").read_text())
    manifest = json.loads((FOLDER / "manifest.json").read_text())
    if manifest["protocol_sha256"] != sha(FOLDER / "protocol.json"):
        raise ValueError("physical source/protocol mismatch")
    groups = {}
    for entry in manifest["entries"]:
        path = (BASE_DIR / entry["path"]).resolve()
        if not path.is_relative_to(FOLDER.resolve()) or sha(path) != entry["sha256"]:
            raise ValueError("physical primary source changed")
        group = groups.setdefault(
            entry["station_id"],
            {
                "site": entry["site"],
                "provider": entry["provider"],
                "observed": {},
                "quality_counts": Counter(),
                "rejected": 0,
                "datums": set(),
                "record_ids": set(),
            },
        )
        if entry["provider"] == "noaa":
            raw = json.loads(path.read_text())
            group["lat"] = float(raw["metadata"]["lat"])
            for row in raw["data"]:
                try:
                    value = float(row["v"])
                except (TypeError, ValueError):
                    group["rejected"] += 1
                    continue
                if not math.isfinite(value) or row.get("q", "v") != "v" or any(f != "0" for f in row["f"].split(",")):
                    group["rejected"] += 1
                    continue
                at = datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                if at in group["observed"]:
                    raise ValueError("duplicate measured station time")
                group["observed"][at] = value
                group["quality_counts"][row.get("q", "verified_hourly_product")] += 1
            group["datums"].add("MLLW")
        else:
            with path.open() as handle:
                reader = csv.DictReader(handle)
                next(reader)  # provider units row, retained in raw source
                for row in reader:
                    try:
                        value = float(row["sea_level"]) / 1000
                        quality = int(row["quality"])
                    except (ValueError, TypeError):
                        group["rejected"] += 1
                        continue
                    if not math.isfinite(value) or quality < 3 or value <= -32:
                        group["rejected"] += 1
                        continue
                    at = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
                    if at in group["observed"]:
                        raise ValueError("duplicate UHSLC record/time; do not pick a version using test error")
                    group["observed"][at] = value
                    group["lat"] = float(row["latitude"])
                    group["quality_counts"][str(quality)] += 1
                    group["datums"].add(row["reference_datum"])
                    group["record_ids"].add(row["record_id"])
        if len(group["datums"]) != 1 or len(group["record_ids"]) > 1:
            raise ValueError("unresolved datum/record change: " + entry["station_id"])
    return plan, manifest, groups


def block(month):
    first = datetime.strptime(month + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return first, first + timedelta(days=8)


def targets(month, resolution):
    first, end = block(month)
    start = first + timedelta(days=1)
    return [
        start + timedelta(minutes=resolution * i) for i in range(int((end - start).total_seconds() / (resolution * 60)))
    ]


def radius(errors, quantile):
    values = sorted(abs(e) for e in errors)
    if not values:
        raise ValueError("no calibration residuals")
    return values[min(len(values) - 1, math.ceil((len(values) + 1) * quantile) - 1)]


def prediction(at, observed, tide, horizon, memory, resolution):
    cutoff = at - timedelta(minutes=horizon)
    times = [cutoff - timedelta(minutes=resolution * i) for i in range(memory)]
    if at not in tide or any(t not in observed or t not in tide for t in times):
        return None
    residual = sum(observed[t] - tide[t] for t in times) / memory
    return tide[at] + residual, observed[cutoff], cutoff


def metrics(errors, radius_m, expected, limits, baseline):
    import numpy as np

    if not errors:
        return {"passed": False, "n": 0, "expected": expected, "blockers": ["no_evaluable_observations"]}
    mae = float(np.mean(np.abs(errors)))
    checks = {
        "mae": mae <= limits["mae_m"],
        "coverage": float(np.mean(np.abs(errors) <= radius_m)) >= limits["coverage"],
        "interval_width": radius_m * 2 <= limits["width_m"],
        "availability": len(errors) / expected >= 0.95,
        "matches_or_beats_baseline": mae <= float(np.mean(baseline)) + 1e-9,
    }
    return {
        "n": len(errors),
        "expected": expected,
        "mae_m": mae,
        "rmse_m": float(np.sqrt(np.mean(np.asarray(errors) ** 2))),
        "bias_m": float(np.mean(errors)),
        "baseline_mae_m": float(np.mean(baseline)),
        "coverage": float(np.mean(np.abs(errors) <= radius_m)),
        "interval_width_m": 2 * radius_m,
        "availability": len(errors) / expected,
        "checks": checks,
        "blockers": [k for k, v in checks.items() if not v],
        "passed": all(checks.values()),
    }


def study():
    import numpy as np
    import utide

    destination = FOLDER / "report.json"
    if destination.exists():
        raise ValueError("never overwrite a viewed physical holdout")
    plan, manifest, groups = load()
    models, fitted = [], {}
    # Fit/select every station before calculating any fresh test metric.
    for sid, group in groups.items():
        observed = group["observed"]
        start = date_cutoff = plan.get("per_station_training_override", {}).get(sid, ["2024-01-01", "2024-12-31"])[0]
        start = datetime.strptime(date_cutoff, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        train = sorted(t for t in observed if start <= t < datetime(2025, 1, 1, tzinfo=timezone.utc) and t.minute == 0)
        if len(train) < 7000:
            raise ValueError("annual harmonic fit has insufficient observed hours: " + sid)
        validation_times = sorted(
            set(
                t
                for month in plan["validation_blocks"]
                for t in [*targets(month, 60), *([*targets(month, 6)] if group["provider"] == "noaa" else [])]
            )
        )
        # Include causal context but never fit or select using 2026 observations.
        dev_times = sorted(t for t in observed if t.year == 2025)
        candidates = []
        for names in plan["harmonic_candidates"]["constituents"]:
            coef = utide.solve(
                np.asarray(train, dtype="datetime64[ns]"),
                np.asarray([observed[t] for t in train]),
                lat=group["lat"],
                constit=names,
                method="ols",
                conf_int="none",
                trend=False,
                nodal=True,
                verbose=False,
            )
            pred = utide.reconstruct(np.asarray(dev_times, dtype="datetime64[ns]"), coef, min_SNR=0, verbose=False).h
            tide = dict(zip(dev_times, pred.tolist()))
            errors = [tide[t] - observed[t] for t in validation_times if t.minute == 0 and t in observed]
            candidates.append((float(np.mean(np.abs(errors))), coef, tide, len(names)))
        chosen = min(candidates, key=lambda c: c[0])
        _, coef, tide, count = chosen
        long_errors = [tide[t] - observed[t] for t in validation_times if t.minute == 0 and t in observed]
        choices = []
        horizons = plan["short_horizons_minutes"] + (
            plan["additional_noaa_horizon_minutes"] if group["provider"] == "noaa" else []
        )
        for horizon in horizons:
            resolution = 6 if horizon == 6 else 60
            options = []
            for memory in plan["residual_memory_candidates"]:
                errors = []
                for month in plan["validation_blocks"]:
                    for at in targets(month, resolution):
                        pred = prediction(at, observed, tide, horizon, memory, resolution)
                        if pred and at in observed:
                            errors.append(pred[0] - observed[at])
                if errors:
                    options.append(
                        {
                            "memory": memory,
                            "mae_m": float(np.mean(np.abs(errors))),
                            "radius_m": radius(errors, plan["interval_nominal_quantile"]),
                            "n": len(errors),
                        }
                    )
            selected = min(options, key=lambda c: c["mae_m"])
            choices.append({"horizon": horizon, "resolution": resolution, "selected": selected, "candidates": options})
        model_path = FOLDER / ("coefficients-" + sid + ".json")
        write(model_path, encode(coef))
        models.append(
            {
                "station_id": sid,
                "site": group["site"],
                "provider": group["provider"],
                "lat": group["lat"],
                "training_hours": len(train),
                "basis_count": count,
                "candidate_mae_m": [c[0] for c in candidates],
                "coefficient_path": str(model_path.relative_to(BASE_DIR)),
                "coefficient_sha256": sha(model_path),
                "long_radius_m": radius(long_errors, plan["interval_nominal_quantile"]),
                "short_choices": choices,
                "quality_counts": dict(group["quality_counts"]),
                "rejected": group["rejected"],
                "datums": sorted(group["datums"]),
                "record_ids": sorted(group["record_ids"]),
            }
        )
        fitted[sid] = (coef, candidates[0][1])
        print("selected", sid, count, "validation", chosen[0], flush=True)
    selection = {
        "frozen_before_test_at": datetime.now(timezone.utc).isoformat(),
        "implementation_sha256": sha(Path(__file__)),
        "protocol_sha256": sha(FOLDER / "protocol.json"),
        "manifest_sha256": sha(FOLDER / "manifest.json"),
        "models": models,
        "dependencies": {"numpy": np.__version__, "utide": utide.__version__},
        "selection_uses_test_labels": False,
    }
    write(FOLDER / "selection-before-test.json", selection)
    rows = []
    trace_path = FOLDER / "predictions.jsonl.gz"
    with gzip.open(trace_path, "wt") as handle:
        for model in models:
            sid = model["station_id"]
            group = groups[sid]
            observed = group["observed"]
            times = sorted(t for t in observed if t.year == 2026)
            coef, baseline_coef = fitted[sid]
            tide = dict(
                zip(
                    times,
                    utide.reconstruct(
                        np.asarray(times, dtype="datetime64[ns]"), coef, min_SNR=0, verbose=False
                    ).h.tolist(),
                )
            )
            baseline = dict(
                zip(
                    times,
                    utide.reconstruct(
                        np.asarray(times, dtype="datetime64[ns]"), baseline_coef, min_SNR=0, verbose=False
                    ).h.tolist(),
                )
            )
            for month in plan["fresh_test_blocks"]:
                expected_times = targets(month, 60)
                errors = [tide[t] - observed[t] for t in expected_times if t in observed]
                base_errors = [abs(baseline[t] - observed[t]) for t in expected_times if t in observed]
                row = {
                    "station_id": sid,
                    "site": group["site"],
                    "month": month,
                    "kind": "long_open_loop",
                    **metrics(
                        errors,
                        model["long_radius_m"],
                        len(expected_times),
                        plan["research_limits"]["long_open_loop"],
                        base_errors,
                    ),
                }
                rows.append(row)
                for t in expected_times:
                    if t in observed:
                        handle.write(
                            json.dumps(
                                {
                                    "station_id": sid,
                                    "kind": "long_open_loop",
                                    "at": t.isoformat(),
                                    "actual_m": observed[t],
                                    "predicted_m": tide[t],
                                    "radius_m": model["long_radius_m"],
                                }
                            )
                            + "\n"
                        )
                for choice in model["short_choices"]:
                    horizon = choice["horizon"]
                    expected_times = targets(month, choice["resolution"])
                    errors, base_errors = [], []
                    radius_m = choice["selected"]["radius_m"]
                    for t in expected_times:
                        pred = prediction(
                            t, observed, tide, horizon, choice["selected"]["memory"], choice["resolution"]
                        )
                        if pred and t in observed:
                            errors.append(pred[0] - observed[t])
                            base_errors.append(abs(pred[1] - observed[t]))
                            handle.write(
                                json.dumps(
                                    {
                                        "station_id": sid,
                                        "kind": "short_assimilation",
                                        "horizon_minutes": horizon,
                                        "at": t.isoformat(),
                                        "input_cutoff": pred[2].isoformat(),
                                        "actual_m": observed[t],
                                        "predicted_m": pred[0],
                                        "radius_m": radius_m,
                                    }
                                )
                                + "\n"
                            )
                    rows.append(
                        {
                            "station_id": sid,
                            "site": group["site"],
                            "month": month,
                            "kind": "short_assimilation",
                            "horizon_minutes": horizon,
                            **metrics(
                                errors,
                                radius_m,
                                len(expected_times),
                                plan["research_limits"][str(horizon)],
                                base_errors,
                            ),
                        }
                    )
    result = {
        "schema": "xiaoyi-international-physical-twin.v2",
        "protocol": plan,
        "sources": manifest,
        "selection": selection,
        "results": rows,
        "trace_path": str(trace_path.relative_to(BASE_DIR)),
        "trace_sha256": sha(trace_path),
        "selection_sha256": sha(FOLDER / "selection-before-test.json"),
        "long_passed": sum(r["passed"] for r in rows if r["kind"] == "long_open_loop"),
        "long_total": sum(r["kind"] == "long_open_loop" for r in rows),
        "short_passed": sum(r["passed"] for r in rows if r["kind"] == "short_assimilation"),
        "short_total": sum(r["kind"] == "short_assimilation" for r in rows),
        "production_authority": False,
        "notice": "新国际测站与2026留出。归档观测短期回放假设本地传感器即时可用；UHSLC归档本身有4-6周延迟。保留旧物理失败和本轮全部未通过单元，不代替全港物理标定。",
    }
    write(destination, result)
    return result


def report():
    value = json.loads((FOLDER / "report.json").read_text())
    issues = []
    checks = [
        (Path(__file__), value["selection"]["implementation_sha256"]),
        (FOLDER / "protocol.json", value["selection"]["protocol_sha256"]),
        (FOLDER / "manifest.json", value["selection"]["manifest_sha256"]),
        (FOLDER / "selection-before-test.json", value["selection_sha256"]),
        (BASE_DIR / value["trace_path"], value["trace_sha256"]),
    ]
    checks += [(BASE_DIR / e["path"], e["sha256"]) for e in value["sources"]["entries"]]
    metadata = value["sources"]["uhslc_metadata"]
    checks.append((BASE_DIR / metadata["path"], metadata["sha256"]))
    checks += [(BASE_DIR / m["coefficient_path"], m["coefficient_sha256"]) for m in value["selection"]["models"]]
    for path, expected in checks:
        if not path.exists() or sha(path) != expected:
            issues.append(str(path.relative_to(BASE_DIR)))
    value["historical_only"] = bool(issues)
    value["current_validation_issues"] = issues
    return value
