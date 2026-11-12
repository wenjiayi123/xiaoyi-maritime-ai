"""Conservative deterministic checks, independent of the model's completion claim."""

import re
import json
from decimal import Decimal, InvalidOperation

from app.harness.contracts import digest, completed_tools


def numbers(text):
    # Unit suffixes are common in operator prose, e.g. 3065.40kWh. Separate
    # recognized units before scanning, so a decimal cannot become a partial integer.
    text = re.sub(r"(?<=\d)(?=(?:kWh|MWh|GWh|kW|MW|TEU|kg)(?![A-Za-z0-9_]))"," ",text,flags=re.I)
    text = re.sub(r"\[T\d+\]", "", text)
    text = re.sub(r"(?m)^\s*\d+[.)、](?!\d)\s*", "", text)
    # Chinese prose can put an ordered list on one line after colons or
    # clause separators. Only remove a consecutive series starting at one;
    # decimal measurements, dates and unrelated counts remain verifiable.
    inline = list(re.finditer(r"(?<=[：；;。])[ \t]*(\d{1,2})[.)、](?!\d)[ \t]*(?=[\u4e00-\u9fff])", text))
    serials = []
    for marker in inline:
        number = int(marker.group(1))
        if number == 1:
            serials.append([marker])
        elif serials and number == len(serials[-1]) + 1:
            serials[-1].append(marker)
    for group in reversed(serials):
        if len(group) >= 2:
            for marker in reversed(group):
                text = text[:marker.start()] + text[marker.end():]
    values = set()
    for token in re.findall(r"(?<![A-Za-z0-9])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z0-9])", text):
        try:
            values.add(str(Decimal(token.replace(",", "")).normalize()))
        except InvalidOperation:
            continue
    return values


def claims_production_action(text):
    pattern = r"(?:已|已经).{0,12}?(?:生产调度|现场控制|实船控制|下发.{0,8}(?:设备|船舶))"
    negative = r"(?:不|未|尚未|没有|禁止|不得|暂缓|关闭|禁用)(?:执行|进行|实施|开展|启用|开放|获准|完成)?(?:生产调度|现场控制|实船控制|下发.{0,8}(?:设备|船舶))"
    for clause in re.split(r"[，,；;。！？!?\n]", text):
        for match in re.finditer(pattern, clause):
            if re.search(r"(?:不代表|不表示|不能声称|不得声称|未宣称|没有宣称)\s*$", clause[: match.start()]):
                continue
            if re.search(negative, match.group()):
                continue
            return True
    return False


def claims_all_normal(text):
    """Catch affirmative blanket clearance without rejecting explicit caveats."""
    pattern = r"(?:全部|全都|各项|均)(?:正常|符合要求|合格)|没有风险|无任何风险"
    for clause in re.split(r"[，,；;。！？!?\n]", text):
        for match in re.finditer(pattern, clause):
            if re.search(r"(?:不能|不得|无法)(?:声称|认为|认定|证明)?|不代表|不表示|未证明|并非|并不", clause[:match.start()]):
                continue
            return True
    return False


