"""Replay a bimonthly TEU projection from the local signed-off data snapshot."""
import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
from forecast import Forecaster

HERE=Path(__file__).resolve().parent


def main(argv):
    p=argparse.ArgumentParser(description="按已发布公报复算双月集装箱吞吐量（TEU）。")
    p.add_argument("site",choices=("shanghai","ningbo","singapore"))
    p.add_argument("--target",default="2027-01-01",help="目标双月第一天，须为奇数月1日")
    p.add_argument("--as-of",default="2026-11-09",help="预测签发日期")
    args=p.parse_args(argv)
    try:
        start,issue=(date.fromisoformat(x) for x in (args.target,args.as_of))
    except ValueError: p.error("日期格式应为 YYYY-MM-DD")
    if start.isoformat()!=args.target or issue.isoformat()!=args.as_of: p.error("请输入完整日期")
    if start.day!=1 or start.month%2!=1: p.error("目标须为奇数月第一天")
    if not "2025-01-01"<=args.as_of<="2026-11-09": p.error("超出模型选定后至数据快照日的可复算区间")
    if not 0<=(start-issue).days<=62:p.error("签发日须在目标首日或之前62天内")
    raw=(HERE/"data.json").read_bytes()
    if sha256(raw).hexdigest()!="fe4b9ead68bb2d7f6d44b2a304b3b0267af8c104c36e9d92454dbd9c4d6a62a9":raise ValueError("统计快照完整性校验失败")
    data=json.loads(raw)
    obs=[r for r in data["observations"] if r["site"]==args.site]
    model=Forecaster(obs);res=model.predict(args.target,args.as_of)
    if res is None:p.error("缺少可用的历史同期")
    method=data["selected"][args.site]
    print(json.dumps(dict(site=args.site,target=args.target,as_of=args.as_of,unit="TEU",
        scope="two_calendar_months",method=method,forecast_teu=round(res["pred"][method]),
        inputs=res["inputs"],latest_input=res["latest_input"],latest_available=res["latest_available"],
        alternatives={k:round(v) for k,v in res["pred"].items()},snapshot_sha256=sha256(raw).hexdigest()),
        ensure_ascii=False,indent=2))


if __name__=="__main__":
    args=sys.argv[1:]
    main(args[1:] if args[:1] and args[0].lower()=="throughput" else args)
