/* Local adapter jobs are executed and verified by the backend, never by DOM claims. */
window.createLinkedAgent = function ({api: callApi, openModal, escapeHtml: esc, toast, isOpen}) {
  const api = (path, options={}) => callApi(path,{...options,headers:{"Content-Type":"application/json",...(options.headers || {})}});
  let actions = [], selected = "energy.compare", plan = null, run = null, busy = false;
  let openVersion = 0, draftVersion = 0, requestVersion = 0;
  let draft = {command:"", parameters:{}, samples:"3", interval:"2", restore:true};
  const executionRequests = new Map();
  const working = () => busy || run?.status === "running";
  const visible = version => isOpen() && (version == null || version === openVersion);
  const labels = {aggregate_kw:"聚合功率 kW", queue_vessels:"排队船舶数", delay_minutes:"延误分钟", throughput_teu:"吞吐 TEU", energy_kwh:"能耗 kWh", peak_grid_kw:"电网峰值 kW", cost_myr:"成本 MYR", carbon_tons:"碳排放 t", service_level_percent:"服务率 %", safety_risk_percent:"安全风险 %", resilience_index:"韧性指标", carbon_kg:"碳排放 kg", cost_cny:"成本 CNY", grid_peak_kw:"电网峰值 kW", service_fulfilment_pct:"服务完成率 %", total_cost_saving_cny:"试算成本节省 CNY", abatement_ton:"试算减排 t", green_preference:"绿色偏好", energy_mwh:"能耗 MWh"};
  const statuses = {running:"执行与观测中", completed:"已完成", failed:"失败，未确认变更", needs_review:"需要核查目标状态", cancelled:"已停止观测"};
  Object.assign(labels,{equipment_life_cost_cny:"设备寿命成本 CNY",safety_violations:"安全约束违规次数"});
  const fmt = v => typeof v === "number" ? Number(v.toFixed(3)).toLocaleString("zh-CN") : String(v ?? "—");
  function summarize(result) {
    const lines=[`${result.plan.label}：${statuses[result.status] || result.status}。`,`本次参数：${JSON.stringify(result.plan.parameters)}。`];
    const evaluation=result.evaluation;
    if(evaluation) {
      lines.push(evaluation.scope);
      if(evaluation.changes) evaluation.changes.forEach(row=>lines.push(`${labels[row.metric] || row.metric}：${fmt(row.before)} → ${fmt(row.after)}（变化 ${fmt(row.change)}）。`));
      else lines.push(`评估点 ${evaluation.points?.length || 0}；平均功率 ${fmt(evaluation.average_kw)} kW；峰值 ${fmt(evaluation.peak_kw)} kW。`);
    }
    lines.push(`已完成 ${(result.observations || []).length} 次接口观测。${result.comparison_notice}`);
    (result.changes || []).slice(0,8).forEach(row=>lines.push(`${labels[row.metric] || row.metric}：${fmt(row.before)} → ${fmt(row.after)}。`));
    if(result.plan.mutates) lines.push(result.restored ? "本轮调整已执行；原配置已恢复并通过目标回读核验。" : result.applied ? "目标保留本轮配置，可在操作台恢复；不会倒放已发生的模拟业务时间。" : result.write_attempted ? "写入结果尚未核验，请根据回执核查目标配置。" : "本轮未变更目标配置。");
    lines.push(`回执：${result.id}。操作历史可查看参数、前后快照并导出完整回执。当前结果来自本机模拟或公开数据模型，生产权限关闭。`);
    return lines.join("\n\n");
  }
  const spec = () => actions.find(item => item.id === selected);
  function defaultParameters() {
    return Object.fromEntries(Object.entries(spec()?.parameters || {}).map(([key,p])=>[key,String(p.default ?? "")]));
  }
  function usePlan(prepared) {
    selected=prepared.action_id;
    draft.parameters={...defaultParameters(),...prepared.parameters};
    draft.samples=String(prepared.samples); draft.interval=String(prepared.interval_seconds);
    draft.restore=prepared.restore_after_observation;
  }
  function invalidatePlan() {
    draftVersion++; requestVersion++; plan=null;
    const host=visible() && document.querySelector("#laPlan");
    if(host) host.textContent="参数已修改，请重新预览。";
  }
  function syncControls() {
    if(!visible()) return;
    document.querySelectorAll("[data-la-preview],[data-la-parse],[data-la-execute],[data-la-history],#laAction,[data-la-param],#laSamples,#laInterval,#laRestore,#laCommand").forEach(control=>control.disabled=working());
  }
  const table = rows => `<div class="la-table-wrap"><table class="la-table"><thead><tr><th>指标</th><th>之前</th><th>之后</th><th>变化</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(labels[r.metric] || r.metric)}</td><td>${esc(fmt(r.before))}</td><td>${esc(fmt(r.after))}</td><td>${esc(fmt(r.change))}</td></tr>`).join("")}</tbody></table></div>`;
  function fields() {
    return Object.entries(spec()?.parameters || {}).map(([key,p])=>`<label>${esc(p.title || key)}${p.enum ? `<select data-la-param="${esc(key)}">${p.enum.map((v,i)=>`<option value="${esc(String(v))}" ${String(v) === String(draft.parameters[key] ?? p.default) ? "selected" : ""}>${esc(p.enumNames?.[i] || v)}</option>`).join("")}</select>` : `<input data-la-param="${esc(key)}" type="number" value="${esc(String(draft.parameters[key] ?? p.default ?? ""))}" ${p.minimum == null ? "" : `min="${p.minimum}"`} ${p.maximum == null ? "" : `max="${p.maximum}"`} step="${p.type === "integer" ? "1" : "any"}">`}<small>${esc(p.description || "参数按目标接口登记范围校验")}</small></label>`).join("");
  }
  function chart(observations) {
    if (observations.length < 2) return "";
    const key = Object.keys(observations[0].metrics || {})[0];
    const values = observations.map(o=>o.metrics[key]);
    if (!key || values.some(v=>!Number.isFinite(v))) return "";
    const low = Math.min(...values), high = Math.max(...values), span = Math.max(high-low,1);
    const points = values.map((v,i)=>`${20+i*540/(values.length-1)},${88-(v-low)/span*65}`).join(" ");
    return `<figure class="la-chart"><figcaption>${esc(labels[key] || key)} · ${values.length} 次真实接口采样 · ${esc(fmt(values[0]))} → ${esc(fmt(values.at(-1)))}</figcaption><svg viewBox="0 0 580 110" role="img" aria-label="${esc(labels[key] || key)}的本次观测序列"><path d="M20 10V90H565" fill="none" stroke="#375d7a"/><polyline points="${points}" fill="none" stroke="#72dce6" stroke-width="2"/></svg></figure>`;
  }
  function receipt() {
    if (!run) return "";
    const evaluation = run.evaluation;
    const samples = run.observations || [];
    return `<section class="la-receipt"><header><strong>${esc(statuses[run.status] || run.status)}</strong><span>${samples.length}/${run.plan.samples} 次采样</span></header><p>${esc(run.plan.label)} · ${esc(run.id)}</p>
      ${run.error ? `<p class="la-warning">${esc(run.error)}</p>` : ""}
      ${run.restore_error ? `<p class="la-warning">${esc(run.restore_error)}</p>` : ""}
      ${run.plan.mutates ? `<p>目标配置：${run.restored ? "已恢复并回读核验" : run.applied ? "已调整并回读核验" : run.write_attempted ? "请求已发出，结果需核查" : "尚未变更"}</p>` : ""}
      ${evaluation ? `<h4>计算结果</h4><p>${esc(evaluation.scope)}</p>${evaluation.changes ? table(evaluation.changes) : `<p>评估点 ${evaluation.points?.length || 0} · 平均功率 ${esc(fmt(evaluation.average_kw))} kW · 峰值 ${esc(fmt(evaluation.peak_kw))} kW</p>`}` : ""}
      <h4>运行状态观测</h4><p>${esc(run.comparison_notice)}</p>${chart(samples)}${table(run.changes || [])}
      <details><summary>参数、前后快照与哈希回执</summary><pre>${esc(JSON.stringify(run,null,2))}</pre></details>
      <div class="la-buttons">${run.status === "running" ? `<button type="button" class="outline-button" data-la-cancel="${esc(run.id)}">停止观测</button>` : ""}${run.applied && !run.restored && run.status !== "running" ? `<button type="button" class="outline-button" data-la-rollback="${esc(run.id)}">恢复本轮配置</button>` : ""}<button type="button" class="outline-button" data-la-refresh="${esc(run.id)}">刷新回执</button><button type="button" class="outline-button" data-la-export>导出完整回执</button></div></section>`;
  }
  function render() {
    if (!isOpen()) return;
    const root = document.querySelector("#modalBody");
    root.innerHTML = `<div class="linked-agent-console"><p class="la-intro">先读取目标状态，再执行登记操作并观测。参数试算作用于本次计算；模拟配置调整会改变目标沙盘。默认观测后恢复本轮配置。</p>
      <div class="la-command"><input id="laCommand" value="${esc(draft.command)}" placeholder="例如：能碳绿色偏好调到0.8，碳价100，进行对比试算"><button class="outline-button" type="button" data-la-parse>解析指令</button></div>
      <label>操作能力<select id="laAction" ${busy ? "disabled" : ""}>${actions.map(a=>`<option value="${esc(a.id)}" ${selected===a.id ? "selected" : ""}>${esc(a.label)}${a.mutates ? " · 调整模拟配置" : " · 读取/试算"}</option>`).join("")}</select></label>
      <div class="la-fields">${fields()}<label>观测次数<input id="laSamples" type="number" min="1" max="12" value="${esc(draft.samples)}"></label><label>间隔（秒）<input id="laInterval" type="number" min="1" max="10" step="1" value="${esc(draft.interval)}"></label></div>
      ${spec()?.mutates ? `<label class="la-checkbox"><input id="laRestore" type="checkbox" ${draft.restore ? "checked" : ""}>观测结束或停止后，恢复本轮模拟配置</label>` : ""}
      <div class="la-buttons"><button type="button" class="primary-button" data-la-preview ${busy ? "disabled" : ""}>读取状态并预览方案</button><button type="button" class="outline-button" data-la-history>操作历史</button></div>
      <div id="laPlan">${plan ? planMarkup() : ""}</div><div id="laReceipt">${receipt()}</div></div>`;
    syncControls();
  }
  function planMarkup() {
    return `<section class="la-plan"><h4>${esc(plan.label)} · 方案预览</h4><p>目标：${esc(plan.target)} · ${plan.samples} 次观测，每 ${plan.interval_seconds} 秒一次</p><pre>${esc(JSON.stringify({当前配置:plan.before.config,本次参数:plan.parameters,观测后恢复:plan.mutates ? plan.restore_after_observation : "无全局配置变更"},null,2))}</pre><p>来源：${esc(plan.before.source)} · 读取时间：${esc(plan.before.observed_at)}</p><small>方案有效期 5 分钟 · ${esc(plan.plan_sha256.slice(0,16))}</small><button type="button" class="primary-button" data-la-execute ${busy ? "disabled" : ""}>${plan.mutates ? "执行本轮模拟调整" : "开始试算与观测"}</button></section>`;
  }
  function updateRun() {
    if (isOpen() && document.querySelector("#laReceipt")) document.querySelector("#laReceipt").innerHTML = receipt();
    syncControls();
  }
  function revealReceipt() {
    if(visible()) document.querySelector("#laReceipt")?.scrollIntoView?.({block:"start",behavior:"smooth"});
  }
  function acceptRun(latest) {
    if(run?.id !== latest.id) return;
    // A slower refresh must not roll a verified terminal receipt back to running.
    if(run.status !== "running" && latest.status === "running") return;
    if(run.restored && !latest.restored) return;
    run=latest; updateRun();
  }
  async function open(command) {
    const version=++openVersion;
    openModal("联动智能体操作台", "参数试算 · 模拟调整 · 连续观测 · 配置恢复", "正在读取已登记能力…", "", "linked-agent");
    try {
      const result=await api("/api/linked-agent/catalog");
      if(!visible(version)) return;
      actions=result.actions;
      if(!actions.length) throw new Error("当前没有可用的已登记操作");
      if(!spec()) {selected=actions[0].id; draft.parameters=defaultParameters(); plan=null;}
      render();
      if(command && !working()) {draft.command=String(command); render(); await parse(draft.command);}
    } catch(error) {
      if(!visible(version)) return;
      document.querySelector("#modalBody").innerHTML=`<div class="drawer-note"><strong>操作台读取失败：</strong>${esc(error.message)}<button type="button" class="outline-button" data-la-reload>重试读取</button></div>`;
    }
  }
  async function parse(command) {
    if(working()) return;
    command=String(command || "").trim();
    if(!command) {toast("请填写操作指令","输入需要读取、试算或调整的内容。","warning");return null;}
    draft.command=command;
    const version=openVersion, revision=draftVersion, request=++requestVersion;
    const result = await api("/api/linked-agent/parse", {method:"POST",body:JSON.stringify({command})});
    if(!visible(version) || revision !== draftVersion || request !== requestVersion) return null;
    if (result.clarification) {toast("请补充操作参数",result.clarification,"warning");return null;}
    selected = result.action_id; plan=null;
    draft.parameters={...defaultParameters(),...result.parameters}; draftVersion++;
    render();
    return result;
  }
  async function prepare(payload, {fromForm=false}={}) {
    const version=openVersion, revision=draftVersion, request=++requestVersion;
    const prepared = await api("/api/linked-agent/plans", {method:"POST",body:JSON.stringify(payload),timeoutMs:50000});
    if(request !== requestVersion || (fromForm && (!visible(version) || revision !== draftVersion))) return prepared;
    plan=prepared;
    if(!fromForm) {usePlan(prepared);if(visible(version))render();}
    else if(visible(version) && document.querySelector("#laPlan")) document.querySelector("#laPlan").innerHTML=planMarkup();
    return prepared;
  }
  async function runPlan(prepared = plan, shouldStop = ()=>false) {
    if (!prepared || working()) throw new Error("请先预览方案，或等待当前操作结束；连接中断时请刷新回执核查");
    busy=true; syncControls();
    // An uncertain POST response must be retried with the same request identity.
    if(!executionRequests.has(prepared.id)) executionRequests.set(prepared.id,crypto.randomUUID().replaceAll("-",""));
    try {
      let job=await api(`/api/linked-agent/plans/${prepared.id}/execute`,{method:"POST",body:JSON.stringify({plan_sha256:prepared.plan_sha256,request_id:executionRequests.get(prepared.id)})});
      run=job;
      const jobId=job.id;
      let cancelRequested=false;
      updateRun();
      revealReceipt();
      while(job.status === "running") {
        if(shouldStop() && !cancelRequested) {await api(`/api/linked-agent/runs/${jobId}/cancel`,{method:"POST",body:"{}"});cancelRequested=true;}
        await new Promise(resolve=>setTimeout(resolve,1000));
        job=await api(`/api/linked-agent/runs/${jobId}`);
        acceptRun(job);
      }
      if(run?.id === jobId) revealReceipt();
      if(job.status !== "completed") throw new Error(job.error || statuses[job.status]);
      return job;
    } finally {busy=false; syncControls();}
  }
  function trackDraft(event) {
    const input=event.target;
    if(!visible() || working()) return;
    if(input.id === "laAction") {
      if(selected === input.value) return;
      selected=input.value; draft.parameters=defaultParameters(); invalidatePlan(); render();
    } else if(input.matches?.("[data-la-param],#laSamples,#laInterval,#laRestore,#laCommand")) {
      if(input.dataset.laParam) draft.parameters[input.dataset.laParam]=input.value;
      else if(input.id === "laSamples") draft.samples=input.value;
      else if(input.id === "laInterval") draft.interval=input.value;
      else if(input.id === "laRestore") draft.restore=input.checked;
      else draft.command=input.value;
      invalidatePlan();
    }
  }
  document.addEventListener("input",trackDraft);
  document.addEventListener("change",trackDraft);
  document.addEventListener("click",async event=>{
    const button=event.target.closest?.("[data-la-preview],[data-la-parse],[data-la-execute],[data-la-cancel],[data-la-rollback],[data-la-history],[data-la-run],[data-la-export],[data-la-refresh],[data-la-reload]");
    if(!button || button.disabled || !visible()) return;
    const version=openVersion;
    button.disabled=true;
    try {
      if(button.hasAttribute("data-la-reload")) await open();
      if(button.hasAttribute("data-la-parse")) await parse(document.querySelector("#laCommand").value);
      if(button.hasAttribute("data-la-preview")) {
        const inputs=[...document.querySelectorAll("[data-la-param],#laSamples,#laInterval")];
        const invalid=inputs.find(input=>!input.value.trim() || (input.checkValidity && !input.checkValidity()));
        if(invalid) {invalid.reportValidity?.(); throw new Error("请填写完整参数，并遵守登记的数值范围与步长");}
        const parameters={}; document.querySelectorAll("[data-la-param]").forEach(input=>parameters[input.dataset.laParam]=input.type==="number" ? Number(input.value) : input.value);
        plan=null; document.querySelector("#laPlan").textContent="正在读取目标状态…";
        await prepare({action_id:selected,parameters,samples:Number(document.querySelector("#laSamples").value),interval_seconds:Number(document.querySelector("#laInterval").value),restore_after_observation:document.querySelector("#laRestore")?.checked ?? true},{fromForm:true});
      }
      if(button.hasAttribute("data-la-execute")) await runPlan();
      if(button.hasAttribute("data-la-cancel")) {
        const id=button.dataset.laCancel, result=await api(`/api/linked-agent/runs/${id}/cancel`,{method:"POST",body:"{}"});
        toast(result.cancellation_requested ? "已请求停止" : "当前任务已不在观测中",result.cancellation_requested ? "等待当前请求结束并核验恢复结果。" : "正在重新读取最终回执，请核对状态。","warning");
        const latest=await api(`/api/linked-agent/runs/${id}`);
        acceptRun(latest);
      }
      if(button.hasAttribute("data-la-rollback")) {
        const id=button.dataset.laRollback;
        busy=true;syncControls();
        try {const latest=await api(`/api/linked-agent/runs/${id}/rollback`,{method:"POST",body:"{}",timeoutMs:50000});acceptRun(latest);}
        finally {busy=false;syncControls();}
      }
      if(button.hasAttribute("data-la-history")) {
        const result=await api("/api/linked-agent/runs");
        if(visible(version) && document.querySelector("#laReceipt")) document.querySelector("#laReceipt").innerHTML=`<section class="la-receipt"><h4>最近操作</h4>${result.items.map(r=>`<button class="la-history" type="button" data-la-run="${esc(r.id)}">${esc(r.created_at)} · ${esc(r.plan.label)} · ${esc(statuses[r.status] || r.status)}</button>`).join("") || "暂无操作记录"}</section>`;
      }
      if(button.dataset.laRun) {const latest=await api(`/api/linked-agent/runs/${button.dataset.laRun}`);if(visible(version)) {run=latest;updateRun();}}
      if(button.hasAttribute("data-la-refresh")) {const id=button.dataset.laRefresh,latest=await api(`/api/linked-agent/runs/${id}`);acceptRun(latest);}
      if(button.hasAttribute("data-la-export")) {const url=URL.createObjectURL(new Blob([JSON.stringify(run,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download=`${run.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    } catch(error) {
      if(visible(version) && button.hasAttribute("data-la-preview") && !plan && document.querySelector("#laPlan")) document.querySelector("#laPlan").textContent=`方案读取未完成：${error.message}。请重新预览。`;
      toast("联动操作未完成",error.message,"warning",6500);
    } finally {button.disabled=false;syncControls();}
  });
  return {open,prepare,runPlan,summarize,showRun: result=>{run=result;updateRun();}};
};
