"""Causal, publication-lagged forecast diagnostics. Research decisions only.

Selection (2023), calibration (2024), and retrospective audit (2025/2026)
are separate. Previously inspected public archives are not a new blind test.
Empirical intervals have no exchangeability guarantee for dependent series.
"""

from __future__ import annotations

import math
import statistics as stats
from datetime import date, timedelta

MODELS = ("persistence", "mean7", "weekday28", "weekday84", "blend")
LEVELS = (0.5, 0.8, 0.9)
HORIZONS = (1, 7, 14)
LAG = 7
WINDOW = 84
MODEL_AVAILABLE_FROM = date(2025, 1, 8)
SELECTION_AVAILABLE_FROM = date(2024, 1, 8)
POLICY = {
    "min_monitor_samples": 28,
    "minimum_90_coverage": 0.80,
    "maximum_normalized_90_width": 2.0,
    "maximum_mae_ratio": 1.05,
    "drift_z_limit": 3.0,
    "scope": "工程研究阈值；不是IMO/DCSA规定，也不是现场安全保证",
}


def interval_score(actual, low, high, alpha):
    if not all(math.isfinite(x) for x in (actual, low, high, alpha)) or low > high or not 0 < alpha < 1:
        raise ValueError("invalid interval")
    return high - low + 2 / alpha * max(low - actual, 0) + 2 / alpha * max(actual - high, 0)


def weighted_interval_score(actual, point, intervals):
    if not math.isfinite(point) or not intervals:
        raise ValueError("finite point and intervals required")
    return (
        0.5 * abs(actual - point)
        + sum(
            (1 - level) / 2 * interval_score(actual, low, high, 1 - level) for level, (low, high) in intervals.items()
        )
    ) / (len(intervals) + 0.5)


def validated(rows):
    result = {}
    for row in rows:
        day = row["date"] if isinstance(row["date"], date) else date.fromisoformat(row["date"])
        value = row["calls"]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise ValueError("finite nonnegative observations required")
        if day in result:
            raise ValueError("duplicate observation date")
        result[day] = float(value)
    return result


def history_at(mapping, origin, lag=LAG):
    if lag < 0:
        raise ValueError("negative publication lag")
    cutoff = origin - timedelta(days=lag)
    days = [cutoff - timedelta(days=i) for i in reversed(range(WINDOW))]
    if any(day not in mapping for day in days):
        raise ValueError("missing_or_stale_history: 84 continuous published days required; no imputation")
    return [(day, mapping[day]) for day in days]


def estimate(kind, history, target):
    if kind not in MODELS or len(history) != WINDOW or history[-1][0] >= target:
        raise ValueError("invalid causal forecast input")
    values = [v for _, v in history]
    weekday28 = stats.mean(v for d, v in history[-28:] if d.weekday() == target.weekday())
    weekday84 = stats.mean(v for d, v in history if d.weekday() == target.weekday())
    return {
        "persistence": values[-1],
        "mean7": stats.mean(values[-7:]),
        "weekday28": weekday28,
        "weekday84": weekday84,
        "blend": 0.5 * weekday28 + 0.5 * stats.mean(values[-7:]),
    }[kind]


def scale(history):
    return max(1.0, stats.mean(v for _, v in history[-28:]))


def examples(mapping, year, horizon, lag=LAG):
    for target in sorted(d for d in mapping if d.year == year):
        origin = target - timedelta(days=horizon)
        try:
            history = history_at(mapping, origin, lag)
        except ValueError:
            continue
        yield history, target, mapping[target]


def quantile(values, level):
    values = sorted(values)
    rank = math.ceil((len(values) + 1) * level)
    if not values or rank > len(values):
        raise ValueError("insufficient calibration observations for finite empirical quantile")
    return values[rank - 1]


def fit(series, development_ports):
    """Never inspect audit years or audit ports during selection/calibration."""
    result = {
        "horizons": {},
        "policy": dict(POLICY),
        "lag_days": LAG,
        "history_days": WINDOW,
        "selection_year": 2023,
        "calibration_year": 2024,
        "development_ports": list(development_ports),
    }
    for horizon in HORIZONS:
        by_port, residuals = {}, {k: [] for k in MODELS}
        for port in development_ports:
            mapping = validated(series[port])
            pairs = list(examples(mapping, 2023, horizon))
            if len(pairs) < 180:
                raise ValueError("insufficient development-year coverage")
            by_port[port] = {k: stats.mean(abs(estimate(k, h, t) - a) / scale(h) for h, t, a in pairs) for k in MODELS}
            cal = [
                pair
                for pair in examples(mapping, 2024, horizon)
                if pair[1] - timedelta(days=horizon) >= SELECTION_AVAILABLE_FROM
            ]
            if len(cal) < 180:
                raise ValueError("insufficient separate calibration-year coverage")
            for kind in MODELS:
                residuals[kind].extend(abs(estimate(kind, h, t) - a) / scale(h) for h, t, a in cal)
        ranked = {k: stats.mean(v[k] for v in by_port.values()) for k in MODELS}
        selected = min(MODELS, key=lambda k: ranked[k])
        baseline = min((k for k in MODELS if k != "blend"), key=lambda k: ranked[k])
        result["horizons"][str(horizon)] = {
            "selected": selected,
            "baseline": baseline,
            "selection_normalized_mae": ranked,
            "port_selection_metrics": by_port,
            "radii": {k: {str(level): quantile(r, level) for level in LEVELS} for k, r in residuals.items()},
            "calibration_samples": {k: len(r) for k, r in residuals.items()},
        }
    return result


