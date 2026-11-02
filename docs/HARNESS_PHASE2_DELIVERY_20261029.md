# 双模式Harness二期交付（2026-10-29）

已交付完整原生航次、固定开源预训练策略推理、同约束基线比较、资源事件执行、原生业务审批执行核验补偿、客户端签收和故障门禁。验收范围与未验证边界见 [二期验收报告](HARNESS_PHASE2_ACCEPTANCE_20261029.md)。

## 稳定与研究分离

企业模式采用登记流程与合格基线，新预训练运输策略只作影子比较；研究模式允许在独立约束复核后采用学习策略。两种模式共享来源、版本、审批、预算、幂等和审计门禁。原有评估与短时航行样本仍为默认；完整流程显式选择，不替换旧功能。

## 主要代码

- `app/harness/transport.py`：本地隔离模型身份/版本检查、SI路线复核、基线与策略选择。
- `integrations/policy_runtime/`：固定上游策略、补载求解器、动作语义转换、依赖锁和systemd服务。
- `app/harness/coordination.py`：共同工程时钟、资源和原有协同接口适配。
- `app/harness/business.py`：逐操作写前记录、原生工作单、审批、执行、读回和补偿。
- `app/harness/joint.py`、`dual_api.py`、`contracts.py`：可选完整工作流、二次审批、可恢复取消/核查和协议。
- `web/joint_harness.js`：完整范围、岗位选择、候选数值比较、审阅/控制/导出；`web/app.js`保留快速打开的工作台，资源版本已更新。
- 数字孪生新增 `tools/harness_business_worker.py`、`app/services/harness_event_execution.py`；航行新增 `tools/harness_full_voyage.gd`；Flutter扩展原联合任务卡。

## 交付路径

- 本机入口：http://127.0.0.1:8010/；Flutter：http://127.0.0.1:7357/。
- 最终企业任务：jm-0b2a7dd640044757ad71a8ec0f78d365；完整研究任务：jm-88323d580ada46089b46df05e01b33d6。
- 安装与启动：[运行时说明](HARNESS_POLICY_RUNTIME_20261029.md)。
- 原有一期报告和失败记录保留，二期补齐结论以本次报告和原始回执为准。

没有重新训练或替换小懿原大模型。新增运行时、模拟控制和测试都保留在本机。真实生产授权与本机演练分开。
