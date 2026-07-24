# 小懿港口运营数据适配器

## 1. 目标

小懿的页面、问答、任务和报告统一读取 `PortOperationsDataSource`。默认实现 `SandboxPortDataSource`，用于生成可重复、随时间变化的港口运营沙箱事件；生产实现 `HttpPortDataSource`，只读访问站点集成网关。两者共用 `port-ops.v1`，因此生产切换不需要改前端和业务问答代码。

沙箱数据不是生产实绩。所有响应必须同时提供 `data_mode`、`source_system`、`observed_at`、`generated_at`、`quality_code`、`quality_score`、`latency_ms`、`schema_version`、`live_data_verified` 和 `write_enabled`。

## 2. 默认沙箱

```bash
export XIAOYI_PORT_DATA_MODE=operations_sandbox
bash run.sh
```

沙箱每五分钟进入新的事件桶，动态生成船舶挂靠、泊位作业、岸桥、AGV、场桥、堆场、闸口、能耗和告警。相同事件桶可重复，便于测试与面试展示；跨事件桶数值变化，便于验证刷新链路。

## 3. 生产切换

```bash
export XIAOYI_PORT_DATA_MODE=live
export XIAOYI_PORT_BASE_URL=https://port-integration.example.internal/api
export XIAOYI_PORT_API_TOKEN='read-only-token'
export XIAOYI_PORT_TIMEOUT_SECONDS=5
bash run.sh
```

生产网关需要提供：

| 网关资源 | 用途 |
| --- | --- |
| `GET /runtime/status` | 来源、观测时间、质量和版本校验 |
| `GET /operations/overview` | 在港船舶、累计吞吐、岸桥与 AGV 指标 |
| `GET /energy?range=today` | 能耗摘要、时序和洞察 |
| `GET /alerts?status=active&limit=100` | 活动告警与处置建议 |
| `GET /runtime/snapshot` | 船舶挂靠、设备、堆场和闸口业务对象 |

`/runtime/status` 必须返回 `data_mode=live`、`live_data_verified=true`、`schema_version=port-ops.v1`。任一条件不满足，适配器拒绝把数据标记为生产实绩。小懿的生产适配器只调用 GET；写操作由独立连接器门禁、单次人工确认和现场权限控制。

## 4. 站点字段映射

生产网关负责把现场 TOS、PCS、EMS、EAM、VTS/AIS 和闸口系统字段映射为统一业务对象。建议保留原系统主键、事件时间、接收时间、站点字段名、转换版本和质量码，避免只保留页面展示值。船名不能作为唯一键，船舶优先使用 IMO 编号；箱、设备、泊位和航次也必须保留稳定标识。

## 5. 验证

```bash
curl http://127.0.0.1:8010/api/runtime/status
curl http://127.0.0.1:8010/api/runtime/snapshot
curl http://127.0.0.1:8010/api/dashboard
```

前端点击“运营沙箱/生产数据”标签，可核对适配器、来源系统、港区代码、质量码、延迟、观测时间和真实性声明。
