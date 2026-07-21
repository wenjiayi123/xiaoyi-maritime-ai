from fastapi.testclient import TestClient

from app import simulator_launcher
from app.main import app


client = TestClient(app)


def test_launch_reuses_existing_simulator(monkeypatch) -> None:
    monkeypatch.setattr(
        simulator_launcher,
        "_probe_simulator",
        lambda: ("online", "模拟器首页与 8000 端口均已就绪。"),
    )
    monkeypatch.setattr(simulator_launcher, "_simulator_process", None)

    response = client.post("/api/simulator/launch", json={"target": "port-dt-multi"})

    assert response.status_code == 202
    payload = response.json()
    assert payload["state"] == "online"
    assert payload["running"] is True
    assert payload["already_running"] is True


def test_launcher_rejects_unregistered_target() -> None:
    response = client.post("/api/simulator/launch", json={"target": "shell-command"})

    assert response.status_code == 422


def test_launcher_skips_conflicted_preferred_port(monkeypatch) -> None:
    monkeypatch.setattr(simulator_launcher, "_SIMULATOR_PORTS", (8000, 8001, 8002))
    monkeypatch.setattr(simulator_launcher, "_active_port", None)
    monkeypatch.setattr(simulator_launcher, "_conflicted_ports", [])
    monkeypatch.setattr(simulator_launcher, "_simulator_process", None)
    monkeypatch.setattr(
        simulator_launcher,
        "_probe_port",
        lambda port: ("port_conflict", "occupied") if port == 8000 else ("offline", "available"),
    )

    runtime = simulator_launcher.simulator_status()

    assert runtime.state == "offline"
    assert runtime.port == 8001
    assert runtime.fallback_used is True
    assert runtime.conflicted_ports == [8000]


def test_launcher_passes_selected_fallback_port_to_simulator(monkeypatch, tmp_path) -> None:
    captured = {}

    class FakeProcess:
        pid = 4242

        def poll(self):
            return None

    def fake_popen(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return FakeProcess()

    monkeypatch.setattr(simulator_launcher, "_SIMULATOR_PORTS", (8000, 8001, 8002))
    monkeypatch.setattr(simulator_launcher, "_active_port", None)
    monkeypatch.setattr(simulator_launcher, "_conflicted_ports", [])
    monkeypatch.setattr(simulator_launcher, "_simulator_process", None)
    simulator_root = tmp_path / "port-dt-multi"
    (simulator_root / "app").mkdir(parents=True)
    (simulator_root / "app/server.py").write_text("", encoding="utf-8")
    simulator_python = tmp_path / "python"
    simulator_python.write_text("#!/bin/sh\n", encoding="utf-8")
    simulator_python.chmod(0o755)
    monkeypatch.setattr(simulator_launcher, "_SIMULATOR_ROOT", simulator_root)
    monkeypatch.setattr(simulator_launcher, "_SIMULATOR_PYTHON", simulator_python)
    monkeypatch.setattr(simulator_launcher, "_LOG_PATH", tmp_path / "simulator.log")
    monkeypatch.setattr(
        simulator_launcher,
        "_probe_port",
        lambda port: ("port_conflict", "occupied") if port == 8000 else ("offline", "available"),
    )
    monkeypatch.setattr(simulator_launcher.subprocess, "Popen", fake_popen)

    response = client.post("/api/simulator/launch", json={"target": "port-dt-multi"})

    assert response.status_code == 202
    assert response.json()["state"] == "starting"
    assert response.json()["port"] == 8001
    assert captured["env"]["PORT_DT_SERVER_PORT"] == "8001"
