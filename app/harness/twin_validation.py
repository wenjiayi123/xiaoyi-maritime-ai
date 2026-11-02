"""Audit causal forecast pairs and held-out accuracy without granting site authority."""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone

from pydantic import Field, model_validator

from app.harness.contracts import StrictModel, digest


class ForecastPair(StrictModel):
    issued_at: datetime
    target_at: datetime
    predicted: float
    actual: float
    baseline: float
    lower: float
    upper: float
    source_row: str = Field(min_length=1, max_length=150)

    @model_validator(mode="after")
    def causal(self):
        if any(t.tzinfo is None for t in [self.issued_at, self.target_at]):
            raise ValueError("forecast timestamps require explicit timezone")
        if self.issued_at >= self.target_at:
            raise ValueError("forecast must be issued before target observation")
        if not self.lower <= self.predicted <= self.upper:
            raise ValueError("prediction must lie within its declared interval")
        return self


class ValidationRequest(StrictModel):
    site_id: str = Field(min_length=1, max_length=100)
    variable: str = Field(min_length=1, max_length=80)
    unit: str = Field(min_length=1, max_length=40)
    model_version: str = Field(min_length=1, max_length=120)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    frozen_at: datetime
    maximum_mae: float = Field(gt=0, le=1e9)
    maximum_interval_width: float = Field(gt=0, le=1e9)
    minimum_coverage: float = Field(0.8, ge=0.5, le=1.0)
    calibration: list[ForecastPair] = Field(min_length=1, max_length=2000)
    holdout: list[ForecastPair] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def split(self):
        if self.frozen_at.tzinfo is None:
            raise ValueError("frozen_at requires timezone")
        pairs = self.calibration + self.holdout
        if len({r.target_at for r in pairs}) != len(pairs) or len({r.source_row for r in pairs}) != len(pairs):
            raise ValueError("duplicated calibration/holdout observations")
        if max(r.target_at for r in self.calibration) > self.frozen_at:
            raise ValueError("calibration observations exceed frozen cutoff")
        if min(r.issued_at for r in self.holdout) < self.frozen_at:
            raise ValueError("holdout prediction precedes model freeze")
        if max(r.target_at for r in pairs) > datetime.now(timezone.utc):
            raise ValueError("future actual observations are not accepted")
        return self


def _metrics(rows):
    errors = [r.predicted - r.actual for r in rows]
    return {
        "n": len(rows),
        "mae": statistics.mean(abs(e) for e in errors),
        "rmse": math.sqrt(statistics.mean(e * e for e in errors)),
        "bias": statistics.mean(errors),
        "baseline_mae": statistics.mean(abs(r.baseline - r.actual) for r in rows),
        "interval_coverage": statistics.mean(r.lower <= r.actual <= r.upper for r in rows),
        "mean_interval_width": statistics.mean(r.upper - r.lower for r in rows),
    }


def validate(request: ValidationRequest):
    calibration, holdout = _metrics(request.calibration), _metrics(request.holdout)
    checks = {
        "calibration_sample_count": calibration["n"] >= 20,
        "holdout_sample_count": holdout["n"] >= 30,
        "mae_within_tolerance": holdout["mae"] <= request.maximum_mae,
        "beats_or_matches_persistence": holdout["mae"] <= holdout["baseline_mae"],
        "interval_coverage": holdout["interval_coverage"] >= request.minimum_coverage,
        "interval_width": holdout["mean_interval_width"] <= request.maximum_interval_width,
        "residual_drift": holdout["mae"] <= max(request.maximum_mae * 0.25, calibration["mae"] * 2),
    }
    return {
        "schema": "xiaoyi-twin-validation.v1",
        "input_sha256": digest(request.model_dump(mode="json")),
        "site_id": request.site_id,
        "variable": request.variable,
        "unit": request.unit,
        "model_version": request.model_version,
        "source_sha256": request.source_sha256,
        "calibration": calibration,
        "holdout": holdout,
        "checks": checks,
        "blockers": [k for k, v in checks.items() if not v],
        "validation_passed": all(checks.values()),
        "operational_release": False,
        "production_authority": False,
        "evidence_origin": "caller_supplied_pairs; source_authenticity_requires_separate_verification",
        "notice": "时序留出点预测与区间校验；阈值为显式研究参数。此结果不验证物理孪生、现场传感器、实船动力学或第三方认证。",
    }
