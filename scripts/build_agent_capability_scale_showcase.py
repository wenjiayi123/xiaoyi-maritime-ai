"""Package a stopped 30-task rehearsal; retain failed and unattempted cases."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_agent_capability_scale as scale  # noqa: E402

NAMES = {"E_more_sft": "SFT", "D_rl": "SFT＋RL"}


def build(round_dir, out):
    c = scale.core
    p = c.verify(round_dir)
    result = c.read(round_dir / "RESULTS.json")
    status = c.read(round_dir / "STATUS.json")
    if status["phase"] not in {"complete", "needs_diagnosis"}:
        raise ValueError("Only package a stopped, fully recorded stage")
    for row in result["results"]:
        folder = Path(row["folder"])
        c.audit_job(c.read(folder / "job.json"), folder, p)
    out.mkdir(parents=True, exist_ok=False)
    shutil.copytree(scale.ACCEPTED / "专家展示包-最终版", out / "accepted-v1")
    for old in sorted(scale.BASE.glob("round-*")):
        if old.is_dir() and (old / "PROTOCOL.json").exists() and not old.name.endswith(".preparing"):
            shutil.copytree(old, out / "native-records" / old.name,
                            ignore=shutil.ignore_patterns("frozen-prefix-cache"))
    data = out / "data"
    data.mkdir()
    for name in ["PLAN.json", "TASK_CATALOG.json", "CONTRACT_PREFLIGHT.json"]:
        shutil.copy2(scale.BASE / name, data / name)
    c.live.save(data / "current-results.json", result)
    c.live.save(data / "plot-data.json", {"cases": p["cases"], "groups": p["groups"], "results": result["results"],
                                         "training_curves_source": "accepted-v1/data/plot-data.json",
                                         "new_training_in_this_round": bool(p.get("new_training")),
                                         "additional_rl_updates": p.get("additional_rl_updates", 0)})
    source = out / "implementation"
    source.mkdir()
    shutil.copy2(Path(__file__), source / Path(__file__).name)
    for name in ["live-registration", "live-demo", "screenshots"]:
        if (scale.BASE / name).exists():
            shutil.copytree(scale.BASE / name, out / name)
    if (scale.BASE / "UI_QA.json").exists():
        shutil.copy2(scale.BASE / "UI_QA.json", data / "UI_QA.json")
    adaptation = Path(p["adaptation"]) if p.get("adaptation") else None
    if adaptation:
        audit = c.read(adaptation / "PARAMETER_AND_OBJECTIVE_AUDIT.json")
        if audit.get("passed") is not True or audit["updates_verified"] != p["additional_rl_updates"]:
            raise ValueError("Additional training lacks completed independent arithmetic/tensor audit")
        shutil.copytree(adaptation, out / "adaptation-evidence")
        shutil.copy2(ROOT / "scripts/audit_agent_capability_adaptation.py", source / "audit_agent_capability_adaptation.py")
        # The latest RL adapter is distinct from the preserved accepted-v1 adapter.
        shutil.copytree(adaptation / "checkpoints/step-00064", out / "current-adapters/SFT-plus-RL")
        shutil.copytree(Path(p["models"]["E_more_sft"]["adapter"]).parent, out / "current-adapters/SFT")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.colors import ListedColormap
    import numpy as np

    font = font_manager.FontProperties(fname="/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    font_manager.fontManager.addfont(font.get_file())
    plt.rcParams.update({"font.family": font.get_name(), "axes.unicode_minus": False, "svg.fonttype": "none"})
    figures = out / "figures"
    figures.mkdir()
    values = np.zeros((30, 4))
    lookup = {(r["case"], r["group"], r["repetition"]): r for r in result["results"]}
    cols = [(g, r) for g in p["groups"] for r in [1, 2]]
    fig, ax = plt.subplots(figsize=(10, 13), layout="constrained")
    for i, case in enumerate(p["cases"]):
        for k, (g, repetition) in enumerate(cols):
            row = lookup.get((case["id"], g, repetition))
            values[i, k] = (2 if row["success"] else 1) if row else 0
            ax.text(k, i, ("通过 " if row["success"] else "失败 ") + str(row["steps"]) + "步" if row else "未执行",
                    ha="center", va="center", fontsize=9, color="#123047")
    ax.imshow(values, cmap=ListedColormap(["#edf0f4", "#f8c9c4", "#b8e1d8"]), vmin=0, vmax=2, aspect="auto")
    ax.set_xticks(range(4), [NAMES[g] + f" 第{r}次" for g, r in cols])
    ax.set_yticks(range(30), [f"{i+1:02d} {x['id']}" for i, x in enumerate(p["cases"])])
    ax.axhline(23.5, color="#28475a", lw=2)
    ax.set_title("30项任务 × 两版模型 × 两次执行\n灰色未执行，红色失败，绿色通过；横线下为6项进阶任务", pad=16)
    for ext in ["png", "svg"]:
        fig.savefig(figures / ("task-matrix." + ext), dpi=150, bbox_inches="tight")
    plt.close(fig)

    adaptation_section = ""
    if adaptation:
        training = [json.loads(line) for line in (adaptation / "training.jsonl").read_text().splitlines()]
        c.live.save(data / "additional-rl-plot-data.json", training)
        fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
        x = [r["step"] for r in training]
        for field, label, color in [("expected_two_step_return_before", "本状态更新前", "#b5a5c8"),
                                    ("expected_two_step_return_after", "本状态更新后", "#7552a4")]:
            axes[0, 0].plot(x, [r[field] for r in training], label=label, color=color, lw=1.2)
        axes[0, 0].set(title="新增64次RL：期望两步模拟回报", ylabel="回报（状态不同，不是任务成功率）")
        axes[0, 0].legend()
        axes[0, 1].plot(x, [r["loss"] for r in training], color="#7552a4")
        axes[0, 1].set(title="真实反向更新的RL目标损失", ylabel="损失")
        axes[1, 0].plot(x, [r["parameter_l2_from_start"] for r in training], color="#087d89")
        axes[1, 0].set(title="相对补训起点的参数变化", ylabel="LoRA参数L2变化")
        axes[1, 1].plot(x, [r["kl_to_starting_rl"] for r in training], color="#b27933")
        axes[1, 1].set(title="对原RL策略的KL约束", ylabel="KL散度")
        for ax in axes.flat:
            ax.set_xlabel("新增更新次数")
            ax.grid(alpha=.2)
        for ext in ["png", "svg"]:
            fig.savefig(figures / ("additional-rl-training." + ext), dpi=160, bbox_inches="tight")
        plt.close(fig)
        baseline = c.read(Path(p["baseline_native_round"]) / "RESULTS.json")
        comparison = {}
        fig, ax = plt.subplots(figsize=(9, 4.5), layout="constrained")
        for i, g in enumerate(p["groups"]):
            before = [r for r in baseline["results"] if r["group"] == g and r["repetition"] == 1]
            after = [r for r in result["results"] if r["group"] == g and r["stage"] == "core24-r1"]
            comparison[g] = {"before_successes": sum(r["success"] for r in before), "before_attempted": len(before),
                             "after_successes": sum(r["success"] for r in after), "after_attempted": len(after)}
            for offset, value, color, label in [(-.18, comparison[g]["before_successes"], "#a6b8c5", "补训前"),
                                                (.18, comparison[g]["after_successes"], "#088689" if i == 0 else "#7654ad", "补训后")]:
                ax.bar(i + offset, value, width=.33, color=color, label=label if i == 0 else None)
                ax.text(i + offset, value + .4, f"{value}/24", ha="center")
        ax.set_xticks(range(2), [NAMES[g] for g in p["groups"]])
        ax.set(ylim=(0, 28), ylabel="完成任务数", title="同24项基础任务首轮：定向RL修复与能力保持")
        ax.legend()
        fig.supxlabel("基础任务用于补训与工程回归；不是独立泛化测试，也不主张RL优于SFT。", fontsize=10)
        for ext in ["png", "svg"]:
            fig.savefig(figures / ("targeted-repair." + ext), dpi=160, bbox_inches="tight")
        plt.close(fig)
        c.live.save(data / "targeted-repair-comparison.json", comparison)
        adaptation_section = f'''<section><h2>新增训练：64次定向RL参数更新</h2>
<p>扩展前24项基础任务首轮：SFT为24/24，RL版为22/24。两项RL失败均出现重复读取。为修复这个实际问题，采用32次失败状态回放＋32次已有成功状态保持，共48条不同状态；覆盖24项基础任务的保持状态。SFT没有追加训练。</p>
<img src="figures/additional-rl-training.png" alt="新增64次RL回报损失参数变化和KL曲线">
<p>本轮采用固定末步64的权重。独立审计核实64次均有真实张量变化，训练参数数目为{audit["trainable_values"]:,}；损失和回报重算最大误差为{audit["max_rl_arithmetic_error"]:.2g}。</p>
<img src="figures/targeted-repair.png" alt="同24基础任务定向RL补训前后工程回归对比">
<p class="note">训练状态来自已观察的基础任务，基础任务复验属于工程回归；6项进阶组合未参与本次补训。枚举模拟环境的两步回报来更新策略，RL目标不读取SFT动作标签，但成功轨迹用于提供保持状态，因此不主张完全不需要示范。</p>
<p><a href="adaptation-evidence/CONFIG.json">冻结补训协议</a> · <a href="data/additional-rl-plot-data.json">64次全部原始指标</a> · <a href="adaptation-evidence/PARAMETER_AND_OBJECTIVE_AUDIT.json">独立参数与目标审计</a> · <a href="adaptation-evidence/STATES.json">训练状态</a></p></section>'''

    esc = html.escape
    rows = []
    for i, case in enumerate(p["cases"]):
        cells = []
        for g in p["groups"]:
            links = []
            for rep in [1, 2]:
                row = lookup.get((case["id"], g, rep))
                if row is None:
                    links.append(f"第{rep}次：未执行")
                else:
                    stem = f"native-records/{round_dir.name}/runs/{row['id']}"
                    word = "通过" if row["success"] else "失败"
                    link = f'<a href="{stem}/job.json">第{rep}次：{word} · {row["steps"]}步</a>'
                    if row["success"]:
                        link += f' · <a href="{stem}/report.html">实际报告</a>'
                    links.append(link)
            cells.append("<td>" + "<br>".join(links) + "</td>")
        rows.append(f'<tr><td>{i+1:02d} · {esc(case["id"])}<br><small>{esc(case["category"])}</small></td>'
                    f'<td>{esc(case["goal"])}<br><small>{"原版锚点" if case["previously_accepted_anchor"] else "新增任务实例"} · '
                    f'{"基础" if case["stage"] == "core24" else "进阶"}</small></td>{"".join(cells)}</tr>')
    summaries = []
    for g in p["groups"]:
        v = result["counts"][g]
        summaries.append(f'<article><h2>{NAMES[g]}</h2><b>{v["successes"]}/{v["attempted"]}</b><p>已执行中的成功次数</p>'
                         f'<p>登记 {v["registered"]} 次，尚未执行 {v["not_attempted"]} 次</p></article>')
    label = "本轮有限范围验收通过" if result["suite_passed"] else "本轮尚未验收：保留失败，等待改进"
    new_training_text = "本轮SFT复用原权重，RL在原权重上新增64次参数更新。" if adaptation else "本轮复用已有权重；新增训练次数为0。"
    page = f'''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>舷鸥 · 30项港航任务能力扩展</title><style>
body{{margin:0;background:#edf2f7;color:#193344;font:16px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}}main{{max-width:1180px;margin:auto;padding:36px 22px}}
h1{{font-size:36px;line-height:1.3}}h2{{font-size:23px}}a{{color:#087d89}}section,article{{background:white;padding:24px;border-radius:16px;margin:22px 0}}
.cards{{display:grid;grid-template-columns:repeat(2,1fr);gap:18px}}.cards article{{margin:0}}b{{font-size:36px}}.badge{{display:inline-block;background:#e7e1f7;padding:5px 12px;border-radius:8px}}
img{{max-width:100%;height:auto}}.matrix{{max-height:1150px;display:block;margin:auto}}.table{{overflow:auto}}table{{border-collapse:collapse;width:100%;min-width:860px}}td,th{{padding:12px;border-bottom:1px solid #dfe6ee;text-align:left;vertical-align:top}}small{{color:#607685}}.note{{background:#f0f5f8;padding:14px;border-left:4px solid #1b8490}}
@media(max-width:650px){{h1{{font-size:28px}}main{{padding:18px 12px}}section{{padding:18px}}.cards{{grid-template-columns:1fr}}}}</style>
<main><p>本机真实工具调用 · 两条参数训练路线 · 全过程可追溯</p><h1>舷鸥：30项港航任务能力扩展</h1>
<p class="badge">{label}</p><p>24项基础任务＋6项跨系统恢复任务；每项为两版模型各登记两次执行。新版本独立保存，原已验收版本完整保留。</p>
<p><a href="http://127.0.0.1:18790/control">本机现场演示入口</a> · <a href="accepted-v1/index.html">已验收原版</a></p>
<div class="cards">{"".join(summaries)}</div>
<section><h2>这次扩大了什么</h2><p>从原版6条语义任务、每版12次执行，扩展到30条不同任务实例、每版60次登记执行。包括8组能碳参数、3种港口情景、1项交通报告、8项联合任务、4项能碳读取恢复及6项联合读取恢复。</p>
<p class="note">30是任务实例数，包含参数和故障组合，不是30种独立业务能力，也不是新增30条训练样本。{new_training_text}灰色未执行项不能计为成功。</p></section>
<section><h2>每次执行都能逐项核查</h2><a href="figures/task-matrix.png"><img class="matrix" src="figures/task-matrix.png" alt="30项任务两版模型两次执行矩阵"></a>
<p><a href="figures/task-matrix.svg">矢量图</a> · <a href="data/plot-data.json">原始绘图数据</a> · <a href="data/current-results.json">本轮完整结果</a></p></section>
{adaptation_section}
<section><h2>历史训练能力证据：完整保留</h2><p>两版模型分别来自继续SFT与SFT后RL。此前各保留512次参数更新，原已验收版使用此前选定的第384次权重。229,376个LoRA参数参与训练；原始损失、期望回报、梯度和权重校验均保留。{new_training_text}</p>
<img src="accepted-v1/figures/training-curves.png" alt="已审计512次SFT和RL训练曲线"><img src="accepted-v1/figures/parameter-updates.png" alt="参数更新审计">
<p>这里的RL采用有限动作空间的两步模拟前瞻和策略期望回报优化，并用KL约束维持已有行为。曲线是历史训练证据，不是本轮新增训练或30项任务的成功率；方法不称作完整长时序PPO或GRPO。</p>
<p><a href="accepted-v1/index.html">打开已验收原版完整展示</a> · <a href="accepted-v1/data/plot-data.json">训练曲线原始数据</a> · <a href="accepted-v1/data/original-experiment-004/parameter-change-audit.json">参数变化审计</a></p></section>
<section><h2>模型、Harness与系统如何配合</h2><p>明确用户指令 → 确定性提取任务参数 → 模型结合当前状态选择下一工具 → Harness调用本机系统 → 将实际反馈返回模型 → 继续执行 → 核验数据与参数 → 生成带来源的报告。</p>
<p>每一步记录输入、13个候选的概率、模型权重指纹、所选工具、API原始响应与哈希。遇到注入的读取超时，由模型选择后续动作。没有用规则代替模型决定下一步。</p>
<p class="note">范围：13个受约束的动作/参数候选、确定性参数解析与报告渲染；下游数据为公开数据校准的工程模拟。报告是本机业务闭环证据，不代表真实港口生产调度，也不证明任意模糊指令的普遍成功率。</p></section>
<section><h2>30项清单与所有本轮执行</h2><div class="table"><table><thead><tr><th>任务</th><th>指令及范围</th><th>SFT</th><th>SFT＋RL</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>
<section><h2>复查与复现</h2><p><a href="data/TASK_CATALOG.json">事前任务清单</a> · <a href="native-records/{round_dir.name}/PROTOCOL.json">冻结协议</a> · <a href="native-records/{round_dir.name}/SOURCES.json">源代码哈希</a> · <a href="MANIFEST.json">完整文件清单</a></p>
<p>所有已结束轮次的成功与失败均在native-records目录；其中round-002因原生执行环境缺少依赖而中止，故障与中止记录完整保留，不计入当前轮次的有效能力成绩。已验收原版保存在accepted-v1目录。有限重复演示与独立算法对照分开，本包不主张RL优于SFT。</p></section>
<footer>生成时间：{esc(c.now())} · 当前轮次：{esc(round_dir.name)}</footer></main></html>'''
    (out / "index.html").write_text(page)
    script = """专家展示讲解稿（本机工程演示范围）

