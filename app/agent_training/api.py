"""Authenticated, additive experiment API; no changes to the default 4B model."""

from __future__ import annotations

from dataclasses import asdict
import json
import logging
import os
from pathlib import Path
import re
import threading
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.access_control import has_permission
from app.security import request_identity
from .environment import digest
from .live import ACCEPTANCE_GOAL, JOBS, ROOT, execute_job, local_request, parse_goal, save

router = APIRouter(prefix="/api/harness/agent-rl", tags=["Language-model-RL-experiment"])
EXPERIMENT = Path(
    os.getenv("XIAOYI_AGENT_RL_EXPERIMENT", str(ROOT / ".codex_artifacts/agent-rl-v1-20261101/experiment-003"))
)
LOCK = threading.Lock()
ACTIVE = set()


def load(path, default=None):
    return json.loads(path.read_text()) if path.is_file() else default


def development_progress():
    baseline = load(EXPERIMENT / "evaluations/validation-C_sft.json")
    retention = load(EXPERIMENT / "retention/validation-C_sft.json", {})
    curve = EXPERIMENT / "validation-curve.jsonl"
    rows = []
    if curve.is_file():
        # A concurrent append may expose an incomplete last line. Completed
        # records are still shown; no pending point is invented.
        for line in curve.read_text().splitlines(keepends=True):
            if line.endswith("\n") and line.strip():
                rows.append(json.loads(line))
    refinement = EXPERIMENT / "selection-refinement.jsonl"
    completed = {(r["phase"], r["step"]) for r in rows}
    if refinement.is_file():
        for line in refinement.read_text().splitlines(keepends=True):
            if not line.endswith("\n") or not line.strip():
                continue
            record = json.loads(line)
            if record.get("eligible") is False and (record["group"], record["step"]) not in completed:
                rows.append(
                    {
                        "phase": record["group"],
                        "step": record["step"],
                        "successes": None,
                        "mean_reward": None,
                        "retention": record["retention"],
                        "excluded_by_retention": True,
                    }
                )
    return {
        "scope": "开发验证集；用于选模型，不是最终留出测试",
        "baseline": {
            "n": baseline["n"],
            "successes": baseline.get("successes", sum(c["success"] for c in baseline.get("cases", []))),
            "success_rate": baseline["success_rate"],
            "retention_accuracy": retention.get("accuracy"),
            "mean_reward": baseline.get(
                "mean_reward", sum(c["reward"] for c in baseline.get("cases", [])) / baseline["n"]
            ),
        }
        if baseline
        else None,
        "checkpoints": rows,
        "test_opened": (EXPERIMENT / "test-opened.json").exists(),
    }


def actor(request, permission="chat.use"):
    identity = request_identity(request)
    if not has_permission(identity.role, permission):
        raise HTTPException(403, "当前身份没有此实验操作权限")
    return identity


def get_job(job_id, request):
    if not re.fullmatch(r"arj-[a-f0-9]{32}", job_id):
        raise HTTPException(404, "任务不存在")
    job = load(JOBS / job_id / "job.json")
    identity = actor(request)
    if not job:
        raise HTTPException(404, "任务不存在")
    if job["actor_id"] != identity.actor_id and identity.role != "admin":
        raise HTTPException(403, "只能查看自己的任务")
    return job


@router.get("/status")
def status(request: Request):
    actor(request)
    return {
        "experiment": EXPERIMENT.name,
        "status": load(EXPERIMENT / "status.json", {"stage": "not_started"}),
        "config": load(EXPERIMENT / "config.json"),
        "manifest": load(EXPERIMENT / "task-manifest.json"),
        "summary": load(EXPERIMENT / "audited-summary.json"),
        "results_pending_audit": (EXPERIMENT / "summary.json").is_file()
        and not (EXPERIMENT / "audited-summary.json").is_file(),
        "figures_available": (EXPERIMENT / "figures/four-group-comparison.svg").is_file()
        and (EXPERIMENT / "figures/training-and-retention.svg").is_file(),
        "acceptance_goal": ACCEPTANCE_GOAL,
        "model_scope": "本机1.7B受约束工具动作实验；原4B未改动",
        "production_authority": False,
        "development": development_progress(),
    }


