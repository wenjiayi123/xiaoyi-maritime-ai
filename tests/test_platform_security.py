from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app
from app.model_gateway import ModelGateway
from app.models import ChatResponse
from app.observability import TelemetryRegistry
from app.security import PlatformMiddleware, issue_access_token, verify_access_token
from app.settings import Settings
from app.runtime_store import RuntimeStore


client = TestClient(app)


def test_runtime_store_health_does_not_expose_database_exception(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = RuntimeStore(tmp_path / "runtime.db")

    def fail_connect():
        raise sqlite3.OperationalError("secret/filesystem/runtime.db")

    monkeypatch.setattr(store, "_connect", fail_connect)
    result = store.health_check()

    assert result["error"] == "runtime_store_unavailable"
    assert "secret" not in str(result)


def _secure_client(*, limit: int = 20) -> tuple[TestClient, Settings]:
    configuration = replace(
        Settings.from_env(),
        environment="staging",
        security_mode="jwt",
        jwt_secret="test-signing-secret-with-at-least-32-bytes",
        rate_limit_requests=limit,
        rate_limit_window_seconds=60,
    )
    secured = FastAPI()
    secured.add_middleware(PlatformMiddleware, settings=configuration, telemetry=TelemetryRegistry())

    @secured.get("/api/system/info")
    def info() -> dict[str, bool]:
        return {"ok": True}

    @secured.post("/api/automation/plans")
    def mutate() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(secured), configuration


def _authorization(configuration: Settings, role: str = "viewer") -> dict[str, str]:
    token = issue_access_token(actor_id="platform-test", role=role, settings=configuration)
    return {"Authorization": f"Bearer {token}"}


def test_jwt_authentication_and_role_permissions_are_enforced() -> None:
    secured, configuration = _secure_client()

    unauthorized = secured.get("/api/system/info")
    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"] == "Bearer"
    assert unauthorized.headers["x-content-type-options"] == "nosniff"
    assert unauthorized.headers["x-frame-options"] == "DENY"
    assert unauthorized.headers["x-request-id"].startswith("req-")

    viewer = secured.get("/api/system/info", headers=_authorization(configuration, "viewer"))
    assert viewer.status_code == 200
    assert viewer.json() == {"ok": True}

    forbidden = secured.post("/api/automation/plans", headers=_authorization(configuration, "viewer"))
    assert forbidden.status_code == 403
    assert "automation.execute" in forbidden.json()["detail"]

    allowed = secured.post("/api/automation/plans", headers=_authorization(configuration, "admin"))
    assert allowed.status_code == 200


def test_rate_limit_returns_retry_metadata() -> None:
    secured, configuration = _secure_client(limit=1)
    headers = _authorization(configuration)
    assert secured.get("/api/system/info", headers=headers).status_code == 200
    limited = secured.get("/api/system/info", headers=headers)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


def test_access_token_expiry_and_production_configuration_gate() -> None:
    configuration = replace(
        Settings.from_env(),
        security_mode="jwt",
        jwt_secret="test-signing-secret-with-at-least-32-bytes",
    )
    token = issue_access_token(actor_id="operator-1", role="operator", settings=configuration, expires_minutes=1)
    identity = verify_access_token(token, configuration)
    assert identity.actor_id == "operator-1"
    assert identity.authenticated is True

    future = datetime.now(timezone.utc) + timedelta(minutes=3)
    try:
        verify_access_token(token, configuration, now=future)
    except ValueError as exc:
        assert "过期" in str(exc)
    else:
        raise AssertionError("过期令牌不得通过验证")

    unsafe = replace(Settings.from_env(), environment="production", security_mode="local", jwt_secret="")
    blockers = unsafe.deployment_blockers()
    assert any("XIAOYI_SECURITY_MODE=jwt" in item for item in blockers)
    assert any("至少32字节" in item for item in blockers)


def test_deep_health_metrics_and_secure_response_headers() -> None:
    live = client.get("/health/live")
    assert live.status_code == 200
    assert live.json()["status"] == "alive"
    assert live.headers["content-security-policy"].startswith("default-src 'self'")
    assert live.headers["x-request-id"].startswith("req-")

    ready = client.get("/health/ready")
    assert ready.status_code == 200
    payload = ready.json()
    assert payload["status"] == "ready"
    assert payload["checks"]["runtime_store"]["integrity"] == "ok"
    assert payload["checks"]["knowledge_index"]["chunks"] > 0
    assert payload["checks"]["rl_datasets"]["available"] > 0
    assert payload["runtime_posture"]["application_ready"] is True
    assert payload["runtime_posture"]["recommendation_only"] is True
    assert payload["runtime_posture"]["dispatch_allowed"] is False
    assert payload["runtime_posture"]["production_authority"] is False

    info = client.get("/api/system/info").json()
    assert info["recommendation_only"] is True
    assert info["dispatch_allowed"] is False
    assert info["production_authority"] is False
    assert "shadow_operation" in info["authority_admission_requirements"]

    comparison = client.get("/api/system/competitive-benchmark").json()
    assert comparison["comparison_status"] == "not_claimed_surpassed"
    assert comparison["superiority_claim_gate"]["passed"] is False
    assert comparison["xiaoyi_verified_snapshot"]["production_authority"] is False
    assert len(comparison["artifact_sha256"]) == 64

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "xiaoyi_http_requests_total" in metrics.text
    assert "xiaoyi_build_info" in metrics.text


def test_idempotency_replays_success_and_rejects_key_reuse() -> None:
    key = f"test-{uuid4().hex}"
    headers = {"X-Idempotency-Key": key}
    body = {"report_type": "energy", "include_recommendations": True, "energy_range": "7d"}

    first = client.post("/api/reports", json=body, headers=headers)
    second = client.post("/api/reports", json=body, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.headers["x-idempotent-replay"] == "true"
    assert second.json()["id"] == first.json()["id"]

    conflict = client.post(
        "/api/reports",
        json={**body, "energy_range": "30d"},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert "幂等键" in conflict.json()["detail"]


def test_server_chat_history_streaming_and_clear() -> None:
    session_id = f"test-{uuid4().hex}"
    body = {
        "question": "小懿的核心能力是什么？",
        "mode": "expert",
        "top_k": 5,
        "strict_evidence": True,
        "session_id": session_id,
    }
    answered = client.post("/api/chat", json=body)
    assert answered.status_code == 200
    answer_id = answered.json()["answer_id"]
    assert answered.json()["generation_provider"] == "local_rules"

    history = client.get(f"/api/conversations/{session_id}")
    assert history.status_code == 200
    assert any(item["response"]["answer_id"] == answer_id for item in history.json()["items"])

    streamed = client.post("/api/chat/stream", json=body)
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert "event: metadata" in streamed.text
    assert "event: token" in streamed.text
    assert "event: done" in streamed.text

    cleared = client.delete(f"/api/conversations/{session_id}")
    assert cleared.status_code == 200
    assert cleared.json()["deleted"] >= 2
    assert client.get(f"/api/conversations/{session_id}").json()["items"] == []


def test_external_model_requires_explicit_data_egress_authorization() -> None:
    configuration = replace(
        Settings.from_env(),
        model_provider="openai_compatible",
        model_base_url="https://model.example.test/v1",
        model_name="approved-model",
        model_api_key="fixture-value",
        model_external_data_allowed=False,
    )
    gateway = ModelGateway(configuration)
    local = ChatResponse(
        app="小懿",
        mode="expert",
        intent="knowledge_qa",
        question="test",
        answer="local answer",
        evidence=[],
        confidence="low",
        next_questions=[],
        grounded=True,
    )
    result = gateway.enhance("test", local)
    assert result.answer == "local answer"
    assert result.generation_fallback is True
    assert "external_data_not_authorized" in (result.generation_notice or "")
    assert gateway.status()["requests"] == 0
