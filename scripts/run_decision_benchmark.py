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

from app.decision_evaluation import run_decision_benchmark  # noqa: E402
from app.knowledge_api import get_knowledge_status  # noqa: E402


REPORT_JSON = ROOT / "reports" / "maritime_decision_readiness_benchmark_v3.json"
REPORT_MARKDOWN = ROOT / "reports" / "maritime_decision_readiness_benchmark_v3.md"
EVIDENCE_FILES = (
    "data/evaluation/maritime_decision_readiness_benchmark_v3.json",
    "data/xiaoyi_index.json",
    "data/source_registry.json",
    "app/decision_assurance.py",
    "app/decision_evaluation.py",
    "app/query_intelligence.py",
    "app/xiaoyi.py",
    "app/models.py",
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
        ROOT / "reports" / f"maritime_decision_readiness_benchmark_v3_{safe_tag}.json",
        ROOT / "reports" / f"maritime_decision_readiness_benchmark_v3_{safe_tag}.md",
    )


def _markdown(report: dict[str, Any]) -> str:
    result = report["benchmark"]
    snapshot = report["knowledge_snapshot"]
    return f"""# 小懿AI 港航决策保障固定基准 v3

生成时间：{report["generated_at"]}

## 结果

- 知识快照：{snapshot["documents"]} 份文档、{snapshot["chunks"]} 个分块、{snapshot["official_documents"]} 份官方核验来源。
- v3：{result["case_count"]} 题；与 v1、v2 合计 {result["combined_case_count"]} 题。
- 真实问答链路的决策就绪与升级动作：{result["query"]["summary"]["passed_count"]}/{result["query"]["summary"]["case_count"]}，通过率 {_percent(result["query"]["summary"]["pass_rate"])}。
- 合成冲突、新鲜度和失败关闭保障：{result["assurance"]["summary"]["passed_count"]}/{result["assurance"]["summary"]["case_count"]}，通过率 {_percent(result["assurance"]["summary"]["pass_rate"])}。
- v3 发布门禁：{"PASS" if result["passed"] else "FAIL"}。

## 验证范围

- `ready`、`ready_with_review`、`partial`、澄清、实时数据、官方全文、证据不足、证据冲突和沙箱边界。
- 同主题同辖区的强状态极性冲突、同一来源的版本/哈希分歧，以及复核到期或新鲜度未知。
- 阻断结果必须返回明确 blocker、风险级别和下一步动作。

## 口径

{result["scope"]} 冲突检测是保守的词面与元数据门禁，未检出冲突不等于事实或法律结论已被证明。

## 证据哈希

```json
{json.dumps(report["evidence_sha256"], ensure_ascii=False, indent=2)}
```

## 复现

```bash
.venv/bin/python scripts/run_decision_benchmark.py verify
.venv/bin/python scripts/run_decision_benchmark.py run
```
"""


def run_and_persist(*, output_tag: str | None = None) -> int:
    benchmark = run_decision_benchmark()
    status = get_knowledge_status()
    report = {
        "schema_version": "3.0",
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
    print(f"decision benchmark: {'PASS' if benchmark['passed'] else 'FAIL'}")
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
    print("decision-benchmark verify: PASS")
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
