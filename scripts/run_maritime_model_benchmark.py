from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time
from typing import Any
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = (
    ROOT / "data" / "evaluation" / "maritime_question_universe_benchmark_v6.json"
)
DEFAULT_WORKFORCE_CASES = (
    ROOT / "data" / "evaluation" / "maritime_workforce_daily_benchmark_v1.json"
)
DEFAULT_OUTPUT = ROOT / "reports" / "maritime_model_benchmark_v7_baseline.json"
TRAINING_MODEL_ID = os.getenv(
    "XIAOYI_LORA_BASE_MODEL",
    str(ROOT / ".runtime" / "models" / "maritime-training-1.7b"),
)
TRAINING_MODEL_REVISION = os.getenv("XIAOYI_LORA_BASE_REVISION", "").strip() or None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 4)
    weight = position - lower
    return round(
        ordered[lower] * (1 - weight) + ordered[upper] * weight,
        4,
    )


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 4) if values else 0.0


def _mean_or_none(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _load_tokenizer() -> tuple[Any | None, str]:
    try:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            TRAINING_MODEL_ID,
            revision=TRAINING_MODEL_REVISION,
            local_files_only=True,
        )
        return tokenizer, "exact_training_architecture_tokenizer"
    except (ImportError, OSError, ValueError):
        return None, "unavailable"


def _token_count(tokenizer: Any | None, text: str) -> int | None:
    if tokenizer is None:
        return None
    return len(tokenizer.encode(text, add_special_tokens=False))


def _lexical_query_coverage(question: str, answer: str) -> float:
    ignored = set("的是了和与及或在把被对为有么吗呢啊请问如何什么哪些一下一个进行")
    question_units = {
        char.casefold()
        for char in question
        if (char.isalnum() or "\u4e00" <= char <= "\u9fff")
        and char.casefold() not in ignored
    }
    answer_units = {
        char.casefold()
        for char in answer
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    }
    if not question_units:
        return 1.0
    return round(len(question_units & answer_units) / len(question_units), 4)


def _consume_sse(
    endpoint: str,
    payload: dict[str, Any],
    *,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, float]]:
    started = time.perf_counter()
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-Xiaoyi-Trace-Id": f"benchmark-{payload['session_id']}",
        },
        method="POST",
    )
    first_token_at: float | None = None
    completed: dict[str, Any] | None = None
    event_name = "message"
    data_lines: list[str] = []

    def consume_event() -> None:
        nonlocal first_token_at, completed, event_name, data_lines
        if not data_lines:
            event_name = "message"
            return
        event_data = json.loads("\n".join(data_lines))
        if event_name == "token" and first_token_at is None:
            first_token_at = time.perf_counter()
        elif event_name == "done":
            completed = event_data
        event_name = "message"
        data_lines = []

    with urlopen(request, timeout=timeout) as response:
        headers_at = time.perf_counter()
        for raw_line in response:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if not line:
                consume_event()
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        consume_event()
    finished = time.perf_counter()
    if completed is None:
        raise RuntimeError("SSE stream did not return a done event")
    return completed, {
        "headers_seconds": round(headers_at - started, 4),
        "ttft_seconds": round((first_token_at or finished) - started, 4),
        "total_seconds": round(finished - started, 4),
    }


def _rank_metrics(evidence: list[dict[str, Any]], expected_source: str) -> dict[str, float]:
    rank = next(
        (
            index
            for index, item in enumerate(evidence[:10], start=1)
            if item.get("source") == expected_source
        ),
        None,
    )
    return {
        "recall_at_5": 1.0 if rank is not None and rank <= 5 else 0.0,
        "mrr_at_10": round(1.0 / rank, 4) if rank is not None else 0.0,
        "ndcg_at_10": (
            round(1.0 / math.log2(rank + 1), 4) if rank is not None else 0.0
        ),
    }


