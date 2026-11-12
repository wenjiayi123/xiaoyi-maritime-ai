"""Read-only council evidence for the versioned crane and storage simulation in CarbonOps."""
import hashlib
import json
from typing import Literal
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from pydantic import BaseModel, ConfigDict, Field

from app.policy_release import CHECK_METRICS, ROLE_CHECKS, ReleaseUnavailable

RELEASE = "port-storage-20261112"
SOURCE = "http://127.0.0.1:5173/port-storage-council-20261112.json"
SHA256 = "138e1e4a2f1e3fd61f5ad318d1c5fee2a2e9b243487631a6ec9c8782c132b7bd"

class StorageSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release: Literal["port-storage-20261112"]
    case_id: str = Field(pattern=r"^(?:known|fresh)-2025-\d\d-\d\d-(?:88|93|119|131)$")
    strategy: Literal["q_crane","capacity","idle_only","capacity_idle","capacity_peak","capacity_q"]

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def role_inputs(name, task, default):
    if name in {"policy.energy","policy.operations","policy.safety"} and task.get("council_role_review"):
        if (task.get("policy_context") or {}).get("release") == RELEASE:
            return StorageSelection
    return default

def evidence():
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(SOURCE,timeout=4) as response:
            raw=response.read(250_001)
            if response.geturl()!=SOURCE or len(raw)>250_000 or hashlib.sha256(raw).hexdigest()!=SHA256:
                raise ReleaseUnavailable("港机与储能的发布原件或摘要不匹配")
    except (OSError,URLError) as exc:
        raise ReleaseUnavailable("能碳系统未提供登记的港机与储能回执") from exc
    data=json.loads(raw)
    if data["schema"]!=RELEASE or data["production_authority"] is not False:
        raise ReleaseUnavailable("储能回执版本或仿真边界不符")
    return data

def review_role(role, selection):
    data=evidence()
    record=data["cases"].get(selection.case_id)
    if record is None:
        raise ReleaseUnavailable("没有该日期与负荷组合的冻结工况")
    candidate=record["policies"][selection.strategy]
    baseline=record["policies"]["mpc"]
    tolerance=1e-6
    checks={
        "cost":candidate["cost"]<baseline["cost"]-tolerance,
        "carbon":candidate["carbon_kg"]<=baseline["carbon_kg"]+tolerance,
        "service":candidate["processed_teu"]>=baseline["processed_teu"]-tolerance,
        "delay":candidate["delay_minutes"]<=baseline["delay_minutes"]+tolerance,
        "peak":candidate["peak_kw"]<=baseline["peak_kw"]+tolerance,
        "safety":candidate["safety_violations"]==0,
        "terminal_soc":candidate["ending_battery_soc"]>=baseline["ending_battery_soc"]-tolerance,
    }
    selected={k:checks[k] for k in ROLE_CHECKS[role]}
    metrics=[CHECK_METRICS[k] for k in selected]
    return dict(schema="gullmate.storage-role-review.v1",role=role,selection=selection.model_dump(),baseline="mpc",
                checks=selected,decision="pass" if all(selected.values()) else "veto",scope="historical simulation",
                production_authority=False,source_url=SOURCE,release_sha256=SHA256,dataset_sha256=data["dataset_sha256"],
                policy_sha256=data["policy_hashes"][selection.strategy],hourly_source_sha256=record["hourly_source_sha256"],
                period=f"{record['date']} UTC / {record['demand_percent']}% / 24h",
                policy_metrics={k:candidate[k] for k in metrics},baseline_metrics={k:baseline[k] for k in metrics})
