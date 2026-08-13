# 小懿AI 港航助手困难基准 v2

生成时间：2026-08-13T15:52:51+00:00

## 结果

- 当前知识快照：129 份文档、882 个分块、68 份官方核验来源。
- v2 新增困难集：60 题；与 v1 合计 120 题。
- 多轮指代与上下文改写：20/20，通过率 100.00%。
- 复杂问题分解、部分回答与逐项引用：20/20，通过率 100.00%。
- 对抗性证据、安全与实时边界：20/20，通过率 100.00%。
- v2 发布门禁：PASS。

## 新增门禁

- 跨轮问题必须生成可审计的 `standalone_question`，新辖区或新日期替换旧范围，不能把历史上下文无限拼接。
- 多部分问题分别执行辖区、日期、官方全文与实时数据策略；允许“有证据的子结论回答、无证据的子结论拒答”。
- 有依据的事实陈述必须使用 `[E1]` 等有效证据编号；不存在、越界或定位型引用不能通过完整性门禁。
- 官方目录只用于定位，不能回答罚款、限值、具体条款、豁免或个案实时状态。

## 口径

仓库维护的确定性困难集，验证跨轮改写、复杂问题分治、证据引用和安全拒答；不是第三方盲测、用户研究、线上SLA或法律正确率。 v2 用例在开发中可见，不能表述为未见测试集或独立外部评测。`PASS` 只说明当前冻结代码、索引与数据通过这些确定性门禁。

## 证据哈希

```json
{
  "data/evaluation/maritime_assistant_benchmark_v2.json": "8ce1cc805786fd6221d1e6ba8183422bb9ade6579384543de2d7f226da5a13bd",
  "data/evaluation/maritime_qa_benchmark_v1.json": "5126cb7734fb923034fba25c7cc30f52180116260812d065387335498e8aae15",
  "data/xiaoyi_index.json": "8139112712f6574bb20d80174f3286f2bbe2f6af479e181b38b01649eb67a63c",
  "data/source_registry.json": "3865b08a51756b70e97130ea39a75c86007535404b2f7ff7e6ef0d47f0469d32",
  "data/authority_coverage.json": "306cb844b84ea91a9d1fc78a17d26b26fed201f95e4314a81c767a0e6890c12f",
  "app/query_intelligence.py": "5e9e8a476fb518bc08d3cd555177f9917f3b79f9a9d04c270368d252544a7006",
  "app/answer_verification.py": "dc5a500ae01068ad5e1ac5d9710d7c151f6973371e0c3cbcb02ac9610034d183",
  "app/xiaoyi.py": "9061ff33fabc13d5f0d532226d7ce472b58ccf2724b65b1ed0dbd505561df7a2"
}
```

## 复现

```bash
python scripts/run_assistant_benchmark.py verify
python scripts/run_assistant_benchmark.py run
```
