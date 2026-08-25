from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkforceDailyRule:
    patterns: tuple[str, ...]
    answer: str


_RULES = (
    WorkforceDailyRule(
        patterns=(r"咖啡", r"浓茶", r"能量饮料", r"提神饮料"),
        answer=(
            "一般可以适量饮用，但不要把咖啡因当作替代睡眠的办法；如果容易心悸、"
            "胃部不适、正在服药或有医生限制，应先咨询专业人员。咖啡因可能暂时提神，"
            "也可能造成手抖、焦虑或随后疲倦。港航当班人员应结合值班时段控制摄入，"
            "船员、引航、车辆驾驶、中控调度、起重和检维修岗位不能以饮用咖啡替代"
            "疲劳报告、轮换或替岗。"
        ),
    ),
    WorkforceDailyRule(
        patterns=(r"跑步", r"健身", r"运动", r"打球", r"游泳"),
        answer=(
            "可以根据身体状态循序渐进运动，提前补水、热身，并为恢复留出时间；出现胸痛、"
            "眩晕或异常气短应停止并及时求助。运动后的疲劳、脱水或肌肉酸痛可能影响反应和"
            "动作稳定性。港航当班前应预留恢复时间，船员、引航、驾驶、装卸、系解缆、"
            "起重和检维修岗位若状态未恢复，应报告负责人并评估轮换或替岗。"
        ),
    ),
    WorkforceDailyRule(
        patterns=(r"喝酒", r"饮酒", r"啤酒", r"白酒", r"宿醉"),
        answer=(
            "饮酒后不要驾驶或操作设备，也不要用咖啡、洗澡等方式判断自己已经清醒；"
            "如有持续呕吐、意识异常等情况应及时求助。酒精和宿醉会损害判断、反应和协调。"
            "港航人员应遵守单位酒精管理和适岗制度，船员、引航、车辆驾驶、中控调度、"
            "起重、临水和检维修岗位必须如实报告，由负责人按制度安排检测、停岗或替岗。"
        ),
    ),
    WorkforceDailyRule(
        patterns=(r"吃什么", r"想吃", r"吃点清淡", r"吃辣", r"节食", r"减肥"),
        answer=(
            "优先选择规律、均衡且自己能够耐受的饮食，适量补水；不要在身体不适时勉强"
            "节食，若有明确疾病或饮食限制应听从医生建议。空腹、过饱或胃肠不适可能影响"
            "专注和体力。港航轮班人员应给进食和补水留出时间，驾驶、起重、装卸、临水、"
            "中控和检维修岗位出现眩晕或明显不适时应报告并交接，恢复前不做高风险作业。"
        ),
    ),
    WorkforceDailyRule(
        patterns=(r"没睡好", r"睡不够", r"失眠", r"犯困", r"很困", r"夜班.*累"),
        answer=(
            "先补水、适量进食并尽快安排休息；如果困倦持续或明显不适，应咨询医生。"
            "睡眠不足会降低注意力、反应速度和判断稳定性。对港航当班人员，船员、"
            "引航和车辆驾驶不得疲劳操纵，中控与调度应增加指令复诵，装卸、系解缆、"
            "登高和维修岗位应报告值班负责人并评估替岗，状态未恢复前不要承担高风险作业。"
        ),
    ),
    WorkforceDailyRule(
        patterns=(r"感冒药", r"药.*想睡", r"药.*嗜睡", r"吃药.*困", r"昏昏沉沉"),
        answer=(
            "先查看药品说明书是否提示嗜睡或影响驾驶，必要时咨询医生或药师。药物造成的"
            "昏沉会影响反应、判断和手眼协调。港航岗位应立即报告值班负责人；船舶操纵、"
            "引航、车辆驾驶、起重设备、中控调度和检维修不得在受药物影响时继续关键操作，"
            "应安排替岗。"
        ),
    ),
    WorkforceDailyRule(
        patterns=(r"发烧", r"发热", r"头疼", r"头痛", r"身体不舒服", r"生病.*上班"),
        answer=(
            "先测量并记录症状，适当休息；症状严重、突然加重或持续不缓解时及时就医。"
            "身体不适会影响体力、专注和判断。港航现场应报告班组或值班负责人，中控、"
            "调度、船上值班、装卸、闸口和维修先完成明确交接，高风险操作由状态正常的"
            "人员接替。"
        ),
    ),
    WorkforceDailyRule(
        patterns=(r"压力.*大", r"焦虑", r"心情.*差", r"烦躁", r"走神", r"静不下心"),
        answer=(
            "先短暂休息，把任务拆小，并向可信任的同事或负责人说明状态；持续影响生活时"
            "可寻求专业支持。压力、情绪波动和走神会增加沟通遗漏与误操作。港航班组的"
            "中控、调度、驾驶、装卸和维修岗位应使用指令复诵与双人核对，必要时申请轮换，"
            "不要在注意力不稳定时承担高风险作业。"
        ),
    ),
    WorkforceDailyRule(
        patterns=(r"没吃饭", r"没吃早饭", r"低血糖", r"手.*抖", r"饿.*难受"),
        answer=(
            "先停止当前操作，到安全处补充食物和水；症状明显、加重或不能缓解时及时就医。"
            "眩晕、手抖和体力下降会影响精细操作与判断。港航现场的驾驶、起重、登高、临水、"
            "系解缆和检修岗位应立即报告并交接，由同事替岗，状态恢复前不要继续高风险作业。"
        ),
    ),
    WorkforceDailyRule(
        patterns=(r"太热", r"很热", r"一直出汗", r"中暑", r"快虚脱"),
        answer=(
            "立即到阴凉通风处休息、补水和降温；出现意识异常、持续呕吐或高热时呼叫医疗"
            "救助。高温脱水会降低体力、注意力和反应能力。码头露天装卸、堆场、闸口、"
            "系解缆和船上甲板岗位应执行轮换与防暑制度，报告值班负责人，未恢复前不得"
            "继续临水、登高或设备操作。"
        ),
    ),
    WorkforceDailyRule(
        patterns=(r"大雨.*迟到", r"暴雨.*迟到", r"堵车.*交班", r"赶不上.*交班"),
        answer=(
            "优先保证通勤安全，并尽早通知班组和值班负责人预计延误，不要冒险赶路。"
            "港航连续作业不能出现无人值守或默认交接：调度、中控、闸口、堆场、设备和"
            "船上值班应明确延长当前值守或安排替岗，通过电话或系统完成临时交接，到岗后"
            "再补齐记录。"
        ),
    ),
    WorkforceDailyRule(
        patterns=(r"腰.*疼", r"腰痛", r"腿.*疼", r"肌肉.*疼", r"弯不下"),
        answer=(
            "不要勉强搬抬或扭转，先休息并根据疼痛程度就医评估。活动受限会增加失稳、"
            "跌落和二次受伤风险。港口检维修应向负责人报告并重新做作业前风险评估；登高、"
            "受限空间、重物搬运和临水检修应安排替岗，普通点检也应在动作不受限且有人"
            "监护时进行。"
        ),
    ),
)

