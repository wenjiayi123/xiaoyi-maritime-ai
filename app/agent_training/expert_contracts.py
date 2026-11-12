"""Versioned input/outcome contracts for the next expert-facing experiment.

These are engineering validators, not learned understanding, tool selectors,
training rewards, or changes to the accepted30-case entry.
"""
from __future__ import annotations

import math
import re

NUMBER = r"([-+]?\d+(?:\.\d+)?)"


def inspect_energy_request(text: str) -> dict:
    result = {"status": "needs_clarification", "parameters": {}, "issues": [], "normalizations": [],
              "producer": "deterministic_contract_validator", "selects_tool": False,
              "scope": "One explicitly specified local energy comparison; no arbitrary intent understanding"}
    issues = result["issues"]
    if not isinstance(text, str) or not 2 <= len(text) <= 2000:
        issues.append("invalid_input_length")
        return result
    compact = re.sub(r"\s+", "", text).replace("％", "%")
    if not re.search("能碳|绿色偏好|碳价", compact):
        result["status"] = "unsupported_request"
        issues.append("outside_energy_comparison_contract")
        return result
    if re.search(r"(?:不要|禁止|无需|不需要|不得|不)(?:进行|做)?(?:能碳)?(?:比较|对比|试算)", compact):
        issues.append("comparison_not_authorized_by_instruction")
        return result
    if re.search("只读|仅读取|只读取|仅查询|只查询", compact):
        issues.append("read_only_instruction_requires_separate_observation_contract")
    if re.search("下发|实船|真实设备|生产控制", compact) and not re.search(r"(?:不要|禁止|不)(?:进行)?(?:生产)?(?:下发|控制)", compact):
        issues.append("production_operation_outside_local_simulation_scope")
    if re.search(r"碳排(?:放)?.{0,12}(?:降低|减少|下降|不超过)|(?:服务|满足率|费用|成本|预算|潮窗|吃水|风速|靠泊时间).{0,12}(?:低于|高于|不超过|至少|最多|以内|不得|[<>≤≥])", compact):
        issues.append("business_constraints_require_outcome_planner_not_plain_parameter_comparison")
    explicit_defaults = bool(re.search(r"(?:使用|采用|按)(?:登记的?|已登记的?)?默认参数", compact))
    if re.search(r"(?:不要|禁止|不)(?:使用|采用)?(?:登记的?)?默认参数", compact):
        explicit_defaults = False
    patterns = {
        "baseline_green_preference": r"基准(?:绿色偏好|偏好)?",
        "green_preference": r"(?:候选(?:绿色偏好|偏好)?|(?<!基准)绿色偏好)",
        "carbon_price_cny_per_ton": r"碳价",
    }
    defaults = {"baseline_green_preference": .5, "green_preference": .82, "carbon_price_cny_per_ton": 85.0}
    for field, label in patterns.items():
        prior_issue_count = len(issues)
        matches = list(re.finditer(label + r"(?:为|是|=|：|调到|设为)?" + NUMBER + r"(%?)", compact))
        if not matches:
            if explicit_defaults:
                result["parameters"][field] = defaults[field]
                result["normalizations"].append({"field": field, "source": "explicitly_requested_registered_default", "value": defaults[field]})
            else:
                issues.append("missing:" + field)
            continue
        values = []
        for match in matches:
            value = float(match.group(1))
            tail = compact[match.end():]
            if re.match(r"(?:和|、|或|至|到|~|—)" + NUMBER, tail):
                issues.append("multiple_values_require_batch_or_clarification:" + field)
            if field != "carbon_price_cny_per_ton":
                if match.group(2):
                    value /= 100
                    result["normalizations"].append({"field": field, "source": match.group(0), "value": value})
                if not 0 <= value <= 1:
                    issues.append("out_of_range:" + field)
            else:
                if match.group(2):
                    issues.append("carbon_price_is_not_a_percentage")
                currency = re.match(r"(?:美元|美金|USD|欧元|EUR|港元|HKD)", tail, re.I)
                unit = re.match(r"(千|万)?(?:人民币元|人民币|元|CNY|RMB)(?:/|每)(吨|t|kg|千克|公斤)", tail, re.I)
                if currency:
                    issues.append("currency_conversion_requires_explicit_rate_and_date")
                elif unit:
                    value *= {None: 1, "千": 1000, "万": 10000}[unit.group(1)]
                    if unit.group(2).lower() in {"kg", "千克", "公斤"}:
                        value *= 1000
                    result["normalizations"].append({"field": field, "source": match.group(0) + unit.group(0), "value": value, "unit": "CNY/t"})
                else:
                    issues.append("missing_or_unsupported_carbon_currency_and_mass_unit")
                if not 0 <= value <= 5000:
                    issues.append("out_of_range:" + field)
            values.append(value)
        if len(set(values)) > 1:
            issues.append("conflicting_values:" + field)
        elif len(issues) == prior_issue_count:
            result["parameters"][field] = values[0]
    result["issues"] = list(dict.fromkeys(issues))
    result["status"] = "ready_for_context_check" if not result["issues"] else "needs_clarification"
    # Even a complete parameter contract is not evidence of valid source data
    # or that the business objective is achievable.
    result["execution_authorized"] = False
    return result


