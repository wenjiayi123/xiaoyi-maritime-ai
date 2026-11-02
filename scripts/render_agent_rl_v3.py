"""Immutable measured progress plots. Pilot development data, not test claims."""

import argparse
from html import escape
import json
import math
from pathlib import Path
import time


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    args = parser.parse_args()
    root = args.experiment
    config = read(root / "config.json")
    curriculum = bool(config.get("curriculum"))
    groups = ["D_drgrpo", "E_more_sft", "F_experience"]
    updates = {
        g: [read(p.parent / "summary.json") for p in sorted((root / g).glob("step-*/COMMITTED.json"))] for g in groups
    }
    validation = [read(p) for p in sorted((root / "validation").glob("*.json"))]
    rule_path = root / "baselines/A_rules-development.json"
    if rule_path.exists():
        validation.append(read(rule_path))
    warmup = [read(p.parent / "update.json") for p in sorted((root / "warmup").glob("step-*/COMMITTED.json"))]
    diagnostics = {g: [] for g in groups}
    for group in groups:
        for marker in sorted((root / group).glob("step-*/COMMITTED.json")):
            path = marker.parent
            summary = read(path / "summary.json")
            arithmetic = read(path / "arithmetic.json")
            trajectories = read(path / "trajectories.json")
            samples = read(path / "training-samples.json")
            kls, entropies = [], []
            for sample, calc in zip(samples, arithmetic):
                log_probs = calc["log_probs"]
                entropies.append(-sum(math.exp(p) * p for p in log_probs))
                kls.append(
                    sum(
                        math.exp(p) * (p - math.log(max(q, 1e-30)))
                        for p, q in zip(log_probs, sample["reference_probs"])
                    )
                )
            diagnostics[group].append(
                {
                    "step": summary["step"],
                    "gradient_norm": summary["gradient_norm"],
                    "mean_action_kl": sum(kls) / len(kls),
                    "mean_action_entropy": sum(entropies) / len(entropies),
                    "seconds": summary["seconds"],
                    "oracle_labels": summary["oracle_labels"],
                    "new_model_selected_actions": summary["new_environment_calls"],
                    "initialization_prefix_steps_fresh_rollouts": (
                        sum(len(t["task"].get("initial_history", [])) for t in trajectories if not t["replay"])
                        if group != "E_more_sft"
                        else 0
                    ),
                    "replay_rollouts": summary["replay_rollouts"],
                    "fresh_rollouts": summary["fresh_rollouts"],
                    "nonzero_advantage_trajectories": sum(abs(a) > 1e-12 for a in summary["advantages"]),
                    "return_range": max(summary["returns"]) - min(summary["returns"]),
                    "fresh_success_rate": (
                        summary["fresh_successes"] / summary["fresh_rollouts"] if summary["fresh_rollouts"] else None
                    ),
                    "training_prefix_lengths": [len(t["task"].get("initial_history", [])) for t in trajectories],
                }
            )
    target = root / "figures" / (time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000:06d}")
    target.mkdir(parents=True, exist_ok=False)
    (target / "raw-points.json").write_text(
        json.dumps(
            {
                "updates": updates,
                "validation": validation,
                "warmup": warmup,
                "diagnostics": diagnostics,
                "curriculum": config.get("curriculum"),
                "cost_scope": "model-selected actions plus separately reported fresh rollout prefix initialization; oracle/audit replay excluded",
                "validation_scope": "from task start without reference prefix; pilot development only",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    font = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
    font_manager.fontManager.addfont(font)
    plt.rcParams.update(
        {
            "font.family": font_manager.FontProperties(fname=font).get_name(),
            "axes.unicode_minus": False,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
        }
    )
    names = {"D_drgrpo": "D 在线 RL", "E_more_sft": "E 继续 SFT", "F_experience": "F RL＋经验复用"}
    colors = {"D_drgrpo": "#26748b", "E_more_sft": "#d08b2d", "F_experience": "#8b59ac"}
    fig, ax = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    fig.suptitle("小懿 2.0 · 本机可行性试跑\n开发数据，非最终测试；空白表示该阶段尚无记录", fontsize=15)
    ax[0, 0].plot([r["step"] for r in warmup], [r["loss"] for r in warmup], color="#536b82")
    ax[0, 0].set(title="共同 SFT 适配损失", xlabel="单状态更新", ylabel="交叉熵")
    for g in ["D_drgrpo", "F_experience"]:
        rows = updates[g]
        ax[0, 1].plot(
            [r["step"] for r in rows],
            [sum(r["returns"]) / len(r["returns"]) for r in rows],
            "o-",
            label=names[g],
            color=colors[g],
        )
    ax[0, 1].set(
        title="每组轨迹的平均训练回报" + ("（含局部课程任务）" if curriculum else ""),
        xlabel="轨迹组更新",
        ylabel="回报（不同起点/任务，不能跨阶段直接比较）",
    )
    if curriculum:
        for boundary in [8.5, 16.5]:
            ax[0, 1].axvline(boundary, color="#999999", linestyle=":", linewidth=1)
    common = next((r for r in validation if r["phase"] == "C_common_sft"), None)
    if common:
        ax[1, 0].axhline(100 * common["successes"] / common["n"], color="#536b82", linestyle="--", label="C 共同 SFT")
    rules = next((r for r in validation if r["phase"] == "A_rules"), None)
    if rules:
        ax[1, 0].axhline(100 * rules["successes"] / rules["n"], color="#7a7e66", linestyle=":", label="A 规则参考")
    for g in groups:
        vals = sorted([r for r in validation if r["phase"] == g], key=lambda r: r["step"])
        ax[1, 0].plot(
            [r["step"] for r in vals],
            [100 * r["successes"] / r["n"] for r in vals],
            "o-",
            label=names[g],
            color=colors[g],
        )
        rows = updates[g]
        cumulative, costs = 0, []
        for r in rows:
            cumulative += r["new_environment_calls"]
            costs.append(cumulative)
        ax[1, 1].plot([r["step"] for r in rows], costs, "o-", label=names[g], color=colors[g])
    ax[1, 0].set(
        title="从头执行的开发完成率（每节点仅 4 个任务）", xlabel="轨迹组更新", ylabel="完成率 %", ylim=(-5, 105)
    )
    ax[1, 1].set(
        title="模型新选动作的交互成本\n不含课程初始化；E 复用 D 数据，另需标签",
        xlabel="轨迹组更新",
        ylabel="累计模型动作次数",
    )
    for a in ax.flat:
        a.grid(alpha=0.15)
    for a in [ax[0, 1], ax[1, 0], ax[1, 1]]:
        a.set_xlim(0, config["groups"] + 0.5)
        if not any(len(line.get_xdata()) for line in a.lines):
            a.text(
                0.5,
                0.5,
                "该阶段尚无测量记录",
                transform=a.transAxes,
                ha="center",
                va="center",
                color="#667085",
                fontsize=12,
            )
        a.legend(fontsize=8)
    for ext in ["png", "svg", "pdf"]:
        fig.savefig(target / ("pilot-progress." + ext), dpi=170)
    plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(14, 4), layout="constrained")
    fig.suptitle("探索是否产生学习信号（局部课程训练，非完整任务测评）", fontsize=14)
    for axis, metric, title in zip(
        axes,
        ["return_range", "nonzero_advantage_trajectories", "replay_rollouts"],
        ["同组轨迹回报差距", "同组具有非零相对优势的轨迹数", "每组实际复用的历史轨迹数"],
    ):
        for group in ["D_drgrpo", "F_experience"]:
            rows = diagnostics[group]
            axis.plot(
                [r["step"] for r in rows], [r[metric] for r in rows], "o-", color=colors[group], label=names[group]
            )
        axis.set(title=title, xlabel="轨迹组更新", xlim=(0, config["groups"] + 0.5))
        axis.grid(alpha=0.15)
        axis.legend(fontsize=8)
    for ext in ["png", "svg", "pdf"]:
        fig.savefig(target / ("exploration-signal." + ext), dpi=170)
    plt.close(fig)
    fig, axes = plt.subplots(2, 3, figsize=(14, 8), layout="constrained")
    fig.suptitle(
        "小懿 2.0 · 参数更新与成本诊断（开发试跑）\n原始节点全部保留；课程初始化、模型探索与人工标签分别计数",
        fontsize=14,
    )
    settings = [
        ("gradient_norm", "裁剪前梯度范数", False),
        ("mean_action_kl", "相对共同 SFT 的平均动作 KL", False),
        ("mean_action_entropy", "平均动作熵", False),
        ("seconds", "累计处理组训练时间（秒）", True),
        ("oracle_labels", "累计额外 oracle 动作标签", True),
        ("initialization_prefix_steps_fresh_rollouts", "累计课程初始化步骤（非模型动作）", True),
    ]
    for axis, (metric, title, cumulative) in zip(axes.flat, settings):
        for group in groups:
            rows = diagnostics[group]
            values, total = [], 0
            for row in rows:
                total = total + row[metric] if cumulative else row[metric]
                values.append(total)
            axis.plot([r["step"] for r in rows], values, "o-", color=colors[group], label=names[group])
        axis.set(title=title, xlabel="轨迹组更新", xlim=(0, config["groups"] + 0.5))
        axis.grid(alpha=0.15)
        axis.legend(fontsize=8)
    for ext in ["png", "svg", "pdf"]:
        fig.savefig(target / ("training-diagnostics." + ext), dpi=170)
    plt.close(fig)
    latest = {}
    for row in validation:
        if row["phase"] not in latest or row["step"] > latest[row["phase"]]["step"]:
            latest[row["phase"]] = row
    table = []
    for group, name in {"A_rules": "A 规则参考", "C_common_sft": "C 共同 SFT", **names}.items():
        measured = latest.get(group)
        score = f"{measured['successes']} / {measured['n']}" if measured else "尚无完整测量"
        node = str(measured["step"]) if measured else "—"
        committed = len(updates.get(group, [])) if group != "C_common_sft" else len(warmup)
        table.append(f"<tr><td>{name}</td><td>{committed}</td><td>{node}</td><td>{score}</td></tr>")
    page = (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>小懿 2.0 实验记录</title><style>body{max-width:1200px;margin:32px auto;padding:24px;font:16px system-ui;line-height:1.7;color:#203044}"
        "img{width:100%;height:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px;border-bottom:1px solid #ddd}"
        ".note{padding:18px;background:#eef4f5}a{color:#156377}</style>"
        "<h1>小懿 2.0 · 可复核的训练记录</h1><p>生成时间："
        + time.strftime("%Y-%m-%d %H:%M:%S %z")
        + "；实验："
        + escape(root.name)
        + "</p>"
        '<p class="note">这是开发试跑，独立测试尚未开启。局部课程练习不等于从头完成指令；未完成的对照不作胜负结论。'
        "规则接口探针不计作模型成绩。每组都使用相同的工具和执行接口。</p>"
        "<h2>最近已完成的开发测量</h2><table><tr><th>组别</th><th>已提交更新</th><th>测量节点</th><th>从头完成任务</th></tr>"
        + "".join(table)
        + "</table><p>C的更新单位为单个示范状态；D/E/F为一个轨迹组，不能直接比较更新数字。</p>"
        '<img src="pilot-progress.png" alt="共同适配、训练回报、开发完成率与模型动作成本">'
        '<img src="training-diagnostics.png" alt="梯度、KL、动作熵、时间、标签与课程初始化成本">'
        '<img src="exploration-signal.png" alt="回报区分信号与实际经验复用">'
        "<p>灰色竖线区分课程阶段。奖励对应不同任务和起点，不跨阶段直接解释为能力增长。"
        "E的训练轨迹来自D，其实际能力只看E自己运行的开发验证。</p>"
        '<p><a href="raw-points.json">全部绘图原始数据</a> · <a href="pilot-progress.svg">主图 SVG</a> · '
        '<a href="pilot-progress.pdf">主图 PDF</a> · <a href="training-diagnostics.pdf">诊断 PDF</a> · '
        '<a href="../../config.json">冻结实验配置</a> · <a href="../../STATUS.json">当前执行状态</a></p></html>'
    )
    (target / "progress.html").write_text(page)
    pointer = root / "latest-progress.json"
    temporary = pointer.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"report": str((target / "progress.html").resolve()), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    temporary.replace(pointer)
    relative = (target / "progress.html").relative_to(root).as_posix()
    pointer_html = root / "latest-report.html"
    temporary_html = pointer_html.with_suffix(".tmp")
    temporary_html.write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta http-equiv="refresh" content="0;url=' + relative + '">'
        '<title>小懿实验最新记录</title><p><a href="' + relative + '">打开最近生成的实验记录</a></p></html>'
    )
    temporary_html.replace(pointer_html)
    print(target.resolve())


if __name__ == "__main__":
    main()
