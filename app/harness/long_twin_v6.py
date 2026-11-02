"""Full-year, fixed-origin tide calibration with untouched station/period tests.

All candidate choices and interval radii are sealed before acquiring test truth.
Archive event time does not establish historical publication time or live access.
"""

import argparse
import csv
import gzip
import io
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import utide

from app.harness import physical_v2 as old
from app.harness.physical_v3 import decode, reconstruct

DATA = old.BASE_DIR / "data/public/long_twin_v6_20261030"
UTC = timezone.utc
NAMES = [
    "M2",
    "S2",
    "N2",
    "K2",
    "K1",
    "O1",
    "P1",
    "Q1",
    "M4",
    "MS4",
    "MN4",
    "2N2",
    "MU2",
    "NU2",
    "L2",
    "T2",
    "J1",
    "OO1",
    "SA",
    "SSA",
]


def hours(year):
    first, end = datetime(year, 1, 1, tzinfo=UTC), datetime(year + 1, 1, 1, tzinfo=UTC)
    return [first + timedelta(hours=i) for i in range(int((end - first).total_seconds() / 3600))]


def load(phase):
    manifest = json.loads((DATA / f"{phase}-manifest.json").read_text())
    if manifest["protocol_sha256"] != old.sha(DATA / "protocol.json"):
        raise ValueError("registered protocol changed")
    groups = {}
    for e in manifest["entries"]:
        path = old.BASE_DIR / e["path"]
        if old.sha(path) != e["sha256"]:
            raise ValueError("primary response changed")
        g = groups.setdefault(
            e["station_id"],
            {
                "site": e["site"],
                "provider": e["provider"],
                "observed": {},
                "quality": Counter(),
                "rejected": Counter(),
                "datums": set(),
                "records": set(),
                "errors": [],
                "last_rq_dates": set(),
            },
        )
        body = gzip.decompress(path.read_bytes()) if e["compression"] != "none" else path.read_bytes()
        if e["provider_error"] or body.startswith(b"Error {"):
            g["errors"].append(
                {
                    "label": e["label"],
                    "http_status": e["http_status"],
                    "path": e["path"],
                    "returned_error": body.decode(e["encoding"], errors="replace")[:1000],
                }
            )
            continue
        text = body.decode(e["encoding"])
        if e["provider"] == "noaa":
            raw = json.loads(text)
            g["lat"] = float(raw["metadata"]["lat"])
            g["datums"].add("MLLW")
            rows = raw["data"]
        else:
            reader = csv.DictReader(io.StringIO(text))
            next(reader)  # provider units, preserved in the raw response
            rows = reader
        for r in rows:
            noaa = e["provider"] == "noaa"
            at = (
                datetime.strptime(r["t"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
                if noaa
                else datetime.fromisoformat(r["time"].replace("Z", "+00:00"))
            )
            try:
                value = float(r["v"]) if noaa else float(r["sea_level"]) / 1000
                valid = (
                    (r.get("q", "v") == "v" and all(f == "0" for f in r["f"].split(",")))
                    if noaa
                    else int(r["quality"]) >= 3
                )
            except (ValueError, TypeError):
                value, valid = math.nan, False
            if not valid or not math.isfinite(value) or value <= -32 or at.minute:
                g["rejected"][str(at.year)] += 1
                continue
            if at in g["observed"] and abs(g["observed"][at] - value) > 0.001001:
                raise ValueError("conflicting primary observations")
            g["observed"][at] = value
            g["quality"][r.get("q", "verified_hourly") if noaa else r["quality"]] += 1
            if not noaa:
                g["lat"] = float(r["latitude"])
                g["datums"].add(r["reference_datum"])
                g["records"].add(r["record_id"])
                g["last_rq_dates"].add(r["last_rq_date"])
        if len(g["datums"]) > 1 or len(g["records"]) > 1:
            raise ValueError("datum/record reconciliation required, do not fit through it")
    return manifest, groups


def fit(group, years, count, trend):
    times = sorted(t for t in group["observed"] if t.year in years)
    availability = {str(y): sum(t.year == y for t in times) / len(hours(y)) for y in years}
    if any(v < 0.8 for v in availability.values()):
        raise ValueError("less than80percent historical coverage in a fit year")
    y = np.asarray([group["observed"][t] for t in times])
    coef = utide.solve(
        np.asarray([t.replace(tzinfo=None) for t in times], dtype="datetime64[ns]"),
        y,
        lat=group["lat"],
        constit=NAMES[:count],
        method="ols",
        conf_int="none",
        trend=trend,
        nodal=True,
        verbose=False,
    )
    latest = [t for t in times if t.year == max(years)]
    correction = float(np.mean(np.asarray([group["observed"][t] for t in latest]) - reconstruct(latest, coef)))
    return coef, correction, availability


def quarter_mae(times, predicted, observed):
    return [
        float(np.mean([abs(predicted[i] - observed[t]) for i, t in enumerate(times) if (t.month - 1) // 3 == q]))
        for q in range(4)
    ]


def select_one(sid, group, protocol):
    case = protocol["new_station_annual_test"] if group["provider"] == "uhslc" else protocol["new_period_noaa_test"]
    folds, candidates = [], []
    for year in case["selection_years"]:
        target = [t for t in hours(year) if t in group["observed"]]
        if any(sum(t.month == m for t in target) < 24 * 20 for m in range(1, 13)):
            raise ValueError("selection year lacks a usable month")
        forecasts = {}
        for count in [8, 20]:
            for trend in [False, True]:
                coef, correction, _ = fit(group, list(range(year - 3, year)), count, trend)
                plain = reconstruct(target, coef)
                for weight in [0.0, 0.5]:
                    forecasts[count, trend, weight] = plain + weight * correction
        folds.append((target, forecasts))
    baseline_options = []
    for count in [8, 20]:
        qs = [
            v for times, forecasts in folds for v in quarter_mae(times, forecasts[count, False, 0.0], group["observed"])
        ]
        baseline_options.append({"count": count, "quarter_mae_m": qs, "mean_quarter_mae_m": float(np.mean(qs))})
    baseline = min(baseline_options, key=lambda r: r["mean_quarter_mae_m"])
    bq = np.asarray(baseline["quarter_mae_m"])
    for count in [8, 20]:
        for trend in [False, True]:
            for correction in [0.0, 0.5]:
                for blend in [0.0, 0.5, 1.0]:
                    qs = []
                    for times, forecasts in folds:
                        pred = (
                            blend * forecasts[count, trend, correction]
                            + (1 - blend) * forecasts[baseline["count"], False, 0.0]
                        )
                        qs.extend(quarter_mae(times, pred, group["observed"]))
                    qualifies = np.mean(bq) - np.mean(qs) >= 0.003 and bool(np.all(np.asarray(qs) <= bq + 1e-12))
                    candidates.append(
                        {
                            "count": count,
                            "trend": trend,
                            "level_weight": correction,
                            "blend": blend,
                            "quarter_mae_m": qs,
                            "mean_quarter_mae_m": float(np.mean(qs)),
                            "admissible_complexity": bool(qualifies),
                        }
                    )
    eligible = [r for r in candidates if r["admissible_complexity"]]
    chosen = (
        min(eligible, key=lambda r: r["mean_quarter_mae_m"])
        if eligible
        else {
            "count": baseline["count"],
            "trend": False,
            "level_weight": 0.0,
            "blend": 1.0,
            "mean_quarter_mae_m": baseline["mean_quarter_mae_m"],
            "quarter_mae_m": baseline["quarter_mae_m"],
            "admissible_complexity": False,
        }
    )
    calibration_year = case["interval_calibration_year"]
    calibration_times = [t for t in hours(calibration_year) if t in group["observed"]]
    cyears = list(range(calibration_year - 3, calibration_year))
    bc, _, _ = fit(group, cyears, baseline["count"], False)
    cc, correction, _ = fit(group, cyears, chosen["count"], chosen["trend"])
    predictions = chosen["blend"] * (reconstruct(calibration_times, cc) + chosen["level_weight"] * correction) + (
        1 - chosen["blend"]
    ) * reconstruct(calibration_times, bc)
    residual = {t: float(predictions[i] - group["observed"][t]) for i, t in enumerate(calibration_times)}
    radii = {}
    for month in range(1, 13):
        values = [e for t, e in residual.items() if t.month == month]
        if len(values) < 24 * 20:
            raise ValueError("interval calibration month has insufficient true observations")
        radii[str(month)] = max(0.02, old.radius(values, protocol["interval"]["absolute_residual_quantile"]) * 1.1)
    models = {}
    for label, count, trend in [("chosen", chosen["count"], chosen["trend"]), ("baseline", baseline["count"], False)]:
        coef, correction, coverage = fit(group, case["final_fit_years"], count, trend)
        path = DATA / f"coefficients-{sid}-{label}.json"
        old.write(path, old.encode(coef))
        models[label] = {
            "path": str(path.relative_to(old.BASE_DIR)),
            "sha256": old.sha(path),
            "latest_training_year_residual_mean_m": correction,
            "fit_availability": coverage,
        }
    return {
        "station_id": sid,
        "site": group["site"],
        "provider": group["provider"],
        "selected": chosen,
        "baseline": baseline,
        "baseline_candidates": baseline_options,
        "candidates": candidates,
        "month_radii_m": radii,
        "models": models,
        "forecast_origin": case["forecast_origin"],
        "final_fit_years": case["final_fit_years"],
        "status": "frozen",
    }


def provenance(group):
    return {
        "quality_counts": dict(group["quality"]),
        "rejected_by_year": dict(group["rejected"]),
        "datums": sorted(group["datums"]),
        "record_ids": sorted(group["records"]),
        "last_rq_dates": sorted(group["last_rq_dates"]),
        "source_errors": group["errors"],
    }


def develop():
    if (DATA / "selection-before-test.json").exists():
        raise ValueError("selection immutable")
    protocol = json.loads((DATA / "protocol.json").read_text())
    manifest, groups = load("history")
    models = []
    for sid, group in groups.items():
        try:
            model = select_one(sid, group, protocol)
        except ValueError as exc:
            model = {
                "station_id": sid,
                "site": group["site"],
                "provider": group["provider"],
                "status": "blocked",
                "reason": str(exc),
            }
        model.update(provenance(group))
        models.append(model)
        print("LONG_TWIN_FROZEN", sid, model["status"], model.get("selected"), flush=True)
    old.write(
        DATA / "selection-before-test.json",
        {
            "schema": "xiaoyi-long-selection.v6",
            "frozen_at": datetime.now(UTC).isoformat(),
            "source_sha256": old.sha(Path(__file__)),
            "protocol_sha256": old.sha(DATA / "protocol.json"),
            "history_manifest_sha256": old.sha(DATA / "history-manifest.json"),
            "models": models,
            "test_labels_used": False,
            "production_authority": False,
        },
    )


def metrics(points, limits):
    valid = [p for p in points if p["actual_m"] is not None and p["predicted_m"] is not None]
    if not valid:
        return {
            "passed": False,
            "n": 0,
            "expected": len(points),
            "availability": 0,
            "blockers": ["missing_truth_or_frozen_model"],
            "checks": {"available": False},
        }
    errors = np.asarray([p["predicted_m"] - p["actual_m"] for p in valid])
    radii = np.asarray([p["radius_m"] for p in valid])
    base = float(np.mean([abs(p["baseline_m"] - p["actual_m"]) for p in valid]))
    mae, coverage, width, availability = (
        float(np.mean(abs(errors))),
        float(np.mean(abs(errors) <= radii)),
        float(max(radii) * 2),
        len(valid) / len(points),
    )
    checks = {
        "mae": mae <= limits["mae_m"],
        "coverage": coverage >= limits["coverage"],
        "interval_width": width <= limits["width_m"],
        "availability": availability >= limits["availability"],
        "matches_or_beats_baseline": mae <= base + limits["baseline_noninferiority_epsilon_m"],
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "blockers": [k for k, v in checks.items() if not v],
        "n": len(valid),
        "expected": len(points),
        "mae_m": mae,
        "baseline_mae_m": base,
        "coverage": coverage,
        "interval_width_m": width,
        "mean_interval_width_m": float(np.mean(radii) * 2),
        "availability": availability,
        "bias_m": float(np.mean(errors)),
        "rmse_m": float(np.sqrt(np.mean(errors**2))),
    }


def assess():
    if (DATA / "report.json").exists():
        raise ValueError("never overwrite an inspected holdout")
    selection = json.loads((DATA / "selection-before-test.json").read_text())
    for key, path in [
        ("source_sha256", Path(__file__)),
        ("protocol_sha256", DATA / "protocol.json"),
        ("history_manifest_sha256", DATA / "history-manifest.json"),
    ]:
        if old.sha(path) != selection[key]:
            raise ValueError("frozen selection inputs changed")
    protocol = json.loads((DATA / "protocol.json").read_text())
    manifest, groups = load("test")
    rows = []
    trace = DATA / "predictions.jsonl.gz"
    with gzip.open(trace, "wt") as handle:
        for model in selection["models"]:
            sid = model["station_id"]
            group = groups[sid]
            if model["provider"] == "uhslc":
                expected = hours(2025)
                periods = [("annual2025", expected)] + [
                    (f"2025Q{q + 1}", [t for t in expected if (t.month - 1) // 3 == q]) for q in range(4)
                ]
            else:
                expected, periods = [], []
                for begin, end in protocol["new_period_noaa_test"]["periods"]:
                    first, last = (
                        datetime.fromisoformat(begin).replace(tzinfo=UTC),
                        datetime.fromisoformat(end).replace(tzinfo=UTC) + timedelta(days=1),
                    )
                    times = [first + timedelta(hours=i) for i in range(int((last - first).total_seconds() / 3600))]
                    expected.extend(times)
                    periods.append((begin[:7] + "-days8plus", times))
            frozen = model["status"] == "frozen"
            chosen_values = base_values = None
            if frozen:
                if set(model["datums"]) != group["datums"] or set(model["record_ids"]) != group["records"]:
                    # With no truth there is no inferred datum. Retain an empty source as missing.
                    if group["observed"]:
                        raise ValueError("history/test datum or record changed")
                coefs = {}
                for label, meta in model["models"].items():
                    path = old.BASE_DIR / meta["path"]
                    if old.sha(path) != meta["sha256"]:
                        raise ValueError("frozen coefficients changed")
                    coefs[label] = decode(json.loads(path.read_text()))
                base_values = reconstruct(expected, coefs["baseline"])
                chosen = model["selected"]
                chosen_values = (
                    chosen["blend"]
                    * (
                        reconstruct(expected, coefs["chosen"])
                        + chosen["level_weight"] * model["models"]["chosen"]["latest_training_year_residual_mean_m"]
                    )
                    + (1 - chosen["blend"]) * base_values
                )
            points = {}
            origin = model.get("forecast_origin")
            for i, at in enumerate(expected):
                point = {
                    "station_id": sid,
                    "at": at.isoformat(),
                    "forecast_origin": origin,
                    "actual_m": group["observed"].get(at),
                    "predicted_m": float(chosen_values[i]) if frozen else None,
                    "baseline_m": float(base_values[i]) if frozen else None,
                    "radius_m": model["month_radii_m"][str(at.month)] if frozen else None,
                    "observation_available": at in group["observed"],
                    "test_observation_used_as_input": False,
                }
                handle.write(json.dumps(point, allow_nan=False) + "\n")
                points[at] = point
            for period, times in periods:
                rows.append(
                    {
                        "station_id": sid,
                        "site": model["site"],
                        "provider": model["provider"],
                        "period": period,
                        "kind": "full_year_open_loop" if period.startswith("annual") else "fixed_origin_period",
                        "forecast_origin": origin,
                        "new_station": sid not in protocol["development_noaa"],
                        "model_status": model["status"],
                        **metrics([points[t] for t in times], protocol["research_limits"]),
                        **provenance(group),
                    }
                )
            print(
                "LONG_TWIN_TEST",
                sid,
                [(r["period"], r["passed"], r["blockers"]) for r in rows if r["station_id"] == sid],
                flush=True,
            )

    def summary(subset):
        return {
            "passed": sum(r["passed"] for r in subset),
            "total": len(subset),
            "all_passed": bool(subset) and all(r["passed"] for r in subset),
        }

    old.write(
        DATA / "report.json",
        {
            "schema": "xiaoyi-long-openloop-report.v6",
            "protocol": protocol,
            "selection": selection,
            "selection_sha256": old.sha(DATA / "selection-before-test.json"),
            "sources": {"history": json.loads((DATA / "history-manifest.json").read_text()), "test": manifest},
            "results": rows,
            "annual": summary([r for r in rows if r["kind"] == "full_year_open_loop"]),
            "quarters": summary([r for r in rows if "Q" in r["period"]]),
            "new_periods": summary([r for r in rows if r["provider"] == "noaa"]),
            "trace_path": str(trace.relative_to(old.BASE_DIR)),
            "trace_sha256": old.sha(trace),
            "notice": "Full365day2025andallfourquarters, plus genuinely new late2026periods, scored separately. Baseline fallback is explicit model selection, not an AI improvement. Missing sources remain failures. Archived event time is not as-published or live access. Old V2-V4 failures retained unchanged. No test-period water initialization, weather reanalysis or assimilation.",
            "production_authority": False,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["develop", "assess"])
    {"develop": develop, "assess": assess}[parser.parse_args().phase]()
