from pathlib import Path

from fastapi.testclient import TestClient

from app import linked_system_launcher
from app.main import app


client = TestClient(app)


def test_energy_readiness_uses_fast_service_health_not_deep_linkage_rollup() -> None:
    health_url = str(linked_system_launcher._TARGETS["energy-cockpit"]["health_url"])

    assert health_url.endswith("/api/health")
    assert not health_url.endswith("/api/linkage/health")


def test_launcher_reuses_online_whitelisted_systems(monkeypatch) -> None:
    monkeypatch.setattr(
        linked_system_launcher,
        "_probe_target",
        lambda target: ("online", f"{target} ready"),
    )

    response = client.post(
        "/api/linked-systems/launch",
        json={"targets": ["port-dt-multi", "energy-cockpit", "malacca-sandbox"]},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["all_ready"] is True
    assert set(payload["systems"]) == {
        "port-dt-multi",
        "energy-cockpit",
        "malacca-sandbox",
    }
    assert all(item["already_running"] for item in payload["systems"].values())
    assert payload["production_write_enabled"] is False


def test_launcher_starts_only_registered_missing_target(monkeypatch) -> None:
    states = {"energy-cockpit": "offline"}

    def probe(target):
        state = states.get(target, "online")
        return state, "ready" if state == "online" else "offline"

    def start(target):
        states[target] = "online"

    monkeypatch.setattr(linked_system_launcher, "_probe_target", probe)
    monkeypatch.setattr(linked_system_launcher, "_start_registered_process", start)

    response = client.post(
        "/api/linked-systems/launch",
        json={"targets": ["energy-cockpit"]},
    )

    assert response.status_code == 202
    assert response.json()["systems"]["energy-cockpit"]["state"] == "online"


def test_launcher_rejects_arbitrary_command_target() -> None:
    response = client.post(
        "/api/linked-systems/launch",
        json={"targets": ["bash -lc arbitrary-command"]},
    )

    assert response.status_code == 422


def test_probe_requires_backend_and_frontend(monkeypatch) -> None:
    monkeypatch.setattr(
        linked_system_launcher,
        "_probe_json_health",
        lambda _url: ("online", "backend ready"),
    )
    monkeypatch.setattr(
        linked_system_launcher,
        "_probe_ui",
        lambda _url: ("offline", "前端页面尚未启动。"),
    )

    state, message = linked_system_launcher._probe_target("energy-cockpit")

    assert state == "offline"
    assert "后端已在线" in message
    assert "前端页面尚未启动" in message


def test_energy_launcher_repairs_missing_backend_when_frontend_is_managed(monkeypatch) -> None:
    runtime = linked_system_launcher.LinkedSystemRuntime(
        target="energy-cockpit",
        name="能碳驾驶舱",
        state="starting",
        running=False,
        managed_by_xiaoyi=True,
        pid=4242,
        url="http://127.0.0.1:5173/",
        message="前端在线，后端尚未启动。",
    )
    started: list[str] = []
    monkeypatch.setattr(linked_system_launcher, "_runtime", lambda _target: runtime)
    monkeypatch.setattr(
        linked_system_launcher,
        "_probe_json_health",
        lambda _url: ("offline", "backend missing"),
    )
    monkeypatch.setattr(
        linked_system_launcher,
        "_start_registered_process",
        lambda target: started.append(target),
    )

    result = linked_system_launcher._launch_target("energy-cockpit")

    assert result.state == "starting"
    assert started == ["energy-cockpit"]


def test_rl_lab_no_longer_launches_external_showcase_systems() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "web/app.js").read_text(encoding="utf-8")

    rl_branch = script.split('if (["open_rl_mission"', 1)[1].split("const weatherKinds", 1)[0]
    assert "/api/rl-mission/train" in rl_branch
    assert "requestLinkedSystemsStartup" not in rl_branch
    assert "port-dt-multi" not in rl_branch
    assert "energy-cockpit" not in rl_branch
    assert "confirm-linked-systems-startup" in script
    assert "/api/linked-systems/launch" in script
    assert "runtime.all_ready" in script
