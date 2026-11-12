const el=id=>document.getElementById(id);
let rows=[],ticket=null,timer=null,submitting=false,polling=false;
const states={completed:"已交付",blocked:"核验拦截",failed:"执行失败",partial:"部分交付",queued:"已排队",running:"执行中",paused:"已暂停",waiting_input:"等待补充",budget_exceeded:"预算已用尽",cancelled:"已取消"};
const names={"forecast.port_load":"读取日前负荷预测","dispatch.tariff_week":"读取储能调度周账单","evidence.match_scope":"按两份原件核对范围","systems.inspect":"读取业务系统资源"};
const labels={real_local_14b:"本机 14B 原生调用",free_tool_choice:"未预设必选工具",planned_before_calls:"模型先列计划",delivered:"实际交付",no_production:"现场控制边界",requested_forecast:"所问日期及来源的预测",requested_dispatch:"所问周及工况的账单",used_scope_comparison:"实际引用两份原件对账",cited_comparison:"交付引用对账工件",peak_kw:"交付的日峰数值",correct_bill:"交付的账单数值",cost_direction:"费用增减方向",disclosed_mismatch:"说明口径或日期不匹配",no_frozen_peer:"区分在线复算与冻结回执",fallback_disclosed:"说明待机回退",actual_coverage:"真实孪生覆盖资料",actual_carbonops_forecast:"真实能碳预测",cited_sources:"引用两个系统",coverage_fact:"覆盖项数及比例",forecast_fact:"模型或预测数值",all_horizons:"预测时距与场景总数"};
const make=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
async function verified(){
 const res=await fetch("./runs.json",{cache:"no-store"});if(!res.ok)throw Error("工单回执未读取");
 const b=await res.arrayBuffer(),d=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",b)),v=>v.toString(16).padStart(2,"0")).join("");
 if(d!=="e098404ed2f1bbff36575d694c9e50038f07e639dd951d846373267fe703e913")throw Error("工单回执指纹不符");return JSON.parse(new TextDecoder().decode(b));
}
function show(){
 const r=rows[el("pick").selectedIndex];el("question").textContent=r.input;el("lane").textContent=r.lane+" · "+r.model;
 el("verdict").className=r.passed?"ok":"failed";el("verdict").textContent=(states[r.status]||r.status)+" · "+(r.passed?"独立内容复核通过":"独立内容复核未通过");
 el("answer").textContent=r.answer||r.stop_reason||"未取得最终答复";el("basis").textContent=r.citations.length?"最终引用 "+r.citations.join("、"):"没有已交付的引用。";
 el("plans").replaceChildren(...r.plans.map((steps,i)=>{const box=make("details",""),title=make("summary",(i?"修订计划":"初始计划")+" · "+steps.length+" 步");box.open=i===0;const list=make("ol","");list.append(...steps.map(s=>make("li",s)));box.append(title,list);return box;}));
 el("traces").replaceChildren(...r.traces.map(t=>{const d=make("details",""),h=make("summary",t.id+" · "+(names[t.tool]||t.tool)+" · "+(t.success?"成功":t.resolved_by?"失败，已由 "+t.resolved_by+" 恢复":"失败"));d.append(h,make("pre",JSON.stringify(t.arguments,null,2)+"\nSHA-256  "+t.hash));return d;}));
 el("checks").replaceChildren(...Object.entries(r.checks).map(([k,v])=>make("li",(v?"通过　":"未通过　")+(labels[k]||k))));
 el("id").textContent=r.id+" · "+r.run;el("record").hidden=false;
}
function display(t){
 el("out").hidden=false;el("stage").textContent=t.id+" · "+(states[t.status]||t.status);
 el("actions").replaceChildren(...(t.plan||[]).map(s=>make("li",s)),...(t.results||[]).map(r=>make("li",r.id+"  "+r.tool+"  "+(r.ok?"已取得回执":"未取得回执"))));
 el("latest").textContent=t.final?.text||t.stop_reason||t.question||"";el("export").href="/api/harness/tasks/"+encodeURIComponent(t.id)+"/export";
}
async function request(url,init){const response=await fetch(url,{cache:"no-store",...init});if(!response.ok)throw Error("小鸥接口 HTTP "+response.status);return response.json();}
const stash="gullmate.readonly-orders.v1";
function save(t){ticket=t;try{if(t)sessionStorage.setItem(stash,JSON.stringify(t));else sessionStorage.removeItem(stash);}catch{}}
function stop(){clearTimeout(timer);timer=null;}
async function poll(){
 if(polling||!ticket?.id||document.hidden||el("compose").hidden)return;
 const current=ticket.id;polling=true;stop();
 try{const t=await request("/api/harness/tasks/"+encodeURIComponent(current));if(ticket?.id!==current)return;display(t);
   if(["queued","running"].includes(t.status))timer=setTimeout(poll,1800);
 }catch(e){el("message").textContent=e.message+"，可稍后重新打开本页核对。";}finally{polling=false;}
}
function mode(isReview){
 el("review").hidden=!isReview;el("compose").hidden=isReview;el("reviewTab").setAttribute("aria-pressed",isReview);el("runTab").setAttribute("aria-pressed",!isReview);
 if(isReview)stop();else poll();
}
async function submit(){
 if(submitting)return;
 const goal=el("goal").value.trim();if(goal.length<2){el("message").textContent="请填写业务问题。";return;}
 if(ticket?.id&&ticket.goal===goal){el("message").textContent="已提交，读回同一工单。";await poll();return;}
 submitting=true;el("send").disabled=true;el("local").hidden=true;el("example").textContent="";
 try{
   const caps=await request("/api/harness/capabilities");
   const domain=/日前|独立日峰|电价.{0,8}(?:识别|工况|延后|提前|账单)|对账/.test(goal);
   const allowed=domain?["forecast.port_load","dispatch.tariff_week","evidence.match_scope","systems.inspect","calculate","policy.shore_storage"]:["systems.inspect","linked.observe","calculate","knowledge.search"];
   const registered=new Set(caps.tools.map(x=>x.name));
   if(allowed.some(n=>!registered.has(n))){
      el("message").textContent="尚未提交。";el("local").hidden=false;
      const quoted=goal.replaceAll("'","''");
      el("example").textContent="PowerShell\n& 'G:\\AI\\WindowsDeploy\\portai.cmd' order run ops-"+crypto.randomUUID().slice(0,8)+" '"+quoted+"'";return;
   }
   if(!ticket||ticket.goal!==goal)save({key:"ops-web-"+crypto.randomUUID(),goal});
   const result=await request("/api/harness/tasks",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({
      goal,request_id:ticket.key,planning_mode:"adaptive",driver:"model",allowed_tools:allowed,required_tools:[],skills:["maritime-evidence"],use_memory:false,
      budget:{max_steps:18,max_tool_calls:12,max_tokens:90000,max_active_seconds:900,context_chars:15500}})});
   if(!/^ht-[a-f0-9]{32}$/.test(result.id)||result.request_id!==ticket.key)throw Error("工单回执身份不符");
   save({...ticket,id:result.id});el("message").textContent="已提交到常驻小鸥任务中心。";display(result);await poll();
 }catch(e){el("message").textContent=e.message+"。重试相同问题将使用同一请求编号。";}finally{submitting=false;el("send").disabled=false;}
}
el("reviewTab").onclick=()=>mode(true);el("runTab").onclick=()=>mode(false);el("send").onclick=submit;el("clear").onclick=()=>{
 if(submitting)return;stop();save(null);el("out").hidden=true;el("local").hidden=true;el("example").textContent="";el("message").textContent="可提交新的工单。";
};
try{const old=JSON.parse(sessionStorage.getItem(stash)||"null");if(old&&typeof old.goal==="string"&&/^ops-web-[a-f0-9-]{36}$/.test(old.key)&&(!old.id||/^ht-[a-f0-9]{32}$/.test(old.id))){ticket=old;el("goal").value=old.goal;}}catch{}
document.addEventListener("visibilitychange",()=>{if(document.hidden)stop();else poll();});window.addEventListener("pagehide",stop);
try{rows=await verified();el("pick").replaceChildren(...rows.map(r=>new Option(r.title)));el("pick").onchange=show;show();}
catch(e){el("record").hidden=true;el("error").textContent=e.message;}
