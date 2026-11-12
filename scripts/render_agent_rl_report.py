"""Render publication/export figures exclusively from measured experiment JSON."""

from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path


def wilson(successes, n):
    z = 1.96
    p = successes / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0, mid - half), min(1, mid + half)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    args = parser.parse_args()
    folder = args.experiment
    source = folder / "audited-summary.json"
    if not source.is_file():
        raise SystemExit("run the independent result audit before rendering comparison figures")
    summary = json.loads(source.read_text())
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    import numpy as np

    font = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams.update(
        {
            "axes.unicode_minus": False,
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
        }
    )
    output = folder / "figures"
    output.mkdir(exist_ok=True)
    keys = ["A_rules", "B_base", "C_sft", "D_rl"]
    labels = ["A 固定规则", "B 原始模型", "C 仅 SFT", "D SFT＋RL"]
    colors = ["#7a899b", "#8aa9cb", "#49a79b", "#715fa5"]
    family_names = {
        "port_read": "港口查询",
        "energy_compare": "能碳比较",
        "port_scenario": "港口情景",
        "traffic_read": "交通查询",
        "joint": "跨系统联合",
        "read_recovery": "读取恢复",
        "write_recovery": "回执恢复",
        "clock_restore": "状态恢复",
    }
    fig, axes = plt.subplots(2, 1, figsize=(11, 8.5), gridspec_kw={"height_ratios": [1, 1.15]}, layout="constrained")
    values = [summary["groups"][k]["success_rate"] * 100 for k in keys]
    intervals = []
    for k in keys:
        group = summary["groups"][k]
        wins = sum(row["success"] for row in group["cases"])
        intervals.append(wilson(wins, group["n"]))
    errors = np.array(
        [
            [v - lo * 100 for v, (lo, hi) in zip(values, intervals)],
            [hi * 100 - v for v, (lo, hi) in zip(values, intervals)],
        ]
    )
    bars = axes[0].bar(labels, values, color=colors, width=0.58, yerr=errors, capsize=5)
    axes[0].set_ylim(0, 115)
    axes[0].set_yticks([0, 20, 40, 60, 80, 100])
    axes[0].set_ylabel("独立测试任务完成率（%）")
    axes[0].set_title("同一工具、任务与预算下的四组实测", loc="left", fontweight="bold")
    for bar, value, k, (_, upper) in zip(bars, values, keys, intervals):
        group = summary["groups"][k]
        wins = sum(r["success"] for r in group["cases"])
        axes[0].text(
            bar.get_x() + bar.get_width() / 2,
            min(109, upper * 100 + 3),
            f"{value:.1f}%  ({wins}/{group['n']})",
            ha="center",
            fontsize=10,
        )
    families = list(family_names)
    matrix = np.array([[summary["groups"][k]["by_family"][f]["success_rate"] * 100 for f in families] for k in keys])
    image = axes[1].imshow(matrix, vmin=0, vmax=100, cmap="Blues", aspect="auto")
    axes[1].set_xticks(range(len(families)), [family_names[f] for f in families], rotation=20, ha="right")
    axes[1].set_yticks(range(4), labels)
    axes[1].set_title("各任务类别分别报告，保留失败", loc="left", fontweight="bold")
    for y in range(4):
        for x in range(len(families)):
            axes[1].text(
                x,
                y,
                f"{matrix[y, x]:.0f}%",
                ha="center",
                va="center",
                color="white" if matrix[y, x] > 55 else "#142534",
            )
    fig.colorbar(image, ax=axes[1], label="完成率（%）", fraction=0.025, pad=0.02)
    fig.suptitle(
        f"舷鸥 1.7B · 多任务语言模型 RL 本机实验\nRL 相对 SFT：{summary['rl_increment'] * 100:+.1f} 个百分点",
        fontsize=15,
    )
    fig.supxlabel(
        "单训练种子 · 每类 3 个独立参数案例 · 误差线为 Wilson 95% 区间；小样本探索，不代表普遍优势", fontsize=9
    )
    for extension in ["png", "svg", "pdf"]:
        fig.savefig(output / f"four-group-comparison.{extension}", dpi=180, bbox_inches="tight")
    plt.close(fig)
    rows = [json.loads(line) for line in (folder / "training.jsonl").read_text().splitlines() if line.strip()]
    sft = [r for r in rows if r["stage"] == "sft"]
    rl = [r for r in rows if r["stage"] == "rl"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), layout="constrained")
    axes[0].plot([r["step"] for r in sft], [r["loss"] for r in sft], color=colors[2], linewidth=1.4)
    axes[0].set(xlabel="SFT 更新步数", ylabel="动作选择交叉熵", title="实际 SFT 训练信号")
    axes[1].plot(
        [r["group"] for r in rl],
        [sum(r["scores"]) / len(r["scores"]) for r in rl],
        color=colors[3],
        marker="o",
        markersize=3,
    )
    axes[1].set(xlabel="RL 采样组", ylabel="训练环境平均回报", title="实际 RL 训练信号")
    retain_keys = keys[1:]
    retain = [summary["retention"][k]["accuracy"] * 100 for k in retain_keys]
    axes[2].bar(labels[1:], retain, color=colors[1:])
    axes[2].set_ylim(0, 110)
    axes[2].set(ylabel="固定回归题正确率（%）", title="原有能力的有限回归检查")
    for i, value in enumerate(retain):
        axes[2].text(i, value + 3, f"{value:.1f}%", ha="center")
    fig.suptitle("训练信号与任务效果分开；8 道回归题不构成全面能力保持证明", fontsize=13)
    for extension in ["png", "svg", "pdf"]:
        fig.savefig(output / f"training-and-retention.{extension}", dpi=180, bbox_inches="tight")
    plt.close(fig)
    (output / "figure-provenance.json").write_text(
        json.dumps(
            {
                "source": "../audited-summary.json",
                "training_source": "../training.jsonl",
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "training_source_sha256": hashlib.sha256((folder / "training.jsonl").read_bytes()).hexdigest(),
                "matplotlib_version": matplotlib.__version__,
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
