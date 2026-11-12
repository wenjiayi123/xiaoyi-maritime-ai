"""Archive completed experiment and plot actual logs, without loading a model."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
import zipfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_agent_expert import verify  # noqa: E402


def read(p):
    return json.loads(p.read_text())


def write(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def digest(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run():
    root = ROOT / ".codex_artifacts/agent-rl-expert-expansion-20261102"
    verify(root / "evaluation-001")
    results = read(root / "evaluation-001/RESULTS.json")
    assert results["completed_attempts"] == 176
    out = root / "evidence-preservation-001"
    out.mkdir(exist_ok=False)
    plt.rcParams.update({"font.family": "Arial Unicode MS", "axes.unicode_minus": False,
                         "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    series = {}
    for route in ("E_sft", "D_rl"):
        log = root / "training-001" / route / "training.jsonl"
        rows = [json.loads(x) for x in log.read_text().splitlines()]
        assert len(rows) == 64 and [r["step"] for r in rows] == list(range(1, 65))
        derived = []
        for r in rows:
            d = {k: r[k] for k in ("step", "loss", "gradient_norm_before_clip",
                 "parameter_step_l2", "parameter_l2_from_parent", "seconds")}
            d["state_group"] = r["minibatch"]["origin"]
            d["source"] = {"file": str(log), "sha256": digest(log), "line": r["step"]}
            if route == "D_rl":
                details = r["details"]
                for key in ("expected_return", "kl", "entropy"):
                    d[key] = float(np.mean([x[key] for x in details]))
                d["expected_return_after"] = float(np.mean([
                    np.dot(x["probabilities_after"], x["returns"]) for x in details]))
                d["expected_standardized_advantage"] = float(np.mean([
                    np.dot(x["probabilities"], x["advantages"]) for x in details]))
            derived.append(d)
        series[route] = derived
    write(out / "plot-data.json", series)

    def finish(fig, name, note):
        fig.text(.02, .015, note, fontsize=9, color="#444444")
        fig.tight_layout(rect=(0, .065, 1, 1))
        for suffix in ("png", "svg"):
            fig.savefig(out / f"{name}.{suffix}", dpi=170)
        plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7))
    for ax, origin, label in zip(axes, ("new_tasks", "retention"), ("新增任务状态", "旧任务保持状态")):
        rr = [x for x in series["E_sft"] if x["state_group"] == origin]
        ax.plot([x["step"] for x in rr], [x["loss"] for x in rr], "o-", ms=3, color="#316bad")
        ax.set(title=f"SFT交叉熵 · {label}", xlabel="优化器更新序号", ylabel="当前小批次平均损失")
        ax.grid(alpha=.2)
    finish(fig, "01-sft-loss", "全部原始点；每批状态不同，连线仅辅助阅读；不是固定验证集曲线，不加虚构置信区间。")

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for col, origin, label in zip(range(2), ("new_tasks", "retention"), ("新增任务：塑形回报", "旧任务：原回报")):
        rr = [x for x in series["D_rl"] if x["state_group"] == origin]
        for key, name, color in [("expected_return", "本次更新前", "#316bad"), ("expected_return_after", "同批状态更新后", "#d17820")]:
            axes[0, col].plot([x["step"] for x in rr], [x[key] for x in rr], "o-", ms=3, label=name, color=color)
        axes[0, col].set(title=label, xlabel="优化器更新序号", ylabel="精确枚举两步预期回报")
        axes[0, col].legend()
        axes[1, col].plot([x["step"] for x in rr], [x["expected_standardized_advantage"] for x in rr], "o-", ms=3, color="#568752")
        axes[1, col].set(title=f"{label} · 概率加权优势", xlabel="优化器更新序号", ylabel="Eπ[(Q−动作均值)/max(动作标准差,0.1)]")
        for ax in axes[:, col]: ax.grid(alpha=.2)
    finish(fig, "02-rl-return-advantage", "新旧回报分轴展示；13动作、两步仿真枚举，非在线采样完整回合奖励。各步批次不同，不代表验证成功率。")

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for route, label, color in [("E_sft", "SFT", "#316bad"), ("D_rl", "SFT＋RL", "#d17820")]:
        rr = series[route]
        for ax, key, title in [(axes[0, 0], "gradient_norm_before_clip", "裁剪前梯度范数"), (axes[0, 1], "parameter_l2_from_parent", "LoRA参数相对各自起点的L2距离")]:
            ax.plot([x["step"] for x in rr], [x[key] for x in rr], label=label, color=color)
            ax.set(title=title, xlabel="优化器更新序号")
            ax.legend()
    axes[0, 0].set_yscale("log")
    for origin, label, color in [("new_tasks", "新任务", "#316bad"), ("retention", "旧任务", "#d17820")]:
        rr = [x for x in series["D_rl"] if x["state_group"] == origin]
        for ax, key, title in [(axes[1, 0], "kl", "RL相对自身父模型的KL（训练温度2）"), (axes[1, 1], "entropy", "RL动作分布熵（训练温度2）")]:
            ax.plot([x["step"] for x in rr], [x[key] for x in rr], "o-", ms=3, label=label, color=color)
            ax.set(title=title, xlabel="优化器更新序号")
            ax.legend()
    for ax in axes.ravel(): ax.grid(alpha=.2)
    finish(fig, "03-parameter-gradient", "229,376个可训练LoRA参数；两路线父权重不同，SFT无同样KL约束。梯度或参数变化不等于业务能力提升。")

    fig, axes = plt.subplots(1, 3, figsize=(12, 4.8))
    for ax, split, title in zip(axes, ("legacy_native", "new_sealed", "new_native_demo"), ("旧30项复测 · 各两遍", "新12项留出配置 · 各两遍", "四类原生演示 · 训练配置")):
        vals = [results["groups"][g][split] for g in ("E_expert_sft", "D_expert_rl")]
        bars = ax.bar(["SFT", "SFT＋RL"], [100*v["correct"]/v["registered"] for v in vals], color=["#316bad", "#d17820"])
        ax.set(title=title, ylabel="本轮正确比例（%）", ylim=(0, 117))
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+3, f'{v["correct"]}/{v["registered"]}', ha="center", fontsize=13)
        ax.axhline(100, color="#888888", linewidth=.8, linestyle="--")
    finish(fig, "04-complete-results", "176次全部展示，无未执行项；重复不算独立样本。新增能力均未验收；旧能力差异不是同起点RL优越性的证明。")

    findings = {"created_at": datetime.now(timezone.utc).isoformat(), "purpose": "Preserve all results including loss of old capabilities", "accepted_new_version": False,
        "training_only_diagnostic": {
            route: {"first_four_new_losses": [r["loss"] for r in rows if r["state_group"] == "new_tasks"][:4],
                    "last_four_new_losses": [r["loss"] for r in rows if r["state_group"] == "new_tasks"][-4:],
                    "last_parent_l2": rows[-1]["parameter_l2_from_parent"]} for route, rows in series.items()},
        "results": results["groups"], "boundaries": ["Different parent weights and training histories", "RL has KL and entropy terms absent in SFT", "No universal or causal superiority claim", "One public historical24h window, not multiple independent ports", "New task completion failed for both", "Old30 accepted weights/package remain unchanged"]}
    write(out / "FINDINGS.json", findings)
    write(out / "ALL_RESULTS.json", results)
    text = """舷鸥港航专家扩展实验：证据保存版