def _operational_row(
    case: dict[str, Any],
    response: dict[str, Any],
    timing: dict[str, float],
    tokenizer: Any | None,
) -> dict[str, Any]:
    answer = str(response.get("answer") or "")
    evidence = list(response.get("evidence") or [])
    required_terms = list(case.get("required_answer_terms") or [])
    matched_terms = [
        term for term in required_terms if term.casefold() in answer.casefold()
    ]
    rank_metrics = _rank_metrics(evidence, case["expected_source"])
    expected_evidence_count = sum(
        item.get("source") == case["expected_source"] for item in evidence
    )
    verification = dict(response.get("answer_verification") or {})
    output_tokens = _token_count(tokenizer, answer)
    decode_seconds = max(0.0001, timing["total_seconds"] - timing["ttft_seconds"])
    generated_tokens = max(0, (output_tokens or 1) - 1)
    measured_generation = response.get("generation_provider") == "openai_compatible"
    required_term_recall = (
        round(len(matched_terms) / len(required_terms), 4)
        if required_terms
        else None
    )
    response_relevancy = (
        required_term_recall
        if required_term_recall is not None
        else _lexical_query_coverage(case["question"], answer)
    )
    checks = {
        "grounded": bool(response.get("grounded")),
        "expected_source_retrieved": rank_metrics["recall_at_5"] == 1.0,
        "required_terms": len(matched_terms) == len(required_terms),
        "citation_verification": verification.get("status") == "passed",
    }
    return {
        "case_type": "operational",
        "id": case["id"],
        "domain": case["domain"],
        "question": case["question"],
        "answer": answer,
        "generation_provider": response.get("generation_provider"),
        "generation_model": response.get("generation_model"),
        "grounded": response.get("grounded"),
        "confidence": response.get("confidence"),
        "expected_source": case["expected_source"],
        "retrieved_sources": [item.get("source") for item in evidence],
        "required_terms": required_terms,
        "matched_terms": matched_terms,
        "required_term_recall": required_term_recall,
        "retrieval": rank_metrics,
        "ragas_aligned_deterministic_proxies": {
            "context_precision": round(
                expected_evidence_count / max(1, len(evidence)),
                4,
            ),
            "context_recall": rank_metrics["recall_at_5"],
            "response_relevancy": response_relevancy,
            "faithfulness": float(verification.get("evidence_alignment") or 0.0),
            "scope": (
                "Deterministic task-specific proxies aligned to RAGAS concepts; "
                "not RAGAS LLM-judge scores."
            ),
        },
        "answer_verification": verification,
        "latency": {
            **timing,
            "output_tokens": output_tokens,
            "tokens_per_second_after_first": (
                round(generated_tokens / decode_seconds, 4)
                if output_tokens is not None and measured_generation
                else None
            ),
            "tpot_seconds": (
                round(decode_seconds / generated_tokens, 4)
                if generated_tokens and measured_generation
                else None
            ),
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def _boundary_row(
    case: dict[str, Any],
    response: dict[str, Any],
    timing: dict[str, float],
) -> dict[str, Any]:
    answer = str(response.get("answer") or "")
    required_terms = list(case.get("required_answer_terms") or [])
    checks = {
        "not_grounded": not bool(response.get("grounded")),
        "refusal_reason": (
            response.get("refusal_reason") == case["expected_refusal_reason"]
        ),
        "required_terms": all(
            term.casefold() in answer.casefold() for term in required_terms
        ),
    }
    return {
        "case_type": "boundary",
        "id": case["id"],
        "question": case["question"],
        "answer": answer,
        "generation_provider": response.get("generation_provider"),
        "generation_model": response.get("generation_model"),
        "expected_refusal_reason": case["expected_refusal_reason"],
        "actual_refusal_reason": response.get("refusal_reason"),
        "latency": timing,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _workforce_row(
    case: dict[str, Any],
    response: dict[str, Any],
    timing: dict[str, float],
    tokenizer: Any | None,
) -> dict[str, Any]:
    answer = str(response.get("answer") or "")
    groups = dict(case.get("required_term_groups") or {})
    matched_groups = {
        group: [term for term in terms if term.casefold() in answer.casefold()]
        for group, terms in groups.items()
    }
    output_tokens = _token_count(tokenizer, answer)
    decode_seconds = max(0.0001, timing["total_seconds"] - timing["ttft_seconds"])
    generated_tokens = max(0, (output_tokens or 1) - 1)
    measured_generation = response.get("generation_provider") == "openai_compatible"
    checks = {
        "normal_response_first": bool(matched_groups.get("normal_response")),
        "maritime_work_impact": bool(matched_groups.get("maritime_impact")),
        "port_role_advice": bool(matched_groups.get("port_roles")),
        "answer_returned": bool(answer.strip()),
    }
    return {
        "case_type": "workforce_daily",
        "id": case["id"],
        "domain": "maritime_workforce_daily",
        "question": case["question"],
        "answer": answer,
        "generation_provider": response.get("generation_provider"),
        "generation_model": response.get("generation_model"),
        "grounded": response.get("grounded"),
        "required_term_groups": groups,
        "matched_term_groups": matched_groups,
        "group_coverage": round(
            sum(bool(values) for values in matched_groups.values())
            / max(1, len(matched_groups)),
            4,
        ),
        "latency": {
            **timing,
            "output_tokens": output_tokens,
            "tokens_per_second_after_first": (
                round(generated_tokens / decode_seconds, 4)
                if output_tokens is not None and measured_generation
                else None
            ),
            "tpot_seconds": (
                round(decode_seconds / generated_tokens, 4)
                if generated_tokens and measured_generation
                else None
            ),
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def _aggregate(rows: list[dict[str, Any]], tokenizer_status: str) -> dict[str, Any]:
    operational = [
        row for row in rows if row.get("case_type") == "operational"
    ]
    boundaries = [row for row in rows if row.get("case_type") == "boundary"]
    workforce = [
        row for row in rows if row.get("case_type") == "workforce_daily"
    ]
    ttft = [row["latency"]["ttft_seconds"] for row in rows]
    total = [row["latency"]["total_seconds"] for row in rows]
    tps = [
        row["latency"]["tokens_per_second_after_first"]
        for row in operational + workforce
        if row["latency"].get("tokens_per_second_after_first") is not None
    ]
    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in operational:
        by_domain[row["domain"]].append(row)
    by_provider: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_provider[str(row.get("generation_provider") or "unreported")].append(row)
    return {
        "case_count": len(rows),
        "operational_case_count": len(operational),
        "boundary_case_count": len(boundaries),
        "workforce_daily_case_count": len(workforce),
        "workforce_daily_passed_count": sum(row["passed"] for row in workforce),
        "workforce_daily_pass_rate": round(
            sum(row["passed"] for row in workforce) / max(1, len(workforce)),
            4,
        ),
        "workforce_daily_group_coverage": _mean(
            [row["group_coverage"] for row in workforce]
        ),
        "passed_count": sum(row["passed"] for row in rows),
        "pass_rate": round(
            sum(row["passed"] for row in rows) / max(1, len(rows)),
            4,
        ),
        "retrieval": {
            metric: _mean([row["retrieval"][metric] for row in operational])
            for metric in ("recall_at_5", "mrr_at_10", "ndcg_at_10")
        },
        "generation": {
            "required_term_recall": _mean_or_none(
                [
                    row["required_term_recall"]
                    for row in operational
                    if row["required_term_recall"] is not None
                ]
            ),
            "required_term_case_count": sum(
                row["required_term_recall"] is not None for row in operational
            ),
            "citation_verification_pass_rate": _mean(
                [
                    1.0
                    if row["checks"]["citation_verification"]
                    else 0.0
                    for row in operational
                ]
            ),
            "faithfulness_proxy": _mean(
                [
                    row["ragas_aligned_deterministic_proxies"]["faithfulness"]
                    for row in operational
                ]
            ),
            "response_relevancy_proxy": _mean(
                [
                    row["ragas_aligned_deterministic_proxies"]["response_relevancy"]
                    for row in operational
                ]
            ),
        },
        "latency": {
            "ttft_p50_seconds": _percentile(ttft, 0.5),
            "ttft_p95_seconds": _percentile(ttft, 0.95),
            "total_p50_seconds": _percentile(total, 0.5),
            "total_p95_seconds": _percentile(total, 0.95),
            "tokens_per_second_after_first_mean": _mean_or_none(tps),
            "tokenizer_status": tokenizer_status,
            "metric_scope": (
                "MLPerf-style single-stream TTFT, TPOT and output token rate; "
                "this is a local engineering benchmark, not an MLPerf submission."
            ),
        },
        "generation_provider_counts": dict(
            Counter(
                row.get("generation_provider")
                for row in rows
            )
        ),
        "latency_by_provider": {
            provider: {
                "case_count": len(provider_rows),
                "ttft_p50_seconds": _percentile(
                    [
                        row["latency"]["ttft_seconds"]
                        for row in provider_rows
                    ],
                    0.5,
                ),
                "ttft_p95_seconds": _percentile(
                    [
                        row["latency"]["ttft_seconds"]
                        for row in provider_rows
                    ],
                    0.95,
                ),
                "total_p50_seconds": _percentile(
                    [
                        row["latency"]["total_seconds"]
                        for row in provider_rows
                    ],
                    0.5,
                ),
            }
            for provider, provider_rows in sorted(by_provider.items())
        },
        "failed_ids": [row["id"] for row in rows if not row["passed"]],
        "domains": {
            domain: {
                "case_count": len(domain_rows),
                "passed_count": sum(row["passed"] for row in domain_rows),
                "required_term_recall": _mean_or_none(
                    [
                        row["required_term_recall"]
                        for row in domain_rows
                        if row["required_term_recall"] is not None
                    ]
                ),
            }
            for domain, domain_rows in sorted(by_domain.items())
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    benchmark = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = list(benchmark["cases"])
    if args.limit:
        cases = cases[: args.limit]
    tokenizer, tokenizer_status = _load_tokenizer()
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        response, timing = _consume_sse(
            args.endpoint,
            {
                "question": case["question"],
                "mode": "expert",
                "top_k": 8,
                "strict_evidence": True,
                "session_id": f"v7-{args.profile}-{case['id']}",
            },
            timeout=args.timeout,
        )
        row = _operational_row(case, response, timing, tokenizer)
        rows.append(row)
        print(
            f"[{index}/{len(cases)}] {case['id']}: "
            f"{'PASS' if row['passed'] else 'FAIL'} "
            f"ttft={timing['ttft_seconds']:.2f}s total={timing['total_seconds']:.2f}s",
            flush=True,
        )
    if args.include_boundaries:
        for case in benchmark.get("boundary_cases") or []:
            response, timing = _consume_sse(
                args.endpoint,
                {
                    "question": case["question"],
                    "mode": "expert",
                    "top_k": 8,
                    "strict_evidence": True,
                    "session_id": f"v7-{args.profile}-{case['id']}",
                },
                timeout=args.timeout,
            )
            rows.append(_boundary_row(case, response, timing))
    workforce_source_sha256 = None
    if args.include_workforce:
        workforce_benchmark = json.loads(
            args.workforce_cases.read_text(encoding="utf-8")
        )
        workforce_source_sha256 = _sha256(args.workforce_cases)
        for case in workforce_benchmark.get("cases") or []:
            response, timing = _consume_sse(
                args.endpoint,
                {
                    "question": case["question"],
                    "mode": "expert",
                    "top_k": 8,
                    "strict_evidence": True,
                    "session_id": f"v7-{args.profile}-{case['id']}",
                },
                timeout=args.timeout,
            )
            row = _workforce_row(case, response, timing, tokenizer)
            rows.append(row)
            print(
                f"[workforce] {case['id']}: "
                f"{'PASS' if row['passed'] else 'FAIL'} "
                f"ttft={timing['ttft_seconds']:.2f}s "
                f"total={timing['total_seconds']:.2f}s",
                flush=True,
            )
    report = {
        "schema_version": "1.0",
        "benchmark_id": "xiaoyi-maritime-model-benchmark-v7",
        "profile": args.profile,
        "generated_at": datetime.now(timezone.utc).replace(
            microsecond=0
        ).isoformat(),
        "endpoint": args.endpoint,
        "case_source": str(args.cases.relative_to(ROOT)),
        "case_source_sha256": _sha256(args.cases),
        "workforce_case_source": (
            str(args.workforce_cases.relative_to(ROOT))
            if args.include_workforce
            else None
        ),
        "workforce_case_source_sha256": workforce_source_sha256,
        "methodology": {
            "retrieval": "BEIR-aligned Recall@5, MRR@10 and nDCG@10 with repository qrels.",
            "generation": (
                "RAGAS-aligned deterministic proxies for context precision/recall, "
                "response relevancy and faithfulness, plus citation/numeric verifier."
            ),
            "latency": "MLPerf-style TTFT, TPOT, total latency and output tokens/s.",
            "limitations": [
                "Repository-authored fixed cases, not an independent blinded study by operational participants excluded from development.",
                "RAGAS-aligned deterministic proxies are not RAGAS LLM-judge scores.",
                "Single-user localhost measurements are not a concurrency SLA.",
            ],
        },
        "summary": _aggregate(rows, tokenizer_status),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Xiaoyi maritime end-to-end model benchmark."
    )
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:8010/api/chat/stream",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--profile", default="baseline-4b")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--include-boundaries", action="store_true")
    parser.add_argument("--include-workforce", action="store_true")
    parser.add_argument(
        "--workforce-cases",
        type=Path,
        default=DEFAULT_WORKFORCE_CASES,
    )
    arguments = parser.parse_args()
    report = run(arguments)
    summary = report["summary"]
    print(
        "maritime-model-benchmark: "
        f"{summary['passed_count']}/{summary['case_count']} "
        f"({summary['pass_rate'] * 100:.2f}%)"
    )
    print(f"report: {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
