"""Build a local, auditable expert demonstration package from completed measurements."""

from __future__ import annotations
import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
LABELS = {"A_rules": "A 固定规则", "B_base": "B 原始模型", "C_sft": "C 仅 SFT", "D_rl": "D SFT＋RL"}


def pct(value):
    return "无数据" if value is None else f"{value * 100:.1f}%"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--job", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.experiment.resolve()
    summary = json.loads((source / "audited-summary.json").read_text())
    if not summary["audit"]["all_replayed"] or summary["status"] != "completed":
        raise SystemExit("completed, audited measurements are required")
    output = args.output.resolve()
    if output.exists() or output.with_suffix(".zip").exists():
        raise SystemExit("use a new output path; existing evidence is preserved")
    output.mkdir(parents=True)
    # Explicit artifact selection: never package runtime databases, credentials or base weights.
    destinations = [
        "config.json",
        "summary.json",
        "audited-summary.json",
        "evaluation-audit.json",
        "task-manifest.json",
        "training.jsonl",
        "source-manifest.json",
        "sft-lineage.json",
        "cpu-cache-verification.json",
        "parameter-change-audit.json",
        "checkpoint-selection.json",
        "sft-demonstrations.json",
        "tasks",
        "evaluations",
        "retention",
        "rollouts",
        "trajectories",
        "checkpoints",
        "source",
        "figures",
    ]
    for name in destinations:
        path = source / name
        target = output / "experiment" / name
        if path.is_dir():
            shutil.copytree(path, target)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    for name in [
        "protected-before.json",
        "protected-after.json",
        "dataset-integrity.json",
        "cpu-probe.json",
        "python-regression.log",
        "frontend-regression.log",
        "agent-targeted-final.log",
    ]:
        path = source.parent / name
        if path.is_file():
            target = output / "engineering-checks" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    if (source.parent / "native-runtime-sources").is_dir():
        shutil.copytree(source.parent / "native-runtime-sources", output / "native-runtime-sources")
    for name in [
        "docs/AGENT_RL_V1_METHODS.md",
        "docs/AGENT_RL_V1_DEMO_GUIDE.md",
        "docs/AGENT_RL_V1_IMPLEMENTATION_20261101.md",
        "docs/AGENT_RL_V1_ACCEPTANCE_20261101.md",
        "requirements-agent-rl-intel.lock",
        "scripts/audit_agent_rl_results.py",
        "scripts/render_agent_rl_report.py",
        "scripts/package_agent_rl_evidence.py",
        "scripts/start_agent_rl_v1.py",
        "scripts/serve_agent_rl_v1.py",
        "app/agent_training/live.py",
        "app/agent_training/api.py",
    ]:
        path = ROOT / name
        if path.is_file():
            target = output / "implementation" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    native = []
    for job_dir in args.job:
        job = json.loads((job_dir / "job.json").read_text())
        if job["experiment"] != source.name:
            raise ValueError("native task belongs to a different experiment")
        if (
            job.get("expected_adapter_sha256")
            != summary["weights"][{"B_base": "initial", "C_sft": "sft", "D_rl": "rl"}[job["group"]]]
        ):
            raise ValueError("native checkpoint identity does not match")
        target = output / "native" / job["id"]
        target.mkdir(parents=True)
        for path in job_dir.iterdir():
            if path.is_file() and (
                path.name in {"job.json", "report.html", "report.json"} or path.name.startswith("evidence-")
            ):
                shutil.copy2(path, target / path.name)
        native.append(job)
    rows = []
    for key, label in LABELS.items():
        group = summary["groups"][key]
        wins = sum(c["success"] for c in group["cases"])
        matches = sum(c["parameter_matches"] for c in group["cases"])
        cells = [
            label,
            f"{wins}/{group['n']}",
            pct(group["success_rate"]),
            f"{pct(group['parameter_accuracy'])}（{matches}/{group['parameter_attempts']}）",
            pct(group["recovery_rate"]),
            f"{group['mean_steps']:.1f}",
            pct(summary["retention"].get(key, {}).get("accuracy")),
        ]
        rows.append("<tr>" + "".join(f"<td>{html.escape(v)}</td>" for v in cells) + "</tr>")
    increment = summary["rl_increment"] * 100
    conclusion = (
        "本轮独立测试观察到 RL 相对同一起点 SFT 的完成率提高。"
        if increment > 0
        else "本轮没有观察到 RL 相对 SFT 的总体完成率提高；参数更新本身不能作为能力提升证明。"
    )
    native_rows = []
    for job in native:
        passed = job["status"] == "completed" and job["success"]
        location = "native/" + job["id"] + "/"
        link = location + ("report.html" if passed else "job.json")
        native_rows.append(
            f"<li><b>{html.escape(LABELS[job['group']])} · {'完成' if passed else '未完成'}</b> · "
            f"{len(job['steps'])} 步 · {job.get('elapsed_seconds', 0):.1f} 秒"
            f'<p>{html.escape(job["goal"])}</p><a href="{link}">查看结果与完整记录</a></li>'
        )
    counts = summary["training_counts"]
    paired = summary["paired_rl_effect"]
    report = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>舷鸥语言模型 RL · 实测证据</title>
