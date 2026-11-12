/* Shared chat entry for the persistent model-driven Harness. */
window.createHarnessChat = function ({api: rawApi, escapeHtml: esc, onUpdate}) {
  const api = (path, options={}) => rawApi(path,{...options,headers:{"Content-Type":"application/json",...(options.headers||{})}});
  let task = null, timer = null, busy = false, generation = 0;
  const key = "xiaoyi_harness_chat_v13", requestKey = key + "_request";
  const terminal = new Set(["completed", "partial", "failed", "blocked", "cancelled", "budget_exceeded", "needs_review"]);
  const labels = {queued:"排队",running:"模型正在判断下一步",waiting_approval:"等待操作审批",waiting_input:"等待补充",paused:"已暂停",completed:"已完成核验",partial:"部分完成",failed:"执行失败",blocked:"已阻止",cancelled:"已取消",budget_exceeded:"达到预算",needs_review:"待核查执行结果"};
  function root() {
    let el = document.getElementById("harnessChat");
    if (!el) { el = document.createElement("section"); el.id = "harnessChat"; el.className = "harness-chat"; document.getElementById("conversationFeed").append(el); el.addEventListener("click", click); }
    return el;
  }
  function button(action, text) { return `<button type="button" data-hchat="${action}" ${busy?"disabled":""}>${text}</button>`; }
  function render() {
    if (!task) return;
    const openResultIds=new Set([...root().querySelectorAll("details[open] [data-ref]")].map(x=>x.dataset.ref));
    const previousInput = root().querySelector("[data-hchat-input]");
    const draft = previousInput?.value || "", focused = document.activeElement === previousInput;
    const selection = previousInput?.selectionStart;
    const pending = task.pending;
    root().innerHTML = `<header><strong>Harness 自主任务</strong><span>${esc(labels[task.status]||task.status)}</span></header>
      <p>${esc(task.goal)}</p><small>模型逐步选择工具 · ${task.usage.tool_calls} 次工具调用 · ${Math.round(task.usage.active_seconds)} 秒活动时间</small>
      ${task.plan.length?`<ol>${task.plan.map(s=>`<li>${esc(s)}</li>`).join("")}</ol>`:""}
      <div class="harness-chat-results">${task.results.map(r=>`<details><summary>${esc(r.id)} · ${esc(r.tool)} · ${r.ok?"成功":r.resolved_by?"失败后已恢复":"未成功"}</summary><pre>${esc(r.summary)}</pre>${r.ok&&r.tool==="policy.deep_storage"?'<button type="button" data-hchat="deep" data-ref="'+esc(r.id)+'">查看 24 小时策略</button>':""}</details>`).join("")}</div>
      ${task.status==="waiting_approval"&&pending?`<div class="harness-chat-approval"><b>请核对本次具体操作</b><pre>${esc(JSON.stringify({tool:pending.action.tool,arguments:pending.action.arguments,preview:pending.prepared},null,2))}</pre>${button("approve","批准本次操作")}${button("reject","拒绝")}</div>`:""}
      ${task.question&&task.status==="waiting_input"?`<p>${esc(task.question)}</p>`:""}
      ${task.final?`<p class="harness-chat-final">${esc(task.final.text)}</p><small>${esc(task.final.data_notice)}</small>`:""}
      ${task.stop_reason?`<p>${esc(task.stop_reason)}</p>`:""}
      <div class="harness-chat-controls">${["running","queued"].includes(task.status)?button("pause","暂停"):""}${task.status==="paused"?button("resume","继续"):""}${!terminal.has(task.status)?button("cancel","取消任务"):""}${task.status==="needs_review"?button("reconcile","读取回执核查"):""}${button("refresh","刷新")}${button("export","导出回执")}${button("trajectory","导出RL研究轨迹")}</div>
      ${!terminal.has(task.status)?`<label>补充目标或约束<input data-hchat-input placeholder="例如：先不要改配置，只做参数对比"></label>${button("input","发送补充")}`:""}<p data-hchat-notice role="status"></p>`;
    const nextInput = root().querySelector("[data-hchat-input]");
    if (nextInput) { nextInput.value = draft; if (focused) { nextInput.focus(); nextInput.setSelectionRange(selection,selection); } }
    root().querySelectorAll("[data-ref]").forEach(x=>{if(openResultIds.has(x.dataset.ref))x.closest("details").open=true;});
    onUpdate?.(task);
  }
  async function refresh() {
    if (!task) return;
    const id = task.id, revision = generation;
    const value = await api(`/api/harness/tasks/${id}`);
    if (revision !== generation) return;
    task = value; render();
    clearTimeout(timer);
    if (["running","queued"].includes(task.status)) timer = setTimeout(()=>refresh().catch(showError), 1800);
  }
  function showError(error) {
    const el = root().querySelector("[data-hchat-notice]"); if (el) el.textContent = "读取或操作失败：" + error.message + "。任务仍保留，可点击刷新核查。";
  }
  async function click(event) {
    const control = event.target.closest("[data-hchat]");
    if (!control || busy || !task) return;
    const action = control.dataset.hchat, id = task.id;
    const input = root().querySelector("[data-hchat-input]")?.value.trim();
    busy = true;
    try {
      if (action === "deep") {
        const result=task.results.find(x=>x.id===control.dataset.ref && x.tool==="policy.deep_storage" && x.ok);
        if(!result)throw new Error("找不到对应的储能回执");
        const file=await api("/api/harness/tasks/"+id+"/artifacts/"+encodeURIComponent(result.artifact));
        if(task?.id!==id)return;
        const {openDeepStorage}=await import("/web/deep-storage-view.js");
        if(task?.id===id)openDeepStorage(JSON.parse(file.content),control);
        return;
      }
      if (action === "refresh") { await refresh(); return; }
      if (["pause","resume","cancel"].includes(action)) await api(`/api/harness/tasks/${id}/control/${action}`, {method:"POST"});
      if (["approve","reject"].includes(action)) {
        const p = task.pending;
        await api(`/api/harness/tasks/${id}/approval`, {method:"POST", body:JSON.stringify({approval_id:p.id,action_sha256:p.action_sha256,approve:action==="approve"})});
      }
      if (action === "input") {
        if (!input) throw new Error("请填写补充目标或约束");
        await api(`/api/harness/tasks/${id}/inputs`, {method:"POST",body:JSON.stringify({text:input,request_id:crypto.randomUUID()})});
        const field = root().querySelector("[data-hchat-input]"); if (field) field.value = "";
      }
      if (action === "reconcile") await api(`/api/harness/tasks/${id}/reconcile`, {method:"POST"});
      if (["export","trajectory"].includes(action)) {
        const receipt = await api(`/api/harness/tasks/${id}/${action==="trajectory"?"learning-trajectory":"export"}`), link = document.createElement("a");
        link.href = URL.createObjectURL(new Blob([JSON.stringify(receipt,null,2)],{type:"application/json"}));
        link.download = id + (action==="trajectory"?"-rl-trajectory":"") + ".json"; link.click(); setTimeout(()=>URL.revokeObjectURL(link.href),1000);
      }
      await refresh();
    } catch (e) { showError(e); }
    finally { busy = false; root().querySelectorAll("button").forEach(b=>b.disabled=false); }
  }
  async function start(text, signal, forceTask=false) {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(requestKey)); } catch {}
    if (!saved || saved.text !== text || saved.force_task !== forceTask) {
      saved = {text,force_task:forceTask,request_id:crypto.randomUUID()}; localStorage.setItem(requestKey,JSON.stringify(saved));
    }
    const response = await api("/api/harness/chat", {method:"POST",body:JSON.stringify(saved),signal});
    if (!response.handled) { localStorage.removeItem(requestKey); return false; }
    ++generation; clearTimeout(timer); task = response.task;
    localStorage.setItem(key,task.id); localStorage.removeItem(requestKey); render();
    timer = setTimeout(()=>refresh().catch(showError),500); return true;
  }
  async function restore() {
    const id = localStorage.getItem(key); if (!id || !/^ht-[a-f0-9]{32}$/.test(id)) return;
    try { task = await api(`/api/harness/tasks/${id}`); render(); await refresh(); } catch { /* Original history remains available in the workbench. */ }
  }
  return {start,restore};
};
