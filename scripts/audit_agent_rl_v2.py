"""Recompute V2 held-out outcomes, action evidence, training counts and weights."""

from __future__ import annotations
import argparse
import copy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.environment import LETTERS, TaskSpec, digest, reference_action  # noqa: E402
from app.agent_training.environment_v2 import ProgressEnvironment, counterfactuals, replay_state  # noqa: E402
from scripts.run_agent_rl_v1 import RETENTION, save  # noqa: E402


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(a, b):
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return math.isclose(a, b, abs_tol=1e-12, rel_tol=0)
    return a == b


def timestamp(value):
    # Python 3.9 requires a colon in the UTC offset; the preserved training
    # records use strftime('%z'), whereas the web environment uses Python 3.12.
    if value[-5] in "+-" and value[-4:].isdigit():
        value = value[:-2] + ":" + value[-2:]
    return datetime.fromisoformat(value)


def audit_selection(folder, selection):
    amendment_ref = selection.get("selection_amendment")
    if not amendment_ref:
        return {"amended": False}
    amendment = read(folder / amendment_ref["file"])
    start = read(folder / "selection-refinement-start.json")
    original_path = folder / amendment_ref["original_selection_file"]
    if (
        sha(folder / amendment_ref["file"]) != amendment_ref["sha256"]
        or start["amendment_sha256"] != amendment_ref["sha256"]
        or sha(original_path) != amendment_ref["original_selection_sha256"]
        or start["original_selection_sha256"] != amendment_ref["original_selection_sha256"]
        or sha(folder / "selection-refinement-source.py") != start["script_sha256"]
        or sha(folder / "config.json") != amendment["config_sha256"]
        or sha(folder / "task-manifest.json") != amendment["task_manifest_sha256"]
    ):
        raise ValueError("selection amendment provenance mismatch")
    if not (
        timestamp(amendment["at"])
        <= timestamp(start["at"])
        <= timestamp(selection["at"])
        <= timestamp(read(folder / "test-opened.json")["at"])
    ):
        raise ValueError("checkpoint refinement/test chronology mismatch")
    all_candidates = read(folder / "selection-refinement-candidates.json")
    baseline = read(folder / "retention/validation-C_sft.json")["accuracy"]
    for group in amendment["groups"]:
        rows = all_candidates[group]
        produced = [s for s in amendment["grid"] if (folder / "checkpoints" / group / f"step-{s:05d}").exists()]
        if [r["step"] for r in rows] != produced:
            raise ValueError("checkpoint grid incomplete or selected asymmetrically")
        for row in rows:
            name = f"validation-{group}-{row['step']}"
            keep = read(folder / "retention" / (name + ".json"))
            if len(keep["rows"]) != len(RETENTION) or any(
                r["prompt"] != prompt or r["expected"] != answer for r, (prompt, answer) in zip(keep["rows"], RETENTION)
            ):
                raise ValueError("selection used different retention questions")
            accuracy = sum(r["choice"] == answer for r, (_, answer) in zip(keep["rows"], RETENTION)) / len(RETENTION)
            if keep != row["retention"] or keep["accuracy"] != accuracy or row["eligible"] != (accuracy >= baseline):
                raise ValueError("selection retention gate mismatch")
            if row["validation"] is not None:
                val = read(folder / "evaluations" / (name + ".json"))
                if val != row["validation"] or val["successes"] != sum(c["success"] for c in val["cases"]):
                    raise ValueError("selection validation evidence mismatch")
        eligible = [r for r in rows if r["eligible"] and r["validation"]]
        if eligible:
            best = max(
                eligible,
                key=lambda r: (
                    r["validation"]["successes"],
                    -r["validation"]["total_errors"],
                    -r["validation"]["mean_steps"],
                    -r["step"],
                ),
            )
            if any(selection["selected"][group][k] != best[k] for k in ["step", "checkpoint", "parameter_sha256"]):
                raise ValueError("checkpoint selection violates registered ranking")
    return {"amended": True, "grid": amendment["grid"], "same_grid_both_groups": True, "test_used": False}


