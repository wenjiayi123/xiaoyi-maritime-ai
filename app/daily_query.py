from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DailyQueryRule:
    category: str
    patterns: tuple[str, ...]
    canonical_query: str


_RULES = (
    DailyQueryRule(
        category="energy_peak",
        patterns=(
            r"削峰",
            r"错峰用电",
            r"用电峰值.*高",
            r"峰值负荷.*高",
            r"需量.*高",
            r"怎么降峰",
        ),
        canonical_query=(
            "港口如何削峰填谷 降低峰值需求 岸桥场桥冷藏箱岸电充电储能"
        ),
    ),
    DailyQueryRule(
        category="carbon_reduction",
        patterns=(
            r"减少.*碳排",
            r"降低.*碳排",
            r"港口.*减碳",
            r"怎么.*减碳",
            r"降碳",
            r"低碳措施",
            r"节能减排",
            r"脱碳",
            r"碳足迹.*降",
            r"碳盘查",
            r"碳核算",
            r"碳清单",
            r"排放因子",
            r"碳强度",
        ),
        canonical_query=(
            "港口如何减少碳排放 碳盘查 基线 岸电 设备电动化 能效 "
            "可再生能源 储能 船舶等待 集疏运"
        ),
    ),
    DailyQueryRule(
        category="charging",
        patterns=(r"充电.*排", r"集中充电", r"充电高峰", r"充电.*错峰"),
        canonical_query="AGV电动集卡充电如何错峰 充电窗口 SOC 作业计划",
    ),
    DailyQueryRule(
        category="berth_pressure",
        patterns=(
            r"船.*集中到港",
            r"压港",
            r"泊位.*打架",
            r"泊位.*冲突",
            r"前船.*延误.*后船",
        ),
        canonical_query="船舶集中到港 泊位窗口冲突 前船延误 滚动靠泊计划",
    ),
    DailyQueryRule(
        category="crane_efficiency",
        patterns=(
            r"岸桥.*等车",
            r"桥吊.*等车",
            r"岸桥.*效率.*低",
            r"船时效率.*低",
            r"装卸.*效率.*低",
        ),
        canonical_query="岸桥效率低 等待水平运输 船时效率 作业节拍怎么处理",
    ),
    DailyQueryRule(
        category="yard_pressure",
        patterns=(
            r"堆场.*爆满",
            r"堆场.*快满",
            r"场地.*不够",
            r"翻箱.*太多",
            r"备箱.*来不及",
        ),
        canonical_query="堆场占用率高 翻箱过多 出口备箱来不及怎么处理",
    ),
    DailyQueryRule(
        category="gate_pressure",
        patterns=(
            r"闸口.*堵",
            r"集卡.*排队",
            r"车辆.*积压",
            r"预约.*扎堆",
            r"进港.*高峰",
        ),
        canonical_query="闸口车辆排队 预约到车波峰 车道增开 错峰分流",
    ),
    DailyQueryRule(
        category="equipment_queue",
        patterns=(
            r"设备.*排队",
            r"任务.*积压",
            r"场桥.*忙闲不均",
            r"AGV.*拥堵",
            r"设备.*不够用",
        ),
        canonical_query="设备任务积压 场桥忙闲不均 AGV拥堵 任务重排",
    ),
    DailyQueryRule(
        category="system_data",
        patterns=(
            r"TOS.*卡",
            r"系统.*卡顿",
            r"数据.*对不上",
            r"口径.*不一致",
            r"EDI.*失败",
            r"报文.*失败",
        ),
        canonical_query="TOS卡顿 数据不一致 EDI报文失败 降级运行 对账",
    ),
    DailyQueryRule(
        category="customer_update",
        patterns=(
            r"客户.*催",
            r"客户.*追问",
            r"怎么回复客户",
            r"延误.*怎么解释",
            r"信息不确定.*回复",
        ),
        canonical_query="客户追问作业进度 延误说明 信息未确认如何回复",
    ),
    DailyQueryRule(
        category="shift_handover",
        patterns=(
            r"交班.*要交",
            r"交班.*交什么",
            r"交班.*交哪些",
            r"交班.*包含什么",
            r"交接班.*事项",
            r"值班.*交接清单",
        ),
        canonical_query=(
            "交接班哪些事项不能漏 交班必须交代什么 值班交接清单 "
            "未闭环异常 风险状态 责任人 下一动作时间"
        ),
    ),
    DailyQueryRule(
        category="shift_management",
        patterns=(
            r"人手.*不够",
            r"人员.*不足",
            r"临时任务.*插",
            r"多部门.*协调",
            r"交班.*漏",
            r"早会.*怎么",
        ),
        canonical_query="港口班组人员不足 临时任务插入 多部门协调 交接班",
    ),
)


def daily_query_categories(question: str) -> list[str]:
    compact = re.sub(r"[\s，。！？、,.!?]", "", question).casefold()
    return [
        rule.category
        for rule in _RULES
        if any(re.search(pattern, compact, re.IGNORECASE) for pattern in rule.patterns)
    ]


def expand_daily_queries(question: str) -> list[str]:
    queries = [question.strip()]
    compact = re.sub(r"[\s，。！？、,.!?]", "", question).casefold()
    for rule in _RULES:
        if any(
            re.search(pattern, compact, re.IGNORECASE)
            for pattern in rule.patterns
        ):
            queries.append(rule.canonical_query)
    return list(dict.fromkeys(query for query in queries if query))
