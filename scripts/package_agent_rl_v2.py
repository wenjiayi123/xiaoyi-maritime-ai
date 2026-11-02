"""Freeze an audited V2 experiment, earlier negative result and native evidence."""

from __future__ import annotations
import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "A_rules": "A 固定规则",
    "B_base": "B 原始模型",
    "C_sft": "C 冻结 SFT",
    "D_rl": "D SFT＋RL",
    "E_more_sft": "E 继续 SFT",
}


def load(p):
    return json.loads(p.read_text())


def pct(v):
    return "—" if v is None else f"{v * 100:.1f}%"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--job", type=Path, action="append", default=[])
    args = parser.parse_args()
    run, dest = args.experiment.resolve(), args.output.resolve()
    summary = load(run / "audited-summary.json")
    native_audit = load(run / "native-acceptance-audit.json")
    if not summary["audit"]["all_replayed"] or summary["status"] != "completed":
        raise ValueError("completed independent audit required")
    if not native_audit["all_records_replayed"]:
        raise ValueError("native transcript audit required")
    if dest.exists() or dest.with_suffix(".zip").exists():
        raise ValueError("fresh evidence destination required")
    dest.mkdir(parents=True)
    # Explicit source root only: excludes model base, computation cache, runtime
    # databases, credentials, and unrelated workspace files.
    shutil.copytree(run, dest / "experiment")
    for name in [
        "agent-regression.log",
        "agent-regression-final.log",
        "evidence-regression.log",
        "ruff-final.log",
        "frontend-syntax-check.json",
        "frontend-label-syntax-check.json",
        "protected-model-check.json",
        "protected-model-final-check.json",
        "packaging-helper-lint.log",
        "SESSION_STATE.json",
        "session-history.jsonl",
    ]:
        src = run.parent / name
        if src.exists():
            target = dest / "engineering-checks" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    previous = ROOT / ".codex_artifacts/agent-rl-v1-20261101/experiment-003"
    shutil.copytree(previous, dest / "previous-negative-run")
    shutil.copy2(previous.with_suffix(".log"), dest / "previous-negative-run/console.log")
    for name in ["experiment-001", "experiment-002"]:
        shutil.copytree(previous.parent / name, dest / "earlier-attempts" / name)
        shutil.copy2(previous.parent / (name + ".log"), dest / "earlier-attempts" / (name + ".log"))
    oldjob = ROOT / ".runtime/agent-rl-v1/tasks/arj-0bcf516f42dd4760960c9cebccced49a/job.json"
    if oldjob.exists():
        shutil.copy2(oldjob, dest / "previous-negative-run/native-failed-job.json")
    for rel in [
        "docs/AGENT_RL_V2_METHODS_20261102.md",
        "docs/AGENT_RL_V2_ACCEPTANCE_20261102.md",
        "requirements-agent-rl-intel.lock",
        "scripts/audit_agent_rl_v2.py",
        "scripts/audit_agent_rl_native_v2.py",
        "scripts/render_agent_rl_v2.py",
        "scripts/package_agent_rl_v2.py",
        "scripts/probe_agent_rl_mps.py",
        "scripts/refine_agent_rl_selection.py",
        "scripts/evaluate_agent_rl_retention.py",
        "tests/test_agent_training_v2_evidence.py",
        "tests/test_agent_training_v2.py",
        "tests/test_agent_training_v2_native.py",
        "tests/test_agent_training_api.py",
        "scripts/start_agent_rl_v1.py",
        "scripts/serve_agent_rl_v1.py",
        "app/agent_training/live.py",
        "app/agent_training/api.py",
        "web/agent-rl.html",
        "web/agent-rl.js",
        "web/agent-rl.css",
    ]:
        src, target = ROOT / rel, dest / "implementation" / rel
        if src.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    native = []
    native_records = {r["job_id"]: r for r in native_audit["results"]}
    if {load(p / "job.json")["id"] for p in args.job} != set(native_records):
        raise ValueError("package must include all audited native successes and failures")
    for folder in args.job:
        job = load(folder / "job.json")
        key = {"B_base": "initial", "C_sft": "sft", "D_rl": "rl", "E_more_sft": "more_sft"}[job["group"]]
        if job["experiment"] != run.name or job["expected_adapter_sha256"] != summary["weights"][key]:
            raise ValueError("native evidence checkpoint mismatch")
        if (
            hashlib.sha256((folder / "job.json").read_bytes()).hexdigest()
            != native_records[job["id"]]["job_file_sha256"]
        ):
            raise ValueError("native evidence changed after audit")
        target = dest / "native" / job["id"]
        target.mkdir(parents=True)
        for src in folder.iterdir():
            if src.is_file() and (
                src.name in {"job.json", "report.json", "report.html"} or src.name.startswith("evidence-")
            ):
                shutil.copy2(src, target / src.name)
        native.append(job)
    rows = []
    for key, label in LABELS.items():
        g = summary["groups"][key]
        values = [
            label,
            f"{g['successes']}/{g['n']}",
            pct(g["success_rate"]),
            pct(g["parameter_accuracy"]),
            pct(g["recovery_rate"]),
            f"{g['mean_steps']:.2f}",
            pct(summary["retention"].get(key, {}).get("accuracy")),
            pct(summary["independent_retention"]["groups"].get(key, {}).get("accuracy")),
        ]
        rows.append("<tr>" + "".join("<td>" + html.escape(v) + "</td>" for v in values) + "</tr>")
    native_html = []
    for j in native:
        file = "report.html" if j["success"] else "job.json"
        native_html.append(
            f"<li><b>{html.escape(LABELS[j['group']])}：{'完成' if j['success'] else '未完成'}</b>，{len(j['steps'])} 步，{j.get('elapsed_seconds', 0):.1f} 秒。<p>{html.escape(j['goal'])}</p><a href='native/{j['id']}/{file}'>完整结果与证据</a></li>"
        )
    gain = summary["rl_increment"] * 100
    control = summary["rl_vs_continued_sft"] * 100
    example = load(run / "training-step-explanation.json")
    example_html = (
        f"第 {example['step']} 次 RL 参数更新的一个训练例子："
        f"最大概率动作从 <code>{html.escape(json.dumps(example['before_action'], ensure_ascii=False))}</code> "
        f"变为 <code>{html.escape(json.dumps(example['after_action'], ensure_ascii=False))}</code>。"
        f"这两个动作的两步模拟回报分别是 {example['before_return']:.3f} 和 {example['after_return']:.3f}。"
        "这是按时间找到的第一个此类变化，用于说明学习机制，不代表最终测试表现或每一步都会变好。"
    )
    training_text = (
        f"本轮 RL 实际更新 {summary['training_counts']['D_rl']} 步，继续 SFT 更新 {summary['training_counts']['E_more_sft']} 步；"
        f"验证后分别选用第 {summary['selection']['selected']['D_rl']['step']} 步和"
        f"第 {summary['selection']['selected']['E_more_sft']['step']} 步的保存版本。"
        "D 先运行并承担首次缓存生成，E 复用缓存，耗时不能作为严格同条件速度比较。"
    )
    conclusion = (
        "观察到加入 RL 后的完成率高于冻结 SFT。" if gain > 0 else "本轮未观察到加入 RL 后的总体完成率高于冻结 SFT。"
    )
    control_text = (
        "RL 也高于继续 SFT 对照。"
        if control > 0
        else "RL 与继续 SFT 完成率相同，尚不能证明 RL 比额外监督训练更有优势。"
        if control == 0
        else "继续 SFT 的完成率更高，不能宣称 RL 是本轮最有效的额外训练方法。"
    )
    report = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>小懿 RL 实测展示</title>
