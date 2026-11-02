"""Dual-mode APIs share the existing authentication and keep legacy routes intact."""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, HTTPException, Request

from app.access_control import has_permission
from app.config import BASE_DIR
from app.harness import (
    joint,
    research,
    public_port,
    portcall,
    twin_validation,
    crossport,
    portwatch_data,
    multisite_twin,
    adaptive_twin,
    port_readiness,
    remediation_v2,
    remediation_v3,
    remediation_v4,
    research_v6,
    open_models as candidate_models,
)
from app.harness.api import perform
from app.security import request_identity

router = APIRouter(prefix="/api/harness", tags=["双模式Harness与六系统任务"])


def enabled():
    return os.getenv("XIAOYI_DUAL_HARNESS_ENABLED", "true").lower() not in {"0", "false", "off"}


def identity_for(request, permission="chat.use"):
    if not enabled():
        raise HTTPException(503, "双模式扩展已关闭，原有小懿功能保持可用")
    identity = request_identity(request)
    if not has_permission(identity.role, permission):
        raise HTTPException(403, "当前身份缺少所需权限")
    return identity


@router.get("/joint/capabilities")
def capabilities(request: Request):
    identity_for(request)
    return joint.catalog()


@router.get("/assurance/public-data")
def public_data(request: Request):
    identity_for(request)
    return perform(public_port.catalog)


@router.post("/assurance/historical-study")
def historical_study(payload: public_port.ReplayArgs, request: Request):
    identity_for(request)
    return perform(lambda: public_port.replay(payload))


@router.post("/assurance/forecast-validation")
def public_forecast_validation(request: Request):
    identity_for(request)
    return perform(public_port.forecast_validation)


@router.post("/assurance/twin-validation")
def validate_twin(payload: twin_validation.ValidationRequest, request: Request):
    identity_for(request, "rl.manage")
    return perform(lambda: twin_validation.validate(payload))


@router.post("/assurance/portcall-plan")
def plan_portcall(payload: portcall.PlanRequest, request: Request):
    identity_for(request, "operations.manage")
    return perform(lambda: portcall.plan(payload))


@router.get("/assurance/crossport/catalog")
def crossport_catalog(request: Request):
    identity_for(request)
    return portwatch_data.catalog()


@router.get("/assurance/crossport/diagnosis")
def crossport_diagnosis(request: Request):
    identity_for(request)
    return perform(crossport.diagnosis)


@router.post("/assurance/multisite-twin")
def multisite_calibration(request: Request):
    identity_for(request, "rl.manage")
    return perform(multisite_twin.study)


@router.get("/assurance/adaptive-twin")
def adaptive_calibration_report(request: Request):
    identity_for(request)
    return perform(adaptive_twin.report)


@router.get("/assurance/remediation-v2")
def remediation_report(request: Request):
    identity_for(request)
    return perform(remediation_v2.report)


@router.get("/assurance/remediation-v3")
def remediation_latest_report(request: Request):
    identity_for(request)
    return perform(remediation_v3.report)


@router.get("/assurance/remediation-v4")
def remediation_risk_report(request: Request):
    identity_for(request)
    return perform(remediation_v4.report)


@router.get("/assurance/capability-scorecard")
def current_capability_scorecard(request: Request):
    identity_for(request)

    def read():
        data = remediation_v4.report()
        return {**data["scorecard"], "current": data["current"], "production_authority": False}

    return perform(read)


@router.get("/assurance/research-v6")
def latest_research_report(request: Request):
    identity_for(request)
    return perform(research_v6.report)


@router.get("/assurance/crossport/runs")
def crossport_runs(request: Request):
    identity = identity_for(request)
    return {"items": crossport.list_jobs(identity.actor_id, identity.role == "admin")}


@router.post("/assurance/crossport/runs", status_code=202)
def start_crossport(payload: crossport.Start, request: Request):
    identity = identity_for(request, "rl.manage")
    return perform(lambda: crossport.start(payload, identity.actor_id))


@router.get("/assurance/crossport/runs/{job_id}")
def get_crossport(job_id: str, request: Request):
    identity = identity_for(request)
    return perform(lambda: crossport.get(job_id, identity.actor_id, identity.role == "admin"))


@router.get("/assurance/crossport/runs/{job_id}/report")
def report_crossport(job_id: str, request: Request):
    identity = identity_for(request)
    return perform(lambda: crossport.report(job_id, identity.actor_id, identity.role == "admin"))


@router.get("/assurance/crossport/runs/{job_id}/readiness")
def readiness_crossport(job_id: str, request: Request):
    identity = identity_for(request)
    return perform(
        lambda: research_v6.enrich(
            remediation_v4.enrich(
                remediation_v3.enrich(
                    remediation_v2.enrich(port_readiness.assess(job_id, identity.actor_id, identity.role == "admin"))
                )
            )
        )
    )


@router.post("/assurance/crossport/runs/{job_id}/cancel")
def cancel_crossport(job_id: str, request: Request):
    identity = identity_for(request, "rl.manage")
    return perform(lambda: crossport.cancel(job_id, identity.actor_id, identity.role == "admin"))


@router.get("/open-models")
def open_models(request: Request):
    identity_for(request)
    path = BASE_DIR / ".codex_artifacts/joint-harness-20261029/downloads.json"
    items = json.loads(path.read_text()) if path.is_file() else []
    compatibility = BASE_DIR / ".runtime/open-models/compatibility.json"
    return {
        "items": items,
        "compatibility": json.loads(compatibility.read_text()) if compatibility.is_file() else {},
        "planner": candidate_models.planner_status(),
        "registry": candidate_models.registry(),
        "notice": "下载校验与运行准入分别记录；权重文件大小不等于推理内存。",
        "production_authority": False,
    }


