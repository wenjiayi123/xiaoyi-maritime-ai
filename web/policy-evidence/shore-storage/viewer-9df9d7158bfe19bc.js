"use strict";
const $=id=>document.getElementById(id),embedded=$("data")?JSON.parse($("data").textContent):null;
let en=false,mode="week",index,row,seq=0;
const L=(a,b)=>en?b:a,fmt=(n,p=2)=>Number(n).toLocaleString(en?"en-US":"zh-CN",{minimumFractionDigits:p,maximumFractionDigits:p});
const partNames={validation:["验证","Validation"],repeat:["重复测试","Repeated test"],forward:["前向基准","Forward benchmark"]};
const metrics=[["total_cost_cny","账单（元）","Bill (CNY)"],["carbon_kg","碳排（kg）","Carbon (kg)"],["peak_kw","峰值（kW）","Peak (kW)"]];
function node(tag,text){const n=document.createElement(tag);n.textContent=text;return n}
function labels(){
 document.documentElement.lang=en?"en":"zh-CN";$("lang").textContent=en?"中文":"EN";
 const t={title:["岸电与储能复核","Shore power and storage"],intro:["上海工程仿真 · 策略周回放与逐船供电记录","Shanghai engineering simulations · weekly dispatch and separate vessel meter records"],
 weekTab:["周策略","Weekly policy"],callTab:["逐船电表","Vessel meters"],lp:["评测分区","Partition"],lw:["周起点（UTC）","Week start (UTC)"],lc:["工程船次","Simulated call"],
 overallTitle:["分区评测","Partition results"],compareTitle:["本周配对账单","Paired weekly outcomes"],hourTitle:["逐小时功率","Hourly power"],meterTitle:["靠泊期间供电","Metered energy during call"],source:["来源与复跑","Sources and reproduction"]};
 for(const [id,val] of Object.entries(t))$(id).textContent=L(...val);
 const part=$("part").value||"forward";$("part").replaceChildren(...Object.entries(partNames).map(([k,n])=>new Option(L(...n),k)));$("part").value=part;
 $("mhead").replaceChildren(...L(["指标","待机","受训","固定方案"],["Measure","Idle","Learned","Fixed"]).map(v=>node("th",v)));
 $("legend").textContent=L("灰线为待机基线，绿线为受训方案。曲线位置按本周功率范围缩放。","Grey is idle and green is learned. The vertical range follows this week's meter readings.");
}
async function load(name,expected){
 let raw;if(embedded)raw=embedded[name];else{const r=await fetch(name);if(!r.ok)throw Error("HTTP "+r.status);raw=await r.text()}
 const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(raw));
 if([...new Uint8Array(digest)].map(v=>v.toString(16).padStart(2,"0")).join("")!==expected)throw Error("回执哈希不符 / receipt hash mismatch");
 return JSON.parse(raw);
}
function graph(hours){
 const svg=$("chart"),ns="http://www.w3.org/2000/svg";svg.replaceChildren();
 const values=hours.flatMap(h=>[h.base_kw,h.pcc_kw]);const low=Math.min(...values),high=Math.max(...values);
 for(const [key,color] of [["base_kw","#8a9c98"],["pcc_kw","#006b67"]]){
  const line=document.createElementNS(ns,"polyline");line.setAttribute("fill","none");line.setAttribute("stroke",color);line.setAttribute("stroke-width",key==="base_kw"?3:1.5);
  line.setAttribute("points",hours.map((h,i)=>(i*840/167+5).toFixed(2)+","+(143-137*(h[key]-low)/Math.max(1,high-low)).toFixed(2)).join(" "));svg.append(line)}
}
function hour(){
 if(!row||mode!=="week")return;const h=row.hours[+$("hour").value];
 $("hourLabel").textContent=L("窗口内第 ","Window hour ")+(h.hour+1)+"/168";
 $("hourData").textContent=L("电网输入 ","Grid import ")+fmt(h.pcc_kw)+" kW · "+L("电池 ","Battery ")+fmt(h.bess_kw)+" kW · "+L("柔性负荷变化 ","Flexible demand change ")+fmt(h.flex_kw)+" kW · SOC "+fmt(h.soc*100)+"%.";
}
function draw(){
 if(!row||!index)return;
 if(mode==="week"){
  const s=index.parts[row.part],a=row.audited;
  $("overall").textContent=s.joint+"/"+s.n+L(" 周成本、碳排和峰值同时下降"," weeks reduced cost, carbon and peak");
  $("overallDetail").textContent=L("各周相对待机平均降低 · 账单 ","Mean reduction vs idle · bill ")+fmt(s.gains.total_cost_cny,4)+"% · "+L("碳排 ","carbon ")+fmt(s.gains.carbon_kg,5)+"% · "+L("峰值 ","peak ")+fmt(s.gains.peak_kw,4)+"%.";
  $("metrics").replaceChildren(...metrics.map(([k,cn,eng])=>{const tr=document.createElement("tr");tr.append(node("td",L(cn,eng)),...["baseline","candidate","fixed"].map(f=>node("td",fmt(row[f][k]))));return tr}));
  $("decision").className=row.all_three_improved?"yes":"hold";
  $("decision").textContent=row.all_three_improved?L("本周三个指标均严格改善。","All three metrics strictly improved this week."):L("本周有指标持平或未改善。","At least one metric was flat or worse this week.");
  $("attribution").textContent=L("相对待机的碳排变化：电池 ","Carbon change vs idle · battery ")+fmt(a.battery_carbon_kg,3)+" kg · "+L("柔性负荷 ","flexible demand ")+fmt(a.flex_carbon_kg,3)+" kg · "+L("合计 ","total ")+fmt(a.carbon_delta_kg,3)+" kg.";
  $("weeklyService").textContent=L("模型保障的岸电量 ","Modeled protected shore supply ")+fmt(a.mandatory_model_shore_kwh)+" kWh · "+L("期末 SOC 误差 ","terminal SOC error ")+fmt(a.terminal_soc_error,6)+" · "+L("待补负荷 ","remaining workload ")+fmt(a.terminal_queue_kwh,4)+" kWh.";
  $("scope").textContent=L("固定方案是在训练段选出的柔性调度规则。周模型以公开数据校准，保障岸电作为物理约束。电池正功率表示放电。","The fixed option was chosen on training data. Public inputs calibrate the weekly plant. Shore service is a physical constraint. Positive battery power denotes discharge.");
  $("command").textContent="G:\\AI\\WindowsDeploy\\portai.cmd shore --week "+row.week+" --simulate --json";
  $("digest").textContent="SHA-256 "+index.weeks[row.week];graph(row.hours);hour();
 }else{
  $("quantity").textContent=row.call+" · "+fmt(row.in_call_kwh,3)+" kWh";
  $("meterInfo").textContent=row.vessel+" · "+row.berth+" · "+row.eta+" → "+row.etd+" · "+row.samples+L(" 条读数"," readings");
  $("meterBoundary").textContent=L("每条读数最多计入后续 15 分钟，到登记离泊时刻截止。该船次在离泊时刻有 ","Each reading covers up to the next 15 minutes, clipped at departure. Readings exactly at departure: ")+row.terminal_readings+L(" 条。"," .");
  $("scope").textContent=L("逐船模拟电表与周模型使用不同资产和数据口径。本页的船次电量只用于该数据源对账。","The call meter and weekly benchmark use distinct assets and data. Vessel kWh reconciles only this meter series.");
  $("command").textContent="G:\\AI\\WindowsDeploy\\portai.cmd shore --call "+row.call+" --json";$("digest").textContent="SHA-256 "+index.calls[row.call];
 }
}
function modeControls(){
 const w=mode==="week";$("weekTab").setAttribute("aria-pressed",w);$("callTab").setAttribute("aria-pressed",!w);
 $("weekControls").style.display=w?"flex":"none";$("callControls").hidden=w;$("weekly").hidden=!w;$("meter").hidden=w;
}
async function select(change){
 const n=++seq;row=null;$("err").textContent="";
 // Do not display the previous receipt while a new selection is loading.
 $("weekly").hidden=true;$("meter").hidden=true;$("digest").textContent="";$("command").textContent="";$("scope").textContent="";
 if(mode==="week"&&change){const dates=index.parts[$("part").value].dates;$("week").replaceChildren(...dates.map(v=>new Option(v,v)))}
 const k=mode==="week"?$("week").value:$("call").value;
 try{const kind=mode==="week"?"weeks":"calls";const r=await load(kind+"/"+k+".json",index[kind][k]);if(n!==seq)return;
 if((mode==="week"?r.week:r.call)!==k||r.production_authority!==false)throw Error("Scope mismatch");row=r;modeControls();draw()}
 catch(e){if(n===seq)$("err").textContent=e.message}
}
labels();$("lang").onclick=()=>{en=!en;labels();draw()};$("hour").oninput=hour;
$("weekTab").onclick=()=>{mode="week";modeControls();select(true)};$("callTab").onclick=()=>{mode="call";modeControls();select(false)};
$("part").onchange=()=>select(true);$("week").onchange=$("call").onchange=()=>select(false);
load("index.json","3493a7b28b388ac168806a7227e6da275c8632b4a91f376ab8da26f84b4229d3").then(v=>{index=v;$("call").replaceChildren(...Object.keys(v.calls).map(k=>new Option(k,k)));modeControls();return select(true)}).catch(e=>{$("err").textContent=e.message});
