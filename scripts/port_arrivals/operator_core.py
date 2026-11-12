"""Produce an ETA advisory or a hypothetical capacity reservation from a frozen local snapshot."""
from datetime import datetime,timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from model import predict
from reservation import reserve

HERE=Path(__file__).resolve().parent


def read_bundle():
    b=(HERE/"bundle.json").read_bytes()
    if sha256(b).hexdigest()!="94fac31433932376c728256f7531d11c20d8af6543d2fefa7e3e3b8d2ac7acae":raise ValueError("到港模型或泊位目录的校验和不符")
    return json.loads(b)


def time_value(s):
    try:d=datetime.fromisoformat(s)
    except (ValueError,TypeError):raise ValueError("日期时间需要 ISO 8601 格式并带时区") from None
    if d.tzinfo is None:raise ValueError("日期时间需要时区")
    return d.timestamp()/60


def utc(n):
    return datetime.fromtimestamp(n*60,timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")


def quote(data,row):
    if not isinstance(row,dict) or set(row)-{"port","eta","updated","as_of","imo","kind","call"}:
        raise ValueError("包含未知输入字段")
    required={"port","eta","updated","as_of"}
    if required-row.keys():raise ValueError("缺少港口、申报 ETA、更新时间或签发时间")
    port=row["port"]
    if not isinstance(port,str) or port not in data["deployment"]:raise ValueError("未登记该港口")
    eta,known,issue=[time_value(row[k]) for k in ("eta","updated","as_of")]
    if known>issue or issue>eta:raise ValueError("须满足申报更新时间 ≤ 签发时间 ≤ 申报 ETA")
    if issue<time_value(data["release_utc"]):raise ValueError("该版本尚未发布，历史评测请查看封存记录")
    imo=row.get("imo");kind=row.get("kind")
    if imo is not None and (type(imo) is not int or not 1000000<=imo<=9999999):raise ValueError("IMO 应为七位整数")
    if kind is not None and (type(kind) is not int or not 0<=kind<=999):raise ValueError("船型代码应为非负整数")
    # The study's decision point was six hours before declaration. Later revisions or earlier issues retain the declaration.
    at_horizon=known<=eta-360 and issue>=eta-360
    method=data["deployment"][port] if at_horizon else "declared"
    predicted=predict(data["weights"],port,imo,kind,eta)[method]
    valid_prediction=predicted>=issue
    limits=data["intervals"][port][method] if at_horizon and valid_prediction else None
    key=f"{port}|{imo}"
    options=data["berths"].get(key,[])
    return dict(port=port,imo=imo,kind=kind,as_of=utc(issue),declared_eta=utc(eta),method=method,
                predicted_eta=utc(predicted) if valid_prediction else None,
                six_hour_basis_utc=utc(eta-360) if at_horizon else None,
                historical_interval_80_utc=[utc(predicted+x) for x in limits] if limits else None,
                status="available" if valid_prediction else "check_arrival_status",
                berth_options=options,berth_scope="historical_use_only",production_control=False)


def plan(data,rows):
    if not isinstance(rows,list) or not 1<=len(rows)<=1000:raise ValueError("工单需包含 1 到 1000 个航次")
    requests=[];by_id={};declined=[]
    for row in rows:
        q=quote(data,row)
        call=row.get("call")
        if type(call) is not int or call<=0 or call in by_id:raise ValueError("航次编号应为不重复的正整数")
        by_id[call]=q
        if not q["berth_options"] or q["status"]!="available":
            declined.append(call)
            continue
        requests.append(dict(call=call,port=q["port"],imo=q["imo"],issue=time_value(q["as_of"]),
                             eta=time_value(q["declared_eta"])))
    # The tested mean occupancy delay did not support replacing the raw, fixed-berth reference.
    bookings=reserve(requests,data["berths"],corrected=False,flexible=False)
    return dict(turnaround_minutes=10,reservations=[dict(call=i,port=v["port"],berth=v["berth"],
                     start=utc(v["start"]),end=utc(v["end"])) for i,v in bookings.items()],
                needs_manual_check=declined,other_traffic_included=False,production_control=False)
