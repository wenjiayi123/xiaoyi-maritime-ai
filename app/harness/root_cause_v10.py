"""Evidence-bound diagnosis and frozen seasonal tide replay; no LLM invocation."""

import hashlib
import json
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from app.config import BASE_DIR
from app.harness import annual_v9
from app.harness.contracts import StrictModel, digest
from app.harness.dual_api import identity_for
from app.harness.physical_v3 import decode

REGISTRY = BASE_DIR / "config/root_cause_v10_registry.json"
OWN = [
    "app/harness/root_cause_v10.py",
    "app/harness/annual_v9.py",
    "app/harness/seasonal_twin_v10.py",
    "app/harness/root_control_v10.py",
    "app/harness/physical_v3.py",
    "app/harness/twin_v7.py",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


LOADED = {p: sha(BASE_DIR / p) for p in OWN}
router = APIRouter(prefix="/api/harness/root-cause-v10", tags=["模型体量与根因诊断"])


def checked(entry):
    p = (BASE_DIR / entry["path"]).resolve()
    if not p.is_relative_to(BASE_DIR.resolve()) or not p.is_file() or sha(p) != entry["sha256"]:
        raise ValueError("登记证据缺失或变化")
    return json.loads(p.read_text())


def registered():
    r = json.loads(REGISTRY.read_text())
    issues = [p for p, h in r["sources"].items() if not (BASE_DIR / p).is_file() or sha(BASE_DIR / p) != h]
    issues += [p + ":loaded" for p in OWN if r["sources"].get(p) != LOADED[p]]
    return r, issues


def invoke(fn):
    try:
        return fn()
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, "根因评估证据不可用：" + str(exc)[:160]) from exc


@router.get("/catalog")
def catalog(request: Request):
    identity_for(request)

    def value():
        r, issues = registered()
        return {k: checked(r["reports"][k]) for k in ["summary", "scorecard"]} | {
            "current": not issues,
            "issues": issues,
            "production_authority": False,
        }

    return invoke(value)


class TideArgs(StrictModel):
    station_id: str = Field(max_length=20)
    day: date = date(2025, 6, 1)


@router.post("/annual")
def annual(payload: TideArgs, request: Request):
    identity_for(request)

    def value():
        r, issues = registered()
        if issues:
            raise HTTPException(409, "代码或证据变化，暂停重算")
        if payload.day.year != 2025:
            raise HTTPException(422, "请选择本次独立测试的2025年归档日期")
        frozen = checked(r["reports"]["annual_selection"])
        station = next((s for s in frozen["stations"] if s["station_id"] == payload.station_id), None)
        if station is None:
            raise HTTPException(422, "请选择本轮登记新站点")
        if station["status"] != "ready":
            return {"status": "hold", "reason": station["reason"], "production_authority": False}
        version = station["versions"]["v9"]
        times = [t for t in annual_v9.old.previous.hours(2025) if t.date() == payload.day]
        pred = annual_v9.predict(times, decode(version["model"]), version["choice"])
        lower, upper = station["v10_bands"][payload.day.isoformat()]
        old_radius = version["quarter_radii_m"][str((payload.day.month - 1) // 3 + 1)]
        report = checked(r["reports"]["annual"])
        cell = next(
            c for c in report["cells"] if c["station_id"] == payload.station_id and c["method"] == "v10_selected"
        )
        qualified = cell["annual"]["passed"] and all(q["passed"] for q in cell["quarters"].values())
        result = {
            "station_id": payload.station_id,
            "site": station["site"],
            "status": "research_only" if qualified else "hold",
            "method": frozen["selected"],
            "annual": cell["annual"],
            "quarters": cell["quarters"],
            "units": "m",
            "datum": "MLLW",
            "time_zone": "UTC",
            "rows": [
                {
                    "time": t.isoformat(),
                    "prediction": float(v),
                    "lower90": float(v + lower),
                    "upper90": float(v + upper),
                    "v9_lower90": float(v - old_radius),
                    "v9_upper90": float(v + old_radius),
                }
                for t, v in zip(times, pred)
            ],
            "language_model_used": False,
            "production_authority": False,
        }
        result["result_sha256"] = digest(result)
        return result

    return invoke(value)
