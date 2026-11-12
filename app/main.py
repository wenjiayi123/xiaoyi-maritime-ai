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
from app import offer_comparison, offer_language
from app import policy_release
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
from app.models import AnswerTiming, ChatRequest, ChatResponse, DemoTriadRequest, QueryAnalysis
from app.model_gateway import model_gateway, router as model_router
from app.observability import telemetry
from app.analytics_throughput import router as throughput_analytics_router
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
from app.linked_agent import router as linked_agent_router
from app.harness.api import router as harness_router, close_harness
from app.harness.workorders_api import router as workorders_router, close_workorders
from app.cycle_routes import router as decision_cycle_router
from app.harness.dual_api import router as dual_harness_router, recover as recover_dual_harness
from app.harness.proof_api import router as proof_router
from app.harness.capability_review_v8 import router as capability_review_router
from app.harness.priority_v9 import router as priority_v9_router
from app.harness.root_cause_v10 import router as root_cause_v10_router
from app.harness.shanghai_lab import router as shanghai_lab_router
from app.agent_training.api import router as agent_rl_router
from app.xiaoyi import XiaoyiAI


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_startup()
    recover_dual_harness()
    try:
        yield
    finally:
        close_workorders()
        close_harness()


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
app.include_router(throughput_analytics_router)
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
app.include_router(linked_agent_router)
app.include_router(harness_router)
app.include_router(workorders_router)
app.include_router(decision_cycle_router)
app.include_router(dual_harness_router)
app.include_router(proof_router)
app.include_router(capability_review_router)
app.include_router(priority_v9_router)
app.include_router(root_cause_v10_router)
app.include_router(shanghai_lab_router)
app.include_router(agent_rl_router)


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
        "usage": "可直接点击或用现场口语提问；业务对象不明确时，舷鸥会先追问船名、设备号、泊位或时间范围。",
        "safety_boundary": "沙箱态势与知识证据分层展示；生产动作必须由授权岗位确认。",
    }


