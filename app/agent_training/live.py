"""Native local-system execution for the registered agent-RL demonstration.

Training uses a resettable synthetic environment. This module calls actual
registered local APIs and keeps raw responses; it never substitutes fixtures.
"""

from __future__ import annotations

import copy
from dataclasses import asdict
from html import escape
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from .environment import REVISION as LEGACY_REVISION, TaskEnvironment, TaskSpec, digest
from .environment_v2 import REVISION as PROGRESS_REVISION, ProgressEnvironment

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ENVIRONMENT_SOURCE_SHA256 = {
    name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
    for name in ["environment.py", "environment_v2.py"]
}
JOBS = ROOT / ".runtime/agent-rl-v1/tasks"
ACCEPTANCE_GOAL = (
    "读取港口、能碳和马六甲系统的当前状态；比较基准绿色偏好0.50、候选绿色偏好0.82、"
    "碳价85元/吨的能碳方案；评估港口高密度靠泊情景。遇到可恢复的读取故障请处理后继续，"
    "最后给我带来源、参数、结果和实际执行记录的联合报告。只在本机工程模拟中操作。"
)


def execution_origin(tool):
    if tool.endswith(".read") or tool in {
        "energy.compare",
        "port.evaluate",
        "energy.pause",
        "energy.restore",
        "execution.diagnose",
    }:
        return "actual_local_system_api"
    return "local_runtime_tool"


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def report_html(report):
    def number(value):
        return f"{value:,.6f}".rstrip("0").rstrip(".") if isinstance(value, (int, float)) else str(value)

    def table(headers, rows):
        head = "".join("<th>" + escape(h) + "</th>" for h in headers)
        body = "".join("<tr>" + "".join("<td>" + escape(str(v)) + "</td>" for v in row) + "</tr>" for row in rows)
        return "<table><thead><tr>" + head + "</tr></thead><tbody>" + body + "</tbody></table>"

    summaries = report["summaries"]
    sections = [
        "<h1>舷鸥任务执行报告</h1><p>" + escape(report["goal"]) + "</p>",
        "<p class='scope'>本报告来自本机原系统的实际接口调用。各系统保留自己的地点、模拟时钟和数据来源，不能视作同一真实港区的现场联合效果。</p>",
    ]
    sources = []
    for key, title in [("port", "港口数字孪生"), ("energy", "能碳驾驶舱"), ("traffic", "马六甲沙盘")]:
        if key in summaries:
            s = summaries[key]
            sources.append(
                [
                    title,
                    s.get("site_id") or "接口未提供地点编号",
                    s.get("observed_at"),
                    s.get("event_time") or "接口未提供独立事件时间",
                    s.get("source_mode"),
                ]
            )
    sections.append(
        "<h2>查询时读到的模拟状态</h2>"
        + table(["系统", "地点编号", "响应生成时间", "模拟事件时间", "数据模式"], sources)
    )
    observations = []
    for key, title in [("port", "港口"), ("energy", "能碳"), ("traffic", "交通")]:
        for metric in summaries.get(key, {}).get("metrics", []):
            observations.append(
                [
                    title,
                    metric["label"],
                    number(metric["value"]) if metric["value"] is not None else "源数据缺失",
                    metric["unit"],
                    metric["field"],
                ]
            )
    if observations:
        sections.append(table(["系统", "观测指标", "值", "单位", "原始字段"], observations))
    comparison = summaries.get("energy_comparison")
    if comparison:
        baseline, candidate = comparison
        index = {(r["label"], r["unit"]): r for r in baseline["summary"]["kpis"]}
        rows = []
        for item in candidate["summary"]["kpis"]:
            old = index.get((item["label"], item["unit"]))
            if old and isinstance(old["value"], (int, float)) and isinstance(item["value"], (int, float)):
                delta = item["value"] - old["value"]
                rows.append(
                    [
                        item["label"],
                        number(old["value"]),
                        number(item["value"]),
                        ("+" if delta > 0 else "") + number(delta),
                        item["unit"],
                    ]
                )
        sections.append(
            "<h2>能碳方案的实际比较</h2><p>基准绿色偏好 "
            + escape(number(baseline["parameters"]["green"]))
            + "；候选绿色偏好 "
            + escape(number(candidate["parameters"]["green"]))
            + "；两组碳价均为 "
            + escape(number(candidate["parameters"]["carbon"]))
            + " 元/吨。</p>"
            + table(["指标", "本次基准", "本次候选", "候选－本次基准", "单位"], rows)
            + "<p>费用和碳排分别判断，不把费用降低自动解释为低碳。差值针对本次两个方案，未采用接口中相对于其他参照的差值。</p>"
            + "<p>能碳数据集："
            + escape(baseline["summary"]["dataset_id"])
            + "；两方案数据摘要相同。</p>"
        )
    if "port_evaluation" in summaries:
        p = summaries["port_evaluation"]
        sections.append(
            "<h2>港口情景评估</h2>"
            + table(
                ["情景", "评估时长（分钟）", "返回点数", "峰值功率（kW）", "平均功率（kW）"],
                [
                    [
                        p["parameters"]["scenario"],
                        p["parameters"]["horizon_min"],
                        p["points"],
                        number(p["peak_kw"]),
                        number(p["average_kw"]),
                    ]
                ],
            )
        )
        if p.get("source_warning"):
            sections.append("<p class='scope'>" + escape(p["source_warning"]) + "</p>")
    sections.append(
        "<h2>结果核验与原始证据</h2><p>"
        + str(sum(report["verification"]["checks"].values()))
        + " 项核验通过。摘要由已核验数值自动编制，模型负责选择执行步骤。</p><ul>"
        + "".join(
            "<li><a href='" + escape(row["file"]) + "'>" + escape(row["tool"] + " · " + row["file"]) + "</a></li>"
            for row in report["evidence"]
        )
        + "</ul><p><a href='report.json'>下载结构化报告</a></p>"
    )
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>舷鸥任务执行报告</title><style>body{font:16px system-ui;color:#203044;max-width:1080px;margin:36px auto;padding:24px;line-height:1.8}h1{font-size:28px}h2{font-size:21px;margin-top:32px}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:12px;border-bottom:1px solid #d7e0e7;overflow-wrap:anywhere}th,.scope{background:#eef4f5}.scope{padding:16px}a{color:#146b64}@media print{body{margin:0;padding:0}}@media(max-width:650px){body{padding:14px}table{font-size:12px}th,td{padding:6px}}</style>'
        + "".join(sections)
        + "</html>"
    )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("registered API redirects are not allowed")


