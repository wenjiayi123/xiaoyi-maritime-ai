# 小懿AI 港航检索与证据安全固定基准 v1

生成时间：2026-07-24T10:48:20+00:00

## 可复现结论

- 知识快照：112 份文档、708 个分块、60 份官方核验来源。
- 固定评测集：60 题，其中固定测试分区 35 题（检索 24、策略 11）。
- Hybrid Sparse Hit@5：100.00%；BM25-only Hit@5：100.00%；提升 0.00 个百分点。
- Hybrid Sparse MRR：0.9236；BM25-only MRR：0.8507；提升 7.29 个百分点。
- 官方来源要求通过率：100.00%。
- 官方查询 Top-5 来源纯度：100.00%；Top-5 证据双哈希完整率：100.00%。
- 显式本地辖区路由：7 题，准确率 100.00%；国际通用问题保持无本地辖区误路由的比例为 100.00%。
- 证据策略安全通过率：100.00%；无依据回答阻断率：100.00%。
- 辖区路由、日期适用性和实时数据边界通过率分别为 100.00%、100.00%、100.00%。
- 发布门禁：PASS。

## 对照与口径

Hybrid 与 BM25 使用同一知识快照、同一辖区/官方来源过滤、同一 Top-5 口径。`GLOBAL` 表示无需路由到单一国家，并不要求问题显式出现“全球”字样；本地辖区准确率仅统计 CN/SG/MY 显式路由题。测试分区用于 v1 发布验收，并在本版本工程修复中暴露过缺陷，因此不是未经查看的独立留出集。题目和标注由本仓库维护，不是第三方用户研究。

这些是固定仓库基准上的检索与证据治理指标，不是港口生产 KPI、业务收益、全球知识覆盖率、法律意见或线上 SLA。本地延迟仅用于诊断，不进入简历指标。

## 测试分区明细

- 检索测试：24 题；Hybrid Hit@1/3/5 = 87.50% / 100.00% / 100.00%。
- 策略测试：11 题；条款级拒答、官方入口、日期切换和实时数据边界分类结果均保存在同名 JSON 报告。

## 证据哈希

```json
{
  "data/evaluation/maritime_qa_benchmark_v1.json": "5126cb7734fb923034fba25c7cc30f52180116260812d065387335498e8aae15",
  "data/xiaoyi_index.json": "cbd2117cfbbc03cd21bc6d879a6bc918e4125a8121d07e779f4379b7dab3bb71",
  "data/source_registry.json": "07c5d46195f79e107cc781e12852e02bdb1b9e81ff8956f88648d4ebef14293d",
  "app/evaluation.py": "b4adfb65aa01e5c43801e3f3c601a179bcf67f2bf3abf72d3d7855cae86ede28",
  "app/retrieval.py": "3dbc3ffa5f17624faf5eb059ddf615a4cde9cddb9c27f4993b37b8ad6b237515",
  "app/knowledge_policy.py": "af8f07399d1f09ccba7d924253714fb8c3d88e87f14aff960ed9b9f8df94d1ee",
  "app/operator_assistant.py": "f8e26a8906dafb5e605fdcdf46cbb5402ab978a6bbc86eb4ec533ac2d9a7694d",
  "app/xiaoyi.py": "82663d85019a30ea9280657d10f751e6c7e79554dcc00a30bebe6025158d9f80"
}
```

## 复现

```bash
python scripts/run_rag_benchmark.py verify
python scripts/run_rag_benchmark.py verify --deep
python scripts/run_rag_benchmark.py run
```

`verify` 校验固定数据、索引、来源注册表和核心策略代码的 SHA-256；`verify --deep` 还会重新执行全部 60 题并比对确定性指标。完整离线复跑在普通单核环境可能需要数分钟。
