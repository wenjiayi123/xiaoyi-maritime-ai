from pathlib import Path

from fastapi.testclient import TestClient

from app import system_linkage
from app.main import app


client = TestClient(app)


def test_overview_aggregates_four_registered_systems(monkeypatch) -> None:
    monkeypatch.setattr(
        system_linkage,
        "_runtime",
        lambda target: {
            "target": target,
            "name": target,
            "state": "online",
            "running": True,
            "message": "ready",
        },
    )

    response = client.get("/api/system-linkage/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 4
    assert payload["online_count"] == 4
    assert payload["all_ready"] is True
    assert set(payload["systems"]) == {
        "port-dt-multi",
        "energy-cockpit",
        "malacca-sandbox",
        "sailing-simulator",
    }
    assert payload["execution_boundary"]


def test_command_returns_trace_and_per_system_receipts(monkeypatch) -> None:
    def execute(target, request, trace_id):
        return {
            "trace_id": trace_id,
            "target": target,
            "name": target,
            "status": "completed",
            "action": request.command,
            "summary": {"verified": True},
            "payload_sha256": "a" * 64,
            "duration_ms": 12,
            "completed_at": "2026-07-27T00:00:00+00:00",
            "boundary": "offline",
        }

    monkeypatch.setattr(system_linkage, "_execute_target", execute)

    response = client.post(
        "/api/system-linkage/command",
        json={
            "target": "all",
            "command": "读取四系统状态并执行本机联动验证",
            "session_id": "test-linkage",
            "auto_start": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["all_succeeded"] is True
    assert payload["succeeded"] == payload["total"] == 4
    assert payload["correlation_id"].startswith("link-")
    assert len({item["trace_id"] for item in payload["results"]}) == 4
    assert payload["production_write_enabled"] is False


def test_sailing_request_bridge_is_atomic_and_context_aware(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request_file = tmp_path / "malacca_validation_request.json"
    result_file = tmp_path / "malacca_validation_result.json"
    result_file.write_text('{"requestId":"old"}', encoding="utf-8")
    monkeypatch.setattr(system_linkage, "_BRIDGE_DIR", tmp_path)
    monkeypatch.setattr(system_linkage, "_BRIDGE_REQUEST", request_file)
    monkeypatch.setattr(system_linkage, "_BRIDGE_RESULT", result_file)

    request = system_linkage.LinkageCommandRequest(
        target="sailing-simulator",
        command="验证 MMSI 413123456 在碰撞风险场景下的安全航速",
        session_id="bridge-test",
        context={"mmsi": "413123456", "scenario_id": "collision-risk"},
        parameters={"targetKnots": 9.5, "maxSafeKnots": 13},
    )
    payload = system_linkage._sailing_request("trace-bridge", request)
    system_linkage._write_sailing_request(payload)

    assert payload["requestId"] == "trace-bridge"
    assert payload["vesselId"] == "413123456"
    assert payload["speedProfile"]["targetKnots"] == 9.5
    assert request_file.is_file()
    assert not result_file.exists()
    assert "trace-bridge" in request_file.read_text(encoding="utf-8")
