"""Approved local simulation transactions with durable per-operation checkpoints."""

from __future__ import annotations
import json
import subprocess
import time
import hashlib
from pathlib import Path
import os
from app.config import BASE_DIR
from app.harness.contracts import digest, encoded, now
from app.harness.store import Conflict

PORT = Path(os.getenv("XIAOYI_SIMULATOR_ROOT", BASE_DIR.parent / "port-dt-multi"))


def _call(job, target, method, path, body=None, key=None):
    from app.linked_agent import _request

    return _request(target, method, path, body, trace_id=job["id"], idempotency_key=key)


def operation(job, key, fn):
    from app.harness import joint

    with joint._lock:
        current = joint.get(job["id"])
        ops = current.setdefault("business_operations", {})
        if key in ops:
            if ops[key]["status"] == "confirmed":
                if ops[key].get("result_sha256") != digest(ops[key]["result"]):
                    raise Conflict("业务操作回执摘要错误，禁止重用: " + key)
                return ops[key]["result"]
            raise Conflict("未决业务写入必须先核查，禁止自动重放: " + key)
        ops[key] = {"status": "intent", "at": now()}
        joint._save(current, "business.write_intent", {"operation": key})
    result = fn()
    with joint._lock:
        current = joint.get(job["id"])
        current["business_operations"][key].update(
            status="confirmed", result=result, result_sha256=digest(result), confirmed_at=now()
        )
        joint._save(current, "business.receipt", {"operation": key, "sha256": digest(result)})
    return result


