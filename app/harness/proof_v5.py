"""Executable demonstrations backed by immutable local receipts and original inputs."""

import copy
import gzip
import hashlib
import json
import re
import time
from typing import Literal

from fastapi.encoders import jsonable_encoder
from pydantic import Field

from app.config import BASE_DIR
from app.harness import maritime, operations_v5
from app.harness.contracts import StrictModel, digest, now
from app.harness.local_lock import ProcessLease
from app.harness.store import Conflict
from app.runtime_store import runtime_store

KIND = "xiaoyi-capability-proof-v5"
KINDS = {"optimization", "facts", "faults", "knowledge", "twin", "rl", "runtime", "standards", "long_twin_v6", "rl_v6"}


class RunRequest(StrictModel):
    request_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,100}$")
    kind: Literal[
        "optimization", "facts", "faults", "knowledge", "twin", "rl", "runtime", "standards", "long_twin_v6", "rl_v6"
    ]
    parameters: dict = Field(default_factory=dict, max_length=12)


class TwinArgs(StrictModel):
    cell: int = Field(0, ge=0, le=55)


class RlArgs(StrictModel):
    port_id: str = Field("port23", max_length=30)
    quarter: Literal["01", "04"] = "01"
    scenario: Literal["normal", "demand_surge", "resource_outage", "publication_delay"] = "normal"


class LongTwinArgs(StrictModel):
    cell: int = Field(0, ge=0, le=55)


class RlV6Args(RlArgs):
    port_id: str = Field("port192", max_length=30)
    seed: int = Field(632101, ge=632101, le=632105)


def filehash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_json(path, expected=None):
    p = BASE_DIR / path
    if expected and filehash(p) != expected:
        raise ValueError("证据文件已变化，请重新验收")
    return json.loads(p.read_text())


def research(name):
    registry = checked_json("config/remediation_v4_evidence_registry.json")
    entry = registry["reports"][name]
    return checked_json(entry["path"], entry["sha256"])


def twin(args):
    data = research("physical")
    cell = data["results"][args.cell]
    path = operations_v5.checked(data["trace_path"], data["trace_sha256"])
    points = []
    with gzip.open(path, "rt") as handle:
        for line in handle:
            point = json.loads(line)
            if all(point[k] == cell[k] for k in ["station_id", "run", "mode"]):
                points.append(point)
    return {
        "cell": cell,
        "cell_index": args.cell,
        "cells": data["results"],
        "points": points,
        "source_trace": {"path": data["trace_path"], "sha256": data["trace_sha256"]},
        "sources": data["sources"],
        "assumptions": data["protocol"],
        "explanation": "逐点显示原始观测、冻结预测、强基线与原区间。空单元保持空；选不同单元是查看已评分历史，不重新标定、不升级年度资格。",
        "production_authority": False,
    }


def rl(args):
    data = research("learning")
    window = f"{args.port_id}.2026.{args.quarter}"
    if window not in {w["id"] for w in data["windows"]}:
        raise ValueError("请选择已登记的历史RL港口和窗口")
    chosen = data["selection"]
    names = {chosen["selected_rl"], chosen["selected_cost_mpc"], chosen["selected_safe_mpc"], "risk_model_rl_p0.none"}
    path = operations_v5.checked(data["trace_path"], data["trace_sha256"])
    runs = []
    with gzip.open(path, "rt") as handle:
        for line in handle:
            run = json.loads(line)
            if run["window"] == window and run["scenario"] == args.scenario and run["algorithm"] in names:
                runs.append(run)
    return {
        "runs": runs,
        "ports": data["sources"]["entries"],
        "diagnostics": research("diagnostics"),
        "source_trace": {"path": data["trace_path"], "sha256": data["trace_sha256"]},
        "notice": "重放既有90天原始轨迹；原始动作、过滤后动作、队列、成本及输入截止日分别展示。不是新留出或重新训练；不能把安全规则收益归给RL。",
        "production_authority": False,
    }


