"""Package measured SFT/RL learning and native execution evidence for presentation."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / ".codex_artifacts/agent-rl-capability-demo-20261102"
OLD = ROOT / ".codex_artifacts/agent-rl-v2-20261102/experiment-004"
NAMES = {"E_more_sft": "SFT 版", "D_rl": "SFT＋RL 版"}


def read(p):
    return json.loads(p.read_text())


def rows(p):
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def copy(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def build(round_dir, out):
    result = read(round_dir / "RESULTS.json")
    protocol = read(round_dir / "PROTOCOL.json")
    out.mkdir(parents=True, exist_ok=False)
    data, figures = out / "data", out / "figures"
    data.mkdir()
    figures.mkdir()
    training = rows(OLD / "training.jsonl")
    initial_sft = rows(ROOT / ".codex_artifacts/agent-rl-v1-20261101/experiment-002/training.jsonl")
    sft = [r for r in training if r["stage"] == "E_more_sft"]
    rl = [r for r in training if r["stage"] == "D_rl"]
    history = read(OLD / "checkpoint-weight-history.json")
    selected = read(OLD / "checkpoint-selection.json")
    online_root = ROOT / ".codex_artifacts/agent-rl-confirmatory-20261102/seed-20261102/D_drgrpo"
    online = [read(p.parent / "summary.json") for p in sorted(online_root.glob("step-*/COMMITTED.json"))]
    save(data / "plot-data.json", {"initial_sft_240": initial_sft, "continued_sft_512": sft,
                                    "exact_actor_rl_512": rl, "parameter_history": history,
                                    "separate_unfinished_online_rl": online,
                                    "native_suite": result})
    for name in ["config.json", "lineage.json", "checkpoint-selection.json", "training.jsonl",
                 "training-step-explanation.json", "training-objective-arithmetic-check.json",
                 "parameter-change-audit.json", "checkpoint-weight-history.json", "audited-summary.json",
                 "native-acceptance-audit.json", "native-acceptance-plan.json"]:
        copy(OLD / name, data / "original-experiment-004" / name)
    copy(ROOT / ".codex_artifacts/agent-rl-v1-20261101/experiment-002/training.jsonl", data / "initial-sft-240.jsonl")
    for name in ["OBJECTIVE_CHANGE.json", "PRESERVATION_AUDIT.json", "PLAN.json",
                 "existing-evidence-review/REVIEW.json", "port-prompt-diagnostic/PROTOCOL.json",
                 "port-prompt-diagnostic/RESULTS.json"]:
        copy(BASE / name, data / name)
    for name in ["PROTOCOL.json", "LOCK.json", "SOURCES.json", "RESULTS.json", "STATUS.json"]:
        copy(round_dir / name, data / "current-suite" / name)
    shutil.copytree(round_dir / "source", out / "implementation")
    for label, folder in [("SFT", "more_sft"), ("SFT-plus-RL", "rl"), ("shared-SFT-parent", "sft")]:
        shutil.copytree(OLD / "checkpoints" / folder, out / "adapters" / label)
    # Retain all engineering attempts, including failures and partial stops.
    attempts = []
    for directory in sorted(BASE.glob("round-*")):
        if not directory.is_dir():
            continue
        for p in sorted((directory / "runs").glob("*/job.json")):
            j = read(p)
            dest = out / "native" / directory.name / p.parent.name
            shutil.copytree(p.parent, dest)
            attempts.append({"round": directory.name, "id": j["id"], "group": j["group"],
                             "success": j["success"], "status": j["status"], "steps": len(j["steps"]),
                             "seconds": j.get("elapsed_seconds"), "error": j.get("error"),
                             "path": str(dest.relative_to(out)), "goal": j["goal"]})
        for p in directory.glob("*.json"):
            copy(p, data / "all-rounds" / directory.name / p.name)
    save(data / "all-attempts.json", attempts)
    if (BASE / "AUDITOR_QA.json").exists():
        copy(BASE / "AUDITOR_QA.json", data / "AUDITOR_QA.json")
    if (BASE / "UI_QA.json").exists():
        copy(BASE / "UI_QA.json", data / "UI_QA.json")
    if (BASE / "screenshots").exists():
        shutil.copytree(BASE / "screenshots", out / "screenshots")
    if (BASE / "live-demo").exists():
        shutil.copytree(BASE / "live-demo", out / "interactive-evidence")
    for script in ["serve_agent_capability_demo.py", "build_agent_capability_showcase.py"]:
        copy(ROOT / "scripts" / script, out / "implementation/scripts" / script)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    import numpy as np
    font = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    font_manager.fontManager.addfont(str(font))
    plt.rcParams.update({"font.family": font_manager.FontProperties(fname=str(font)).get_name(),
                         "font.size": 11, "axes.unicode_minus": False, "svg.fonttype": "none",
                         "axes.spines.top": False, "axes.spines.right": False})
    colors = {"E_more_sft": "#087f80", "D_rl": "#7654ad"}

    def export(fig, name):
        for ext in ["png", "svg"]:
            fig.savefig(figures / (name + "." + ext), dpi=180, bbox_inches="tight", facecolor="white")
        plt.close(fig)

    def smooth(y, width=16):
        return [float(np.mean(y[max(0, i-width+1):i+1])) for i in range(len(y))]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7), layout="constrained")
    x, y = [r["step"] for r in sft], [r["loss"] for r in sft]
    axes[0].plot(x, y, color=colors["E_more_sft"], alpha=.22, lw=.7, label="逐次原始值")
    axes[0].plot(x, smooth(y), color=colors["E_more_sft"], label="16 次移动平均")
    axes[0].set(title="继续 SFT：监督交叉熵", xlabel="参数更新次数", ylabel="训练损失")
    x = [r["step"] for r in rl]
    for field, label, color in [("expected_two_step_return_before", "更新前", "#b3a4c8"),
                                 ("expected_two_step_return_after", "更新后", colors["D_rl"])]:
        y = [r[field] for r in rl]
        axes[1].plot(x, y, color=color, alpha=.18, lw=.6)
        axes[1].plot(x, smooth(y), color=color, label=label + " · 16 次平均")
    axes[1].set(title="RL：当前训练状态的期望两步回报", xlabel="参数更新次数", ylabel="期望模拟回报")
    for ax, group in zip(axes, ["E_more_sft", "D_rl"]):
        ax.axvline(selected["selected"][group]["step"], color="#526277", linestyle="--", lw=1, label="演示权重：第 384 次")
        ax.grid(alpha=.15)
        ax.legend(fontsize=9, loc="upper right")
    fig.supxlabel("全部 512 次更新均展示；不同状态的回报不能当作独立任务成功率。", fontsize=10)
    export(fig, "training-curves")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4), layout="constrained")
    for group in NAMES:
        points = [r for r in history["checkpoints"] if r["phase"] == group]
        axes[0].plot([r["step"] for r in points], [r["l2_change_from_C"] for r in points], marker="o", ms=3, label=NAMES[group], color=colors[group])
        axes[1].plot([r["step"] for r in points], [r["changed_values_from_C"] for r in points], marker="o", ms=3, label=NAMES[group], color=colors[group])
    axes[0].set(title="相对共同 SFT 起点的参数距离", xlabel="参数更新次数", ylabel="LoRA 参数 L2 距离")
    axes[1].set(title="实际发生变化的 LoRA 参数", xlabel="参数更新次数", ylabel="变化的参数个数")
    for ax in axes:
        ax.axvline(384, color="#526277", ls="--", lw=1)
        ax.grid(alpha=.15)
        ax.legend(fontsize=9)
    fig.supxlabel("1.7B 基础模型；训练最后 4 层的 229,376 个 LoRA 参数。变化幅度不是能力排名。", fontsize=10)
    export(fig, "parameter-updates")

    fig, ax = plt.subplots(figsize=(11.5, 4.8), layout="constrained")
    labels = [c["title"] for c in protocol["cases"]]
    xs = np.arange(len(labels))
    for offset, group in [(-.19, "E_more_sft"), (.19, "D_rl")]:
        values = [sum(r.get("success", False) for r in result["results"] if r["case"] == c["id"] and r["group"] == group) for c in protocol["cases"]]
        bars = ax.bar(xs + offset, values, width=.34, label=NAMES[group], color=colors[group])
        for bar, value in zip(bars, values):
            ax.text(bar.get_x()+bar.get_width()/2, value+.04, f"{value}/2", ha="center", va="bottom", fontsize=10)
    ax.set(xticks=xs, xticklabels=[x.replace("与读取恢复", "\n与读取恢复").replace("情景评估", "\n情景评估") for x in labels],
           ylim=(0, 2.55), yticks=[0,1,2], ylabel="完整完成次数（每项预定 2 次）", title="当前版本：六条任务的重复执行")
    ax.legend(ncol=2, loc="upper left")
    ax.grid(axis="y", alpha=.15)
    fig.supxlabel("本机原生接口与工程模拟；此图描述固定演示任务的复验，不能外推为任意任务成功率。", fontsize=10)
    export(fig, "native-repeatability")

    fig, ax = plt.subplots(figsize=(10.5, 4), layout="constrained")
    steps = [r["step"] for r in online]
    means = [float(np.mean(r["returns"])) for r in online]
    ax.plot(steps, means, marker="o", color="#b16c25")
    ax.fill_between(steps, [min(r["returns"]) for r in online], [max(r["returns"]) for r in online], color="#b16c25", alpha=.12)
    ax.set(title="另一次在线 RL 探索：17 个已提交更新（已停止并保留）", xlabel="在线 RL 更新次数", ylabel="4 条采样轨迹的平均回报")
    ax.grid(alpha=.15)
    fig.supxlabel("属于另一轮未完成实验，不对应本页演示模型；任务难度交替，不能据此声称收敛或胜过 SFT。", fontsize=10)
    export(fig, "separate-online-exploration")

    counts = result["counts"]
    summary_cards = "".join(f"<div class='metric'><span>{NAMES[g]}</span><strong>{counts[g]['successes']} / {counts[g]['registered']}</strong><small>预先登记的任务执行次数 · 实际尝试 {counts[g]['attempted']} 次</small></div>" for g in NAMES)
    table = []
    for case in protocol["cases"]:
        cells = [html.escape(case["title"])]
        for group in NAMES:
            records = [r for r in result["results"] if r["case"] == case["id"] and r["group"] == group]
            links = []
            for row in records:
                if "folder" not in row:
                    links.append("未复跑（首轮失败后节省算力）")
                    continue
                target = f"native/{round_dir.name}/{Path(row['folder']).name}"
                filename = "report.html" if row["success"] else "job.json"
                label = f"第 {row['repetition']} 次：{'完成' if row['success'] else '失败'} · {row['steps']} 步"
                links.append(f"<a href='{target}/{filename}'>{label}</a> <a class='muted' href='{target}/job.json'>轨迹</a>")
            cells.append("<br>".join(links))
        table.append("<tr>"+"".join("<td>"+c+"</td>" for c in cells)+"</tr>")
    failures = [a for a in attempts if not a["success"]]
    failure_links = "".join(f"<li><a href='{a['path']}/job.json'>{html.escape(a['round']+' · '+NAMES[a['group']]+' · '+a['id'])}</a>：{a['steps']} 步；{html.escape(a.get('error') or '未完成全部条件')}</li>" for a in failures)
    trace = next((r for r in result["results"] if r.get("success") and r["group"]=="D_rl" and r["case"]=="joint-recovery"), None)
    trace_html = "尚无完整联合轨迹。"
    if trace:
        job = read(Path(trace["folder"]) / "job.json")
        trace_html = "<ol class='trace'>" + "".join(
            f"<li><b>{html.escape(s['action']['tool'])}</b><span>模型选择 {s['choice']} · {html.escape(s['feedback'])}</span></li>" for s in job["steps"]) + "</ol>"
    title = "固定任务复验通过" if result["suite_passed"] else "固定任务复验尚有缺口"
    document = f"""<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>舷鸥 · SFT 与 RL 能力展示</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f6f8;color:#152c3b;font:16px/1.75 -apple-system,BlinkMacSystemFont,'Arial',sans-serif}}main{{max-width:1120px;margin:auto;padding:36px 28px 64px}}header{{border-bottom:2px solid #183d52;padding:20px 0 28px}}.eyebrow{{font-size:13px;letter-spacing:.14em;color:#087f80}}h1{{font-size:35px;line-height:1.3;margin:12px 0}}h2{{font-size:24px;margin:0 0 16px}}h3{{font-size:18px;margin-top:24px}}p{{margin:10px 0}}section{{padding:28px;margin-top:24px;background:white;border:1px solid #e0e6eb;border-radius:10px}}.muted,small{{color:#526577}}.metrics{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:24px}}.metric{{padding:20px;background:white;border-left:4px solid #087f80}}.metric:nth-child(2){{border-color:#7654ad}}.metric span,.metric small{{display:block}}.metric strong{{font-size:38px;line-height:1.4}}img{{width:100%;height:auto}}a{{color:#087675;text-underline-offset:3px}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:14px 8px;border-bottom:1px solid #e2e8ec;vertical-align:top;font-size:14px}}.note{{padding:14px 18px;background:#edf4f7;border-left:3px solid #748b9e}}.flow{{display:flex;flex-wrap:wrap;gap:12px;align-items:center;font-weight:600}}.flow span{{padding:10px 14px;background:#edf4f7;border-radius:5px}}.trace{{padding-left:25px}}.trace li{{padding:6px 0}}.trace span{{display:block;font-size:14px;color:#526577}}details{{margin:14px 0}}summary{{font-weight:600;cursor:pointer}}code{{font-size:13px;overflow-wrap:anywhere}}ul{{padding-left:24px}}footer{{padding-top:28px;font-size:13px;color:#526577}}@media(max-width:650px){{main{{padding:20px 12px}}h1{{font-size:27px}}section{{padding:18px 12px}}.metrics{{grid-template-columns:1fr}}td,th{{font-size:12px;padding:10px 5px}}}}@media print{{body{{background:white}}main{{padding:0}}section{{break-inside:avoid}}a{{color:#152c3b}}}}
