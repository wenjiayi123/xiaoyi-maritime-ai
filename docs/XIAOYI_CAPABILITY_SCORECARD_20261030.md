# 小懿逐项功能评分与前沿差距

评估日期：2026-10-30。共37个功能模块。

**当前定位：有实际本机模型、工具任务、公开数据研究、仿真与可追溯验收的工程研究平台；真实港口生产资格尚未具备。**

分数是本次按证据所作的成熟度粗评，不能解释为全球百分位、模型排行榜、第三方评测或行业认证。每项给出现在能做什么以及未闭合部分。

## 评分尺度

每项五维各0至4分，相加乘5。由本次代码、实际运行和研究证据作工程判断，不是全球排名、标准化竞赛成绩或第三方认证。

五维为功能覆盖、验证深度、陌生场景泛化、港航业务闭合、运行成熟度；各0—4分，相加乘5。每项的五维原分保留在JSON和界面，分差5分不代表统计显著。对纯工程模块，运行成熟度按该模块隔离部署、恢复与规模验证衡量；涉及现场的模块还需要真实港口证据。

|分数|怎样理解|
|---|---|
|0|未具备或无验收证据|
|20|概念或局部展示|
|40|局部可运行、验证不足|
|60|可复现离线研究/工程能力|
|80|多场景稳健、业务与运行验证较充分|
|100|该模块目标范围内长期、独立、规模化验收充分；这是本量表目标定义，不是行业超级智能认证|

现场自主调度0分表示没有已授权现场执行证据；生产权限关闭属于现有保护机制。没有用工程测试数量折算智能水平，也没有把界面字段数量折算现场数据深度。

## 逐项评分

