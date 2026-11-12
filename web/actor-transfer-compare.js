'use strict';
const reference = JSON.parse(document.querySelector('#transfer-data').textContent);
const native = JSON.parse(document.querySelector('#native-transfer-data').textContent);
const environments = {
  native: {runs: native.runs, models: {base: '原始 14B', anchor: '监督训练后', reinforced: '追加 RL 后', parent: '追加数值偏好训练后'}},
  hf: {runs: reference.runs, models: {base: '原始 14B', integrated: '上一轮联合权重', anchor: '监督训练后', reinforced: '追加 RL 后'}}
};
const families = ['交换候选顺序，恢复丢失回执', '两次计算后变更目标', '资料齐备，核对两项候选', '缺少基线且没有回复'];
const outcomes = {step_limit: '步数用尽，未完成交付', verified_candidate_recommended: '已推荐有证据的可行候选', no_registered_candidate_meets_requirements: '两个候选均不满足条件', awaiting_user_clarification: '等待补充必要资料', incorrect_report: '结论与证据不符', evidence_gap_reported: '报告资料缺口'};
const actions = {A: '询问基线偏好', B: '询问碳价', C: '询问业务要求', D: '读取来源与场景', E: '计算候选 1', F: '计算候选 2', G: '读回原生回执', H: '按当前目标核验候选 1', I: '按当前目标核验候选 2', J: '推荐候选 1', K: '推荐候选 2', L: '报告无可行候选', M: '报告证据不足'};
const element = id => document.getElementById(id);
const number = new Intl.NumberFormat('zh-CN', {maximumFractionDigits: 2});

function node(tag, content, className) {
  const item = document.createElement(tag);
  if (content !== undefined) item.textContent = content;
  if (className) item.className = className;
  return item;
}

function addOption(select, value, label) {
  const item = node('option', label);
  item.value = value;
  select.append(item);
}

function fillModels() {
  const {models} = environments[element('environment').value];
  for (const side of ['left', 'right']) {
    const select = element(side);
    const previous = select.value;
    select.replaceChildren();
    for (const [key, name] of Object.entries(models)) addOption(select, key, name);
    select.value = models[previous] ? previous : side === 'left' ? 'anchor' : 'reinforced';
  }
}

function renderTrace(target, trial) {
  const panel = element(target);
  panel.replaceChildren(node('p', outcomes[trial.outcome] || trial.outcome, 'term ' + (trial.correct ? 'pass' : 'stop')));
  const chosen = trial.trace.filter(action => action.model_selection).length;
  panel.append(node('p', `${trial.steps} 步 · 模型选择 ${chosen} 次 · 无效调用 ${trial.invalid} 次`, 'muted'));
  const list = node('ol', undefined, 'trace');
  for (const action of trial.trace) {
    const item = node('li');
    const content = node('div', actions[action.label] || action.tool);
    let detail = action.model_selection ? '模型选择' : '此时只有一个可执行动作';
    if (action.productive === false && !action.error && 'DEFGHI'.includes(action.label)) detail = '重复取证，未取得新资料';
    content.append(node('small', `${action.error || detail} · 目标版本 ${action.version}`));
    item.append(content);
    list.append(item);
  }
  panel.append(list);
}

function render() {
  const environment = element('environment').value;
  const {runs, models} = environments[environment];
  const arm = element('arm').value;
  const id = element('task').value;
  const [groupIndex, familyIndex] = id.split('-').slice(1).map(Number);
  const group = reference.groups[groupIndex];
  const brief = element('brief');
  brief.replaceChildren(node('h3', families[familyIndex]));
  brief.append(node('p', `${id} · ${familyIndex === 3 ? '基线偏好未提供' : '基线偏好 ' + group.baseline} · 碳价 ${group.price} 元/吨`, 'muted'));
  for (const side of ['left', 'right']) {
    const selection = runs[element(side).value + '-' + arm];
    renderTrace(side + 'Trace', selection.trials[id]);
  }
  const scores = element('scores');
  scores.replaceChildren();
  for (const [key, name] of Object.entries(models)) {
    const summary = runs[key + '-' + arm].summary;
    const tr = node('tr');
    const values = [name, summary.correct + '/16', summary.business, summary.valid_wait ?? summary.wait, summary.wrong_reports,
      summary.invalid, summary.redundant ?? '未计量', summary.model_choices ?? summary.choices];
    for (const value of values) tr.append(node('td', value));
    scores.append(tr);
  }
  const receipts = element('receipts');
  receipts.replaceChildren();
  const order = familyIndex === 0 ? [1, 0] : [0, 1];
  for (const [i, index] of order.entries()) {
    const receipt = reference.receipts[groupIndex][index];
    const panel = node('article', undefined, 'panel facts');
    panel.append(node('h3', `候选 ${i + 1} · 绿色偏好 ${receipt.preference}`),
      node('p', `成本 ${number.format(receipt.cost)} 元 · 碳排 ${number.format(receipt.carbon)} kg`),
      node('p', `服务率 ${number.format(receipt.service)}%`));
    const details = node('details');
    details.append(node('summary', '查看原生回执校验值'), node('code', receipt.sha));
    panel.append(details);
    receipts.append(panel);
  }
  element('environment-note').textContent = environment === 'native' ?
    '本机 Q4 使用共享显存配置，逐次清空上下文并核对输入 token。表中数据来自实际加载的原生权重。' :
    '训练框架使用 HF/NF4 权重。此轮只单独统计了无效调用，重复取证次数未计量。';
}

for (const id of reference.ids) {
  const [group, family] = id.split('-').slice(1).map(Number);
  addOption(element('task'), id, `参数组 ${group + 1} · ${families[family]} · ${id}`);
}
element('task').value = native.examples.improved[0] || 'transfer-3-0';
fillModels();
for (const [kind, label] of [['improved', '查看原生改善案例'], ['regressed', '查看原生退化案例']]) {
  for (const task of native.examples[kind]) {
    const button = node('button', `${label} · ${task}`);
    button.type = 'button';
    button.addEventListener('click', () => {
      element('environment').value = 'native';
      fillModels();
      element('left').value = 'anchor';
      element('right').value = 'reinforced';
      element('arm').value = 'free';
      element('task').value = task;
      render();
    });
    element('example-links').append(button);
  }
}
element('environment').addEventListener('change', () => { fillModels(); render(); });
for (const key of ['arm', 'task', 'left', 'right']) element(key).addEventListener('change', render);
render();
