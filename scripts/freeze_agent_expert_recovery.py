"""Prepare/freeze common recovery warm-start; final conditions never train."""

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import argparse
import collections
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.registered_receipts import read_receipt
from scripts.agent_expert_recovery_support import (  # noqa: E402
    DATA,
    EXPERT,
    REGISTRY,
    REGISTRY_SHA,
    balanced_order,
    read,
    save,
    sha,
    now,
)
from scripts.probe_agent_expert_observation import verify as verify_probe  # noqa: E402
from app.agent_training.expert_energy import check_receipt  # noqa: E402
from app.agent_training.expert_contracts import assess_energy_option  # noqa: E402
from app.agent_training.expert_environment import ExpertTask  # noqa: E402


def holdout(cases):
    """New registered constraints/events derived only from training receipts."""
    rows, labels = [], []
    families = ["clarification", "multiple_constraints", "unknown_receipt", "changed_goal"]
    for index, config in enumerate([1, 3, 5]):
        for fi, family in enumerate(families):
            case = deepcopy(next(c for c in cases if c["configuration_index"] == config and c["family"] == family))
            task = case["task"]
            for key, value in task["scripted_replies"].items():
                task[key] = value
            task.update(
                scripted_replies={},
                lose_response_candidates=[],
                changed_requirements=None,
                case_id=f"continuation003-holdout-{index:02d}-{family}",
                max_steps=18,
                goal="请根据这次登记的业务条件比较两个能碳方案，补齐缺项并逐项核验，给出有证据的最终结论；遇到回执未知先读回，目标改变后按新条件核验。",
            )
            facts = []
            for path in case["receipt_files"]:
                receipt = read_receipt(path)
                facts.append(check_receipt(receipt, receipt["parameters"]))
            costs = [f[1]["cost_cny"] for f in facts]
            reductions = [(f[0]["carbon_kg"] - f[1]["carbon_kg"]) / f[0]["carbon_kg"] * 100 for f in facts]
            goal = dict(
                max_cost_cny=round(max(costs) + 247.125 + index * 41.125 + fi * 9.125, 3),
                min_service_pct=96.3125 + index * 0.1875,
            )
            if max(reductions) > 0:
                goal["min_carbon_reduction_pct"] = round(max(reductions) * (0.37 + 0.03 * index + 0.007 * fi), 6)
            if index == 2:
                goal = dict(max_cost_cny=round(min(costs) - 463.125 - fi * 19.125, 3), min_service_pct=96.6875)
            task["requirements"] = goal
            if family == "clarification":
                key = ["carbon_price_cny_per_ton", "baseline_green_preference", "requirements"][index]
                task["scripted_replies"] = {key: task[key]}
                task[key] = None
            elif family == "unknown_receipt":
                task["lose_response_candidates"] = [[0, 1], [0], [1]][index]
            elif family == "changed_goal":
                task["requirements"] = dict(max_cost_cny=round(max(costs) + 1123.375, 3), min_service_pct=95.8125)
                task["changed_requirements"] = goal
                task["change_after_calculations"] = 2
            case["task"] = asdict(ExpertTask(**task))
            case["configuration_index"] = 200 + index
            case["source_training_configuration"] = config
            allowed = [
                i
                for i, f in enumerate(facts)
                if assess_energy_option(*f, goal)["status"] == "meets_registered_requirements"
            ]
            if bool(allowed) != (index != 2):
                raise ValueError("Numerical holdout label not supported")
            labels.append(
                dict(
                    case_id=task["case_id"],
                    expected_outcome="verified_candidate_recommended"
                    if allowed
                    else "no_registered_candidate_meets_requirements",
                    allowed_recommendation_indices=allowed,
                )
            )
            rows.append(case)
    return rows, labels


