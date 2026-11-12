"""Locked paired analysis and exportable figures for the formal comparison."""

import argparse
from html import escape
import json
from pathlib import Path
import time

import numpy as np


def read(path):
    return json.loads(path.read_text())


def cluster(task):
    return json.dumps([task["shocks"], task["require_restore"], task["menu_seed"],
                       task["switch_step"], task["timed_revisions"]], sort_keys=True)


def interval(values, tasks, *, replicates=20000, seed=9072026):
    """Pair methods before resampling; parameter repeats remain inside clusters."""
    data = np.asarray(values, dtype=float)
    keys = sorted({cluster(t) for t in tasks})
    labels = [cluster(t) for t in tasks]
    means = np.stack([data[:, [i for i, key in enumerate(labels) if key == k]].mean(axis=1) for k in keys], axis=1)
    rng = np.random.default_rng(seed)
    seeds = rng.integers(0, means.shape[0], size=(replicates, means.shape[0]))
    scenarios = rng.integers(0, means.shape[1], size=(replicates, means.shape[1]))
    samples = means[seeds[:, :, None], scenarios[:, None, :]].mean(axis=(1, 2))
    lo, hi = np.quantile(samples, [0.0125, 0.9875])
    return {"mean_lift": float(data.mean()), "interval_97_5": [float(lo), float(hi)],
            "training_seeds": data.shape[0], "scenario_clusters": len(keys),
            "paired_seed_lifts": data.mean(axis=1).tolist(), "bootstrap_replicates": replicates,
            "scope": "small synthetic scenario set and three training seeds; not field/general-business evidence"}


def read_scores(base, phase, step, tier, seed=None):
    folder = base / "baseline" if seed is None else base / ("seed-" + str(seed)) / "evaluation"
    result = read(folder / (phase + "-%05d-%s.json" % (step, tier)))
    expected = read(base / "tasks" / (tier + ".json"))
    if result["phase"] == "A_rules":
        rows = result["tasks"]
        if [r["case_id"] for r in rows] != [t["case_id"] for t in expected]:
            raise ValueError("rule case alignment")
    else:
        rows = result["trajectories"]
        if [r["task"] for r in rows] != expected:
            raise ValueError("model case alignment")
    return np.array([float(r["success"]) for r in rows])


def analyze(base):
    protocol = read(base / "PROTOCOL.json")
    seeds = protocol["training_seeds"]
    values = {}
    for tier in ["simple", "complex", "future", "retention"]:
        values[tier] = {g: read_scores(base, g, 0, tier) for g in ["A_rules", "C_common_sft"]}
        for g in ["D_drgrpo", "E_more_sft"]:
            values[tier][g] = np.stack([read_scores(base, g, 48, tier, seed) for seed in seeds])
    complex_difference = values["complex"]["D_drgrpo"] - values["complex"]["E_more_sft"]
    complex_result = interval(complex_difference, read(base / "tasks/complex.json"))
    future_mid = {g: np.stack([read_scores(base, g, 24, "future", seed) for seed in seeds])
                  for g in ["D_drgrpo", "E_more_sft"]}
    # Trapezoidal area /48 at fixed nodes0,24,48; common start cancels.
    future_difference = 0.5 * (future_mid["D_drgrpo"] - future_mid["E_more_sft"]) + 0.25 * (
        values["future"]["D_drgrpo"] - values["future"]["E_more_sft"])
    future_result = interval(future_difference, read(base / "tasks/future.json"))
    future_result["final_rl_success_rate"] = float(values["future"]["D_drgrpo"].mean())
    complex_result["passed"] = complex_result["mean_lift"] >= 0.10 and complex_result["interval_97_5"][0] > 0
    future_result["passed"] = (future_result["mean_lift"] >= 0.10 and future_result["interval_97_5"][0] > 0
                               and future_result["final_rl_success_rate"] >= 0.80)
    retention = float(values["retention"]["D_drgrpo"].mean() - values["retention"]["C_common_sft"].mean())
    result = {"complex_primary": complex_result, "future_auc_primary": future_result,
              "retention_change": retention, "retention_passed": retention >= -0.05,
              "statistical_route_passed": bool(complex_result["passed"] or future_result["passed"]),
              "native_acceptance_completed": False, "final_acceptance_passed": False,
              "boundary": "Formal controlled local benchmark only; native task acceptance remains separate"}
    return result, values, future_mid


