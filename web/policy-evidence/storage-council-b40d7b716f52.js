(() => {
  const element = id => document.getElementById(id);
  const cases = JSON.parse(element("caseIndex").textContent);
  const wording = {
    back:["返回策略复验","Back to policy replay"], title:["港机与储能三岗会审","Equipment and battery council"],
    intro:["能碳、运营和安全岗位将所选策略与同一历史工况的 MPC 基线逐项比较。七项均满足后提交人工复核，有一项未满足即保留基线。","The energy, operations and safety reviewers compare the selected strategy with MPC for the same historical day. An eligible proposal goes to human review. A failed check retains the baseline."],
    cohort:["试验组","Scenario group"],day:["日期与需求倍率","UTC date and demand multiplier"],policy:["候选策略","Candidate policy"],replay:["查看策略与 MPC 的逐小时记录","View hourly policy and MPC records"]
  };
  const policies = {capacity_peak:["设备能力与储能限峰","Equipment capacity and peak-limited battery"],capacity_idle:["设备能力与储能空闲","Equipment capacity and idle battery"],capacity_q:["设备能力与受训储能 Q 策略","Equipment capacity and learned battery Q policy"],capacity:["设备能力控制","Equipment capacity control"],q_crane:["受保护港机 Q 策略","Guarded crane Q policy"],idle_only:["仅保持储能空闲","Idle battery only"]};
  let english = new URLSearchParams(location.search).get("lang")==="en";
  function populate(id, entries, selected) {
    const field = element(id);
    field.replaceChildren(...entries.map(([key, label])=>new Option(label,key)));
    if(entries.some(([key])=>key===selected)) field.value=selected;
  }
  function render() {
    const index=english?1:0;
    document.documentElement.lang=english?"en":"zh-CN";
    document.title=wording.title[index];
    for(const node of document.querySelectorAll("[data-label]"))node.textContent=wording[node.dataset.label][index];
    element("language").textContent=english?"中文":"English";
    populate("load",[["fresh",english?"Additional 24 scenarios":"新增的 24 个工况"],["known",english?"Previously studied 24 scenarios":"已研究的 24 个工况"]],element("load").value);
    populate("window",cases[element("load").value].map(row=>[row.id,row.date+" · ×"+(row.percent/100).toFixed(2)]),element("window").value);
    populate("policy",Object.entries(policies).map(([key,labels])=>[key,labels[index]]),element("policy").value);
  }
  element("load").addEventListener("change",render);
  element("language").addEventListener("click",()=>{english=!english;render();});
  render();
})();

