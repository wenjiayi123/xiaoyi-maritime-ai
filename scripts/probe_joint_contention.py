import json
import threading
import time
import urllib.request
import urllib.error
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.policy_runtime.contracts import fixture, validate_routes, Route

root = Path(".codex_artifacts/joint-harness-phase2-20261029")
case = fixture(44201, 50).model_copy(update={"allow_refill": True})
barrier = threading.Barrier(8)


def probe(i):
    body = json.dumps({"model": "routefinder", "case": case.model_dump(), "max_compute_ms": 1000}).encode()
    barrier.wait()
    start = time.monotonic()
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                "http://127.0.0.1:11839/solve", data=body, headers={"Content-Type": "application/json"}
            ),
            timeout=35,
        ) as response:
            d = json.load(response)
        validation = validate_routes(case, [Route.model_validate(r) for r in d["routes"]])
        return {
            "i": i,
            "status": 200,
            "seconds": time.monotonic() - start,
            "feasible": validation["feasible"],
            "violations": validation["violations"],
        }
    except urllib.error.HTTPError as exc:
        return {"i": i, "status": exc.code, "seconds": time.monotonic() - start, "body": exc.read().decode()[:300]}


with ThreadPoolExecutor(8) as pool:
    results = list(pool.map(probe, range(8)))
(root / "policy-contention.json").write_text(
    json.dumps(
        {
            "requests": 8,
            "results": results,
            "bounded_rejection": all(r["status"] in [200, 409] for r in results),
            "production_authority": False,
        },
        indent=2,
    )
)
print(json.dumps(results))