def prepare(out):
    verify_probe(EXPERT / "continuation-003/observation-probe-001")
    for name, expected in read(DATA / "DATA_LOCK.json")["artifact_hashes"].items():
        if sha(DATA / name) != expected:
            raise ValueError("Recovery data drift")
    if sha(REGISTRY) != REGISTRY_SHA:
        raise ValueError("Current registry drift")
    out.mkdir(parents=True, exist_ok=False)
    states = read(DATA / "STATES.json")
    cases = read(DATA / "CASES.json")
    gold = {r["case_id"]: r for r in read(DATA / "TRAIN_GOLD.json")}
    gate = [dict(kind="expert", case_id=c["task"]["case_id"], case=c, gold=gold[c["task"]["case_id"]]) for c in cases]
    provenance = read(EXPERT / "continuation-002/RETENTION_SOURCES.json")
    jobpaths = [p for p in provenance if "/round-001/runs/" in p and p.endswith("/job.json")]
    if len(jobpaths) != 24:
        raise ValueError("Expected exactly24 old training anchor jobs")
    for path in jobpaths:
        if sha(Path(path)) != provenance[path]:
            raise ValueError("Legacy source drift")
        job = read(Path(path))
        gate.append(
            dict(
                kind="legacy",
                case_id=job["task"]["case_id"],
                job={k: job[k] for k in ["task", "environment"] if k in job},
                prompt_mode="port_task_nouns",
                source_job=path,
            )
        )
    if len({g["case_id"] for g in gate}) != 48:
        raise ValueError("Duplicate gate identity")
    seed = 20261105
    order = balanced_order(states, seed)
    exposures = collections.Counter(s for row in order for s in row["states"])
    if set(exposures) != {s["state_id"] for s in states}:
        raise ValueError("Training coverage missing")
    parent = read(EXPERT / "continuation-003/RECOVERY_DESIGN.json")["common_warm_start_parent"]
    cfg = dict(
        time=now(),
        stage="common_supervised_recovery_warm_start",
        seed=seed,
        max_updates=512,
        batch_size=12,
        new_per_update=8,
        legacy_per_update=4,
        lr_initial=2e-4,
        lr_final=2e-5,
        optimizer="AdamW",
        betas=[0.9, 0.999],
        epsilon=1e-8,
        weight_decay=0.0,
        gradient_clip=1.0,
        objective="mean13-action supervised cross entropy, temperature1; no KL or entropy term",
        parent=parent,
        threads=4,
        cache_limit_gib=3,
        cache_dir=str(EXPERT / "continuation-003/frozen-prefix-cache"),
        data_root=str(DATA),
        data_lock_sha256=sha(DATA / "DATA_LOCK.json"),
        original_registry=str(REGISTRY),
        original_registry_sha256=REGISTRY_SHA,
        gate_interval=64,
        gate_cases=48,
        gate_new_cases=24,
        gate_old_cases=24,
        selection="First second consecutive all48-correct TRAINING gate spaced64updates; else final512 marked not_ready. Every checkpoint retained.",
        deployment_gate=False,
        heldout_model_access=False,
        later_RL="Separately frozen full-policy episodes and normal SFT from the same ready warm-start; no RL training in this stage.",
        evaluation=dict(
            new_cases=12,
            repetitions=2,
            legacy_cases=30,
            legacy_repetitions=2,
            native_cases=4,
            per_route_gate="24/24 new,60/60 legacy,4/4 native; retain joint outcome and primary RL outcome",
            open_after="Warm readiness, separately frozen RL/SFT routes, trained adapter audits, separate final evaluator lock",
        ),
    )
    save(out / "CONFIG.json", cfg)
    save(out / "STATES.json", states)
    save(out / "ORDER.json", order)
    save(out / "GATE_CASES.json", gate)
    save(
        out / "ORDER_AUDIT.json",
        dict(
            states=len(states),
            updates=512,
            total_exposures=6144,
            min_state_exposure=min(exposures.values()),
            max_state_exposure=max(exposures.values()),
            exposures=dict(exposures),
            new_class_balance=True,
        ),
    )
    rows, labels = holdout(cases)
    save(out / "sealed-test/tasks.json", rows)
    save(out / "sealed-test/oracle-labels.json", labels)
    save(
        out / "DATA_SPLIT.json",
        dict(
            training_states=360,
            source_records=423,
            train_new_cases=24,
            train_legacy_anchors=24,
            new_holdout_conditions=12,
            feasible=8,
            no_registered_candidate=4,
            physical_windows=1,
            scope="New constraint/event combinations on known training physics, not independent ports.",
            old_opened_test_parsed=False,
            new_holdout_model_calls=0,
            new_holdout_environment_rollouts=0,
            label_check="Numerical native receipt assessment only; no model scoring or parameter selection.",
        ),
    )
    save(
        out / "PROVENANCE.json",
        {
            **read(DATA / "SOURCE_MANIFEST.json"),
            **{p: provenance[p] for p in jobpaths},
            str(DATA / "DATA_LOCK.json"): sha(DATA / "DATA_LOCK.json"),
        },
    )
    save(out / "STATUS.json", dict(time=now(), phase="prepared_not_frozen", training_started=False))
    print({"prepared": str(out), "updates_cap": 512, "training_states": 360, "holdout_conditions": 12})


