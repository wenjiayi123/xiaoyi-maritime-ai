"""Compute remaining running-time allowance for one explicitly described maintenance meter."""
from decimal import Decimal
import re

SERVICE = r"(?:预防性)?(?:维保|保养|检修|维护)"
def applicable(facts, question):
    subject = re.search(rf"{SERVICE}(?:到|的?累计|工时|限值|时限|上限|触发|到期|周期)", facts + " " + question)
    other = re.search(r"MTBF|平均故障|平均无故障|平均修复|可用率", question, re.I)
    time_quantity = re.search(r"小时|分钟|多久|多长时间|\b(?:h|min)\b", question, re.I)
    return bool(subject and time_quantity and not other and re.search(r"剩余|尚余|还剩|还可|尚有|还能|余量|距.{0,12}(?:限值|到期)|到限前", question))


TIME = r"(?P<n>[0-9]{1,10}(?:\.[0-9]{1,6})?)\s*(?P<u>小时|分钟|min\b|h\b)"
SEP = r"\s*(?:为|是|=|[：:])?\s*"
RULES = {
    "limit": re.compile(rf"(?:{SERVICE}(?:到|(?:累计(?:运行)?)?(?:工时)?(?:限值|时限|上限|触发值|到期读数))|(?:下次)?{SERVICE}的累计运行上限){SEP}{TIME}\s*(?:必须执行|到期)?", re.I),
    "current": re.compile(rf"(?:当前|现在|班前)(?:的)?(?:累计(?:运行)?(?:工时|时间)?|运行小时表读数|计时器读数|仪表读数)?{SEP}{TIME}", re.I),
    "demand": re.compile(rf"(?:下一班(?:任务)?|下班次|本班(?:任务)?|本次任务|计划班次)(?:需(?:要)?|计划|用时|时长|须)?(?:连续)?(?:运行|作业)?{SEP}{TIME}", re.I),
}
INCLUSIVE = re.compile(r"不允许途中超限|班末可恰好到限|班末允许恰好到限|到限时停机维保|班末读数不得超过限值")
STRICT = re.compile(r"必须在到限前结束|班末读数必须严格小于限值|必须在达到限值前停机")
PUNCT = re.compile(r"[\s，,。；;、：:]+")
NAMES = {"limit":"维保触发读数","current":"班前累计读数","demand":"班次连续运行时间"}
REQUEST = re.compile(
    rf"(?:距(?:下次|下一次)?{SERVICE}(?:限值|到期)(?:尚有|剩余|还剩|还能运行|还可运行)|"
    rf"(?:班前|开始前|当前|现在)(?:距{SERVICE}(?:限值|到期))?(?:尚有|剩余|尚余|还剩|还能运行|还可运行)|"
    r"(?:班后|班末|完成(?:本班|这一班|该班次|班次|任务)后)(?:的)?(?:净余量|带符号余量|剩余时间|余量)(?:为|是|还有)?)"
    r"(?:多少|几)(?:个)?(?:小时|分钟|h|min)(?:[（(]超限用负数[）)])?", re.I)
DECISION = re.compile(r"(?:接下该班次是否合规|(?:本班|该班次|本班任务)(?:是否合规|是否可行|可否按计划完成)|能否承接(?:本班|该班次|这一班)|"
                      r"是否能(?:按计划)?完成(?:该班次|本班)|按所给限值能否承接本班)")


