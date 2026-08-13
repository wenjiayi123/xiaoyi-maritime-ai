# 小懿港口实时数据模拟与换源适配器

## 1. 当前交付是什么

小懿默认运行 `PortRealtimeSimulator`，通过 `port-realtime.v1` 产生 2 秒一帧的完整事件快照，再兼容映射到已有 `port-ops.v1` 页面、问答、任务和报告接口。它用于在没有现场端点时真实验收“数据进入—质量门禁—态势展示—约束建议—双人审批—模拟执行—审计—回滚”闭环。

页面和接口统一标注 **公开数据校准实时模拟**。公共 AIS 只用于校准交通变化包络，UCI 公共能源数据只验证时序接入与特征耦合；泊位、设备、堆场、闸口、能耗量级、天气潮汐和业务影响为带物理约束的工程模拟。它们不是上海港或其他港口实测，不是生产 KPI、财务实绩或核证减排。

## 2. 数据契约

权威契约为 [`data/contracts/port_realtime_telemetry_v1.json`](../data/contracts/port_realtime_telemetry_v1.json)，当前固定：

| 项目 | 当前实现 |
|---|---|
| 业务域 | 10 个：港口挂靠、AIS/VTS、泊位/海事服务、设备、堆场、闸口/集疏运、能源碳排、气象潮汐、安全维护、治理审计 |
| 规范字段 | 153 个必需字段；字段覆盖不等于 153 项独立观测 |
| 事件周期 | 2 秒；包含 `event_time`、`received_at`、`sequence`、`run_id`、`seed` |
| 场景 | 常态生产、集中到港、设备故障、需量高峰、大风低能见度 |
| 设备对象 | 18 台岸桥、96 台 AGV、54 台场桥，共 168 台 |
| 质量门禁 | 完整率、重复、乱序、新鲜度、物理约束、功率平衡、漂移 |
| 权限 | `physical_dispatch_allowed=false`、`production_authority=false` |

关键不变量包括 SOC 0–100%、非负流量/功率/库存、岸桥作业受风速门禁、设备状态决定可用能力、能源供需平衡、同一业务对象稳定主键和事件序列单调递增。场景不是把曲线整体乘系数：例如设备故障会减少工作岸桥并增加故障告警，风暴会触发岸桥停机并降低能见度，需量高峰会增加电网需量并生成 BESS 削峰建议。

## 3. 本地运行与可复验入口

```bash
XIAOYI_GENERATIVE_MODEL_ENABLED=false bash run.sh
```

```bash
curl -s http://127.0.0.1:8010/api/port-simulator/status
curl -s http://127.0.0.1:8010/api/port-simulator/contract
curl -s http://127.0.0.1:8010/api/port-simulator/snapshot
curl -N http://127.0.0.1:8010/api/port-simulator/stream
```

浏览器点击“数据分析 → 港口实时数据模拟与决策闭环”。可以切换五种场景、查看 10 域数据、打开数据契约与 SHA-256、分别点击“调度员审批”和“值班长复核”，再执行到模拟状态并回滚。

固定证据包由下列命令追加生成和复验：

```bash
python scripts/build_realtime_simulator_evidence.py generate
python scripts/build_realtime_simulator_evidence.py verify
```

报告保存在 `reports/port_realtime_simulator_evidence_v1_20260813.json/.md`，包含独立 `run_id`、契约/实现/公共数据哈希、五场景结果和单人审批阻断证据。生成新版本时必须新建报告文件或 run_id，不覆盖历史训练、模型、失败实验或旧报告。

## 4. 公开校准来源

| 来源 | 在本模拟器中的作用 | 不允许的解释 |
|---|---|---|
| NOAA / MarineCadastre 洛杉矶—长滩 AIS 公共切片，710 个独立分钟桶 | 校准船流时间变化和轨迹数据结构；文件、许可证、时间窗与 SHA-256 见契约和 provenance | 不代表上海港数据；不能把扩展的 2 秒帧数称为独立 AIS 实测量 |
| UCI Appliances Energy，19,735 行，CC BY 4.0 | 验证采样、时序特征和能源数据适配路径 | 非港口能源数据，不能校准港口真实功率、金额或碳量 |
| NOAA CO-OPS Data API 契约 | 定义未来可替换的水位、潮汐、风和气象字段及单位/时区要求 | 当前模拟值不是 API 实时返回 |
| DCSA Port Call 2.0 | 对齐港口挂靠、服务与时间戳语义 | 不表示已接入 DCSA 网络或任何码头 PCS |

所有来源的 URL、访问时间、许可证、字段映射和哈希均登记在契约中；生产环境仍须按实际授权和供应商条款复核。

## 5. 接入港口时只换数据源

现场适配器负责把 TOS、PCS、EMS、EAM、VTS/AIS、METOC、闸口/OCR、岸电和 BESS 数据转换为相同的 `port-realtime.v1` 对象。前端、规则、小懿分析、审批链与审计接口无需重写。

适配器必须同时保留：

- 源系统主键、规范主键、源字段名、映射版本和转换代码哈希；
- 事件时间、接收时间、时区、采样周期、迟到/乱序/重复语义；
- 单位、倍率、坐标系、枚举、质量码、空值和异常值处理；
- 数据所有者、许可证/授权、保留期、敏感等级和访问角色；
- 原始批次/消息哈希、清洗结果哈希和不可变审计关联 ID。

推荐接口仍可使用现有只读网关：

```bash
XIAOYI_PORT_DATA_MODE=live
XIAOYI_PORT_BASE_URL=https://port-integration.example.internal/api
XIAOYI_PORT_ALLOWED_HOSTS=port-integration.example.internal
```

`XIAOYI_PORT_ALLOWED_HOSTS` 必须精确列出网关主机。适配器只接受 HTTPS
（回环开发地址例外），拒绝 URL 内嵌凭据、非白名单主机、重定向和自由拼接路径；
只会访问下列固定只读资源，能源范围仅允许 `today`、`7d` 或 `30d`，响应上限
为 2 MB。

```text
GET /runtime/status
GET /runtime/snapshot
GET /operations/overview
GET /energy?range=today
GET /alerts?status=active&limit=100
```

`/runtime/status` 只有在站点清单、字段映射、质量、漂移、标定、时区和各自 SHA-256 均满足 [`port_site_admission_v1.json`](../data/contracts/port_site_admission_v1.json) 时，才允许返回 `data_mode=live` 和 `live_data_verified=true`。完整性、重复率、乱序率、物理约束、新鲜度或 PSI 任一失败都必须降级为不可信状态，不能沿用最近成功值伪装在线。

## 6. 生产权限边界

模拟器中的审批、执行和回滚只改变内存/本地模拟状态并写审计事件；它不调用 PLC、TOS、EMS、PCS 或 VTS 写接口。接入真实数据也不会继承模拟审批结果。

生产准入仍须完成七项门禁：现场字段映射、计量标定、漂移基线、只读影子运行、可信身份下的双人审批、回滚演练、OT/IT 安全隔离。全部完成前保持：

```text
recommendation_only=true
dispatch_allowed=false
physical_dispatch_allowed=false
production_authority=false
```

故障时按失败关闭处理：停止消费异常源、冻结新建议、显示最后可信时间和缺失字段、降级到人工 SOP；不得静默插值成“实时现场值”，也不得把模拟器自动切成生产源。