def render(base, result, values, future_mid):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt, font_manager
    font = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
    font_manager.fontManager.addfont(font)
    plt.rcParams.update({"font.family": font_manager.FontProperties(fname=font).get_name(),
                         "axes.unicode_minus": False, "svg.fonttype": "none", "pdf.fonttype": 42,
                         "axes.spines.top": False, "axes.spines.right": False})
    out = base / "figures" / (time.strftime("%Y%m%d-%H%M%S") + "-%d" % time.time_ns())
    out.mkdir(parents=True)
    names = {"A_rules": "规则参考", "C_common_sft": "共同 SFT", "E_more_sft": "继续 SFT", "D_drgrpo": "SFT＋RL"}
    colors = {"A_rules": "#92987b", "C_common_sft": "#8793a7", "E_more_sft": "#cc8a39", "D_drgrpo": "#18877d"}
    tiers = {"simple": "简单业务", "complex": "复杂异常", "future": "变化适应"}
    def save(fig, stem):
        for suffix in ["png", "svg", "pdf"]:
            fig.savefig(out / (stem + "." + suffix), dpi=180, bbox_inches="tight")
        plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), layout="constrained")
    for ax, (tier, title) in zip(axes, tiers.items()):
        for i, g in enumerate(names):
            v = values[tier][g]
            ax.bar(i, v.mean() * 100, color=colors[g])
            if v.ndim == 2:
                ax.scatter(np.full(v.shape[0], i), v.mean(axis=1) * 100, s=30, color="#182b40", zorder=3)
        ax.set(title=title, xticks=range(4), xticklabels=list(names.values()), ylim=(0, 110), ylabel="完整任务完成率 %")
    fig.suptitle("正式封存测试 · 固定最后权重\n点为各训练种子；规则与共同 SFT 各测一次，未重复计样本")
    save(fig, "three-tier-comparison")
    fig, ax = plt.subplots(figsize=(8, 4.7), layout="constrained")
    common = values["future"]["C_common_sft"].mean()
    for g in ["E_more_sft", "D_drgrpo"]:
        points = np.stack([np.full(3, common), future_mid[g].mean(axis=1), values["future"][g].mean(axis=1)], axis=1)
        ax.plot([0, 24, 48], points.mean(axis=0) * 100, "o-", color=colors[g], label=names[g])
        for row in points:
            ax.plot([0, 24, 48], row * 100, color=colors[g], alpha=0.25)
    ax.set(title="受控接口变化后的适应曲线（全部训练冻结后统一测量）", xlabel="混合任务更新次数", ylabel="完整任务完成率 %", ylim=(-5, 105))
    ax.legend()
    save(fig, "adaptation-curve")
    raw = []
    for seed in read(base / "PROTOCOL.json")["training_seeds"]:
        for g in ["D_drgrpo", "E_more_sft"]:
            for p in sorted((base / ("seed-" + str(seed)) / g).glob("step-*/summary.json")):
                row = read(p)
                raw.append({"seed": seed, **row})
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.2), layout="constrained")
    for seed in read(base / "PROTOCOL.json")["training_seeds"]:
        for g in ["D_drgrpo", "E_more_sft"]:
            rows = [r for r in raw if r["seed"] == seed and r["phase"] == g]
            x = [r["step"] for r in rows]
            if g == "D_drgrpo":
                axes[0].plot(x, [np.mean(r["returns"]) for r in rows], label=str(seed), alpha=0.7)
            if g == "E_more_sft":
                axes[1].plot(x, [r["loss"] for r in rows], label=str(seed), alpha=0.7)
            axes[2].plot(x, [r["gradient_norm"] for r in rows], color=colors[g], alpha=0.45)
    for ax, title in zip(axes, ["RL 采样平均奖励（非测试成绩）", "继续 SFT 训练损失", "梯度范数：绿 RL / 橙 SFT"]):
        ax.set(title=title, xlabel="更新次数")
    axes[0].legend(fontsize=8)
    axes[1].legend(fontsize=8)
    save(fig, "training-curves")
    (out / "raw-points.json").write_text(json.dumps({"final": {t: {g: a.tolist() for g, a in v.items()} for t, v in values.items()},
                                                    "future_mid": {g: a.tolist() for g, a in future_mid.items()},
                                                    "training": raw, "statistics": result}, ensure_ascii=False, indent=2) + "\n")
    text = "统计优势指标通过，仍需原生系统闭环验收。" if result["statistical_route_passed"] and result["retention_passed"] else "尚未达到登记的 RL 优势与能力保持标准。"
    html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>舷鸥正式RL对照</title>'
            '<style>body{max-width:1200px;margin:35px auto;padding:24px;font:17px system-ui;line-height:1.7;color:#24354a}img{width:100%}pre{white-space:pre-wrap;background:#eef3f7;padding:20px}</style>'
            '<h1>舷鸥 · 正式 RL 配对实验</h1><p>' + text + '</p>'
            '<p>3个训练种子；共同起点；D/E各48次更新，梯度动作位置匹配。固定最后权重；所有训练完成后统一开启测试。'
            '这是受控模拟环境，13个工具/参数候选，不能外推成任意新API或真实港口全业务能力。三种子与情景类型有限，区间仍有局限。</p>')
    for stem in ["three-tier-comparison", "adaptation-curve", "training-curves"]:
        html += '<img src="' + stem + '.png"><p><a href="' + stem + '.pdf">PDF</a> · <a href="' + stem + '.svg">SVG</a></p>'
    html += '<pre>' + escape(json.dumps(result, ensure_ascii=False, indent=2)) + '</pre><a href="raw-points.json">全部绘图原始数据</a></html>'
    (out / "report.html").write_text(html)
    relative = (out / "report.html").relative_to(base).as_posix()
    (base / "latest-report.html").write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=' + relative + '"><a href="' + relative + '">正式对照报告</a>')
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    base = parser.parse_args().root.resolve()
    result, values, future_mid = analyze(base)
    (base / "STATISTICS.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(render(base, result, values, future_mid))


if __name__ == "__main__":
    main()
