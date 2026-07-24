# 小懿

> 当前版本：0.3.0。项目按可公开复现、证据边界明确和生产默认安全的标准维护。

小懿是一个面向港口、航运、港航运行场景的迷你版 LLM 助手。

它的核心能力包括：

- 港航基础知识库
- 本地 RAG 检索
- 港航专家回答模板
- 专业问答模式
- SOP 与告警解释模式
- FastAPI 服务
- Web 交互页面
- CLI 命令行问答
- 生产形态的港口运营动态沙箱、能耗趋势与预警 API
- 可逐步推进的智能任务和结构化报告生成
- 真实时序数据驱动的本地 RL 训练实验室
- 4 种强化学习算法与 1 种 PID 控制基线
- 训练无渲染、训练后保留测试集轨迹与模型/数据哈希
- JWT 身份验证、四级角色权限、限流、安全响应头和持久幂等
- 服务端会话、任务、报告、自动化计划与审计状态持久化
- 深度就绪检查、Prometheus 指标、JSON 日志和请求追踪编号
- 可选 OpenAI-compatible 模型网关，含证据门禁、隐私开关、重试、熔断和本地回退

## 项目结构

```text
小懿AI/
  app/
    main.py              # FastAPI 服务入口
    operations.py        # 运营看板、任务执行与结构化报告 API
    port_runtime.py      # 沙箱/生产可替换数据适配器
    rl_lab/              # 数据契约、环境、4种RL、PID、后台训练与评估API
    operator_assistant.py # 一线口语、对象追问和岗位快捷问法
    xiaoyi.py            # 小懿回答引擎
    retrieval.py         # Hybrid Sparse 与 BM25 对照检索
    prompts.py           # 港航专业提示词
    models.py            # 请求与响应模型
    config.py            # 路径与配置
  data/
    kb/                  # 港航基础知识库
    evaluation/          # 固定港航检索与证据安全评测集
    public/              # 公开RL基准数据与血缘记录
    rl_datasets.json     # 公开与站点数据集目录
    xiaoyi_index.json    # 构建后的检索索引
  scripts/
    build_index.py       # 知识库索引构建脚本
    fetch_public_rl_dataset.py # 固定来源下载并校验公开RL数据
    run_rag_benchmark.py # 运行/验证固定RAG基准并生成带哈希报告
  web/
    index.html           # Web 交互页面
  tests/
    test_retrieval.py    # 基础验证
    test_operations_api.py # 运营 API 与兼容性回归
```

## 快速运行

推荐直接使用项目启动脚本；首次运行会创建 `.venv`、安装运行依赖、重建索引并启动服务：

```bash
cd <xiaoyi-ai-repository>
bash run.sh
```

也可以手动运行：

```bash
cd <xiaoyi-ai-repository>
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
python scripts/build_index.py
uvicorn app.main:app --reload --port 8010
```

打开：

```text
http://127.0.0.1:8010
```

## 命令行测试

```bash
cd <xiaoyi-ai-repository>
python -m app.cli "岸电 THDi 超标告警应该先检查什么？"
python -m app.cli "小懿的核心能力是什么？" --mode expert
```

## 系统说明

小懿是面向港航场景的小型 AI 助手。它采用本地港航知识库和 RAG 检索，结合专业问答、SOP 生成、告警解释和运营建议。默认 `local_rules` 生成路径不依赖外部模型；也可显式配置 OpenAI-compatible 模型网关。只有已通过证据门禁、不含沙箱运营数据且完成外发授权的回答才允许发往外部模型；其他情况保留本地严格证据答案。

运营看板默认使用后端持续生成的运营沙箱事件流。它具有生产形态的业务对象、时间戳、质量码、延迟和来源适配器，但明确标记为非生产实绩。切换生产时保持 `port-ops.v1` 契约并配置只读数据网关；高风险任务仍返回 `requires_human_confirmation: true`，不会因接入真实数据自动获得写权限。

## 港口运营数据 API

```text
GET  /api/dashboard                 聚合运营概况、能耗、预警和快捷任务
GET  /api/runtime/status            数据模式、来源、质量、延迟与生产边界
GET  /api/runtime/snapshot          船舶、泊位、设备、堆场和闸口业务对象
GET  /api/operations/overview       实时运营概况
GET  /api/energy?range=today        能耗与碳排趋势（today / 7d / 30d）
GET  /api/alerts                    预警列表，可按 level/status 筛选
GET  /api/tasks/templates           可执行任务模板
POST /api/tasks                     创建运营沙箱任务
POST /api/tasks/{task_id}/next      完成当前步骤并推进到下一步
POST /api/reports                   生成结构化运营报告
GET  /api/reports/{report_id}       获取已生成报告
GET  /api/operator/scenarios        一线岗位快捷问法与安全边界
```

