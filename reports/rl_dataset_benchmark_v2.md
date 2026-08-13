# 小懿 RL 公开数据对比与候选准入证据 v2

生成时间：2026-08-13T12:47:28+00:00

本报告追加于v1之后，不覆盖旧训练。它使用固定时间顺序 70%/15%/15% 训练、验证、测试隔离，训练阶段不渲染；全部训练结束后才读取保留测试段并生成轨迹。每套数据使用 3 个随机种子、4 种 RL、PID与现场SOP固定规则两类强基线。95%置信区间使用三种子Student t区间（df=2），小样本区间较宽。

| 数据集 | 行数 | 环境 | 测试均值诊断优选（不用于选模） | 准入状态 | 保留测试摘要 |
|---|---:|---|---|---|---|
| `uci_appliances_energy` | 19,735 | energy_storage | sop_rule | baseline_retained_or_candidate_rejected | 平均测试净成本变化代理 -7.71%（95%CI -7.71%~-7.71%）；峰值变化 -41.52%；终端SOC 0.657；平均约束违例 0.00 |
| `uci_household_power_5min` | 409,887 | energy_storage | sop_rule | baseline_retained_or_candidate_rejected | 平均测试净成本变化代理 0.72%（95%CI 0.72%~0.72%）；峰值变化 -22.92%；终端SOC 0.540；平均约束违例 0.00 |
| `noaa_la_lb_ais_2024_12_25_1min` | 710 | port_operations | pid | baseline_retained_or_candidate_rejected | 平均校准场景积压 103.19；平均约束违例 0.00 |

## 可信度结论

- 新的大规模公开能源基准为 409,887 行，是原 19,735 行基准的 20.77 倍。它提高的是算法规模、重复性与分布跨度证据，不是港口现场真实性。
- NOAA 港口场景来自 AIS 实测交通消息。船舶数量、航速、航行状态和船型来自公开观测；服务量、积压、等待和得分是校准仿真输出，不是洛杉矶或长滩码头生产 KPI。
- 候选只能由验证集多数票选出；测试均值只做盲测诊断，不反向选模。PID或SOP规则胜出时保留基线，失败RL候选及原因全部保留。
- 能源环境v2把终端SOC恢复设为硬门禁，净成本纳入电池吞吐衰减成本，不再允许“放空电池换节费”通过准入。
- 接真实港口仍需提供 DCSA/TOS/VTS/EMS、泊位、堆场、设备、工班、潮汐、天气、闸口与授权字段，并在现场数据上重新标定和测试。

## 可复现与门禁

- 算法：Q-learning、SARSA、Expected SARSA、Double Q-learning、PID、现场SOP固定规则。
- 每种 RL：320 回合；单回合 72 步。
- 固定种子：260813, 260814, 260815。
- 数据、端口配置、模型和测试结果均进入 SHA-256 证据清单。
- 旧的 2026-07-24 UCI 10 回合训练包原样保存在 `reports/rl_evidence/legacy_uci_smoke_20260724/`，并明确标注为烟雾级运行。

证据完整性PASS定义：All scheduled runs completed, temporal and rendering boundaries held, and evidence hashes were generated. Evidence PASS does not mean an RL candidate beat strong baselines or that production targets were met.

生产权限：`production_authority=false`，`dispatch_allowed=false`。离线候选即使通过，也只允许进入现场映射、标定和影子运行阶段。

范围声明：Public offline benchmark and calibrated planning sandbox only. No field productivity, live-control, safety-certification or production-SLA claim is made.
