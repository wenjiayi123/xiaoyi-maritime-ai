from __future__ import annotations

import re
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


@router.get("/{session_id}")
def conversation_history(
    session_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    identity = request_identity(request)
    items = runtime_store.list_chat_turns(
        _validate_session(session_id),
        actor_id=identity.actor_id,
        allow_all=identity.role == "admin",
        limit=limit,
    )
    return {
        "session_id": session_id,
        "total": len(items),
        "retention_scope": "current_actor_or_admin",
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
