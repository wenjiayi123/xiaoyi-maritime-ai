"use strict";
const byId = id => document.getElementById(id);
const receipt = JSON.parse(byId("records").textContent);
const labels = {
  zh: {
    title:"港机与储能调度复算", back:"返回策略复验", intro:"2025 年历史能碳仿真。逐小时对照同一工况的 MPC、设备能力控制和受训策略。",
    group:"试验组", window:"日期与需求倍率", mode:"控制策略", time:"查看小时", known:"已研究的 24 个工况", fresh:"新增的 24 个工况",
    total:"本组通过数", change:"本组平均成本变化", current:"所选工况", measures:"当日七项业务约束", name:"指标", selected:"所选策略", baseline:"MPC", rule:"条件",
    hourly:"逐小时对照", horizon:"小时", load:"负荷 · kW", soc:"荷电比例", cost:"模拟成本 · 元", crane:"岸桥控制比例", yard:"场内设备控制比例", battery:"储能功率比例",
    passed:"通过", missed:"未通过", reference:"对照基线", matches:"项通过", explanation:"各回合从同一初态运行 24 小时。正储能功率表示放电，负值表示充电。新增组复用同一港口历史数据，各组内两个需求倍率共享日期。金额均来自仿真。",
    modes:["MPC","受保护的港机 Q","设备能力控制","储能空闲","设备能力 + 储能空闲","设备能力 + 储能限峰","设备能力 + 储能 Q"],
    metrics:["成本（元）","碳排放（kg）","处理量（TEU）","延误（分钟）","峰值功率（kW）","安全违规（次）","期末荷电比例"],
    rules:["严格低于 MPC","至多等于 MPC","至少等于 MPC","至多等于 MPC","至多等于 MPC","等于零","至少等于 MPC"]},
  en: {
    title:"Equipment and battery dispatch", back:"Policy replay", intro:"Historical 2025 energy simulation. Compare MPC, capacity-based dispatch and trained policies for the same operating conditions.",
    group:"Evaluation group",window:"Date and demand multiplier",mode:"Dispatch policy",time:"Hour",known:"24 previously studied scenarios",fresh:"24 additional scenarios",
    total:"Group pass count",change:"Group mean cost change",current:"Selected scenario",measures:"Daily operating constraints",name:"Metric",selected:"Selected policy",baseline:"MPC",rule:"Requirement",
    hourly:"Hourly comparison",horizon:"Hour",load:"Load · kW",soc:"State of charge",cost:"Simulated cost · CNY",crane:"Crane setpoint",yard:"Yard setpoint",battery:"Battery power ratio",
    passed:"Pass",missed:"Miss",reference:"Baseline",matches:"criteria met",explanation:"Each 24-hour episode starts from the same state. Positive battery power discharges. Negative power charges. Both groups reuse one port dataset, and the two demand multipliers in each group share dates. Costs are simulated.",
    modes:["MPC","Shielded crane Q","Capacity control","Idle battery","Capacity + idle battery","Capacity + peak limiting","Capacity + battery Q"],
    metrics:["Cost (CNY)","Carbon (kg)","Handled volume (TEU)","Delay (min)","Peak load (kW)","Safety violations","Ending state of charge"],
    rules:["Strictly below MPC","At most MPC","At least MPC","At most MPC","At most MPC","Zero","At least MPC"]}
};
let lang = "zh";
function options(el,pairs,choice){el.replaceChildren(...pairs.map(([value,label])=>new Option(label,value)));el.value=choice;}
function row(values){const tr=document.createElement("tr");for (const value of values){const td=document.createElement("td");td.textContent=value;tr.append(td);}return tr;}
function setup(){
  const l=labels[lang],g=byId("group").value||"fresh",m=byId("policy").value||"capacity_peak",w=byId("window").value||"0";
  document.documentElement.lang=lang==="zh"?"zh-CN":"en";document.title=l.title;
  document.querySelectorAll("[data-label]").forEach(el=>el.textContent=l[el.dataset.label]);byId("language").textContent=lang==="zh"?"English":"中文";
  options(byId("group"),["known","fresh"].map(k=>[k,l[k]]),g);
  options(byId("policy"),receipt.modes.map((k,i)=>[k,l.modes[i]]),m);
  options(byId("window"),receipt.rows.filter(r=>r.group===g).map((r,i)=>[String(i),r.date+" · ×"+r.load]),w);
  draw();
}
function draw(){
  const l=labels[lang],g=byId("group").value,m=byId("policy").value,index=Number(byId("window").value),hr=Number(byId("hour").value);
  const current=receipt.rows.filter(r=>r.group===g)[index],series=current.runs[m],base=current.runs.mpc,summary=receipt.summary[g][m],flags=series.flags;
  byId("passes").textContent=m==="mpc"?"—":summary.passed+" / 24";byId("delta").textContent=summary.cost_pct.toFixed(3)+"%";
  byId("score").textContent=m==="mpc"?l.reference:flags.filter(Boolean).length+" / 7 "+l.matches;
  byId("metrics").replaceChildren(...series.metrics.map((v,i)=>row([l.metrics[i],v.toLocaleString(lang,{maximumFractionDigits:4}),base.metrics[i].toLocaleString(lang,{maximumFractionDigits:4}),l.rules[i],m==="mpc"?"—":flags[i]?l.passed:l.missed])));
  byId("readHour").textContent=String(hr).padStart(2,"0")+":00 UTC";
  const a=series.trace[hr],b=base.trace[hr],fields=[l.load,l.soc,l.cost,l.crane,l.yard,l.battery];
  byId("trace").replaceChildren(...fields.map((k,i)=>row([k,a[i].toLocaleString(lang,{maximumFractionDigits:4}),b[i].toLocaleString(lang,{maximumFractionDigits:4})])));
}
byId("group").addEventListener("change",()=>{byId("window").value="0";setup()});
byId("policy").addEventListener("change",draw);byId("window").addEventListener("change",draw);byId("hour").addEventListener("input",draw);
byId("language").addEventListener("click",()=>{lang=lang==="zh"?"en":"zh";setup();});setup();
