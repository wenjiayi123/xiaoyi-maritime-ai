"""Conservative deterministic checks, independent of the model's completion claim."""

import re
import json
from decimal import Decimal, InvalidOperation

from app.harness.contracts import digest, completed_tools


def numbers(text):
    text = re.sub(r"\[T\d+\]", "", text)
    text = re.sub(r"(?m)^\s*\d+[.)、]\s*", "", text)
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
    for ref in action.evidence_ids:
        if ref not in successful:
            continue
        record = successful[ref]
        artifact = store.artifact(task["id"], record["artifact"])
        if not artifact or artifact["sha256"] != digest(artifact["content"]) or record["sha256"] != artifact["sha256"]:
            checks["artifact_integrity"] = False
        elif record["tool"] in {
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
    unsupported = sorted(numbers(action.text) - numbers(support))
    checks["numeric_support"] = not unsupported
    issues, withheld, comparison = [], False, False
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
