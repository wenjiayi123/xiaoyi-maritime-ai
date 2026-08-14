from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.rl_lab.algorithms import ALL_ALGORITHM_IDS, algorithm_catalog
from app.rl_lab.contracts import environment_contract, environment_contract_catalog
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


class AdvisorRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    run_id: Optional[str] = None


def _evidence_report() -> dict[str, Any]:
    reports_dir = Path(__file__).resolve().parents[2] / "reports"
    path = reports_dir / "rl_dataset_benchmark_v2.json"
    legacy_path = reports_dir / "rl_dataset_benchmark_v1.json"
    if not path.is_file() and legacy_path.is_file():
        path = legacy_path
    if not path.is_file():
        return {
            "status": "not_generated",
            "report": None,
            "notice": "尚未生成固定公开数据集对比报告。",
        }
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "invalid",
            "report": None,
            "notice": "证据报告不可读取；请在服务端检查文件权限、JSON格式和审计日志。",
        }
    return {
        "status": "available",
        "report": report,
        "report_path": str(path.relative_to(path.parents[1])),
        "notice": report.get("scope_notice"),
    }


@router.get("/health")
def rl_lab_health() -> dict[str, object]:
    datasets = [item.public_dict() for item in dataset_catalog().values()]
    return {
        "status": "ready" if any(item["available"] for item in datasets) else "dataset_required",
        "engine": "xiaoyi-reproducible-tabular-rl",
        "algorithms": algorithm_catalog(),
        "algorithm_count": len(ALL_ALGORITHM_IDS),
        "datasets": datasets,
        "environment_contracts": environment_contract_catalog(),
        "training_render_mode": None,
        "test_render_mode": "trace",
        "execution_boundary": "训练和测试均为本地计算；测试轨迹只在训练完成后生成；不向生产设备写入。",
    }


@router.get("/algorithms")
def list_algorithms() -> dict[str, object]:
    return {
        "items": algorithm_catalog(),
        "count": len(ALL_ALGORITHM_IDS),
        "comparison_rule": "四种RL算法与PID、现场SOP固定规则两类强基线共享数据划分、时域、环境参数和评估种子。",
        "environment_contracts": environment_contract_catalog(),
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
                "temperature_c",
                "humidity_percent",
                "wind_speed_mps",
                "visibility_km",
                "pressure_hpa",
                "price_per_kwh",
                "carbon_kg_per_kwh",
            ],
            "environment_type": "energy_storage",
        },
        "contracts": {
            item["id"]: {
                "required": item["required_fields"],
                "optional": item["optional_fields"],
                "environment_type": item["environment_type"],
            }
            for item in items
        },
        "swap_method": (
            "set XIAOYI_RL_DATASET_PATH, XIAOYI_RL_ENVIRONMENT_TYPE and optional "
            "XIAOYI_RL_DATASET_MAPPING/XIAOYI_RL_PROFILE_PATH"
        ),
    }


@router.get("/contracts")
def list_environment_contracts() -> dict[str, object]:
    return {
        "items": environment_contract_catalog(),
        "count": len(environment_contract_catalog()),
        "production_boundary": (
            "合同覆盖可执行观测、动作、目标和约束；站点未提供的因素保持缺失或显式默认，"
            "不会伪装为港口实测。"
        ),
    }


@router.get("/evidence")
def get_rl_evidence() -> dict[str, Any]:
    return _evidence_report()


