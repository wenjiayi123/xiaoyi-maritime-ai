from __future__ import annotations

from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/advanced-rl", tags=["已退役RL展示接口"])


class AdvancedMissionPayload(BaseModel):
    mission_id: str = Field(default_factory=lambda: f"arm-{uuid4().hex[:10]}")
    command: str = ""
    policy_id: Optional[str] = None


@router.get("/health")
def advanced_health() -> dict[str, object]:
    return {
        "status": "retired",
        "online_count": 0,
        "total": 0,
        "production_write_enabled": False,
        "replacement": "/api/rl-lab",
        "reason": (
            "旧版极端天气MAPPO与岸桥-AGV-堆场多智能体页面依赖外部演示接口和公式拼装，"
            "无法在本仓库内证明模型、训练数据与检查点，因此已停止返回算法结果。"
        ),
    }


def _retired() -> None:
    raise HTTPException(
        status_code=410,
        detail=(
            "该展示型RL任务已退役。请使用 /api/rl-lab 创建真实训练任务；"
            "如需MAPPO多智能体能力，必须先接入可复现环境、训练代码、数据集和模型检查点。"
        ),
    )


@router.post("/weather/scenario")
def weather_scenario(payload: AdvancedMissionPayload) -> None:
    _retired()


@router.post("/weather/inference")
def weather_inference(payload: AdvancedMissionPayload) -> None:
    _retired()


@router.post("/weather/benchmark")
def weather_benchmark(payload: AdvancedMissionPayload) -> None:
    _retired()


@router.post("/weather/replay")
def weather_replay(payload: AdvancedMissionPayload) -> None:
    _retired()


@router.post("/weather/verify")
def weather_verify(payload: AdvancedMissionPayload) -> None:
    _retired()


@router.post("/weather/dispatch")
def weather_dispatch(payload: AdvancedMissionPayload) -> None:
    _retired()


@router.post("/marl/scenario")
def marl_scenario(payload: AdvancedMissionPayload) -> None:
    _retired()


@router.post("/marl/coordinate")
def marl_coordinate(payload: AdvancedMissionPayload) -> None:
    _retired()


@router.post("/marl/verify")
def marl_verify(payload: AdvancedMissionPayload) -> None:
    _retired()


@router.post("/marl/dispatch")
def marl_dispatch(payload: AdvancedMissionPayload) -> None:
    _retired()
