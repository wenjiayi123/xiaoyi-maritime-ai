"use strict";
const $=key=>document.getElementById(key);
let en=false,index,dayData,requestNumber=0;
const embedded=$("offline");
const local=embedded?JSON.parse(embedded.textContent):null;
const edition=$("edition")?JSON.parse($("edition").textContent):null;
const language=(cn,eng)=>en?eng:cn;
const fmt=(v,n=2)=>Number(v).toLocaleString(en?"en-US":"zh-CN",{maximumFractionDigits:n,minimumFractionDigits:n});
const listing={
 anchor:[["fixed","固定规则","Fixed rule"],["mpc2","两步 MPC","Two-step MPC"]],
 demand:[["normal","常规需求","Normal demand"],["stress","需求提高 25%","Demand +25%"]],
 method:[["trained","受训四岗协调","Trained team"],["untrained_scores","相同约束，未训练网络","Untrained, same constraints"],
 ["minimum_cost","相同动作集，按成本排序","Lowest-cost feasible action"],["cranes_only","仅起重设备可调整","Crane controls only"],
 ["flex_only","仅充电、冷藏与楼宇可调整","Electrical flexibility only"]]};
if(edition)listing.method=edition.methods;
const gates=[
 ["cost","日成本（元）","Cost (CNY)","cost"],["carbon","碳排放（kg）","Carbon (kg)","carbon_kg"],
 ["throughput","完成量（TEU）","Throughput (TEU)","processed_teu"],["delay","延误（分钟）","Delay (min)","delay_minutes"],
 ["peak","峰值（kW）","Peak (kW)","peak_kw"],["zero_safety","安全违规（次）","Safety violations","safety_violations"],
 ["shore_service","岸电交付（kWh）","Shore power (kWh)","shore_power_kwh"],["terminal_soc","期末储能 SOC","Final storage SOC","ending_battery_soc"],
 ["agv_delivered","AGV 实充（kWh）","AGV charging (kWh)","agv_charged_kwh"],["agv_departures","未满足出车电量（kWh）","Missed departure energy (kWh)","agv_missed_required_kwh"],
 ["cold_chain","冷链热违规（次）","Cold-chain violations","reefer_thermal_violation_steps"],["terminal_thermal_debt","期末制冷欠量（模型单位）","Final thermal debt (model units)","ending_reefer_thermal_debt"],
 ["building_service","无合同依据的楼宇减供（kWh）","Unsupported building reduction (kWh)","unbacked"],
 ["dr_commitment","响应承诺（kWh）","Response commitment (kWh)","demand_response_target_kwh"],
 ["dr_delivery","响应交付（kWh）","Response delivered (kWh)","demand_response_delivered_kwh"]];
