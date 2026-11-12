"""Export measured comparison and learning curves; raw points stay available."""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

LABELS = {
    "A_rules": "A 固定规则",
    "B_base": "B 原始模型",
    "C_sft": "C 冻结 SFT",
    "D_rl": "D SFT＋RL",
    "E_more_sft": "E 继续 SFT",
}
COLORS = ["#778899", "#91b4cf", "#33988e", "#7954b3", "#d18c35"]
FAMILIES = {
    "port_read": "港口查询",
    "energy_compare": "能碳比较",
    "port_scenario": "港口情景",
    "traffic_read": "交通查询",
    "joint": "跨系统联合",
    "read_recovery": "读取恢复",
    "write_recovery": "回执恢复",
    "clock_restore": "状态恢复",
}


def read(path):
    return json.loads(path.read_text())


def lines(path):
    if not path.exists():
        return []
    return [json.loads(s) for s in path.read_text().splitlines() if s.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--interim", action="store_true")
    args = parser.parse_args()
    folder = args.experiment
    updates = lines(folder / "training.jsonl")
    curves = lines(folder / "validation-curve.jsonl")
    phases = {key: [r for r in updates if r["stage"] == key] for key in ["D_rl", "E_more_sft"]}
    if args.interim:
        output = folder / f"figures-progress-D{len(phases['D_rl']):04d}-E{len(phases['E_more_sft']):04d}"
        summary = None
    else:
        summary = read(folder / "audited-summary.json")
        if not summary["audit"]["all_replayed"]:
            raise ValueError("audited measurements required")
        output = folder / "figures"
    if output.exists():
        raise ValueError("figure version already exists; retain it")
    output.mkdir()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    import numpy as np

    font = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    font_manager.fontManager.addfont(str(font))
    plt.rcParams.update(
        {
            "font.family": font_manager.FontProperties(fname=str(font)).get_name(),
            "axes.unicode_minus": False,
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
        }
    )

    def export(fig, name):
        for extension in ["png", "svg", "pdf"]:
            fig.savefig(output / (name + "." + extension), dpi=180, bbox_inches="tight")
        plt.close(fig)

    if summary:
        keys = list(LABELS)
        fig, axes = plt.subplots(
            2, 1, figsize=(12, 8.8), gridspec_kw={"height_ratios": [1, 1.15]}, layout="constrained"
        )
        values = [summary["groups"][k]["success_rate"] * 100 for k in keys]
        bars = axes[0].bar(list(LABELS.values()), values, color=COLORS, width=0.55)
        axes[0].set(
            ylim=(0, 112),
            yticks=[0, 20, 40, 60, 80, 100],
            ylabel="最终留出任务完成率（%）",
            title="四组主对照 + 继续 SFT 对照：所有组使用同一 Harness",
        )
        for bar, key, value in zip(bars, keys, values):
            g = summary["groups"][key]
            axes[0].text(
                bar.get_x() + bar.get_width() / 2, value + 2, f"{g['successes']}/{g['n']} · {value:.1f}%", ha="center"
            )
        matrix = np.array(
            [
                [
                    summary["groups"][k]["by_family"][f]["successes"] / summary["groups"][k]["by_family"][f]["n"] * 100
                    for f in FAMILIES
                ]
                for k in keys
            ]
        )
        im = axes[1].imshow(matrix, vmin=0, vmax=100, cmap="Blues", aspect="auto")
        axes[1].set_xticks(range(8), list(FAMILIES.values()), rotation=18, ha="right")
        axes[1].set_yticks(range(5), list(LABELS.values()))
        axes[1].set_title("各类任务完成数（每类 3 个案例）", loc="left")
        for i, k in enumerate(keys):
            for j, f in enumerate(FAMILIES):
                g = summary["groups"][k]["by_family"][f]
                axes[1].text(
                    j,
                    i,
                    f"{g['successes']}/{g['n']}",
                    ha="center",
                    va="center",
                    color="white" if matrix[i, j] > 55 else "#183447",
                )
        fig.colorbar(im, ax=axes[1], label="完成率（%）", fraction=0.025)
        fig.suptitle(
            f"舷鸥 1.7B · 本机语言模型强化学习实测\nD−C：{summary['rl_increment'] * 100:+.1f} 个百分点；D−E：{summary['rl_vs_continued_sft'] * 100:+.1f} 个百分点",
            fontsize=15,
        )
        fig.supxlabel(
            "单训练种子 · 已知任务族的新参数与开头措辞 · 小样本工程实验，不能外推为所有任务或所有 RL 的优势", fontsize=9
        )
        export(fig, "four-group-comparison")
        fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), layout="constrained")
        candidates_file = folder / "selection-refinement-candidates.json"
        candidates = read(candidates_file) if candidates_file.exists() else {}
        for phase, color in [("D_rl", COLORS[3]), ("E_more_sft", COLORS[4])]:
            rows = candidates.get(phase, [])
            axes[0].plot(
                [0] + [r["step"] for r in rows],
                [100] + [r["retention"]["accuracy"] * 100 for r in rows],
                marker="o",
                color=color,
                label=LABELS[phase],
            )
        axes[0].set(
            ylim=(0, 107), xlabel="额外训练步数", ylabel="8 题开发回归正确率（%）", title="包括未达能力保持门槛的检查点"
        )
        axes[0].legend()
        independent = summary["independent_retention"]
        keys = list(LABELS)[1:]
        for i, key in enumerate(keys):
            row = independent["groups"][key]
            axes[1].bar(i, row["accuracy"] * 100, color=COLORS[i + 1], width=0.6)
            axes[1].text(i, row["accuracy"] * 100 + 2, f"{row['correct']}/{row['n']}", ha="center")
        axes[1].set_xticks(range(4), [LABELS[k] for k in keys], rotation=18)
        axes[1].set(ylim=(0, 112), ylabel="20 道新检查题正确率（%）", title="最终独立检查：未用于训练或选择")
        fig.suptitle("任务变强是否伴随能力退步？分别保留开发检查与独立检查", fontsize=14)
        fig.supxlabel("有限的二选一领域、算术与证据处理检查；部分概念相近，不是全面通用能力基准。", fontsize=9)
        export(fig, "retention-checks")
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), layout="constrained")
    rl = phases["D_rl"]
    x = [r["step"] for r in rl]
    gains = [r["expected_two_step_return_after"] - r["expected_two_step_return_before"] for r in rl]
    axes[0, 0].plot(x, gains, color=COLORS[3], alpha=0.24, linewidth=0.7, label="每次更新的实际变化")
    if len(gains) >= 16:
        axes[0, 0].plot(
            x[15:], np.convolve(gains, np.ones(16) / 16, mode="valid"), color=COLORS[3], label="16 步滑动平均"
        )
    axes[0, 0].axhline(0, color="#aab4be", linewidth=0.7)
    axes[0, 0].set(
        xlabel="RL 更新步数", ylabel="同一状态的更新后 − 更新前", title="两步代理回报的变化（不是任务完成率）"
    )
    axes[0, 0].legend(fontsize=8)
    baseline_file = folder / "evaluations/validation-C_sft.json"
    baseline = read(baseline_file) if baseline_file.exists() else None
    for phase, color in [("D_rl", COLORS[3]), ("E_more_sft", COLORS[4])]:
        rows = sorted([r for r in curves if r["phase"] == phase], key=lambda r: r["step"])
        xs = [0] + [r["step"] for r in rows] if baseline else [r["step"] for r in rows]
        success = ([baseline["success_rate"] * 100] if baseline else []) + [r["successes"] / 16 * 100 for r in rows]
        rewards = ([baseline["mean_reward"]] if baseline else []) + [r["mean_reward"] for r in rows]
        axes[0, 1].plot(xs, success, color=color, marker="o", label=LABELS[phase])
        axes[0, 2].plot(xs, rewards, color=color, marker="o", label=LABELS[phase])
    axes[0, 1].set(
        xlabel="额外更新步数", ylabel="16 个验证任务完成率（%）", ylim=(0, 105), title="完整闭环任务：验证曲线"
    )
    axes[0, 2].set(xlabel="额外更新步数", ylabel="完整任务平均累计回报", title="完整闭环任务：实际回报")
    axes[0, 1].legend(fontsize=8)
    axes[0, 2].legend(fontsize=8)
    axes[1, 0].plot(x, [r["kl_to_frozen_sft"] for r in rl], color=COLORS[3], label="KL 到冻结 SFT")
    axes[1, 0].set(xlabel="RL 更新步数", ylabel="KL", title="更新幅度：保留全部原始点")
    axes[1, 1].plot(x, [r["gradient_norm_before_clip"] for r in rl], color=COLORS[3], alpha=0.65)
    axes[1, 1].set(xlabel="RL 更新步数", ylabel="裁剪前梯度范数", title="真实反向传播与优化记录")
    if summary:
        keys = list(LABELS)[1:]
        values = [summary["retention"][k]["accuracy"] * 100 for k in keys]
        axes[1, 2].bar([LABELS[k] for k in keys], values, color=COLORS[1:])
        axes[1, 2].set(ylim=(0, 112), ylabel="8 道固定回归题正确率（%）", title="有限能力保持检查")
        axes[1, 2].tick_params(axis="x", labelrotation=20)
        for i, v in enumerate(values):
            axes[1, 2].text(i, v + 2, f"{v / 100 * 8:.0f}/8", ha="center")
    else:
        for phase, color in [("D_rl", COLORS[3]), ("E_more_sft", COLORS[4])]:
            rows = phases[phase]
            axes[1, 2].plot(
                [r["step"] for r in rows], [r["seconds"] for r in rows], color=color, label=LABELS[phase], alpha=0.6
            )
        axes[1, 2].set(xlabel="更新步数", ylabel="单次更新秒数", title="本机实际训练耗时")
        axes[1, 2].legend(fontsize=8)
    fig.suptitle(
        "训练信号、闭环任务表现与能力回归分别展示" + (" · 训练中，尚无最终测试结论" if args.interim else ""),
        fontsize=15,
    )
    fig.supxlabel(
        "不同训练步对应不同状态；曲线保留波动。8 题回归不能证明全面能力保持。完整 JSON 原始数据随图保存。", fontsize=9
    )
    export(fig, "training-and-retention")
    # Losses are different objectives, so separate panels prevent comparison of
    # their numerical scales as if they measured the same quantity.
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), layout="constrained")
    for ax, phase, color in zip(axes[0], phases, [COLORS[3], COLORS[4]]):
        rows = phases[phase]
        ax.plot([r["step"] for r in rows], [r["loss"] for r in rows], color=color, alpha=0.7)
        ax.set(xlabel="额外更新步数", ylabel="各自训练目标", title=LABELS[phase] + " 损失（数值不能跨图直接比较）")
    axes[1, 0].plot(x, [r["entropy"] for r in rl], color=COLORS[3])
    axes[1, 0].set(xlabel="RL 更新步数", ylabel="动作分布熵", title="动作选择分布的变化")
    for phase, color in [("D_rl", COLORS[3]), ("E_more_sft", COLORS[4])]:
        rows = phases[phase]
        axes[1, 1].plot(
            [r["step"] for r in rows], np.cumsum([r["seconds"] for r in rows]), color=color, label=LABELS[phase]
        )
    axes[1, 1].set(
        xlabel="额外更新步数", ylabel="累计更新耗时（秒，含参考计算，不含验证）", title="实际计算成本分别报告"
    )
    axes[1, 1].legend()
    export(fig, "optimization-details")
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), layout="constrained")
    for suffix, label, color in [("before", "更新前策略", "#8d9cae"), ("after", "更新后策略", COLORS[3])]:
        values = [r["expected_two_step_return_" + suffix] for r in rl]
        axes[0].plot(x, values, color=color, alpha=0.2, linewidth=0.6)
        if len(values) >= 32:
            axes[0].plot(
                x[31:], np.convolve(values, np.ones(32) / 32, mode="valid"), color=color, label=label + " · 32 步均值"
            )
    axes[0].set(xlabel="RL 参数更新步数", ylabel="策略分布下的两步模拟回报", title="训练代理回报：全部原始点与滑动均值")
    axes[0].legend(fontsize=8)
    for phase, color in [("D_rl", COLORS[3]), ("E_more_sft", COLORS[4])]:
        rows = sorted([r for r in curves if r["phase"] == phase], key=lambda r: r["step"])
        axes[1].plot(
            ([0] if baseline else []) + [r["step"] for r in rows],
            ([baseline["mean_reward"]] if baseline else []) + [r["mean_reward"] for r in rows],
            marker="o",
            color=color,
            label=LABELS[phase],
        )
    axes[1].set(xlabel="额外训练步数", ylabel="16 个完整验证任务的平均累计回报", title="实际闭环回报：固定验证任务")
    axes[1].legend(fontsize=8)
    fig.suptitle("奖励曲线：训练中的短期估计与完整任务实测分开呈现", fontsize=14)
    fig.supxlabel("左图每步对应不同训练状态，不能将其波动直接解释为能力变化；右图包含全部成功与失败。", fontsize=9)
    export(fig, "reward-trajectories")
    (output / "plot-data.json").write_text(
        json.dumps({"training": updates, "validation": curves, "summary": summary}, ensure_ascii=False, indent=2) + "\n"
    )
    sources = [
        p
        for p in [folder / "training.jsonl", folder / "validation-curve.jsonl", folder / "audited-summary.json"]
        if p.exists()
    ]
    (output / "figure-provenance.json").write_text(
        json.dumps(
            {
                "sources": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sources],
                "matplotlib": matplotlib.__version__,
                "interim": args.interim,
                "invented_values": False,
                "test_repeated_for_chart": False,
            },
            indent=2,
        )
        + "\n"
    )
    print(output)


if __name__ == "__main__":
    main()
