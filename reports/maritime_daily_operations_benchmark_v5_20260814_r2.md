# 小懿AI 港口日常问答固定基准 v5

生成时间：2026-08-13T23:43:53+00:00

## 结果

- 当前知识快照：129 份文档、882 个分块、68 份官方核验来源。
- 日常运营问答：60/60。
- 模糊问题与实时数据边界：3/3。
- 与 v1-v4 合计固定题：230 题；v5 发布门禁：PASS。

## 六类覆盖

- documents: 10/10，通过率 100.00%。
- energy: 10/10，通过率 100.00%。
- equipment: 10/10，通过率 100.00%。
- shift_coordination: 10/10，通过率 100.00%。
- vessel_berth: 10/10，通过率 100.00%。
- yard_gate: 10/10，通过率 100.00%。

## 口径

仓库维护的60题港口日常问答固定集，覆盖能源、船舶泊位、堆场闸口、班组协同、单证和设备六类高频场景；不是第三方盲测、全部港口流程证明、现场生产效果或法律正确率。 其中60题计入固定能力基准，3题边界用例单列，不用额外叠加题量。

## 证据哈希

```json
{
  "data/evaluation/maritime_daily_operations_benchmark_v5.json": "76f4365c9387b2c8c9f3c2bf9f93c985d59ef0237b9e8bbf604f661628c8a56f",
  "data/xiaoyi_index.json": "8139112712f6574bb20d80174f3286f2bbe2f6af479e181b38b01649eb67a63c",
  "data/source_registry.json": "3865b08a51756b70e97130ea39a75c86007535404b2f7ff7e6ef0d47f0469d32",
  "app/daily_query.py": "4af1d5b4a2c0995084d692c33c2920d85f7998fca92564a8e029c97798083bc7",
  "app/operator_assistant.py": "64baf6e2039a3a21a27417d4a4db51122880fd8e05dc0aeb44c4a22f76aaeebe",
  "app/answer_verification.py": "dc5a500ae01068ad5e1ac5d9710d7c151f6973371e0c3cbcb02ac9610034d183",
  "app/xiaoyi.py": "9061ff33fabc13d5f0d532226d7ce472b58ccf2724b65b1ed0dbd505561df7a2",
  "tests/test_daily_query_intelligence.py": "40b4208ecf0c0f47056ba5fece6e438967f274491fb64a99d460b67d972f42ec"
}
```

## 复现

```bash
python scripts/run_daily_operations_benchmark.py verify
python scripts/run_daily_operations_benchmark.py run
```
