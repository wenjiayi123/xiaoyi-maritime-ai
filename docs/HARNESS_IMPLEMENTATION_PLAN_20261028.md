# 小懿 Harness 实施与验收清单

日期：2026-10-28。实施前基线：Python 470 项通过（49.72 秒）；Node 46 项通过。保留原工作区修改，原问答、RL、系统启动器、联动和数据检查入口继续存在。

2026-10-29执行状态：以下六步的本机实施与验收已完成；结果、实测和未达条件见 [最新验收记录](HARNESS_ACCEPTANCE_20261029.md)。国际顶级综合性能与全产品功能覆盖尚无验收证据。

## 实施步骤

1. 固定基线与保护范围，记录现有工作区和核心文件摘要。
2. 实现独立的持久化任务运行层：模型/规则双适配、有界工具循环、计划、检查点、租约、取消、暂停、恢复、追问、运行中补充约束、上下文整理、工件和回执。
3. 接入现有港航知识、运行快照、登记联动动作与确定性计算；工具逐项校验身份和参数；有副作用动作必须绑定具体方案审批，未知写结果不自动重试。
4. 增加任务工作台：创建、历史、实时步骤、工具轨迹、预算、来源、审批、追问、停止、恢复和导出。按需加载，不影响原页面启动。
5. 建立协议、故障、安全、并发和端到端评测，复跑原有回归，修复缺陷。
6. 记录实际模型联调、浏览器验收、能力对照和限制，形成验收报告。

## 能力验收

- 运行：多步工具结果反馈、结构化动作、计划、步数/工具数/时间/token预算、重复无进展停止。
- 状态：SQLite事务、任务隔离、事件序号与摘要链、检查点、执行租约、过期工作恢复、不确定副作用隔离。
- 控制：运行中补充指令、追问与回答、暂停/继续、取消、审批接受/拒绝/过期，禁止过期许可重放。
- 上下文：目标与约束保留、大输出引用、工具结果摘要、版本化技能、显式用户记忆与删除。
- 工具：白名单、严格参数、来源保留、同任务虚拟工件、受限算术、并行只读研究分支、现有跨系统联动复用。
- 集成：可配置 OpenAI-compatible 模型接口；规则回退明确标识；MCP 只读工具服务；认证事件流。
- 质量：任务轨迹、结果引用核验、失败归因、独立任务评测、回放与实际模型结果分开记录。
- 回归：原有 Python/Node 测试无新增失败；新增工作台在桌面与窄屏可操作。

## 对标口径

参照 OpenAI Codex/Agents、Anthropic Agent SDK 长任务实践、LangGraph/Deep Agents 公开能力设计。实现覆盖与实测性能分别报告。完整业务 Harness 不意味着授予任意主机 Shell、开放真实设备控制或覆盖所有厂商产品功能；不宣称未经共同基准支持的国际性能排名。

参考：

- https://developers.openai.com/blog/codex-as-a-platform
- https://developers.openai.com/api/docs/guides/agents/guardrails-approvals
- https://www.anthropic.com/research/effective-harnesses-for-long-running-agents
- https://www.anthropic.com/research/demystifying-evals-for-ai-agents
- https://docs.langchain.com/oss/python/deepagents/overview
