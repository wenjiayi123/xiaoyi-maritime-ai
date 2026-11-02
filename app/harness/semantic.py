"""Small source-grounded views and bounded checks for free snapshot summaries.

No model-written facts, timestamp refresh, or production authority are introduced.
Presence is a source-field state, not an inference from a shortened summary.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re


def requested_scenarios(goal):
    """Conservative literal names in explicit comparison clauses, not free intent NLP."""
    names = {
        "normal": r"常态|正常工况|(?<![A-Za-z_])normal(?![A-Za-z_])",
        "vessel_surge": r"船舶激增|船舶集中到港|vessel_surge",
        "equipment_failure": r"设备故障|equipment_failure",
        "energy_peak": r"需量高峰|能源高峰|energy_peak",
        "storm": r"大风|风暴|(?<![A-Za-z_])storm(?![A-Za-z_])",
    }
    required = set()
    for match in re.finditer(r"(?:比较|对比|推演)([^。；;\n]{0,100})", goal):
        clause = match[1]
        # Do not turn exclusions or a negative instruction into required work.
        if re.search(r"不要|不含|不包括|排除|无需|不对比|不比较", goal[max(0, match.start()-3):match.end()]):
            continue
        required.update(key for key, pattern in names.items() if re.search(pattern, clause, re.I))
    return required


def field(row, key, *, path, label, entity="", unit="", required=False):
    state = "absent" if key not in row else "null" if row[key] is None else "empty" if row[key] == "" else "present"
    return {"path": path, "label": label, "entity": entity, "state": state, "value": row.get(key), "unit": unit, "required": required}


def snapshot_view(snapshot, goal=""):
    identity_required = bool(re.search(r"港[区口].{0,8}(?:名称|编号|代码|身份)|港区身份|名称和编号", goal))
    fields = [
        field(snapshot.get("port", {}), "name", path="port.name", label="港区名称", required=identity_required),
        field(snapshot.get("port", {}), "code", path="port.code", label="港区编号", required=identity_required),
        field(snapshot.get("metadata", {}), "observed_at", path="metadata.observed_at", label="观测时间", required=bool(re.search("观测时间|快照时间|采集时间|观测日期", goal))),
    ]
    for key, label, pattern, unit in [
        ("shore_power_kw", "岸电负荷", r"岸电.{0,8}(?:负荷|功率)|(?:负荷|功率).{0,8}岸电", "kW"),
        ("grid_demand_kw", "电网需量", r"电网.{0,8}(?:需量|负荷)|总需电", "kW"),
        ("bess_soc_percent", "储能SOC", r"储能.{0,8}(?:SOC|电量|荷电)", "%"),
    ]:
        if not goal or re.search(pattern, goal, re.I):
            fields.append(field(snapshot.get("energy", {}), key, path="energy." + key, label=label, unit=unit, required=bool(goal)))
    requested_times = [key for key in ["eta", "etb", "atb", "etc", "etd"] if re.search(r"(?<![A-Za-z])" + key + r"(?![A-Za-z])", goal, re.I)]
    calls = snapshot.get("port_calls", [])
    selected = [(i, c) for i, c in enumerate(calls) if c.get("vessel_name") and c["vessel_name"] in goal]
    if not selected:
        selected = list(enumerate(calls))[:3]
    for index, call in selected:
        for key in requested_times:
            fields.append(field(call, key, path=f"port_calls/{index}/{key}", label=key.upper(), entity=call.get("vessel_name", call.get("vessel_call_id", "未命名对象")), required=True))
    active = [a for a in snapshot.get("alerts", []) if a.get("status") not in {"resolved", "closed"}]
    rank = {"critical": 0, "high": 1, "warning": 2, "medium": 2, "low": 3, "info": 4}
    active.sort(key=lambda a: rank.get(a.get("severity", a.get("level")), 5))
    alerts = [{"id": a.get("event_id", a.get("id")), "entity": a.get("asset_id"), "severity": a.get("severity", a.get("level")), "title": a.get("title", a.get("message", "")), "state": a.get("status")} for a in active[:6]]
    risk_requested = bool(re.search(r"风险|告警|预警|异常|交班|交接", goal))
    critical = [a for a in alerts if a["severity"] in {"critical", "high"}]
    required_alerts = critical or alerts[:1] if risk_requested else []
    return {
        "scope": "公开数据校准工程模拟；现场未接入，生产权限关闭",
        "field_semantics": "present含0和false；null为空值，absent为字段不存在，empty为空字符串；三者均不是0。未到业务阶段不等于故障。未列入本视图的字段不能断言缺失。",
        "fields": fields,
        "active_alerts": alerts,
        "omitted_alert_count": max(0, len(active) - len(alerts)),
        "required_alert_ids": [a["id"] for a in required_alerts],
        "site_connected": snapshot.get("port", {}).get("site_connected") is True,
        "connection_fact": "未接入现场生产源；这是已知接入缺项，与模拟港区身份字段和读工具权限分开" if snapshot.get("port", {}).get("site_connected") is not True else "数据源声明现场已接入，仍须独立现场准入核验",
        "production_authority": False,
    }


def _clauses(text):
    return re.split(r"[。；;\n]", text)


def _gap_claim(text, labels):
    for clause in re.split(r"[，,。；;\n]", text):
        if re.search(r"(?:真实|现场|生产)(?:港|数据|对象|身份|系统)|不能.{0,10}(?:断言|认为|声称)|不代表|并非", clause):
            continue
        for label in labels:
            if re.search(r"(?:缺少|缺失|未提供|未给出|未知|空缺)[^。；;]{0,18}" + label, clause) or re.search(label + r"[^，,。；;]{0,8}(?:缺少|缺失|未提供|未给出|未知|为空|空缺)", clause):
                return True
    return False


def _topic_terms(title):
    for marker, terms in [
        ("锁销", ["锁销", "吊具"]), ("能耗", ["能耗", "耗能"]),
        ("SOC", ["SOC", "低电", "电量", "充电"]), ("需量", ["需量", "功率", "超限"]),
        ("冲突", ["冲突", "窗口", "泊位"]), ("风", ["风", "气象"]),
        ("故障", ["故障", "检修", "异常"]), ("到车", ["到车", "闸口", "排队"]),
    ]:
        if marker in title:
            return terms
    return [title] if title else []


def check_summary(snapshot, goal, text):
    view = snapshot_view(snapshot, goal)
    issues = []
    covered = []
    if not re.search("模拟|仿真", text):
        issues.append("正文必须说明本次来源为工程模拟，不能只在外层通知中补充")
    for sentence in _clauses(text):
        if re.search(r"(?:因|由于|鉴于|受|导致|所以|因此)", sentence) and re.search(r"权限.{0,10}(?:关闭|禁用|不足|限制|未开放)", sentence) and re.search(r"(?:无法|不能|不可).{0,8}(?:读取|获取|取得|采集).{0,12}(?:数据|快照|观测)", sentence):
            issues.append("禁止无依据因果：生产控制权限关闭不意味着不能读取数据；现场源未接入须单独说明")
    # Source identities and timestamps may be present even when a retrieval answer
    # requests a *real site's* identity. Keep those two evidence scopes distinct.
    aliases = {"port.name": ["港区名称", "港口名称", "港区身份", "港口身份"], "port.code": ["港区编号", "港口编号"], "metadata.observed_at": ["观测时间", "快照时间", "采集时间", "观测日期"]}
    for item in view["fields"]:
        label, state, value = item["label"], item["state"], item["value"]
        labels = aliases.get(item["path"], [re.escape(label)])
        if state == "present" and _gap_claim(text, labels):
            issues.append(f"源字段{item['path']}已有值，不能误报{label}缺失；现场接入缺项须另行说明")
        if not item["required"]:
            continue
        entities = {f["entity"] for f in view["fields"] if f["entity"]}
        candidates = []
        for sentence in _clauses(text):
            if item["entity"] and item["entity"] not in sentence:
                if len(entities) > 1 or item["entity"] not in text or any(e in sentence for e in entities):
                    continue
            candidates.extend(c for c in re.split("[，,]", sentence) if label in c or (label == "岸电负荷" and "岸电" in c))
        if state != "present":
            accepted = any(re.search(r"空|未提供|未报告|未填|未知|缺失|不存在|null|absent", c, re.I) for c in candidates)
            if not accepted:
                issues.append(f"需说明{item['entity']}{label}的源字段状态为{state}，不可填成0或猜测")
        elif item["path"] in {"port.name", "port.code"}:
            accepted = str(value) in text
            if not accepted:
                issues.append(f"遗漏已提供的{label}：{value}")
        elif item["unit"]:
            synonyms = {"岸电负荷": r"岸电(?:负荷|功率)?", "电网需量": r"电网(?:需量|负荷)?", "储能SOC": r"储能(?:SOC|荷电状态|电量)?"}
            found = re.findall(synonyms[label] + r"[^\d。；;\n]{0,12}([-+]?\d+(?:\.\d+)?)\s*(kW|千瓦|%)?", text, re.I)
            try:
                accepted = any(Decimal(n) == Decimal(str(value)) and (u.lower() == item["unit"].lower() or (u == "千瓦" and item["unit"] == "kW")) for n, u in found)
            except InvalidOperation:
                accepted = False
            if not accepted:
                issues.append(f"{label}需保留对应值和单位：{value} {item['unit']}，不能借用其他指标数字")
        else:
            timestamp = str(value)
            accepted = any(timestamp in c or (len(timestamp) >= 16 and timestamp[11:16] in c) for c in candidates)
            if not accepted:
                issues.append(f"遗漏{item['entity']}{label}的已提供时间值：{value}")
        if accepted:
            covered.append(item["path"])
    for alert in view["active_alerts"]:
        if alert["id"] not in view["required_alert_ids"]:
            continue
        entity = alert["entity"]
        candidates = [c for c in _clauses(text) if not entity or entity in c]
        if not any(any(term.lower() in c.lower() for term in _topic_terms(alert["title"])) for c in candidates):
            issues.append(f"遗漏主要告警：{entity or ''} {alert['title']}；原始告警仍未关闭")
        else:
            covered.append("alerts/" + str(alert["id"]))
    if view["omitted_alert_count"] and not re.search("更多|其余|其他告警|详见工件|完整告警", text):
        issues.append("告警视图有省略项，必须说明其余告警见完整工件")
    return {"passed": not issues, "issues": issues, "covered_source_paths": covered, "scope": "显式请求字段、主要告警、0/空值和部分错误缺项声明；不等同任意自然语言语义正确性证明"}
