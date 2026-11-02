"""HTTP contracts, evidence drift, identity checks, and bounded research actions."""

import json

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.harness import capability_review_v8 as api


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as value:
        yield value


def test_complete_catalog_scores_and_known_failures_are_preserved(client):
    response = client.get("/api/harness/capability-review/catalog")
    assert response.status_code == 200
    body = response.json()
    assert body["current"] and not body["production_authority"]
    rows = body["scorecard"]["components"]
    assert len(rows) == len({r["id"] for r in rows}) == 37
    assert all(r["score"] == sum(r["dimensions"].values()) * 5 for r in rows)
    assert next(r for r in rows if r["id"] == "dispatch")["score"] == 0
    assert body["results"]["forecast_statuses"]["hold"] > 0
    assert body["results"]["candidate_beats_strong_baseline_mae_cells"] == 0


def test_forecast_missing_data_and_drift_are_real_copy_operations(client):
    base = {"port_id": "port31", "origin": "2026-06-01", "horizon": 7}
    before = client.post("/api/harness/capability-review/forecast", json=base).json()
    for fault in ["source_gap", "demand_shift"]:
        response = client.post("/api/harness/capability-review/forecast", json={**base, "fault": fault})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "hold" and not body["research_plan_allowed"]
        assert not body["production_authority"]
        assert body["input_sha256"] != before["input_sha256"]
    after = client.post("/api/harness/capability-review/forecast", json=base).json()
    assert after == before


@pytest.mark.parametrize(
    "body",
    [
        {"port_id": "not-a-port"},
        {"port_id": "../../private"},
        {"port_id": "port31", "horizon": 365},
        {"port_id": "port31", "origin": "2024-01-01"},
        {"port_id": "port31", "production_authority": True},
    ],
)
def test_unknown_ports_out_of_range_inputs_and_permission_payloads_rejected(client, body):
    assert client.post("/api/harness/capability-review/forecast", json=body).status_code == 422


def test_changed_source_blocks_recompute_and_marks_catalog_historical(client, monkeypatch, tmp_path):
    registry = json.loads(api.REGISTRY.read_text())
    registry["sources"]["app/harness/predictive_v8.py"] = "0" * 64
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(api, "REGISTRY", path)
    assert client.get("/api/harness/capability-review/catalog").json()["current"] is False
    assert client.post("/api/harness/capability-review/forecast", json={"port_id": "port31"}).status_code == 409


def test_changed_report_and_loaded_code_fail_closed(client, monkeypatch, tmp_path):
    registry = json.loads(api.REGISTRY.read_text())
    registry["reports"]["forecast"]["sha256"] = "0" * 64
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(api, "REGISTRY", path)
    assert client.get("/api/harness/capability-review/catalog").status_code == 503
    monkeypatch.setattr(api, "REGISTRY", api.BASE_DIR / "config/capability_review_v8_registry.json")
    monkeypatch.setattr(api, "LOADED", {**api.LOADED, "app/harness/predictive_v8.py": "old"})
    assert client.post("/api/harness/capability-review/forecast", json={"port_id": "port31"}).status_code == 409


def test_permission_is_checked_before_any_computation(client, monkeypatch):
    def deny(*args):
        raise HTTPException(403, "denied")

    monkeypatch.setattr(api, "identity_for", deny)
    assert client.get("/api/harness/capability-review/catalog").status_code == 403
    assert client.post("/api/harness/capability-review/forecast", json={"port_id": "port31"}).status_code == 403
    assert client.post("/api/harness/capability-review/schedule", json={"port_id": "port31"}).status_code == 403


def test_optimization_concurrency_is_bounded(client):
    api.COMPUTE_LOCK.acquire()
    try:
        assert client.post("/api/harness/capability-review/schedule", json={"port_id": "port31"}).status_code == 429
    finally:
        api.COMPUTE_LOCK.release()


def test_real_optimization_response_preserves_all_five_checks(client):
    response = client.post(
        "/api/harness/capability-review/schedule", json={"port_id": "port31", "source_day": "2026-06-15"}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["robust"]["scenarios"]) == 5
    assert body["robust"]["all_declared_scenarios_feasible"]
    assert body["nominal_failed_scenarios"] > 0
    assert body["result_sha256"]
    assert not body["production_authority"]
