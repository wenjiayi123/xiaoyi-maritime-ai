# 小懿AI 港航决策保障固定基准 v3

生成时间：2026-07-27T13:56:02+00:00

## 结果

- 知识快照：129 份文档、882 个分块、68 份官方核验来源。
- v3：30 题；与 v1、v2 合计 150 题。
- 真实问答链路的决策就绪与升级动作：14/14，通过率 100.00%。
- 合成冲突、新鲜度和失败关闭保障：16/16，通过率 100.00%。
- v3 发布门禁：PASS。

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
  "app/decision_assurance.py": "185959b0843c88a7d1baf1db81ce52b7980c7f869edb97bcda770e039862bf1c",
  "app/decision_evaluation.py": "2083daaae855ad24ee9c018616219b74f80918a1ce44ffa178183a61338db9eb",
  "app/query_intelligence.py": "5e9e8a476fb518bc08d3cd555177f9917f3b79f9a9d04c270368d252544a7006",
  "app/xiaoyi.py": "f6c48984190b73c57d12fcaec4259ea1c294e5882b86ca0fac18ee0b2dc88bae",
  "app/models.py": "b883002e50d1a787f7dc795d26a5a36bf1d1d0118ed8975eee1bb29f31dec453"
}
```

## 复现

```bash
.venv/bin/python scripts/run_decision_benchmark.py verify
.venv/bin/python scripts/run_decision_benchmark.py run
```
