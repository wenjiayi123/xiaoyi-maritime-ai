# 可复现 RL 能源调度实验室

## 这次运行的是真训练

左下角“真实RL训练实验室”连接的是本仓库内的训练器，不再读取其他项目的
历史曲线，也不使用前端定时器伪造训练百分比。

完整公平基线包括：

1. Q-learning；
2. SARSA；
3. Expected SARSA；
4. Double Q-learning；
5. PID 控制理论基线。

四种强化学习算法会真实执行 episode、更新动作价值表并保存模型。PID 不冒充
强化学习，它直接根据峰值目标、SOC误差以及比例、积分、微分项生成控制动作。

## 数据来源与边界

默认数据是 UCI Appliances Energy Prediction：19,735 条十分钟级真实用电和
室外气象观测，许可证为 CC BY 4.0，DOI 为 `10.24432/C5VC8G`。它只用于证明
算法、训练进度、产物和测试链真实可复现，**不是港口、AGV或生产实绩**。

数据文件：`data/public/uci_appliances_energy.csv`

血缘文件：`data/public/uci_appliances_energy.provenance.json`

重新获取并验证：

```bash
.venv/bin/python scripts/fetch_public_rl_dataset.py
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
7. 查看五算法成本、峰值、约束违例和综合分数；
8. 复现门禁通过后，可人工确认归档本地 Dry-run 回执。

## API 操作

```text
GET  /api/rl-lab/health
GET  /api/rl-lab/algorithms
GET  /api/rl-lab/datasets
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

## 换成港口数据

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
