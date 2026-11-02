"""Port-local uncertainty calibration with delayed, once-only online feedback.

The point model is the frozen V8 weekday84 baseline. ACI is bounded and applied
with delayed observations; no universal coverage theorem is claimed here.
"""

from __future__ import annotations

import math
import statistics as stats
from datetime import date, timedelta

from app.harness import predictive_v8 as old

METHODS = {
    "global_v8": {"window": None, "gamma": 0},
    "local_frozen": {"window": 0, "gamma": 0},
    "rolling90": {"window": 90, "gamma": 0},
    "rolling180": {"window": 180, "gamma": 0},
    "rolling365": {"window": 365, "gamma": 0},
    "aci90": {"window": 90, "gamma": 0.01},
    "aci180": {"window": 180, "gamma": 0.01},
}
MIN_RESIDUALS = 60


def point_cache(mapping, horizon, end=date(2026, 7, 24)):
    cache = {}
    first = date(2024, 1, 8) + timedelta(days=horizon)
    for offset in range((end - first).days + 1):
        target = first + timedelta(days=offset)
        origin = target - timedelta(days=horizon)
        if origin < date(2024, 1, 8):
            continue
        try:
            history = old.history_at(mapping, origin)
        except ValueError:
            continue
        point = old.estimate("weekday84", history, target)
        scale = old.scale(history)
        recent = [v for _, v in history[-14:]]
        past = [v for _, v in history[:-14]]
        drift = abs(stats.mean(recent) - stats.mean(past)) / max(1.0, stats.pstdev(past), 0.1 * stats.mean(past))
        actual = mapping.get(target)
        cache[target] = {
            "point": point,
            "scale": scale,
            "actual": actual,
            "error": abs(actual - point) / scale if actual is not None else None,
            "drift_z": drift,
        }
    return cache


def empirical_radius(residuals, level):
    ordered = sorted(residuals)
    rank = math.ceil((len(ordered) + 1) * level)
    if len(ordered) < MIN_RESIDUALS or rank > len(ordered):
        return None
    return ordered[rank - 1]


def replay(cache, model, horizon, method, year, *, keep=True):
    config = METHODS[method]
    begin = date(year, 1, 8)
    end = date(year, 12, 31) if year == 2025 else date(2026, 7, 24)
    frozen = [r["error"] for t, r in cache.items() if t.year == year - 1 and r["error"] is not None]
    alpha = 0.1
    pending, feedback, rows = {}, [], []
    origin = begin
    while origin + timedelta(days=horizon) <= end:
        target, cutoff = origin + timedelta(days=horizon), origin - timedelta(days=old.LAG)
        # Only the forecast issued for this target receives its delayed feedback.
        matured = pending.get(cutoff)
        if matured is not None and cutoff in cache and cache[cutoff]["actual"] is not None:
            error = not (matured["intervals"][0.9][0] <= cache[cutoff]["actual"] <= matured["intervals"][0.9][1])
            alpha = min(0.25, max(0.02, alpha + config["gamma"] * (0.1 - float(error))))
            feedback.append({"target": cutoff, "covered": not error})
        item = cache.get(target)
        row = {
            "origin": origin.isoformat(),
            "target": target.isoformat(),
            "horizon_days": horizon,
            "publication_cutoff": cutoff.isoformat(),
            "method": method,
            "alpha90": alpha,
            "last_feedback_target": feedback[-1]["target"].isoformat() if feedback else None,
            "monitor_samples": min(28, len(feedback)),
            "production_authority": False,
        }
        if item is None:
            row.update(prediction=None, status="hold", reasons=["missing_input_or_truth"])
        else:
            window = config["window"]
            residuals = (
                frozen
                if window == 0
                else [
                    r["error"]
                    for t, r in cache.items()
                    if cutoff - timedelta(days=window or 365) < t <= cutoff and r["error"] is not None
                ]
            )
            radii = {
                level: (
                    model["radii"]["weekday84"][str(level)]
                    if window is None
                    else empirical_radius(residuals, min(0.98, max(0.02, level + (0.1 - alpha))))
                )
                for level in old.LEVELS
            }
            if any(v is None for v in radii.values()):
                row.update(prediction=None, status="hold", reasons=["insufficient_local_residuals"])
            else:
                intervals = {
                    level: (max(0.0, item["point"] - radius * item["scale"]), item["point"] + radius * item["scale"])
                    for level, radius in radii.items()
                }
                pred = {"point": item["point"], "intervals": intervals}
                pending[target] = pred
                low, high = intervals[0.9]
                coverage = stats.mean(v["covered"] for v in feedback[-28:]) if feedback else None
                reasons = []
                if len(feedback) < 28 or coverage < 0.8:
                    reasons.append("monitor_not_ready_or_undercoverage")
                if (high - low) / item["scale"] > 2:
                    reasons.append("interval_too_wide")
                if item["drift_z"] > 3:
                    reasons.append("observed_demand_shift")
                actual = item["actual"]
                row.update(
                    prediction=pred,
                    actual=actual,
                    scale=item["scale"],
                    calibration_n=len(residuals) if window is not None else model["calibration_samples"]["weekday84"],
                    calibration_latest_day=(
                        "2024-12-31" if window is None else cutoff.isoformat() if window else f"{year - 1}-12-31"
                    ),
                    absolute_error=abs(actual - item["point"]) if actual is not None else None,
                    covered90=low <= actual <= high if actual is not None else None,
                    width90_normalized=(high - low) / item["scale"],
                    wis=old.weighted_interval_score(actual, item["point"], intervals) if actual is not None else None,
                    monitor_coverage90=coverage,
                    drift_z=item["drift_z"],
                    status="hold" if reasons else "research_eligible",
                    reasons=reasons,
                )
        if target >= date(year, 1, 22):
            rows.append(row)
        origin += timedelta(days=1)

    def summarize(subset):
        scored = [r for r in subset if r.get("prediction") and r.get("actual") is not None]
        return {
            "expected": len(subset),
            "n": len(scored),
            "coverage90": stats.mean(r["covered90"] for r in scored) if scored else None,
            "mean_width90_normalized": stats.mean(r["width90_normalized"] for r in scored) if scored else None,
            "maximum_width90_normalized": max((r["width90_normalized"] for r in scored), default=None),
            "normalized_wis": stats.mean(r["wis"] / r["scale"] for r in scored) if scored else None,
            "mae": stats.mean(r["absolute_error"] for r in scored) if scored else None,
            "retained": sum(r["status"] == "research_eligible" for r in subset),
            "coverage_gate": bool(scored) and stats.mean(r["covered90"] for r in scored) >= 0.8,
            "width_gate": bool(scored) and stats.mean(r["width90_normalized"] for r in scored) <= 2,
        }

    summary = summarize(rows)
    summary["quarters"] = {
        str(q): summarize([r for r in rows if (date.fromisoformat(r["target"]).month - 1) // 3 + 1 == q])
        for q in range(1, 5)
    }
    return {"method": method, "year": year, "horizon_days": horizon, "summary": summary, "rows": rows if keep else []}
