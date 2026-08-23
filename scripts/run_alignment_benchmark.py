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

from app.alignment_evaluation import run_alignment_benchmark  # noqa: E402
from app.knowledge_api import get_knowledge_status  # noqa: E402


REPORT_JSON = ROOT / "reports" / "maritime_claim_alignment_benchmark_v4.json"
REPORT_MARKDOWN = ROOT / "reports" / "maritime_claim_alignment_benchmark_v4.md"
EVIDENCE_FILES = (
    "data/evaluation/maritime_claim_alignment_benchmark_v4.json",
    "data/xiaoyi_index.json",
    "data/source_registry.json",
    "app/answer_verification.py",
    "app/alignment_evaluation.py",
    "app/model_gateway.py",
    "app/models.py",
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
        ROOT / "reports" / f"maritime_claim_alignment_benchmark_v4_{safe_tag}.json",
        ROOT / "reports" / f"maritime_claim_alignment_benchmark_v4_{safe_tag}.md",
    )


def _markdown(report: dict[str, Any]) -> str:
    result = report["benchmark"]
    snapshot = report["knowledge_snapshot"]
    categories = result["categories"]
    return f"""# 小懿AI 主张—证据对齐固定基准 v4

生成时间：{report["generated_at"]}

## 结果

- 知识快照：{snapshot["documents"]} 份文档、{snapshot["chunks"]} 个分块、{snapshot["official_documents"]} 份官方核验来源。
- v4：{result["case_count"]} 题；与 v1、v2、v3 合计 {result["combined_case_count"]} 题。
- 引用编号与支持角色：{categories["citation"]["summary"]["passed_count"]}/{categories["citation"]["summary"]["case_count"]}。
- 主张—证据词面对齐：{categories["alignment"]["summary"]["passed_count"]}/{categories["alignment"]["summary"]["case_count"]}。
- 数字、日期与量值完整性：{categories["numeric"]["summary"]["passed_count"]}/{categories["numeric"]["summary"]["case_count"]}。
- v4 总通过率：{_percent(result["overall"]["pass_rate"])}；完整性检查：{"PASS" if result["passed"] else "FAIL"}。

## 验证范围

- 阻断不存在、越界或 `locator_only` 的引用编号。
- 阻断“编号有效但证据主题与主张不对齐”的回答。
- 阻断证据未出现的百分比、日期、数量和带单位量值。
- 不同日期格式会先规范化再比对；一个主张可由多个明确引用共同支持。

## 口径

{result["scope"]}

## 证据哈希

```json
{json.dumps(report["evidence_sha256"], ensure_ascii=False, indent=2)}
```

## 复现

```bash
.venv/bin/python scripts/run_alignment_benchmark.py verify
.venv/bin/python scripts/run_alignment_benchmark.py run
```
"""


def run_and_persist(*, output_tag: str | None = None) -> int:
    benchmark = run_alignment_benchmark()
    status = get_knowledge_status()
    report = {
        "schema_version": "4.0",
        "generated_at": datetime.now(timezone.utc).replace(
            microsecond=0
        ).isoformat(),
        "knowledge_snapshot": {
            "documents": status.document_count,
            "chunks": status.chunk_count,
            "official_documents": status.official_verified_documents,
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
    print(f"alignment benchmark: {'PASS' if benchmark['passed'] else 'FAIL'}")
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
    benchmark = report.get("benchmark", {})
    if benchmark.get("case_count") != 20:
        errors.append("v4 fixed case count is not 20")
    if benchmark.get("combined_case_count") != 170:
        errors.append("combined v1-v4 case count is not 170")
    if not benchmark.get("passed"):
        errors.append("recorded benchmark gate is not PASS")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("alignment-benchmark verify: PASS")
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
