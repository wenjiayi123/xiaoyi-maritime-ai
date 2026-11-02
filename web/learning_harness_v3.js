/* Frozen new-port evidence; adverse outcomes have the same visibility as gains. */
window.renderLearningV3=function(data,esc){
  const num=v=>Number.isFinite(v)?v.toFixed(4):'—';
  const table=(headers,rows)=>`<div class="hx-table-scroll"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const detail=(label,value)=>`<details><summary>${esc(label)}</summary><pre>${esc(JSON.stringify(value,null,2))}</pre></details>`;
  const labels={reference_td:'参考：TD价值学习+模仿',td_off:'只关闭TD更新（仍是模仿）',imitation_off:'只关闭模仿约束',gamma_one:'只将折扣改为1',encoder_frozen:'只固定共享特征层',monte_carlo_target:'只改为已发生回报目标',learning_rate_tenth:'只把学习率降至十分之一'};
  const research=data.learning,physical=data.physical,ops=data.operations;
  const rl=research.aggregate.find(r=>r.algorithm===research.selection.selected_rl);
  const mpc=research.aggregate.find(r=>r.algorithm===research.selection.selected_baseline);
  const gain=100*(1-rl.test_score/mpc.test_score);
  const names=Object.fromEntries(research.sources.entries.map(e=>[e.id,e.name]));
  const shortValid=physical.results.filter(r=>r.kind==='short_assimilation'&&r.n>0);
  const sourceLink=url=>{try{const u=new URL(url);return u.protocol==='https:'?`<a href="${esc(u.href)}" target="_blank" rel="noopener">${esc(u.hostname)} ↗</a>`:'';}catch{return '';}};
  return `<h3>六项续改 · 单因素消融与未看过的港口 · ${data.current?'当前证据已核验':'存在版本漂移，停止采信'}</h3>
    <p>八个新整港留出；2025开发选型封存后才评分。平均代理成本相对验证选定MPC变化：降低${num(gain)}%。研究准入：${rl.research_admission?'所列门禁通过':'未通过'}。平均改善不能抵消置信区间跨零、逐港退化或安全违规。</p>
    <h3>单因素消融 · 为什么越学越差</h3>
    <p>每个种子固定同一初始权重、优化器重置、回放、批次顺序和3000次更新；七个条件各五种子。只关闭TD后明显改善，固定特征层、减小更新或替换自举目标也有改善，支持当前价值学习破坏模仿策略的诊断。不能据此认定唯一原因或给各原因分配贡献；只模仿不计作RL训练成果。</p>
    ${table(['单因素条件','2025验证Score','相对参考的均值差','五种子配对95%区间'],research.ablation.paired.map(r=>[esc(labels[r.condition]||r.condition),num(research.ablation.validation_means[r.condition]),num(r.mean_delta),r.seed_bootstrap_ci95.map(num).join(' ~ ')]))}
    ${detail('消融曲线、全部配对结果、固定回放/权重哈希及实验局限',{notice:research.ablation.notice,conditions:research.ablation.conditions,replays:research.ablation.replays,models:research.ablation.models,curves:research.ablation.curves,paired:research.ablation.paired})}
    <h3>新港独立留出 · 强MPC与离线经验模型RL</h3>
    <p>选定策略：${esc(research.selection.selected_rl)}；强基线：${esc(research.selection.selected_baseline)}。经验模型RL在训练期公开指标上学习转移不确定性、使用声明的队列物理先验做离线Bellman备份；测试只查封存策略表，没有在线MPC回退。它与模型无关DQN分列。Score是负代理成本，不是货币、吞吐或现场收益。</p>
    ${table(['候选','2025验证Score','新港Score','相对MPC港口簇95%区间','可行窗口违规步数','研究准入'],research.aggregate.map(r=>[esc(r.algorithm),num(r.validation_score),num(r.test_score),r.new_port_interval.port_cluster_ci95.map(num).join(' ~ '),esc(r.feasible_constraint_violations),r.algorithm===research.selection.selected_rl?(r.research_admission?'通过':'未通过'):'对照 / 未选中']))}
    ${table(['新港口','相对MPC常态Score差'],Object.entries(rl.new_port_interval.per_port_mean_delta).map(([p,v])=>[esc(names[p]),num(v)]))}
    ${detail('所有压力结果、集中收益、退化港口、约束违规及封存选型',{selection:research.selection,aggregate:research.aggregate,windows:research.windows,excluded:research.excluded_windows,trace_path:research.trace_path,trace_sha256:research.trace_sha256})}
    <h3>国际真实公开来源 · 本次八港</h3>
    ${table(['港口 / 来源国家地区','记录数','实际时期'],research.sources.entries.map(e=>[`${esc(e.name)} / ${esc(e.country)}`,esc(e.rows),`${esc(e.start)} — ${esc(e.end)}`]))}
    <p>${sourceLink(research.sources.landing_url)} 同一已固定IMF导出版本中新提取的未评分港口；不是新供应商或实时数据。允许目标港滞后历史作上下文，不参与拟合选型。</p>
    ${detail('来源、许可、原始导出校验值和先行协议',{sources:research.sources,protocol:research.protocol})}
    <h3>冻结需求预测 · 新八港补充验证 ${esc(data.forecast.passed)}/${esc(data.forecast.total)}</h3>
    <p>沿用先前冻结的预测模型、区间乘数和门禁，不重拟合；这些补充结果未用于RL选型。旧12港结果继续保留，单元通过数不是准确率。</p>
    ${table(['港口','点数','MAE / 滞后基线MAE','覆盖率 / 平均区间宽度','结果'],data.forecast.rows.map(r=>[esc(r.port),esc(r.n),`${num(r.mae)} / ${num(r.persistence_mae)}`,`${num(r.coverage)} / ${num(r.mean_width)}`,r.passed?'通过':`未通过：${esc(Object.entries(r.checks).filter(([,v])=>!v).map(([k])=>k).join('、'))}`]))}
    <h3>孪生新时期 · 长期 ${esc(physical.long_passed)}/${esc(physical.long_total)} · 短期 ${esc(physical.short_passed)}/${esc(physical.short_total)}</h3>
    <p>新2026年3/6/9月；七站两年天文拟合。长期泛化与区间仍失败；短期有观测的${esc(shortValid.length)}个单元中${esc(shortValid.filter(r=>r.passed).length)}个通过，缺测仍计失败。校准集与模型选择分离；短期区间只能使用输入截止前已知误差。NOAA/UHSLC归档不能证明实时传感器可用，UHSLC通常延后4—6周。</p>
    ${table(['站点 / 月份','任务 / 提前分钟','有效 / 预期','MAE / m','基线MAE / m','覆盖率 / 最大宽度m','结果与失败原因'],physical.results.map(r=>[`${esc(r.site)} / ${esc(r.month)}`,`${esc(r.kind)} / ${esc(r.horizon_minutes??'长期开环')}`,`${esc(r.n)} / ${esc(r.expected)}`,num(r.mae_m),num(r.baseline_mae_m),`${num(r.coverage)} / ${num(r.interval_width_m)}`,r.passed?'通过':`未通过：${esc(r.blockers.join('、'))}`]))}
    <p>${physical.sources.landing_urls.map(sourceLink).join(' · ')}</p>
    ${detail('物理来源、质量拒绝、当地垂直基准、完整先行协议和模型',{sources:physical.sources,protocol:physical.protocol,selection:physical.selection,trace_path:physical.trace_path,trace_sha256:physical.trace_sha256})}
    <h3>全港业务、协同与安全 · 新32个工程案例</h3>
    <p>全工单原子预留与可靠供电约束同时检查，避免已承诺工作缺电或只排半个工单。设备/能源参数及工单映射仍为工程假设，暂缓工作不算完成。未匹配水深、吃水、垂直基准和授权的UKC仍暂缓。</p>
    ${table(['港口 / 场景','合成 / 完成工单','旧 / 新未供电kWh','暂缓工单','工程检查'],ops.cases.map(r=>[`${esc(r.port)} / ${esc(r.scenario)}`,`${esc(r.synthetic_calls)} / ${esc(r.completed_calls)}`,`${num(r.before_unserved_kwh)} / ${num(r.after_unserved_kwh)}`,esc(r.deferred_calls.length),Object.values(r.checks).every(Boolean)?'通过':'未通过']))}
    <p>DCSA PC2.0.0官方OpenAPI子集与E-R-P-A语义本地检查：${ops.contracts.passed?'通过':'未通过'}；外部一致性认证：未完成。真实子进程崩溃重放、冲突、角色、时钟和网络分区失败均有回执。</p>
    ${detail('官方规范来源、契约与故障回执、所有假设和现场缺项',{sources:ops.sources.standards,contracts:ops.contracts,resilience:ops.resilience,assumptions:ops.assumptions,field_evidence:ops.field_evidence})}
    <h3>Docker实际构建与启动 · ${data.docker.current?'当前版本通过':'待当前外部构建回执'}</h3>
    <p>${esc(data.docker.status||'未验证')}。构建、只读非root启动与本地健康检查不等于港口部署授权。</p>
    ${detail('Docker镜像、构建指纹、运行约束和实际探针',data.docker)}
    ${detail('全仓回归、独立回读和当前源码指纹',{quality:data.quality,independent:data.independent})}
    <p>${esc(data.notice)} 原八项研究及其失败继续保留在“查看8项整改与2026新留出”。</p>`;
};
