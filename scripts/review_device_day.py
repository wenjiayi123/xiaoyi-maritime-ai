"""Command-line reader for frozen business receipts. No HTTP service or inference process is required."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.cooperative_review import DeviceReview,inspect_day


def main():
    p=argparse.ArgumentParser(description="舷鸥 · 多岗位设备调配历史日复核")
    p.add_argument("day",help="冻结的评测日期，YYYY-MM-DD")
    p.add_argument("--baseline",choices=("fixed","mpc2"),required=True)
    p.add_argument("--demand",choices=("normal","stress"),required=True)
    p.add_argument("--method",choices=("trained","untrained_scores","minimum_cost","cranes_only","flex_only"),default="trained")
    p.add_argument("--json",action="store_true")
    argv=sys.argv[1:]
    if argv and argv[0].lower()=="devices":argv=argv[1:]
    args=p.parse_args(argv)
    try:result=inspect_day(DeviceReview(day=args.day,baseline=args.baseline,demand=args.demand,method=args.method))
    except (OSError,ValueError) as exc:p.exit(2,"设备策略复核失败："+str(exc)+"\n")
    if args.json:print(json.dumps(result,ensure_ascii=False,indent=2))
    else:
        print(args.day,args.baseline,args.demand,args.method)
        print("离线裁决",result["decision"],"　成本变化",f"{result['cost_change_pct']:+.2f}%")
        print("未过门槛",", ".join(result["failed"]) if result["failed"] else "无")
        cap=result["dr_capacity_review"]
        label={"no_event":"当日没有响应事件","incompatible_with_service":"响应门槛超出充电与冷链约束下的物理上界",
               "delivered":"达到最低响应交付","shortfall_undetermined":"响应交付不足，可行性仍待核查"}[cap["status"]]
        print("历史响应复核",label)
        if cap["status"]!="no_event":
            print(f'最低交付 {cap["required_kwh"]:.2f} kWh，实交 {cap["delivered_kwh"]:.2f} kWh，事后上界 {cap["upper_kwh"]:.3f} kWh')
        print("回执 SHA-256",result["receipt_sha256"])

if __name__=="__main__":main()
