"""Frozen annual harmonic hindcasts with season-balanced level/trend selection.

No test-year assimilation, gap filling, or width clipping. Archive event-time
experiments are not historical-as-published or operational certificates.
"""

import calendar
import gzip
import json
import math
from collections import Counter
from datetime import datetime, timezone

import numpy as np
from scipy.stats import theilslopes

from app.harness import physical_v2 as files, twin_v7 as old
from app.harness.physical_v3 import reconstruct

ROOT = files.BASE_DIR
DATA = ROOT / "data/public/annual_v9_20261031"
UTC = timezone.utc


def load(phase, station=None):
    manifest = json.loads((DATA / f"{phase}-manifest.json").read_text())
    if manifest["protocol_sha256"] != files.sha(DATA / "protocol.json"):
        raise ValueError("source protocol changed")
    groups = {}
    for entry in manifest["entries"]:
        sid = entry["station_id"]
        if station is not None and sid != station:
            continue
        path = ROOT / entry["path"]
        if files.sha(path) != entry["sha256"]:
            raise ValueError("original NOAA response changed")
        g = groups.setdefault(sid, {"site": entry["site"], "observed": {}, "rejected": Counter(), "errors": []})
        if entry["provider_error"]:
            g["errors"].append(entry["path"])
            continue
        raw = json.loads(gzip.decompress(path.read_bytes()))
        g["lat"] = float(raw["metadata"]["lat"])
        for row in raw["data"]:
            at = datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            try:
                value = float(row["v"])
                good = row.get("q") == "v" and all(f == "0" for f in row["f"].split(","))
            except (ValueError, TypeError, KeyError):
                value, good = math.nan, False
            if not good or not math.isfinite(value) or at.minute:
                g["rejected"][str(at.year)] += 1
                continue
            if at in g["observed"] and abs(g["observed"][at] - value) > 1e-9:
                raise ValueError("conflicting observations")
            g["observed"][at] = value
    return manifest, groups


def balanced_residuals(times, residual):
    """Equal month weights prevent a long missing season changing the level."""
    buckets = {}
    for at, value in zip(times, residual):
        buckets.setdefault((at.year, at.month), []).append(float(value))
    monthly = {
        key: float(np.mean(values))
        for key, values in buckets.items()
        if len(values) >= calendar.monthrange(*key)[1] * 24 * 0.7
    }
    annual = {}
    for year in sorted({t.year for t in times}):
        months = [v for (y, _), v in monthly.items() if y == year]
        if len(months) >= 9:
            annual[year] = float(np.mean(months))
    if len(annual) < 2 or max(annual) != max(t.year for t in times):
        raise ValueError("insufficient seasonal support for residual level/trend")
    return {
        "balanced_last_residual_m": annual[max(annual)],
        "balanced_slope_m_per_year": float(theilslopes(list(annual.values()), list(annual)).slope),
        "balanced_annual_means_m": {str(y): v for y, v in annual.items()},
        "balanced_months": len(monthly),
    }


def fit(g, year, window, count, plan):
    years = list(range(year - window, year))
    model = old.fit(g, years, count, plan)
    times = sorted(t for t in g["observed"] if t.year in years)
    residual = np.asarray([g["observed"][t] for t in times]) - reconstruct(times, model["coef"])
    model.update(balanced_residuals(times, residual))
    return model


def adjust(times, harmonic, model, choice, balanced=True):
    level = model["balanced_last_residual_m"] if balanced else model["last_year_mean_residual_m"]
    slope = model["balanced_slope_m_per_year"] if balanced else model["residual_slope_m_per_year"]
    return (
        harmonic
        + choice["level_weight"] * level
        + choice["trend_weight"] * slope * (old.year_coordinate(times) - model["last_year_midpoint"])
    )


def predict(times, model, choice, balanced=True):
    return adjust(times, reconstruct(times, model["coef"]), model, choice, balanced)


def select(candidates, regression_limit):
    baseline = min([c for c in candidates if c["level_weight"] == c["trend_weight"] == 0], key=lambda c: c["objective"])
    eligible = [
        c
        for c in candidates
        if baseline["objective"] - c["objective"] >= 0.001
        and all(a <= b + regression_limit for a, b in zip(c["quarter_mae_m"], baseline["quarter_mae_m"]))
    ]
    return (min(eligible, key=lambda c: c["objective"]) if eligible else baseline), baseline


