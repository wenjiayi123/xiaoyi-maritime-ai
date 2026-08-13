from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "data/contracts/port_site_admission_v1.json"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _payload_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def evaluate_live_metadata(
    metadata: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Fail-closed admission for read-only normalized site data.

    Passing this gate allows display in recommendation workflows. It never
    enables production dispatch authority.
    """

    contract = _load_contract()
    thresholds = contract["read_only_quality_thresholds"]
    blockers: list[str] = []
    missing = [field for field in contract["required_live_metadata"] if field not in metadata]
    if missing:
        blockers.append(f"missing_metadata:{','.join(missing)}")
    if metadata.get("data_mode") != "live":
        blockers.append("data_mode_not_live")
    if metadata.get("live_data_verified") is not True:
        blockers.append("live_data_not_verified")
    if metadata.get("schema_version") != "port-ops.v1":
        blockers.append("schema_version_incompatible")
    for field in (
        "source_manifest_sha256",
        "field_mapping_sha256",
        "quality_report_sha256",
        "drift_report_sha256",
        "calibration_report_sha256",
    ):
        if not SHA256_PATTERN.fullmatch(str(metadata.get(field) or "")):
            blockers.append(f"invalid_sha256:{field}")

    observed_at = _parse_time(metadata.get("observed_at"))
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    freshness_seconds: float | None = None
    if observed_at is None:
        blockers.append("observed_at_invalid_or_timezone_missing")
    else:
        freshness_seconds = (checked_at - observed_at).total_seconds()
        if freshness_seconds < -60:
            blockers.append("observed_at_too_far_in_future")
        if freshness_seconds > thresholds["maximum_freshness_seconds"]:
            blockers.append("data_stale")

    quality = metadata.get("quality_report")
    if not isinstance(quality, dict):
        blockers.append("quality_report_missing")
        quality = {}
    quality_checks = (
        (quality.get("schema_validation_passed") is True, "schema_validation_failed"),
        (quality.get("timezone_normalized") is True, "timezone_not_normalized"),
        (
            _as_float(quality.get("completeness_rate"), -1)
            >= thresholds["minimum_completeness_rate"],
            "completeness_below_threshold",
        ),
        (
            _as_float(quality.get("duplicate_rate"), 2) <= thresholds["maximum_duplicate_rate"],
            "duplicate_rate_above_threshold",
        ),
        (
            _as_float(quality.get("out_of_order_rate"), 2)
            <= thresholds["maximum_out_of_order_rate"],
            "out_of_order_rate_above_threshold",
        ),
        (
            _as_int(quality.get("physical_constraint_violations"), 1)
            <= thresholds["maximum_physical_constraint_violations"],
            "physical_constraint_violation",
        ),
    )
    blockers.extend(reason for passed, reason in quality_checks if not passed)
    if metadata.get("quality_report_sha256") != _payload_sha256(quality):
        blockers.append("quality_report_hash_mismatch")

    drift = metadata.get("drift_report")
    if not isinstance(drift, dict):
        blockers.append("drift_report_missing")
        drift = {}
    drift_checks = (
        (drift.get("status") == thresholds["drift_status_required"], "drift_status_not_passed"),
        (
            _as_float(drift.get("feature_coverage_rate"), -1)
            >= thresholds["minimum_feature_coverage_rate"],
            "feature_coverage_below_threshold",
        ),
        (
            _as_float(drift.get("max_population_stability_index"), 2)
            <= thresholds["maximum_population_stability_index"],
            "population_drift_above_threshold",
        ),
    )
    blockers.extend(reason for passed, reason in drift_checks if not passed)
    if metadata.get("drift_report_sha256") != _payload_sha256(drift):
        blockers.append("drift_report_hash_mismatch")
    blockers = list(dict.fromkeys(blockers))
    return {
        "contract_id": contract["contract_id"],
        "read_only_admission_passed": not blockers,
        "checked_at": checked_at.isoformat(),
        "freshness_seconds": freshness_seconds,
        "blockers": blockers,
        "recommendation_only": True,
        "dispatch_allowed": False,
        "production_authority": False,
    }


def site_admission_payload() -> dict[str, Any]:
    contract = _load_contract()
    mode = os.getenv("XIAOYI_PORT_DATA_MODE", "operations_sandbox").strip().lower()
    contract["artifact"] = str(CONTRACT_PATH.relative_to(ROOT))
    contract["artifact_sha256"] = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()
    contract["runtime"] = {
        "configured_data_mode": mode,
        "read_only_admission_status": (
            "not_evaluated_live_endpoint" if mode == "live" else "blocked_non_live_data"
        ),
        "recommendation_only": True,
        "dispatch_allowed": False,
        "production_authority": False,
        "notice": (
            "The status endpoint does not contact a site automatically. A live payload is "
            "evaluated fail-closed when the read-only adapter is called."
        ),
    }
    return contract
