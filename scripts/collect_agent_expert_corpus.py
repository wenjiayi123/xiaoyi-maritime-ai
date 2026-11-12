"""Collect fixed native trial evidence without loading a language model.

This corpus uses one existing physical window. The train/test designation is
for new parameter and decision configurations, not temporal/port generalization.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.expert_energy import ExpertEnergyBackend, digest  # noqa: E402

CONFIGURATIONS = {
    "train": [
        (85.0, (0.05, 0.35)),
        (100.0, (0.2, 0.7)),
        (120.0, (0.1, 0.95)),
        (90.0, (0.35, 0.9)),
        (110.0, (0.25, 0.75)),
        (130.0, (0.15, 0.6)),
    ],
    "sealed_test": [(95.0, (0.12, 0.72)), (105.0, (0.32, 0.88)), (125.0, (0.08, 0.92))],
}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base", default="http://127.0.0.1:18810")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    save(
        args.output / "COLLECTION_PLAN.json",
        {
            "time": datetime.now(timezone.utc).isoformat(),
            "configurations": CONFIGURATIONS,
            "baseline_green_preference": 0.5,
            "base": args.base,
            "max_comparisons": 18,
            "model_calls": 0,
            "scope": "native offline evidence construction, one known24hour physical window",
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "no_task_training_or_final_model_evaluation": True,
        },
    )
    rows, failures = [], []
    for split, configurations in CONFIGURATIONS.items():
        for config_index, (carbon, greens) in enumerate(configurations):
            for candidate_index, green in enumerate(greens):
                folder = args.output / split / f"config-{config_index:02d}" / f"candidate-{candidate_index}"
                tool = ExpertEnergyBackend(folder, args.base)
                parameters = {
                    "baseline_green_preference": 0.5,
                    "green_preference": green,
                    "carbon_price_cny_per_ton": carbon,
                }
                request_id = "expert-corpus-" + digest({"folder": str(folder.resolve()), "parameters": parameters})[:48]
                try:
                    tool.read_context()
                    tool.compare(parameters, request_id)
                    result = tool.verify(
                        {"min_carbon_reduction_pct": 0.0, "max_cost_cny": 1e9, "min_service_pct": 98.0}
                    )
                    save(folder / "RESULT.json", result)
                    facts = result["alternatives"]
                    if any(f["status"] != "ready" for f in facts):
                        raise ValueError("native calculation facts not ready")
                    row = {
                        "split": split,
                        "config_index": config_index,
                        "candidate_index": candidate_index,
                        "parameters": parameters,
                        "receipt_file": str((folder / "energy-journal.json").resolve()),
                        "receipt_sha256": tool.state["receipt"]["receipt_sha256"],
                        "dataset_sha256": facts[0]["dataset_sha256"],
                        "window_id": facts[0]["window_id"],
                        "baseline": {k: facts[0][k] for k in ["carbon_kg", "cost_cny", "service_pct"]},
                        "candidate": {k: facts[1][k] for k in ["carbon_kg", "cost_cny", "service_pct"]},
                        "deltas": result["assessment"]["deltas"],
                    }
                    rows.append(row)
                    print(
                        json.dumps(
                            {
                                "split": split,
                                "configuration": config_index,
                                "green": green,
                                "carbon_change": row["deltas"]["carbon_kg"],
                                "cost_change": row["deltas"]["cost_cny"],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                except Exception as exc:
                    failures.append(
                        {
                            "split": split,
                            "config_index": config_index,
                            "candidate_index": candidate_index,
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
                    save(folder / "FAILURE.json", failures[-1])
                    save(args.output / "PARTIAL.json", {"rows": rows, "failures": failures})
                    raise
                save(args.output / "PARTIAL.json", {"rows": rows, "failures": failures})
    summary = {
        "time": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "failures": failures,
        "native_comparisons": len(rows),
        "physical_windows": sorted({r["window_id"] for r in rows}),
        "model_calls": 0,
        "training_updates": 0,
        "scope": "parameter-combination corpus, not18physical scenarios or18model successes",
    }
    save(args.output / "COLLECTION_COMPLETE.json", summary)


if __name__ == "__main__":
    main()
