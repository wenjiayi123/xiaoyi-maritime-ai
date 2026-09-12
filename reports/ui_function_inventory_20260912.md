# 小懿 AI 功能与按钮静态清单（2026-09-12）

本文件记录源码审计与可重复的 Node 行为测试，不代表逐项浏览器点击、真实网络或窄屏视觉验收已经通过。浏览器验收由本次主审计另行记录。

## 覆盖

- 源码：`web/index.html`、`web/app.js`、`web/linked_agent.js`、`web/styles.css`。
- 六主页面：智能对话、决策建议、数据分析、知识库、训练中心、任务中心。
- 动态窗口：接口中心、四系统联动、联动智能体、智能联动中心/RAG评测、知识目录/来源/覆盖/上传、设置、状态/准入、历史/收藏/报告、训练配置、任务步骤/自动化确认。
- 运行结果继续区分本机模拟、公开数据模型、真实接口观测与生产权限。未连接现场、没有授权的按钮保持门禁。

## 动态控件族与预期反应

| 控件族 | 预期反应 / 显示 |
|---|---|
| 问题、发送/停止、Enter/Shift+Enter、回答模式、证据数、严格证据、智能操作 | 当前问题/参数传入请求，流式文本、来源与后续问题对应；停止和错误不假报完成 |
| 导航、侧栏、右栏、新建对话、历史/会话/收藏记录 | 正确进入页面、恢复对应内容；新建不继承旧答案 |
| 搜索知识、分类标签、专业目录搜索/状态、来源筛选、来源链接 | 查询与结果一致，迟到结果不能覆盖新查询，来源标签不夸大核验程度 |
| 预警条目、处置模板、决策建议、任务模板/记录/步骤 | 事件来源和模拟边界清楚，任务ID/步骤/进度一致 |
| 任务下一步、自动、暂停、人工确认 | 并发不可越步；确认只适用于当次任务，错误后停止自动推进 |
| 能耗今日/7日/30日、五种模拟场景 | 图表、选中状态、数值时窗与来源一致，定时刷新不重置选择 |
| 模拟决策双角色审批、执行、回滚、血缘 | 双人模拟审批、回执和回滚事件可追踪；生产权限关闭 |
| RL配置：数据集、六算法、回合/时域/种子 | 至少一种RL，契约范围有效，当前配置传入训练任务 |
| RL证据/契约/刷新、顾问建议/输入提交、全系统助手 | 数据/算法/门禁一致，每条顾问问题更新自己的占位与回答 |
| 四系统指令、运行/启动/刷新/打开、失败重试 | 独立运行状态和回执；打开目标后小懿窗口可返回 |
| 联动智能体能力、指令、参数、次数/间隔/恢复 | 草稿重开保留，修改立即使旧预览失效 |
| 联动解析/预览/执行 | 解析→读取状态→显示具体方案→后端执行观测；迟到响应不污染其他窗口 |
| 联动停止/恢复/刷新/历史/记录/导出/读取重试 | 取消据是否受理提示，恢复须回读；断网保留执行锁，刷新核查；完整回执可导出 |
| 生成报告、Markdown/JSON下载 | 当前报告与选择时窗一致，文件可下载，迟到失败不覆盖其他窗口 |
| 附件、发布机构/URL/版本/官方声明、提交待审核 | TXT/MD/CSV、2MB/100万字符限制；暂存不进索引，声明不等于已核验 |
| 设置、主题、形象、访问令牌保存/清除 | 偏好实际保存；令牌仅当前标签会话；形象切换与返回保留 |
| 关闭、Escape、遮罩、启动/拒绝确认 | 正确关闭对应层；启动中、确认拒绝与执行停止语义一致 |

## 静态确定问题与处理

