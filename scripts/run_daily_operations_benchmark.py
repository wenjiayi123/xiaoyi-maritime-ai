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

from app.daily_evaluation import run_daily_operations_benchmark  # noqa: E402
from app.knowledge_api import get_knowledge_status  # noqa: E402


REPORT_JSON = ROOT / "reports" / "maritime_daily_operations_benchmark_v5.json"
REPORT_MARKDOWN = ROOT / "reports" / "maritime_daily_operations_benchmark_v5.md"
EVIDENCE_FILES = (
    "data/evaluation/maritime_daily_operations_benchmark_v5.json",
    "data/xiaoyi_index.json",
    "data/source_registry.json",
    "app/daily_query.py",
    "app/operator_assistant.py",
    "app/answer_verification.py",
    "app/xiaoyi.py",
    "tests/test_daily_query_intelligence.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_atomic(path: Path, text: str) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _markdown(report: dict[str, Any]) -> str:
    result = report["benchmark"]
    knowledge = report["knowledge_snapshot"]
    category_lines = "\n".join(
        f"- {category}: {summary['passed_count']}/{summary['case_count']}，"
        f"通过率 {_percent(summary['pass_rate'])}。"
        for category, summary in result["categories"].items()
    )
    return f"""# 小懿AI 港口日常问答固定基准 v5

生成时间：{report["generated_at"]}

## 结果

- 当前知识快照：{knowledge["documents"]} 份文档、{knowledge["chunks"]} 个分块、{knowledge["official_documents"]} 份官方核验来源。
- 日常运营问答：{result["operational"]["summary"]["passed_count"]}/{result["operational_case_count"]}。
- 模糊问题与实时数据边界：{result["boundary"]["summary"]["passed_count"]}/{result["boundary_case_count"]}。
- 与 v1-v4 合计固定题：{result["combined_fixed_case_count"]} 题；v5 发布门禁：{"PASS" if result["passed"] else "FAIL"}。

## 六类覆盖

{category_lines}

## 口径

{result["scope"]} 其中60题计入固定能力基准，3题边界用例单列，不用额外叠加题量。

## 证据哈希

```json
{json.dumps(report["evidence_sha256"], ensure_ascii=False, indent=2)}
```

## 复现

```bash
python scripts/run_daily_operations_benchmark.py verify
python scripts/run_daily_operations_benchmark.py run
```
"""


def run_and_persist() -> int:
    benchmark = run_daily_operations_benchmark()
    status = get_knowledge_status()
    report = {
        "schema_version": "1.0",
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
    _write_atomic(
        REPORT_JSON,
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    _write_atomic(REPORT_MARKDOWN, _markdown(report))
    print(f"daily operations benchmark: {'PASS' if benchmark['passed'] else 'FAIL'}")
    print(f"report: {REPORT_JSON}")
    return 0 if benchmark["passed"] else 1


def verify() -> int:
    try:
        report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
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
    benchmark = report.get("benchmark", {})
    if benchmark.get("operational_case_count") != 60:
        errors.append("daily operational case count is not 60")
    if benchmark.get("boundary_case_count") != 3:
        errors.append("daily boundary case count is not 3")
    if benchmark.get("combined_fixed_case_count") != 230:
        errors.append("v1-v5 combined fixed case count is not 230")
    if not benchmark.get("passed"):
        errors.append("recorded daily benchmark gate is not PASS")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("daily-operations-benchmark verify: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("run", "verify"))
    arguments = parser.parse_args()
    return run_and_persist() if arguments.command == "run" else verify()


if __name__ == "__main__":
    raise SystemExit(main())
