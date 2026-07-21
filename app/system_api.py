from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

from app.config import APP_NAME, APP_VERSION, INDEX_PATH
from app.model_gateway import model_gateway
from app.observability import telemetry
from app.rl_lab.datasets import dataset_catalog
from app.runtime_store import runtime_store
from app.settings import settings


router = APIRouter(tags=["系统健康与可观测性"])


def _index_check() -> dict[str, Any]:
    if not INDEX_PATH.is_file():
        return {"ok": False, "detail": "知识索引文件不存在"}
    try:
        payload = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "detail": f"知识索引不可读：{str(exc)[:200]}"}
    chunks = payload.get("chunks") if isinstance(payload, dict) else payload if isinstance(payload, list) else None
    return {
        "ok": isinstance(chunks, list) and len(chunks) > 0,
        "chunks": len(chunks) if isinstance(chunks, list) else 0,
        "detail": "索引可读" if isinstance(chunks, list) and chunks else "索引没有可检索片段",
    }


def _dataset_check() -> dict[str, Any]:
    try:
        items = [item.public_dict(inspect_file=False) for item in dataset_catalog().values()]
    except Exception as exc:
        return {"ok": False, "detail": str(exc)[:200], "available": 0}
    available = sum(bool(item["available"]) for item in items)
    return {"ok": available > 0, "available": available, "registered": len(items)}


def readiness_payload() -> dict[str, Any]:
    checks = {
        "runtime_store": runtime_store.health_check(),
        "knowledge_index": _index_check(),
        "rl_datasets": _dataset_check(),
        "model_gateway": {
            "ok": bool(model_gateway.status()["configured"]),
            **model_gateway.status(),
        },
        "deployment_configuration": {
            "ok": not settings.deployment_blockers(),
            "blockers": settings.deployment_blockers(),
            "environment": settings.environment,
            "security_mode": settings.security_mode,
        },
    }
    ready = all(bool(item.get("ok")) for item in checks.values())
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "status": "ready" if ready else "not_ready",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "telemetry": telemetry.snapshot(),
    }


@router.get("/health/live")
def liveness() -> dict[str, str]:
    return {"app": APP_NAME, "version": APP_VERSION, "status": "alive"}


@router.get("/health/ready")
def readiness() -> JSONResponse:
    payload = readiness_payload()
    return JSONResponse(status_code=200 if payload["status"] == "ready" else 503, content=payload)


@router.get("/api/system/readiness")
def system_readiness() -> JSONResponse:
    payload = readiness_payload()
    return JSONResponse(status_code=200 if payload["status"] == "ready" else 503, content=payload)


@router.get("/api/system/info")
def system_info() -> dict[str, Any]:
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "environment": settings.environment,
        "security_mode": settings.security_mode,
        "authentication_verified": settings.security_mode == "jwt",
        "docs_enabled": settings.docs_enabled,
        "chat_retention_enabled": settings.chat_retention_enabled,
        "chat_retention_days": settings.chat_retention_days,
        "idempotency_enabled": True,
        "observability": ["structured_json_logs", "request_id", "prometheus_metrics", "deep_readiness"],
        "production_write_default": False,
    }


@router.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics() -> PlainTextResponse:
    return PlainTextResponse(
        telemetry.prometheus(app_name=APP_NAME, version=APP_VERSION),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
