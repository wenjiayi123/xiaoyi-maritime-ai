from __future__ import annotations

import re
from dataclasses import dataclass

from app.daily_query import expand_daily_queries


@dataclass(frozen=True)
class QuestionDomain:
    id: str
    label: str
    patterns: tuple[str, ...]
    canonical_query: str


@dataclass(frozen=True)
class QuestionForm:
    id: str
    label: str
    patterns: tuple[str, ...]
    canonical_terms: str


DOMAINS = (
    QuestionDomain(
        "port_basics",
        "港口基础与港口体系",
        (
            r"港口是什么",
            r"港口定义",
            r"码头是什么",
            r"港口类型",
            r"港口功能",
            r"港区组成",
            r"港区.*(?:分|区域|组成)",
        ),
        "港口基础 港口类型 功能分区 参与方 运营指标",
    ),
    QuestionDomain(
        "shipping",
        "航运与船公司运营",
        (
            r"船公司",
            r"航线",
            r"船期",
            r"班轮",
            r"航次",
            r"舱位",
            r"租船",
            r"运价",
        ),
        "航运 船公司 航线 船期 航次 订舱 箱管 运价 租船",
    ),
    QuestionDomain(
        "vessel_port_call",
        "船舶航海与进出港",
        (
            r"船舶",
            r"靠泊",
            r"离泊",
            r"到港",
            r"引航",
            r"拖轮",
            r"锚地",
            r"航道",
            r"船别",
            r"船.*早到",
            r"船.*空等",
            r"ETA|ETB|ETD|AIS|VTS",
        ),
        "船舶进出港 ETA ETB ETD 泊位 引航 拖轮 锚地 航道 VTS AIS",
    ),
    QuestionDomain(
        "container_terminal",
        "集装箱码头运营",
        (
            r"集装箱",
            r"箱号",
            r"堆场",
            r"闸口",
            r"岸桥",
            r"场桥",
            r"桥吊",
            r"翻箱",
            r"装船",
            r"卸船",
        ),
        "集装箱码头 泊位 岸桥 场桥 堆场 闸口 翻箱 装卸 水平运输",
    ),
    QuestionDomain(
        "special_cargo",
        "散杂货、液体散货与专业货类",
        (
            r"散货",
            r"件杂货",
            r"矿石",
            r"煤炭",
            r"粮食",
            r"油品",
            r"化工品",
            r"LNG",
            r"滚装",
            r"邮轮",
            r"大件",
            r"超限",
            r"冷链",
        ),
        "散杂货 液体散货 干散货 LNG 油品 化工品 冷链 滚装 邮轮 大件货",
    ),
    QuestionDomain(
        "customs_documents",
        "口岸通关与贸易单证",
        (
            r"海关",
            r"通关",
            r"报关",
            r"查验",
            r"放行",
            r"订舱",
            r"提单",
            r"舱单",
            r"单证",
            r"VGM|EDI|D/O|B/L",
        ),
        "口岸 通关 单证 订舱 提单 舱单 VGM EDI 查验 放行",
    ),
    QuestionDomain(
        "intermodal",
        "多式联运与腹地物流",
        (
            r"海铁",
            r"铁路",
            r"火车",
            r"班列",
            r"公路",
            r"驳船",
            r"内陆港",
            r"集疏运",
            r"短驳",
        ),
        "多式联运 海铁联运 铁路班列 公路集疏运 驳船 内陆港 腹地物流",
    ),
    QuestionDomain(
        "equipment_engineering",
        "港口设备、维护与工程",
        (
            r"设备",
            r"维修",
            r"维护",
            r"保养",
            r"点检",
            r"备件",
            r"故障",
            r"告警",
            r"疏浚",
            r"水深",
            r"码头结构",
            r"裂缝",
            r"护舷",
            r"防波堤",
        ),
        "港口设备 点检 维护 维修 可靠性 备件 港口工程 疏浚 水深 码头结构",
    ),
    QuestionDomain(
        "energy_environment",
        "能源、绿色港口与环境",
        (
            r"能耗",
            r"用电",
            r"岸电",
            r"储能",
            r"削峰",
            r"错峰",
            r"碳排",
            r"减碳",
            r"降碳",
            r"低碳",
            r"脱碳",
            r"节能减排",
            r"温室气体",
            r"碳足迹",
            r"环保",
            r"污水",
            r"粉尘",
            r"噪声",
        ),
        "港口能源 绿色港口 碳排放 碳盘查 减碳 岸电 电动化 能效 储能 可再生能源",
    ),
    QuestionDomain(
        "safety_security",
        "安全、保安与应急",
        (
            r"安全",
            r"危险品",
            r"危险货物",
            r"消防",
            r"火灾",
            r"火情",
            r"泄漏",
            r"受伤",
            r"事故",
            r"保安",
            r"门禁",
            r"没证.*进",
            r"闯入",
            r"尾随",
            r"应急",
            r"台风",
        ),
        "港口安全 HSE 危险品 消防 人员安全 港口设施保安 应急 隔离 恢复",
    ),
    QuestionDomain(
        "smart_port_data",
        "智慧港口与数据系统",
        (
            r"TOS|PCS|EMS|EAM|WMS|OCR|IoT",
            r"系统",
            r"接口",
            r"数据",
            r"数字孪生",
            r"人工智能",
            r"AI",
            r"网络安全",
            r"主数据",
        ),
        "智慧港口 TOS PCS EMS EAM OCR IoT 数据治理 接口 网络安全 AI 数字孪生",
    ),
    QuestionDomain(
        "commercial_legal",
        "商务、法务、保险与金融",
        (
            r"费用",
            r"费率",
            r"合同",
            r"SLA",
            r"索赔",
            r"赔付",
            r"货损",
            r"保险",
            r"滞期",
            r"速遣",
            r"投资",
            r"成本",
            r"客户",
            r"收费",
        ),
        "港口商务 费率 合同 SLA 客户 索赔 保险 法务 投资 成本",
    ),
    QuestionDomain(
        "people_management",
        "人员、组织与运营管理",
        (
            r"人员",
            r"班组",
            r"岗位",
            r"交接班",
            r"值班",
            r"培训",
            r"资质",
            r"早会",
            r"晨会",
            r"运营重点",
            r"多部门",
            r"复盘",
            r"绩效",
        ),
        "港口人员 班组 岗位责任 值班 交接班 培训 资质 复盘 运营管理",
    ),
    QuestionDomain(
        "planning_kpi",
        "计划、经营指标与持续改进",
        (
            r"计划",
            r"调度",
            r"指标",
            r"KPI",
            r"吞吐量",
            r"利用率",
            r"效率",
            r"停时",
            r"预测",
            r"产能",
            r"爆量",
            r"箱量",
        ),
        "港口计划 调度 经营指标 KPI 吞吐量 利用率 效率 停时 预测 产能",
    ),
    QuestionDomain(
        "live_operations",
        "实时状态、自动动作与审计边界",
        (
            r"当前",
            r"现在",
            r"今天",
            r"实时",
            r"本班",
            r"下发",
            r"自动执行",
            r"直接执行",
            r"(?:AI|人工智能|小懿).*建议.*(?:能不能用|可用|执行)",
        ),
        "实时港口状态 业务对象 时间戳 数据质量 连接器 权限 人工确认 审计",
    ),
)


