# 小懿AI 港口问题全集分层基准 v6

生成时间：2026-08-13T14:06:00+00:00

## 结果

- 当前知识快照：129 份文档、882 个分块、68 份官方核验来源。
- 15个业务域正式/日常固定题：24/30。
- 模糊、实时与官方全文边界：5/5。
- v1-v6 合计固定题：260 题；v6 发布门禁：FAIL。

## 分域结果

- commercial_legal: 2/2。
- container_terminal: 1/2。
- customs_documents: 2/2。
- energy_environment: 1/2。
- equipment_engineering: 2/2。
- intermodal: 0/2。
- live_operations: 2/2。
- people_management: 2/2。
- planning_kpi: 2/2。
- port_basics: 2/2。
- safety_security: 2/2。
- shipping: 2/2。
- smart_port_data: 1/2。
- special_cargo: 1/2。
- vessel_port_call: 2/2。

## 问题全集

- 15个业务域 × 26种问题形式 = 390个意图单元。
- 每个单元含正式/日常两种基准表达，共780条矩阵问法。
- 全量清单见 `docs/PORT_QUESTION_UNIVERSE.md`；固定基准是其中的分层样本，不把样本通过率表述为所有自由表达准确率。

## 口径

覆盖15个港航业务域的30题正式/日常分层固定集，并单列5题澄清、实时数据与官方全文边界；由本仓库维护且开发可见，不是第三方盲测、全部自由表达证明、现场验收或法律正确率。

## 证据哈希

```json
{
  "data/evaluation/port_question_universe_v1.json": "0d06a366f815af24e085279d2e947e8a72db6b7c49db1c15e74a2a8c48575c27",
  "data/evaluation/maritime_question_universe_benchmark_v6.json": "71ea3bb4166dceadefda1e9063a7c9c16db95f15f48c6950cc2158b95ab1bc39",
  "data/xiaoyi_index.json": "8139112712f6574bb20d80174f3286f2bbe2f6af479e181b38b01649eb67a63c",
  "data/source_registry.json": "3865b08a51756b70e97130ea39a75c86007535404b2f7ff7e6ef0d47f0469d32",
  "app/question_universe.py": "31ca34924610707633e0c6e309d1d752f5704c187621fbd98337d66a7fd70f00",
  "app/daily_query.py": "6ddbef85206a1e957e49c85e4d92d25e108468d9304fe9abd6c36cd7cf52de33",
  "app/knowledge_policy.py": "e61caef14b250dcd8e094c58fed558e7f4f5f961fb0144dc2e01f7150d3ef1d0",
  "app/xiaoyi.py": "234db55f3f774d9ae19ee6d2842fb18423484703a45229abb122f397efb81dd5"
}
```

## 复现

```bash
python scripts/build_port_question_universe.py
python scripts/run_question_universe_benchmark.py verify
python scripts/run_question_universe_benchmark.py run
```
