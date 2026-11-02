"""Frozen, causal state assimilation; independent 2025 seasonal replay, not UKC clearance."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import statistics
from datetime import datetime, timedelta, timezone

from app.config import BASE_DIR
from app.harness import multisite_twin

FOLDER = BASE_DIR / "data/public/adaptive_tide_20261030"
PLAN = FOLDER / "frozen-protocol.json"
REPORT = FOLDER / "report.json"
PERIODS = {
    "winter": ["20250101", "20250108"],
    "summer": ["20250701", "20250708"],
    "late_year": ["20251201", "20251208"],
}
LIMITS = {6: (0.05, 0.20), 60: (0.10, 0.50), 360: (0.20, 0.75)}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def rows(raw):
    result = {}
    for row in raw["data"]:
        if row.get("q") != "v" or any(x != "0" for x in row.get("f", "").split(",")):
            continue
        try:
            value = float(row["v"])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        at = datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        if at in result:
            raise ValueError("duplicate water-level event time")
        result[at] = value
    return result


def harmonic(at, model):
    return sum(a * b for a, b in zip(multisite_twin.vector(at, model["basis"]), model["coefficients"]))


def causal_prediction(at, observed, model, horizon, memory):
    """Target at, observation cutoff at-horizon. No interpolation or future assimilation."""
    cutoff = at - timedelta(minutes=horizon)
    times = [cutoff - timedelta(minutes=6 * k) for k in range(memory)]
    if any(t not in observed for t in times):
        return None
    innovation = statistics.mean(observed[t] - harmonic(t, model) for t in times)
    return harmonic(at, model) + innovation, observed[cutoff], cutoff


def freeze(legacy_report):
    if PLAN.exists() or REPORT.exists():
        raise ValueError("protocol already frozen; never overwrite after seeing held-out results")
    FOLDER.mkdir(parents=True, exist_ok=True)
    source = json.loads(legacy_report.read_text())
    _, groups = multisite_twin.load()
    stations = []
    for old in source["multisite_physical_calibration"]["results"]:
        model = {"basis": old["selected_basis"], "coefficients": old["coefficients"]}
        parts = groups[old["station_id"]]
        # December 2024 has now been inspected: explicitly development, never a new test.
        development = [dict(parts[p]["rows"]) for p in ("validation", "sealed_test")]
        choices = []
        for horizon in LIMITS:
            candidates = []
            for memory in [1, 6, 24]:
                errors = []
                for obs in development:
                    start = min(obs) + timedelta(days=1)
                    for at, actual in sorted(obs.items()):
                        if at < start:
                            continue
                        pred = causal_prediction(at, obs, model, horizon, memory)
                        if pred:
                            errors.append(abs(pred[0] - actual))
                candidates.append({"memory_samples": memory, "mae_m": statistics.mean(errors), "errors": errors})
            chosen = min(candidates, key=lambda c: c["mae_m"])
            residuals = sorted(chosen["errors"])
            radius = residuals[min(len(residuals) - 1, math.ceil((len(residuals) + 1) * 0.90) - 1)]
            choices.append(
                {
                    "horizon_minutes": horizon,
                    "memory_samples": chosen["memory_samples"],
                    "interval_radius_m": radius,
                    "development_n": len(residuals),
                    "candidates": [{k: v for k, v in c.items() if k != "errors"} for c in candidates],
                }
            )
        stations.append({"station_id": old["station_id"], "site": old["site"], "harmonic": model, "choices": choices})
    plan = {
        "schema": "xiaoyi-adaptive-twin-frozen-protocol.v1",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "implementation_sha256": sha(__file_path()),
        "legacy_report_path": str(legacy_report.relative_to(BASE_DIR)),
        "legacy_report_sha256": sha(legacy_report),
        "development_manifest_sha256": sha(multisite_twin.FOLDER / "manifest.json"),
        "harmonic_implementation_sha256": sha(BASE_DIR / "app/harness/multisite_twin.py"),
        "development": "January 2024 harmonic coefficients; July AND already-viewed December 2024 select memory and 90% residual interval. December 2024 is no longer a new holdout.",
        "fresh_holdout_periods": PERIODS,
        "stations": stations,
        "horizons_minutes": list(LIMITS),
        "research_limits_by_horizon_minutes": {
            str(k): {"mae_at_most_m": v[0], "interval_width_at_most_m": v[1]} for k, v in LIMITS.items()
        },
        "minimum_interval_coverage": 0.8,
        "minimum_availability": 0.95,
        "model": "fixed harmonic forecast plus mean of recent observed harmonic residuals, all inputs <= target minus horizon",
        "assumptions": [
            "Verified historical observations assumed available at event time; actual historical release times and live feed latency unknown.",
            "First 24h of each eight-day block is context; remaining seven days evaluated at six-minute cadence.",
            "Missing or rejected context withholds forecast; no interpolation, target leakage, interval retuning or test-based selection.",
            "MLLW is local station datum. Fixed filter and validation residual interval; correlated six-minute errors do not provide field-risk certification.",
            "Short-horizon assimilation does not repair or replace the failed month-ahead open-loop experiment.",
            "Three US ports and 21 target days per port are limited physical diversity, not all-weather international twin qualification.",
        ],
        "production_authority": False,
    }
    write(PLAN, plan)
    return plan


def __file_path():
    return BASE_DIR / "app/harness/adaptive_twin.py"


def evaluate():
    if REPORT.exists():
        raise ValueError("held-out evaluation already exists; frozen result must not be overwritten")
    plan = json.loads(PLAN.read_text())
    if plan["implementation_sha256"] != sha(__file_path()):
        raise ValueError("implementation changed after protocol freeze")
    manifest = json.loads((FOLDER / "manifest.json").read_text())
    if manifest["frozen_protocol_sha256"] != sha(PLAN):
        raise ValueError("data acquired against a different protocol")
    models = {m["station_id"]: m for m in plan["stations"]}
    results = []
    trace = FOLDER / "heldout-predictions.jsonl.gz"
    with gzip.open(trace, "wt", encoding="utf-8") as out:
        for entry in manifest["entries"]:
            path = BASE_DIR / entry["path"]
            if sha(path) != entry["sha256"]:
                raise ValueError("NOAA source changed")
            raw = json.loads(path.read_text())
            obs = rows(raw)
            start = datetime.strptime(entry["period"][0], "%Y%m%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            end = datetime.strptime(entry["period"][1], "%Y%m%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            station = models[entry["station_id"]]
            for choice in station["choices"]:
                horizon = choice["horizon_minutes"]
                errors, baseline_errors, covered = [], [], []
                expected = int((end - start).total_seconds() / 360)
                for i in range(expected):
                    at = start + timedelta(minutes=6 * i)
                    pred = causal_prediction(at, obs, station["harmonic"], horizon, choice["memory_samples"])
                    if pred is None or at not in obs:
                        continue
                    prediction, baseline, cutoff = pred
                    error = prediction - obs[at]
                    errors.append(error)
                    baseline_errors.append(abs(baseline - obs[at]))
                    covered.append(abs(error) <= choice["interval_radius_m"])
                    out.write(
                        json.dumps(
                            {
                                "station_id": entry["station_id"],
                                "season": entry["season"],
                                "horizon_minutes": horizon,
                                "target_at": at.isoformat(),
                                "input_cutoff": cutoff.isoformat(),
                                "actual_m": obs[at],
                                "prediction_m": prediction,
                                "persistence_m": baseline,
                                "radius_m": choice["interval_radius_m"],
                            }
                        )
                        + "\n"
                    )
                if not errors:
                    raise ValueError("no evaluable observations")
                mae = statistics.mean(abs(e) for e in errors)
                coverage = statistics.mean(covered)
                width = 2 * choice["interval_radius_m"]
                limits = plan["research_limits_by_horizon_minutes"][str(horizon)]
                checks = {
                    "mae": mae <= limits["mae_at_most_m"],
                    "coverage": coverage >= plan["minimum_interval_coverage"],
                    "interval_width": width <= limits["interval_width_at_most_m"],
                    "availability": len(errors) / expected >= plan["minimum_availability"],
                    "no_worse_than_persistence": mae <= statistics.mean(baseline_errors),
                }
                results.append(
                    {
                        "station_id": entry["station_id"],
                        "site": entry["site"],
                        "season": entry["season"],
                        "horizon_minutes": horizon,
                        "expected_targets": expected,
                        "evaluated_targets": len(errors),
                        "source_rows": len(raw["data"]),
                        "source_rejected_rows": len(raw["data"]) - len(obs),
                        "availability": len(errors) / expected,
                        "mae_m": mae,
                        "rmse_m": math.sqrt(statistics.mean(e * e for e in errors)),
                        "bias_m": statistics.mean(errors),
                        "persistence_mae_m": statistics.mean(baseline_errors),
                        "interval_coverage": coverage,
                        "interval_width_m": width,
                        "checks": checks,
                        "blockers": [k for k, v in checks.items() if not v],
                        "research_gates_passed": all(checks.values()),
                        "operational_release": False,
                    }
                )
    result = {
        "schema": "xiaoyi-causal-assimilation-twin.v1",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "protocol_sha256": sha(PLAN),
        "manifest_sha256": sha(FOLDER / "manifest.json"),
        "protocol": plan,
        "sources": manifest,
        "results": results,
        "trace_path": str(trace.relative_to(BASE_DIR)),
        "trace_sha256": sha(trace),
        "all_research_gates_passed": all(r["research_gates_passed"] for r in results),
        "production_authority": False,
        "physical_identifiability": "Short-horizon station water level only. UKC/bathymetry, weather/surge drivers, vessel/terminal/energy dynamics remain uncalibrated.",
        "notice": "2025新留出短期状态同化复验，不能替代2024长期开环失败。阈值为本项目冻结的研究门禁，不是监管或超级智能认证。",
    }
    write(REPORT, result)
    return result


def report():
    if not REPORT.exists():
        raise ValueError("尚无冻结的2025状态同化复验；请显式运行研究脚本")
    value = json.loads(REPORT.read_text())
    issues = []
    checks = [
        (PLAN, value["protocol_sha256"]),
        (FOLDER / "manifest.json", value["manifest_sha256"]),
        (__file_path(), value["protocol"]["implementation_sha256"]),
        (BASE_DIR / "app/harness/multisite_twin.py", value["protocol"]["harmonic_implementation_sha256"]),
        (BASE_DIR / value["trace_path"], value["trace_sha256"]),
        (BASE_DIR / value["protocol"]["legacy_report_path"], value["protocol"]["legacy_report_sha256"]),
    ]
    checks.extend((BASE_DIR / e["path"], e["sha256"]) for e in value["sources"]["entries"])
    for path, expected in checks:
        if not path.exists() or sha(path) != expected:
            issues.append(str(path.relative_to(BASE_DIR)))
    value["historical_only"] = bool(issues)
    value["current_validation_issues"] = issues
    return value
