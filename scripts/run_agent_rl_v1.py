"""Real local SFT + on-policy group-relative clipped policy-gradient experiment.

Only next-token choices among registered complete actions are trained. This is
not unrestricted JSON argument generation, full-scale GRPO, or a 4B experiment.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.environment import (  # noqa: E402
    FAMILIES,
    FAMILY_NAMES,
    LETTERS,
    REVISION,
    TaskEnvironment,
    digest,
    make_task,
    reference_action,
    run_reference,
)


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temp.replace(path)


def append(path, value):
    with Path(path).open("a") as f:
        f.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")


def prepare(output):
    splits = {
        split: [make_task(split, f, i) for f in FAMILIES for i in range(n)]
        for split, n in [("train", 6), ("validation", 2), ("test", 3)]
    }
    manifest = {
        "schema": "xiaoyi-agent-task-manifest.v1",
        "environment": REVISION,
        "split_rule": "disjoint case seeds; test green/carbon combinations held out; fixed known tool/fault families",
        "scope": "8 bounded synthetic tool-workflow families; not all 60 roadmap capabilities",
        "families": FAMILY_NAMES,
        "partitions": {},
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    for split, tasks in splits.items():
        rows = [asdict(t) for t in tasks]
        manifest["partitions"][split] = {
            "cases": len(rows),
            "sha256": digest(rows),
            "case_ids": [t.case_id for t in tasks],
        }
        save(output / "tasks" / f"{split}.json", rows)
    save(output / "task-manifest.json", manifest)
    return splits, manifest


def demonstrations(tasks):
    rows = []
    for task in tasks:
        env = TaskEnvironment(task)
        while not env.done:
            prompt = env.prompt()
            label = reference_action(env)
            rows.append({"case_id": task.case_id, "family": task.family, "prompt": prompt, "choice": label})
            env.step(label)
        if not env.success:
            raise AssertionError("demonstrator failed")
    return rows


def rollout(policy, task, *, sample=False, temperature=1.0):
    env = TaskEnvironment(task)
    decisions = []
    while not env.done:
        prompt = env.prompt()
        label, meta = policy.choose(prompt, sample=sample, temperature=temperature)
        transition = env.step(label)
        decisions.append(
            {
                "prompt": prompt,
                "label": label,
                "old_logp": meta["log_probability"],
                "inference_seconds": meta["seconds"],
                "transition": transition,
            }
        )
    return env, decisions


def evaluate(policy, tasks, name, output, *, rule=False):
    rows = []
    for i, task in enumerate(tasks):
        started = time.monotonic()
        if rule:
            env = run_reference(task)
            decisions = []
        else:
            env, decisions = rollout(policy, task)
        row = env.outcome()
        row["elapsed_seconds"] = round(time.monotonic() - started, 4)
        rows.append(row)
        save(
            output / "trajectories" / name / (task.case_id + ".json"),
            {"task": asdict(task), "outcome": row, "steps": env.steps, "decisions": decisions},
        )
        print(
            json.dumps(
                {
                    "stage": "evaluation",
                    "group": name,
                    "case": i + 1,
                    "total": len(tasks),
                    "success": row["success"],
                    "case_id": task.case_id,
                }
            ),
            flush=True,
        )
    groups = {f: [r for r in rows if r["family"] == f] for f in FAMILIES}
    fault = [r for r in rows if r["fault_injected"]]
    result = {
        "group": name,
        "n": len(rows),
        "success_rate": sum(r["success"] for r in rows) / len(rows),
        "macro_success_rate": sum(sum(r["success"] for r in v) / len(v) for v in groups.values()) / len(groups),
        "by_family": {
            f: {
                "n": len(v),
                "successes": sum(r["success"] for r in v),
                "success_rate": sum(r["success"] for r in v) / len(v),
            }
            for f, v in groups.items()
        },
        "mean_steps": sum(r["steps"] for r in rows) / len(rows),
        "mean_seconds": sum(r["elapsed_seconds"] for r in rows) / len(rows),
        "parameter_accuracy": sum(r["parameter_correct"] for r in rows)
        / max(1, sum(r["parameter_attempts"] for r in rows)),
        "fault_cases": len(fault),
        "recovery_rate": sum(r["recovered"] for r in fault) / len(fault) if fault else None,
        "cases": rows,
    }
    save(output / "evaluations" / (name + ".json"), result)
    return result


RETENTION = [
    ("港口的泊位主要用于什么？ A:船舶停靠作业 B:飞机起降", "A"),
    ("岸电主要指什么？ A:船上柴油发电 B:船舶靠港使用岸上供电", "B"),
    ("1兆瓦等于多少千瓦？ A:1000 B:100", "A"),
    ("报告数字缺少来源，应如何处理？ A:编一个合理数 B:说明缺失并核查", "B"),
    ("工具返回超时，能否直接声称执行成功？ A:可以 B:不能，应核验", "B"),
    ("用户明确说只读，应该怎样做？ A:只读取信息 B:直接改参数", "A"),
    ("给出3加5的结果。 A:8 B:15", "A"),
    ("两个方案分别便宜和低碳，怎样说明？ A:说明权衡 B:说便宜的一定低碳", "A"),
]


def retention(policy, name, output):
    rows = []
    for prompt, expected in RETENTION:
        label, meta = policy.choose(prompt)
        rows.append(
            {
                "prompt": prompt,
                "expected": expected,
                "choice": label,
                "correct": label == expected,
                "seconds": meta["seconds"],
            }
        )
    result = {
        "group": name,
        "n": len(rows),
        "accuracy": sum(r["correct"] for r in rows) / len(rows),
        "scope": "8 fixed multiple-choice regression probes; not a general knowledge benchmark",
        "rows": rows,
    }
    save(output / "retention" / (name + ".json"), result)
    return result


def train(args):
    from app.agent_training.policy import LanguagePolicy, BASE

    output = args.output
    if (output / "training.jsonl").exists():
        raise SystemExit("use a fresh run directory; prior evidence is never overwritten")
    output.mkdir(parents=True, exist_ok=True)
    splits, manifest = prepare(output)
    config = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    config.update(
        {
            "method": "LoRA SFT then group-relative clipped policy gradient on constrained action tokens",
            "base_model": str(BASE),
            "task_manifest_sha256": digest(manifest),
            "no_external_teacher": True,
            "model_scale": "1.7B",
            "original_4b_modified": False,
            "test_used_for_selection": False,
            "training_environment": "synthetic_resettable",
            "action_space": "13 displayed bounded tool/parameter candidates; same for all groups",
        }
    )
    save(output / "config.json", config)
    source_manifest = []
    import shutil

    for source in [ROOT / "app/agent_training/environment.py", ROOT / "app/agent_training/policy.py", Path(__file__)]:
        relative = source.relative_to(ROOT)
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        source_manifest.append({"path": str(relative), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    save(output / "source-manifest.json", source_manifest)
    started = time.monotonic()

    def status(stage, **extra):
        save(output / "status.json", {"stage": stage, "elapsed_seconds": round(time.monotonic() - started, 2), **extra})

    status("loading_model")
    policy = LanguagePolicy(threads=args.threads, seed=args.seed)
    torch = policy.torch
    initial = policy.state()
    before_hash = policy.fingerprint()
    resumed_steps = 0
    if args.resume_sft:
        from safetensors.torch import load_file
        from peft import set_peft_model_state_dict

        parent = args.resume_sft.resolve()
        parent_manifest = json.loads((parent / "task-manifest.json").read_text())
        if parent_manifest["partitions"]["train"]["sha256"] != manifest["partitions"]["train"]["sha256"]:
            raise ValueError("resume SFT dataset does not match")
        adapter = parent / "checkpoints/sft/adapter_model.safetensors"
        set_peft_model_state_dict(policy.model, load_file(str(adapter)))
        for line in (parent / "training.jsonl").read_text().splitlines():
            row = json.loads(line)
            if row["stage"] == "sft":
                append(output / "training.jsonl", row)
                resumed_steps += 1
        save(
            output / "sft-lineage.json",
            {
                "parent": str(parent),
                "steps": resumed_steps,
                "adapter_file_sha256": hashlib.sha256(adapter.read_bytes()).hexdigest(),
                "adapter_parameter_sha256": policy.fingerprint(),
                "retrained": False,
            },
        )
    save(
        output / "cpu-cache-verification.json", policy.verify_prefix_cache(TaskEnvironment(splits["train"][0]).prompt())
    )
    examples = demonstrations(splits["train"])
    save(output / "sft-demonstrations.json", examples)
    rng = random.Random(args.seed)
    order = list(range(len(examples)))
    rng.shuffle(order)
    optimizer = torch.optim.AdamW(policy.parameters, lr=args.sft_lr)
    policy.model.train()
    for step in range(0 if args.resume_sft else args.sft_steps):
        row = examples[order[step % len(order)]]
        t0 = time.monotonic()
        optimizer.zero_grad(set_to_none=True)
        logits = policy.logits(row["prompt"])
        loss = torch.nn.functional.cross_entropy(logits.unsqueeze(0), torch.tensor([LETTERS.index(row["choice"])]))
        if not torch.isfinite(loss):
            raise RuntimeError("nonfinite SFT loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(policy.parameters, 1.0)
        optimizer.step()
        record = {
            "stage": "sft",
            "step": step + 1,
            "loss": float(loss.detach()),
            "family": row["family"],
            "seconds": round(time.monotonic() - t0, 3),
        }
        append(output / "training.jsonl", record)
        print(json.dumps(record), flush=True)
        status("sft", step=step + 1, total=args.sft_steps)
    policy.model.eval()
    sft = policy.state()
    sft_hash = policy.fingerprint()
    policy.save(output / "checkpoints" / "sft")
    status("validation_sft")
    val_sft = evaluate(policy, splits["validation"], "C_sft_validation", output)
    optimizer = torch.optim.AdamW(policy.parameters, lr=args.rl_lr)
    reference_cache = {}
    for group in range(args.rl_groups):
        task = splits["train"][(group % len(FAMILIES)) * 6 + (group // len(FAMILIES)) % 6]
        current = policy.state()
        episodes = []
        for rep in range(args.group_size):
            env, decisions = rollout(policy, task, sample=True, temperature=args.temperature)
            episodes.append((env, decisions))
            save(
                output / "rollouts" / f"group-{group:03d}-{rep}.json",
                {"task": asdict(task), "outcome": env.outcome(), "steps": env.steps, "decisions": decisions},
            )
        scores = [env.outcome()["reward"] for env, _ in episodes]
        mean = sum(scores) / len(scores)
        std = math.sqrt(sum((s - mean) ** 2 for s in scores) / len(scores))
        advantages = [(score - mean) / (std + 1e-6) for score in scores]
        all_prompts = {d["prompt"] for _, ds in episodes for d in ds}
        policy.load_state(sft)
        with torch.no_grad():
            for prompt in all_prompts:
                key = digest(prompt)
                if key not in reference_cache:
                    reference_cache[key] = torch.log_softmax(policy.logits(prompt) / args.temperature, 0).detach()
        policy.load_state(current)
        losses = []
        grad_norm = 0.0
        if std > 1e-8:
            optimizer.zero_grad(set_to_none=True)
            for adv, (env, decisions) in zip(advantages, episodes):
                for decision in decisions:
                    logits = policy.logits(decision["prompt"]) / args.temperature
                    logp = torch.log_softmax(logits, 0)
                    probs = logp.exp()
                    picked = logp[LETTERS.index(decision["label"])]
                    ratio = (picked - decision["old_logp"]).exp()
                    gain = torch.minimum(ratio * adv, torch.clamp(ratio, 0.8, 1.2) * adv)
                    reference = reference_cache[digest(decision["prompt"])]
                    kl = (probs * (logp - reference)).sum()
                    entropy = -(probs * logp).sum()
                    loss = (-gain + args.kl_beta * kl - 0.002 * entropy) / (args.group_size * len(decisions))
                    if not torch.isfinite(loss):
                        raise RuntimeError("nonfinite RL loss")
                    loss.backward()
                    losses.append(float(loss.detach()))
            grad_norm = float(torch.nn.utils.clip_grad_norm_(policy.parameters, 1.0))
            optimizer.step()
        record = {
            "stage": "rl",
            "group": group + 1,
            "family": task.family,
            "scores": scores,
            "advantages": advantages,
            "successes": sum(env.success for env, _ in episodes),
            "loss": sum(losses),
            "gradient_norm": grad_norm,
            "updated": std > 1e-8,
            "adapter_sha256": policy.fingerprint(),
        }
        append(output / "training.jsonl", record)
        print(json.dumps(record), flush=True)
        status("rl", group=group + 1, total=args.rl_groups)
    rl = policy.state()
    rl_hash = policy.fingerprint()
    policy.save(output / "checkpoints" / "rl")
    status("validation_rl")
    val_rl = evaluate(policy, splits["validation"], "D_rl_validation", output)
    # Selection is fixed before opening the held-out test. No test-driven tuning.
    save(
        output / "checkpoint-selection.json",
        {
            "selected": "rl",
            "rule": "final registered RL checkpoint; no test selection",
            "validation_sft": val_sft["success_rate"],
            "validation_rl": val_rl["success_rate"],
        },
    )
    results = {}
    retain = {}
    results["A_rules"] = evaluate(policy, splits["test"], "A_rules", output, rule=True)
    for name, state in [("B_base", initial), ("C_sft", sft), ("D_rl", rl)]:
        status("independent_test", group=name)
        policy.load_state(state)
        results[name] = evaluate(policy, splits["test"], name, output)
        retain[name] = retention(policy, name, output)
    summary = {
        "schema": "xiaoyi-language-agent-rl-experiment.v1",
        "status": "completed",
        "training_performed": True,
        "model_scale": "1.7B",
        "seed": args.seed,
        "training_seeds": 1,
        "trainable_parameters": sum(p.numel() for p in policy.parameters),
        "weights": {"initial": before_hash, "sft": sft_hash, "rl": rl_hash},
        "sft_parameters_changed": before_hash != sft_hash,
        "rl_parameters_changed": sft_hash != rl_hash,
        "groups": results,
        "retention": retain,
        "rl_increment": results["D_rl"]["success_rate"] - results["C_sft"]["success_rate"],
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "config": config,
        "limitations": [
            "single training seed, 24 held-out synthetic cases",
            "constrained candidate action/parameter selection, not free-form tool generation",
            "known tool/fault families with held-out numeric combinations, not unseen task families",
            "live multi-system acceptance is separate and not part of held-out scores",
            "4B and previous domain RL weights unchanged",
            "8 regression questions are not broad retention proof",
        ],
    }
    save(output / "summary.json", summary)
    status("completed", summary="summary.json", rl_increment=summary["rl_increment"])
    print(json.dumps({"completed": True, "output": str(output), "rl_increment": summary["rl_increment"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume-sft", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261101)
    parser.add_argument("--sft-steps", type=int, default=80)
    parser.add_argument("--sft-lr", type=float, default=1e-4)
    parser.add_argument("--rl-groups", type=int, default=16)
    parser.add_argument("--group-size", type=int, default=3)
    parser.add_argument("--rl-lr", type=float, default=4e-5)
    parser.add_argument("--temperature", type=float, default=1.5)
    parser.add_argument("--kl-beta", type=float, default=0.03)
    args = parser.parse_args()
    if args.prepare_only:
        prepare(args.output)
        print("task partitions prepared")
    else:
        train(args)


if __name__ == "__main__":
    main()