FORMS = (
    QuestionForm("definition", "概念定义", (r"是什么", r"啥是", r"什么意思"), "定义 适用场景 边界"),
    QuestionForm("abbreviation", "术语缩写", (r"缩写", r"全称", r"代表什么"), "英文全称 中文含义 用途"),
    QuestionForm("process", "流程说明", (r"流程", r"程序", r"怎么走"), "流程 步骤 参与方 节点"),
    QuestionForm("role", "角色职责", (r"谁负责", r"职责", r"谁来管"), "职责 边界 协同 人工确认"),
    QuestionForm("comparison", "对比辨析", (r"区别", r"对比", r"一样吗"), "区别 对象 主体 适用场景"),
    QuestionForm("metric", "指标解释", (r"指标", r"说明什么", r"怎么看"), "指标 口径 业务含义"),
    QuestionForm("calculation", "指标计算", (r"怎么算", r"如何计算", r"公式"), "计算公式 输入数据 单位 口径"),
    QuestionForm("cause", "原因分析", (r"为什么", r"原因", r"咋回事"), "直接原因 根因 排查顺序"),
    QuestionForm("impact", "影响评估", (r"有什么影响", r"会影响什么", r"后果"), "影响范围 时间窗 指标 通知"),
    QuestionForm("risk", "风险判断", (r"风险", r"严重吗", r"危险吗"), "风险等级 触发条件 升级阈值"),
    QuestionForm("handling", "异常处置", (r"怎么办", r"咋办", r"咋整", r"怎么处理", r"如何处置"), "确认 隔离 处置 恢复 复盘"),
    QuestionForm("sop", "SOP生成", (r"SOP", r"标准作业", r"处置步骤"), "适用范围 启动条件 步骤 角色 恢复"),
    QuestionForm("decision", "决策建议", (r"要不要", r"是否应该", r"能不能"), "建议 前置条件 风险 替代方案"),
    QuestionForm("priority", "优先级排序", (r"先处理", r"优先", r"先做哪个"), "安全 合规 时间窗 全局影响"),
    QuestionForm("checklist", "检查清单", (r"检查什么", r"核对什么", r"清单"), "对象 数据 设备 人员 单证 记录"),
    QuestionForm("evidence", "数据源与证据", (r"需要什么数据", r"证据", r"依据"), "系统数据 人工记录 时间戳 版本"),
    QuestionForm("interface", "系统接口", (r"接口", r"怎么对接", r"如何同步"), "系统边界 输入 输出 频率 异常"),
    QuestionForm("data_quality", "数据质量", (r"数据不一致", r"数据错误", r"对不上"), "权威来源 采集 传输 纠错 对账"),
    QuestionForm("compliance", "合规审计", (r"合规", r"法规", r"审批"), "辖区 日期 官方证据 审批 审计"),
    QuestionForm("commercial", "商务费用", (r"费用", r"收费", r"结算"), "计费对象 触发条件 合同 证据"),
    QuestionForm("communication", "客户沟通", (r"怎么回复", r"怎么解释", r"客户"), "已确认事实 影响 下一节点 更新时间"),
    QuestionForm("briefing", "汇报摘要", (r"汇报", r"简报", r"总结"), "背景 状态 风险 动作 责任人"),
    QuestionForm("review", "复盘改进", (r"复盘", r"怎么改进", r"如何优化"), "计划实际 偏差 根因 改进 验证"),
    QuestionForm("forecast", "预测预警", (r"预测", r"预警", r"会不会"), "数据窗口 假设 上下界 触发条件"),
    QuestionForm("training", "培训说明", (r"怎么培训", r"新人", r"怎么教"), "对象 目标 场景 测试 记录"),
    QuestionForm("template", "模板生成", (r"模板", r"生成一份", r"整理成"), "字段 责任人 时间 状态 证据"),
)


