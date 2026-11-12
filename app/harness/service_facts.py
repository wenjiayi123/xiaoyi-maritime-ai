"""Distinguish measured service from the counterfactual response commitment in policy reports."""
import re


def service_facts(receipt):
    checks=receipt["checks"];capacity=receipt["dr_capacity_review"]
    charge=checks["agv_delivered"] and checks["agv_departures"]
    cold=checks["cold_chain"] and checks["terminal_thermal_debt"]
    observed=("能，两项服务在本次实际仿真中同时达标。" if charge and cold else "该方案并未同时满足两项服务。")
    third={"no_event":"本日没有响应承诺。",
           "delivered":"本方案达到了最低响应交付。",
           "incompatible_with_service":"若再要求交足最低响应电量，三项不能同时达标。冲突发生在第三项响应交付。",
           "shortfall_undetermined":"上界没有排除达成最低交付的可能。现有回执不能证明联合目标可行，也不能证明不可能。"}[capacity["status"]]
    return {"能否同时保持充电与冷链":observed,"另外要求最低响应交付时的结论":third}


def unanswered_feasibility(task,answer,receipt):
    if receipt["dr_capacity_review"]["status"]!="shortfall_undetermined":return False
    text=" ".join([task.get("goal",""),*(r.get("text","") for r in task.get("inputs",[]))])
    if not re.search(r"证明.{0,12}(不可能|可行)|可行性|(?:上界|上限).{0,10}能(?:否|证明)|物理上不可能",text):return False
    return not re.search(r"(?:未能|不能|无法|尚未|没有|不足以|难以|未|不代表|不等于|不意味着).{0,20}(?:证明|排除|判定|确定|不可能|不可行)|可行性.{0,8}(?:未定|未知|待核|未明|不确定)",answer)
