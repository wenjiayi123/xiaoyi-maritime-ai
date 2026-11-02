"""Port decision support over immutable task evidence. No live control or arbitrary SQL."""

from __future__ import annotations

import copy
import json
import re
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import Field, model_validator

from app.harness.contracts import StrictModel, digest

MODEL_VERSION = "xiaoyi-port-study.v1"
NOTICE = "公开数据校准工程模拟；不是现场观测、生产KPI、作业许可或实测收益。"
SourceRef = str
Scenario = Literal["normal", "vessel_surge", "equipment_failure", "energy_peak", "storm"]
Metric = Literal[
    "vessels",
    "waiting_vessels",
    "grid_demand",
    "peak_limit",
    "shore_power",
    "bess_soc",
    "low_soc_agv",
    "fault_equipment",
    "yard_occupancy",
    "gate_queue",
    "wind_speed",
    "minimum_ukc",
]

# Meanings and units are versioned independently of natural-language model output.
METRICS = {
    "vessels": ("在港/计划港口挂靠记录数", "艘次", "port_calls", "min"),
    "waiting_vessels": ("待引航或计划挂靠记录数", "艘次", "port_calls.status", "min"),
    "grid_demand": ("瞬时电网需量", "kW", "energy.grid_demand_kw", "min"),
    "peak_limit": ("场景需量上限", "kW", "energy.peak_limit_kw", None),
    "shore_power": ("瞬时岸电负荷", "kW", "energy.shore_power_kw", None),
    "bess_soc": ("储能荷电状态", "%", "energy.bess_soc_percent", None),
    "low_soc_agv": ("SOC低于20%的AGV数量，含SOC为零", "台", "equipment.soc_percent", "min"),
    "fault_equipment": ("故障设备数", "台", "equipment.status", "min"),
    "yard_occupancy": ("总占用TEU/总容量TEU，加权堆场占用率", "%", "yard_blocks", "min"),
    "gate_queue": ("各闸口排队车辆之和", "辆", "gates.queue_vehicles", "min"),
    "wind_speed": ("场景风速", "m/s", "weather_tide.wind_speed_ms", None),
    "minimum_ukc": ("已提供净空值的泊位最小富余水深", "m", "berths.under_keel_clearance_m", "max"),
}
TABLES = {
    "port_calls": ("port_call_id", ["port_call_id", "imo", "mmsi", "vessel_name", "berth_id", "status", "eta", "etc"]),
    "berths": ("berth_id", ["berth_id", "occupied", "port_call_id", "under_keel_clearance_m", "window_risk_minutes"]),
    "equipment": ("asset_id", ["asset_id", "asset_type", "status", "availability", "soc_percent", "power_kw"]),
    "yard_blocks": ("block_id", ["block_id", "capacity_teu", "occupied_teu", "occupancy_percent"]),
    "gates": ("gate_id", ["gate_id", "queue_vehicles", "lanes_open", "turn_time_minutes"]),
    "alerts": ("event_id", ["event_id", "asset_id", "severity", "title", "status", "occurred_at"]),
}
REQUIRED = ["runtime.snapshot", "maritime.query", "maritime.risk", "twin.compare", "maritime.handover"]
TEMPLATES = [
    {
        "id": "port-future-study", "name": "公开港口历史复盘与未来能力评估",
        "goal": "查验国际港口公开历史数据及来源，在洛杉矶历史数据绑定下比较JIT挂靠资源排程，并独立验证NOAA水位预测，说明实测、代理、假设与缺项，不执行现场控制。",
        "required_tools": ["evidence.public_catalog", "port.study", "twin.validate_public"],
        "seconds": 420, "max_tokens": 24000,
    },
    {
        "id": "port-briefing",
        "name": "港航联合研判与交接",
        "goal": "对当前工程模拟港区做港航联合研判：核验时效、结构化问数、分析风险，对比常态、需量高峰和大风情景，生成交接简报，不调整设备。",
        "required_tools": REQUIRED,
        "seconds": 600,
        "max_tokens": 32000,
        "delivery_mode": "verified_business_report",
    },
    {
        "id": "port-query",
        "name": "港区结构化问数",
        "goal": "对当前工程模拟港区结构化问数，列出电网需量、岸电负荷、低电量AGV和闸口队列，保留单位与来源。",
        "required_tools": REQUIRED[:2],
        "seconds": 300,
        "max_tokens": 16000,
    },
    {
        "id": "twin-study",
        "name": "同基线孪生情景对比",
        "goal": "读取当前工程模拟港区快照，在同一基线下做孪生情景对比，核查风险并说明推演假设，不调整当前场景。",
        "required_tools": ["runtime.snapshot", "maritime.risk", "twin.compare"],
        "seconds": 420,
        "max_tokens": 24000,
    },
]