|功能|分数 / 100|现在能做什么|关键限制|
|---|---:|---|---|
|港航知识问答|55|结合登记资料回答概念、常见业务问题并标注证据。|固定题与本地案例有证据；陌生港口业务人员盲评和全球知识覆盖不足。|
|语义检索与Hybrid RAG|65|本地向量、Sparse/BM25、多证据召回与引用。|882分块属于有限知识快照，固定题高命中不能推算开放世界准确率。|
|多轮理解与问题拆解|55|改写追问、拆分问题、继承结构化上下文。|缺大量未见长对话、指代冲突及跨工具长程盲测。|
|SOP与风险提示|60|生成核验步骤、补齐对象信息并提示高风险事项。|建议性质；没有港方现场操作签收和真实事故复盘验证。|
|法规辖区、时效与冲突治理|60|区分辖区、日期、证据冲突和新鲜度。|登记范围有限，缺持续全量法规更新与外部专业审查。|
|报告与交接草稿|60|生成结构化业务/研究交接并保留来源和缺项。|草稿需业务责任人复核，尚无机构正式签收。|
|结构化问数与业务分析|60|读取登记字段和运行快照，输出可追溯数字。|现场数据连接未验证，模拟字段完整度不等于实测字段完整度。|
|本机4B生成模型|40|本机完成文本生成与真实工具选择，减少外发。|基础能力来自开放权重；未做与前沿基础模型的同条件独立盲测。|
|LoRA训练与领域适配|30|有本机适配器训练、导出和推理工程流程。|质量准入仍阻断；少量loss下降不证明业务质量或前沿模型水平。|
|Harness工具型任务工作台|75|真实模型/规则调工具、预算、审批、工件及受控结果核验。|可复现工程任务较完整；缺开放任务基准、跨机构长期运行和外部盲评。|
|检查点、租约、恢复与取消|70|持久任务、跨进程目标锁、故障恢复、取消和状态保留。|本地进程与SQLite证据；未覆盖分布式集群灾备或港口OT。|
|技能、显式记忆和MCP只读工具|60|按任务引用技能、显式记忆及只读工具接口。|不等于自主学习全港知识；缺外部生态与陌生任务规模验证。|
|四系统联动与连续观测|70|八个登记本机适配器动作、连续观测与参数恢复。|连接的是已登记演示/研究系统；观测差值不自动构成因果收益。|
|受控模拟执行与回滚|65|预览、角色检查、幂等、配置完整性与模拟回滚。|没有真实设备指令权限，组织身份及OT恢复尚未签收。|
|十域实时业务模拟|65|船舶、设备、泊位、堆场、闸口、能碳等模拟流与场景。|物理容量、设备负荷和故障影响多为工程假设。|
|孪生可视化与跨端展示|50|通过登记接口展示二维/三维态势与场景。|外部联动能力；几何和动画不能证明水深、设备或全港物理标定。|
|公开数据、来源与证据血缘|80|跨港真实公开指标、原始文件、时钟、质量、版本和失败可查。|同源归档不等于实时现场遥测，历史修订/发布时间仍有不确定性。|
|跨港需求预测与区间|65|独立新港验证预测和区间，沿用冻结模型与宽度门禁。|是AIS活动指标预测；没有真实到港预约、现场发布时间和漂移SLA。|
|RL研究、消融与策略评估框架|70|真实训练、固定回放单因素消融、强基线、逐港风险和失败追溯。|方法验证较完整，复杂多智能体真实港口任务与独立机构复核仍不足。|
|RL相对强MPC的有效收益|30|可训练并评估候选，识别退化与安全/收益取舍。|安全版与安全MPC动作相同；没有额外RL收益准入，跨港相对成本和集中收益仍失败。|
|PID/MPC控制与强基线|55|整定PID、不同预测时域/稳健系数MPC和同条件安全过滤。|五档容量代理问题；未完成真实设备动态、业务成本和控制链标定。|
|短期水位预测与因果同化|60|有观测的46个新年度单元达到冻结误差、覆盖、宽度和可用率门禁。|完整项46/54；缺测和实时传感器可用性仍阻断资格。|
|年度开环物理孪生|40|可用多年真实观测拟合天文模型，报告跨季偏差和区间。|年度新留出5/21；稳定跨年/跨季标定尚未通过。|
|逐次天气预报强迫的七日孪生|50|同一初始化天气预报驱动七日水位，初始水位模式另列。|两种模式均15/28；覆盖、基线和数据可用性仍失败，不能替代年度资格。|
|引航、泊位、岸桥和堆场排程|40|在合成工单上做资源时隙、整单预留与未完成工单守恒。|缺真实船舶工单、港区布局、服务时长和效率标定。|
|能耗、储能与碳核算|45|检查kW/kWh、SOC及供电缺口；未知碳因子时暂缓。|未取得港口电表、设备工况及可核验电网因子，不能宣称实测节能减排。|
|全港多业务物理闭环|35|能连接多业务接口并验证工程一致性。|水深/吃水/基准、设备能耗和全港实际业务数据仍缺，现场物理闭环未成立。|
|DCSA/MSW多机构协同|35|官方PC2.0.0 schema子集和E-R-P-A时序、冲突与分区本地演练。|尚无完整外部一致性测试、MSW接入、机构身份或签收。|
|航行/运输模型联动|50|历史航行场景和真实预训练运输策略推理可经联动核查。|属于外部系统联动；缺真实航道、硬件和端到端RL训练验收。|
|移动与客户端签收|50|有Web/Flutter自动检查及客户端签收记录。|原生桌面窗口既定验收仍未通过；历史签收不能当作当前全设备兼容证明。|
|审计回执与执行证据完整性|80|工件、来源、事件链、哈希、独立回读及历史失败完整保留。|本地SHA一致性尚无外部签名、独立不可篡改存证和多方取证。|
|权限、注入防护与供应链|60|角色约束、审批、注入固定回归、依赖锁和生产边界。|缺外部红队、真实机构IAM/密钥及OT网络安全验收。|
|监控、健康和故障诊断|65|健康/就绪、日志、模型网关、失败和恢复状态可查。|本机时点/历史持续探测证据，缺多站点长期SLO和高可用实测。|
|Docker发行与可复现部署|70|真实镜像构建、非root只读启动、源码核验和重启持久化。|单机Linux容器；未验证高可用集群、灾备、现场运维或容器内4B推理。|
|真实港口只读接入准备|25|已有字段、质量、漂移和标定元数据门禁与接口适配框架。|没有完成港方现场七项准入；真实接入完成度仍为0/7。|
|真实港口自主调度|0|当前系统保持生产权限关闭。|没有签字授权、现场HIL、影子运行和生产调度资格。|
|视频/雷达多模态感知|0|当前可查的是文本、结构化数据和演示/研究场景。|没有已验收的真实港口视频识别、雷达融合或视觉闭环。|

