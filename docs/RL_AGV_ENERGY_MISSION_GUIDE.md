# 可复现 RL 能源与港口作业实验室

## 这次运行的是真训练

左下角“真实RL训练实验室”连接的是本仓库内的训练器，不再读取其他项目的
历史曲线，也不使用前端定时器伪造训练百分比。

完整公平基线包括：

1. Q-learning；
2. SARSA；
3. Expected SARSA；
4. Double Q-learning；
5. PID 控制理论基线；
6. 现场 SOP 固定规则基线。

四种强化学习算法会真实执行 episode、更新动作价值表并保存模型。PID 与SOP
规则都不冒充强化学习：前者按峰值目标、SOC误差和控制项生成动作，后者只按
冻结的业务规则作用于当前观测。

## 三套公开数据与边界

仓库同时保留原始基准、大规模基准和港口交通场景：

- UCI Appliances：19,735 条十分钟级用电与气象观测；
- UCI Household Power：409,887 条五分钟级用电观测，是原基准的规模对照；
- NOAA LA–Long Beach AIS：710 个包含公开 AIS 消息的一分钟港区交通观测桶。

两套 UCI 数据许可证均为 CC BY 4.0，只证明能源环境上的算法规模和复现链，
**不是港口、AGV或生产实绩**。NOAA 场景的船舶数、航速、航行状态和船型来自
公开 AIS；服务量、积压、等待和得分是校准仿真输出，**不是码头生产 KPI**。

重新获取并运行固定多种子对比：

```bash
.venv/bin/python scripts/fetch_public_rl_dataset.py
.venv/bin/python scripts/fetch_large_public_rl_dataset.py
.venv/bin/python scripts/fetch_noaa_port_ais_dataset.py
.venv/bin/python scripts/run_rl_dataset_benchmark.py run
.venv/bin/python scripts/run_rl_dataset_benchmark.py verify
```

## 训练与测试隔离

数据按时间顺序切分，不随机打乱：

- 70% 训练集；
- 15% 验证集，用于算法选择；
- 15% 保留测试集，训练完成前不读取。

训练环境强制 `render_mode=None`。只有全部选定的RL算法训练完毕后，测试接口
才能使用保留测试段生成 `trace`。因此页面显示的测试轨迹来自训练后的策略，
不是训练过程中同步播放的装饰动画。

## 网页操作

1. 启动小懿并打开 `http://127.0.0.1:8010`；
2. 点击左下角“真实RL训练实验室”；
3. 选择数据集、算法、每种算法训练回合、时域步数和随机种子；
4. 点击“启动真实训练”；
5. 查看真实完成 episode 数和后台进度；
6. 训练完成后，系统才执行保留测试集渲染；
7. 查看4种RL、PID与SOP规则共六种候选的成本、峰值、约束违例和综合分数；
8. 复现门禁通过后，可人工确认归档本地 Dry-run 回执。

## API 操作

```text
GET  /api/rl-lab/health
GET  /api/rl-lab/algorithms
GET  /api/rl-lab/datasets
GET  /api/rl-lab/contracts
GET  /api/rl-lab/evidence
POST /api/rl-lab/advisor
POST /api/rl-lab/runs
GET  /api/rl-lab/runs/{run_id}
POST /api/rl-lab/runs/{run_id}/cancel
POST /api/rl-lab/runs/{run_id}/evaluate
```

训练请求示例：

```json
{
  "dataset_id": "uci_appliances_energy",
  "algorithms": [
    "q_learning",
    "sarsa",
    "expected_sarsa",
    "double_q_learning",
    "pid"
  ],
  "episodes": 160,
  "horizon_steps": 72,
  "seed": 240520
}
```

## 换成港口能源数据

最小CSV契约只有两个必填字段：

```csv
timestamp,load_kw
2026-07-20T08:00:00+08:00,1380.4
2026-07-20T08:05:00+08:00,1422.8
```

可选字段为 `temperature_c`、`humidity_percent`、`wind_speed_mps`、
`visibility_km`、`pressure_hpa`、`price_per_kwh` 和 `carbon_kg_per_kwh`。

```bash
export XIAOYI_RL_DATASET_PATH=/data/port/agv_energy.csv
export XIAOYI_RL_DATASET_ID=site-port-energy
export XIAOYI_RL_DATASET_LABEL='某港AGV与站点能源时序'
export XIAOYI_RL_DATASET_TIMEZONE=Asia/Shanghai
```

若现场列名不同，用JSON映射，不改训练代码：

```bash
export XIAOYI_RL_DATASET_MAPPING='{"timestamp":"event_time","load_kw":"agv_and_terminal_load_kw","price_per_kwh":"tariff"}'
```

生产接入仍然只读。模型测试结果不会自动获得TOS、EMS、PLC或AGV控制器写权限。

## 换成港口作业数据

最小港口作业 CSV 契约：

```csv
timestamp,vessel_count,anchored_vessels,avg_sog_knots
2026-07-20T08:00:00+08:00,86,12,3.8
2026-07-20T08:01:00+08:00,88,13,3.5
```

建议同步提供 `slow_vessels`、各船型数量、`berth_occupancy_ratio`、
`yard_occupancy_ratio`、`equipment_availability_ratio`、`gate_queue_trucks`、
`moves_demand`、`wind_speed_mps`、`visibility_km` 和 `tide_window_open`。

```bash
export XIAOYI_RL_DATASET_PATH=/data/port/port_operations.csv
export XIAOYI_RL_DATASET_ID=site-port-operations
export XIAOYI_RL_DATASET_LABEL='站点港口交通与作业时序'
export XIAOYI_RL_ENVIRONMENT_TYPE=port_operations
export XIAOYI_RL_PROFILE_PATH=/data/port/port_profile.json
export XIAOYI_RL_EVIDENCE_LEVEL=site_measured
```

完整观测、动作、目标函数、国际港口因素和验收门禁见
[港口 RL 可替换数据契约](PORT_RL_DATA_CONTRACT.md)。
