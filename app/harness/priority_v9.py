"""Bound, read-only experiments for the three priority capability upgrades."""

import csv
import hashlib
import json
import threading
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from app.config import BASE_DIR
from app.harness import interval_v9, predictive_v8, annual_v9
from app.harness.contracts import StrictModel, digest
from app.harness.dual_api import identity_for
from app.harness.physical_v3 import decode

REGISTRY = BASE_DIR / "config/priority_v9_registry.json"
OWN = [
    "app/harness/priority_v9.py",
    "app/harness/interval_v9.py",
    "app/harness/annual_v9.py",
    "app/harness/constrained_rl_v9.py",
    "app/harness/predictive_v8.py",
    "app/harness/twin_v7.py",
    "app/harness/physical_v3.py",
]
LOCK = threading.Lock()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


LOADED = {p: sha(BASE_DIR / p) for p in OWN}
router = APIRouter(prefix="/api/harness/priority-v9", tags=["预测、RL与年度孪生专项提升"])


def checked(entry):
    p = (BASE_DIR / entry["path"]).resolve()
    if not p.is_relative_to(BASE_DIR.resolve()) or not p.is_file() or sha(p) != entry["sha256"]:
        raise ValueError("证据缺失或摘要已变化")
    return p


def read(entry):
    return json.loads(checked(entry).read_text())


def registered():
    registry = json.loads(REGISTRY.read_text())
    issues = [p for p, h in registry["sources"].items() if not (BASE_DIR / p).is_file() or sha(BASE_DIR / p) != h]
    issues += [p + ":loaded" for p in OWN if LOADED[p] != registry["sources"].get(p)]
    return registry, issues


def invoke(fn):
    try:
        return fn()
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, "专项证据不可用：" + str(exc)[:180]) from exc


def current():
    registry, issues = registered()
    if issues:
        raise HTTPException(409, "代码或登记输入已变化，暂停重算；请重新验收")
    return registry


@router.get("/catalog")
def catalog(request: Request):
    identity_for(request)

    def value():
        registry, issues = registered()
        result = {key: read(registry["reports"][key]) for key in ["scorecard", "summary", "forecast", "annual", "rl"]}
        # The large raw trajectory archive stays in its separately hashed evidence package.
        result["rl"] = {k: v for k, v in result["rl"].items() if k not in ["runs", "diagnosis"]}
        result["ports"] = read(registry["reports"]["forecast_manifest"])["entries"]
        return {**result, "current": not issues, "issues": issues, "production_authority": False}

    return invoke(value)


class ForecastArgs(StrictModel):
    port_id: str = Field(max_length=40)
    origin: date = date(2026, 6, 1)
    horizon: Literal[1, 7, 14] = 7
    fault: Literal["none", "source_gap"] = "none"


@router.post("/forecast")
def forecast(payload: ForecastArgs, request: Request):
    identity = identity_for(request)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, "已有重算正在进行")
    try:

        def value():
            registry = current()
            reports = registry["reports"]
            if not date(2026, 1, 8) <= payload.origin <= date(2026, 7, 24) - timedelta(days=payload.horizon):
                raise HTTPException(422, "请选择可用归档日期，目标日期不得超过2026-07-24")
            manifest = read(reports["forecast_manifest"])
            entry = next((e for e in manifest["entries"] if e["id"] == payload.port_id), None)
            if entry is None:
                raise HTTPException(422, "请选择本轮登记港口")
            sealed = read(reports["forecast_selection"])
            with checked(entry).open() as f:
                mapping = predictive_v8.validated(
                    [{"date": r["date"], "calls": float(r["portcalls"])} for r in csv.DictReader(f)]
                )
            if payload.fault == "source_gap":
                mapping.pop(payload.origin - timedelta(days=7), None)
            cache = interval_v9.point_cache(
                mapping, payload.horizon, end=payload.origin + timedelta(days=payload.horizon)
            )
            rows = interval_v9.replay(
                cache, sealed["point_models"][str(payload.horizon)], payload.horizon, sealed["selected"], 2026
            )["rows"]
            result = next((r for r in rows if r["origin"] == payload.origin.isoformat()), None)
            if result is None:
                raise HTTPException(422, "目标日期须不早于2026-01-22")
            # Future truth is deliberately absent from a decision response.
            result = {k: v for k, v in result.items() if k not in ["actual", "covered90", "absolute_error", "wis"]}
            result.update(
                actor_id=identity.actor_id,
                fault=payload.fault,
                scope="公开归档因果重算，非实时船期",
                rl_decision_authorized=False,
                production_authority=False,
            )
            result["result_sha256"] = digest(result)
            return result

        return invoke(value)
    finally:
        LOCK.release()


class AnnualArgs(StrictModel):
    station_id: str = Field(max_length=20)
    day: date = date(2025, 6, 1)


@router.post("/annual")
def annual(payload: AnnualArgs, request: Request):
    identity_for(request)

    def value():
        registry = current()
        if payload.day.year != 2025:
            raise HTTPException(422, "本轮只验收2025年归档全年预测")
        frozen = read(registry["reports"]["annual_selection"])
        station = next((s for s in frozen["stations"] if s["station_id"] == payload.station_id), None)
        if station is None:
            raise HTTPException(422, "请选择登记站点")
        if station["status"] != "ready":
            return {
                "station_id": payload.station_id,
                "status": "hold",
                "reason": station["reason"],
                "production_authority": False,
            }
        version = station["versions"]["v9"]
        times = [t for t in annual_v9.old.previous.hours(2025) if t.date() == payload.day]
        values = annual_v9.predict(times, decode(version["model"]), version["choice"])
        radius = version["quarter_radii_m"][str((payload.day.month - 1) // 3 + 1)]
        report = read(registry["reports"]["annual"])
        cell = next(c for c in report["cells"] if c["station_id"] == payload.station_id and c["method"] == "v9")
        result = {
            "station_id": payload.station_id,
            "site": station["site"],
            "status": "research_only"
            if cell["annual"]["passed"] and all(q["passed"] for q in cell["quarters"].values())
            else "hold",
            "annual_checks": cell["annual"],
            "quarter_checks": cell["quarters"],
            "datum": "MLLW",
            "units": "m",
            "time_zone": "UTC",
            "rows": [
                {
                    "time": t.isoformat(),
                    "prediction": float(v),
                    "lower90": float(v - radius),
                    "upper90": float(v + radius),
                }
                for t, v in zip(times, values)
            ],
            "production_authority": False,
            "scope": "无2025观测同化；归档年度潮位分量，不代表完整港口数字孪生",
        }
        result["result_sha256"] = digest(result)
        return result

    return invoke(value)
