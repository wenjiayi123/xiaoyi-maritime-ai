"""Classify explicit requests for physical port control in the research chat interface."""
import re

_FIELD = re.compile(r"生产(?:系统|策略|工单|设备|控制|调度|现场)|现场|真实|真船|实船|实港|在航船舶|危险区域|受限空间|设备联锁|physical|live (?:port|crane|equipment)|production",re.I)
_ACTION = re.compile(
    r"下发|(?:控制|执行|操纵).{0,12}(?:设备|岸桥|吊具|船舶|动作|指令)|发出.{0,8}指令|批准.{0,12}(?:策略|工单|复工|入场|放行)|(?:跳过|绕过|旁路).{0,8}联锁|"
    r"(?:派人|安排人员).{0,8}(?:入场|进入)|(?:重启|启动|停止|解锁|释放|投放|调配).{0,12}(?:设备|吊具|吊机|岸桥|港机|船舶)|"
    r"解除.{0,8}隔离|(?:改写|修改|更改|置位).{0,20}(?:控制器|控制柜|控制参数|阀位|联锁状态)|"
    r"(?:开启|开动|关停|启动|停止).{0,12}(?:输送带|卸船机|泵机|泵站)|(?:指泊|移泊|调度)指令.{0,15}(?:发给|发送至|传达给).{0,8}(?:实船|船舶)|"
    r"(?:dispatch|restart|override|authorize|energize).{0,30}(?:crane|equipment|interlock|physical operation|production plan)",
    re.I,
)
_DIRECTIVE = re.compile(r"请(?:你)?(?:立即|现在|直接|代为|替我|马上|帮我)?|要求|直接|立即|马上|自动批准|替我|代为|我要你|please|(?:^|[。；;])\s*(?:dispatch|restart|override|authorize|energize|下发|派人|重启|启动|绕过|旁路)",re.I)
_EDUCATIONAL = re.compile(r"为什么|为何|解释|如何|怎样|怎么|哪些(?:步骤|条件|证据|资料)|(?:列出|说明|介绍).{0,15}(?:条件|要求|证据|风险|步骤)|(?:核对|核实|检查)是否(?:具备|满足).{0,20}条件|能否直接用于|\b(?:why|explain|what evidence|how to|(?:steps|procedure|sequence) to)\b",re.I)
_NEGATED = re.compile(r"(?:不要|勿|不得|禁止|不能|不许|无需|不必|不应|不允许|do not|never)\s*(?:直接|自动|立即|马上)?\s*$",re.I)
_SIM_ONLY = re.compile(r"仅.{0,8}(?:沙箱|模拟|仿真|演练)|只.{0,8}(?:沙箱|模拟|仿真|演练)|simulation only|sandbox only",re.I)
_NEXT_ACTION = re.compile(r"\s+and then\s+(?=(?:please\s+)?(?:dispatch|restart|override|authorize|energize)\b)",re.I)
_DESCRIBED_SEQUENCE = re.compile(r"\b(?:how to|whether to|why|steps to|procedure to|sequence to)\b",re.I)
_DELEGATE = re.compile(r"替(?:值班员|调度员|班长|公司|当班人员)|帮我|帮公司|^再(?:把|向|将|给)|^\s*(?:pay|wire|remit|forward|send|upload)\b",re.I)
_PAYMENT = re.compile(r"支付|付款|汇款|转账|划款|转给|汇给|\b(?:pay|wire|remit|transfer)\b",re.I)
_SETTLEMENT = re.compile(r"收款(?:方|人|账户)|收款账号|供应商|对方账户|费用|泊位费|港杂费|滞期费|发票款|\b(?:payee|beneficiary|invoice|vendor|supplier|bank account)\b",re.I)
_DISCLOSE = re.compile(r"转发|传送|上传|发往|发送|发给|发到|传到|\b(?:forward|send|upload|email|transfer)\b",re.I)
_SENSITIVE = re.compile(r"未公开|保密|机密|仅限内网|只获准在本机阅读|confidential|nonpublic|internal.only",re.I)
_OUTSIDE = re.compile(r"外部(?:系统|平台|邮箱|公司|机构)|私人邮箱|公共网盘|互联网|公网|external (?:system|portal|email|mailbox)|personal email|public cloud",re.I)
_QUOTE_ONLY = re.compile(r"(?:核对|查看|查询|复核|核实|核算|汇总|整理|摘录).{0,20}(?:回执|凭证|记录|清单|报表|历史|金额)|\b(?:review|read|check|summarize)\b.{0,35}\b(?:ledger|receipt|report|history)\b",re.I)
_NO_TRANSFER = re.compile(r"(?:不要|不得|禁止|切勿|不允许)\s*(?:把|将|向|给).{0,35}$|\b(?:do not|never)\s+(?:actually|directly|automatically)\s*$",re.I)
_PROCEDURE = re.compile(r"(?:说明|介绍|讲解|列出).{0,28}(?:流程|制度|核验步骤|注意事项)|\bwhat (?:is|are) the (?:process|steps|rules)\b",re.I)


def protected_scope(question: str):
    physical = bool(_FIELD.search(question))
    for sentence in re.split(r"[。！？!?；;\n]|(?<!\d)\.(?=\s|$)",question):
        sentence=re.sub(r"^\s*then\s+","",sentence,flags=re.I)
        descriptive=_DESCRIBED_SEQUENCE.search(sentence)
        sentence=_NEXT_ACTION.sub(lambda match: "，" if not descriptive or sentence[match.end():].lower().startswith("please ") else match.group(),sentence)
        for part in re.split(r"[，,]|(?:但|然后|并)(?=请|立即|直接|自动|马上|要求)",sentence):
            if not (_DIRECTIVE.search(part) or _DELEGATE.search(part)) or _EDUCATIONAL.search(part) or _PROCEDURE.search(part):
                continue
            if _SIM_ONLY.search(part) and not re.search(r"真实|对生产系统|实船|physical|live equipment",part,re.I):
                continue
            def affirmative(pattern):
                return any(not _NEGATED.search(part[:m.start()]) and not _NO_TRANSFER.search(part[:m.start()]) for m in pattern.finditer(part))
            if physical and affirmative(_ACTION):
                return "physical"
            if _QUOTE_ONLY.search(part):
                continue
            if _SETTLEMENT.search(part) and affirmative(_PAYMENT):
                return "settlement"
            if _SENSITIVE.search(question) and _OUTSIDE.search(part) and affirmative(_DISCLOSE):
                return "disclosure"
    return None


def requests_field_control(question: str) -> bool:
    """Keep existing chat and historical-command callers on the same restricted-action check."""
    return protected_scope(question) is not None
