"""Version-bound review API; bounded read-only experiments on public archives."""

import csv
import hashlib
import json
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from app.config import BASE_DIR
from app.harness import predictive_v8 as forecast, robust_schedule_v8 as robust, operations_v5 as ops
from app.harness.contracts import StrictModel, digest
from app.harness.dual_api import identity_for

REGISTRY = BASE_DIR / "config/capability_review_v8_registry.json"
COMPUTE_LOCK = threading.Lock()
OWN_SOURCES = [
    "app/harness/capability_review_v8.py",
    "app/harness/predictive_v8.py",
    "app/harness/robust_schedule_v8.py",
    "app/harness/operations_v5.py",
]


def filehash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


LOADED = {p: filehash(BASE_DIR / p) for p in OWN_SOURCES}
router = APIRouter(prefix="/api/harness/capability-review", tags=["逐项能力评估与改进"])


def checked(entry):
    path = (BASE_DIR / entry["path"]).resolve()
    if not path.is_relative_to(BASE_DIR.resolve()) or not path.is_file() or filehash(path) != entry["sha256"]:
        raise ValueError("登记证据缺失或摘要变化，暂停使用旧结果")
    return path


def read_json(entry):
    return json.loads(checked(entry).read_text())


def registered():
    if not REGISTRY.is_file():
        raise ValueError("本轮评估尚未登记")
    registry = json.loads(REGISTRY.read_text())
    issues = []
    for path, expected in registry["sources"].items():
        if not (BASE_DIR / path).is_file() or filehash(BASE_DIR / path) != expected:
            issues.append(path)
    issues.extend(p + ":loaded_code_differs" for p in OWN_SOURCES if registry["sources"].get(p) != LOADED[p])
    return registry, issues


def invoke(fn):
    try:
        return fn()
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, "评估证据不可用：" + str(exc)[:240]) from exc


def require_current():
    registry, issues = registered()
    if issues:
        raise HTTPException(409, "评估所绑定的代码或输入已变化，请重新验收；暂停使用旧模型重算")
    return registry


@router.get("/catalog")
def catalog(request: Request):
    identity_for(request)

    def value():
        registry, issues = registered()
        scorecard = read_json(registry["reports"]["scorecard"])
        results = read_json(registry["reports"]["summary"])
        data = read_json(registry["reports"]["forecast"])
        scheduling = read_json(registry["reports"]["scheduling"])
        return {
            "scorecard": scorecard,
            "results": results,
            "forecast_cells": data["cells"],
            "ports": data["ports"],
            "schedule_cases": scheduling["cases"],
            "current": not issues,
            "current_issues": issues,
            "production_authority": False,
        }

    return invoke(value)


class ForecastArgs(StrictModel):
    port_id: str = Field(max_length=40)
    origin: date = date(2026, 6, 1)
    horizon: Literal[1, 7, 14] = 7
    fault: Literal["none", "source_gap", "demand_shift"] = "none"


@router.post("/forecast")
def run_forecast(payload: ForecastArgs, request: Request):
    identity = identity_for(request)

    def value():
        registry = require_current()
        frozen = read_json(registry["reports"]["selection"])
        manifest = ops.catalog()
        entry = next((e for e in manifest["entries"] if e["id"] == payload.port_id), None)
        if entry is None:
            raise HTTPException(422, "请选择登记的港口")
        if not forecast.MODEL_AVAILABLE_FROM <= payload.origin <= date(2026, 7, 24):
            raise HTTPException(422, "请选择校准模型可用后的归档决策日期（2025-01-08至2026-07-24）")
        with checked(entry).open() as handle:
            records = [{"date": r["date"], "calls": float(r["portcalls"])} for r in csv.DictReader(handle)]
        mapping = forecast.validated(records)
        cutoff = payload.origin - timedelta(days=forecast.LAG)
        if payload.fault == "source_gap":
            mapping.pop(cutoff, None)
        elif payload.fault == "demand_shift":
            for day in mapping:
                if cutoff - timedelta(days=13) <= day <= cutoff:
                    mapping[day] = 100 * max(1.0, mapping[day])
        result = forecast.forecast(mapping, frozen["model"], payload.origin, payload.horizon)
        result["actor_id"] = identity.actor_id
        result["fault_injected_into_copy"] = payload.fault
        result["input_sha256"] = digest(
            {"parameters": payload.model_dump(mode="json"), "source_sha256": entry["sha256"]}
        )
        result["result_sha256"] = digest(result)
        return result

    return invoke(value)


@router.post("/schedule")
def run_schedule(payload: ops.OptimizeArgs, request: Request):
    identity = identity_for(request)
    if not COMPUTE_LOCK.acquire(blocking=False):
        raise HTTPException(429, "已有一项联合优化正在计算，请等待回执")
    try:

        def value():
            require_current()
            # All available source dates/port IDs are checked by the existing adapter.
            result = robust.compare(payload)
            result["actor_id"] = identity.actor_id
            result["result_sha256"] = digest(result)
            return result

        return invoke(value)
    finally:
        COMPUTE_LOCK.release()