def distribution(model, history, target, kind):
    point = estimate(kind, history, target)
    intervals = {
        level: (
            max(0.0, point - model["radii"][kind][str(level)] * scale(history)),
            point + model["radii"][kind][str(level)] * scale(history),
        )
        for level in LEVELS
    }
    return {"model": kind, "point": point, "intervals": intervals}


def metrics(points):
    if not points:
        return {"n": 0, "mae": None, "wis": None, "coverage90": None, "width90_normalized": None}
    return {
        "n": len(points),
        "mae": stats.mean(p["absolute_error"] for p in points),
        "wis": stats.mean(p["wis"] for p in points),
        "coverage90": stats.mean(p["covered90"] for p in points),
        "width90_normalized": stats.mean(p["width90_normalized"] for p in points),
    }


def scored(prediction, actual, history):
    low, high = prediction["intervals"][0.9]
    return {
        "absolute_error": abs(prediction["point"] - actual),
        "wis": weighted_interval_score(actual, prediction["point"], prediction["intervals"]),
        "covered90": low <= actual <= high,
        "width90_normalized": (high - low) / scale(history),
    }


def monitor(mapping, model, origin, horizon):
    """Only use realized targets already published at the decision origin."""
    cutoff = origin - timedelta(days=LAG)
    records = {k: [] for k in {model["selected"], model["baseline"]}}
    for i in reversed(range(POLICY["min_monitor_samples"])):
        target = cutoff - timedelta(days=i)
        if target - timedelta(days=horizon) < MODEL_AVAILABLE_FROM:
            continue
        if target not in mapping:
            continue
        try:
            history = history_at(mapping, target - timedelta(days=horizon))
        except ValueError:
            continue
        for kind in records:
            records[kind].append(scored(distribution(model, history, target, kind), mapping[target], history))
    return {"latest_realized_target": cutoff.isoformat(), "models": {k: metrics(v) for k, v in records.items()}}


def forecast(mapping, calibration, origin, horizon, *, with_monitor=True):
    if horizon not in HORIZONS or origin < MODEL_AVAILABLE_FROM:
        raise ValueError("origin must follow frozen calibration; supported horizons: 1/7/14 days")
    model = calibration["horizons"][str(horizon)]
    target = origin + timedelta(days=horizon)
    base = {
        "origin": origin.isoformat(),
        "target": target.isoformat(),
        "horizon_days": horizon,
        "publication_cutoff": (origin - timedelta(days=LAG)).isoformat(),
        "source_mode": "public_archive_with_assumed_7_day_publication_lag",
        "production_authority": False,
        "research_plan_allowed": False,
    }
    try:
        history = history_at(mapping, origin)
    except ValueError as exc:
        return {**base, "status": "hold", "reasons": [str(exc)], "prediction": None}
    recent = [v for _, v in history[-14:]]
    reference = [v for _, v in history[:-14]]
    drift = abs(stats.mean(recent) - stats.mean(reference)) / max(
        1.0, stats.pstdev(reference), 0.1 * stats.mean(reference)
    )
    prediction = distribution(model, history, target, model["selected"])
    baseline = distribution(model, history, target, model["baseline"])
    monitoring = monitor(mapping, model, origin, horizon) if with_monitor else None
    reasons = []
    if drift > POLICY["drift_z_limit"]:
        reasons.append("observed_demand_shift")

    def acceptable(kind, dist):
        width = (dist["intervals"][0.9][1] - dist["intervals"][0.9][0]) / scale(history)
        if not monitoring:
            return False
        metric = monitoring["models"][kind]
        return (
            metric["n"] >= POLICY["min_monitor_samples"]
            and metric["coverage90"] >= POLICY["minimum_90_coverage"]
            and width <= POLICY["maximum_normalized_90_width"]
        )

    candidate_ok = acceptable(model["selected"], prediction)
    baseline_ok = acceptable(model["baseline"], baseline)
    skill_ok = (
        bool(monitoring)
        and monitoring["models"][model["selected"]]["n"] >= 28
        and (
            monitoring["models"][model["selected"]]["mae"]
            <= POLICY["maximum_mae_ratio"] * monitoring["models"][model["baseline"]]["mae"] + 1e-12
        )
    )
    status = "candidate"
    if reasons or not (candidate_ok or baseline_ok):
        status = "hold"
        if not (candidate_ok or baseline_ok):
            reasons.append("insufficient_monitoring_or_interval_quality")
    elif not candidate_ok or not skill_ok:
        status = "baseline" if baseline_ok else "hold"
        reasons.append("candidate_quality_requires_baseline" if baseline_ok else "no_qualified_baseline")
        if baseline_ok:
            prediction = baseline
    return {
        **base,
        "status": status,
        "reasons": reasons,
        "prediction": prediction,
        "candidate": distribution(model, history, target, model["selected"]),
        "baseline": baseline,
        "monitor": monitoring,
        "drift_z": drift,
        "scale": scale(history),
        "research_plan_allowed": status != "hold",
        "notice": "公开AIS活动指标的研究预测；区间与漂移阈值不能授权实际船舶/设备调度。",
    }