本轮训练参数审计通过，但新增业务能力未验收。共176次评测，全部成功和失败均保留。
旧能力保持：SFT 8/60，SFT＋RL 60/60；新任务两版0/24；原生演示两版0/4。
旧版30项成功版本不被覆盖。两条路线父权重和训练约束不同，不能把差异全部归因于RL。
“学习新任务后旧能力退化”是应当保留的现象；本轮也未证明新任务已经学会。
图01为SFT当前小批次损失；图02为RL两步枚举预期回报与优势；图03为梯度、参数、KL和熵；图04为全部结果。
plot-data.json逐点指向原始training.jsonl及行号。没有平滑、挑选点或虚构置信区间。
原始训练/优化器/RNG/全部检查点/评测轨迹/工具回执/数据/协议/审计在同目录ZIP中保存。
RL实际为有限13动作的两步枚举策略优化，非PPO/GRPO或真实港口在线探索。规则负责参数处理、数值核验和报告。
"""
    (out / "阅读说明.txt").write_text(text)
    source_dirs = ["training-001", "evaluation-001", "tasks-002", "corpus-001", "training-phase-001", "evaluation-preparation-phase-001", "live-registration-001"]
    sources = sorted(p for folder in source_dirs for p in (root/folder).rglob("*") if p.is_file())
    sources += [root/"BASELINE_LOCK.json", Path(__file__).resolve()]
    manifest = [{"path": str(p), "sha256": digest(p), "bytes": p.stat().st_size} for p in sources]
    write(out / "SOURCE_MANIFEST.json", manifest)
    archive = out / "完整训练与评测证据.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for p in sources:
            name = str(p.relative_to(root)) if p.is_relative_to(root) else "implementation/"+p.name
            z.write(p, name)
        for p in sorted(out.iterdir()):
            if p != archive: z.write(p, "展示曲线/"+p.name)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
    assert all(digest(Path(x["path"])) == x["sha256"] for x in manifest)
    write(out / "PRESERVATION_AUDIT.json", {"passed": True, "source_count": len(manifest), "all_sources_unchanged": True,
        "archive": str(archive), "archive_bytes": archive.stat().st_size, "archive_sha256": digest(archive),
        "zip_crc_checked": True, "model_loads": 0, "new_training_updates": 0, "curve_visual_qa": "pending"})
    print(json.dumps({"saved": str(out), "sources": len(manifest), "archive_bytes": archive.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    run()
