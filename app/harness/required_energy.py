"""Return exact, cited readings when the operator explicitly requests a numerical threshold or bound."""
import re
from app.harness.verification import numbers


def required_energy_issues(task,answer,receipt):
    query=" ".join([task.get("goal",""),*(r.get("text","") for r in task.get("inputs",[]))])
    if not re.search(r"给出|列出|请列|报出|是多少|为多少|多少\s*(?:kWh|千瓦时)|具体数值",query,re.I):return []
    visible=numbers(answer)
    cap=receipt["dr_capacity_review"]
    issues=[]
    for requested,key,label in (("最低交付","required_kwh","最低交付"),("上界","upper_kwh","事后物理上界")):
        if requested not in query:continue
        value=cap[key]
        supported=numbers(" ".join((format(value,".2f"),format(value,".3f"),str(value))))
        if not visible.intersection(supported):
            issues.append(f"用户明确要求{label}，最终正文须列出凭证数值 {value:.2f} kWh")
    return issues
