"""Read an integrity-checked daily vessel schedule without loading a simulator or model."""
from datetime import date
from pathlib import Path
from typing import Literal
from pydantic import BaseModel,ConfigDict
from app.config import WEB_DIR
from app.cooperative_review import checked

DIRECTORY=WEB_DIR/"policy-evidence/shanghai-vessel-dispatch"
INDEX_SHA="2f1d51ec05a242f3eec24255082284862ab8ac179e16aec58a1975ee72926d52"


class VesselQuery(BaseModel):
    model_config=ConfigDict(extra="forbid")
    day: date
    scenario: Literal["normal","arrival_surge","berth_outage","grid_derating","weather_closure"]="normal"
    method: Literal["trained","untrained","immediate_cost","milp","native","repair","repair_greedy","repair_untrained"]="trained"


def review_plan(query:VesselQuery):
    index=checked(DIRECTORY/"index.json",INDEX_SHA,100_000)
    stamp=query.day.isoformat()
    directory=DIRECTORY
    repair=False
    if stamp not in index["dates"]:
        directory=DIRECTORY.parent/"shanghai-vessel-repair"
        extra=checked(directory/"index.json","4e1ecf0d410339620fb9a2090bc21cc0849814ddad559e55ed7911b53c46a6ee",100_000)
        if stamp not in extra["dates"]:raise ValueError("该日期没有留出评测回执。可用日期 "+", ".join(sorted(index["dates"]+extra["dates"])))
        index=extra
        repair=True
    if query.method not in index["summary"]:raise ValueError("该日期没有评测此方法；可用方法 "+", ".join(index["summary"]))
    key=query.scenario+"/"+stamp
    digest=index["receipts"][key]
    day=checked(directory/(key+".json"),digest,500_000)
    if (day["date"]!=stamp or day["scenario"]!=query.scenario or day["production_authority"] is not False or
            day["weight_sha256"]!=index["weight_sha256"]):raise ValueError("船期、工况、权重或权限不匹配")
    m=day["methods"][query.method]
    if len({v["job_id"] for v in m["scheduled"]})!=len(day["jobs"]) or not m["verified"]:
        raise ValueError("回执未覆盖全部船舶或未经原生复核")
    return {"schema":"gullmate.vessel-review.v1","day":stamp,"scenario":query.scenario,"method":query.method,
            **({"repair_steps":m.get("steps",[]),"retained_step":m.get("retained_step",0),
                "native_at_solver_bound":day["native_at_bound"],"solver_lower_bound_cny":day["solver_lower_bound"],
                "method_weight_sha256":index["weight_sha256"] if query.method=="repair" else index["construction_sha256"] if query.method=="trained" else None} if repair else {}),
            "jobs":day["jobs"],"schedule":m["scheduled"],"metrics":m["metrics"],"baseline":day["methods"]["native"]["metrics"],
            "checks":m["checks"],"eligible_improvement":m["eligible"],"receipt_sha256":digest,"weight_sha256":index["weight_sha256"],
            "snapshot_sha256":day["snapshot_sha256"],"production_authority":False,
            "scope":"上海港公开日数据锚定的回顾性工程排程。逐船身份、需求、工时与资源为工程补足。"}
