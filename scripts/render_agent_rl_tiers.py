"""Compare the three registered tiers without mixing historical test scores."""

import argparse
from html import escape
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    base = parser.parse_args().root.resolve()
    groups = {
        "C_common_sft": "共同 SFT",
        "D_drgrpo": "SFT＋RL",
        "E_more_sft": "继续 SFT",
        "F_experience": "RL＋经验复用",
    }
    tiers = {"simple": "简单业务", "complex": "复杂异常", "future": "变化适应"}
    rows = {}
    for tier in tiers:
        root = base / (tier + "-001")
        rows[tier] = {"prepared": (root / "config.json").exists(), "measurements": {g: [] for g in groups}}
        rule_path = root / "baselines/A_rules-development.json"
        rows[tier]["rules"] = json.loads(rule_path.read_text()) if rule_path.exists() else None
        for path in sorted((root / "validation").glob("*.json")):
            data = json.loads(path.read_text())
            if data["phase"] in groups:
                rows[tier]["measurements"][data["phase"]].append(
                    {"step": data["step"], "successes": data["successes"], "n": data["n"], "source": str(path)}
                )
    target = base / "figures" / (time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000:06d}")
    target.mkdir(parents=True, exist_ok=False)
    (target / "raw-points.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt, font_manager

    font = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
    font_manager.fontManager.addfont(font)
    plt.rcParams.update(
        {
            "font.family": font_manager.FontProperties(fname=font).get_name(),
            "axes.unicode_minus": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    colors = {"C_common_sft": "#64748b", "D_drgrpo": "#167c80", "E_more_sft": "#c77e24", "F_experience": "#8751a3"}
    figure, axes = plt.subplots(1, 3, figsize=(15, 4.8), layout="constrained")
    figure.suptitle(
        "舷鸥 · 三层任务环境 × 相同学习对照\n开发验证记录；空白是尚未测量，非零分；独立测试仍封存", fontsize=15
    )
    table = []
    for axis, (tier, title) in zip(axes, tiers.items()):
        measured = rows[tier]["measurements"]
        rules = rows[tier]["rules"]
        if rules:
            axis.axhline(100 * rules["successes"] / rules["n"], color="#7a7e66", linestyle=":", label="规则参考")
            table.append(
                f"<tr><td>{title}</td><td>规则参考</td><td>0</td><td>{rules['successes']}/{rules['n']}</td></tr>"
            )
        for group, name in groups.items():
            points = sorted(measured[group], key=lambda x: x["step"])
            if group == "C_common_sft" and points:
                axis.axhline(
                    100 * points[0]["successes"] / points[0]["n"], color=colors[group], linestyle="--", label=name
                )
            else:
                axis.plot(
                    [p["step"] for p in points],
                    [100 * p["successes"] / p["n"] for p in points],
                    "o-",
                    color=colors[group],
                    label=name,
                )
            last = points[-1] if points else None
            table.append(
                f"<tr><td>{title}</td><td>{name}</td><td>{last['step'] if last else '—'}</td><td>"
                + (f"{last['successes']}/{last['n']}" if last else "尚未测量")
                + "</td></tr>"
            )
        if not any(measured.values()):
            axis.text(
                0.5,
                0.5,
                "等待共同源 SFT 和本层训练",
                transform=axis.transAxes,
                ha="center",
                va="center",
                color="#64748b",
            )
        axis.set(title=title, xlabel="处理组更新次数", ylabel="从头完成任务 %", xlim=(0, 49), ylim=(-5, 105))
        axis.grid(alpha=0.15)
        axis.legend(fontsize=8, loc="lower right")
    for ext in ["png", "svg", "pdf"]:
        figure.savefig(target / ("three-tier-comparison." + ext), dpi=180)
    plt.close(figure)
    queue = json.loads((base / "QUEUE_STATUS.json").read_text()) if (base / "QUEUE_STATUS.json").exists() else {}
    html = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>舷鸥三层实验</title><style>body{max-width:1280px;margin:32px auto;padding:24px;font:16px system-ui;line-height:1.7;color:#203044}img{width:100%}table{width:100%;border-collapse:collapse}th,td{padding:10px;text-align:left;border-bottom:1px solid #ddd}.note{background:#eef4f5;padding:18px}</style><h1>舷鸥三层任务环境与RL对照</h1>'
    html += (
        "<p>生成时间："
        + time.strftime("%Y-%m-%d %H:%M:%S %z")
        + '</p><p class="note">每层24个训练实例、8个开发实例、24个封存测试实例。共同起点和工具框架相同。当前为开发试跑，不能据此宣布最终RL优势。历史004的24项测试单独保存，不混入这张比较图。</p>'
    )
    html += (
        "<p>队列状态："
        + escape(queue.get("phase", "尚未启动"))
        + '</p><img src="three-tier-comparison.png" alt="简单、复杂、变化适应三个环境中的训练对照"><table><tr><th>任务环境</th><th>学习方法</th><th>最近开发节点</th><th>完整任务完成</th></tr>'
        + "".join(table)
        + "</table>"
    )
    html += '<p>比较时使用相同更新节点；尚未训练的组不能按零分计算。变化适应是受控接口与状态变化，并非对未来港口的预测。</p><p><a href="raw-points.json">原始绘图数据</a> · <a href="three-tier-comparison.pdf">PDF</a> · <a href="three-tier-comparison.svg">SVG</a> · <a href="../../design/DESIGN.json">冻结设计</a></p></html>'
    (target / "report.html").write_text(html)
    relative = (target / "report.html").relative_to(base).as_posix()
    temporary = base / "latest-report.tmp"
    temporary.write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url='
        + relative
        + '"><a href="'
        + relative
        + '">打开最新三层实验报告</a></html>'
    )
    temporary.replace(base / "latest-report.html")
    print(target)


if __name__ == "__main__":
    main()
