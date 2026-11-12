"""A bounded offline comparison whose tool sequence is chosen by the trained 14B actor."""
from __future__ import annotations
import base64,gzip,hashlib,json,os,subprocess,tempfile,time
from functools import lru_cache
from pathlib import Path
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from app import file_lease
from app.harness.contracts import digest,encoded

NAME="agent.credit_trial"
class TrialParams(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False,strict=True)
    first:float=Field(ge=0,le=1)
    second:float=Field(ge=0,le=1)
    baseline:float=Field(ge=0,le=1)
    carbon_price:float=Field(ge=0,le=5000)
    budget:float=Field(ge=0,le=10000000)
    service_pct:float=Field(ge=0,le=100)
    policy:Literal["joint","alone","rules"]
    loss:Literal["none","first","second"]

def hardware(policy):
    if policy=="rules":return "cpu"
    try:
        r=subprocess.run(["nvidia-smi","--id=0","--query-gpu=memory.free","--format=csv,noheader,nounits"],
            capture_output=True,text=True,timeout=4,creationflags=subprocess.CREATE_NO_WINDOW,check=True)
        return "shared" if int(r.stdout.strip())>=9600 else "cpu"
    except (OSError,ValueError,subprocess.SubprocessError):
        return "cpu"

@lru_cache(maxsize=2)
def cached_sha(path,size,mtime_ns,ctime_ns):
    with Path(path).open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def verify_files():
    from app.credit_pin import INPUTS
    for name,expected in INPUTS.items():
        path=Path(name);st=path.stat()
        if st.st_size>=1_000_000_000:actual=cached_sha(name,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
        else:
            with path.open("rb") as f:actual=hashlib.file_digest(f,"sha256").hexdigest()
        if actual!=expected:raise ValueError("登记的 14B 编排实验文件版本已改变")

def summary(result):
    options=result["options"];chosen=result["recommendation"]
    if chosen is not None:
        row=next(r for r in options if r["candidate"]==chosen)
        return f"推荐候选{chosen}，历史仿真成本 {row['cost']:.3f} 元。"
    labels={"no_registered_candidate_meets_requirements":"两项登记方案均未达到当前条件。","evidence_gap_reported":"当前证据不足，转人工核对。",
            "step_limit":"策略达到步数上限，本次未交付有效结论。","incorrect_report":"策略的结论未通过业务核验。"}
    return labels.get(result["outcome"],"本次未交付有效推荐。")

def evidence(result,store,task_id):
    from app.agent_training.expert_energy import check_receipt
    from app.agent_training.expert_contracts import assess_energy_option
    for opt in result["options"]:
        artifact=store.artifact(task_id,opt["artifact"])
        if not artifact or artifact["sha256"]!=digest(artifact["content"]):raise ValueError("原件存储摘要不符")
        packet=json.loads(artifact["content"])
        raw=gzip.decompress(base64.b64decode(packet["gzip_base64"],validate=True))
        if hashlib.sha256(raw).hexdigest()!=packet["sha256_utf8"]:raise ValueError("原件解压摘要不符")
        receipt=json.loads(raw)
        if receipt["receipt_sha256"]!=opt["receipt_sha256"]:raise ValueError("回执编号不符")
        p=result["params"];args=receipt["parameters"]
        if (args["request_id"]!=opt["request_id"] or args["green_preference"]!=p[("first","second")[opt["candidate"]-1]] or
                args["baseline_green_preference"]!=p["baseline"] or args["carbon_price_cny_per_ton"]!=p["carbon_price"]):
            raise ValueError("原始计算条件与工单不符")
        facts=check_receipt(receipt,args);v=assess_energy_option(*facts,{"max_cost_cny":p["budget"],"min_service_pct":p["service_pct"]})
        if (facts[1]["cost_cny"]!=opt["cost"] or facts[1]["service_pct"]!=opt["service_pct"] or v["status"]!=opt["assessment"]):
            raise ValueError("原件不能支持候选指标或核验结论")
    if result["correct"]:
        if {r["candidate"] for r in result["options"]}!={1,2}:raise ValueError("推荐缺少两份原件")
        statuses={r["candidate"]:r["assessment"] for r in result["options"]}
        outcome=result["outcome"];chosen=result["recommendation"]
        if chosen is not None:valid=outcome=="verified_candidate_recommended" and statuses[chosen]=="meets_registered_requirements"
        elif outcome=="no_registered_candidate_meets_requirements":valid=set(statuses.values())=={"does_not_meet_registered_requirements"}
        else:valid=outcome=="evidence_gap_reported" and "needs_evidence" in statuses.values() and "meets_registered_requirements" not in statuses.values()
        if not valid:raise ValueError("终局结论与有效回执不符")
    return summary(result)

def execute(task,store,call_id,cancelled,owner):
    from app.credit_pin import BASE,PYTHON
    from app.credit_process import process_tree
    params=TrialParams.model_validate(task["credit_trial"]).model_dump()
    verify_files()
    root=Path(BASE);runtime=root/"operator-runs";runtime.mkdir(exist_ok=True)
    deadline=time.monotonic()+max(1,task["budget"]["max_active_seconds"]-task["usage"]["active_seconds"])
    task_id=task["id"]
    def check():
        if cancelled():raise ValueError("本次推理已按工单控制停止")
        if time.monotonic()>=deadline:raise ValueError("本次编排推理已达到任务时间预算")
    def publish(event,detail):
        def set_progress(t):t["credit_progress"]=detail
        store.mutate(task_id,set_progress,event,detail,owner=owner)
    publish("credit.queued",{"phase":"排队等待本机推理资源","step":0,"call_id":call_id})
    with (runtime/"inference.lock").open("a+b") as lock:
        while True:
            check()
            try:file_lease.flock(lock,file_lease.LOCK_EX|file_lease.LOCK_NB);break
            except BlockingIOError:time.sleep(.35)
        profile=hardware(params["policy"])
        with tempfile.TemporaryDirectory(prefix=call_id+"-",dir=runtime,ignore_cleanup_errors=True) as name:
            folder=Path(name);progress=folder/"progress.jsonl"
            env=dict(os.environ,PYTHONNOUSERSITE="1",PYTHONDONTWRITEBYTECODE="1",PYTHONIOENCODING="utf-8",PYTHONUTF8="1",
                HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",TOKENIZERS_PARALLELISM="false",TMP=name,TEMP=name)
            env.pop("PYTHONPATH",None)
            with progress.open("wb") as output,(folder/"error.log").open("wb") as errors,process_tree(
                    [PYTHON,"-B","-X","utf8","-u",str(root/"live_worker.py"),name],cwd=root,
                    stdin=subprocess.PIPE,stdout=output,stderr=errors,env=env) as child:
                child.stdin.write(json.dumps({"params":params,"profile":profile}).encode()+b"\n");child.stdin.close()
                pos=0
                while True:
                    check()
                    with progress.open("rb") as f:
                        f.seek(pos)
                        for line in f:
                            if not line.endswith(b"\n"):break
                            pos+=len(line);record=json.loads(line)
                            if record["kind"]=="action":publish("credit.action",{"phase":"执行工具","step":record["step"],"tool":record["tool"],"action":record["action"],"profile":profile,"call_id":call_id})
                            if record["kind"]=="ready":publish("credit.loading",{"phase":"加载模型与本地仿真","step":0,"profile":profile,"call_id":call_id})
                    if child.poll() is not None:break
                    time.sleep(.25)
                if child.returncode!=0:
                    tail=(folder/"error.log").read_text("utf8",errors="replace").splitlines()
                    reason=tail[-1].split(":",1)[0][:50] if tail else str(child.returncode)
                    raise ValueError("本机策略进程未完成，未签发推荐。错误类型 "+reason)
            result=json.loads((folder/"measured.json").read_bytes())
            if result["params"]!=params or result["production_authority"] is not False:raise ValueError("回执范围与任务不符")
            attachments=[]
            for opt in result["options"]:
                i=opt["candidate"];src=folder/f"receipt-{i}.json";receipt=json.loads(src.read_bytes())
                raw=encoded(receipt).encode()
                label=f"{call_id}-source-{i}.json";opt["artifact"]=label
                attachments.append({"name":label,"media_type":"application/json","content":encoded({"encoding":"gzip+base64",
                    "sha256_utf8":hashlib.sha256(raw).hexdigest(),"gzip_base64":base64.b64encode(gzip.compress(raw,mtime=0)).decode()})})
            check()
            store.mutate(task_id,lambda t:None,"credit.evidence",{"call_id":call_id,"receipts":len(attachments)},owner=owner,artifacts=attachments)
            result["summary"]=evidence(result,store,task_id)
            return result
