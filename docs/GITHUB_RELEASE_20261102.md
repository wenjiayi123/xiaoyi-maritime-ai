# 小懿 Harness 与语言模型 RL 发布记录

发布快照：2026-11-02；发布标识：`harness-rl-20261102`。本次将 9 月以来的本地工程更新、Harness V13、语言模型 RL 实验代码和已完成的对照结果同步到公开仓库。基础应用 API 版本仍为 `0.4.0`；Harness、实验协议与发布快照分别标识版本。

## 本次内容

- Harness 任务持久化、审批、追问、暂停/恢复、工具循环、检查点、执行核验与失败恢复；V13 支持 4B 模型逐步选择工具，预算为 18 步/900 秒，模型不可用时不把规则回退伪装成自主执行。
- 港口、能碳、马六甲、航行模拟器等本机适配器，以及联合研究、来源与时效检查、上海港公开数据实验工作台。
- 独立的 1.7B 语言模型工具策略训练入口、环境、LoRA 更新、对照与能力保持检查、轨迹重放审计、实验展示页面。
- 已完成 `experiment-004` 的五组结果与图表；保留 `experiment-003` 的负结果、前两次未完成尝试和全部六次本机 API 验收结果。

原 4B 日常模型与 1.7B RL 实验模型分别运行；本次发布没有重训模型。模型基座、访问凭据、个人工作资料、运行数据库和计算缓存不随源码发布。

## RL 结果与解释

主报告：[完整验收说明](AGENT_RL_V2_ACCEPTANCE_20261102.md)；[方法与目标函数](AGENT_RL_V2_METHODS_20261102.md)；[机器可读结果](../reports/agent-rl/20261102/audited-summary.json)。

| 同一 Harness 下的组别 | 留出案例完成数 | 完成率 | 平均工具调用 |
|---|---:|---:|---:|
| A 固定规则 | 24/24 | 100.0% | 4.38 |
| B 原始 1.7B 模型 | 9/24 | 37.5% | 10.50 |
| C 冻结 SFT | 14/24 | 58.3% | 8.54 |
| D SFT＋RL | 19/24 | 79.2% | 6.29 |
| E 继续 SFT | 22/24 | 91.7% | 5.58 |

D 相对 C 增加 20.8 个百分点，但低于 E 12.5 个百分点。配对案例中 D 相对 C 为 6 个失败变成功、1 个成功变失败。单训练种子、24 个合成留出案例、已知的 8 个任务族与 13 个动作候选，不构成统计显著、未知任务泛化或 RL 全面优越性的证明。方法是两步模拟器前瞻的有限动作 actor 优化，不是 PPO/GRPO。

D/E 各完成 512 次更新，在开发验证后均选第 384 步；229,376 个 LoRA 参数真实更新。选择网格在最终测试前修订，原协议和修订均保留。独立 20 题保持检查 C/D/E 均为 15/20；三条本机指令 C/D 均为 2/3。实际系统执行没有观察到组间成功率优势；20.8 个百分点来自合成留出评测。

第一轮 `experiment-003` 为 C=11/24、D=10/24，作为负结果保留。后续 `experiment-005-pilot` 因可行性问题停止；`experiment-006-curriculum` 在本次取快照时仍在开发训练，未打开最终测试，不纳入已完成结果。后续策略见[研究说明](AGENT_RL_V3_STRATEGY_20261102.md)。

## 下载与复核

