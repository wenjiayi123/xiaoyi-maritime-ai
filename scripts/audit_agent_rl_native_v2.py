"""Replay recorded native decisions without contacting APIs or rerunning models."""

from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.environment import LETTERS, digest  # noqa: E402
from app.agent_training.live import environment_for_job, native_step, save  # noqa: E402


def load(path):
    return json.loads(path.read_text())


def audit(run, folders):
    summary = load(run / "audited-summary.json")
    plan = load(run / "native-acceptance-plan.json")
    expected = {(g, task["id"]): task for g in plan["groups"] for task in plan["tasks"]}
    seen, results = set(), []
    for folder in folders:
        job = load(folder / "job.json")
        matches = [t for t in plan["tasks"] if t["goal"] == job["goal"]]
        if len(matches) != 1:
            raise ValueError("unregistered native command")
        task = matches[0]
        key = job["group"], task["id"]
        if key not in expected or key in seen:
            raise ValueError("unregistered or repeated native attempt")
        seen.add(key)
        contract = {k: v for k, v in job["task"].items() if k != "case_id"}
        if contract != task["normalized_contract"] or job["experiment"] != run.name:
            raise ValueError("native contract or experiment mismatch")
        weight_key = {"C_sft": "sft", "D_rl": "rl"}[job["group"]]
        fingerprint = summary["weights"][weight_key]
        if job["expected_adapter_sha256"] != fingerprint:
            raise ValueError("wrong model in native execution")
        env = environment_for_job(job)
        for actual in job["steps"]:
            if actual["decision_input"] != env.prompt():
                raise ValueError("native decision was given a different state")
            model = actual["model"]
            probs = model["probabilities"]
            if (
                model["adapter_sha256"] != fingerprint
                or model["group"] != job["group"]
                or len(probs) != 13
                or not all(math.isfinite(p) and p >= 0 for p in probs)
                or not math.isclose(sum(probs), 1, abs_tol=2e-6)
                or LETTERS[max(range(13), key=lambda i: probs[i])] != actual["choice"]
                or model["choice"] != actual["choice"]
                or not actual["model_action"]
            ):
                raise ValueError("native action not supported by model probabilities")

            class RecordedBackend:
                def execute(self, action, state):
                    if actual.get("native_result_valid") is False:
                        raise RuntimeError(actual["feedback"].removeprefix("native_error:"))
                    entry = actual["native_evidence"]
                    record = load(folder / entry["file"])
                    if digest(record) != entry["sha256"] or record["action"] != action:
                        raise ValueError("native raw response or action changed")
                    if record["production_authority"] is not False:
                        raise ValueError("native evidence outside simulation scope")
                    return record["response"]

                def record(self, action, response):
                    return actual["native_evidence"]

            rebuilt = native_step(env, RecordedBackend(), actual["choice"])
            rebuilt.update(decision_input=actual["decision_input"], model=model)
            if rebuilt != actual:
                raise ValueError("native state/feedback transcript replay mismatch")
        if job.get("outcome") is not None and env.outcome() != job["outcome"]:
            raise ValueError("native reported outcome differs from replay")
        if job["success"] != env.success or job["status"] not in {"completed", "failed"}:
            raise ValueError("native completion not supported by actions")
        evidence = {}
        for entry in job.get("evidence", []):
            record = load(folder / entry["file"])
            if digest(record) != entry["sha256"]:
                raise ValueError("native evidence hash mismatch")
            evidence[entry["file"]] = record
        if job["success"]:
            report = load(folder / "report.json")
            if not (folder / "report.html").is_file() or not all(report["verification"]["checks"].values()):
                raise ValueError("completed native task lacks verified deliverable")
            final = evidence[job["steps"][-1]["native_evidence"]["file"]]["response"]
            if final["sha256"] != digest(report):
                raise ValueError("report differs from tool result")
            required = {r + ".read" for r in env.required["reads"]}
            if env.required["port"]:
                required.add("port.evaluate")
            if env.required["energy"]:
                required.add("energy.compare")
            if not required <= {r["action"]["tool"] for r in evidence.values()}:
                raise ValueError("completed report lacks actual required tool responses")
            for r in evidence.values():
                if r["action"]["tool"] == "energy.compare":
                    alternatives = r["response"]["alternatives"]
                    if [a["parameters"]["green"] for a in alternatives] != [env.task.baseline, env.task.green]:
                        raise ValueError("reported energy alternatives mismatch requested parameters")
                    for alternative in alternatives:
                        raw = alternative["raw"]
                        if (
                            raw["green_preference"] != alternative["parameters"]["green"]
                            or raw["carbon_market"]["carbon_price_cny_per_ton"] != env.task.carbon
                        ):
                            raise ValueError("actual energy solver parameter echo mismatch")
        results.append(
            {
                "group": job["group"],
                "task": task["id"],
                "job_id": job["id"],
                "success": job["success"],
                "steps": len(job["steps"]),
                "raw_response_files": len(evidence),
                "model_parameter_sha256": fingerprint,
                "job_file_sha256": hashlib.sha256((folder / "job.json").read_bytes()).hexdigest(),
                "replayed": True,
            }
        )
    if seen != set(expected):
        raise ValueError("not all six registered native attempts were supplied")
    output = {
        "all_records_replayed": True,
        "model_calls_during_audit": 0,
        "external_API_calls_during_audit": 0,
        "scope": "offline transcript, raw-response, parameter, model-probability and deliverable consistency; not field validation or third-party attestation",
        "D_at_least_one_task_complete": any(r["success"] for r in results if r["group"] == "D_rl"),
        "D_joint_completed": any(r["success"] for r in results if r["group"] == "D_rl" and r["task"] == "joint"),
        "results": results,
    }
    save(run / "native-acceptance-audit.json", output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--job", type=Path, action="append", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.experiment.resolve(), args.job), ensure_ascii=False))
