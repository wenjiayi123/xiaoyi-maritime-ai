from __future__ import annotations

import asyncio
import json
import threading
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.access_control import has_permission
from app.harness import model, tools
from app.harness.contracts import (
    TERMINAL,
    DUAL_TEMPLATES,
    WAITING,
    VERSION,
    ApprovalRequest,
    CreateTask,
    InputRequest,
    MemoryRequest,
    digest,
    encoded,
)
from app.harness.runner import Harness
from app.harness.store import Conflict, HarnessStore
from app.runtime_store import runtime_store
from app.security import request_identity
from app.settings import settings
from app.harness.runtime import build_info
from pydantic import Field
from app.harness.contracts import StrictModel, Budget

router = APIRouter(prefix="/api/harness", tags=["Harness港航任务运行层"])
_runtime: Harness | None = None
_runtime_lock = threading.RLock()


def get_harness() -> Harness:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = Harness(HarnessStore(runtime_store.path))
            _runtime.start()
        return _runtime


def close_harness():
    global _runtime
    with _runtime_lock:
        if _runtime is not None:
            _runtime.close()
            _runtime = None


def task_for(task_id: str, request: Request) -> dict:
    task = get_harness().store.get(task_id)
    if not task:
        raise HTTPException(404, "未找到任务")
    identity = request_identity(request)
    if identity.actor_id != task["actor_id"] and identity.role != "admin":
        raise HTTPException(403, "只能访问自己的任务")
    return task


def perform(fn):
    try:
        return fn()
    except Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)[:500]) from exc


@router.get("/capabilities")
def capabilities(request: Request):
    identity = request_identity(request)
    config = model.configuration()
    return {
        "schema": VERSION,
        "runtime": build_info(),
        "modes": [{"id": "enterprise", "label": "企业受控模式"}, {"id": "research", "label": "RL策略研究模式"}],
        "dual_templates": DUAL_TEMPLATES,
        "model_profiles": [{"id": "existing", "label": "小懿现有模型"}, {"id": "open_agent", "label": "AgentCPM开源候选（独立服务）"}],
        "tools": tools.catalog(identity.role),
        "skills": list(tools.SKILLS.values()),
        "drivers": {
            "rules": True,
            "model": config["available"],
            "model_name": config["name"] or None,
            "model_local": config["local"],
            "notice": config["notice"],
        },
        "features": [
            "tool_loop",
            "planning",
            "durable_checkpoints",
            "leases",
            "pause_resume",
            "cancel",
            "steering",
            "clarification",
            "bound_approvals",
            "context_compaction",
            "skills",
            "explicit_memory",
            "virtual_artifacts",
            "parallel_reads",
            "mcp_read_tools",
            "sse",
            "trace_export",
            "evaluation",
        ],
        "production_authority": False,
        "execution_environment": "登记业务工具与任务虚拟工作区；无任意Shell或主机文件执行权限",
        "maritime": tools.maritime.catalog(),
    }


@router.post("/tasks", status_code=202)
def create_task(payload: CreateTask, request: Request):
    return perform(lambda: get_harness().create(payload, request_identity(request)))


class ChatTask(StrictModel):
    text: str = Field(min_length=2, max_length=4000)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")
    force_task: bool = False


@router.post("/chat")
def chat_task(payload: ChatTask, request: Request):
    import re
    from app.harness.adaptive import ADAPTIVE_TOOLS

    # This routes an imperative to the agent; it supplies neither actions nor order.
    operational = bool(re.search(r"查看|检查|读取|比较|对比|试算|暂停|恢复|切换|验证|核验|回放|执行|帮我|请", payload.text))
    subject = bool(re.search(r"能碳|马六甲|数字孪生|航行模拟器|强化学习|RL|策略|Harness|harness", payload.text))
    conceptual = bool(re.search(r"是什么|什么是|怎么实现|如何实现|能否|可以吗|能不能|原理", payload.text))
    if not payload.force_task and not (operational and subject and not conceptual):
        return {"handled": False, "route": "existing_chat"}
    identity = request_identity(request)
    names = [t["name"] for t in tools.catalog(identity.role, ADAPTIVE_TOOLS)]
    if not re.search(r"强化学习|RL|策略|回放|基线", payload.text, re.I):
        names = [n for n in names if not n.startswith("strategy.")]
    task = perform(lambda: get_harness().create(CreateTask(goal=payload.text, request_id=payload.request_id,
        planning_mode="adaptive", driver="model", allowed_tools=names, required_tools=[],
        budget=Budget(max_steps=18, max_tool_calls=24, max_active_seconds=900, max_tokens=48000)), identity))
    return {"handled": True, "route": "adaptive_harness", "task": task, "runtime": build_info()}


