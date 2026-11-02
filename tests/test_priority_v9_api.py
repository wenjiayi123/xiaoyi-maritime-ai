import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.harness import priority_v9 as api


@pytest.fixture
def client():
    application = FastAPI()
    application.include_router(api.router)
    with TestClient(application) as value:
        yield value


def test_registered_catalog_retains_all_scores_and_failed_trials(client):
    response = client.get("/api/harness/priority-v9/catalog")
    assert response.status_code == 200
    data = response.json()
    assert data["current"] and not data["production_authority"]
    assert len(data["scorecard"]["components"]) == 37
    assert all(c["score"] == 5 * sum(c["dimensions"].values()) for c in data["scorecard"]["components"])
    assert len(data["forecast"]["summary"]) == 3 and len(data["annual"]["cells"]) == 16
    assert any(not r["research_admission"] for r in data["rl"]["aggregate"])


def test_forecast_recomputes_without_future_truth_and_preserves_missingness(client):
    args = {"port_id": "port1318", "origin": "2026-06-01", "horizon": 7}
    before = client.post("/api/harness/priority-v9/forecast", json=args)
    assert before.status_code == 200
    result = before.json()
    assert result["publication_cutoff"] == "2026-05-25" and result["target"] == "2026-06-08"
    assert not {"actual", "wis", "absolute_error", "covered90"} & result.keys()
    assert result["production_authority"] is False
    gap = client.post("/api/harness/priority-v9/forecast", json={**args, "fault": "source_gap"}).json()
    assert gap["prediction"] is None and gap["status"] == "hold"
    assert client.post("/api/harness/priority-v9/forecast", json=args).json() == result


@pytest.mark.parametrize(
    "args",
    [
        {"port_id": "port1318", "origin": "2025-01-01"},
        {"port_id": "port1318", "origin": "2026-07-24", "horizon": 14},
        {"port_id": "../../private"},
        {"port_id": "port1318", "production_authority": True},
    ],
)
def test_invalid_or_unregistered_inputs_rejected(client, args):
    assert client.post("/api/harness/priority-v9/forecast", json=args).status_code == 422


def test_annual_gate_requires_each_quarter_and_blocks_missing_model(client):
    gap = client.post("/api/harness/priority-v9/annual", json={"station_id": "9414290"}).json()
    assert gap["status"] == "hold" and "rows" not in gap
    failure = client.post("/api/harness/priority-v9/annual", json={"station_id": "8724580"}).json()
    assert failure["annual_checks"]["passed"] and not failure["quarter_checks"]["4"]["passed"]
    assert failure["status"] == "hold"
    ready = client.post("/api/harness/priority-v9/annual", json={"station_id": "8771450"}).json()
    assert ready["status"] == "research_only" and len(ready["rows"]) == 24
    assert ready["datum"] == "MLLW" and ready["units"] == "m" and not ready["production_authority"]
    assert (
        client.post("/api/harness/priority-v9/annual", json={"station_id": "8771450", "day": "2026-01-01"}).status_code
        == 422
    )


def test_changed_code_or_report_invalidates_results(client, monkeypatch, tmp_path):
    registry = json.loads(api.REGISTRY.read_text())
    registry["sources"]["app/harness/interval_v9.py"] = "changed"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(api, "REGISTRY", path)
    assert not client.get("/api/harness/priority-v9/catalog").json()["current"]
    assert client.post("/api/harness/priority-v9/forecast", json={"port_id": "port1318"}).status_code == 409
    registry["reports"]["rl"]["sha256"] = "changed"
    path.write_text(json.dumps(registry))
    assert client.get("/api/harness/priority-v9/catalog").status_code == 503


def test_identity_and_concurrency_checked_before_expensive_work(client, monkeypatch):
    api.LOCK.acquire()
    try:
        assert client.post("/api/harness/priority-v9/forecast", json={"port_id": "port1318"}).status_code == 429
    finally:
        api.LOCK.release()

    def deny(*args):
        raise HTTPException(403, "denied")

    monkeypatch.setattr(api, "identity_for", deny)
    assert client.get("/api/harness/priority-v9/catalog").status_code == 403
    assert client.post("/api/harness/priority-v9/annual", json={"station_id": "8771450"}).status_code == 403
