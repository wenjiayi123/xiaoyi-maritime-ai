"""Declared development-only checkpoint-grid refinement; never reads test cases.

The initial selection/config are retained. Both methods receive the same grid;
saved weights are evaluated, not retrained or edited. Retention gates selection.
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_agent_rl_v1 import append, retention, save  # noqa: E402
from scripts.run_agent_rl_v2 import evaluate, init_policy, load, sha, task_rows  # noqa: E402

GRID = [64, 128, 192, 256, 320, 384, 448, 512]


def register(args):
    out = args.experiment
    target = out / "selection-grid-amendment.json"
    if target.exists() or (out / "test-opened.json").exists():
        raise ValueError("amendment already registered or final test already opened")
    save(
        target,
        {
            "schema": "development-selection-amendment.v1",
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "reason": "512-step RL improves validation task success but fails the predeclared retention gate; examine saved intermediate checkpoints before final test",
            "grid": GRID,
            "groups": ["D_rl", "E_more_sft"],
            "eligibility": "at least frozen-C accuracy on the same fixed 8 regression probes",
            "selection": "validation successes, then fewer errors, fewer calls, earlier step",
            "missing_checkpoints": "skip only checkpoints never produced because of original early-stop rule",
            "retention_screen": "screen every available grid checkpoint; full task validation only for eligible new checkpoints; retain existing scores including ineligible points",
            "test_opened": False,
            "config_sha256": sha(out / "config.json"),
            "task_manifest_sha256": sha(out / "task-manifest.json"),
            "data_reward_environment_weights_unchanged": True,
            "new_training_steps": 0,
            "initial_protocol_deviation": "additional development validation grid; original three-checkpoint results remain intact",
        },
    )
    print(target, flush=True)


def run(args):
    out = args.experiment
    amendment = load(out / "selection-grid-amendment.json")
    original = load(out / "checkpoint-selection.json")
    if (out / "test-opened.json").exists() or (out / "selection-refinement-start.json").exists():
        raise ValueError("test opened or refinement already started; no evidence overwritten")
    if (
        sha(out / "config.json") != amendment["config_sha256"]
        or sha(out / "task-manifest.json") != amendment["task_manifest_sha256"]
    ):
        raise ValueError("protocol/data changed after amendment")
    if amendment["grid"] != GRID:
        raise ValueError("unexpected selection grid")
    shutil.copy2(out / "checkpoint-selection.json", out / "checkpoint-selection.pre-refinement.json")
    shutil.copy2(Path(__file__), out / "selection-refinement-source.py")
    save(
        out / "selection-refinement-start.json",
        {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "amendment_sha256": sha(out / "selection-grid-amendment.json"),
            "original_selection_sha256": sha(out / "checkpoint-selection.pre-refinement.json"),
            "script_sha256": sha(out / "selection-refinement-source.py"),
        },
    )
    cfg = load(out / "config.json")
    policy, _, _ = init_policy(argparse.Namespace(output=out, threads=args.threads))
    frozen_hash = policy.fingerprint()
    from safetensors.torch import load_file
    from peft import set_peft_model_state_dict

    baseline_retention = load(out / "retention/validation-C_sft.json")["accuracy"]
    tasks = task_rows(out, "validation")
    selections = {}
    all_candidates = {}
    for group in amendment["groups"]:
        candidates = []
        for step in amendment["grid"]:
            checkpoint = out / "checkpoints" / group / f"step-{step:05d}"
            if not checkpoint.exists():
                append(
                    out / "selection-refinement.jsonl",
                    {"group": group, "step": step, "status": "not_produced_by_original_training"},
                )
                continue
            set_peft_model_state_dict(policy.model, load_file(str(checkpoint / "adapter_model.safetensors")))
            fingerprint = policy.fingerprint()
            if fingerprint != load(checkpoint / "metadata.json")["parameter_sha256"]:
                raise ValueError("checkpoint changed")
            save(
                out / "status.json",
                {"stage": "refining_checkpoint_selection", "group": group, "step": step, "max_steps": 512},
            )
            name = f"validation-{group}-{step}"
            keep_file = out / "retention" / (name + ".json")
            keep = load(keep_file) if keep_file.exists() else retention(policy, name, out)
            eligible = keep["accuracy"] >= baseline_retention
            evaluation_file = out / "evaluations" / (name + ".json")
            existing = evaluation_file.exists()
            result = load(evaluation_file) if existing else evaluate(policy, tasks, name, out) if eligible else None
            row = {
                "step": step,
                "checkpoint": str(checkpoint.relative_to(out)),
                "parameter_sha256": fingerprint,
                "retention": keep,
                "eligible": eligible,
                "validation": result,
                "evaluation_reused": existing,
                "not_retrained": True,
            }
            candidates.append(row)
            append(
                out / "selection-refinement.jsonl",
                {
                    "group": group,
                    "step": step,
                    "eligible": eligible,
                    "retention": keep["accuracy"],
                    "successes": result["successes"] if result else None,
                    "evaluation_reused": existing,
                },
            )
            if result is not None and not existing:
                append(
                    out / "validation-curve.jsonl",
                    {
                        "phase": group,
                        "step": step,
                        "successes": result["successes"],
                        "mean_reward": result["mean_reward"],
                        "errors": result["total_errors"],
                        "mean_steps": result["mean_steps"],
                        "retention": keep["accuracy"],
                        "selection_amendment": True,
                    },
                )
            print(
                json.dumps(
                    {
                        "group": group,
                        "step": step,
                        "eligible": eligible,
                        "successes": result["successes"] if result else None,
                    }
                ),
                flush=True,
            )
        all_candidates[group] = candidates
        eligible = [r for r in candidates if r["eligible"] and r["validation"]]
        if not eligible:
            selections[group] = {
                "checkpoint": "checkpoints/sft",
                "step": 0,
                "parameter_sha256": frozen_hash,
                "reason": "no eligible trained checkpoint",
            }
        else:
            best = max(
                eligible,
                key=lambda r: (
                    r["validation"]["successes"],
                    -r["validation"]["total_errors"],
                    -r["validation"]["mean_steps"],
                    -r["step"],
                ),
            )
            selections[group] = {k: best[k] for k in ["checkpoint", "step", "parameter_sha256"]}
            selections[group]["validation_successes"] = best["validation"]["successes"]
    save(out / "selection-refinement-candidates.json", all_candidates)
    save(
        out / "checkpoint-selection.json",
        {
            "selected": selections,
            "selection_rule": cfg["selection"],
            "test_opened": False,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "config_sha256": sha(out / "config.json"),
            "baseline_validation": original["baseline_validation"],
            "selection_amendment": {
                "file": "selection-grid-amendment.json",
                "sha256": sha(out / "selection-grid-amendment.json"),
                "original_selection_file": "checkpoint-selection.pre-refinement.json",
                "original_selection_sha256": sha(out / "checkpoint-selection.pre-refinement.json"),
            },
        },
    )
    save(out / "status.json", {"stage": "selection_refined_test_unopened", "selected": selections})
    print(json.dumps(selections), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["register", "evaluate"])
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    {"register": register, "evaluate": run}[args.mode](args)