@router.post("/open-models/activate")
def activate_model(request: Request):
    identity_for(request, "operations.manage")
    return perform(candidate_models.activate)


@router.post("/joint/missions", status_code=201)
def create_mission(payload: joint.MissionCreate, request: Request):
    identity = identity_for(request, "operations.manage")
    return perform(lambda: joint.create(payload, identity))


@router.get("/joint/missions")
def missions(request: Request):
    identity = identity_for(request)
    return {
        "items": [
            {k: j[k] for k in ["id", "status", "config", "created_at", "updated_at", "version"]}
            for j in joint.list_jobs(identity.actor_id, identity.role == "admin")
        ]
    }


@router.get("/joint/business-review-inbox")
def business_review_inbox(request: Request):
    identity = identity_for(request, "operations.manage")
    items = joint.runtime_store.list_artifacts(joint.KIND, limit=200)
    return {
        "items": [
            {k: j[k] for k in ["id", "status", "actor_id", "config", "business_approval_sha256"]}
            for j in items
            if j["status"] == "waiting_business_approval" and j["config"].get("business_approval") == "human"
        ]
    }


@router.get("/joint/missions/{job_id}")
def mission(job_id: str, request: Request):
    identity = identity_for(request)

    def read():
        job = joint.get(job_id)
        reviewing = job["status"] == "waiting_business_approval" and has_permission(identity.role, "operations.manage")
        if job["actor_id"] != identity.actor_id and identity.role != "admin" and not reviewing:
            raise PermissionError("只能访问自己的联合任务或待审批业务工作单")
        path = job.get("voyage_progress_path")
        if path and job.get("active_step") == "sailing":
            try:
                job["voyage_progress"] = json.loads(__import__("pathlib").Path(path).read_text())
            except (OSError, ValueError):
                pass
        return job

    return perform(read)


@router.post("/joint/missions/{job_id}/approval")
def approve_mission(job_id: str, payload: joint.MissionApproval, request: Request):
    identity = identity_for(request, "operations.manage")
    return perform(lambda: joint.approve(job_id, payload, identity))


@router.post("/joint/missions/{job_id}/business-approval")
def business_approval(job_id: str, payload: joint.BusinessApproval, request: Request):
    identity = identity_for(request, "operations.manage")
    return perform(lambda: joint.approve_business(job_id, payload, identity))


@router.get("/open-models/policy-runtime")
def policy_runtime(request: Request):
    identity_for(request)
    from app.harness import transport

    return perform(transport.health)


@router.post("/joint/missions/{job_id}/control/{command}")
def control_mission(job_id: str, command: str, request: Request):
    identity = identity_for(request, "operations.manage")
    return perform(lambda: joint.control(job_id, command, identity))


@router.post("/joint/missions/{job_id}/mobile-ack")
def mobile_ack(job_id: str, payload: joint.MobileAck, request: Request):
    identity = identity_for(request, "operations.manage")
    return perform(lambda: joint.acknowledge(job_id, payload, identity))


@router.post("/joint/missions/{job_id}/compensate")
def compensate_mission(job_id: str, request: Request):
    identity = identity_for(request, "operations.manage")
    return perform(lambda: joint.compensate(job_id, identity))


@router.post("/joint/missions/{job_id}/reconcile")
def reconcile_mission(job_id: str, request: Request):
    identity = identity_for(request, "operations.manage")
    return perform(lambda: joint.reconcile(job_id, identity))


@router.get("/joint/missions/{job_id}/export")
def export_mission(job_id: str, request: Request):
    identity = identity_for(request)
    return perform(lambda: joint.export(joint.get(job_id, identity.actor_id, identity.role == "admin")))


@router.get("/research/runs")
def experiments(request: Request):
    identity = identity_for(request)
    return {"items": research.list_jobs(identity.actor_id, identity.role == "admin")}


@router.post("/research/runs", status_code=202)
def start_experiment(payload: research.StartExperiment, request: Request):
    identity = identity_for(request, "rl.manage")
    return perform(lambda: research.start(payload, identity.actor_id))


@router.get("/research/runs/{job_id}")
def experiment(job_id: str, request: Request):
    identity = identity_for(request)
    return perform(lambda: research.get(job_id, identity.actor_id, identity.role == "admin"))


@router.post("/research/runs/{job_id}/cancel")
def cancel_experiment(job_id: str, request: Request):
    identity = identity_for(request, "rl.manage")
    return perform(lambda: research.cancel(job_id, identity.actor_id, identity.role == "admin"))


@router.get("/research/runs/{job_id}/report")
def experiment_report(job_id: str, request: Request):
    identity = identity_for(request)

    def read():
        job = research.get(job_id, identity.actor_id, identity.role == "admin")
        if job["status"] != "completed":
            raise ValueError("实验尚未完成")
        path = BASE_DIR / job["report_path"]
        if research.file_sha256(path) != job["report_sha256"]:
            raise ValueError("研究报告哈希不一致")
        report = json.loads(path.read_text())
        try:
            research.report_for(research.CompareArgs(experiment_id=job_id), identity.actor_id, identity.role == "admin")
            report["historical_only"] = False
        except ValueError as exc:
            report.update(historical_only=True, current_validation_notice=str(exc))
        return report

    return perform(read)


@router.post("/research/runs/{job_id}/replay")
def replay_experiment(job_id: str, payload: research.ReplayArgs, request: Request):
    identity = identity_for(request, "rl.manage")
    if payload.experiment_id is not None and payload.experiment_id != job_id:
        raise HTTPException(422, "研究任务编号不一致")
    payload.experiment_id = job_id
    return perform(lambda: research.replay(payload, identity.actor_id, identity.role == "admin"))


def recover():
    if enabled():
        joint.recover()
        research.recover()
        crossport.recover()