class SnapshotArgs(StrictModel):
    source_ref: SourceRef = Field(pattern=r"^T[1-9]\d*$")


class QueryArgs(SnapshotArgs):
    dataset: Literal["metrics", "port_calls", "berths", "equipment", "yard_blocks", "gates", "alerts"] = "metrics"
    metrics: list[Metric] = Field(
        default_factory=lambda: ["grid_demand", "shore_power", "low_soc_agv", "gate_queue"], min_length=1, max_length=12
    )
    entity_id: str | None = Field(None, min_length=1, max_length=100)
    limit: int = Field(20, ge=1, le=100)


class RiskArgs(SnapshotArgs):
    max_age_seconds: int = Field(120, ge=10, le=3600)


class CompareArgs(SnapshotArgs):
    scenarios: list[Scenario] = Field(
        default_factory=lambda: ["normal", "energy_peak", "storm"], min_length=2, max_length=5
    )
    horizon_minutes: int = Field(10, ge=1, le=60)
    samples: int = Field(3, ge=2, le=12)

    @model_validator(mode="after")
    def unique_scenarios(self):
        if len(set(self.scenarios)) != len(self.scenarios):
            raise ValueError("对比情景不得重复")
        return self


class HandoverArgs(SnapshotArgs):
    result_refs: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def valid_refs(self):
        if len(set(self.result_refs)) != len(self.result_refs) or any(
            not re.fullmatch(r"T[1-9]\d*", s) for s in self.result_refs
        ):
            raise ValueError("报告需要非重复的当前任务结果引用")
        return self


def catalog():
    return {
        "model_version": MODEL_VERSION,
        "metric_schema_sha256": digest(METRICS),
        "metrics": [{"id": k, "label": v[0], "unit": v[1], "source_path": v[2]} for k, v in METRICS.items()],
        "datasets": {k: {"entity_key": v[0], "columns": v[1]} for k, v in TABLES.items()},
        "templates": TEMPLATES,
        "notice": NOTICE,
    }


def simulator_digest():
    return hashlib.sha256((Path(__file__).parents[1] / "realtime_port_simulator.py").read_bytes()).hexdigest()


def result(task, store, ref, allowed):
    row = next((r for r in task["results"] if r["id"] == ref and r["ok"]), None)
    if not row or row["tool"] not in allowed:
        raise ValueError("引用必须指向当前任务已成功的对应工具结果")
    artifact = store.artifact(task["id"], row["artifact"])
    if not artifact or artifact["sha256"] != digest(artifact["content"]) or artifact["sha256"] != row["sha256"]:
        raise ValueError("来源工件摘要不一致，停止业务分析")
    return json.loads(artifact["content"])


def source(task, store, ref):
    data = result(task, store, ref, {"runtime.snapshot"})
    snapshot = data["snapshot"]
    if snapshot.get("metadata", {}).get("schema_version") != "port-ops.v1":
        raise ValueError("不支持的港区数据合同")
    return snapshot, {
        "source_ref": ref,
        "snapshot_sha256": digest(snapshot),
        "port_code": snapshot.get("port", {}).get("code"),
        "observed_at": snapshot.get("metadata", {}).get("observed_at"),
        "dataset_id": snapshot.get("metadata", {}).get("source_dataset_id"),
        "data_mode": snapshot.get("metadata", {}).get("data_mode"),
        "simulator_source_sha256": data.get("simulator_source_sha256"),
        "model_version": MODEL_VERSION,
        "production_authority": False,
        "notice": NOTICE,
    }


def _time(value):
    try:
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value.astimezone(timezone.utc) if value.tzinfo else None
    except (ValueError, TypeError):
        return None


