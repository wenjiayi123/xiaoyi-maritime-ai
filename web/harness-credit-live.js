"use strict";
(() => {
  const el=id=>document.getElementById(id);
  const form=el("credit-form"), run=el("credit-run"), status=el("credit-status"), out=el("credit-output");
  const sessionKey="gullmate-credit-live-v1";
  let current=null,timer=null,requestId=null,busy=false;
  const titles={verified_candidate_recommended:"推荐已核验的候选",no_registered_candidate_meets_requirements:"两项候选均未达到当前条件",evidence_gap_reported:"有证据缺口",step_limit:"已到步数上限",incorrect_report:"模型结论未通过核验"};
  function node(tag,message){const n=document.createElement(tag);if(message!=null)n.textContent=message;return n;}
  async function api(path,options={}){
    const headers=new Headers(options.headers);if(options.body)headers.set("Content-Type","application/json");
    const token=sessionStorage.getItem("xiaoyi_access_token");if(token)headers.set("Authorization","Bearer "+token);
    const res=await fetch(path,{...options,headers});const value=await res.json();
    if(!res.ok)throw Error(typeof value.detail==="string"?value.detail:"请求失败（"+res.status+"）");
    return value;
  }
  const route=id=>"/api/harness/tasks/"+encodeURIComponent(id);
  function sync(on){busy=on;form.querySelectorAll("button,input,select").forEach(x=>x.disabled=on);el("credit-refresh").disabled=!current;}
  function saved(data){sessionStorage.setItem(sessionKey,JSON.stringify(data));}
  function applyParams(p){
    if(!p)return;
    const fields={first:"first",second:"second",baseline:"base",carbon_price:"price",budget:"budget",service_pct:"service",policy:"policy",loss:"loss"};
    for(const [k,id] of Object.entries(fields)){if(k in p)el("credit-"+id).value=p[k];}
  }
  async function source(id,option,button){
    button.disabled=true;
    try{
      const art=await api(route(id)+"/artifacts/"+encodeURIComponent(option.artifact));
      const packet=JSON.parse(art.content);
      const bytes=Uint8Array.from(atob(packet.gzip_base64),c=>c.charCodeAt(0));
      const raw=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer();
      const sha=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",raw)),x=>x.toString(16).padStart(2,"0")).join("");
      const r=JSON.parse(new TextDecoder().decode(raw));
      if(sha!==packet.sha256_utf8||r.receipt_sha256!==option.receipt_sha256||r.request_id!==option.request_id)throw Error("原始回执摘要不符");
      const url=URL.createObjectURL(new Blob([raw],{type:"application/json"}));const link=node("a");
      link.href=url;link.download=r.request_id+".json";link.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
    }catch(err){status.textContent=err.message;}finally{button.disabled=false;}
  }
  function render(id,r){
    out.replaceChildren();
    out.append(node("h3",r.summary),node("p","策略结果 · "+(titles[r.outcome]||r.outcome)+" · "+r.steps.length+" 步 · 工单 "+id));
    const basis={joint:"Qwen3-14B 与 RL 编排价值网络",alone:"Qwen3-14B 单独选工具",rules:"固定规则"};
    out.append(node("p",basis[r.params.policy]+" · 预算 "+r.params.budget.toLocaleString("zh-CN")+" 元 · 模拟箱量完成率下限 "+r.params.service_pct+"%"));
    if(r.engine.adapter_sha256)out.append(node("small","14B 适配器 "+r.engine.adapter_sha256.slice(0,16)+" · "+(r.engine.compute==="cpu"?"与常驻服务并行的 CPU 推理":"共享显卡推理")));
    r.options.forEach(o=>{
      const line=node("p","候选 "+o.candidate+" · 绿色偏好 "+o.preference+" · 成本 "+o.cost.toLocaleString("zh-CN",{minimumFractionDigits:3,maximumFractionDigits:3})+" 元 · ");
      const link=node("button","下载原始回执");link.type="button";link.addEventListener("click",()=>source(id,o,link));line.append(link);out.append(line);
    });
    const list=node("ol");list.className="flow";
    for(const s of r.steps){
      const li=node("li"),det=node("details");det.append(node("summary",s.number+". "+s.action+" · "+s.tool),node("p",s.feedback));
      if(s.logits){det.append(node("div","14B 原始动作分 "+s.logits.map((v,i)=>String.fromCharCode(65+i)+" "+v.toFixed(2)).join("　")));}
      if(s.combined){det.append(node("div","联合动作分 "+s.combined.map((v,i)=>String.fromCharCode(65+i)+" "+v.toFixed(3)).join("　")));}
      for(const c of s.calls)det.append(node("div",c.method+" "+c.path+(c.receipt?" · 回执 "+c.receipt.slice(0,14):"")));
      li.append(det);list.append(li);
    }out.append(list);
  }
  async function poll(id){
    clearTimeout(timer);
    try{
      const task=await api(route(id));if(current!==id)return;
      const prog=task.credit_progress;
      if(["queued","running"].includes(task.status)){
        status.textContent=(prog?.phase||"工单已登记")+(prog?.tool?" · 第 "+prog.step+" 步 · "+prog.tool:"")+" · "+id;
        sync(true);timer=setTimeout(()=>poll(id),1100);return;
      }
      const row=task.results.find(x=>x.tool==="agent.credit_trial"&&x.ok);
      if(task.status==="completed"&&row){
        const art=await api(route(id)+"/artifacts/"+encodeURIComponent(row.artifact));
        if(current!==id)return;
        const receipt=JSON.parse(art.content);
        if(art.sha256!==row.sha256||receipt.schema!=="gullmate.harness-credit-live.v1")throw Error("运行回执与工单不匹配");
        status.textContent="本次复算已核验";render(id,receipt);
      }else{
        const failure=task.results.find(x=>x.tool==="agent.credit_trial"&&!x.ok);
        status.textContent="工单状态 "+task.status+" · "+(failure?.summary||task.stop_reason||"尚无完整回执");
      }
      requestId=null;saved({id,params:task.credit_trial});sync(false);
    }catch(err){if(current===id){status.textContent="读取运行状态失败，可点刷新。"+err.message;sync(false);}}
  }
  function inputs(){return {first:+el("credit-first").value,second:+el("credit-second").value,baseline:+el("credit-base").value,
    carbon_price:+el("credit-price").value,budget:+el("credit-budget").value,service_pct:+el("credit-service").value,
    policy:el("credit-policy").value,loss:el("credit-loss").value};}
  el("credit-swap").addEventListener("click",()=>{const a=el("credit-first"),b=el("credit-second");[a.value,b.value]=[b.value,a.value];});
  form.addEventListener("submit",async ev=>{
    ev.preventDefault();if(busy||!form.reportValidity())return;
    const params=inputs(),fingerprint=JSON.stringify(params);clearTimeout(timer);
    const old=JSON.parse(sessionStorage.getItem(sessionKey)||"null");
    requestId=old?.pending&&old.fingerprint===fingerprint?old.pending:crypto.randomUUID();
    saved({pending:requestId,fingerprint,params});current=null;out.replaceChildren();sync(true);status.textContent="正在登记新工单…";
    try{
      const task=await api("/api/harness/tasks",{method:"POST",body:JSON.stringify({request_id:requestId,goal:"按当前条件核验两项港区能碳方案的工具编排过程",driver:"rules",credit_trial:params,budget:{max_active_seconds:600}})});
      current=task.id;saved({id:current,params});await poll(current);
    }catch(err){status.textContent=err.message;sync(false);}
  });
  el("credit-refresh").addEventListener("click",()=>{if(current)poll(current);});
  let restored=null;
  try{restored=JSON.parse(sessionStorage.getItem(sessionKey)||"null");current=restored?.id||null;applyParams(restored?.params);}catch{}
  sync(false);
  if(current)poll(current);
  else if(restored?.pending&&restored?.params)form.requestSubmit();
})();