| 问题 | 原始实现函数 | 处理 |
|---|---|---|
| 清空历史吞掉DELETE失败仍声称完全清除 | handleModalAction | 交主代理修复和浏览器验收 |
| 两组range激活不一致，定时刷新重置today，请求乱序 | loadEnergy / loadDashboard | 交主代理修复 |
| 顾问并发pop错误消息、任务下一步重复请求 | askRLAdvisor / advanceTask | 交主代理修复 |
| noopener返回null后错误同页跳走 | openLinkedSystem | 交主代理修复 |
| 报告失败、资料成功、健康检查迟到覆写/重开弹窗 | generateReport / submitKnowledgeIntake / checkConnectorHealth | 交主代理修复 |
| 读取失败停留加载、迟到响应污染弹窗 | linked_agent.js open / parse / history | 已修复；Node行为测试 |
| 草稿重开丢失，预览中改参仍可执行旧方案 | linked_agent.js render / prepare | 已修复；Node行为测试 |
| 轮询失败解锁、取消未受理仍报成功 | linked_agent.js runPlan / cancel | 已修复；Node行为测试 |
| 执行不确定重试换request_id；未应用变更仍宣称保留配置 | linked_agent.js runPlan / summarize | 已修复；Node行为测试 |

## 覆盖限度与窄屏注意项

`tests/test_frontend_contract.py` 检查 DOM ID唯一、字面动作注册、后端入口、证据与来源边界、会话/流式标记、四系统入口、RL矩阵、安全白名单及资源版本。它不能证明点击后的真实网络、画面、窗口生命周期或异步竞态通过。

`tests/linked_agent.behavior.test.js` 用独立最小 DOM 和受控异步 API 验证迟到响应、重开、输入校验、执行去重、断网恢复与取消语义。真实后端和浏览器另行验收。

现有620/600/900px断点对联动字段、表格滚动、方案断行做了处理。模拟器审批字级、多个按钮同排、长回执ID、抽屉底栏和侧栏遮挡仍应以窄屏截图核对。HTML含启动占位和隐藏兼容控件，源码按钮总数不能充当运行时全部按钮验收数。


## HTML controls in source order

Source inventory only; no browser pass is implied.