def assess_energy_option(baseline: dict, candidate: dict, requirements: dict) -> dict:
    """Judge supplied solver evidence; never manufacture missing business metrics."""
    result = {"status": "needs_evidence", "issues": [], "checks": {}, "deltas": {},
              "producer": "deterministic_outcome_validator", "selects_tool": False}
    allowed = {"min_carbon_reduction_pct", "max_cost_cny", "min_service_pct"}
    if not requirements or set(requirements) - allowed:
        result["issues"].append("missing_or_unsupported_requirements")
    for key, value in requirements.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            result["issues"].append("invalid_requirement:" + key)
        elif value < 0 or (key in {"min_carbon_reduction_pct", "min_service_pct"} and value > 100):
            result["issues"].append("out_of_range_requirement:" + key)
    for key in ["dataset_sha256", "window_id", "site_id"]:
        if not baseline.get(key) or not candidate.get(key):
            result["issues"].append("missing_context:" + key)
        elif baseline[key] != candidate[key]:
            result["issues"].append("incomparable_context:" + key)
    units = {"carbon_kg": "kgCO2e", "cost_cny": "CNY", "service_pct": "%"}
    required_metrics = {"carbon_kg", "cost_cny"}
    if "min_service_pct" in requirements:
        required_metrics.add("service_pct")
    for name, option in [("baseline", baseline), ("candidate", candidate)]:
        for metric in required_metrics:
            value = option.get(metric)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                result["issues"].append("missing_or_invalid_metric:" + name + "." + metric)
            elif value < 0 or (metric == "service_pct" and value > 100):
                result["issues"].append("out_of_range_metric:" + name + "." + metric)
            if option.get("units", {}).get(metric) != units[metric]:
                result["issues"].append("unit_mismatch:" + name + "." + metric)
    if result["issues"]:
        return result
    carbon_delta = candidate["carbon_kg"] - baseline["carbon_kg"]
    cost_delta = candidate["cost_cny"] - baseline["cost_cny"]
    result["deltas"] = {"carbon_kg": carbon_delta, "cost_cny": cost_delta}
    if "min_carbon_reduction_pct" in requirements:
        if baseline["carbon_kg"] == 0:
            result["issues"].append("relative_carbon_reduction_undefined_for_zero_baseline")
            return result
        reduction = -carbon_delta / baseline["carbon_kg"] * 100
        result["deltas"]["carbon_reduction_pct"] = reduction
        result["checks"]["carbon_target"] = reduction >= requirements["min_carbon_reduction_pct"]
    if "max_cost_cny" in requirements:
        result["checks"]["cost_limit"] = candidate["cost_cny"] <= requirements["max_cost_cny"]
    if "min_service_pct" in requirements:
        result["checks"]["service_floor"] = candidate["service_pct"] >= requirements["min_service_pct"]
    result["status"] = "meets_registered_requirements" if all(result["checks"].values()) else "does_not_meet_registered_requirements"
    return result
