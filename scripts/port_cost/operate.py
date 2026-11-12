"""Pure standard library: finite, signed-scope, read-only financial receipts."""
import argparse,json,sys
from hashlib import sha256
from pathlib import Path
def read_receipt(case):
    from cost_pin import SHA
    b=Path(__file__).with_name("evidence.json").read_bytes()
    if sha256(b).hexdigest()!=SHA:raise ValueError("运营费用核对失败")
    return json.loads(b)[case]
def main():
    a=sys.argv[1:];a=a[1:] if a[:1]==["port-cost"] else a;p=argparse.ArgumentParser()
    p.add_argument("case",choices=["budget2024","budget2025","bridge2025","history"]);args=p.parse_args(a)
    print(json.dumps(read_receipt(args.case),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