| Line | Type / ID | Label or accessible name | Binding |
|---|---|---|---|
| 50 | button | 港航小懿AI智能助手 MARITIME COPILOT | data-action=home |
| 56 | button | 智能对话 | data-view-target=chat |
| 57 | button | 决策建议 | data-view-target=decisions |
| 58 | button | 数据分析 | data-view-target=analytics |
| 59 | button | 训练中心 | data-view-target=rl |
| 60 | button | 知识库 | data-view-target=knowledge |
| 61 | button | 任务中心0 | data-view-target=tasks |
| 65 | button | 打开功能侧栏 | data-action=toggle-sidebar |
| 66 | button | 打开运营看板 | data-action=toggle-rail |
| 67 | button | 查看系统状态 | data-action=system-status |
| 70 | button | 0 | data-action=notifications |
| 71 | button | 设置 | data-action=settings |
| 72 | button | 管理员 | data-action=profile |
| 85 | button #newTopicBtn | 新建对话 | data-action=new-chat |
| 86 | button | 对话历史0 | data-action=history |
| 87 | button | 常用指令 | data-action=commands |
| 88 | button | 我的收藏0 | data-action=favorites |
| 89 | button #connectorCenterBtn | 接口中心待接入 | data-action=connectors |
| 90 | button #intelligenceHubBtn | 智能联动中心模块7/7 | data-action=intelligence-hub |
| 91 | button #systemLaunchHubBtn | 四系统联动0/4 | data-action=system-linkage |
| 92 | button #ragEvaluationBtn | RAG评测闭环评测 | data-action=rag-evaluation |
| 98 | button | 本班先处理什么 | data-q=根据工作台当前活动告警，按风险、影响和时效排出本班前三项。; data-mode=ops |
| 99 | button | 待靠船为什么没靠 | data-q=工作台里 EASTERN HORIZON 为什么还没靠？给我先核对什么。; data-mode=ops |
| 100 | button | QC-03 告警处置 | data-q=工作台里 QC-03 当前告警是什么？按先安全后恢复给处置步骤。; data-mode=sop |
| 101 | button | 生成当前交班摘要 | data-q=按船舶、设备、堆场、闸口、告警五部分生成当前工作台交班摘要。; data-mode=ops |
| 102 | button | 查询岸桥处置 SOP | data-q=岸桥单位作业能耗偏高怎么处理？给我现场可读的逐步 SOP，并标明需确认的岗位。; data-mode=sop |
| 107 | button | 深海模式沉浸式港航驾驶舱 | data-action=theme |
| 109 | button | 真实RL训练实验室 | data-rl-mission-launch; data-q=启动RL训练实验：使用真实公开能源时序数据，运行Q-learning、SARSA、Expected SARSA、Double Q-learning和PID控制基线；训练阶段不渲染，训练完成后再用保留测试集渲染并比较结果。; data-mode=ops |
| 125 | button | 智能问答解答港航运营相关问题 | data-action=capability-chat |
| 126 | button | 数据分析多维数据分析与可视化 | data-view-target=analytics |
| 127 | button | 决策建议提供优化建议与决策支持 | data-view-target=decisions |
| 128 | button | 报告生成自动生成分析报告 | data-action=generate-report |
| 143 | span #runtimeStatusBadge | 公开数据校准模拟 | data-action=runtime-status |
| 145 | button | 收藏当前回答 | data-action=favorite-current |
| 146 | button | 更多操作 | data-action=response-menu |
| 173 | button | 依据与来源0 | data-action=evidence |
| 177 | button | 生成详细报告 | data-action=generate-report |
| 178 | button | 帮我逐步分析 | data-task-template=analyze-energy |
| 179 | button | 能耗趋势预测 | data-q=请预测未来 7 日港口能耗趋势。; data-mode=expert |
| 186 | button | 添加附件 | data-action=attachment |
| 187 | button #agentModeBtn | 智能操作 | data-action=toggle-agent-mode |
| 188 | textarea #question | 问题输入 | ID/form/native or startup placeholder |
| 189 | button | 专业 | data-action=advanced |
| 190 | button #askBtn | 发送 | ID/form/native or startup placeholder |
| 192 | select #mode | 专业问答运营问答SOP 生成简报摘要 | ID/form/native or startup placeholder |
| 193 | input #topK | (no text) | ID/form/native or startup placeholder |
| 194 | input #strictEvidence | (no text) | ID/form/native or startup placeholder |
| 211 | button | 切换形象 | data-action=avatar |
| 217 | button #decisionGenerateButton | 生成智能方案 | data-task-template=optimize-berth |
| 219 | span | 公开数据校准模拟 | data-action=runtime-status |
| 226 | button | 今日 | data-range=today |
| 226 | button | 7日 | data-range=7d |
| 226 | button | 30日 | data-range=30d |
| 229 | span | 公开数据校准模拟 | data-action=runtime-status |
| 230 | button | 让小懿深度分析 | data-task-template=analyze-energy |
| 234 | button | 数据契约与血缘 | data-action=simulator-lineage |
| 238 | button | 常态生产 | data-simulator-scenario=normal |
| 239 | button | 集中到港 | data-simulator-scenario=vessel_surge |
| 240 | button | 设备故障 | data-simulator-scenario=equipment_failure |
| 241 | button | 需量高峰 | data-simulator-scenario=energy_peak |
| 242 | button | 大风低能见度 | data-simulator-scenario=storm |
| 255 | button | 专业目录 | data-action=knowledge-catalog |
| 255 | button | 权威覆盖 | data-action=authority-coverage |
| 255 | button | 来源审计 | data-action=knowledge-sources |
| 255 | button | 知识全景 | data-action=knowledge-map |
| 256 | input #knowledgeSearch | 搜索港口运营、航运调度、岸电、TOS、安全应急... | ID/form/native or startup placeholder |
| 260 | button | 展开查看 | data-action=knowledge-map |
| 268 | button | 正式证据与失败候选 | data-rl-center-action=show-evidence |
| 269 | button | 刷新证据 | data-rl-center-action=refresh |
| 270 | button | 配置六算法对比 | data-rl-center-action=start-training |
| 291 | button | 解释观测与目标 | data-rl-advisor-prompt=这次训练的观测、动作、目标函数和硬约束是什么？ |
| 292 | button | 比较数据可信度 | data-rl-advisor-prompt=目前公开数据有多少行、来源和许可是什么，哪套更可信？ |
| 293 | button | 解释六算法矩阵 | data-rl-advisor-prompt=六种候选与基线的区别是什么，为什么保留PID和SOP规则？ |
| 296 | textarea #rlAdvisorInput | 训练顾问问题 | ID/form/native or startup placeholder |
| 297 | button | 发送给训练顾问 | ID/form/native or startup placeholder |
| 302 | button | 展开契约 | data-rl-center-action=show-contract |
| 310 | button | 训练中心 | data-rl-center-action=start-training |
| 312 | button | 算法矩阵 | data-rl-center-action=show-contract |
| 314 | button | 训练顾问 | data-rl-center-action=ask-advisor |
| 316 | button | 全系统助手 | data-action=intelligence-hub |
| 323 | button | 新建智能任务 | data-action=new-task |
| 333 | span | SIM | data-action=runtime-status |
| 333 | button | 查看更多 | data-view-target=analytics |
| 338 | span | SIM | data-action=runtime-status |
| 338 | button | 今日 | data-range=today |
| 338 | button | 7日 | data-range=7d |
| 338 | button | 30日 | data-range=30d |
| 344 | button | 查看更多 | data-action=notifications |
| 349 | button | 查看更多 | data-view-target=knowledge |
| 350 | button | 港口运营 | ID/form/native or startup placeholder |
| 350 | button | 能源管理 | ID/form/native or startup placeholder |
| 350 | button | 设备管理 | ID/form/native or startup placeholder |
| 350 | button | 政策法规 | ID/form/native or startup placeholder |
| 350 | button | 行业标准 | ID/form/native or startup placeholder |
| 350 | button | 案例分析 | ID/form/native or startup placeholder |
| 358 | button | 关闭 | data-action=close-drawer |
| 365 | button | 关闭 | data-action=close-modal |
| 370 | input #fileInput | (no text) | ID/form/native or startup placeholder |
| 375 | button #clearTopicsBtn | (no text) | ID/form/native or startup placeholder |

