from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.runtime_store import runtime_store
from app.access_control import ROLE_PERMISSIONS, Role, has_permission
from app.security import request_identity


router = APIRouter(prefix="/api/governance", tags=["身份权限与持久审计"])

class Identity(BaseModel):
    actor_id: str
    role: Role
    permissions: list[str]
    authentication_status: str
    authenticated: bool
    production_notice: str


class AuthorizationRequest(BaseModel):
    actor_id: str = Field(..., min_length=2, max_length=100)
    role: Role
    permission: str = Field(..., min_length=3, max_length=100)


@router.get("/identity", response_model=Identity)
def current_identity(request: Request) -> Identity:
    identity = request_identity(request)
    return Identity(
        actor_id=identity.actor_id,
        role=identity.role,
        permissions=identity.permissions,
        authentication_status=identity.authentication_status,
        authenticated=identity.authenticated,
        production_notice=(
            "当前身份已通过服务端签名令牌验证。"
            if identity.authenticated
            else "当前为本地开发身份，不构成生产认证；生产模式必须使用服务端验证的Bearer令牌。"
        ),
    )


@router.post("/authorize")
def authorize(payload: AuthorizationRequest) -> dict[str, Any]:
    allowed = has_permission(payload.role, payload.permission)
    return {
        "actor_id": payload.actor_id, "role": payload.role, "permission": payload.permission,
        "authorized": allowed, "decision": "allow" if allowed else "deny",
    }


@router.get("/audit")
def audit_events(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    correlation_id: Optional[str] = Query(None),
) -> dict[str, Any]:
    identity = request_identity(request)
    if not has_permission(identity.role, "audit.read") and identity.role != "admin":
        raise HTTPException(status_code=403, detail="只有 operator 或 admin 可以读取跨系统审计记录")
    items = runtime_store.list_audit(limit=limit, correlation_id=correlation_id)
    return {"total": len(items), "persistent": True, "items": items}


@router.get("/metrics")
def governance_metrics() -> dict[str, Any]:
    return {"persistent_store": True, "permissions": ROLE_PERMISSIONS, **runtime_store.metrics()}
