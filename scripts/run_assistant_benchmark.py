from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.assistant_evaluation import run_assistant_benchmark  # noqa: E402
from app.knowledge_api import get_knowledge_status  # noqa: E402


REPORT_JSON = ROOT / "reports" / "maritime_assistant_benchmark_v2.json"
REPORT_MARKDOWN = ROOT / "reports" / "maritime_assistant_benchmark_v2.md"
EVIDENCE_FILES = (
    "data/evaluation/maritime_assistant_benchmark_v2.json",
    "data/evaluation/maritime_qa_benchmark_v1.json",
    "data/xiaoyi_index.json",
    "data/source_registry.json",
    "data/authority_coverage.json",
    "app/query_intelligence.py",
    "app/answer_verification.py",
    "app/xiaoyi.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_atomic(path: Path, text: str) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _report_paths(output_tag: str | None) -> tuple[Path, Path]:
    if not output_tag:
        return REPORT_JSON, REPORT_MARKDOWN
    safe_tag = "".join(
        character for character in output_tag if character.isalnum() or character in {"-", "_"}
    )
    if not safe_tag:
        raise ValueError("output tag must contain a letter or number")
    return (
        ROOT / "reports" / f"maritime_assistant_benchmark_v2_{safe_tag}.json",
        ROOT / "reports" / f"maritime_assistant_benchmark_v2_{safe_tag}.md",
    )


def _markdown(report: dict[str, Any]) -> str:
    result = report["benchmark"]
    knowledge = report["knowledge_snapshot"]
    return f"""# 小懿AI 港航助手困难基准 v2

生成时间：{report["generated_at"]}

## 结果

- 当前知识快照：{knowledge["documents"]} 份文档、{knowledge["chunks"]} 个分块、{knowledge["official_documents"]} 份官方核验来源。
- v2 新增困难集：{result["case_count"]} 题；与 v1 合计 {result["combined_with_v1_case_count"]} 题。
- 多轮指代与上下文改写：{result["dialogue"]["summary"]["passed_count"]}/{result["dialogue"]["summary"]["case_count"]}，通过率 {_percent(result["dialogue"]["summary"]["pass_rate"])}。
- 复杂问题分解、部分回答与逐项引用：{result["complex"]["summary"]["passed_count"]}/{result["complex"]["summary"]["case_count"]}，通过率 {_percent(result["complex"]["summary"]["pass_rate"])}。
- 对抗性证据、安全与实时边界：{result["adversarial"]["summary"]["passed_count"]}/{result["adversarial"]["summary"]["case_count"]}，通过率 {_percent(result["adversarial"]["summary"]["pass_rate"])}。
- v2 发布门禁：{"PASS" if result["passed"] else "FAIL"}。

## 新增门禁

- 跨轮问题必须生成可审计的 `standalone_question`，新辖区或新日期替换旧范围，不能把历史上下文无限拼接。
- 多部分问题分别执行辖区、日期、官方全文与实时数据策略；允许“有证据的子结论回答、无证据的子结论拒答”。
- 有依据的事实陈述必须使用 `[E1]` 等有效证据编号；不存在、越界或定位型引用不能通过完整性门禁。
- 官方目录只用于定位，不能回答罚款、限值、具体条款、豁免或个案实时状态。

## 口径

{result["scope"]} v2 用例在开发中可见，不能表述为未见测试集或独立外部评测。`PASS` 只说明当前冻结代码、索引与数据通过这些确定性门禁。

## 证据哈希

```json
{json.dumps(report["evidence_sha256"], ensure_ascii=False, indent=2)}
```

## 复现

```bash
python scripts/run_assistant_benchmark.py verify
python scripts/run_assistant_benchmark.py run
```
"""


def run_and_persist(*, output_tag: str | None = None) -> int:
    benchmark = run_assistant_benchmark()
    status = get_knowledge_status()
    report = {
        "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).replace(
            microsecond=0
        ).isoformat(),
        "knowledge_snapshot": {
            "documents": status.document_count,
            "chunks": status.chunk_count,
            "official_documents": status.official_verified_documents,
            "official_full_text_documents": status.official_full_text_documents,
            "completeness_claim": status.completeness_claim,
        },
        "evidence_sha256": {
            relative: _sha256(ROOT / relative) for relative in EVIDENCE_FILES
        },
        "benchmark": benchmark,
    }
    report_json, report_markdown = _report_paths(output_tag)
    _write_atomic(
        report_json,
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    _write_atomic(report_markdown, _markdown(report))
    print(f"assistant benchmark: {'PASS' if benchmark['passed'] else 'FAIL'}")
    print(f"report: {report_json}")
    return 0 if benchmark["passed"] else 1


def verify(*, output_tag: str | None = None) -> int:
    try:
        report_json, _ = _report_paths(output_tag)
        report = json.loads(report_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: report unreadable: {exc}")
        return 1
    errors: list[str] = []
    if set(report.get("evidence_sha256", {})) != set(EVIDENCE_FILES):
        errors.append("evidence file inventory mismatch")
    for relative, expected in report.get("evidence_sha256", {}).items():
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing evidence file: {relative}")
        elif _sha256(path) != expected:
            errors.append(f"evidence hash changed: {relative}")
    if not report.get("benchmark", {}).get("passed"):
        errors.append("recorded benchmark gate is not PASS")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("assistant-benchmark verify: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("run", "verify"))
    parser.add_argument("--output-tag", help="append or verify a tagged immutable report")
    arguments = parser.parse_args()
    return (
        run_and_persist(output_tag=arguments.output_tag)
        if arguments.command == "run"
        else verify(output_tag=arguments.output_tag)
    )


if __name__ == "__main__":
    raise SystemExit(main())