## Literal action values

| Attribute | Values |
|---|---|
| data-action | advanced, attachment, authority-coverage, avatar, capability-chat, close-drawer, close-modal, commands, competitive-benchmark, confirm-automation, connectors, evidence, favorite-current, favorites, generate-report, history, home, hub-run-demo, hub-run-evaluation, hub-submit-feedback, intelligence-hub, knowledge-catalog, knowledge-intake, knowledge-map, knowledge-sources, linked-agent, new-chat, new-task, notifications, profile, rag-evaluation, response-menu, resume-automation, runtime-status, settings, simulator-lineage, site-admission, stop-automation, system-linkage, system-status, theme, toggle-agent-mode, toggle-rail, toggle-sidebar |
| data-modal-action | clear-history, clear-history-confirmed, confirm-automation, confirm-linked-systems-startup, confirm-task, reject-automation, reject-linked-systems-startup, save-settings, start-rl-lab, submit-knowledge-intake |
| data-view-target | analytics, chat, decisions, knowledge, rl, tasks |
| data-task-template | analyze-energy, handle-alert, optimize-berth |
| data-task-action | auto, next |
| data-report-download | json, markdown |
| data-source-filter | all |
| data-catalog-status | all, indexed, partial, planned |
| data-range | 30d, 7d, today |
| data-simulator-scenario | energy_peak, equipment_failure, normal, storm, vessel_surge |
| data-rl-center-action | ask-advisor, refresh, show-contract, show-evidence, start-training |
| data-linkage-run | all |
| data-linkage-start | all |
| data-linkage-open |  |
| data-avatar | analyst, navigator |
