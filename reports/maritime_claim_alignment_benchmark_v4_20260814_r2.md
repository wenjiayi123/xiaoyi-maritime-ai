# 小懿AI 主张—证据对齐固定基准 v4

生成时间：2026-08-13T23:43:43+00:00

## 结果

- 知识快照：129 份文档、882 个分块、68 份官方核验来源。
- v4：20 题；与 v1、v2、v3 合计 170 题。
- 引用编号与支持角色：6/6。
- 主张—证据词面对齐：6/6。
- 数字、日期与量值完整性：8/8。
- v4 总通过率：100.00%；发布门禁：PASS。

## 验证范围

- 阻断不存在、越界或 `locator_only` 的引用编号。
- 阻断“编号有效但证据主题与主张不对齐”的回答。
- 阻断证据未出现的百分比、日期、数量和带单位量值。
- 不同日期格式会先规范化再比对；一个主张可由多个明确引用共同支持。

## 口径

仓库维护、开发可见的确定性引用对齐基准；验证证据编号、支持型证据、主张词面对齐和数字日期量值完整性，不是外部盲测、语义蕴含证明、事实正确率、法律正确率或线上SLA。

## 证据哈希

```json
{
  "data/evaluation/maritime_claim_alignment_benchmark_v4.json": "c1c6955ecdd00b32fc4d7f1dddd72db7f6d453d6154338cf9f826d412868ac8f",
  "data/xiaoyi_index.json": "8139112712f6574bb20d80174f3286f2bbe2f6af479e181b38b01649eb67a63c",
  "data/source_registry.json": "3865b08a51756b70e97130ea39a75c86007535404b2f7ff7e6ef0d47f0469d32",
  "app/answer_verification.py": "dc5a500ae01068ad5e1ac5d9710d7c151f6973371e0c3cbcb02ac9610034d183",
  "app/alignment_evaluation.py": "7e3070ae5b4c7b992b4986bd8eb9524320c87acb533fa37ce796a37e57ea2441",
  "app/model_gateway.py": "cc540999594f469527d9923a2989398277b7c5849bef3bffbad48b851addf678",
  "app/models.py": "a04827ad14f7d2a72c2ce6665306e1ab3d5735434ede0545725c91e2b4c1f0e0",
  "app/xiaoyi.py": "9061ff33fabc13d5f0d532226d7ce472b58ccf2724b65b1ed0dbd505561df7a2"
}
```

## 复现

```bash
.venv/bin/python scripts/run_alignment_benchmark.py verify
.venv/bin/python scripts/run_alignment_benchmark.py run
```