## 证据和五维分解

表中源文件、历史报告和本次新验证不是同一种证据。基础模型没有独立同条件前沿对比；旧固定题、参数量和loss下降均不作为前沿排名。当前任务审阅与容器运行另有真实回执；原生窗口未通过的边界保留。

- **港航知识问答：55分**。功能覆盖3/4，验证深度3/4，陌生场景泛化1/4，港航业务闭合3/4，运行成熟度1/4。证据：[xiaoyi.py](/Users/apple/Desktop/小懿AI/app/xiaoyi.py)、[maritime_rag_benchmark_v1_20260814_r3.json](/Users/apple/Desktop/小懿AI/reports/maritime_rag_benchmark_v1_20260814_r3.json)。
- **语义检索与Hybrid RAG：65分**。功能覆盖4/4，验证深度3/4，陌生场景泛化1/4，港航业务闭合3/4，运行成熟度2/4。证据：[retrieval.py](/Users/apple/Desktop/小懿AI/app/retrieval.py)、[vector_retrieval.py](/Users/apple/Desktop/小懿AI/app/vector_retrieval.py)。
- **多轮理解与问题拆解：55分**。功能覆盖3/4，验证深度3/4，陌生场景泛化1/4，港航业务闭合2/4，运行成熟度2/4。证据：[query_intelligence.py](/Users/apple/Desktop/小懿AI/app/query_intelligence.py)、[conversations.py](/Users/apple/Desktop/小懿AI/app/conversations.py)。
- **SOP与风险提示：60分**。功能覆盖3/4，验证深度4/4，陌生场景泛化1/4，港航业务闭合3/4，运行成熟度1/4。证据：[decision_assurance.py](/Users/apple/Desktop/小懿AI/app/decision_assurance.py)、[answer_verification.py](/Users/apple/Desktop/小懿AI/app/answer_verification.py)。
- **法规辖区、时效与冲突治理：60分**。功能覆盖3/4，验证深度4/4，陌生场景泛化1/4，港航业务闭合3/4，运行成熟度1/4。证据：[governance.py](/Users/apple/Desktop/小懿AI/app/governance.py)、[evidence_fusion.py](/Users/apple/Desktop/小懿AI/app/evidence_fusion.py)。
- **报告与交接草稿：60分**。功能覆盖3/4，验证深度4/4，陌生场景泛化1/4，港航业务闭合3/4，运行成熟度1/4。证据：[maritime.py](/Users/apple/Desktop/小懿AI/app/harness/maritime.py)、[business.py](/Users/apple/Desktop/小懿AI/app/harness/business.py)。
- **结构化问数与业务分析：60分**。功能覆盖3/4，验证深度4/4，陌生场景泛化1/4，港航业务闭合3/4，运行成熟度1/4。证据：[maritime.py](/Users/apple/Desktop/小懿AI/app/harness/maritime.py)、[port_runtime.py](/Users/apple/Desktop/小懿AI/app/port_runtime.py)。
- **本机4B生成模型：40分**。功能覆盖2/4，验证深度2/4，陌生场景泛化1/4，港航业务闭合1/4，运行成熟度2/4。证据：[model_gateway.py](/Users/apple/Desktop/小懿AI/app/model_gateway.py)、[model_registry.json](/Users/apple/Desktop/小懿AI/data/model_registry.json)。
- **LoRA训练与领域适配：30分**。功能覆盖2/4，验证深度2/4，陌生场景泛化0/4，港航业务闭合1/4，运行成熟度1/4。证据：[lora_admission_v1.json](/Users/apple/Desktop/小懿AI/reports/lora_admission_v1.json)、[local_lora_inference_v3.json](/Users/apple/Desktop/小懿AI/reports/local_lora_inference_v3.json)。
- **Harness工具型任务工作台：75分**。功能覆盖4/4，验证深度4/4，陌生场景泛化2/4，港航业务闭合3/4，运行成熟度2/4。证据：[runner.py](/Users/apple/Desktop/小懿AI/app/harness/runner.py)、[HARNESS_RUNTIME.md](/Users/apple/Desktop/小懿AI/docs/HARNESS_RUNTIME.md)。
- **检查点、租约、恢复与取消：70分**。功能覆盖4/4，验证深度4/4，陌生场景泛化2/4，港航业务闭合2/4，运行成熟度2/4。证据：[store.py](/Users/apple/Desktop/小懿AI/app/harness/store.py)、[linked_agent.py](/Users/apple/Desktop/小懿AI/app/linked_agent.py)、[test_runtime_test_isolation.py](/Users/apple/Desktop/小懿AI/tests/test_runtime_test_isolation.py)。
- **技能、显式记忆和MCP只读工具：60分**。功能覆盖3/4，验证深度3/4，陌生场景泛化1/4，港航业务闭合3/4，运行成熟度2/4。证据：[tools.py](/Users/apple/Desktop/小懿AI/app/harness/tools.py)、[HARNESS_RUNTIME.md](/Users/apple/Desktop/小懿AI/docs/HARNESS_RUNTIME.md)。
- **四系统联动与连续观测：70分**。功能覆盖4/4，验证深度4/4，陌生场景泛化2/4，港航业务闭合2/4，运行成熟度2/4。证据：[linked_agent_acceptance_risk_v4_final_20261030.json](/Users/apple/Desktop/小懿AI/reports/linked_agent_acceptance_risk_v4_final_20261030.json)、[linked_agent_catalog.py](/Users/apple/Desktop/小懿AI/app/linked_agent_catalog.py)。
- **受控模拟执行与回滚：65分**。功能覆盖4/4，验证深度4/4，陌生场景泛化2/4，港航业务闭合2/4，运行成熟度1/4。证据：[linked_agent.py](/Users/apple/Desktop/小懿AI/app/linked_agent.py)、[operations_v3.py](/Users/apple/Desktop/小懿AI/app/harness/operations_v3.py)。
- **十域实时业务模拟：65分**。功能覆盖4/4，验证深度4/4，陌生场景泛化2/4，港航业务闭合2/4，运行成熟度1/4。证据：[realtime_port_simulator.py](/Users/apple/Desktop/小懿AI/app/realtime_port_simulator.py)、[port_realtime_simulator_evidence_remediation_20261030.json](/Users/apple/Desktop/小懿AI/reports/port_realtime_simulator_evidence_remediation_20261030.json)。
- **孪生可视化与跨端展示：50分**。功能覆盖3/4，验证深度3/4，陌生场景泛化1/4，港航业务闭合2/4，运行成熟度1/4。证据：[HARNESS_PHASE3_ACCEPTANCE_20261029.md](/Users/apple/Desktop/小懿AI/docs/HARNESS_PHASE3_ACCEPTANCE_20261029.md)、[capability_hub.py](/Users/apple/Desktop/小懿AI/app/capability_hub.py)。
- **公开数据、来源与证据血缘：80分**。功能覆盖4/4，验证深度4/4，陌生场景泛化3/4，港航业务闭合3/4，运行成熟度2/4。证据：[remediation_v4_evidence_registry.json](/Users/apple/Desktop/小懿AI/config/remediation_v4_evidence_registry.json)、[manifest.json](/Users/apple/Desktop/小懿AI/data/public/portwatch_v4_20261030/manifest.json)。
- **跨港需求预测与区间：65分**。功能覆盖3/4，验证深度4/4，陌生场景泛化3/4，港航业务闭合2/4，运行成熟度1/4。证据：[forecast-new-eight.json](/Users/apple/Desktop/小懿AI/.codex_artifacts/remediation-v4-20261030/forecast-new-eight.json)。
- **RL研究、消融与策略评估框架：70分**。功能覆盖4/4，验证深度4/4，陌生场景泛化2/4，港航业务闭合3/4，运行成熟度1/4。证据：[ablation-development.json](/Users/apple/Desktop/小懿AI/.runtime/learning-v3-20261030/ablation-development.json)、[report.json](/Users/apple/Desktop/小懿AI/.runtime/robust-v4-20261030/report.json)。
- **RL相对强MPC的有效收益：30分**。功能覆盖2/4，验证深度3/4，陌生场景泛化0/4，港航业务闭合1/4，运行成熟度0/4。证据：[rl-diagnostics.json](/Users/apple/Desktop/小懿AI/.codex_artifacts/remediation-v4-20261030/rl-diagnostics.json)。
- **PID/MPC控制与强基线：55分**。功能覆盖3/4，验证深度3/4，陌生场景泛化2/4，港航业务闭合2/4，运行成熟度1/4。证据：[modelbased_v3.py](/Users/apple/Desktop/小懿AI/app/harness/modelbased_v3.py)、[robust_v4.py](/Users/apple/Desktop/小懿AI/app/harness/robust_v4.py)。
- **短期水位预测与因果同化：60分**。功能覆盖3/4，验证深度4/4，陌生场景泛化2/4，港航业务闭合2/4，运行成熟度1/4。证据：[report.json](/Users/apple/Desktop/小懿AI/data/public/physical_twin_v3_20261030/report.json)。
- **年度开环物理孪生：40分**。功能覆盖2/4，验证深度3/4，陌生场景泛化1/4，港航业务闭合2/4，运行成熟度0/4。证据：[report.json](/Users/apple/Desktop/小懿AI/data/public/physical_twin_v3_20261030/report.json)。
- **逐次天气预报强迫的七日孪生：50分**。功能覆盖3/4，验证深度3/4，陌生场景泛化1/4，港航业务闭合2/4，运行成熟度1/4。证据：[report.json](/Users/apple/Desktop/小懿AI/data/public/forecast_forcing_v4_20261030/report.json)。
- **引航、泊位、岸桥和堆场排程：40分**。功能覆盖3/4，验证深度3/4，陌生场景泛化1/4，港航业务闭合1/4，运行成熟度0/4。证据：[operations_v3.py](/Users/apple/Desktop/小懿AI/app/harness/operations_v3.py)、[report.json](/Users/apple/Desktop/小懿AI/.codex_artifacts/remediation-v3-20261030/operations/report.json)。
- **能耗、储能与碳核算：45分**。功能覆盖3/4，验证深度4/4，陌生场景泛化1/4，港航业务闭合1/4，运行成熟度0/4。证据：[operations_v3.py](/Users/apple/Desktop/小懿AI/app/harness/operations_v3.py)、[operations_v2.py](/Users/apple/Desktop/小懿AI/app/harness/operations_v2.py)。
- **全港多业务物理闭环：35分**。功能覆盖2/4，验证深度3/4，陌生场景泛化1/4，港航业务闭合1/4，运行成熟度0/4。证据：[operations_v3.py](/Users/apple/Desktop/小懿AI/app/harness/operations_v3.py)、[port_site_admission_v1.json](/Users/apple/Desktop/小懿AI/data/contracts/port_site_admission_v1.json)。
- **DCSA/MSW多机构协同：35分**。功能覆盖2/4，验证深度3/4，陌生场景泛化1/4，港航业务闭合1/4，运行成熟度0/4。证据：[manifest.json](/Users/apple/Desktop/小懿AI/data/public/port_standards_v3_20261030/manifest.json)、[operations_v3.py](/Users/apple/Desktop/小懿AI/app/harness/operations_v3.py)。
- **航行/运输模型联动：50分**。功能覆盖3/4，验证深度3/4，陌生场景泛化1/4，港航业务闭合2/4，运行成熟度1/4。证据：[HARNESS_PHASE3_ACCEPTANCE_20261029.md](/Users/apple/Desktop/小懿AI/docs/HARNESS_PHASE3_ACCEPTANCE_20261029.md)、[HARNESS_MODELS_EXPLAINED_20261029.md](/Users/apple/Desktop/小懿AI/docs/HARNESS_MODELS_EXPLAINED_20261029.md)。
- **移动与客户端签收：50分**。功能覆盖3/4，验证深度3/4，陌生场景泛化1/4，港航业务闭合2/4，运行成熟度1/4。证据：[HARNESS_PHASE3_ACCEPTANCE_20261029.md](/Users/apple/Desktop/小懿AI/docs/HARNESS_PHASE3_ACCEPTANCE_20261029.md)。
- **审计回执与执行证据完整性：80分**。功能覆盖4/4，验证深度4/4，陌生场景泛化3/4，港航业务闭合3/4，运行成熟度2/4。证据：[store.py](/Users/apple/Desktop/小懿AI/app/harness/store.py)、[verify_v4_evidence.py](/Users/apple/Desktop/小懿AI/scripts/verify_v4_evidence.py)。
- **权限、注入防护与供应链：60分**。功能覆盖3/4，验证深度4/4，陌生场景泛化2/4，港航业务闭合2/4，运行成熟度1/4。证据：[access_control.py](/Users/apple/Desktop/小懿AI/app/access_control.py)、[prompt_injection_benchmark_v1_20260813.json](/Users/apple/Desktop/小懿AI/reports/prompt_injection_benchmark_v1_20260813.json)、[dependency_audit_admission_v3.json](/Users/apple/Desktop/小懿AI/reports/dependency_audit_admission_v3.json)。
- **监控、健康和故障诊断：65分**。功能覆盖3/4，验证深度4/4，陌生场景泛化2/4，港航业务闭合2/4，运行成熟度2/4。证据：[observability.py](/Users/apple/Desktop/小懿AI/app/observability.py)、[main.py](/Users/apple/Desktop/小懿AI/app/main.py)、[HARNESS_PHASE3_ACCEPTANCE_20261029.md](/Users/apple/Desktop/小懿AI/docs/HARNESS_PHASE3_ACCEPTANCE_20261029.md)。
- **Docker发行与可复现部署：70分**。功能覆盖4/4，验证深度4/4，陌生场景泛化2/4，港航业务闭合2/4，运行成熟度2/4。证据：[Dockerfile](/Users/apple/Desktop/小懿AI/Dockerfile)、[compose.yaml](/Users/apple/Desktop/小懿AI/compose.yaml)、[verify_container_v4.py](/Users/apple/Desktop/小懿AI/scripts/verify_container_v4.py)。
- **真实港口只读接入准备：25分**。功能覆盖2/4，验证深度2/4，陌生场景泛化0/4，港航业务闭合1/4，运行成熟度0/4。证据：[site_admission.py](/Users/apple/Desktop/小懿AI/app/site_admission.py)、[port_site_admission_v1.json](/Users/apple/Desktop/小懿AI/data/contracts/port_site_admission_v1.json)。
- **真实港口自主调度：0分**。功能覆盖0/4，验证深度0/4，陌生场景泛化0/4，港航业务闭合0/4，运行成熟度0/4。证据：[port_site_admission_v1.json](/Users/apple/Desktop/小懿AI/data/contracts/port_site_admission_v1.json)。
- **视频/雷达多模态感知：0分**。功能覆盖0/4，验证深度0/4，陌生场景泛化0/4，港航业务闭合0/4，运行成熟度0/4。证据：尚无已验收模型或实际感知链证据。

