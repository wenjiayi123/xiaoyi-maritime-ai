"""Preserve an explicitly named vessel policy while leaving comparisons and unspecified choices open."""
import re
from typing import get_args
from app.vessel_review import VesselQuery

METHODS=get_args(VesselQuery.model_fields["method"].annotation)
IDENTIFIER=re.compile(r"(?<![a-zA-Z0-9_])(?:"+"|".join(map(re.escape,sorted(METHODS,key=len,reverse=True)))+r")(?![a-zA-Z0-9_])")


def vessel_method(task):
    texts=[task.get("goal",""),*(v.get("text","") for v in task.get("inputs",[]))]
    for text in reversed(texts):
        matches=list(IDENTIFIER.finditer(text))
        if not matches:continue
        if len({m.group() for m in matches})!=1:return None
        for m in matches:
            before=text[max(0,m.start()-20):m.start()]
            if re.search(r"(?:不用|不要|排除|禁止|不选|不是|except|exclude|not)\s*(?:用|采用|选择)?\s*(?:方法|策略|method)?[\s（(:：=]*$",before,re.I):
                return None
            if re.search(r"(?:方法|策略|算法|method|policy)(?:标识|名称)?[\s（(:：=为]*$",before,re.I):
                return m.group()
        return None
    return None