def _prepare_answer(payload: ChatRequest, request: Request):
    started_at = time.monotonic()
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
    if payload.offer_sheet is None:
        compare_requested, sheet = offer_language.from_question(payload.question)
    else:
        compare_requested, sheet = True, payload.offer_sheet
    review_requested, selection = policy_release.from_command(payload.question)
    from app.production_boundary import requests_field_control

    control_text = payload.question
    if payload.shore_case is not None and payload.shore_change:
        control_text += "。" + payload.shore_change
    if requests_field_control(control_text):
        response = engine.ask(control_text, mode=payload.mode, strict_evidence=True)
    elif payload.shore_case is not None:
        from app import shore_history

        receipt=None;proposer=None
        try:
            case=payload.shore_case
            amendment=None
            if payload.shore_change and case.as_of.isoformat()==shore_history.source_notes()["as_of"]:
                from app.shore_changes import bind

                proposal,proposer=model_gateway.propose_shore_change(case,payload.shore_change)
                case,amendment=bind(case,payload.shore_change,proposal)
                amendment.update(proposer_model=proposer,proposed_changes=proposal["changes"],
                    confirmed_berth_range=case.berth_range.model_dump() if case.berth_range else None)
            receipt=shore_history.evaluate(case)
            if amendment is not None:receipt["amendment"]=amendment
            answer=shore_history.summary(receipt)
        except (OSError,ValueError) as exc:
            answer="本次岸电历史核对暂缓，原因是"+str(exc)[:160]+"。"
        complete=bool(receipt and all(receipt[key]["label"]!="U" for key in ("national","local")))
        response=ChatResponse(app=APP_NAME,mode=payload.mode,question=payload.question,intent="historical_shore_review",
            answer=answer,shore_history_receipt=receipt,evidence=[],confidence="medium" if complete else "low",next_questions=[],
            strict_evidence=payload.strict_evidence,source_quality="declared_case_and_verified_source" if receipt else "unverified",
            evidence_requirement="two_named_historical_provisions",requires_human_review=True,
            refusal_reason=None if complete else "historical_scope_or_evidence_missing",
            generation_model=proposer or "gullmate-historical-shore-v1",generation_provider="openai_compatible" if proposer else "local_rules",
            generation_notice="模型提议事实变更，按原文和具名条款复核。" if proposer else "按登记事实与具名条款核对。",
            completion_status="complete" if complete else "partial")
    elif payload.exercise_record is not None:
        from app import exercise_records

        general=payload.exercise_record.kind=="general"
        receipt=(model_gateway.reason_about_exercise(payload.exercise_record,payload.question) if general
                 else exercise_records.verify(payload.exercise_record,payload.question))
        complete=receipt["decision"]!="UNKNOWN"
        response=ChatResponse(app=APP_NAME, mode=payload.mode, question=payload.question,
            intent="exercise_receipt", answer=exercise_records.summary(receipt), exercise_receipt=receipt,
            evidence=[], confidence="medium" if complete else "low", next_questions=[],
            strict_evidence=payload.strict_evidence, source_quality="declared_scenario",
            evidence_requirement="user_declared_exercise_record", requires_human_review=True,
            refusal_reason=None if complete else "insufficient_exercise_record",
            generation_provider="openai_compatible" if general and receipt.get("model") else "local_rules",
            generation_model=receipt.get("model") if general else "gullmate-exercise-v1",
            generation_notice=("本地模型选择核算项目，核验器按已提供的统计与练习条件核对。" if receipt.get("model_role")=="operation_selection"
                               else "模型按用户资料试算，独立业务核验尚需完成。" if general else "逐字段核对用户提供的演练资料，仅在给定假设内成立。"),
            completion_status="complete" if complete else "partial")
    elif review_requested and payload.offer_sheet is None:
        policy_receipt = None
        if selection is None:
            answer = "请使用 /策略复验 scenario=stress seed=17 baseline=fixed window=0。窗口从 0 到 11；省略窗口可查看均值。"
        else:
            try:
                policy_receipt = policy_release.compare(selection)
                answer = policy_release.summarize(policy_receipt)
            except policy_release.ReleaseUnavailable as exc:
                answer = str(exc) + "，本次没有可引用的策略结果。"
        response = ChatResponse(app=APP_NAME, mode=payload.mode, question=payload.question,
            intent="trained_policy_review", answer=answer, evidence=[], policy_comparison=policy_receipt,
            confidence="medium" if policy_receipt else "low", next_questions=[], strict_evidence=payload.strict_evidence,
            source_quality="verified_simulation" if policy_receipt else "unverified", evidence_requirement="carbonops_pinned_receipt",
            requires_human_review=True, generation_provider="local_rules", generation_model="gullmate-policy-release-v1",
            completion_status="complete" if policy_receipt else "partial")
    elif compare_requested:
        receipt = offer_comparison.compare(sheet) if sheet else None
        complete = receipt is not None and receipt["status"] != "needs_evidence"
        answer = offer_comparison.summarize(receipt) if receipt else (
            "要确认最低可行报价，需要逐项核对候选、价格及其适用约束。"
            "请在「决策建议 → 可行方案比选」填写每项报价、吃水或供电容量以及核验来源；缺项可留空。"
        )
        response = ChatResponse(app=APP_NAME, mode=payload.mode, question=payload.question,
            intent="offer_comparison", answer=answer, evidence=[], offer_comparison=receipt,
            confidence="medium" if complete else "low", next_questions=[], strict_evidence=payload.strict_evidence,
            source_quality="declared_scenario", evidence_requirement="declared_offer_sheet",
            requires_human_review=True, generation_provider="local_rules", generation_model="offer-comparison-v1",
            generation_notice="报价与约束按登记计算规则处理。", completion_status="complete" if complete else "partial")
    elif query_analysis.requires_clarification:
        response = ChatResponse(
            app=APP_NAME, mode=payload.mode, question=payload.question,
            intent="operator_clarification",
            answer="我还不能确定你指的是哪项要求或哪个业务对象。请补充刚才的问题、法规名称，或船舶、设备、港口及时间范围，我再继续分析。",
            evidence=[], confidence="low",
            next_questions=["港口交接班需要交代哪些事项？", "船舶到港报告应从哪里核验？"],
            strict_evidence=payload.strict_evidence, source_quality="not_applicable",
            refusal_reason="business_object_required", completion_status="not_applicable",
        )
    elif len(query_analysis.subquestions) > 1:
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
            "timing": AnswerTiming(preparation_ms=round((time.monotonic() - started_at) * 1000, 3)),
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
    verification_started_at = time.monotonic()
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
    verification_ms = (time.monotonic() - verification_started_at) * 1000
    timing = response.timing.model_copy(update={
        "verification_ms": round(verification_ms, 3),
        "total_ms": round(response.timing.preparation_ms + response.timing.generation_ms + verification_ms, 3),
    })
    response = response.model_copy(update={"session_id": payload.session_id, "answer_id": answer_id, "timing": timing})
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
            **({"offer_sheet_sha256": response.offer_comparison["sheet_sha256"],
                "offer_result_sha256": response.offer_comparison["result_sha256"]} if response.offer_comparison else {}),
            **({"exercise_source":response.exercise_receipt["source"],
                "exercise_facts_sha256":response.exercise_receipt["facts_sha256"],
                "exercise_decision":response.exercise_receipt["decision"]} if response.exercise_receipt else {}),
            **({"shore_case_sha256":response.shore_history_receipt["case_sha256"],
                "shore_source_sha256":response.shore_history_receipt["evidence_sha256"]} if response.shore_history_receipt else {}),
            **({"policy_release_sha256": response.policy_comparison["release_sha256"],
                "policy_sha256": response.policy_comparison["policy_sha256"]} if response.policy_comparison else {}),
            "timing": response.timing.model_dump(),
        },
        detail="问答结果已记录证据策略与回答校验指标；校验结果不阻断生成答案，审计仅保存请求与结果哈希。",
    )
    return response