def _compact(question: str) -> str:
    return re.sub(r"[\s，。！？、,.!?；;：:（）()]+", "", question).casefold()


def question_domains(question: str) -> list[str]:
    compact = _compact(question)
    return [
        domain.id
        for domain in DOMAINS
        if any(re.search(pattern, compact, re.IGNORECASE) for pattern in domain.patterns)
    ]


def question_forms(question: str) -> list[str]:
    compact = _compact(question)
    return [
        form.id
        for form in FORMS
        if any(re.search(pattern, compact, re.IGNORECASE) for pattern in form.patterns)
    ]


def expand_port_queries(question: str) -> list[str]:
    queries = expand_daily_queries(question)
    compact = _compact(question)
    matched_domains = [
        domain
        for domain in DOMAINS
        if any(re.search(pattern, compact, re.IGNORECASE) for pattern in domain.patterns)
    ]
    matched_forms = [
        form
        for form in FORMS
        if any(re.search(pattern, compact, re.IGNORECASE) for pattern in form.patterns)
    ]
    form_terms = " ".join(form.canonical_terms for form in matched_forms[:2])
    for domain in matched_domains[:3]:
        queries.append(
            f"{domain.canonical_query} {form_terms}".strip()
        )
    return list(dict.fromkeys(query for query in queries if query.strip()))
