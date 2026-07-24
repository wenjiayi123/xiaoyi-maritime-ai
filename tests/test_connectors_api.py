from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import connectors as connectors_module
from app.connectors import ConnectorRegistry, HumanConfirmation, WritePreflightRequest
from app.main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_connector_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """API tests must never inherit a developer machine's live connector config."""

    monkeypatch.setattr(connectors_module, "registry", ConnectorRegistry(environment={}))


def test_connector_catalog_is_fail_closed_by_default() -> None:
    response = client.get("/api/connectors")
    assert response.status_code == 200

    payload = response.json()
    assert payload["total"] == 8
    assert payload["online"] == 0
    assert payload["demo"] == 0
    assert payload["offline"] == 8
    assert {item["id"] for item in payload["items"]} == {
        "tos",
        "pcs",
        "ems",
        "eam",
        "vts",
        "ais",
        "weather",
        "single-window",
    }
    assert all(item["mode"] == "offline" for item in payload["items"])
    assert all(item["health_status"] == "offline" for item in payload["items"])
    assert all(item["base_url"] is None for item in payload["items"])
    assert all(item["credential_configured"] is False for item in payload["items"])
    assert all(item["write_enabled"] is False for item in payload["items"])


def test_connector_exposes_capabilities_and_field_mapping_without_claiming_live_data() -> None:
    response = client.get("/api/connectors/tos")
    assert response.status_code == 200

    payload = response.json()
    assert payload["code"] == "TOS"
    assert "vessel_calls" in payload["capabilities"]["read"]
    assert "dispatch_order" in payload["capabilities"]["write"]
    assert payload["requires_human_confirmation"] is True
    assert payload["configured"] is False
    assert payload["configuration_errors"] == []

    mappings = client.get("/api/connectors/tos/field-mappings")
    assert mappings.status_code == 200
    assert any(item["canonical_field"] == "vessel_call_id" for item in mappings.json())

    ais = client.get("/api/connectors/ais").json()
    assert ais["capabilities"]["read_only"] is True
    assert ais["capabilities"]["write"] == []


def test_offline_health_check_never_pretends_connector_is_online() -> None:
    response = client.post("/api/connectors/ems/health-check")
    assert response.status_code == 200

    payload = response.json()
    assert payload["mode"] == "offline"
    assert payload["status"] == "offline"
    assert payload["reachable"] is False
    assert payload["live_data_verified"] is False


def test_write_preflight_requires_human_confirmation_and_live_connection() -> None:
    missing_confirmation = client.post(
        "/api/connectors/tos/write-preflight",
        json={"operation": "dispatch_order", "payload": {"job_id": "J-001"}},
    )
    assert missing_confirmation.status_code == 403
    assert "人工明确确认" in missing_confirmation.json()["detail"]

    confirmed_but_offline = client.post(
        "/api/connectors/tos/write-preflight",
        json={
            "operation": "dispatch_order",
            "payload": {"job_id": "J-001"},
            "confirmation": {
                "confirmed": True,
                "operator_id": "dispatcher-01",
                "reason": "已复核作业计划",
                "reference": "approval-2026-001",
            },
        },
    )
    assert confirmed_but_offline.status_code == 409
    assert "live 模式" in confirmed_but_offline.json()["detail"]


def test_live_mode_requires_real_configuration_and_never_exposes_secret() -> None:
    secret = "do-not-return-this-token"
    registry = ConnectorRegistry(
        environment={
            "XIAOYI_CONNECTOR_TOS_MODE": "live",
            "XIAOYI_CONNECTOR_TOS_BASE_URL": "https://tos.example.test/api",
            "XIAOYI_CONNECTOR_TOS_AUTH_TYPE": "bearer",
            "XIAOYI_CONNECTOR_TOS_CREDENTIAL": secret,
            "XIAOYI_CONNECTOR_TOS_ALLOW_WRITE": "true",
        }
    )

    info = registry.get_info("tos")
    assert info.mode == "live"
    assert info.health_status == "unchecked"
    assert info.credential_configured is True
    assert info.write_enabled is True
    assert secret not in info.model_dump_json()


class _HealthyResponse:
    status = 204

    def __enter__(self) -> "_HealthyResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_online_status_requires_successful_health_response_and_preflight_does_not_dispatch() -> None:
    registry = ConnectorRegistry(
        environment={
            "XIAOYI_CONNECTOR_TOS_MODE": "live",
            "XIAOYI_CONNECTOR_TOS_BASE_URL": "https://tos.example.test/api",
            "XIAOYI_CONNECTOR_TOS_AUTH_TYPE": "bearer",
            "XIAOYI_CONNECTOR_TOS_CREDENTIAL": "test-token",
            "XIAOYI_CONNECTOR_TOS_ALLOW_WRITE": "true",
        }
    )
    with patch("app.connectors.urlopen", return_value=_HealthyResponse()):
        health = registry.check_health("tos")

    assert health.status == "online"
    assert health.live_data_verified is True
    assert registry.get_info("tos").health_status == "online"

    authorization = registry.authorize_write(
        "tos",
        WritePreflightRequest(
            operation="dispatch_order",
            payload={"job_id": "J-001"},
            confirmation=HumanConfirmation(
                confirmed=True,
                operator_id="dispatcher-01",
                reason="已复核作业计划",
                reference="approval-2026-001",
            ),
        ),
    )
    assert authorization.authorized is True
    assert authorization.dispatch_performed is False


def test_unknown_connector_returns_404() -> None:
    response = client.get("/api/connectors/not-real")
    assert response.status_code == 404
