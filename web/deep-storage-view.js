/* Render the authenticated work-order artifact. All metric values come from that receipt. */
export function openDeepStorage(receipt, returnFocus) {
  if(receipt.schema !== "gullmate.deep-storage.v1" || receipt.steps?.length !== 24) throw new Error("缺少完整的逐时策略回执");
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const fmt=(x,n=2)=>x.toLocaleString("zh-CN",{minimumFractionDigits:n,maximumFractionDigits:n});
  if(!document.querySelector("link[data-deep-style]")){
    const style=el("link");style.rel="stylesheet";style.href="/web/deep-storage-view.css";style.dataset.deepStyle="";document.head.append(style);
  }
  const dlg=el("dialog",undefined,"deep-storage-view");
  const close=el("button","关闭");close.type="button";close.onclick=()=>dlg.close();
  const title=el("h2","储能策略逐时复核");title.id="deep-storage-view-title";dlg.setAttribute("aria-labelledby",title.id);
  const head=el("header");head.append(title,close);dlg.append(head);
  const facts=receipt.summary;
  dlg.append(el("p",facts["日期UTC"]+" UTC　·　负荷 "+receipt.args.demand_pct+"%　·　"+facts["方法"]+"　·　港区仿真","deep-meta"));
  const controls=el("label","查看小时（UTC） ");const hour=el("select");
  receipt.steps.forEach(step=>{const opt=el("option",String(step.hour).padStart(2,"0")+":00");opt.value=String(step.hour);hour.add(opt);});
  hour.value=String(receipt.args.hour);controls.append(hour);dlg.append(controls);
  const action=el("h3");const soc=el("p");const scores=el("ol",undefined,"deep-scores");scores.setAttribute("aria-label","动作估值，由高到低");
  const policyStatus=el("p");policyStatus.className="deep-meta";
  dlg.append(action,soc,policyStatus,scores);
  function draw(){
    const step=receipt.steps[Number(hour.value)];const chosen=receipt.action_order[step.action];
    action.textContent=String(step.hour).padStart(2,"0")+":00　"+chosen;
    const ratio=step.control.battery_power_ratio;
    soc.textContent="电池指令 "+fmt(ratio,3)+"（正值放电，负值充电）　·　仿真实际充放电量 "+fmt(step.selected.battery_throughput_kwh)+" kWh　·　荷电状态 "+fmt(step.state[5]*100,1)+"% → "+fmt(step.selected.battery_soc*100,1)+"%";
    policyStatus.hidden=!step.risk;
    if(step.risk){
      const eligible=step.eligible.filter(Boolean).length;
      policyStatus.textContent=step.fallback?"风险网络将五项动作全部判为可能越限，本小时选择风险估计最低的动作。":"风险网络放行 "+eligible+" 项动作，再在其中选取回报估值最高者。";
    }
    scores.replaceChildren();
    receipt.action_order.map((label,index)=>({label,index,value:step.q[index]})).sort((a,b)=>b.value-a.value).forEach(item=>{
      const line=el("li");if(item.index===step.action)line.className="deep-chosen";
      line.append(el("span",item.label));
      if(step.risk)line.append(el("small",(step.eligible[item.index]?"可选":"预计越限")+" · 风险 "+fmt(step.risk[item.index],3)));
      line.append(el("strong",fmt(item.value,4)));scores.append(line);
    });
  }
  hour.onchange=draw;draw();
  dlg.append(el("p","Q 值是训练奖励的折扣估计，数值越高越优先。表中取两个价值网络对同一动作评分的较小值。","deep-meta"),el("h3","全天结果"));
  const table=el("table");const tr=el("tr");
  ["指标","深度策略","MPC","固定限峰"].forEach(k=>tr.append(el("th",k)));const th=el("thead");th.append(tr);table.append(th);
  const body=el("tbody");const metrics=[
    ["cost","成本（元）",2,1],["carbon_kg","碳排放（kg）",2,1],["processed_teu","吞吐量（TEU）",2,1],["peak_kw","峰值功率（kW）",2,1],
    ["delay_minutes","延误（分钟）",2,1],["safety_violations","安全违规（次）",0,1],["ending_battery_soc","日末电量（%）",2,100]];
  for(const [k,label,precision,scale] of metrics){
    const row=el("tr");row.append(el("th",label));
    for(const data of [receipt.metrics,receipt.mpc,receipt.fixed_peak])row.append(el("td",fmt(data[k]*scale,precision)));
    body.append(row);
  }
  table.append(body);const wrap=el("div",undefined,"deep-table");wrap.append(table);dlg.append(wrap);
  if(receipt.attribution){
    const d=receipt.attribution;
    dlg.append(el("h3","峰值与碳排差额"),el("p","策略日峰出现在 "+d.peak_hour+" 时，MPC 日峰出现在 "+d.mpc_peak_hour+" 时。两者日峰相差 "+fmt(d.daily_peak_difference_kw)+" kW（策略减 MPC）。"));
    const parts="全天逐时加总，增碳 "+fmt(d.positive_carbon_kg)+" kg，减碳 "+fmt(Math.abs(d.negative_carbon_kg))+" kg，净差 "+fmt(d.carbon_difference_kg)+" kg。";
    dlg.append(el("p",parts+(d.largest_increase_hour!==null?" 增碳最多的小时是 "+d.largest_increase_hour+" 时。":"")));
  }
  const failed=facts["相对MPC未通过的约束"];
  dlg.append(el("p",facts["结论"]+"。"+(failed.length?"相对 MPC 未通过的约束为"+failed.join("、")+"。":"本日相对 MPC 的七项检查均通过。"),"deep-decision"));
  const pin=el("details");pin.append(el("summary","查看权重与数据版本"),el("p","策略 "+receipt.network+"　SHA-256 "+receipt.weights),el("p","仿真数据 SHA-256 "+receipt.data));dlg.append(pin);
  dlg.addEventListener("close",()=>{dlg.remove();returnFocus?.focus();},{once:true});document.body.append(dlg);dlg.showModal();
}
