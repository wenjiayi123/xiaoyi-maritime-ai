"""CPU feasibility study with full-episode action-policy RL and strong SFT.

Each completed update has an immutable directory, checkpoint, optimizer/RNG
state, rollouts, and per-action arithmetic. Resume starts at the last committed
update; interrupted work is retained separately. No final-test command yet:
confirmatory multi-seed evaluation requires a separately frozen next protocol.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.environment import LETTERS, digest  # noqa: E402
from app.agent_training.environment_v3 import (  # noqa: E402
    DynamicEnvironment,
    DynamicTask,
    demonstrations,
    task_splits,
    teacher_action,
    REVISION,
)
from app.agent_training.objectives_v3 import action_loss, centered_advantages  # noqa: E402

PARENT = ROOT / ".codex_artifacts/agent-rl-v2-20261102/experiment-004"
SOURCES = [
    "app/agent_training/environment.py",
    "app/agent_training/environment_v3.py",
    "app/agent_training/policy.py",
    "app/agent_training/policy_v2.py",
    "app/agent_training/objectives_v3.py",
    "scripts/run_agent_rl_v3.py",
    "tests/test_agent_training_v3.py",
    "tests/test_agent_training_v3_objectives.py",
]


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(args):
    out = args.output
    if out.exists():
        raise ValueError("output must be new; previous runs are immutable")
    out.mkdir(parents=True)
    parent = PARENT / "checkpoints/E_more_sft/step-00384/adapter_model.safetensors"
    config = {
        "schema": "xiaoyi-agent-rl.v3-pilot",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": "feasibility_not_confirmatory",
        "environment": REVISION,
        "parent_adapter": str(parent),
        "parent_sha256": sha(parent),
        "parent_choice": "strongest continued-SFT checkpoint in frozen experiment-004; old test is disclosed",
        "seed": 20261102,
        "warmup_updates": 64,
        "groups": 8,
        "group_size": 4,
        "max_steps": 20,
        "temperature": 1.4,
        "learning_rate": 0.0001,
        "warmup_learning_rate": 0.0002,
        "kl_coefficient": 0.02,
        "clip": 0.2,
        "replay_beta": 0.1,
        "replay_start_group": 3,
        "replay_slot_fraction_max": 0.25,
        "validation_milestones": [0, 4, 8],
        "selection": "none in pilot; show all registered milestones",
        "groups_description": {
            "A_rules": "visible-state competent rules",
            "C_common_sft": "prior strongest SFT + shared 64-update dynamic-task warmup",
            "D_drgrpo": "on-policy episode-return group-relative clipped action-token RL",
            "E_more_sft": "same start and D-collected prompts, oracle corrections, same update/token budget",
            "F_experience": "same start; D loss plus ExGRPO-inspired historical success replay",
        },
        "source_status": "Dr.GRPO COLM2025 core; ExGRPO ICLR2026 mechanism, adapted not exact reproduction",
        "rl_teacher_labels": False,
        "sft_teacher_labels": "strong oracle on every D trajectory state, including mistakes and recovery",
        "fairness": "D/E equal gradient action positions and optimizer updates; label/rollout/compute costs reported separately",
        "replay_adaptations": "fixed shared task schedule, same-query low-current-surprisal success; no difficulty buckets or query retirement",
        "reward": "success +3; failure -1; per call -.02; avoidable error -.1; no progress -.05; potential shaping telescopes",
        "output_scope": "13 constrained tool/parameter candidates; not unconstrained JSON generation",
        "test_access": "sealed tasks only; no evaluation or tuning on test/retention during pilot",
        "production_authority": False,
        "live_api_calls": False,
        "threads": 4,
        "cache_limit_gib": 2,
    }
    save(out / "config.json", config)
    for source in SOURCES:
        target = out / "source" / source
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / source, target)
    save(out / "source-manifest.json", {s: sha(ROOT / s) for s in SOURCES})
    manifest = {}
    for split, tasks in task_splits().items():
        rows = [asdict(t) for t in tasks]
        save(out / "tasks" / (split + ".json"), rows)
        manifest[split] = {
            "count": len(rows),
            "sha256": digest(rows),
            "fault_compositions": sorted({str(t.shocks) for t in tasks}),
        }
    save(out / "task-manifest.json", manifest)
    demos = demonstrations(task_splits()["train"])
    save(out / "common-demonstrations.json", demos)
    # Fixed task order reused by all learned treatment groups.
    schedule = list(range(len(task_splits()["train"])))
    random.Random(config["seed"]).shuffle(schedule)
    # Repeat four tasks so replay has a chance to activate in this small pilot.
    schedule = schedule[:4] * 2
    save(out / "schedule.json", schedule)
    save(
        out / "protocol-lock.json",
        {
            "config": sha(out / "config.json"),
            "sources": sha(out / "source-manifest.json"),
            "tasks": sha(out / "task-manifest.json"),
            "schedule": sha(out / "schedule.json"),
        },
    )
    save(out / "STATUS.json", {"phase": "prepared", "final_test_opened": False})
    print(
        json.dumps({"prepared": str(out), "demonstrations": len(demos), "splits": manifest}, ensure_ascii=False),
        flush=True,
    )


def load_adapter(policy, path):
    from safetensors.torch import load_file

    values = load_file(str(path))
    own = policy.state()
    mapped = {k: values[k.replace(".default", "")] for k in own}
    policy.load_state(mapped)


def verify_protocol(out):
    lock = read(out / "protocol-lock.json")
    for key, name in [
        ("config", "config.json"),
        ("sources", "source-manifest.json"),
        ("tasks", "task-manifest.json"),
        ("schedule", "schedule.json"),
    ]:
        if sha(out / name) != lock[key]:
            raise ValueError("protocol drift: " + name)
    for s, expected in read(out / "source-manifest.json").items():
        if sha(ROOT / s) != expected:
            raise ValueError("source drift: " + s)
    for split, entry in read(out / "task-manifest.json").items():
        if digest(read(out / "tasks" / (split + ".json"))) != entry["sha256"]:
            raise ValueError("task drift: " + split)


def checkpoint(policy, optimizer, path, extra):
    policy.save(path / "adapter")
    state = {
        "model": policy.state(),
        "optimizer": optimizer.state_dict(),
        "torch_rng": policy.torch.get_rng_state(),
        "python_rng": random.getstate(),
        "extra": extra,
    }
    policy.torch.save(state, path / "resume.pt")
    save(
        path / "COMMITTED.json",
        {
            "fingerprint": policy.fingerprint(),
            "resume_sha256": sha(path / "resume.pt"),
            "adapter_sha256": sha(path / "adapter/adapter_model.safetensors"),
            **extra,
        },
    )


def restore(policy, optimizer, path):
    if sha(path / "resume.pt") != read(path / "COMMITTED.json")["resume_sha256"]:
        raise ValueError("checkpoint integrity failure")
    obj = policy.torch.load(path / "resume.pt", map_location="cpu", weights_only=False)
    policy.load_state(obj["model"])
    optimizer.load_state_dict(obj["optimizer"])
    policy.torch.set_rng_state(obj["torch_rng"])
    random.setstate(obj["python_rng"])
    return obj["extra"]


def staged(out, phase, step):
    path = out / phase / f"step-{step:05d}"
    if path.exists() and not (path / "COMMITTED.json").exists():
        path.rename(path.with_name(path.name + ".interrupted-" + str(time.time_ns())))
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_status(out, phase, **values):
    row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "phase": phase, "final_test_opened": False, **values}
    save(out / "STATUS.json", row)
    print(json.dumps(row, ensure_ascii=False), flush=True)


def collect(policy, task, cfg, *, greedy=False, path=None):
    env = DynamicEnvironment(task)
    records = []
    while not env.done:
        prompt = env.prompt()
        choice, details = policy.choose(prompt, sample=not greedy, temperature=1 if greedy else cfg["temperature"])
        row = env.step(choice)
        records.append({"prompt": prompt, "choice": choice, "policy": details, "transition": row})
        if path:
            save(path, {"in_progress": True, "steps": records})
    trajectory = {
        "task": asdict(task),
        "steps": records,
        "success": env.success,
        "return": sum(r["transition"]["reward"] for r in records),
        "behavior_fingerprint": policy.fingerprint(),
        "behavior_temperature": 1 if greedy else cfg["temperature"],
        "report": env.report,
        "replay": False,
    }
    if path:
        save(path, trajectory)
    return trajectory


def evaluate(policy, out, cfg, phase, step):
    path = out / "validation" / f"{phase}-{step:05d}.json"
    if path.exists():
        return read(path)
    tasks = [DynamicTask(**r) for r in read(out / "tasks/validation.json")]
    rows = [collect(policy, t, cfg, greedy=True) for t in tasks]
    result = {
        "phase": phase,
        "step": step,
        "fingerprint": policy.fingerprint(),
        "successes": sum(r["success"] for r in rows),
        "n": len(rows),
        "trajectories": rows,
    }
    save(path, result)
    log_status(out, "validation", group=phase, step=step, successes=result["successes"], n=len(rows))
    return result


def corrected_label(record, task):
    env = DynamicEnvironment(DynamicTask(**task))
    for label in record["history"]:
        env.step(label)
    if env.prompt() != record["prompt"]:
        raise ValueError("oracle prompt replay mismatch")
    return teacher_action(env)


def develop(args):
    out, cfg = args.output, read(args.output / "config.json")
    verify_protocol(out)
    if sha(cfg["parent_adapter"]) != cfg["parent_sha256"]:
        raise ValueError("parent changed")
    from app.agent_training.policy_v2 import CachedLanguagePolicy

    policy = CachedLanguagePolicy(
        cache_dir=out.parent / "prefix-cache",
        threads=cfg["threads"],
        seed=cfg["seed"],
        cache_limit_gib=cfg["cache_limit_gib"],
    )
    torch = policy.torch
    random.seed(cfg["seed"])
    load_adapter(policy, cfg["parent_adapter"])
    starting_fingerprint = policy.fingerprint()
    demos = read(out / "common-demonstrations.json")
    save(out / "prefix-cache-check.json", policy.verify_prefix_cache(demos[0]["prompt"]))
    optimizer = torch.optim.AdamW(policy.parameters, lr=cfg["warmup_learning_rate"], weight_decay=0)
    order = list(range(len(demos)))
    random.Random(cfg["seed"]).shuffle(order)
    warm_start = 0
    committed = sorted((out / "warmup").glob("step-*/COMMITTED.json"))
    if committed:
        warm_start = restore(policy, optimizer, committed[-1].parent)["step"]
    for step in range(warm_start + 1, cfg["warmup_updates"] + 1):
        path = staged(out, "warmup", step)
        record = demos[order[(step - 1) % len(order)]]
        optimizer.zero_grad(set_to_none=True)
        logits = policy.logits(record["prompt"])
        loss = torch.nn.functional.cross_entropy(logits[None], torch.tensor([LETTERS.index(record["target"])]))
        loss.backward()
        norm = float(torch.nn.utils.clip_grad_norm_(policy.parameters, 1.0))
        optimizer.step()
        save(
            path / "update.json",
            {
                "step": step,
                "loss": float(loss.detach()),
                "gradient_norm": norm,
                "training_record": record,
                "probabilities": logits.softmax(-1).detach().tolist(),
            },
        )
        checkpoint(policy, optimizer, path, {"step": step, "phase": "warmup"})
        if step % 8 == 0:
            log_status(out, "common_sft_warmup", step=step, total=cfg["warmup_updates"], loss=float(loss.detach()))
    common = policy.state()
    common_fp = policy.fingerprint()
    save(
        out / "common-initialization.json",
        {
            "prior_fingerprint": starting_fingerprint,
            "common_fingerprint": common_fp,
            "trainable_parameters": sum(p.numel() for p in policy.parameters),
        },
    )
    evaluate(policy, out, cfg, "C_common_sft", 0)
    train = [DynamicTask(**r) for r in read(out / "tasks/train.json")]
    schedule = read(out / "schedule.json")
    ref_cache = {}

    def reference(prompt):
        key = digest(prompt)
        if key not in ref_cache:
            now = policy.state()
            policy.load_state(common)
            with torch.no_grad():
                ref_cache[key] = (policy.logits(prompt) / cfg["temperature"]).softmax(-1).tolist()
            policy.load_state(now)
        return ref_cache[key]

    for phase in ["D_drgrpo", "E_more_sft", "F_experience"]:
        policy.load_state(common)
        torch.manual_seed(cfg["seed"] + 1)
        random.seed(cfg["seed"] + 1)
        optimizer = torch.optim.AdamW(policy.parameters, lr=cfg["learning_rate"], weight_decay=0)
        done = sorted((out / phase).glob("step-*/COMMITTED.json"))
        start = 0
        buffer = {}
        if done:
            extra = restore(policy, optimizer, done[-1].parent)
            start, buffer = extra["step"], extra.get("buffer", {})
        for step in range(start + 1, cfg["groups"] + 1):
            path = staged(out, phase, step)
            task = train[schedule[step - 1]]
            log_status(out, "collecting", group=phase, step=step, total=cfg["groups"], task=task.case_id)
            before = policy.fingerprint()
            start_time = time.monotonic()
            if phase == "E_more_sft":
                trajectories = read(out / "D_drgrpo" / f"step-{step:05d}" / "trajectories.json")
            else:
                trajectories = []
                candidates = buffer.get(task.case_id, [])
                if phase == "F_experience" and step >= cfg["replay_start_group"] and candidates:
                    scored = []
                    for trajectory in candidates:
                        with torch.no_grad():
                            surprise = sum(
                                -float(
                                    (policy.logits(r["prompt"]) / cfg["temperature"]).log_softmax(-1)[
                                        LETTERS.index(r["choice"])
                                    ]
                                )
                                for r in trajectory["steps"]
                            ) / len(trajectory["steps"])
                        scored.append((surprise, trajectory))
                    selected = json.loads(json.dumps(min(scored, key=lambda x: x[0])[1]))
                    selected["replay"] = True
                    trajectories.append(selected)
                    save(
                        path / "replay-selection.json",
                        {"scores": [s for s, _ in scored], "criterion": "lowest current mean action surprisal"},
                    )
                while len(trajectories) < cfg["group_size"]:
                    trajectories.append(collect(policy, task, cfg, path=path / f"rollout-{len(trajectories)}.json"))
            save(path / "trajectories.json", trajectories)
            advantages = centered_advantages([r["return"] for r in trajectories])
            samples = []
            for i, trajectory in enumerate(trajectories):
                history = []
                for r in trajectory["steps"]:
                    record = {
                        **r,
                        "history": history.copy(),
                        "trajectory": i,
                        "advantage": advantages[i],
                        "replay": trajectory["replay"],
                    }
                    if phase == "E_more_sft":
                        record["target"] = corrected_label(record, trajectory["task"])
                    # Reference is computed BEFORE constructing any gradient graph.
                    record["reference_probs"] = reference(r["prompt"])
                    samples.append(record)
                    history.append(r["choice"])
            save(path / "training-samples.json", samples)
            optimizer.zero_grad(set_to_none=True)
            arithmetic = []
            denominator = cfg["group_size"] * cfg["max_steps"]
            for sample in samples:
                logps = (policy.logits(sample["prompt"]) / cfg["temperature"]).log_softmax(-1)
                if phase == "E_more_sft":
                    # Same temperature, same constant denominator, same state positions and optimizer steps.
                    target = LETTERS.index(sample["target"])
                    loss = -logps[target]
                    q = torch.tensor(sample["reference_probs"])
                    kl = (logps.exp() * (logps - q.clamp_min(1e-30).log())).sum()
                    loss = loss + cfg["kl_coefficient"] * kl
                    metrics = {"cross_entropy": float(-logps[target].detach()), "kl": float(kl.detach())}
                else:
                    loss, metrics = action_loss(
                        logps,
                        LETTERS.index(sample["choice"]),
                        sample["policy"]["log_probability"],
                        sample["advantage"],
                        replay=sample["replay"],
                        clip=cfg["clip"],
                        beta=cfg["replay_beta"],
                        reference_probs=sample["reference_probs"],
                        kl_coefficient=cfg["kl_coefficient"],
                    )
                (loss / denominator).backward()
                arithmetic.append(
                    {
                        "trajectory": sample["trajectory"],
                        "choice": sample["choice"],
                        "replay": sample["replay"],
                        "advantage": sample["advantage"],
                        "log_probs": logps.detach().tolist(),
                        "loss": float(loss.detach()),
                        **metrics,
                    }
                )
            norm = float(torch.nn.utils.clip_grad_norm_(policy.parameters, 1.0))
            if not all(bool(torch.isfinite(p.grad).all()) for p in policy.parameters if p.grad is not None):
                raise ValueError("nonfinite gradient; refusing update")
            optimizer.step()
            fresh = [r for r in trajectories if not r["replay"]]
            successes = sum(r["success"] for r in fresh)
            if phase == "F_experience" and 0 < successes < len(fresh):
                buffer.setdefault(task.case_id, []).extend(r for r in fresh if r["success"])
            summary = {
                "phase": phase,
                "step": step,
                "task": task.case_id,
                "before_fingerprint": before,
                "after_fingerprint": policy.fingerprint(),
                "common_fingerprint": common_fp,
                "returns": [r["return"] for r in trajectories],
                "advantages": advantages,
                "successes": sum(r["success"] for r in trajectories),
                "fresh_successes": successes,
                "fresh_rollouts": len(fresh) if phase != "E_more_sft" else 0,
                "replay_rollouts": sum(r["replay"] for r in trajectories),
                "gradient_action_positions": len(samples),
                "normalization": denominator,
                "gradient_norm": norm,
                "loss": sum(r["loss"] for r in arithmetic) / denominator,
                "seconds": time.monotonic() - start_time,
                "cache": policy.cache_stats,
                "oracle_labels": len(samples) if phase == "E_more_sft" else 0,
                "new_environment_calls": sum(len(t["steps"]) for t in fresh) if phase != "E_more_sft" else 0,
            }
            save(path / "arithmetic.json", arithmetic)
            save(path / "summary.json", summary)
            checkpoint(policy, optimizer, path, {"phase": phase, "step": step, "buffer": buffer})
            log_status(
                out,
                "update_committed",
                group=phase,
                step=step,
                successes=summary["successes"],
                replay_rollouts=summary["replay_rollouts"],
                seconds=summary["seconds"],
            )
            if step in cfg["validation_milestones"]:
                evaluate(policy, out, cfg, phase, step)
        save(out / phase / "FINISHED.json", {"fingerprint": policy.fingerprint(), "groups": cfg["groups"]})
    log_status(
        out,
        "pilot_complete",
        final_test_opened=False,
        conclusion="development feasibility only; no confirmatory RL advantage claim",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "develop"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.command == "prepare":
        prepare(args)
        return
    # fcntl prevents two trainers from mutating the same evidence directory.
    import fcntl

    with (args.output / "trainer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            develop(args)
        except BaseException:
            save(args.output / ("failure-" + str(time.time_ns()) + ".json"), {"traceback": traceback.format_exc()})
            raise


if __name__ == "__main__":
    main()