@router.post("/advisor")
def rl_training_advisor(request: AdvisorRequest) -> dict[str, Any]:
    message = request.message.strip()
    compact = message.lower().replace(" ", "")
    run: Optional[dict[str, Any]] = None
    if request.run_id:
        try:
            run = rl_lab_service.get_run(request.run_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail=f"unknown run_id: {request.run_id}") from exc
    else:
        runs = rl_lab_service.list_runs(1)
        run = runs[0] if runs else None

    if any(term in compact for term in ("观测", "动作", "目标函数", "奖励", "约束")):
        environment_type = (
            str(run.get("config", {}).get("environment_type") or "energy_storage")
            if run
            else "port_operations"
        )
        contract = environment_contract(environment_type)
        observations = "、".join(item["id"] for item in contract["observation"])
        actions = "、".join(item["label"] for item in contract["actions"])
        answer = (
            f"可以，先把这次实验的决策语义说清楚。当前环境是“{contract['label']}”。"
            f"观测包含 {observations}；动作是 {actions}。目标按"
            f"“{contract['objective']['formula']}”最大化，并由硬约束先屏蔽不安全动作。"
            "如果接真实港口，缺少的泊位、工班、潮汐或设备字段会显示为待接入，不会自动补成实测值。"
        )
        evidence = ["app/rl_lab/contracts.py", f"environment:{environment_type}"]
    elif any(term in compact for term in ("数据", "可信", "多少行", "来源", "许可")):
        datasets = [item.public_dict() for item in dataset_catalog().values()]
        available = [item for item in datasets if item["available"]]
        detail = "；".join(
            f"{item['label']} {item.get('row_count', '—')}行，{item['license']}，"
            f"{'港口交通观测' if item['port_data'] else '非港口公开基准'}"
            for item in available
        )
        answer = (
            f"当前可复现数据共有 {len(available)} 套：{detail}。"
            "我会优先比较保留测试段，而不是只看训练曲线；AIS场景中的交通量和航速是实测，"
            "服务量、队列和等待改善属于校准仿真指标，不能写成码头生产实绩。"
        )
        evidence = ["data/rl_datasets.json", "dataset_sha256", "provenance"]
    elif any(term in compact for term in ("算法", "区别", "矩阵", "pid")):
        algorithms = algorithm_catalog()
        answer = (
            "六种候选与基线各自解决的偏差不同：Q-learning看下一状态最大价值，SARSA跟随实际探索动作，"
            "Expected SARSA对策略分布取期望，Double Q-learning拆分选择与评估以降低最大化偏差；"
            "PID不学习价值表，SOP代理按当前观测执行固定业务规则；两者共同作为非学习强基线。公平比较要求同一数据划分、时域、随机种子和约束。"
        )
        evidence = [f"{item['id']}:{item['update_equation']}" for item in algorithms]
    elif run:
        dataset = run.get("dataset", {})
        validation = run.get("validation", {})
        test = run.get("test_evaluation") or {}
        answer = (
            f"我查到最近任务 {run['run_id']}，当前状态是 {run['status']}，"
            f"使用 {dataset.get('label', run['config']['dataset_id'])} 的 {dataset.get('row_count', '—')} 行数据。"
            f"训练完成 {run.get('completed_training_episodes', 0)}/{run.get('total_training_episodes', 0)} 个回合；"
            f"验证集当前优选 {validation.get('best_algorithm_id') or '尚未产生'}，"
            f"保留测试集优选 {test.get('best_algorithm_id') or '尚未执行'}。"
            "下一步应先核对数据、配置和模型哈希，再判断结果是否满足港口试点门禁。"
        )
        evidence = [
            run.get("reproducibility", {}).get("dataset_sha256", ""),
            run.get("reproducibility", {}).get("config_sha256", ""),
        ]
    else:
        answer = (
            "训练中心还没有运行记录。你可以先选公开大规模能源基准验证学习稳定性，"
            "再用公开AIS场景核对港口交通语义，最后接入站点DCSA/TOS/VTS/EMS字段做现场标定。"
            "我会把训练、验证、保留测试和生产写入边界分开记录。"
        )
        evidence = ["environment_contracts", "dataset_catalog"]
    return {
        "answer": answer,
        "run_id": run.get("run_id") if run else None,
        "evidence": [item for item in evidence if item],
        "suggested_actions": [
            {"id": "inspect_contract", "label": "查看观测/动作/目标"},
            {"id": "open_training", "label": "配置六策略训练"},
            {"id": "inspect_evidence", "label": "核对数据与模型证据"},
        ],
        "generation_provider": "local_evidence_advisor",
        "grounded": True,
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
