"""Auditable CPU experiment: two-step model-based actor RL vs continued SFT.

Development never reads test tasks. Final evaluation is a separate command
requiring frozen checkpoint selection. All learned groups share the same input.
"""

from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.environment import FAMILIES, LETTERS, TaskSpec, digest, reference_action  # noqa: E402
from app.agent_training.environment_v2 import (  # noqa: E402
    REVISION,
    ProgressEnvironment,
    build_state_pool,
    make_task_v2,
)
from scripts.run_agent_rl_v1 import save, append, retention  # noqa: E402

PARENT = ROOT / ".codex_artifacts/agent-rl-v1-20261101/experiment-003"
SOURCE_FILES = [
    "app/agent_training/environment.py",
    "app/agent_training/environment_v2.py",
    "app/agent_training/policy.py",
    "app/agent_training/policy_v2.py",
    "scripts/run_agent_rl_v1.py",
    "scripts/run_agent_rl_v2.py",
    "tests/test_agent_training_v2.py",
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def prepare(args):
    out = args.output
    if out.exists():
        raise ValueError("new output required; previous evidence is never overwritten")
    out.mkdir(parents=True)
    splits = {
        split: [make_task_v2(split, f, i) for f in FAMILIES for i in range(n)]
        for split, n in [("train", 6), ("validation", 2), ("test", 3)]
    }
    protocol = {
        "schema": "xiaoyi-agent-rl.v2",
        "environment": REVISION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "method": "exact categorical actor objective with two-step simulator lookahead; KL to frozen SFT",
        "not_claimed": "not full long-horizon PPO/GRPO; not unrestricted JSON or arbitrary parameter generation",
        "model": "Qwen3-1.7B float32; 229376 LoRA parameters in last 4 layers",
        "seed": 20261102,
        "temperature": 2.0,
        "learning_rate": 0.0002,
        "kl_coefficient": 0.02,
        "entropy_coefficient": 0.001,
        "gradient_clip": 1.0,
        "weight_decay": 0.0,
        "milestones": [128, 256, 512],
        "checkpoint_every": 32,
        "log_every_update": True,
        "selection": "validation success count, then fewer errors, then fewer calls, then earlier step; retention >= frozen C",
        "early_stop": "per group stop only at 16/16 validation with zero avoidable errors and unchanged retention",
        "C_parent": str(PARENT),
        "C_adapter_file_sha256": sha(PARENT / "checkpoints/sft/adapter_model.safetensors"),
        "control": "E: continued cross-entropy SFT; same C, state pool, order, LR, update cap and validation selection; measured compute need not be identical",
        "reward": "potential shaping 2*(Phi_next-Phi), terminal Phi=0; step -0.1; invalid -0.2; no state progress -0.2; success +3; budget failure -1",
        "state_pool": "reference-path states plus rejected-report branches at first two states; same exposure for D and E",
        "rl_label_access": False,
        "live_api_calls_during_training": False,
        "test_used_for_selection": False,
        "production_authority": False,
        "test_scope": "known task/tool/fault families; new numerical grids and held-out introductory wording only; not unseen task compositions",
        "prior_negative_run": str(PARENT),
        "old_test_disclosed": True,
    }
    save(out / "config.json", protocol)
    manifest = {"environment": REVISION, "partitions": {}, "initial_prompt_overlap": {}}
    prompt_sets = {}
    for split, tasks in splits.items():
        rows = [asdict(t) for t in tasks]
        prompts = [ProgressEnvironment(t).prompt() for t in tasks]
        prompt_sets[split] = set(prompts)
        manifest["partitions"][split] = {
            "cases": len(rows),
            "sha256": digest(rows),
            "unique_initial_prompts": len(set(prompts)),
            "case_ids": [t.case_id for t in tasks],
        }
        save(out / "tasks" / (split + ".json"), rows)
    for a, b in [("train", "validation"), ("train", "test"), ("validation", "test")]:
        manifest["initial_prompt_overlap"][a + "/" + b] = len(prompt_sets[a] & prompt_sets[b])
    if any(manifest["initial_prompt_overlap"].values()):
        raise ValueError("exact input overlap across splits")
    save(out / "task-manifest.json", manifest)
    records = build_state_pool(splits["train"])
    for record in records:
        branches = record.pop("counterfactuals")
        rel = "counterfactuals/" + record["state_id"] + ".json"
        save(out / rel, branches)
        record["counterfactual_file"] = rel
        record["counterfactual_sha256"] = sha(out / rel)
    save(out / "training-states.json", records)
    from transformers import AutoTokenizer
    from app.agent_training.policy import BASE, SYSTEM

    tok = AutoTokenizer.from_pretrained(BASE, local_files_only=True)

    def length(prompt):
        return len(
            tok.apply_chat_template(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                tokenize=True,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        )

    lengths = [length(r["prompt"]) for r in records]
    if max(lengths) > 768:
        raise ValueError("registered context budget exceeded")
    integrity = {
        "training_states": len(records),
        "states_sha256": digest(records),
        "family_counts": dict(Counter(r["task"]["family"] for r in records)),
        "origin_counts": dict(Counter(r["origin"] for r in records)),
        "max_train_tokens": max(lengths),
        "mean_train_tokens": sum(lengths) / len(lengths),
        "counterfactual_branches": sum(len(LETTERS) + len(LETTERS) ** 2 for _ in records),
        "counterfactual_count_note": "upper bound; terminal first actions have no second expansion",
    }
    save(out / "dataset-integrity.json", integrity)
    sources = []
    for rel in SOURCE_FILES:
        dest = out / "source" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
        sources.append({"path": rel, "sha256": sha(dest)})
    save(out / "source-manifest.json", sources)
    save(out / "status.json", {"stage": "prepared", "protocol_sha256": sha(out / "config.json")})
    print(json.dumps(integrity), flush=True)


def task_rows(out, split):
    rows = load(out / "tasks" / (split + ".json"))
    expected = load(out / "task-manifest.json")["partitions"][split]["sha256"]
    if digest(rows) != expected:
        raise ValueError("task file checksum mismatch")
    return [TaskSpec(**r) for r in rows]


def evaluate(policy, tasks, name, out, rule=False):
    rows = []
    for task in tasks:
        path = out / "trajectories" / name / (task.case_id + ".json")
        if path.exists():
            raise ValueError("evaluation evidence already exists")
        env, decisions = ProgressEnvironment(task), []
        started = time.monotonic()
        while not env.done:
            prompt = env.prompt()
            if rule:
                label, meta = reference_action(env), {"model_used": False}
            else:
                label, meta = policy.choose(prompt)
            row = env.step(label)
            if rule:
                row["model_action"] = False
                row["origin"] = "fixed_rule_baseline"
            decisions.append({"prompt": prompt, "label": label, **meta})
        outcome = env.outcome()
        # Parameter correctness is an attempt-level metric even if prerequisites
        # fail; execution correctness is separately retained in env.outcome.
        attempts = [s for s in env.steps if s["action"]["tool"] == "energy.compare"]
        outcome["parameter_matches"] = sum(
            s["action"]["arguments"]["green_preference"] == task.green
            and s["action"]["arguments"]["carbon_price_cny_per_ton"] == task.carbon
            for s in attempts
        )
        outcome["elapsed_seconds"] = round(time.monotonic() - started, 4)
        rows.append(outcome)
        save(path, {"task": asdict(task), "outcome": outcome, "steps": env.steps, "decisions": decisions})
        print(
            json.dumps(
                {
                    "stage": "evaluation",
                    "group": name,
                    "case": task.case_id,
                    "success": env.success,
                    "steps": len(env.steps),
                }
            ),
            flush=True,
        )
    faults = [r for r in rows if r["family"] in {"read_recovery", "write_recovery"}]
    attempts = sum(r["parameter_attempts"] for r in rows)
    result = {
        "group": name,
        "n": len(rows),
        "successes": sum(r["success"] for r in rows),
        "success_rate": sum(r["success"] for r in rows) / len(rows),
        "mean_steps": sum(r["steps"] for r in rows) / len(rows),
        "mean_reward": sum(r["reward"] for r in rows) / len(rows),
        "total_errors": sum(r["errors"] for r in rows),
        "parameter_attempts": attempts,
        "parameter_accuracy": sum(r["parameter_matches"] for r in rows) / attempts if attempts else None,
        "fault_cases": len(faults),
        "fault_exposed_cases": sum(r["fault_injected"] for r in faults),
        "recovery_rate": sum(r["recovered"] for r in faults) / len(faults) if faults else None,
        "by_family": {
            f: {
                "n": len([r for r in rows if r["family"] == f]),
                "successes": sum(r["success"] for r in rows if r["family"] == f),
            }
            for f in FAMILIES
        },
        "cases": rows,
    }
    save(out / "evaluations" / (name + ".json"), result)
    return result


def init_policy(args):
    from app.agent_training.policy_v2 import CachedLanguagePolicy
    from safetensors.torch import load_file
    from peft import set_peft_model_state_dict

    cfg = load(args.output / "config.json")
    policy = CachedLanguagePolicy(
        cache_dir=args.output.parent / "frozen-prefix-cache", threads=args.threads, seed=cfg["seed"]
    )
    initial = policy.state()
    base_hash = policy.fingerprint()
    parent = Path(cfg["C_parent"]) / "checkpoints/sft/adapter_model.safetensors"
    if sha(parent) != cfg["C_adapter_file_sha256"]:
        raise ValueError("C checkpoint changed")
    set_peft_model_state_dict(policy.model, load_file(str(parent)))
    return policy, initial, base_hash


def checkpoint(policy, optimizer, out, phase, step, cfg, order, rng):
    folder = out / "checkpoints" / phase / f"step-{step:05d}"
    if folder.exists():
        raise ValueError("checkpoint already exists")
    policy.save(folder)
    policy.torch.save(
        {
            "optimizer": optimizer.state_dict(),
            "torch_rng": policy.torch.get_rng_state(),
            "python_rng": rng.getstate(),
            "order": order,
            "step": step,
            "phase": phase,
            "config_sha256": digest(cfg),
        },
        folder / "optimizer-rng.pt",
    )
    save(
        folder / "metadata.json",
        {
            "phase": phase,
            "step": step,
            "parameter_sha256": policy.fingerprint(),
            "adapter_file_sha256": sha(folder / "adapter_model.safetensors"),
        },
    )


def development(args):
    out = args.output
    if (out / "training.jsonl").exists() or (out / "development-start.json").exists():
        raise ValueError("development already started; evidence is not overwritten")
    cfg = load(out / "config.json")
    states = load(out / "training-states.json")
    if digest(states) != load(out / "dataset-integrity.json")["states_sha256"]:
        raise ValueError("training state checksum mismatch")
    save(
        out / "development-start.json",
        {"pid": os.getpid(), "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "config_sha256": sha(out / "config.json")},
    )
    started = time.monotonic()

    def status(stage, **extra):
        save(out / "status.json", {"stage": stage, "seconds": time.monotonic() - started, **extra})

    status("loading_model")
    policy, initial, initial_hash = init_policy(args)
    torch = policy.torch
    frozen = policy.state()
    frozen_hash = policy.fingerprint()
    policy.save(out / "checkpoints/sft")
    status("verifying_exact_cache")
    check = policy.verify_prefix_cache(states[0]["prompt"])
    policy.prefix_cache.clear()
    with torch.no_grad():
        disk = policy.logits(states[0]["prompt"])
        full = policy.model(**policy.batch(states[0]["prompt"]), logits_to_keep=1).logits[0, -1, policy.ids]
    check["disk_logit_max_absolute_error"] = float((disk - full).abs().max())
    if check["disk_logit_max_absolute_error"] > 1e-4:
        raise ValueError("disk cache mismatch")
    save(out / "cpu-cache-verification.json", check)
    val = task_rows(out, "validation")
    status("C_validation")
    baseline = evaluate(policy, val, "validation-C_sft", out)
    baseline_retention = retention(policy, "validation-C_sft", out)
    save(out / "lineage.json", {"initial": initial_hash, "sft": frozen_hash, "parent": cfg["C_parent"]})
    references = {}
    selected = {}
    for phase in ["D_rl", "E_more_sft"]:
        policy.load_state(frozen)
        policy.model.eval()  # dropout=0; autograd remains enabled
        optimizer = torch.optim.AdamW(policy.parameters, lr=cfg["learning_rate"], weight_decay=cfg["weight_decay"])
        rng = random.Random(cfg["seed"])
        order = list(range(len(states)))
        candidates = []
        for i in range(max(cfg["milestones"])):
            if i % len(states) == 0:
                rng.shuffle(order)
            record = states[order[i % len(states)]]
            step = i + 1
            status("training", phase=phase, step=step, max_steps=max(cfg["milestones"]))
            tick = time.monotonic()
            optimizer.zero_grad(set_to_none=True)
            key = record["state_id"]
            if phase == "D_rl" and key not in references:
                current = policy.state()
                policy.load_state(frozen)
                with torch.no_grad():
                    references[key] = policy.logits(record["prompt"]).detach().clone()
                policy.load_state(current)
                append(
                    out / "frozen-reference-logits.jsonl",
                    {"state_id": key, "logits": references[key].tolist(), "C_parameter_sha256": frozen_hash},
                )
            logits = policy.logits(record["prompt"])
            probs = torch.softmax(logits / cfg["temperature"], 0)
            logp = torch.log_softmax(logits / cfg["temperature"], 0)
            entropy = -(probs * logp).sum()
            before_probs = probs.detach().tolist()
            extra = {}
            if phase == "D_rl":
                # No sft_target access in the RL objective.
                returns = torch.tensor(record["rewards"], dtype=torch.float32)
                advantages = (returns - returns.mean()) / returns.std(unbiased=False).clamp(min=0.1)
                ref_logp = torch.log_softmax(references[key] / cfg["temperature"], 0)
                kl = (probs * (logp - ref_logp)).sum()
                expected = (probs * returns).sum()
                loss = -(probs * advantages).sum() + cfg["kl_coefficient"] * kl - cfg["entropy_coefficient"] * entropy
                extra = {
                    "expected_two_step_return_before": float(expected.detach()),
                    "kl_to_frozen_sft": float(kl.detach()),
                    "action_returns": record["rewards"],
                    "advantage": advantages.tolist(),
                }
            else:
                target = LETTERS.index(record["sft_target"])
                loss = -torch.log_softmax(logits, 0)[target]
                extra = {"supervised_target": record["sft_target"]}
            if not torch.isfinite(loss):
                raise ValueError("nonfinite loss")
            loss.backward()
            grad = torch.nn.utils.clip_grad_norm_(policy.parameters, cfg["gradient_clip"])
            if not torch.isfinite(grad):
                raise ValueError("nonfinite gradient")
            optimizer.step()
            with torch.no_grad():
                after_probs = torch.softmax(policy.logits(record["prompt"]) / cfg["temperature"], 0)
            row = {
                "stage": phase,
                "step": step,
                "state_id": key,
                "case_id": record["task"]["case_id"],
                "family": record["task"]["family"],
                "state_origin": record["origin"],
                "loss": float(loss.detach()),
                "entropy": float(entropy.detach()),
                "gradient_norm_before_clip": float(grad),
                "learning_rate": cfg["learning_rate"],
                "seconds": time.monotonic() - tick,
                "probabilities_before": before_probs,
                "probabilities_after": after_probs.tolist(),
                "choice_before": LETTERS[max(range(13), key=lambda n: before_probs[n])],
                "choice_after": LETTERS[int(after_probs.argmax())],
                "cache": dict(policy.cache_stats),
                "parameter_sha256": policy.fingerprint(),
                **extra,
            }
            if phase == "D_rl":
                row["expected_two_step_return_after"] = float((after_probs * returns).sum())
            append(out / "training.jsonl", row)
            if step % 8 == 0:
                print(
                    json.dumps(
                        {k: row[k] for k in ["stage", "step", "loss", "seconds", "choice_before", "choice_after"]}
                    ),
                    flush=True,
                )
            if step % cfg["checkpoint_every"] == 0:
                checkpoint(policy, optimizer, out, phase, step, cfg, order, rng)
            if step in cfg["milestones"]:
                status("validation", phase=phase, step=step)
                name = f"validation-{phase}-{step}"
                result = evaluate(policy, val, name, out)
                keep = retention(policy, name, out)
                candidate = {
                    "step": step,
                    "checkpoint": f"checkpoints/{phase}/step-{step:05d}",
                    "parameter_sha256": policy.fingerprint(),
                    "validation": result,
                    "retention": keep,
                    "eligible": keep["accuracy"] >= baseline_retention["accuracy"],
                }
                candidates.append(candidate)
                append(
                    out / "validation-curve.jsonl",
                    {
                        "phase": phase,
                        "step": step,
                        "successes": result["successes"],
                        "mean_reward": result["mean_reward"],
                        "errors": result["total_errors"],
                        "mean_steps": result["mean_steps"],
                        "retention": keep["accuracy"],
                    },
                )
                # Required transient/lost-response faults each count as one error.
                if result["successes"] == len(val) and result["total_errors"] <= 4 and candidate["eligible"]:
                    break
        save(out / (phase + "-candidates.json"), candidates)
        eligible = [c for c in candidates if c["eligible"]]
        if not eligible:
            selected[phase] = {
                "checkpoint": "checkpoints/sft",
                "step": 0,
                "parameter_sha256": frozen_hash,
                "reason": "all adapted checkpoints failed retention constraint",
            }
        else:
            best = max(
                eligible,
                key=lambda c: (
                    c["validation"]["successes"],
                    -c["validation"]["total_errors"],
                    -c["validation"]["mean_steps"],
                    -c["step"],
                ),
            )
            selected[phase] = {k: best[k] for k in ["checkpoint", "step", "parameter_sha256"]}
            selected[phase]["validation_successes"] = best["validation"]["successes"]
    save(
        out / "checkpoint-selection.json",
        {
            "selected": selected,
            "selection_rule": cfg["selection"],
            "test_opened": False,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "config_sha256": sha(out / "config.json"),
            "baseline_validation": baseline["successes"],
        },
    )
    status("development_completed_test_unopened", selected=selected)


def final_test(args):
    out = args.output
    selection = load(out / "checkpoint-selection.json")
    if selection["test_opened"] or (out / "test-opened.json").exists():
        raise ValueError("final test already opened; never overwrite or reuse for selection")
    cfg = load(out / "config.json")
    if selection["config_sha256"] != sha(out / "config.json"):
        raise ValueError("protocol changed after selection")
    save(
        out / "test-opened.json",
        {"selection_sha256": sha(out / "checkpoint-selection.json"), "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
    )
    policy, initial, initial_hash = init_policy(args)
    frozen, frozen_hash = policy.state(), policy.fingerprint()
    from safetensors.torch import load_file
    from peft import set_peft_model_state_dict

    tasks = task_rows(out, "test")
    groups = {"A_rules": evaluate(None, tasks, "A_rules", out, rule=True)}
    holds = {}
    weights = {"initial": initial_hash, "sft": frozen_hash}
    for group in ["B_base", "C_sft", "D_rl", "E_more_sft"]:
        if group == "B_base":
            policy.load_state(initial)
        elif group == "C_sft":
            policy.load_state(frozen)
        else:
            selected = selection["selected"][group]
            set_peft_model_state_dict(
                policy.model, load_file(str(out / selected["checkpoint"] / "adapter_model.safetensors"))
            )
            if policy.fingerprint() != selected["parameter_sha256"]:
                raise ValueError("selected checkpoint identity mismatch")
            weights["rl" if group == "D_rl" else "more_sft"] = policy.fingerprint()
            policy.save(out / "checkpoints" / ("rl" if group == "D_rl" else "more_sft"))
        save(out / "status.json", {"stage": "final_test", "group": group})
        groups[group] = evaluate(policy, tasks, group, out)
        holds[group] = retention(policy, group, out)

    def paired(a, b):
        pairs = list(zip(groups[a]["cases"], groups[b]["cases"]))
        return {
            "failure_to_success": sum(not x["success"] and y["success"] for x, y in pairs),
            "success_to_failure": sum(x["success"] and not y["success"] for x, y in pairs),
        }

    summary = {
        "status": "completed_pending_audit",
        "seed": cfg["seed"],
        "groups": groups,
        "retention": holds,
        "weights": weights,
        "trainable_parameters": sum(p.numel() for p in policy.parameters),
        "rl_parameters_changed": weights["rl"] != weights["sft"],
        "rl_increment": groups["D_rl"]["success_rate"] - groups["C_sft"]["success_rate"],
        "rl_vs_continued_sft": groups["D_rl"]["success_rate"] - groups["E_more_sft"]["success_rate"],
        "paired_rl_effect": paired("C_sft", "D_rl"),
        "paired_vs_continued_sft": paired("E_more_sft", "D_rl"),
        "environment": REVISION,
        "selection": selection,
        "scope": cfg["test_scope"],
        "training_counts": {
            p: max(
                r["step"] for r in map(json.loads, (out / "training.jsonl").read_text().splitlines()) if r["stage"] == p
            )
            for p in ["D_rl", "E_more_sft"]
        },
    }
    save(out / "summary.json", summary)
    save(out / "status.json", {"stage": "completed_pending_audit"})
    print(
        json.dumps(
            {"successes": {k: v["successes"] for k, v in groups.items()}, "rl_increment": summary["rl_increment"]}
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "develop", "test"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    args.output = args.output.resolve()
    {"prepare": prepare, "develop": development, "test": final_test}[args.mode](args)


if __name__ == "__main__":
    main()
