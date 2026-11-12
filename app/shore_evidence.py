"""Read a registered V8 week or a separate ship-call meter reconciliation."""
from datetime import date
from typing import Annotated
from pydantic import BaseModel,ConfigDict,Field,model_validator
from app.config import WEB_DIR
from app.cooperative_review import checked

DIRECTORY=WEB_DIR/"policy-evidence/shore-storage"
INDEX_SHA="3493a7b28b388ac168806a7227e6da275c8632b4a91f376ab8da26f84b4229d3"


class ShoreQuery(BaseModel):
    model_config=ConfigDict(extra="forbid")
    verify_twin: bool=False
    week: date|None=None
    call_id: Annotated[str,Field(pattern=r"^SC_[0-9]{5}$")]|None=None
    hour: Annotated[int,Field(strict=True,ge=0,le=167)]|None=None

    @model_validator(mode="after")
    def scope(self):
        if (self.week is None)==(self.call_id is None):raise ValueError("周起始日期与工程船次必须且只能指定一种")
        if self.call_id and self.verify_twin:raise ValueError("逐船电表没有 V8 周重放身份")
        if self.call_id and self.hour is not None:raise ValueError("小时索引只适用于周策略")
        return self


def review_shore(q:ShoreQuery):
    index=checked(DIRECTORY/"index.json",INDEX_SHA,200_000)
    if q.call_id:
        if q.call_id not in index["calls"]:raise ValueError("未登记的工程岸电船次")
        code=index["calls"][q.call_id]
        row=checked(DIRECTORY/"calls"/(q.call_id+".json"),code,100_000)
        if row["call"]!=q.call_id or row["production_authority"] is not False:raise ValueError("船次回执身份或权限不符")
        kwh=sum(v["kw"]*v["covered_hours"] for v in row["meter"])
        if abs(kwh-row["in_call_kwh"])>1e-5:raise ValueError("船次电量复算不符")
        return {"schema":"gullmate.shore-call-review.v1","receipt_sha256":code,
                **{k:v for k,v in row.items() if k!="meter"},"simulation":True,
                "scope":"单独的模拟泊位电表，按读数持续至下个 15 分钟或登记离泊时刻计量。不能归到 V8 电池的收益账。"}
    day=q.week.isoformat()
    if day not in index["weeks"]:raise ValueError("该日期不是登记的 168 小时窗口起点")
    code=index["weeks"][day]
    row=checked(DIRECTORY/"weeks"/(day+".json"),code,400_000)
    if row["week"]!=day or row["weight"]!=index["weight"] or row["production_authority"] is not False:raise ValueError("周回执身份或权限不符")
    evidence={k:row[k] for k in ("week","end","part","weight","baseline","candidate","fixed","reduction_pct","audited",
                                "checks","all_three_improved","days","production_authority")}
    if q.hour is not None:evidence["hourly"]=row["hours"][q.hour]
    if q.verify_twin:
        from app.twin_readback import compare_with_twin
        evidence["twin_readback"]=compare_with_twin(evidence)
    return {"schema":"gullmate.shore-week-review.v1","receipt_sha256":code,**evidence,
            "scope":"上海公开数据校准的 168 小时工程仿真。岸电保障量由模型约束给定；逐船电表另有独立数据源。"}


def shore_digest(r):
    if r["schema"]=="gullmate.shore-call-review.v1":
        return {"工程船次":r["call"],"泊位":r["berth"],"到泊":r["eta"],"离泊":r["etd"],
                "计入电量_kWh":format(r["in_call_kwh"],".3f"),"采样数":r["samples"],
                "离泊端点读数条数":r["terminal_readings"],"不截断读数电量_kWh":format(r["unclipped_kwh"],".3f"),
                "离泊之后的一刻钟计入吗":"不计入。船舶服务在登记离泊时刻结束；端点之后的供电不属于该次靠泊。",
                "计量口径":r["scope"],"现场权限":False,"回执":r["receipt_sha256"]}
    a=r["audited"]
    info={"周起点UTC":r["week"],"周末UTC":r["end"],"分区":r["part"],
          "总成本减少比例_百分数":format(r["reduction_pct"]["total_cost_cny"],".5f"),
          "碳排减少比例_百分数":format(r["reduction_pct"]["carbon_kg"],".5f"),"峰值减少比例_百分数":format(r["reduction_pct"]["peak_kw"],".5f"),
          "相对待机的账单变化_元":format(a["cost_delta_cny"],".2f"),"相对待机的碳排变化_kg":format(a["carbon_delta_kg"],".3f"),
          "电池的碳排变化_kg":format(a["battery_carbon_kg"],".3f"),"柔性负荷的碳排变化_kg":format(a["flex_carbon_kg"],".3f"),
          "碳排变化含义":"正值为增加，负值为减少。电池与柔性负荷按各小时电量和场景碳因子分别核算。",
          "模型保障岸电量_kWh":format(a["mandatory_model_shore_kwh"],".2f"),"三个指标当周均严格改善":r["all_three_improved"],
          "周末SOC误差":a["terminal_soc_error"],"周末待补电量_kWh":a["terminal_queue_kwh"],"保护违规次数":a["guardrail_violations"],
          "适用边界":r["scope"],"现场权限":False,"回执":r["receipt_sha256"]}
    if "twin_readback" in r:info["独立TwinLab在线重放"]=r["twin_readback"]
    else:info["复核来源"]="已冻结的本地回执"
    if "hourly" in r:
        h=r["hourly"]
        info["所查小时"]=h
        info["小时计量显示"]={"窗口内第几小时":h["hour"]+1,"零基索引":h["hour"],"输入电网功率_kW":format(h["pcc_kw"],".2f"),
                          "电池功率_kW":format(h["bess_kw"],".2f"),"柔性负荷变化_kW":format(h["flex_kw"],".2f"),
                          "SOC_百分数":format(100*h["soc"],".2f")}
    return info
