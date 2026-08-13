# 港口 RL 可替换数据契约

本契约把数据接入、环境语义、训练证据和生产权限分开。部署方可以更换港口与列名，
但不能跳过时间顺序、来源、质量、配置和模型哈希门禁。

## 两类可执行环境

| 环境 | 最小必填字段 | 用途 | 不代表 |
|---|---|---|---|
| `energy_storage` | `timestamp, load_kw` | 能源/储能五档充放电调度 | 港口作业量或 AGV 现场收益 |
| `port_operations` | `timestamp, vessel_count, anchored_vessels, avg_sog_knots` | 交通—服务能力协同规划沙箱 | 码头生产吞吐、等待或装卸效率实绩 |

公共字段可通过 `XIAOYI_RL_DATASET_MAPPING` 映射到站点列名。所有时间戳必须
唯一且严格递增；每个训练、验证和测试分区至少保留 24 条记录。

## 港口环境观测

| 观测 | 默认来源 | 证据层级 |
|---|---|---|
| `hour_bin` | `timestamp` | 实测时间 |
| `traffic_bin` | `vessel_count` | AIS/VTS 实测 |
| `queue_bin` | `anchored_vessels + slow_vessels` | AIS 代理；接站点后使用锚地/航道事件 |
| `speed_bin` | `avg_sog_knots` | AIS 实测 |
| `backlog_bin` | 环境内部积压状态 | 校准仿真状态 |
| `berth_bin` | `berth_occupancy_ratio` | TOS/PCS；缺失时使用显式代理 |
| `yard_bin` | `yard_occupancy_ratio` | TOS；公开 AIS 场景使用声明默认值 |
| `equipment_bin` | `equipment_availability_ratio` | EAM/TOS；公开 AIS 场景使用声明默认值 |
| `weather_risk_bin` | `wind_speed_mps + visibility_km` | 气象海洋服务；缺失时为声明默认值 |
| `tide_window` | `tide_window_open` | 港调/VTS/潮汐服务；缺失时为声明默认值 |
| `traffic_trend_bin` | 下一时刻与当前船舶数差 | 派生 |

缺失站点因素不会标成实测。公开 AIS 场景中的泊位、堆场、设备、潮汐、天气、
能源和碳排均在数据目录的 `factor_coverage` 中标记为 `site_required`。

## 动作与目标函数

动作是五个离散服务能力档位：

1. 安全降载 `0.65`；
2. 稳态保守 `0.82`；
3. 平衡运行 `1.00`；
4. 增派资源 `1.15`；
5. 高峰恢复 `1.30`。

港口目标函数：

```text
maximize
+ 1.8 * served_units
- backlog
- 12 * safety_violation
- 8 * yard_overflow
- 0.6 * action_change
- 0.5 * resource_boost
```

恶劣天气、设备可用率低或潮窗关闭时，高能力动作先由动作掩码屏蔽。训练和测试
不会写入 TOS、VTS、EMS、PLC 或设备控制器。

## 国际港口换场景清单

每个站点配置需要登记：

- 身份：UN/LOCODE、码头 ID、时区、坐标范围；
- Port Call：DCSA ETA/RTA/PTA/ATA、ETD/RTD/PTD/ATD 与作业量预报；
- 航海服务：泊位、航道、引航、拖轮、带缆、吃水、潮汐、水流；
- 交通：AIS/VTS 船舶数、SOG、航行状态、船型；
- 码头：泊位、岸桥、场桥、堆场、冷藏箱、危险品、工班；
- 集疏运：闸口排队、集卡预约、铁路窗口；
- 环境：风、能见度、浪、水位、能源和碳强度；
- 治理：来源、许可、质量码、更新时间、操作者、人工确认和审计。

没有真实值的字段必须保持缺失或声明默认，不能用随机数补成“现场数据”。

## 环境变量接入

```bash
export XIAOYI_RL_DATASET_PATH=/data/port/port_operations.csv
export XIAOYI_RL_DATASET_ID=site-port-operations
export XIAOYI_RL_DATASET_LABEL='站点港口交通与作业时序'
export XIAOYI_RL_ENVIRONMENT_TYPE=port_operations
export XIAOYI_RL_PROFILE_PATH=/data/port/port_profile.json
export XIAOYI_RL_DATASET_TIMEZONE=Asia/Shanghai
export XIAOYI_RL_EVIDENCE_LEVEL=site_measured
export XIAOYI_RL_DATASET_MAPPING='{"timestamp":"event_time","vessel_count":"ais_vessels","anchored_vessels":"anchorage_count","avg_sog_knots":"mean_sog","berth_occupancy_ratio":"berth_utilization","equipment_availability_ratio":"equipment_ready"}'
```

站点 profile 与数据文件都会进入 SHA-256 记录。训练后任一文件或模型发生变化，
保留测试评估将失败关闭。

## 上线验收

1. 字段映射、单位、时区、缺失率和来源通过数据质量检查；
2. 时间顺序 70%/15%/15% 隔离，测试段训练前不可用；
3. 4 种 RL 与 PID、现场SOP规则使用同一数据划分、时域、随机种子和约束；
4. 至少三个随机种子报告平均值、离散度和优选次数；
5. 训练阶段 `render_mode=None`，训练后才生成测试轨迹；
6. 数据、profile、配置、模型和评估文件哈希匹配；
7. 与调度员回放历史事件并确认动作语义；
8. 影子模式、回滚、人工确认与只读权限通过后，才能讨论更高权限。
