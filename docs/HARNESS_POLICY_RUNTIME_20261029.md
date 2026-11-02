# 本机开源策略运行时与复现

本说明对应 macOS 14.1、Intel x86_64、16GB 内存的当前工作站。小懿原有 Python 环境、生成模型和嵌入模型继续使用；运输预训练策略在本机隔离 Linux 客体中运行，没有使用云端算力，没有重新训练大模型。

## 当前运行配置

| 项目 | 固定版本或约束 |
|---|---|
| Lima | 2.2.1，官方 Darwin x86_64 发布包 |
| 虚拟化 | macOS VZ；2 vCPU、2GiB RAM、8GiB 稀疏磁盘 |
| 系统镜像 | Ubuntu 24.04 minimal，release-20261001，实际内核 6.8 |
| Python / Torch | 客体 Python 3.12 / torch 2.5.1+cpu |
| TorchRL / TensorDict / RL4CO | 0.6.0 / 0.6.2 / 0.5.2 |
| RouteFinder 源码 | v0.4.0，cc3ab078650e8db62c0562a60f421defe38d5ae3 |
| PARCO 源码 | v0.2.0，a118c704ff10539560578f886bce909ebfe55f94 |
| 服务 | 客体 systemd `xiaoyi-policy.service`；主机仅 127.0.0.1:11839 |
| 挂载 | 只读：上游源码、两份权重、推理服务源码；不挂载用户主目录 |
| 其他端口 | catch-all `proto:any` 忽略转发；重启日志已核验 UDP5353 等未转发 |

`requirements.txt` 固定直接依赖，`requirements.lock.txt` 保存实际客体完整安装版本。上游仓库保留原许可证，两个仓库为 MIT。主机不安装新 Torch，不替换原有策略。

## 已核对的下载

- Lima 归档 SHA-256：`6b776e4bc41f358e6ee01fefcc78e2eb26f11635a0fcff632234af77a566c6c4`。
- Ubuntu 镜像 SHA-256：`a8eb6570f87a941f3de2e000c046b9367f8ab1423756a94830d454fae8ad80ff`。
- RouteFinder 权重：`eb09cee46108bac04012c2702f7cd4aac64341064167363255f02f2e63167f90`。
- PARCO 权重：`820ec654d63886ec6e7ad7a39f470eb49bb155596ed9b6dfa6a580bfc9a1844c`。

镜像配置使用普通绝对路径；本机 Lima 的 `file://` 中文路径编码会被误当成字面路径。保留固定内核镜像，不能直接换成滚动的 `current` 镜像。原生 Intel Torch/TorchRL 依赖失败、Homebrew 无 bottle、首次下载与编码路径错误的记录均保留在证据目录，没有将失败当成模型推理成功。

## 本机日常启动

在小懿项目根目录执行：

```bash
.venv/bin/python scripts/manage_policy_runtime.py check
.venv/bin/python scripts/manage_policy_runtime.py start
.venv/bin/python scripts/run_joint_demo.py
```

完整业务任务勾选按登记配置启动时，也会先检查并按需启动这一本机策略服务。启动失败会停在前置门禁，不影响原有问答与联合评估。`stop` 只停止此客体；`freeze` 导出当前健康信息和完整依赖清单。依赖重建使用 `bootstrap`，已有正常运行的客体不需要重装。

新机器重建需要先按官方发布包安装固定 Lima、取得上述固定镜像、权重和源码提交，将 `integrations/policy_runtime/lima-template.json` 中的 `__PROJECT_ROOT__` 替换为项目绝对路径，保存为 `.runtime/policy-vm-config.yaml`，用同一 `LIMA_HOME` 创建 `xiaoyi-policy-runtime` 实例，再运行 `bootstrap`。该模板针对当前 Intel/Apple 账号环境；更换账号时同步调整 systemd 文件中的用户和客体虚拟环境路径。运行时代码位于 `integrations/policy_runtime/`；安装日志和下载摘要位于 `.codex_artifacts/joint-harness-phase2-20261029/`。

## 每次推理的门禁

1. 检查本地服务身份、代码 SHA、关键依赖版本与权重版本。
2. 加载前验证公开固定权重哈希，严格装载所有 `policy.*` 参数，冻结为 eval；没有重训练、随机参数替代或伪造模型类。
3. 验证 SI 单位、车辆、作业、容量、窗口、路网和证据分类；不支持的预训练问题变体明确拒绝。
4. 保留模型原始动作。PARCO 连续同节点动作按其原生 `stay_flag` 解释为等待；非连续重复服务仍被约束检查拒绝。
5. 主机重新检查每箱恰好服务一次、容量、回库补载权限、时间窗、班次、禁行边与车辆能量预算。
6. 选择可行候选中实际目标较好的方案；模型失败或较差时使用合格基线。RouteFinder 对比最近邻和 OR-Tools；PARCO 还使用允许回库补载的同约束 OR-Tools 对照。

距离采用声明的开放堆场欧氏米制距离，不代表已建成实际码头道路地图。RouteFinder 是同质车队距离目标；PARCO HCVRP 是异质车辆最大完工时间目标，不能把二者目标值直接横向相减。OR-Tools 有限计算预算不提供全局最优证明。

## 复核命令

```bash
.venv/bin/python scripts/benchmark_same_contract_policies.py
.venv/bin/python scripts/probe_joint_contention.py
```

前者使用冻结的 44401—44410 实例种子、两个问题域、每例30个作业；完整保留全部结果。后者验证8个同时请求的串行执行与409拒绝。现场数据、真实设备控制、长期SLA与全球榜单结论不由这组有限本机实验推出。

参考原始来源：[RouteFinder](https://github.com/ai4co/routefinder)、[PARCO](https://github.com/ai4co/parco)、[Lima 安装](https://lima-vm.io/docs/installation/)、[VZ 配置](https://lima-vm.io/docs/config/vmtype/)、[OR-Tools 回库示例](https://github.com/google/or-tools/blob/stable/ortools/constraint_solver/samples/cvrp_reload.py)、[路由维度与最长路径目标](https://developers.google.com/optimization/routing/vrp)。
