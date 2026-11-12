"""Bounded native evidence probe. No language model or training is performed."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent_training.expert_energy import API, ExpertEnergyBackend  # noqa: E402


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base", default="http://127.0.0.1:18810")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "engineering API contract probe, not model evaluation or final test",
        "model_calls": 0,
        "training_updates": 0,
        "sources": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__),
                ROOT / "app/agent_training/expert_energy.py",
                ROOT / "app/agent_training/expert_contracts.py",
            ]
        },
    }
    save(args.output / "MANIFEST.json", manifest)
    results = []
    parameters = {"baseline_green_preference": 0.5, "green_preference": 0.82, "carbon_price_cny_per_ton": 85.0}
    for number, green in enumerate([0.82, 0.5], start=1):
        folder = args.output / ("trial-" + str(number))
        tool = ExpertEnergyBackend(folder, args.base)
        context = tool.read_context()
        parameters["green_preference"] = green
        request_id = "expert-probe-" + hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:32]
        tool.compare(parameters, request_id, withhold_response=True)
        restarted = ExpertEnergyBackend(folder, args.base)
        prevented = False
        try:
            restarted.compare(parameters, request_id + "x")
        except RuntimeError:
            prevented = True
        if not prevented:
            raise RuntimeError("unknown-write resubmission was not prevented")
        restarted.recover()
        result = restarted.verify({"min_carbon_reduction_pct": 0.0, "max_cost_cny": 1e9, "min_service_pct": 98.0})
        duplicate = restarted.request(API, restarted.state["receipt"]["parameters"])
        if duplicate.get("duplicate") is not True or duplicate["receipt"] != restarted.state["receipt"]:
            raise RuntimeError("duplicate calculation did not return the original receipt")
        errors = {}
        for name, payload in [
            ("stale_source", {**parameters, "request_id": request_id + "s", "expected_source_version": "0" * 64}),
            ("changed_parameters_same_id", {**restarted.state["receipt"]["parameters"], "green_preference": 0.1}),
            (
                "missing_parameter",
                {
                    "request_id": request_id + "m",
                    "expected_source_version": context["source_version"],
                    "baseline_green_preference": 0.5,
                    "green_preference": green,
                },
            ),
        ]:
            try:
                restarted.request(API, payload)
            except HTTPError as exc:
                errors[name] = {"status": exc.code, "body": exc.read().decode()}
            else:
                raise RuntimeError("invalid request was not rejected: " + name)
        if [errors[name]["status"] for name in errors] != [409, 409, 422]:
            raise RuntimeError("unexpected rejection status")
        result.update(
            response_loss_recovered=True,
            duplicate_reused=True,
            unsafe_resubmission_prevented=True,
            error_probes=errors,
            context=context,
        )
        save(folder / "RESULT.json", result)
        results.append(result)
        print(
            json.dumps(
                {
                    "trial": number,
                    "assessment": result["assessment"],
                    "service_pct": [r["service_pct"] for r in result["alternatives"]],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    ready = all(f["status"] == "ready" for r in results for f in r["alternatives"])
    summary = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "model_calls": 0,
        "training_updates": 0,
        "native_trials": len(results),
        "all_facts_ready": ready,
        "business_outcomes": [r["assessment"]["status"] for r in results],
        "recovery_and_request_checks_passed": True,
        "scope": "two engineering probes using local public-data-calibrated calculations; not learned model success",
    }
    save(args.output / "SUMMARY.json", summary)
    if not ready:
        raise SystemExit("Missing evidence preserved; inspect RESULT files before training")


if __name__ == "__main__":
    main()