def readiness(snapshot, max_age=120, *, at=None):
    at = at or datetime.now(timezone.utc)
    metadata, quality = snapshot.get("metadata", {}), snapshot.get("quality", {})
    observed = _time(metadata.get("observed_at"))
    age = (at - observed).total_seconds() if observed else None
    times = {
        "energy": snapshot.get("energy", {}).get("observed_at"),
        "weather_tide": snapshot.get("weather_tide", {}).get("observation_time"),
        **{f"equipment/{i}": r.get("event_time") for i, r in enumerate(snapshot.get("equipment", []))},
        **{f"port_calls/{i}": r.get("event_time") for i, r in enumerate(snapshot.get("port_calls", []))},
    }
    stale_components = [
        key
        for key, value in times.items()
        if _time(value) is None or not -5 <= (at - _time(value)).total_seconds() <= max_age
    ]
    missing = [
        k
        for k in ["port_calls", "berths", "equipment", "energy", "weather_tide", "gates", "yard_blocks", "alerts"]
        if k not in snapshot
    ]
    checks = {
        "timestamp_valid": observed is not None,
        "fresh": age is not None and -5 <= age <= max_age,
        "component_times": not stale_components,
        "schema": metadata.get("schema_version") == "port-ops.v1",
        "quality_gate": quality.get("gate_passed") is True,
        "complete_domains": not missing,
        "production_disabled": snapshot.get("governance", {}).get("production_authority") is False,
        "power_balance": abs(snapshot.get("energy", {}).get("power_balance_error_kw", float("inf"))) <= 1,
        "sequence_consistency": metadata.get("stream_sequence") == snapshot.get("simulation", {}).get("sequence"),
    }
    return {
        "analysis_usable": all(checks.values()),
        "assessed_at": at.isoformat(),
        "checks": checks,
        "age_seconds": round(age, 2) if age is not None else None,
        "max_age_seconds": max_age,
        "missing_domains": missing,
        "stale_components": stale_components,
        "site_connected": snapshot.get("port", {}).get("site_connected") is True,
        "simulation_only": metadata.get("data_mode") == "operations_sandbox",
        "operational_release": False,
    }


def metric_values(s):
    energy = s.get("energy", {})
    equipment = s.get("equipment", [])
    yards = s.get("yard_blocks", [])
    capacity = sum(r.get("capacity_teu", 0) for r in yards)
    ukc = [r["under_keel_clearance_m"] for r in s.get("berths", []) if r.get("under_keel_clearance_m") is not None]
    values = {
        "vessels": len(s.get("port_calls", [])),
        "waiting_vessels": sum(r.get("status") in {"awaiting_pilot", "scheduled"} for r in s.get("port_calls", [])),
        "grid_demand": energy.get("grid_demand_kw"),
        "peak_limit": energy.get("peak_limit_kw"),
        "shore_power": energy.get("shore_power_kw"),
        "bess_soc": energy.get("bess_soc_percent"),
        "low_soc_agv": sum(
            r.get("asset_type") == "agv" and r.get("soc_percent") is not None and r["soc_percent"] < 20
            for r in equipment
        ),
        "fault_equipment": sum(r.get("status") == "fault" for r in equipment),
        "yard_occupancy": round(100 * sum(r.get("occupied_teu", 0) for r in yards) / capacity, 3) if capacity else None,
        "gate_queue": sum(r.get("queue_vehicles", 0) for r in s.get("gates", [])),
        "wind_speed": s.get("weather_tide", {}).get("wind_speed_ms"),
        "minimum_ukc": min(ukc) if ukc else None,
    }
    for domain, ids in {
        "port_calls": ["vessels", "waiting_vessels"],
        "equipment": ["low_soc_agv", "fault_equipment"],
        "gates": ["gate_queue"],
    }.items():
        if domain not in s:
            for metric in ids:
                values[metric] = None
    return values


