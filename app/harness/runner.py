from __future__ import annotations

import copy
import json
import re
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.access_control import has_permission
from app.harness import model, tools
from app.harness.contracts import (
    TERMINAL,
    WAITING,
    VERSION,
    Action,
    Budget,
    CreateTask,
    completed_tools,
    digest,
    encoded,
    now,
)
from app.harness.store import Conflict, HarnessStore


class DecisionChanged(RuntimeError):
    pass


class Harness:
    def __init__(self, store: HarnessStore, model_driver=None, workers=4):
        self.store = store
        self.model_driver = model_driver or model.CompatibleDriver()
        self.rules_driver = model.RulesDriver()
        self.instance = "hx-" + uuid4().hex
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="harness")
        self.lock = threading.RLock()
        self.active: set[str] = set()
        self.stopping = threading.Event()
        self.dispatcher: threading.Thread | None = None

    def start(self):
        with self.lock:
            if self.dispatcher and self.dispatcher.is_alive():
                return
            self.stopping.clear()
            self.dispatcher = threading.Thread(target=self._dispatch, daemon=True, name="harness-dispatch")
            self.dispatcher.start()

    def close(self):
        self.stopping.set()
        if self.dispatcher:
            self.dispatcher.join(timeout=2)
        # In-flight I/O reaches its bounded safe boundary; no write is replayed.
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _dispatch(self):
        while not self.stopping.wait(0.3):
            try:
                self.store.recover()
                for task in self.store.list(None, 200):
                    if task["status"] == "queued":
                        self.schedule(task["id"])
            except Exception:
                # Persistent tasks remain queued/recoverable if DB is temporarily busy.
                continue

    def create(self, payload: CreateTask, identity, *, schedule=True) -> dict:
        if (
            payload.mode == "research"
            or payload.model_profile == "open_agent"
            or payload.template_id in {"strategy-research", "joint-preview"}
        ):
            from app.harness.dual_api import enabled

            if not enabled():
                raise ValueError("双模式扩展已关闭")
        if (
            payload.template_id in {"strategy-research", "crossport-review", "remediation-review", "operations-study"}
            and payload.mode != "research"
        ):
            raise ValueError("策略研究模板需要研究模式")
        if not has_permission(identity.role, "chat.use"):
            raise PermissionError("当前角色没有任务使用权限")
        names = [s["name"] for s in tools.catalog(identity.role, payload.allowed_tools)]
        if payload.allowed_tools is None and payload.planning_mode == "adaptive":
            from app.harness.adaptive import ADAPTIVE_TOOLS

            names = [n for n in names if n in ADAPTIVE_TOOLS]
        elif payload.allowed_tools is None and payload.template_id not in {"strategy-research", "joint-preview"}:
            names = [n for n in names if not n.startswith(("strategy.", "joint."))]
        allowed = payload.allowed_tools if payload.allowed_tools is not None else names
        if not allowed or len(set(allowed)) != len(allowed) or any(n not in names for n in allowed):
            raise ValueError("任务工具范围必须是当前身份可用登记工具的非空子集")
        if any(s not in tools.SKILLS for s in payload.skills):
            raise ValueError("技能未登记")
        required = payload.required_tools
        effective_budget = payload.budget.model_dump()
        if payload.template_id:
            from app.harness.maritime import TEMPLATES

            from app.harness.contracts import DUAL_TEMPLATES

            template = next(t for t in [*TEMPLATES, *DUAL_TEMPLATES] if t["id"] == payload.template_id)
            for field, value in {
                "max_tokens": template["max_tokens"],
                "max_active_seconds": template["seconds"],
            }.items():
                if field not in payload.budget.model_fields_set:
                    effective_budget[field] = value
            if required is not None and not set(template["required_tools"]).issubset(required):
                raise ValueError("模板的交付条件不可省略")
            required = list(dict.fromkeys([*template["required_tools"], *(required or [])]))
        if required is None and payload.planning_mode == "adaptive":
            required = []
        if required is None:
            required = []
            for name, pattern in [
                ("runtime.snapshot", r"快照|当前港区|当前港口|实时态势"),
                ("knowledge.search", r"检索|SOP|法规|知识"),
                ("calculate", r"计算\s*[\d(]"),
                ("maritime.query", r"结构化问数|港航联合研判"),
                ("maritime.risk", r"港航联合研判|孪生情景对比"),
                ("twin.compare", r"港航联合研判|孪生情景对比"),
                ("maritime.handover", r"港航联合研判"),
            ]:
                if name in allowed and re.search(pattern, payload.goal, re.IGNORECASE):
                    required.append(name)
            if any(n in required for n in ["maritime.query", "maritime.risk", "twin.compare", "maritime.handover"]):
                if "runtime.snapshot" not in allowed:
                    raise ValueError("港航分析需要先采集本任务快照")
                required = list(dict.fromkeys(["runtime.snapshot", *required]))
        if "maritime.handover" in required:
            required = list(
                dict.fromkeys(["runtime.snapshot", "maritime.query", "maritime.risk", "twin.compare", *required])
            )
        elif any(name in required for name in ["maritime.query", "maritime.risk", "twin.compare"]):
            required = list(dict.fromkeys(["runtime.snapshot", *required]))
        if any(name not in allowed for name in required) or len(set(required)) != len(required):
            raise ValueError("交付所需工具必须是允许范围内的非重复工具")
        config = (
            model.configuration(payload.model_profile)
            if payload.model_profile == "open_agent"
            else model.configuration()
        )
        driver = "model" if payload.planning_mode == "adaptive" or payload.driver == "model" or payload.driver == "auto" and config["available"] else "rules"
        if driver == "model" and not config["available"] and isinstance(self.model_driver, model.CompatibleDriver):
            raise ValueError("模型尚未配置或外发未授权，可选择明确标识的规则运行")
        effective_budget = Budget.model_validate(effective_budget).model_dump()
        request_config = payload.model_dump(mode="json")
        request_config["budget"] = effective_budget
        task = {
            "id": "ht-" + uuid4().hex,
            "schema": VERSION,
            "actor_id": identity.actor_id,
            "actor_role": identity.role,
            "request_id": payload.request_id,
            "request_sha256": digest(request_config),
            "goal": payload.goal,
            "driver": driver,
            "driver_requested": payload.driver,
            "planning_mode": payload.planning_mode,
            "mode": payload.mode,
            "model_profile": payload.model_profile,
            "template_id": payload.template_id,
            "output_policy": {
                "port-briefing": "verified_business_report",
                "joint-preview": "verified_joint_plan",
                "strategy-research": "verified_research_report",
                "port-future-study": "verified_public_port_report",
                "crossport-review": "verified_crossport_report",
                "remediation-review": "verified_remediation_report",
                "operations-study": "verified_operations_report",
            }.get(payload.template_id, "model_or_rules_summary"),
            "joint_context": payload.joint_context.model_dump() if payload.joint_context else None,
            "operations_context": payload.operations_context,
            "model": config["name"] if driver == "model" else None,
            "model_local": config["local"],
            "allowed_tools": allowed,
            "required_tools": required,
            "skills": payload.skills,
            "use_memory": payload.use_memory,
            "skill_versions": {s: digest(tools.SKILLS[s]) for s in payload.skills},
            "skill_snapshots": {s: copy.deepcopy(tools.SKILLS[s]) for s in payload.skills},
            "budget": effective_budget,
            "status": "queued",
            "created_at": now(),
            "updated_at": now(),
            "inputs": [],
            "plan": [],
            "results": [],
            "pending": None,
            "inflight": {},
            "final": None,
            "control": {"cancel": False, "pause": False},
            "usage": {
                "steps": 0,
                "tool_calls": 0,
                "tokens": 0,
                "tokens_estimated": False,
                "active_seconds": 0.0,
                "compactions": 0,
            },
            "stop_reason": "",
            "production_authority": False,
            "failure_count": 0,
        }
        result, created = self.store.create(task)
        if created and schedule:
            self.schedule(result["id"])
        return result

    def schedule(self, task_id):
        with self.lock:
            if task_id in self.active or len(self.active) >= 4 or self.stopping.is_set():
                return
            if not self.store.claim(task_id, self.instance):
                return
            self.active.add(task_id)
        self.pool.submit(self._work, task_id)

    def _mutate(self, task_id, fn, event, detail=None):
        return self.store.mutate(task_id, fn, event, detail, owner=self.instance)

    def _stop(self, task_id, status, reason):
        return self._mutate(
            task_id, lambda t: t.update(status=status, stop_reason=reason), "task." + status, {"reason": reason}
        )

    def _boundary(self, task_id, after_model=False):
        task = self.store.get(task_id)
        if task["status"] != "running":
            return None
        if task["control"]["cancel"]:
            self._stop(task_id, "cancelled", "用户取消；未决目标操作请按关联回执核查")
            return None
        if task["control"]["pause"] or self.stopping.is_set():
            self._stop(task_id, "paused", "已在安全边界暂停")
            return None
        if (
            (
                not after_model
                and task["usage"]["steps"] >= task["budget"]["max_steps"]
                and not self._can_publish_report(task)
            )
            or task["usage"]["tokens"] > task["budget"]["max_tokens"]
            or task["usage"]["active_seconds"] >= task["budget"]["max_active_seconds"]
        ):
            self._stop(task_id, "budget_exceeded", "达到任务资源预算；未将预算退出标记为完成")
            return None
        return task

    @staticmethod
    def _can_publish_report(task):
        if task.get("output_policy") in {
            "verified_joint_plan",
            "verified_research_report",
            "verified_public_port_report",
            "verified_crossport_report",
            "verified_remediation_report",
            "verified_operations_report",
        }:
            return bool(
                not task.get("inputs")
                and task.get("required_tools")
                and set(task["required_tools"]).issubset(completed_tools(task))
            )
        return (
            task.get("output_policy") == "verified_business_report"
            and not task.get("inputs")
            and set(task["required_tools"]).issubset(completed_tools(task))
            and any(r["tool"] == "maritime.handover" and r["ok"] for r in task["results"])
        )

    def _publish_report(self, task):
        if task.get("output_policy") == "verified_operations_report":
            from app.harness import operations_v5
            from app.harness.maritime import result

            row = next(r for r in task["results"] if r["tool"] == "operations.optimize" and r["ok"])
            data = result(task, self.store, row["id"], {"operations.optimize"})
            if (
                data["source_sha256"]
                != operations_v5.hashlib.sha256(Path(operations_v5.__file__).read_bytes()).hexdigest()
            ):
                self._stop(task["id"], "blocked", "联合优化源码在交付前变化")
                return True
            entry = data["problem"]["source"]["entry"]
            operations_v5.checked(entry["path"], entry["sha256"])
            chosen = data["selected"]
            origin = (
                "模型实际选择优化工具；正式报告由核验工件汇总。"
                if task["driver"] == "model"
                else "规则实际调用优化工具；正式报告由核验工件汇总。"
            )
            text = origin + "\n公开来源：" + entry["name"] + "；" + str(data["problem"]["input"]) + "\n"
            text += "\n".join(
                f"{b['algorithm']}：目标分值{b['objective_points']}，完成{b['completed_calls']}，暂缓{b['deferred_calls']}。"
                for b in data["baselines"]
            )
            text += f"\n采用{chosen['algorithm']}，目标分值{chosen['objective_points']}；相对最佳启发式改善百分比{data['objective_improvement_vs_best_baseline_pct']}。"
            text += f"\n最优性已证明：{data['solver']['optimality_proven']}；求解间隙{data['solver']['mip_gap']}；等待小时{chosen['total_waiting_hours']}；电网电量kWh{chosen['grid_energy_kwh']}。"
            text += "\n" + data["notice"] + "\n" + "；".join(data["problem"]["assumptions"])
            return self._finalize(
                task,
                Action(kind="final", text=text, evidence_ids=[row["id"]]),
                producer={"mode": task["output_policy"], "model_authored": False, "notice": origin},
            )
        if task.get("output_policy") == "verified_remediation_report":
            from app.harness.remediation_v2 import compact_review
            from app.harness.maritime import result

            row = next(r for r in task["results"] if r["tool"] == "remediation.review" and r["ok"])
            data = result(task, self.store, row["id"], {"remediation.review"})
            current = compact_review()
            if current["registry_sha256"] != data["registry_sha256"]:
                self._stop(task["id"], "blocked", "整改证据在交付前发生变化")
                return True
            origin = (
                "模型实际选择证据工具；正式报告由已核验工件汇总。"
                if task["driver"] == "model"
                else "规则驱动；正式报告由已核验工件汇总。"
            )
            counts = data["counts"]
            text = origin + f"\n强基线：{data['selected_baseline']}；验证选定RL：{data['selected_rl']}。\n"
            text += "\n".join(
                f"{r['algorithm']}：留出Score {r['test_score']}；研究准入 {r['research_admission']}；阻断项 {','.join(r['blockers'])}"
                for r in data["aggregate"]
            )
            text += f"\n需求预测{counts['forecast_passed']}/{counts['forecast_total']}；长期开环{counts['long_passed']}/{counts['long_total']}；短期同化{counts['short_passed']}/{counts['short_total']}。"
            text += (
                "\n全仓发布检查："
                + str(data["quality_passed"])
                + "；现场证据缺项："
                + ",".join(k for k, v in data["field_evidence"].items() if not v)
            )
            if not current["current"]:
                text += "\n存在版本漂移，暂缓采信当前准入。"
            text += "\n" + data["notice"]
            if data.get("diagnostics"):
                finding = data["diagnostics"]
                text += (
                    f"\n本轮安全过滤器干预比例：{finding['safety_override_fraction']}；"
                    f"与安全MPC动作差：{finding['action_mismatches_vs_safe_mpc']}；"
                    f"全局代理成本增加百分比：{finding['global_proxy_cost_increase_vs_cost_mpc_pct']}；"
                    f"等港口相对成本增加百分比：{finding['equal_port_relative_cost_increase_pct']}。"
                )
            if data.get("weekly_forcing"):
                text += "\n七日天气强迫（另列，不替代年度资格）：" + encoded(data["weekly_forcing"])
            if data.get("latest_research"):
                latest = data["latest_research"]
                rl = latest["selected_rl"]
                text += f"\n最新V6独立验证：成本强基线{latest['selected_cost_baseline']}；RL相对成本改善比例{rl['new_port_relative_cost_interval']['mean_delta']}，研究准入{rl['research_admission']}；失败{','.join(rl['blockers'])}。"
                text += "\n完整年度、各季度和新晚期时段分别验收：" + encoded(
                    {k: latest[k] for k in ["annual", "quarters", "new_periods"]}
                )
                text += "\n" + latest["notice"]
                if latest.get("posthoc_diagnosis"):
                    diagnostic = latest["posthoc_diagnosis"]
                    text += "\n查看留出后追加的公平原策略比较（仅诊断，不计独立准入）：" + encoded(
                        diagnostic["raw_to_raw_comparisons"]
                    )
            if data.get("capability_scores"):
                text += "\n功能评分为本次证据审视，非第三方排名：\n" + "\n".join(
                    f"{r['name']}：{r['score']}分" for r in data["capability_scores"]
                )
            return self._finalize(
                task,
                Action(kind="final", text=text, evidence_ids=[r["id"] for r in task["results"] if r["ok"]]),
                producer={"mode": task["output_policy"], "model_authored": False, "notice": origin},
            )
        if task.get("output_policy") == "verified_crossport_report":
            from app.harness import crossport
            from app.harness.maritime import result

            row = next(r for r in task["results"] if r["tool"] == "crossport.compare" and r["ok"])
            data = result(task, self.store, row["id"], {"crossport.compare"})
            checked = crossport.compare(
                crossport.CompareArgs(study_id=data["study_id"]), task["actor_id"], task["actor_role"] == "admin"
            )
            if checked["report_sha256"] != data["report_sha256"]:
                self._stop(task["id"], "blocked", "跨港研究证据在交付前变化")
                return True
            notice = (
                "模型实际选择工具；正式报告由核验工件整理。"
                if task["driver"] == "model"
                else "规则驱动；正式报告由核验工件整理。"
            )
            text = (
                notice + f"\n验证集选型：{data['selected_algorithm']}；固定比较基线：{data['comparator_algorithm']}。\n"
            )
            text += "\n".join(
                f"{r['algorithm']}：常态测试Score {r['nominal_test_score']}；研究准入 {r['research_admission']}；阻断项 {','.join(r['blockers'])}"
                for r in data["aggregate"]
            )
            text += "\n旧RL状态覆盖、奖励和行为策略诊断为探索性旧测试复盘，不冒充新留出验证。"
            if checked["historical_only"]:
                text += "\n当前是历史版本，证据暂缓采信；不能用于当前准入。"
            if not data["multisite_physical_calibration"]["all_station_calibration_gates_passed"]:
                text += "\n多站点物理标定仍有未通过指标，暂缓扩大物理适用范围。"
            text += "\n" + data["notice"]
            return self._finalize(
                task,
                Action(kind="final", text=text, evidence_ids=[r["id"] for r in task["results"] if r["ok"]]),
                producer={"mode": task["output_policy"], "model_authored": False, "notice": notice},
            )
        if task.get("output_policy") == "verified_public_port_report":
            from app.harness import public_port

            artifacts = {}
            for row in task["results"]:
                if row["ok"]:
                    from app.harness.maritime import result

                    artifacts[row["tool"]] = result(task, self.store, row["id"], {row["tool"]})
            sources = artifacts["evidence.public_catalog"]
            current = public_port.catalog()
            if current["manifest_sha256"] != sources["manifest_sha256"] or not all(
                e["integrity_valid"] for e in current["entries"]
            ):
                self._stop(task["id"], "blocked", "公开来源在交付前变化或摘要不一致，请创建新的历史复盘任务")
                return True
            study, forecast = artifacts["port.study"], artifacts["twin.validate_public"]
            plan, selected = study["plan"], study["plan"]["selected"]
            notice = (
                "模型负责实际工具选择；正式报告由受控工件整理。"
                if task["driver"] == "model"
                else "规则驱动；正式报告由受控工件整理。"
            )
            text = notice + "\n公开历史资料的出处、时期、单位、变换及缺测已记录，现场作业权限关闭。\n"
            if selected:
                text += f"JIT工程排程采用{selected['method']}；等待{selected['metrics']['total_wait_minutes']}分钟；迟延{selected['metrics']['total_late_minutes']}分钟；完工{selected['metrics']['makespan_minutes']}分钟。\n"
            else:
                text += "JIT完整资源方案不可行，暂缓推荐。\n"
            text += f"水位留出点数{forecast['holdout']['n']}；MAE {forecast['holdout']['mae']} m；持续值基线MAE {forecast['holdout']['baseline_mae']} m。\n"
            text += (
                "所列水位研究阈值通过，仍需独立现场标定。\n"
                if forecast["validation_passed"]
                else "水位研究阈值未全部通过，暂缓采信。\n"
            )
            text += study["notice"] + "\n" + forecast["notice"]
            self._mutate(
                task["id"],
                lambda t: None,
                "report.compiled",
                {"producer": task["output_policy"], "manifest_sha256": current["manifest_sha256"]},
            )
            return self._finalize(
                task,
                Action(kind="final", text=text, evidence_ids=[r["id"] for r in task["results"] if r["ok"]]),
                producer={"mode": task["output_policy"], "model_authored": False, "notice": notice},
            )
        if task.get("output_policy") in {"verified_joint_plan", "verified_research_report"}:
            name = "joint.preview" if task["output_policy"] == "verified_joint_plan" else "strategy.compare"
            row = next(r for r in task["results"] if r["tool"] == name and r["ok"])
            data = json.loads(self.store.artifact(task["id"], row["artifact"])["content"])
            notice = (
                "模型负责工具选择与参数；正式交付由受控工件整理。"
                if task["driver"] == "model"
                else "规则驱动；正式交付由受控工件整理。"
            )
            if name == "joint.preview":
                text = (
                    notice
                    + f"\n\n联合评估计划已生成，尚未执行。任务编号：{data['id']}。请在双模式联合工作台审阅并审批此计划。\n"
                )
                text += "\n".join(s["label"] for s in data["plan"]["steps"])
                text += "\n" + data["notice"]
            else:
                text = notice + f"\n\n实验：{data['experiment_id']}；验证集选型：{data['selected_algorithm']}。\n"
                text += "\n".join(
                    f"{r['algorithm']}：测试Score均值 {r['metrics']['score']}；约束违反 {r['metrics']['constraint_violations']}；研究准入 {r['research_admission']}"
                    for r in data["aggregate"]
                )
                text += "\n" + data["notice"] + "\n策略回放保留实际状态、动作、奖励与动作掩码。"
            self._mutate(
                task["id"],
                lambda t: None,
                "report.compiled",
                {"source_artifact": row["artifact"], "producer": task["output_policy"]},
            )
            return self._finalize(
                task,
                Action(kind="final", text=text, evidence_ids=[r["id"] for r in task["results"] if r["ok"]]),
                producer={
                    "mode": task["output_policy"],
                    "model_authored": False,
                    "source_artifact": row["artifact"],
                    "notice": notice,
                },
            )
        from app.harness import maritime

        row = next(r for r in reversed(task["results"]) if r["tool"] == "maritime.handover" and r["ok"])
        report = maritime.result(task, self.store, row["id"], {"maritime.handover"})
        snapshot, _ = maritime.source(task, self.store, report["source_ref"])
        gate = maritime.readiness(snapshot)
        qualification = (
            "交付时数据检查通过，仍需人工复核。"
            if gate["analysis_usable"]
            else "交付时证据时效或质量未通过，当前建议暂缓，需更新数据后复核。"
        )
        origin = (
            "模型负责工具决策；正式报告由已核验交接工件整理，不作为模型自由撰写能力的证据。"
            if task["driver"] == "model"
            else "规则驱动（未使用模型自主规划）；正式报告由已核验交接工件整理。"
        )
        text = (
            origin
            + "\n\n"
            + qualification
            + "现场放行关闭。\n\n"
            + report["markdown"].replace("数据可分析：", "工件生成时数据可分析：")
        )
        self._mutate(
            task["id"],
            lambda t: None,
            "report.compiled",
            {"source_artifact": row["artifact"], "producer": "verified_business_report"},
        )
        return self._finalize(
            task,
            Action(kind="final", text=text, evidence_ids=list(dict.fromkeys([*report["evidence_refs"], row["id"]]))),
            producer={
                "mode": "verified_business_report",
                "source_artifact": row["artifact"],
                "model_authored": False,
                "notice": origin,
            },
        )

    def _work(self, task_id):
        heartbeat_stop = threading.Event()

        def beat():
            while not heartbeat_stop.wait(10):
                if not self.store.heartbeat(task_id, self.instance):
                    return

        heartbeat = threading.Thread(target=beat, daemon=True)
        heartbeat.start()
        tick = time.monotonic()

        def charge(**usage):
            nonlocal tick
            elapsed = time.monotonic() - tick
            tick = time.monotonic()

            def update(t):
                t["usage"]["active_seconds"] += round(elapsed, 4)
                for key, value in usage.items():
                    if key == "tokens_estimated":
                        t["usage"][key] = t["usage"][key] or value
                    else:
                        t["usage"][key] += value

            return self._mutate(task_id, update, "usage.updated")

        try:
            while (task := self._boundary(task_id)) is not None:
                if task.get("planning_mode") == "adaptive" and "execution.verify" in task["allowed_tools"]:
                    # Verification is a runtime postcondition, not a business
                    # plan. Failed checks return to the model for a new decision.
                    due = []
                    for record in task["results"]:
                        if record["tool"] == "linked.action" and record["ok"]:
                            due.append(record["id"])
                        elif record["tool"] == "execution.verify":
                            due = [ref for ref in due if ref != record["arguments"]["source_ref"]]
                        elif record["tool"] == "execution.restore" and record["ok"]:
                            due.append(record["arguments"]["source_ref"])
                    if due:
                        self._mutate(task_id, lambda t: None, "verification.scheduled", {"source_ref":due[0], "origin":"runtime_postcondition"})
                        continued = self._invoke(task, Action(kind="tool", tool="execution.verify", arguments={"source_ref":due[0]}))
                        charge()
                        if not continued:
                            break
                        continue
                if self._can_publish_report(task):
                    finished = self._publish_report(task)
                    charge()
                    if finished:
                        break
                    continue
                if task.get("pending") and task["pending"].get("decision") == "approved":
                    pending = task["pending"]
                    if time.time() > pending["expires_epoch"] or pending["action_sha256"] != digest(pending["action"]):
                        self._stop(task_id, "blocked", "审批已过期或动作不一致，请创建新的明确任务")
                        break
                    action = Action.model_validate(pending["action"])
                    continued = self._invoke(task, action, prepared=pending.get("prepared"))
                    charge()
                    if not continued:
                        break
                    continue
                memories = self.store.memories(task["actor_id"]) if task["use_memory"] else []
                if task["driver"] == "model":
                    from app.harness.semantic import snapshot_view

                    # Re-derive from the immutable artifact after any steering;
                    # never treat a previous shortened view as the source of truth.
                    goal = task["goal"] + "\n" + "\n".join(i["text"] for i in task.get("inputs", []))
                    for record in task["results"]:
                        if record["ok"] and record["tool"] == "runtime.snapshot":
                            artifact = self.store.artifact(task_id, record["artifact"])
                            if not artifact or artifact["sha256"] != digest(artifact["content"]) or artifact["sha256"] != record["sha256"]:
                                raise ValueError("快照工件完整性不通过，未向模型提供事实视图")
                            record["source_facts"] = snapshot_view(json.loads(artifact["content"])["snapshot"], goal)
                messages, compacted = model.context(task, memories)
                if compacted:
                    charge(compactions=1)
                # A durable intent precedes every model call; a format failure still consumes a step.
                self._mutate(
                    task_id,
                    lambda t: t["usage"].update(steps=t["usage"]["steps"] + 1),
                    "model.started",
                    {"driver": task["driver"]},
                )
                task = self.store.get(task_id)
                revision = len(task["inputs"])
                try:
                    driver = self.model_driver if task["driver"] == "model" else self.rules_driver
                    action, usage = driver.next(task, messages)
                    charge(tokens=usage.get("tokens", 0), tokens_estimated=usage.get("estimated", False))
                    if usage.get("performance"):
                        self._mutate(task_id, lambda t: None, "model.performance", usage["performance"])
                except Exception as exc:
                    charge(tokens=getattr(exc, "tokens", 0))
                    if isinstance(exc, PermissionError):
                        self._stop(task_id, "blocked", tools.safe_error(exc))
                        break
                    if getattr(exc, "response_text", None):
                        self.store.artifact(task_id, f"model-error-{task['usage']['steps']}.txt", exc.response_text)
                    self._mutate(
                        task_id,
                        lambda t, error_message=getattr(exc, "validation_error", tools.safe_error(exc)): t.update(
                            failure_count=t["failure_count"] + 1,
                            last_model_error=error_message,
                        ),
                        "model.failed",
                        {"error": tools.safe_error(exc)},
                    )
                    if self.store.get(task_id)["failure_count"] >= 2:
                        self._stop(task_id, "failed", tools.safe_error(exc))
                        break
                    continue
                task = self._boundary(task_id, after_model=True)
                if not task:
                    break
                # New input invalidates a model decision made on an older user context.
                if len(task["inputs"]) != revision:
                    self._mutate(task_id, lambda t: None, "model.discarded", {"reason": "运行中收到新的用户约束"})
                    continue
                self._mutate(task_id, lambda t: None, "model.action", action.model_dump(mode="json"))
                if action.kind == "plan":
                    if task["plan"] and task.get("plan_at_result_count", 0) == len(task["results"]):
                        self._stop(task_id, "blocked", "重复规划但未执行，触发无进展保护")
                        break

                    def update_plan(t):
                        self._check_decision(t, task)
                        t.update(
                            plan=action.steps,
                            plan_at_result_count=len(t["results"]),
                            plan_at_input_count=len(t["inputs"]),
                            plan_at_failure_count=sum(not r["ok"] for r in t["results"]),
                        )

                    try:
                        self._mutate(task_id, update_plan, "plan.updated")
                    except DecisionChanged:
                        continue
                elif action.kind == "ask":
                    if model.read_before_clarifying(task):
                        self._mutate(
                            task_id,
                            lambda t: t.update(
                                last_model_error="本历史复盘模板的只读参数与验证方法已登记，请先读取剩余必需工具结果；不重复向用户索取已有参数。"
                            ),
                            "clarification.deferred",
                            {"reason": "registered_read_defaults_available"},
                        )
                        charge()
                        continue

                    def ask_user(t):
                        self._check_decision(t, task)
                        t.update(status="waiting_input", question=action.text)

                    try:
                        self._mutate(task_id, ask_user, "task.waiting_input")
                    except DecisionChanged:
                        continue
                    break
                elif action.kind == "final":
                    if self._finalize(task, action):
                        break
                    continue
                else:
                    continued = self._invoke(task, action)
                    charge()
                    if not continued:
                        break
                    continue
                charge()
        except Conflict:
            # Lost lease: this worker has no authority to publish or start more calls.
            pass
        except Exception as exc:
            try:
                task = self.store.get(task_id)
                status = "needs_review" if task.get("inflight", {}).get("side_effect") else "failed"
                self._stop(task_id, status, tools.safe_error(exc))
            except Exception:
                pass
        finally:
            heartbeat_stop.set()
            self.store.release(task_id, self.instance)
            with self.lock:
                self.active.discard(task_id)

    def _invoke(self, task, action: Action, prepared=None):
        task_id = task["id"]
        try:
            args = tools.validate(action.tool, action.arguments, task)
            if action.tool == "linked.action":
                # User constraints are enforced even if the model proposes a contradictory call.
                user_text = task["goal"] + "\n" + "\n".join(i["text"] for i in task["inputs"])
                if tools.ACTIONS[args.action_id].get("mutates") and re.search(
                    r"只读|仅查询|不要.*(?:改|调|操作)|不调整|禁止.*(?:改|调|操作)", user_text
                ):
                    raise PermissionError("用户约束禁止修改配置")
            fingerprint = digest({"tool": action.tool, "arguments": args.model_dump(mode="json")})
            repeated = [r for r in task["results"] if r["fingerprint"] == fingerprint]
            if task.get("planning_mode") == "adaptive":
                repeated = [r for r in repeated if r.get("input_revision", 0) == len(task["inputs"])]
                if action.tool == "linked.action" and any(r["ok"] for r in repeated):
                    raise ValueError("本任务已完成相同操作，禁止重复下发。请根据现有结果结束或选择新的必要操作。")
                if len(repeated) >= 2 and all(r["ok"] for r in repeated[-2:]):
                    self._stop(task_id, "blocked", "同一参数已成功读取或执行两次，未向目标推进；停止重复调用，可按回执诊断")
                    return False
            if len(repeated) >= 2 and repeated[-1]["sha256"] == repeated[-2]["sha256"]:
                self._stop(task_id, "blocked", "相同工具与参数重复且无进展，已停止")
                return False
            cost = 1 + (len(args.branches) if action.tool == "research.parallel" else 0)
            if task["usage"]["tool_calls"] + cost > task["budget"]["max_tool_calls"]:
                self._stop(task_id, "budget_exceeded", "工具调用预算不足，未执行本次动作")
                return False
            if tools.REGISTRY[action.tool][2] and prepared is None:
                preview = (tools.prepare_action(task, action.arguments) if action.tool == "linked.action"
                           else tools.prepare_action(task, action.arguments, name=action.tool, store=self.store))
                proposal = action.model_dump(mode="json")
                pending = {
                    "id": "ha-" + uuid4().hex,
                    "action": proposal,
                    "action_sha256": digest(proposal),
                    "prepared": preview,
                    "decision": "pending",
                    "expires_epoch": min(time.time() + 300, preview["expires_at_epoch"]),
                }

                def request_approval(t):
                    self._check_decision(t, task)
                    t.update(status="waiting_approval", pending=pending)

                self._mutate(
                    task_id,
                    request_approval,
                    "approval.requested",
                    {"id": pending["id"], "action_sha256": pending["action_sha256"]},
                )
                return False
        except DecisionChanged:
            return True
        except Exception as exc:
            if task.get("planning_mode") == "adaptive" and not isinstance(exc, PermissionError) and task.get("argument_repairs", 0) < 2:
                self._mutate(task_id, lambda t, error=tools.safe_error(exc): t.update(argument_repairs=t.get("argument_repairs", 0) + 1,
                    last_model_error="本次工具未执行，可修正参数或读取状态后重试：" + error),
                    "tool.rejected", {"tool": action.tool, "error": tools.safe_error(exc), "executed": False})
                return True
            self._stop(task_id, "blocked", tools.safe_error(exc))
            return False
        call_id = "hc-" + uuid4().hex
        side_effect = tools.REGISTRY[action.tool][2]

        def start(t):
            self._check_decision(t, task)
            t["usage"]["tool_calls"] += cost
            t["inflight"] = {
                "id": call_id,
                "tool": action.tool,
                "arguments": action.arguments,
                "side_effect": side_effect,
                "started_at": now(),
            }
            t["pending"] = None

        try:
            self._mutate(
                task_id, start, "tool.started", {"call_id": call_id, "tool": action.tool, "arguments": action.arguments}
            )
        except DecisionChanged:
            return True
        started = time.monotonic()

        def cancelled():
            current = self.store.get(task_id)
            return current["control"]["cancel"] or current["control"]["pause"] or self.stopping.is_set()

        try:
            result = tools.execute(
                action.tool, action.arguments, task, self.store, prepared=prepared, call_id=call_id, cancelled=cancelled
            )
            ok = result.get("status") not in {"failed", "needs_review", "cancelled", "blocked", "partial", "rejected", "budget_exceeded"}
            if action.tool == "research.parallel":
                ok = any(b["ok"] for b in result["branches"])
        except Exception as exc:
            result, ok = {"error": tools.safe_error(exc)}, False
        try:
            raw = encoded(result)
        except (TypeError, ValueError):
            result, ok = {"error": "工具输出不符合有限JSON数据契约，未作为有效结果使用"}, False
            raw = encoded(result)
        # A source larger than the cap must fail visibly, never be silently truncated as a complete artifact.
        if len(raw.encode()) > 200000:
            result, ok = {"error": "工具输出超过单工件200KB上限，未保存不完整结果"}, False
            raw = encoded(result)
        result_id = "T" + str(len(task["results"]) + 1)
        name = result_id + ".json"
        self.store.artifact(task_id, name, raw, "application/json")
        summary = self._summary(action.tool, result)
        record = {
            "id": result_id,
            "call_id": call_id,
            "tool": action.tool,
            "arguments": action.arguments,
            "ok": ok,
            "partial": action.tool == "research.parallel"
            and ok
            and any(not b["ok"] for b in result.get("branches", [])),
            "executed_tools": [action.tool]
            + (
                [b["tool"] for b in result.get("branches", []) if b["ok"]] if action.tool == "research.parallel" else []
            ),
            "summary": summary,
            "artifact": name,
            "sha256": digest(raw),
            "fingerprint": fingerprint,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "input_revision": len(task["inputs"]),
        }
        if ok and action.tool == "runtime.snapshot":
            from app.harness.semantic import snapshot_view

            goal = task["goal"] + "\n" + "\n".join(i["text"] for i in task.get("inputs", []))
            record["source_facts"] = snapshot_view(result["snapshot"], goal)

        def finish(t):
            if ok:
                # Repair feedback describes the earlier state. Do not keep
                # asking the model to fix a missing result after it has arrived.
                # The append-only event ledger retains the original rejection.
                t.pop("last_model_error", None)
            if ok and not side_effect and t.get("planning_mode") == "adaptive":
                for previous in t["results"]:
                    if not previous["ok"] and previous["fingerprint"] == fingerprint:
                        previous["resolved_by"] = result_id
            t["results"].append(record)
            if ok or not side_effect:
                t["inflight"] = {}
            if not ok and side_effect:
                t.update(status="needs_review", stop_reason="联动结果未核验成功；请查看关联目标回执，未自动重试")

        current = self._mutate(task_id, finish, "tool.completed" if ok else "tool.failed", record)
        return current["status"] == "running"

    @staticmethod
    def _check_decision(current, decided):
        if (
            current["status"] != "running"
            or any(current["control"].values())
            or len(current["inputs"]) != len(decided["inputs"])
        ):
            raise DecisionChanged("用户约束或任务状态已变化，丢弃旧决策")

    @staticmethod
    def _summary(name, result):
        if name == "systems.inspect" and result.get("resource") == "status":
            data = result["data"]
            return encoded({"target": result["target"], "resource": "status", "systems": data["systems"],
                "read_resources": data["read_resources"], "available_actions": [a["id"] for a in data["actions"]],
                "production_authority": False})
        if name == "linked.action" and result.get("receipt"):
            receipt = result["receipt"]
            return encoded({"linked_run_id": result["linked_run_id"], "status": result["status"],
                "action_id": receipt["plan"]["action_id"], "parameters": receipt["plan"]["parameters"],
                "applied": receipt.get("applied"), "restored": receipt.get("restored"),
                "evaluation": receipt.get("evaluation"), "production_authority": False})[:3000]
        if name == "strategy.compare" and result.get("experiment_id"):
            return encoded({k: result[k] for k in ["experiment_id", "selected_algorithm", "aggregate", "policy_assurance", "notice"] if k in result})[:3500]
        if name == "strategy.replay" and result.get("result"):
            data = result["result"]
            return encoded({"experiment_id": result["experiment_id"], "model_sha256": result["model_sha256"],
                "notice": result["notice"], "result": {k: v for k, v in data.items() if k not in {"trajectory", "frames", "trace"}}})[:3000]
        if result.get("error"):
            return result["error"]
        if name == "remediation.review":
            return "八项整改的新国际港口与2026留出已读取；保留RL、物理与现场缺项。" + encoded(
                {
                    "current": result["current"],
                    "selected_rl": result["selected_rl"],
                    "selected_baseline": result["selected_baseline"],
                    "counts": result["counts"],
                    "quality_passed": result["quality_passed"],
                }
            )
        if name == "crossport.diagnosis":
            return (
                "已读取冻结旧RL的实证消融；低状态覆盖、动作记忆缺项、资源奖励与双表行为分别保留，属于旧测试探索诊断。"
                + encoded(
                    {"findings": result["observation_findings"], "markov_alias_probe": result["markov_alias_probe"]}
                )
            )
        if name == "crossport.compare":
            return (
                "跨港研究为公开AIS衍生指标驱动的服务代理；不是现场收益或全港物理标定。"
                + encoded(
                    {
                        "study_id": result["study_id"],
                        "historical_only": result["historical_only"],
                        "selected_algorithm": result["selected_algorithm"],
                        "comparator_algorithm": result["comparator_algorithm"],
                        "results": [
                            {k: r[k] for k in ["algorithm", "nominal_test_score", "research_admission", "blockers"]}
                            for r in result["aggregate"]
                        ],
                        "physical_all_gates_passed": result["multisite_physical_calibration"][
                            "all_station_calibration_gates_passed"
                        ],
                    }
                )[:2400]
            )
        if name == "evidence.public_catalog":
            return (
                "真实公开历史数据清单；原始链接、时期与SHA-256见工件。"
                + encoded(
                    {
                        "entries": [
                            {
                                k: e.get(k)
                                for k in ["id", "provider", "time_start", "time_end", "rows", "unit", "integrity_valid"]
                            }
                            for e in result["entries"]
                        ]
                    }
                )[:2500]
            )
        if name == "port.study":
            plan = result["plan"]
            return "历史数据驱动工程推演；挂靠、设备能力和服务时间为显式假设，未证明最优或现场收益。" + encoded(
                {
                    "site": result["config"]["site"],
                    "scenario": result["config"]["scenario"],
                    "status": plan["recommendation_status"],
                    "blockers": plan["blockers"],
                    "selected_method": (plan["selected"] or {}).get("method"),
                    "metrics": (plan["selected"] or {}).get("metrics"),
                    "missing": result["missing_for_site_validation"],
                }
            )
        if name == "twin.validate_public":
            state = "留出检查通过，仍需独立现场标定" if result["validation_passed"] else "暂缓预测采信，存在未通过指标"
            return (
                state
                + "；仅公开站点水位短期前推，不等于物理孪生准入。"
                + encoded(
                    {
                        k: result[k]
                        for k in ["model_version", "unit", "calibration", "holdout", "blockers", "operational_release"]
                    }
                )
            )
        if name == "maritime.query":
            return (
                "港区问数（保留单位与原始快照引用）"
                + encoded(
                    {
                        k: result[k]
                        for k in ["source_ref", "observed_at", "rows", "matched_count", "truncated", "readiness"]
                    }
                )[:2200]
            )
        if name == "maritime.risk":
            status = "暂缓，先核对数据时效与质量" if result["recommendation_status"] == "withheld" else "需人工复核"
            return (
                f"工程风险筛查，建议状态={status}（{result['recommendation_status']}）；检查时数据通过={result['readiness']['analysis_usable']}；现场放行关闭。"
                + encoded(
                    {
                        k: result[k]
                        for k in [
                            "source_ref",
                            "readiness",
                            "recommendation_status",
                            "finding_count",
                            "findings",
                            "missing_evidence",
                        ]
                    }
                )[:2200]
            )
        if name == "twin.compare":
            return (
                "同基线隔离情景采样，无当前系统写入、无综合排名、无置信区间。"
                + encoded(
                    {
                        "source_ref": result["source_ref"],
                        "baseline_scenario": result["baseline_scenario"],
                        "horizon_minutes": result["horizon_minutes"],
                        "endpoints": [
                            {
                                "scenario": b["scenario"],
                                "metrics": b["points"][-1]["metrics"],
                                "delta_vs_baseline": b["delta_vs_baseline"],
                            }
                            for b in result["branches"]
                        ],
                        "units": result["metric_units"],
                    }
                )[:2200]
            )
        if name == "maritime.handover":
            facts = "；".join(
                f"{r['scenario']}需量{r['grid_demand_kw']}kW/差值{r['delta_grid_kw']}kW/风速{r['wind_speed_ms']}m/s"
                for r in result["comparison_summary"]
            )
            status = "暂缓，先核对数据时效与质量" if result["recommendation_status"] == "withheld" else "需人工复核"
            return (
                f"交接建议状态={status}（{result['recommendation_status']}）；检查时数据通过={result['readiness']['analysis_usable']}；现场放行关闭。比较事实：{facts}。未做统计显著性检验，未求解最优策略。\n"
                + result["markdown"][:5500]
            )
        if name == "knowledge.search":
            return (
                result["answer"][:2600]
                + f"；来源数={len(result['evidence'])}；source_quality={result['source_quality']}"
            )
        if name == "runtime.snapshot":
            from app.harness.semantic import snapshot_view

            return "已读取工程模拟快照；身份、字段状态与告警见来源事实视图；完整原始字段仍在工件。" + encoded(snapshot_view(result["snapshot"]))
        return encoded(result)[:2600]

    def _finalize(self, task, action, *, producer=None):
        from app.harness.verification import verify

        verification = verify(task, action, self.store)
        if (task.get("planning_mode") == "adaptive" and verification["references_valid"]
                and verification["artifact_integrity"] and verification["production_boundary"]
                and not verification["numeric_support"] and task.get("numeric_repairs",0) < 2):
            self._mutate(task["id"],lambda t:t.update(numeric_repairs=t.get("numeric_repairs",0)+1,
                last_model_error="摘要数值没有原始证据支持：" + ", ".join(verification["unsupported_numbers"])
                    + "。请用工具原始数值或删除无依据数值；不要自行取整、换算或推导。只修正总结，不重复操作。"),
                "completion.numeric_repair",verification)
            return False
        if (
            verification["references_valid"]
            and not verification["required_tools_executed"]
            and task.get("completion_repairs", 0) < 2
        ):
            self._mutate(
                task["id"],
                lambda t: t.update(
                    completion_repairs=t.get("completion_repairs", 0) + 1,
                    last_model_error="尚未完成交付所需工具："
                    + ", ".join(verification["missing_tools"])
                    + "。请先获取结果再交付。",
                ),
                "completion.incomplete",
                verification,
            )
            return False
        if (
            verification["references_valid"]
            and not verification["business_claims"]
            and task.get("business_repairs", 0) < 2
        ):
            self._mutate(
                task["id"],
                lambda t: t.update(
                    business_repairs=t.get("business_repairs", 0) + 1,
                    last_model_error="业务摘要核验失败："
                    + "；".join(verification["business_issues"])
                    + "。按原字段纠正这些问题；保留其他已支持事实、风险和模拟边界。",
                ),
                "completion.business_repair",
                {"issues": verification["business_issues"]},
            )
            return False
        if not verification["passed"]:
            self._mutate(task["id"],lambda t:None,"completion.rejected",verification)
            self._stop(task["id"], "blocked", "交付核验未通过：工具引用、工件、数值、业务表述或生产权限存在问题")
            return True
        failed = [r["id"] for r in task["results"] if (not r["ok"] and not r.get("resolved_by")) or r.get("partial")]
        final = {
            "text": action.text[: task["budget"]["max_output_chars"]],
            "evidence_ids": action.evidence_ids,
            "verification": verification,
            "data_notice": "公开资料、工程模拟或登记接口回执；现场真实性以原始来源为准，生产权限关闭。",
            "synthesis": producer or {"mode": task["driver"], "model_authored": task["driver"] == "model"},
        }
        if verification.get("delivery_readiness") and not verification["delivery_readiness"]["analysis_usable"]:
            final["data_notice"] += (
                "交付时证据时效或质量未通过，当前建议暂缓；本次结果按已采集快照使用，需更新数据后重新评估。"
            )

        def publish(t):
            self._check_decision(t, task)
            t.update(
                status="partial" if failed else "completed",
                final=final,
                stop_reason="已完成工具引用、工件与数值边界核验",
            )

        try:
            self._mutate(task["id"], publish, "task.finalized", final["verification"])
        except DecisionChanged:
            return False
        self.store.artifact(task["id"], "report.md", final["text"] + "\n\n" + final["data_notice"])
        return True

    def control(self, task_id, command, role, *, actor_id=None):
        def change(t):
            execution_role = role if actor_id is None or actor_id == t["actor_id"] else t["actor_role"]
            if command == "resume":
                if t["status"] != "paused" or t.get("inflight", {}).get("side_effect"):
                    raise Conflict("仅能继续已安全暂停的任务；未决副作用必须先核查")
                if any(not has_permission(execution_role, tools.REGISTRY[n][1]) for n in t["allowed_tools"]):
                    raise PermissionError("当前角色权限不足以继续该任务")
                t.update(status="queued", actor_role=execution_role, stop_reason="")
                t["control"] = {"cancel": False, "pause": False}
            elif command in {"pause", "cancel"}:
                if t["status"] in TERMINAL:
                    raise Conflict("任务已结束")
                t["control"][command] = True
                if t["status"] != "running":
                    t.update(status="cancelled" if command == "cancel" else "paused", pending=None)
            else:
                raise ValueError("未知控制动作")

        result = self.store.mutate(
            task_id, change, "control." + command, {"submitted_by": actor_id, "submitted_role": role}
        )
        if result["status"] == "queued":
            self.schedule(task_id)
        return result

    def input(self, task_id, payload, role, *, actor_id=None):
        def change(t):
            if t["status"] in TERMINAL:
                raise Conflict("已结束任务不能追加指令，请创建新任务")
            old = next((i for i in t["inputs"] if i["request_id"] == payload.request_id), None)
            if old:
                if old["text"] != payload.text:
                    raise Conflict("同一输入编号不能用于不同内容")
                return
            if len(t["inputs"]) >= 20:
                raise Conflict("单任务最多20次补充输入")
            t["inputs"].append({"text": payload.text, "request_id": payload.request_id, "at": now()})
            # Even an approved proposal may still be queued; steering revokes it
            # until a decision is made against the new user context.
            t["pending"] = None
            if t["status"] in {"waiting_input", "waiting_approval"}:
                execution_role = role if actor_id is None or actor_id == t["actor_id"] else t["actor_role"]
                t.update(status="queued", pending=None, actor_role=execution_role)

        result = self.store.mutate(
            task_id, change, "input.received", {"submitted_by": actor_id, "submitted_role": role}
        )
        if result["status"] == "queued":
            self.schedule(task_id)
        return result

    def approve(self, task_id, payload, identity):
        def change(t):
            if t["status"] != "waiting_approval" or not t.get("pending"):
                raise Conflict("任务没有待处理审批")
            p = t["pending"]
            if (
                p["id"] != payload.approval_id
                or p["action_sha256"] != payload.action_sha256
                or p["decision"] != "pending"
            ):
                raise Conflict("审批对象或动作摘要不匹配")
            if not has_permission(identity.role, "operations.manage"):
                raise PermissionError("没有联动操作审批权限")
            if time.time() > p["expires_epoch"]:
                raise Conflict("审批方案已过期，请补充指令重新生成方案")
            p.update(
                decision="approved" if payload.approve else "rejected", decided_by=identity.actor_id, decided_at=now()
            )
            t.update(
                status="queued" if payload.approve else "blocked",
                actor_role=identity.role if identity.actor_id == t["actor_id"] else t["actor_role"],
                stop_reason="" if payload.approve else "用户拒绝执行，未调用目标操作",
            )

        result = self.store.mutate(
            task_id,
            change,
            "approval.decided",
            {
                "approve": payload.approve,
                "approval_id": payload.approval_id,
                "action_sha256": payload.action_sha256,
                "approver_id": identity.actor_id,
                "approver_role": identity.role,
            },
        )
        if result["status"] == "queued":
            self.schedule(task_id)
        return result

    def reconcile(self, task):
        """Read a persisted target receipt; never retry the operation to learn its outcome."""
        from app import linked_agent

        if task["status"] != "needs_review" or not task.get("inflight", {}).get("side_effect"):
            raise Conflict("该任务没有未决联动操作")
        call = task["inflight"]
        run_id = call.get("linked_run_id") or "lar-" + linked_agent.digest([task["actor_id"], call["id"]])[:32]
        result = linked_agent.get_run(run_id, tools.internal_request(task))
        if call["tool"] == "execution.restore":
            # The original action's completed receipt cannot prove later restore.
            current = linked_agent._observe(result["plan"]["target"])
            if not result.get("restored") or current["config"] != result["plan"]["before"]["config"]:
                raise Conflict("恢复回执或当前配置尚未证明恢复成功；未重试或重放操作")
        if result["status"] == "completed":
            outcome = "paused"
        elif result["status"] == "cancelled" and (result.get("restored") or not result.get("applied")):
            outcome = "cancelled"
        elif result["status"] == "failed" and not result.get("write_attempted"):
            outcome = "failed"
        else:
            raise Conflict("关联回执仍未证明安全结束，请在原系统核查；未重试或重放操作")
        raw = encoded({"linked_run_id": run_id, "status": result["status"], "receipt": result,
                       **({"source_ref": call["arguments"]["source_ref"]} if call["tool"] == "execution.restore" else {})})
        result_id = "T" + str(len(task["results"]) + 1)
        name = result_id + ".json"
        self.store.artifact(task["id"], name, raw, "application/json")

        def resolve(t):
            if t["status"] != "needs_review" or t["inflight"].get("id") != call["id"]:
                raise Conflict("任务状态已发生变化")
            for record in t["results"]:
                if record["call_id"] == call["id"] and not record["ok"]:
                    record["resolved_by"] = result_id
            t["results"].append(
                {
                    "id": result_id,
                    "call_id": call["id"],
                    "tool": call["tool"],
                    "arguments": call["arguments"],
                    "ok": outcome == "paused",
                    "summary": "读取关联回执核验：" + result["status"],
                    "artifact": name,
                    "sha256": digest(raw),
                    "fingerprint": digest({"tool": call["tool"], "arguments": call["arguments"]}),
                    "elapsed_ms": 0,
                }
            )
            t.update(status=outcome, inflight={}, stop_reason="已按关联持久化回执核查；未重新下发操作")

        return self.store.mutate(
            task["id"], resolve, "operation.reconciled", {"linked_run_id": run_id, "status": result["status"]}
        )
