import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rl_lab.datasets import get_dataset, load_records
from app.rl_lab.environment import EnergySchedulingEnvironment, derive_parameters
from app.rl_lab import service as service_module


ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def test_public_dataset_has_license_provenance_and_matching_hash() -> None:
    definition = get_dataset("uci_appliances_energy")
    records = load_records(definition)
    provenance = json.loads(
        (ROOT / "data/public/uci_appliances_energy.provenance.json").read_text(encoding="utf-8")
    )
    digest = hashlib.sha256(definition.path.read_bytes()).hexdigest()

    assert len(records) == provenance["row_count"] == 19735
    assert digest == provenance["derived_csv_sha256"]
    assert provenance["license"].endswith("(CC BY 4.0)")
    assert provenance["doi"] == "10.24432/C5VC8G"
    assert "not port" in provenance["scope_notice"].lower()


def test_training_environment_refuses_rendering_outside_test_split() -> None:
    records = load_records(get_dataset("uci_appliances_energy"))[:1000]
    parameters = derive_parameters(records)
    with pytest.raises(ValueError, match="only on the untouched test split"):
        EnergySchedulingEnvironment(
            records,
            parameters,
            horizon_steps=24,
            seed=7,
            split_name="train",
            render_mode="trace",
        )


def test_algorithm_and_dataset_api_expose_real_contract() -> None:
    algorithms = client.get("/api/rl-lab/algorithms").json()
    datasets = client.get("/api/rl-lab/datasets").json()

    assert algorithms["count"] == 5
    assert sum(item["family"] == "reinforcement_learning" for item in algorithms["items"]) == 4
    assert sum(item["family"] == "control_theory" for item in algorithms["items"]) == 1
    assert datasets["items"][0]["source_type"] == "public_benchmark"
    assert datasets["items"][0]["port_data"] is False
    assert datasets["contract"]["required"] == ["timestamp", "load_kw"]


def test_custom_algorithm_selection_still_uses_real_progress_and_holdout() -> None:
    response = client.post(
        "/api/rl-lab/runs",
        json={
            "algorithms": ["q_learning", "pid"],
            "episodes": 10,
            "horizon_steps": 24,
            "seed": 991,
        },
    )
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        run = client.get(f"/api/rl-lab/runs/{run_id}").json()
        if run["status"] not in {"queued", "training", "cancelling"}:
            break
        time.sleep(0.02)
    assert run["status"] == "trained"
    assert run["total_training_episodes"] == 10
    assert run["completed_training_episodes"] == 10
    assert set(run["training"]["algorithms"]) == {"q_learning", "pid"}
    assert run["training"]["rendering_performed"] is False
    assert run["validation"]["results"]

    evaluation = client.post(f"/api/rl-lab/runs/{run_id}/evaluate", json={}).json()
    assert evaluation["rendering_performed"] is True
    assert {item["algorithm_id"] for item in evaluation["results"]} == {"q_learning", "pid"}
    assert all(frame["split"] == "test" for item in evaluation["results"] for frame in item["frames"])


def test_background_training_failure_freezes_error_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(service_module, "RUNS_DIR", tmp_path / "rl_runs")
    monkeypatch.setattr(service_module, "BASE_DIR", tmp_path)

    def fail_training(*args, **kwargs):
        raise RuntimeError("forced training failure")

    monkeypatch.setattr(service_module, "train_tabular_policy", fail_training)
    service = service_module.RLLabService()
    started = service.start_run(
        {
            "algorithms": ["q_learning"],
            "episodes": 1,
            "horizon_steps": 24,
            "seed": 77,
        }
    )

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = service.get_run(started["run_id"])
        if run["status"] not in {"queued", "training"}:
            break
        time.sleep(0.01)

    assert run["status"] == "failed"
    assert run["phase"] == "failed"
    assert run["error"] == "forced training failure"
    assert "RuntimeError: forced training failure" in run["error_trace"]
