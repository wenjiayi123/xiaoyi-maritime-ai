from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation import run_benchmark  # noqa: E402


REPORT_JSON = ROOT / "reports" / "maritime_rag_benchmark_v1.json"
REPORT_MARKDOWN = ROOT / "reports" / "maritime_rag_benchmark_v1.md"
EVIDENCE_FILES = (
    "data/evaluation/maritime_qa_benchmark_v1.json",
    "data/xiaoyi_index.json",
    "data/source_registry.json",
    "app/evaluation.py",
    "app/retrieval.py",
    "app/knowledge_policy.py",
    "app/operator_assistant.py",
    "app/xiaoyi.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _deterministic_projection(benchmark: dict[str, Any]) -> dict[str, Any]:
    return {
        "benchmark_id": benchmark["benchmark_id"],
        "benchmark_sha256": benchmark["benchmark_sha256"],
        "top_k": benchmark["top_k"],
        "knowledge_snapshot": benchmark["knowledge_snapshot"],
        "retrieval_test": benchmark["retrieval"]["test"],
        "policy_test": benchmark["policy"]["test"],
        "resume_safe_metrics": benchmark["resume_safe_metrics"],
        "passed": benchmark["passed"],
    }


def _render_markdown(report: dict[str, Any]) -> str:
    benchmark = report["benchmark"]
    metrics = benchmark["resume_safe_metrics"]
    snapshot = benchmark["knowledge_snapshot"]
    retrieval = benchmark["retrieval"]["test"]
    policy = benchmark["policy"]["test"]
    hashes = report["evidence_sha256"]
    return f"""# 小懿AI 港航检索与证据安全固定基准 v1

生成时间：{report["generated_at"]}

## 可复现结论

- 知识快照：{snapshot["documents"]} 份文档、{snapshot["chunks"]} 个分块、{snapshot["official_documents"]} 份官方核验来源。
- 固定评测集：{metrics["fixed_case_count"]} 题，其中固定测试分区 {metrics["fixed_test_case_count"]} 题（检索 {metrics["test_retrieval_case_count"]}、策略 {metrics["test_policy_case_count"]}）。
- Hybrid Sparse Hit@5：{_percent(metrics["hybrid_hit_at_5"])}；BM25-only Hit@5：{_percent(metrics["bm25_hit_at_5"])}；提升 {metrics["hit_at_5_lift_percentage_points"]:.2f} 个百分点。
- Hybrid Sparse MRR：{metrics["hybrid_mrr"]:.4f}；BM25-only MRR：{metrics["bm25_mrr"]:.4f}；提升 {metrics["mrr_lift_percentage_points"]:.2f} 个百分点。
- 官方来源要求通过率：{_percent(metrics["official_requirement_pass_rate"])}。
- 官方查询 Top-5 来源纯度：{_percent(metrics["official_top_k_precision"])}；Top-5 证据双哈希完整率：{_percent(metrics["evidence_hash_completeness_rate"])}。
- 显式本地辖区路由：{metrics["retrieval_jurisdiction_routing_case_count"]} 题，准确率 {_percent(metrics["retrieval_jurisdiction_routing_accuracy"])}；国际通用问题保持无本地辖区误路由的比例为 {_percent(metrics["global_scope_neutrality_accuracy"])}。
- 证据策略安全通过率：{_percent(metrics["policy_safety_pass_rate"])}；无依据回答阻断率：{_percent(metrics["unsupported_answer_block_rate"])}。
- 辖区路由、日期适用性和实时数据边界通过率分别为 {_percent(metrics["jurisdiction_routing_accuracy"])}、{_percent(metrics["temporal_applicability_accuracy"])}、{_percent(metrics["live_data_boundary_pass_rate"])}。
- 发布门禁：{"PASS" if benchmark["passed"] else "FAIL"}。

## 对照与口径

Hybrid 与 BM25 使用同一知识快照、同一辖区/官方来源过滤、同一 Top-5 口径。`GLOBAL` 表示无需路由到单一国家，并不要求问题显式出现“全球”字样；本地辖区准确率仅统计 CN/SG/MY 显式路由题。测试分区用于 v1 发布验收，并在本版本工程修复中暴露过缺陷，因此不是未经查看的独立留出集。题目和标注由本仓库维护，不是第三方用户研究。

这些是固定仓库基准上的检索与证据治理指标，不是港口生产 KPI、业务收益、全球知识覆盖率、法律意见或线上 SLA。本地延迟仅用于诊断，不进入简历指标。

## 测试分区明细

- 检索测试：{retrieval["hybrid"]["case_count"]} 题；Hybrid Hit@1/3/5 = {_percent(retrieval["hybrid"]["hit_at_1"])} / {_percent(retrieval["hybrid"]["hit_at_3"])} / {_percent(retrieval["hybrid"]["hit_at_5"])}。
- 策略测试：{policy["case_count"]} 题；条款级拒答、官方入口、日期切换和实时数据边界分类结果均保存在同名 JSON 报告。

## 证据哈希

```json
{json.dumps(hashes, ensure_ascii=False, indent=2)}
```

## 复现

```bash
python scripts/run_rag_benchmark.py verify
python scripts/run_rag_benchmark.py verify --deep
python scripts/run_rag_benchmark.py run
```

`verify` 校验固定数据、索引、来源注册表和核心策略代码的 SHA-256；`verify --deep` 还会重新执行全部 60 题并比对确定性指标。完整离线复跑在普通单核环境可能需要数分钟。
"""


def run_and_persist() -> int:
    print("running 60-case RAG benchmark; this may take several minutes", flush=True)
    benchmark = run_benchmark(top_k=5)
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "evidence_sha256": {
            relative: _sha256(ROOT / relative) for relative in EVIDENCE_FILES
        },
        "benchmark": benchmark,
    }
    _write_text_atomic(
        REPORT_JSON,
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    _write_text_atomic(REPORT_MARKDOWN, _render_markdown(report))
    print(f"report: {REPORT_JSON}")
    print(f"markdown: {REPORT_MARKDOWN}")
    print(f"release_gate: {'PASS' if benchmark['passed'] else 'FAIL'}")
    return 0 if benchmark["passed"] else 1


def verify_report(*, deep: bool) -> int:
    errors: list[str] = []
    try:
        report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: report unreadable: {exc}")
        return 1
    for relative, expected in report.get("evidence_sha256", {}).items():
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing evidence file: {relative}")
        elif _sha256(path) != expected:
            errors.append(f"evidence hash changed: {relative}")
    expected_files = set(EVIDENCE_FILES)
    recorded_files = set(report.get("evidence_sha256", {}))
    if recorded_files != expected_files:
        errors.append("evidence file inventory does not match the verifier")
    benchmark = report.get("benchmark", {})
    if benchmark.get("benchmark_sha256") != _sha256(
        ROOT / "data/evaluation/maritime_qa_benchmark_v1.json"
    ):
        errors.append("benchmark hash does not match report")
    if deep and not errors:
        print("deep verification reruns all 60 cases", flush=True)
        current = run_benchmark(top_k=5)
        if _deterministic_projection(current) != _deterministic_projection(benchmark):
            errors.append("recomputed deterministic metrics differ from report")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"benchmark-report verify: PASS ({'deep' if deep else 'hash-only'})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run or verify the fixed Xiaoyi maritime RAG benchmark."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="run all cases and replace the report")
    verify = subparsers.add_parser("verify", help="verify report evidence hashes")
    verify.add_argument(
        "--deep",
        action="store_true",
        help="also rerun all cases and compare deterministic metrics",
    )
    arguments = parser.parse_args()
    if arguments.command == "run":
        return run_and_persist()
    return verify_report(deep=arguments.deep)


if __name__ == "__main__":
    raise SystemExit(main())
