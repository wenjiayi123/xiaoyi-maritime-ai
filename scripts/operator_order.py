"""Run a read-only model work order through XiaoYi, with a durable per-order task store."""
import argparse
from datetime import datetime,timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
from uuid import uuid4

APP=Path(__file__).resolve().parents[1]
DEPLOY=APP.parents[1]


def ready():
    try:
        with urlopen("http://127.0.0.1:8000/openapi.json",timeout=4) as r:
            if r.geturl()!="http://127.0.0.1:8000/openapi.json":return False
            content=r.read(4_000_001)
        return len(content)<=4_000_000 and "/api/forecast/external-load/{case}/{day}" in json.loads(content).get("paths",{})
    except (OSError,URLError,ValueError):return False


def run_order(a,api,folder,resident):
    from app.harness.operation_intent import menu
    route_file=folder/"resident-id.json"
    if a.action=="run":
        allowed=menu(a.goal) or ["systems.inspect","linked.observe","calculate","knowledge.search"]
        caps=api("GET","/capabilities")
        registered={t["name"]:t for t in caps["tools"]}
        if any(n not in registered for n in allowed):
            raise ValueError("该网关尚未加载所需只读工具；本机可使用独立工单入口")
        task=api("POST","/tasks",{"goal":a.goal,"request_id":a.order,"planning_mode":"adaptive","driver":"model","allowed_tools":allowed,"required_tools":[],
                                 "skills":["maritime-evidence"],"use_memory":False,"budget":{"max_steps":18,"max_tool_calls":12,"max_tokens":90000,"max_active_seconds":900,"context_chars":15500}})
        if resident:
            if not re.fullmatch(r"ht-[0-9a-f]{32}",task["id"]):raise ValueError("主站返回工单标识无效")
            pointer={"id":task["id"],"order":a.order,"actor_id":task["actor_id"]}
            if route_file.exists() and json.loads(route_file.read_bytes())!=pointer:raise ValueError("工单指针冲突")
            temp=folder/(uuid4().hex+".pending")
            try:
                temp.write_text(json.dumps(pointer),encoding="utf-8");os.replace(temp,route_file)
            finally:temp.unlink(missing_ok=True)
    elif resident:
        pointer=json.loads(route_file.read_bytes());key=pointer["id"]
        if pointer["order"]!=a.order or not re.fullmatch(r"ht-[0-9a-f]{32}",key):raise ValueError("本机工单索引无效")
        task=api("GET","/tasks/"+key)
        if task["actor_id"]!=pointer["actor_id"]:raise ValueError("工单身份不一致")
    else:
        items=api("GET","/tasks?limit=5")["items"];match=[t for t in items if t["request_id"]==a.order]
        if len(match)!=1:raise ValueError("找不到唯一工单")
        task=api("GET","/tasks/"+match[0]["id"])
    if task["request_id"]!=a.order:raise ValueError("工单键不一致")
    route="/tasks/"+task["id"]
    if a.action=="export":result=api("GET",route+"/export")
    else:
        if a.action in ("run","resume"):
            expiry=None;resumed=set()
            if a.action=="resume" and task["status"]=="paused" and not task.get("waiting_source"):
                task=api("POST",route+"/control/resume")
            recovered_interruption=False
            while True:
                if (a.action=="resume" and not recovered_interruption and task["status"]=="paused"
                    and task.get("stop_reason")=="执行进程中断；可从检查点继续只读工作"
                    and not any(task.get("control",{}).values()) and not task.get("waiting_source")):
                    recovered_interruption=True
                    task=api("POST",route+"/control/resume");continue
                if (task["status"]=="paused" and task.get("waiting_source",{}).get("name")=="twin"
                    and not any(task.get("control",{}).values())):
                    waiting=task["waiting_source"]["result_id"]
                    if waiting in resumed or len(resumed)>=2:break
                    if expiry is None:expiry=time.monotonic()+a.dependency_wait
                    if ready():
                        task=api("POST",route+"/control/resume");resumed.add(waiting);continue
                    if time.monotonic()>=expiry:break
                elif task["status"] not in ("running","queued"):break
                time.sleep(.7);task=api("GET",route)
        result=task
    if a.json or a.action=="export":print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    else:
        print(f"{a.order} · {task['id']} · {task['status']}")
        for i,step in enumerate(task.get("plan",[]),1):print(i,step)
        for r in task["results"]:print(r["id"],r["tool"],"通过" if r["ok"] else "未通过")
        print((task.get("final") or {}).get("text") or task.get("stop_reason") or task.get("question",""))
    return 3 if a.action in ("run","resume") and task["status"]!="completed" else 0


