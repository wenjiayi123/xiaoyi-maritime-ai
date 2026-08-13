from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_JSON = ROOT / "reports" / "lora_admission_v1.json"
OUTPUT_MARKDOWN = ROOT / "reports" / "lora_admission_v1.md"
INPUTS = (
    "reports/local_lora_inference_v3.json",
    "reports/local_rag_lora_e2e_v3.json",
    "reports/maritime_model_benchmark_v7_lora_r96.json",
    "reports/maritime_model_benchmark_v7_baseline.json",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def build_report() -> dict[str, Any]:
    inference = json.loads((ROOT / INPUTS[0]).read_text(encoding="utf-8"))
    e2e = json.loads((ROOT / INPUTS[1]).read_text(encoding="utf-8"))
    model_benchmark = json.loads((ROOT / INPUTS[2]).read_text(encoding="utf-8"))
    training = inference["training_summary"]
    training_config = training["training"]
    provider_counts = model_benchmark["summary"].get("generation_provider_counts", {})
    checks = [
        {
            "id": "artifact_integrity",
            "passed": all(
                inference["evidence"][name].get("sha256")
                for name in ("dataset_manifest", "training_report", "lora_gguf")
            ) and bool(training.get("adapter_sha256")),
            "observed": "manifest, training report, PEFT adapter and GGUF hashes recorded",
            "required": "all training and inference artifacts are content-addressed",
        },
        {
            "id": "real_local_generation_probe",
            "passed": inference.get("status") == "completed"
            and inference.get("response", {}).get("usage", {}).get("completion_tokens", 0) > 0
            and e2e.get("status") == "completed",
            "observed": (
                f"{inference.get('response', {}).get('usage', {}).get('completion_tokens', 0)} "
                "completion tokens plus one RAG-to-LoRA probe"
            ),
            "required": "matching-base adapter loads and produces tokens through the local runtime",
        },
        {
            "id": "multi_seed_training",
            "passed": False,
            "observed": f"1 seed ({training_config['seed']})",
            "required": ">=3 independently trained seeds",
        },
        {
            "id": "heldout_generation_quality",
            "passed": False,
            "observed": (
                f"validation/test loss use {training_config['validation_cases']}/"
                f"{training_config['test_cases']} sampled cases; no expert blind preference study"
            ),
            "required": ">=100 source-isolated unseen generation cases plus expert blind review",
        },
        {
            "id": "lora_attributable_benchmark",
            "passed": False,
            "observed": (
                "model benchmark provider counts are "
                f"{provider_counts}; they do not isolate adapter causal lift"
            ),
            "required": "same-base baseline vs LoRA paired benchmark with 95% CI and no safety regression",
        },
        {
            "id": "training_depth",
            "passed": False,
            "observed": f"{training_config['max_steps']} optimizer steps on one CPU run",
            "required": "predeclared convergence budget with multi-seed stability and early-stop evidence",
        },
    ]
    engineering_passed = all(item["passed"] for item in checks[:2])
    quality_passed = all(item["passed"] for item in checks)
    report = {
        "schema_version": "xiaoyi-lora-admission.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_run_id": training["run_id"],
        "training_type": "PEFT_LoRA_SFT_adapter",
        "foundation_model_trained_from_scratch": False,
        "engineering_integrity_passed": engineering_passed,
        "quality_admission_passed": quality_passed,
        "admission_status": (
            "quality_admitted" if quality_passed else "engineering_only_quality_blocked"
        ),
        "production_authority": False,
        "claim_boundary": (
            "This is an adapter engineering and local inference proof. Loss reduction is not answer "
            "accuracy, expert preference, port KPI, legal correctness, or proof that the base model "
            "was trained from scratch."
        ),
        "training_snapshot": {
            "seed_count": 1,
            "seed": training_config["seed"],
            "optimizer_steps": training_config["max_steps"],
            "train_examples": training["dataset"]["train_examples"],
            "validation_examples": training["dataset"]["validation_examples"],
            "test_examples": training["dataset"]["test_examples"],
            "validation_loss_cases": training_config["validation_cases"],
            "test_loss_cases": training_config["test_cases"],
            "initial_validation_loss": training_config["initial_validation_loss"],
            "final_validation_loss": training_config["final_validation_loss"],
            "initial_test_loss": training_config["initial_test_loss"],
            "final_test_loss": training_config["final_test_loss"],
            "adapter_sha256": training["adapter_sha256"],
            "gguf_sha256": inference["evidence"]["lora_gguf"]["sha256"],
        },
        "checks": checks,
        "evidence_sha256": {relative: _sha256(ROOT / relative) for relative in INPUTS},
    }
    return report


def _markdown(report: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| `{item['id']}` | {'PASS' if item['passed'] else 'BLOCKED'} | {item['observed']} | {item['required']} |"
        for item in report["checks"]
    )
    snapshot = report["training_snapshot"]
    return f"""# 小懿 LoRA 工程与质量准入报告 v1

生成时间：{report['generated_at']}
来源run_id：`{report['source_run_id']}`

| 门禁 | 结果 | 当前证据 | 晋级要求 |
|---|---|---|---|
{rows}

## 结论

- 工程完整性：`{str(report['engineering_integrity_passed']).lower()}`；质量准入：`{str(report['quality_admission_passed']).lower()}`。
- 当前定位：`{report['admission_status']}`。这是PEFT LoRA/SFT适配器训练，不是从零训练基础模型。
- 训练快照：1个种子、{snapshot['optimizer_steps']}步、{snapshot['train_examples']}/{snapshot['validation_examples']}/{snapshot['test_examples']}条来源隔离样本；loss仅抽取{snapshot['validation_loss_cases']}/{snapshot['test_loss_cases']}例计算。
- 适配器SHA-256：`{snapshot['adapter_sha256']}`；GGUF SHA-256：`{snapshot['gguf_sha256']}`。
- `production_authority=false`。loss下降不等于回答准确率、专家偏好、港口KPI或法律正确性。
"""


def verify() -> list[str]:
    errors: list[str] = []
    report = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
    for relative, expected in report["evidence_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or _sha256(path) != expected:
            errors.append(f"evidence hash mismatch: {relative}")
    if report.get("engineering_integrity_passed") is not True:
        errors.append("LoRA engineering integrity is not complete")
    if report.get("quality_admission_passed") is not False:
        errors.append("current LoRA quality admission must remain blocked")
    if report.get("foundation_model_trained_from_scratch") is not False:
        errors.append("LoRA must not be labeled foundation training")
    return errors


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    arguments = parser.parse_args()
    if arguments.command == "build":
        report = build_report()
        _atomic_write(OUTPUT_JSON, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        _atomic_write(OUTPUT_MARKDOWN, _markdown(report))
        print(json.dumps({"report": str(OUTPUT_JSON.relative_to(ROOT)), "status": report["admission_status"]}))
        return 0
    errors = verify()
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print("lora-admission: PASS (engineering proof retained; quality gate blocked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