def current_snapshot():
    from app.realtime_port_simulator import simulator_snapshot

    return jsonable_encoder(simulator_snapshot())


def facts():
    raw = current_snapshot()
    source = {
        "source_ref": "T1",
        "snapshot_sha256": digest(raw),
        "simulator_source_sha256": maritime.simulator_digest(),
        "data_notice": maritime.NOTICE,
    }
    query = maritime.query(raw, source, maritime.QueryArgs(source_ref="T1"))
    risk = maritime.risk(raw, source, maritime.RiskArgs(source_ref="T1"))
    branches = maritime.compare(raw, source, maritime.CompareArgs(source_ref="T1"))
    return {
        "snapshot": raw,
        "query": query,
        "risk": risk,
        "branches": branches,
        "evidence_ids": {
            "T1": "本次真实读取的登记工程模拟快照",
            "T2": "该快照问数",
            "T3": "该快照风险",
            "T4": "该快照隔离推演",
        },
        "checks": {
            "same_snapshot": all(r["snapshot_sha256"] == digest(raw) for r in [query, risk, branches]),
            "no_source_mutation": digest(raw) == source["snapshot_sha256"],
        },
        "notice": "真实读取当前接口并计算；数据本身为公开数据校准的工程模拟。情景来自隔离副本，未修改正在运行的模拟器。",
        "production_authority": False,
    }


def faults():
    from app.harness.operations_v2 import ukc_gate

    original = current_snapshot()
    original_hash = digest(original)
    cases = []
    for kind in ["stale_clock", "power_imbalance", "sequence_mismatch", "missing_energy"]:
        altered = copy.deepcopy(original)
        if kind == "stale_clock":
            altered["metadata"]["observed_at"] = "2000-01-01T00:00:00+00:00"
        elif kind == "power_imbalance":
            altered["energy"]["power_balance_error_kw"] = 1000
        elif kind == "sequence_mismatch":
            altered["metadata"]["stream_sequence"] = -1
        else:
            altered.pop("energy")
        gate = maritime.readiness(altered)
        restored = copy.deepcopy(original)
        cases.append(
            {
                "fault": kind,
                "blocked": not gate["analysis_usable"],
                "failed_checks": [k for k, v in gate["checks"].items() if not v],
                "gate": gate,
                "restored_hash_matches": digest(restored) == original_hash,
            }
        )
    ukc = ukc_gate(None, None, None, None, False, False, False)
    return {
        "baseline_sha256": original_hash,
        "baseline_gate": maritime.readiness(original),
        "cases": cases,
        "unknown_ukc": ukc,
        "passed": all(c["blocked"] and c["restored_hash_matches"] for c in cases)
        and ukc["status"] == "withheld"
        and digest(original) == original_hash,
        "notice": "对本次真实读取快照的隔离副本注入四类故障并恢复；不是现场停机或OT灾备演练。原始失败和阻断检查逐条保留。",
        "production_authority": False,
    }


def calculate(kind, parameters):
    if kind in {"long_twin_v6", "rl_v6"}:
        from app.harness import research_v6

        if kind == "long_twin_v6":
            return research_v6.twin(LongTwinArgs.model_validate(parameters).cell)
        return research_v6.rl(**RlV6Args.model_validate(parameters).model_dump())
    if kind == "optimization":
        return operations_v5.optimize(operations_v5.OptimizeArgs.model_validate(parameters))
    if kind == "twin":
        return twin(TwinArgs.model_validate(parameters))
    if kind == "rl":
        return rl(RlArgs.model_validate(parameters))
    if kind == "knowledge":
        from app.harness.tools import KnowledgeArgs, knowledge_engine

        args = KnowledgeArgs.model_validate(parameters)
        response = knowledge_engine().ask(**args.model_dump(), strict_evidence=True)
        return {
            "answer": response.answer,
            "grounded": response.grounded,
            "completion_status": response.completion_status,
            "source_quality": response.source_quality,
            "evidence": [e.model_dump(mode="json") for e in response.evidence],
            "notice": "当前知识索引真实检索及证据约束回答；不是4B模型自由生成或开放世界准确率测评。",
            "production_authority": False,
        }
    if parameters:
        raise ValueError("此演示不接受额外参数")
    if kind == "facts":
        return facts()
    if kind == "faults":
        return faults()
    if kind == "standards":
        from app.harness.operations_v3 import contract_drill

        sources = checked_json("data/public/port_standards_v3_20261030/manifest.json")
        for entry in sources["entries"]:
            operations_v5.checked(entry["path"], entry["sha256"])
        return {**contract_drill(), "sources": sources, "production_authority": False}
    from app.system_api import readiness_payload

    return {
        "health": readiness_payload(),
        "configuration": {"simulation": True, "production_authority": False},
        "notice": "当前进程真实健康核查；不能作为长期SLO或集群高可用证明。",
        "production_authority": False,
    }