def audit_independent_retention(folder, result):
    manifest = read(folder / "retention-holdout-manifest.json")
    opened = read(folder / "retention-holdout-opened.json")
    questions = read(folder / "retention-holdout-questions.json")
    data = read(folder / "retention-independent-summary.json")
    if (
        manifest["questions_sha256"] != sha(folder / "retention-holdout-questions.json")
        or opened["manifest_sha256"] != sha(folder / "retention-holdout-manifest.json")
        or opened["selection_sha256"] != sha(folder / "checkpoint-selection.json")
        or data["questions_sha256"] != manifest["questions_sha256"]
        or data["selection_sha256"] != opened["selection_sha256"]
        or manifest["used_for_training"]
        or manifest["used_for_checkpoint_selection"]
        or len(questions) != manifest["count"]
    ):
        raise ValueError("independent retention protocol mismatch")
    if timestamp(manifest["at"]) > timestamp(read(folder / "test-opened.json")["at"]):
        raise ValueError("retention holdout defined after final test")
    decisions = [json.loads(s) for s in (folder / "retention-holdout-decisions.jsonl").read_text().splitlines()]
    if len(decisions) != 4 * len(questions):
        raise ValueError("independent retention decisions missing or repeated")
    for group, key in [("B_base", "initial"), ("C_sft", "sft"), ("D_rl", "rl"), ("E_more_sft", "more_sft")]:
        recorded = data["groups"][group]
        rows = recorded["rows"]
        if rows != [r for r in decisions if r["group"] == group] or len(rows) != len(questions):
            raise ValueError("independent retention raw record mismatch")
        if recorded != read(folder / "retention-independent" / (group + ".json")):
            raise ValueError("independent retention group mismatch")
        for row, question in zip(rows, questions):
            probs = row["probabilities"]
            if (
                any(row[k] != value for k, value in question.items())
                or row["parameter_sha256"] != result["weights"][key]
                or len(probs) != 13
                or not all(math.isfinite(p) and p >= 0 for p in probs)
                or not math.isclose(sum(probs), 1, abs_tol=2e-6)
                or row["choice"] != LETTERS[max(range(13), key=lambda i: probs[i])]
                or row["correct"] != (row["choice"] == row["expected"])
            ):
                raise ValueError("independent retention action/answer mismatch")
        correct = sum(r["correct"] for r in rows)
        if (
            recorded["n"] != len(questions)
            or recorded["correct"] != correct
            or recorded["accuracy"] != correct / len(questions)
        ):
            raise ValueError("independent retention score mismatch")
    return data


