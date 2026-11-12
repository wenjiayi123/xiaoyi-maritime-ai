"""Authenticated specialist work orders running on the existing Harness."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
import threading

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from app.access_control import has_permission
from app.config import BASE_DIR
from app.harness import model, tools
from app.harness.contracts import CreateTask, InputRequest, StrictModel, digest
from app.harness.local_lock import ProcessLease
from app.harness.store import Conflict
from app.policy_release import PolicySelection
from app.security import request_identity
from app.specialist_orders import EvidenceError, journal, register, run_order, save
from app.specialist_planner import ROLES, WorkstationModel, available_roles

router = APIRouter(prefix="/api/harness/work-orders", tags=["港航专业岗位工单"])
logger = logging.getLogger(__name__)


class OrderRequest(StrictModel):
    request_id: str = Field(min_length=4, max_length=70, pattern=r"^[A-Za-z0-9_-]+$")
    goal: str = Field(min_length=2, max_length=1200)
    selection: PolicySelection | None = None
    use_memory: bool = False


class Revision(StrictModel):
    reason: str = Field(min_length=2, max_length=360)


class BoundHarness:
    """Use the requesting user's existing role and serve only that user's task artifacts."""

    policy_binding = True

    def __init__(self, identity):
        from app.harness.api import get_harness

        self.identity = identity
        self.actor = identity.actor_id
        self.harness = get_harness()
        self.tools = {
            t["name"]
            for t in tools.catalog(identity.role)
            if not t["requires_approval"]
        }

    def create(self, payload):
        return self.harness.create(CreateTask.model_validate(payload), self.identity)

    def task(self, tid):
        row = self.harness.store.get(tid)
        if not row or row["actor_id"] != self.actor:
            raise PermissionError("岗位工件不属于当前用户")
        return row

    def original(self, tid, record):
        self.task(tid)
        row = self.harness.store.artifact(tid, record["artifact"])
        if (
            not row
            or digest(row["content"]) != row["sha256"]
            or row["sha256"] != record["sha256"]
        ):
            raise EvidenceError("岗位工件的校验值不匹配")
        return json.loads(row["content"])

    def events(self, tid):
        self.task(tid)
        return self.harness.store.events(tid)

    def figure(self, title, window):
        from app.visual_evidence import search_figures

        return search_figures(title, window)


def root():
    return Path(
        os.getenv(
            "XIAOYI_WORKORDER_DIR", str(BASE_DIR / ".runtime" / "specialist-orders")
        )
    )


def principal(request):
    identity = request_identity(request)
    if not has_permission(identity.role, "chat.use"):
        raise HTTPException(403, "当前用户没有工单权限")
    return identity


def lookup(key, identity):
    try:
        path = journal(root(), identity.actor_id, key)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not path.is_file():
        raise HTTPException(404, "未找到当前用户的工单")
    state = json.loads(path.read_bytes())
    if state["actor"] != identity.actor_id or state["key"] != key:
        raise HTTPException(409, "工单身份校验失败")
    return state


def make_model():
    config = model.configuration()
    if not config["local"] or not config["available"]:
        raise ValueError("专业工单需要已配置的本机模型")
    return WorkstationModel(config["base"])


class OrderWorkers:
    def __init__(self):
        self.pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="port-workorder"
        )
        self.lock = threading.Lock()
        self.active = set()
        self.stopping = threading.Event()

    def submit(self, identity, state, reason=None):
        key = (identity.actor_id, state["key"])
        with self.lock:
            if key in self.active:
                return
            if self.stopping.is_set():
                raise HTTPException(503, "服务正在关闭，工单已保存")
            self.active.add(key)
            self.pool.submit(self.work, identity, state["key"], reason)

    def work(self, identity, key, reason):
        location = root()
        try:
            if self.stopping.is_set():
                return
            gw = BoundHarness(identity)
            run_order(
                location,
                gw,
                make_model(),
                key,
                retry_reason=reason,
                stopping=self.stopping,
                notify=lambda msg: logger.info("workorder %s %s", key, msg),
            )
        except Conflict:
            # A different process already owns this same durable work order.
            pass
        except Exception as exc:
            logger.exception("Specialist work order interrupted")
            path = journal(location, identity.actor_id, key)
            try:
                lease = ProcessLease(path.with_suffix(".lock")).acquire()
            except Conflict:
                return
            try:
                state = json.loads(path.read_bytes())
                if state["status"] not in ("completed", "needs_evidence"):
                    state.update(
                        status="interrupted",
                        last_error=type(exc).__name__ + "；可从已保存的分工继续",
                    )
                    save(path, state)
            finally:
                lease.release()
        finally:
            with self.lock:
                self.active.discard((identity.actor_id, key))


_workers = None
_lock = threading.Lock()


def workers():
    global _workers
    with _lock:
        if _workers is None:
            _workers = OrderWorkers()
        return _workers


def close_workorders():
    global _workers
    with _lock:
        if _workers:
            _workers.stopping.set()
            _workers.pool.shutdown(wait=False, cancel_futures=True)
        _workers = None


@router.get("/catalog")
def catalog(request: Request):
    gw = BoundHarness(principal(request))
    return {
        "roles": [
            {"id": k, "name": ROLES[k][0], "responsibility": ROLES[k][1], "tools": v}
            for k, v in available_roles(gw.tools).items()
        ],
        "production_authority": False,
    }


@router.post("", status_code=202)
def create_order(payload: OrderRequest, request: Request):
    identity = principal(request)
    try:
        path = journal(root(), identity.actor_id, payload.request_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        state = register(
            path,
            identity.actor_id,
            payload.request_id,
            payload.goal,
            payload.selection.model_dump() if payload.selection else None,
            payload.use_memory,
        )
    except (ValueError, Conflict, PermissionError) as exc:
        raise HTTPException(409, str(exc)) from exc
    if state["status"] in ("planning", "running", "suspended", "interrupted"):
        workers().submit(identity, state)
    return state


@router.get("/{key}")
def get_order(key: str, request: Request):
    return lookup(key, principal(request))


@router.post("/{key}/resume", status_code=202)
def resume_order(key: str, request: Request):
    identity = principal(request)
    state = lookup(key, identity)
    if state["status"] not in ("completed", "needs_evidence"):
        workers().submit(identity, state)
    return state


@router.post("/{key}/retry", status_code=202)
def retry_order(key: str, payload: Revision, request: Request):
    identity = principal(request)
    state = lookup(key, identity)
    if state["status"] != "needs_evidence":
        raise HTTPException(409, "工单当前无需重做证据核验")
    workers().submit(identity, state, payload.reason)
    return state


@router.post("/{key}/inputs", status_code=202)
def input_order(key: str, payload: InputRequest, request: Request):
    identity = principal(request)
    state = lookup(key, identity)
    if state["status"] != "waiting_input":
        raise HTTPException(409, "工单当前没有等待补充资料的岗位")
    gw = BoundHarness(identity)
    tid = state["waiting_task"]
    gw.task(tid)
    try:
        gw.harness.input(tid, payload, identity.role, actor_id=identity.actor_id)
    except (ValueError, Conflict) as exc:
        raise HTTPException(409, str(exc)) from exc
    workers().submit(identity, state)
    return state
