"""Authenticated, read-only Har­ness evidence for forecast and dispatch work orders."""
from datetime import date,timedelta
from hashlib import sha256
import json
import math
from typing import Literal
from urllib.error import HTTPError,URLError
from urllib.request import HTTPRedirectHandler,ProxyHandler,build_opener

from pydantic import Field
from app.config import WEB_DIR
from app.cooperative_review import checked
from app.harness.contracts import StrictModel,digest

ROOT=WEB_DIR/"policy-evidence/external-load"
INDEX="52f010bde54361fe54fa2c9458cf0dfa205615d3f486846813750dab4a586547"
WEIGHT="1cedb00d486f4e7cd9f318242a52c120f4b851b7545de711915cf9d899c6b1bc"
NAMES=("forecast.port_load","dispatch.tariff_week","evidence.match_scope")
CASES=Literal["shanghai","industrial_mix","industrial_mix_price_shift","phase_minus3","phase_plus6","week_switch","unlisted_tariff"]
LABELS={"shanghai":"上海原负荷原电价","industrial_mix":"工业混合负荷原电价","industrial_mix_price_shift":"工业混合负荷，电价延后 4 小时",
        "phase_minus3":"电价提前 3 小时","phase_plus6":"电价延后 6 小时","week_switch":"周内切换电价时段","unlisted_tariff":"未知电价表"}


class ForecastRequest(StrictModel):
    site:Literal["shanghai","funchal","industrial_mix"]
    day:date
    source:Literal["archive","twin"]="archive"


class DispatchRequest(StrictModel):
    scenario:CASES
    week:date
    source:Literal["archive","twin"]="archive"


class MatchRequest(StrictModel):
    forecast_ref:str=Field(pattern=r"^T[1-9][0-9]*$")
    dispatch_ref:str=Field(pattern=r"^T[1-9][0-9]*$")


