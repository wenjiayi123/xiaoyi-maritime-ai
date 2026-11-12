"""Readable observed facts; unchanged thirteen tools and business semantics.

No action is chosen or masked here. Future events, labels, rewards and case IDs
are absent. This engineering revision must be disclosed separately from RL.
"""
from __future__ import annotations

import json

from .expert_environment import ExpertEnvironment

REVISION = 'expert-observed-facts.v2'


def render_observed_facts(state, menu, past_actions):
    def value(item):
        return '未提供' if item is None else json.dumps(item, ensure_ascii=False, separators=(',', ':'))

    known = state['known']
    verified = state['verified']
    lines = [
        '任务：' + state['goal'],
        f"当前目标版本：{state['goal_version']}；已执行操作数：{len(past_actions)}",
        '已确认的用户输入：',
        '基准绿色偏好=' + value(known['baseline_green_preference']),
        '碳价(元/吨)=' + value(known['carbon_price_cny_per_ton']),
        '当前业务约束=' + value(known['requirements']),
        '两项候选绿色偏好=' + value(state['candidates']),
        '工具执行记录（仅已发生事实）：',
        '计算来源已读取=' + ('是' if state['context_read'] else '否'),
        '回执未确认的候选=' + ('无' if state['pending_candidate'] is None else str(state['pending_candidate'] + 1)),
    ]
    for index in range(2):
        record = verified.get(index, verified.get(str(index)))
        lines.append(f"候选{index + 1}：计算回执已取得=" + ('是' if index in state['calculated'] else '否')
                     + '；核验记录=' + ('无' if record is None else value(record)))
    lines += ['最近三个已执行工具=' + ','.join(past_actions[-3:]),
              '最近反馈=' + state['feedback'],
              '可调用工具（始终列全；由你判断下一步）：',
              '；'.join(letter + '=' + name for letter, name in menu.items()),
              '只输出一个工具字母。服务指标是历史模拟窗口箱量完成率，不是现场SLA。']
    return '\n'.join(lines)


class ObservedFactsEnvironment(ExpertEnvironment):
    def prompt(self):
        return render_observed_facts(self.observation(), self.menu(), [s['label'] for s in self.steps])
