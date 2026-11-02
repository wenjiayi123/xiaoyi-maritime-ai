"""Frozen additional instances with a reload-capable solver under the same contract."""

import json
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.harness.transport import compare, fixture, health
from integrations.policy_runtime.contracts import sha

root = Path(".codex_artifacts/joint-harness-phase2-20261029")
protocol = {
    "schema": "same-contract-policy-benchmark.v2",
    "seeds": list(range(44401, 44411)),
    "jobs": 30,
    "domains": [
        {"name": "CVRP", "heterogeneous": False, "allow_refill": False, "ortools_budget_ms": 1000},
        {"name": "HCVRP", "heterogeneous": True, "allow_refill": True, "ortools_budget_ms": 5000},
    ],
    "selection": "all declared instances; checkpoint frozen; no excluded infeasible candidates",
    "ortools_reload": "optional depot visits for each vehicle; same continuing physical vehicle clock and capacity; independent host verification",
    "primary_metric": "minimum feasible distance_m or makespan_seconds, including all feasible baselines; inference compute time reported separately",
    "evidence_class": "declared engineering fixtures; no field KPI or optimality certificate",
}
protocol["sha256"] = sha(protocol)
p = root / "same-contract-protocol.json"
if p.exists() and json.loads(p.read_text()) != protocol:
    raise RuntimeError("frozen protocol changed")
p.write_text(json.dumps(protocol, indent=2))
results = []
began = time.time()
for domain in protocol["domains"]:
    for seed in protocol["seeds"]:
        case = fixture(seed, 30, domain["heterogeneous"]).model_copy(update={"allow_refill": domain["allow_refill"]})
        r = compare(case)
        results.append({"domain": domain["name"], "seed": seed, **r})
        (root / "same-contract-benchmark.json").write_text(
            json.dumps(
                {
                    "protocol": protocol,
                    "results": results,
                    "complete": len(results) == 20,
                    "runtime": health(),
                    "wall_seconds": time.time() - began,
                },
                indent=2,
            )
        )
        print(
            domain["name"],
            seed,
            r["selected"]["model"],
            [
                (c["model"], c["validation"].get("feasible"), round(c["validation"].get("objective_value", 0), 3))
                for c in r["candidates"]
            ],
            flush=True,
        )