const textNode=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;return e};
function options(id){
 const sel=$(id),last=sel.value;sel.replaceChildren(...listing[id].map(([key,cn,eng])=>new Option(language(cn,eng),key)));
 if([...sel.options].some(v=>v.value===last))sel.value=last;
}
function labels(){
 document.documentElement.lang=en?"en":"zh-CN";$("language").textContent=en?"中文":"EN";
 const labels={title:["四岗联合调配","Four-agent dispatch"],intro:["洛杉矶港历史工程仿真 · 2024 年日窗口","Port of Los Angeles engineering simulation · 2024 daily windows"],
 baselineLabel:["对照调度","Baseline"],demandLabel:["需求","Demand"],methodLabel:["调配方法","Method"],dayLabel:["评测日期","Evaluation day"],
 overviewTitle:["全部日窗口","All daily windows"],checkTitle:["所选日期的业务验收","Business checks for the selected day"],
 hourTitle:["逐时动作与实物交付","Hourly controls and delivered service"],proofLabel:["来源与复核","Source and verification"],
 specialists:["查看冷站、照明与上海联合仿真复验","Cooling, lighting and Shanghai coordination evidence"]};
 if(edition)Object.assign(labels,edition.labels);
 for(const [id,names] of Object.entries(labels))$(id).textContent=language(...names);
 for(const id of ["anchor","demand","method"])options(id);
 $("metricHead").replaceChildren(...(en?["Measure","Baseline","Candidate","Check"]:["指标","对照","候选","门槛"]).map(v=>textNode("th",v)));
 $("flowHead").replaceChildren(...(en?["Delivery","Baseline","Candidate"]:["实物交付","对照","候选"]).map(v=>textNode("th",v)));
}
async function measured(raw,expected){
 const bytes=new TextEncoder().encode(raw),hash=await crypto.subtle.digest("SHA-256",bytes);
 const actual=[...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,"0")).join("");
 if(actual!==expected)throw Error("证据摘要不符 / Evidence hash mismatch");
 return JSON.parse(raw);
}
async function readBound(name,expected){
 let raw;
 if(local)raw=local[name];else{const r=await fetch(name);if(!r.ok)throw Error("HTTP "+r.status);raw=await r.text()}
 return measured(raw,expected);
}
function clearReceipt(){dayData=null;for(const id of ["disposition","failed","capacity","metrics","flow","proposal","hourText","digest","command","evidence"])$(id).replaceChildren()}
function draw(){
 if(!index)return;
 const grp=$("anchor").value+"-"+$("demand").value,method=$("method").value,summary=index.groups[grp].summary[method];
 $("overall").textContent=summary.pass+" / "+summary.n+language(" 日通过全部 15 项条件"," days passed all 15 conditions");
 $("overallCost").textContent=language("逐日成本变化的平均值 ","Mean paired cost change ")+fmt(summary.mean_cost_pct)+"%.";
 $("boundary").textContent=language("每组使用相同的 "+summary.n+" 个日期。通过表示可以提交离线复核，各方案均无现场控制权限。","Groups reuse the same "+summary.n+" dates. Passing permits offline review. No method has field-control authority.");
 if(!dayData)return;
 const d=dayData,r=d.methods[method],b=d.baseline,m=r.metrics;
 $("disposition").textContent=r.passed?language("可提交离线复核","Eligible for offline review"):language("暂缓此候选","Withhold candidate");
 $("disposition").className="fact "+(r.passed?"pass":"fail");
 const rejected=gates.filter(g=>!r.checks[g[0]]).map(g=>language(g[1],g[2]));
 $("failed").textContent=rejected.length?language("未过门槛 · ","Failed · ")+rejected.join(en?", ":"、"):language("全部 15 项均已核对。","All 15 conditions checked.");
 $("capacity").textContent=d.target>0?language("需求响应最低交付 ","Minimum DR delivery ")+fmt(d.target*.98)+" kWh · "+language("实交 ","Delivered ")+fmt(m.demand_response_delivered_kwh)+" kWh.":"";
 $("metrics").replaceChildren(...gates.map(([gate,cn,eng,k])=>{const tr=document.createElement("tr"),base=k==="unbacked"?0:b[k],value=k==="unbacked"?r.unbacked_building_kwh:m[k];
 const flag=textNode("td",r.checks[gate]?language("通过","Pass"):language("未过","Fail"));flag.className=r.checks[gate]?"pass":"fail";
 tr.append(textNode("td",language(cn,eng)),textNode("td",fmt(base,k.includes("debt")?5:2)),textNode("td",fmt(value,k.includes("debt")?5:2)),flag);return tr}));
 const h=Number($("hour").value),t=r.hours[h],ref=d.reference_hours[h];
 $("hourText").textContent=d.day+" · "+language("窗口内第 "+(h+1)+" 小时","hour "+(h+1)+" of 24");
 $("flow").replaceChildren(...[[0,"负荷（kW）","Load (kW)"],[1,"作业量（TEU）","Throughput (TEU)"],[2,"AGV 充电（kWh）","AGV charge (kWh)"],
 [3,"制冷欠量","Thermal debt"],[4,"楼宇供电（kWh）","Building supply (kWh)"],[5,"响应交付（kWh）","DR delivered (kWh)"]].map(([i,cn,eng])=>{
 const tr=document.createElement("tr");tr.append(textNode("td",language(cn,eng)),textNode("td",fmt(ref[i],i===3?5:2)),textNode("td",fmt(t.flow[i],i===3?5:2)));return tr}));
 const actionStatus=t.certified===0?language("该小时没有找到可认证的组合，沿用对照指令。","No certified menu item this hour. The baseline command was retained."):language("当小时通过初步筛选的动作组合数 ","Physical menu items passing preliminary checks ")+t.certified+"。";
 $("proposal").textContent=language("送入仿真的设备比例 · 岸桥、场桥、AGV、冷藏、楼宇 ","Submitted ratios · quay crane, yard crane, AGV, reefer, building ")+t.ratios.map(x=>fmt(x,2)).join(" / ")+"。 "+actionStatus;
 $("evidence").textContent=language("四个本地效用网络采用共同团队回报训练。大部分设备输入是公开锚定和工程估计。综合节约不能归为每个岗位各自的学习收益。","Four local utility networks trained on a common team reward. The plant combines public anchors with engineering assumptions. Aggregate savings do not identify each agent's contribution.");
 $("command").textContent="G:\\AI\\WindowsDeploy\\portai.cmd devices "+d.day+" --baseline "+$("anchor").value+" --demand "+$("demand").value+" --method "+method+" --json";
 $("digest").textContent=language("权重 SHA-256　","Weight SHA-256 · ")+index.weight;
 if(edition){
  $("command").textContent=language("原始日回执　","Daily source · ")+d.source+" · SHA-256 "+d.native_source_sha256;
  $("evidence").textContent=language(...edition.evidence);
 }
}
async function selectDay(groupChanged){
 const id=++requestNumber;clearReceipt();
 const grp=$("anchor").value+"-"+$("demand").value,days=index.groups[grp].days,prior=$("day").value;
 if(groupChanged){$("day").replaceChildren(...days.map(v=>new Option(v.day,v.day)));if(days.some(v=>v.day===prior))$("day").value=prior}
 const day=$("day").value,record=days.find(r=>r.day===day);draw();$("disposition").textContent=language("核对原件中…","Checking receipt…");
 try{const fresh=await readBound(grp+"-"+day+".json",record.sha256);if(id!==requestNumber)return;
 if(fresh.group!==grp||fresh.day!==day||fresh.production_authority!==false)throw Error("Invalid receipt scope");
 dayData=fresh;draw()}catch(e){if(id===requestNumber){clearReceipt();$("disposition").textContent=String(e.message)}}
}
labels();$("language").onclick=()=>{en=!en;labels();draw()};
$("hour").addEventListener("input",draw);$("method").addEventListener("change",draw);
for(const id of ["anchor","demand"])$(id).addEventListener("change",()=>selectDay(true));$("day").addEventListener("change",()=>selectDay(false));
readBound("index.json","c30f3381a5234110425cb16d105c7a20c8d143a361e94046e7acb3a1b6e81e86").then(v=>{index=v;selectDay(true)}).catch(e=>{$("overall").textContent=String(e.message)});
