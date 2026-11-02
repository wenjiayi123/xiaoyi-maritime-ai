(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  const steps = [
    { phase:"00 场景证据", title:"已训练场景算法与数据清单", label:"显示全部已训练场景", selector:'[data-demo-evidence-open]', waitSelector:'.demo-evidence-panel[data-state="ready"]', closeSurface:true,
      script:"逐个场景核对实际训练算法、数据集名称与记录数、State状态、Reward奖励、Action动作和输出。每张卡保留训练记录、来源文件与SHA-256；真实观测、派生量、模拟状态和未准入候选分别注明。" },
    {
      phase:"01 系统开场", title:"系统价值与安全边界", label:"查看系统状态", selector:'[data-action="system-status"]',
      script:"这套小懿AI把证据问答、数据治理、强化学习和跨系统编排接成一条可审计链。先看运行边界：本机应用可用不等于现场系统在线，当前保持推荐模式，生产写入和调度权限关闭。"
    },
    {
      phase:"01 小懿对话", title:"填入一般知识问题", label:"填入一般问题", selector:'[data-chat-demo-prompt="general"]', closeSurface:true, waitSelector:'#question[data-demo-chat-category="general"]',
      script:"先演示一般问答。我点击蓝色模板，只把问题真实填进下方输入框；此时还没有答案，观众能看清我准备问的是TOS与PCS的职责及协同关系。"
    },
    {
      phase:"01 小懿对话", title:"发送并等待一般回答", label:"发送一般问题", selector:'html[data-demo-chat-category="general"] #askBtn', context:'[data-chat-demo-prompt="general"]', waitSelector:'#assistantMessage[data-demo-chat-category="general"][data-demo-chat-complete="true"]', timeoutMs:240000,
      script:"现在点击页面原有的发送键。小懿会依次显示理解意图、检索知识、组织回答和证据校验，蓝色回答强调概念解释、职责边界与来源依据；回答完成后我再进入下一题。"
    },
    {
      phase:"01 小懿对话", title:"填入日常运营问题", label:"填入日常问题", selector:'[data-chat-demo-prompt="daily"]', waitSelector:'#question[data-demo-chat-category="daily"]',
      script:"第二轮是日常运营问答。我把岸桥单位作业能耗偏高的问题填入同一个输入框，让小懿从值班人员的实际工作顺序来回答。"
    },
    {
      phase:"01 小懿对话", title:"发送并等待日常回答", label:"发送日常问题", selector:'html[data-demo-chat-category="daily"] #askBtn', context:'[data-chat-demo-prompt="daily"]', waitSelector:'#assistantMessage[data-demo-chat-category="daily"][data-demo-chat-complete="true"]', timeoutMs:240000,
      script:"这次仍走真实问答链路。绿色回答不只解释概念，而是给出现象判断、排查先后、岗位交接和复核动作，展示小懿对日常运营工作的可执行支持。"
    },
    {
      phase:"01 小懿对话", title:"填入紧急处置问题", label:"填入紧急问题", selector:'[data-chat-demo-prompt="emergency"]', waitSelector:'#question[data-demo-chat-category="emergency"]',
      script:"第三轮是紧急问答。我把冷藏箱区域冒烟的问题填入输入框，现场演示同一个小懿如何切换到应急SOP表达，而不是展示预先排好的静态卡片。"
    },
    {
      phase:"01 小懿对话", title:"发送并等待紧急回答", label:"发送紧急问题", selector:'html[data-demo-chat-category="emergency"] #askBtn', context:'[data-chat-demo-prompt="emergency"]', waitSelector:'#assistantMessage[data-demo-chat-category="emergency"][data-demo-chat-complete="true"]', timeoutMs:240000,
      script:"红色回答会优先给出停止危险作业、人员隔离、报警通报和禁止盲目处置等动作，再补充恢复门禁与审计要求。三轮都是逐题输入、逐题等待、逐题形成真实对话记录。"
    },
    {
      phase:"01 证据底座", title:"进入港航知识库", label:"打开知识库", selector:'.top-nav [data-view-target="knowledge"]', closeSurface:true,
      script:"小懿不是只靠大模型生成答案，而是先检索登记过的港航知识，再把结论和证据对应起来（先找依据，再组织回答）。"
    },
    {
      phase:"01 证据底座", title:"核验官方来源", label:"查看来源审计", selector:'[data-action="knowledge-sources"]', context:'.top-nav [data-view-target="knowledge"]',
      script:"这里能看到发布机构、版本、辖区、来源网址和校验状态。官方目录、摘要和正文会分开标记，避免把“能搜到”误说成“已有完整官方正文”。"
    },
    {
      phase:"02 RL训练", title:"进入真实训练与证据中心", label:"打开训练中心", selector:'.top-nav [data-view-target="rl"]', closeSurface:true,
      script:"强化学习部分不是播放动画：四种RL算法与PID、现场SOP强基线共享同一数据划分和约束，训练完成后才读取保留测试段。"
    },
    {
      phase:"02 RL训练", title:"训练数据与官方来源", label:"查看数据集血缘", selector:'[data-rl-center-action="show-datasets"]', context:'.top-nav [data-view-target="rl"]',
      script:"数据集会同时展示官方来源、许可、行数、字段、SHA-256和适用边界。UCI用于能源算法公开基准，NOAA与美国海岸警卫队AIS用于港区交通场景；校准运营量不是现场KPI。"
    },
    {
      phase:"02 RL训练", title:"解释State、Action与Reward", label:"展开训练契约", selector:'[data-rl-center-action="show-contract"]', context:'.top-nav [data-view-target="rl"]', closeSurface:true,
      script:"这里把状态、动作、目标函数和硬约束落到代码契约：状态描述港区态势，动作是有界调度档位，奖励衡量服务收益、等待、能耗和风险，硬约束始终优先。"
    },
    {
      phase:"02 RL训练", title:"配置六候选对比", label:"配置六算法对比", selector:'[data-rl-center-action="start-training"]', context:'.top-nav [data-view-target="rl"]', closeSurface:true,
      script:"训练任务可以选择数据集、回合、时域和随机种子，并同时比较Q-learning、SARSA、Expected SARSA、Double Q-learning、PID与SOP规则。参数可复现，强基线不会冒充RL。"
    },
    {
      phase:"02 价值证据", title:"查看已训练业务指标", label:"正式证据与失败候选", selector:'[data-rl-center-action="show-evidence"]', context:'.top-nav [data-view-target="rl"]', closeSurface:true,
      script:"这里看的是已保存的正式训练证据：多数据集、多种子、验证集选模、保留测试和失败候选都被保留。系统展示区间和准入结果，不把一次高分包装成生产收益。"
    },
    {
      phase:"03 小懿联动", title:"让小懿解释训练证据", label:"询问小懿训练顾问", selector:'[data-rl-advisor-prompt*="公开数据有多少行"]', waitSelector:'.rl-advisor-message.assistant:last-child small', timeoutMs:25000, context:'.top-nav [data-view-target="rl"]', closeSurface:true,
      script:"我可以直接问小懿哪套数据更可信。它只根据当前数据目录、环境契约、运行记录和证据回答（不是凭宣传语补数字）。"
    },
    {
      phase:"03 小懿联动", title:"打开智能联动中心", label:"进入智能联动中心", selector:'#intelligenceHubBtn',
      script:"联动中心把自然语言意图转换为白名单能力计划，并分层展示知识证据、业务系统结果、推演结果和交接入口；默认只做dry-run（安全预览）。"
    },
    {
      phase:"03 小懿联动", title:"自然语言跨系统编排", label:"开始安全编排", selector:'#genericModal [data-action="hub-run-demo"]', waitSelector:'#hubOrchestrationResult .hub-run-summary', timeoutMs:30000, context:'#intelligenceHubBtn',
      script:"这条指令会识别港口、泊位和时间范围，选择可用能力并生成可审计步骤。此处只规划和解释，不自动改变其他系统。"
    },
    {
      phase:"03 小懿联动", title:"查看四系统交接回执", label:"打开四系统回执", selector:'#genericModal [data-action="system-linkage"]', context:'#intelligenceHubBtn',
      script:"小懿把数字孪生、能碳驾驶舱、马六甲沙盘和航行模拟器统一成回执入口。每个系统仍保留自己的业务逻辑、权限和失败状态，小懿只负责安全编排与交接。"
    },
    {
      phase:"03 跨系统闭环", title:"启动并确认能碳系统在线", label:"启动能碳系统", selector:'#genericModal [data-linkage-start="energy-cockpit"]', context:'#systemLaunchHubBtn', waitSelector:'[data-system-linkage-card="energy-cockpit"].online', timeoutMs:60000,
      script:"现在只启动本次需要的能碳驾驶舱，而不是一次拉起所有大系统。启动后小懿会先确认目标本机接口在线，再允许下一步业务试算。"
    },
    {
      phase:"03 跨系统闭环", title:"打开八项能力实操矩阵", label:"打开八项能力矩阵", selector:'#genericModal [data-action="linked-agent"]', context:'#systemLaunchHubBtn',
      script:"这里不是一句‘小懿有八项能力’，而是八个可点击的真实白名单动作：数字孪生2项、能碳2项、马六甲3项、航行隔离核验1项。每项都写明目标系统、参数边界和是否会改变模拟状态。"
    },
    {
      phase:"03 跨系统闭环", title:"核验八项能力接口状态", label:"八项能力联动体检", selector:'#genericModal [data-la-check-capabilities]', contextChain:['#systemLaunchHubBtn','#genericModal [data-action="linked-agent"]'], waitSelector:'#genericModal [data-la-capability-audit="complete"]', timeoutMs:10000,
      script:"我现在一次读取四个目标的真实接口状态。八张能力卡会同步标出在线、离线或隔离核验；这一步只做快速体检，不启动大系统、不执行写操作，现场几秒内就能说明小懿到底能联动什么。"
    },
    {
      phase:"03 跨系统闭环", title:"让小懿执行能碳参数对比", label:"一键执行能碳试算", selector:'#genericModal [data-la-demo-energy]', contextChain:['#systemLaunchHubBtn','#genericModal [data-action="linked-agent"]'], waitSelector:'#genericModal [data-la-status="completed"][data-la-action="energy.compare"]', timeoutMs:30000,
      script:"这一步是真正的跨系统操作：小懿读取能碳当前状态，在同一公开数据集上对比绿色偏好 0.50 和 0.82、试算碳价 100，并回写成本、减排、数据哈希和 trace ID。它不改变生产参数。"
    },
    {
      phase:"03 跨系统闭环", title:"进入目标系统RL训练配置", label:"打开能碳 RL 配置", selector:'#genericModal [data-la-open-rl="energy-cockpit"]', contextChain:['#systemLaunchHubBtn','#genericModal [data-action="linked-agent"]'],
      script:"从小懿直接打开能碳驾驶舱原生RL训练配置。目标页面会同时展开数据集、算法、State、Action、Reward和训练参数；顶部的双向任务链可把配置结果再回传小懿。"
    },
    {
      phase:"03 跨系统闭环", title:"核验小懿·能碳双向回执", label:"完成闭环核验", selector:'#genericModal [data-action="ack-roundtrip-receipt"]',
      script:"能碳系统已把业务目标、数据集、当前策略、安全边界和 trace ID 回传小懿。这才是最关键的联动能力：自然语言下发目标，目标系统原生处理，再把可审计证据带回；生产写入始终关闭。"
    },
    {"phase": "04 Harness核心", "title": "Harness任务工作台", "label": "打开任务工作台", "selector": "#harnessConsoleBtn", "script": "Harness将任务目标、预算、真实工具调用、检查点和证据绑定到同一任务编号，关闭界面后任务仍可恢复。", "closeSurface": true, "waitSelector": "#harnessConsole [data-hx-capabilities] p"},
    {"phase": "04 Harness核心", "title": "同一快照的多工具业务任务", "label": "填入联合研判任务", "selector": "[data-hx=\"briefing-preset\"]", "script": "明确选择规则驱动，演示同一快照的问数、风险、情景比较和交接草稿。后面再单独展示真实4B模型调用工具，二者分别记账。", "waitSelector": "#harnessConsole[data-hx-preset=\"port-briefing\"]"},
    {"phase": "04 Harness核心", "title": "运行Harness联合研判", "label": "执行多工具任务", "selector": "[data-hx=\"create\"]", "script": "真实调用工具，逐项显示调用耗时、预算、来源和输出。只在后端任务完成后继续；工程模拟数据和现场观测分别标明。", "timeoutMs": 90000, "waitSelector": "[data-hx-task-status=\"completed\"]"},
    {"phase": "04 Harness核心", "title": "检查任务执行轨迹", "label": "展开执行轨迹", "selector": "[data-hx-trace] summary", "script": "从任务编号追到实际工具调用和检查点事件，可以复核失败与恢复，不仅看最终回答。", "waitSelector": "[data-hx-trace][open] .hx-events"},
    {"phase": "04 Harness核心", "title": "导出可校验任务回执", "label": "导出Harness回执", "selector": "[data-hx=\"export\"]", "script": "导出任务、工具工件与事件链；以实际返回的完整性校验为准。", "waitSelector": "#harnessConsole[data-hx-export-valid=\"true\"]"},
    {"phase": "04 Harness核心", "title": "双模式联合系统", "label": "打开双模式联合系统", "selector": "#jointHarnessBtn", "script": "企业受控模式和RL策略研究模式共用编排与回执。这里先生成具体计划，未经审批不会执行跨系统动作。", "closeSurface": true, "waitSelector": "#jointHarness [data-jh=\"preview\"]"},
    {"phase": "04 Harness核心", "title": "生成需要审批的联合计划", "label": "生成联合计划", "selector": "[data-jh=\"preview\"]", "script": "实际保存目标、步骤、配置和计划摘要，观察人工审批门禁；原有策略与训练数据不受影响。", "waitSelector": "[data-jh-status=\"waiting_approval\"]"},
    {"phase": "04 Harness核心", "title": "验证拒绝执行门禁", "label": "拒绝本次计划", "selector": "[data-jh=\"reject\"]", "script": "拒绝刚才的具体计划，确认停止而不执行。拒绝回执仍保留，不用成功动画掩盖真实状态。", "waitSelector": "[data-jh-status=\"rejected\"]"},
    {"phase": "05 核心实证", "title": "进入能力实证演示", "label": "打开能力实证", "selector": "#proofConsoleBtn", "script": "下面执行独立实证台的全部八步，并补上V6独立留出、年度孪生与DCSA异常演练；历史失败同样保留。", "closeSurface": true, "waitSelector": "#proofConsole [data-pf-guide]"},
    {"phase": "05 核心实证", "title": "证据问答", "label": "执行证据问答", "selector": "[data-pf=\"run\"][data-kind=\"knowledge\"]", "script": "真实读取或计算，等待带事件链与结果哈希的回执；演示动作完成不替代业务准入。", "timeoutMs": 120000, "waitSelector": "[data-pf-kind=\"knowledge\"][data-pf-status=\"completed\"][data-pf-integrity=\"true\"]"},
    {"phase": "05 核心实证", "title": "问数与隔离推演", "label": "执行问数与隔离推演", "selector": "[data-pf=\"run\"][data-kind=\"facts\"]", "script": "真实读取或计算，等待带事件链与结果哈希的回执；演示动作完成不替代业务准入。", "timeoutMs": 120000, "waitSelector": "[data-pf-kind=\"facts\"][data-pf-status=\"completed\"][data-pf-integrity=\"true\"]"},
    {"phase": "05 核心实证", "title": "联合资源优化", "label": "执行联合资源优化", "selector": "[data-pf=\"run\"][data-kind=\"optimization\"]", "script": "实时求解联合资源问题，保留四个比较基线、最优性界限、来源和合成假设。", "timeoutMs": 120000, "waitSelector": "[data-pf-kind=\"optimization\"][data-pf-status=\"completed\"][data-pf-integrity=\"true\"]"},
    {"phase": "05 核心实证", "title": "RL与强基线回放", "label": "执行RL与强基线回放", "selector": "[data-pf=\"run\"][data-kind=\"rl\"]", "script": "回放已训练策略与强MPC的实际动作、队列和成本；曲线重合或收益未过门禁会原样展示。", "timeoutMs": 120000, "waitSelector": "[data-pf-kind=\"rl\"][data-pf-status=\"completed\"][data-pf-integrity=\"true\"]"},
    {"phase": "05 核心实证", "title": "物理孪生逐点核验", "label": "执行物理孪生逐点核验", "selector": "[data-pf=\"run\"][data-kind=\"twin\"]", "script": "逐点对照观测、预测、强基线与原区间；缺测不断言为零，未通过单元不会隐藏。", "timeoutMs": 120000, "waitSelector": "[data-pf-kind=\"twin\"][data-pf-status=\"completed\"][data-pf-integrity=\"true\"]"},
    {"phase": "05 核心实证", "title": "故障阻断与恢复", "label": "执行故障阻断与恢复", "selector": "[data-pf=\"run\"][data-kind=\"faults\"]", "script": "在隔离副本注入故障，核验阻断原因、恢复结果与哈希，不改变原有业务状态。", "timeoutMs": 120000, "waitSelector": "[data-pf-kind=\"faults\"][data-pf-status=\"completed\"][data-pf-integrity=\"true\"]"},
    {"phase": "05 核心实证", "title": "本机运行核查", "label": "执行本机运行核查", "selector": "[data-pf=\"run\"][data-kind=\"runtime\"]", "script": "真实读取或计算，等待带事件链与结果哈希的回执；演示动作完成不替代业务准入。", "timeoutMs": 120000, "waitSelector": "[data-pf-kind=\"runtime\"][data-pf-status=\"completed\"][data-pf-integrity=\"true\"]"},
    {"phase": "05 核心实证", "title": "真实4B模型调用优化工具", "label": "运行模型工具任务", "selector": "[data-pf=\"model\"]", "script": "使用本机现有4B模型选择工具，真实优化器计算，核验后整理报告。模型决策、算法计算与报告汇总分别留痕，CPU运行可能需要数分钟。", "timeoutMs": 360000, "waitSelector": "[data-pf-model-status=\"completed\"][data-pf-model-verified=\"true\"]"},
    {"phase": "05 核心实证", "title": "新八港RL独立留出与消融", "label": "核验新八港RL独立留出与消融", "selector": "[data-pf=\"run\"][data-kind=\"rl_v6\"]", "script": "核对原始来源、冻结协议、检查项和失败原因。动作执行通过不等于研究收益、现场验收或标准认证通过。", "timeoutMs": 120000, "waitSelector": "[data-pf-kind=\"rl_v6\"][data-pf-status=\"completed\"][data-pf-integrity=\"true\"]"},
    {"phase": "05 核心实证", "title": "完整年度与新时期孪生", "label": "核验完整年度与新时期孪生", "selector": "[data-pf=\"run\"][data-kind=\"long_twin_v6\"]", "script": "核对原始来源、冻结协议、检查项和失败原因。动作执行通过不等于研究收益、现场验收或标准认证通过。", "timeoutMs": 120000, "waitSelector": "[data-pf-kind=\"long_twin_v6\"][data-pf-status=\"completed\"][data-pf-integrity=\"true\"]"},
    {"phase": "05 核心实证", "title": "DCSA协同异常演练", "label": "核验DCSA协同异常演练", "selector": "[data-pf=\"run\"][data-kind=\"standards\"]", "script": "核对原始来源、冻结协议、检查项和失败原因。动作执行通过不等于研究收益、现场验收或标准认证通过。", "timeoutMs": 120000, "waitSelector": "[data-pf-kind=\"standards\"][data-pf-status=\"completed\"][data-pf-integrity=\"true\"]"},
    {"phase": "05 核心实证", "title": "导出完整核心实证包", "label": "导出实证证据包", "selector": "[data-pf=\"export\"]", "script": "导出本次实际动作、模型工具记录和未完成项，原有训练证据继续独立保留。", "waitSelector": "#proofConsole[data-pf-exported=\"true\"]"},
    {"phase": "06 上海港联动", "title": "上海港统一联动入口", "label": "打开上海港试验", "selector": "#shanghaiLabBtn", "script": "将上海港公开活动数据和气象统一绑定到同一试验。补足的资源与工单明确标记为工程假设，不能称为实港生产验证。", "closeSurface": true, "waitSelector": "#run:not(:disabled)", "waitFrame":"#shanghaiLabFrame"},
    {"phase": "06 上海港联动", "title": "执行上海统一作业链", "label": "运行联合试验", "selector": "#run", "script": "同一输入依次执行马六甲排程、能碳守恒、Port执行读回与恢复，再生成小懿核验简报。查看成本、碳排和服务约束的真实取舍。", "frame": "#shanghaiLabFrame", "timeoutMs": 90000, "waitSelector": "#metrics .metric"},
    {"phase": "06 上海港联动", "title": "导出上海统一联动证据", "label": "导出上海试验证据", "selector": "#export", "script": "保留试验编号、输入与实现摘要、各系统回执和签收状态。移动端签收必须实际完成才算闭环，未签收会保留待办。", "frame": "#shanghaiLabFrame"},
    {"phase": "07 最新独立证据", "title": "打开V9专项实证", "label": "打开V9专项实证", "selector": "[data-action=\"priority-v9\"]", "script": "现场重算与冻结历史证据分别展示。保留全部门槛、强基线、未通过单元和来源；研究回放不代表现场准入。", "context": "#proofConsoleBtn", "closeSurface": true, "waitSelector": "#export:not(:disabled)", "waitFrame":"#researchReviewFrame"},
    {"phase": "07 最新独立证据", "title": "因果重算活动预测", "label": "因果重算活动预测", "selector": "#run-forecast", "script": "现场重算与冻结历史证据分别展示。保留全部门槛、强基线、未通过单元和来源；研究回放不代表现场准入。", "frame": "#researchReviewFrame", "timeoutMs": 60000, "waitSelector": "#forecast-result h3"},
    {"phase": "07 最新独立证据", "title": "重算V9年度潮位", "prepareSelect": {"selector":"#station", "label":"Galveston Pier 21"}, "label": "重算V9年度潮位", "selector": "#run-annual", "script": "现场重算与冻结历史证据分别展示。保留全部门槛、强基线、未通过单元和来源；研究回放不代表现场准入。", "frame": "#researchReviewFrame", "timeoutMs": 60000, "waitSelector": "#annual-result h3"},
    {"phase": "07 最新独立证据", "title": "导出V9专项证据", "label": "导出V9专项证据", "selector": "#export", "script": "现场重算与冻结历史证据分别展示。保留全部门槛、强基线、未通过单元和来源；研究回放不代表现场准入。", "frame": "#researchReviewFrame"},
    {"phase": "07 最新独立证据", "title": "打开V10根因与独立复验", "label": "打开V10根因与独立复验", "selector": "[data-action=\"root-cause-v10\"]", "script": "现场重算与冻结历史证据分别展示。保留全部门槛、强基线、未通过单元和来源；研究回放不代表现场准入。", "context": "#proofConsoleBtn", "closeSurface": true, "waitSelector": "#export:not(:disabled)", "waitFrame":"#researchReviewFrame"},
    {"phase": "07 最新独立证据", "title": "重算新站点24小时潮位", "label": "重算新站点24小时潮位", "selector": "#run", "script": "现场重算与冻结历史证据分别展示。保留全部门槛、强基线、未通过单元和来源；研究回放不代表现场准入。", "frame": "#researchReviewFrame", "timeoutMs": 60000, "waitSelector": "#annual-receipt h3"},
    {"phase": "07 最新独立证据", "title": "导出V10根因证据", "label": "导出V10根因证据", "selector": "#export", "script": "现场重算与冻结历史证据分别展示。保留全部门槛、强基线、未通过单元和来源；研究回放不代表现场准入。", "frame": "#researchReviewFrame"}
  ];

  const guide = $("#demoGuide");
  const launch = $("[data-demo-guide-launch]");
  if (!guide || !launch) return;

  const nodes = {
    progress:$("#demoGuideProgress"), phase:$("#demoGuidePhase"), count:$("#demoGuideCount"),
    list:$("#demoGuideSteps"), title:$("#demoGuideTitle"), script:$("#demoGuideScript"),
    state:$("#demoGuideState"), primary:$("#demoGuidePrimary")
  };
  const progressKey = "xiaoyi_demo_progress_v2";
  let savedProgress = {};
  try { savedProgress = JSON.parse(sessionStorage.getItem(progressKey) || "{}"); } catch {}
  const validIndices = values => Array.isArray(values) ? values.filter(i => Number.isInteger(i) && i >= 0 && i < steps.length) : [];
  const resumeState = sessionStorage.getItem("xiaoyi_demo_resume") || "";
  let index = resumeState === "roundtrip-ready" ? Math.max(0, steps.findIndex(s => s.selector.includes("ack-roundtrip-receipt"))) : (Number.isInteger(savedProgress.index) ? Math.max(0, Math.min(steps.length, savedProgress.index)) : 0);
  let programmaticClick = false;
  let stepExecuted = false;
  let waitTimer = null;
  let revision = 0;
  const skipped = new Set(validIndices(savedProgress.skipped));
  const completed = new Set(validIndices(savedProgress.completed));
  if (resumeState === "roundtrip-ready" && savedProgress.index === 23) completed.add(23);
  stepExecuted = Boolean(savedProgress.stepExecuted && completed.has(index) && resumeState !== "roundtrip-ready");

  function visibleTarget(selector, frame = null) {
    const scope = frame ? $(frame)?.contentDocument : document;
    if (!scope) return null;
    return $$(selector, scope).find((node) => !node.hidden && node.getClientRects().length && !node.disabled) || null;
  }

  function setState(message, tone = "") {
    nodes.state.textContent = message;
    nodes.state.className = `demo-guide__state${tone ? ` ${tone}` : ""}`;
  }

  function closeSurface() {
    window.dispatchEvent(new Event("demo-evidence-close"));
    const close = visibleTarget('#genericModal [data-action="close-modal"]')
      || visibleTarget('#smartDrawer [data-action="close-drawer"]');
    if (!close) return;
    programmaticClick = true;
    close.click();
    programmaticClick = false;
  }

  function flash(node) {
    node.classList.add("demo-guide-target");
    window.setTimeout(() => node.classList.remove("demo-guide-target"), 680);
  }

  function ensureCurrentVisible() {
    const active = nodes.list.querySelector("li.active");
    active?.scrollIntoView({ block:"nearest" });
  }

  function render() {
    sessionStorage.setItem(progressKey, JSON.stringify({index, stepExecuted, completed:[...completed], skipped:[...skipped]}));
    const complete = index >= steps.length;
    const safeIndex = complete ? steps.length - 1 : index;
    const step = steps[safeIndex];
    nodes.progress.style.width = `${complete ? 100 : Math.round((index / steps.length) * 100)}%`;
    nodes.phase.textContent = complete ? "演示完成" : step.phase;
    nodes.count.textContent = `${complete ? steps.length : index + 1}/${steps.length}`;
    const jump=$("#demoGuideJump");if(jump)jump.value=String(safeIndex);
    nodes.list.innerHTML = steps.map((item, itemIndex) => {
      const stateClass = itemIndex === index ? "active" : skipped.has(itemIndex) ? "skipped" : completed.has(itemIndex) ? "done" : "";
      const marker = completed.has(itemIndex) ? "✓" : String(itemIndex + 1).padStart(2, "0");
      return `<li class="${stateClass}"><i>${marker}</i><span>${item.title}<small>${item.label}</small></span></li>`;
    }).join("");
    nodes.title.textContent = complete ? `本次演示结束 · ${completed.size}/${steps.length}步已执行` : step.title;
    nodes.script.textContent = complete
      ? "小懿已经完成官方来源、原有训练证据、Harness任务、核心实证与上海统一联动的展示。当前结论仍限定在公开数据、离线训练和本机回执，生产授权保持关闭。"
      : step.script;
    nodes.primary.textContent = complete ? "↻ 重新开始演示" : stepExecuted ? "▶ 下一步并演示" : `▶ ${step.label}`;
    nodes.primary.disabled = false;
    setState(complete ? `已执行 ${completed.size}/${steps.length} 步，跳过 ${skipped.size} 步；未执行内容不计通过。可重新开始或选择步骤复验。` : stepExecuted ? "页面已完成本步变化；请保持本步台词，讲完后单击即可执行下一步。" : "点击本步按钮；也可直接点击页面上的同名按钮，引导会自动同步。", complete || stepExecuted ? "success" : "");
    requestAnimationFrame(ensureCurrentVisible);
  }

  function openGuide() {
    guide.hidden = false;
    guide.setAttribute("aria-hidden", "false");
    guide.classList.remove("collapsed");
    render();
  }

  function closeGuide() {
    if (waitTimer) { window.clearTimeout(waitTimer); waitTimer = null; }
    guide.hidden = true;
    guide.setAttribute("aria-hidden", "true");
  }

  function setIndex(next) {
    revision += 1;
    if (waitTimer) { window.clearTimeout(waitTimer); waitTimer = null; }
    index = Math.max(0, Math.min(steps.length, next));
    stepExecuted = false;
    render();
  }

  function markExecuted(message = "页面已完成本步变化。") {
    stepExecuted = true;
    completed.add(index);skipped.delete(index);
    render();
    setState(`${message}请讲完当前台词后再点下一步。`, "success");
  }

  function waitForStep(step) {
    const token = revision;
    if (!step.waitSelector) { window.setTimeout(() => { if(token === revision) markExecuted(); }, 260); return; }
    const started = Date.now();
    const timeoutMs = Number(step.timeoutMs || 15000);
    setState("功能正在执行，引导只等待可见回执，不会阻塞页面…", "warning");
    const poll = () => {
      if(token !== revision || guide.hidden) return;
      if (visibleTarget(step.waitSelector, step.waitFrame || step.frame)) {
        waitTimer = null;
        markExecuted("已收到本步的可见回执。");
      } else if (Date.now() - started >= timeoutMs) {
        waitTimer = null;
        nodes.primary.disabled = false;
        setState("本步等待超时已自动解锁；可重试、重置或使用保底下一步。", "warning");
      } else waitTimer = window.setTimeout(poll, 120);
    };
    waitTimer = window.setTimeout(poll, 120);
  }

  function clickContext(selector) {
    if (!selector) return false;
    const target = visibleTarget(selector);
    if (!target) return false;
    programmaticClick = true;
    target.click();
    programmaticClick = false;
    return true;
  }

  function waitVisible(selector, timeoutMs = 5000) {
    return new Promise((resolve) => {
      const started = Date.now();
      const poll = () => {
        const target = visibleTarget(selector);
        if (target || Date.now() - started >= timeoutMs) {
          resolve(target);
        } else window.setTimeout(poll, 80);
      };
      window.setTimeout(poll, 80);
    });
  }

  async function runCurrent() {
    if (index >= steps.length) {
      skipped.clear();completed.clear();
      setIndex(0);
      return;
    }
    if (stepExecuted) {
      window.dispatchEvent(new Event("demo-evidence-close"));
      setIndex(index + 1);
      if(index >= steps.length) return;
    }
    const step = steps[index];
    if (step.ready && !step.ready()) {
      setState("本步数据仍在首次读取。页面没有卡死，请稍候后点“重试本步”；也可使用“保底下一步”。", "warning");
      return;
    }
    if (step.closeSurface) closeSurface();
    let target = visibleTarget(step.selector, step.frame);
    if (!target && (step.context || step.contextChain)) {
      closeSurface();
      for (const selector of (step.contextChain || [step.context])) {
        const context = await waitVisible(selector);
        if (!context) break;
        programmaticClick = true; context.click(); programmaticClick = false;
        await new Promise(resolve => window.setTimeout(resolve, 100));
      }
      target = await waitVisible(step.selector);
    }
    if (!target) {
      setState("当前页面按钮尚未就绪。请点“重置本步”恢复所在页面，或点“保底下一步”继续。", "warning");
      return;
    }
    if (step.prepareSelect) {
      const control=visibleTarget(step.prepareSelect.selector,step.frame);
      const option=control && [...control.options].find(o=>o.textContent.trim()===step.prepareSelect.label);
      if (!option) { setState("示例站点未就绪，请稍候重试；没有替换原始数据。","warning");return; }
      control.value=option.value;control.dispatchEvent(new Event("change",{bubbles:true}));
    }
    flash(target);
    nodes.primary.disabled = true;
    setState("页面已收到点击，正在切换本步视图…", "warning");
    programmaticClick = true;
    target.click();
    programmaticClick = false;
    waitForStep(step);
  }

  async function resetStep() {
    if (waitTimer) { window.clearTimeout(waitTimer); waitTimer = null; }
    stepExecuted = false;
    closeSurface();
    const step = steps[Math.min(index, steps.length - 1)];
    await new Promise((resolve) => window.setTimeout(resolve, 60));
    const chain = step?.contextChain || (step?.context ? [step.context] : []);
    for (const selector of chain) {
      const target = await waitVisible(selector);
      if (!target) break;
      programmaticClick = true; target.click(); programmaticClick = false;
    }
    setState("本步引导状态已重置；页面入口已恢复，可立即重试。", "success");
    nodes.primary.disabled = false;
  }

  function resetAll() {
    closeSurface();
    skipped.clear();completed.clear();
    window.setTimeout(() => {
      clickContext('[data-action="home"]');
      setIndex(0);
      setState("演示已回到第一步；未启动任何后台预加载。", "success");
    }, 60);
  }

  const evidenceButton=document.createElement("button");
  evidenceButton.type="button";evidenceButton.dataset.demoEvidenceOpen="";
  evidenceButton.className="demo-guide__evidence";evidenceButton.textContent="场景算法与数据清单";
  nodes.primary.before(evidenceButton);
  const jump=document.createElement("select");jump.id="demoGuideJump";jump.setAttribute("aria-label","选择演示步骤");
  jump.style.cssText="width:100%;margin:8px 0;padding:6px;border:1px solid #ccd9e7;border-radius:6px;background:#fff;color:#24384d;font-size:12px";
  jump.innerHTML=steps.map((s,i)=>`<option value="${i}">${i+1}. ${s.title}</option>`).join("");
  nodes.list.before(jump);jump.addEventListener("change",()=>setIndex(Number(jump.value)));
  launch.addEventListener("click", openGuide);
  nodes.primary.addEventListener("click", runCurrent);
  guide.addEventListener("click", (event) => {
    const action = event.target.closest("[data-demo-guide-action]")?.dataset.demoGuideAction;
    if (!action) return;
    if (action === "close") closeGuide();
    if (action === "collapse") guide.classList.toggle("collapsed");
    if (action === "retry") { stepExecuted = false; runCurrent(); }
    if (action === "reset-step") resetStep();
    if (action === "fallback" && index < steps.length) { skipped.add(index); setIndex(index + 1); }
    if (action === "reset-all") resetAll();
  });

  document.addEventListener("click", (event) => {
    if (programmaticClick || guide.hidden || event.target.closest("#demoGuide") || event.target.closest("[data-demo-guide-launch]")) return;
    const matched = steps.findIndex((step) => event.target.closest(step.selector));
    if (matched < 0) return;
    window.setTimeout(() => {
      if (guide.hidden) return;
      if (matched < index) return;
      if (matched !== index) setIndex(matched);
      waitForStep(steps[matched]);
      if (!steps[matched].waitSelector) setState(`已识别页面按钮“${steps[matched].label}”，引导已同步本步台词。`, "success");
    }, 280);
  }, true);

  window.__xiaoyiDemoGuide = {
    steps:steps.map(({ phase, title, label, selector }) => ({ phase, title, label, selector })),
    open:openGuide,
    close:closeGuide,
    reset:resetAll,
    get index() { return index; }
  };
  if (resumeState === "roundtrip-ready") {
    sessionStorage.removeItem("xiaoyi_demo_resume");
    window.setTimeout(openGuide, 120);
  }
})();
