from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.site_admission import evaluate_live_metadata


client = TestClient(app)
HASH = "a" * 64


def _valid_metadata(now: datetime) -> dict[str, object]:
    quality = {
        "schema_validation_passed": True,
        "timezone_normalized": True,
        "completeness_rate": 0.999,
        "duplicate_rate": 0.0,
        "out_of_order_rate": 0.0,
        "physical_constraint_violations": 0,
    }
    drift = {
        "status": "passed",
        "feature_coverage_rate": 1.0,
        "max_population_stability_index": 0.05,
    }

    def digest(payload: object) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    return {
        "data_mode": "live",
        "live_data_verified": True,
        "schema_version": "port-ops.v1",
        "source_system": "authorized-site-gateway",
        "source_dataset_id": "site-window-20260813",
        "source_manifest_sha256": HASH,
        "field_mapping_version": "site-map.v1",
        "field_mapping_sha256": HASH,
        "quality_report_sha256": digest(quality),
        "drift_report_sha256": digest(drift),
        "calibration_report_sha256": HASH,
        "observed_at": now.isoformat(),
        "generated_at": now.isoformat(),
        "timezone": "Asia/Shanghai",
        "quality_report": quality,
        "drift_report": drift,
    }


def test_site_admission_status_is_blocked_and_never_grants_authority() -> None:
    payload = client.get("/api/system/site-admission").json()
    assert payload["current_evidence"]["overall_status"] == "blocked_pending_site"
    assert payload["runtime"]["dispatch_allowed"] is False
    assert payload["runtime"]["production_authority"] is False
    assert len(payload["production_admission_gates"]) == 7
    assert len(payload["artifact_sha256"]) == 64


def test_live_read_only_metadata_passes_only_all_quality_and_drift_gates() -> None:
    now = datetime.now(timezone.utc)
    result = evaluate_live_metadata(_valid_metadata(now), now=now)
    assert result["read_only_admission_passed"] is True
    assert result["dispatch_allowed"] is False
    assert result["production_authority"] is False

    stale = _valid_metadata(now)
    stale["observed_at"] = "2025-01-01T00:00:00+00:00"
    stale_result = evaluate_live_metadata(stale, now=now)
    assert stale_result["read_only_admission_passed"] is False
    assert "data_stale" in stale_result["blockers"]

    drifting = _valid_metadata(now)
    drifting["drift_report"] = {
        "status": "blocked",
        "feature_coverage_rate": 0.8,
        "max_population_stability_index": 0.35,
    }
    drifting["drift_report_sha256"] = hashlib.sha256(
        json.dumps(drifting["drift_report"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    drift_result = evaluate_live_metadata(drifting, now=now)
    assert drift_result["read_only_admission_passed"] is False
    assert "population_drift_above_threshold" in drift_result["blockers"]
