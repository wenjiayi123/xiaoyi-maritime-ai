"use strict";
(() => {
  const $ = selector => document.querySelector(selector);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const num = value => Number.isFinite(value) ? value.toFixed(2) : "未取得";
  const percent = value => Number.isFinite(value) ? (100*value).toFixed(1)+"%" : "未取得";
  let catalog;
  const receipts=[];
  async function api(path, body) {
    const headers = {"Content-Type":"application/json"};
    const token = sessionStorage.getItem("xiaoyi_access_token");
    if(token) headers.Authorization="Bearer "+token;
    const response=await fetch("/api/harness/capability-review/"+path,{method:body?"POST":"GET",headers,body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(45000)});
    if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{detail=response.statusText;}throw new Error(typeof detail==="string"?detail:JSON.stringify(detail));}
    return response.json();
  }
  function renderComponents(){
    const query=$("#search").value.trim().toLowerCase(),priority=$("#priority").value;
    const rows=catalog.scorecard.components.filter(c=>(!query||[c.name,c.can_do,c.boundary,c.target.target].join(" ").toLowerCase().includes(query))&&(!priority||c.target.priority===priority));
    $("#count").textContent=rows.length+" / 37 项";
    $("#components").innerHTML=rows.length?rows.map(c=>`<details data-component="${esc(c.id)}"><summary><span class="name">${esc(c.name)}</span><span class="priority">${esc(c.target.priority)}</span><strong>${c.score}</strong></summary><div class="detail"><p>${Object.entries(c.dimensions).map(([k,v])=>`<span class="dimension">${esc(k)} ${v}/4</span>`).join("")}</p><dl><dt>现在能做什么</dt><dd>${esc(c.can_do)}</dd><dt>当前边界</dt><dd>${esc(c.boundary)}</dd><dt>本轮状态</dt><dd>${esc(c.round_status)}；${esc(c.score_change_reason)}</dd><dt>对标目标</dt><dd>${esc(c.target.target)}</dd><dt>逐项提升动作</dt><dd>${esc(c.target.next)}</dd><dt>下一道验收条件</dt><dd>${esc(c.target.acceptance)}</dd><dt>本地依据（历史与本轮分别保留）</dt><dd>${c.evidence.map(esc).join("<br>")||"无已验收证据"}</dd></dl></div></details>`).join(""):'<p class="empty">没有匹配的能力。</p>';
  }
  function renderCells(){
    const rows=catalog.forecast_cells.filter(c=>c.port_id===$("#port").value&&c.horizon_days===Number($("#horizon").value));
    $("#forecast-cells").innerHTML=rows.map(c=>`<tr><td>${c.year}</td><td>${c.all_candidate.n}/${c.expected_samples}</td><td>${num(c.all_candidate.mae)}</td><td>${num(c.all_strong_baseline.mae)}</td><td>${num(c.all_candidate.wis)}</td><td>${percent(c.all_candidate.coverage90)}</td><td>${percent(c.retained_fraction)}</td></tr>`).join("");
  }
  const reasons={observed_demand_shift:"最近观测与历史规模发生显著变化",insufficient_monitoring_or_interval_quality:"监控样本不足或区间覆盖/宽度不达研究门槛",candidate_quality_requires_baseline:"候选退化，采用通过门槛的基线",no_qualified_baseline:"候选退化，且没有合格回退基线"};
  function renderForecast(r){
    const label={candidate:"通过本次研究使用检查",baseline:"降级为合格基线",hold:"暂停将预测用于计划"}[r.status];
    const p=r.prediction;
    $("#forecast-result").innerHTML=`<h3 class="${r.status==='hold'?'hold':''}">${label}</h3><p>目标日期 ${esc(r.target)} · 观测截止 ${esc(r.publication_cutoff)} · 提前 ${r.horizon_days} 天</p>${p?`<p>日活动指标点预测 <strong>${num(p.point)}</strong>；90%区间 <strong>[${num(p.intervals['0.9'][0])}, ${num(p.intervals['0.9'][1])}]</strong>。模型 ${esc(p.model)}。</p>`:"<p>所需历史窗口缺测或陈旧，未填补观测，未发出有效预测。</p>"}<p>${r.reasons.map(x=>esc(reasons[x]||x)).join("；")||"此状态仅允许研究分析，不能放行船舶或下发设备指令。"}</p><p>副本故障：${esc(r.fault_injected_into_copy)} · 生产权限：关闭</p><p class="receipt">输入摘要 ${esc(r.input_sha256)}<br>结果摘要 ${esc(r.result_sha256)}</p>`;
  }
  function gantt(result){
    const jobs=result.problem.jobs;
    function panel(title,schedule,offset,extra){
      return `<text x="10" y="${offset+18}" fill="#e9f2f6" font-size="15">${title}</text>`+schedule.map((s,i)=>`<text x="10" y="${offset+47+i*26}" fill="#a9bdc9" font-size="12">${esc(jobs[s.job].id)} · 泊${s.berth+1}</text><rect x="${115+s.start/48*760}" y="${offset+32+i*26}" width="${(jobs[s.job].duration+extra)/48*760}" height="19" rx="3" fill="${extra?'#6de0cb':'#7ba9e1'}"/>`).join("");
    }
    const n=result.nominal.schedule.length,m=result.robust.schedule.length,split=72+n*26,height=split+88+m*26;
    return `<svg viewBox="0 0 940 ${height}" role="img" aria-label="名义计划和稳健计划的甘特图，横轴0至24小时">${[0,6,12,18,24].map(h=>`<text x="${115+h/24*760}" y="${height-8}" fill="#a9bdc9" font-size="12">${h}h</text><line x1="${115+h/24*760}" x2="${115+h/24*760}" y1="25" y2="${height-26}" stroke="#2b4253"/>`).join("")}${panel("名义计划",result.nominal.schedule,0,0)}${panel("共享计划（显示最长服务时长）",result.robust.schedule,split,2)}</svg>`;
  }
  function renderSchedule(r){
    const names={nominal:"名义",late_arrival:"到港延迟",long_service:"作业延长",resource_loss:"资源损失",combined:"综合压力"};
    $("#schedule-result").innerHTML=`<h3>五种情景不满足约束次数：${r.nominal_failed_scenarios} → ${r.robust_failed_scenarios}</h3><p>同一名义情景下，综合代理成本增加 ${num(r.nominal_cost_increase_points)} 点；额外暂缓 ${r.additional_deferred_jobs} 单。此数值不是货币、节能量或真实经济收益。</p><p>共享计划最优性证明：${r.robust.solver.optimality_proven?"已取得":"未取得，保留当前可行结果"}；求解界 ${num(r.robust.solver.dual_bound)}。${r.robust.solver.defer_all_fallback?"求解失败，全部工单暂缓。":""}</p>${gantt(r)}<div class="table-scroll"><table><thead><tr><th>情景</th><th>原计划可行</th><th>共享计划可行</th><th>共享计划完成/暂缓</th><th>共享计划代理成本</th></tr></thead><tbody>${r.robust.scenarios.map((c,i)=>`<tr><td>${names[c.name]}</td><td>${r.nominal_stress[i].passed?"是":"否"}</td><td>${c.passed?"是":"否"}</td><td>${c.completed_calls} / ${c.deferred_calls}</td><td>${num(c.objective_points)}</td></tr>`).join("")}</tbody></table></div><p>仅覆盖所列有限情景，未取得真实工单、现场标定和生产执行资格。</p>${r.result_sha256?`<p class="receipt">结果摘要 ${esc(r.result_sha256)}</p>`:"<p class=muted>以上为已登记回放；点击重算生成本次回执。</p>"}`;
  }
  async function compute(button,result,fn,render){
    const original=button.textContent;button.disabled=true;button.textContent="正在计算…";$(result).textContent="正在使用冻结参数计算，请等待回执。";
    try{const r=await fn();receipts.push(r);render(r);}catch(e){$(result).textContent="计算未完成："+e.message;}finally{button.disabled=!catalog.current;button.textContent=original;}
  }
  $("#search").addEventListener("input",()=>catalog&&renderComponents());
  $("#priority").addEventListener("change",()=>catalog&&renderComponents());
  for(const id of ["#port","#horizon"])$(id).addEventListener("change",()=>catalog&&renderCells());
  $("#run-forecast").addEventListener("click",()=>compute($("#run-forecast"),"#forecast-result",()=>api("forecast",{port_id:$("#port").value,origin:$("#origin").value,horizon:Number($("#horizon").value),fault:$("#fault").value}),renderForecast));
  $("#run-schedule").addEventListener("click",()=>compute($("#run-schedule"),"#schedule-result",()=>api("schedule",{port_id:$("#schedule-port").value,source_day:$("#source-day").value,scenario:$("#scenario").value,grid_kw:Number($("#grid").value),objective:"balanced"}),renderSchedule));
  $("#export").addEventListener("click",()=>{const url=URL.createObjectURL(new Blob([JSON.stringify({catalog,session_receipts:receipts,notice:"本次未执行的项目不视为通过",production_authority:false},null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download="xiaoyi-capability-review-v8.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  api("catalog").then(data=>{
    catalog=data;const r=data.results;
    $("#status").textContent=data.current?"证据与本轮源码一致。预测精度仍有失败；真实港口自主调度和多模态感知仍为0分。":"证据已陈旧："+data.current_issues.join("，")+"。下方仅供历史查阅，重算暂停。";
    $("#metrics").innerHTML=[["37","逐项能力评估"],[r.candidate_90_coverage_pass_cells+" / "+r.forecast_cells,"预测单元达到覆盖研究门槛"],[r.declared_scenario_evaluations-r.robust_failed_scenarios+" / "+r.declared_scenario_evaluations,"共享计划通过所列情景约束"],["0","真实港口自主调度资格"]].map(([v,t])=>`<div class="metric"><strong>${v}</strong><span>${t}</span></div>`).join("");
    const options=data.ports.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");$("#port").innerHTML=options;$("#schedule-port").innerHTML=options;
    renderComponents();renderCells();renderSchedule(data.schedule_cases[0]);
    $("#sources").innerHTML=data.scorecard.references.map(s=>`<article><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.name)}</a><p>${esc(s.kind)} · 核查 ${esc(s.checked_on)}</p></article>`).join("");
    document.querySelectorAll("[data-compute]").forEach(b=>b.disabled=!data.current);$("#export").disabled=false;
  }).catch(e=>{$("#status").textContent="无法读取评估："+e.message+"。请核对服务与登录状态；未加载不能视为通过。";});
})();
