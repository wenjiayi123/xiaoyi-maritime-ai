"""Independent CE/logit gradients, parameter chain and full training gates."""

import argparse
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.freeze_agent_expert_recovery import verify  # noqa: E402
from scripts.agent_expert_recovery_support import LETTERS, learning_rate, ready, replay_gate, read, save, sha, now  # noqa: E402
from scripts.audit_agent_capability_adaptation import tensors  # noqa: E402


def audit(out):
    cfg = verify(out)
    complete = read(out / "TRAINING_COMPLETE.json")
    states = {s["state_id"]: s for s in read(out / "STATES.json")}
    order = read(out / "ORDER.json")
    rows = [json.loads(s) for s in (out / "training.jsonl").read_text().splitlines()]
    count = complete["updates"]
    if not 1 <= count <= cfg["max_updates"] or len(rows) != count or complete["heldout_opened"]:
        raise ValueError("Invalid training budget/completion")
    initial, fp = tensors(Path(cfg["parent"]["adapter"]))
    previous = initial
    if fp != cfg["parent"]["parameter_fingerprint"]:
        raise ValueError("Parent fingerprint mismatch")
    largest = 0.0
    audit_rows = []
    for index, row in enumerate(rows, 1):
        checkpoint = out / "checkpoints" / f"step-{index:05d}"
        if row["step"] != index or row["minibatch"] != order[index - 1] or read(checkpoint / "COMMITTED.json") != row:
            raise ValueError("Commit or order mismatch")
        if abs(row["learning_rate"] - learning_rate(index, cfg)) > 1e-14:
            raise ValueError("Schedule mismatch")
        if sha(checkpoint / "optimizer-rng.pt") != row["optimizer_sha256"]:
            raise ValueError("Optimizer/RNG hash mismatch")
        current, current_fp = tensors(checkpoint / "adapter_model.safetensors")
        if (
            row["parameter_before"] != fp
            or row["parameter_after"] != current_fp
            or sha(checkpoint / "adapter_model.safetensors") != row["adapter_file_sha256"]
        ):
            raise ValueError("Weight chain mismatch")
        changed = sum(int(np.count_nonzero(current[k] != previous[k])) for k in current)
        delta = sum(float(np.square((current[k] - previous[k]).astype(float)).sum()) for k in current) ** 0.5
        total = sum(float(np.square((current[k] - initial[k]).astype(float)).sum()) for k in current) ** 0.5
        if (
            abs(delta - row["parameter_step_l2"]) > 1e-8
            or abs(total - row["parameter_l2_from_parent"]) > 1e-8
            or bool(changed) != row["parameter_changed"]
        ):
            raise ValueError("Parameter change not supported")
        if [d["state_id"] for d in row["details"]] != order[index - 1]["states"]:
            raise ValueError("Exposures mismatch")
        errors = []
        for detail in row["details"]:
            state = states[detail["state_id"]]
            if detail["target"] != state["target"] or detail["origin"] != state["origin"]:
                raise ValueError("Target mismatch")
            z = np.asarray(detail["logits_before"], dtype=float)
            target = LETTERS.index(state["target"])
            probs = np.exp(z - z.max())
            probs /= probs.sum()
            gradient = probs.copy()
            gradient[target] -= 1
            loss = float(np.log(np.exp(z - z.max()).sum()) + z.max() - z[target])
            errors += [
                abs(loss - detail["loss"]),
                float(np.max(np.abs(probs - detail["probabilities"]))),
                float(np.max(np.abs(gradient - detail["gradient_logits_unaveraged"]))),
            ]
        errors.append(abs(row["loss"] - np.mean([d["loss"] for d in row["details"]])))
        if not all(np.isfinite(errors)) or max(errors) > 1e-5 or not np.isfinite(row["gradient_norm_before_clip"]):
            raise ValueError("Loss/gradient audit failed")
        largest = max(largest, *errors)
        audit_rows.append(dict(step=index, changed_values=changed, max_error=max(errors)))
        previous, fp = current, current_fp
    if not any(r["changed_values"] for r in audit_rows):
        raise ValueError("No actual parameter learning")
    if fp != complete["parameter_fingerprint"] or sha(Path(complete["adapter"])) != complete["file_sha256"]:
        raise ValueError("Final weight mismatch")
    cases = {c["case_id"]: c for c in read(out / "GATE_CASES.json")}
    gates = read(out / "TRAINING_GATES.json")
    expected_steps = list(range(64, count + 1, 64))
    if [g["step"] for g in gates] != expected_steps or complete["training_gates"] != gates:
        raise ValueError("Missing readiness gate")
    for i, g in enumerate(gates):
        result = read(Path(g["file"]))
        if sha(Path(g["file"])) != g["sha256"] or result["passed"] != g["passed"]:
            raise ValueError("Gate summary drift")
        checkpoint_fp = tensors(out / "checkpoints" / f"step-{g['step']:05d}" / "adapter_model.safetensors")[1]
        if (
            result["fingerprint"] != checkpoint_fp
            or len(result["rows"]) != 48
            or {r["case_id"] for r in result["rows"]} != set(cases)
        ):
            raise ValueError("Incomplete or wrong-policy gate")
        for row in result["rows"]:
            job = read(Path(row["trajectory"]))
            if sha(Path(row["trajectory"])) != row["sha256"] or job["fingerprint"] != checkpoint_fp:
                raise ValueError("Gate trace drift")
            replay_gate(cases[row["case_id"]], job)
            if row["correct"] != job["metrics"]["decision_correct"]:
                raise ValueError("Gate score mismatch")
        if g["passed"] != all(r["correct"] for r in result["rows"]):
            raise ValueError("False readiness")
        if ready(gates[: i + 1]) and i != len(gates) - 1:
            raise ValueError("Trained beyond registered stopping gate")
    if complete["warm_ready"] != ready(gates) or (not ready(gates) and count != 512):
        raise ValueError("Stopping rule mismatch")
    report = dict(
        time=now(),
        passed=True,
        updates=count,
        maximum_error=largest,
        changed_values_audit=audit_rows,
        readiness_gates_replayed=len(gates),
        warm_ready=complete["warm_ready"],
        capability_accepted=False,
        model_loads=0,
        scope="Independent safetensor delta/identity chain, CE and logit gradients, optimizer/RNG hashes, all training gates; no optimizer-step replay",
    )
    save(out / "PARAMETER_AND_OBJECTIVE_AUDIT.json", report)
    print({k: v for k, v in report.items() if k != "changed_values_audit"})


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--experiment", type=Path, required=True)
    audit(p.parse_args().experiment.resolve())
