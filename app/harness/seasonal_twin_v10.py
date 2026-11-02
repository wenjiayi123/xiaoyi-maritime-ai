"""Seasonal signed residual calibration, separate from harmonic point capacity.

Intervals are never clipped to a width gate. All calibration labels precede the
annual issue year. No test-year observations enter point forecasts or bounds.
"""

import math
from datetime import datetime

import numpy as np

from app.harness import annual_v9 as old

METHODS = [
    "v9_global",
    "quarter_symmetric",
    "quarter_signed",
    "quarter_signed_union",
    "seasonal_signed90",
    "seasonal_signed120",
]


def coordinate(at):
    return (
        (at - datetime(at.year, 1, 1, tzinfo=at.tzinfo)).total_seconds()
        / 86400
        * 365.25
        / (366 if __import__("calendar").isleap(at.year) else 365)
    )


def signed_quantile(values, probability):
    ordered = sorted(float(v) for v in values)
    if len(ordered) < 200:
        raise ValueError("calibration segment lacks 200 true observations")
    rank = (
        math.floor((len(ordered) + 1) * probability)
        if probability < 0.5
        else math.ceil((len(ordered) + 1) * probability)
    )
    return ordered[max(0, min(len(ordered) - 1, rank - 1))]


def limits(errors, method, target):
    # error convention: actual - point forecast, unlike V7's point - actual.
    q = (target.month - 1) // 3
    if method == "v9_global":
        bands = []
        for y in sorted({t.year for t, e in errors}):
            for quarter in range(4):
                own = [abs(e) for t, e in errors if t.year == y and (t.month - 1) // 3 == quarter]
                if len(own) < 200:
                    raise ValueError("calibration quarter lacks true observations")
                bands.append(old.files.radius(own, 0.9) * 1.1)
        radius = max(0.02, *bands)
        return -radius, radius
    if method.startswith("quarter"):
        selected = [(t, e) for t, e in errors if (t.month - 1) // 3 == q]
    else:
        half = int(method.removeprefix("seasonal_signed")) / 2
        selected = [
            (t, e)
            for t, e in errors
            if min(abs(coordinate(t) - coordinate(target)), 365.25 - abs(coordinate(t) - coordinate(target))) <= half
        ]
    if method == "quarter_symmetric":
        radius = max(
            0.02,
            *[
                old.files.radius([e for t, e in selected if t.year == y], 0.9) * 1.1
                for y in sorted({t.year for t, e in selected})
            ],
        )
        return -radius, radius
    if method == "quarter_signed_union":
        lower = min(
            signed_quantile([e for t, e in selected if t.year == y], 0.05)
            for y in sorted({t.year for t, e in selected})
        )
        upper = max(
            signed_quantile([e for t, e in selected if t.year == y], 0.95)
            for y in sorted({t.year for t, e in selected})
        )
    else:
        lower = signed_quantile([e for t, e in selected], 0.05)
        upper = signed_quantile([e for t, e in selected], 0.95)
    center = (lower + upper) / 2
    half = max(0.02, (upper - lower) / 2 * 1.1)
    # Maintain a coherent central interval containing the harmonic point estimate.
    return min(0.0, center - half), max(0.0, center + half)


def calibration(g, choice, plan):
    errors = []
    for year in plan["calibration_years"]:
        model = old.fit(g, year, choice["window_years"], choice["count"], plan)
        times = [t for t in old.old.previous.hours(year) if t in g["observed"]]
        values = old.predict(times, model, choice)
        for quarter in range(4):
            if sum((t.month - 1) // 3 == quarter for t in times) < 200:
                raise ValueError("calibration quarter lacks actual residuals")
        errors.extend((t, float(g["observed"][t] - v)) for t, v in zip(times, values))
    return errors


def bands_for_year(errors, method, year):
    # Repeated hourly values share a daily band, avoiding 8,760 sorts.
    cache = {}
    shared = {}
    coordinates = np.asarray([coordinate(t) for t, e in errors])
    residuals = np.asarray([e for t, e in errors])
    for at in old.old.previous.hours(year):
        day = at.date()
        if day not in cache:
            target = at.replace(hour=12)
            if method.startswith("seasonal_signed"):
                half_window = int(method.removeprefix("seasonal_signed")) / 2
                distance = abs(coordinates - coordinate(target))
                values = residuals[np.minimum(distance, 365.25 - distance) <= half_window]
                lo, hi = signed_quantile(values, 0.05), signed_quantile(values, 0.95)
                center, half = (lo + hi) / 2, max(0.02, (hi - lo) / 2 * 1.1)
                cache[day] = (min(0.0, center - half), max(0.0, center + half))
            else:
                key = "all" if method == "v9_global" else (target.month - 1) // 3
                if key not in shared:
                    shared[key] = limits(errors, method, target)
                cache[day] = shared[key]
    return {day.isoformat(): list(values) for day, values in cache.items()}


def rows(times, pred, baseline, observed, bands):
    result = []
    for at, value, base in zip(times, pred, baseline):
        lo, hi = bands[at.date().isoformat()]
        result.append(
            {
                "time": at.isoformat(),
                "quarter": str((at.month - 1) // 3 + 1),
                "actual": observed.get(at),
                "prediction": float(value),
                "baseline": float(base),
                "lower": float(value + lo),
                "upper": float(value + hi),
            }
        )
    return result


def score(records, plan):
    return {
        "annual": old.summarize(records, plan["limits"]),
        "quarters": {
            str(q): old.summarize([r for r in records if r["quarter"] == str(q)], plan["limits"]) for q in range(1, 5)
        },
    }
