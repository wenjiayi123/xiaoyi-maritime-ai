"""Read and verify a frozen, retrospective multi-device dispatch result without loading an actor."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel,ConfigDict
from app.config import WEB_DIR

DIRECTORY=WEB_DIR/"policy-evidence"/"cooperative-device-20261108"
INDEX_SHA256="bda54e70a41cd9d8bd9dc6f47de65cd4442c3b984b1710cff6d7160c5e6b9b38"
CAPACITY_SHA256="02daed1e9a1a24211db2d58dfbe9f74b58e1185bb7c370d3b7b68c36ed724a2e"


class DeviceReview(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
    day: date
    baseline: Literal["fixed","mpc2"]
    demand: Literal["normal","stress"]
    method: Literal["trained","untrained_scores","minimum_cost","cranes_only","flex_only"]="trained"


def checked(path:Path,checksum:str,limit:int):
    with path.open("rb") as stream:data=stream.read(limit+1)
    if len(data)>limit or sha256(data).hexdigest()!=checksum:
        raise ValueError("设备回执内容或版本与登记值不符")
    return json.loads(data)


def inspect_day(selection:DeviceReview):
    index=checked(DIRECTORY/"index.json",INDEX_SHA256,1_000_000)
    group=selection.baseline+"-"+selection.demand
    calendar=index["groups"][group]["days"];stamp=selection.day.isoformat()
    record=next((r for r in calendar if r["day"]==stamp),None)
    if not record:raise ValueError("该日期没有冻结的配对回执。登记日期："+", ".join(r["day"] for r in calendar))
    name=group+"-"+stamp+".json"
    day=checked(DIRECTORY/name,record["sha256"],2_000_000)
    if (day["day"]!=stamp or day["group"]!=group or day["weight"]!=index["weight"] or day["production_authority"] is not False):
        raise ValueError("设备回执日期、场景、权重或权限不符")
    case=day["methods"][selection.method];m=case["metrics"];b=day["baseline"];tol=1e-6
    checks={"cost":m["cost"]<b["cost"],"carbon":m["carbon_kg"]<=b["carbon_kg"]+tol,
        "throughput":m["processed_teu"]+tol>=b["processed_teu"],"delay":m["delay_minutes"]<=b["delay_minutes"]+tol,
        "peak":m["peak_kw"]<=b["peak_kw"]+tol,"zero_safety":m["safety_violations"]==0,
        "shore_service":m["shore_power_kwh"]+tol>=b["shore_power_kwh"],"terminal_soc":m["ending_battery_soc"]+tol>=b["ending_battery_soc"],
        "agv_delivered":m["agv_charged_kwh"]+tol>=b["agv_charged_kwh"],"agv_departures":m["agv_missed_required_kwh"]<=tol,
        "cold_chain":m["reefer_thermal_violation_steps"]==0,"terminal_thermal_debt":m["ending_reefer_thermal_debt"]<=b["ending_reefer_thermal_debt"]+tol,
        "building_service":case["unbacked_building_kwh"]<=tol,"dr_commitment":abs(m["demand_response_target_kwh"]-day["target"])<=tol,
        "dr_delivery":m["demand_response_delivered_kwh"]+tol>=.98*day["target"]}
    failed=[k for k,v in checks.items() if not v]
    if checks!=case["checks"] or case["passed"]!=(not failed):raise ValueError("日终门槛复算结果与已发布记录不符")
    evidence=checked(DIRECTORY/("capacity-"+CAPACITY_SHA256+".json"),CAPACITY_SHA256,250_000)
    cert=evidence["groups"][group][stamp]
    if (evidence["release_sha256"]!=INDEX_SHA256 or cert["receipt_sha256"]!=record["sha256"]
            or abs(cert["required_kwh"]-.98*day["target"])>tol):
        raise ValueError("物理上界与冻结日回执不匹配")
    proven=cert["upper_kwh"]+tol<cert["required_kwh"]
    disposition=("no_event" if day["target"]==0 else "incompatible_with_service" if proven
                 else "delivered" if checks["dr_delivery"] else "shortfall_undetermined")
    return {"schema":"gullmate.cooperative-device-review.v1","selection":selection.model_dump(mode="json"),"weight_sha256":index["weight"],
        "dataset_sha256":index["dataset"],"receipt_sha256":record["sha256"],"release_sha256":INDEX_SHA256,"checks":checks,"failed":failed,
        "cost_change_pct":(m["cost"]/b["cost"]-1)*100,"candidate_metrics":m,"baseline_metrics":b,
        "dr_contract_kwh":day["target"],"dr_optimistic_upper_kwh":cert["upper_kwh"],"dr_infeasibility_proven":proven,
        "dr_capacity_review":{"status":disposition,"required_kwh":cert["required_kwh"],"delivered_kwh":m["demand_response_delivered_kwh"],
            "upper_kwh":cert["upper_kwh"],"audit_sha256":CAPACITY_SHA256,"historical_only":True,
            "scope":"事后物理上界。假设预知全天并保留充电与冷链服务；不作事前可承诺容量。"},
        "decision":"eligible_for_offline_review" if not failed else "withhold_candidate","production_authority":False,
        "scope":"2024 洛杉矶港公开锚定工程仿真中已登记的 24 小时。对调配方案的自动筛查只用于离线复核。"}
