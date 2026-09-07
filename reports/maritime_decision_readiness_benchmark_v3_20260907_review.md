# 小懿AI 港航决策保障固定基准 v3

生成时间：2026-09-07T07:27:04+00:00

## 结果

- 知识快照：129 份文档、882 个分块、68 份官方核验来源。
- v3：30 题；与 v1、v2 合计 150 题。
- 真实问答链路的决策就绪与升级动作：11/14，通过率 78.57%。
- 合成冲突、新鲜度和失败关闭保障：16/16，通过率 100.00%。
- v3 完整性检查：FAIL。

## 验证范围

- `ready`、`ready_with_review`、`partial`、澄清、实时数据、官方全文、证据不足、证据冲突和沙箱边界。
- 同主题同辖区的强状态极性冲突、同一来源的版本/哈希分歧，以及复核到期或新鲜度未知。
- 阻断结果必须返回明确 blocker、风险级别和下一步动作。

## 口径

仓库维护、开发可见的确定性决策保障基准；验证决策就绪度、证据冲突、新鲜度和升级动作，不是外部盲测、生产安全认证、法律正确率或线上SLA。 冲突检测是保守的词面与元数据门禁，未检出冲突不等于事实或法律结论已被证明。

## 证据哈希

```json
{
  "data/evaluation/maritime_decision_readiness_benchmark_v3.json": "4ced28b3f04a858ee1b5ac3afbcc546d48c296464728fde572558f4e435d9b54",
  "data/xiaoyi_index.json": "8139112712f6574bb20d80174f3286f2bbe2f6af479e181b38b01649eb67a63c",
  "data/source_registry.json": "3865b08a51756b70e97130ea39a75c86007535404b2f7ff7e6ef0d47f0469d32",
  "app/decision_assurance.py": "beb3a28d0ab2fe6895ec1623c48d59a0971d7c79f982fd389ff16681ac631c30",
  "app/decision_evaluation.py": "a0a5b97c7c9b377dc1b89d3873110aaef91a710114e43897d90476021576ffac",
  "app/query_intelligence.py": "5b768556c56f3d2a457c672a8db933d71905449b942f3aa4d8ef1706828b1c33",
  "app/xiaoyi.py": "ba9253c3b95dbcc9fd10502ead6b972f61aefe204e172baf954ea05aa7fbd27e",
  "app/models.py": "fe07dd8a07232a69a927bd962faaec9a2910fc21eb46074287a7f5e9a5a4cd45"
}
```

## 复现

```bash
.venv/bin/python scripts/run_decision_benchmark.py verify
.venv/bin/python scripts/run_decision_benchmark.py run
```
