import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rl_lab.datasets import get_dataset, load_records
from app.rl_lab.environment import EnergySchedulingEnvironment, derive_parameters
from app.rl_lab.port_environment import (
    PortOperationsEnvironment,
    derive_port_parameters,
)
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


@pytest.mark.parametrize(
    ("dataset_id", "provenance_name", "expected_rows", "expected_environment"),
    [
        (
            "uci_household_power_5min",
            "uci_household_power_5min.provenance.json",
            409887,
            "energy_storage",
        ),
        (
            "noaa_la_lb_ais_2024_12_25_1min",
            "noaa_la_lb_ais_2024_12_25_1min.provenance.json",
            710,
            "port_operations",
        ),
    ],
)
def test_added_public_datasets_match_provenance(
    dataset_id: str,
    provenance_name: str,
    expected_rows: int,
    expected_environment: str,
) -> None:
    definition = get_dataset(dataset_id)
    records = load_records(definition)
    provenance = json.loads(
        (ROOT / "data/public" / provenance_name).read_text(encoding="utf-8")
    )
    recorded_rows = provenance.get("row_count", provenance.get("derived_rows"))

    assert len(records) == recorded_rows == expected_rows
    assert hashlib.sha256(definition.path.read_bytes()).hexdigest() == provenance["derived_csv_sha256"]
    assert definition.environment_type == expected_environment
    assert records[0].timestamp < records[-1].timestamp


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


def test_energy_action_mask_blocks_projected_soc_violation() -> None:
    records = load_records(get_dataset("uci_appliances_energy"))[:1000]
    parameters = derive_parameters(records)
    environment = EnergySchedulingEnvironment(
        records,
        parameters,
        horizon_steps=24,
        seed=7,
        split_name="train",
        render_mode=None,
    )
    environment.reset(start_index=0)
    environment.soc = parameters.minimum_soc
    assert environment.valid_action_mask()[:2] == (False, False)
    environment.soc = parameters.maximum_soc
    assert environment.valid_action_mask()[-2:] == (False, False)


def test_energy_environment_accounts_for_degradation_and_terminal_recovery() -> None:
    records = load_records(get_dataset("uci_appliances_energy"))[:1000]
    parameters = derive_parameters(records)
    environment = EnergySchedulingEnvironment(
        records,
        parameters,
        horizon_steps=24,
        seed=17,
        split_name="test",
        render_mode="trace",
    )
    environment.reset(start_index=0)
    while environment.steps < environment.horizon_steps:
        mask = environment.valid_action_mask()
        action = 0 if mask[0] else 4 if mask[4] else next(
            index for index, valid in enumerate(mask) if valid
        )
        _, _, done, frame = environment.step(action)
        if done:
            break
    metrics = environment.episode_metrics(0.0)

    assert parameters.public_dict()["environment_version"] == "xiaoyi-energy-env.v2"
    assert metrics["total_degradation_cost"] > 0
    assert metrics["total_cost"] == pytest.approx(
        metrics["total_grid_energy_cost"] + metrics["total_degradation_cost"],
        abs=1e-7,
    )
    assert metrics["terminal_soc_recovered"] is True
    assert metrics["terminal_soc"] >= parameters.initial_soc - parameters.terminal_soc_tolerance
    assert frame["terminal_recovery_violation"] is False


def test_port_environment_refuses_training_render_and_masks_unsafe_actions() -> None:
    records = load_records(get_dataset("noaa_la_lb_ais_2024_12_25_1min"))
    parameters = derive_port_parameters(records[:497])
    with pytest.raises(ValueError, match="only on the untouched test split"):
        PortOperationsEnvironment(
            records[:497],
            parameters,
            horizon_steps=48,
            seed=7,
            split_name="train",
            render_mode="trace",
        )


def test_algorithm_and_dataset_api_expose_real_contract() -> None:
    algorithms = client.get("/api/rl-lab/algorithms").json()
    datasets = client.get("/api/rl-lab/datasets").json()

    assert algorithms["count"] == 6
    assert sum(item["family"] == "reinforcement_learning" for item in algorithms["items"]) == 4
    assert sum(item["family"] == "control_theory" for item in algorithms["items"]) == 1
    assert sum(item["family"] == "operations_rule" for item in algorithms["items"]) == 1
    assert datasets["items"][0]["source_type"] == "public_benchmark"
    assert datasets["items"][0]["port_data"] is False
    assert datasets["contract"]["required"] == ["timestamp", "load_kw"]


def test_port_contract_and_grounded_training_advisor_are_exposed() -> None:
    contracts = client.get("/api/rl-lab/contracts")
    advisor = client.post(
        "/api/rl-lab/advisor",
        json={"message": "五种算法的区别是什么，为什么保留PID？"},
    )

    assert contracts.status_code == 200
    port_contract = next(
        item for item in contracts.json()["items"] if item["id"] == "port_operations"
    )
    assert len(port_contract["observation"]) == 11
    assert len(port_contract["actions"]) == 5
    assert "DCSA Port Call" in {
        item.get("standard")
        for item in port_contract["international_port_factors"]
    }
    assert advisor.status_code == 200
    assert advisor.json()["grounded"] is True
    assert advisor.json()["generation_provider"] == "local_evidence_advisor"
    assert "Double Q-learning" in advisor.json()["answer"]


def test_fixed_rl_evidence_exposes_v2_admission_failures_and_authority_boundary() -> None:
    payload = client.get("/api/rl-lab/evidence").json()
    report = payload["report"]

    assert payload["report_path"] == "reports/rl_dataset_benchmark_v2.json"
    assert report["schema_version"] == "xiaoyi-rl-dataset-benchmark.v2"
    assert report["evidence_integrity_passed"] is True
    assert report["policy_admission_passed"] is False
    assert report["production_authority"] is False
    assert len(report["configuration"]["algorithms"]) == 6
    for experiment in report["experiments"].values():
        assert len(experiment["runs"]) == 3
        assert len(experiment["admission"]["failed_candidates"]) == 4
        assert experiment["admission"]["production_authority"] is False
        for metrics in experiment["aggregate"]["algorithm_metrics"].values():
            assert metrics["score"]["ci95_method"] == "two-sided Student t, df=2"


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


def test_port_training_uses_ais_contract_and_test_only_trace() -> None:
    response = client.post(
        "/api/rl-lab/runs",
        json={
            "dataset_id": "noaa_la_lb_ais_2024_12_25_1min",
            "algorithms": ["q_learning", "pid"],
            "episodes": 10,
            "horizon_steps": 48,
            "seed": 260729,
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
    assert run["config"]["environment_type"] == "port_operations"
    assert run["dataset"]["row_count"] == 710
    assert run["reproducibility"]["profile_sha256"]
    assert run["training"]["rendering_performed"] is False

    evaluation = client.post(f"/api/rl-lab/runs/{run_id}/evaluate", json={}).json()
    assert evaluation["environment_type"] == "port_operations"
    assert evaluation["render_mode"] == "trace"
    assert all(
        frame["evidence_level"] == "measured_ais_plus_calibrated_operations_proxy"
        for item in evaluation["results"]
        for frame in item["frames"]
    )


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
