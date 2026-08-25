from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import BASE_DIR
from app.rl_lab.algorithms import ALL_ALGORITHM_IDS, algorithm_catalog
from app.rl_lab.datasets import DatasetError, dataset_catalog
from app.rl_lab.service import RunConflict, RunNotFound, rl_lab_service


router = APIRouter(prefix="/api/rl-mission", tags=["小懿RL训练工作流"])

MISSION_COMMAND = (
    "使用公开能源时序数据启动四种强化学习算法和PID控制基线的公平训练，训练时不渲染，"
    "训练完成后再用未参与训练的测试集渲染策略效果。"
)


class MissionPayload(BaseModel):
    mission_id: str = Field(default_factory=lambda: f"rlm-{uuid4().hex[:10]}")
    command: str = MISSION_COMMAND
    run_id: Optional[str] = None
    dataset_id: str = "uci_appliances_energy"
    algorithms: list[str] = Field(default_factory=lambda: list(ALL_ALGORITHM_IDS))
    episodes: int = Field(160, ge=10, le=5000)
    horizon_steps: int = Field(72, ge=12, le=576)
    seed: int = Field(240520, ge=0)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run_or_404(run_id: Optional[str]) -> dict[str, Any]:
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id is required")
    try:
        return rl_lab_service.get_run(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"unknown run_id: {run_id}") from exc


@router.get("/health")
def mission_health() -> dict[str, Any]:
    datasets = [item.public_dict() for item in dataset_catalog().values()]
    public_ready = any(item["available"] for item in datasets)
    systems = {
        "xiaoyi": {
            "id": "xiaoyi",
            "label": "小懿AI",
            "online": True,
            "mode": "local-orchestrator",
        },
        "dataset": {
            "id": "dataset",
            "label": "真实公开数据",
            "online": public_ready,
            "mode": "public-dataset" if public_ready else "missing",
        },
        "trainer": {
            "id": "trainer",
            "label": "本地RL训练器",
            "online": True,
            "mode": "cpu-tabular-rl",
        },
        "guardrail": {
            "id": "guardrail",
            "label": "测试隔离门禁",
            "online": True,
            "mode": "train-no-render/test-render-only",
        },
    }
    return {
        "updated_at": _now(),
        "systems": systems,
        "online_count": sum(bool(item["online"]) for item in systems.values()),
        "total": len(systems),
        "algorithms": algorithm_catalog(),
        "datasets": datasets,
        "production_write_enabled": False,
        "execution_boundary": "训练只读训练集且不渲染；训练结束后测试接口才读取保留测试集并生成轨迹。",
    }


@router.post("/scenario")
def build_scenario(payload: MissionPayload) -> dict[str, Any]:
    definitions = dataset_catalog()
    definition = definitions.get(payload.dataset_id)
    if definition is None:
        raise HTTPException(status_code=422, detail=f"unknown dataset_id: {payload.dataset_id}")
    try:
        dataset = definition.public_dict()
    except DatasetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    port_operations = dataset.get("environment_type") == "port_operations"
    site_data = dataset.get("source_type") == "site_csv"
    if site_data:
        data_notice = "当前使用部署方登记的站点数据；训练仍保持只读、分段与数据哈希审计。"
    elif port_operations:
        data_notice = (
            "当前使用公开港区船舶自动识别系统交通观测；船舶数量、类型和航速为实测，"
            "服务量、积压、等待和容量利用率为校准仿真输出，不是码头生产实绩。"
        )
    else:
        data_notice = (
            "默认数据是知识共享署名许可的真实建筑能源公开基准，不是港口实绩；"
            "站点部署只需用统一时序数据契约替换配置路径。"
        )
    return {
        "mission_id": payload.mission_id,
        "updated_at": _now(),
        "scenario": {
            "id": (
                "measured-port-operations-coordination"
                if port_operations
                else "measured-energy-storage-scheduling"
            ),
            "label": (
                "公开港区交通观测驱动的作业协同"
                if port_operations
                else "真实时序数据驱动的能源调度"
            ),
            "horizon_steps": payload.horizon_steps,
            "dataset_id": payload.dataset_id,
            "algorithm_count": len(payload.algorithms),
            "render_during_training": False,
            "render_after_training": True,
        },
        "dataset": dataset,
        "config": {
            "algorithms": payload.algorithms,
            "episodes": payload.episodes,
            "horizon_steps": payload.horizon_steps,
            "seed": payload.seed,
            "split": "70% train / 15% validation / 15% untouched test",
        },
        "data_notice": data_notice,
    }


@router.post("/train", status_code=202)
def start_training(payload: MissionPayload) -> dict[str, Any]:
    try:
        run = rl_lab_service.start_run(
            {
                "dataset_id": payload.dataset_id,
                "algorithms": payload.algorithms,
                "episodes": payload.episodes,
                "horizon_steps": payload.horizon_steps,
                "seed": payload.seed,
            }
        )
    except (DatasetError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"mission_id": payload.mission_id, "updated_at": _now(), **run}


@router.get("/training/{run_id}")
def training_status(run_id: str) -> dict[str, Any]:
    return _run_or_404(run_id)


