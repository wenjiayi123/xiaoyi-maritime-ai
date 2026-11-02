"""Train-only global demand calibration, with an explicit seven-day public-data lag."""

from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

from app.harness.portwatch_data import TRAIN_PORTS

LAG_DAYS = 7


def vector(history, target):
    scale = max(1.0, statistics.mean(v for _, v in history[-28:]))
    values = [v / scale for _, v in history[-7:]]
    return [
        1.0,
        *values,
        *[float(target.weekday() == i) for i in range(7)],
        math.sin(target.timetuple().tm_yday * 2 * math.pi / 365.25),
        math.cos(target.timetuple().tm_yday * 2 * math.pi / 365.25),
    ], scale


def predict(model, history, target):
    if len(history) < 28 or history[-1][0] > target - timedelta(days=LAG_DAYS):
        raise ValueError("forecast history violates publication-lag contract")
    x, scale = vector(history, target)
    kind = model["kind"]
    if kind == "lagged_persistence":
        return history[-1][1]
    if kind == "weekday_mean":
        values = [v for d, v in history[-28:] if d.weekday() == target.weekday()]
        return statistics.mean(values)
    if kind == "mean7":
        return statistics.mean(v for _, v in history[-7:])
    return max(0.0, min(4 * scale, sum(a * b for a, b in zip(x, model["coefficients"])) * scale))


def examples(rows, first_year, last_year):
    pairs = []
    values = [(r["date"], r["calls"]) for r in rows]
    for i in range(35, len(values)):
        target, actual = values[i]
        if not first_year <= target.year <= last_year:
            continue
        window = values[i - 35 : i + 1]
        if any(b[0] - a[0] != timedelta(days=1) for a, b in zip(window, window[1:])):
            continue
        history = values[i - 35 : i - LAG_DAYS + 1]
        pairs.append((history, target, actual))
    return pairs


def fit(series):
    import numpy as np

    train = [row for port in TRAIN_PORTS if port in series for row in examples(series[port], 2019, 2022)]
    validation = [row for port in TRAIN_PORTS if port in series for row in examples(series[port], 2023, 2023)]
    if len(train) < 2000 or len(validation) < 500:
        raise ValueError("cross-port train/validation coverage insufficient")
    x, y = [], []
    for history, day, actual in train:
        f, scale = vector(history, day)
        x.append(f)
        y.append(actual / scale)
    x = np.asarray(x)
    y = np.asarray(y)
    penalty = np.eye(x.shape[1]) * 0.1
    penalty[0, 0] = 0
    coefficients = np.linalg.solve(x.T @ x + penalty, x.T @ y).tolist()
    candidates = [{"kind": kind} for kind in ["lagged_persistence", "weekday_mean", "mean7"]] + [
        {"kind": "ridge_ar7", "coefficients": coefficients}
    ]
    metrics = []
    for model in candidates:
        errors = [abs(predict(model, h, d) - a) / vector(h, d)[1] for h, d, a in validation]
        metrics.append({"kind": model["kind"], "validation_normalized_mae": statistics.mean(errors)})
    selected = min(
        candidates, key=lambda m: next(r["validation_normalized_mae"] for r in metrics if r["kind"] == m["kind"])
    )
    residuals = sorted(abs(predict(selected, h, d) - a) / vector(h, d)[1] for h, d, a in validation)
    radius = residuals[min(len(residuals) - 1, math.ceil((len(residuals) + 1) * 0.90) - 1)]
    return {
        "selected": selected,
        "candidates": metrics,
        "normalized_interval_radius": radius,
        "training_samples": len(train),
        "validation_samples": len(validation),
        "fit_ports": [p for p in TRAIN_PORTS if p in series],
        "training_period": [2019, 2022],
        "validation_period": [2023, 2023],
        "public_data_lag_days": LAG_DAYS,
        "interval_method": "pooled validation absolute residual 90th quantile; serial dependence, no exchangeability guarantee",
    }


def assess(series, calibration):
    rows = []
    for port, records in series.items():
        for year in [2024, 2025]:
            pairs = examples(records, year, year)
            if len(pairs) < 180:
                raise ValueError(f"{port}/{year} insufficient sealed forecast holdout")
            errors, baseline, covered, widths, monthly = [], [], [], [], {}
            for history, target, actual in pairs:
                estimate = predict(calibration["selected"], history, target)
                scale = vector(history, target)[1]
                radius = calibration["normalized_interval_radius"] * scale
                errors.append(abs(estimate - actual))
                baseline.append(abs(history[-1][1] - actual))
                covered.append(max(0.0, estimate - radius) <= actual <= estimate + radius)
                widths.append(estimate + radius - max(0.0, estimate - radius))
                monthly.setdefault(target.strftime("%Y-%m"), []).append(abs(estimate - actual) / scale)
            mae, base = statistics.mean(errors), statistics.mean(baseline)
            rows.append(
                {
                    "port_id": port,
                    "role": "temporal_holdout" if port in TRAIN_PORTS else "whole_port_holdout",
                    "year": year,
                    "n": len(pairs),
                    "mae_calls_per_day": mae,
                    "baseline_mae_calls_per_day": base,
                    "skill_vs_lagged_persistence": 1 - mae / max(1e-9, base),
                    "interval_coverage": statistics.mean(covered),
                    "mean_interval_width_calls_per_day": statistics.mean(widths),
                    "monthly_normalized_mae": {k: statistics.mean(v) for k, v in monthly.items()},
                    "checks": {
                        "enough_samples": len(pairs) >= 180,
                        "beats_persistence": mae <= base,
                        "coverage_at_least_80pct": statistics.mean(covered) >= 0.8,
                    },
                    "operational_release": False,
                }
            )
    return {
        "schema": "xiaoyi-crossport-demand-calibration.v1",
        "calibration": calibration,
        "holdout": rows,
        "passed_cells": sum(all(r["checks"].values()) for r in rows),
        "total_cells": len(rows),
        "all_cells_passed": all(all(r["checks"].values()) for r in rows),
        "physical_calibration": {
            "observed_variables": ["AIS-derived daily port-call indicator"],
            "unobserved_variables": [
                "terminal service capacity",
                "real queue",
                "berth/yard/equipment",
                "fuel/energy",
                "vessel dynamics",
            ],
            "status": "demand_forecast_calibrated; service/queue physical twin not identifiable from these data",
        },
        "production_authority": False,
    }
