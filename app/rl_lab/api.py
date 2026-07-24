from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.rl_lab.algorithms import ALL_ALGORITHM_IDS, algorithm_catalog
from app.rl_lab.datasets import DatasetError, dataset_catalog
from app.rl_lab.service import RunConflict, RunNotFound, rl_lab_service


router = APIRouter(prefix="/api/rl-lab", tags=["可复现RL训练实验室"])


class TrainRunRequest(BaseModel):
    dataset_id: str = "uci_appliances_energy"
    algorithms: list[str] = Field(default_factory=lambda: list(ALL_ALGORITHM_IDS))
    episodes: int = Field(160, ge=10, le=5000)
    horizon_steps: int = Field(72, ge=12, le=576)
    seed: int = Field(240520, ge=0, le=2_147_483_647)
    train_ratio: float = Field(0.70, ge=0.50, le=0.85)
    validation_ratio: float = Field(0.15, ge=0.05, le=0.25)
    learning_rate: float = Field(0.12, gt=0.0, le=1.0)
    discount_factor: float = Field(0.97, ge=0.0, le=1.0)
    epsilon_start: float = Field(1.0, gt=0.0, le=1.0)
    epsilon_end: float = Field(0.05, ge=0.0, lt=1.0)

    @model_validator(mode="after")
    def validate_split_and_exploration(self) -> "TrainRunRequest":
        if self.train_ratio + self.validation_ratio > 0.95:
            raise ValueError("at least 5% of rows must remain untouched for testing")
        if self.epsilon_end >= self.epsilon_start:
            raise ValueError("epsilon_end must be smaller than epsilon_start")
        return self


class EvaluationRequest(BaseModel):
    algorithms: Optional[list[str]] = None


@router.get("/health")
def rl_lab_health() -> dict[str, object]:
    datasets = [item.public_dict() for item in dataset_catalog().values()]
    return {
        "status": "ready" if any(item["available"] for item in datasets) else "dataset_required",
        "engine": "xiaoyi-reproducible-tabular-rl",
        "algorithms": algorithm_catalog(),
        "algorithm_count": len(ALL_ALGORITHM_IDS),
        "datasets": datasets,
        "training_render_mode": None,
        "test_render_mode": "trace",
        "execution_boundary": "训练和测试均为本地计算；测试轨迹只在训练完成后生成；不向生产设备写入。",
    }


@router.get("/algorithms")
def list_algorithms() -> dict[str, object]:
    return {
        "items": algorithm_catalog(),
        "count": len(ALL_ALGORITHM_IDS),
        "comparison_rule": "四种RL算法与PID控制基线共享数据划分、时域、环境参数和评估种子。",
    }


@router.get("/datasets")
def list_datasets() -> dict[str, object]:
    items = [item.public_dict() for item in dataset_catalog().values()]
    return {
        "items": items,
        "count": len(items),
        "available": sum(bool(item["available"]) for item in items),
        "port_dataset_count": sum(bool(item["port_data"]) for item in items),
        "contract": {
            "required": ["timestamp", "load_kw"],
            "optional": [
                "temperature_c", "humidity_percent", "wind_speed_mps", "visibility_km",
                "pressure_hpa", "price_per_kwh", "carbon_kg_per_kwh",
            ],
            "swap_method": "set XIAOYI_RL_DATASET_PATH and optional XIAOYI_RL_DATASET_MAPPING",
        },
    }


@router.post("/runs", status_code=202)
def start_training(request: TrainRunRequest) -> dict[str, object]:
    try:
        return rl_lab_service.start_run(request.model_dump())
    except DatasetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs")
def list_training_runs(limit: int = Query(20, ge=1, le=100)) -> dict[str, object]:
    items = rl_lab_service.list_runs(limit)
    return {"items": items, "count": len(items)}


@router.get("/runs/{run_id}")
def get_training_run(run_id: str) -> dict[str, object]:
    try:
        return rl_lab_service.get_run(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"unknown run_id: {run_id}") from exc


@router.post("/runs/{run_id}/cancel", status_code=202)
def cancel_training_run(run_id: str) -> dict[str, object]:
    try:
        return rl_lab_service.cancel_run(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"unknown run_id: {run_id}") from exc
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/runs/{run_id}/evaluate")
def evaluate_training_run(run_id: str, request: EvaluationRequest) -> dict[str, object]:
    try:
        return rl_lab_service.evaluate_run(run_id, algorithms=request.algorithms)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=f"unknown run_id: {run_id}") from exc
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (DatasetError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
