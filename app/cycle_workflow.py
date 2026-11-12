"""Durable research sandbox. Its only mutable state is this SQLite journal."""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from app.config import RUNTIME_DB_PATH
from app.cycle_evidence import DIRECTORY, SHA
from app.cycle_reader import checked,read_case
from app.cycle_settlement import settle
from app.cycle_workflow_pin import RELEASE_SHA
from app.harness.contracts import digest,encoded,now
from app.harness.store import Conflict

RELEASE=DIRECTORY.with_name("decision-cycle-workflow-v1")
MODE="historical_sandbox"
METRICS=("total_cost_cny","carbon_kg","peak_kw")


def object_json(key):
    return json.loads(checked(RELEASE/"objects"/key,key))


def catalog():
    registry=json.loads(checked(RELEASE/"index.json",RELEASE_SHA))
    return [{"case_id":k,"decision":v["disposition"],"status":v["status"],"scenarios":list(v["scenarios"])}
            for k,v in registry.items()]


def proposal(case_id,scenario=None):
    evidence=read_case(DIRECTORY,SHA,case_id)
    registry=json.loads(checked(RELEASE/"index.json",RELEASE_SHA))
    case=registry[case_id]
    if case["case_id"]!=case_id or case["business_sha"]!=evidence["业务原件 SHA256"] or case["model_sha"]!=evidence["模型版本 SHA256"]:
        raise ValueError("工单、模型与评审版本不符")
    for review in case["reviews"]:
        checked(RELEASE/"objects"/review["raw"],review["raw"])
    if scenario is not None and scenario not in case["scenarios"]:
        raise ValueError("该工单无此仿真工况")
    spec=case["scenarios"].get(scenario)
    if spec:
        checked(RELEASE/"objects"/spec["native"],spec["native"])
        checked(RELEASE/"objects"/spec["config"],spec["config"])
    bind={"case_id":case_id,"model":case["model_sha"],"source":case["business_sha"],"scenario":scenario,
          "spec":spec,"scope":MODE,"reviews":[v["raw"] for v in case["reviews"]],"release":RELEASE_SHA}
    return {"case_id":case_id,"scenario":scenario,"proposal_sha":digest(bind),"scope":MODE,"status":case["status"],
            "evidence":evidence,"reviews":case["reviews"],"spec":spec,"production_authority":False}


def initial():
    return {"phase":"pending_signatures","signers":[],"meter":None,"active_schedule":None,
            "feedback":None,"evaluation_candidate":None}


def connection():
    runtime=Path(os.environ.get("XIAOYI_RUNTIME_DB",str(RUNTIME_DB_PATH)))
    path=runtime.with_name(runtime.stem+"-decision-cycles.sqlite")
    path.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(path,timeout=12,isolation_level=None)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("""CREATE TABLE IF NOT EXISTS cycle_events (
            proposal TEXT NOT NULL,seq INTEGER NOT NULL,request_key TEXT NOT NULL,body TEXT NOT NULL,
            sha TEXT NOT NULL,PRIMARY KEY(proposal,seq),UNIQUE(proposal,request_key))""")
        return con
    except BaseException:
        con.close()
        raise


def history(con,proposal_sha):
    rows=con.execute("SELECT seq,request_key,body,sha FROM cycle_events WHERE proposal=? ORDER BY seq",(proposal_sha,))
    result=[]
    previous=None
    before=initial()
    for n,(seq,key,raw,sha) in enumerate(rows,1):
        event=json.loads(raw)
        if (seq!=n or event["seq"]!=seq or event["request_key"]!=key or event["proposal_sha"]!=proposal_sha or
            event["parent_sha"]!=previous or digest(event)!=sha or event["before_sha"]!=digest(before) or
            event["after_sha"]!=digest(event["after"])):
            raise Conflict("沙箱日志校验失败")
        result.append({**event,"sha":sha})
        previous=sha
        before=event["after"]
    return result


def read_status(case_id,scenario):
    offer=proposal(case_id,scenario)
    with closing(connection()) as con:
        events=history(con,offer["proposal_sha"])
    state=events[-1]["after"] if events else initial()
    if offer["status"]!="simulation_candidate":
        state={**state,"phase":offer["status"]}
    return {**offer,"state":state,"state_sha":digest(state),"events":events}


def workplace(spec):
    raw=object_json(spec["native"])
    if raw["production_authority"] is not False or not raw["verified_twin"] or raw["week"]!=spec["week"]:
        raise Conflict("缺少原生复算或工况周不匹配")
    config=object_json(spec["config"])
    candidate=settle(raw["records"][spec["selected"]],config)
    def against(arm):
        other=settle(raw["records"][arm],config)
        return {k:other[k]-candidate[k] for k in METRICS}
    feedback={"relative_to_idle":against("idle"),"relative_to_original":against("original"),
              "relative_to_fixed_recognition":against("adaptive_clock"),"units":["CNY","kg","kW"],
              "scope":MODE,"week":spec["week"]}
    return candidate,feedback