class Unavailable(ValueError):
    """This registered read can be retried after the official service is reachable."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def remote(path):
    url="http://127.0.0.1:8000"+path
    try:
        with build_opener(ProxyHandler({}),NoRedirect()).open(url,timeout=85) as response:
            body=response.read(1_500_001)
    except HTTPError as e:
        if e.code in (429,502,503,504):raise Unavailable("TwinLab 暂不可用，恢复后按同一范围重试") from e
        raise ValueError(f"TwinLab 未接受所请求的登记范围（HTTP {e.code}）") from e
    except (URLError,TimeoutError,OSError) as e:raise Unavailable("TwinLab 当前无法连接，须等待原生服务恢复") from e
    if len(body)>1_500_000:raise ValueError("孪生返回超过登记大小")
    return json.loads(body),sha256(body).hexdigest()


def frozen(group,key,day):
    meta=checked(ROOT/"index.json",INDEX,160000)[group][key]
    rows=checked(ROOT/f"{group}-{key}.json",meta["sha"],1_500_000)
    return next((r for r in rows if r["day"]==day),None),meta["sha"]


def near(a,b):
    return type(a) in (int,float) and type(b) in (int,float) and math.isfinite(a) and math.isfinite(b) and math.isclose(a,b,abs_tol=1e-6,rel_tol=0)


def forecast(q):
    day=q.day.isoformat();key={"shanghai":"fresh_shanghai","funchal":"funchal_same_period","industrial_mix":"industrial_mix"}[q.site]
    row,seal=frozen("forecast",key,day);cross=False
    if q.source=="archive":
        if row is None:raise ValueError("该日期没有已登记的日前回执")
        peak=row["day_peak"];curve=row["center_peak"];last=row["last_feedback_day"]
    else:
        if q.site=="industrial_mix":raise ValueError("叠加工况的日前预测只登记了工程归档，在线端点没有该站点")
        obj,seal=remote(f"/api/forecast/port-load/{q.site}/{day}?assess_peak=true")
        if obj.get("day")!=day or obj.get("site")!=q.site or obj.get("production_authority") is not False or len(obj.get("hours",[]))!=24:
            raise ValueError("原生预测回执范围不符")
        p=obj["peak_assessment"];peak=p["daily_peak_kw"];curve=p["curve_max_kw"];last=p["last_feedback_day"]
        if p["peak_time"] is not None or not near(curve,max(h["p50"] for h in obj["hours"])):raise ValueError("原生峰值口径不符")
        if row is not None:
            cross=near(peak,row["day_peak"]) and near(curve,row["center_peak"]) and last==row["last_feedback_day"] and all(near(v["p50"],k) for v,k in zip(obj["hours"],row["center"],strict=True))
            if not cross:raise ValueError("原生预测与同日归档有差异")
    return {"schema":"operations.forecast.v1","site":q.site,"day":day,"source":q.source,"archive_match":cross,"archive_exists":row is not None,"receipt_sha256":seal,
            "peak_kw":peak,"curve_peak_kw":curve,"last_feedback_day":last,"hours":24,"production_authority":False,
            "data_kind":"公开港口电表回放" if q.site=="funchal" else "上海工程负荷与外部扰动" if q.site=="industrial_mix" else "上海月度统计与气象重构负荷"}


def dispatch(q):
    week=q.week.isoformat();row,seal=frozen("control",q.scenario,week);cross=False
    if q.source=="archive":
        if row is None:raise ValueError("该周不是冻结回执起点")
        v=row["policies"]["adaptive_clock"];saving=v["vs_original"][0];idle=v["vs_idle"][0];safe=v["safe"]
        plans=row["tariff_plans"]
    else:
        obj,seal=remote(f"/api/forecast/external-load/{q.scenario}/{week}")
        if obj.get("case")!=q.scenario or obj.get("week")!=week or obj.get("production_authority") is not False or obj.get("weight")!=WEIGHT:
            raise ValueError("原生周回执日期、权重或权限不符")
        a=obj["records"];r=a["adaptive_clock"];m=r["metrics"];hh=r["hourly"];plans=r["plans"]
        if len(hh)!=168 or len(a["original"]["hourly"])!=168 or len(plans)!=8:raise ValueError("原生控制回放不完整")
        saving=a["original"]["metrics"]["total_cost_cny"]-m["total_cost_cny"];idle=a["idle"]["metrics"]["total_cost_cny"]-m["total_cost_cny"]
        safe=(abs(m["terminal_soc_error"])<1e-7 and abs(m["terminal_flex_backlog_kwh"])<1e-7 and m["guardrail_violations"]==0 and
              all(max(abs(float(v)) for v in line[8:13])<1e-7 for line in hh))
        if row is not None:
            v=row["policies"]["adaptive_clock"]
            cross=(near(saving,v["vs_original"][0]) and near(idle,v["vs_idle"][0]) and v["safe"]==safe and plans==row["tariff_plans"]
                   and all(all(near(x,y) for x,y in zip((o[3],c[3],c[5],c[4]),f,strict=True)) for o,c,f in zip(a["original"]["hourly"],hh,row["hours"],strict=True)))
            if not cross:raise ValueError("原生控制与冻结周回执不一致")
    return {"schema":"operations.dispatch.v1","week":week,"scenario":q.scenario,"site":"shanghai" if q.scenario=="shanghai" else "industrial_mix",
            "source":q.source,"receipt_sha256":seal,"weight":WEIGHT,"archive_match":cross,"archive_exists":row is not None,"hours":168,
            "saved_vs_original_cny":saving,"saved_vs_idle_cny":idle,"safe":safe,"fallbacks":sum(bool(p["fallback"]) for p in plans),"production_authority":False}


def committed(task,store,ref,name):
    record=next((r for r in task["results"] if r["id"]==ref and r["ok"] and r["tool"]==name),None)
    if record is None:raise ValueError("引用必须是本工单成功的 "+name+" 工具结果")
    a=store.artifact(task["id"],record["artifact"])
    if not a or a["sha256"]!=record["sha256"] or digest(a["content"])!=a["sha256"]:raise ValueError("所引工件完整性校验失败")
    return json.loads(a["content"]),record["sha256"]


def reconcile(q,task,store):
    f,fs=committed(task,store,q.forecast_ref,NAMES[0]);d,ds=committed(task,store,q.dispatch_ref,NAMES[1])
    start=date.fromisoformat(d["week"]);day=date.fromisoformat(f["day"])
    contains=start<=day<start+timedelta(days=7);same=f["site"]==d["site"]
    return {"schema":"operations.match.v1","forecast_ref":q.forecast_ref,"dispatch_ref":q.dispatch_ref,"parent_sha256":[fs,ds],
            "day":f["day"],"week":d["week"],"forecast_site":f["site"],"scenario":d["scenario"],"forecast_source":f["source"],
            "dispatch_source":d["source"],"within_week":contains,"same_load":same,"scope_matches":contains and same,
            "peak_kw":f["peak_kw"],"saved_vs_original_cny":d["saved_vs_original_cny"],"fallbacks":d["fallbacks"],
            "dispatch_archive_exists":d.get("archive_exists",True if d["source"]=="archive" or d["archive_match"] else None),
            "causal_attribution_verified":False,"production_authority":False}


def compact(r):
    if "error" in r:return {"error":r["error"],"依赖":r.get("retryable_dependency")}
    source={"twin":"本次官方 TwinLab HTTP 原生重算","archive":"已冻结的研究回执"}
    if r["schema"]=="operations.forecast.v1":
        return {"港区":r["site"],"预测日UTC":r["day"],"独立日峰_kW":format(r["peak_kw"],".2f"),"小时中心曲线最大_kW":format(r["curve_peak_kw"],".2f"),
                "小时数":24,"数据口径":r["data_kind"],"读取来源":source[r["source"]],"已比对冻结回执":r["archive_match"],"现场权限":False}
    if r["schema"]=="operations.dispatch.v1":
        return {"工况":r["scenario"],"工况说明":LABELS[r["scenario"]],"周起点UTC":r["week"],"相对原策略节省_元":format(r["saved_vs_original_cny"],".2f"),
                "相对原策略的费用方向":("多花" if r["saved_vs_original_cny"]<0 else "节省")+format(abs(r["saved_vs_original_cny"]),".2f")+"元",
                "相对待机节省_元":format(r["saved_vs_idle_cny"],".2f"),"退到待机段数":r["fallbacks"],"小时数":168,
                "正负含义":"正数为省钱，负数为增加费用","仿真保护通过":r["safe"],"读取来源":source[r["source"]],"已比对冻结回执":r["archive_match"],
                "存在同日起点冻结周回执":r.get("archive_exists",True if r["source"]=="archive" or r["archive_match"] else None),"现场权限":False}
    return {"两份原件":[r["forecast_ref"],r["dispatch_ref"]],"预测日":r["day"],"周起点":r["week"],"工况":r["scenario"],"工况说明":LABELS[r["scenario"]],"预测负荷来源":r["forecast_site"],
            "日期在周内":r["within_week"],"负荷口径相同":r["same_load"],"允许同口径并列复核":r["scope_matches"],
            "日峰_kW":format(r["peak_kw"],".2f"),"较原策略节省_元":format(r["saved_vs_original_cny"],".2f"),
            "较原策略的费用方向":("多花" if r["saved_vs_original_cny"]<0 else "节省")+format(abs(r["saved_vs_original_cny"]),".2f")+"元",
            "峰值来源":source[r["forecast_source"]],"账单来源":source[r["dispatch_source"]],"存在同日起点冻结周回执":r.get("dispatch_archive_exists"),
            "因果归因验证":False,"现场权限":False}
