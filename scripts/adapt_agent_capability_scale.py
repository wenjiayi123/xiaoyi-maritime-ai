"""Bounded RL failure-state replay; preserve accepted weights and all evidence."""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
import json
import os
from pathlib import Path
import random
import shutil
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_agent_capability_scale as scale  # noqa: E402
from app.agent_training.environment import LETTERS, digest  # noqa: E402
from app.agent_training.environment_v2 import counterfactuals  # noqa: E402

c = scale.core


def append(path, row):
    with path.open("a") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def prepare(out, baseline):
    if out.exists():
        raise ValueError("Use a new adaptation directory")
    p = c.verify(baseline)
    results = c.read(baseline / "RESULTS.json")
    if (results["counts"]["E_more_sft"]["successes"] != 24
            or results["counts"]["D_rl"]["attempted"] != 24
            or results["counts"]["D_rl"]["successes"] != 22):
        raise ValueError("This bounded repair is registered for the observed 24/24 versus 22/24 baseline")
    environments, focus_ids, retention = {}, [], {}
    audits = []
    for row in results["results"]:
        folder = Path(row["folder"])
        job = c.read(folder / "job.json")
        audit = c.audit_job(job, folder, p)
        audits.append({"id": row["id"], **audit})
        if row["group"] != "E_more_sft" and row["success"]:
            continue
        env = c.live.environment_for_job(job)
        for actual in job["steps"]:
            prompt = c.prompt_for(env, p["prompt_mode"])
            if prompt != actual["decision_input"]:
                raise ValueError("Native state not reproducible for training")
            key = digest(prompt)
            environments.setdefault(key, copy.deepcopy(env))
            if row["group"] == "E_more_sft":
                retention.setdefault(row["case"], []).append(key)
            elif actual["choice"] == "B" and "energy" in env.reads and "energy" not in env.receipts:
                if key not in focus_ids:
                    focus_ids.append(key)
            env.step(actual["choice"])
    if not focus_ids or len(retention) != 24:
        raise ValueError("Incomplete failed-state / retention coverage")
    rng = random.Random(20261102)
    rng.shuffle(focus_ids)
    cases = list(retention)
    order = []
    for i in range(32):
        order.append({"state_id": focus_ids[i % len(focus_ids)], "origin": "failed_native_state_replay"})
        keys = retention[cases[i % len(cases)]]
        order.append({"state_id": keys[(i + i // len(cases)) % len(keys)], "origin": "successful_native_state_retention"})
    out.mkdir(parents=True)
    records = []
    for key in dict.fromkeys(x["state_id"] for x in order):
        env = environments[key]
        branches = counterfactuals(env)
        rel = "counterfactuals/" + key + ".json"
        c.live.save(out / rel, branches)
        records.append({"state_id": key, "task": asdict(env.task), "history": [s["choice"] for s in env.steps],
                        "prompt": c.prompt_for(env, p["prompt_mode"]),
                        "returns": [branches[a]["two_step_return"] for a in LETTERS],
                        "counterfactual_file": rel, "counterfactual_sha256": c.sha(out / rel)})
    cfg = {
        "time": c.now(), "seed": 20261102, "source_native_round": str(baseline),
        "objective": "Repair observed repeated reads while retaining completed tasks; no RL versus SFT superiority requirement",
        "method": "Exact categorical actor expected two-step simulator return; replay failed states mixed with successful states; KL to frozen starting RL adapter",
        "not_claimed": "Not sampled PPO/GRPO, not new online real-world exploration, not independent generalization evidence",
        "model": "Qwen3-1.7B float32; last four layer q/v LoRA, 229376 trainable values", "threads": 4,
        "updates": 64, "temperature": 2.0, "learning_rate": 0.00005, "kl_coefficient": 0.02,
        "entropy_coefficient": 0.001, "gradient_clip": 1.0, "weight_decay": 0.0,
        "source_models": p["models"], "trained_group": "D_rl", "extra_sft_updates": 0,
        "state_schedule": "32 failed-state replay updates alternated with 32 retention updates across all24 core task instances; frozen order",
        "label_access": False, "reward_code_unchanged": True, "harness_prompt_unchanged": True,
        "selection": "Fixed final step64 only; checkpoints each step for audit, not selection using final outcomes",
        "stop": "64 updates or nonfinite arithmetic, identity mismatch, pause, source drift, or exception; no automatic restart",
        "data_split": {"training": "Previously observed core24 engineering states; SFT trajectories provide visited states but no labels in the RL objective",
                       "rehearsal": "Core24 are deliberately reused after adaptation; explicitly not independent tests",
                       "extension": "Six registered joint fault combinations not executed or included in this adaptation",
                       "old_formal_tests": "Remain closed; not read by this experiment"},
        "evaluation": "After training, register round-002 with final weight hashes; run all30 contracts for both versions twice under original frozen stage gates and unchanged success checks",
        "compute": "One existing base-model allocation at a time; stop old worker before loading; reuse frozen prefix cache; restore accepted worker after process exits",
        "cache_dir": str(c.OLD.parent / "frozen-prefix-cache"), "production_authority": False,
    }
    c.live.save(out / "CONFIG.json", cfg)
    c.live.save(out / "STATES.json", records)
    c.live.save(out / "ORDER.json", order)
    c.live.save(out / "BASELINE_AUDIT.json", {"passed": True, "attempts": audits, "new_model_calls": 0})
    c.live.save(out / "DATASET.json", {"unique_states": len(records), "focus_unique_states": len(focus_ids),
                                      "retention_task_instances": len(retention), "updates": len(order),
                                      "teacher_labels_in_training_records": 0, "old_test_access": False})
    sources = dict(c.read(baseline / "SOURCES.json"))
    sources[str(Path(__file__).relative_to(ROOT))] = c.sha(Path(__file__))
    sources["scripts/launch_agent_capability_adaptation.py"] = c.sha(ROOT / "scripts/launch_agent_capability_adaptation.py")
    for rel in sources:
        dest = out / "source" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
    c.live.save(out / "SOURCES.json", sources)
    c.live.save(out / "LOCK.json", {name: c.sha(out / name) for name in ["CONFIG.json", "STATES.json", "ORDER.json", "SOURCES.json", "DATASET.json"]})
    c.live.save(out / "STATUS.json", {"time": c.now(), "phase": "registered", "updates": 0})
    print(json.dumps(c.read(out / "DATASET.json")), flush=True)


def verify(out):
    for name, h in c.read(out / "LOCK.json").items():
        if c.sha(out / name) != h:
            raise ValueError("Frozen adaptation data drift")
    for rel, h in c.read(out / "SOURCES.json").items():
        if c.sha(ROOT / rel) != h or c.sha(out / "source" / rel) != h:
            raise ValueError("Adaptation source drift: " + rel)
    cfg = c.read(out / "CONFIG.json")
    for model in cfg["source_models"].values():
        if c.sha(Path(model["adapter"])) != model["file_sha256"]:
            raise ValueError("Parent model drift")
    for r in c.read(out / "STATES.json"):
        if c.sha(out / r["counterfactual_file"]) != r["counterfactual_sha256"]:
            raise ValueError("Counterfactual evidence drift")
        env = c.live.environment_for_job({"task": r["task"], "environment": c.REVISION})
        for a in r["history"]:
            env.step(a)
        b = counterfactuals(env)
        if c.prompt_for(env, scale.wording.MODE) != r["prompt"] or [b[a]["two_step_return"] for a in LETTERS] != r["returns"]:
            raise ValueError("Training state/reward replay failed")
    return cfg


def run(out, evaluation):
    cfg = verify(out)
    if (out / "TRAINING_START.json").exists():
        raise ValueError("Previously started experiment retained; no automatic replay")
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", 18781)) == 0:
            raise ValueError("Existing worker must exit before loading the training model")
    c.live.save(out / "TRAINING_START.json", {"time": c.now(), "pid": os.getpid()})
    c.live.save(out / "STATUS.json", {"time": c.now(), "phase": "loading_model", "pid": os.getpid()})
    from app.agent_training.policy_v2 import CachedLanguagePolicy
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file

    policy = CachedLanguagePolicy(cache_dir=cfg["cache_dir"], threads=cfg["threads"], seed=cfg["seed"])
    torch = policy.torch
    set_peft_model_state_dict(policy.model, load_file(cfg["source_models"]["D_rl"]["adapter"]))
    frozen = policy.state()
    start_hash = policy.fingerprint()
    if start_hash != cfg["source_models"]["D_rl"]["parameter_fingerprint"]:
        raise ValueError("Loaded adapter differs from registered parent")
    optimizer = torch.optim.AdamW(policy.parameters, lr=cfg["learning_rate"], weight_decay=cfg["weight_decay"])
    records = {r["state_id"]: r for r in c.read(out / "STATES.json")}
    references = {}
    order = c.read(out / "ORDER.json")
    for step, item in enumerate(order, 1):
        if (scale.BASE / "PAUSE").exists():
            raise RuntimeError("Expansion pause requested")
        r = records[item["state_id"]]
        tick = time.monotonic()
        c.live.save(out / "STATUS.json", {"time": c.now(), "phase": "training", "pid": os.getpid(), "step": step, "total": 64})
        if r["state_id"] not in references:
            current = policy.state()
            policy.load_state(frozen)
            with torch.no_grad():
                references[r["state_id"]] = policy.logits(r["prompt"]).detach().clone()
            policy.load_state(current)
            append(out / "frozen-reference-logits.jsonl", {"state_id": r["state_id"], "logits": references[r["state_id"]].tolist(), "parameter_fingerprint": start_hash})
        optimizer.zero_grad(set_to_none=True)
        logits = policy.logits(r["prompt"])
        probs = torch.softmax(logits / cfg["temperature"], 0)
        logp = torch.log_softmax(logits / cfg["temperature"], 0)
        returns = torch.tensor(r["returns"], dtype=torch.float32)
        advantages = (returns - returns.mean()) / returns.std(unbiased=False).clamp(min=0.1)
        kl = (probs * (logp - torch.log_softmax(references[r["state_id"]] / cfg["temperature"], 0))).sum()
        entropy = -(probs * logp).sum()
        loss = -(probs * advantages).sum() + cfg["kl_coefficient"] * kl - cfg["entropy_coefficient"] * entropy
        if not torch.isfinite(loss):
            raise ValueError("Nonfinite loss")
        before_hash = policy.fingerprint()
        loss.backward()
        grad = torch.nn.utils.clip_grad_norm_(policy.parameters, cfg["gradient_clip"])
        if not torch.isfinite(grad):
            raise ValueError("Nonfinite gradient")
        optimizer.step()
        with torch.no_grad():
            after = torch.softmax(policy.logits(r["prompt"]) / cfg["temperature"], 0)
            current = policy.state()
            delta_l2 = sum(float(((current[n] - frozen[n]).double() ** 2).sum()) for n in frozen) ** .5
            changed = sum(int((current[n] != frozen[n]).sum()) for n in frozen)
        after_hash = policy.fingerprint()
        checkpoint = out / "checkpoints" / f"step-{step:05d}"
        policy.save(checkpoint)
        torch.save({"optimizer": optimizer.state_dict(), "torch_rng": torch.get_rng_state(), "step": step,
                    "config_sha256": c.sha(out / "CONFIG.json")}, checkpoint / "optimizer-rng.pt")
        row = {"time": c.now(), "step": step, "stage": "D_scale_rl", **item, "loss": float(loss.detach()),
               "case_id": r["task"]["case_id"], "probabilities_before": probs.detach().tolist(), "probabilities_after": after.tolist(),
               "action_returns": r["returns"], "advantage": advantages.tolist(), "entropy": float(entropy.detach()),
               "kl_to_starting_rl": float(kl.detach()), "gradient_norm_before_clip": float(grad),
               "expected_two_step_return_before": float((probs.detach() * returns).sum()),
               "expected_two_step_return_after": float((after * returns).sum()),
               "choice_before": LETTERS[int(probs.argmax())], "choice_after": LETTERS[int(after.argmax())],
               "parameter_before": before_hash, "parameter_after": after_hash, "parameter_l2_from_start": delta_l2,
               "changed_values_from_start": changed, "seconds": time.monotonic() - tick,
               "adapter_file_sha256": c.sha(checkpoint / "adapter_model.safetensors"), "cache": dict(policy.cache_stats)}
        append(out / "training.jsonl", row)
        c.live.save(checkpoint / "COMMITTED.json", row)
        print(json.dumps({k: row[k] for k in ["step", "loss", "origin", "choice_before", "choice_after", "seconds"]}), flush=True)
    verify(out)
    rl_state = policy.state()
    rl_hash = policy.fingerprint()
    if rl_hash == start_hash:
        raise ValueError("No RL parameter change")
    set_peft_model_state_dict(policy.model, load_file(cfg["source_models"]["E_more_sft"]["adapter"]))
    sft_state = policy.state()
    sft_hash = policy.fingerprint()
    if sft_hash != cfg["source_models"]["E_more_sft"]["parameter_fingerprint"]:
        raise ValueError("SFT baseline drift")
    c.live.save(out / "TRAINING_COMPLETE.json", {"time": c.now(), "updates": 64, "additional_sft_updates": 0,
                                               "rl_before": start_hash, "rl_after": rl_hash, "sft_unchanged": sft_hash,
                                               "fixed_final_step": 64, "checkpoint": str(out / "checkpoints/step-00064")})
    draft = evaluation.with_name(evaluation.name + ".preparing")
    scale.prepare(draft)
    p = c.read(draft / "PROTOCOL.json")
    adapter = out / "checkpoints/step-00064/adapter_model.safetensors"
    p["models"]["D_rl"] = {"adapter": str(adapter), "file_sha256": c.sha(adapter), "parameter_fingerprint": rl_hash}
    p.update(new_training=True, adaptation=str(out), additional_rl_updates=64, additional_sft_updates=0,
             source_experiment=str(out), baseline_native_round=cfg["source_native_round"],
             RL_method=cfg["method"], data_split=cfg["data_split"],
             evaluation_transport="Same one local model object used serially through an in-process /decide adapter; actual native API calls and the exact original audit are unchanged")
    c.live.save(draft / "PROTOCOL.json", p)
    sources = c.read(draft / "SOURCES.json")
    for f in [Path(__file__), out / "CONFIG.json", out / "TRAINING_COMPLETE.json"]:
        rel = str(f.relative_to(ROOT))
        sources[rel] = c.sha(f)
        dst = draft / "source" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
    c.live.save(draft / "SOURCES.json", sources)
    c.live.save(draft / "LOCK.json", {n: c.sha(draft / n) for n in ["PROTOCOL.json", "SOURCES.json"]})
    draft.rename(evaluation)
    hashes = {"E_more_sft": sft_hash, "D_rl": rl_hash}
    states = {"E_more_sft": sft_state, "D_rl": rl_state}
    original_request, original_execute = c.live.local_request, c.execute

    def request(base, path, payload=None, **kwargs):
        if base == "http://127.0.0.1:18781":
            if path == "/health":
                return {"weights": hashes, "model": "1.7B", "transport": "serial_same_process", "pid": os.getpid()}
            if path == "/decide":
                group = payload["group"]
                policy.load_state(states[group])
                choice, meta = policy.choose(payload["prompt"])
                return {"choice": choice, **meta, "group": group, "model": "Qwen3-1.7B", "adapter_sha256": hashes[group],
                        "decision_mode": "causal_lm_constrained_next_token", "transport": "serial_same_process"}
            raise ValueError("Unknown in-process model endpoint")
        return original_request(base, path, payload, **kwargs)

    def execute(job, folder, protocol):
        job["experiment"] = out.name
        return original_execute(job, folder, protocol)

    c.live.local_request, c.execute = request, execute
    c.live.save(out / "STATUS.json", {"time": c.now(), "phase": "native_evaluation", "pid": os.getpid(), "updates": 64, "round": str(evaluation)})
    try:
        code = scale.run(evaluation)
        res = c.read(evaluation / "RESULTS.json")
        res.update(new_training=True, additional_rl_updates=64, additional_sft_updates=0)
        c.live.save(evaluation / "RESULTS.json", res)
        c.live.save(out / "STATUS.json", {"time": c.now(), "phase": "complete" if code == 0 else "needs_diagnosis",
                                         "updates": 64, "evaluation_exit_code": code, "round": str(evaluation)})
        return code
    finally:
        c.live.local_request, c.execute = original_request, original_execute


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--evaluation", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output.resolve(), args.baseline.resolve())
    else:
        code = 1
        try:
            code = run(args.output.resolve(), args.evaluation.resolve())
        except Exception as exc:
            c.live.save(args.output / "ERROR.json", {"time": c.now(), "error": str(exc), "pid": os.getpid()})
            raise
        finally:
            c.live.save(args.output / "process-exit.json", {"time": c.now(), "exit_code": code, "pid": os.getpid()})
        raise SystemExit(code)
