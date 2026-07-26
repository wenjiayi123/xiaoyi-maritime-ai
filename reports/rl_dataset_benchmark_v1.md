# 小懿 RL 公开数据对比证据 v1

生成时间：2026-07-26T01:00:27+00:00

本报告使用固定时间顺序 70%/15%/15% 训练、验证、测试隔离，训练阶段不渲染；全部训练结束后才读取保留测试段并生成轨迹。每套数据使用 3 个随机种子、4 种 RL 与 1 个 PID 控制基线。

| 数据集 | 行数 | 环境 | 多种子平均测试优选 | 保留测试摘要 |
|---|---:|---|---|---|
| `noaa_la_lb_ais_2024_12_25_1min` | 710 | port_operations | pid | 平均校准场景积压 103.19；平均约束违例 0.00 |
| `uci_appliances_energy` | 19,735 | energy_storage | pid | 平均测试节费代理 -8.74%；峰值变化 10.55%；终端SOC 0.503；平均约束违例 0.00 |
| `uci_household_power_5min` | 409,887 | energy_storage | expected_sarsa | 平均测试节费代理 35.46%；峰值变化 -86.58%；终端SOC 0.107；平均约束违例 0.00 |

## 可信度结论

- 新的大规模公开能源基准为 409,887 行，是原 19,735 行基准的 20.77 倍。它提高的是算法规模、重复性与分布跨度证据，不是港口现场真实性。
- NOAA 港口场景来自 AIS 实测交通消息。船舶数量、航速、航行状态和船型来自公开观测；服务量、积压、等待和得分是校准仿真输出，不是洛杉矶或长滩码头生产 KPI。
- 多种子结果允许 PID 胜出。发布证据保留真实比较结果，不为了展示 RL 而隐藏控制基线。
- 接真实港口仍需提供 DCSA/TOS/VTS/EMS、泊位、堆场、设备、工班、潮汐、天气、闸口与授权字段，并在现场数据上重新标定和测试。

## 可复现与门禁

- 算法：Q-learning、SARSA、Expected SARSA、Double Q-learning、PID。
- 每种 RL：320 回合；单回合 72 步。
- 固定种子：260726, 260727, 260728。
- 数据、端口配置、模型和测试结果均进入 SHA-256 证据清单。
- 旧的 2026-07-24 UCI 10 回合训练包原样保存在 `reports/rl_evidence/legacy_uci_smoke_20260724/`，并明确标注为烟雾级运行。

PASS 定义：全部计划运行已完成，时间与渲染边界成立且证据哈希已生成；不代表 RL 战胜 PID，也不代表达到生产目标。

范围声明：Public offline benchmark and calibrated planning sandbox only. No field productivity, live-control, safety-certification or production-SLA claim is made.
