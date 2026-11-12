"""Check the sign and named source when a Chinese report expresses signed kg as a positive magnitude."""
import re

VERB=re.compile(r"(多排|少排|减排|增排|增碳|减碳|减少|增加|降低|下降|上升)(?:了|约为|约|为)?\s*"
                r"([+−-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:kg|千克|公斤)(?![A-Za-z])",re.I)
DOWN={"少排","减排","减碳","减少","降低","下降"}


def directions(answer,receipt,task):
    receipts=receipt if isinstance(receipt,list) else [receipt]
    weeks=[r for r in receipts if r.get("schema")=="gullmate.shore-week-review.v1"]
    if not weeks:return [],[]
    approved=[];issues=[]
    for sentence in re.split(r"[。；;！？\n]",answer):
        for m in VERB.finditer(sentence):
            prefix=re.split(r"[，,]",sentence[:m.start()])[-1]
            # Prefer the current clause, then the question when the answer
            # omits its subject. Explicit joint totals take precedence.
            group=prefix
            if not re.search(r"电池|储能循环|柔性|联合|合计|总体|总碳",group):
                group=task.get("goal","")
            if re.search(r"联合|合计|总体|总碳",group):key="carbon_delta_kg"
            elif "柔性" in group:key="flex_carbon_kg"
            elif "电池" in group or "储能循环" in group:key="battery_carbon_kg"
            else:key="carbon_delta_kg"
            shown=m.group(2).replace(",","").replace("−","-")
            amount=float(shown);digits=len(shown.rsplit(".",1)[1]) if "." in shown else 0
            dates=set(re.findall(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)",sentence))
            source=[r["audited"][key] for r in weeks if not dates or r["week"] in dates]
            matches=any((m.group(1) in DOWN)==(value<0) and abs(float(format(abs(value),f".{digits}f"))-amount)<=1e-9 for value in source)
            if amount<0 or not matches:
                issues.append("口头增减方向、公斤数或归因对象与已引周回执不符")
            else:approved.append(shown)
    return approved,issues
