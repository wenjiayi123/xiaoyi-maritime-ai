"""English evidence views use the same verified record, units and comparison as the Chinese view."""
import re
from app.harness.response_language import english_goal


def project(receipt,goal):
    result={"case_id":receipt["工单编号"],"source_sha256":receipt["业务原件 SHA256"],
            "policy_sha256":receipt["模型版本 SHA256"],"evidence_read_utc":receipt["本次从原件取证时刻 UTC"]}
    if "实际有效周" in receipt:
        result.update(source="U.S. Bureau of Transportation Statistics (BTS) historical queue observations",
                      model_owner="GullMate",observed_period=receipt["实际观测范围"],valid_weeks=receipt["实际有效周"],
                      high_queue_weeks=receipt["高等泊周"],threshold_vessels=receipt["高等泊门槛（艘）"],
                      candidate=dict(zip(("hits","misses"),receipt["候选方法的命中和漏报"])),
                      persistence=dict(zip(("hits","misses"),receipt["沿用前次状态的命中和漏报"])),
                      disposition="Automatic alerts declined. Historical weekly replay available.")
    elif "目标周" in receipt:
        result.update(historical_source="U.S. Bureau of Transportation Statistics (BTS)",forecaster="GullMate",
                      issued_utc=receipt["签发时刻 UTC"],target_week_start=receipt["目标周"][0],target_week_end=receipt["目标周"][1],
                      forecast_vessels=receipt["预测艘数"],threshold_vessels=receipt["高等泊门槛（艘）"],
                      probability_of_reaching_threshold=receipt["达到门槛的模型概率"],
                      target_week_observation_available=receipt["官方目标周实绩"] is not None,target_week_observed_vessels=receipt["官方目标周实绩"],
                      disposition="Await official observations after the target week.")
        if re.search(r"latest|last input|historical observation date",goal,re.I):
            result["date_of_last_individual_input_observation"]=receipt["最后输入观测日"]
    else:
        references={"fixed tariff recognition":("相对固定电价识别每工况周均减少",r"fixed (?:tariff|rate)[ -]recognition|fixed adaptive"),
                    "idle":("相对待机每工况周均减少",r"\bidle\b|standby"),
                    "original trained policy":("相对固定原训练策略每工况周均减少",r"original (?:trained )?(?:policy|strategy|controller)")}
        named=[k for k,(_,pattern) in references.items() if re.search(pattern,goal,re.I)]
        metrics={"cost_reduction_CNY":"省费（元）","carbon_reduction_kg":"少排（kg）","peak_reduction_kW":"降峰（kW）"}
        result.update(source="TwinLab engineering simulation",policy_owner="GullMate",seed=receipt["原训练种子"],weeks=receipt["周数"],
                      comparison={k:{eng:receipt[references[k][0]][cn] for eng,cn in metrics.items()} for k in (named or references)},
                      universal_replacement_qualified=False,disposition="Eligible for historical sandbox replay.")
    result.update(approval_record=receipt["审批记录"],field_execution_record=receipt["现场执行记录"])
    return result


def scope_issue(goal,answer):
    if "CYCLE-US-20261120" in goal.upper() and re.search(r"week (?:ending|ended|through) (?:on )?(?:November 0?3\b|2026-11-03)",answer,re.I):
        return ["November 3 was an individual historical observation date. November 20 is the end date of the forecast target week."]
    if not (re.search(r"fixed (?:tariff|rate)[ -]recognition|fixed adaptive",goal,re.I) and "CYCLE-BESS-7COST" in goal.upper()):
        return []
    if re.search(r"original (?:trained )?(?:policy|strategy|controller)|\bidle\b",goal,re.I):
        return []
    domain=re.search(r"fixed (?:tariff|rate)[ -]recognition|fixed adaptive",answer,re.I)
    amounts=re.findall(r"(?<![\w.])([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:CNY|yuan|RMB|kg|kilograms?|kW|kilowatts?)\b",answer,re.I)
    if any(float(value.replace(",",""))!=0 for value in amounts):
        return ["The requested baseline has zero measured differences. Remove the nonzero values from other baselines."]
    zeros=re.search(r"(?:all|three|each).{0,105}(?:zero|\b0(?:\.0+)?\b)|(?:zero|no) (?:additional |incremental )?(?:reductions?|gains?|savings?|improvements?)|did not reduce",answer,re.I|re.S)
    individual=sum(bool(re.search(r"\b(?:zero|0(?:\.0+)?)\s*"+unit,answer,re.I)) for unit in [r"(?:CNY|yuan|RMB)",r"(?:kg|kilograms?)",r"(?:kW|kilowatts?)"])==3
    gate=re.search(r"(?:did not|didn't|does not|cannot|not (?:qualified|eligible|approved)|failed|rejected|not meet|ineligible|not chosen|not qualify)",answer,re.I)
    if not (domain and (zeros or individual) and gate):
        return ["Use the fixed tariff-recognition comparison in the receipt. Give the three zero reductions and the replacement decision in English."]
    return []
