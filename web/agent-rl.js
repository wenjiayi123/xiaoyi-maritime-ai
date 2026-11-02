"use strict";
const API = "/api/harness/agent-rl";
const $ = (id) => document.getElementById(id);
let activeJob = null;
let requestId = null;
let modelRunnable = false;
const pct = (x) => x == null ? "—" : `${(x * 100).toFixed(1)}%`;
const names = { A_rules: "A · 固定规则", B_base: "B · 原始 1.7B", C_sft: "C · SFT", D_rl: "D · SFT＋RL", E_more_sft: "E · 继续 SFT" };
const stages = { training: "训练中", validation: "开发验证中", C_validation: "检查 SFT 基线", loading_model: "加载实验模型", verifying_exact_cache: "核验计算一致性", refining_checkpoint_selection: "检查中间模型版本", development_completed_test_unopened: "训练完成，独立测试尚未开始", selection_refined_test_unopened: "模型版本已选定，独立测试尚未开始", final_test: "独立测试中", completed_pending_audit: "独立测试完成，结果核验中", completed: "结果已核验", not_started: "尚未开始" };
async function api(path, options = {}) {
  const response = await fetch(API + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
  return data;
}
function cell(row, text) { const td = document.createElement("td"); td.textContent = text; row.append(td); }
async function refresh() {
  try {
    const data = await api("/status");
    const stage = data.status;
    const stageName = data.summary ? "结果已核验" : (stages[stage.stage] || stage.stage);
    $("status").textContent = `实验：${data.experiment} ｜${stageName}${stage.step ? ` · ${stage.step} 步` : ""}${stage.group || stage.phase ? ` · ${names[stage.group || stage.phase] || stage.group || stage.phase}` : ""} ｜${data.model_scope}`;
    if (!$("goal").value) $("goal").value = data.acceptance_goal;
    $("evidence-json").textContent = JSON.stringify({ config: data.config, partitions: data.manifest?.partitions, weights: data.summary?.weights, limitations: data.summary?.limitations }, null, 2);
    modelRunnable = Boolean(data.summary?.rl_parameters_changed);
    $("submit-task").disabled = !modelRunnable || Boolean(activeJob);
    const development = data.development;
    $("development").hidden = !development?.baseline;
    if (development?.baseline) {
      $("development-note").textContent = `${development.scope}。${development.test_opened ? "最终测试已按冻结检查点打开。" : "最终测试尚未打开。"}这里保留每个检查点的进步和退步。`;
      $("development-rows").replaceChildren();
      const baseline = development.baseline;
      const baseRow = document.createElement("tr");
      ["C · 冻结 SFT", "0", `${baseline.successes} / ${baseline.n}`, baseline.mean_reward.toFixed(3), pct(baseline.retention_accuracy)].forEach(x => cell(baseRow, x));
      $("development-rows").append(baseRow);
      for (const point of [...development.checkpoints].sort((a, b) => a.phase.localeCompare(b.phase) || a.step - b.step)) {
        const row = document.createElement("tr");
        [names[point.phase] || point.phase, point.step, point.excluded_by_retention ? "未测：回归检查未通过" : `${point.successes} / ${baseline.n}`, point.mean_reward == null ? "—" : point.mean_reward.toFixed(3), pct(point.retention)].forEach(x => cell(row, x));
        $("development-rows").append(row);
      }
    }
    if (data.summary) {
      const s = data.summary; $("groups").replaceChildren();
      $("group").querySelector('option[value="E_more_sft"]').disabled = !s.weights.more_sft;
      for (const key of Object.keys(names)) {
        const g = s.groups[key]; if (!g) continue; const row = document.createElement("tr");
        const matched = g.cases.reduce((n, c) => n + (c.parameter_matches || 0), 0);
        const parameterMetric = `${pct(g.parameter_accuracy)}（${matched}/${g.parameter_attempts} 次）`;
        [names[key], `${g.cases.filter(x => x.success).length} / ${g.n}`, pct(g.success_rate), parameterMetric, pct(g.recovery_rate), g.mean_steps.toFixed(1), pct(s.retention[key]?.accuracy), pct(s.independent_retention?.groups[key]?.accuracy)].forEach(x => cell(row, x));
        $("groups").append(row);
      }
      $("metrics").replaceChildren();
      for (const [label, value] of [["RL 相对 SFT 的实测增量", `${(s.rl_increment * 100).toFixed(1)} 个百分点`], ["独立测试规模", `${s.groups.D_rl.n} 个案例 / 8 类`], ["实际训练参数", s.trainable_parameters.toLocaleString()]]) {
        const block = document.createElement("div"); block.className = "metric";
        const caption = document.createElement("span"); caption.textContent = label;
        const number = document.createElement("strong"); number.textContent = value;
        block.append(caption, number); $("metrics").append(block);
      }
      $("figures").hidden = !data.figures_available;
      if (data.figures_available) {
        for (const chart of $("figures").querySelectorAll("img[data-src]")) {
          if (chart.dataset.independent && !s.independent_retention) { chart.closest("figure").hidden = true; continue; }
          const source = `${chart.dataset.src}?experiment=${encodeURIComponent(data.experiment)}`;
          if (chart.getAttribute("src") !== source) chart.setAttribute("src", source);
        }
      }
    }
  } catch (error) { $("status").textContent = `读取失败：${error.message}。请启动“语言模型RL实验”服务。`; }
}
function renderJob(job) {
  $("task-status").textContent = `执行记录 · ${names[job.group] || job.group} · 实验 ${job.experiment} · 任务 ${job.id}：${job.status} · ${job.steps.length} 步${job.elapsed_seconds ? ` · ${job.elapsed_seconds.toFixed(1)} 秒` : ""}${job.error ? ` · ${job.error}` : ""}`;
  $("executed-goal").hidden = false;
  $("executed-goal").textContent = `该记录的指令：${job.goal}`;
  $("trajectory").replaceChildren();
  for (const step of job.steps) {
    const item = document.createElement("li"); item.className = step.ok ? "" : "failed";
    const title = document.createElement("strong"); title.textContent = `${step.action.tool} ${JSON.stringify(step.action.arguments)}`;
    const origin = step.execution_origin === "actual_local_system_api" ? " · 原系统接口调用" : step.backend_executed ? " · 本机核验或报告工具" : step.native_executed ? " · 后端工具执行" : "";
    const detail = document.createElement("small"); detail.textContent = `${step.feedback}${step.fault_injection ? " · 明确注入的测试故障" : ""}${origin}`;
    item.append(title, detail); $("trajectory").append(item);
  }
  $("report-links").replaceChildren();
  if (job.status === "completed") {
    for (const [name, file] of [["查看任务报告", "report.html"], ["下载实际执行记录", "job.json"]]) {
      const link = document.createElement("a"); link.textContent = name; link.href = `${API}/tasks/${encodeURIComponent(job.id)}/files/${file}`; link.target = "_blank"; link.rel = "noopener"; $("report-links").append(link);
    }
  }
}
async function pollJob() {
  if (!activeJob) return;
  try {
    const job = await api(`/tasks/${encodeURIComponent(activeJob)}`); renderJob(job);
    if (["completed", "failed"].includes(job.status)) { localStorage.setItem("xiaoyi-agent-rl-last-job", job.id); activeJob = null; requestId = null; localStorage.removeItem("xiaoyi-agent-rl-active-job"); $("submit-task").disabled = !modelRunnable; return; }
  } catch (error) { $("task-status").textContent = `读取任务状态失败：${error.message}；保留任务编号并继续查询。`; }
  setTimeout(pollJob, 2500);
}
$("task-form").addEventListener("submit", async (event) => {
  event.preventDefault(); if (activeJob) return;
  requestId ||= `arl_${crypto.randomUUID().replaceAll("-", "")}`;
  $("submit-task").disabled = true;
  try {
    const job = await api("/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goal: $("goal").value, group: $("group").value, inject_read_fault: $("inject-fault").checked, request_id: requestId }) });
    activeJob = job.id; localStorage.setItem("xiaoyi-agent-rl-active-job", activeJob); renderJob(job); pollJob();
  } catch (error) { $("task-status").textContent = error.message; $("submit-task").disabled = !modelRunnable; }
});
const savedJob = localStorage.getItem("xiaoyi-agent-rl-active-job") || localStorage.getItem("xiaoyi-agent-rl-last-job");
if (savedJob && /^arj-[a-f0-9]{32}$/.test(savedJob)) { activeJob = savedJob; pollJob(); }
refresh();
setInterval(refresh, 15000);
