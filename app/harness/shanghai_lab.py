"""Shanghai trial orchestration over three native APIs, with isolated receipts."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import fcntl
import tempfile
import time
from contextlib import contextmanager
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import APIRouter, HTTPException, Request as APIRequest
from pydantic import Field

from app.config import BASE_DIR
from app.access_control import has_permission
from app.harness.contracts import StrictModel
from app.harness.dual_api import identity_for
from integrations.shanghai_lab_v1.data import contract, digest, file_sha, make_case, verified_dataset
from integrations.shanghai_lab_v1.protocol import packed, validate_plan, verify_energy
from integrations.shanghai_lab_v1.planning import compare_and_select
from integrations.shanghai_lab_v1.briefing import compile_briefing, check_claims
from integrations.shanghai_lab_v1 import delivery

router = APIRouter(prefix="/api/harness/shanghai", tags=["Shanghai-public-lab"])
ROOT = BASE_DIR / ".runtime/shanghai-lab-v1"
IMPLEMENTATION = {
    str(p.relative_to(BASE_DIR)): file_sha(p)
    for p in [Path(__file__), *sorted((BASE_DIR / "integrations/shanghai_lab_v1").glob("*.py"))]
}
LOCK = threading.RLock()
URLS = {
    "malacca": os.getenv("SHANGHAI_LAB_MALACCA_URL", "http://127.0.0.1:5174"),
    "energy": os.getenv("SHANGHAI_LAB_ENERGY_URL", "http://127.0.0.1:8808"),
    "port": os.getenv("SHANGHAI_LAB_PORT_URL", "http://127.0.0.1:8000"),
}


@contextmanager
def trial_lock():
    ROOT.mkdir(parents=True, exist_ok=True)
    with LOCK, (ROOT / ".trial.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class TrialRequest(StrictModel):
    request_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    day: str = Field("2025-10-15", pattern=r"^2025-\d{2}-\d{2}$")
    scenario: str = Field("normal", max_length=40)
    seed: int = Field(17, ge=0, le=100000)


class ClaimsRequest(StrictModel):
    claims: list[dict] = Field(min_length=1, max_length=30)


class DeliveryRequest(StrictModel):
    request_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    result_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["operations_review", "energy_review", "acknowledge"]
    client: Literal["flutter-web", "flutter-macos", "flutter-mobile", "contract-test"]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("trial service redirects are forbidden")


def call(system, path, payload=None):
    base = URLS[system].rstrip("/")
    parsed = urlparse(base)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.path
    ):
        raise ValueError("trial services must use explicit loopback endpoints")
    headers = {"Content-Type": "application/json"}
    token = os.getenv("SHANGHAI_LAB_" + system.upper() + "_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    try:
        with build_opener(NoRedirect).open(Request(base + path, data=data, headers=headers), timeout=25) as response:
            raw = response.read(1500001)
    except HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", errors="replace")
        raise ValueError(f"{system} rejected trial (HTTP {exc.code}): {detail}") from exc
    if len(raw) > 1500000:
        raise ValueError("trial response too large")
    return json.loads(raw)


def save(result):
    ROOT.mkdir(parents=True, exist_ok=True)
    target = ROOT / (result["id"] + ".json")
    with tempfile.NamedTemporaryFile(
        mode="w", dir=ROOT, prefix=result["id"] + "-", suffix=".tmp", delete=False
    ) as stream:
        temporary = Path(stream.name)
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)
    descriptor = os.open(ROOT, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@router.get("/catalog")
def catalog(request: APIRequest):
    identity_for(request)
    try:
        manifest, daily, weather, assumptions = verified_dataset()
        return {
            "dataset": manifest,
            "contract": contract(),
            "assumptions": assumptions,
            "daily_rows": len(daily),
            "weather_hours": len(weather),
            "production_authority": False,
            "implementation": IMPLEMENTATION,
        }
    except (OSError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/trials")
def run_trial(payload: TrialRequest, request: APIRequest):
    identity = identity_for(request, "operations.manage")
    run_id = "sjt-" + digest({"actor": identity.actor_id, "request_id": payload.request_id})[:24]
    signature = digest(payload.model_dump())
    with trial_lock():
        path = ROOT / (run_id + ".json")
        if path.exists():
            old = json.loads(path.read_text())
            if old["request_sha256"] != signature:
                raise HTTPException(409, "request id already bound to another trial")
            return get_trial(run_id, request)
        result = {
            "schema": "shanghai-joint-result.v1",
            "id": run_id,
            "actor_id": identity.actor_id,
            "request_sha256": signature,
            "request": payload.model_dump(),
            "status": "running",
            "steps": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "production_authority": False,
            "sailing_simulator": "excluded_by_user",
            "mobile_ack": None,
            "implementation": IMPLEMENTATION,
        }
        start = time.monotonic()
        try:
            case = make_case(payload.day, payload.scenario, payload.seed)
            packet = packed(case, "snapshot")
            result["snapshot"] = case
            result["steps"].append({"step": "shared_snapshot", "sha256": case["snapshot_sha256"], "status": "passed"})
            plan = call("malacca", "/api/shanghai-lab/v1/plan", packet)
            result["native_heuristic_plan"] = plan
            plan = compare_and_select(case, plan)
            validation = validate_plan(case, plan)
            result["plan"] = plan
            result["steps"].append(
                {
                    "step": "malacca_plan_and_resource_recheck",
                    "status": "passed",
                    "metrics": {k: v for k, v in validation.items() if isinstance(v, (int, float, bool))},
                }
            )
            packet.update(packed(plan, "plan"))
            native_review = call("malacca", "/api/shanghai-lab/v1/review", packet)
            if (
                not native_review.get("reviewed")
                or native_review.get("plan_transport_sha256") != packet["plan_transport_sha256"]
            ):
                raise ValueError("native selected-plan review mismatch")
            result["native_selected_plan_review"] = native_review
            energy = call("energy", "/api/shanghai-lab/v1/evaluate", packet)
            verify_energy(case, plan, energy)
            result["energy"] = energy
            result["steps"].append({"step": "energy_ledger_recheck", "status": "passed", "totals": energy["totals"]})
            packet.update(packed(energy, "energy"))
            execution = call("port", "/api/shanghai-lab/v1/execute", packet)
            readback = call("port", "/api/shanghai-lab/v1/runs/" + execution["run_id"])
            if (
                execution != readback
                or not readback["restore_verified"]
                or readback["source_snapshot_sha256"] != case["snapshot_sha256"]
            ):
                raise ValueError("independent readback/restoration mismatch")
            if digest({k: v for k, v in readback.items() if k != "receipt_sha256"}) != readback["receipt_sha256"]:
                raise ValueError("execution receipt hash mismatch")
            result["execution"] = readback
            result["steps"].append(
                {"step": "port_execution_readback_and_restore", "status": "passed", "events": len(readback["events"])}
            )
            result["status"] = "completed_simulation_pending_mobile"
            result["summary"] = {
                "authorship": "verified_artifact_compiler_not_llm",
                "port": "上海港公开数据校准试验",
                "trial_id": case["trial_id"],
                "source_snapshot_sha256": case["snapshot_sha256"],
                "tasks": len(case["jobs"]),
                "processed_teu": validation["processed_teu"],
                "late_vessel_hours": validation["late_vessel_hours"],
                "total_cny": energy["totals"]["total_cny"],
                "notice": "公开统计、AIS派生指标、再分析气象与工程补足共同驱动的模拟结果；未使用现场工单和计量。",
            }
        except (ValueError, KeyError, TypeError, OSError, HTTPError, URLError) as exc:
            result["status"] = "blocked"
            result["error"] = str(exc)
            result["steps"].append({"step": "failure", "status": "blocked", "reason": str(exc)})
        result["elapsed_seconds"] = time.monotonic() - start
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        result["result_sha256"] = digest({k: v for k, v in result.items() if k not in {"result_sha256", "mobile_ack"}})
        save(result)
        return result


@router.get("/trials/{run_id}")
def get_trial(run_id: str, request: APIRequest):
    identity = identity_for(request)
    if not re.fullmatch(r"sjt-[a-f0-9]{24}", run_id):
        raise HTTPException(422, "invalid trial id")
    try:
        result = json.loads((ROOT / (run_id + ".json")).read_text())
    except FileNotFoundError as exc:
        raise HTTPException(404, "trial not found") from exc
    if result["actor_id"] != identity.actor_id and identity.role != "admin":
        raise HTTPException(403, "trial owner mismatch")
    if digest({k: v for k, v in result.items() if k not in {"result_sha256", "mobile_ack"}}) != result["result_sha256"]:
        raise HTTPException(409, "trial integrity mismatch")
    return result


@router.get("/trials/{run_id}/briefing")
def briefing(run_id: str, request: APIRequest):
    try:
        return compile_briefing(get_trial(run_id, request))
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/trials/{run_id}/check-claims")
def claims(run_id: str, payload: ClaimsRequest, request: APIRequest):
    return check_claims(briefing(run_id, request), payload.claims)


@router.get("/trials/{run_id}/delivery")
def delivery_status(run_id: str, request: APIRequest):
    result = get_trial(run_id, request)
    try:
        return delivery.state(ROOT / "delivery.sqlite", run_id, result["result_sha256"])
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/trials/{run_id}/delivery")
def record_delivery(run_id: str, payload: DeliveryRequest, request: APIRequest):
    identity = identity_for(request)
    result = get_trial(run_id, request)
    if result["status"] != "completed_simulation_pending_mobile":
        raise HTTPException(409, "only a verified completed trial can be reviewed")
    try:
        return delivery.append(
            ROOT / "delivery.sqlite", run_id, result["result_sha256"], payload.model_dump(), identity, has_permission
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