def query(snapshot, provenance, args):
    if args.dataset == "metrics":
        values = metric_values(snapshot)
        rows = [
            {
                "metric_id": m,
                "label": METRICS[m][0],
                "value": values[m],
                "unit": METRICS[m][1],
                "source_path": METRICS[m][2],
            }
            for m in dict.fromkeys(args.metrics)
        ]
        if args.entity_id is not None:
            raise ValueError("指标查询使用港区整体口径；对象筛选请选择实体数据集")
    else:
        key, columns = TABLES[args.dataset]
        rows = snapshot.get(args.dataset, [])
        if args.entity_id is not None:
            needle = args.entity_id.casefold().strip()
            fields = [key] + (["imo", "mmsi", "vessel_name"] if args.dataset == "port_calls" else [])
            rows = [r for r in rows if any(str(r.get(k, "")).casefold() == needle for k in fields)]
        rows = [{k: r.get(k) for k in columns} for r in sorted(rows, key=lambda r: str(r.get(key, "")))]
    return {
        **provenance,
        "query": args.model_dump(),
        "query_sha256": digest(args.model_dump()),
        "metric_schema_sha256": digest(METRICS),
        "rows": rows[: args.limit],
        "matched_count": len(rows),
        "truncated": len(rows) > args.limit,
        "ambiguous_entity": args.entity_id is not None and len(rows) > 1,
        "readiness": readiness(snapshot),
        "semantics": "固定只读语义口径；没有任意SQL或跨港口隐式拼接；空值不解释为零",
    }


def risk(snapshot, provenance, args):
    values, findings = metric_values(snapshot), []

    def add(rule, domain, severity, paths, value, threshold, message):
        findings.append(
            {
                "rule_id": rule,
                "domain": domain,
                "severity": severity,
                "source_paths": paths,
                "observed_value": value,
                "threshold": threshold,
                "message": message,
                "threshold_basis": "本地工程筛查参数；不是适用于所有港口的法规或作业许可",
            }
        )

    if (
        values["grid_demand"] is not None
        and values["peak_limit"] is not None
        and values["grid_demand"] > values["peak_limit"]
    ):
        add(
            "power-limit",
            "energy",
            "high",
            ["energy.grid_demand_kw", "energy.peak_limit_kw"],
            values["grid_demand"],
            values["peak_limit"],
            "模拟需量超过场景上限；先由能源值班员核对计量与可调负荷",
        )
    if values["low_soc_agv"]:
        add(
            "agv-soc",
            "equipment",
            "medium",
            ["equipment.soc_percent"],
            values["low_soc_agv"],
            "SOC < 20%",
            "低电量车辆需核对任务余程和充电资源，不自动改派",
        )
    if values["fault_equipment"]:
        add(
            "equipment-fault",
            "equipment",
            "high",
            ["equipment.status"],
            values["fault_equipment"],
            "fault",
            "故障设备保持隔离，需设备主管与许可核验",
        )
    if values["wind_speed"] is not None and values["wind_speed"] >= 15:
        add(
            "wind",
            "marine_safety",
            "high",
            ["weather_tide.wind_speed_ms"],
            values["wind_speed"],
            "15 m/s",
            "检查设备手册和港区现行停工条件；本阈值仅作工程筛查",
        )
    if values["minimum_ukc"] is not None and values["minimum_ukc"] < 1:
        add(
            "ukc",
            "marine_safety",
            "high",
            ["berths.under_keel_clearance_m"],
            values["minimum_ukc"],
            "1 m",
            "核对潮窗、实测水深、吃水及港口UKC制度，不据此放行",
        )
    if values["yard_occupancy"] is not None and values["yard_occupancy"] > 85:
        add(
            "yard-capacity",
            "terminal",
            "medium",
            ["yard_blocks"],
            values["yard_occupancy"],
            "85%",
            "检查堆场容量和箱区结构，不能只凭平均占用率调度",
        )
    if abs(snapshot.get("energy", {}).get("power_balance_error_kw", 0)) > 1:
        add(
            "power-balance",
            "data_quality",
            "high",
            ["energy.power_balance_error_kw"],
            snapshot["energy"]["power_balance_error_kw"],
            "1 kW",
            "计量平衡异常，暂缓能源建议",
        )
    gate = readiness(snapshot, args.max_age_seconds)
    return {
        **provenance,
        "readiness": gate,
        "recommendation_status": "human_review_required" if gate["analysis_usable"] else "withheld",
        "findings": findings,
        "finding_count": len(findings),
        "active_source_alerts": [
            a for a in snapshot.get("alerts", []) if a.get("status") not in {"resolved", "closed"}
        ],
        "review_domains": ["marine_safety", "terminal", "equipment", "energy"],
        "review_method": "确定性规则逐项核验；不是四个自主模型或独立专家投票",
        "missing_evidence": ["现场设备作业许可与联锁", "经核验的实时传感器与气象水文", "当班责任人与港区适用制度"],
        "production_authority": False,
    }