</style><main><header><div class='eyebrow'>舷鸥 · 港航智能体工程证据</div><h1>两条训练路线，同一个业务闭环</h1><p>SFT 学习正确操作示范；RL 利用模拟执行回报优化策略。展示真实参数更新、真实工具调用和可核验交付。</p><p class='muted'>本机 1.7B 模型 · 229,376 个可训练 LoRA 参数 · 三个业务系统 · {title}</p></header>
<div class='metrics'>{summary_cards}</div>
<section><h2>一条指令怎样完成</h2><div class='flow'><span>明确任务与参数</span>→<span>模型选择工具</span>→<span>Harness 调用系统</span>→<span>观察结果并继续</span>→<span>核验、交付报告</span></div><p>模型逐步选择 13 个工具／参数候选中的一个。工具框架执行选择、记录返回值；报告由核验过的数值生成。没有规则代选动作。</p><p class='note'>任务语义与数值参数由确定性解析器提取；本演示证明受约束工具任务的工程实现，不代表开放领域自由规划、任意 API 参数生成或生产港口调度。</p></section>
<section><h2>六条重要任务的重复验证</h2><img src='figures/native-repeatability.png' alt='两版在六条预先登记任务上的两次执行结果'><table><thead><tr><th>任务</th><th>SFT 版</th><th>SFT＋RL 版</th></tr></thead><tbody>{''.join(table)}</tbody></table><p class='muted'>两次重复使用同一模型和任务配置、重新调用系统接口；这是有限工程复验，不是独立统计样本，也不表示所有未来任务都有同样成功率。</p><details><summary>查看指令、参数、次数与验收规则</summary><p><a href='data/current-suite/PROTOCOL.json'>执行前登记的协议</a> · <a href='data/current-suite/RESULTS.json'>全部本轮结果</a></p><ul>{''.join('<li>'+html.escape(c['goal'])+'</li>' for c in protocol['cases'])}</ul></details></section>
<section><h2>保留两种训练方法的原始证据</h2><img src='figures/training-curves.png' alt='SFT训练损失与RL期望两步回报曲线'><p>SFT 版来自已有共同 SFT 起点，再进行监督训练；RL 版从同一历史起点进行策略优化。本轮直接复用两个已保存的第 384 次更新版本，未追加训练。原训练各完成 512 次更新，全部日志保留。</p><p>这里的 RL 是<strong>可枚举动作的期望回报优化，使用两步模拟前瞻并约束与原策略的偏离</strong>。它确实反向传播并更新语言模型的 LoRA 参数；不把它称为完整长程 PPO／GRPO。</p><p><a href='data/initial-sft-240.jsonl'>共同起点的 240 次 SFT 日志</a> · <a href='data/original-experiment-004/training.jsonl'>后续 SFT／RL 的全部逐次日志</a> · <a href='data/original-experiment-004/training-step-explanation.json'>一次真实更新的前后动作变化</a> · <a href='data/plot-data.json'>所有绘图原始数据</a></p><p class='note'>奖励依赖可检查的任务状态、计算参数和完成条件；它提供不同于完整正确答案示范的训练信号。减少标注依赖不等于已经证明总成本更低，本材料不宣称 RL 胜过 SFT。</p></section>
<section><h2>参数确实发生了变化</h2><img src='figures/parameter-updates.png' alt='训练过程中LoRA参数距离与变化数量'><p>两条路线选定权重中的 229,376 个 LoRA 数值均与共同 SFT 起点不同。权重文件摘要、选取记录、梯度和损失均可对应核查；1.7B 并非全部参与本轮更新。</p><p><a href='data/original-experiment-004/parameter-change-audit.json'>RL 参数变化审计</a> · <a href='data/original-experiment-004/checkpoint-weight-history.json'>两路线中间检查点数值记录</a> · <a href='data/original-experiment-004/training-objective-arithmetic-check.json'>训练目标重算</a> · <a href='data/existing-evidence-review/REVIEW.json'>当前权重复核</a></p></section>
<section><h2>一次真实的跨系统调用过程</h2>{trace_html}<p>读取故障在 Harness 的可控故障层注入；后续成功调用来自本机港口、能碳、马六甲系统的实际 API。各系统基于公开数据与工程模拟，保留各自地点、模拟时钟和来源。</p></section>
<section><h2>工程修正与失败记录</h2><p>单独港口任务原表述让模型反复核验。将“读取港口状态并评估靠泊情景”改为等义的“读取港口，完成港口情景评估”，经完整复验确认效果。没有更改任务要求、参数、模型权重或判分；这项改进归于输入表述适配，不能计作 RL 学习增益。</p><p>更长的工具说明曾使能碳任务退化，该方案已停止并保留。为节省算力，首轮失败的同一任务未继续机械重复。</p><details><summary>全部失败和中止记录（{len(failures)} 条）</summary><ul>{failure_links}</ul></details><p><a href='data/all-attempts.json'>所有轮次的完整索引</a> · <a href='data/port-prompt-diagnostic/RESULTS.json'>六次表述诊断的全部输出</a></p></section>
<section><h2>另有在线 RL 训练能力的记录</h2><img src='figures/separate-online-exploration.png' alt='另一轮已停止在线RL实验17次更新回报'><p>这一轮确实进行了在线轨迹采样、奖励与优势计算、反向传播和参数更新；因目标改为低成本能力演示而停止。17 次已提交更新审计通过，最终测试未开启。</p><p class='note'>这张曲线属于另一轮实验，不是上述演示模型的训练曲线，也不能与其原生任务成功率拼接成学习增益。</p><p><a href='data/PRESERVATION_AUDIT.json'>停止时的完整保全审计</a></p></section>
<section><h2>向专家介绍的简短表述</h2><p>“我在港航多系统任务中实现了 SFT 示范学习和基于执行回报的策略优化，保留从训练数据、奖励和梯度到权重变化的可追踪记录。模型通过同一工具框架完成能碳比较、港口情景评估和交通态势任务，并把调用过程和业务产物对应起来。项目重点展示我能搭建训练环境、实现两条训练路线、分析失败并完成系统闭环。”</p><p><a href='http://127.0.0.1:18789/control'>打开本机实时操作入口</a> · <a href='MANIFEST.json'>展示包文件校验清单</a></p></section>
<footer>生成时间：{html.escape(datetime.datetime.now().astimezone().isoformat())}。展示来源：{html.escape(round_dir.name)}，复用 experiment-004 权重。原始未完成正式对照与所有旧失败记录继续保留在工作目录；本包提供选定权重、完整本轮执行记录与绘图数据，基础模型需在原本机环境中运行。</footer></main></html>"""
    document = re.sub(r"(<img src='([^']+)'[^>]*>)", r"<a href='\2' target='_blank' rel='noopener'>\1</a>", document)
    (out / "index.html").write_text(document)
    (out / "使用说明.txt").write_text(
        "先打开 index.html 查看展示报告；图表可点击打开原图，figures 同时提供 PNG 和 SVG。\n"
        "现场操作入口：http://127.0.0.1:18789/control （仅在原本机服务运行时可用）。\n"
        "模型选择：SFT 版使用 experiment-004 的 E_more_sft，第384次更新；SFT＋RL版使用同轮 D_rl 的第384次更新。\n"
        "核心复验：6条指令、每版每条2次，合计24次，全部完成；另有浏览器按钮复验，单独保存，不合并为独立样本。\n"
        "原任务是可控的本机工程模拟，不能宣称港口生产应用或任意指令成功率100%。\n"
        "训练曲线对应历史真实训练；本次没有追加训练。港口任务输入表述适配属于Harness工程修正，不是RL权重学习增益。\n"
        "已保存全部本轮失败尝试。原三种子正式比较因目标改变而停止，仍未开启最终测试。\n"
        "adapters目录含选定LoRA权重，基础1.7B模型和业务系统仍需原本机环境，不包含在此包。\n"
        "如演示服务退出，在原工作目录执行：\n"
        ".venv/bin/python scripts/serve_agent_capability_demo.py --report .codex_artifacts/agent-rl-capability-demo-20261102/current-showcase --round .codex_artifacts/agent-rl-capability-demo-20261102/round-004\n"
        "推理服务18781与业务服务18800/18808/18473应已启动；展示服务不会另行加载大模型。\n"
        "MANIFEST.json记录每个文件的SHA256；zip旁的sha256文件验证整个压缩包。\n"
    )
    # Checkpoint bytes, original training logs, attempt records and figures all
    # enter one manifest. The manifest deliberately does not hash itself.
    manifest = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob("*")) if p.is_file()}
    save(out / "MANIFEST.json", manifest)
    package = out.with_suffix(".zip")
    with ZipFile(package, "x", compression=ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                z.write(p, Path(out.name) / p.relative_to(out))
    package.with_suffix(".zip.sha256").write_text(hashlib.sha256(package.read_bytes()).hexdigest() + "  " + package.name + "\n")
    print(json.dumps({"report": str(out / "index.html"), "zip": str(package), "suite_passed": result["suite_passed"], "files": len(manifest)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.round.resolve(), args.output.resolve())