@router.get("/tasks")
def list_tasks(request: Request, limit: int = Query(60, ge=1, le=100)):
    identity = request_identity(request)
    return {"items": get_harness().store.list(None if identity.role == "admin" else identity.actor_id, limit)}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, request: Request):
    return task_for(task_id, request)


@router.post("/tasks/{task_id}/control/{command}")
def control_task(task_id: str, command: str, request: Request):
    task_for(task_id, request)
    identity = request_identity(request)
    return perform(lambda: get_harness().control(task_id, command, identity.role, actor_id=identity.actor_id))


@router.post("/tasks/{task_id}/inputs")
def input_task(task_id: str, payload: InputRequest, request: Request):
    task_for(task_id, request)
    identity = request_identity(request)
    return perform(lambda: get_harness().input(task_id, payload, identity.role, actor_id=identity.actor_id))


@router.post("/tasks/{task_id}/approval")
def approve_task(task_id: str, payload: ApprovalRequest, request: Request):
    task_for(task_id, request)
    return perform(lambda: get_harness().approve(task_id, payload, request_identity(request)))


@router.post("/tasks/{task_id}/reconcile")
def reconcile_task(task_id: str, request: Request):
    task = task_for(task_id, request)
    identity = request_identity(request)
    if not has_permission(identity.role, "operations.manage"):
        raise HTTPException(403, "没有联动状态核查权限")
    return perform(lambda: get_harness().reconcile(task))


@router.get("/tasks/{task_id}/events")
def task_events(task_id: str, request: Request, after: int = Query(0, ge=0)):
    task = task_for(task_id, request)
    return {"items": get_harness().store.events(task_id, after), "status": task["status"], "version": task["version"]}


@router.get("/tasks/{task_id}/stream")
async def task_stream(task_id: str, request: Request, after: int = Query(0, ge=0)):
    task_for(task_id, request)
    try:
        cursor = max(after, int(request.headers.get("Last-Event-ID", "0")))
    except ValueError as exc:
        raise HTTPException(422, "无效事件游标") from exc
    runtime = get_harness()

    async def stream():
        nonlocal cursor
        started = time.monotonic()
        while time.monotonic() - started < 55 and not await request.is_disconnected():
            events = await asyncio.to_thread(runtime.store.events, task_id, cursor)
            for event in events:
                cursor = event["seq"]
                yield f"id: {cursor}\nevent: harness\ndata: {encoded(event)}\n\n"
            task = await asyncio.to_thread(runtime.store.get, task_id)
            if not events and task["status"] in TERMINAL | WAITING:
                yield f"event: settled\ndata: {encoded({'status': task['status'], 'cursor': cursor})}\n\n"
                break
            yield ": keepalive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/tasks/{task_id}/artifacts")
def task_artifacts(task_id: str, request: Request):
    task_for(task_id, request)
    return {"items": get_harness().store.artifacts(task_id)}


@router.get("/tasks/{task_id}/artifacts/{name}")
def get_artifact(task_id: str, name: str, request: Request):
    task_for(task_id, request)
    perform(lambda: tools.ArtifactRead(name=name))
    result = get_harness().store.artifact(task_id, name)
    if not result:
        raise HTTPException(404, "未找到工件")
    return result


@router.get("/tasks/{task_id}/export")
def export_task(task_id: str, request: Request):
    task = task_for(task_id, request)
    store = get_harness().store
    artifacts = [store.artifact(task_id, a["name"]) for a in store.artifacts(task_id)]
    events = store.events(task_id, 0, 10000)
    previous, valid = "0" * 64, True
    for event in events:
        valid = (
            valid
            and event["previous_sha256"] == previous
            and event["sha256"] == digest({k: v for k, v in event.items() if k != "sha256"})
        )
        previous = event["sha256"]
    return {
        "schema": VERSION + ".receipt",
        "task": task,
        "events": events,
        "artifacts": artifacts,
        "integrity": {
            "event_chain_valid": valid,
            "artifact_hashes_valid": all(a["sha256"] == digest(a["content"]) for a in artifacts),
            "notice": "本地一致性校验；不是外部签名或独立不可篡改存证",
        },
    }