def code_sources():
    names = [
        "app/harness/proof_v5.py",
        "app/harness/operations_v5.py",
        "app/harness/maritime.py",
        "app/realtime_port_simulator.py",
        "app/harness/operations_v2.py",
        "app/harness/operations_v3.py",
        "app/harness/tools.py",
        "app/harness/proof_api.py",
        "app/harness/research_v6.py",
        "app/harness/rl_v6.py",
        "app/harness/long_twin_v6.py",
        "app/harness/dual_api.py",
        "app/harness/runner.py",
        "app/harness/remediation_v2.py",
        "app/main.py",
        "app/access_control.py",
        "app/security.py",
        "app/harness/contracts.py",
        "app/xiaoyi.py",
        "app/retrieval.py",
        "app/vector_retrieval.py",
        "data/xiaoyi_index.json",
    ]
    return {n: filehash(BASE_DIR / n) for n in names}


def input_sources(value):
    files = {}

    def visit(item):
        if isinstance(item, dict):
            if isinstance(item.get("path"), str) and isinstance(item.get("sha256"), str):
                path = BASE_DIR / item["path"]
                if path.is_file() and path.resolve().is_relative_to(BASE_DIR.resolve()):
                    files[item["path"]] = item["sha256"]
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return files


def get(run_id, actor_id, admin=False):
    if not re.fullmatch(r"pr-[a-f0-9]{32}", run_id):
        raise ValueError("无效演示回执编号")
    value = runtime_store.get_artifact(KIND, run_id)
    if value is None or (value["actor_id"] != actor_id and not admin):
        raise ValueError("回执不存在或不属于当前身份")
    previous = "0" * 64
    chain = True
    for event in value["events"]:
        chain = (
            chain
            and event["previous_sha256"] == previous
            and event["sha256"] == digest({k: v for k, v in event.items() if k != "sha256"})
        )
        previous = event["sha256"]
    value["integrity"] = {
        "result_hash_valid": digest(value["result"]) == value["result_sha256"],
        "event_chain_valid": chain,
    }
    value["historical_only"] = any(
        not (BASE_DIR / p).is_file() or filehash(BASE_DIR / p) != h
        for p, h in {**value["code_sha256"], **value.get("input_sha256", {})}.items()
    )
    return value


