"""Read-only standard-library CLI for the sealed port GHG forecasts. Never mutates a forecast."""
import argparse,hashlib,json,sys
from pathlib import Path
def evidence():
    from carbon_pin import SHA
    b=Path(__file__).with_name("evidence.json").read_bytes()
    if hashlib.sha256(b).hexdigest()!=SHA:raise ValueError("洛杉矶碳排归档校验失败")
    return json.loads(b)
def main():
    args=sys.argv[1:];args=args[1:] if args[:1]==["port-carbon"] else args
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="action",required=True);sub.add_parser("compare");sub.add_parser("forward")
    one=sub.add_parser("year");one.add_argument("year",type=int,choices=range(2021,2026));v=p.parse_args(args);data=evidence()
    print(json.dumps(data[str(v.year) if v.action=="year" else v.action],ensure_ascii=False,indent=2))
if __name__=="__main__":
    try:main()
    except (ValueError,OSError) as e:print(str(e),file=sys.stderr);sys.exit(2)
