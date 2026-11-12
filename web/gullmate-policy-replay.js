
"use strict";
const data=JSON.parse(document.getElementById("report").textContent);
const el=id=>document.getElementById(id);
const query=new URLSearchParams(location.search);
let english=query.get("lang")==="en";
const t=(zh,en)=>english?en:zh;
const num=(n,k=1)=>Number(n).toLocaleString(english?"en-US":"zh-CN",{maximumFractionDigits:k});
const fields=["cost","carbon_kg","processed_teu","delay_minutes","peak_kw","safety_violations"];
const labels=()=>[t("模拟成本","Simulated cost"),t("碳排 kg","Carbon kg"),t("作业 TEU","Service TEU"),t("延误 min","Delay min"),t("峰值 kW","Peak kW"),t("违规","Violations")];
function options(id,items,requested){const s=el(id),old=requested??s.value;s.replaceChildren();for(const [value,label] of items)s.add(new Option(label,value));if(items.some(x=>x[0]===old))s.value=old}
function table(id,heads,rows){const node=el(id);node.replaceChildren();const top=node.createTHead().insertRow();for(const h of heads){const th=document.createElement("th");th.textContent=h;top.append(th)}const body=node.createTBody();for(const row of rows){const line=body.insertRow();for(const v of row)line.insertCell().textContent=v}}
function name(k){if(k==="fixed")return t("固定规则","Fixed rule");if(k==="mpc2")return t("二步 MPC","2-step MPC");const [kind,seed]=k.split("-");return ({joint:t("联合 PPO","Joint PPO"),storage:t("储能 PPO","Storage PPO"),cost_only:t("去掉服务惩罚","Service penalty removed")})[kind]+" · "+seed}
function init(first=false){
 document.documentElement.lang=english?"en":"zh-CN";el("language").textContent=english?"中文":"EN";
 const labels={title:t("港口策略复验","Port policy replay"),intro:t("同一时间窗口，逐小时比较真实训练权重与基线。表格和曲线来自保存的仿真回执。","Compare trained policies against baselines hour by hour on matched windows. Tables and curves come from saved simulator receipts."),ll:t("测试负荷","Test load"),lp:t("已训练策略","Trained policy"),lb:t("比较基线","Baseline"),lw:t("测试窗口","Test window"),chartTitle:t("逐小时模拟成本","Hourly simulated cost"),studyTitle:t("全部测试窗口均值","Means across all test windows"),curveTitle:t("训练曲线与权重身份","Training curve and weight identity"),aisTitle:t("AIS 作业策略","AIS operations policy"),sourcesTitle:t("来源与系统入口","Evidence and system links"),aisText:t("公开 AIS 序列按时间留出 108 行，三个测试窗口各 24 步。分数越高越好。作业量和延误是模拟值。","108 historical AIS rows are held out in time. Three 24-step windows are evaluated. Higher scores are better. Service and waiting metrics are simulated."),boundary:t("能碳使用洛杉矶历史数据包驱动的本地模拟。训练为 2020–2023 年，验证为 2024 年，本页回放为 2025 年。历史研究已使用这一数据包。生产执行未授权。","CarbonOps simulates a historical Los Angeles data package. Train: 2020–2023. Validation: 2024. Replay: 2025. The package has been used in earlier research. Production execution is disabled.")};
 for(const [k,v] of Object.entries(labels))el(k).textContent=v;
 el("taskTitle").textContent=t("小鸥联动任务","GullMate cross-system task");
 el("taskText").textContent=t("向本机小鸥提交只读任务。服务返回独立任务编号，可核对真实工具回执。","Submit a read-only task to the local GullMate service and inspect its tool receipts by task ID.");
 el("createTask").textContent=t("在小鸥发起复核","Start review in GullMate");
 el("feedbackText").textContent=t("对本次任务留下反馈，系统会保留关联的任务和策略编号。","Leave feedback on this task. Its task and policy identifiers are attached.");
 el("ratingTitle").textContent=t("评分 1–5","Rating 1–5");el("notesTitle").textContent=t("修正意见（可选）","Correction (optional)");
 el("sendFeedback").textContent=t("提交反馈","Submit feedback");
 options("load",[["evaluate",t("正常","Normal")],["stress",t("需求 +25%","Demand +25%")]],first?query.get("load"):undefined);
 const scene=data[el("load").value];const keys=Object.keys(scene.policies).filter(k=>!["fixed","mpc2"].includes(k));
 options("policy",keys.map(k=>[k,name(k)]),first?(query.get("policy")||"joint-17-8192"):undefined);
 options("base",["fixed","mpc2"].map(k=>[k,name(k)]),first?query.get("base"):undefined);
 options("window",scene.starts.map((v,i)=>[String(i),scene.policies.fixed.rows[i].period+" / "+v]),first?query.get("window"):undefined);
 table("ais",[t("训练种子","Training seed"),"Q-learning","Double Q","PID","SOP"],data.ais.map(r=>[r.seed,...r.scores.map(n=>num(n))]));
 el("rolesTitle").textContent=t("三岗会审记录","Three-role review record");
 el("rolesNote").textContent=t("固定案例：正常负荷第一个窗口，联合策略种子 17，对照固定规则。峰值功率上升，保留基线。","Recorded case: normal load, first window, joint seed 17 against the fixed rule. Higher peak power vetoed adoption.");
 el("roleEvidence").textContent=t("查看岗位证据与任务编号","Show evidence and task IDs");
 table("roles",[t("岗位","Role"),t("结论","Decision"),t("任务编号","Task ID")],Object.entries(data.council.reviews).map(([role,v])=>[({energy:t("能碳","Energy"),operations:t("运营","Operations"),safety:t("安全","Safety")})[role],v.receipt.decision==="veto"?t("否决","Veto"):t("通过","Pass"),v.id]));
 el("roleTrace").textContent=Object.values(data.council.reviews).map(r=>r.id+" · "+r.receipt.role+"\n"+r.report.text).join("\n\n");
 el("links").replaceChildren();for(const [url,zh,en] of data.links){const a=document.createElement("a");a.href=url;a.textContent=t(zh,en);el("links").append(a)}
 render();
}
function render(){
 const scenario=data[el("load").value], index=+el("window").value, key=el("policy").value;
 const chosen=scenario.policies[key],base=scenario.policies[el("base").value],a=chosen.rows[index],b=base.rows[index],m=a.metrics,bm=b.metrics;
 el("metrics").replaceChildren();fields.forEach((f,i)=>{const card=document.createElement("div");card.className="metric";const strong=document.createElement("strong"),small=document.createElement("small");strong.textContent=num(m[f]);small.textContent=t("基线 ","Base ")+num(bm[f]);card.append(labels()[i],strong,small);el("metrics").append(card)});
 const eligible=m.cost<bm.cost&&m.processed_teu>=bm.processed_teu-1e-6&&m.delay_minutes<=bm.delay_minutes+1e-6&&m.safety_violations===0&&m.carbon_kg<=bm.carbon_kg+1e-6&&m.peak_kw<=bm.peak_kw+1e-6&&m.ending_battery_soc>=bm.ending_battery_soc-1e-6;
 el("gate").textContent=eligible?t("本窗口可进入人工复核。","This window qualifies for human review."):t("本窗口保留基线。成本、处理量、延误、碳排、峰值、安全或期末电量有一项未达门槛。","Retain the baseline for this window. At least one cost, service, delay, carbon, peak, safety or terminal charge gate failed.");
 const hour=+el("step").value,A=a.trace[hour],B=b.trace[hour];el("stepLabel").textContent=t("回放小时 ","Replay hour ")+(hour+1)+" / 24";
 const values=[...a.trace,...b.trace].map(r=>r.cost),low=Math.floor(Math.min(...values)),high=Math.ceil(Math.max(...values));
 const y=n=>142-122*(n-low)/Math.max(1,high-low),x=i=>62+i*690/23,svg=el("chart");
 svg.setAttribute("viewBox","0 0 770 168");svg.setAttribute("aria-label",el("chartTitle").textContent);
 svg.innerHTML='<path d="M62 20V142H752" fill="none" stroke="#9baaa6"/><text x="1" y="25" class="axis">'+num(high,0)+'</text><text x="1" y="142" class="axis">'+num(low,0)+'</text><text x="61" y="164" class="axis">1 h</text><text x="722" y="164" class="axis">24 h</text>';
 for(const [rows,color] of [[b.trace,"#b07740"],[a.trace,"#08796b"]]){const pl=document.createElementNS("http://www.w3.org/2000/svg","polyline");pl.setAttribute("stroke",color);pl.setAttribute("points",rows.map((v,i)=>x(i)+","+y(v.cost)).join(" "));svg.append(pl)}
 const marker=document.createElementNS("http://www.w3.org/2000/svg","circle");marker.setAttribute("cx",x(hour));marker.setAttribute("cy",y(A.cost));marker.setAttribute("r",5);marker.setAttribute("fill","#08675c");svg.append(marker);
 el("legend").textContent=t("绿色为 ","Green: ")+name(key)+t("，棕色为 ",". Brown: ")+name(el("base").value);
 table("hourly",[t("策略","Policy"),...labels().slice(0,4),t("动作向量","Action vector")],[[name(key),num(A.cost),num(A.carbon_kg),num(A.processed_teu),num(A.delay_minutes),A.action.map(v=>num(v,2)).join(" / ")],[name(el("base").value),num(B.cost),num(B.carbon_kg),num(B.processed_teu),num(B.delay_minutes),B.action.map(v=>num(v,2)).join(" / ")]]);
 el("study").textContent=t("12 个 24 小时窗口。相同数据包与初态，规则、MPC、PPO 都在同一环境运行。","12 windows of 24 hours each. Rules, MPC and PPO use the same data, initial conditions and simulator.");
 table("summary",[t("策略","Policy"),...labels()],Object.entries(scenario.policies).map(([k,v])=>[name(k),...fields.map(f=>num(v.mean[f]))]));
 const f=data.freezes[key];table("curve",[t("训练步","Steps"),t("验证成本","Validation cost"),t("服务门槛","Service gate")],f.curve.map(row=>[row.steps,num(row.validation.cost),row.passes_service?t("通过","Pass"):t("未通过","Fail")]));
 el("identity").textContent="SHA-256 · "+f.sha256+" · "+t("数据包 ","dataset ")+scenario.dataset_sha256;
}
async function startTask(){
 if(location.origin!=="http://127.0.0.1:8010"){
  const u=new URL("http://127.0.0.1:8010/web/policy-replay.html");
  for(const key of ["load","policy","base","window"])u.searchParams.set(key,el(key).value);
  u.searchParams.set("lang",english?"en":"zh");location.href=u.href;return;
 }
 const btn=el("createTask"),state=el("taskStatus"),link=el("taskLink");btn.disabled=true;link.hidden=true;
 try{
  const call=async(path,body)=>{const r=await fetch(path,body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{});if(!r.ok)throw Error("HTTP "+r.status);return r.json()};
  const cap=await call("/api/harness/capabilities"),modern=cap.tools.some(tool=>tool.name==="policy.release");
  const k=el("policy").value.split("-"), selection={strategy:k[0],seed:+k[1],scenario:el("load").value,baseline:el("base").value,window:+el("window").value};
  const payload=modern?{goal:"调用 policy.release，从能碳服务读取已训练权重的冻结回执，比较成本、碳排、处理量、延误和风险。参数 "+JSON.stringify(selection),allowed_tools:["policy.release"],required_tools:["policy.release"]}:{goal:"并行只读观测 energy-cockpit 和 malacca-sandbox，分别说明来源、单位和风险。当前主站版本只能做状态观测，此任务不能证明已重算历史策略。",allowed_tools:["research.parallel","linked.observe"],required_tools:["research.parallel"]};
  const key="gullmate-review:"+JSON.stringify([selection,modern]);
  let requestId=sessionStorage.getItem(key);
  if(!requestId){requestId="policy-review-"+crypto.randomUUID();sessionStorage.setItem(key,requestId)}
  let task=await call("/api/harness/tasks",{...payload,driver:"model",request_id:requestId,budget:{max_steps:8,max_active_seconds:180}});
  link.href="/api/harness/tasks/"+encodeURIComponent(task.id);link.textContent=task.id;link.hidden=false;
  state.textContent=t("任务已提交，等待工具回执。","Submitted. Waiting for tool receipts.");
  for(let n=0;n<95&&["running","queued"].includes(task.status);n++){await new Promise(resolve=>setTimeout(resolve,2000));task=await call(link.pathname)}
  state.textContent=task.status+" · "+(task.final?.text||task.stop_reason||t("可从任务编号继续查看。","Open the task ID for details."));
  if(task.status==="completed"){el("feedback").hidden=false;el("feedback").dataset.task=task.id;el("feedback").dataset.policy=el("policy").value}
 }catch(e){state.textContent=t("无法取得任务回执。","Task receipt unavailable. ")+String(e.message)}finally{btn.disabled=false}
}
el("createTask").onclick=startTask;
el("feedback").onsubmit=async e=>{
 e.preventDefault();const form=el("feedback"),btn=el("sendFeedback");btn.disabled=true;
 try{
  const body=JSON.stringify({question:"策略复核 "+form.dataset.task,rating:+el("rating").value,correction:el("notes").value||null,evidence_ids:[form.dataset.task,form.dataset.policy]});
  if(form.dataset.submission!==body){form.dataset.submission=body;form.dataset.key="feedback-"+crypto.randomUUID()}
  const r=await fetch("/api/evaluation/feedback",{method:"POST",headers:{"Content-Type":"application/json","X-Idempotency-Key":form.dataset.key},body});
  if(!r.ok)throw Error("HTTP "+r.status);
  const result=await r.json();el("feedbackState").textContent=t("已登记，等待复核。","Recorded for review. ")+(result.id||result.item?.id||"");
 }catch(err){btn.disabled=false;el("feedbackState").textContent=err.message}
};
el("language").onclick=()=>{english=!english;init()};el("load").onchange=()=>init();for(const id of ["policy","base","window"])el(id).onchange=render;el("step").oninput=render;init(true);
