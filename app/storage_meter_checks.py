"""Bind statements about delivered energy to the matching metered hour and direction."""
import re
def meter_issues(goal,text,row):
    if not re.search(r"实际[充放电池交付量能\s或和/、]{1,10}(?:量|多少|了多少)|实际充放电量|实测电量",goal):return []
    # Receipts from the previous release can still be displayed and verified.
    step=row["steps"][row["args"]["hour"]]
    energy=step["selected"]["battery_throughput_kwh"]
    direction="待机" if energy<1e-6 else "充电" if step["selected"]["battery_soc"]>step["state"][5] else "放电"
    numbers=re.finditer(r"([-+]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:kWh|千瓦时|度电)",text,re.I)
    for hit in numbers:
        literal=hit[1].replace(",","")
        shown=float(literal)
        decimals=len(literal.partition(".")[2])
        if abs(shown-round(energy,decimals))>1e-6:continue
        clause=re.split(r"[。；;！？\n]",text[:hit.start()])[-1][-60:]
        clause=clause.replace("充放电量","电量").replace("充放电","调度")
        suffix=text[hit.end():hit.end()+25]
        after=re.match(r"\s*[（(，,、]?\s*(?:方向(?:为|是)|即|属于)?\s*(充电|放电|充入|放出)",suffix)
        if direction=="待机" or direction in clause or direction=="充电" and re.search("充入|补电|补充电量",clause) or direction=="放电" and re.search("放出|供出",clause):
            return []
        if after and after[1][0]==direction[0]:return []
    return [f"请按查询小时报告实际电量。第 {step['hour']} 时仿真计量为{direction} {energy:,.2f} kWh；请求比例和实际电量要分别表述。"]
