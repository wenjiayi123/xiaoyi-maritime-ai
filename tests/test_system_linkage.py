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


def test_command_failure_does_not_expose_internal_exception(monkeypatch) -> None:
    def fail_execute(target, request, trace_id):
        raise RuntimeError("secret-host.internal token=do-not-leak")

    monkeypatch.setattr(system_linkage, "_execute_target", fail_execute)
    monkeypatch.setattr(
        system_linkage,
        "_runtime",
        lambda target: {"target": target, "name": target, "running": False},
    )

    response = client.post(
        "/api/system-linkage/command",
        json={"target": "port-dt-multi", "command": "读取本机联动状态"},
    )

    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["error"] == "linked_target_execution_failed"
    assert item["retryable"] is True
    assert "secret-host" not in response.text

    overview = client.get("/api/system-linkage/overview").json()
    persisted = overview["systems"]["port-dt-multi"]["last_result"]
    assert persisted["status"] == "failed"
    assert persisted["trace_id"] == item["trace_id"]
    assert overview["last_command"]["failed_targets"] == ["port-dt-multi"]
    assert overview["last_command"]["all_succeeded"] is False


def test_linkage_overview_restores_sanitized_receipt_from_runtime_store(
    monkeypatch,
) -> None:
    receipt = {
        "correlation_id": "link-persisted",
        "command": "恢复联动回执",
        "succeeded": 1,
        "total": 1,
        "all_succeeded": True,
        "failed_targets": [],
        "completed_at": "2026-08-14T10:00:00+00:00",
        "production_write_enabled": False,
    }
    result = {
        "trace_id": "link-persisted-1",
        "target": "port-dt-multi",
        "status": "completed",
        "production_write_enabled": False,
    }
    system_linkage._last_results.clear()
    system_linkage._last_command_summary.clear()
    monkeypatch.setattr(
        system_linkage.runtime_store,
        "get_context",
        lambda _key: {
            "context": {
                "last_results": {
                    "port-dt-multi": result,
                    "unknown-system": {"status": "completed"},
                },
                "last_command": receipt,
            }
        },
    )

    try:
        overview = client.get("/api/system-linkage/overview").json()

        assert overview["last_command"] == receipt
        assert overview["systems"]["port-dt-multi"]["last_result"] == result
        assert "unknown-system" not in overview["systems"]
    finally:
        system_linkage._last_results.clear()
        system_linkage._last_command_summary.clear()


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