生产数据切换说明见 [港口运营数据适配器](docs/PORT_OPERATIONS_DATA_ADAPTER.md)。默认无需配置；接生产网关时设置 `XIAOYI_PORT_DATA_MODE=live`、`XIAOYI_PORT_BASE_URL` 和可选只读令牌即可。网关未返回 `live_data_verified=true` 或版本不是 `port-ops.v1` 时，服务会失败关闭，绝不把数据冒充生产实绩。

运行测试：

```bash
python -m pip install -r requirements-dev.lock
pytest -q
```

## 安全、持久化与运维

本地模式仅用于回环开发。生产模式必须使用签名 JWT、显式主机名和 CORS 来源，否则服务拒绝启动。对话、任务、报告、自动化计划、反馈与审计保存在 SQLite；中断工作在重启后会安全标记为失败或取消，不会无声续跑。

```text
GET  /health/live               进程存活
GET  /health/ready              存储、索引、RL数据、模型和部署配置深度就绪
GET  /metrics                   Prometheus指标（生产应限制到监控网络）
GET  /api/system/info           当前安全与运维能力
GET  /api/models                模型配置、回退与熔断状态
GET  /api/conversations/{id}    当前身份的持久对话历史
POST /api/chat/stream           服务端事件流式回答
```

部署、TLS/SSO、密钥、备份、模型数据外发和多实例边界见 [部署指南](docs/DEPLOYMENT.md)；信任边界见 [系统架构](docs/ARCHITECTURE.md)；开源审计结论见 [真实性与工程化评估](docs/OPEN_SOURCE_READINESS.md)。

## 当前适合问的问题

完整分类问题库见：[小懿可询问问题库](小懿可询问问题库/00_问题库使用说明.md)。其中已区分当前运营沙箱、知识库问答和生产系统接入后实时问题。

## 可复现 RL 训练实验室

RL板块不再回放其他项目的历史训练曲线。当前实现会在后台真实执行
Q-learning、SARSA、Expected SARSA 和 Double Q-learning，并用 PID 作为控制
理论基线。训练百分比来自已完成 episode 数，模型按算法保存并计算 SHA-256。

默认数据为 UCI Appliances Energy Prediction 的 19,735 条真实十分钟级能源与
气象观测（CC BY 4.0，DOI `10.24432/C5VC8G`）。它是公开算法基准，不是港口
实绩。数据按时间切成训练/验证/保留测试段；训练强制不渲染，训练全部结束后
测试接口才生成轨迹。

```bash
# 数据随仓库提供；也可以从固定UCI来源重新生成并核验
.venv/bin/python scripts/fetch_public_rl_dataset.py

# 运行全部测试
.venv/bin/python -m pytest -q
```

接口：

```text
GET  /api/rl-lab/health
GET  /api/rl-lab/algorithms
GET  /api/rl-lab/datasets
POST /api/rl-lab/runs
GET  /api/rl-lab/runs/{run_id}
POST /api/rl-lab/runs/{run_id}/cancel
POST /api/rl-lab/runs/{run_id}/evaluate
```

接入港口时提供至少包含 `timestamp,load_kw` 的CSV并设置
`XIAOYI_RL_DATASET_PATH`；可选接入电价、碳强度和气象列，不需要修改训练器。
完整说明见[可复现RL能源调度实验室](docs/RL_AGV_ENERGY_MISSION_GUIDE.md)。

- 港口由哪些核心业务模块组成？
- 集装箱码头从船舶靠泊到离港的流程是什么？
- TOS 系统在港口运营里负责什么？
- 岸电 THDi 超标告警应该先检查什么？
- 台风红色预警下港区要启动哪些安全流程？
- 港口碳排放盘查需要保留哪些证据？
- 小懿的系统架构是什么？

## 真实港口连接器（待站点联调）

项目已预留 TOS、PCS、EMS、EAM、VTS、AIS、气象海洋和国际贸易单一窗口连接器契约，但默认全部离线，未配置任何真实端点或凭据。安全配置、站点联调、写操作门禁、回滚和审计要求见 [港口连接器接入手册](docs/PORT_CONNECTOR_INTEGRATION.md)，环境变量模板见 [`.env.connectors.example`](.env.connectors.example)。

```text
GET  /api/connectors                              连接器目录与状态
GET  /api/connectors/{id}/field-mappings          字段映射模板
POST /api/connectors/{id}/health-check            执行真实健康探测
POST /api/connectors/{id}/write-preflight         写操作预检（不执行下发）
```

