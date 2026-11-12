"""Preserve continuation002 all results and four traceable figures, no model."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.preserve_agent_expert_evidence import read, write, digest  # noqa: E402
from scripts.evaluate_agent_expert_continuation import verify  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def run():
    root = ROOT / '.codex_artifacts/agent-rl-expert-expansion-20261102'
    verify(root / 'evaluation-002')
    results = read(root / 'evaluation-002/RESULTS.json')
    assert results['completed_attempts'] == results['registered_attempts'] == 176
    assert read(root / 'evaluation-002/process-exit.json')['returncode'] in (0, 2)
    out = root / 'evidence-preservation-002'
    out.mkdir(exist_ok=False)
    origins = ('new_reference_visited_state', 'legacy_core24_full_trajectory_retention')
    labels = ('新增任务参考轨迹状态', '旧任务完整轨迹状态')
    series = {}
    for route in ('E_sft', 'D_rl'):
        log = root / 'continuation-002' / route / 'training.jsonl'
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        assert [r['step'] for r in rows] == list(range(1, 65))
        source_hash = digest(log)
        series[route] = []
        for r in rows:
            d = {k: r[k] for k in ('step', 'loss', 'gradient_norm_before_clip', 'parameter_step_l2',
                                  'parameter_l2_from_parent', 'seconds')}
            d['source'] = dict(file=str(log), sha256=source_hash, line=r['step'])
            d['origins'] = {}
            for origin in origins:
                entries = [e for e in r['details'] if e['origin'] == origin]
                assert len(entries) == 4
                item = {k: float(np.mean([e[k] for e in entries])) for k in ('loss', 'learning_loss', 'kl', 'entropy')}
                item['states'] = [e['state_id'] for e in entries]
                if route == 'E_sft':
                    item['cross_entropy'] = float(np.mean([e['cross_entropy'] for e in entries]))
                else:
                    item['expected_return_before'] = float(np.mean([e['expected_return'] for e in entries]))
                    item['expected_return_after'] = float(np.mean([np.dot(e['probabilities_after'], e['returns']) for e in entries]))
                    item['expected_standardized_advantage'] = float(np.mean([np.dot(e['probabilities'], e['advantages']) for e in entries]))
                d['origins'][origin] = item
            series[route].append(d)
    write(out / 'plot-data.json', series)
    plt.rcParams.update({'font.family': 'Arial Unicode MS', 'axes.unicode_minus': False, 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})

    def finish(fig, name, note):
        fig.text(.02, .015, note, fontsize=9, color='#444444')
        fig.tight_layout(rect=(0, .065, 1, 1))
        for extension in ('png', 'svg'):
            fig.savefig(out / f'{name}.{extension}', dpi=170)
        plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for ax, origin, label in zip(axes, origins, labels):
        rows = series['E_sft']
        ax.plot([r['step'] for r in rows], [r['origins'][origin]['cross_entropy'] for r in rows], color='#316bad')
        ax.set(title=f'SFT交叉熵 · {label}', xlabel='优化器更新序号', ylabel='当前批次4个状态的平均交叉熵')
        ax.grid(alpha=.2)
    finish(fig, '01-sft-loss', '全部64次更新；每批4新＋4旧，状态随批次变化。这不是固定验证集曲线，也不等于任务成功率。')

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    rows = series['D_rl']
    for col, origin, label in zip(range(2), origins, ('新增任务：势函数塑形回报', '旧任务：原始回报')):
        for key, legend, color in [('expected_return_before', '更新前', '#316bad'), ('expected_return_after', '同批状态更新后', '#d17820')]:
            axes[0, col].plot([r['step'] for r in rows], [r['origins'][origin][key] for r in rows], label=legend, color=color)
        axes[0, col].set(title=label, ylabel='精确枚举两步预期回报', xlabel='优化器更新序号')
        axes[0, col].legend()
        axes[1, col].plot([r['step'] for r in rows], [r['origins'][origin]['expected_standardized_advantage'] for r in rows], color='#568752')
        axes[1, col].set(title=f'{label} · 概率加权优势', ylabel='Eπ[标准化两步回报]', xlabel='优化器更新序号')
        for ax in axes[:, col]:
            ax.grid(alpha=.2)
    finish(fig, '02-rl-return-advantage', '温度8；13动作两步仿真枚举，第二步取最优动作；不是当前策略在线完整回合奖励。新旧回报分轴。')

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for route, label, color in [('E_sft', 'SFT＋保持正则', '#316bad'), ('D_rl', 'SFT＋RL＋保持正则', '#d17820')]:
        rows = series[route]
        for ax, key, title in [(axes[0, 0], 'gradient_norm_before_clip', '裁剪前梯度范数'),
                               (axes[0, 1], 'parameter_l2_from_parent', 'LoRA参数相对共同父模型的L2距离')]:
            ax.plot([r['step'] for r in rows], [r[key] for r in rows], label=label, color=color)
            ax.set(title=title, xlabel='优化器更新序号')
        for ax, key, title in [(axes[1, 0], 'kl', '相对共同父模型的KL（温度8）'),
                               (axes[1, 1], 'entropy', '动作分布熵（温度8）')]:
            ax.plot([r['step'] for r in rows], [np.mean([r['origins'][o][key] for o in origins]) for r in rows], label=label, color=color)
            ax.set(title=title, xlabel='优化器更新序号')
    axes[0, 0].set_yscale('log')
    for ax in axes.ravel():
        ax.grid(alpha=.2)
        ax.legend(fontsize=8)
    finish(fig, '03-parameter-gradient', '229,376个LoRA参数；共同起点已有旧能力退化。两路线使用相同复习安排、KL与熵系数；单种子，非普遍优劣结论。')

    fig, axes = plt.subplots(1, 3, figsize=(12, 4.8))
    for ax, split, title in zip(axes, ('legacy_native', 'new_sealed', 'new_native_demo'),
                               ('旧30项 · 各两遍', '新12项留出组合 · 各两遍', '四家族原生演示 · 训练配置')):
        vals = [results['groups'][g][split] for g in ('E_expert_sft2', 'D_expert_rl2')]
        bars = ax.bar(['SFT', 'SFT＋RL'], [100 * v['correct'] / v['registered'] for v in vals], color=['#316bad', '#d17820'])
        ax.set(title=title, ylabel='本轮正确比例（%）', ylim=(0, 117))
        for bar, value in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height()+3, f"{value['correct']}/{value['registered']}", ha='center', fontsize=13)
        ax.axhline(100, color='#888888', linewidth=.8, linestyle='--')
    finish(fig, '04-complete-results', '176次全部展示，无未执行项；重复不算独立任务。两路线旧任务均恢复通过，但新增能力均未验收。')
    write(out / 'ALL_RESULTS.json', results)
    write(out / 'FINDINGS.json', dict(created_at=datetime.now(timezone.utc).isoformat(),
          results=results['groups'], accepted=results['accepted'], primary_delivery_accepted=results['primary_delivery_accepted'],
          interpretation='Both retained all registered old tasks after replay/regularization, neither learned new closed-loop tasks. No RL superiority demonstrated.',
          scope='Single seed, same warm SFT parent, one known physical 24h window. Repeated trials are not independent tasks.'))
    (out / '阅读说明.txt').write_text('''舷鸥港航扩展 continuation002：完整证据保存版
两路线各64更新，真实参数与目标梯度审计通过。176次能力评测全部执行：两版旧任务均60/60，新任务均0/24，原生演示均0/4；新增能力未验收。
本轮是相同退化父模型出发的旧能力修复和新增任务学习。恢复旧任务成功不代表新增任务学会，也未证明RL优越。
两个版本都有旧任务复习及KL/熵正则。RL目标是参考状态上13动作两步枚举预期回报，并非PPO/GRPO、当前策略完整回合在线奖励或真实港口探索。
图01为SFT交叉熵；图02新旧回报分开；图03为梯度、参数距离、KL和熵；图04展示全部成功与失败。原始数据及行号在plot-data.json。没有虚构阴影或置信区间。
同一公开24小时窗口的参数/约束变化不能称为多个独立港口。模型在13动作中选工具；结构化参数、数值核验、报告由程序负责。
旧30项成功版本、此前失败版本及完整审计均保留；后续改进另立实验，不覆盖本轮。
''')
    folders = ['continuation-002', 'evaluation-002', 'training-phase-002', 'evaluation-preparation-phase-002']
    sources = sorted(p for folder in folders for p in (root / folder).rglob('*') if p.is_file())
    sources += [root / 'BASELINE_LOCK.json', Path(__file__).resolve(), ROOT / 'scripts/preserve_agent_expert_evidence.py']
    manifest = [dict(path=str(p), sha256=digest(p), bytes=p.stat().st_size) for p in sources]
    write(out / 'SOURCE_MANIFEST.json', manifest)
    archive = out / '完整训练与评测证据.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for p in sources:
            name = str(p.relative_to(root)) if p.is_relative_to(root) else 'implementation/' + p.name
            z.write(p, name)
        for p in sorted(out.iterdir()):
            if p != archive:
                z.write(p, '展示曲线/' + p.name)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
    assert all(digest(Path(item['path'])) == item['sha256'] for item in manifest)
    audit = dict(passed=True, time=datetime.now(timezone.utc).isoformat(), source_count=len(manifest),
                 archive=str(archive), archive_bytes=archive.stat().st_size, archive_sha256=digest(archive),
                 zip_crc_checked=True, source_hashes_unchanged=True, model_loads=0, training_updates=0,
                 curve_visual_qa='pending')
    write(out / 'PRESERVATION_AUDIT.json', audit)
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == '__main__':
    run()
