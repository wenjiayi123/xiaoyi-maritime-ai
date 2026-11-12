"""Versioned revision002 data/protocol freeze; never train on final tests."""

from __future__ import annotations
import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_agent_expert_training import read, save, sha, verify as verify_previous, EXPERT  # noqa: E402
from app.agent_training.expert_energy import check_receipt  # noqa: E402
from app.agent_training.expert_contracts import assess_energy_option  # noqa: E402
from app.agent_training.expert_environment import ExpertTask  # noqa: E402


def prepare(out):
    verify_previous(EXPERT / "training-001")
    if (out / "CONFIG.json").exists():
        raise ValueError("Preparation already exists; preserve it")
    design = read(out / "DESIGN.json")
    prior = EXPERT / "tasks-002"
    data = out / "tasks-003"
    data.mkdir(exist_ok=False)
    shutil.copytree(prior / "train", data / "train")
    train = read(data / "train/tasks.json")
    cases, gold, receipts_used = [], [], {}
    families = ("clarification", "multiple_constraints", "unknown_receipt", "changed_goal")
    # Predefined new constraint / event combinations on existing native evidence.
    # No opened final-test file is parsed, relabelled, or used to choose thresholds.
    for index, config in enumerate((0, 2, 4)):
        for fi, family in enumerate(families):
            source = next(c for c in train if c["configuration_index"] == config and c["family"] == family)
            case = deepcopy(source)
            task = case["task"]
            task["case_id"] = f"continuation002-holdout-{index:02d}-{family}"
            task["goal"] = (
                "请为这次登记的能碳试算逐项核对约束，再提交有回执依据的候选建议。缺的信息先补齐，结果未知时先查回执；目标有变更则按最新目标核验。"
            )
            facts = []
            for p in case["receipt_files"]:
                receipt = read(Path(p))["receipt"]
                facts.append(check_receipt(receipt, receipt["parameters"]))
                receipts_used[p] = sha(Path(p))
            costs = [f[1]["cost_cny"] for f in facts]
            reductions = [(f[0]["carbon_kg"] - f[1]["carbon_kg"]) / f[0]["carbon_kg"] * 100 for f in facts]
            feasible = {
                "max_cost_cny": round(max(costs) + 137.25 + index * 53.5 + fi * 7.25, 3),
                "min_service_pct": 97.125 + index * 0.125,
            }
            if max(reductions) > 0:
                feasible["min_carbon_reduction_pct"] = round(max(reductions) * (0.23 + 0.07 * index + 0.01 * fi), 6)
            infeasible = {"max_cost_cny": round(min(costs) - 357.25 - fi * 13.75, 3), "min_service_pct": 97.375}
            final_goal = infeasible if index == 2 else feasible
            # Restore any missing training field, then apply a new missing-field pattern.
            for key, value in task.get("scripted_replies", {}).items():
                task[key] = value
            task["scripted_replies"] = {}
            task["requirements"] = final_goal
            task["changed_requirements"] = None
            task["lose_response_candidates"] = []
            if family == "clarification":
                key = ("requirements", "baseline_green_preference", "carbon_price_cny_per_ton")[index]
                task["scripted_replies"] = {key: task[key]}
                task[key] = None
            elif family == "unknown_receipt":
                task["lose_response_candidates"] = [1 - index % 2] if index < 2 else [0, 1]
            elif family == "changed_goal":
                task["requirements"] = {"max_cost_cny": round(max(costs) + 921.75, 3), "min_service_pct": 96.625}
                task["changed_requirements"] = final_goal
                task["change_after_calculations"] = 1
            task["max_steps"] = 18
            case["task"] = asdict(ExpertTask(**task))
            case["configuration_index"] = 100 + index
            case["source_training_configuration"] = config
            valid = [
                i
                for i, f in enumerate(facts)
                if assess_energy_option(*f, final_goal)["status"] == "meets_registered_requirements"
            ]
            assert bool(valid) == (index != 2)
            expected = "verified_candidate_recommended" if valid else "no_registered_candidate_meets_requirements"
            cases.append(case)
            gold.append(
                {"case_id": task["case_id"], "expected_outcome": expected, "allowed_recommendation_indices": valid}
            )
    save(data / "sealed-test/tasks.json", cases)
    save(data / "sealed-test/oracle-labels.json", gold)
    save(
        data / "DATA_AUDIT.json",
        {
            "train_tasks": 24,
            "new_holdout_cases": 12,
            "feasible": 8,
            "no_registered_candidate": 4,
            "physical_windows": 1,
            "reused_training_physical_evidence": True,
            "holdout_scope": "New constraint/event combinations only; known underlying metrics. Not new ports/independent physical trajectories.",
            "old_opened_final_test_parsed": False,
            "holdout_model_runs": 0,
            "holdout_environment_rollouts": 0,
            "label_validation": "Independent native receipt numerical assessment only",
        },
    )
    files = {str(p.resolve()): sha(p) for p in data.rglob("*") if p.is_file()}
    save(
        data / "DATA_LOCK.json",
        {"files": {**files, **receipts_used}, "created_at": datetime.now(timezone.utc).isoformat()},
    )
    for name in ("STATES.json", "SFT_LABELS.json", "ORDER.json"):
        value = read(out / "training-data" / name)
        if name == "STATES.json":
            for r in value:
                r["branch_file"] = "training-data/" + r["branch_file"]
        save(out / name, value)
    cfg = {
        k: design[k]
        for k in (
            "seed",
            "route_order",
            "total_update_cap",
            "minibatch_states",
            "learning_rate",
            "weight_decay",
            "gradient_clip",
            "temperature",
            "kl_coefficient",
            "entropy_coefficient",
            "selection",
            "sft_objective",
            "rl_objective",
        )
    }
    cfg.update(
        created_at=datetime.now(timezone.utc).isoformat(),
        purpose=design["purpose"],
        parents={g: design["common_parent"] for g in design["route_order"]},
        updates_per_needed_route=64,
        threads=4,
        cache_dir=str(ROOT / ".codex_artifacts/agent-rl-v2-20261102/frozen-prefix-cache"),
        data_root=str(data.resolve()),
        data_lock_sha256=sha(data / "DATA_LOCK.json"),
        preflight="No extra parent model trial: fixed training continuation authorized; parent selected from training-only CE progress, samefixed-final64 for both.",
        model="Qwen3-1.7B float32, last4q/v LoRA r8,229376trainable values",
        regularization_matched=True,
        superiority_claimed=False,
        evaluation={
            "new_cases": 12,
            "new_repetitions": 2,
            "legacy_cases": 30,
            "legacy_repetitions": 2,
            "native_cases": 4,
            "native_repetitions": 1,
            "planned_total_attempts": 176,
            "acceptance": "Each route24/24new correct,60/60old correct,4/4fixed native demonstrations. All semantic failures continue and are preserved.",
            "generalization_limit": "12new constraint/event combinations on one known physical window; shared training physics,not independentports. Repeats not independentcases.",
            "open_only_after": "Both fixed-final64adapters and parameter/objectiveaudit complete, then separate evaluator/source freeze. No tuning using this or previous final tests.",
        },
    )
    save(out / "CONFIG.json", cfg)
    save(out / "RETENTION_SOURCES.json", read(out / "training-data/SOURCE_MANIFEST.json"))
    print({"new_holdout": 12, "training_states": 279, "model_calls": 0, "frozen": False})


