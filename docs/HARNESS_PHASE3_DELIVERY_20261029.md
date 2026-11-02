# 三期演示与验收使用说明

本轮最终结论、尚未完成项目与证据见[三期验收报告](HARNESS_PHASE3_ACCEPTANCE_20261029.md)。模型分工和面试介绍见[小懿现在调用了哪些模型](HARNESS_MODELS_EXPLAINED_20261029.md)。当前已完成所列本机验收，原生窗口仍按用户要求跳过。

## 启动与检查

在 `/Users/apple/Desktop/小懿AI` 执行：

```bash
.venv/bin/python scripts/manage_policy_runtime.py check
.venv/bin/python scripts/run_joint_demo.py
```

`check`显示策略服务在线后即可继续。只有尚未就绪、确需启动策略运行时，才在没有执行任务时运行 `.venv/bin/python scripts/manage_policy_runtime.py start`；当前这个命令会重启客体策略服务，已有正常服务无需重复运行。

原有问答在 <http://127.0.0.1:8010/>；联合系统入口是侧栏“双模式港航联合系统”。Flutter网页客户端在 <http://127.0.0.1:7357/>。完整任务按登记配置检查、启动所需业务服务。当前Intel本机使用既有隔离Linux运行两个预训练运输策略，详细版本和迁移条件见[开源策略运行时说明](HARNESS_POLICY_RUNTIME_20261029.md)。

原生窗口自动控制按用户要求跳过，不需要升级系统或修改系统安全设置来完成网页与headless演示。

## 现场执行一轮新任务

1. 选择企业受控或RL研究模式，执行范围选择“完整原生航次与业务执行、核验、补偿”。单人本地演示选择明确标注的“显式模拟两个岗位的演练”。
2. 选择已准入航行情景，例如港内航行或自动靠泊。研究模式需要先选已有有效研究记录；追越场景另需协议确认。
3. 使用“生成联合计划”查看受控模板，或使用“由模型理解并规划”调用原语言模型。模型请求需要实际推理时间，避免重复提交。审阅计划后批准。
4. 等原生航次运行到终点，再核对运输对照、来源、共同工程时钟和资源排程。未通过的候选不获准采用。
5. 审阅三个系统的具体工作单后，点击模拟岗位演练确认。真实岗位模式需要两个独立认证身份；本机local身份不能冒充正式签字。
6. 等待原系统实际执行、读回核验、补偿与恢复，再由页面提供的真实链接进入Flutter读取并签收同一任务。
7. 回到小懿刷新，确认状态为“已完成”，导出JSON回执。只有实际客户端确认才计入该完整终态。

历史已完成记录可以直接从“任务历史”查看，用于时间有限的讲解；应说明是在回看已有实际执行回执。当前两份客户端签收的三期记录为：

- 企业：`jm-fb1fde6b80534698a2c5354ccf4aa5d2`。
- 研究：`jm-2214c578e09b426a973692e13d80e751`。

旧待审批计划受时效和实现摘要约束。过期或版本改变时重新生成计划，不复用旧批准。

## 复跑持续测试

以下输出目录必须是尚不存在的新目录。测试仅使用本地仿真和显式模拟岗位，不替代Flutter签收。

```bash
.venv/bin/python scripts/soak_joint_system.py --seconds 7200 --out .codex_artifacts/recheck-soak-new
.venv/bin/python scripts/soak_full_business.py --cycles 14 --out .codex_artifacts/recheck-business-new
```

第一条探测九个服务并运行原短时评估和运输比较；第二条覆盖七个完整航行情景各两种模式。它们共享串行执行器，会保留忙时跳过或409记录。后台单独测试正常结束时保留`partial`回执，再通过正常取消入口结束本测试任务，释放未结束任务名额；这不等于手机签收。

实际测试未结束前，不应关掉所依赖的服务。停止测试使用正常SIGINT/SIGTERM；服务启动器只负责它自己创建的进程，不会覆盖其他端口上的未知服务。

## 本机证据位置

`/Users/apple/Desktop/小懿AI/.codex_artifacts/joint-harness-phase3-20261029/` 包含：

- `ui-coverage.json`：五个网页原演示主流程122步及原生窗口跳过说明。
- `enterprise-ui-export.json`、`research-ui-export.json`：实际页面下载的任务回执。
- `active-model-identities.json`：生成、嵌入、预训练策略及可选规划器的实测状态。
- `original-integrity-phase3-final.json`：原数据、模型和数据库最终校验。
- `soak-accepted-2h/`：持续探测协议、每个样本、负载记录、原运行脚本与终态统计。
- `native-business-soak/`：最终14轮完整业务循环的协议、逐轮回执、正常收尾回执及终态统计。
- `evidence-summary.json`、`native-voyage-matrix.csv`：不混淆终态的汇总与逐航次核对。
- `stability-evidence.png/.svg`及三个CSV：直接来自原始观测的图和可复算数据，无平滑或推断的现场收益。

准备阶段失败、配额保护记录和旧任务均保留。测试通过范围限定为本机软件仿真，不代表真实港口生产授权、硬件在环、海试、认证或长期SLA。

本轮17份源文件的本地审阅快照为`HARNESS_PHASE3_SOURCE_20261029.zip`，每份文件及ZIP均记录SHA-256，已检查ZIP完整性。它包含相应文件中用户已有的更改；合并其他版本前先对比，运行时仍依赖原工程、数据和权重。