def compare(snapshot, provenance, args):
    from fastapi.encoders import jsonable_encoder
    from app.realtime_port_simulator import PortRealtimeSimulator, _AIS_SHA256, _ENERGY_SHA256, _CONTRACT_SHA256

    lineage = snapshot.get("lineage", {})
    if provenance.get("simulator_source_sha256") != simulator_digest():
        raise ValueError("模拟器源码已变化或旧快照缺少版本摘要，请重新采集快照")
    if (
        snapshot.get("port", {}).get("site_connected") is not False
        or snapshot["metadata"].get("data_mode") != "operations_sandbox"
    ):
        raise ValueError("当前推演模型只接受登记工程模拟源；不能套用到现场数据")
    for k, h in {
        "public_ais_sha256": _AIS_SHA256,
        "public_energy_sha256": _ENERGY_SHA256,
        "contract_sha256": _CONTRACT_SHA256,
    }.items():
        if lineage.get(k) != h:
            raise ValueError("校准数据或合同已变化，旧快照不能使用当前模型直接复现")
    clock = _time(snapshot["metadata"].get("observed_at"))
    if clock is None:
        raise ValueError("缺少带时区的基线时间")
    sim = snapshot["simulation"]
    sequence, seed = sim["sequence"], sim["simulation_seed"]
    executed = {r["decision_id"] for r in snapshot.get("decisions", []) if r.get("executed_in_sandbox") is True}
    offsets = [round(args.horizon_minutes * 60 * i / (args.samples - 1)) for i in range(args.samples)]
    baseline_scenario = sim["scenario_id"]
    scenarios = list(dict.fromkeys([baseline_scenario, *args.scenarios]))
    branches = []
    for scenario in scenarios:
        private = PortRealtimeSimulator(seed=seed)
        private._run_id = sim["run_id"]
        private._started_at = _time(sim["started_at"])
        private._scenario_id = scenario
        private._executed = copy.copy(executed)
        points = []
        for offset in offsets:
            sample = jsonable_encoder(
                private.snapshot_at(sequence=sequence + offset // 2, observed_at=clock + timedelta(seconds=offset))
            )
            points.append(
                {
                    "offset_seconds": offset,
                    "sequence": sample["simulation"]["sequence"],
                    "observed_at": sample["metadata"]["observed_at"],
                    "metrics": metric_values(sample),
                    "quality_gate": sample["quality"]["gate_passed"],
                    "sample_sha256": digest(sample),
                }
            )
        branches.append({"scenario": scenario, "points": points})
    baseline = branches[0]
    if baseline["points"][0]["metrics"] != metric_values(snapshot):
        raise ValueError("当前模型不能复现基线指标，停止情景对比")
    for branch in branches:
        branch["delta_vs_baseline"] = {
            m: round(branch["points"][-1]["metrics"][m] - baseline["points"][-1]["metrics"][m], 4)
            if branch["points"][-1]["metrics"][m] is not None and baseline["points"][-1]["metrics"][m] is not None
            else None
            for m in METRICS
        }
    valid = all(p["quality_gate"] for b in branches for p in b["points"])
    return {
        **provenance,
        "baseline_scenario": baseline_scenario,
        "seed": seed,
        "sequence": sequence,
        "frozen_clock": clock.isoformat(),
        "horizon_minutes": args.horizon_minutes,
        "branches": branches,
        "metric_units": {k: v[1] for k, v in METRICS.items()},
        "all_quality_gates_passed": valid,
        "forecast_validated": False,
        "quality_gate_scope": "原模拟器数据合同检查，不是独立动力学校准或预测准确率验收",
        "reproducible_input_sha256": digest(
            {"snapshot_sha256": provenance["snapshot_sha256"], "args": args.model_dump(), "model": MODEL_VERSION}
        ),
        "method": "相同种子、时钟、序号、执行状态和校准数据下，独立实例采样登记情景；没有向当前模拟器写场景",
        "assumptions": [
            "设备SOC为序号驱动工程示例，尚无完整电池充放电状态积分，不能用于续航或长期能耗预测",
            "未来采样为既有工程模型的条件情景轨迹，不是统计置信区间或外部气象预报",
            "情景是不同压力条件，不是已经优化得到的策略",
            "指标方向存在权衡，不计算未经业务授权的综合排名",
            "没有计算实测节能收益或现场调度许可",
        ],
        "production_authority": False,
    }


def handover(task, store, provenance, args):
    reports = []
    for ref in args.result_refs:
        data = result(task, store, ref, {"maritime.query", "maritime.risk", "twin.compare"})
        if data.get("snapshot_sha256") != provenance["snapshot_sha256"]:
            raise ValueError("交接资料不属于同一基线快照，禁止混用")
        reports.append((ref, data))
    kinds = {next(r["tool"] for r in task["results"] if r["id"] == ref) for ref, _ in reports}
    if not {"maritime.query", "maritime.risk", "twin.compare"}.issubset(kinds):
        raise ValueError("联合交接需要问数、风险和情景对比三类证据")
    lines = [
        "# 港航交接简报",
        NOTICE,
        f"港区：{provenance['port_code']}；基线时间：{provenance['observed_at']}",
        f"快照摘要：{provenance['snapshot_sha256']}",
    ]
    risk_report = next(d for _, d in reports if "findings" in d)
    comparison = next(d for _, d in reports if "branches" in d)
    comparison_summary = [
        {"scenario": b["scenario"], "grid_demand_kw": b["points"][-1]["metrics"]["grid_demand"], "delta_grid_kw": b["delta_vs_baseline"]["grid_demand"], "wind_speed_ms": b["points"][-1]["metrics"]["wind_speed"]}
        for b in comparison["branches"]
    ]
    gate = risk_report["readiness"]
    gate = readiness(source(task, store, args.source_ref)[0], gate["max_age_seconds"])
    lines += [
        "\n## 数据与放行边界",
        f"数据可分析：{gate['analysis_usable']}；现场作业放行：False",
        "\n## 已知事实与风险",
    ]
    for ref, data in reports:
        if "rows" in data:
            lines += [f"- [{ref}] {r['label']}：{r['value']} {r['unit']}" for r in data["rows"] if "metric_id" in r]
        if "findings" in data:
            lines += [
                f"- [{ref}] {r['rule_id']} / {r['severity']}：{r['message']}；观测值={r['observed_value']}；阈值={r['threshold']}"
                for r in data["findings"]
            ]
        if "branches" in data:
            lines += [
                f"- [{ref}] 情景 {b['scenario']}：末时点相对基线差异 {json.dumps(b['delta_vs_baseline'], ensure_ascii=False)}；单位见指标目录"
                for b in data["branches"]
            ]
    lines += [
        "\n## 未决事项",
        *[f"- {s}" for s in risk_report["missing_evidence"]],
        "\n## 责任角色与下一步",
        "- 海务值班：核对潮窗、UKC和气象水文适用性。",
        "- 设备主管：核对故障、隔离和检修许可。",
        "- 能源值班：复核计量、储能SOC和可调负荷。",
        "- 交班接收人：实名确认待办和截至时间；本工具不代替签收、确认告警或下发工单。",
    ]
    return {
        **provenance,
        "evidence_refs": [args.source_ref, *args.result_refs],
        "readiness": gate,
        "recommendation_status": "human_review_required" if gate["analysis_usable"] else "withheld",
        "markdown": "\n\n".join(lines),
        "comparison_summary": comparison_summary,
        "handover_state": "draft_requires_human_acceptance",
        "missing_assignments": ["当班责任人", "任务截止时间", "接收人签收"],
        "production_authority": False,
    }


def execute(name, args, task, store):
    snapshot, provenance = source(task, store, args.source_ref)
    if name == "maritime.query":
        return query(snapshot, provenance, args)
    if name == "maritime.risk":
        return risk(snapshot, provenance, args)
    if name == "twin.compare":
        return compare(snapshot, provenance, args)
    if name == "maritime.handover":
        return handover(task, store, provenance, args)
    raise ValueError("港航工具未登记")
