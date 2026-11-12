"""Five adapters, a dependency plan and verifiable receipts for federated simulations."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from app.access_control import has_permission
from app.config import BASE_DIR
from app.harness.contracts import StrictModel, digest, encoded, now
from app.harness.store import Conflict
from app.harness.local_lock import ProcessLease
from app.runtime_store import runtime_store

KIND = "harness_joint_mission_v1"
_lock = threading.RLock()
_active: set[str] = set()
_controls: dict[str, dict] = {}
_thread_factory = threading.Thread
_executor_lease = None
TERMINAL = {"completed", "failed", "cancelled", "needs_review", "blocked", "rejected", "budget_exceeded"}
SYSTEMS = ["malacca-sandbox", "sailing-simulator", "port-dt-multi", "energy-cockpit", "mobile-client"]
ROOT = BASE_DIR / ".runtime" / "joint-missions"
with Path(__file__).open("rb") as _source_file:
    _LOADED_SOURCE_SHA256 = hashlib.file_digest(_source_file, "sha256").hexdigest()


class MissionArgs(StrictModel):
    goal: str = Field(
        "联动五系统，完成航行样本验证、港区情景评估和能碳试算，回传移动端。", min_length=2, max_length=2000
    )
    mode: Literal["enterprise", "research"] = "enterprise"
    scenario: Literal["normal", "peak-arrivals", "extreme-weather"] = "normal"
    mutate_sandbox: bool = False
    require_mobile: bool = True
    auto_start: bool = True
    max_seconds: int = Field(360, ge=30, le=7200)
    workflow: Literal["assessment", "full_business"] = "assessment"
    voyage_scenario: Literal[
        "open_water",
        "harbor",
        "auto_berthing",
        "auto_unberthing",
        "narrow_channel_head_on",
        "crossing_starboard",
        "narrow_channel_overtaking",
    ] = "open_water"
    overtaking_agreement_confirmed: bool = False
    business_approval: Literal["human", "role_rehearsal"] = "human"
    experiment_id: str | None = Field(None, pattern=r"^hr-[a-f0-9]{32}$")


class MissionCreate(MissionArgs):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")


class MissionApproval(StrictModel):
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    approve: bool = True


class MobileAck(StrictModel):
    receipt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    client: Literal["flutter-web", "flutter-macos", "flutter-mobile"]


class BusinessApproval(StrictModel):
    bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    slot: Literal["operator", "safety_officer", "role_rehearsal"]
    opinion: str = Field("", max_length=400)
    approve: bool = True


def implementation():
    files = [Path(__file__).with_name(n) for n in ["business.py", "coordination.py", "transport.py"]]
    files += [
        BASE_DIR / "integrations/policy_runtime" / n
        for n in ["contracts.py", "server.py", "action_codec.py", "ortools_multitrip.py"]
    ]
    files += [
        Path(os.getenv("XIAOYI_SAILING_SIMULATOR_ROOT", BASE_DIR.parent / "sailing-simulator")) / "tools/harness_full_voyage.gd",
        Path(os.getenv("XIAOYI_SIMULATOR_ROOT", BASE_DIR.parent / "port-dt-multi")) / "tools/harness_business_worker.py",
    ]
    files += [
        BASE_DIR / "app/linked_agent.py",
        BASE_DIR / "scripts/manage_policy_runtime.py",
        BASE_DIR / "integrations/policy_runtime/requirements.txt",
        BASE_DIR / "integrations/policy_runtime/requirements.lock.txt",
        BASE_DIR / "integrations/policy_runtime/bootstrap.sh",
        BASE_DIR / "integrations/policy_runtime/xiaoyi-policy.service",
        Path(os.getenv("XIAOYI_SIMULATOR_ROOT", BASE_DIR.parent / "port-dt-multi")) / "app/services/harness_event_execution.py",
    ]
    return {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}


def catalog():
    from app import linked_agent_catalog

    return {
        "schema": "xiaoyi-joint-capabilities.v1",
        "systems": SYSTEMS,
        "modes": [{"id": "enterprise", "label": "企业受控模式"}, {"id": "research", "label": "RL策略研究模式"}],
        "actions": linked_agent_catalog.catalog(),
        "mission_actions": [
            "malacca.snapshot",
            "sailing.validate_sample",
            "port.evaluate",
            "energy.compare",
            "mobile.ack",
        ],
        "workflows": ["assessment", "full_business"],
        "policy_runtime": "http://127.0.0.1:11839",
        "production_authority": False,
        "scene_mapping": "federated-port-lab.v1：各源地点和时钟分别保留，经显式敏感性映射形成联合工程场景。",
    }


def _save(job, event, detail=None):
    events = job.setdefault("events", [])
    item = {
        "seq": len(events) + 1,
        "at": now(),
        "event": event,
        "status": job["status"],
        "detail": detail or {},
        "previous_sha256": events[-1]["sha256"] if events else "0" * 64,
    }
    item["sha256"] = digest(item)
    events.append(item)
    job["updated_at"] = now()
    job["version"] = job.get("version", 0) + 1
    runtime_store.save_artifact(KIND, job["id"], job, max_items=200)
    return copy.deepcopy(job)


def get(job_id, actor_id=None, admin=False):
    job = runtime_store.get_artifact(KIND, job_id)
    if not job:
        raise ValueError("联合任务不存在")
    if actor_id is not None and actor_id != job["actor_id"] and not admin:
        raise PermissionError("只能访问自己的联合任务")
    return job


def list_jobs(actor_id, admin=False):
    return runtime_store.list_artifacts(KIND, limit=200, actor_id=None if admin else actor_id)


def create(payload: MissionCreate, identity):
    if not has_permission(identity.role, "operations.manage"):
        raise PermissionError("联合任务需要业务操作权限")
    if payload.mutate_sandbox and any(w in payload.goal for w in ["只读", "不修改", "不调整"]):
        raise ValueError("只读目标与沙盘变更选项冲突")
    if not re.search(r"联合|联动|跨系统|五系统|六系统|情景评估", payload.goal):
        raise ValueError("当前模板执行跨系统联合评估；请明确联合评估目标，单系统动作请使用登记动作工作台")
    if re.search(
        r"(?:真实|实船|现场|生产环境).{0,12}(?:控制|下发|执行)|(?:控制|下发).{0,12}(?:实船|真实设备)", payload.goal
    ):
        raise PermissionError("该能力只接受登记的工程模拟与评估，未获准执行现场控制")
    with _lock:
        for old in list_jobs(identity.actor_id):
            if old["request_id"] == payload.request_id:
                if old["request_sha256"] != digest(payload.model_dump()):
                    raise Conflict("同一联合请求编号不能改变计划")
                return old
        if sum(j["status"] not in TERMINAL for j in list_jobs(identity.actor_id)) >= 10:
            raise Conflict("当前用户已有10个未结束联合任务，请先处理历史任务")
        steps = [
            {"id": "services", "system": "xiaoyi", "label": "检查并按登记配置启动服务", "depends_on": []},
            {"id": "traffic", "system": "malacca-sandbox", "label": "读取交通情景和来源", "depends_on": ["services"]},
            {
                "id": "sailing",
                "system": "sailing-simulator",
                "label": "独立Godot实例验证航行样本",
                "depends_on": ["traffic"],
            },
            {
                "id": "port",
                "system": "port-dt-multi",
                "label": "按航行反馈选择港区情景并计算负荷",
                "depends_on": ["sailing"],
            },
            {
                "id": "energy",
                "system": "energy-cockpit",
                "label": "按港区负荷映射试算参数并比较",
                "depends_on": ["port"],
            },
        ]
        if payload.workflow == "full_business":
            steps[2]["label"] = "原生SAC从起点执行到完整任务终点"
            steps += [
                {"id": sid, "system": system, "label": label, "depends_on": [dependency]}
                for sid, system, label, dependency in [
                    ("transport", "xiaoyi", "预训练运输策略与基线独立约束复核", "energy"),
                    ("coordination", "port-dt-multi", "共同工程时钟与十一资源九阶段协同排程", "transport"),
                    ("business_prepare", "xiaoyi", "生成港区、沙盘、能碳原生业务工作单", "coordination"),
                    ("business_approval", "xiaoyi", "绑定实际工作单的双岗位审批或显式角色演练", "business_prepare"),
                    ("port_execute", "port-dt-multi", "原生V6完整24步港区业务闭环仿真", "business_approval"),
                    ("traffic_execute", "malacca-sandbox", "沙盘原生审批、执行及回执", "port_execute"),
                    ("energy_execute", "energy-cockpit", "能碳原生审批、执行及回执", "traffic_execute"),
                    ("business_verify", "xiaoyi", "重新读取三个系统核验执行状态与轨迹", "energy_execute"),
                    ("business_rollback", "xiaoyi", "逐系统补偿、状态恢复和回滚核验", "business_verify"),
                ]
            ]
        if payload.mode == "research":
            steps.append(
                {"id": "research", "system": "xiaoyi", "label": "核对研究版本并比较RL与基线", "depends_on": ["energy"]}
            )
        if payload.mutate_sandbox:
            steps.append(
                {
                    "id": "restore",
                    "system": "malacca-sandbox",
                    "label": "检查并恢复本任务沙盘配置",
                    "depends_on": ["energy"],
                }
            )
        steps.append(
            {
                "id": "mobile",
                "system": "mobile-client",
                "label": "移动端读取并确认同一任务回执",
                "depends_on": [steps[-1]["id"]],
            }
        )
        config = payload.model_dump(exclude={"request_id"})
        if payload.mode == "research":
            from app.harness.research import CompareArgs, report_for

            verified = report_for(CompareArgs(experiment_id=payload.experiment_id), identity.actor_id)
            config.update(experiment_id=verified["experiment_id"], research_report_sha256=verified["report_sha256"])
        plan = {
            "config": config,
            "steps": steps,
            "task_kind": "federated_joint_assessment.v1",
            "scene_mapping": "federated-port-lab.v1",
            "executor_sha256": _LOADED_SOURCE_SHA256,
            "production_authority": False,
        }
        if payload.workflow == "full_business":
            plan["implementation_sha256"] = implementation()
            plan["task_kind"] = "federated_full_native_simulation_business.v2"
        job = {
            "id": "jm-" + uuid4().hex,
            "actor_id": identity.actor_id,
            "actor_role": identity.role,
            "request_id": payload.request_id,
            "request_sha256": digest(payload.model_dump()),
            "config": config,
            "plan": plan,
            "plan_sha256": digest(plan),
            "expires_epoch": time.time() + 300,
            "status": "waiting_approval",
            "created_at": now(),
            "results": {},
            "events": [],
            "active_step": None,
            "production_authority": False,
            "completed_scope": "交通读取、原生航行样本、港区情景计算、能碳参数比较与客户端回执",
            "notice": "联合评估模板；各源原始时间和地点分别保留。航行仅验证短时样本，不证明完整航次安全或现场供电可行性。",
        }
        if payload.workflow == "full_business":
            job.update(
                completed_scope="完整原生航次、约束运输、工程资源协同、原生港区业务、沙盘及能碳执行核验和补偿、移动端签收",
                notice="完整业务仿真工作流；模拟岗位审批会明确标识。各源地理和时钟保留，统一时钟仅用于声明的工程情景。补偿恢复控制，不倒放既有业务时间或能耗。",
            )
        return _save(job, "mission.created", {"plan_sha256": job["plan_sha256"]})


def approve(job_id, payload: MissionApproval, identity):
    global _executor_lease
    with _lock:
        job = get(job_id, identity.actor_id, identity.role == "admin")
        if not has_permission(identity.role, "operations.manage"):
            raise PermissionError("没有联合任务执行权限")
        if payload.plan_sha256 != job["plan_sha256"] or digest(job["plan"]) != job["plan_sha256"]:
            raise Conflict("审批摘要与计划不一致")
        with Path(__file__).open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != _LOADED_SOURCE_SHA256:
                raise Conflict("执行源码已更新，请重启服务并重新预览计划")
        if job["plan"].get("executor_sha256") != _LOADED_SOURCE_SHA256 or job["config"] != job["plan"]["config"]:
            raise Conflict("计划执行器或参数版本变化，请重新预览")
        if (
            job["plan"].get("implementation_sha256") is not None
            and job["plan"]["implementation_sha256"] != implementation()
        ):
            raise Conflict("联合业务实现或模型契约已更新，请重新生成计划")
        if job["status"] != "waiting_approval":
            if job.get("approved_sha256") == payload.plan_sha256 and payload.approve:
                return job
            raise Conflict("任务已处理，不能重放审批")
        if time.time() > job["expires_epoch"]:
            raise Conflict("计划审批已过期，请重新预览")
        if not payload.approve:
            job["status"] = "rejected"
            return _save(job, "approval.rejected", {"actor": identity.actor_id})
        if _active:
            raise Conflict("另一联合任务正在运行，请在资源释放后执行")
        _executor_lease = ProcessLease(runtime_store.path.with_suffix(".joint.lock")).acquire()
        job.update(
            status="running",
            approved_sha256=payload.plan_sha256,
            started_epoch=time.time(),
            approved_by=identity.actor_id,
            approved_role=identity.role,
        )
        _save(job, "approval.accepted", {"actor": identity.actor_id})
        _active.add(job_id)
        _controls[job_id] = {"cancel": False, "pause": False}
    _thread_factory(target=_run, args=(job_id,), daemon=True, name="harness-joint").start()
    return get(job_id)


def _request(target, method, path, body=None, trace_id=None):
    from app.linked_agent import _request as invoke

    return invoke(target, method, path, body, trace_id=trace_id)


def _sailing(job, stop):
    from app import sailing_simulator_launcher as launcher
    from app.system_linkage import LinkageCommandRequest, _sailing_request

    if job["config"]["scenario"] == "extreme-weather":
        raise ValueError("极端天气尚无匹配的已准入航行样本策略，已暂缓后续联合执行")
    folder = ROOT / job["id"]
    folder.mkdir(parents=True, exist_ok=True)
    request = _sailing_request(
        job["id"],
        LinkageCommandRequest(
            target="sailing-simulator",
            command=job["config"]["goal"],
            parameters={
                "riskEvents": [],
                "targetKnots": 8.0 if job["config"]["scenario"] == "extreme-weather" else 10.0,
            },
        ),
    )
    request["upstream_receipt_sha256"] = job["results"]["traffic"]["sha256"]
    request["attempt_id"] = uuid4().hex
    full = job["config"].get("workflow") == "full_business"
    if full:
        request.update(
            voyage_scenario=job["config"]["voyage_scenario"],
            overtaking_agreement_confirmed=job["config"]["overtaking_agreement_confirmed"],
        )
    request_path = folder / f"sailing-request-{request['attempt_id']}.json"
    result_path = folder / f"sailing-result-{request['attempt_id']}.json"
    request_path.write_text(encoded(request))
    env = os.environ.copy()
    env.update(
        XIAOYI_JOINT_REQUEST=str(request_path),
        XIAOYI_JOINT_RESULT=str(result_path),
        XIAOYI_SIM_BRIDGE_DIR=str(folder / request["attempt_id"]),
    )
    command = [
        str(launcher._GODOT_BINARY),
        "--headless",
        "--fixed-fps",
        "60",
        "--path",
        str(launcher._SAILING_ROOT),
        "--script",
        "res://tools/harness_full_voyage.gd" if full else "res://tools/harness_joint_validation.gd",
    ]
    if not Path(command[0]).is_file():
        raise ValueError("登记Godot引擎不可用")
    if full:
        with _lock:
            current = get(job["id"])
            current["voyage_progress_path"] = str(result_path) + ".progress.json"
            _save(current, "voyage.attempt", {"request_sha256": digest(request), "attempt_id": request["attempt_id"]})
    started = time.monotonic()
    with (folder / "sailing.log").open("a") as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                if stop():
                    process.terminate()
                    raise InterruptedError("航行样本到达停止边界")
                if time.monotonic() - started > (min(3600, job["config"]["max_seconds"]) if full else 90):
                    process.terminate()
                    raise TimeoutError("原生航行超过本次预算，未视为完成")
                time.sleep(0.2)
            if process.returncode != 0 or not result_path.is_file():
                raise ValueError("Godot未返回有效结果；详见本任务sailing.log")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
    raw = json.loads(result_path.read_text())
    if raw.get("requestId") != job["id"] or raw.get("source_request_sha256") != digest(request):
        raise ValueError("航行回执未绑定本次请求")
    if raw.get("production_authority") is not False or not raw.get("scene_loaded"):
        raise ValueError("航行回执缺少场景或隔离边界")
    result = raw["validation"]
    if not result.get("safePass") or result.get("collisionCount", 0) or result.get("groundingCount", 0):
        raise ValueError("航行样本验证未通过，已停止依赖步骤")
    if full:
        trace = Path(str(result_path) + ".trace.ndjson")
        if (
            raw.get("schema") != "xiaoyi-godot-full-voyage.v1"
            or result.get("reachedDestination") is not True
            or raw.get("trajectory_teleporting") is not False
        ):
            raise ValueError("完整航次缺少正常到达终点的原生判定")
        if (
            raw.get("trace_path") != str(trace)
            or not trace.is_file()
            or hashlib.sha256(trace.read_bytes()).hexdigest() != raw.get("trace_sha256")
        ):
            raise ValueError("完整航次状态动作轨迹摘要错误")
        return {
            "source": "Godot/main.tscn/MissionRLController",
            "raw": raw,
            "scope": "正常准入控制器完整起终点航次，原有物理步进；未观测的搁浅字段保留空值，非实船准入",
        }
    return {
        "source": "Godot/main.tscn/MissionRLController",
        "raw": raw,
        "scope": "复用已准入开放水域SAC的短时原生样本；未推演真实马六甲航次、搁浅或到港延误",
    }


def _perform(step, job, stop):
    from app import linked_agent, system_linkage

    config = job["config"]
    if config.get("workflow") == "full_business" and job["plan"].get("implementation_sha256") != implementation():
        raise ValueError("联合业务实现版本变化，停止后续步骤并保留已执行回执")
    if step == "services":
        if config.get("workflow") == "full_business":
            from app.harness import transport

            transport.ensure_running() if config["auto_start"] else transport.health()
        if config["mode"] == "research":
            from app.harness.research import CompareArgs, report_for

            verified = report_for(CompareArgs(experiment_id=config["experiment_id"]), job["actor_id"])
            if verified["report_sha256"] != config["research_report_sha256"]:
                raise ValueError("审批后研究证据版本发生变化")
        runtimes = {}
        for target in ["port-dt-multi", "energy-cockpit", "malacca-sandbox"]:
            if stop():
                raise InterruptedError("任务取消")
            state = (
                system_linkage._ensure_running(target, 45) if config["auto_start"] else system_linkage._runtime(target)
            )
            if not state.get("running"):
                raise ValueError(target + "未就绪")
            runtimes[target] = state
        return {"runtimes": runtimes, "source": "registered_launchers", "production_authority": False}
    if step == "traffic":
        before = linked_agent._observe("malacca-sandbox")
        raw = _request("malacca-sandbox", "GET", "/api/operations/snapshot", trace_id=job["id"])
        if config["mutate_sandbox"]:
            with _lock:
                current = get(job["id"])
                current.setdefault("write_intents", {})["traffic"] = {
                    "before": before,
                    "requested_scenario": config["scenario"],
                    "at": now(),
                }
                _save(current, "write.intent", {"step": "traffic", "scenario": config["scenario"]})
            response = _request(
                "malacca-sandbox",
                "POST",
                "/api/operations/scenarios",
                {"scenario": config["scenario"]},
                trace_id=job["id"],
            )
            after = linked_agent._observe("malacca-sandbox")
            if after["config"]["scenario"] != config["scenario"]:
                raise ValueError("沙盘未确认采用请求情景")
            raw = _request("malacca-sandbox", "GET", "/api/operations/snapshot", trace_id=job["id"])
            return {
                "before": before,
                "after": after,
                "raw": raw,
                "operation": response,
                "source": "/api/operations/scenarios",
                "production_authority": False,
            }
        return {
            "before": before,
            "after": before,
            "raw": raw,
            "source": "/api/operations/snapshot",
            "production_authority": False,
        }
    if step == "sailing":
        return _sailing(job, stop)
    if step == "port":
        sailing = job["results"]["sailing"]["data"]["raw"]["validation"]
        delay = sailing.get("delayDeltaMinutes") if sailing.get("delay_observed") else None
        delay_source = "native_sailing_observation"
        if delay is None:
            delay = job["results"]["traffic"]["data"]["raw"].get("kpis", {}).get("delay_minutes")
            delay_source = "malacca_aggregate_simulation_delay_proxy"
        if delay is not None and (not isinstance(delay, (float, int)) or not math.isfinite(delay) or delay < 0):
            raise ValueError("交通延误指标不符合有限非负分钟契约")
        scenario = (
            "typhoon_closure"
            if config["scenario"] == "extreme-weather"
            else (
                "channel_congestion"
                if config["scenario"] == "peak-arrivals" or delay is not None and delay > 5
                else "strategy"
            )
        )
        raw = _request(
            "port-dt-multi",
            "GET",
            f"/api/v3/runtime/series?scenario={scenario}&horizon_min=60&step_min=15",
            trace_id=job["id"],
        )
        values = [float(p["kW"]) for p in raw.get("series", {}).get("p50", [])]
        if raw.get("production_authority") is not False or not values or not all(math.isfinite(v) for v in values):
            raise ValueError("港区评估结果不满足数据契约")
        return {
            "raw": raw,
            "peak_kw": max(values),
            "scenario": scenario,
            "unit": "kW",
            "input_binding": {
                "sailing_receipt": job["results"]["sailing"]["sha256"],
                "delay_delta_minutes": delay,
                "delay_source": delay_source,
                "traffic_receipt": job["results"]["traffic"]["sha256"],
                "mapping": "declared_peak_or_simulation_delay_gt_5min_to_congestion.v1",
            },
            "scope": "显式情景敏感性映射；非同一物理港口的现场因果预测",
            "production_authority": False,
        }
    if step == "energy":
        port = job["results"]["port"]["data"]
        preference = round(min(0.95, max(0.5, 0.5 + port["peak_kw"] / 100000)), 4)
        results = []
        for value in [0.5, preference]:
            raw = _request(
                "energy-cockpit",
                "POST",
                "/api/optimization/recompute",
                {"green_preference": value, "carbon_price_cny_per_ton": 85},
                trace_id=job["id"],
            )
            compact = system_linkage._compact_energy(raw)
            if compact.get("production_dispatch_enabled") is not False or raw.get("green_preference") != value:
                raise ValueError("能碳试算未确认采用参数或隔离边界")
            results.append({"parameters": {"green_preference": value}, "summary": compact, "raw_sha256": digest(raw)})
        if (
            not results[0]["summary"].get("dataset_sha256")
            or results[0]["summary"]["dataset_sha256"] != results[1]["summary"]["dataset_sha256"]
        ):
            raise ValueError("两次能碳试算数据版本不一致")
        return {
            "baseline": results[0],
            "candidate": results[1],
            "production_authority": False,
            "input_binding": {
                "port_receipt": job["results"]["port"]["sha256"],
                "peak_kw": port["peak_kw"],
                "mapping": "preference=clip(0.5+peak_kw/100000,0.5,0.95).v1",
            },
            "scope": "公开离线数据集上的参数比较；未改变能碳运行控制，也未证明港区供电可行性",
        }
    if step == "transport":
        from app.harness.transport import fixture, compare

        case = fixture(
            seed=44001,
            heterogeneous=config["mode"] == "research",
            source_receipts={s: job["results"][s]["sha256"] for s in ["sailing", "traffic", "port", "energy"]},
        )
        if config["mode"] == "research":
            case = case.model_copy(update={"allow_refill": True})
        return compare(case, include_pretrained=True, allow_pretrained_selection=config["mode"] == "research")
    if step == "coordination":
        from app.harness.coordination import bundle

        payload = bundle(job)
        raw = _request("port-dt-multi", "POST", "/api/v3/end-to-end-coordination/run", payload, trace_id=job["id"])
        if not raw.get("valid") or raw.get("evidence", {}).get("coordination_status") != "pass":
            raise ValueError("跨资源排程未通过原生容量、交接、截止和冻结门禁")
        return {
            "raw": raw,
            "shared_engineering_clock": payload["planning"],
            "site_id": payload["site_id"],
            "native_arrival_seconds": job["results"]["sailing"]["data"]["raw"]["validation"][
                "simulatedDurationSeconds"
            ],
            "traffic_and_energy_source_clocks_preserved": True,
            "second_chain_is_declared_background_demand": True,
            "production_authority": False,
        }
    if step == "business_prepare":
        from app.harness.business import prepare

        return prepare(job)
    if step in {"port_execute", "traffic_execute", "energy_execute"}:
        from app.harness.business import execute

        return execute(job, step.removesuffix("_execute"))
    if step == "business_verify":
        from app.harness.business import verify

        return verify(job)
    if step == "business_rollback":
        from app.harness.business import rollback

        return rollback(job)
    if step == "research":
        from app.harness.research import CompareArgs, report_for

        return report_for(CompareArgs(experiment_id=config["experiment_id"]), job["actor_id"])
    if step == "restore":
        return _restore(job)
    raise ValueError("未登记的联合步骤")


def _restore(job):
    from app.linked_agent import _observe

    evidence = job["results"].get("traffic", {}).get("data", {})
    if not evidence.get("operation"):
        return {"status": "not_changed"}
    before, after = evidence["before"]["config"], evidence["after"]["config"]
    current = _observe("malacca-sandbox")["config"]
    if current != after:
        raise ValueError("沙盘配置已被其他操作改变，未覆盖并发修改")
    response = _request(
        "malacca-sandbox", "POST", "/api/operations/scenarios", {"scenario": before["scenario"]}, trace_id=job["id"]
    )
    actual = _observe("malacca-sandbox")["config"]
    if actual["scenario"] != before["scenario"]:
        raise ValueError("恢复未获得目标回写确认")
    return {
        "status": "restored",
        "response_sha256": digest(response),
        "before": before,
        "actual": actual,
        "notice": "只恢复情景配置，不倒放业务时间",
    }


def _run(job_id):
    try:
        job = get(job_id)
        for definition in job["plan"]["steps"]:
            step = definition["id"]
            with _lock:
                job = get(job_id)
                if job["status"] != "running":
                    return
                flags = _controls[job_id]
                if flags["cancel"] or flags["pause"]:
                    job["status"] = "cancelled" if flags["cancel"] else "paused"
                    _save(job, "mission." + job["status"])
                    return
                if job.get("active_seconds", 0) + time.time() - job["started_epoch"] >= job["config"]["max_seconds"]:
                    job["status"] = "budget_exceeded"
                    _save(job, "mission.budget_exceeded")
                    return
                if step in job["results"]:
                    continue
                if any(dep not in job["results"] for dep in definition["depends_on"]):
                    raise ValueError("前置步骤未完成")
                job["active_step"] = step
                if step == "business_approval":
                    job["business_approval_sha256"] = digest(
                        {
                            "mission_id": job_id,
                            "plan_sha256": job["plan_sha256"],
                            "prepared": job["results"]["business_prepare"]["sha256"],
                            "transport": job["results"]["transport"]["sha256"],
                            "coordination": job["results"]["coordination"]["sha256"],
                        }
                    )
                    job["status"] = "waiting_business_approval"
                    return _save(
                        job,
                        "business.approval_required",
                        {
                            "bundle_sha256": job["business_approval_sha256"],
                            "approvals_simulated": job["config"]["business_approval"] == "role_rehearsal",
                        },
                    )
                if step == "mobile":
                    evidence = {k: v["sha256"] for k, v in job["results"].items()}
                    job["delivery_sha256"] = digest(
                        {"mission_id": job_id, "plan_sha256": job["plan_sha256"], "results": evidence}
                    )
                    job["status"] = "waiting_mobile" if job["config"]["require_mobile"] else "partial"
                    return _save(
                        job,
                        "mobile.delivery_ready",
                        {"sha256": job["delivery_sha256"], "mobile_required": job["config"]["require_mobile"]},
                    )
                _save(job, "step.started", {"step": step})

            def stopped():
                flags = _controls.get(job_id, {"cancel": True})
                return (
                    flags.get("cancel", False)
                    or flags.get("pause", False)
                    or job.get("active_seconds", 0) + time.time() - job["started_epoch"] > job["config"]["max_seconds"]
                )

            result = _perform(step, job, stopped)
            with _lock:
                job = get(job_id)
                job["results"][step] = {"at": now(), "sha256": digest(result), "data": result}
                _save(job, "step.completed", {"step": step, "sha256": digest(result)})
    except Exception as exc:
        with _lock:
            job = get(job_id)
            has_unknown_write = (job.get("active_step") == "traffic" and job["config"]["mutate_sandbox"]) or any(
                v.get("status") == "intent" for v in job.get("business_operations", {}).values()
            )
            status = "blocked"
            if has_unknown_write:
                status = "needs_review"
            elif isinstance(exc, InterruptedError):
                flags = _controls.get(job_id, {})
                status = "cancelled" if flags.get("cancel") else "paused" if flags.get("pause") else "budget_exceeded"
            job.update(status=status, error=str(exc)[:800])
            _save(job, "mission." + job["status"], {"error": job["error"]})
    finally:
        with _lock:
            job = get(job_id)
            job["active_seconds"] = round(job.get("active_seconds", 0) + time.time() - job["started_epoch"], 3)
            _save(job, "usage.updated")
            if (
                job["status"] not in {"waiting_business_approval", "paused", "running"}
                and any(
                    job.get("business_operations", {}).get(t + ".execute", {}).get("status") == "confirmed"
                    for t in ["port", "energy", "traffic"]
                )
                and "business_rollback" not in job["results"]
            ):
                try:
                    from app.harness.business import rollback

                    result = rollback(job)
                    job = get(job_id)
                    job["results"]["business_rollback"] = {"at": now(), "sha256": digest(result), "data": result}
                    _save(job, "business.compensation_completed")
                except Exception as exc:
                    job = get(job_id)
                    job.update(status="needs_review", compensation_error=str(exc)[:500])
                    _save(job, "business.compensation_failed")
            if job["config"]["mutate_sandbox"] and "traffic" in job["results"] and "restore" not in job["results"]:
                try:
                    result = _restore(job)
                    job["results"]["restore"] = {"at": now(), "sha256": digest(result), "data": result}
                    _save(job, "compensation.completed")
                except Exception as exc:
                    job.update(status="needs_review", compensation_error=str(exc)[:500])
                    _save(job, "compensation.failed")
            _active.discard(job_id)
            _controls.pop(job_id, None)
            if _executor_lease is not None:
                _executor_lease.release()


def control(job_id, command, identity):
    global _executor_lease
    with _lock:
        job = get(job_id, identity.actor_id, identity.role == "admin")
        if not has_permission(identity.role, "operations.manage"):
            raise PermissionError("没有操作权限")
        if command not in {"cancel", "pause", "resume"}:
            raise ValueError("未知控制命令")
        if command == "resume":
            if job["status"] != "paused" or _active:
                raise Conflict("仅能恢复已暂停任务，且需等待资源释放")
            if (
                job["plan"].get("implementation_sha256") is not None
                and job["plan"]["implementation_sha256"] != implementation()
            ):
                raise Conflict("实现版本改变，请重新预览计划")
            _executor_lease = ProcessLease(runtime_store.path.with_suffix(".joint.lock")).acquire()
            job.update(status="running", started_epoch=time.time())
            job.pop("error", None)
            _save(job, "mission.resumed", {"actor": identity.actor_id})
            _active.add(job_id)
            _controls[job_id] = {"cancel": False, "pause": False}
            _thread_factory(target=_run, args=(job_id,), daemon=True).start()
        elif job_id in _controls:
            _controls[job_id][command] = True
            _save(job, "control." + command, {"actor": identity.actor_id})
        elif job["status"] not in TERMINAL:
            job["status"] = "cancelled" if command == "cancel" else "paused"
            _save(job, "mission." + job["status"])
            needs_compensation = (
                command == "cancel"
                and "business_rollback" not in job["results"]
                and any(
                    job.get("business_operations", {}).get(target + ".execute", {}).get("status") == "confirmed"
                    for target in ["port", "traffic", "energy"]
                )
            )
            if needs_compensation:
                try:
                    return compensate(job_id, identity)
                except Exception as exc:
                    current = get(job_id)
                    current.update(status="needs_review", compensation_error=str(exc)[:500])
                    return _save(current, "business.cancel_compensation_needs_review")
        return get(job_id)


def acknowledge(job_id, payload: MobileAck, identity):
    with _lock:
        job = get(job_id, identity.actor_id, identity.role == "admin")
        if not has_permission(identity.role, "operations.manage"):
            raise PermissionError("没有移动端任务签收权限")
        if payload.receipt_sha256 != job.get("delivery_sha256"):
            raise Conflict("移动端读取的回执与当前任务结果不一致")
        if job["status"] == "completed":
            return job
        if job["status"] != "waiting_mobile":
            raise Conflict("当前任务不处于移动端待签收状态")
        result = {
            "client": payload.client,
            "actor_id": identity.actor_id,
            "received_at": now(),
            "receipt_sha256": payload.receipt_sha256,
            "actor_authenticated": identity.authenticated,
            "authentication_status": identity.authentication_status,
            "notice": ("记录已认证身份的客户端签收" if identity.authenticated else "记录本地未认证身份的客户端签收")
            + "，不证明物理设备执行",
        }
        job["results"]["mobile"] = {"sha256": digest(result), "at": now(), "data": result}
        job.update(status="completed", finished_at=now(), active_step=None)
        return _save(job, "mission.completed", result)


def export(job):
    previous, valid = "0" * 64, True
    for event in job["events"]:
        valid = (
            valid
            and event["previous_sha256"] == previous
            and event["sha256"] == digest({k: v for k, v in event.items() if k != "sha256"})
        )
        previous = event["sha256"]
    return {
        "mission": job,
        "integrity": {
            "event_chain_valid": valid,
            "result_hashes_valid": all(r["sha256"] == digest(r["data"]) for r in job["results"].values()),
            "business_operation_hashes_valid": all(
                v.get("result_sha256") == digest(v["result"])
                for v in job.get("business_operations", {}).values()
                if v.get("status") == "confirmed"
            ),
            "notice": "本地一致性校验，不是外部签名",
        },
    }


def recover():
    with _lock:
        if _active:
            return
        lease = _executor_lease
        try:
            if lease is None or lease.handle is None:
                lease = ProcessLease(runtime_store.path.with_suffix(".joint.lock")).acquire()
        except Conflict:
            return
        try:
            for job in runtime_store.list_artifacts(KIND, limit=200):
                if job["status"] == "running":
                    job.update(status="needs_review", error="服务重启；核查已有回执后另建任务，未自动重放步骤")
                    _save(job, "recovery.needs_review")
        finally:
            lease.release()


def reconcile(job_id, identity):
    from app.linked_agent import _observe

    with _lock:
        job = get(job_id, identity.actor_id, identity.role == "admin")
        if not has_permission(identity.role, "operations.manage"):
            raise PermissionError("没有核查权限")
        if job["status"] != "needs_review":
            raise Conflict("当前任务不需要未决操作核查")
    observed = _observe("malacca-sandbox")
    with _lock:
        job = get(job_id)
        result = {
            "observed": observed,
            "write_intents": job.get("write_intents", {}),
            "notice": "只读核查，未重放写入或推断未知操作归属；恢复需另行审阅登记动作。",
        }
        job["reconciliation"] = result
        return _save(job, "reconciliation.observed", {"sha256": digest(result)})


def approve_business(job_id, payload: BusinessApproval, identity):
    global _executor_lease
    with _lock:
        job = get(job_id)
        if not has_permission(identity.role, "operations.manage"):
            raise PermissionError("缺少业务审批权限")
        if job["status"] != "waiting_business_approval" or payload.bundle_sha256 != job.get("business_approval_sha256"):
            raise Conflict("当前业务计划或审批摘要不匹配")
        if job["plan"].get("implementation_sha256") != implementation():
            raise Conflict("审批后实现版本变化，需重新预览")
        prepared = job["results"]["business_prepare"]["data"]
        if time.time() - prepared["prepared_epoch"] > prepared["expires_seconds"]:
            raise Conflict("业务计划已过期，请重新生成快照和计划")
        if not payload.approve:
            job.update(status="rejected")
            return _save(job, "business.approval_rejected", {"actor": identity.actor_id})
        approvals = job.setdefault("business_approvals", [])
        if payload.slot == "role_rehearsal":
            if job["config"]["business_approval"] != "role_rehearsal" or identity.actor_id != job["actor_id"]:
                raise PermissionError("只有显式模拟岗位演练任务的创建者可以确认角色演练")
            approvals[:] = [
                {
                    "actor_id": "simulation:" + job_id + ":" + slot,
                    "slot": slot,
                    "simulated": True,
                    "confirmed_by": identity.actor_id,
                }
                for slot in ["operator", "safety_officer"]
            ]
        else:
            if (
                job["config"]["business_approval"] != "human"
                or identity.actor_id == job["actor_id"]
                or not identity.authenticated
                or identity.authentication_status in {"auth_disabled", "local_development"}
            ):
                raise PermissionError("真实岗位审批要求独立的已认证用户；不能由申请人或模拟角色替代")
            if payload.slot == "safety_officer" and identity.role != "admin":
                raise PermissionError("安全复核岗位需要管理员权限")
            if any(a["actor_id"] == identity.actor_id or a["slot"] == payload.slot for a in approvals):
                raise Conflict("岗位与审批人必须分别互异")
            approvals.append({"actor_id": identity.actor_id, "slot": payload.slot, "simulated": False, "at": now(),
                              "opinion": payload.opinion.strip()})
        if len(approvals) < 2:
            return _save(job, "business.approval_recorded", {"actor": identity.actor_id, "slot": payload.slot})
        if _active:
            raise Conflict("其他联合任务占用执行资源，请在释放后重新确认")
        _executor_lease = ProcessLease(runtime_store.path.with_suffix(".joint.lock")).acquire()
        result = {
            "bundle_sha256": payload.bundle_sha256,
            "approvals": approvals,
            "approvals_simulated": payload.slot == "role_rehearsal",
        }
        job["results"]["business_approval"] = {"at": now(), "sha256": digest(result), "data": result}
        job.update(status="running", started_epoch=time.time())
        _save(job, "business.approved", result)
        _active.add(job_id)
        _controls[job_id] = {"cancel": False, "pause": False}
    _thread_factory(target=_run, args=(job_id,), daemon=True, name="harness-joint-business").start()
    return get(job_id)


def compensate(job_id, identity):
    with _lock:
        job = get(job_id, identity.actor_id, identity.role == "admin")
        if not has_permission(identity.role, "operations.manage") or job["status"] not in {
            "needs_review",
            "blocked",
            "cancelled",
        }:
            raise Conflict("仅能补偿已停止且需要核查的任务")
        if _active:
            raise Conflict("执行资源尚未释放")
        integrity = export(job)["integrity"]
        if not all(
            integrity[k] for k in ["result_hashes_valid", "business_operation_hashes_valid", "event_chain_valid"]
        ):
            raise Conflict("结果、操作回执或事件摘要校验失败，不能自动补偿")
        if any(v.get("status") == "intent" for v in job.get("business_operations", {}).values()):
            raise Conflict("仍有写入结果未知，需要先人工核查；不自动重放")
        lease = ProcessLease(runtime_store.path.with_suffix(".joint.lock")).acquire()
        try:
            from app.harness.business import rollback

            result = rollback(job)
            current = get(job_id)
            current["results"]["business_rollback"] = {"at": now(), "sha256": digest(result), "data": result}
            current.pop("compensation_error", None)
            current["status"] = "cancelled"
            return _save(current, "business.manual_compensation_verified", {"actor": identity.actor_id})
        finally:
            lease.release()
