# 小懿智能联动中心

## 设计边界

小懿是港航知识与智能编排入口，不重复建设其他系统已经闭环的功能。内部兼容模式值默认为 `demo`，网页统一显示为 `ISOLATED / 隔离预览`：只读取本地能力清单、生成调用预览和原系统跳转，不会访问、启动或改变能碳驾驶舱、数字孪生平台、马六甲沙盘或航行模拟器。

切换为 `live` 也只开放登记为 `GET` 的只读能力。小懿没有内部系统写操作端点。

## 七项能力

1. 系统能力注册：四个系统、只读能力契约、健康地址与原系统入口。
2. 统一业务上下文：港口、码头、IMO、MMSI、挂靠、泊位、设备、场景、策略和时间范围。
3. 多源证据融合：知识证据、系统结果、推演结果和调用契约分层展示。
4. RAG 2.0：BM25式词项相关度、稀疏语义相似度、覆盖度、来源质量和二次排序。
5. 自然语言编排：问题理解、上下文、知识检索、能力选择、安全预览和原系统交接。
6. 权限与持久审计：角色权限、调用请求/响应哈希、关联ID和SQLite审计。
7. 评测与反馈闭环：固定问答回归、Hit@K、官方来源要求、反馈审核和知识待审核区。

## 网页验证

1. 启动小懿并打开 `http://127.0.0.1:8010/?hub=1`。
2. 点击左侧“智能联动中心”。
3. 确认顶部显示 `7 / 7 READY`。
4. 查看四个系统及能力数量，确认状态为 `ISOLATED` 和“隔离预览”。
5. 保留默认问题，点击“开始编排”。
6. 查看港口、泊位、时间范围识别结果、编排步骤、证据数量和原系统跳转。
7. 点击“重新评测”查看固定评测结果。
8. 选择评分、修改修订建议并点击“提交待审核”。

## API验证

### 1. 系统能力注册

```bash
curl -s http://127.0.0.1:8010/api/hub/systems | python3 -m json.tool
curl -s http://127.0.0.1:8010/api/hub/capabilities | python3 -m json.tool
```

### 2. 统一业务上下文

```bash
curl -s -X POST http://127.0.0.1:8010/api/context/resolve \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"verify-ctx","question":"分析 CNYTN 泊位 3 未来3小时岸电风险"}' \
  | python3 -m json.tool
```

再次使用同一 `session_id` 提问“再看一下设备情况”，可以看到港口和泊位上下文被继承。

### 3. 多源证据融合

```bash
curl -s -X POST http://127.0.0.1:8010/api/evidence/fuse \
  -H 'Content-Type: application/json' \
  -d '{"query":"岸电安全操作规程","external_evidence":[{"source_type":"capability_contract","source_id":"verify-preview","system_id":"energy-cockpit","capability_id":"energy_linkage_health","title":"能碳联动预览","payload":{"status":"preview"},"verification_status":"preview_only"}]}' \
  | python3 -m json.tool
```

### 4. RAG 2.0

```bash
curl -s -X POST http://127.0.0.1:8010/api/knowledge/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"IMO 海事单一窗口 2024","official_only":true,"top_k":5}' \
  | python3 -m json.tool
```

检查 `lexical_score`、`semantic_score`、`rerank_score` 和 `retrieval_method`。

### 5. 跨系统编排

```bash
curl -s -X POST http://127.0.0.1:8010/api/orchestrator/run \
  -H 'Content-Type: application/json' \
  -d '{"command":"分析 CNYTN 泊位 3 未来3小时岸电风险，并告诉我去哪个系统看详情","session_id":"verify-orchestrator","execute_read_only":false}' \
  | python3 -m json.tool
```

检查 `selected_capabilities`、`steps`、`evidence_summary`、`handoff_links` 和 `execution_boundary`。

### 6. 权限与持久审计

```bash
curl -s -X POST http://127.0.0.1:8010/api/governance/authorize \
  -H 'Content-Type: application/json' \
  -d '{"actor_id":"viewer-01","role":"viewer","permission":"capability.invoke_read"}' \
  | python3 -m json.tool

curl -s http://127.0.0.1:8010/api/governance/audit | python3 -m json.tool
```

### 7. 评测与反馈闭环

```bash
curl -s -X POST http://127.0.0.1:8010/api/evaluation/run \
  -H 'Content-Type: application/json' -d '{"top_k":8}' | python3 -m json.tool

curl -s -X POST http://127.0.0.1:8010/api/evaluation/feedback \
  -H 'Content-Type: application/json' \
  -d '{"question":"岸电告警怎么处理？","rating":2,"correction":"应先确认告警来源、时间和适用设备，再按现场SOP处置。","submitted_by":"verify-user"}' \
  | python3 -m json.tool
```

反馈默认 `pending_review`，不会直接进入正式索引。管理员调用审核接口批准后，内容只会进入 `kb_pending` 待审核区，仍需正式知识治理流程才能索引。
