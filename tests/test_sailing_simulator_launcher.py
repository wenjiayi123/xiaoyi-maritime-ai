from pathlib import Path

from fastapi.testclient import TestClient

from app import sailing_simulator_launcher
from app.main import app


client = TestClient(app)


def _configure_launchable_project(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "航行模拟器"
    project_root.mkdir()
    project_config = project_root / "project.godot"
    project_config.write_text('[application]\nrun/main_scene="res://main.tscn"\n', encoding="utf-8")
    godot_binary = tmp_path / "Godot"
    godot_binary.write_text("#!/bin/sh\n", encoding="utf-8")
    godot_binary.chmod(0o755)
    monkeypatch.setattr(sailing_simulator_launcher, "_SAILING_ROOT", project_root)
    monkeypatch.setattr(sailing_simulator_launcher, "_PROJECT_CONFIG", project_config)
    monkeypatch.setattr(sailing_simulator_launcher, "_GODOT_BINARY", godot_binary)
    monkeypatch.setattr(sailing_simulator_launcher, "_LOG_PATH", tmp_path / "sailing.log")
    monkeypatch.setattr(sailing_simulator_launcher, "_sailing_process", None)
    monkeypatch.setattr(sailing_simulator_launcher, "_launched_at", None)
    monkeypatch.setattr(sailing_simulator_launcher, "_external_process_pid", lambda: None)
    return project_root, godot_binary


def test_status_distinguishes_missing_project_from_running_state(monkeypatch, tmp_path: Path) -> None:
    missing_root = tmp_path / "missing"
    monkeypatch.setattr(sailing_simulator_launcher, "_SAILING_ROOT", missing_root)
    monkeypatch.setattr(sailing_simulator_launcher, "_PROJECT_CONFIG", missing_root / "project.godot")
    monkeypatch.setattr(sailing_simulator_launcher, "_sailing_process", None)
    monkeypatch.setattr(sailing_simulator_launcher, "_external_process_pid", lambda: None)

    response = client.get("/api/sailing-simulator/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "unavailable"
    assert payload["running"] is False
    assert payload["launchable"] is False


def test_launcher_rejects_unregistered_desktop_target() -> None:
    response = client.post(
        "/api/sailing-simulator/launch",
        json={"target": "port-dt-multi"},
    )

    assert response.status_code == 422


def test_launcher_starts_registered_godot_project(monkeypatch, tmp_path: Path) -> None:
    project_root, godot_binary = _configure_launchable_project(monkeypatch, tmp_path)
    captured = {}

    class FakeProcess:
        pid = 4242

        def poll(self):
            return None

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs["cwd"]
        return FakeProcess()

    monkeypatch.setattr(sailing_simulator_launcher.subprocess, "Popen", fake_popen)

    response = client.post(
        "/api/sailing-simulator/launch",
        json={"target": "sailing-simulator"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["state"] == "starting"
    assert payload["managed_by_xiaoyi"] is True
    assert payload["pid"] == 4242
    assert captured["args"] == [str(godot_binary), "--path", str(project_root)]
    assert captured["cwd"] == str(project_root)


def test_launcher_reuses_external_sailing_simulator(monkeypatch, tmp_path: Path) -> None:
    _configure_launchable_project(monkeypatch, tmp_path)
    monkeypatch.setattr(sailing_simulator_launcher, "_external_process_pid", lambda: 7788)
    monkeypatch.setattr(sailing_simulator_launcher, "_activate_godot", lambda: None)

    response = client.post(
        "/api/sailing-simulator/launch",
        json={"target": "sailing-simulator"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["state"] == "online"
    assert payload["already_running"] is True
    assert payload["managed_by_xiaoyi"] is False
    assert payload["pid"] == 7788
