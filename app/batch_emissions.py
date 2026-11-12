"""Net avoided emissions from declared batches and separately identified project emissions."""
from decimal import Decimal
import re

NUMBER = r"[0-9]{1,10}(?:\.[0-9]{1,6})?"
MASS = r"kg|千克|公斤|吨|t"
GAS = r"CO2e|CO₂e|CO2|CO₂|二氧化碳当量|二氧化碳"
MEASURE = rf"(?P<n>{NUMBER})\s*(?P<u>{MASS})(?:\s*(?P<gas>{GAS}))?"
COUNTED = re.compile(
    rf"(?:(?:一个独立的仿真项目|演练项目|本项目|本次|项目)\s*)?(?:回收|循环利用|再利用|利用)\s*(?P<count>{NUMBER})\s*"
    rf"(?P<item>批|次)(?P<material>余热|废热|循环材料|回用物料|余能)\s*[，,；;：:]\s*每(?P<per>批|次)"
    rf"(?:可)?(?:替代|避免|减少)\s*{MEASURE}(?:\s*排放)?", re.I)
COUNTED_MATERIAL_FIRST = re.compile(
    rf"(?:(?:一个独立的仿真项目|演练项目|本项目|本次|项目)\s*)?(?:回收|循环利用|再利用|利用)(?P<material>余热|废热|循环材料|回用物料|余能)"
    rf"\s*(?:共(?:计)?)?\s*(?P<count>{NUMBER})\s*(?P<item>批|次)\s*[，,；;：:]\s*每(?P<per>批|次)"
    rf"(?:可)?(?:替代|避免|减少)\s*{MEASURE}(?:\s*排放)?", re.I)
ADDED = re.compile(rf"(?:配套)?(?P<activity>运输|泵送|收集|装卸|处理)(?:环节)?(?:新增|增加|额外产生)(?:了)?\s*{MEASURE}(?:\s*排放)?", re.I)
LIMIT = re.compile(rf"(?:项目目标|演练目标|目标|验收要求)(?:为|是|[：:])?\s*(?P<op>至少|不低于|严格高于|超过|至多|不超过|低于)"
                   rf"\s*(?:净避免|净减排|减少|避免)?\s*{MEASURE}(?:\s*排放)?", re.I)
NO_ADDED = re.compile(r"已确认没有项目新增排放|配套环节新增排放为零")
QUESTION = re.compile(rf"(?:该项目|本项目|本次|项目)?(?:净避免(?:的排放量)?|净减排(?:量)?)(?:为|是|有)?(?:多少|几)"
                      rf"(?P<u>{MASS})(?P<gas>{GAS})?", re.I)
FOLLOW = {"项目是否达标","本项目是否达标","是否达到目标","是否满足所给目标","能否达标","是否达标"}


def applicable(facts,question):
    return bool(re.search(r"净避免|净减排",question) and re.search(r"每(?:批|次)",facts) and re.search(r"回收|循环利用|再利用|余热|废热|回用",facts))


def gas(raw):
    text=(raw or "").lower().replace("₂","2")
    return {"":"recorded","co2":"CO2","二氧化碳":"CO2","co2e":"CO2e","二氧化碳当量":"CO2e"}[text]


def kg(unit):
    return Decimal(1000) if unit.lower() in ("吨","t") else Decimal(1)


