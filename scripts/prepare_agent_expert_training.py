"""Prepare one bounded dual-route experiment using training evidence only."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.expert_environment import ExpertEnvironment, ExpertTask, RecordedEnergyProvider  # noqa: E402
from app.agent_training.artifact_path import artifact_path
from app.agent_training.expert_learning import counterfactuals, GAMMA  # noqa: E402
from scripts import run_agent_capability_scale as scale  # noqa: E402
from app.agent_training.environment_v2 import counterfactuals as legacy_counterfactuals  # noqa: E402

EXPERT = ROOT / ".codex_artifacts/agent-rl-expert-expansion-20261102"
DATA = EXPERT / "tasks-002"
OLD = ROOT / ".codex_artifacts/agent-rl-capability-scale-20261102"


def read(path):
    return json.loads(artifact_path(path).read_bytes())


def sha(path):
    return hashlib.sha256(artifact_path(path).read_bytes()).hexdigest()


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def verify_preserved():
    lock = read(EXPERT / "BASELINE_LOCK.json")
    files = {**lock["files"], lock["archive"]: lock["archive_sha256"]}
    files.update(read(DATA / "DATA_LOCK.json")["files"])
    for path, expected in files.items():
        # Sealed files are hashed for preservation only, never parsed here.
        if sha(path) != expected:
            raise ValueError("Preserved file drift: " + path)


def environment(case):
    files = [Path(p) for p in case["receipt_files"]]
    if any("sealed_test" in p.parts or "sealed-test" in p.parts for p in files):
        raise ValueError("Held-out evidence is forbidden during preparation/training")
    receipts = [read(p)["receipt"] for p in files]
    return ExpertEnvironment(ExpertTask(**case["task"]), RecordedEnergyProvider(receipts))


def prepare(out):
    verify_preserved()
    out.mkdir(parents=True, exist_ok=False)
    cases = {c["task"]["case_id"]: c for c in read(DATA / "train/tasks.json")}
    demonstrations = read(DATA / "train/demonstrations.json")
    states, labels, new_ids = [], {}, []
    for number, demo in enumerate(demonstrations):
        env = environment(cases[demo["case_id"]])
        for action in demo["history"]:
            env.step(action)
        if env.done or env.prompt() != demo["prompt"]:
            raise ValueError("Training demonstration state mismatch")
        sid = f"new-{number:03d}"
        branches = counterfactuals(env)
        rel = "branches/" + sid + ".json"
        save(out / rel, branches)
        states.append(
            {
                "state_id": sid,
                "origin": "new_reference_visited_state",
                "case_id": demo["case_id"],
                "prompt": env.prompt(),
                "history": demo["history"],
                "returns": [branches[a]["two_step_return"] for a in "ABCDEFGHIJKLM"],
                "branch_file": rel,
                "branch_sha256": sha(out / rel),
            }
        )
        labels[sid] = demo["target"]
        new_ids.append(sid)

    # Retention uses only the previously adapted core24, never the six old
    # extension cases or any paused confirmatory final-test material.
    legacy_protocol = scale.core.verify(OLD / "round-001")
    results = read(OLD / "round-001/RESULTS.json")["results"]
    jobs = [r for r in results if r["group"] == "E_more_sft" and r["stage"] == "core24-r1"]
    if len(jobs) != 24 or not all(r["success"] for r in jobs):
        raise ValueError("Expected successful core24 source demonstrations")
    legacy_by_case, provenance = [], {}
    for item in jobs:
        path = Path(item["folder"]) / "job.json"
        job = read(path)
        provenance[str(path)] = sha(path)
        env = scale.core.live.environment_for_job(job)
        pool = []
        for step in job["steps"]:
            prompt = scale.core.prompt_for(env, legacy_protocol["prompt_mode"])
            if prompt != step["decision_input"]:
                raise ValueError("Legacy prompt mismatch")
            pool.append((deepcopy(env), step["choice"], prompt))
            env.step(step["choice"])
        legacy_by_case.append(pool)
    retention_ids = []
    for i in range(64):
        pool = legacy_by_case[i % 24]
        index = 0 if i < 24 else len(pool) - 1 if i < 48 else len(pool) // 2
        env, target, prompt = pool[index]
        sid = f"retention-{i:03d}"
        branches = legacy_counterfactuals(env)
        rel = "branches/" + sid + ".json"
        save(out / rel, branches)
        states.append(
            {
                "state_id": sid,
                "origin": "legacy_core24_retention",
                "case_id": env.task.case_id,
                "prompt": prompt,
                "returns": [branches[a]["two_step_return"] for a in "ABCDEFGHIJKLM"],
                "branch_file": rel,
                "branch_sha256": sha(out / rel),
            }
        )
        labels[sid] = target
        retention_ids.append(sid)
    rng = random.Random(20261103)
    rng.shuffle(new_ids)
    order = []
    for block in range(16):
        for j in range(3):
            start = (block * 3 + j) * 4
            order.append(
                {"origin": "new_tasks", "states": [new_ids[k % len(new_ids)] for k in range(start, start + 4)]}
            )
        order.append({"origin": "retention", "states": retention_ids[block * 4 : block * 4 + 4]})
    registry = read(OLD / "live-registration/REGISTRY.json")
    # Registry format is deliberately checked before relying on it.
    models = registry.get("models", registry.get("groups", {}))
    parents = {"E_sft": models["E_more_sft"], "D_rl": models["D_scale_rl"]}
    cfg = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": 20261103,
        "route_order": ["E_sft", "D_rl"],
        "purpose": "Dual-route capability demonstration; different accepted parents, no superiority comparison",
        "parents": parents,
        "data_root": str(DATA),
        "data_lock_sha256": sha(DATA / "DATA_LOCK.json"),
        "updates_per_needed_route": 64,
        "total_update_cap": 128,
        "minibatch_states": 4,
        "threads": 4,
        "learning_rate": 0.00005,
        "weight_decay": 0.0,
        "gradient_clip": 1.0,
        "temperature": 2.0,
        "kl_coefficient": 0.02,
        "entropy_coefficient": 0.001,
        "sft_objective": "Mean cross entropy on declared action demonstrations, temperature1, no RL returns",
        "rl_objective": "Mean exact categorical expected standardized two-step simulator return + KL to own parent - entropy bonus",
        "new_returns": {
            "gamma": GAMMA,
            "shaping": "r + gamma*Phi(next) - Phi(current); terminal Phi=0",
            "potential": ".05*supplied_fields + .10*context_read + .15*received_candidates + .15*current_goal_verifications",
            "horizon": 2,
            "continuation": "max enumerated second-action shaped reward",
            "physical_simulation": "exact replay of frozen native training receipts only",
        },
        "retention_returns": "Unchanged legacy environment_v2.counterfactuals: raw first reward plus max raw second reward",
        "exploration": "All13first actions and all13second actions when nonterminal; no sampled on-policy trajectories used for gradients",
        "credit_limit": "Two-step privileged simulator return on reference-visited states, not unbiased long-horizon policy return",
        "labels": "E reads SFT_LABELS.json. D never reads that file; reference trajectories still supply D training states",
        "schedule": "48new minibatches*4=192state exposures covering156demonstrations;16retention minibatches*4=64states across24oldcoretasks",
        "preflight": "Once per parent, greedy training cases until first failure or all24correct; skip additional training only if24correct. Early failure is not a full success-rate estimate. No separate development training.",
        "selection": "Unchanged parent if preflight passes24/24, else fixed final step64; intermediate checkpoints audit only",
        "stop": "PAUSE, source/hash mismatch, nonfinite loss/gradient, exception or64updates; no automatic restart/extra budget",
        "evaluation": {
            "open_only_after": "Both routes committed and independent parameter/objective audit passed",
            "sealed_cases": 12,
            "repetitions": 2,
            "legacy_cases": 30,
            "legacy_repetitions": 2,
            "metrics": [
                "decision correctness",
                "verified business completion among8feasible cases",
                "correct none-of-two explanation among4infeasible cases",
                "clarification",
                "receipt recovery",
                "current-goal verification",
                "old30 retention",
            ],
            "acceptance": "Each route24/24correct new attempts and60/60old attempts, plus four native task-family demonstrations per route. All failures retained. No final-test-driven retraining.",
            "generalization_limit": "12new parameter/constraint configurations, one known offline window, overlapping physical vectors; not independent ports or field SLA",
        },
        "model": "Qwen3-1.7B float32; last four layer q/v LoRA r8;229376trainable values",
        "cache_dir": str(ROOT / ".codex_artifacts/agent-rl-v2-20261102/frozen-prefix-cache"),
        "reward_shaping_source": "https://ai.stanford.edu/~ang/papers/shaping-icml99.pdf",
        "theory_limit": "Potential-shaping complete discounted-return identity; no optimality guarantee for truncated two-step approximation",
        "production_authority": False,
        "final_tests_opened": False,
    }
    save(out / "CONFIG.json", cfg)
    save(out / "STATES.json", states)
    save(out / "SFT_LABELS.json", labels)
    save(out / "ORDER.json", order)
    save(out / "RETENTION_SOURCES.json", provenance)
    save(
        out / "PREPARED.json",
        {
            "states": len(states),
            "new_states": 156,
            "retention_states": 64,
            "new_task_count": 24,
            "legacy_task_count": 24,
            "updates_per_route": 64,
            "model_calls": 0,
            "training_updates": 0,
            "protocol_frozen": False,
        },
    )


def freeze(out):
    verify_preserved()
    if (out / "LOCK.json").exists():
        raise ValueError("Already frozen")
    cfg = read(out / "CONFIG.json")
    for parent in cfg["parents"].values():
        if sha(parent["adapter"]) != parent["file_sha256"]:
            raise ValueError("Parent drift")
    if not read(out / "OBJECTIVE_AUDIT.json")["passed"] or not read(out / "TOKEN_AUDIT.json")["passed"]:
        raise ValueError("Objective and token audits required")
    sources = {str((ROOT / rel).resolve()): sha(ROOT / rel) for rel in read(OLD / "round-003/SOURCES.json")}
    for p in list((ROOT / "app/agent_training").glob("*.py")) + [
        Path(__file__),
        ROOT / "scripts/train_agent_expert.py",
        ROOT / "scripts/audit_agent_expert_training.py",
        ROOT / "scripts/audit_agent_expert_objective.py",
        ROOT / "tests/test_agent_expert_learning.py",
        ROOT / "scripts/audit_agent_capability_adaptation.py",
        ROOT / "scripts/adapt_agent_capability_scale.py",
    ]:
        sources[str(p.resolve())] = sha(p)
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


def verify(out):
    for rel, expected in read(out / "LOCK.json").items():
        if sha(out / rel) != expected:
            raise ValueError("Frozen file drift: " + rel)
    for path, expected in read(out / "SOURCES.json").items():
        if sha(path) != expected or sha(out / "sources" / Path(path).relative_to(ROOT)) != expected:
            raise ValueError("Frozen source drift: " + path)
    for path, expected in read(out / "RETENTION_SOURCES.json").items():
        if sha(path) != expected:
            raise ValueError("Retention source drift")
    verify_preserved()
    cfg = read(out / "CONFIG.json")
    for parent in cfg["parents"].values():
        if sha(parent["adapter"]) != parent["file_sha256"]:
            raise ValueError("Parent drift")
    return cfg


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "freeze", "verify"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    {"prepare": prepare, "freeze": freeze, "verify": verify}[args.command](args.output.resolve())