def audit(folder):
    raw = read(folder / "summary.json")
    result = copy.deepcopy(raw)
    tasks = read(folder / "tasks/test.json")
    if digest(tasks) != read(folder / "task-manifest.json")["partitions"]["test"]["sha256"]:
        raise ValueError("test manifest mismatch")
    expected = {t["case_id"]: t for t in tasks}
    if len(expected) != len(tasks) or set(result["groups"]) != {"A_rules", "B_base", "C_sft", "D_rl", "E_more_sft"}:
        raise ValueError("five complete groups with unique cases required")
    selection = read(folder / "checkpoint-selection.json")
    if read(folder / "test-opened.json")["selection_sha256"] != sha(folder / "checkpoint-selection.json"):
        raise ValueError("checkpoint selection changed after opening test")
    if selection["config_sha256"] != sha(folder / "config.json"):
        raise ValueError("protocol changed")
    selection_audit = audit_selection(folder, selection)
    for source in read(folder / "source-manifest.json"):
        if sha(folder / "source" / source["path"]) != source["sha256"]:
            raise ValueError("source snapshot changed")
    for filename in ["environment.py", "environment_v2.py"]:
        rel = "app/agent_training/" + filename
        if sha(ROOT / rel) != sha(folder / "source" / rel):
            raise ValueError("audit environment differs from run; use saved source")
    checks = []
    for name, group in result["groups"].items():
        if len(group["cases"]) != len(expected) or {c["case_id"] for c in group["cases"]} != set(expected):
            raise ValueError("groups evaluated different cases")
        for case in group["cases"]:
            trace = read(folder / "trajectories" / name / (case["case_id"] + ".json"))
            if trace["task"] != expected[case["case_id"]] or digest(trace["steps"]) != case["trajectory_sha256"]:
                raise ValueError("task or trajectory checksum mismatch")
            if trace["outcome"] != case or len(trace["decisions"]) != len(trace["steps"]):
                raise ValueError("missing or inconsistent decision evidence")
            env = ProgressEnvironment(TaskSpec(**trace["task"]))
            matches = 0
            for step, decision in zip(trace["steps"], trace["decisions"]):
                if decision["prompt"] != env.prompt() or decision["label"] != step["choice"]:
                    raise ValueError("decision input/action mismatch")
                if name == "A_rules":
                    if step["choice"] != reference_action(env) or step["model_action"]:
                        raise ValueError("rule baseline mismatch")
                else:
                    probabilities = decision["probabilities"]
                    if len(probabilities) != 13 or not all(math.isfinite(p) and p >= 0 for p in probabilities):
                        raise ValueError("invalid model probabilities")
                    if not math.isclose(sum(probabilities), 1, abs_tol=2e-6):
                        raise ValueError("model distribution not normalized")
                    selected = max(range(13), key=lambda j: probabilities[j])
                    if LETTERS[selected] != step["choice"] or not step["model_action"]:
                        raise ValueError("action not selected by model argmax")
                rebuilt = env.step(step["choice"])
                for key in ["action", "ok", "feedback", "reward", "reward_components", "after", "result"]:
                    if rebuilt[key] != step[key]:
                        raise ValueError("replay mismatch: " + key)
                if step["action"]["tool"] == "energy.compare":
                    a, t = step["action"]["arguments"], env.task
                    matches += (
                        a["green_preference"] == t.green
                        and a["carbon_price_cny_per_ton"] == t.carbon
                        and a["baseline_green_preference"] == t.baseline
                    )
            outcome = env.outcome()
            for key in [
                "success",
                "steps",
                "reward",
                "errors",
                "parameter_attempts",
                "parameter_correct",
                "fault_injected",
                "recovered",
                "checks",
            ]:
                if not close(outcome[key], case[key]):
                    raise ValueError("outcome mismatch: " + key)
            if matches != case["parameter_matches"]:
                raise ValueError("parameter match count mismatch")
            if abs(sum(s["reward_components"]["potential_shaping"] for s in env.steps)) > 1e-12:
                raise ValueError("terminal potential did not telescope")
            checks.append({"group": name, "case_id": case["case_id"], "reproduced": True})
        cases = group["cases"]
        attempts = sum(c["parameter_attempts"] for c in cases)
        faults = [c for c in cases if c["family"] in {"read_recovery", "write_recovery"}]
        metrics = {
            "n": len(cases),
            "successes": sum(c["success"] for c in cases),
            "success_rate": sum(c["success"] for c in cases) / len(cases),
            "mean_steps": sum(c["steps"] for c in cases) / len(cases),
            "mean_reward": sum(c["reward"] for c in cases) / len(cases),
            "total_errors": sum(c["errors"] for c in cases),
            "parameter_attempts": attempts,
            "parameter_accuracy": sum(c["parameter_matches"] for c in cases) / attempts if attempts else None,
            "fault_cases": len(faults),
            "fault_exposed_cases": sum(c["fault_injected"] for c in faults),
            "recovery_rate": sum(c["recovered"] for c in faults) / len(faults) if faults else None,
        }
        for key, value in metrics.items():
            if not close(group[key], value):
                raise ValueError("aggregate mismatch: " + key)
        for family, values in group["by_family"].items():
            cases_of_family = [c for c in cases if c["family"] == family]
            if values != {"n": len(cases_of_family), "successes": sum(c["success"] for c in cases_of_family)}:
                raise ValueError("family metric mismatch")
    states = read(folder / "training-states.json")
    if digest(states) != read(folder / "dataset-integrity.json")["states_sha256"]:
        raise ValueError("training state checksum changed")
    state_map = {r["state_id"]: r for r in states}
    branch_count = 0
    for state_index, record in enumerate(states):
        training_env = replay_state(record)
        file = folder / record["counterfactual_file"]
        if sha(file) != record["counterfactual_sha256"] or record["task"]["split"] != "train":
            raise ValueError("counterfactual evidence changed or holdout used")
        branches = read(file)
        if branches != counterfactuals(training_env):
            raise ValueError("counterfactual reward/transition replay mismatch")
        if (state_index + 1) % 50 == 0:
            print(
                json.dumps({"stage": "training_reward_replay", "states": state_index + 1, "total": len(states)}),
                flush=True,
            )
        values = []
        for label in LETTERS:
            row = branches[label]
            branch_count += 1 + len(row["following"])
            if row["first"]["model_action"] or any(r["model_action"] for r in row["following"].values()):
                raise ValueError("simulator expansion mislabeled as model execution")
            values.append(row["first"]["reward"] + max((r["reward"] for r in row["following"].values()), default=0))
        if values != record["rewards"]:
            raise ValueError("two-step training returns mismatch")
    updates = [json.loads(line) for line in (folder / "training.jsonl").read_text().splitlines()]
    config = read(folder / "config.json")
    phase_states = {phase: [r["state_id"] for r in updates if r["stage"] == phase] for phase in ["D_rl", "E_more_sft"]}
    common_length = min(map(len, phase_states.values()))
    if phase_states["D_rl"][:common_length] != phase_states["E_more_sft"][:common_length]:
        raise ValueError("training state order differs between controls")
    counts = {}
    for phase in ["D_rl", "E_more_sft"]:
        rows = [r for r in updates if r["stage"] == phase]
        if [r["step"] for r in rows] != list(range(1, len(rows) + 1)):
            raise ValueError("training step gaps or duplicate updates")
        if len(rows) != raw["training_counts"][phase]:
            raise ValueError("training count mismatch")
        for r in rows:
            if r["state_id"] not in state_map or not all(
                math.isfinite(r[k]) for k in ["loss", "entropy", "gradient_norm_before_clip", "seconds"]
            ):
                raise ValueError("invalid training update")
            if phase == "D_rl" and "supervised_target" in r:
                raise ValueError("supervised label in RL update evidence")
            if phase == "D_rl":
                if r["action_returns"] != state_map[r["state_id"]]["rewards"]:
                    raise ValueError("RL optimized different returns than replayed environment")
                for suffix in ["before", "after"]:
                    probs = r["probabilities_" + suffix]
                    expected_return = sum(p * q for p, q in zip(probs, r["action_returns"]))
                    if not math.isclose(expected_return, r["expected_two_step_return_" + suffix], abs_tol=2e-6):
                        raise ValueError("RL expected-return curve disagrees with raw action probabilities")
                    if LETTERS[max(range(13), key=lambda i: probs[i])] != r["choice_" + suffix]:
                        raise ValueError("training argmax action mismatch")
                recomputed_loss = (
                    -sum(p * a for p, a in zip(r["probabilities_before"], r["advantage"]))
                    + config["kl_coefficient"] * r["kl_to_frozen_sft"]
                    - config["entropy_coefficient"] * r["entropy"]
                )
                if not math.isclose(recomputed_loss, r["loss"], abs_tol=2e-6):
                    raise ValueError("RL objective log mismatch")
        counts[phase] = {
            "updates": len(rows),
            "update_seconds": sum(r["seconds"] for r in rows),
            "selected_step": selection["selected"][phase]["step"],
        }
    from safetensors.numpy import load_file
    import numpy as np

    c = load_file(str(folder / "checkpoints/sft/adapter_model.safetensors"))
    d = load_file(str(folder / "checkpoints/rl/adapter_model.safetensors"))

    def parameter_fingerprint(arrays):
        h = hashlib.sha256()
        for key in sorted(arrays):
            name = key.replace(".lora_A.weight", ".lora_A.default.weight").replace(
                ".lora_B.weight", ".lora_B.default.weight"
            )
            h.update(name.encode())
            h.update(arrays[key].tobytes())
        return h.hexdigest()

    for label in ["sft", "rl", "more_sft"]:
        arrays = load_file(str(folder / "checkpoints" / label / "adapter_model.safetensors"))
        actual = parameter_fingerprint(arrays)
        if actual != result["weights"][label]:
            raise ValueError("saved adapter parameter fingerprint mismatch")
        if label != "sft":
            phase = "D_rl" if label == "rl" else "E_more_sft"
            chosen = selection["selected"][phase]
            selected_arrays = load_file(str(folder / chosen["checkpoint"] / "adapter_model.safetensors"))
            if parameter_fingerprint(selected_arrays) != actual or chosen["parameter_sha256"] != actual:
                raise ValueError("aliased checkpoint differs from frozen selection")
    if set(c) != set(d):
        raise ValueError("adapter topology mismatch")
    delta = {
        "parameters": sum(x.size for x in c.values()),
        "changed_values": sum(int(np.count_nonzero(c[k] != d[k])) for k in c),
        "max_absolute_change": max(float(np.max(np.abs(c[k] - d[k]))) for k in c),
        "all_finite": all(bool(np.isfinite(x).all()) for x in d.values()),
        "sft_file_sha256": sha(folder / "checkpoints/sft/adapter_model.safetensors"),
        "rl_file_sha256": sha(folder / "checkpoints/rl/adapter_model.safetensors"),
        "per_tensor": [
            {
                "name": key,
                "parameters": c[key].size,
                "changed_values": int(np.count_nonzero(c[key] != d[key])),
                "max_absolute_change": float(np.max(np.abs(c[key] - d[key]))),
                "l2_change": float(np.linalg.norm((d[key] - c[key]).astype(np.float64))),
            }
            for key in sorted(c)
        ],
    }
    if not delta["all_finite"] or bool(delta["changed_values"]) != raw["rl_parameters_changed"]:
        raise ValueError("RL parameter change evidence mismatch")
    update_hashes = {(r["stage"], r["step"]): r["parameter_sha256"] for r in updates}
    weight_history = []
    for phase in ["D_rl", "E_more_sft"]:
        for checkpoint in sorted((folder / "checkpoints" / phase).glob("step-*")):
            metadata = read(checkpoint / "metadata.json")
            arrays = load_file(str(checkpoint / "adapter_model.safetensors"))
            fingerprint = parameter_fingerprint(arrays)
            if fingerprint != metadata["parameter_sha256"] or fingerprint != update_hashes[(phase, metadata["step"])]:
                raise ValueError("saved intermediate weights differ from update log")
            if set(arrays) != set(c) or not all(np.isfinite(v).all() for v in arrays.values()):
                raise ValueError("invalid intermediate adapter topology or values")
            weight_history.append(
                {
                    "phase": phase,
                    "step": metadata["step"],
                    "parameter_sha256": fingerprint,
                    "changed_values_from_C": sum(int(np.count_nonzero(c[k] != arrays[k])) for k in c),
                    "max_absolute_change_from_C": max(float(np.max(np.abs(c[k] - arrays[k]))) for k in c),
                    "l2_change_from_C": math.sqrt(
                        sum(float(np.square((arrays[k] - c[k]).astype(np.float64)).sum()) for k in c)
                    ),
                }
            )
    save(
        folder / "checkpoint-weight-history.json",
        {
            "scope": "actual saved LoRA parameter distances; not a task-capability metric",
            "baseline_parameter_sha256": result["weights"]["sft"],
            "checkpoints": weight_history,
        },
    )
    for other, field in [("C_sft", "rl_increment"), ("E_more_sft", "rl_vs_continued_sft")]:
        difference = result["groups"]["D_rl"]["success_rate"] - result["groups"][other]["success_rate"]
        if not close(raw[field], difference):
            raise ValueError("reported RL effect mismatch")
        a = {c["case_id"]: c for c in result["groups"][other]["cases"]}
        b = {c["case_id"]: c for c in result["groups"]["D_rl"]["cases"]}
        paired = {
            "failure_to_success": sum(not a[k]["success"] and b[k]["success"] for k in a),
            "success_to_failure": sum(a[k]["success"] and not b[k]["success"] for k in a),
        }
        pair_field = "paired_rl_effect" if other == "C_sft" else "paired_vs_continued_sft"
        if raw[pair_field] != paired:
            raise ValueError("paired effect mismatch")
    for group, recorded in result["retention"].items():
        file = read(folder / "retention" / (group + ".json"))
        if file != recorded or file["n"] != len(RETENTION) or len(file["rows"]) != len(RETENTION):
            raise ValueError("retention evidence mismatch")
        for row, (prompt, answer) in zip(file["rows"], RETENTION):
            if row["prompt"] != prompt or row["expected"] != answer or row["correct"] != (row["choice"] == answer):
                raise ValueError("retention answer mismatch")
        if file["accuracy"] != sum(r["correct"] for r in file["rows"]) / len(RETENTION):
            raise ValueError("retention accuracy mismatch")
    result["independent_retention"] = audit_independent_retention(folder, result)
    result["selection_audit"] = selection_audit
    result["status"] = "completed"
    result["audit"] = {
        "all_replayed": True,
        "trajectories": len(checks),
        "training_states": len(states),
        "counterfactual_transitions": branch_count,
        "counterfactual_transitions_replayed": True,
        "common_training_state_order_verified": common_length,
        "rl_expected_return_and_loss_recomputed": True,
        "all_intermediate_weights_verified": len(weight_history),
        "source_summary_sha256": sha(folder / "summary.json"),
        "model_calls_made_during_audit": 0,
        "outcomes_modified": False,
    }
    result["training_resource_counts"] = counts
    result["metric_definitions"] = {
        "success": "all required task conditions, verification and report delivery must finish within the action budget",
        "total_errors": "actions returning failure, including injected faults; valid but unproductive repeated actions are not counted here",
        "mean_steps": "all assigned tasks, including failures that use the full budget",
        "recovery_rate": "completed recoveries divided by all assigned read/write fault cases, including cases where the policy never reached the fault",
    }
    result["limitations"] = [
        raw["scope"],
        "single training seed; 8 development regression probes plus 20 new held-out probes, not comprehensive general-capability evidence",
        "two-step simulator lookahead, constrained 13-action policy",
        "same state/update cap; measured compute differs; no universal superiority claim",
        "D runs first and bears cold-prefix cache cost; E reuses cache. Timings include concurrent engineering checks and are not a controlled speed benchmark.",
    ]
    save(folder / "parameter-change-audit.json", delta)
    save(folder / "evaluation-audit.json", {"audit": result["audit"], "checks": checks})
    save(folder / "audited-summary.json", result)
    return {
        "audit": result["audit"],
        "parameter_change": delta,
        "successes": {k: v["successes"] for k, v in result["groups"].items()},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    print(json.dumps(audit(parser.parse_args().experiment), ensure_ascii=False))
