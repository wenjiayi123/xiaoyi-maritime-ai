'use strict';
const evidence = JSON.parse(document.querySelector('#transfer-data').textContent);
const names = {base:'原始 14B',integrated:'上一轮联合权重',anchor:'本轮监督训练后',reinforced:'本轮追加 RL 后'};
const families = ['交换候选顺序，恢复丢失回执','两次计算后变更目标','资料齐备，核对两项候选','缺少基线且没有回复'];
const outcomes = {step_limit:'步数用尽，未完成交付',verified_candidate_recommended:'已推荐有证据的可行候选',no_registered_candidate_meets_requirements:'两个候选均不满足条件',awaiting_user_clarification:'等待补充必要资料',incorrect_report:'结论与证据不符',evidence_gap_reported:'报告资料缺口'};
const tools = {A:'询问基线偏好',B:'询问碳价',C:'询问业务要求',D:'读取来源与场景',E:'计算候选 1',F:'计算候选 2',G:'读回原生回执',H:'按当前目标核验候选 1',I:'按当前目标核验候选 2',J:'推荐候选 1',K:'推荐候选 2',L:'报告无可行候选',M:'报告证据不足'};
const byId = id => document.getElementById(id);
function node(tag, value, cls) {
  const el = document.createElement(tag);
  if (value !== undefined) el.textContent = value;
  if (cls) el.className = cls;
  return el;
}
function option(select, value, label) {
  const item = node('option', label); item.value=value; select.append(item);
}
for(const id of ['left','right']){
  for(const [value,label] of Object.entries(names)) option(byId(id),value,label);
}
byId('left').value='anchor'; byId('right').value='reinforced';
for(const id of evidence.ids){
  const [g,i]=id.split('-').slice(1).map(Number);
  option(byId('task'),id,'参数组 '+(g+1)+' · '+families[i]+' · '+id);
}
byId('task').value='transfer-3-0';
function renderTrace(target,trial){
  const dest=byId(target);dest.replaceChildren();
  dest.append(node('p',outcomes[trial.outcome]||trial.outcome,'term '+(trial.correct?'pass':'stop')));
  dest.append(node('p',trial.steps+' 步 · '+trial.invalid+' 次无效调用','muted'));
  const list=node('ol',undefined,'trace');
  for(const action of trial.trace){
    const step=node('li');const detail=node('div',tools[action.label]||action.tool);
    detail.append(node('small',action.error||(!action.model_selection?'此时只有一个可执行动作':'模型选择')+' · 目标版本 '+action.version));
    step.append(detail);list.append(step);
  }
  dest.append(list);
}
function render(){
  const arm=byId('arm').value,id=byId('task').value;
  const [g,i]=id.split('-').slice(1).map(Number);const group=evidence.groups[g];
  const brief=byId('brief');brief.replaceChildren(node('h3',families[i]),node('p',id+' · '+(i===3?'基线偏好未提供':'基线偏好 '+group.baseline)+' · 碳价 '+group.price+' 元/吨','muted'));
  if(id==='transfer-3-0' && arm==='free') brief.append(node('p','训练框架 HF/NF4 的监督权重在第 18 步超时，追加 RL 后在第 7 步推荐候选 1。完整模板的原生 Q4 复验中，两者均在第 18 步超时。'));
  if(i===3) brief.append(node('p','模拟接收方没有回复基线偏好。下方回执供实验人员复核，不能用来替模型补答。'));
  for(const side of ['left','right']){
    const model=byId(side).value;renderTrace(side+'Trace',evidence.runs[model+'-'+arm].trials[id]);
  }
  const body=byId('scores');body.replaceChildren();
  for(const [model,name] of Object.entries(names)){
    const r=evidence.runs[model+'-'+arm].summary,row=node('tr');
    for(const value of [name,r.correct+'/16',r.business,r.valid_wait,r.wrong_reports,r.invalid]) row.append(node('td',value));
    body.append(row);
  }
  const receiptPanel=byId('receipts');receiptPanel.replaceChildren();
  const indices=i===0?[1,0]:[0,1];
  for(const [j,idx] of indices.entries()){
    const rec=evidence.receipts[g][idx];const box=node('article',undefined,'panel facts');
    box.append(node('h3','候选 '+(j+1)+' · 绿色偏好 '+rec.preference));
    const fmt=new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2});
    box.append(node('p','成本 '+fmt.format(rec.cost)+' 元 · 碳排 '+fmt.format(rec.carbon)+' kg'));
    box.append(node('p','服务率 '+fmt.format(rec.service)+'%'));
    const details=node('details');details.append(node('summary','查看原生回执校验值'),node('code',rec.sha));box.append(details);
    receiptPanel.append(box);
  }
}
for(const id of ['left','right','task','arm']) byId(id).addEventListener('change',render);
render();
