"""Serial, frozen, CPU-only SFT and expected-return actor adaptation.

Training never loads held-out tasks. It exits after preserving both final
adapters; a separate audited phase restores the model registry and evaluates.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import socket
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import fcntl
except ImportError:  # Windows uses the project's non-blocking file lease.
    from app import windows_flock as fcntl
from scripts.prepare_agent_expert_training import read, save, sha, verify, environment, EXPERT  # noqa: E402
from app.agent_training.expert_learning import actor_objective  # noqa: E402


def now():
    return datetime.now(timezone.utc).isoformat()


def append(path, row):
    with Path(path).open("a") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def check_pause(out):
    if any((p / "PAUSE").exists() for p in (EXPERT, out)):
        raise RuntimeError("Pause requested; preserve all partial artifacts")


def single_model_guard():
    for port in (18781,):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError("Existing 1.7B inference worker must exit first")
    listing = subprocess.check_output(["ps", "-axo", "pid=,comm=,args="], text=True)
    names = (
        "serve_agent",
        "train_agent",
        "adapt_agent",
        "run_agent_rl_confirmatory.py run",
        "run_agent_rl_tiered_queue.py",
        "agent_training.worker",
    )
    for line in listing.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and int(parts[0]) != os.getpid() and "python" in parts[1].lower():
            if any(name in parts[2] for name in names):
                raise RuntimeError("Another possible model process: " + line)


def preflight(policy, cases, folder, out):
    results = []
    for case in cases:
        check_pause(out)
        env = environment(case)
        decisions = []
        while not env.done:
            prompt = env.prompt()
            action, info = policy.choose(prompt, sample=False)
            transition = env.step(action)
            decisions.append({"prompt": prompt, "action": action, "policy": info, "transition": transition})
        row = {
            "case_id": env.task.case_id,
            "success": env.success,
            "business_complete": env.business_complete,
            "outcome": env.outcome,
            "decisions": decisions,
            "parent_fingerprint": policy.fingerprint(),
            "split": "training_only",
            "used_to_select_training_need_not_checkpoint": True,
        }
        save(folder / (env.task.case_id + ".json"), row)
        results.append({k: row[k] for k in ("case_id", "success", "business_complete", "outcome")})
        # One failure already establishes that this parent needs adaptation.
        # Do not spend CPU estimating its training success rate more precisely.
        if not env.success:
            break
    save(
        folder / "SUMMARY.json",
        {"correct": sum(r["success"] for r in results), "total": len(results), "results": results},
    )
    return len(results) == len(cases) and all(row["success"] for row in results)


def run(out):
    cfg = verify(out)
    check_pause(out)
    if (out / "TRAINING_START.json").exists():
        raise RuntimeError("Prior attempt retained; no automatic restart")
    guard = (EXPERT / "MODEL.lock").open("a+")
    fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    single_model_guard()
    save(out / "TRAINING_START.json", {"time": now(), "pid": os.getpid(), "lock_sha256": sha(out / "LOCK.json")})
    save(out / "STATUS.json", {"time": now(), "phase": "loading_one_base", "pid": os.getpid()})
    from app.agent_training.policy_v2 import CachedLanguagePolicy
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file

    policy = CachedLanguagePolicy(cache_dir=cfg["cache_dir"], threads=cfg["threads"], seed=cfg["seed"])
    torch = policy.torch
    records = {r["state_id"]: r for r in read(out / "STATES.json")}
    order = read(out / "ORDER.json")
    cases = read(Path(cfg["data_root"]) / "train/tasks.json")
    final = {}
    for route in cfg["route_order"]:
        check_pause(out)
        verify(out)
        folder = out / route
        folder.mkdir(exist_ok=False)
        parent = cfg["parents"][route]
        set_peft_model_state_dict(policy.model, load_file(parent["adapter"]))
        if policy.fingerprint() != parent["parameter_fingerprint"]:
            raise RuntimeError("Loaded parent fingerprint mismatch")
        torch.manual_seed(cfg["seed"])
        random.seed(cfg["seed"])
        save(out / "STATUS.json", {"time": now(), "phase": "training_need_check", "route": route, "pid": os.getpid()})
        reusable = preflight(policy, cases, folder / "parent-training-check", out)
        if reusable:
            final[route] = {**parent, "additional_updates": 0, "reason": "parent completed24training cases; reused"}
            save(folder / "ROUTE_COMPLETE.json", final[route])
            continue
        frozen = policy.state()
        start_hash = policy.fingerprint()
        labels = read(out / "SFT_LABELS.json") if route == "E_sft" else None
        references = {}
        optimizer = torch.optim.AdamW(policy.parameters, lr=cfg["learning_rate"], weight_decay=cfg["weight_decay"])
        for step, item in enumerate(order, 1):
            check_pause(out)
            if step > cfg["updates_per_needed_route"]:
                raise RuntimeError("Update budget exceeded")
            tick = time.monotonic()
            save(
                out / "STATUS.json",
                {
                    "time": now(),
                    "phase": "training",
                    "route": route,
                    "step": step,
                    "total": len(order),
                    "pid": os.getpid(),
                },
            )
            before_state = policy.state()
            before_hash = policy.fingerprint()
            optimizer.zero_grad(set_to_none=True)
            details = []
            for sid in item["states"]:
                record = records[sid]
                if route == "D_rl" and sid not in references:
                    current = policy.state()
                    policy.load_state(frozen)
                    with torch.no_grad():
                        references[sid] = policy.logits(record["prompt"]).detach().clone()
                    policy.load_state(current)
                logits = policy.logits(record["prompt"])
                if route == "E_sft":
                    target = "ABCDEFGHIJKLM".index(labels[sid])
                    loss = torch.nn.functional.cross_entropy(logits.unsqueeze(0), torch.tensor([target]))
                    metrics = {"probabilities": torch.softmax(logits, 0)}
                    extra = {"target": labels[sid]}
                else:
                    loss, metrics = actor_objective(
                        logits,
                        references[sid],
                        record["returns"],
                        temperature=cfg["temperature"],
                        kl_coefficient=cfg["kl_coefficient"],
                        entropy_coefficient=cfg["entropy_coefficient"],
                    )
                    extra = {"reference_logits": references[sid].tolist(), "returns": record["returns"]}
                if not bool(torch.isfinite(loss)):
                    raise ValueError("Nonfinite loss")
                logits.retain_grad()
                (loss / len(item["states"])).backward()
                details.append(
                    {
                        "state_id": sid,
                        "case_id": record["case_id"],
                        "origin": record["origin"],
                        "logits_before": logits.detach().tolist(),
                        "loss": float(loss.detach()),
                        "gradient_logits_unaveraged": (logits.grad * len(item["states"])).tolist(),
                        **{k: v.detach().tolist() for k, v in metrics.items()},
                        **extra,
                    }
                )
            grad = torch.nn.utils.clip_grad_norm_(policy.parameters, cfg["gradient_clip"])
            if not bool(torch.isfinite(grad)):
                raise ValueError("Nonfinite gradient")
            optimizer.step()
            after_state = policy.state()
            if any(not bool(torch.isfinite(v).all()) for v in after_state.values()):
                raise ValueError("Nonfinite parameters")
            after_hash = policy.fingerprint()
            if after_hash == before_hash:
                raise ValueError("No actual parameter change")
            with torch.no_grad():
                for detail in details:
                    after_logits = policy.logits(records[detail["state_id"]]["prompt"])
                    detail["logits_after"] = after_logits.tolist()
                    temp = cfg["temperature"] if route == "D_rl" else 1.0
                    detail["probabilities_after"] = torch.softmax(after_logits / temp, 0).tolist()
            checkpoint = folder / "checkpoints" / f"step-{step:05d}"
            policy.save(checkpoint)
            torch.save(
                {
                    "optimizer": optimizer.state_dict(),
                    "torch_rng": torch.get_rng_state(),
                    "python_rng": random.getstate(),
                    "step": step,
                    "route": route,
                    "config_sha256": sha(out / "CONFIG.json"),
                },
                checkpoint / "optimizer-rng.pt",
            )
            delta = sum(float(((after_state[n] - before_state[n]).double() ** 2).sum()) for n in after_state) ** 0.5
            total_delta = sum(float(((after_state[n] - frozen[n]).double() ** 2).sum()) for n in frozen) ** 0.5
            row = {
                "time": now(),
                "route": route,
                "step": step,
                "minibatch": item,
                "details": details,
                "loss": sum(d["loss"] for d in details) / len(details),
                "gradient_norm_before_clip": float(grad),
                "parameter_before": before_hash,
                "parameter_after": after_hash,
                "parameter_step_l2": delta,
                "parameter_l2_from_parent": total_delta,
                "seconds": time.monotonic() - tick,
                "adapter_file_sha256": sha(checkpoint / "adapter_model.safetensors"),
                "optimizer_sha256": sha(checkpoint / "optimizer-rng.pt"),
                "cache": dict(policy.cache_stats),
            }
            append(folder / "training.jsonl", row)
            save(checkpoint / "COMMITTED.json", row)
            print(json.dumps({k: row[k] for k in ("route", "step", "loss", "seconds")}), flush=True)
        verify(out)
        adapter = folder / "checkpoints" / f"step-{len(order):05d}" / "adapter_model.safetensors"
        final[route] = {
            "adapter": str(adapter),
            "file_sha256": sha(adapter),
            "parameter_fingerprint": policy.fingerprint(),
            "additional_updates": len(order),
            "parent_fingerprint": start_hash,
            "selection": "fixed final registered update",
        }
        save(folder / "ROUTE_COMPLETE.json", final[route])
    if sum(x["additional_updates"] for x in final.values()) > cfg["total_update_cap"]:
        raise RuntimeError("Total budget exceeded")
    verify(out)
    save(
        out / "TRAINING_COMPLETE.json",
        {
            "time": now(),
            "routes": final,
            "sealed_tests_opened": False,
            "audit_required_before_evaluation": True,
            "base_model_instances": 1,
        },
    )
    save(out / "STATUS.json", {"time": now(), "phase": "training_complete_awaiting_audit", "routes": final})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.experiment.resolve())
    except BaseException as exc:
        save(
            args.experiment / ("FAILURE-" + str(time.time_ns()) + ".json"),
            {"time": now(), "error": repr(exc), "traceback": traceback.format_exc(), "pid": os.getpid()},
        )
        save(args.experiment / "STATUS.json", {"time": now(), "phase": "stopped_with_failure", "error": repr(exc)})
        raise
