"use strict";
const evidence=JSON.parse(document.getElementById("receipts").textContent);
const el=id=>document.getElementById(id);
let english=false;
const tr=(zh,en)=>english?en:zh;
const fields=[
 ["成本（元）","cost","cost",2],["碳排（千克）","carbon_kg","carbon",2],["作业量（TEU）","processed_teu","service",2],
 ["延误（分钟）","delay_minutes","delay",3],["峰值负荷（千瓦）","peak_kw","peak",2],["期末电量（%）","ending_battery_soc","terminal_soc",2],["安全违规（次）","safety_violations","safety",0]
];
const fmt=(value,digits=2)=>Number(value).toLocaleString(english?"en-US":"zh-CN",{minimumFractionDigits:digits,maximumFractionDigits:digits});
function chart(base,chosen,hour){
 const canvas=el("chart"),scale=window.devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;
 canvas.width=w*scale;canvas.height=h*scale;const ctx=canvas.getContext("2d");ctx.scale(scale,scale);
 const numbers=[...base,...chosen].map(row=>row[0]),lo=Math.floor(Math.min(...numbers)/1000)*1000,hi=Math.ceil(Math.max(...numbers)/1000)*1000;
 const x=i=>52+(w-66)*i/23,y=n=>h-28-(n-lo)/Math.max(1,hi-lo)*(h-49);
 ctx.font="12px sans-serif";ctx.textAlign="right";for(let i=0;i<3;i++){const value=lo+(hi-lo)*i/2;ctx.fillStyle="#385353";ctx.fillText(fmt(value,0),47,y(value)+4);ctx.strokeStyle="#e0e6df";ctx.beginPath();ctx.moveTo(52,y(value));ctx.lineTo(w-14,y(value));ctx.stroke()}
 for(const [rows,color,dash] of [[base,"#795229",[5,3]],[chosen,"#006b74",[]]]){ctx.strokeStyle=color;ctx.lineWidth=2;ctx.setLineDash(dash);ctx.beginPath();rows.forEach((r,i)=>i?ctx.lineTo(x(i),y(r[0])):ctx.moveTo(x(i),y(r[0])));ctx.stroke()}
 ctx.setLineDash([]);ctx.strokeStyle="#687d78";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x(hour),14);ctx.lineTo(x(hour),h-24);ctx.stroke();
 ctx.textAlign="center";ctx.fillStyle="#385353";for(const i of [0,6,12,18,23])ctx.fillText(i+tr("时","h"),x(i),h-6);
}
function render(){
 const code=el("anchor").value+"-"+el("scenario").value,group=evidence.groups[code],policy=el("policy").value;
 const selected=group.strategies[policy],idx=Number(el("window").value),hour=Number(el("hour").value);
 const base=group.base[idx],row=selected.rows[idx],flags=row.checks;
 el("overall").textContent=selected.passed+" / 12 个窗口通过全部条件";
 el("costSummary").textContent="逐窗口成本变化的算术平均为 "+(selected.cost_pct>0?"+":"")+fmt(selected.cost_pct,2)+"%。";
 el("metrics").replaceChildren(...fields.map(([label,key,rule,detail])=>{const tr=document.createElement("tr");const mul=key==="ending_battery_soc"?100:1;[label,fmt(base.metrics[key]*mul,detail),fmt(row.metrics[key]*mul,detail),flags[rule]?"通过":"未过"].forEach((v,i)=>{const td=document.createElement("td");td.textContent=v;if(i===3)td.className=flags[rule]?"pass":"fail";tr.append(td)});return tr}));
 chart(base.trace,row.trace,hour);const t=row.trace[hour],b=base.trace[hour];
 el("hourLabel").textContent=base.period+"　窗口内第 "+(hour+1)+" 小时";
 el("hourData").textContent="负荷 "+fmt(t[0])+" 千瓦（对照 "+fmt(b[0])+"）。岸桥启用 "+fmt(t[1]*100,1)+"%，场桥启用 "+fmt(t[2]*100,1)+"%。本小时成本 "+fmt(t[3])+" 元。"+(policy==="raw"?(t[4]?"提议满足单步约束。":"动作关闭保护后实际执行，未满足单步约束。"):(t[4]?"提议满足单步约束。":"保护规则恢复了对照动作。"));
 el("provenance").textContent="权重 SHA-256　"+evidence.weight+"。数据集 SHA-256　"+evidence.dataset+"。";
 if(english){
  el("overall").textContent=selected.passed+" / 12 windows passed all checks";
  el("costSummary").textContent="Mean of the paired cost changes: "+fmt(selected.cost_pct,2)+"%.";
  const labels=["Cost (CNY)","Carbon (kg)","Throughput (TEU)","Delay (min)","Peak load (kW)","Final charge (%)","Safety violations"];
  [...el("metrics").rows].forEach((r,i)=>{r.cells[0].textContent=labels[i];r.cells[3].textContent=flags[fields[i][2]]?"Pass":"Fail"});
  el("hourLabel").textContent=base.period+" · hour "+(hour+1)+" of 24";
  el("hourData").textContent="Load "+fmt(t[0])+" kW (baseline "+fmt(b[0])+" kW). Quay cranes "+fmt(t[1]*100,1)+"%, yard cranes "+fmt(t[2]*100,1)+"%. Hourly cost CNY "+fmt(t[3])+". "+(t[4]?"Proposal passed the hourly checks.":policy==="raw"?"Unprotected proposal failed an hourly check.":"The shield restored the baseline action.");
  el("provenance").textContent="Weights SHA-256 "+evidence.weight+". Dataset SHA-256 "+evidence.dataset+".";
 }
}
const translations=[];
function translation(node,en,textOnly=false){translations.push([node,en,textOnly?node.firstChild.textContent:node.textContent,textOnly])}
function many(selector,strings,textOnly=false){document.querySelectorAll(selector).forEach((node,i)=>translation(node,strings[i],textOnly))}
many("h1",["Trained equipment dispatch"]);
many("header p",["GullMate · CarbonOps historical simulation. Compare hourly quay-crane and yard-crane dispatch under cost, service and safety constraints."]);
many(".controls label",["Baseline","Demand scenario","Candidate","24-hour window"],true);
many("#anchor option",["Fixed rule","Two-step MPC"]);
many("#scenario option",["Normal demand","Demand +25%"]);
many("#policy option",["Trained Q + shield","Same weights, shield off","Fixed cap + shield","Random + shield","Enumerate feasible actions"]);
many("article h2",["Twelve holdout windows","Seven checks for this window","Hourly replay","Completed negotiation orders"]);
many("article:first-of-type .muted",["Cost must fall. Carbon, throughput, delay, peak power and final state of charge must meet the baseline thresholds, with zero safety violations."]);
many("thead th",["Metric","Baseline","Candidate","Check"]);
many(".chart-legend span",["━ Candidate load","┄ Baseline load","kW"]);
many("article:last-child details summary",["Training, action protection and comparisons"]);
many("article:last-child details p:not(#provenance)",["Three Q-learning seeds each completed 4,608 updates using 2020–2023 data. The 2024 validation results selected seed 59. The normal and stress scenarios reuse the same twelve 2025 historical windows.",
 "Each hour the policy caps quay-crane and yard-crane use on top of a baseline action. A causal one-step simulation checks service, cost and safety. If the proposal fails a check, the original action is restored. With MPC selected, the starting action comes from two-step MPC.",
 "Validation alone selected the constant cap. The enumeration control tests all eleven actions on the current simulated state and picks the lowest-cost feasible one. The replay uses saved simulation receipts."]);