def finish_evaluation(before,receipt_key,events):
    if not receipt_key or not before.get("evaluation_candidate"):
        raise Conflict("缺少已登记候选或评估回执")
    candidate=before["evaluation_candidate"]
    if candidate["status"]!="queued_for_offline_evaluation":
        raise Conflict("该候选的评估已经结算")
    directory=DIRECTORY.with_name("decision-cycle-evaluations")
    try:
        receipt=json.loads(checked(directory/(receipt_key+".json"),receipt_key))
    except FileNotFoundError as exc:
        raise ValueError("无此已复核评估回执") from exc
    submitted=next((e for e in events if e["action"]=="submit_evaluation"),None)
    if (not submitted or receipt["event_sha"]!=submitted["sha"] or receipt["case_id"]!=submitted["case_id"]
        or receipt["feedback_sha"]!=candidate["feedback_sha"] or receipt["promoted"] is not False):
        raise Conflict("评估回执与当前工单、反馈或候选不匹配")
    return {**before,"evaluation_candidate":{**candidate,"receipt_sha":receipt_key,"result":receipt["average_vs_fixed"],
            "status":"evaluated_qualified_for_review" if receipt["gate_passed"] else "evaluated_rejected","promoted":False}}


def transition(action,actor,before,spec):
    phase=before["phase"]
    after=dict(before)
    if action=="sign":
        if phase not in ("pending_signatures","one_signature") or actor in before["signers"]:
            raise Conflict("此主体已经签注或当前阶段不接受签注")
        after["signers"]=[*before["signers"],actor]
        after["phase"]="approved_sandbox" if len(after["signers"])==2 else "one_signature"
    elif action=="execute":
        if phase!="approved_sandbox" or len(set(before["signers"]))!=2:
            raise Conflict("执行需要两位不同的已认证操作员签注同一方案")
        meter,feedback=workplace(spec)
        after.update(phase="settled",active_schedule=spec["native"],meter=meter,feedback=feedback)
    elif action=="submit_evaluation":
        if phase!="settled" or before["evaluation_candidate"]:
            raise Conflict("只有已结算且尚未登记的仿真可以提交下一轮评估")
        after["evaluation_candidate"]={"schedule":spec["native"],"feedback_sha":digest(before["feedback"]),
                                       "status":"queued_for_offline_evaluation","promoted":False}
    elif action=="rollback":
        if phase!="settled":
            raise Conflict("没有可回滚的已结算沙箱状态")
        after.update(phase="rolled_back",meter=None,active_schedule=None)
    else:
        raise ValueError("未知沙箱操作")
    return after


def transact(case_id,scenario,action,payload,actor):
    offer=proposal(case_id,scenario)
    if offer["status"]!="simulation_candidate" or not offer["spec"]:
        raise Conflict(offer["evidence"]["处置"])
    if payload.scope!=MODE or payload.proposal_sha!=offer["proposal_sha"]:
        raise Conflict("作用域、来源或版本与本次签注对象不符")
    if action!="finish_evaluation" and payload.evaluation_sha is not None:
        raise ValueError("评估回执只适用于结算评估的操作")
    fingerprint=digest({"actor":actor,"action":action,"body":payload.model_dump(exclude_none=True)})
    with closing(connection()) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            events=history(con,offer["proposal_sha"])
            for event in events:
                if event["request_key"]==payload.request_key:
                    if event["request_sha"]!=fingerprint:
                        raise Conflict("同一请求号被用于不同操作、主体或内容")
                    con.commit()
                    return event
            before=events[-1]["after"] if events else initial()
            if payload.state_sha!=digest(before):
                raise Conflict("沙箱状态已变更，请读取当前状态再提交")
            after=(finish_evaluation(before,payload.evaluation_sha,events) if action=="finish_evaluation"
                   else transition(action,actor,before,offer["spec"]))
            event={"seq":len(events)+1,"case_id":case_id,"scenario":scenario,"action":action,"actor":actor,
                   "at":now(),"scope":MODE,"proposal_sha":offer["proposal_sha"],"request_key":payload.request_key,
                   "request_sha":fingerprint,"before_sha":digest(before),"after":after,"after_sha":digest(after),
                   "parent_sha":events[-1]["sha"] if events else None,"reason":payload.reason,"production_authority":False}
            sha=digest(event)
            con.execute("INSERT INTO cycle_events VALUES (?,?,?,?,?)",(offer["proposal_sha"],event["seq"],payload.request_key,encoded(event),sha))
            con.commit()
            return {**event,"sha":sha}
        except BaseException:
            con.rollback()
            raise
