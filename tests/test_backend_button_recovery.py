import json
import threading
import time

from fastapi.testclient import TestClient

from app import operations
from app.main import app
from app.rl_lab import api as rl_api
from app.rl_lab import service as rl_service
from app.runtime_store import RuntimeStore


def test_failed_task_step_can_be_retried_without_skipping_work(tmp_path, monkeypatch):
    monkeypatch.setattr(operations, "runtime_store", RuntimeStore(tmp_path / "runtime.sqlite3"))
    store = operations._TaskStore()
    monkeypatch.setattr(operations, "_tasks", store)
    client = TestClient(app)
    task = client.post("/api/tasks", json={"template_id": "analyze-energy"}).json()
    assert all(step["description"] == f"步骤内容：{step['title']}" for step in task["steps"])
    original_execute = operations._execute_task_step

    def fail_read(*args):
        raise RuntimeError("source read unavailable")

    monkeypatch.setattr(operations, "_execute_task_step", fail_read)
    failed = client.post(f"/api/tasks/{task['id']}/next")
    assert failed.status_code == 500

    unchanged = client.get(f"/api/tasks/{task['id']}").json()
    assert unchanged == task
    monkeypatch.setattr(operations, "_execute_task_step", original_execute)
    retried = client.post(f"/api/tasks/{task['id']}/next").json()["task"]
    assert retried["status"] == "running"
    assert retried["progress_percent"] == 20
    assert [step["status"] for step in retried["steps"]] == [
        "completed", "running", "pending", "pending", "pending",
    ]
    for _ in range(4):
        retried = client.post(f"/api/tasks/{task['id']}/next").json()["task"]
    assert retried["status"] == "completed"
    assert all(step["result"] for step in retried["steps"])


def test_zero_training_parameters_reach_real_model_and_saved_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(rl_service, "RUNS_DIR", tmp_path / "rl_runs")
    monkeypatch.setattr(rl_service, "BASE_DIR", tmp_path)
    service = rl_service.RLLabService()
    monkeypatch.setattr(rl_api, "rl_lab_service", service)
    client = TestClient(app)
    response = client.post(
        "/api/rl-lab/runs",
        json={
            "algorithms": ["q_learning", "pid"],
            "episodes": 10,
            "horizon_steps": 12,
            "seed": 0,
            "discount_factor": 0,
            "epsilon_end": 0,
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
    assert run["completed_training_episodes"] == 10
    assert run["config"]["seed"] == 0
    assert run["config"]["discount_factor"] == 0
    assert run["config"]["epsilon_end"] == 0
    assert run["reproducibility"]["seed"] == 0
    saved = json.loads((tmp_path / run["artifact_root"] / "run.json").read_text())
    assert saved["config"] == run["config"]
    model = json.loads((tmp_path / run["artifact_root"] / "models/q_learning.json").read_text())
    assert model["seed"] == 0
    assert model["hyperparameters"]["discount_factor"] == 0
    assert model["hyperparameters"]["epsilon_end"] == 0
    evaluation = client.post(f"/api/rl-lab/runs/{run_id}/evaluate", json={})
    assert evaluation.status_code == 200
    assert evaluation.json()["data_split"] == "test"
    assert evaluation.json()["production_execution"] is False


def test_training_cancel_during_validation_remains_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(rl_service, "RUNS_DIR", tmp_path / "rl_runs")
    monkeypatch.setattr(rl_service, "BASE_DIR", tmp_path)
    service = rl_service.RLLabService()
    monkeypatch.setattr(rl_api, "rl_lab_service", service)
    validation_started = threading.Event()
    resume_validation = threading.Event()
    evaluate_policy = rl_service.evaluate_policy

    def pause_validation(*args, **kwargs):
        validation_started.set()
        assert resume_validation.wait(10)
        return evaluate_policy(*args, **kwargs)

    monkeypatch.setattr(rl_service, "evaluate_policy", pause_validation)
    client = TestClient(app)
    response = client.post(
        "/api/rl-lab/runs",
        json={"algorithms": ["q_learning"], "episodes": 10, "horizon_steps": 12},
    )
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    try:
        assert validation_started.wait(10)
        cancelled = client.post(f"/api/rl-lab/runs/{run_id}/cancel")
        assert cancelled.status_code == 202
        assert cancelled.json()["status"] == "cancelling"
    finally:
        resume_validation.set()
        service._threads[run_id].join(timeout=10)
    run = client.get(f"/api/rl-lab/runs/{run_id}").json()
    assert run["status"] == "cancelled"
    assert run["phase"] == "cancelled"
    assert run["validation"]["best_algorithm_id"] is None
    assert client.post(f"/api/rl-lab/runs/{run_id}/evaluate", json={}).status_code == 409
