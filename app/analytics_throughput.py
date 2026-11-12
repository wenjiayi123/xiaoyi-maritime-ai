import csv
from datetime import date,timedelta
from decimal import Decimal,ROUND_HALF_UP
from functools import lru_cache
from hashlib import sha256
import io,json
from pathlib import Path
import re
from typing import Literal
from fastapi import APIRouter,HTTPException,Query
from fastapi.responses import Response
from app.throughput_ui_pin import SHA

router=APIRouter(prefix="/api/analytics/throughput",tags=["集装箱吞吐量"])
Unit=Literal["TEU","10k_TEU"]
Port=Literal["shanghai","ningbo","singapore"]
PORTS={"shanghai":["上海","Shanghai"],"ningbo":["宁波舟山","Ningbo-Zhoushan"],"singapore":["新加坡","Singapore"]}


@lru_cache(maxsize=1)
def data():
    raw=(Path(__file__).resolve().parents[1]/"data/analytics-throughput/periods.json").read_bytes()
    if sha256(raw).hexdigest()!=SHA:raise HTTPException(503,"吞吐量快照校验失败 / Snapshot failed verification")
    obj=json.loads(raw);by_port={p:{} for p in PORTS}
    for row in obj["records"]:by_port[row["port"]][row["start"]]=row
    return obj,by_port


def add_months(start,count):
    n=start.year*12+start.month-1+count
    return date(n//12,n%12+1,1)


def amount(n,unit):
    return str(n) if unit=="TEU" else format(Decimal(n)/10000,"f")


def window(port,first,months,unit):
    if not re.fullmatch(r"[0-9]{4}-(?:01|03|05|07|09|11)",first) or not 1900<=int(first[:4])<=2100:
        raise HTTPException(422,"从已登记双月的首月开始 / Choose an odd-numbered starting month")
    start=date.fromisoformat(first+"-01");source,index=data();rows=[]
    for offset in range(0,months,2):
        at=add_months(start,offset).isoformat()[:7]
        if at not in index[port]:raise HTTPException(422,"缺少已登记实绩 / Missing observed period: "+at)
        row=index[port][at]
        rows.append({"start":at,"end":(add_months(start,offset+2)-timedelta(days=1)).isoformat(),
                     "teu":row["teu"],"display":amount(row["teu"],unit),
                     "sources":[{"sha256":h,**source["sources"][h]} for h in row["sources"]]})
    total=sum(x["teu"] for x in rows)
    return {"start":first,"end":rows[-1]["end"],"teu":total,"display":amount(total,unit),"rows":rows}


@router.get("/catalog")
def catalog():
    s,index=data()
    return {"snapshot":s["snapshot"],"sha256":SHA,"ports":{p:{"name":names,"periods":sorted(index[p])} for p,names in PORTS.items()}}


@router.get("/compare")
def compare(port:Port,base:str,current:str,months:int=2,unit:Unit="TEU"):
    if months not in (2,6,12):raise HTTPException(422,"可选 2、6 或 12 个月")
    a=window(port,base,months,unit);b=window(port,current,months,unit);diff=b["teu"]-a["teu"]
    pct=None if a["teu"]==0 else str((Decimal(diff)*100/Decimal(a["teu"])).quantize(Decimal(".01"),rounding=ROUND_HALF_UP))
    spec=[SHA,port,base,current,months,unit]
    return {"port":port,"name":PORTS[port],"unit":unit,"months":months,"base":a,"current":b,"delta_teu":diff,
            "delta":amount(diff,unit),"percent":pct,"overlap":not(a["end"]<current+"-01" or b["end"]<base+"-01"),
            "snapshot":data()[0]["snapshot"],"comparison_sha":sha256(json.dumps(spec,separators=(",",":")).encode()).hexdigest()}


@router.get("/download")
def download(port:Port,base:str,current:str,months:int=2,unit:Unit="TEU",comparison_sha:str=Query(min_length=64,max_length=64)):
    q=compare(port,base,current,months,unit)
    if q["comparison_sha"]!=comparison_sha:raise HTTPException(409,"筛选或来源已变化，请重新比较 / Re-run this comparison")
    buf=io.StringIO(newline="")
    writer=csv.writer(buf)
    writer.writerow(["record","port","from","through","observed_TEU","display_value","display_unit","percent_change","source_urls","source_sha256","snapshot","comparison_sha"])
    def line(kind,start,end,total,value,pct="",sources=()):
        writer.writerow([kind,port,start,end,total,value,unit,pct," | ".join(s["download"] for s in sources)," | ".join(s["sha256"] for s in sources),q["snapshot"],comparison_sha])
    for name in ("base","current"):
        w=q[name];line(name+"_total",w["start"],w["end"],w["teu"],w["display"])
        for r in w["rows"]:line(name+"_period",r["start"],r["end"],r["teu"],r["display"],sources=r["sources"])
    line("current_minus_base",current,q["current"]["end"],q["delta_teu"],q["delta"],q["percent"])
    filename=f"throughput-{port}-{base}-{current}-{months}m-{unit}.csv"
    return Response(buf.getvalue().encode("utf-8-sig"),media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":f'attachment; filename="{filename}"',"X-Comparison-SHA256":comparison_sha})
