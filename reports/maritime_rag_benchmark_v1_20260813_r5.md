# 小懿AI 港航检索与证据安全固定基准 v1

生成时间：2026-08-13T14:48:53+00:00

## 可复现结论

- 知识快照：129 份文档、882 个分块、68 份官方核验来源。
- 固定评测集：60 题，其中固定测试分区 35 题（检索 24、策略 11）。
- Hybrid Sparse Hit@5：100.00%；BM25-only Hit@5：95.83%；提升 4.17 个百分点。
- Hybrid Sparse MRR：1.0000；BM25-only MRR：0.9583；提升 4.17 个百分点。
- 官方来源要求通过率：100.00%。
- 官方查询 Top-5 来源纯度：100.00%；Top-5 证据双哈希完整率：100.00%。
- 显式本地辖区路由：7 题，准确率 100.00%；国际通用问题保持无本地辖区误路由的比例为 100.00%。
- 证据策略安全通过率：100.00%；无依据回答阻断率：100.00%。
- 辖区路由、日期适用性和实时数据边界通过率分别为 100.00%、100.00%、100.00%。
- 发布门禁：PASS。

## 对照与口径

Hybrid 与 BM25 使用同一知识快照、同一辖区/官方来源过滤、同一 Top-5 口径。`GLOBAL` 表示无需路由到单一国家，并不要求问题显式出现“全球”字样；本地辖区准确率仅统计 CN/SG/MY 显式路由题。测试分区用于 v1 发布验收，并在本版本工程修复中暴露过缺陷，因此不是未经查看的独立留出集。题目和标注由本仓库维护，不是第三方用户研究。

这些是固定仓库基准上的检索与证据治理指标，不是港口生产 KPI、业务收益、全球知识覆盖率、法律意见或线上 SLA。本地延迟仅用于诊断，不进入发布指标。

## 测试分区明细

- 检索测试：24 题；Hybrid Hit@1/3/5 = 100.00% / 100.00% / 100.00%。
- 策略测试：11 题；条款级拒答、官方入口、日期切换和实时数据边界分类结果均保存在同名 JSON 报告。

## 证据哈希

```json
{
  "data/evaluation/maritime_qa_benchmark_v1.json": "5126cb7734fb923034fba25c7cc30f52180116260812d065387335498e8aae15",
  "data/xiaoyi_index.json": "8139112712f6574bb20d80174f3286f2bbe2f6af479e181b38b01649eb67a63c",
  "data/source_registry.json": "3865b08a51756b70e97130ea39a75c86007535404b2f7ff7e6ef0d47f0469d32",
  "app/evaluation.py": "922cbecd7c578adbdd157ba4ed7eb3fa0a57a210ff430ae78c878dc0582aa292",
  "app/retrieval.py": "982dee23ce784751dbf06271c0cdbc475e01cd35df65b64fd96f699619b2a962",
  "app/knowledge_policy.py": "e61caef14b250dcd8e094c58fed558e7f4f5f961fb0144dc2e01f7150d3ef1d0",
  "app/operator_assistant.py": "e0fc02ccab83a86f5ae7379b62a379f244529dc273b9ca200a01d64fd0786880",
  "app/xiaoyi.py": "f0fc0ba470dfee0acda24a21251b688c52fbac799b35328448d6a7ed6159385d"
}
```

## 复现

```bash
python scripts/run_rag_benchmark.py verify
python scripts/run_rag_benchmark.py verify --deep
python scripts/run_rag_benchmark.py run
```

`verify` 校验固定数据、索引、来源注册表和核心策略代码的 SHA-256；`verify --deep` 还会重新执行全部 60 题并比对确定性指标。完整离线复跑在普通单核环境可能需要数分钟。
