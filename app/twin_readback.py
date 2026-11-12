"""Compare the official loopback TwinLab reply to the original content-addressed weekly receipt."""
import json
import math
from urllib.error import HTTPError,URLError
from urllib.request import HTTPRedirectHandler,ProxyHandler,build_opener

BASE="http://127.0.0.1:8000/api/rl/shore-storage/weekly/"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def check_response(source,live):
    if (live.get("schema")!="twin.shore-storage-week.v1" or live.get("week")!=source["week"] or live.get("part")!=source["part"]
            or live.get("weight_sha256")!=source["weight"] or live.get("production_authority") is not False or live.get("hours")!=168):
        raise ValueError("TwinLab 回执日期、分区、权重、完整度或权限不符")
    comparisons=[]
    for method,group in (("idle","baseline"),("selected","candidate"),("best_fixed","fixed")):
        for key,expected in source[group].items():
            comparisons.append((f"{method}.{key}",expected,live["methods"][method][key]))
    a=source["audited"]
    comparisons.extend((f"carbon.{k}",a[field],live["carbon_delta_by_component"][k]) for k,field in (
        ("battery_kg","battery_carbon_kg"),("flex_kg","flex_carbon_kg")))
    comparisons.extend((k,a[k],live["methods"]["selected"][raw]) for k,raw in (
        ("terminal_soc_error","terminal_soc_error"),("terminal_queue_kwh","terminal_flex_backlog_kwh"),("guardrail_violations","guardrail_violations")))
    for field,expected,actual in comparisons:
        if type(actual) not in (int,float) or not math.isfinite(actual) or not math.isclose(expected,actual,rel_tol=0.,abs_tol=1e-6):
            raise ValueError("TwinLab 原生结果与冻结回执不符："+field)
    return {"verified":True,"source":"TwinLab localhost:8000","fields":len(comparisons),"hours":168,
            "week":source["week"],"weight_sha256":live["weight_sha256"],"production_authority":False}


def compare_with_twin(source):
    opener=build_opener(ProxyHandler({}),NoRedirect())
    try:
        with opener.open(BASE+source["week"],timeout=85) as response:raw=response.read(100_001)
    except HTTPError as exc:raise ValueError("TwinLab 返回 HTTP "+str(exc.code)) from exc
    except (URLError,OSError) as exc:raise ValueError("TwinLab 当前无法连接；仍可单独查验已冻结的周回执") from exc
    if len(raw)>100_000:raise ValueError("TwinLab 回执超过预期大小")
    try:return check_response(source,json.loads(raw))
    except (KeyError,TypeError,json.JSONDecodeError) as exc:raise ValueError("TwinLab 周回执格式不符") from exc
