from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Literal
from app.settings import settings
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.runtime_store import runtime_store
from app.security import request_identity


router = APIRouter(prefix="/api/conversations", tags=["持久对话历史"])
_SESSION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")


def _validate_session(session_id: str) -> str:
    if not _SESSION_ID.fullmatch(session_id):
        raise HTTPException(status_code=422, detail="session_id 只能包含字母、数字、点、下划线、冒号和连字符")
    return session_id


def _personal_cutoff(request: Request) -> str:
    if not request_identity(request).authenticated:
        raise HTTPException(status_code=403, detail="请先验证个人身份")
    return (datetime.now(timezone.utc) - timedelta(days=settings.chat_retention_days)).isoformat().replace("+00:00", "Z")


@router.get("")
def my_conversations(request: Request, limit: int = Query(30, ge=1, le=100)) -> dict[str, Any]:
    cutoff = _personal_cutoff(request)
    rows = runtime_store.list_chat_sessions(actor_id=request_identity(request).actor_id, cutoff=cutoff, limit=limit)
    return {"items": rows, "retention_scope": "current_actor"}


@router.get("/{session_id}")
def conversation_history(
    session_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    scope: Literal["accessible", "mine"] = "accessible",
) -> dict[str, Any]:
    identity = request_identity(request)
    items = runtime_store.list_chat_turns(
        _validate_session(session_id),
        actor_id=identity.actor_id,
        allow_all=identity.role == "admin" and scope != "mine",
        cutoff=_personal_cutoff(request) if scope == "mine" else None,
        limit=limit,
    )
    return {
        "session_id": session_id,
        "total": len(items),
        "retention_scope": "current_actor" if scope == "mine" else "current_actor_or_admin",
        "items": items,
    }


@router.delete("/{session_id}")
def clear_conversation(session_id: str, request: Request) -> dict[str, Any]:
    identity = request_identity(request)
    deleted = runtime_store.delete_chat_turns(
        _validate_session(session_id),
        actor_id=identity.actor_id,
        allow_all=identity.role == "admin",
    )
    return {"session_id": session_id, "deleted": deleted, "status": "cleared"}