## 智能操作与可审计知识库

```text
POST /api/automation/plans                       将自然语言解析为白名单界面步骤
POST /api/automation/plans/{id}/next             回写当前步骤结果并推进计划
POST /api/automation/plans/{id}/confirm          绑定当前动作的人工确认或拒绝
GET  /api/knowledge/status                       文档、片段、官方来源与索引哈希
GET  /api/knowledge/catalog                      24 大类 / 96 主题的专业资料覆盖路线图
GET  /api/knowledge/authority-coverage           权威来源族、已覆盖、缺口与许可隔离矩阵
POST /api/knowledge/search                       检索正文索引并返回来源与双 SHA-256
GET  /api/knowledge/sources                      查看来源登记与验证等级
POST /api/knowledge/intake                       暂存待人工审核资料，不进入正式索引
```

专业资料全目录与当前覆盖状态见 [港航专业知识总目录](docs/PORT_MARITIME_KNOWLEDGE_CATALOG.md)；知识来源分级、资料审核、发布、索引重建与拒答边界见 [知识库治理说明](docs/KNOWLEDGE_GOVERNANCE.md)。

一线调度、值班、设备、闸口、堆场和交接班人员的完整使用流程见 [一线操作人员系统指南](docs/XIAOYI_FRONTLINE_OPERATOR_SYSTEM_GUIDE.md)。

## 小懿智能联动中心（7项能力）

小懿只承担港航知识、RAG、上下文识别、能力路由、结果解释和审计，不复制能碳驾驶舱、数字孪生平台、马六甲沙盘或航行模拟器的业务功能。跨系统能力默认 `offline`，不访问其他系统；dry-run 只检查契约，显式配置为 `live` 后也只允许登记的 GET 只读能力。

```text
GET  /api/hub/systems                            四个内部系统能力目录
GET  /api/hub/capabilities                       只读能力清单
POST /api/hub/capabilities/{id}/invoke           隔离预览或授权只读调用
POST /api/context/resolve                        统一港航业务上下文
POST /api/evidence/fuse                          知识/系统/推演证据融合
POST /api/orchestrator/run                       自然语言跨系统编排
GET  /api/governance/audit                       SQLite 持久审计
POST /api/evaluation/run                         固定 RAG 回归评测
POST /api/evaluation/feedback                    提交人工反馈
POST /api/evaluation/feedback/{id}/review        审核后转入知识待审核区
```

网页左侧点击“智能联动中心”即可查看 7/7 完成度、系统能力注册表、跨系统安全预览、RAG 评测和反馈闭环。完整验证步骤见 [智能联动中心说明](docs/XIAOYI_INTELLIGENCE_HUB.md)。

## 可复现港航 RAG 与证据安全基准

仓库提供 60 题固定版本评测集：40 题检索、20 题证据策略；其中 35
题构成 v1 固定测试分区。当前知识快照为 112 份文档、708 个分块和 60
份官方核验来源。测试分区的 24 个检索题上，Hybrid Sparse 的
Hit@1/3/5 为 87.50%/100%/100%，BM25-only 为
75.00%/95.83%/100%；Hybrid 在首位命中率上提升 12.50 个百分点，
MRR 为 0.9236 对 0.8507（+7.29 个百分点）。Hit@5 同为 100%，不把
已经饱和的 Top-5 指标包装成提升。
11 个策略测试覆盖条款级拒答、无依据回答阻断、辖区路由、法规日期切换和
实时数据边界，当前为 11/11。

```bash
# 快速核对报告所绑定的数据、索引和核心代码哈希
.venv/bin/python scripts/run_rag_benchmark.py verify

# 完整重跑全部60题并比对确定性结果，单核环境可能需要数分钟
.venv/bin/python scripts/run_rag_benchmark.py verify --deep

# 重新生成报告
.venv/bin/python scripts/run_rag_benchmark.py run
```

固定题集、[JSON证据报告](reports/maritime_rag_benchmark_v1.json)和
[可读报告](reports/maritime_rag_benchmark_v1.md)随仓库发布。该测试分区用于
v1 发布验收，并在工程修复中暴露过缺陷，因此不是“从未查看的独立留出集”；
题目由项目维护，也不是第三方用户研究。上述数字是仓库基准上的检索与安全
指标，不是港口生产收益、全球知识覆盖率、法律意见或线上 SLA。

简历可用声明与禁用表述见 [简历指标口径](docs/RESUME_CLAIMS.md)。