@router.get("/tasks/{task_id}/learning-trajectory")
def learning_trajectory(task_id: str, request: Request):
    from app.harness.trajectory import export_trajectory

    return export_trajectory(task_for(task_id, request), get_harness().store)


@router.get("/memory")
def memories(request: Request):
    return {"items": get_harness().store.memories(request_identity(request).actor_id)}


@router.post("/memory", status_code=201)
def save_memory(payload: MemoryRequest, request: Request):
    identity = request_identity(request)
    memory_id = "hm-" + uuid4().hex
    perform(lambda: get_harness().store.save_memory(identity.actor_id, memory_id, payload.text, payload.label))
    return {"id": memory_id, "notice": "仅供当前用户选择启用；模型不会自动保存记忆"}


@router.delete("/memory/{memory_id}")
def delete_memory(memory_id: str, request: Request):
    if not get_harness().store.delete_memory(request_identity(request).actor_id, memory_id):
        raise HTTPException(404, "未找到当前用户的记忆")
    return {"deleted": True}


@router.post("/mcp")
def mcp(request: Request, payload: dict):
    """Stateless JSON-RPC MCP tool surface: deliberately read-only, normal auth applies."""
    request_id = payload.get("id")
    method, params = payload.get("method"), payload.get("params", {})
    origin = request.headers.get("origin")
    if origin and origin not in settings.cors_origins:
        raise HTTPException(403, "MCP来源不在允许范围")
    if payload.get("jsonrpc") != "2.0" or not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": "Invalid Request"}}
    protocol = request.headers.get("Mcp-Protocol-Version")
    if protocol == "2026-07-28":
        meta = params.get("_meta", {})
        if (
            not isinstance(meta, dict)
            or meta.get("io.modelcontextprotocol/protocolVersion") != protocol
            or request.headers.get("Mcp-Method") != method
            or method == "tools/call"
            and request.headers.get("Mcp-Name") != params.get("name")
        ):
            raise HTTPException(400, "HeaderMismatch：MCP请求头与元数据不一致")
    elif protocol and protocol not in {"2025-06-18", "2025-11-25"}:
        raise HTTPException(400, "不支持该MCP协议版本")
    if method == "notifications/initialized" and request_id is None:
        return Response(status_code=202)
    identity = request_identity(request)
    names = {"knowledge.search", "runtime.snapshot", "calculate", "skill.read", "linked.observe"}
    available = [t for t in tools.catalog(identity.role) if t["name"] in names]
    if method == "initialize":
        requested = params.get("protocolVersion")
        result = {
            "protocolVersion": requested if requested in {"2025-06-18", "2025-11-25"} else "2025-11-25",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "xiaoyi-maritime-harness", "version": "1.0.0"},
            "instructions": "只读港航工具；无生产控制权限。结果来源以原始字段为准。",
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "inputSchema": t["parameters"],
                    "annotations": {"readOnlyHint": True},
                }
                for t in available
            ]
        }
    elif method == "tools/call":
        name = params.get("name")
        if name not in {t["name"] for t in available}:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Tool not allowed"}}
        transient = {
            "actor_id": identity.actor_id,
            "actor_role": identity.role,
            "allowed_tools": [t["name"] for t in available],
        }
        try:
            result_value = tools.execute(name, params.get("arguments", {}), transient, get_harness().store)
            result = {"content": [{"type": "text", "text": encoded(result_value)}], "isError": False}
        except Exception as exc:
            result = {"content": [{"type": "text", "text": tools.safe_error(exc)}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


@router.post("/evaluation")
def evaluation(request: Request):
    if not has_permission(request_identity(request).role, "evaluation.run"):
        raise HTTPException(403, "当前角色没有评测权限")
    from app.harness.evaluation import run_evaluation

    return run_evaluation()
