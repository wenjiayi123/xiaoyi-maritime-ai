import argparse
import json
from pathlib import Path
import sys
from operator_core import read_bundle,quote,plan


def main(args):
    p=argparse.ArgumentParser(description="用本机冻结的四港模型估计到港时间、试排泊位")
    sub=p.add_subparsers(dest="action",required=True)
    q=sub.add_parser("quote");q.add_argument("port");q.add_argument("--eta",required=True)
    q.add_argument("--updated",required=True);q.add_argument("--as-of",required=True)
    q.add_argument("--imo",type=int);q.add_argument("--kind",type=int)
    s=sub.add_parser("plan");s.add_argument("file",type=Path)
    sub.add_parser("report")
    opt=p.parse_args(args);data=read_bundle()
    try:
        if opt.action=="quote":result=quote(data,{k:v for k,v in vars(opt).items() if k!="action"})
        elif opt.action=="plan":result=plan(data,json.loads(opt.file.read_text(encoding="utf-8-sig")))
        else:result=data["summary"]
    except (OSError,ValueError,TypeError,OverflowError) as e:p.error(str(e))
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=="__main__":
    args=sys.argv[1:];main(args[1:] if args and args[0].lower()=="arrivals" else args)