def freeze(out):
    if (out / "LOCK.json").exists():
        raise ValueError("Already frozen")
    if not read(out / "ENGINEERING_CHECKS.json")["passed"]:
        raise ValueError("Engineering checks required")
    if not read(out / "GATE_FIXTURE_AUDIT.json")["passed"] or not read(out / "CE_ARITHMETIC.json")["passed"]:
        raise ValueError("Independent gate fixtures and objective arithmetic required")
    sources = read(EXPERT / "continuation-003/observation-probe-001/SOURCES.json")
    sources.update(read(EXPERT / "training-001/SOURCES.json"))
    names = [
        "agent_expert_recovery_support.py",
        "freeze_agent_expert_recovery.py",
        "train_agent_expert_recovery.py",
        "audit_agent_expert_recovery_training.py",
        "run_agent_expert_recovery_queue.py",
        "serve_agent_expert_registry.py",
        "train_agent_expert_continuation.py",
        "audit_agent_capability_adaptation.py",
    ]
    paths = [ROOT / "scripts" / name for name in names] + [ROOT / "tests/test_agent_expert_recovery_training.py"]
    for p in paths:
        sources[str(p)] = sha(p)
    for p in (ROOT / "app/agent_training").glob("*.py"):
        sources[str(p)] = sha(p)
    for path in sources:
        p = Path(path)
        dest = out / "sources" / p.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
    save(out / "SOURCES.json", sources)
    names = [
        "CONFIG.json",
        "STATES.json",
        "ORDER.json",
        "GATE_CASES.json",
        "ORDER_AUDIT.json",
        "DATA_SPLIT.json",
        "PROVENANCE.json",
        "SOURCES.json",
        "ENGINEERING_CHECKS.json",
        "GATE_FIXTURE_AUDIT.json",
        "CE_ARITHMETIC.json",
        "sealed-test/tasks.json",
        "sealed-test/oracle-labels.json",
    ]
    save(out / "LOCK.json", {n: sha(out / n) for n in names})
    verify(out)
    save(out / "STATUS.json", dict(time=now(), phase="frozen_ready_not_started", training_started=False))


def verify(out):
    for name, expected in read(out / "LOCK.json").items():
        if sha(out / name) != expected:
            raise ValueError("Frozen protocol drift: " + name)
    for path, expected in read(out / "SOURCES.json").items():
        if sha(Path(path)) != expected or sha(out / "sources" / Path(path).relative_to(ROOT)) != expected:
            raise ValueError("Frozen source drift: " + path)
    for path, expected in read(out / "PROVENANCE.json").items():
        if sha(Path(path)) != expected:
            raise ValueError("Training provenance drift: " + path)
    for name, expected in read(DATA / "DATA_LOCK.json")["artifact_hashes"].items():
        if sha(DATA / name) != expected:
            raise ValueError("Training data drift")
    cfg = read(out / "CONFIG.json")
    if (
        sha(Path(cfg["parent"]["adapter"])) != cfg["parent"]["file_sha256"]
        or sha(REGISTRY) != cfg["original_registry_sha256"]
    ):
        raise ValueError("Parent/registry drift")
    return cfg


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["prepare", "freeze", "verify"])
    p.add_argument("--experiment", type=Path, required=True)
    a = p.parse_args()
    globals()[a.mode](a.experiment.resolve())
