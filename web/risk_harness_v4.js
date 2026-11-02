/* Research results, source gaps and evidence-based capability scores remain distinct. */
window.renderCapabilityScorecard=function(data,esc){
  const table=(headers,rows)=>`<div class="hx-table-scroll"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const link=u=>{try{const x=new URL(u);return x.protocol==='https:'?`<a href="${esc(x.href)}" target="_blank" rel="noopener">${esc(x.hostname)} ↗</a>`:'';}catch{return '';}};
  return `<h3>小懿逐项能力评分 · ${data.components.length}项 · ${data.current?'证据当前有效':'待当前证据核验'}</h3>
    <p>${esc(data.rubric.method)} 每个模块同时给出当前能做的事情和未闭合的部分。现场自主调度为0分表示没有已授权现场执行证据；生产权限关闭属于现有保护机制。</p>
    <p>参考尺度：40分局部可运行，60分可复现离线研究/工程能力，80分需要更充分的多场景、业务与运行验证。分差5分不代表统计显著。</p>
    ${table(['功能模块','本次分数 / 100','目前能做到','限制与下一步','证据'],data.components.map(r=>[esc(r.name),`<strong>${esc(r.score)}</strong>`,esc(r.can_do),esc(r.boundary),`<details><summary>查看五维分解与来源</summary><pre>${esc(JSON.stringify({dimensions:r.dimensions,evidence:r.evidence,confidence:r.confidence},null,2))}</pre></details>`]))}
    <details><summary>评分方法、适用范围和全部前沿对标依据</summary><pre>${esc(JSON.stringify(data.rubric,null,2))}</pre>${data.references.map(r=>`<p>${esc(r.name)} · ${link(r.url)} · ${esc(r.relevance)}</p>`).join('')}</details>`;
};

window.renderRiskV4=function(data,esc){
  const n=v=>Number.isFinite(v)?v.toFixed(4):'—';
  const table=(headers,rows)=>`<div class="hx-table-scroll"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const detail=(label,value)=>`<details><summary>${esc(label)}</summary><pre>${esc(JSON.stringify(value,null,2))}</pre></details>`;
  const link=u=>{try{const x=new URL(u);return x.protocol==='https:'?`<a href="${esc(x.href)}" target="_blank" rel="noopener">${esc(x.hostname)} ↗</a>`:'';}catch{return '';}};
  const r=data.learning, d=data.diagnostics, p=data.physical;
  const selected=r.aggregate.find(x=>x.algorithm===r.selection.selected_rl);
  const cost=selected.comparisons.find(x=>x.baseline===r.selection.selected_cost_mpc);
  const names=Object.fromEntries(r.sources.entries.map(e=>[e.id,e.name]));
  const validation=Object.fromEntries(r.selection.validation_summary.map(x=>[x.algorithm,x]));
  return `<h3>最新安全复验、孪生与能力评分 · ${data.current?'当前证据已核验':'证据变化，暂缓采信'}</h3>
    <p>20个已看过港口仅用于开发，再以另外八港作新留出。历史4步违规回放现为${esc(d.historical_four_step_new_violations)}；新港可行窗口违规${esc(d.feasible_window_violations)}，全部违规${esc(d.all_violations)}与最大能力基线${esc(d.maximum_capacity_minimum_violations)}相同。容量不可行只针对本代理模型，不是实际港口容量结论。</p>
    <h3>安全改善的来源与真实代价</h3>
    <p>选中RL：${esc(r.selection.selected_rl)}；成本强MPC：${esc(r.selection.selected_cost_mpc)}；安全强MPC：${esc(r.selection.selected_safe_mpc)}。</p>
    <p>安全过滤器干预${n(100*d.safety_override_fraction)}%动作。与安全MPC比较${esc(d.compared_actions)}步，动作差${esc(d.action_mismatches_vs_safe_mpc)}，安全改进不能包装为额外RL收益。全局平均成本高${n(d.global_proxy_cost_increase_vs_cost_mpc_pct)}%；按港口等权的相对成本平均高${n(d.equal_port_relative_cost_increase_pct)}%。两种归一化分别保留，收益研究准入仍未通过。</p>
    ${table(['策略','2025常态验证Score','新八港Score','过滤干预率','可行 / 全部违规步数','研究准入'],r.aggregate.map(a=>[esc(a.algorithm),n(validation[a.algorithm]?.normal_score),n(a.test_score),n(a.safety_override_fraction),`${esc(a.feasible_constraint_violations)} / ${esc(a.all_constraint_violations)}`,a.algorithm===r.selection.selected_rl?(a.research_admission?'通过':'未通过'):'对照 / 未选中']))}
    ${table(['新港口','相对成本MPC的Score差','季度相对改善均值（负为退化）'],Object.entries(cost.absolute_port_interval.per_port_mean_delta).map(([id,v])=>[esc(names[id]),n(v),n(100*cost.relative_port_interval.per_port_mean_delta[id])+'%']))}
    <p>正收益最大港口占比${n(100*cost.largest_positive_gain_share)}%；去掉最优港口后的平均Score差${n(cost.mean_without_best_port)}。绝对差值95%区间${cost.absolute_port_interval.port_cluster_ci95.map(n).join(' ~ ')}，相对差值区间另存。739步未隐藏，也不作现场安全保证。</p>
    ${detail('封存协议、全部压力/退化/集中收益、因果队列、原始动作与干预说明',{protocol:r.protocol,selection:r.selection,aggregate:r.aggregate,diagnostics:d,historical_shadow_path:r.historical_shadow_path,trace_path:r.trace_path,trace_sha256:r.trace_sha256})}
    <h3>新八港真实公开数据与冻结需求预测</h3>
    ${table(['港口 / 国家地区','实际范围 / 记录数'],r.sources.entries.map(e=>[`${esc(e.name)} / ${esc(e.country)}`,`${esc(e.start)} — ${esc(e.end)} / ${esc(e.rows)}`]))}
    <p>${link(r.sources.landing_url)} 同一固定IMF导出版本；非新供应商、非实时遥测。新八港预测补充验证${esc(data.forecast.passed)}/${esc(data.forecast.total)}；不同批次模型分别报告。</p>
    ${detail('原始来源、许可、派生方法、完整窗口与预测失败',{sources:r.sources,windows:r.windows,excluded:r.excluded_windows,forecast:data.forecast})}
    <h3>七日天气强迫 · 原年度资格仍未通过</h3>
    <p>逐次初始化天气预报，假定初始化后8小时可用；禁止拼接未来新模式。2025 IFS49R1回算档案与2026年7月50R1归档有版本差异，不声称历史发布SLA。七日结果另列，原年度开环${esc(data.legacy_summary.long_passed)}/${esc(data.legacy_summary.long_total)}与原短期${esc(data.legacy_summary.short_passed)}/${esc(data.legacy_summary.short_total)}均保留。</p>
    <p>不用测试期水位初始化：${esc(p.modes.no_test_water_initialization.passed)}/${esc(p.modes.no_test_water_initialization.total)}；只用起点水位、此后七日不更新：${esc(p.modes.causal_initial_water_then_open_loop_7d.passed)}/${esc(p.modes.causal_initial_water_then_open_loop_7d.total)}。天气为模式输出，水位真值来自测站；没有把气象强迫当作真实设备或UKC标定。</p>
    ${table(['站点 / 预报起日','模式','有效 / 预期','MAE / 强基线MAE m','覆盖率 / 最大宽度m','结果'],p.results.map(a=>[`${esc(a.site)} / ${esc(a.run)}`,a.mode==='no_test_water_initialization'?'无测试水位初始化':'起点水位后开环七日',`${esc(a.n)} / ${esc(a.expected)}`,`${n(a.mae_m)} / ${n(a.baseline_mae_m)}`,`${n(a.coverage)} / ${n(a.interval_width_m)}`,a.passed?'通过':`未通过：${esc(a.blockers.join('、'))}`]))}
    ${detail('逐次预报URL、初始化/可用时钟、网格坐标、模型、偏差与区间',{sources:p.sources,protocol:p.protocol,selection:p.selection,trace_path:p.trace_path,trace_sha256:p.trace_sha256})}
    <h3>真实缺测核查 · 不拿预报或邻站充当真值</h3>
    ${table(['来源','最新合格观测','7月合格小时','响应 / 公开链接'],data.availability.entries.map(e=>[esc(e.name),esc(e.last_valid??'政策说明'),esc(e.july_valid_hours??'—'),`${esc(e.http_status)} / ${link(e.url)}`]))}
    ${detail('官方当年数据访问政策、原始响应与全部假设',data.availability)}
    <p>既有32个资源—能源案例、DCSA语义子集与故障演练继续保留。设备标定、测深/吃水、正式互操作、OT、HIL、港口授权和现场SLA仍缺，生产权限关闭。</p>
    <h3>当前Docker与全仓工程门禁 · ${data.docker.current?'已验证':'待当前构建回执'}</h3><p>${esc(data.quality.notice)}</p>
    ${detail('当前容器、源码指纹、原始回执与独立回读',{docker:data.docker,quality:data.quality,independent:data.independent})}
    ${detail('开发负面结果、运行环境错误和修复记录（未删除）',data.failures)}
    <details><summary>逐项查看小懿全部功能评分与前沿差距</summary>${window.renderCapabilityScorecard({...data.scorecard,current:data.current},esc)}</details>
    <p>${esc(data.notice)}</p>`;
};