<style>body{{font:16px/1.75 system-ui,sans-serif;background:#f0f4f7;color:#183044;max-width:1100px;margin:auto;padding:32px}}
section{{background:white;padding:24px;margin:22px 0;border-radius:14px}}h1{{font-size:30px}}h2{{font-size:22px}}
table{{border-collapse:collapse;width:100%;font-size:15px}}td,th{{padding:10px;border-bottom:1px solid #dce4eb;text-align:left}}
img{{width:100%;height:auto}}a{{color:#14678b}}code{{overflow-wrap:anywhere}}li{{margin-bottom:16px}}.lead{{font-size:19px}}</style>
<h1>舷鸥 1.7B 语言模型强化学习：本机实测</h1>
<p>实验 {html.escape(source.name)} · CPU LoRA · 8 类工具任务 · 原 4B 保持不变</p>
<section><p class="lead">{conclusion} RL 增量为 <b>{increment:+.1f} 个百分点</b>。</p>
<p>比较的是相同工具、候选、任务和调用预算。C→D 有 {paired["failure_to_success"]} 个案例从失败变成功，
{paired["success_to_failure"]} 个从成功变失败。固定规则作为完整基线保留，不能据此声称 RL 普遍优于工程规则。</p>
<table><thead><tr><th>组别</th><th>完成</th><th>完成率</th><th>参数尝试正确率</th><th>故障任务恢复率</th><th>平均调用</th><th>8 题回归</th></tr></thead><tbody>{"".join(rows)}</tbody></table>
<p>单训练种子；24 个合成留出案例，属于已知任务族的新参数组合。未尝试参数显示“无数据”。八道固定题不能证明全面能力保持。</p></section>
<section><h2>四组对照与任务类别</h2><img src="experiment/figures/four-group-comparison.png" alt="实测四组对照">
<p><a href="experiment/figures/four-group-comparison.pdf">PDF</a> · <a href="experiment/figures/four-group-comparison.svg">SVG</a></p></section>
<section><h2>哪些部分是模型学到的</h2><p>语言模型看到目标、状态和 13 个工具/参数候选，生成一个动作字母。Harness 按登记映射执行工具，将实际结果送回模型。
SFT 学习正确示例；RL 从同一个 SFT 检查点出发，根据不同尝试的实际回报更新 LoRA 参数。</p>
<p>本轮 {summary["trainable_parameters"]:,} 个可训练参数；{counts["sft_steps"]} 步 SFT；{counts["rl_sampling_groups"]} 个 RL 采样组，
{counts["rl_rollouts"]} 次尝试，其中 {counts["rl_optimizer_updates"]} 组发生优化器更新。没有自由生成任意 JSON 或数字参数；参数枚举、计算和报告排版由程序完成。</p>
<img src="experiment/figures/training-and-retention.png" alt="实际训练与回归检查">
<p><a href="experiment/training.jsonl">逐次训练日志</a> · <a href="experiment/config.json">训练配置</a> ·
<a href="experiment/evaluation-audit.json">四组轨迹重放审计</a></p></section>
<section><h2>实际系统指令验收</h2><p>以下为本机原系统 API 的单独验收，不加入上面的独立测试得分。模拟读取故障明确标记，失败记录保留。
不同系统的地点、时钟和数据来源分别记录，不作为现场港口联动或下层业务 RL 增益证明。</p>
<ol>{"".join(native_rows) or "<li>尚未收录实际系统验收，不应声称通过。</li>"}</ol></section>
<section><h2>向专家演示的顺序</h2><ol><li>打开项目“启动语言模型RL实验.command”，在实验页下达指令，观察逐步执行与故障恢复。</li>
<li>查看原始结果、参数回执和模型检查点身份，确认不是固定脚本代替模型选择。</li>
<li>比较 C 与 D，分清 SFT 收益和 RL 增量，再查看失败类别及能力回归结果。</li>
<li>展示奖励定义、训练轨迹、LoRA 检查点和可复现命令。说明这是小规模工程研究验证，尚非全任务能力。</li></ol>
<p><a href="implementation/docs/AGENT_RL_V1_METHODS.md">方法与复现说明</a> ·
<a href="implementation/docs/AGENT_RL_V1_ACCEPTANCE_20261101.md">验收结论</a> ·
<a href="experiment/audited-summary.json">全部实测指标</a> · <a href="manifest.json">证据文件摘要清单</a></p></section></html>"""
    (output / "展示报告.html").write_text(report)
    files = [
        {
            "path": str(p.relative_to(output)),
            "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in sorted(output.rglob("*"))
        if p.is_file()
    ]
    (output / "manifest.json").write_text(
        json.dumps({"schema": "xiaoyi-agent-evidence-package.v1", "files": files}, ensure_ascii=False, indent=2) + "\n"
    )
    archive = output.with_suffix(".zip")
    with ZipFile(archive, "w", ZIP_DEFLATED) as z:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(output.parent))
    print(
        json.dumps(
            {
                "report": str(output / "展示报告.html"),
                "archive": str(archive),
                "files": len(files),
                "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
