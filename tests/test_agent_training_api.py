import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.access_control import IdentityContext
from app.agent_training import api
from app.agent_training.live import ACCEPTANCE_GOAL


@pytest.fixture
def client(tmp_path, monkeypatch):
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    summary = {"rl_parameters_changed": True, "weights": {"initial": "base", "sft": "sft", "rl": "trained"}}
    (experiment / "summary.json").write_text(json.dumps(summary))
    monkeypatch.setattr(api, "EXPERIMENT", experiment)
    monkeypatch.setattr(api, "JOBS", tmp_path / "tasks")
    monkeypatch.setattr(api, "ACTIVE", set())
    monkeypatch.setattr(
        api, "local_request", lambda *a, **k: {"weights": {"B_base": "base", "C_sft": "sft", "D_rl": "trained"}}
    )

    class IdleThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(api.threading, "Thread", IdleThread)
    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.identity = IdentityContext(
            request.headers.get("x-test-actor", "owner"), request.headers.get("x-test-role", "operator"), True, "test"
        )
        return await call_next(request)

    app.include_router(api.router)
    return TestClient(app)


def test_viewer_cannot_create_executing_task(client):
    response = client.post(
        "/api/harness/agent-rl/tasks",
        json={"goal": ACCEPTANCE_GOAL, "request_id": "request001"},
        headers={"x-test-role": "viewer"},
    )
    assert response.status_code == 403


def test_figures_are_allowlisted_and_cannot_follow_external_symlinks(client, tmp_path):
    figures = api.EXPERIMENT / "figures"
    figures.mkdir()
    image = figures / "four-group-comparison.png"
    image.write_bytes(b"published-figure")
    assert client.get("/api/harness/agent-rl/figures/four-group-comparison.png").content == b"published-figure"
    assert client.get("/api/harness/agent-rl/figures/unregistered.png").status_code == 404
    outside = tmp_path / "private.png"
    outside.write_bytes(b"private")
    image.unlink()
    image.symlink_to(outside)
    assert client.get("/api/harness/agent-rl/figures/four-group-comparison.png").status_code == 404


def test_model_health_hides_internal_exception_details(client, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("internal/private/model-path and sensitive transport details")

    monkeypatch.setattr(api, "local_request", unavailable)
    result = client.get("/api/harness/agent-rl/model-health")
    assert result.status_code == 200 and result.json()["available"] is False
    assert "private" not in result.text and "transport" not in result.text


def test_repeated_request_returns_same_task_and_changed_payload_conflicts(client):
    payload = {"goal": ACCEPTANCE_GOAL, "request_id": "request001"}
    first = client.post("/api/harness/agent-rl/tasks", json=payload)
    assert first.status_code == 202
    again = client.post("/api/harness/agent-rl/tasks", json=payload)
    assert again.json()["id"] == first.json()["id"]
    changed = client.post("/api/harness/agent-rl/tasks", json={**payload, "inject_read_fault": True})
    assert changed.status_code == 409


def test_task_and_files_are_actor_scoped(client):
    job = client.post("/api/harness/agent-rl/tasks", json={"goal": ACCEPTANCE_GOAL, "request_id": "request001"}).json()
    for path in [f"/tasks/{job['id']}", f"/tasks/{job['id']}/files/job.json"]:
        assert client.get("/api/harness/agent-rl" + path, headers={"x-test-actor": "other"}).status_code == 403


def test_inference_checkpoint_mismatch_blocks_creation(client, monkeypatch):
    monkeypatch.setattr(api, "local_request", lambda *a, **k: {"weights": {"D_rl": "different"}})
    response = client.post("/api/harness/agent-rl/tasks", json={"goal": ACCEPTANCE_GOAL, "request_id": "request001"})
    assert response.status_code == 409


def test_progress_handles_concurrent_partial_log_and_legacy_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "EXPERIMENT", tmp_path)
    (tmp_path / "evaluations").mkdir()
    baseline = {
        "n": 2,
        "success_rate": 0.5,
        "cases": [{"success": True, "reward": 1}, {"success": False, "reward": -1}],
    }
    (tmp_path / "evaluations/validation-C_sft.json").write_text(json.dumps(baseline))
    (tmp_path / "validation-curve.jsonl").write_text('{"phase":"D_rl","step":128,"successes":1}\n{"phase":')
    (tmp_path / "selection-refinement.jsonl").write_text(
        '{"group":"D_rl","step":448,"eligible":false,"retention":0.875,"successes":null}\n'
    )
    progress = api.development_progress()
    assert progress["baseline"]["successes"] == 1
    assert progress["baseline"]["mean_reward"] == 0
    assert len(progress["checkpoints"]) == 2
    assert progress["checkpoints"][1]["successes"] is None
    assert progress["checkpoints"][1]["excluded_by_retention"]
    assert not progress["test_opened"]
