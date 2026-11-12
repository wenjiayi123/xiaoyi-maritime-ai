"""Independent loss/gradient arithmetic and complete tensor-chain audit."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_agent_expert_training import read, save, sha, verify  # noqa: E402
from scripts.audit_agent_capability_adaptation import tensors  # noqa: E402
from app.agent_training.expert_learning import numpy_actor_audit  # noqa: E402


def audit(out):
    import json

    cfg = verify(out)
    complete = read(out / "TRAINING_COMPLETE.json")
    if set(complete["routes"]) != set(cfg["route_order"]) or complete["sealed_tests_opened"]:
        raise ValueError("Unexpected completion marker")
    states = {r["state_id"]: r for r in read(out / "STATES.json")}
    labels = read(out / "SFT_LABELS.json")
    order = read(out / "ORDER.json")
    results = {}
    for route in cfg["route_order"]:
        folder = out / route
        final = complete["routes"][route]
        parent = cfg["parents"][route]
        initial, initial_fp = tensors(Path(parent["adapter"]))
        if initial_fp != parent["parameter_fingerprint"]:
            raise ValueError("Parent tensor fingerprint mismatch")
        if final["additional_updates"] == 0:
            check = read(folder / "parent-training-check/SUMMARY.json")
            if check["correct"] != 24 or check["total"] != 24 or final["file_sha256"] != parent["file_sha256"]:
                raise ValueError("Unsupported reuse decision")
            results[route] = {"reused": True, "updates": 0, "tensor_fingerprint": initial_fp}
            continue
        rows = [json.loads(line) for line in (folder / "training.jsonl").read_text().splitlines()]
        if len(rows) != 64 or [r["step"] for r in rows] != list(range(1, 65)):
            raise ValueError("Missing or repeated updates")
        previous, prev_fp = initial, initial_fp
        audits, largest = [], 0.0
        for row, scheduled in zip(rows, order):
            checkpoint = folder / "checkpoints" / f"step-{row['step']:05d}"
            if read(checkpoint / "COMMITTED.json") != row or row["minibatch"] != scheduled:
                raise ValueError("Commit or order mismatch")
            if [d["state_id"] for d in row["details"]] != scheduled["states"]:
                raise ValueError("State schedule mismatch")
            if sha(checkpoint / "optimizer-rng.pt") != row["optimizer_sha256"]:
                raise ValueError("Optimizer/RNG file drift")
            current, fp = tensors(checkpoint / "adapter_model.safetensors")
            if (
                row["parameter_before"] != prev_fp
                or row["parameter_after"] != fp
                or row["adapter_file_sha256"] != sha(checkpoint / "adapter_model.safetensors")
            ):
                raise ValueError("Broken tensor identity chain")
            changed = sum(int(np.count_nonzero(current[k] != previous[k])) for k in current)
            # Match the recorded float32 subtraction followed by float64 sum.
            step_l2 = sum(float(np.square((current[k] - previous[k]).astype(float)).sum()) for k in current) ** 0.5
            total_l2 = sum(float(np.square((current[k] - initial[k]).astype(float)).sum()) for k in current) ** 0.5
            if (
                changed == 0
                or abs(step_l2 - row["parameter_step_l2"]) > 1e-8
                or abs(total_l2 - row["parameter_l2_from_parent"]) > 1e-8
            ):
                raise ValueError("Unsupported parameter-change claim")
            errors = []
            for detail in row["details"]:
                state = states[detail["state_id"]]
                if route == "D_rl":
                    if "target" in detail or detail["returns"] != state["returns"]:
                        raise ValueError("RL labels/returns mismatch")
                    expected = numpy_actor_audit(
                        detail["logits_before"], detail["reference_logits"], state["returns"], cfg
                    )
                    for key in ("loss", "kl", "entropy", "expected_return", "advantages", "probabilities"):
                        errors.append(float(np.max(np.abs(np.asarray(detail[key]) - expected[key]))))
                    expected_gradient = expected["gradient_logits"]
                else:
                    z = np.asarray(detail["logits_before"], dtype=float)
                    logp = z - z.max() - np.log(np.exp(z - z.max()).sum())
                    p = np.exp(logp)
                    target = "ABCDEFGHIJKLM".index(labels[detail["state_id"]])
                    if detail["target"] != labels[detail["state_id"]]:
                        raise ValueError("SFT target mismatch")
                    errors.append(abs(-logp[target] - detail["loss"]))
                    errors.append(float(np.max(np.abs(p - detail["probabilities"]))))
                    expected_gradient = p.copy()
                    expected_gradient[target] -= 1
                errors.append(
                    float(np.max(np.abs(np.asarray(expected_gradient) - detail["gradient_logits_unaveraged"])))
                )
                temp = cfg["temperature"] if route == "D_rl" else 1.0
                z = np.asarray(detail["logits_after"]) / temp
                p = np.exp(z - z.max())
                p /= p.sum()
                errors.append(float(np.max(np.abs(p - detail["probabilities_after"]))))
            errors.append(abs(row["loss"] - np.mean([d["loss"] for d in row["details"]])))
            largest = max(largest, *errors)
            if (
                max(errors) > 1e-5
                or not np.isfinite(row["gradient_norm_before_clip"])
                or row["gradient_norm_before_clip"] <= 0
            ):
                raise ValueError("Arithmetic/gradient mismatch")
            audits.append(
                {
                    "step": row["step"],
                    "changed_tensor_values": changed,
                    "step_l2": step_l2,
                    "total_l2": total_l2,
                    "max_arithmetic_error": max(errors),
                    "fingerprint": fp,
                }
            )
            previous, prev_fp = current, fp
        if (
            prev_fp != final["parameter_fingerprint"]
            or sha(final["adapter"]) != final["file_sha256"]
            or final["additional_updates"] != 64
            or read(folder / "ROUTE_COMPLETE.json") != final
        ):
            raise ValueError("Final weight mismatch")
        results[route] = {
            "reused": False,
            "updates": 64,
            "max_arithmetic_error": largest,
            "trainable_values": sum(v.size for v in initial.values()),
            "details": audits,
        }
    result = {
        "passed": True,
        "model_loads": 0,
        "sealed_test_access": False,
        "routes": results,
        "scope": "Every committed adapter delta, optimizer/RNG hashes, action objective and analytic logit gradient; no optimizer-step replay",
    }
    save(out / "PARAMETER_AND_OBJECTIVE_AUDIT.json", result)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--experiment", type=Path, required=True)
    result = audit(p.parse_args().experiment.resolve())
    print({"passed": result["passed"], "routes": list(result["routes"]), "model_loads": 0})
