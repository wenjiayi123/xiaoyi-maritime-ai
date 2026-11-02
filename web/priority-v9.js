"use strict";
const $ = id => document.getElementById(id);
const labels = { aci90: "分港滚动自适应（冻结选型）", global_v8: "V8 跨港统一区间", local_frozen: "分港固定校准（简单对照）", "constrained.reserve": "约束内训练 RL", "former.reserve": "原 RL＋外部过滤", "constrained.stochastic28.reserve": "同分布约束随机 MPC", "constrained_seed.stochastic28.reserve": "同重采样约束随机 MPC" };
let catalog = null;
const receipts = {};
const pct = v => v == null ? "—" : `${(v * 100).toFixed(2)}%`;
const num = v => v == null ? "—" : Number(v).toFixed(4);
const reasons = {
  monitor_not_ready_or_undercoverage: "已公布误差样本不足或近期覆盖不足", interval_too_wide: "区间过宽",
  observed_demand_shift: "已观测到需求突变", missing_input_or_truth: "必需的历史输入缺失",
  insufficient_local_residuals: "本港历史误差不足", positive_port_cluster_ci: "港口簇收益区间下界未大于零",
  gain_not_concentrated: "缺少跨港分散的正收益", no_excess_over_max_capacity: "仍有超过最大产能对照的约束违规",
  no_mean_port_regression: "存在港口平均退化", stress_noninferiority: "压力场景退化", no_feasible_window_violation: "可行窗口仍有违规"
};
function row(parent, values) {
  const tr = document.createElement("tr");
  for (const value of values) { const td = document.createElement("td"); td.textContent = String(value); tr.append(td); }
  $(parent).append(tr);
}
function option(parent, value, text) { const item = document.createElement("option"); item.value = value; item.textContent = text; $(parent).append(item); }
async function request(path, body) {
  const response = await fetch(`/api/harness/priority-v9/${path}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
  return data;
}
function render(data) {
  catalog = data;
  $("status").textContent = data.current ? "证据摘要与当前代码一致 · 研究回放可用 · 生产权限关闭" : "证据或代码发生变化，已暂停重算。";
  const items = data.summary.priorities;
  for (const item of items) {
    const card = document.createElement("article"); card.className = "metric";
    const title = document.createElement("h3"); title.textContent = item.name;
    const score = document.createElement("strong"); score.textContent = `${item.previous_score} → ${item.score}`;
    const text = document.createElement("p"); text.textContent = item.verdict;
    card.append(title, score, text); $("metrics").append(card);
  }
  for (const r of data.forecast.summary) row("forecast-methods", [labels[r.method] || r.method, `${r.joint_pass}/${r.cells}`, pct(r.worst_coverage), num(r.mean_width), num(r.mean_normalized_wis), `${pct(r.retained / r.expected)} (${r.retained}/${r.expected})`]);
  for (const p of data.ports) option("port", p.id, p.name);
  for (const r of data.rl.aggregate) {
    const interval = r.relative_cost_interval;
    row("rl-methods", [labels[r.algorithm] || r.algorithm, pct(interval.mean_delta), interval.port_cluster_ci95.map(pct).join(" 至 "), pct(r.override_fraction), r.research_admission ? "通过" : "未通过"]);
  }
  const candidate = data.rl.aggregate.find(r => r.algorithm === "constrained.reserve");
  $("rl-verdict").textContent = candidate.research_admission ? "候选通过本次离线研究门槛，仍无生产授权。" : `RL收益准入未通过。强基线：${labels[candidate.matched_baseline] || candidate.matched_baseline}。失败项：${Object.entries(candidate.checks).filter(([, v]) => !v).map(([k]) => reasons[k] || k).join("；")}。`;
  for (const c of data.annual.cells.filter(c => c.method === "v9")) {
    const old = data.annual.cells.find(r => r.method === "legacy_v7_rule" && r.station_id === c.station_id);
    const tally = v => `${v.annual.passed ? "通过" : "未过"} / ${Object.values(v.quarters).filter(q => q.passed).length}/4`;
    row("annual-cells", [c.site, tally(old), tally(c), num(c.annual.mae_m), pct(c.annual.coverage90), num(c.annual.max_width90_m), pct(c.annual.availability)]);
    option("station", c.station_id, c.site);
  }
  for (const c of data.scorecard.components) row("score-rows", [c.name, `${c.previous_score} → ${c.score}`, c.score_change_reason]);
  for (const ref of data.summary.references) {
    const p = document.createElement("p"); const link = document.createElement("a"); link.textContent = ref.title; link.href = ref.url; link.rel = "noopener noreferrer"; p.append(link); $("references").append(p);
  }
  document.querySelectorAll("[data-compute]").forEach(b => { b.disabled = !data.current; });
  $("export").disabled = false;
}
function textBlock(parent, text, tag = "p") { const item = document.createElement(tag); item.textContent = text; parent.append(item); return item; }
function tideChart(parent, rows) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 760 240"); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "24小时潮位预测及90%区间，横轴为UTC小时，纵轴为MLLW米");
  svg.style.width = "100%";
  const low = Math.min(...rows.map(r => r.lower90)), high = Math.max(...rows.map(r => r.upper90));
  const x = i => 64 + i * 670 / (rows.length - 1);
  const y = value => 190 - (value - low) * 155 / Math.max(0.01, high - low);
  const shape = (type, attrs) => { const item = document.createElementNS(ns, type); Object.entries(attrs).forEach(([k, v]) => item.setAttribute(k, String(v))); svg.append(item); return item; };
  shape("polygon", { points: [...rows.map((r, i) => `${x(i)},${y(r.upper90)}`), ...rows.map((r, i) => `${x(i)},${y(r.lower90)}`).reverse()].join(" "), fill: "#5dd5c044" });
  shape("polyline", { points: rows.map((r, i) => `${x(i)},${y(r.prediction)}`).join(" "), fill: "none", stroke: "#6ce2cf", "stroke-width": 2.5 });
  for (const value of [low, (low + high) / 2, high]) { const item = shape("text", { x: 6, y: y(value) + 4, fill: "#b4c8d2", "font-size": 12 }); item.textContent = value.toFixed(2); }
  for (const i of [0, 6, 12, 18, 23]) { const item = shape("text", { x: x(i), y: 214, fill: "#b4c8d2", "font-size": 12, "text-anchor": "middle" }); item.textContent = rows[i].time.slice(11, 16); }
  const axis = shape("text", { x: 64, y: 18, fill: "#b4c8d2", "font-size": 12 }); axis.textContent = "潮位 / MLLW 米 · 阴影：90%名义区间 · 时间：UTC";
  parent.append(svg);
}
function showReceipt(kind, data) {
  const parent = $(`${kind}-result`); parent.replaceChildren();
  textBlock(parent, data.status === "hold" ? "暂停研究使用" : "仅可用于公开归档研究回放", "h3");
  if (kind === "forecast") {
    textBlock(parent, `决策日 ${data.origin} → 目标日 ${data.target}；只使用截至 ${data.publication_cutoff} 的已公布观测。`);
    if (data.prediction) {
      textBlock(parent, `日活动指标点估计：${num(data.prediction.point)}`);
      textBlock(parent, Object.entries(data.prediction.intervals).map(([level, limits]) => `${Math.round(Number(level) * 100)}%区间 ${num(limits[0])} 至 ${num(limits[1])}`).join("；"));
      textBlock(parent, `近期已实现样本覆盖率：${pct(data.monitor_coverage90)}；监控样本：${data.monitor_samples}。`);
    }
    if (data.reasons?.length) textBlock(parent, `原因：${data.reasons.map(r => reasons[r] || r).join("；")}。`);
  } else if (data.rows) {
    const failed = Object.entries(data.quarter_checks).filter(([, q]) => !q.passed).map(([q]) => `第${q}季度`);
    textBlock(parent, `${data.site} · 全年${data.annual_checks.passed ? "通过" : "未通过"}；${failed.length ? `${failed.join("、")}未通过，保持暂停。` : "四个季度均通过。"}`);
    textBlock(parent, `全年误差 ${num(data.annual_checks.mae_m)} m；覆盖 ${pct(data.annual_checks.coverage90)}；最大区间宽度 ${num(data.annual_checks.max_width90_m)} m。`);
    tideChart(parent, data.rows);
  } else textBlock(parent, "历史校准季度的合格观测不足，未生成年度预测模型。不能用补值代替真实验证。");
  const details = document.createElement("details"); textBlock(details, "查看完整计算回执", "summary");
  const raw = textBlock(details, JSON.stringify(data, null, 2), "pre"); raw.style.whiteSpace = "pre-wrap"; raw.style.overflowWrap = "anywhere"; parent.append(details);
}
async function run(kind, button, body) {
  button.disabled = true; $(`${kind}-result`).textContent = "正在实际重算…";
  try { const data = await request(kind, body); receipts[kind] = data; showReceipt(kind, data); }
  catch (error) { $(`${kind}-result`).textContent = `未完成：${error.message}`; }
  finally { button.disabled = !catalog?.current; }
}
$("run-forecast").addEventListener("click", event => run("forecast", event.currentTarget, { port_id: $("port").value, origin: $("origin").value, horizon: Number($("horizon").value), fault: $("fault").value }));
$("run-annual").addEventListener("click", event => run("annual", event.currentTarget, { station_id: $("station").value, day: $("annual-day").value }));
$("export").addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify({ catalog, receipts }, null, 2)], { type: "application/json" }));
  const link = document.createElement("a"); link.href = url; link.download = "xiaoyi-priority-v9-evidence.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
request("catalog").then(render).catch(error => { $("status").textContent = `证据不可用：${error.message}`; });
