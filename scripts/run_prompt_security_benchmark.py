from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/evaluation/prompt_injection_benchmark_v1.json"
CODE = ROOT / "app/prompt_security.py"
REPORT = ROOT / "reports/prompt_injection_benchmark_v1_20260813.json"
MARKDOWN = ROOT / "reports/prompt_injection_benchmark_v1_20260813.md"

sys.path.insert(0, str(ROOT))

from app.prompt_security import detect_prompt_injection, isolate_untrusted_text  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate() -> dict[str, Any]:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    tp = fp = tn = fn = isolated_attacks = 0
    for case in dataset["cases"]:
        original = str(case["text"])
        expected = bool(case["expected_injection"])
        detections = detect_prompt_injection(original)
        isolation = isolate_untrusted_text(original)
        predicted = bool(detections)
        tp += int(expected and predicted)
        fp += int(not expected and predicted)
        tn += int(not expected and not predicted)
        fn += int(expected and not predicted)
        isolated_attacks += int(expected and isolation.isolated and "ISOLATED_UNTRUSTED_INSTRUCTION" in isolation.text)
        results.append(
            {
                "case_id": case["id"],
                "expected_injection": expected,
                "predicted_injection": predicted,
                "detections": list(detections),
                "isolated": isolation.isolated,
                "source_record_unchanged": original == case["text"],
                "passed": predicted == expected and (not expected or isolation.isolated),
            }
        )
    positives = tp + fn
    negatives = tn + fp
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / positives if positives else 0.0
    metrics = {
        "case_count": len(results),
        "attack_case_count": positives,
        "benign_case_count": negatives,
        "true_positive": tp,
        "false_positive": fp,
        "true_negative": tn,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "benign_specificity": tn / negatives if negatives else 0.0,
        "attack_isolation_rate": isolated_attacks / positives if positives else 0.0,
    }
    dataset_hash = _sha256(DATASET)
    code_hash = _sha256(CODE)
    run_id = f"promptsec-20260813-{hashlib.sha256(f'{dataset_hash}:{code_hash}'.encode()).hexdigest()[:12]}"
    passed = all(item["passed"] for item in results) and all(
        metrics[field] == 1.0
        for field in ("precision", "recall", "benign_specificity", "attack_isolation_rate")
    )
    return {
        "run_id": run_id,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_id": dataset["benchmark_id"],
        "scope": dataset["scope"],
        "evidence_sha256": {
            str(DATASET.relative_to(ROOT)): dataset_hash,
            str(CODE.relative_to(ROOT)): code_hash,
        },
        "metrics": metrics,
        "passed": passed,
        "production_security_certification": False,
        "external_red_team_completed": False,
        "results": results,
    }


def _markdown(payload: dict[str, Any]) -> str:
    metrics = payload["metrics"]
    return "\n".join(
        [
            "# Prompt-injection regression v1",
            "",
            f"- Run ID: `{payload['run_id']}`",
            f"- Result: **{'PASS' if payload['passed'] else 'FAIL'}**",
            f"- Fixed cases: {metrics['case_count']} ({metrics['attack_case_count']} attack / {metrics['benign_case_count']} benign)",
            f"- Precision / recall / benign specificity: {metrics['precision']:.3f} / {metrics['recall']:.3f} / {metrics['benign_specificity']:.3f}",
            f"- Attack isolation rate: {metrics['attack_isolation_rate']:.3f}",
            "",
            "This fixed bilingual regression checks deterministic pattern detection and isolation only. ",
            "It is not an external red-team, does not cover adaptive attacks, and does not certify production security.",
            "Source knowledge records remain unchanged; isolation is applied only to model context.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("run", "verify"))
    args = parser.parse_args()
    current = evaluate()
    if args.command == "run":
        REPORT.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        MARKDOWN.write_text(_markdown(current), encoding="utf-8")
        print(f"prompt-security benchmark: {'PASS' if current['passed'] else 'FAIL'} {current['run_id']}")
        return 0 if current["passed"] else 1
    stored = json.loads(REPORT.read_text(encoding="utf-8"))
    comparable_keys = ("run_id", "benchmark_id", "evidence_sha256", "metrics", "passed", "results")
    if any(stored.get(key) != current.get(key) for key in comparable_keys):
        print("prompt-security benchmark verification: FAIL (report is stale)", file=sys.stderr)
        return 1
    print(f"prompt-security benchmark verification: PASS {stored['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