/* Run the current replay selection through the three registered review tasks. */
(() => {
  const host = document.getElementById("liveCouncil");
  if (!host) return;
  const get = id => document.getElementById(id);
  const text = (zh,en) => document.documentElement.lang.startsWith("en") ? en : zh;
  const expectedRelease = host.dataset.sha;
  const roles = ["energy","operations","safety"];
  const roleNames = {energy:["能碳","Energy"],operations:["运营","Operations"],safety:["安全","Safety"]};
  const labels = {
    queued:["排队中","Queued"],running:["运行中","Running"],completed:["已完成","Completed"],
    waiting_input:["等待补充资料","Waiting for input"],waiting_approval:["等待审批","Waiting for approval"],
    paused:["已暂停","Paused"],needs_review:["需要复核","Needs review"],budget_exceeded:["预算已用完","Budget exhausted"],
    blocked:["受阻","Blocked"],failed:["失败","Failed"],cancelled:["已取消","Cancelled"],partial:["部分完成","Partial"],
    pass:["通过","Pass"],veto:["否决","Veto"],retain_baseline:["保留基线","Retain baseline"],
    human_review:["提交人工复核","Refer for human review"],awaiting_evidence:["等待岗位证据","Awaiting role evidence"],
  };
  const stateName = key => labels[key] ? text(...labels[key]) : key;
  const button = get("liveCouncilStart"), status = get("liveCouncilStatus"), table = get("liveCouncilRows");
  const session = new Map();
  let timer, version=0, busy=false;
  function selection() {
    return {release:"port-storage-20261112",case_id:get("window").value,strategy:get("policy").value};
  }
  function selectedKey() { return "gullmate.policy.council."+expectedRelease+"."+JSON.stringify(selection()); }
  function load(key) {
    if (session.has(key)) return session.get(key);
    try { return JSON.parse(sessionStorage.getItem(key)); } catch { return null; }
  }
  function save(key,value) {
    session.set(key,value);
    try { if (value) sessionStorage.setItem(key,JSON.stringify(value)); else sessionStorage.removeItem(key); } catch {}
  }
  async function post(route,body) {
    const headers={"Content-Type":"application/json"};
    let token;
    try { token=sessionStorage.getItem("xiaoyi_access_token"); } catch {}
    if(token) headers.Authorization="Bearer "+token;
    const response=await fetch("/api/harness/"+route,{method:"POST",headers,body:JSON.stringify(body)});
    if(!response.ok) throw Object.assign(new Error("HTTP "+response.status),{status:response.status});
    return response.json();
  }
  function resetTable() { table.replaceChildren(); }
  function draw(state,chosen) {
    const body=document.createElement("tbody");
    for(const role of roles) {
      const row=state.reviews[role], line=body.insertRow();
      line.insertCell().textContent=text(...roleNames[role]);
      line.insertCell().textContent=stateName(row.status);
      const cell=line.insertCell(), receipt=row.receipt;
      if(receipt) {
        const matches=receipt.role===role && receipt.release_sha256===expectedRelease && receipt.production_authority===false &&
          Object.entries(chosen).every(([k,v])=>receipt.selection?.[k]===v);
        if(!matches) throw new Error(text("岗位回执与当前策略版本或窗口不一致","The receipt uses a different release or selection"));
        cell.textContent=stateName(receipt.decision)+" · "+Object.entries(receipt.checks).map(([key,passed])=>key+(passed?" ✓":" ×")).join(" / ");
      } else cell.textContent="—";
      line.insertCell().textContent=row.id;
      if(row.report?.text){
        const report=body.insertRow().insertCell();
        report.colSpan=4;
        const details=document.createElement("details"), title=document.createElement("summary");
        title.textContent=text("查看岗位报告及证据","Read role report and evidence");
        const explanation=document.createElement("p");explanation.textContent=row.report.text;
        details.append(title,explanation);
        if(receipt){
          const pre=document.createElement("pre");pre.style.whiteSpace="pre-wrap";pre.style.overflowWrap="anywhere";
          pre.textContent=JSON.stringify({result:row.evidence_id,period:receipt.period,
            policy_metrics:receipt.policy_metrics,baseline_metrics:receipt.baseline_metrics,release_sha256:receipt.release_sha256,hourly_source_sha256:receipt.hourly_source_sha256},null,2);
          details.append(pre);
        }
        report.append(details);
      }
    }
    resetTable();
    const tr=table.createTHead().insertRow();
    for(const label of [text("岗位","Role"),text("任务状态","Task status"),text("证据判定","Evidence check"),text("任务编号","Task ID")]){
      const th=document.createElement("th");th.textContent=label;tr.append(th);
    }
    table.append(body);
    const states=Object.values(state.reviews).map(r=>r.status);
    const ongoing=states.some(s=>s==="queued" || s==="running");
    const independentFailure=states.some(s=>["partial","needs_review","budget_exceeded","failed","blocked","cancelled","expired"].includes(s));
    const decision=independentFailure && !state.all_evidence_present && !state.vetoes.length ? "needs_review" : state.decision;
    status.textContent=stateName(decision)+" · "+text("已有岗位回执","Role receipts")+" "+
      Object.values(state.reviews).filter(r=>r.receipt).length+"/3 · "+text("历史仿真","Historical simulation");
    return ongoing;
  }
  async function poll(key,entry,rev) {
    if(rev!==version) return;
    try{
      const latest=await post("policy-council/status",entry.group);
      if(rev!==version) return;
      const pending=draw(latest,entry.selection);
      button.textContent=text("刷新会审回执","Refresh review receipts");
      button.disabled=false;
      if(pending) timer=setTimeout(()=>poll(key,entry,rev),3000);
    }catch(error){
      if(rev!==version) return;
      resetTable();
      if([403,404].includes(error.status)) save(key,null);
      status.textContent=text("未取到本次会审回执 · ","Review receipts unavailable · ")+error.message;
      button.disabled=false;
    }
    if(rev===version)busy=false;
  }
  function refresh() {
    clearTimeout(timer);const rev=++version;
    busy=false;resetTable();status.textContent="";
    get("liveCouncilTitle").textContent=text("会审当前策略","Review the selected policy");
    button.textContent=text("发起三岗会审","Start three-role review");
    button.disabled=!/^https?:$/.test(location.protocol);
    if(button.disabled){status.textContent=text("请从本机小鸥主站发起会审。","Open the workstation gateway to start a review.");return;}
    const key=selectedKey(),entry=load(key);
    if(entry?.group) poll(key,entry,rev);
  }
  button.addEventListener("click",async()=>{
    if(busy)return;
    clearTimeout(timer);
    const rev=++version,key=selectedKey();
    let entry=load(key);
    if(!entry){entry={id:"web-council-"+crypto.randomUUID(),selection:selection()};save(key,entry);}
    if(entry.group){busy=true;button.disabled=true;await poll(key,entry,rev);return;}
    busy=true;button.disabled=true;
    status.textContent=text("正在创建岗位任务…","Creating review tasks…");
    try{
      const group=await post("policy-council",{request_id:entry.id,selection:entry.selection});
      entry.group={group:group.group,tasks:group.tasks,selection:group.selection};
      save(key,entry);
      if(rev===version)await poll(key,entry,rev);
    }catch(error){
      if(rev===version){busy=false;button.disabled=false;status.textContent=text("会审尚未取得回执 · ","No review receipt received · ")+error.message;}
    }
  });
  for(const id of ["load","policy","window"])get(id).addEventListener("change",refresh);
  get("language").addEventListener("click",refresh);
  window.addEventListener("pagehide",()=>{clearTimeout(timer);version++;});
  refresh();
})();
