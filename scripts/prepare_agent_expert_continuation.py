"""Prepare revision002 training data only; no model or final test access."""

from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_agent_expert_training import read, save, sha, verify, EXPERT, OLD  # noqa: E402
from scripts import run_agent_capability_scale as scale  # noqa: E402
from app.agent_training.environment_v2 import counterfactuals  # noqa: E402


def prepare():
    old_training = EXPERT / "training-001"
    verify(old_training)
    out = EXPERT / "continuation-002"
    data = out / "training-data"
    data.mkdir(exist_ok=False)
    states = []
    labels = {}
    provenance = {}
    source_states = old_training / "STATES.json"
    source_labels = old_training / "SFT_LABELS.json"
    old_labels = read(source_labels)
    for record in read(source_states):
        if record["origin"] != "new_reference_visited_state":
            continue
        record = deepcopy(record)
        old_branch = old_training / record["branch_file"]
        if sha(old_branch) != record["branch_sha256"]:
            raise ValueError("Branch drift")
        provenance[str(old_branch)] = sha(old_branch)
        dest = data / record["branch_file"]
        dest.parent.mkdir(exist_ok=True)
        dest.write_bytes(old_branch.read_bytes())
        states.append(record)
        labels[record["state_id"]] = old_labels[record["state_id"]]
    provenance.update({str(p): sha(p) for p in [source_states, source_labels, old_training / "CONFIG.json"]})
    protocol = scale.core.verify(OLD / "round-001")
    jobs = [
        r
        for r in read(OLD / "round-001/RESULTS.json")["results"]
        if r["group"] == "E_more_sft" and r["stage"] == "core24-r1"
    ]
    assert len(jobs) == 24 and all(x["success"] for x in jobs)
    legacy_count = 0
    for result in jobs:
        path = Path(result["folder"]) / "job.json"
        job = read(path)
        provenance[str(path)] = sha(path)
        env = scale.core.live.environment_for_job(job)
        history = []
        for saved_step in job["steps"]:
            prompt = scale.core.prompt_for(env, protocol["prompt_mode"])
            if prompt != saved_step["decision_input"]:
                raise ValueError("Legacy state mismatch")
            sid = f"retention-full-{legacy_count:03d}"
            legacy_count += 1
            branch = counterfactuals(deepcopy(env))
            rel = "branches/" + sid + ".json"
            save(data / rel, branch)
            states.append(
                {
                    "state_id": sid,
                    "origin": "legacy_core24_full_trajectory_retention",
                    "case_id": env.task.case_id,
                    "prompt": prompt,
                    "history": history.copy(),
                    "returns": [branch[a]["two_step_return"] for a in "ABCDEFGHIJKLM"],
                    "branch_file": rel,
                    "branch_sha256": sha(data / rel),
                }
            )
            labels[sid] = saved_step["choice"]
            env.step(saved_step["choice"])
            history.append(saved_step["choice"])
    new_ids = [r["state_id"] for r in states if r["origin"] == "new_reference_visited_state"]
    old_ids = [r["state_id"] for r in states if r["origin"] == "legacy_core24_full_trajectory_retention"]
    assert len(new_ids) == 156 and len(old_ids) <= 256
    rng = random.Random(20261104)

    def exposures(ids):
        result = []
        while len(result) < 256:
            pool = ids.copy()
            rng.shuffle(pool)
            result.extend(pool)
        return result[:256]

    new_exposures, old_exposures = exposures(new_ids), exposures(old_ids)
    order = [
        {"origin": "mixed_new_and_retention", "states": new_exposures[i : i + 4] + old_exposures[i : i + 4]}
        for i in range(0, 256, 4)
    ]
    assert set(new_exposures) == set(new_ids) and set(old_exposures) == set(old_ids)
    save(data / "STATES.json", states)
    save(data / "SFT_LABELS.json", labels)
    save(data / "ORDER.json", order)
    parent = read(old_training / "TRAINING_COMPLETE.json")["routes"]["E_sft"]
    design = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "design_and_training_data_prepared_not_frozen",
        "purpose": "Shared partially-adapted SFT parent; learn new tasks and repair/retain old tasks with both training routes. Not proof of general RL superiority.",
        "common_parent": {k: parent[k] for k in ["adapter", "file_sha256", "parameter_fingerprint"]},
        "parent_selection_reason": "Reuse fixed-final64 SFT adapter: training-only new-state CE decreased and continuing from it saves compute; not a checkpoint search on final tests.",
        "seed": 20261104,
        "route_order": ["E_sft", "D_rl"],
        "updates_per_route": 64,
        "total_update_cap": 128,
        "minibatch_states": 8,
        "schedule": "4new+4old per update,256state exposures each, full coverage before repeats",
        "learning_rate": 0.0001,
        "weight_decay": 0.0,
        "gradient_clip": 1.0,
        "temperature": 8.0,
        "kl_coefficient": 0.02,
        "entropy_coefficient": 0.001,
        "common_preservation": "Both routes use reverseKL to the same starting parent at temperature8 and identical entropy coefficient; old-state replay identical.",
        "sft_objective": "Demonstration cross entropy at temperature1 + common KL - common entropy; report as regularizedSFT.",
        "rl_objective": "Negative probability-weighted standardized13-action two-step returns at temperature8 + common KL - common entropy; no SFT target in objective.",
        "temperature_reason": "Fixed temperature8 to reduce probability saturation identified in training logs. No model hyperparameter sweep or heldout selection.",
        "return_semantics": "Unchanged new potential-shaped and old raw two-step enumerations; separate in charts. No on-policy trajectory or full-horizon claim.",
        "state_count": len(states),
        "new_states": 156,
        "old_full_trajectory_states": legacy_count,
        "new_task_count": 24,
        "old_core_task_count": 24,
        "model_oracle_at_inference": False,
        "source_files": provenance,
        "heldout_status": "New distinct conditions still to be created and frozen; no finaltest read in this preparation.",
        "selection": "Fixed final64, retain every intermediate checkpoint, optimizer/RNG and failure. No finaltest checkpoint selection.",
        "launch_allowed": False,
        "remaining_preconditions": [
            "New untouched holdout specification and data separation audit",
            "Versioned trainer and independent auditor for common objective",
            "Token limits verified without secondmodel",
            "All protocol/config/data/source hashes frozen",
            "Safely stop verified inference worker only after readiness, train serially, restore original+new aliases",
        ],
        "limits": [
            "One known historical physical window",
            "Common start already underwent64SFT updates; this is continuation, not fresh-base training",
            "Same update count does not guarantee equal compute",
            "KL parent initially imperfect: need measure both restoration and new skill acquisition",
        ],
    }
    save(out / "DESIGN.json", design)
    save(
        data / "PREPARATION_AUDIT.json",
        {
            "passed": True,
            "new_states": 156,
            "old_states": legacy_count,
            "total_states": len(states),
            "old_cases": 24,
            "coverage_all_states": True,
            "updates_per_route": 64,
            "state_exposures_per_route": 512,
            "model_loads": 0,
            "training_updates": 0,
            "final_test_access": False,
            "frozen_training_protocol": False,
        },
    )
    save(data / "SOURCE_MANIFEST.json", provenance)
    print({"states": len(states), "old_full_states": legacy_count, "model_loads": 0, "launch_allowed": False})


if __name__ == "__main__":
    prepare()