我做的是港航领域语言模型的工具决策训练和系统闭环。
模型负责根据任务和工具反馈选择下一步，Harness负责执行工具、保留回执和核验产物。
我保留两条路线：SFT从正确示范学习；RL利用模拟环境给出的动作回报来更新策略参数。

训练与展示数量要分开说：
1. 基础模型为Qwen3-1.7B；可训练的LoRA参数为229,376个。
2. 历史继续SFT、RL各保存512次更新，原已验收版本使用各自此前选定的384步权重。
3. 本轮从RL的384步权重分支继续64次更新；不能把历史未被选中的128步算进当前权重的训练链。
4. 本轮补训用了48条不同状态，32次失败状态回放与32次成功状态保持；SFT追加更新为0。
5. 验收登记30项任务实例，两版各重复两次，共120次执行。30不是30类独立业务能力，也不是训练样本数。

最有说服力的演示顺序：
先打开现场入口，选一条跨系统读取超时恢复任务，让模型执行到生成报告。
再展示每步的候选概率、所选工具、API原始返回、参数回显和权重指纹。
然后展示历史SFT损失、历史RL回报，以及本轮64次RL的损失、回报、梯度和权重变化审计。
最后展示完整30项矩阵和保留的失败记录，不只挑一次好结果。

如何准确解释本轮RL贡献：
原24项基础任务首轮，SFT完成24项，RL完成22项。
这次针对RL重复读取的实际问题补训，保持Harness提示、工具和成功标准不变，再做工程回归。
基础任务参与了补训，所以其复验不能称为独立泛化测试；6项进阶组合未参加本次补训。
本次目标是展示两条真实训练路线与可靠的有限任务闭环，不主张RL普遍比SFT强。