@router.post("/training-replay")
def training_compatibility(payload: MissionPayload) -> dict[str, Any]:
    """Compatibility route that returns real run state and never replays a fake curve."""
    if not payload.run_id:
        raise HTTPException(
            status_code=409,
            detail="历史曲线加速回放已停用；请先调用 /api/rl-mission/train 创建真实训练任务。",
        )
    run = _run_or_404(payload.run_id)
    return {
        "mission_id": payload.mission_id,
        "updated_at": _now(),
        "run_id": payload.run_id,
        "status": run["status"],
        "progress_percent": run["progress_percent"],
        "training": run["training"],
        "display_mode": "real-training-metrics",
        "rendering_performed": False,
        "notice": "返回真实训练指标；训练阶段没有环境渲染或加速回放。",
    }


@router.post("/simulate")
def evaluate_strategies(payload: MissionPayload) -> dict[str, Any]:
    _run_or_404(payload.run_id)
    try:
        evaluation = rl_lab_service.evaluate_run(payload.run_id or "")
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    results = evaluation["results"]
    environment_type = str(evaluation.get("environment_type") or "energy_storage")
    labels = {item["id"]: item["label"] for item in algorithm_catalog()}
    race: list[dict[str, Any]] = []
    for result in results:
        metrics = result["metrics"]
        item = {
            "id": result["algorithm_id"],
            "label": labels.get(result["algorithm_id"], result["algorithm_id"]),
            "score": metrics["score"],
            "constraint_violations": metrics["constraint_violations"],
            "environment_type": environment_type,
            "metric_boundary": metrics.get("metric_boundary"),
        }
        if environment_type == "port_operations":
            item.update(
                {
                    "served_units": metrics["served_units"],
                    "average_backlog_units": metrics["average_backlog_units"],
                    "wait_proxy_hours": metrics["wait_proxy_hours"],
                    "capacity_utilization_percent": metrics[
                        "capacity_utilization_percent"
                    ],
                    "terminal_backlog_units": metrics["terminal_backlog_units"],
                }
            )
        else:
            item.update(
                {
                    "cost_saving_percent": metrics["cost_saving_percent"],
                    "peak_reduction_percent": metrics["peak_reduction_percent"],
                }
            )
        race.append(item)
    return {
        "mission_id": payload.mission_id,
        "updated_at": _now(),
        "run_id": payload.run_id,
        "evaluation_id": evaluation["evaluation_id"],
        "best_algorithm_id": evaluation["best_algorithm_id"],
        "environment_type": environment_type,
        "results": results,
        "race": race,
        "rendering_performed": True,
        "render_split": "test",
        "notice": evaluation["notice"],
    }


@router.post("/verify")
def verify_policy(payload: MissionPayload) -> dict[str, Any]:
    run = _run_or_404(payload.run_id)
    evaluation = run.get("test_evaluation") or {}
    checks = [
        {
            "name": "训练阶段禁止渲染",
            "passed": run["training"]["rendering_performed"] is False,
            "detail": "render_mode=None",
        },
        {
            "name": "测试集训练隔离",
            "passed": run["reproducibility"]["test_rows_touched_during_training"] is False,
            "detail": "chronological holdout",
        },
        {
            "name": "六种候选与基线完整",
            "passed": set(run["config"]["algorithms"]) == set(ALL_ALGORITHM_IDS),
            "detail": "4 RL + PID + SOP规则",
        },
        {
            "name": "模型与数据哈希",
            "passed": all(item.get("artifact_sha256") for item in run["training"]["algorithms"].values()),
            "detail": run["reproducibility"]["dataset_sha256"],
        },
        {
            "name": "测试轨迹已生成",
            "passed": bool(evaluation.get("rendering_performed")),
            "detail": evaluation.get("evaluation_id") or "not evaluated",
        },
        {
            "name": "生产写入锁",
            "passed": True,
            "detail": "local evaluation only",
        },
    ]
    return {
        "mission_id": payload.mission_id,
        "updated_at": _now(),
        "run_id": payload.run_id,
        "ok": all(item["passed"] for item in checks),
        "status": "verified" if all(item["passed"] for item in checks) else "blocked",
        "checks": checks,
        "passed": sum(bool(item["passed"]) for item in checks),
        "total": len(checks),
        "production_write_enabled": False,
    }


@router.post("/dispatch")
def dispatch_dry_run(payload: MissionPayload) -> dict[str, Any]:
    verified = verify_policy(payload)
    if not verified["ok"]:
        raise HTTPException(status_code=409, detail="训练/测试证据未通过验证，不能归档Dry-run")
    run = _run_or_404(payload.run_id)
    receipt = {
        "mission_id": payload.mission_id,
        "run_id": payload.run_id,
        "evaluation_id": run["test_evaluation"]["evaluation_id"],
        "recorded_at": _now(),
        "status": "dry_run_recorded",
        "production_executed": False,
        "operator_confirmation_scope": "current evaluation receipt only",
    }
    path = Path(run["artifact_root"]) / "dry_run_receipt.json"
    absolute = BASE_DIR / path
    absolute.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        **receipt,
        "systems_completed": 1,
        "systems_total": 1,
        "artifact": str(path),
        "audit_notice": "仅归档本地测试结果，没有调用TOS、EMS、PLC、AGV控制器或任何生产写接口。",
    }
