
'use strict';
const data=JSON.parse(document.getElementById('policy-data').textContent);
const el=id=>document.getElementById(id);
const labels={parent:'训练前 · DPO',reward:'纯奖励 RL',reward_validity:'RL 加动作前提辅助训练'};
const actions={A:'询问基线偏好',B:'询问碳价',C:'询问业务要求',D:'读取来源与场景',E:'计算候选 1',F:'计算候选 2',G:'读回原生回执',H:'核验候选 1',I:'核验候选 2',J:'推荐候选 1',K:'推荐候选 2',L:'报告无可行候选',M:'报告证据不足'};
const outcomes={step_limit:'步数用尽，未完成',verified_candidate_recommended:'推荐有依据的可行候选',no_registered_candidate_meets_requirements:'两项候选均不满足条件',awaiting_user_clarification:'等待补充必要资料',incorrect_report:'报告结论与证据不符',evidence_gap_reported:'报告资料缺口'};
const families=['交换候选顺序及恢复回执','中途更换业务要求','复核两个候选','缺少基线且暂无法补充'];
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function run(mode){return data.runs[[el('env').value,el('part').value,el('arm').value,mode].join('/')]}
function fillTask(){
 const previous=el('task').value;el('task').replaceChildren();
 for(const id of Object.keys(run('parent').items).sort()){const suffix=id.split('-').slice(-2).map(Number);const option=node('option','组 '+(suffix[0]+1)+' · '+families[suffix[1]]+' · '+id);option.value=id;el('task').append(option)}
 if(Object.hasOwn(run('parent').items,previous))el('task').value=previous;
}
function errorMessage(error){
 const message=typeof error==='string'?error:error.message||error.type||'原因未登记';
 const known={'completed calculation and current requirements required':'尚缺该候选的计算结果或当前业务要求，无法核验','no unresolved receipt':'当前没有待恢复的回执','requested field already supplied':'该字段已确认，无需再次询问','missing confirmed fields/context or unresolved pending result':'尚缺确认字段、来源或待恢复的回执'};
 return known[message]||message;
}
function trace(target,item){
 const panel=el(target);const result=node('p',outcomes[item.outcome]||item.outcome,'status '+(item.correct?'good':'bad'));
 const list=node('ol');for(const step of item.trace){const li=node('li',actions[step.label]||step.label);const flags=[step.model_selection?'模型选择':'前提规则唯一可选','目标版本 '+step.version];if(step.error)flags.push('调用失败 · '+errorMessage(step.error));else if(!step.productive)flags.push('未推进当前任务');li.append(node('span',flags.join(' / '),'flag'));list.append(li)}
 panel.replaceChildren(result,list);
}
function render(){
 const parent=run('parent'),after=run(el('method').value),id=el('task').value;
 el('scores').replaceChildren();for(const mode of Object.keys(labels)){const s=run(mode).scores;const tr=node('tr');tr.append(node('td',labels[mode]));for(const k of ['correct','business','wait','wrong_reports','step_limits','invalid','redundant','actual_choices'])tr.append(node('td',s[k]));el('scores').append(tr)}
 el('examples').replaceChildren();for(const direction of [true,false]){const target=Object.keys(parent.items).find(k=>parent.items[k].correct!==after.items[k].correct&&after.items[k].correct===direction);if(target){const b=node('button',direction?'查看改善案例':'查看退化案例');b.type='button';b.onclick=()=>{el('task').value=target;render()};el('examples').append(b)}}
 el('afterTitle').textContent=labels[el('method').value];trace('before',parent.items[id]);trace('after',after.items[id]);
 el('hashes').replaceChildren(...parent.items[id].receipt_hashes.map((hash,i)=>node('code','候选 '+(i+1)+' · '+hash)));
}
for(const id of ['env','part','arm'])el(id).onchange=()=>{fillTask();render()};
for(const id of ['method','task'])el(id).onchange=render;
for(const mode of ['reward','reward_validity']){const t=data.training[mode];el('train').append(node('p',labels[mode]+' · '+t.episodes+' 条训练轨迹，'+t.actual_updates+' 次参数更新，其中 '+t.nonzero_return_advantages+' 组回报有差异。'),node('code','适配器 SHA-256 · '+t.sha256))}
fillTask();render();