方法边界：
RL使用13个受约束候选动作上的两步模拟前瞻期望回报与KL约束，不称完整长时序PPO/GRPO。
RL目标不读取SFT动作标签，但成功轨迹提供了保持状态，所以不是完全零示范。
用户参数由确定性解析器提取，报告由核验后的工具结果渲染；不是任意自然语言与任意JSON工具生成。
下游为本机工程模拟，不是实际港口生产调度。
此前港口任务的词语调整属于工程适配；round-002的依赖修复属于运行环境修复，均与RL参数收益区分。

复现说明：
index.html可直接离线阅读，证据与图在本包内；现场执行需原项目和本地Qwen3-1.7B基础权重（未重复打入本包）。
原版适配器与展示包在accepted-v1，当前适配器在current-adapters；训练全过程在adaptation-evidence。
本包不包含未来尚未执行的实验结果。
"""
    if not adaptation:
        script = "本包为补训前工程评估；新增训练0次。请以index.html及各任务原始轨迹为准，尚未通过时不称已验收。\n"
    (out / "专家讲解与复现说明.txt").write_text(script)
    manifest = {str(f.relative_to(out)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(out.rglob("*")) if f.is_file()}
    c.live.save(out / "MANIFEST.json", {"time": c.now(), "files": manifest})
    archive = out.with_suffix(".zip")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                z.write(f, str(Path(out.name) / f.relative_to(out)))
    archive.with_suffix(".zip.sha256").write_text(c.sha(archive) + "  " + archive.name + "\n")
    print(json.dumps({"output": str(out), "suite_passed": result["suite_passed"], "files": len(manifest), "zip_sha256": c.sha(archive)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.round.resolve(), args.output.resolve())
