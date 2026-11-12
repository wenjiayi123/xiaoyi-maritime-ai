
'use strict';
const data=JSON.parse(document.querySelector('#payload').textContent);
const labels={rule:'规则专家',base:'原版 14B',continued_imitation:'继续示范',reward_actor:'回执奖励 RL',episodic:'完整轨迹 RL'};
const outcomes={verified_candidate_recommended:'核验后推荐可行候选',no_registered_candidate_meets_requirements:'两项候选均未满足条件',incorrect_report:'提交了错误报告',evidence_gap_reported:'证据不足',awaiting_user_clarification:'等待用户补充',step_limit:'达到步数上限'};
const families={clarification:'缺项澄清',multiple_constraints:'多个业务约束',unknown_receipt:'响应丢失',changed_goal:'途中更改目标','missing user requirement + lost response':'缺项后又丢失响应','goal change after first calculation + lost response':'目标变更与丢失响应','two confirmed business constraints':'两项已知业务约束','clarification intentionally unavailable':'缺项且没有补充资料'};
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n};
const query=id=>document.getElementById(id);const names=Object.keys(labels);const selections=['episodic','base'];
function part(){return query('part').value}
function cases(){return data.traces[part()].rule}
function buildCases(){const c=query('case');c.replaceChildren();for(const row of cases()){const group=/fresh-(\d+)-|sealed_test-(\d+)-/.exec(row.id);const suffix=group?' · 回执组 '+(1+Number(group[1]??group[2])):'';let opt=el('option',(families[row.family]||row.family)+suffix);opt.value=row.id;c.append(opt)}draw()}
function draw(){const p=part(), id=query('case').value;const s=query('score');s.replaceChildren();for(const key of names){let row=el('tr',null,selections.includes(key)?'picked':'');const v=data.summary[key][p];for(const value of [labels[key],v.correct+'/'+v.n,v.business,v.wait,v.wrong_reports,v.invalid])row.append(el('td',String(value)));s.append(row)}
query('scope').textContent=p==='fresh'?'分区含八份原生计算回执和十六种业务条件。资料不足时，正确停下追问计入判断正确。':'分区含六份不同的原生计算回执，任务在训练前按回执分组隔离。';
let container=query('cols');container.replaceChildren();
for(let side=0;side<2;side++){const name=selections[side], info=data.traces[p][name].find(x=>x.id===id);const pane=el('section',null,'panel');let label=el('label',side?'对照方法':'查看方法');let menu=el('select');menu.id='method'+side;for(const k of names){const o=el('option',labels[k]);o.value=k;o.selected=k===name;menu.append(o)}menu.onchange=()=>{selections[side]=menu.value;draw()};label.append(menu);pane.append(label);
const line=el('div',null,'metrics');for(const v of [[info.steps,'步'],[info.invalid,'次无效调用'],[info.business?1:0,'项推荐']]){const span=el('span');span.append(el('b',String(v[0])),document.createTextNode(v[1]));line.append(span)}pane.append(line,el('h3',outcomes[info.outcome]||info.outcome,info.correct?'':'problem'));
let list=el('ol',null,'trail');info.trace.forEach((x,i)=>{const li=el('li');li.append(el('span',(i+1)+'  '),el('code',x.tool));const how=name==='rule'?'规则选择':(x.model_selection?'模型选择':'唯一允许动作');const options=(x.eligible||[]).map(k=>String.fromCharCode(65+k)).join('、');li.append(el('div',how+(options?' · 候选 '+options:'')+' · 目标版本 '+x.version,'small'));if(x.error)li.append(el('div',x.error.message,'problem'));list.append(li)});pane.append(list);container.append(pane)}
const test=cases().find(x=>x.id===id),ev=query('evidence');ev.replaceChildren(el('p','任务 '+id+' · '+(families[test.family]||test.family)),el('p','SHA-256　'+test.receipt_hashes.join(' / '),'small'));
}
query('part').onchange=buildCases;query('case').onchange=draw;buildCases();