def choose(station):
    plan = json.loads((DATA / "protocol.json").read_text())
    _, groups = load("history", station)
    g = groups[station]
    models, values = {}, {}

    def cached(year, window, count):
        key = (year, window, count)
        if key not in models:
            models[key] = fit(g, year, window, count, plan)
            times = [t for t in old.previous.hours(year) if t in g["observed"]]
            values[key] = (times, reconstruct(times, models[key]["coef"]))
        return models[key], values[key]

    try:
        for year in plan["selection_years"]:
            times = [t for t in old.previous.hours(year) if t in g["observed"]]
            if len(times) < 0.8 * len(old.previous.hours(year)) or any(
                sum((t.month - 1) // 3 == q for t in times) < 400 for q in range(4)
            ):
                raise ValueError("selection year/quarter lacks observations")
        candidates, legacy = [], []
        for window in plan["fit_windows_years"]:
            for count in plan["constituents"]:
                for level in plan["level_weights"]:
                    for trend in sorted(set(plan["trend_weights"] + [1])):
                        choice = {"window_years": window, "count": count, "level_weight": level, "trend_weight": trend}
                        for balanced in [True, False]:
                            if (balanced and trend not in plan["trend_weights"]) or (
                                not balanced and (window != 3 or trend == 0.25)
                            ):
                                continue
                            qs = []
                            for year in plan["selection_years"]:
                                model, (times, harmonic) = cached(year, window, count)
                                pred = adjust(times, harmonic, model, choice, balanced)
                                qs.extend(old.quarter_errors(times, pred, g["observed"]))
                            (candidates if balanced else legacy).append(
                                {**choice, "quarter_mae_m": qs, "objective": float(np.mean(qs) + 0.25 * max(qs))}
                            )
        selected, baseline = select(candidates, 0.002)
        former, former_baseline = select(legacy, 0.005)
        versions = {}
        for label, choice, balanced, base in [
            ("v9", selected, True, baseline),
            ("legacy_v7_rule", former, False, former_baseline),
        ]:
            radii, calibration, means = {}, [], []
            for year in plan["calibration_years"]:
                model, (times, harmonic) = cached(year, choice["window_years"], choice["count"])
                errors = adjust(times, harmonic, model, choice, balanced) - np.asarray(
                    [g["observed"][t] for t in times]
                )
                means.append(float(np.mean(errors)))
                qrow = {}
                for q in range(4):
                    subset = [float(e) for t, e in zip(times, errors) if (t.month - 1) // 3 == q]
                    if len(subset) < 200:
                        raise ValueError("interval quarter lacks actual residuals")
                    r = max(0.02, files.radius(subset, 0.9) * 1.1)
                    radii[str(q + 1)] = max(radii.get(str(q + 1), 0), r)
                    qrow[str(q + 1)] = {"n": len(subset), "radius_m": r}
                calibration.append({"year": year, "quarters": qrow})
            if balanced:
                # Fixed prior to seeing 2025; the same worst-season band for every hour.
                radii = {q: max(radii.values()) for q in radii}
            else:
                spread = (max(means) - min(means)) * 1.1
                radii = {q: max(r, spread) for q, r in radii.items()}
            model, _ = cached(plan["test_year"], choice["window_years"], choice["count"])
            base_model, _ = cached(plan["test_year"], base["window_years"], base["count"])
            versions[label] = {
                "choice": choice,
                "baseline_choice": base,
                "model": files.encode(model),
                "baseline_model": files.encode(base_model),
                "quarter_radii_m": radii,
                "calibration": calibration,
            }
        print("ANNUAL_FROZEN_STATION", station, selected, flush=True)
        return {
            "station_id": station,
            "site": g["site"],
            "status": "ready",
            "versions": versions,
            "candidates": candidates,
            "legacy_candidates": legacy,
            "rejected": dict(g["rejected"]),
            "errors": g["errors"],
        }
    except (ValueError, KeyError) as exc:
        print("ANNUAL_BLOCKED", station, str(exc), flush=True)
        return {"station_id": station, "site": g["site"], "status": "blocked", "reason": str(exc)}


def summarize(rows, limits):
    known = [r for r in rows if r["actual"] is not None and r["prediction"] is not None]
    availability = len(known) / len(rows) if rows else 0
    if not known:
        return {"n": 0, "expected": len(rows), "availability": availability, "passed": False}
    errors = [abs(r["actual"] - r["prediction"]) for r in known]
    base_errors = [abs(r["actual"] - r["baseline"]) for r in known]
    widths = [r["upper"] - r["lower"] for r in known]
    covered = [r["lower"] <= r["actual"] <= r["upper"] for r in known]
    interval_scores = [
        w + 20 * (max(0, r["lower"] - r["actual"]) + max(0, r["actual"] - r["upper"])) for r, w in zip(known, widths)
    ]
    mae, base_mae, coverage = float(np.mean(errors)), float(np.mean(base_errors)), float(np.mean(covered))
    checks = {
        "mae": mae <= limits["mae_m"],
        "coverage": coverage >= limits["coverage"],
        "width": max(widths) <= limits["width_m"],
        "availability": availability >= limits["availability"],
        "baseline_noninferiority": mae <= base_mae + limits["baseline_noninferiority_epsilon_m"],
    }
    return {
        "n": len(known),
        "expected": len(rows),
        "availability": availability,
        "mae_m": mae,
        "baseline_mae_m": base_mae,
        "coverage90": coverage,
        "max_width90_m": max(widths),
        "wis90_m": float(np.mean((0.5 * np.asarray(errors) + 0.05 * np.asarray(interval_scores)) / 1.5)),
        "checks": checks,
        "passed": all(checks.values()),
    }
