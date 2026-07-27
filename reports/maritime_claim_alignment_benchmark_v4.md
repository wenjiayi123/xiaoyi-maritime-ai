# 小懿AI 主张—证据对齐固定基准 v4

生成时间：2026-07-27T13:55:59+00:00

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
  "app/answer_verification.py": "4c6ad61b3845d8c2bda76f8298b2d2c6eb91ddd36a4670770f35d00a482b2227",
  "app/alignment_evaluation.py": "7e3070ae5b4c7b992b4986bd8eb9524320c87acb533fa37ce796a37e57ea2441",
  "app/model_gateway.py": "d8897f7737077c916f6acc335fcf8017172fc14e8fc579deb73411f3d8d2ce00",
  "app/models.py": "b883002e50d1a787f7dc795d26a5a36bf1d1d0118ed8975eee1bb29f31dec453",
  "app/xiaoyi.py": "f6c48984190b73c57d12fcaec4259ea1c294e5882b86ca0fac18ee0b2dc88bae"
}
```

## 复现

```bash
.venv/bin/python scripts/run_alignment_benchmark.py verify
.venv/bin/python scripts/run_alignment_benchmark.py run
```
