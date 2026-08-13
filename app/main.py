import json
import time
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.automation import router as automation_router
from app.answer_verification import verify_response
from app.decision_assurance import assess_response
from app.advanced_rl_missions import router as advanced_rl_router
from app.capability_hub import router as capability_hub_router
from app.config import APP_NAME, APP_VERSION, DEFAULT_TOP_K, KB_DIR, WEB_DIR
from app.connectors import router as connectors_router
from app.conversations import router as conversations_router
from app.domain_context import router as domain_context_router
from app.evaluation import router as evaluation_router
from app.evidence_fusion import router as evidence_fusion_router
from app.governance import router as governance_router
from app.knowledge_api import get_knowledge_status, router as knowledge_router
from app.knowledge_intake import router as knowledge_intake_router
from app.linked_system_launcher import router as linked_system_launcher_router
from app.models import ChatRequest, ChatResponse, QueryAnalysis
from app.model_gateway import model_gateway, router as model_router
from app.observability import telemetry
from app.operations import router as operations_router
from app.operator_assistant import operator_scenarios
from app.orchestrator import router as orchestrator_router
from app.query_intelligence import build_query_analysis
from app.realtime_port_simulator import router as realtime_port_simulator_router
from app.rl_mission import router as rl_mission_router
from app.rl_lab import router as rl_lab_router
from app.runtime_store import runtime_store
from app.security import IdempotencyMiddleware, PlatformMiddleware, request_identity
from app.sailing_simulator_launcher import router as sailing_simulator_launcher_router
from app.simulator_launcher import router as simulator_launcher_router
from app.settings import settings
from app.system_api import router as system_router
from app.system_linkage import router as system_linkage_router
from app.xiaoyi import XiaoyiAI


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_startup()
    yield


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
engine = XiaoyiAI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization", "Content-Type", "X-Request-ID", "X-Xiaoyi-Trace-Id", "X-Idempotency-Key",
        "X-Xiaoyi-Actor", "X-Xiaoyi-Role", "X-Xiaoyi-Generation-Id",
    ],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(IdempotencyMiddleware, settings=settings)
app.add_middleware(PlatformMiddleware, settings=settings, telemetry=telemetry)
app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")
app.include_router(automation_router)
app.include_router(advanced_rl_router)
app.include_router(connectors_router)
app.include_router(knowledge_router)
app.include_router(knowledge_intake_router)
app.include_router(operations_router)
app.include_router(realtime_port_simulator_router)
app.include_router(capability_hub_router)
app.include_router(domain_context_router)
app.include_router(evidence_fusion_router)
app.include_router(orchestrator_router)
app.include_router(governance_router)
app.include_router(evaluation_router)
app.include_router(rl_mission_router)
app.include_router(rl_lab_router)
app.include_router(sailing_simulator_launcher_router)
app.include_router(simulator_launcher_router)
app.include_router(linked_system_launcher_router)
app.include_router(conversations_router)
app.include_router(model_router)
app.include_router(system_router)
app.include_router(system_linkage_router)


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict[str, str]:
    return {"app": APP_NAME, "version": APP_VERSION, "status": "ready"}


@app.get("/api/knowledge")
def knowledge() -> dict[str, object]:
    files = sorted(path.name for path in KB_DIR.glob("*.md"))
    status = get_knowledge_status()
    return {
        "count": status.document_count,
        "files": files,
        "default_top_k": DEFAULT_TOP_K,
        "chunk_count": status.chunk_count,
        "official_verified_documents": status.official_verified_documents,
        "official_summary_documents": status.official_summary_documents,
        "official_locator_documents": status.official_locator_documents,
        "official_full_text_documents": status.official_full_text_documents,
        "completeness_claim": status.completeness_claim,
        "internal_curated_documents": status.internal_curated_documents,
        "index_sha256": status.index_sha256,
        "strict_evidence_default": status.strict_evidence_default,
    }


@app.get("/api/operator/scenarios")
def frontline_operator_scenarios() -> dict[str, object]:
    return {
        "items": operator_scenarios(),
        "usage": "可直接点击或用现场口语提问；业务对象不明确时，小懿会先追问船名、设备号、泊位或时间范围。",
        "safety_boundary": "沙箱态势与知识证据分层展示；生产动作必须由授权岗位确认。",
    }


def _prepare_answer(payload: ChatRequest, request: Request):
    identity = request_identity(request)
    history = (
        runtime_store.list_chat_turns(
            payload.session_id,
            actor_id=identity.actor_id,
            allow_all=False,
            limit=6,
        )
        if settings.chat_retention_enabled
        else []
    )
    query_analysis = build_query_analysis(payload.question, history=history)
    if len(query_analysis.subquestions) > 1:
        response = engine.ask_compound(
            query_analysis.standalone_question,
            query_analysis.subquestions,
            mode=payload.mode,
            top_k=payload.top_k,
            strict_evidence=payload.strict_evidence,
            jurisdiction=payload.jurisdiction,
            as_of_date=payload.as_of_date,
        )
    else:
        response = engine.ask(
            query_analysis.standalone_question,
            mode=payload.mode,
            top_k=payload.top_k,
            strict_evidence=payload.strict_evidence,
            jurisdiction=payload.jurisdiction,
            as_of_date=payload.as_of_date,
            retrieval_queries=query_analysis.subquestions,
        )
    response = response.model_copy(
        update={
            "question": payload.question,
            "query_analysis": query_analysis,
        }
    )
    return identity, history, query_analysis, response


