"""One common supervised warm-start; only training-side readiness gates."""

import argparse
import json
import os
from pathlib import Path
import random
import signal
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import file_lease as fcntl
from scripts.freeze_agent_expert_recovery import verify  # noqa: E402
from scripts.agent_expert_recovery_support import (  # noqa: E402
    EXPERT,
    LETTERS,
    learning_rate,
    read,
    save,
    sha,
    now,
    ready,
    resource_check,
    training_gate,
)
from scripts.train_agent_expert_continuation import single_model_guard  # noqa: E402


def append(path, value):
    with path.open("a") as f:
        f.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def run(out):
    cfg = verify(out)
    resource_check(out)
    if (out / "TRAINING_START.json").exists():
        raise RuntimeError("Prior attempt retained; no automatic restart")
    guard = (EXPERT / "MODEL.lock").open("a+")
    fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    single_model_guard()
    os.nice(10)
    save(
        out / "TRAINING_START.json",
        dict(time=now(), pid=os.getpid(), protocol_sha256=sha(out / "LOCK.json"), heldout_opened=False),
    )
    save(out / "STATUS.json", dict(time=now(), phase="loading_one_base", pid=os.getpid()))
    from app.agent_training.policy_v2 import CachedLanguagePolicy
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file

    policy = CachedLanguagePolicy(
        cache_dir=cfg["cache_dir"], cache_limit_gib=cfg["cache_limit_gib"], threads=cfg["threads"], seed=cfg["seed"]
    )
    torch = policy.torch
    set_peft_model_state_dict(policy.model, load_file(cfg["parent"]["adapter"]))
    if policy.fingerprint() != cfg["parent"]["parameter_fingerprint"]:
        raise ValueError("Warm parent mismatch")
    torch.manual_seed(cfg["seed"])
    random.seed(cfg["seed"])
    parent = policy.state()
    records = {r["state_id"]: r for r in read(out / "STATES.json")}
    order = read(out / "ORDER.json")
    cases = read(out / "GATE_CASES.json")
    optimizer = torch.optim.AdamW(
        policy.parameters,
        lr=cfg["lr_initial"],
        betas=tuple(cfg["betas"]),
        eps=cfg["epsilon"],
        weight_decay=cfg["weight_decay"],
    )
    gates = []
    for scheduled in order:
        resource_check(out)
        step = scheduled["step"]
        tick = time.monotonic()
        if step > cfg["max_updates"]:
            raise RuntimeError("Training budget exceeded")
        lr = learning_rate(step, cfg)
        for group in optimizer.param_groups:
            group["lr"] = lr
        save(
            out / "STATUS.json",
            dict(
                time=now(),
                phase="supervised_recovery_training",
                step=step,
                max_updates=cfg["max_updates"],
                pid=os.getpid(),
            ),
        )
        before = policy.state()
        before_fp = policy.fingerprint()
        optimizer.zero_grad(set_to_none=True)
        details = []
        for sid in scheduled["states"]:
            resource_check(out)
            record = records[sid]
            target = LETTERS.index(record["target"])
            logits = policy.logits(record["prompt"])
            logits.retain_grad()
            loss = -torch.log_softmax(logits, dim=0)[target]
            if not bool(torch.isfinite(loss)):
                raise ValueError("Nonfinite loss")
            (loss / cfg["batch_size"]).backward()
            details.append(
                dict(
                    state_id=sid,
                    origin=record["origin"],
                    target=record["target"],
                    logits_before=logits.detach().tolist(),
                    loss=float(loss.detach()),
                    probabilities=torch.softmax(logits.detach(), 0).tolist(),
                    gradient_logits_unaveraged=(logits.grad * cfg["batch_size"]).tolist(),
                )
            )
        norm = torch.nn.utils.clip_grad_norm_(policy.parameters, cfg["gradient_clip"])
        if not bool(torch.isfinite(norm)):
            raise ValueError("Nonfinite gradient")
        optimizer.step()
        after = policy.state()
        after_fp = policy.fingerprint()
        if any(not bool(torch.isfinite(v).all()) for v in after.values()):
            raise ValueError("Nonfinite weights")
        delta = sum(float(((after[n] - before[n]).double() ** 2).sum()) for n in after) ** 0.5
        total = sum(float(((after[n] - parent[n]).double() ** 2).sum()) for n in after) ** 0.5
        checkpoint = out / "checkpoints" / f"step-{step:05d}"
        policy.save(checkpoint)
        torch.save(
            dict(
                optimizer=optimizer.state_dict(),
                torch_rng=torch.get_rng_state(),
                python_rng=random.getstate(),
                step=step,
                config_sha256=sha(out / "CONFIG.json"),
            ),
            checkpoint / "optimizer-rng.pt",
        )
        row = dict(
            time=now(),
            step=step,
            learning_rate=lr,
            minibatch=scheduled,
            details=details,
            loss=sum(d["loss"] for d in details) / len(details),
            gradient_norm_before_clip=float(norm),
            parameter_before=before_fp,
            parameter_after=after_fp,
            parameter_step_l2=delta,
            parameter_l2_from_parent=total,
            parameter_changed=after_fp != before_fp,
            seconds=time.monotonic() - tick,
            adapter_file_sha256=sha(checkpoint / "adapter_model.safetensors"),
            optimizer_sha256=sha(checkpoint / "optimizer-rng.pt"),
            cache=dict(policy.cache_stats),
        )
        append(out / "training.jsonl", row)
        save(checkpoint / "COMMITTED.json", row)
        print(json.dumps({k: row[k] for k in ["step", "loss", "seconds", "parameter_changed"]}), flush=True)
        if step % cfg["gate_interval"] == 0:
            verify(out)
            result = training_gate(policy, cases, out, step)
            gates.append(
                dict(
                    step=step,
                    passed=result["passed"],
                    groups=result["groups"],
                    file=str(out / "training-gates" / f"step-{step:05d}" / "RESULTS.json"),
                    sha256=sha(out / "training-gates" / f"step-{step:05d}" / "RESULTS.json"),
                )
            )
            save(out / "TRAINING_GATES.json", gates)
            if ready(gates):
                break
    verify(out)
    adapter = out / "checkpoints" / f"step-{step:05d}" / "adapter_model.safetensors"
    result = dict(
        time=now(),
        warm_ready=ready(gates),
        updates=step,
        parent_fingerprint=cfg["parent"]["parameter_fingerprint"],
        adapter=str(adapter),
        file_sha256=sha(adapter),
        parameter_fingerprint=policy.fingerprint(),
        selection=cfg["selection"],
        training_gates=gates,
        heldout_opened=False,
        base_model_instances=1,
        capability_accepted=False,
        subsequent_RL_started=False,
    )
    save(out / "TRAINING_COMPLETE.json", result)
    save(
        out / "STATUS.json",
        dict(time=now(), phase="warm_training_complete_awaiting_audit", warm_ready=result["warm_ready"], updates=step),
    )
    return 0 if result["warm_ready"] else 2


def interrupted(signum, frame):
    raise InterruptedError("Training interrupted by signal " + str(signum))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--experiment", type=Path, required=True)
    out = p.parse_args().experiment.resolve()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        code = run(out)
    except BaseException as exc:
        save(
            out / ("FAILURE-" + str(time.time_ns()) + ".json"),
            dict(time=now(), error=repr(exc), traceback=traceback.format_exc(), pid=os.getpid()),
        )
        save(out / "STATUS.json", dict(time=now(), phase="stopped_with_failure", error=repr(exc)))
        raise
    sys.exit(code)
