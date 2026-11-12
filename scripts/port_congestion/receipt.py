import argparse,json,sys
from hashlib import sha256
from pathlib import Path
CASES=("savannah","lalb","other","national","forward")
def get(case,path,pin):
    b=path.read_bytes()
    if sha256(b).hexdigest()!=pin:raise ValueError("拥堵证据摘要校验失败")
    return json.loads(b)[case]
if __name__=="__main__":
    from queue_pin import SHA
    args=sys.argv[1:];p=argparse.ArgumentParser();p.add_argument("case",choices=CASES)
    print(json.dumps(get(p.parse_args(args[1:] if args[:1]==["congestion"] else args).case,Path(__file__).with_name("evidence.json"),SHA),ensure_ascii=False,indent=2))
