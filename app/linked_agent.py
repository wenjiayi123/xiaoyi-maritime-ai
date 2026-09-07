"""Server-owned, bounded local observation and parameter experiment jobs."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request as HttpRequest, build_opener
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import system_linkage
from app.access_control import has_permission
from app.linked_agent_catalog import ACTIONS, catalog, parse_command
from app.runtime_store import runtime_store
from app.security import request_identity


router = APIRouter(prefix="/api/linked-agent", tags=["联动智能体操作与观测"])
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="linked-agent")
_lock = threading.RLock()
_active: dict[str, str] = {}
_cancel: dict[str, threading.Event] = {}
_KIND = "linked_agent_run_v1"
_PLAN_KIND = "linked_agent_plan_v1"
_LIMIT = 10000


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _can_operate(request: Request) -> None:
    if not has_permission(request_identity(request).role, "operations.manage"):
        raise HTTPException(403, "当前角色不具备联动操作权限")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("登记接口不得重定向到其他地址")


def _request(target: str, method: str, path: str, payload=None) -> dict[str, Any]:
    if target == "energy-cockpit":
        base = system_linkage._ENERGY_API
    else:
        state = system_linkage._runtime(target)
        if not state.get("running"):
            raise ValueError("目标系统未就绪，请先在四系统联动中心启动该系统")
        base = state["url"].rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("只允许登记的本机 HTTP 服务")
    headers = {"Content-Type": "application/json"}
    token_var = {"energy-cockpit": "XIAOYI_ENERGY_API_TOKEN", "malacca-sandbox": "XIAOYI_MALACCA_API_TOKEN", "port-dt-multi": "XIAOYI_PORT_DT_API_TOKEN"}[target]
    token = os.getenv(token_var, "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload, allow_nan=False).encode() if payload is not None else None
    with build_opener(NoRedirect).open(HttpRequest(base.rstrip("/") + path, data=body, method=method, headers=headers), timeout=35) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("目标快照超出读取上限")
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get("available") is False or result.get("ok") is False:
        raise ValueError("目标没有返回可用的业务结果")
    digest(result)  # Reject non-finite upstream JSON before storing/using it.
    return result


def _numeric(values: dict) -> dict[str, float]:
    return {str(k): float(v) for k, v in values.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}


def _observe(target: str) -> dict[str, Any]:
    if target == "sailing-simulator":
        state = system_linkage._runtime(target)
        raw = {"running": bool(state.get("running")), "state": state.get("state"), "isolated": True}
        return {"observed_at": now(), "source_time": None, "metrics": {}, "config": raw, "payload_sha256": digest(raw), "source": "登记进程隔离状态", "production_authority": False}
    paths = {"port-dt-multi": "/api/v3/runtime/frame", "energy-cockpit": "/api/runtime/snapshot", "malacca-sandbox": "/api/operations/snapshot"}
    raw = _request(target, "GET", paths[target])
    if target == "malacca-sandbox":
        authority = raw.get("authority", {})
        if authority.get("simulation_mode") is not True or any(authority.get(k) is not False for k in ["live_data_verified", "dispatch_allowed", "production_authority"]):
            raise ValueError("目标未证明处于隔离的模拟模式")
        sim = raw.get("simulator", {})
        if not isinstance(sim.get("running"), bool) or not raw.get("run_id") or sim.get("scenario") is None:
            raise ValueError("目标模拟配置不完整")
        config = {"scenario": sim["scenario"], "running": sim["running"], "run_id": raw["run_id"]}
        metrics = _numeric(raw.get("kpis", {}))
        source_time = raw.get("event_time")
    elif target == "energy-cockpit":
        if raw.get("production_authority") is not False or raw.get("data_mode") != "public_data_calibrated_realtime_simulation":
            raise ValueError("能碳数据模式未证明为公开数据校准模拟")
        config = {"scenario": raw.get("active_scenario", {}), "state": raw.get("simulator_state")}
        metrics = _numeric(raw.get("kpis", {}).get("current", {}))
        source_time = raw.get("virtual_event_time")
    else:
        if raw.get("production_authority") is not False:
            raise ValueError("数字孪生权限边界缺失")
        config = {"policy_id": raw.get("policy", {}).get("job_id"), "data_mode": raw.get("telemetry", {}).get("mode")}
        metrics = _numeric({"aggregate_kw": raw.get("aggregate_kw")})
        source_time = raw.get("generated_at")
    return {"observed_at": now(), "source_time": source_time, "metrics": metrics, "config": config,
            "payload_sha256": digest(raw), "source": paths[target], "quality": raw.get("quality", {}), "production_authority": False}


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str = Field(min_length=3, max_length=80)
    parameters: dict[str, Any] = Field(default_factory=dict)
    samples: int = Field(3, ge=1, le=12)
    interval_seconds: float = Field(2, ge=1, le=10, allow_inf_nan=False)
    restore_after_observation: bool = True


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")


class CommandRequest(BaseModel):
    command: str = Field(min_length=2, max_length=500)


def _get(kind: str, key: str, request: Request) -> dict:
    item = runtime_store.get_artifact(kind, key)
    if not item:
        raise HTTPException(404, "未找到该操作记录")
    identity = request_identity(request)
    if item["actor_id"] != identity.actor_id and identity.role != "admin":
        raise HTTPException(403, "只能访问自己的操作记录")
    return item


def _save(run: dict, event: str) -> None:
    with _lock:
        previous = run["events"][-1]["sha256"] if run["events"] else "0" * 64
        row = {"event": event, "at": now(), "previous_sha256": previous, "status": run["status"],
               "result_sha256": digest({k: v for k, v in run.items() if k != "events"})}
        row["sha256"] = digest(row)
        run["events"].append(row)
        run["updated_at"] = row["at"]
        runtime_store.save_artifact(_KIND, run["id"], run, max_items=_LIMIT)


@router.get("/catalog")
def action_catalog() -> dict:
    return {"actions": catalog(), "production_authority": False,
            "notice": "本机参数试算、模拟配置调整与观测；不审批或下发真实设备控制。恢复只恢复本轮配置，不倒放业务时间。"}


@router.post("/parse")
def parse_instruction(payload: CommandRequest) -> dict:
    return parse_command(payload.command) or {"clarification": "请指定联动系统与动作，或在操作台选择已登记能力。"}


@router.post("/plans", status_code=201)
def prepare(payload: PlanRequest, request: Request) -> dict:
    _can_operate(request)
    spec = ACTIONS.get(payload.action_id)
    if not spec:
        raise HTTPException(422, "动作未登记")
    try:
        params = spec["model"].model_validate(payload.parameters).model_dump()
        before = _observe(spec["target"])
    except ValidationError as exc:
        raise HTTPException(422, "参数不符合登记范围：" + "; ".join(str(e["msg"]) for e in exc.errors())) from exc
    except Exception as exc:
        raise HTTPException(503, "目标读取失败；请检查运行状态、访问令牌与模拟模式。") from exc
    identity = request_identity(request)
    plan = {"id": f"lap-{uuid4().hex}", "actor_id": identity.actor_id, "actor_role": identity.role,
            "created_at": now(), "action_id": payload.action_id, "label": spec["label"], "target": spec["target"],
            "parameters": params, "samples": payload.samples, "interval_seconds": payload.interval_seconds,
            "restore_after_observation": payload.restore_after_observation, "mutates": bool(spec.get("mutates")),
            "before": before, "production_authority": False, "expires_at_epoch": time.time() + 300}
    plan["plan_sha256"] = digest(plan)
    runtime_store.save_artifact(_PLAN_KIND, plan["id"], plan, max_items=_LIMIT)
    return plan


def _delta(before: dict, after: dict) -> list[dict]:
    return [{"metric": key, "before": value, "after": after[key], "change": round(after[key] - value, 6)} for key, value in before.items() if key in after]


def _apply(plan: dict, run: dict) -> None:
    action, params, target = plan["action_id"], plan["parameters"], plan["target"]
    if action == "energy.compare":
        results = []
        for preference in [params["baseline_green_preference"], params["green_preference"]]:
            raw = _request(target, "POST", "/api/optimization/recompute", {"green_preference": preference, "carbon_price_cny_per_ton": params["carbon_price_cny_per_ton"]})
            if raw.get("green_preference") != preference:
                raise ValueError("目标未回写实际采用的绿色偏好")
            compact = system_linkage._compact_energy(raw)
            if raw.get("carbon_market", {}).get("carbon_price_cny_per_ton") != params["carbon_price_cny_per_ton"]:
                raise ValueError("目标未回写实际采用的试算碳价")
            if compact.get("production_dispatch_enabled") is not False or not compact.get("dataset_id") or not compact.get("dataset_sha256"):
                raise ValueError("试算结果缺少数据来源或生产权限边界")
            if results and any(compact[key] != results[0]["summary"][key] for key in ["dataset_id", "dataset_sha256"]):
                raise ValueError("两次试算的数据集发生变化，不能作为同数据对比")
            results.append({"parameters": {"green_preference": preference, "carbon_price_cny_per_ton": params["carbon_price_cny_per_ton"]}, "summary": compact, "payload_sha256": digest(raw)})
        run["evaluation"] = {"baseline": results[0], "candidate": results[1], "changes": _delta(_numeric(results[0]["summary"]), _numeric(results[1]["summary"])), "scope": "同一公开离线数据集的参数试算；未改变目标驾驶舱的全局参数，运行态观测是另一条数据链。"}
    elif action == "port.evaluate":
        raw = _request(target, "GET", "/api/v3/runtime/series?" + urlencode(params))
        if raw.get("production_authority") is not False:
            raise ValueError("评估结果缺少生产权限边界")
        points = raw.get("series", {}).get("p50", [])
        values = [float(p["kW"]) for p in points]
        if not values:
            raise ValueError("目标没有返回评估序列")
        run["evaluation"] = {"parameters": params, "points": points, "peak_kw": max(values), "average_kw": sum(values) / len(values), "payload_sha256": digest(raw), "scope": "目标系统公开数据模型输出；评估窗口和情景仅作用于本次计算。"}
    elif plan["mutates"]:
        # Persist the write intent before the request: timeout means unknown,
        # never permission to blindly repeat a state-changing operation.
        run["write_attempted"] = True
        _save(run, "write-intent")
        path = "/api/operations/scenarios" if action == "malacca.scenario" else "/api/operations/simulator/control"
        raw = _request(target, "POST", path, params)
        run["operation_receipt_sha256"] = digest(raw)
        expected = copy.deepcopy(plan["before"]["config"])
        if action == "malacca.scenario":
            expected["scenario"] = params["scenario"]
        else:
            expected["running"] = params["action"] == "start"
        run["expected_config"] = expected
        _save(run, "write-receipt")
        after = _observe(target)
        if after["config"] != expected:
            raise ValueError("目标回读配置不符合本轮预期，需核查")
        run["applied"] = True
        run["after_apply"] = after


def _restore(run: dict) -> None:
    plan = run["plan"]
    current = _observe(plan["target"])
    original = plan["before"]["config"]
    if current["config"] == original:
        run["restored"] = True
        run["after_restore"] = current
        return
    if current["config"] != run.get("expected_config"):
        raise ValueError("目标配置已由其他操作改变，停止恢复以免覆盖其他人的调整")
    params = {"scenario": original["scenario"]} if plan["action_id"] == "malacca.scenario" else {"action": "start" if original["running"] else "stop"}
    path = "/api/operations/scenarios" if plan["action_id"] == "malacca.scenario" else "/api/operations/simulator/control"
    raw = _request(plan["target"], "POST", path, params)
    after = _observe(plan["target"])
    if after["config"] != original:
        raise ValueError("恢复后的配置未通过回读核验")
    run.update(restored=True, after_restore=after, restore_receipt_sha256=digest(raw))


def _work(run: dict) -> None:
    plan = run["plan"]
    event = _cancel[run["id"]]
    try:
        current = _observe(plan["target"])
        if plan["mutates"] and current["config"] != plan["before"]["config"]:
            raise ValueError("预览后目标配置发生变化，请重新生成方案")
        if not event.is_set():
            _apply(plan, run)
        _save(run, "operation-finished")
        for index in range(plan["samples"]):
            if event.is_set() or (index and event.wait(plan["interval_seconds"])):
                break
            sample = _observe(plan["target"])
            run["observations"].append(sample)
            run["changes"] = _delta(run["plan"]["before"]["metrics"], sample["metrics"])
            _save(run, "observation")
        if run.get("applied") and plan["restore_after_observation"]:
            _restore(run)
        run["status"] = "cancelled" if event.is_set() else "completed"
    except Exception as exc:
        run["status"] = "needs_review" if run.get("write_attempted") else "failed"
        run["error"] = str(exc) if isinstance(exc, ValueError) else "目标接口异常或权限不足；未自动重试写入，请读取回执核查。"
        if run.get("applied") and plan["restore_after_observation"]:
            try:
                _restore(run)
            except Exception:
                run["restore_error"] = "恢复未核验成功或目标已变化，请人工核查目标配置。"
    finally:
        try:
            _save(run, "finished")
            runtime_store.add_audit(correlation_id=run["id"], actor_id=run["actor_id"], actor_role=run["actor_role"], action="linked_agent.execute", resource=plan["action_id"], risk_level="medium" if plan["mutates"] else "low", outcome=run["status"], request=plan, response=run, detail="本机联动参数与观测任务；真实回执已保存，生产权限关闭。")
        finally:
            with _lock:
                _active.pop(plan["target"], None)
                _cancel.pop(run["id"], None)


@router.post("/plans/{plan_id}/execute", status_code=202)
def execute(plan_id: str, payload: ExecuteRequest, request: Request) -> dict:
    _can_operate(request)
    plan = _get(_PLAN_KIND, plan_id, request)
    identity = request_identity(request)
    run_id = "lar-" + digest([identity.actor_id, payload.request_id])[:32]
    with _lock:
        old = runtime_store.get_artifact(_KIND, run_id)
        if old:
            if old["plan"]["id"] != plan_id or old["plan"]["plan_sha256"] != payload.plan_sha256:
                raise HTTPException(409, "同一请求编号不能用于另一份方案")
            return old
        if payload.plan_sha256 != plan["plan_sha256"] or time.time() > plan["expires_at_epoch"]:
            raise HTTPException(409, "方案已变化或超过五分钟，请重新预览")
        if plan["target"] in _active or len(_active) >= 4:
            raise HTTPException(409, "目标已有任务执行或恢复中，请等待当前任务完成")
        # One accepted execution per prepared plan, even under a new request id.
        if plan.get("run_id"):
            return _get(_KIND, plan["run_id"], request)
        run = {"id": run_id, "actor_id": identity.actor_id, "actor_role": identity.role, "created_at": now(), "status": "running", "plan": plan,
               "observations": [], "events": [], "changes": [], "applied": False, "restored": False,
               "production_authority": False, "comparison_notice": "观测差值包含模拟时间演进，不能单独归因为参数调整。"}
        plan["run_id"] = run_id
        runtime_store.save_artifact(_PLAN_KIND, plan_id, plan, max_items=_LIMIT)
        _active[plan["target"]] = run_id
        _cancel[run_id] = threading.Event()
        _save(run, "accepted")
        _pool.submit(_work, run)
        return copy.deepcopy(run)


@router.get("/runs")
def list_runs(request: Request) -> dict:
    identity = request_identity(request)
    rows = runtime_store.list_artifacts(_KIND, limit=100)
    return {"items": [row for row in rows if identity.role == "admin" or row["actor_id"] == identity.actor_id]}


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict:
    return _get(_KIND, run_id, request)


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, request: Request) -> dict:
    _can_operate(request)
    run = _get(_KIND, run_id, request)
    with _lock:
        event = _cancel.get(run_id)
        if event:
            event.set()
    return {"id": run_id, "cancellation_requested": bool(event), "status": run["status"], "notice": "停止后续观测；当前请求结束后按方案恢复配置。"}


@router.post("/runs/{run_id}/rollback")
def rollback(run_id: str, request: Request) -> dict:
    _can_operate(request)
    run = _get(_KIND, run_id, request)
    target = run["plan"]["target"]
    with _lock:
        if target in _active:
            raise HTTPException(409, "目标仍有任务运行，请先停止并等候任务结束")
        if not run.get("applied"):
            raise HTTPException(409, "本轮未核验配置变更，不能自动恢复")
        if run.get("restored"):
            return run
        _active[target] = run_id
    try:
        _restore(run)
        _save(run, "manual-restore")
        identity = request_identity(request)
        runtime_store.add_audit(correlation_id=run_id, actor_id=identity.actor_id, actor_role=identity.role,
                               action="linked_agent.restore", resource=run["plan"]["action_id"], risk_level="medium",
                               outcome="completed", response=run, detail="恢复本轮配置并通过目标回读核验。")
        return run
    except Exception as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else "恢复请求未完成，请核查目标状态") from exc
    finally:
        with _lock:
            _active.pop(target, None)


# Never resume an uncertain write after a process restart.
for _old in runtime_store.list_artifacts(_KIND, limit=500):
    if _old.get("status") == "running":
        _old["status"] = "needs_review"
        _old["error"] = "执行进程已重启；未自动续执行，请核查目标并按回执恢复。"
        _save(_old, "process-restart")