def verify(task, action, store, *, at=None):
    successful = {r["id"]: r for r in task["results"] if r["ok"]}
    refs = bool(action.evidence_ids) and all(ref in successful for ref in action.evidence_ids)
    missing = sorted(set(task.get("required_tools", [])) - completed_tools(task))
    checks = {
        "references_valid": refs,
        "required_tools_executed": not missing,
        "artifact_integrity": True,
        "numeric_support": True,
        "production_boundary": not claims_production_action(action.text),
    }
    support = ""
    claim_text = action.text
    verified_calculation = False
    policy_issues = []
    from app.cycle_evidence import check_refs as check_cycle_refs
    policy_issues.extend(check_cycle_refs(task, action))
    shore_receipts = []
    operation_receipts = []
    deep_receipts = []
    for ref in action.evidence_ids:
        if ref not in successful:
            continue
        record = successful[ref]
        artifact = store.artifact(task["id"], record["artifact"])
        if not artifact or artifact["sha256"] != digest(artifact["content"]) or record["sha256"] != artifact["sha256"]:
            checks["artifact_integrity"] = False
        elif record["tool"] in ("forecast.port_load","dispatch.tariff_week","evidence.match_scope"):
            from app.harness.contracts import encoded
            from app.operation_evidence import compact
            receipt=json.loads(artifact["content"])
            operation_receipts.append(receipt)
            support += "\n"+artifact["content"]+"\n"+encoded(compact(receipt))
        elif record["tool"]=="policy.deep_storage":
            from app.harness.contracts import encoded
            receipt=json.loads(artifact["content"])
            deep_receipts.append(receipt)
            from app.storage_decision_claims import presentation
            support += "\n"+encoded(receipt["summary"])+"\n"+encoded(presentation(receipt))
        elif record["tool"]=="systems.inspect":
            from app.harness.contracts import encoded
            from app.harness.operation_intent import inspection
            receipt=json.loads(artifact["content"])
            facts=inspection(receipt)
            from app.harness.operation_intent import wrong_coverage
            if wrong_coverage(action.text,receipt):policy_issues.append("覆盖项数和比例不可互换。请按回执区分已覆盖数、场景总数及百分比。")
            support += "\n"+artifact["content"]+"\n"+(encoded(facts) if facts is not None else record["summary"])
        elif record["tool"] == "policy.shore_storage":
            from app.harness.contracts import encoded
            from app.shore_evidence import shore_digest
            receipt=json.loads(artifact["content"])
            support += "\n" + artifact["content"] + "\n" + encoded(shore_digest(receipt))
            shore_receipts.append(receipt)
        elif record["tool"] in {"policy.vessel_schedule","policy.multidevice"}:
            from app.harness.contracts import encoded
            from app.harness.policy_digest import policy_digest
            # Recompute display precision from the cited, hash-verified artifact.
            # A mutable summary cannot extend the set of supported claims.
            receipt=json.loads(artifact["content"])
            support += "\n" + artifact["content"] + "\n" + encoded(policy_digest(record["tool"],receipt))
            if record["tool"]=="policy.multidevice":
                from app.harness.policy_digest import conflicting_service_claim
                # Allow the documented two- or three-decimal kWh display only
                # for metered delivery, the threshold and the authenticated upper bound.
                cap=receipt["dr_capacity_review"]
                support += " " + " ".join(format(cap[key],fmt) for key in ("required_kwh","delivered_kwh","upper_kwh") for fmt in (".2f",".3f"))
                if conflicting_service_claim(action.text,receipt):
                    policy_issues.append("请直接回答：本方案实际同时保持了充电和冷链。未能满足的是第三项最低响应交付。删除把前两项写成不兼容的结论。")
                from app.harness.service_facts import unanswered_feasibility
                from app.harness.required_energy import required_energy_issues
                policy_issues.extend(required_energy_issues(task,action.text,receipt))
                if unanswered_feasibility(task,action.text,receipt):
                    policy_issues.append("用户问上界能否证明不可行，请按回执说明现有上界仍不能判断可行性。")
        elif record["tool"] in {
            "agent.credit_trial",
            "offers.compare",
            "policy.select",
            "policy.release",
            "policy.energy",
            "policy.operations",
            "policy.safety",
            "cycle.evidence",
            "congestion.queue_week",
            "finance.port_cost",
            "emissions.port_year",
            "equipment.state",
            "portcall.eta",
            "portcall.berths",
            "knowledge.ais_minute",
            "knowledge.figures",
            "knowledge.search",
            "runtime.snapshot",
            "linked.observe",
            "linked.action",
            "systems.inspect",
            "execution.verify",
            "execution.restore",
            "calculate",
            "research.parallel",
            "maritime.query",
            "maritime.risk",
            "twin.compare",
            "maritime.handover",
            "strategy.compare",
            "strategy.replay",
            "joint.preview",
            "joint.status",
            "evidence.public_catalog",
            "port.study",
            "twin.validate_public",
            "crossport.diagnosis",
            "crossport.compare",
            "remediation.review",
            "operations.optimize",
        }:
            support += "\n" + artifact["content"] + "\n" + record["summary"]
            if record["tool"] == "congestion.queue_week":
                from app.queue_evidence import boundary_issues as queue_boundary
                policy_issues.extend(queue_boundary(action.text,record["arguments"].get("case")))
            if record["tool"] == "finance.port_cost":
                from app.port_cost_evidence import boundary_issues
                policy_issues.extend(boundary_issues(action.text,record["arguments"].get("case")))
            if record["tool"] == "calculate":
                from app.harness.calculation_evidence import remove_rounded_value

                claim_text = remove_rounded_value(claim_text, task["goal"], json.loads(artifact["content"]))
                verified_calculation = True
            if record["tool"] in {"policy.release", "policy.energy", "policy.operations", "policy.safety"}:
                receipt = json.loads(artifact["content"])
                if task.get("council_role_review") and not task.get("inputs"):
                    from app.harness.council_report import verified_text
                    if action.text != verified_text(receipt):
                        policy_issues.append("岗位结论、指标、单位和策略/基线顺序须与已核验的岗位工件一致。")
                # Permit ordinary display precision only for actual metrics of this receipt.
                for group in ("policy_metrics", "baseline_metrics"):
                    for value in receipt[group].values():
                        support += " " + " ".join(f"{value:.{places}f}" for places in (0, 1, 2))
    from app.deep_storage_trial import delivery_issues
    policy_issues.extend(delivery_issues(task,action.text,deep_receipts))
    from app.harness.operation_intent import domain_issues
    policy_issues.extend(domain_issues(task,action.text,operation_receipts))
    if shore_receipts:
        from app.shore_carbon_direction import directions
        from app.shore_online_intent import live_claim_problem
        from app.shore_meter_clocks import verify_clock_claims
        claim_text,clock_issues=verify_clock_claims(claim_text,shore_receipts)
        policy_issues.extend(clock_issues)
        amounts,issues=directions(action.text,shore_receipts,task)
        support += " " + " ".join(amounts)
        policy_issues.extend(issues)
        from app.shore_online_intent import incorrect_departure_credit
        if any(r.get("schema")=="gullmate.shore-call-review.v1" for r in shore_receipts) and incorrect_departure_credit(action.text):
            policy_issues.append("本船服务在离泊时刻截止。离泊之后的一刻钟不计入该船次电量，请按凭证纠正计量边界。")
        if live_claim_problem(task,action.text,shore_receipts):
            policy_issues.append("尚无相应周的本次 TwinLab 在线核验凭证，不能声明已与原生重放核对一致。")
    if verified_calculation:
        from app.harness.calculation_evidence import remove_registered_metadata

        claim_text = remove_registered_metadata(claim_text, task["goal"])
    unsupported = sorted(numbers(claim_text) - numbers(support))
    checks["numeric_support"] = not unsupported
    issues, withheld, comparison = policy_issues, False, False
    if verified_calculation and not task.get("production_authority"):
        from app.harness.calculation_evidence import historical_dispatch_issue

        issue = historical_dispatch_issue(task["goal"], action.text)
        if issue:
            issues.append(issue)
    delivery_readiness = None
    active_snapshot_alerts = False
    semantic_check = None
    requested_metric_ids = set()
    query_metric_ids = set()
    comparison_scenarios = set()
    if task.get("template_id") in {"port-query", "port-briefing"}:
        goal = task["goal"] + "\n" + "\n".join(i["text"] for i in task.get("inputs", []))
        requested_metric_ids = {key for key, pattern in {
            "grid_demand": r"电网需量", "shore_power": r"岸电负荷",
            "low_soc_agv": r"低电量\s*AGV", "gate_queue": r"闸口(?:排队|队列)",
        }.items() if re.search(pattern, goal, re.I)}
    for record in successful.values():
        if record["tool"] not in {
            "maritime.query",
            "maritime.risk",
            "maritime.handover",
            "twin.compare",
            "port.study",
            "twin.validate_public",
        }:
            continue
        artifact = store.artifact(task["id"], record["artifact"])
        if not artifact or artifact["sha256"] != digest(artifact["content"]) or artifact["sha256"] != record["sha256"]:
            checks["artifact_integrity"] = False
            continue
        data = json.loads(artifact["content"])
        if record["tool"] == "maritime.query":
            query_metric_ids.update(r.get("metric_id") for r in data.get("rows", []))
        if record["tool"] == "twin.compare":
            comparison_scenarios.update(r.get('scenario') for r in data.get('branches', []))
        if record["tool"] == "twin.validate_public":
            withheld = withheld or not data.get("validation_passed", False)
        if record["tool"] == "port.study":
            withheld = withheld or data.get("plan", {}).get("recommendation_status") == "withheld"
        withheld = withheld or data.get("recommendation_status") == "withheld"
        comparison = comparison or record["tool"] == "twin.compare"
    if requested_metric_ids - query_metric_ids:
        issues.append("明确要求的问数指标尚未取得，实体表不能代替指标：" + ", ".join(sorted(requested_metric_ids - query_metric_ids)))
    if comparison and not task.get('inputs'):
        from app.harness.semantic import requested_scenarios

        missing_scenarios = requested_scenarios(task['goal']) - comparison_scenarios
        if missing_scenarios:
            issues.append('明确要求的情景尚未完成，合法参数不等于情景覆盖完整：' + ', '.join(sorted(missing_scenarios)))
    if any(r["tool"] == "runtime.snapshot" for r in successful.values()):
        from app.harness.maritime import readiness

        snapshot_result = next((r for r in successful.values() if r["tool"] == "runtime.snapshot"), None)
        if snapshot_result:
            artifact = store.artifact(task["id"], snapshot_result["artifact"])
            if artifact and artifact["sha256"] == digest(artifact["content"]) == snapshot_result["sha256"]:
                snapshot = json.loads(artifact["content"])["snapshot"]
                delivery_readiness = readiness(snapshot, at=at)
                active_snapshot_alerts = any(a.get("status") not in {"resolved", "closed"} for a in snapshot.get("alerts", []))
                withheld = withheld or not delivery_readiness["analysis_usable"]
                if task.get("driver") == "model" and task.get("output_policy", "model_or_rules_summary") == "model_or_rules_summary":
                    from app.harness.semantic import check_summary

                    goal = task["goal"] + "\n" + "\n".join(i["text"] for i in task.get("inputs", []))
                    semantic_check = check_summary(snapshot, goal, action.text)
                    issues.extend(semantic_check["issues"])
            else:
                checks["artifact_integrity"] = False
    if active_snapshot_alerts and claims_all_normal(action.text):
        issues.append("原始快照含未关闭告警，不能概括为各项均正常或没有风险；需保留告警与待核查项")
    if withheld:
        if claims_all_normal(action.text) or re.search(r"全部符合|全部核验通过|现场数据已核实", action.text):
            issues.append("证据已暂缓，不能声称全部符合要求或现场已核实")
        if not re.search(r"暂缓|过期|过时|更新数据|重新取数|质量不合格|数据失衡|证据不足", action.text):
            issues.append("建议状态为暂缓，摘要必须说明数据过期、质量问题或证据不足")
    if (comparison or delivery_readiness is not None) and re.search(
        r"(?:未发现|不存在|没有|无)(?:统计上)?显著差异|(?:实现|达到|获得|证明了).{0,8}(?:最优|显著|准确预测)",
        action.text,
    ):
        issues.append("本次只有工程情景采样，未做显著性检验、优化求解或预测准确率验证")
    if any(r["tool"] in {"port.study", "twin.validate_public"} for r in successful.values()):
        if re.search(
            r"(?:已|已经)(?:达到|实现).{0,6}(?:超级智能|国际领先|全港自主)|已还原真实挂靠|通过物理孪生验证|实测减排收益",
            action.text,
        ):
            issues.append("公开历史推演和单站预测不能证明超级智能、真实挂靠还原、全港物理孪生或实测减排")
    from app.harness.adaptive import completion_issues

    issues.extend(completion_issues(task, store))
    checks["business_claims"] = not issues
    return {
        **checks,
        "passed": all(checks.values()),
        "unsupported_numbers": unsupported,
        "missing_tools": missing,
        "business_issues": issues,
        "delivery_readiness": delivery_readiness,
        "semantic_check": semantic_check,
        "failed_result_ids": [r["id"] for r in task["results"] if not r["ok"] and not r.get("resolved_by")],
        "partial_result_ids": [r["id"] for r in task["results"] if r.get("partial")],
        "scope": "工具引用、工件、数值存在性、生产边界、业务暂缓和部分不支持声明检查；不等同完整语义、因果或现场业务准入验证",
    }