[GitHub Release 与完整证据 ZIP](https://github.com/wenjiayi123/xiaoyi-maritime-ai/releases/tag/harness-rl-20261102) 包含冻结的训练日志、权重/优化器检查点、反事实分支、源码快照、六次原生任务记录、负结果以及可离线打开的 `展示报告.html`。ZIP 约 101 MB；SHA-256：

```text
779e36797720c61936efb7393eaeed31a9c79a0c55f8915cbc75e0f06d733a1d
```

仓库内[证据目录](../reports/agent-rl/20261102/README.md)包含全部 120 条最终测试轨迹、图表和摘要，可在不下载基座或启动业务系统的条件下复核：

```bash
python3 scripts/verify_published_agent_rl.py
```

完整审计需要安装 `requirements-agent-rl-intel.lock` 对应的训练依赖（该锁文件面向 Intel macOS，其他平台需适配依赖），并解压 Release ZIP。把下面的路径替换成解压后的证据包根目录：

```bash
mkdir -p /tmp/xiaoyi-rl-replay
cp -R /path/to/evidence/experiment /tmp/xiaoyi-rl-replay/experiment-004
python scripts/audit_agent_rl_v2.py --experiment /tmp/xiaoyi-rl-replay/experiment-004
python scripts/audit_agent_rl_native_v2.py --experiment /tmp/xiaoyi-rl-replay/experiment-004 \
  --job /path/to/evidence/native/arj-a3eaeb4ffbbd4933ba70d4f13639429e \
  --job /path/to/evidence/native/arj-f089295a60134f31bc905325ff7e2355 \
  --job /path/to/evidence/native/arj-5fc6336f04654989ac3403de92a1afde \
  --job /path/to/evidence/native/arj-9a5fc94a5e5d4cab9708dd569a0470f0 \
  --job /path/to/evidence/native/arj-ae158a2de29e4d14b84e649086be6b0d \
  --job /path/to/evidence/native/arj-d3b427977a9b4af5a121a8ea488ae285
```

原生审计按实验编号核验目录名，所以副本保留为 `experiment-004`。审计会写回审计摘要，请对证据包的副本运行；它不调用模型、不访问业务 API、不重新训练。训练复现另需同一基座；原生验收复演另需各业务服务。历史记录内的本机绝对路径属于来源记录，不是其他机器的部署要求。

## 运行与边界

基础运行先按 README 安装依赖并构建知识索引，再运行 `python3 scripts/restore_research_evidence.py` 恢复仓库内封存的 56 份研究报告、选择记录与小型数值策略；恢复程序拒绝覆盖不同内容的本机文件。Harness 入口见[运行说明](HARNESS_RUNTIME.md)和[V13 更新](XIAOYI_HARNESS_V13_20261101.md)，RL 页面入口见[第二轮验收](AGENT_RL_V2_ACCEPTANCE_20261102.md)。外部业务系统、模型权重及运行期证据不在一个源码仓库中；缺少它们时相应核验按现有门禁拒绝通过。

公开研究数据保留加工样本与来源元数据。PortWatch 全港口原始导出约 90 MB，作为 Release 的独立附件 `published-daily-ports-export.csv.gz` 提供；如需完整来源重放，将其放回 `data/public/portwatch_crossport_20261030/raw/`。只运行基础应用和语言模型 RL 证据复核不需要该全量文件。

所有业务结果仍是公开数据回放或本机工程模拟，`production_authority=false`。各系统地点、时钟与数据来源分别解释；下游策略身份警示、失败记录和历史证据均保留。

跨仓库上海港规划测试需要 `SHANGHAI_MALACCA_ROOT` 指向含 `scripts/operations/runShanghaiPlanV1.ts` 的马六甲项目及 Node.js；全量 PortWatch 来源核验需要上述原始导出。依赖缺失时相应测试明确跳过，不计为通过。

## 发布前验证

本次独立发布副本通过 1,051 项 Python 测试、47 项前端测试、Ruff、编译、依赖一致性及发布门禁。独立仓库测试明确跳过 21 项（18 项依赖外部规划器/全量原始导出，3 项依赖可选训练环境）；接入本机外部依赖后，相关 40 项测试另行通过，其中包含与前次重叠的测试，不能相加成总通过数。

10 个本机联动动作重新验收通过，含幂等、观测、配置恢复和关闭生产权限。首次隔离服务缺少航行/Godot路径导致的 9/10 结果保留；配置路径后另起验收记录，未覆盖失败。RL 完整审计重新通过 120 条最终测试轨迹、55,068 个训练分支转移、32 个中间权重检查点和六次原生记录。

验证日志与发布摘要见 [`reports/publication_20261102`](../reports/publication_20261102/summary.json)。GitHub 远程工作流结果以对应提交的 Checks 页面为准。

云端首次检查另外暴露了审批测试依赖作者本机路径、可选 HTTP 客户端未安装及公开 API 错误文本/图表路径/正则问题。发布分支已将审批状态机改用隔离源文件测试，外部港口执行模块缺失时仅跳过对应集成测试；API 固定图表白名单、限制符号链接并隐藏内部异常，相关回归与记录见发布日志。V8 注册表仅重新绑定了错误响应层源码，训练、预测、调度算法及冻结结果未改变。

独立 Linux 策略运行器的新安装清单修复了 GitHub 阻断的 PyTorch critical 漏洞；临时隔离目录完成导入及两套检查点加载检查，现有 VM 未改动。旧环境 freeze 和修订理由保留。该修订独立于已经冻结的语言模型 RL 实验；不把新依赖的兼容检查当作新性能结果。

Release ZIP 内的 `implementation/` 与依赖记录保留实验时的历史快照；新部署使用仓库当前修订源码。安全修订没有重跑或改写冻结的 RL 数值。独立运输策略兼容探针中，RouteFinder 的 10 作业案例通过约束检查，PARCO 案例被独立验证器以 `refill_not_allowed` 拒绝，原始结果保留，不作为策略晋级证据。
