"""Physics-informed reduced tide model; fit January, select July, seal December."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import datetime, timezone

from app.config import BASE_DIR
from app.harness.contracts import digest

FOLDER = BASE_DIR / "data/public/multisite_tide_20261030"
SPEEDS = {"M2": 28.9841042, "S2": 30.0, "K1": 15.0410686, "O1": 13.9430356, "N2": 28.4397295, "Q1": 13.3986609}
EPOCH = datetime(2024, 1, 1, tzinfo=timezone.utc)


def load():
    manifest = json.loads((FOLDER / "manifest.json").read_text())
    reference = manifest.get("harmonic_basis_reference")
    if reference:
        path = (BASE_DIR / reference["path"]).resolve()
        if (
            not path.is_relative_to(FOLDER.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]
        ):
            raise ValueError("harmonic basis reference changed")
    groups = {}
    for entry in manifest["entries"]:
        path = (BASE_DIR / entry["path"]).resolve()
        if not path.is_relative_to(FOLDER.resolve()):
            raise ValueError("unregistered station source path")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("NOAA calibration source changed")
        source = json.loads(raw)["data"]
        rows = []
        for r in source:
            if r.get("q") != "v" or any(f != "0" for f in r.get("f", "").split(",")):
                continue
            try:
                value = float(r["v"])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            at = datetime.strptime(r["t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            rows.append((at, value))
        if len(rows) < 1000 or len({d for d, v in rows}) != len(rows):
            raise ValueError("station calibration records incomplete or duplicated")
        groups.setdefault(entry["station_id"], {})[entry["split"]] = {
            "rows": rows,
            "source": entry,
            "rejected_rows": len(source) - len(rows),
        }
    return manifest, groups


def vector(at, basis=None):
    hours = (at - EPOCH).total_seconds() / 3600
    return [
        1.0,
        *[
            v
            for speed in (SPEEDS[k] for k in (basis or list(SPEEDS)))
            for v in (math.cos(math.radians(speed * hours)), math.sin(math.radians(speed * hours)))
        ],
    ]


def study():
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError("请先安装 requirements-research.txt 中的固定研究依赖") from exc

    manifest, groups = load()
    results = []
    for station, parts in groups.items():
        train = parts["training"]["rows"]
        validation = parts["validation"]["rows"]
        test = parts["sealed_test"]["rows"]
        if not max(d for d, v in train) < min(d for d, v in validation) < min(d for d, v in test):
            raise ValueError("seasonal split leakage")
        y = np.asarray([v for d, v in train])
        candidates = []
        for basis in [list(SPEEDS)[:4], list(SPEEDS)]:
            x = np.asarray([vector(d, basis) for d, v in train])
            for ridge in [0.0, 1.0, 100.0]:
                penalty = np.eye(x.shape[1]) * ridge
                penalty[0, 0] = 0
                coeff = np.linalg.solve(x.T @ x + penalty, x.T @ y).tolist()
                mae = statistics.mean(
                    abs(sum(a * b for a, b in zip(vector(d, basis), coeff)) - v) for d, v in validation
                )
                candidates.append({"basis": basis, "ridge": ridge, "coefficients": coeff, "validation_mae_m": mae})
        chosen = min(candidates, key=lambda r: r["validation_mae_m"])

        def predict(at):
            return sum(a * b for a, b in zip(vector(at, chosen["basis"]), chosen["coefficients"]))

        residuals = sorted(abs(predict(d) - v) for d, v in validation)
        radius = residuals[min(len(residuals) - 1, math.ceil((len(residuals) + 1) * 0.90) - 1)]
        errors = [predict(d) - v for d, v in test]
        baseline = candidates[0]["coefficients"]
        base_mae = statistics.mean(
            abs(sum(a * b for a, b in zip(vector(d, candidates[0]["basis"]), baseline)) - v) for d, v in test
        )
        mae = statistics.mean(abs(e) for e in errors)
        coverage = statistics.mean(abs(e) <= radius for e in errors)
        checks = {
            "training_points": len(train) >= 5000,
            "test_points": len(test) >= 1000,
            "mae_at_most_20cm": mae <= 0.2,
            "matches_or_beats_unregularized_harmonic": mae <= base_mae + 1e-9,
            "interval_coverage_at_least_80pct": coverage >= 0.8,
            "interval_width_at_most_75cm": radius * 2 <= 0.75,
        }
        results.append(
            {
                "station_id": station,
                "site": parts["training"]["source"]["site"],
                "training_n": len(train),
                "validation_n": len(validation),
                "test_n": len(test),
                "model_fitted_at_cutoff": train[-1][0].isoformat(),
                "model_selected_at_cutoff": validation[-1][0].isoformat(),
                "selected_ridge": chosen["ridge"],
                "selected_basis": chosen["basis"],
                "coefficients": chosen["coefficients"],
                "candidates": candidates,
                "mae_m": mae,
                "rmse_m": math.sqrt(statistics.mean(e * e for e in errors)),
                "bias_m": statistics.mean(errors),
                "unregularized_harmonic_mae_m": base_mae,
                "interval_coverage": coverage,
                "interval_width_m": radius * 2,
                "checks": checks,
                "blockers": [k for k, v in checks.items() if not v],
                "calibration_passed": all(checks.values()),
                "source_rejected_counts": {k: p["rejected_rows"] for k, p in parts.items()},
                "preview": [
                    {
                        "target_at": d.isoformat(),
                        "actual_m": v,
                        "prediction_m": predict(d),
                        "lower_m": predict(d) - radius,
                        "upper_m": predict(d) + radius,
                    }
                    for d, v in test[:24]
                ],
                "operational_release": False,
            }
        )
    return {
        "schema": "xiaoyi-multisite-harmonic-twin.v1",
        "source_manifest_sha256": digest(manifest),
        "sources": manifest,
        "model": "four/six-constituent harmonic reduced-order candidates; fixed NOAA astronomical speeds; January coefficients, July selection/interval, December holdout",
        "constituent_speeds_degrees_per_hour": SPEEDS,
        "results": results,
        "all_station_calibration_gates_passed": all(r["calibration_passed"] for r in results),
        "physical_identifiability": {
            "calibrated": ["station water-level harmonic component and residual uncertainty"],
            "not_identified": [
                "bathymetry/UKC",
                "local wind/surge physics",
                "vessel dynamics",
                "terminal equipment",
                "energy/storage",
                "real queue/service rates",
            ],
        },
        "notice": "三港站点、跨季节的低阶物理潮汐模型标定。已剔除不合格观测；失败阈值保留。当地MLLW不可当全球高程；不代表全港物理数字孪生或作业放行。",
        "production_authority": False,
    }
