
'use strict';
const d=JSON.parse(document.getElementById('data').textContent);
const el=id=>document.getElementById(id);
const models={parent:'训练前',reward_validity:'追加 RL 和辅助训练'};
const arms={raw:'自由动作',retry_guard:'限制无进展重试'};
const outcomes={verified_candidate_recommended:'有证据的候选推荐',no_registered_candidate_meets_requirements:'无符合条件的候选',awaiting_user_clarification:'等待补充必要资料',incorrect_report:'报告结论与证据不符',step_limit:'步数用尽',evidence_gap_reported:'报告资料缺口'};
const actions={A:'询问基线偏好',B:'询问碳价',C:'询问业务要求',D:'读取场景来源',E:'试算候选 1',F:'试算候选 2',G:'恢复已提交的回执',H:'核验候选 1',I:'核验候选 2',J:'推荐候选 1',K:'推荐候选 2',L:'报告无可行候选',M:'报告证据不足'};
const fmt=new Intl.NumberFormat('zh-CN',{maximumFractionDigits:3});
function n(tag,txt,cls){const node=document.createElement(tag);if(txt!==undefined)node.textContent=txt;if(cls)node.className=cls;return node}
function terms(obj){if(!obj)return '待补业务约束';const xs=[];if('max_cost_cny' in obj)xs.push('成本不超过 '+fmt.format(obj.max_cost_cny)+' 元');if('min_service_pct' in obj)xs.push('服务指标至少 '+fmt.format(obj.min_service_pct)+'%');if('min_carbon_reduction_pct' in obj)xs.push('相对基线减排至少 '+fmt.format(obj.min_carbon_reduction_pct)+'%');return xs.join('，')}
function panel(id,trial){
 const target=el(id);target.replaceChildren(n('p',outcomes[trial.outcome]||trial.outcome,'status '+(trial.success?'good':'bad')));
 const seq=n('ol');for(const step of trial.trace){const li=n('li',actions[step.label]||step.label);const pieces=['目标版本 '+step.version];if(step.error)pieces.push('调用失败 · '+step.error);if(step.event)pieces.push(step.event==='goal_change'?'收到新业务目标':step.event);li.append(n('span',pieces.join(' / '),'flag'));seq.append(li)}target.append(seq);
 const details=n('details');details.append(n('summary','查看本任务取得的 '+trial.receipts.length+' 份仿真回执'));
 for(const rec of trial.receipts){const b=rec.baseline,c=rec.candidate;details.append(n('p','候选偏好 '+fmt.format(rec.green)+'，窗口从 '+rec.start.slice(0,10)+' 开始。'),
 n('p','基线：成本 '+fmt.format(b.cost_cny)+' 元，碳排放 '+fmt.format(b.carbon_kg)+' kg，服务指标 '+fmt.format(b.service_pct)+'%。','minor'),
 n('p','候选：成本 '+fmt.format(c.cost_cny)+' 元，碳排放 '+fmt.format(c.carbon_kg)+' kg，服务指标 '+fmt.format(c.service_pct)+'%。','minor'),
 n('code','请求号 '+rec.request),n('code','原生回执 SHA-256 '+rec.native))}target.append(details);
}
function render(){const id=el('case').value,arm=el('arm').value;const task=d.tasks.find(t=>t.case_id===id);el('goal').textContent=task.goal;el('terms').textContent='初始条件：'+terms(task.requirements)+(task.changed_requirements?'。试算完成后变更为：'+terms(task.changed_requirements):'')+'。候选偏好 '+task.candidate_green_preferences.join(' / ')+'。';panel('left',d.runs['parent/'+arm].items[id]);panel('right',d.runs['reward_validity/'+arm].items[id])}
for(const m of Object.keys(models))for(const a of Object.keys(arms)){const t=n('tr');t.append(n('td',models[m]+' · '+arms[a]));for(const key of ['correct','business','wait','wrong','timeouts','invalid'])t.append(n('td',d.runs[m+'/'+a].summary[key]));el('score').append(t)}
for(const [i,task] of d.tasks.entries()){const o=n('option','任务 '+(i+1)+' · '+task.case_id);o.value=task.case_id;el('case').append(o)}
el('case').onchange=render;el('arm').onchange=render;render();