<style>body{{font:16px/1.75 system-ui,sans-serif;max-width:1160px;margin:auto;padding:32px;background:#f0f4f7;color:#19334a}}section{{padding:25px;background:white;margin:22px 0;border-radius:14px}}h1{{font-size:30px}}h2{{font-size:23px}}table{{border-collapse:collapse;width:100%}}th,td{{border-bottom:1px solid #dce5ec;padding:10px;text-align:left}}img{{width:100%;height:auto}}a{{color:#146b9b}}code{{overflow-wrap:anywhere}}.lead{{font-size:20px}}</style>
<h1>小懿 1.7B：语言模型 RL 本机实验</h1><p>实验 {html.escape(run.name)} · 模型参数真实更新 · 同一 Harness · 全部失败与中间记录保留</p>
<section><p class="lead">{conclusion} D−C 为 <b>{gain:+.1f} 个百分点</b>；D−E 为 <b>{control:+.1f} 个百分点</b>。</p><p>{control_text}</p>
<table><thead><tr><th>组别</th><th>完成数</th><th>完成率</th><th>参数匹配</th><th>故障恢复</th><th>平均调用</th><th>8 题回归</th><th>20 题独立检查</th></tr></thead><tbody>{"".join(rows)}</tbody></table>
<p>单训练种子、8 个已知任务族、24 个留出案例。新参数与开头措辞不等于未知任务泛化。规则基线完整保留；此结果不是 RL 优于所有规则或所有 Harness 的证明。</p></section>
<section><h2>四组主对照与额外训练对照</h2><img src="experiment/figures/four-group-comparison.png"><p><a href="experiment/figures/four-group-comparison.pdf">PDF</a> · <a href="experiment/figures/four-group-comparison.svg">SVG</a></p></section>
<section><h2>奖励、任务表现与优化过程</h2><img src="experiment/figures/reward-trajectories.png"><img src="experiment/figures/training-and-retention.png"><img src="experiment/figures/optimization-details.png">
<p>两步代理回报与完整任务回报分开展示。RL 和继续 SFT 的损失定义不同，不能直接比较其数值高低。每次更新的概率、KL、熵、梯度、耗时及权重摘要全部保存。</p>
<p>{training_text}</p>
<p><a href="experiment/training.jsonl">逐步训练日志</a> · <a href="experiment/figures/plot-data.json">绘图原始数据</a> · <a href="experiment/checkpoint-selection.json">检查点选择</a> · <a href="experiment/parameter-change-audit.json">参数变化证据</a></p></section>
<section><h2>能力保持与检查点选择</h2><img src="experiment/figures/retention-checks.png"><p>原协议检查 128、256、512 步。发现 RL 的 512 步版本完成数提高但 8 题回归退步后，在最终测试前公开登记了每 64 步筛选的修订，两种训练方法采用相同网格与门槛，原选择和全部负结果保留。这属于开发阶段增加验证，不是最初协议未发生变化。</p><p>20 道新检查题在修订筛选执行前冻结，最终选择后才测一次，未用于训练或选模型。题型有限，部分概念与开发检查相近，不能证明全面通用能力保持。</p><p><a href="experiment/selection-grid-amendment.json">选择协议修订</a> · <a href="experiment/selection-refinement-candidates.json">全部候选记录</a> · <a href="experiment/retention-independent-summary.json">独立能力检查原始结果</a></p></section>
<section><h2>实际系统指令验收</h2><p>模型逐步选择动作，连接港口、能碳、马六甲本机原系统 API。故障注入与实际返回明确记录；报告按核验事实自动排版。不同系统的地点和时钟分别记录，仍属于公开数据和工程模拟。先后执行的耗时受模型前缀缓存和下游服务状态影响，不是严格同条件的速度比较。</p><p><a href="experiment/native-acceptance-plan.json">预先固定的三条指令与两组模型</a> · <a href="experiment/native-acceptance-audit.json">全部六次实际执行的离线重放核验</a></p><ol>{"".join(native_html) or "<li>未收录实际系统验收，不能声称通过。</li>"}</ol></section>
<section><h2>向专家解释你做了什么</h2><p>建立可复位多任务环境，设计可核验奖励和公平对照，用环境回报真正更新语言模型 LoRA，并完成留出测试、能力回归和跨系统指令执行。推理时模型输入不含正确字母或奖励；Harness 负责执行选中的登记动作。</p>
<p>{example_html} <a href="experiment/training-step-explanation.json">查看该步完整输入、概率与参数记录</a></p>
<p>本轮采用两步模拟器前瞻的 actor 优化。动作是 13 个工具/参数候选，不是任意参数自由生成；不是长时域 PPO/GRPO，也不是新的基础 RL 算法。</p>
<p><a href="implementation/docs/AGENT_RL_V2_METHODS_20261102.md">方法与复现步骤</a> · <a href="experiment/config.json">冻结配置</a> · <a href="experiment/evaluation-audit.json">独立轨迹重放审计</a> · <a href="manifest.json">全部文件 SHA256 清单</a></p></section>
<section><h2>保留第一轮负结果</h2><p>第一轮 SFT 11/24，SFT＋RL 10/24，联合指令未通过。该记录没有被删除。第二轮还改变了共享反馈和训练环境，跨轮分数变化不能全部归因于 RL。</p><p><a href="previous-negative-run/audited-summary.json">第一轮完整指标</a> · <a href="previous-negative-run/native-failed-job.json">第一轮执行失败记录</a></p></section></html>"""
    (dest / "展示报告.html").write_text(report)
    files = [
        {
            "path": str(p.relative_to(dest)),
            "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in sorted(dest.rglob("*"))
        if p.is_file()
    ]
    (dest / "manifest.json").write_text(
        json.dumps({"schema": "xiaoyi-agent-rl-evidence.v2", "files": files}, ensure_ascii=False, indent=2) + "\n"
    )
    archive = dest.with_suffix(".zip")
    with ZipFile(archive, "w", ZIP_DEFLATED) as z:
        for p in sorted(dest.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(dest.parent))
    archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(archive_hash + "  " + archive.name + "\n")
    print(
        json.dumps(
            {
                "report": str(dest / "展示报告.html"),
                "archive": str(archive),
                "archive_sha256": archive_hash,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