def run(payload, actor_id):
    run_id = "pr-" + digest({"actor": actor_id, "request_id": payload.request_id})[:32]
    with_lease = ProcessLease(runtime_store.path.with_suffix(".proof.lock"))
    with_lease.acquire()
    try:
        existing = runtime_store.get_artifact(KIND, run_id)
        if existing:
            if existing["request_sha256"] != digest(payload.model_dump(mode="json")):
                raise Conflict("同一请求编号不能更换参数")
            return get(run_id, actor_id)
        started = time.monotonic()
        events = []

        def event(label, detail):
            row = {
                "seq": len(events) + 1,
                "at": now(),
                "event": label,
                "detail": detail,
                "previous_sha256": events[-1]["sha256"] if events else "0" * 64,
            }
            row["sha256"] = digest(row)
            events.append(row)

        event("requested", {"kind": payload.kind, "request_sha256": digest(payload.model_dump(mode="json"))})
        try:
            if code_sources() != LOADED_SOURCES:
                raise ValueError("服务已加载版本与磁盘源码/索引不同，请重启服务后重试；未采信本次计算")
            result = jsonable_encoder(calculate(payload.kind, payload.parameters))
            if code_sources() != LOADED_SOURCES:
                result = {
                    "unqualified_result": result,
                    "error": "运行期间版本变化，本次结果仅作暂缓记录",
                    "production_authority": False,
                }
                status = "failed"
            else:
                status = "completed"
        except Exception as exc:
            result = {"error": str(exc)[:600], "production_authority": False}
            status = "failed"
        event("computed" if status == "completed" else "failed", {"result_sha256": digest(result)})
        value = {
            "schema": "xiaoyi-executable-proof.v5",
            "id": run_id,
            "actor_id": actor_id,
            "created_at": now(),
            "kind": payload.kind,
            "parameters": payload.parameters,
            "status": status,
            "request_sha256": digest(payload.model_dump(mode="json")),
            "result": result,
            "result_sha256": digest(result),
            "elapsed_seconds": time.monotonic() - started,
            "code_sha256": dict(LOADED_SOURCES),
            "input_sha256": input_sources(result),
            "events": events,
            "production_authority": False,
            "notice": "实际本机计算回执；本地哈希及事件链一致性，不是第三方认证或不可篡改外部签名。",
        }
        runtime_store.save_artifact(KIND, run_id, value, max_items=300)
        return get(run_id, actor_id)
    finally:
        with_lease.release()


def catalog():
    from app.harness import research_v6

    registry_path = BASE_DIR / "config/proof_evidence_registry.json"
    registry = json.loads(registry_path.read_text()) if registry_path.exists() else None
    if registry:
        for entry in registry["reports"].values():
            checked_json(entry["path"], entry["sha256"])
    scorecard = research("scorecard")
    operations = operations_v5.catalog()
    for entry in [*operations["entries"], operations["primary_export"]]:
        operations_v5.checked(entry["path"], entry["sha256"])
    report = operations_v5.FOLDER / "report-qualified.json"
    if not report.exists():
        report = operations_v5.FOLDER / "report-final.json"
    if not report.exists():
        report = operations_v5.FOLDER / "report.json"
    evaluation = json.loads(report.read_text()) if report.is_file() else None
    if evaluation:
        checked_json(
            evaluation.get("protocol_path", "data/public/operations_v5_20261030/protocol.json"),
            evaluation["protocol_sha256"],
        )
        evaluation["historical_only"] = evaluation["source_sha256"] != filehash(
            BASE_DIR / "app/harness/operations_v5.py"
        )
    improvement_entry = registry.get("reports", {}).get("improvements") if registry else None
    improvement_file = BASE_DIR / (
        improvement_entry["path"]
        if improvement_entry
        else "data/evaluation/xiaoyi_capability_improvements_v5_20261030.json"
    )
    return {
        "schema": KIND,
        "evidence_registered": registry is not None,
        "runtime_code_current": code_sources() == LOADED_SOURCES,
        "components": scorecard["components"],
        "rubric": scorecard["rubric"],
        "improvements": json.loads(improvement_file.read_text()) if improvement_file.exists() else None,
        "development_failures": checked_json(
            registry["reports"]["failures"]["path"], registry["reports"]["failures"]["sha256"]
        )
        if registry and "failures" in registry["reports"]
        else None,
        "operations_sources": operations,
        "operations_evaluation": {k: v for k, v in evaluation.items() if k not in {"sources", "cases"}}
        if evaluation
        else None,
        "actions": sorted(KINDS),
        "latest_research": research_v6.compact() if research_v6.REGISTRY.is_file() else None,
        "production_authority": False,
        "notice": "点击后真实读取或重算并生成独立回执；回放、合成情景和现场资格分别标记。旧分数不是本次自动提高的承诺。",
    }


# A hot-edited file must not be mistaken for the code already loaded in this process.
LOADED_SOURCES = code_sources()