def verify(facts,question):
    from app.exercise_records import Unresolved
    q = re.split(r"\n问题[：:]",question or "")[-1]
    parts=[s for s in re.split(r"[？?。；;，,]+",re.sub(r"\s+","",q)) if s]
    requested=QUESTION.fullmatch(parts[0]) if parts and len(parts)<=2 else None
    if not requested or (len(parts)==2 and parts[1] not in FOLLOW):
        raise Unresolved("carbon_quantity","需要明确询问所给项目的净避免排放质量、单位及目标")
    mask=list(facts); refs=[]; species=set()
    def mark(hit):
        if all(c==" " for c in mask[hit.start():hit.end()]):
            raise Unresolved("carbon_overlap","存在重复归属的资料")
        mask[hit.start():hit.end()]=" "*(hit.end()-hit.start())
    def amount(hit,role):
        end=hit.end("gas") if hit["gas"] else hit.end("u")
        refs.append({"role":role,"start":hit.start("n"),"end":end,"text":facts[hit.start("n"):end]})
        species.add(gas(hit["gas"]))
        return Decimal(hit["n"])*kg(hit["u"])
    gross=Decimal(0);added=Decimal(0);materials=set();activities=set();terms=[]
    groups=sorted([*COUNTED.finditer(facts),*COUNTED_MATERIAL_FIRST.finditer(facts)],key=lambda hit:hit.start())
    for hit in groups:
        mark(hit)
        count=Decimal(hit["count"])
        if hit["item"]!=hit["per"] or count!=count.to_integral_value() or count<=0 or hit["material"] in materials:
            raise Unresolved("carbon_batches","批次与每单位因子要逐项匹配，且不能重复计入同一来源")
        materials.add(hit["material"])
        refs.append({"role":"活动次数","start":hit.start("count"),"end":hit.end("item"),"text":facts[hit.start("count"):hit.end("item")]})
        rate=amount(hit,"每单位替代量");gross+=count*rate
        terms.append({"material":hit["material"],"count":int(count),"avoided_kg_per_unit":float(rate)})
    for hit in ADDED.finditer(facts):
        mark(hit)
        if hit["activity"] in activities:
            raise Unresolved("carbon_added","同一附加环节出现多次，需核对范围")
        activities.add(hit["activity"]);added+=amount(hit,"项目附加排放")
    zeros=list(NO_ADDED.finditer(facts))
    if not terms or (not activities and len(zeros)!=1) or (activities and zeros):
        raise Unresolved("carbon_boundary","需登记替代活动、独立的项目新增排放或明确为零")
    for hit in zeros:
        mark(hit)
        refs.append({"role":"新增排放确认为零","start":hit.start(),"end":hit.end(),"text":hit[0]})
    limits=list(LIMIT.finditer(facts))
    if len(limits)!=1:
        raise Unresolved("carbon_target","需要唯一的净避免排放目标")
    target=limits[0];mark(target);threshold=amount(target,"净避免目标")
    refs.append({"role":"比较方向","start":target.start("op"),"end":target.end("op"),"text":target["op"]})
    if re.sub(r"[\s，,。；;：:、]+","","".join(mask)):
        raise Unresolved("carbon_coverage","有未归属的数量、排放来源或附加条件")
    if len(species)!=1 or requested["gas"] and gas(requested["gas"]) not in species:
        raise Unresolved("carbon_basis","排放口径须一致；记录不能自行换算气体或当量")
    net=gross-added
    op=target["op"]
    ok={"至少":net>=threshold,"不低于":net>=threshold,"严格高于":net>threshold,"超过":net>threshold,
        "至多":net<=threshold,"不超过":net<=threshold,"低于":net<threshold}[op]
    scale=kg(requested["u"])
    for value in (gross/scale,added/scale,net/scale,threshold/scale):
        if abs(value)>Decimal("1e15") or Decimal(str(float(value)))!=value:
            raise Unresolved("carbon_precision","该数量超出本演练回执可精确表示的范围")
    unit=("吨" if scale==1000 else "kg")+(" "+next(iter(species)) if species!={"recorded"} else "")
    proof={"terms":terms,"gross":float(gross/scale),"added":float(added/scale),"net":float(net/scale),"target":float(threshold/scale),
           "operator":op,"unit":unit,"mass_basis":next(iter(species)),"boundary":"declared_exercise"}
    return net/scale, ok, refs, proof


def summary(receipt):
    p=receipt["proof"];unit=p["unit"]
    result="达到" if receipt["decision"]=="ALLOW" else "未达到"
    def show(key):
        s=format(Decimal(str(p[key])),"f")
        return s.rstrip("0").rstrip(".") if "." in s else s
    return (f"按演练记录 {receipt['source']}，替代排放合计 {show('gross')} {unit}，项目新增 {show('added')} {unit}，"
            f"净避免量为 {show('net')} {unit}。对照“{p['operator']} {show('target')} {unit}”，{result}该目标。")