def _answer(payload: ChatRequest, request: Request) -> ChatResponse:
    review_started_at = time.monotonic()
    identity, history, query_analysis, response = _prepare_answer(payload, request)
    generation_started_at = time.monotonic()
    response = model_gateway.enhance(
        query_analysis.standalone_question,
        response,
        history=_generation_history(history, query_analysis),
        review_started_at=review_started_at,
    )
    response = response.model_copy(update={"timing": response.timing.model_copy(update={
        "generation_ms": round((time.monotonic() - generation_started_at) * 1000, 3),
    })})
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


@app.post("/api/chat/demo-triad")
def chat_demo_triad(payload: DemoTriadRequest, request: Request) -> dict[str, Any]:
    """Run three fixed, evidence-grounded answer forms without model warm-up latency."""
    started_at = time.monotonic()
    prompts = [
        {
            "category": "general",
            "label": "一般问答",
            "tone": "blue",
            "format": "概念解释 · 关系对比 · 来源引用",
            "mode": "expert",
            "question": "港口 TOS 和 PCS 分别负责什么？二者如何协同？",
        },
        {
            "category": "daily",
            "label": "日常问答",
            "tone": "green",
            "format": "现象判断 · 排查顺序 · 岗位交接",
            "mode": "ops",
            "question": "岸桥单位作业能耗偏高，值班人员今天应按什么顺序排查？",
        },
        {
            "category": "emergency",
            "label": "紧急问答",
            "tone": "red",
            "format": "立即停止 · 人员安全 · 通报升级 · 恢复门禁",
            "mode": "sop",
            "question": "堆场冷藏箱区域冒烟怎么办？",
        },
    ]
    items: list[dict[str, Any]] = []
    for item in prompts:
        chat_payload = ChatRequest(
            question=item["question"],
            mode=item["mode"],
            top_k=6,
            strict_evidence=True,
            session_id=f"{payload.session_id}:{item['category']}",
        )
        identity, history, query_analysis, response = _prepare_answer(chat_payload, request)
        response = response.model_copy(
            update={
                "generation_provider": "local_rules",
                "generation_model": None,
                "generation_fallback": False,
                "generation_notice": "三类问答演示使用本地检索与确定性回答结构，不等待生成模型预热。",
                "timing": response.timing.model_copy(update={"generation_ms": 0.0}),
            }
        )
        final = _finalize_answer(
            chat_payload,
            request,
            identity,
            query_analysis,
            response,
        )
        items.append({**item, "response": final.model_dump(mode="json")})
    return {
        "schema_version": "xiaoyi-demo-answer-triad.v1",
        "items": items,
        "completed": len(items) == 3,
        "elapsed_ms": round((time.monotonic() - started_at) * 1000, 3),
        "production_authority": False,
        "notice": "三类回答均完成本地知识检索、来源标记、回答校验和审计留痕；紧急处置不替代现场授权岗位。",
    }


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
            "generation_provider": prepared_response.generation_provider if prepared_response.intent == "offer_comparison" else model_gateway.status()["provider"],
        }
        yield f"event: metadata\ndata: {json.dumps(metadata, ensure_ascii=False)}\n\n"
        generation_started_at = time.monotonic()
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
        response = response.model_copy(update={"timing": response.timing.model_copy(update={
            "generation_ms": round((time.monotonic() - generation_started_at) * 1000, 3),
        })})
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
