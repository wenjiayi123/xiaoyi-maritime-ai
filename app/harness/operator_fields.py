"""Map explicit display labels and ISO dates to the registered vessel query fields."""
import re
from app.harness.explicit_policy import IDENTIFIER,vessel_method

METHOD_LABELS={"受训换位策略":"repair","受训换位方案":"repair","受训修复策略":"repair","贪心修复":"repair_greedy",
               "未训练修复网络":"repair_untrained","逐步最低成本":"immediate_cost","混合整数规划":"milp","沙盘启发式基线":"native",
               "上一轮逐船构造策略":"trained"}
SCENE_LABELS={"泊位停用":"berth_outage","天气封航":"weather_closure","到港量增加":"arrival_surge","供电降额":"grid_derating",
              "电网降额":"grid_derating","常规工况":"normal","常规船期":"normal"}
DATE=re.compile(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)")
NEGATED=re.compile(r"(?:不要|不用|不选|排除|禁止|不是|不包括|而非|except|exclude|not)\s*(?:查|核查|用|采用|选择)?\s*(?:方法|策略|日期|工况)?[\s（(:：=]*$",re.I)


def vessel_fields(task):
    texts=[task.get("goal",""),*(item.get("text","") for item in task.get("inputs",[]))]
    fields={};resolved=set()
    for text in reversed(texts):
        for field,mapping in (("method",METHOD_LABELS),("scenario",SCENE_LABELS),("day",{})):
            if field in resolved:continue
            hits=[]
            for label,value in mapping.items():
                hits.extend((m.start(),value) for m in re.finditer(re.escape(label),text))
            if field=="day":hits=[(m.start(),m.group()) for m in DATE.finditer(text)]
            explicit=None
            if field=="method":
                explicit=vessel_method({"goal":text})
                hits.extend((m.start(),m.group()) for m in IDENTIFIER.finditer(text))
            elif field=="scenario":
                for label in set(mapping.values()):
                    hits.extend((m.start(),label) for m in re.finditer(r"(?<![a-zA-Z0-9_])"+label+r"(?![a-zA-Z0-9_])",text))
            if not hits:continue
            resolved.add(field)
            choices={v for _,v in hits}
            if len(choices)!=1 or any(NEGATED.search(text[max(0,i-24):i]) for i,_ in hits):continue
            if field=="method" and explicit is None and not any(s in text for s in mapping):continue
            fields[field]=choices.pop()
    return fields
