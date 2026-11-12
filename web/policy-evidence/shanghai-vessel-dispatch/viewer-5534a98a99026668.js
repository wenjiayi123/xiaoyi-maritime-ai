"use strict";
const el=k=>document.getElementById(k),local=el("data")?JSON.parse(el("data").textContent):null;
let en=false,index,receipt,counter=0;
const l=(a,b)=>en?b:a;
const scenes={normal:["常规","Normal"],arrival_surge:["到港量增加","Arrival surge"],berth_outage:["泊位停用","Berth outage"],grid_derating:["供电降额","Grid derating"],weather_closure:["天气封航","Weather closure"]};
const methods={trained:["受训策略","Trained policy"],untrained:["未训练网络","Untrained network"],immediate_cost:["逐步最低成本","Lowest immediate cost"],milp:["混合整数规划","Mixed-integer solver"],native:["沙盘启发式基线","Native heuristic"]};
const fields=[["objective_cny","目标成本（元）","Objective (CNY)"],["wait_vessel_hours","总等待（船时）","Total wait (vessel-hours)"],["late_vessel_hours","总逾期（船时）","Total lateness (vessel-hours)"],["processed_teu","完成量（TEU）","Handled TEU"],["shore_kwh","岸电服务（kWh）","Shore service (kWh)"],["crane_hours","岸桥占用（台时）","Crane-hours"]];
const why={complete_pair:["完整计划","Complete pair"],handled_teu:["作业量","Handled TEU"],wait:["总等待","Total wait"],late:["总逾期","Total lateness"],service:["岸电和岸桥服务","Shore and crane service"],strict_cost:["目标成本严格下降","Strict cost reduction"]};
const cell=(tag,value)=>{const e=document.createElement(tag);e.textContent=value;return e};
function options(id,values){const s=el(id),was=s.value;s.replaceChildren(...Object.entries(values).map(([v,t])=>new Option(l(...t),v)));if(values[was])s.value=was}
function header(){
 document.documentElement.lang=en?"en":"zh-CN";el("language").textContent=en?"中文":"EN";
 const names={title:["上海港逐船排程","Shanghai vessel scheduling"],intro:["上海港 2025 年公开日数据与工程船期 · 24 小时回顾性仿真","Shanghai public inputs and simulated port calls · 24-hour retrospective windows"],ld:["评测日期","Evaluation date"],ls:["工况","Scenario"],lm:["方法","Method"],status:["排程复核","Schedule review"],timeline:["船舶与泊位","Vessels and berths"],source:["数据来源与复跑","Sources and reproduction"]};
 for(const [k,v] of Object.entries(names))el(k).textContent=l(...v);
 options("scenario",scenes);options("method",methods);
 const set=(k,a,b)=>el(k).replaceChildren(...l(a,b).map(x=>cell("th",x)));
 set("metricHead",["指标","基线","当前方案"],["Metric","Baseline","Selected"]);
 set("shipHead",["模拟船次","到港","泊位","开工–完工","截止","等待","0–24 时"],["Simulated call","ETA","Berth","Start–end","Due","Wait","0–24 h"]);
}
async function get(file,expected){
 let raw;if(local)raw=local[file];else{const res=await fetch(file);if(!res.ok)throw Error("HTTP "+res.status);raw=await res.text()}
 const hash=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(raw));
 if([...new Uint8Array(hash)].map(v=>v.toString(16).padStart(2,"0")).join("")!==expected)throw Error("回执校验失败 / Receipt hash mismatch");
 return JSON.parse(raw);
}
function clear(){for(const id of ["overall","decision","boundary","metrics","ships","sourceInfo","cmd","sha"])el(id).replaceChildren();receipt=null}
function draw(){
 if(!receipt)return;
 const d=receipt,key=el("method").value,m=d.methods[key],b=d.methods.native,stats=index.summary[key];
 el("overall").textContent=key==="native"?l("基线覆盖全部 60 个组合。","The baseline covers all 60 cases."):l("60 个留出组合中，","Across 60 held-out cases, ")+stats.pass+l(" 个在保证服务后降低了目标成本。"," reduced the objective while preserving service.");
 const misses=Object.keys(m.checks).filter(k=>!m.checks[k]).map(k=>l(...why[k]));
 el("decision").className=m.eligible?"pass":"hold";
 el("decision").textContent=key==="native"?l("该计划用于配对比较。","Paired baseline schedule."):m.eligible?l("本组合达到离线改进门槛。","This case qualifies as an offline improvement."):l("暂缓替换基线。未过条件 · ","Retain the baseline. Unmet conditions · ")+misses.join(en?", ":"、");
 el("boundary").textContent=l("各方案使用相同的全天输入。船次、时长和资源是工程设定，时间为上海当地整点。","All methods share the same full-day inputs. Calls, durations and resources are engineered. Hours are Shanghai local time.");
 const fmt=v=>Number(v).toLocaleString(en?"en-US":"zh-CN",{maximumFractionDigits:2});
 el("metrics").replaceChildren(...fields.map(([k,cn,eng])=>{const tr=document.createElement("tr");tr.append(cell("td",l(cn,eng)),cell("td",fmt(b.metrics[k])),cell("td",fmt(m.metrics[k])));return tr}));
 const jobs=new Map(d.jobs.map(j=>[j.id,j]));
 el("ships").replaceChildren(...[...m.scheduled].sort((a,b)=>a.start_hour-b.start_hour||a.berth-b.berth).map(r=>{
  const job=jobs.get(r.job_id),tr=document.createElement("tr"),timeline=document.createElement("td"),track=cell("span",""),bar=cell("span","");
  track.className="track";bar.className="slot";bar.style.left=(100*r.start_hour/24)+"%";bar.style.width=(100*(r.end_hour-r.start_hour)/24)+"%";track.append(bar);timeline.append(track);
  const short=cell("td",r.job_id.split("-").slice(-2).join("-"));short.title=r.job_id;
  tr.append(short,cell("td",job.arrival_hour),cell("td",r.berth+1),cell("td",r.start_hour+"–"+r.end_hour),cell("td",job.deadline_hour),cell("td",r.start_hour-job.arrival_hour),timeline);return tr}));
 el("sourceInfo").textContent=l("港口公开日数据与再分析气象由上海港统一试验包提供。沙盘独立检查每艘船的泊位、航道、引航、拖轮、岸桥和供电约束。","The Shanghai trial package supplies daily public data and weather reanalysis. The sandbox independently checks each berth, channel, pilot, tug, crane and power constraint.");
 el("cmd").textContent="G:\\AI\\WindowsDeploy\\portai.cmd vessels "+d.date+" --scenario "+d.scenario+" --method "+key+" --json";
 el("sha").textContent="SHA-256 "+index.receipts[d.scenario+"/"+d.date];
}
async function selectDay(){
 const seq=++counter,day=el("date").value,sc=el("scenario").value;clear();el("decision").textContent=l("正在核对回执…","Checking receipt…");
 try{const d=await get(sc+"/"+day+".json",index.receipts[sc+"/"+day]);if(seq!==counter)return;
 if(d.date!==day||d.scenario!==sc||d.production_authority!==false||d.weight_sha256!==index.weight_sha256)throw Error("Scope mismatch");
 receipt=d;draw()}catch(e){if(seq===counter){clear();el("decision").textContent=e.message}}
}
header();el("language").onclick=()=>{en=!en;header();draw()};el("method").onchange=draw;el("scenario").onchange=el("date").onchange=selectDay;
get("index.json","2f1d51ec05a242f3eec24255082284862ab8ac179e16aec58a1975ee72926d52").then(v=>{index=v;el("date").replaceChildren(...v.dates.map(d=>new Option(d,d)));return selectDay()}).catch(e=>{el("decision").textContent=e.message});