many("footer",["GullMate · Historical port policy evaluation"]);
el("language").onclick=()=>{english=!english;document.documentElement.lang=english?"en":"zh-CN";el("language").textContent=english?"中文":"EN";for(const [node,en,zh,first] of translations){if(first)node.firstChild.textContent=english?en:zh;else node.textContent=english?en:zh}render();renderMeeting()};
function renderMeeting(){
 const meetings=evidence.meetings;if(!meetings?.length)return;
 const names={initial:tr("仅原提案","Initial proposal only"),trained:tr("允许受训替代策略","Trained alternative allowed"),all:tr("同时允许穷举策略","Enumeration also allowed")};
 const choices={initial:tr("原始 PPO","Initial PPO"),learned:tr("受训 Q ＋ 动作保护","Trained Q + shield"),greedy:tr("逐小时穷举","Hourly enumeration"),baseline:tr("原对照","Original baseline")};
 const roles={energy:tr("能源岗","Energy"),dispatch:tr("调度岗","Dispatch"),safety:tr("安全岗","Safety")};
 const checks={cost:tr("成本","cost"),carbon:tr("碳排","carbon"),service:tr("服务量","throughput"),delay:tr("延误","delay"),peak:tr("峰值","peak power"),terminal_soc:tr("期末电量","terminal charge"),safety:tr("违规","violations")};
 const index=Number(el("meeting").value||0),m=meetings[index];
 el("meeting").replaceChildren(...meetings.map((v,i)=>new Option(v.period+" · "+names[v.mode],String(i))));el("meeting").value=String(index);
 el("meetings").hidden=false;el("meetingLabel").textContent=tr("选择归档工单","Select an archived negotiation");el("meetingEvidence").textContent=tr("复核本次会审","Verify this negotiation");
 el("meetingScope").textContent=tr("对照 · ","Baseline · ")+(m.anchor==="fixed"?tr("固定规则","fixed rule"):"MPC2")+" · "+(m.scene==="stress"?tr("需求提高 25%","demand +25%"):tr("常规需求","normal demand"))+" · "+m.modelCalls+tr(" 次实际模型调用"," recorded model calls");
 const create=(tag,value)=>{const e=document.createElement(tag);e.textContent=value;return e};
 el("meetingRounds").replaceChildren(...m.rounds.map(r=>{const div=document.createElement("div");div.append(create("h3",tr("第 "+r.round+" 轮　","Round "+r.round+" · ")+choices[r.choice]));
   for(const [role,v] of Object.entries(r.opinions))div.append(create("p",roles[role]+" · "+(v.verdict==="pass"?tr("通过","Pass"):tr("否决","Veto")+" ("+v.failed.map(k=>checks[k]).join(", ")+")")));return div}));
 el("meetingDecision").textContent=tr("管理岗决议　","Management decision · ")+(m.decision==="retain_baseline"?tr("保留原对照","Retain original baseline"):tr("提交人工复核 · ","Submit for human review · ")+choices[m.chosen]);
 el("meetingCommand").textContent="G:\\AI\\WindowsDeploy\\portai.cmd team negotiate "+m.key;
 el("meetingSource").textContent=tr("实际回执组 SHA-256　","Candidate book SHA-256 · ")+m.source;
}
el("meeting").addEventListener("input",renderMeeting);
evidence.groups["fixed-evaluate"].base.forEach((r,i)=>el("window").add(new Option(r.period,String(i))));
for(const id of ["anchor","scenario","policy","window","hour"])el(id).addEventListener("input",render);
window.addEventListener("resize",render);render();renderMeeting();
