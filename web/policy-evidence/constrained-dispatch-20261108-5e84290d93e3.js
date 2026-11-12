"use strict";
const evidence=JSON.parse(document.getElementById("receipts").textContent);
const el=id=>document.getElementById(id);
const fields=[
 ["成本（元）","cost","cost",2],["碳排（千克）","carbon_kg","carbon",2],["作业量（TEU）","processed_teu","service",2],
 ["延误（分钟）","delay_minutes","delay",3],["峰值负荷（千瓦）","peak_kw","peak",2],["期末电量（%）","ending_battery_soc","terminal_soc",2],["安全违规（次）","safety_violations","safety",0]
];
const fmt=(value,digits=2)=>Number(value).toLocaleString("zh-CN",{minimumFractionDigits:digits,maximumFractionDigits:digits});
function chart(base,chosen,hour){
 const canvas=el("chart"),scale=window.devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;
 canvas.width=w*scale;canvas.height=h*scale;const ctx=canvas.getContext("2d");ctx.scale(scale,scale);
 const numbers=[...base,...chosen].map(row=>row[0]),lo=Math.floor(Math.min(...numbers)/1000)*1000,hi=Math.ceil(Math.max(...numbers)/1000)*1000;
 const x=i=>52+(w-66)*i/23,y=n=>h-28-(n-lo)/Math.max(1,hi-lo)*(h-49);
 ctx.font="12px sans-serif";ctx.textAlign="right";for(let i=0;i<3;i++){const value=lo+(hi-lo)*i/2;ctx.fillStyle="#385353";ctx.fillText(fmt(value,0),47,y(value)+4);ctx.strokeStyle="#e0e6df";ctx.beginPath();ctx.moveTo(52,y(value));ctx.lineTo(w-14,y(value));ctx.stroke()}
 for(const [rows,color,dash] of [[base,"#795229",[5,3]],[chosen,"#006b74",[]]]){ctx.strokeStyle=color;ctx.lineWidth=2;ctx.setLineDash(dash);ctx.beginPath();rows.forEach((r,i)=>i?ctx.lineTo(x(i),y(r[0])):ctx.moveTo(x(i),y(r[0])));ctx.stroke()}
 ctx.setLineDash([]);ctx.strokeStyle="#687d78";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x(hour),14);ctx.lineTo(x(hour),h-24);ctx.stroke();
 ctx.textAlign="center";ctx.fillStyle="#385353";for(const i of [0,6,12,18,23])ctx.fillText(i+"时",x(i),h-6);
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
}
evidence.groups["fixed-evaluate"].base.forEach((r,i)=>el("window").add(new Option(r.period,String(i))));
for(const id of ["anchor","scenario","policy","window","hour"])el(id).addEventListener("input",render);
window.addEventListener("resize",render);render();