def _generation_history(
    history: list[dict[str, Any]],
    query_analysis: QueryAnalysis,
) -> list[dict[str, Any]]:
    if query_analysis.resolution != "history_resolved":
        return []
    return history[:1]


def _finalize_answer(
    payload: ChatRequest,
    request: Request,
    identity,
    query_analysis,
    response: ChatResponse,
) -> ChatResponse:
    response = response.model_copy(
        update={"answer_verification": verify_response(response)}
    )
    evidence_health, decision_readiness = assess_response(
        response,
        query_analysis,
    )
    response = response.model_copy(
        update={
            "evidence_health": evidence_health,
            "decision_readiness": decision_readiness,
        }
    )
    answer_id = f"answer-{uuid4().hex}"
    response = response.model_copy(update={"session_id": payload.session_id, "answer_id": answer_id})
    if settings.chat_retention_enabled:
        runtime_store.save_chat_turn(
            session_id=payload.session_id,
            actor_id=identity.actor_id,
            question=payload.question,
            response=response.model_dump(mode="json"),
            retention_days=settings.chat_retention_days,
        )
    runtime_store.add_audit(
        correlation_id=getattr(request.state, "request_id", answer_id),
        actor_id=identity.actor_id,
        actor_role=identity.role,
        action="chat.answer",
        resource=payload.session_id,
        risk_level=response.decision_readiness.risk_level,
        outcome="success",
        request={"question": payload.question, "mode": payload.mode, "strict_evidence": payload.strict_evidence},
        response={
            "answer_id": answer_id,
            "intent": response.intent,
            "grounded": response.grounded,
            "query_resolution": query_analysis.resolution,
            "citation_verification": response.answer_verification.status,
            "evidence_alignment": response.answer_verification.evidence_alignment,
            "numeric_integrity": response.answer_verification.numeric_integrity,
            "evidence_health": response.evidence_health.status,
            "decision_readiness": response.decision_readiness.status,
        },
        detail="问答结果已记录证据策略与回答校验指标；校验结果不阻断生成答案，审计仅保存请求与结果哈希。",
    )
    return response


def _answer(payload: ChatRequest, request: Request) -> ChatResponse:
    review_started_at = time.monotonic()
    identity, history, query_analysis, response = _prepare_answer(payload, request)
    response = model_gateway.enhance(
        query_analysis.standalone_question,
        response,
        history=_generation_history(history, query_analysis),
        review_started_at=review_started_at,
    )
    return _finalize_answer(
        payload,
        request,
        identity,
        query_analysis,
        response,
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    return _answer(payload, request)


@app.post("/api/chat/stream")
def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    review_started_at = time.monotonic()
    generation_id = (
        request.headers.get("X-Xiaoyi-Generation-Id")
        or f"xiaoyi-{uuid4().hex}"
    )
    identity, history, query_analysis, prepared_response = _prepare_answer(payload, request)

    def natural_chunks(text: str, target: int = 28, maximum: int = 52):
        start = 0
        for index, character in enumerate(text, start=1):
            length = index - start
            if length >= maximum or (
                length >= target
                and character in "，。！？；：\n,.!?;:"
            ):
                yield text[start:index]
                start = index
        if start < len(text):
            yield text[start:]

    def events():
        metadata = {
            "session_id": payload.session_id,
            "intent": prepared_response.intent,
            "generation_provider": model_gateway.status()["provider"],
        }
        yield f"event: metadata\ndata: {json.dumps(metadata, ensure_ascii=False)}\n\n"
        stream = model_gateway.enhance_stream(
            query_analysis.standalone_question,
            prepared_response,
            history=_generation_history(history, query_analysis),
            review_started_at=review_started_at,
            generation_id=generation_id,
        )
        streamed = False
        while True:
            try:
                chunk = next(stream)
            except StopIteration as completed:
                response = completed.value
                break
            streamed = True
            yield f"event: token\ndata: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
        if not streamed:
            for chunk in natural_chunks(response.answer):
                yield f"event: token\ndata: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
        response = _finalize_answer(
            payload,
            request,
            identity,
            query_analysis,
            response,
        )
        yield f"event: done\ndata: {response.model_dump_json()}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


@app.delete("/api/chat/generations/{generation_id}")
def cancel_chat_generation(generation_id: str) -> dict[str, object]:
    try:
        return model_gateway.cancel_generation(generation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def custom_openapi() -> dict[str, object]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=APP_NAME, version=APP_VERSION, routes=app.routes)
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {
        "type": "http", "scheme": "bearer", "bearerFormat": "JWT",
        "description": "production 模式使用HS256签名JWT；角色权限由服务端根据role声明映射。",
    }
    for path, methods in schema.get("paths", {}).items():
        if path in {"/", "/health", "/health/live", "/health/ready"}:
            continue
        for operation in methods.values():
            if isinstance(operation, dict):
                operation.setdefault("security", [{"BearerAuth": []}])
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
