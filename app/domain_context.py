from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.runtime_store import runtime_store


router = APIRouter(prefix="/api/context", tags=["统一港航业务上下文"])


class DomainContext(BaseModel):
    port_code: Optional[str] = None
    terminal_id: Optional[str] = None
    imo_number: Optional[str] = None
    mmsi: Optional[str] = None
    vessel_call_id: Optional[str] = None
    berth_id: Optional[str] = None
    asset_id: Optional[str] = None
    scenario_id: Optional[str] = None
    policy_id: Optional[str] = None
    time_range: Optional[str] = None
    language: str = "zh-CN"
    extra: dict[str, str] = Field(default_factory=dict)


class ContextResolveRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=1000)
    session_id: str = Field("default", min_length=1, max_length=120)
    explicit: DomainContext = Field(default_factory=DomainContext)
    persist: bool = True


class ContextResolveResponse(BaseModel):
    session_id: str
    context: DomainContext
    detected_fields: list[str]
    inherited_fields: list[str]
    confidence: float
    notice: str


_TIME_PATTERNS = (
    (r"未来\s*(\d+)\s*小时", lambda m: f"next_{m.group(1)}h"),
    (r"未来\s*(\d+)\s*天", lambda m: f"next_{m.group(1)}d"),
    (r"最近\s*(\d+)\s*天", lambda m: f"last_{m.group(1)}d"),
    (r"今日|今天", lambda _m: "today"),
    (r"本周", lambda _m: "this_week"),
)


def _extract(question: str) -> dict[str, str]:
    text = question.strip()
    found: dict[str, str] = {}
    patterns = {
        "imo_number": r"\bIMO\s*[:：#-]?\s*(\d{7})\b",
        "mmsi": r"\bMMSI\s*[:：#-]?\s*(\d{9})\b",
        "vessel_call_id": r"(?:挂靠|艘次|航次)\s*(?:编号|ID)?\s*[:：#-]?\s*([A-Za-z0-9_-]{3,40})",
        "terminal_id": r"(?:码头|港区)\s*(?:编号|ID)?\s*[:：#-]?\s*([A-Za-z0-9_-]{2,30})",
        "berth_id": r"(?:泊位|泊位号)\s*[:：#-]?\s*([A-Za-z0-9_-]{1,20})",
        "asset_id": r"\b((?:AGV|QC|RTG|RMG|ASC|STS)[-_]?\d{1,5})\b",
        "scenario_id": r"(?:场景|scenario)\s*(?:编号|ID)?\s*[:：#-]?\s*([A-Za-z0-9_-]{2,40})",
        "policy_id": r"(?:策略|policy)\s*(?:编号|ID)?\s*[:：#-]?\s*([A-Za-z0-9_-]{2,40})",
    }
    for field, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            found[field] = match.group(1).upper() if field in {"imo_number", "mmsi", "asset_id"} else match.group(1)
    port_match = re.search(r"\b([A-Z]{5})\b", text)
    if port_match:
        found["port_code"] = port_match.group(1)
    for pattern, formatter in _TIME_PATTERNS:
        match = re.search(pattern, text)
        if match:
            found["time_range"] = formatter(match)
            break
    if re.search(r"[A-Za-z]{4,}", text) and not re.search(r"[\u4e00-\u9fff]", text):
        found["language"] = "en"
    return found


def resolve_context(
    question: str,
    *,
    session_id: str = "default",
    explicit: DomainContext | None = None,
    persist: bool = True,
) -> ContextResolveResponse:
    inherited_payload = runtime_store.get_context(session_id)
    inherited = inherited_payload["context"] if inherited_payload else {}
    detected = _extract(question)
    explicit_values = (explicit or DomainContext()).model_dump(exclude_none=True)
    explicit_values = {key: value for key, value in explicit_values.items() if value not in ({}, "")}
    merged = {**inherited, **detected, **explicit_values}
    context = DomainContext.model_validate(merged)
    detected_fields = sorted(set(detected) | set(explicit_values))
    inherited_fields = sorted(key for key in inherited if key not in detected_fields)
    if persist:
        runtime_store.save_context(session_id, context.model_dump(mode="json"))
    meaningful = [value for key, value in context.model_dump().items() if key not in {"language", "extra"} and value]
    confidence = min(1.0, 0.25 + len(meaningful) * 0.12 + (0.18 if detected_fields else 0.0))
    return ContextResolveResponse(
        session_id=session_id,
        context=context,
        detected_fields=detected_fields,
        inherited_fields=inherited_fields,
        confidence=round(confidence, 2),
        notice="显式字段优先，其次采用当前问题识别结果，最后继承同一会话的已确认上下文。",
    )


@router.post("/resolve", response_model=ContextResolveResponse)
def resolve_context_api(payload: ContextResolveRequest) -> ContextResolveResponse:
    return resolve_context(
        payload.question,
        session_id=payload.session_id,
        explicit=payload.explicit,
        persist=payload.persist,
    )


@router.get("/{session_id}")
def get_context(session_id: str) -> dict[str, Any]:
    item = runtime_store.get_context(session_id)
    if item is None:
        raise HTTPException(status_code=404, detail="尚未建立该会话的港航业务上下文")
    return item