@router.get("/model-health")
def model_health(request: Request):
    actor(request)
    try:
        return local_request(os.getenv("AGENT_RL_MODEL_URL", "http://127.0.0.1:18781"), "/health", timeout=3)
    except Exception:
        logging.getLogger(__name__).warning("Experiment model unavailable", exc_info=True)
        return {"available": False, "error": "实验模型服务不可用，请检查本机服务日志"}


class NewJob(BaseModel):
    goal: str = Field(min_length=2, max_length=2000)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")
    group: str = Field(default="D_rl", pattern=r"^(B_base|C_sft|D_rl|E_more_sft)$")
    inject_read_fault: bool = False


@router.post("/tasks", status_code=202)
def create_job(payload: NewJob, request: Request):
    identity = actor(request, "operations.manage")
    summary = load(EXPERIMENT / "summary.json")
    if not summary or not summary.get("rl_parameters_changed"):
        raise HTTPException(409, "训练尚未完成或尚无有效RL参数更新证据")
    try:
        health = local_request(os.getenv("AGENT_RL_MODEL_URL", "http://127.0.0.1:18781"), "/health", timeout=3)
    except Exception as exc:
        raise HTTPException(503, "1.7B实验模型尚未就绪，请先运行实验启动器") from exc
    weight_key = {"B_base": "initial", "C_sft": "sft", "D_rl": "rl", "E_more_sft": "more_sft"}[payload.group]
    expected_weight = summary["weights"].get(weight_key)
    if not expected_weight:
        raise HTTPException(409, "当前实验没有此对照组检查点")
    if health.get("weights", {}).get(payload.group) != expected_weight:
        raise HTTPException(409, "模型服务与选定实验检查点不一致")
    try:
        task = parse_goal(payload.goal, inject_read_fault=payload.inject_read_fault)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    fingerprint = digest(payload.model_dump())
    with LOCK:
        JOBS.mkdir(parents=True, exist_ok=True)
        for path in JOBS.glob("*/job.json"):
            old = load(path)
            if old.get("actor_id") == identity.actor_id and old.get("request_id") == payload.request_id:
                if old.get("request_sha256") != fingerprint:
                    raise HTTPException(409, "同一请求编号不能更换任务内容")
                return old
        if ACTIVE:
            raise HTTPException(409, "本机一次运行一个语言模型实验任务，请等待当前任务完成")
        job = {
            "id": "arj-" + uuid4().hex,
            "actor_id": identity.actor_id,
            "request_id": payload.request_id,
            "request_sha256": fingerprint,
            "goal": payload.goal,
            "task": asdict(task),
            "group": payload.group,
            "status": "queued",
            "success": False,
            "steps": [],
            "experiment": EXPERIMENT.name,
            "fault_injection_requested": payload.inject_read_fault,
            "production_authority": False,
            "expected_adapter_sha256": expected_weight,
            **({"environment": summary["environment"]} if summary.get("environment") else {}),
        }
        save(JOBS / job["id"] / "job.json", job)
        ACTIVE.add(job["id"])

    def work():
        try:
            execute_job(job)
        finally:
            with LOCK:
                ACTIVE.discard(job["id"])

    threading.Thread(target=work, name="agent-rl-native-task", daemon=True).start()
    return job


@router.get("/tasks/{job_id}")
def read_job(job_id: str, request: Request):
    return get_job(job_id, request)


@router.get("/tasks/{job_id}/files/{filename}")
def job_file(job_id: str, filename: str, request: Request):
    get_job(job_id, request)
    if not re.fullmatch(r"(?:report\.(?:json|html)|job\.json|evidence-\d{3}\.json)", filename):
        raise HTTPException(404, "文件不存在")
    path = JOBS / job_id / filename
    if not path.is_file():
        raise HTTPException(404, "文件尚未生成")
    return FileResponse(path)


@router.get("/figures/{filename}")
def figure(filename: str, request: Request):
    actor(request)
    files = {
        name + "." + extension: EXPERIMENT / "figures" / (name + "." + extension)
        for name in ("four-group-comparison", "reward-trajectories", "training-and-retention",
                     "optimization-details", "retention-checks")
        for extension in ("svg", "png", "pdf")
    }
    if filename not in files:
        raise HTTPException(404, "图表不存在")
    path = files[filename].resolve()
    if not path.is_relative_to((EXPERIMENT / "figures").resolve()):
        raise HTTPException(404, "图表不存在")
    if not path.is_file():
        raise HTTPException(404, "实测图表尚未生成")
    return FileResponse(path)