def local_request(base, path, payload=None, *, timeout=40, token=None):
    parts = urlsplit(base)
    if (
        parts.scheme != "http"
        or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("only registered local HTTP services are allowed")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps(payload, allow_nan=False).encode() if payload is not None else None
    with build_opener(NoRedirect).open(
        Request(base.rstrip("/") + path, data=body, headers=headers), timeout=timeout
    ) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("response too large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("expected object response")
    digest(value)
    return value


def parse_goal(goal, *, inject_read_fault=False):
    if not isinstance(goal, str) or not 2 <= len(goal) <= 2000:
        raise ValueError("请输入2—2000字的任务")
    if re.search(r"真实设备|实船控制|生产下发|删除|任意代码|shell", goal, re.I):
        raise ValueError("此实验入口仅支持登记的本机观测、试算和恢复任务")
    if re.search(r"(?:不要|禁止|无需|不需要|不得).{0,16}(?:比较|试算|评估|暂停|恢复|修改|控制|下发)", goal):
        raise ValueError("此登记任务入口暂不支持带否定操作的复合表述；请直接写明要执行的任务")
    port = bool(re.search(r"港口|泊位|靠泊", goal))
    energy = bool(re.search(r"能碳|能源|绿色偏好|碳价|时钟", goal))
    traffic = bool(re.search(r"马六甲|交通|航道", goal))
    compare = bool(re.search(r"比较|试算|绿色偏好|碳价", goal))
    evaluate = bool(re.search(r"评估|情景|高密度|拥堵", goal))
    read_only = bool(re.search(r"只读|仅查询|只查询|仅读取|只读取|仅查看|只查看", goal))
    if read_only and (compare or evaluate or "暂停" in goal or "恢复" in goal):
        raise ValueError("只读限制与试算或状态操作同时出现；本轮不会自动扩大执行范围")
    if "暂停" in goal:
        if "恢复" not in goal:
            raise ValueError("时钟实验必须明确要求恢复原状态")
        family = "clock_restore"
    elif sum([port, energy, traffic]) >= 2:
        if not (port and energy and traffic and compare and evaluate):
            raise ValueError("当前联合实验需包含港口、能碳、交通读取，以及能碳比较和港口情景评估；可先用单系统任务")
        family = "joint"
    elif energy:
        if not compare:
            raise ValueError("本轮能碳实验请明确要求比较或试算；普通只读可使用原智能操作入口")
        family = "energy_compare"
    elif port:
        family = "port_scenario" if evaluate else "port_read"
    elif traffic:
        family = "traffic_read"
    else:
        raise ValueError("当前实验支持港口查询、能碳比较、港口情景、交通查询、联合评估和模拟时钟恢复")

    def number(pattern, default):
        found = re.search(pattern, goal)
        return float(found.group(1)) if found else default

    green = number(
        r"(?:候选绿色偏好|候选偏好|(?<!基准)绿色偏好)\s*(?:(?:为|是|=|：|调到|设为)\s*)?([-+]?\d+(?:\.\d+)?)", 0.82
    )
    baseline = number(r"基准(?:绿色偏好)?\s*(?:(?:为|是|=|：)\s*)?([-+]?\d+(?:\.\d+)?)", 0.5)
    carbon = number(r"碳价\s*(?:(?:为|是|=|：|设为)\s*)?([-+]?\d+(?:\.\d+)?)", 85)
    if not (0 <= green <= 1 and 0 <= baseline <= 1 and 0 <= carbon <= 5000):
        raise ValueError("绿色偏好需在0—1，碳价需在0—5000元/吨")
    scenario = (
        "equipment_degradation"
        if re.search("设备|退化|故障情景", goal)
        else "channel_congestion"
        if "拥堵" in goal
        else "high_density_berthing"
    )
    fault = "transient_read" if inject_read_fault else "none"
    return TaskSpec(
        "acceptance-" + uuid4().hex, "acceptance", family, 440001, green, carbon, baseline, scenario, fault, 18
    )


class NativeBackend:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.urls = {
            "port": os.getenv("AGENT_RL_PORT_URL", "http://127.0.0.1:18800"),
            "energy": os.getenv("AGENT_RL_ENERGY_URL", "http://127.0.0.1:18808"),
            "traffic": os.getenv("AGENT_RL_TRAFFIC_URL", "http://127.0.0.1:18473"),
        }
        self.evidence = []
        self.clock_before = None
        self.clock_owned = False
        self.summaries = {}

    def request(self, system, path, payload=None):
        token = os.getenv(
            {
                "port": "XIAOYI_PORT_DT_API_TOKEN",
                "energy": "XIAOYI_ENERGY_API_TOKEN",
                "traffic": "XIAOYI_MALACCA_API_TOKEN",
            }[system]
        )
        raw = local_request(self.urls[system], path, payload, token=token)
        return raw

    def record(self, action, data):
        number = len(self.evidence) + 1
        record = {
            "action": action,
            "response": data,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source": execution_origin(action["tool"]),
            "production_authority": False,
        }
        filename = f"evidence-{number:03d}.json"
        save(self.folder / filename, record)
        row = {"file": filename, "sha256": digest(record), "tool": action["tool"]}
        self.evidence.append(row)
        return row

    def read(self, target):
        path = {
            "port": "/api/v3/runtime/frame",
            "energy": "/api/runtime/snapshot",
            "traffic": "/api/operations/snapshot",
        }[target]
        raw = self.request(target, path)
        if target == "traffic":
            a = raw.get("authority", {})
            if a.get("simulation_mode") is not True or any(
                a.get(k) is not False for k in ["production_authority", "dispatch_allowed", "live_data_verified"]
            ):
                raise ValueError("traffic simulation contract failed")
        elif raw.get("production_authority") is not False:
            raise ValueError("simulation authority contract failed")
        if target == "port" and raw.get("available") is not True:
            raise ValueError("port runtime observation unavailable")
        if target == "energy" and raw.get("data_mode") != "public_data_calibrated_realtime_simulation":
            raise ValueError("energy source contract failed")
        fields = {
            "port": [("当前汇总功率", "aggregate_kw", "kW")],
            "energy": [
                ("购电功率", "signals.grid.import_power_kw.value", "kW"),
                ("当前服务满足率", "kpis.current.service_fulfilment_pct", "%"),
                ("当前安全违规数", "kpis.current.safety_violations", "次"),
            ],
            "traffic": [
                ("排队船舶", "kpis.queue_vessels", "艘"),
                ("延误时间", "kpis.delay_minutes", "min"),
                ("服务水平", "kpis.service_level_percent", "%"),
            ],
        }
        metrics = []
        for label, field, unit in fields[target]:
            if field == "signals.grid.import_power_kw.value":
                value = raw.get("signals", {}).get("grid.import_power_kw", {}).get("value")
            else:
                value = raw
                for component in field.split("."):
                    value = value.get(component) if isinstance(value, dict) else None
            metrics.append({"label": label, "field": field, "unit": unit, "value": value})
        self.summaries[target] = {
            "site_id": raw.get("site_id"),
            "observed_at": raw.get("generated_at", raw.get("ingest_time")),
            "event_time": raw.get("virtual_event_time", raw.get("event_time")),
            "source_mode": raw.get(
                "data_mode", raw.get("source", raw.get("telemetry", {}).get("mode", "engineering_simulation"))
            ),
            "metrics": metrics,
            "raw_sha256": digest(raw),
        }
        return raw

    def verify(self, env):
        checks = {}
        for e in self.evidence:
            data = json.loads((self.folder / e["file"]).read_text())
            checks[e["file"]] = digest(data) == e["sha256"]
        required = {r + ".read" for r in env.required["reads"]}
        if env.required["energy"]:
            required.add("energy.compare")
        if env.required["port"]:
            required.add("port.evaluate")
        checks["native_tools_present"] = required <= {e["tool"] for e in self.evidence}
        if env.required["restore"]:
            raw = self.read("energy")
            checks["clock_restored"] = (
                self.clock_before is not None
                and raw.get("simulator_state") == self.clock_before
                and not self.clock_owned
            )
        if not checks or not all(checks.values()):
            raise ValueError("native evidence verification failed: " + str(checks))
        return {
            "checks": checks,
            "evidence": self.evidence.copy(),
            "scope": "local persisted raw-response consistency; not third-party attestation",
        }

    def execute(self, action, env):
        tool, p = action["tool"], action["arguments"]
        if tool.endswith(".read"):
            return self.read(tool.split(".")[0])
        if tool == "energy.compare":
            from app.system_linkage import _compact_energy

            rows = []
            for green in [p["baseline_green_preference"], p["green_preference"]]:
                raw = self.request(
                    "energy",
                    "/api/optimization/recompute",
                    {"green_preference": green, "carbon_price_cny_per_ton": p["carbon_price_cny_per_ton"]},
                )
                summary = _compact_energy(raw)
                if (
                    raw.get("green_preference") != green
                    or raw.get("carbon_market", {}).get("carbon_price_cny_per_ton") != p["carbon_price_cny_per_ton"]
                ):
                    raise ValueError("native solver did not echo requested parameters")
                if summary.get("production_dispatch_enabled") is not False or not summary.get("dataset_sha256"):
                    raise ValueError("native energy provenance missing")
                rows.append(
                    {
                        "parameters": {"green": green, "carbon": p["carbon_price_cny_per_ton"]},
                        "summary": summary,
                        "raw": raw,
                    }
                )
            if rows[0]["summary"]["dataset_sha256"] != rows[1]["summary"]["dataset_sha256"]:
                raise ValueError("energy data changed between alternatives")
            self.summaries["energy_comparison"] = [{k: v for k, v in row.items() if k != "raw"} for row in rows]
            return {
                "alternatives": rows,
                "scope": "same public offline energy dataset; not a causal effect on live port load",
            }
        if tool == "port.evaluate":
            raw = self.request("port", "/api/v3/runtime/series?" + urlencode(p))
            points = raw.get("series", {}).get("p50", [])
            values = [float(row["kW"]) for row in points]
            if (
                raw.get("production_authority") is not False
                or raw.get("available") is not True
                or raw.get("scenario") != p["scenario"]
                or not values
            ):
                raise ValueError("native port series missing")
            self.summaries["port_evaluation"] = {
                "parameters": p,
                "points": len(values),
                "peak_kw": max(values),
                "average_kw": sum(values) / len(values),
            }
            policy = raw.get("policy", {})
            if (
                policy.get("model_sha256")
                and policy.get("loaded_model_sha256")
                and policy["model_sha256"] != policy["loaded_model_sha256"]
            ):
                self.summaries["port_evaluation"]["source_warning"] = (
                    "下游策略声明摘要与实际加载文件摘要不同。本次记录接口计算值，不据此认定既有业务策略版本通过验收或产生RL增益。"
                )
            return {"raw": raw, "summary": self.summaries["port_evaluation"]}
        if tool == "energy.pause":
            before = self.read("energy")
            self.clock_before = before.get("simulator_state")
            if self.clock_before not in {"running", "stopped"}:
                raise ValueError("unsupported clock state")
            result = self.request(
                "energy", "/api/runtime/control", {"action": "stop", "idempotency_key": env.task.case_id + "-pause"}
            )
            self.clock_owned = True
            if self.read("energy").get("simulator_state") != "stopped":
                raise ValueError("pause readback failed")
            return result
        if tool == "energy.restore":
            if not self.clock_owned or self.clock_before is None:
                raise ValueError("no owned clock change")
            if self.read("energy").get("simulator_state") != "stopped":
                raise ValueError("clock changed externally; recovery blocked")
            result = self.request(
                "energy",
                "/api/runtime/control",
                {
                    "action": "start" if self.clock_before == "running" else "stop",
                    "idempotency_key": env.task.case_id + "-restore",
                },
            )
            if self.read("energy").get("simulator_state") != self.clock_before:
                raise ValueError("restore readback failed")
            self.clock_owned = False
            return result
        if tool == "execution.verify":
            return self.verify(env)
        if tool == "execution.diagnose":
            results = {}
            for target in env.required["reads"]:
                try:
                    results[target] = {"ok": True, "sha256": digest(self.read(target))}
                except Exception as exc:
                    results[target] = {"ok": False, "error": str(exc)[:200]}
            return results
        if tool == "artifact.report":
            verification = self.verify(env)
            report = {
                "goal": env.task.goal(),
                "scope": "本机三个系统原生API；公开数据与工程模拟，非现场生产",
                "summaries": self.summaries,
                "verification": verification,
                "evidence": self.evidence.copy(),
                "summary_producer": "deterministic renderer of verified tool facts; not free-form LLM writing",
            }
            save(self.folder / "report.json", report)
            (self.folder / "report.html").write_text(report_html(report))
            return {"report": "report.json", "sha256": digest(report), "verification": verification["checks"]}
        if tool == "task.ask":
            return {"constraint_feedback": "本任务已提供全部登记参数；缺少新信息时应停止并交给用户"}
        raise ValueError("unregistered native tool")


def native_step(env, backend, label):
    before = copy.deepcopy(env)
    preview = copy.deepcopy(env)
    transition = preview.step(label)
    is_fault = transition["feedback"].startswith("read_timeout") and not before.fault_triggered
    if not transition["ok"]:
        env.__dict__.update(preview.__dict__)
        transition["native_executed"] = False
        transition["backend_executed"] = False
        transition["fault_injection"] = is_fault
        return transition
    try:
        response = backend.execute(env.actions[label], env)
        evidence = backend.record(env.actions[label], response)
        env.__dict__.update(preview.__dict__)
        transition["native_executed"] = True
        transition["backend_executed"] = True
        transition["execution_origin"] = execution_origin(env.actions[label]["tool"])
        transition["native_evidence"] = evidence
        transition["result"] = {
            "source": transition["execution_origin"],
            "evidence_file": evidence["file"],
            "sha256": evidence["sha256"],
        }
        transition["source"] = transition["execution_origin"]
        return transition
    except Exception as exc:
        env.last = "native_error:" + str(exc)[:240]
        transition = {
            "step": len(env.steps) + 1,
            "observation": before.observation(),
            "choice": label,
            "action": env.actions[label],
            "ok": False,
            "feedback": env.last,
            "reward": -0.2,
            "native_executed": True,
            "backend_executed": True,
            "execution_origin": execution_origin(env.actions[label]["tool"]),
            "native_result_valid": False,
            "model_action": True,
        }
        env.steps.append(transition)
        if len(env.steps) >= env.task.max_steps:
            env.done = True
        return transition


def environment_for_job(job):
    revision = job.get("environment", LEGACY_REVISION)
    environments = {LEGACY_REVISION: TaskEnvironment, PROGRESS_REVISION: ProgressEnvironment}
    if revision not in environments:
        raise ValueError("unregistered task environment revision")
    return environments[revision](TaskSpec(**job["task"]))


def execute_job(job, *, decider=None):
    folder = JOBS / job["id"]
    folder.mkdir(parents=True, exist_ok=True)
    env = environment_for_job(job)
    backend = NativeBackend(folder)
    started = time.monotonic()
    job["status"] = "running"
    job["runtime_source_sha256"] = RUNTIME_SOURCE_SHA256
    job["environment_source_sha256"] = {
        name: value
        for name, value in ENVIRONMENT_SOURCE_SHA256.items()
        if name == "environment.py" or isinstance(env, ProgressEnvironment)
    }
    save(folder / "job.json", job)
    try:
        while not env.done:
            prompt = env.prompt()
            if decider is None:
                response = local_request(
                    os.getenv("AGENT_RL_MODEL_URL", "http://127.0.0.1:18781"),
                    "/decide",
                    {"prompt": prompt, "group": job["group"]},
                    timeout=120,
                )
            else:
                response = decider(env)
            expected = job.get("expected_adapter_sha256")
            if expected and response.get("adapter_sha256") != expected:
                raise ValueError("当前推理权重与选定对照组不一致，停止任务")
            label = response["choice"]
            if label not in env.actions:
                raise ValueError("model produced unregistered action")
            transition = native_step(env, backend, label)
            transition["decision_input"] = prompt
            transition["model"] = response
            job.update(steps=env.steps, status="running", elapsed_seconds=round(time.monotonic() - started, 2))
            save(folder / "job.json", job)
        job.update(
            status="completed" if env.success else "failed",
            success=env.success,
            outcome=env.outcome(),
            steps=env.steps,
            evidence=backend.evidence,
            elapsed_seconds=round(time.monotonic() - started, 2),
            report="report.html" if env.success else None,
        )
    except Exception as exc:
        job.update(status="failed", success=False, error=str(exc)[:500], steps=env.steps, evidence=backend.evidence)
    finally:
        if backend.clock_owned:
            # Explicitly a runtime cleanup, never counted as a model-selected recovery.
            try:
                cleanup = backend.execute({"tool": "energy.restore", "arguments": {}}, env)
                job["runtime_cleanup"] = {"origin": "runtime_postcondition", "ok": True, "sha256": digest(cleanup)}
            except Exception as exc:
                job["runtime_cleanup"] = {"origin": "runtime_postcondition", "ok": False, "error": str(exc)[:300]}
        save(folder / "job.json", job)
    return job