def port_worker(job, action, approvers=None):
    folder = BASE_DIR / ".runtime/joint-missions" / job["id"]
    folder.mkdir(parents=True, exist_ok=True)
    if action == "prepare":
        selected = job["results"]["transport"]["data"]["selected"]["validation"]
        request = {
            "workorder_dir": str(PORT / ".runtime/harness-workorders" / job["id"]),
            "active_transport_vehicles": selected["vehicles_used"],
            "upstream": {
                k: job["results"][k]["sha256"] for k in ["sailing", "traffic", "port", "transport", "coordination"]
            },
            "resource_schedule": {
                "candidate_plan": job["results"]["coordination"]["data"]["raw"]["evidence"]["candidate_plan"],
                "resources": job["results"]["coordination"]["data"]["raw"]["evidence"]["planning_input"]["resources"],
                "epoch": job["results"]["coordination"]["data"]["shared_engineering_clock"]["horizon_start"],
                "native_arrival_seconds": job["results"]["coordination"]["data"]["native_arrival_seconds"],
            },
        }
    else:
        prepared = job["results"]["business_prepare"]["data"]["port"]
        request = dict(prepared["worker_request"])
        request["plan_sha256"] = prepared["plan_sha256"]
    request["action"] = action
    if action == "execute":
        request.update(
            approved_by=approvers, approvals_simulated=job["config"]["business_approval"] == "role_rehearsal"
        )
    request_path = folder / f"port-{action}-request.json"
    output = folder / f"port-{action}-result.json"
    request_path.write_text(encoded(request))
    with (folder / f"port-{action}.log").open("a") as log:
        process = subprocess.run(
            [
                os.getenv("XIAOYI_SIMULATOR_PYTHON", str(PORT / ".venv312/bin/python")),
                str(PORT / "tools/harness_business_worker.py"),
                "--request",
                str(request_path),
                "--result",
                str(output),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
    if process.returncode or not output.is_file():
        raise ValueError("原生港区业务仿真未返回成功回执，详见port-" + action + ".log")
    result = json.loads(output.read_text())
    if action == "prepare":
        result["worker_request"] = {k: v for k, v in request.items() if k != "action"}
    return result


def prepare(job):
    port = operation(job, "port.prepare", lambda: port_worker(job, "prepare"))
    energy = operation(
        job,
        "energy.prepare",
        lambda: _call(
            job,
            "energy-cockpit",
            "POST",
            "/api/runtime/decisions",
            {
                "objective": "peak" if port["plan"]["predicted_native_totals"]["peak_kw"] > 3500 else "balanced",
                "idempotency_key": job["id"] + "-energy-prepare",
                "requested_by": job["actor_id"],
            },
        ),
    )
    traffic = operation(
        job,
        "traffic.prepare",
        lambda: _call(job, "malacca-sandbox", "POST", "/api/operations/decisions", {"controller_id": "port-sop"}),
    )
    if not energy.get("decision_id") or not traffic.get("decision_id"):
        raise ValueError("原生业务计划缺少ID")
    return {
        "port": port,
        "energy": energy,
        "traffic": traffic,
        "prepared_epoch": time.time(),
        "expires_seconds": 300,
        "simulation_only": True,
        "production_authority": False,
        "approvals_simulated": job["config"]["business_approval"] == "role_rehearsal",
        "coupling": {
            "transport_to_port": "independently validated active vehicle count -> native V6 horizontal transport control",
            "port_to_energy": "source-pinned native V6 24-step preview peak kW -> native MPC peak/balanced objective; verified against execution; original EMS load source retained",
            "source_clocks": "preserved; common event clock belongs to declared engineering resource plan",
        },
    }


def approved_actors(job):
    approval = job["results"]["business_approval"]["data"]
    if (
        approval["bundle_sha256"] != job["business_approval_sha256"]
        or len({r["actor_id"] for r in approval["approvals"]}) < 2
    ):
        raise ValueError("业务计划缺少绑定的双岗位审批")
    return [r["actor_id"] for r in approval["approvals"]]


def execute(job, target):
    actors = approved_actors(job)
    prepared = job["results"]["business_prepare"]["data"]
    if time.time() - prepared["prepared_epoch"] > prepared["expires_seconds"]:
        raise ValueError("业务审批超过5分钟，需重新生成快照和计划")
    if target == "port":
        result = operation(job, "port.execute", lambda: port_worker(job, "execute", actors))
        if (
            result["status"] != "executed_simulation"
            or result["steps"] != 24
            or result.get("forecast_matches_execution") is not True
            or result.get("resource_event_execution", {}).get("tasks_completed") != 18
        ):
            raise ValueError("港区业务执行未完成")
        return result
    decision = prepared["energy" if target == "energy" else "traffic"]
    identifier = decision["decision_id"]
    if target == "energy":
        for index, actor in enumerate(actors):
            # Respect the original native number of required approvals.
            if index >= decision["required_approvals"]:
                break
            operation(
                job,
                f"energy.approve.{index}",
                lambda actor=actor, index=index: _call(
                    job,
                    "energy-cockpit",
                    "POST",
                    f"/api/runtime/decisions/{identifier}/approve",
                    {
                        "approver_id": actor,
                        "decision": "approve",
                        "comment": "Harness simulation approval; real/simulated identity classification retained in joint receipt",
                        "idempotency_key": job["id"] + f"-energy-approve-{index}",
                    },
                ),
            )
        result = operation(
            job,
            "energy.execute",
            lambda: _call(
                job,
                "energy-cockpit",
                "POST",
                f"/api/runtime/decisions/{identifier}/execute",
                {"idempotency_key": job["id"] + "-energy-execute", "executor_id": job["actor_id"]},
            ),
        )
        if (
            result.get("status") != "executed_simulation"
            or result.get("execution_receipt", {}).get("status") != "acknowledged"
        ):
            raise ValueError("能碳执行缺少确认回执")
    else:
        operation(
            job,
            "traffic.approve",
            lambda: _call(
                job,
                "malacca-sandbox",
                "POST",
                f"/api/operations/decisions/{identifier}/approve",
                {
                    "approvers": [
                        {"approver_id": actor, "role": role}
                        for actor, role in zip(actors, ["operator", "safety_officer"])
                    ]
                },
            ),
        )
        result = operation(
            job,
            "traffic.execute",
            lambda: _call(
                job,
                "malacca-sandbox",
                "POST",
                f"/api/operations/decisions/{identifier}/execute",
                {},
                job["id"] + "-traffic-execute",
            ),
        )
        if (
            result.get("decision", {}).get("status") != "executed"
            or result["decision"].get("receipt", {}).get("status") != "acknowledged"
        ):
            raise ValueError("沙盘执行缺少确认回执")
    return {
        "native": result,
        "approvals_simulated": job["config"]["business_approval"] == "role_rehearsal",
        "production_authority": False,
    }


def verify(job):
    prepared = job["results"]["business_prepare"]["data"]
    energy = _call(job, "energy-cockpit", "GET", "/api/runtime/decisions/" + prepared["energy"]["decision_id"])
    traffic = _call(job, "malacca-sandbox", "GET", "/api/operations/decisions/" + prepared["traffic"]["decision_id"])
    port = job["results"]["port_execute"]["data"]
    trace = Path(port["trace_path"])
    if (
        energy["status"] != "executed_simulation"
        or traffic["status"] != "executed"
        or hashlib.sha256(trace.read_bytes()).hexdigest() != port["trace_sha256"]
    ):
        raise ValueError("原生执行状态或港区轨迹复核失败")
    return {
        "status": "verified",
        "energy": energy,
        "traffic": traffic,
        "port_trace_sha256": port["trace_sha256"],
        "resource_event_execution": port["resource_event_execution"],
        "forecast_matches_execution": port["forecast_matches_execution"],
        "native_remaining_backlogs": {
            k: v for k, v in port["native_totals"].items() if "end_" in k or k.endswith("_end")
        },
        "native_business_coverage": [
            "pilotage",
            "towage",
            "berth_service",
            "quay_crane",
            "horizontal_transport",
            "yard_crane",
            "gate",
            "rail",
            "barge",
            "reefer",
            "shore_power",
            "maintenance",
        ],
        "scope": "numerical simulation effects and acknowledged native control receipts; no real customs release or field equipment actuation",
        "production_authority": False,
    }


def rollback(job):
    """Compensate only acknowledged writes. Unknown writes remain needs_review."""
    from app.harness import joint

    current = joint.get(job["id"])
    ops = current.get("business_operations", {})
    result = {}
    prepared = current.get("results", {}).get("business_prepare", {}).get("data", {})
    for target in ["energy", "traffic", "port"]:
        execution = ops.get(target + ".execute", {})
        if execution.get("status") != "confirmed":
            continue
        if target == "port":
            result[target] = operation(current, "port.rollback", lambda: port_worker(current, "rollback"))
            if result[target]["restored_initial_state"] is not True:
                raise ValueError("港区工作单没有恢复初始状态")
        elif target == "energy":
            identifier = prepared["energy"]["decision_id"]
            current_decisions = _call(current, "energy-cockpit", "GET", "/api/runtime/decisions?limit=200").get(
                "items", []
            )
            own = execution["result"]
            own_time = own.get("execution_receipt", {}).get("executed_at", "")
            if any(
                d["decision_id"] != identifier and (d.get("execution_receipt") or {}).get("executed_at", "") > own_time
                for d in current_decisions
            ):
                raise Conflict("能碳已有其他后续执行，不能覆盖其控制；请人工核查补偿")
            result[target] = operation(
                current,
                "energy.rollback",
                lambda: _call(
                    current,
                    "energy-cockpit",
                    "POST",
                    f"/api/runtime/decisions/{identifier}/rollback",
                    {
                        "idempotency_key": job["id"] + "-energy-rollback",
                        "requested_by": job["actor_id"],
                        "reason": "Harness演练结束，恢复原生执行前控制，保留全部执行回执",
                    },
                ),
            )
            if result[target]["status"] != "rolled_back_simulation":
                raise ValueError("能碳回滚未确认")
        else:
            identifier = prepared["traffic"]["decision_id"]
            decisions = _call(current, "malacca-sandbox", "GET", "/api/operations/decisions").get("decisions", [])
            own_time = execution["result"].get("decision", {}).get("receipt", {}).get("executed_at", "")
            if any(
                d["decision_id"] != identifier and (d.get("receipt") or {}).get("executed_at", "") > own_time
                for d in decisions
            ):
                raise Conflict("沙盘已有其他后续执行，不能覆盖其控制；请人工核查补偿")
            result[target] = operation(
                current,
                "traffic.rollback",
                lambda: _call(
                    current,
                    "malacca-sandbox",
                    "POST",
                    f"/api/operations/decisions/{identifier}/rollback",
                    {"reason": "Harness演练结束，恢复原生hold-plan并保留时间和审计"},
                ),
            )
            if result[target]["status"] != "rolled_back":
                raise ValueError("沙盘回滚未确认")
    return {
        "status": "compensated",
        "results": result,
        "notice": "恢复控制与独立仿真状态，已消耗能量、已流逝时钟和既有业务历史不倒放；未决写入仍需核查",
        "production_authority": False,
    }