_MARITIME_OR_PROFESSIONAL = re.compile(
    r"(港口|港航|航运|海运|海事|船舶|船员|船|在港|引航|码头|泊位|靠泊|待靠|还没靠|离泊|锚地|"
    r"岸桥|场桥|龙门吊|起重|装卸|堆场|闸口|集装箱|系解缆|拖轮|航道|潮汐|"
    r"船期|班轮|舱单|提单|通关|报关|危险品|冷藏箱|岸电|能耗|碳排|削峰|"
    r"运营|生产|作业|现场|值班|班组|交接|交班|排班|调度|设备|维修|检修|告警|"
    r"工单|SOP|法规|标准|合规|证据|索引|电力|用电|电费|峰值|负荷|需量|"
    r"储能|功率|排放|燃料|罚款|豁免|法定|通告|公约|条款|细则|限值|"
    r"模型|算法|接口|系统|工作台|数据|报表|KPI|吞吐量|费率|合同|货损|客诉|"
    r"MARPOL|SOLAS|IMO|MCA|Marine\s*Order|eCFR|"
    r"TOS|PCS|EMS|EAM|VTS|AIS|ETA|ETD|ETB|AGV|QC|RTG|EASTERN\s*HORIZON)",
    re.IGNORECASE,
)
_SMALLTALK_OR_IDENTITY = re.compile(
    r"^(你好|您好|嗨|哈喽|早上好|下午好|晚上好|谢谢|感谢|再见|拜拜|"
    r"你是谁|你叫什么|你来自哪里|谁研发的|谁开发的|你能做什么|你会什么)[呀啊吗呢吧？?！!]*$",
    re.IGNORECASE,
)
_DAILY_CONTEXT = re.compile(
    r"(我|家里|今天|今晚|昨晚|明天|周末|上班|下班|迟到|请假|休息|睡|困|累|"
    r"吃|喝|咖啡|运动|跑步|健身|天气|下雨|太热|太冷|心情|压力|头疼|生病|"
    r"感冒|疼|药|通勤|堵车|约会|旅游|买|穿)",
    re.IGNORECASE,
)


def workforce_daily_answer(question: str) -> str | None:
    compact = re.sub(r"[\s，。！？、,.!?]", "", question).casefold()
    for rule in _RULES:
        if any(re.search(pattern, compact, re.IGNORECASE) for pattern in rule.patterns):
            return rule.answer
    return None


def is_general_workforce_question(question: str) -> bool:
    """Route non-maritime daily/general questions away from an irrelevant RAG hit."""
    compact = re.sub(r"\s+", "", question).strip()
    if len(compact) < 2 or _SMALLTALK_OR_IDENTITY.fullmatch(compact):
        return False
    return (
        _DAILY_CONTEXT.search(compact) is not None
        and _MARITIME_OR_PROFESSIONAL.search(compact) is None
    )
