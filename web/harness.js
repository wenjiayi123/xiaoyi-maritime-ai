/* Task state belongs to the backend. Closing this view never cancels a task. */
window.createHarnessConsole = function ({api: callApi, openModal, escapeHtml: esc, toast, isOpen}) {
  const labels = {queued:"排队中",running:"执行中",paused:"已暂停",waiting_input:"等待补充信息",waiting_approval:"等待操作审批",completed:"已完成",partial:"部分完成",failed:"执行失败",cancelled:"已取消",budget_exceeded:"达到预算",blocked:"已阻止",needs_review:"需要核查目标"};
  let epoch=0, selection=0, current=null, catalog=null, timer=null, busy=false, events=[], cursor=0;
  let draft={mode:"enterprise",profile:"existing",goal:"读取舷鸥当前工程模拟港区快照，结合通用岸电SOP说明风险与缺失数据，不调整设备。",driver:"auto",steps:"12",seconds:"180",memory:false,template:""};
  let creationKey=null, creationBody=null, inputKey=null, inputSignature=null;
  const controllers=new Set();
  const root=()=>document.getElementById("harnessConsole");
  const visible=e=>isOpen() && (e==null || e===epoch);
  const id=()=>globalThis.crypto?.randomUUID?.() || `hx-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  async function api(path,options={}) {
    const control=new AbortController(); controllers.add(control);
    const timeout=setTimeout(()=>control.abort(),20000);
    try{return await callApi(`/api/harness${path}`,{...options,signal:control.signal,headers:{"Content-Type":"application/json",...(options.headers||{})}});}
    finally{clearTimeout(timeout);controllers.delete(control);}
  }
  function stopView(){clearTimeout(timer);timer=null;controllers.forEach(c=>c.abort());controllers.clear();}
  function capture(){const r=root();if(!r)return;draft={mode:r.querySelector("[name=harnessMode]")?.value??draft.mode,profile:r.querySelector("[name=modelProfile]")?.value??draft.profile,goal:r.querySelector("[name=goal]")?.value??draft.goal,driver:r.querySelector("[name=driver]")?.value??draft.driver,steps:r.querySelector("[name=steps]")?.value??draft.steps,seconds:r.querySelector("[name=seconds]")?.value??draft.seconds,memory:r.querySelector("[name=memory]")?.checked??draft.memory,template:r.querySelector("[name=template]")?.value??draft.template};}
  function notice(text,error=false){const n=root()?.querySelector("[data-hx-notice]");if(n){n.textContent=text;n.dataset.error=String(error);}}
  const shell=()=>`<div id="harnessConsole" class="hx-console">
    <div class="hx-intro"><strong>港航任务工作台</strong><span>计划、工具、证据和执行回执随任务保存</span></div>
    <div class="hx-template"><label>业务任务<select name="template"><option value="">自定义合同任务</option><option value="adaptive">自主任务 · 模型逐步选工具</option></select></label><p>业务模板共用一次采集的快照，显示单位、风险依据和推演假设；交接报告保留待签收项。</p></div>
    <div class="hx-compose"><label class="hx-goal">任务目标<textarea name="goal" rows="3" maxlength="4000">${esc(draft.goal)}</textarea></label>
    <div class="hx-options"><label>任务模式<select name="harnessMode"><option value="enterprise">企业受控模式</option><option value="research">RL策略研究模式</option></select></label><label>规划模型<select name="modelProfile"><option value="existing">舷鸥现有模型</option><option value="open_agent">AgentCPM开源候选</option></select></label><label>运行方式<select name="driver"><option value="auto">自动选择可用模型</option><option value="model">模型驱动</option><option value="rules">规则驱动</option></select></label><label>最多步骤<input name="steps" type="number" min="1" max="40" value="${esc(draft.steps)}"></label><label>执行预算（秒）<input name="seconds" type="number" min="5" max="1800" value="${esc(draft.seconds)}"></label><label class="hx-check"><input name="memory" type="checkbox" ${draft.memory?"checked":""}>使用我保存的偏好</label></div>
    <div class="hx-actions"><button type="button" data-hx="briefing-preset">填入联合研判演示任务</button><button type="button" data-hx="create" class="primary-button">开始任务</button><button type="button" data-hx="refresh">刷新任务</button><button type="button" data-hx="history">任务历史</button></div></div>
    <p class="hx-notice" data-hx-notice role="status" aria-live="polite">正在读取运行能力…</p>
    <section data-hx-current aria-label="当前任务"><p>提交目标后，可查看每一步实际调用与结果。</p></section>
    <section data-hx-history aria-label="任务历史"></section>
    <details class="hx-details"><summary>工具与运行能力</summary><div data-hx-capabilities></div></details>
    <details class="hx-details"><summary>我的偏好记忆</summary><p>仅保存你在这里明确输入的内容；可随时删除。</p><label>偏好内容<input name="memoryText" maxlength="1000" placeholder="例如：报告优先使用中文，并保留计量单位"></label><button type="button" data-hx="memory-save">保存偏好</button><div data-hx-memory></div></details>
    <details class="hx-details"><summary>评测与验收</summary><p>分别运行规则任务集和公开港口业务门禁，覆盖来源校验、历史规划、未来信息隔离、资源不可用和最差种子。模型自主能力另行评测。</p><button type="button" data-hx="evaluate">运行任务与港口业务评测</button><pre data-hx-evaluation></pre></details>
    <section data-hx-artifact aria-label="工具工件"></section></div>`;
  function renderTask(){
    if(!visible() || !current)return;
    const t=current, host=root()?.querySelector("[data-hx-current]");if(!host)return;
    const active=["queued","running"].includes(t.status),paused=t.status==="paused",pending=t.pending;
    const priorInput=host.querySelector("[name=steer]")?.value||"";
    host.dataset.hxTaskStatus=t.status;
    host.innerHTML=`<div class="hx-task-heading"><div><strong>${esc(labels[t.status]||t.status)}</strong><small>${esc(t.id)} · ${t.driver==="model"?`模型 ${esc(t.model||"")}`:"规则驱动"}</small></div><div class="hx-actions">${active?'<button type="button" data-hx="pause">暂停</button>':""}${paused?'<button type="button" data-hx="resume">从检查点继续</button>':""}${["queued","running","paused","waiting_input","waiting_approval"].includes(t.status)?'<button type="button" data-hx="cancel">取消任务</button>':""}<button type="button" data-hx="export">导出回执</button></div></div>
      <p>${esc(t.goal)}</p><div class="hx-usage"><span>步骤 ${t.usage.steps}/${t.budget.max_steps}</span><span>工具 ${t.usage.tool_calls}/${t.budget.max_tool_calls}</span><span>Token ${t.usage.tokens}${t.usage.tokens_estimated?"（估算）":""}/${t.budget.max_tokens}</span><span>执行 ${Number(t.usage.active_seconds).toFixed(1)}/${t.budget.max_active_seconds}s</span></div>
      ${t.plan.length?`<ol class="hx-plan">${t.plan.map(s=>`<li>${esc(s)}</li>`).join("")}</ol>`:""}
      ${t.status==="waiting_input"?`<p class="hx-question">${esc(t.question)}</p>`:""}
      ${t.status==="needs_review"&&t.inflight?.id?`<div class="hx-approval"><strong>未决操作需要核查</strong><p>调用 ${esc(t.inflight.id)} · ${esc(t.inflight.tool)}</p><p>关联回执：${esc(t.inflight.linked_run_id||"将按操作编号查找")}</p><button type="button" data-hx="reconcile">读取关联回执核查</button></div>`:""}
      ${t.status==="waiting_approval"&&pending?`<div class="hx-approval"><strong>请审阅本次具体操作</strong><p>${esc(pending.prepared?.label||pending.action.tool)}</p><pre>${esc(JSON.stringify(pending.action.arguments,null,2))}</pre><p>审批有效至 ${esc(new Date(pending.expires_epoch*1000).toLocaleTimeString())}；摘要 ${esc(pending.action_sha256.slice(0,16))}</p><div class="hx-actions"><button type="button" data-hx="approve">批准本次操作</button><button type="button" data-hx="reject">拒绝执行</button></div></div>`:""}
      ${["queued","running","waiting_input","waiting_approval","paused"].includes(t.status)?`<label>补充信息或约束<textarea name="steer" rows="2" maxlength="4000" placeholder="运行中补充约束会使尚未执行的旧决策失效">${esc(priorInput)}</textarea></label><button type="button" data-hx="input">提交补充信息</button>`:""}
      ${recoveryView(t)}
      <div class="hx-results">${t.results.map(r=>`<details><summary>${esc(r.id)} · ${esc(r.tool)} · ${r.ok?"已返回":r.resolved_by?"已由 "+esc(r.resolved_by)+" 恢复":"调用失败"} · ${Number(r.elapsed_ms).toFixed(0)}ms</summary><pre>${esc(r.summary)}</pre><button type="button" data-hx="artifact" data-name="${esc(r.artifact)}">查看完整工具结果</button></details>`).join("")}</div>
      ${t.final?`<div class="hx-final"><strong>任务结果</strong>${t.final.synthesis?.notice?`<p>${esc(t.final.synthesis.notice)}</p>`:""}<pre>${esc(t.final.text)}</pre><p>${esc(t.final.data_notice)}</p><small>有效工具引用：${esc(t.final.evidence_ids.join("、"))}</small></div>`:""}
      ${t.stop_reason?`<p class="hx-stop">${esc(t.stop_reason)}</p>`:""}
      <details data-hx-trace><summary>执行轨迹（${events.length} 项已读取）</summary><ol class="hx-events">${events.slice(-50).map(e=>`<li><time>${esc(new Date(e.at).toLocaleTimeString())}</time> ${esc(e.event)} · ${esc(labels[e.status]||e.status)}</li>`).join("")}</ol></details>`;
    setBusy(busy);
  }
  function recoveryView(t){
    const attempts=t.source_recoveries||[];
    if(!attempts.length)return "";
    const fmt=(x)=>Number(x||0).toLocaleString();
    return `<section class="hx-recovery"><h3>恢复记录 / Recovery</h3>${attempts.map(a=>{
      const failure=t.results.find(r=>r.id===a.failed_id);
      const old=a.usage,newUsage=t.usage;
      return `<p><b>${esc(a.failed_id)} → ${esc(failure?.resolved_by||"待回执 / Pending")}</b> · ${esc(a.source)}</p>
      <p>恢复前已留存 / Retained: ${a.retained.map(r=>esc(r.id)).join(", ")||"—"}</p>
      <p>模型 tokens ${fmt(old.tokens)} → ${fmt(newUsage.tokens)} (+${fmt(newUsage.tokens-old.tokens)}) · 工具调用 / Tool calls ${fmt(old.tool_calls)} → ${fmt(newUsage.tool_calls)} (+${fmt(newUsage.tool_calls-old.tool_calls)})</p>`;
    }).join("")}${t.driver==="model"&&t.model_local===true?"<p>推理用量来自本机模型 / Local model inference.</p>":""}</section>`;
  }

  function setBusy(value){busy=value;root()?.querySelectorAll("button[data-hx]").forEach(b=>b.disabled=value);}
  function domainView(data){
    if(!data||typeof data!=="object")return "";
    const gate=data.readiness;
    const scenarioName=id=>({normal:"常态",vessel_surge:"集中到港",equipment_failure:"设备故障",energy_peak:"需量高峰",storm:"大风"}[id]||id);
    const status=gate?`<p class="hx-domain-status">检查时数据通过：${gate.analysis_usable?"是":"否，先核查数据"} · 当时数据年龄 ${esc(gate.age_seconds??"未知")} 秒 · 现场放行：关闭${gate.assessed_at?`<br>检查时间：${esc(new Date(gate.assessed_at).toLocaleString())}`:""}</p>`:"";
    const table=(headers,rows)=>`<div class="hx-table-scroll"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(cell=>`<td>${esc(cell??"缺失")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    if(Array.isArray(data.rows)){
      const metrics=data.rows.some(r=>"metric_id" in r);
      const columns=metrics?["label","value","unit","source_path"]:Object.keys(data.rows[0]||{});
      return status+table(metrics?["指标","值","单位","来源字段"]:columns,data.rows.map(row=>columns.map(k=>row[k])))+`<p>匹配 ${esc(data.matched_count)} 条${data.truncated?"，当前为截取页":""}；快照 ${esc(data.snapshot_sha256)}</p>`;
    }
    if(Array.isArray(data.findings))return status+`<p>建议状态：${esc(data.recommendation_status)}；工程筛查阈值不替代港区制度。</p>`+table(["规则","专业域","等级","观测值","工程阈值","核查事项"],data.findings.map(r=>[r.rule_id,r.domain,r.severity,r.observed_value,r.threshold,r.message]));
    if(Array.isArray(data.branches))return `<p>同一基线的末时点对比 · ${esc(data.horizon_minutes)} 分钟情景采样；未修改当前系统。</p>`+table(["情景","电网需量 kW","相对基线 kW","低电量AGV 台","风速 m/s","最小UKC m"],data.branches.map(b=>{const m=b.points.at(-1).metrics;return [scenarioName(b.scenario),m.grid_demand,b.delta_vs_baseline.grid_demand,m.low_soc_agv,m.wind_speed,m.minimum_ukc];}))+`<p>大风下负荷下降可能来自作业受限，不能据此判为更优的节能策略。</p><ul>${(data.assumptions||[]).map(s=>`<li>${esc(s)}</li>`).join("")}</ul><p>基线 ${esc(data.snapshot_sha256)}</p>`;
    if(typeof data.markdown==="string")return status+`<p>交接草稿，待责任人、截止时间与接收人签收。</p><pre>${esc(data.markdown)}</pre>`;
    return "";
  }
  async function refresh(){
    if(!current||!visible())return;
    const e=epoch,s=selection,taskId=current.id;
    const [t,log]=await Promise.all([api(`/tasks/${encodeURIComponent(taskId)}`),api(`/tasks/${encodeURIComponent(taskId)}/events?after=${cursor}`)]);
    if(!visible(e)||s!==selection||current?.id!==taskId)return;
    if(t.version>=current.version)current=t;
    for(const event of log.items||[]){if(event.seq>cursor){events.push(event);cursor=event.seq;}}
    renderTask();
    if(["running","queued"].includes(current.status))schedulePoll();
  }
  function schedulePoll(){clearTimeout(timer);timer=setTimeout(async()=>{if(!visible())return;try{await refresh();}catch(error){if(visible())notice(`任务状态读取失败：${error.message}。可刷新重试；不要重复创建同一操作。`,true);}},1000);}
  async function history(){const e=epoch;const data=await api("/tasks");if(!visible(e))return;root().querySelector("[data-hx-history]").innerHTML=`<h3>任务历史</h3>${data.items.length?data.items.map(t=>`<button type="button" data-hx="select" data-task="${esc(t.id)}" class="hx-history-item"><span>${esc(t.goal.slice(0,70))}</span><small>${esc(labels[t.status]||t.status)} · ${esc(t.driver)}</small></button>`).join(""):"<p>暂无任务</p>"}`;}
  async function select(taskId){const e=epoch,s=++selection;clearTimeout(timer);const t=await api(`/tasks/${encodeURIComponent(taskId)}`);if(!visible(e)||s!==selection)return;current=t;events=[];cursor=0;await refresh();}
  async function memory(){const e=epoch;const data=await api("/memory");if(!visible(e))return;root().querySelector("[data-hx-memory]").innerHTML=data.items.map(m=>`<div class="hx-memory"><span>${esc(m.text)}</span><button type="button" data-hx="memory-delete" data-memory="${esc(m.id)}">删除</button></div>`).join("")||"<p>尚未保存偏好。</p>";}
  async function handle(button){
    const action=button.dataset.hx,e=epoch;if(busy)return;
    setBusy(true);
    try{
      if(action==="briefing-preset"){
        if(!catalog)throw new Error("能力目录尚未就绪，请稍后重试。");
        const select=root().querySelector("[name=template]");select.value="port-briefing";select.dispatchEvent(new Event("change",{bubbles:true}));
        root().querySelector("[name=driver]").value="rules";capture();root().dataset.hxPreset="port-briefing";
        notice("已填入规则驱动的多工具联合研判：同一快照、风险、分支推演与交接。模型自主调用在能力实证中单独展示。");
      }else if(action==="create"){
        capture();const steps=Number(draft.steps),seconds=Number(draft.seconds);
        if(!draft.goal.trim()||!draft.steps.trim()||!draft.seconds.trim()||!Number.isInteger(steps)||steps<1||steps>40||!Number.isFinite(seconds)||seconds<5||seconds>1800)throw new Error("请填写任务目标及有效的步骤和执行预算。");
        const body={goal:draft.goal.trim(),driver:draft.driver,mode:draft.mode,model_profile:draft.profile,use_memory:draft.memory,budget:{max_steps:steps,max_active_seconds:seconds}};
        if(draft.template==="adaptive"){body.planning_mode="adaptive";body.driver="model";body.required_tools=[];body.budget.max_tokens=48000;}else if(draft.template)body.template_id=draft.template;
        notice(current?"正在提交新任务，收到回执前保留上一任务结果。":"正在提交任务，等待后端接收回执。");
        const signature=JSON.stringify(body);if(signature!==creationBody){creationKey=id();creationBody=signature;}
        const t=await api("/tasks",{method:"POST",body:JSON.stringify({...body,request_id:creationKey})});
        if(!visible(e))return;current=t;selection++;events=[];cursor=0;creationKey=null;creationBody=null;notice("任务已由后端接收，关闭面板后仍保留进度。");await refresh();
      }else if(action==="history")await history();
      else if(action==="select")await select(button.dataset.task);
      else if(action==="refresh"){if(current)await refresh();else await history();}
      else if(["pause","resume","cancel"].includes(action)&&current){const taskId=current.id;const t=await api(`/tasks/${taskId}/control/${action}`,{method:"POST"});if(visible(e)&&current?.id===taskId){current=t;renderTask();notice(action==="resume"?"任务已从检查点继续。":t.status==="running"?`${action==="pause"?"暂停":"取消"}请求已接收；正在等待当前调用到达安全边界。`:`任务${labels[t.status]||t.status}。`);if(["running","queued"].includes(t.status))schedulePoll();}}
      else if(["approve","reject"].includes(action)&&current?.pending){const taskId=current.id,p=current.pending;const t=await api(`/tasks/${taskId}/approval`,{method:"POST",body:JSON.stringify({approval_id:p.id,action_sha256:p.action_sha256,approve:action==="approve"})});if(visible(e)&&current?.id===taskId){current=t;renderTask();schedulePoll();}}
      else if(action==="input"&&current){const text=root().querySelector("[name=steer]")?.value.trim();if(!text)throw new Error("请填写补充信息。");const signature=JSON.stringify([current.id,text]);if(signature!==inputSignature){inputKey=id();inputSignature=signature;}const taskId=current.id;const t=await api(`/tasks/${taskId}/inputs`,{method:"POST",body:JSON.stringify({text,request_id:inputKey})});inputKey=null;inputSignature=null;if(visible(e)&&current?.id===taskId){current=t;const input=root().querySelector("[name=steer]");if(input)input.value="";renderTask();schedulePoll();}}
      else if(action==="reconcile"&&current){const taskId=current.id;const t=await api(`/tasks/${taskId}/reconcile`,{method:"POST"});if(visible(e)&&current?.id===taskId){current=t;renderTask();}}
      else if(action==="export"&&current){const data=await api(`/tasks/${current.id}/export`);if(!visible(e))return;const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});const url=URL.createObjectURL(blob);const link=document.createElement("a");link.href=url;link.download=`${data.task.id}-receipt.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);root().dataset.hxExportValid=String(data.integrity.event_chain_valid);notice(`回执已导出；事件链校验：${data.integrity.event_chain_valid?"通过":"失败"}。`);}
      else if(action==="artifact"&&current){const data=await api(`/tasks/${current.id}/artifacts/${encodeURIComponent(button.dataset.name)}`);if(visible(e)){let parsed=null;try{parsed=JSON.parse(data.content);}catch{}const view=domainView(parsed);root().querySelector("[data-hx-artifact]").innerHTML=`<h3>${esc(data.name)}</h3>${view}${view?`<details><summary>完整原始JSON</summary><pre>${esc(data.content)}</pre></details>`:`<pre>${esc(data.content)}</pre>`}`;}}
      else if(action==="memory-save"){const text=root().querySelector("[name=memoryText]")?.value.trim();if(!text)throw new Error("请输入要明确保存的偏好。");await api("/memory",{method:"POST",body:JSON.stringify({text})});if(visible(e)){root().querySelector("[name=memoryText]").value="";await memory();}}
      else if(action==="memory-delete"){await api(`/memory/${encodeURIComponent(button.dataset.memory)}`,{method:"DELETE"});await memory();}
      else if(action==="evaluate"){const data=await api("/evaluation",{method:"POST"});if(visible(e))root().querySelector("[data-hx-evaluation]").textContent=JSON.stringify(data,null,2);}
    }catch(error){if(visible(e))notice(error.message,true);}
    finally{if(visible(e))setBusy(false);}
  }
  async function open(){
    capture();stopView();const e=++epoch;busy=false;
    openModal("Harness 任务工作台","受控执行 · 可恢复进度 · 工具与证据回执",shell(),"","harness");
    root().querySelector("[name=driver]").value=draft.driver;root().querySelector("[name=harnessMode]").value=draft.mode;root().querySelector("[name=modelProfile]").value=draft.profile;
    root().addEventListener("click",event=>{const b=event.target.closest("button[data-hx]");if(b&&root()?.contains(b))handle(b);});
    root().addEventListener("change",event=>{if(event.target.name!=="template")return;const t=[...(catalog?.maritime?.templates||[]),...(catalog?.dual_templates||[])].find(t=>t.id===event.target.value);draft.template=event.target.value;if(draft.template==="adaptive"){root().querySelector("[name=driver]").value="model";root().querySelector("[name=seconds]").value="900";root().querySelector("[name=steps]").value="18";notice("模型自行选择工具和次序，按实际结果调整；修改模拟状态需审批。无模型时明确失败，不回退固定流程。");}if(t){root().querySelector("[name=harnessMode]").value=t.mode||"enterprise";root().querySelector("[name=goal]").value=t.goal;root().querySelector("[name=seconds]").value=String(t.seconds);capture();notice(`已选择业务任务，模板token预算 ${t.max_tokens}。${t.delivery_mode==="verified_business_report"?"正式交接由已核验工件整理，模型负责工具决策。":""}点击开始任务后执行。`);}});
    root().querySelector("[name=goal]").addEventListener("input",()=>{if(draft.template!=="adaptive"){draft.template="";root().querySelector("[name=template]").value="";}});
    try{
      const data=await api("/capabilities");if(!visible(e))return;catalog=data;
      const templateSelect=root().querySelector("[name=template]");templateSelect.innerHTML=`<option value="">自定义合同任务</option><option value="adaptive">自主任务 · 模型逐步选工具</option>${[...(data.maritime?.templates||[]),...(data.dual_templates||[])].map(t=>`<option value="${esc(t.id)}">${esc(t.name)}</option>`).join("")}`;templateSelect.value=draft.template;
      root().querySelector("[data-hx-capabilities]").innerHTML=`<p>${data.drivers.model?`模型配置：${esc(data.drivers.model_name)}`:"当前未配置任务模型，自动模式使用明确标识的规则运行。"}</p>${data.runtime?`<p>运行版本：${esc(data.runtime.release)} · ${esc(data.runtime.loaded_sha256.slice(0,12))}${data.runtime.restart_required?" · 代码已更新，需重启":" · 与磁盘版本一致"}</p><p>统一入口：${esc(data.runtime.canonical_url||location.origin)}</p>`:""}<p>${esc(data.execution_environment)}</p><ul>${data.tools.map(t=>`<li><code>${esc(t.name)}</code>：${esc(t.description)}${t.requires_approval?"（需审批）":""}</li>`).join("")}</ul>`;
      notice(`已登记 ${data.tools.length} 项当前身份可用工具；生产控制权限关闭。`);
      await Promise.all([history(),memory()]);if(current)await refresh();
    }catch(error){if(visible(e))notice(`读取失败：${error.message}。关闭后可重新打开。`,true);}
  }
  const observer=new MutationObserver(()=>{if(!isOpen()){capture();stopView();epoch++;}});
  observer.observe(document.getElementById("genericModal"),{attributes:true,attributeFilter:["hidden","data-kind"]});
  return {open};
};
