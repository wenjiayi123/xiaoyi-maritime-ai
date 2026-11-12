import argparse
from datetime import date
import json
from pathlib import Path
import subprocess
import sys

APP=Path(__file__).resolve().parents[1];DEPLOY=APP.parents[1]
sys.path.insert(0,str(APP))
from app.shore_evidence import ShoreQuery,review_shore


def main():
    p=argparse.ArgumentParser(description="舷鸥 · 岸电储能历史复核与原生试算")
    scope=p.add_mutually_exclusive_group(required=True)
    scope.add_argument("--week",type=date.fromisoformat,help="UTC 周窗口起点")
    scope.add_argument("--call",dest="call_id",help="独立岸电电表的工程船次编号")
    p.add_argument("--verify-twin",action="store_true",help="比对已运行的官方 TwinLab 原生 HTTP 回执")
    p.add_argument("--hour",type=int);p.add_argument("--simulate",action="store_true");p.add_argument("--json",action="store_true")
    args=sys.argv[1:];args=args[1:] if args and args[0].lower()=="shore" else args
    a=p.parse_args(args)
    if a.simulate and a.verify_twin:p.error("原生试算与在线读回复核只选一种")
    if a.simulate and (not a.week or a.hour is not None):p.error("原生试算需要整周日期")
    try:
        if a.simulate:
            r=subprocess.run([str(DEPLOY/"envs/twin/Scripts/python.exe"),"-X","utf8",str(DEPLOY/"apps/twin/scripts/gullmate_shore/infer_week.py"),a.week.isoformat()],
                             capture_output=True,encoding="utf-8",timeout=90)
            if r.returncode:p.exit(r.returncode,r.stderr)
            data=json.loads(r.stdout)
        else:data=review_shore(ShoreQuery(week=a.week,call_id=a.call_id,hour=a.hour,verify_twin=a.verify_twin))
    except (ValueError,OSError,subprocess.TimeoutExpired) as exc:p.exit(2,str(exc)+"\n")
    if a.json:print(json.dumps(data,ensure_ascii=False,indent=2));return
    if a.call_id:
        print(data["call"],data["berth"],data["eta"],"→",data["etd"])
        print(f'计入供电 {data["in_call_kwh"]:.3f} kWh，共 {data["samples"]} 条读数。')
    elif a.simulate:
        print(a.week,"原生试算",data["part"])
        for label,v in data["methods"].items():
            m=v["metrics"];print(f'{label}　成本 {m["total_cost_cny"]:.2f} 元，碳排 {m["carbon_kg"]:.2f} kg，峰值 {m["peak_kw"]:.2f} kW')
    else:
        s=data["audited"];print(a.week,data["part"],"配对变化（候选减待机）")
        print(f'成本 {s["cost_delta_cny"]:+.2f} 元，碳排 {s["carbon_delta_kg"]:+.3f} kg，峰值 {s["peak_delta_kw"]:+.2f} kW')
        print(f'电池碳排变化 {s["battery_carbon_kg"]:+.3f} kg，柔性负荷碳排变化 {s["flex_carbon_kg"]:+.3f} kg')
        if "hourly" in data:print(json.dumps(data["hourly"],ensure_ascii=False))
    if "twin_readback" in data:print("TwinLab 在线独立读回",data["twin_readback"]["fields"],"项相符。")
    print(data["scope"])


if __name__=="__main__":main()
