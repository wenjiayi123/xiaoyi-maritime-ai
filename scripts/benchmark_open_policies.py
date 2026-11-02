"""Predeclared paired fixtures, including failures; never train or tune on these seeds."""

import json
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.harness.transport import compare, fixture, health
from integrations.policy_runtime.contracts import sha

root = Path(".codex_artifacts/joint-harness-phase2-20261029")
fresh = "--fresh" in sys.argv
prefix = "policy-benchmark-fresh" if fresh else "policy-benchmark"
protocol = {
    "schema": "open-policy-benchmark.v1",
    "seeds": list(range(44301, 44311)) if fresh else list(range(44101, 44111)),
    "jobs": 30,
    "domains": [
        {"name": "CVRP", "objective": "total_distance_m", "heterogeneous": False, "allow_refill": False},
        {"name": "HCVRP", "objective": "makespan_seconds", "heterogeneous": True, "allow_refill": True},
    ],
    "selection": "all declared instances; no exclusions or checkpoint tuning",
    "ortools_budget_ms": 1000,
    "boundaries": "declared engineering fixtures; HCVRP compares the same refill-permitted contract against nearest-neighbor; OR-Tools restricted one-tour baseline excluded from that domain",
}
protocol["sha256"] = sha(protocol)
path = root / (prefix + "-protocol.json")
if path.exists() and json.loads(path.read_text()) != protocol:
    raise RuntimeError("frozen protocol changed")
path.write_text(json.dumps(protocol, indent=2))
results = []
started = time.time()
for domain in protocol["domains"]:
    for seed in protocol["seeds"]:
        case = fixture(seed, 30, domain["heterogeneous"]).model_copy(update={"allow_refill": domain["allow_refill"]})
        result = compare(case)
        results.append({"domain": domain["name"], "seed": seed, **result})
        (root / (prefix + ".json")).write_text(
            json.dumps(
                {
                    "protocol": protocol,
                    "results": results,
                    "complete": len(results) == 20,
                    "duration_seconds": time.time() - started,
                    "runtime": health(),
                },
                indent=2,
            )
        )
        print(
            domain["name"],
            seed,
            result["selected"]["model"],
            [
                (c["model"], c["validation"].get("feasible"), round(c["validation"].get("objective_value", 0), 3))
                for c in result["candidates"]
            ],
            flush=True,
        )