def token_check(out):
    from transformers import AutoTokenizer
    from app.agent_training.policy import BASE, SYSTEM

    tokenizer = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
    counts = []
    for r in read(out / "STATES.json"):
        text = tokenizer.apply_chat_template(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": r["prompt"]}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        counts.append({"state_id": r["state_id"], "tokens": len(tokenizer.encode(text))})
    passed = max(x["tokens"] for x in counts) <= 768
    save(
        out / "TOKEN_AUDIT.json",
        {
            "passed": passed,
            "states": len(counts),
            "max_tokens": max(x["tokens"] for x in counts),
            "limit": 768,
            "model_loaded": False,
            "rows": counts,
        },
    )
    assert passed
    print({"token_max": max(x["tokens"] for x in counts), "model_loaded": False})


def freeze(out):
    verify_previous(EXPERT / "training-001")
    if (out / "LOCK.json").exists():
        raise ValueError("Already frozen")
    assert read(out / "TOKEN_AUDIT.json")["passed"] and read(out / "OBJECTIVE_AUDIT_FINAL.json")["passed"]
    sources = dict(read(EXPERT / "training-001/SOURCES.json"))
    for name in (
        "agent_expert_continuation_objective.py",
        "prepare_agent_expert_continuation.py",
        "freeze_agent_expert_continuation.py",
        "train_agent_expert_continuation.py",
        "audit_agent_expert_continuation.py",
        "run_agent_expert_continuation_queue.py",
        "serve_agent_expert_registry.py",
    ):
        p = ROOT / "scripts" / name
        sources[str(p)] = sha(p)
    test = ROOT / "tests/test_agent_expert_continuation.py"
    sources[str(test)] = sha(test)
    for name in sources:
        p = Path(name)
        dest = out / "sources" / p.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
    save(out / "SOURCES.json", sources)
    files = {
        str(p.relative_to(out)): sha(p)
        for p in out.rglob("*")
        if p.is_file() and "sources" not in p.relative_to(out).parts
    }
    save(out / "LOCK.json", files)
    save(out / "STATUS.json", {"phase": "frozen_ready", "training_started": False})
    verify(out)
    print({"frozen": True, "files": len(files), "source_files": len(sources)})


def verify(out):
    for rel, expected in read(out / "LOCK.json").items():
        if sha(out / rel) != expected:
            raise ValueError("Frozen file drift: " + rel)
    for path, expected in read(out / "SOURCES.json").items():
        if sha(Path(path)) != expected or sha(out / "sources" / Path(path).relative_to(ROOT)) != expected:
            raise ValueError("Frozen source drift: " + path)
    for path, expected in read(out / "RETENTION_SOURCES.json").items():
        if sha(Path(path)) != expected:
            raise ValueError("Training provenance drift")
    cfg = read(out / "CONFIG.json")
    for path, expected in read(Path(cfg["data_root"]) / "DATA_LOCK.json")["files"].items():
        if sha(Path(path)) != expected:
            raise ValueError("New data drift")
    for parent in cfg["parents"].values():
        if sha(Path(parent["adapter"])) != parent["file_sha256"]:
            raise ValueError("Common parent drift")
    verify_previous(EXPERT / "training-001")
    return cfg


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "token-check", "freeze", "verify"])
    parser.add_argument("--experiment", type=Path, required=True)
    a = parser.parse_args()
    {"prepare": prepare, "token-check": token_check, "freeze": freeze, "verify": verify}[a.command](
        a.experiment.resolve()
    )
