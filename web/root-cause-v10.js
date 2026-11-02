"use strict";
const $ = id => document.getElementById(id);
const pct = v => `${(v * 100).toFixed(4)}%`;
const num = v => v == null ? "—" : Number(v).toFixed(4);
const scenarios = { normal: "常态", demand_surge: "需求突增", resource_outage: "资源故障", publication_delay: "发布延迟" };
let catalog, receipt;
function text(parent, content, tag = "p") { const e = document.createElement(tag); e.textContent = content; parent.append(e); return e; }
function row(id, values) { const tr = document.createElement("tr"); for (const v of values) text(tr, String(v), "td"); $(id).append(tr); }
async function request(endpoint, body) {
  const r = await fetch(`/api/harness/root-cause-v10/${endpoint}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  const data = await r.json(); if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)); return data;
}
function render(data) {
  catalog = data; const s = data.summary;
  $("status").textContent = data.current ? "冻结证据与当前实现一致 · 验收门槛未降低" : "代码或证据变化，暂停重算";
  for (const c of s.priorities) { const card = document.createElement("article"); card.className = "metric"; text(card, c.name, "h3"); text(card, `${c.previous_score} → ${c.score}`, "strong"); text(card, c.verdict); $("metrics").append(card); }
  for (const finding of s.findings) text($("root-findings"), finding);
  for (const ref of s.references) { const p = document.createElement("p"); const a = document.createElement("a"); a.href = ref.url; a.textContent = ref.title; a.rel = "noopener noreferrer"; p.append(a); $("references").append(p); }
  for (const [key, v] of Object.entries(s.oracle)) row("oracle", [scenarios[key], `${v.exactly_optimal_baseline_windows}/${v.windows}`, pct(v.mean_gain_upper_bound), pct(v.maximum_gain_upper_bound)]);
  const rl = s.rl.candidate;
  $("rl-result").textContent = `可执行候选相对强MPC收益 ${pct(rl.relative_cost_interval.mean_delta)}；95%港口簇区间 ${rl.relative_cost_interval.port_cluster_ci95.map(pct).join(" 至 ")}。${rl.research_admission ? "研究门槛通过，仍无生产授权。" : "未通过收益准入，不提升为已验证收益策略。"}`;
  $("annual-method").textContent = s.annual.description;
  for (const [method, v] of Object.entries(s.annual.summary)) row("annual-summary", [method === "v9_global" ? "V9全年最差季区间" : "V10冻结季度区间", `${v.annual_passed}/${v.annual_total}`, `${v.quarters_passed}/${v.quarters_total}`, `${v.annual_and_all_quarters}/${v.annual_total}`, num(v.mean_wis)]);
  for (const c of s.annual.cells.filter(c => c.method === "v10_selected")) {
    const old = s.annual.cells.find(r => r.station_id === c.station_id && r.method === "v9_global");
    const count = v => Object.values(v.quarters).filter(q => q.passed).length;
    row("annual-sites", [c.site, `${count(old)}/4 → ${count(c)}/4`, c.annual.passed ? "通过" : "未通过", num(c.annual.mae_m), c.annual.coverage90 == null ? "—" : pct(c.annual.coverage90), num(c.annual.max_width90_m)]);
    const o = document.createElement("option"); o.value = c.station_id; o.textContent = c.site; $("station").append(o);
  }
  for (const c of data.scorecard.components) row("components", [c.name, `${c.previous_score} → ${c.score}`, c.limitation_attribution.category, c.limitation_attribution.verdict]);
  $("run").disabled = !data.current; $("export").disabled = false;
}
function chart(parent, rows) {
  const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 760 250"); svg.style.width = "100%"; svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "24小时潮位：灰色为旧区间，绿色为新季度区间，共用同一条点预测；米，MLLW基准，UTC时间");
  const lo = Math.min(...rows.flatMap(r => [r.lower90, r.v9_lower90])), hi = Math.max(...rows.flatMap(r => [r.upper90, r.v9_upper90]));
  const x = i => 65 + i * 665 / 23, y = v => 200 - (v - lo) * 155 / Math.max(.01, hi - lo);
  function shape(type, attrs, label) { const n = document.createElementNS(ns, type); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v)); if (label) n.textContent = label; svg.append(n); }
  for (const [lower, upper, fill] of [["v9_lower90", "v9_upper90", "#8ba1b43f"], ["lower90", "upper90", "#67ddbb66"]]) shape("polygon", { points: [...rows.map((r, i) => `${x(i)},${y(r[upper])}`), ...rows.map((r, i) => `${x(i)},${y(r[lower])}`).reverse()].join(" "), fill });
  shape("polyline", { points: rows.map((r, i) => `${x(i)},${y(r.prediction)}`).join(" "), fill: "none", stroke: "#6ce2cf", "stroke-width": 2.5 });
  shape("text", { x: 65, y: 20, fill: "#b4c8d2", "font-size": 12 }, "灰：旧区间 · 绿：新季度区间 · 潮位 / MLLW 米 · UTC");
  for (const v of [lo, (lo + hi) / 2, hi]) shape("text", { x: 5, y: y(v) + 4, fill: "#b4c8d2", "font-size": 12 }, v.toFixed(2));
  for (const i of [0, 6, 12, 18, 23]) shape("text", { x: x(i), y: 225, fill: "#b4c8d2", "font-size": 12, "text-anchor": "middle" }, rows[i].time.slice(11, 16));
  parent.append(svg);
}
$("run").addEventListener("click", async () => {
  $("run").disabled = true; const result = $("annual-receipt"); result.textContent = "正在重算数值模型…";
  try {
    receipt = await request("annual", { station_id: $("station").value, day: $("day").value }); result.replaceChildren();
    text(result, receipt.status === "hold" ? "暂停研究使用" : "全年与四季通过，仅用于归档研究", "h3");
    if (receipt.rows) { text(result, `${receipt.site} · 本次重算未调用语言模型 · ${receipt.rows.length}个小时。`); chart(result, receipt.rows); }
    else text(result, "历史观测或校准不足；本轮保留为失败站点，不补造预测。");
    const details = document.createElement("details"); text(details, "完整计算回执", "summary"); const pre = text(details, JSON.stringify(receipt, null, 2), "pre"); pre.style.whiteSpace = "pre-wrap"; pre.style.overflowWrap = "anywhere"; result.append(details);
  } catch (error) { result.textContent = `未完成：${error.message}`; }
  finally { $("run").disabled = !catalog?.current; }
});
$("export").addEventListener("click", () => { const url = URL.createObjectURL(new Blob([JSON.stringify({ catalog, receipt }, null, 2)], { type: "application/json" })); const a = document.createElement("a"); a.href = url; a.download = "xiaoyi-root-cause-v10.json"; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); });
request("catalog").then(render).catch(error => { $("status").textContent = `证据不可用：${error.message}`; });
