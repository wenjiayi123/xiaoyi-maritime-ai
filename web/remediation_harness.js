/* New independent periods stay separate from the original, preserved experiments. */
window.renderRemediationEvidence=function(data,esc){
  const n=v=>Number.isFinite(v)?v.toFixed(4):'—';
  const table=(headers,rows)=>`<div class="hx-table-scroll"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const detail=(label,value)=>`<details><summary>${esc(label)}</summary><pre>${esc(JSON.stringify(value,null,2))}</pre></details>`;
  const port=data.crossport,physical=data.physical,ops=data.operations;
  const names=Object.fromEntries(port.sources.entries.map(e=>[e.id,e.name]));
  const sourceLink=url=>{try{const u=new URL(url);return u.protocol==='https:'?`<a href="${esc(u.href)}" target="_blank" rel="noopener">${esc(u.hostname)} ↗</a>`:'';}catch{return '';}};
  return `<h3>剩余八项整改 · 2026独立留出 · ${data.current?'当前证据已核验':'存在版本漂移，暂缓采信'}</h3>
    <p>2019—2024四港训练、2025选型、2026新时期与八个新增港口留出。最终强基线：${esc(data.selected_baseline)}；验证选定RL：${esc(data.selected_rl)}。保留原研究、失败、模仿快照与真实RL更新后的结果。</p>
    <h3>新公开来源与可用时段</h3>
    ${table(['港口 / 国家','角色','记录数','实际范围'],port.sources.entries.map(e=>[`${esc(e.name)} / ${esc(e.country)}`,e.role==='fresh_whole_port_holdout'?'新增整港留出':'训练与新时间留出',esc(e.rows),`${esc(e.start)} — ${esc(e.end)}`]))}
    <p>官方冻结导出实际只到2026-07-24；完整测试窗口${esc(port.test_windows.length)}个，排除${esc(port.excluded_test_windows.length)}个不完整窗口，不补造第三季度。该批新增记录来自已固定的完整官方导出，未冒充另一个获取版本。${sourceLink(port.sources.landing_url)}</p>
    ${detail('完整新来源、许可、请求时期、校验值与排除窗口',{sources:port.sources,protocol:port.protocol,excluded:port.excluded_test_windows})}
    <h3>RL与更强MPC · 模仿和RL分别验收</h3>
    ${table(['候选','验证Score','新留出Score','时间留出差值95%区间','新港口差值95%区间','可行窗口违规步数','研究准入'],data.aggregate.map(r=>[esc(r.algorithm),n(r.validation_score),n(r.test_score),r.contexts.temporal_holdout.port_cluster_ci95.map(n).join(' ~ '),r.contexts.new_whole_port_holdout.port_cluster_ci95.map(n).join(' ~ '),esc(r.feasible_constraint_violations),r.checks.rl_candidate?(r.research_admission?'所列门禁通过':'未通过'):'对照 / 模仿快照']))}
    <p>Score为原代理成本的负值，越高越好；区间是相对验证选定强基线的差值。MPC14、整定PID、MPC预训练和纯模仿均明示；测试时神经策略没有MPC回退。研究准入不授予现场权限。</p>
    ${detail('真实训练、两阶段开发选型、压力失败与全部阻断项',{selection:port.selection,guided_selection:data.guided.selection,aggregate:data.aggregate})}
    <h3>需求侧孪生 · 新2026留出</h3>
    ${table(['港口','点数','MAE / 艘次每天','滞后基线MAE','覆盖率','平均区间宽度','门禁'],port.demand_forecast.map(r=>[esc(names[r.port_id]),esc(r.n),n(r.mae),n(r.persistence_mae),n(r.coverage),n(r.mean_width),r.passed?'通过':'未通过']))}
    <p>区间按目标时刻之前的波动缩放，乘数只用2025验证集确定；同时限制宽度。通过单元数不是预测准确率。</p>
    <h3>国际物理标定 · 长期开环 ${esc(physical.long_passed)}/${esc(physical.long_total)} · 短期同化 ${esc(physical.short_passed)}/${esc(physical.short_total)}</h3>
    <p>年度真实观测拟合与天文节点修正；六站包括洛杉矶、纽约、西雅图、Fremantle、Colombo、Mombasa。缺测仍显示失败。UHSLC归档通常延迟4—6周；短期回放假设另有本地传感器即时观测，不是实时UHSLC服务。各站当地高程基准分别保留。</p>
    ${table(['站点 / 月份','任务 / 提前分钟','有效 / 预期点数','MAE / m','基线MAE / m','覆盖率 / 宽度m','标定门禁'],physical.results.map(r=>[`${esc(r.site)} / ${esc(r.month)}`,`${esc(r.kind)} / ${esc(r.horizon_minutes??'长期开环')}`,`${esc(r.n)} / ${esc(r.expected)}`,n(r.mae_m),n(r.baseline_mae_m),`${n(r.coverage)} / ${n(r.interval_width_m)}`,r.passed?'通过':`未通过：${esc(r.blockers.join('、'))}`]))}
    <p>${physical.sources.landing_urls.map(sourceLink).join(' · ')}</p>
    ${detail('物理冻结协议、补取训练记录的原因、原始来源、质量等级及全部模型',{protocol:physical.protocol,sources:physical.sources,selection:physical.selection,trace_path:physical.trace_path,trace_sha256:physical.trace_sha256})}
    <h3>全港业务、协同与安全 · 工程检查${ops.engineering_passed?'通过':'未通过'}，现场证据仍有缺项</h3>
    <p>公开活动指标只用于生成声明的合成工单；设备能力、负荷、新能源曲线和效率为工程假设。只将洛杉矶水位用于洛杉矶。未知测深、吃水、碳因子或授权时暂缓，未排完工作与未供电量不隐藏。</p>
    <details><summary>48个同日工程场景：资源、能源、UKC与失败</summary>${table(['港口 / 场景','合成工单','排程','未供电 / kWh','UKC建议'],ops.cases.map(r=>[`${esc(names[r.port_id])} / ${esc(r.scenario)}`,esc(r.synthetic_calls),r.schedule.complete?'完整':'暂缓，有未排完工单',n(r.energy.unserved_kwh),esc(r.ukc.status)]))}</details>
    ${detail('资源/功率/储能守恒、崩溃恢复、冲突拒绝与现场缺项',{checks:ops.checks,resilience:ops.resilience,assumptions:ops.assumptions,field_evidence:ops.field_evidence})}
    <h3>全仓发布门禁 · ${data.quality.passed&&!data.quality.historical_only?'通过当前本地工程发布检查':'未通过或已漂移'}</h3><p>${esc(data.quality.notice)}</p>
    ${detail('当前发布与静态检查的完整回执、版本和历史失败',data.quality)}
    <p>${esc(data.notice)}</p>`;
};
