"""Evaluate hard constraints on a fixed set of recorded CarbonOps strategies. This tool never dispatches controls."""
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.policy_release import load_verified_release

OBJECTIVES={"cost":"成本","carbon_kg":"碳排放","peak_kw":"峰值功率","delay_minutes":"延误"}
UNITS={"cost":"发布数据集成本单位","carbon_kg":"kg","peak_kw":"kW","delay_minutes":"min","processed_teu":"TEU",
       "safety_violations":"次","ending_battery_soc":"比例"}
MINIMUM={"processed_teu","ending_battery_soc"}


class PolicyLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    delay_minutes: float | None = Field(None,ge=-1440,le=1_000_000)
    processed_teu: float | None = Field(None,ge=0,le=1_000_000_000)
    peak_kw: float | None = Field(None,ge=0,le=1_000_000_000)
    cost: float | None = Field(None,ge=0,le=1_000_000_000_000)
    carbon_kg: float | None = Field(None,ge=0,le=1_000_000_000_000)
    ending_battery_soc: float | None = Field(None,ge=0,le=1)


class PolicyBoard(BaseModel):
    model_config = ConfigDict(extra="forbid",allow_inf_nan=False)
    scenario: Literal["evaluate","stress"]
    window: int = Field(ge=0,le=11)
    candidates: list[str] = Field(min_length=2,max_length=11)
    objective: Literal["cost","carbon_kg","peak_kw","delay_minutes"]
    limits: PolicyLimits
    precision: Literal["source","one_decimal"] = "source"

    @model_validator(mode="after")
    def check_candidates(self):
        if len(set(self.candidates)) != len(self.candidates):
            raise ValueError("候选策略不能重复")
        if any(len(name)>60 or not name for name in self.candidates):
            raise ValueError("无效的候选策略标识")
        if not self.limits.model_dump(exclude_none=True):
            raise ValueError("请明确至少一条业务约束")
        return self


def select(request: PolicyBoard) -> dict:
    release,sha = load_verified_release()
    data=release["scenarios"][request.scenario]
    policies=data["policies"]
    unknown=[name for name in request.candidates if name not in policies]
    if unknown:raise ValueError("没有对应发布证据的候选："+", ".join(unknown))
    limits=request.limits.model_dump(exclude_none=True)
    limits["safety_violations"]=0
    rows=[]
    window_start=data["starts"][request.window]
    period=None
    for name in request.candidates:
        window=policies[name]["windows"][request.window]
        if window.get("start")!=window_start or (period is not None and window.get("period")!=period):
            raise ValueError("候选的窗口或月份未对齐")
        period=window["period"]
        metrics={}
        for k in set(limits)|{request.objective}:
            v=window["metrics"].get(k)
            if type(v) not in (int,float) or not math.isfinite(v):
                raise ValueError(f"候选 {name} 缺少有限指标 {k}")
            if k=="safety_violations" and (v<0 or int(v)!=v):
                raise ValueError("安全违规次数必须为非负整数")
            # Source precision always governs safety counts; rounding must never erase a violation.
            metrics[k]=round(v,1) if request.precision=="one_decimal" and k!="safety_violations" else v
        checks={k:(metrics[k]>=threshold if k in MINIMUM else metrics[k]<=threshold) for k,threshold in limits.items()}
        rows.append({"policy":name,"weight_sha256":release["weights"].get(name),"metrics":metrics,
                     "checks":checks,"failed":[k for k,passed in checks.items() if not passed],"feasible":all(checks.values())})
    feasible=[r for r in rows if r["feasible"]]
    preferred=min(feasible,key=lambda r:r["metrics"][request.objective]) if feasible else None
    ties=[r["policy"] for r in feasible if preferred and r["metrics"][request.objective]==preferred["metrics"][request.objective]]
    return {"schema":"gullmate.policy-board.v1","source":"CarbonOps","release_sha256":sha,
            "dataset_sha256":release["dataset_sha256"],"scenario":request.scenario,"window":request.window,
            "period":period,"start":window_start,"limits":limits,"objective":request.objective,"units":UNITS,
            "precision":request.precision,"candidates":rows,"selected":preferred["policy"] if preferred else None,
            "ties":ties,"decision":"human_review" if preferred else "no_feasible_registered",
            "input_issue":"延误为非负量，给定上限使任务不可行" if limits.get("delay_minutes",0)<0 else None,
            "scope":"仅比较登记候选、指定历史仿真窗口和给定阈值","production_authority":False}


def summarize(receipt: dict) -> str:
    picked=receipt["selected"]
    if picked:
        lead=f"建议提交人工复核的候选为 {picked}，在满足全部约束的候选中{OBJECTIVES[receipt['objective']]}最低。"
    else:
        lead="给定窗口中没有满足全部约束的登记候选，暂缓推荐。"
    if receipt["input_issue"]:lead+=" "+receipt["input_issue"]+"。"
    details=["；".join(r["failed"]) if r["failed"] else "满足全部约束" for r in receipt["candidates"]]
    return lead+"\n"+"\n".join(f"{r['policy']}　{reason}" for r,reason in zip(receipt["candidates"],details,strict=True))+"\n依据为 CarbonOps 历史仿真回执。现场策略下发须另行审批。"