## 前沿对标方向与来源

量表由本次审视定义。下列原始资料用于确定应关注的能力方向，没有任何机构为这些分数或本项目背书。

- [MPA Maritime Digital Twin](https://www.mpa.gov.sg/maritime-singapore/innovation-and-r-d/maritime-digital-twin)：历史+实时数据、共享场景、模型验证及先模拟后实施。
- [MPA/SMI Maritime Technology & Research Roadmap2026](https://www.mpa.gov.sg/media-centre/details/singapore-maritime-technology---research-roadmap-2026-edition-to--advance-maritime-innovation-and-capabilities-development)：数字技术规模化、减碳及港航作业整合。
- [DNV RP A204 digital twin assurance](https://www.dnv.com/digital-trust/recommended-practices/digital-twin-assurance-dnv-rp-a204/)：用途、风险、模型及数据可信度的持续保障方向；本项目没有DNV认证。
- [IMO Maritime Single Window](https://www.imo.org/en/ourwork/facilitation/pages/maritimesinglewindow-default.aspx)：跨机构电子信息互通，区别于本地角色演练。
- [DCSA Port Call2.0.0](https://reference.dcsa.org/content/standards/releases/port-call/v2)：统一港口协同语义与接口；本地子集不是完整一致性签收。
- [NIST AI RMF1.0](https://nvlpubs.nist.gov/nistpubs/ai/nist.ai.100-1.pdf)：应用相关有效性、可靠性、风险测量及持续监控；分数并非NIST认证。
- [AgentDojo original benchmark](https://arxiv.org/abs/2406.13352)：真实工具任务中的安全评估方向；固定注入检测题不能替代端到端攻击评测。

MPA/SMI的2026方向涉及数字技术规模应用、减碳及港航流程整合；共享数字孪生还需要历史/实时数据与可运行模型。DCSA/IMO强调跨机构互通；DNV关注数字孪生可信度，NIST关注用途相关的有效性、可靠性和持续风险测量。这些要求使独立验证、真实物理、组织签收和长期运行成为高分条件。

## 如何在界面查看

1. 打开小懿 `http://127.0.0.1:8010`。
2. 进入“**双模式港航联合系统**”。
3. 点击“**小懿逐项功能评分**”，逐项查看分数、能做什么、限制和五维证据。
4. 点击“**最新安全复验、孪生与评分**”，核对最新策略代价、739步容量不可行、气象强迫和缺测。
5. 从“跨港研究历史”选择原已完成研究，点“顶级港口对标验收”，查看仍未通过的六项。
6. 点击“导出研究及来源”，`scorecard`保存评分，`risk`保存本次完整研究和失败；原`learning`、`remediation`分别保留较早研究。

评分JSON为 [xiaoyi_capability_scorecard_20261030.json](../data/evaluation/xiaoyi_capability_scorecard_20261030.json)。变更代码或证据后应重新验收评分依据，不能继续引用旧的“当前有效”标记。


本次最终实际验证为758项Python、47项Node、43项浏览器检查、8个实际本机适配器和12项Docker检查通过；实际4B模型已读取最新证据并完成工具审阅，2,669 tokens，完整失败历史仍保留。[最终验收回执](../.codex_artifacts/remediation-v4-20261030/ACCEPTANCE.json)中的严格港口矩阵仍为5/11，不能将上述工程检查数量解释为智能等级或真实港口生产资格。
