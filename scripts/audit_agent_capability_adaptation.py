"""Independent numpy audit of RL arithmetic and every saved adapter; no model load."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.adapt_agent_capability_scale import verify, c  # noqa: E402
from app.agent_training.environment import LETTERS  # noqa: E402


def tensors(path):
    raw = path.read_bytes()
    length = struct.unpack("<Q", raw[:8])[0]
    header = json.loads(raw[8:8 + length])
    arrays, fingerprint = {}, hashlib.sha256()
    for key in sorted(k for k in header if k != "__metadata__"):
        info = header[key]
        if info["dtype"] != "F32":
            raise ValueError("Unexpected adapter dtype")
        begin, end = info["data_offsets"]
        data = raw[8 + length + begin:8 + length + end]
        arrays[key] = np.frombuffer(data, dtype="<f4").reshape(info["shape"])
        if not np.isfinite(arrays[key]).all():
            raise ValueError("Nonfinite adapter")
        full = key.replace(".lora_A.", ".lora_A.default.").replace(".lora_B.", ".lora_B.default.")
        fingerprint.update(full.encode())
        fingerprint.update(data)
    return arrays, fingerprint.hexdigest()


def audit(out):
    cfg = verify(out)
    complete = c.read(out / "TRAINING_COMPLETE.json")
    rows = [json.loads(line) for line in (out / "training.jsonl").read_text().splitlines()]
    states = {r["state_id"]: r for r in c.read(out / "STATES.json")}
    references = {r["state_id"]: r for r in (json.loads(line) for line in (out / "frozen-reference-logits.jsonl").read_text().splitlines())}
    schedule = c.read(out / "ORDER.json")
    if len(rows) != cfg["updates"] or [r["step"] for r in rows] != list(range(1, 65)):
        raise ValueError("Incomplete or duplicate updates")
    initial, initial_hash = tensors(Path(cfg["source_models"]["D_rl"]["adapter"]))
    previous, prev_hash = initial, initial_hash
    if initial_hash != cfg["source_models"]["D_rl"]["parameter_fingerprint"]:
        raise ValueError("Parent tensor identity mismatch")
    details, max_error = [], 0.0
    for row, planned in zip(rows, schedule):
        step = row["step"]
        folder = out / "checkpoints" / f"step-{step:05d}"
        if c.read(folder / "COMMITTED.json") != row or not (folder / "optimizer-rng.pt").is_file():
            raise ValueError("Checkpoint/log commit mismatch")
        if row["state_id"] != planned["state_id"] or row["origin"] != planned["origin"]:
            raise ValueError("Update order changed")
        current, fingerprint = tensors(folder / "adapter_model.safetensors")
        if (row["parameter_before"] != prev_hash or row["parameter_after"] != fingerprint
                or c.sha(folder / "adapter_model.safetensors") != row["adapter_file_sha256"]):
            raise ValueError("Parameter identity chain broken")
        changed = sum(np.count_nonzero(current[n] != initial[n]) for n in current)
        update_changed = sum(np.count_nonzero(current[n] != previous[n]) for n in current)
        l2 = sum(float(np.square(current[n].astype(float) - initial[n]).sum()) for n in current) ** .5
        if changed != row["changed_values_from_start"] or update_changed == 0 or abs(l2 - row["parameter_l2_from_start"]) > 1e-7:
            raise ValueError("Parameter change claim unsupported")
        before = np.asarray(row["probabilities_before"], dtype=float)
        after = np.asarray(row["probabilities_after"], dtype=float)
        returns = np.asarray(states[row["state_id"]]["returns"], dtype=float)
        reference = references[row["state_id"]]
        if reference["parameter_fingerprint"] != initial_hash:
            raise ValueError("Incorrect frozen reference")
        ref = np.asarray(reference["logits"], dtype=float) / cfg["temperature"]
        ref_logp = ref - (np.log(np.exp(ref - ref.max()).sum()) + ref.max())
        advantage = (returns - returns.mean()) / max(returns.std(), .1)
        if any(not np.isfinite(a).all() for a in [before, after, returns]) or min(before.min(), after.min()) < 0:
            raise ValueError("Invalid probability or reward")
        if max(abs(before.sum() - 1), abs(after.sum() - 1)) > 2e-6:
            raise ValueError("Probability normalization mismatch")
        logp = np.log(np.maximum(before, np.finfo(float).tiny))
        entropy = -float((before * logp).sum())
        kl = float((before * (logp - ref_logp)).sum())
        loss = -float((before * advantage).sum()) + cfg["kl_coefficient"] * kl - cfg["entropy_coefficient"] * entropy
        checks = [(loss, row["loss"]), (entropy, row["entropy"]), (kl, row["kl_to_starting_rl"]),
                  (float(before @ returns), row["expected_two_step_return_before"]),
                  (float(after @ returns), row["expected_two_step_return_after"])]
        error = max(abs(a-b) for a, b in checks)
        max_error = max(error, max_error)
        if (error > 5e-6 or np.max(np.abs(advantage - row["advantage"])) > 5e-6
                or row["action_returns"] != states[row["state_id"]]["returns"]
                or not np.isfinite(row["gradient_norm_before_clip"]) or row["gradient_norm_before_clip"] <= 0
                or row["choice_before"] != LETTERS[int(before.argmax())] or row["choice_after"] != LETTERS[int(after.argmax())]):
            raise ValueError("RL arithmetic / action / gradient claim mismatch at step " + str(step))
        details.append({"step": step, "tensor_fingerprint": fingerprint, "changed_values_this_update": int(update_changed),
                        "l2_from_start": l2, "max_arithmetic_error": error, "optimizer_file_sha256": c.sha(folder / "optimizer-rng.pt")})
        previous, prev_hash = current, fingerprint
    if prev_hash != complete["rl_after"] or complete["updates"] != 64 or complete["rl_before"] != initial_hash:
        raise ValueError("Completion marker mismatch")
    result = {"time": c.now(), "passed": True, "updates_verified": len(rows), "updates_with_real_tensor_changes": len(details),
              "trainable_values": sum(a.size for a in initial.values()), "max_rl_arithmetic_error": max_error,
              "final_l2_from_parent_rl": details[-1]["l2_from_start"], "new_model_loads": 0,
              "scope": "Source/data replay, every saved tensor delta/fingerprint and RL loss/reward arithmetic. Optimizer bytes preserved and hashed; no expensive retraining for optimizer replay.",
              "details": details}
    c.live.save(out / "PARAMETER_AND_OBJECTIVE_AUDIT.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "details"}))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.output.resolve())
