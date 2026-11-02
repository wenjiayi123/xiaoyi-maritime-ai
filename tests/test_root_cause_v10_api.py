import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.harness import root_cause_v10 as api


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as value:
        yield value


def test_catalog_preserves_37_scores_and_oracle_boundary(client):
    response = client.get("/api/harness/root-cause-v10/catalog")
    assert response.status_code == 200
    body = response.json()
    assert body["current"] and not body["production_authority"]
    assert len(body["scorecard"]["components"]) == 37
    assert all(c["score"] == 5 * sum(c["dimensions"].values()) for c in body["scorecard"]["components"])
    assert body["summary"]["oracle"]["normal"]["exactly_optimal_baseline_windows"] == 15
    assert not body["summary"]["rl"]["candidate"]["research_admission"]


def test_real_annual_reconstruction_keeps_gates_and_no_future_truth(client):
    response = client.post("/api/harness/root-cause-v10/annual", json={"station_id": "9419750", "day": "2025-06-01"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["rows"]) == 24 and not data["language_model_used"]
    assert not data["production_authority"] and data["units"] == "m" and data["datum"] == "MLLW"
    assert all("actual" not in r and r["lower90"] <= r["prediction"] <= r["upper90"] for r in data["rows"])
    assert all(r["upper90"] - r["lower90"] <= r["v9_upper90"] - r["v9_lower90"] + 1e-10 for r in data["rows"])
    assert (data["status"] == "research_only") == (
        data["annual"]["passed"] and all(q["passed"] for q in data["quarters"].values())
    )
    missing = client.post("/api/harness/root-cause-v10/annual", json={"station_id": "8775870"}).json()
    assert missing["status"] == "hold" and "rows" not in missing


@pytest.mark.parametrize(
    "args",
    [
        {"station_id": "9419750", "day": "2026-01-01"},
        {"station_id": "../../private"},
        {"station_id": "9419750", "production_authority": True},
    ],
)
def test_invalid_dates_and_authority_payloads_rejected(client, args):
    assert client.post("/api/harness/root-cause-v10/annual", json=args).status_code == 422


def test_changed_evidence_and_loaded_code_block_recomputation(client, monkeypatch, tmp_path):
    r = json.loads(api.REGISTRY.read_text())
    r["sources"]["app/harness/annual_v9.py"] = "changed"
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(r))
    monkeypatch.setattr(api, "REGISTRY", path)
    assert not client.get("/api/harness/root-cause-v10/catalog").json()["current"]
    assert client.post("/api/harness/root-cause-v10/annual", json={"station_id": "9419750"}).status_code == 409
    r["reports"]["summary"]["sha256"] = "changed"
    path.write_text(json.dumps(r))
    assert client.get("/api/harness/root-cause-v10/catalog").status_code == 503


def test_identity_checked_before_reading_evidence(client, monkeypatch):
    def denied(*args):
        raise HTTPException(403, "denied")

    monkeypatch.setattr(api, "identity_for", denied)
    assert client.get("/api/harness/root-cause-v10/catalog").status_code == 403
    assert client.post("/api/harness/root-cause-v10/annual", json={"station_id": "9419750"}).status_code == 403
