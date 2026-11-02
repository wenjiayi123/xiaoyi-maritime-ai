"""Causal assimilation must withhold missing context and preserve adverse results."""

import copy
from datetime import datetime, timedelta, timezone

import pytest

from app.harness import adaptive_twin as t


def test_prediction_cannot_see_target_or_unreleased_observations():
    target = datetime(2025, 1, 2, tzinfo=timezone.utc)
    model = {"basis": ["M2"], "coefficients": [1.0, 0.2, 0.1]}
    obs = {target - timedelta(minutes=6 * i): float(i) / 100 for i in range(300)}
    before = t.causal_prediction(target, obs, model, 60, 24)
    changed = copy.deepcopy(obs)
    for at in changed:
        if at > target - timedelta(minutes=60):
            changed[at] = 99999.0
    assert before == t.causal_prediction(target, changed, model, 60, 24)
    changed[target - timedelta(minutes=60)] += 1.0
    assert before != t.causal_prediction(target, changed, model, 60, 24)


def test_missing_context_withholds_instead_of_interpolating():
    at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    model = {"basis": ["M2"], "coefficients": [0.0] * 3}
    obs = {at - timedelta(minutes=6): 1.0}
    assert t.causal_prediction(at, obs, model, 6, 6) is None


def test_quality_filter_rejects_provisional_flagged_and_nonfinite():
    data = [
        dict(t=f"2025-01-01 00:{i * 6:02}", v=v, q=q, f=f)
        for i, (v, q, f) in enumerate(
            [("1", "v", "0,0,0,0"), ("2", "p", "0,0,0,0"), ("3", "v", "0,1,0,0"), ("nan", "v", "0,0,0,0")]
        )
    ]
    assert list(t.rows({"data": data}).values()) == [1.0]
    with pytest.raises(ValueError, match="duplicate"):
        t.rows({"data": [data[0], data[0]]})


def test_frozen_protocol_cannot_be_replaced_after_test(monkeypatch, tmp_path):
    path = tmp_path / "frozen.json"
    path.write_text("{}")
    monkeypatch.setattr(t, "PLAN", path)
    with pytest.raises(ValueError, match="already frozen"):
        t.freeze(tmp_path / "missing.json")


def test_existing_holdout_cannot_be_recomputed(monkeypatch, tmp_path):
    path = tmp_path / "report.json"
    path.write_text("{}")
    monkeypatch.setattr(t, "REPORT", path)
    with pytest.raises(ValueError, match="must not be overwritten"):
        t.evaluate()


def test_evaluation_records_failure_and_uses_declared_interval_limit(monkeypatch, tmp_path):
    import json

    monkeypatch.setattr(t, "BASE_DIR", tmp_path)
    monkeypatch.setattr(t, "FOLDER", tmp_path)
    monkeypatch.setattr(t, "PLAN", tmp_path / "plan.json")
    monkeypatch.setattr(t, "REPORT", tmp_path / "report.json")
    module = tmp_path / "implementation.py"
    module.write_text("fixture")
    monkeypatch.setattr(t, "__file_path", lambda: module)
    path = tmp_path / "raw.json"
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    data = [
        {
            "t": (start + timedelta(minutes=6 * i)).strftime("%Y-%m-%d %H:%M"),
            "v": str(float(i)),
            "q": "v",
            "f": "0,0,0,0",
        }
        for i in range(480)
    ]
    path.write_text(json.dumps({"data": data}))
    t.write(
        t.PLAN,
        {
            "implementation_sha256": t.sha(module),
            "stations": [
                {
                    "station_id": "synthetic",
                    "harmonic": {"basis": ["M2"], "coefficients": [0, 0, 0]},
                    "choices": [{"horizon_minutes": 6, "memory_samples": 1, "interval_radius_m": 0.01}],
                }
            ],
            "research_limits_by_horizon_minutes": {"6": {"mae_at_most_m": 0.05, "interval_width_at_most_m": 0.2}},
            "minimum_interval_coverage": 0.8,
            "minimum_availability": 0.95,
        },
    )
    t.write(
        tmp_path / "manifest.json",
        {
            "frozen_protocol_sha256": t.sha(t.PLAN),
            "entries": [
                {
                    "station_id": "synthetic",
                    "site": "fixture",
                    "season": "fixture",
                    "period": ["20250101", "20250102"],
                    "path": "raw.json",
                    "sha256": t.sha(path),
                }
            ],
        },
    )
    result = t.evaluate()
    assert result["results"][0]["evaluated_targets"] == 240
    assert result["results"][0]["blockers"] == ["mae", "coverage"]
    assert result["production_authority"] is False and result["all_research_gates_passed"] is False