def main(args):
    p=argparse.ArgumentParser(description="小鸥 · 只读自主业务工单")
    p.add_argument("action",choices=("run","resume","status","export"))
    p.add_argument("order",help="本机稳定工单键，8 至 80 个字母、数字、横线或下划线")
    p.add_argument("goal",nargs="?",help="自然语言业务任务")
    p.add_argument("--json",action="store_true")
    p.add_argument("--resident",action="store_true",help="在当前常驻小鸥网关执行并存入其任务中心")
    p.add_argument("--dependency-wait",type=int,default=180,help="等待 TwinLab 就绪后自动继续的秒数，0 表示保留断点并返回")
    a=p.parse_args(args)
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}",a.order) or not 0<=a.dependency_wait<=3600:p.error("工单键或等待秒数无效")
    if (a.action=="run")!=bool(a.goal):p.error("仅 run 需要任务说明")
    default=Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"GullMate/read-only-orders"
    root=Path(os.environ.get("GULLMATE_ORDER_ROOT",str(default))).resolve()
    folder=root/a.order;db=folder/"runtime.sqlite"
    if a.action!="run" and not (folder/"resident-id.json" if a.resident else db).is_file():sys.exit("工单不存在")
    folder.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(APP))
    if a.resident:
        headers={"Content-Type":"application/json"}
        token=os.environ.get("GULLMATE_GATEWAY_TOKEN")
        if token:headers["Authorization"]="Bearer "+token
        def request(method,path,body=None):
            req=Request("http://127.0.0.1:8010/api/harness"+path,method=method,headers=headers,
                        data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None)
            from app.harness.model import NoRedirect
            from urllib.request import ProxyHandler,build_opener
            try:
                with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=35) as response:return json.loads(response.read())
            except HTTPError as e:raise ValueError("主站返回 HTTP "+str(e.code)) from e
        return run_order(a,request,folder,True)
    # The manager and XiaoYi have intentionally separate Python dependencies.
    config=json.loads(subprocess.check_output([DEPLOY/"envs/manager/Scripts/python.exe","-X","utf8","-c",
        'import json,manage;print(json.dumps(manage.services()["xiaoyi"][4]))'],cwd=DEPLOY,encoding="utf-8",timeout=15))
    os.environ.update(config)
    # This credential is ephemeral and local to this one process, with a separate task database.
    os.environ.update(XIAOYI_RUNTIME_DB=str(db),XIAOYI_WORKORDER_DIR=str(folder/"workorders"),XIAOYI_SECURITY_MODE="jwt",XIAOYI_JWT_SECRET=secrets.token_hex(40))
    from fastapi.testclient import TestClient
    from app.main import app
    from app.harness.api import get_harness
    from app.security import issue_access_token
    from app.settings import settings
    actor="local-order-"+hashlib.sha256((getpass.getuser()+"|"+str(root)).encode()).hexdigest()[:20]
    auth={"Authorization":"Bearer "+issue_access_token(actor_id=actor,role="operator",settings=settings)}
    with TestClient(app,base_url="http://127.0.0.1") as client:
        assert Path(get_harness().store.path).resolve()==db and settings.security_mode=="jwt"
        def api(method,url,body=None):
            response=client.request(method,"/api/harness"+url,json=body,headers=auth)
            if response.status_code>=400:raise ValueError(f"工单接口 {response.status_code} · "+str(response.json().get("detail",""))[:400])
            return response.json()
        return run_order(a,api,folder,False)


if __name__=="__main__":
    try:sys.exit(main(sys.argv[2:] if sys.argv[1:2]==["order"] else sys.argv[1:]))
    except (ValueError,OSError) as e:sys.exit(str(e))
