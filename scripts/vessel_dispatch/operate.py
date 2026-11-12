"""Read a recorded schedule or compute a new retrospective plan using installed local inputs."""
import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
APP=HERE.parents[1]
sys.path.insert(0,str(APP))
from app.vessel_review import VesselQuery,review_plan


def simulate(day,scenario,recipe_seed=None):
    import torch
    from dispatch import Actor,Schedule,gates,hashfile,measures,read,sandbox
    from integrations.shanghai_lab_v1.data import digest,make_case,verified_dataset
    from integrations.shanghai_lab_v1.planning import strong_reference
    manifest=read(HERE/"policy.json")
    if hashfile(HERE/"actor.pt")!=manifest["weight_sha256"]:raise ValueError("策略权重校验失败")
    dataset=verified_dataset()
    if digest(dataset[0])!=manifest["dataset_sha256"]:raise ValueError("上海数据版本不匹配")
    from repair_runtime import REPAIR_DATES,TEST_RECIPE_SEED
    if recipe_seed is None:recipe_seed=TEST_RECIPE_SEED if day in REPAIR_DATES else 903
    case=make_case(day,scenario,recipe_seed,dataset=dataset)
    model=Actor();model.load_state_dict(torch.load(HERE/"actor.pt",weights_only=True));model.eval()
    with sandbox() as engine:
        reference=engine(case)
        if not reference.get("review",{}).get("reviewed"):raise ValueError("沙盘基线未产生完整排程："+reference.get("error",""))
        base=measures(case,reference["plan"])
        outputs={"native":{"plan":reference["plan"],"metrics":base,"native_review":reference["review"]}}
        with torch.inference_mode():p=Schedule(case).run(model,"trained")[0]
        from repair_runtime import proposals,WEIGHT_SHA
        repair_plans=proposals(case,reference["plan"])
        for method in ("trained","repair","repair_greedy","milp"):
            try:
                if method=="milp":p=strong_reference(case,service_limits=base,seconds=1)
                if method in repair_plans:p=repair_plans[method][0]
                receipt=engine(case,p)
                if "review" not in receipt:raise ValueError(receipt["error"])
                metric=measures(case,p);checks=gates(metric,base)
                outputs[method]={"plan":p,"metrics":metric,"checks":checks,"eligible":all(checks.values()),"native_review":receipt["review"]}
                if method in repair_plans:
                    outputs[method]["steps"]=repair_plans[method][1]
                    outputs[method]["method_weight_sha256"]=WEIGHT_SHA if method=="repair" else None
            except ValueError as e:
                outputs[method]={"eligible":False,"reason":str(e)}
        candidates=["native"]+[m for m in ("trained","repair","repair_greedy","milp") if outputs[m]["eligible"]]
        selected=min(candidates,key=lambda m:outputs[m]["metrics"]["objective_cny"])
        return {"schema":"gullmate.vessel-simulation.v1","day":day,"scenario":scenario,"selected":selected,"recipe_seed":recipe_seed,"methods":outputs,
                "snapshot_sha256":case["snapshot_sha256"],"weight_sha256":manifest["weight_sha256"],"production_authority":False,
                "scope":"回顾性上海工程仿真，选择通过所有服务门槛且目标成本最低的已校验方案，未下发排程。"}


def main():
    parser=argparse.ArgumentParser(description="上海港逐船靠泊计划的历史复核与离线试算")
    parser.add_argument("day",type=date.fromisoformat)
    parser.add_argument("--scenario",choices=["normal","arrival_surge","berth_outage","grid_derating","weather_closure"],default="normal")
    group=parser.add_mutually_exclusive_group()
    group.add_argument("--method",choices=["trained","untrained","immediate_cost","milp","native","repair","repair_greedy","repair_untrained"])
    group.add_argument("--simulate",action="store_true",help="重新计算该 2025 年日期的受训策略、沙盘基线和 MILP，复核后选择")
    parser.add_argument("--recipe-seed",type=int,help="覆盖工程船期种子，仅用于 --simulate")
    parser.add_argument("--json",action="store_true")
    args=sys.argv[1:]
    if args and args[0].lower()=="vessels":args=args[1:]
    a=parser.parse_args(args)
    if a.recipe_seed is not None and not a.simulate:parser.error("--recipe-seed 仅用于 --simulate")
    try:
        r=simulate(a.day.isoformat(),a.scenario,a.recipe_seed) if a.simulate else review_plan(VesselQuery(day=a.day,scenario=a.scenario,method=a.method or "trained"))
    except (ValueError,OSError) as e:parser.exit(2,"船舶调度复核失败："+str(e)+"\n")
    if a.json:print(json.dumps(r,ensure_ascii=False,indent=2));return
    if a.simulate:
        selected=r["selected"];m=r["methods"][selected];rows=m["plan"]["scheduled"];metrics=m["metrics"]
        print("本地试算",a.day,a.scenario,"船期种子",r["recipe_seed"],"采用",selected)
    else:
        rows=r["schedule"];metrics=r["metrics"]
        print("冻结回执",a.day,a.scenario,r["method"],"达到改进门槛" if r["eligible_improvement"] else "未达到严格改进门槛")
    print(f'等待 {metrics["wait_vessel_hours"]} 船时，逾期 {metrics["late_vessel_hours"]} 船时，目标成本 {metrics["objective_cny"]:.2f} 元。')
    for v in rows:print(f'{v["job_id"]}　泊位 {v["berth"]+1}　{v["start_hour"]:02d}:00–{v["end_hour"]:02d}:00')
    print(r["scope"])


if __name__=="__main__":main()