def verify(text, question):
    from app.exercise_records import Unresolved
    if not question:
        raise Unresolved("maintenance_quantity", "需要指明要核验的维保工时量及单位")
    q = re.split(r"\n问题[：:]", question)[-1].strip()
    if not applicable(text, q) or re.search(r"停机时间|维保耗时|保养时长|豁免|延期|换表|多台|两台|多个", q):
        raise Unresolved("maintenance_quantity", "问题超出单台设备累计工时演练的核算范围")
    parts = [s for s in re.split(r"[？?。；;，,]+", re.sub(r"\s+", "", q)) if s]
    if len(parts) not in (1,2) or not REQUEST.fullmatch(parts[0]) or (len(parts)==2 and not DECISION.fullmatch(parts[1])):
        raise Unresolved("maintenance_question", "问题含其他核算量或未核验的附加条件")
    hours = bool(re.search(r"小时|(?<![A-Za-z])h\b", q, re.I))
    minutes = bool(re.search(r"分钟|(?<![A-Za-z])min\b", q, re.I))
    if hours == minutes:
        raise Unresolved("maintenance_unit", "问题须指定唯一的小时或分钟口径")
    before = bool(re.search(r"班前|开始前|距.{0,12}(?:限值|到期).{0,8}(?:尚有|还剩|还可|剩余|还能)|(?:当前|现在).{0,8}(?:还可|还能|剩余|尚余)", q))
    after = bool(re.search(r"班后|班末|完成(?:本班|这一班|该班次|班次|任务)后", q))
    if before == after:
        raise Unresolved("maintenance_quantity", "需要分清班前可用时数与完成班次后的余量")
    # Reject extra quantities, replacements, other meters, exceptions and qualification language.
    covered = list(text)
    values = {}
    references = []
    def mark(hit):
        covered[hit.start():hit.end()] = " "*(hit.end()-hit.start())
    for key, pattern in RULES.items():
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise Unresolved("maintenance_field", NAMES[key]+"需要唯一且明确的原文数值")
        hit = matches[0]
        mark(hit)
        value = Decimal(hit["n"])
        values[key] = value * (1 if hit["u"].lower() in ("分钟","min") else 60)
        references.append({"role":NAMES[key],"start":hit.start("n"),"end":hit.end("u"),"text":text[hit.start("n"):hit.end("u")]})
    inclusive = list(INCLUSIVE.finditer(text))
    strict = list(STRICT.finditer(text))
    if inclusive and strict:
        raise Unresolved("maintenance_endpoint", "限值端点的两处说明需要核对")
    for hit in inclusive+strict:
        mark(hit)
        references.append({"role":"端点约束","start":hit.start(),"end":hit.end(),"text":hit[0]})
    if PUNCT.sub("", "".join(covered)):
        raise Unresolved("maintenance_coverage", "记录含未归属的事实、额外工况或例外条件")
    limit, current, demand = (values[k] for k in ("limit","current","demand"))
    if limit <= 0 or demand <= 0:
        raise Unresolved("maintenance_range", "维保上限与本班运行时长须大于零")
    remaining = max(Decimal(0), limit-current)
    margin = limit-current-demand
    if margin == 0 and not (inclusive or strict):
        raise Unresolved("maintenance_endpoint", "班末恰好到限，尚缺端点是否允许的明确说明")
    if after and margin < 0 and not re.search(r"负数|净余量|带符号", q):
        raise Unresolved("maintenance_quantity", "预计班末将超限，需要明确是否报告带符号余量")
    factor, unit = (Decimal(60),"小时") if hours else (Decimal(1),"分钟")
    proof = {k:float(v/factor) for k,v in {"current":current,"limit":limit,"demand":demand,"remaining":remaining,"margin":margin}.items()}
    proof.update(unit=unit, requested="before" if before else "after", endpoint="strict" if strict else "inclusive" if inclusive else "unspecified")
    return (remaining if before else margin)/factor, margin>0 or margin==0 and bool(inclusive), references, proof


def summary(receipt):
    p = receipt["proof"]
    unit = p["unit"]
    result = f"按记录 {receipt['source']}，班前还可运行 {p['remaining']:g} {unit}，本班需连续运行 {p['demand']:g} {unit}。"
    result += (f"完成后尚余 {p['margin']:g} {unit}。" if p["margin"] >= 0 else f"若完成该班，将超出维保限值 {-p['margin']:g} {unit}。")
    return result + ("按所给演练条件可承接该班。" if receipt["decision"] == "ALLOW" else "按所给演练条件应暂缓该班。")
