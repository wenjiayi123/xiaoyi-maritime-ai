"""Score the predeclared new-port joint scheduling cases, preserving zero gains."""

import hashlib
import argparse
import json
import statistics
from datetime import datetime, timezone

from app.harness.operations_v5 import FOLDER, SCENARIOS, OptimizeArgs, catalog, optimize
from app.config import BASE_DIR


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    target = FOLDER / ("report-final.json" if args.final else "report.json")
    if target.exists():
        raise ValueError("Never overwrite a new-port result")
    protocol_path = FOLDER / ("protocol-final.json" if args.final else "protocol.json")
    plan = json.loads(protocol_path.read_text())
    expected = plan["algorithm_source_sha256_before_test"]
    assert hashlib.sha256((BASE_DIR / "app/harness/operations_v5.py").read_bytes()).hexdigest() == expected
    manifest = catalog()
    cases = []
    for entry in manifest["entries"]:
        for scenario in SCENARIOS:
            row = optimize(OptimizeArgs(port_id=entry["id"], source_day=plan["test"]["source_day"], scenario=scenario))
            cases.append(row)
            print(
                entry["name"],
                scenario,
                row["objective_improvement_vs_best_baseline_pct"],
                row["solver"]["optimality_proven"],
                flush=True,
            )
    gains = [r["objective_improvement_vs_best_baseline_pct"] for r in cases]
    result = {
        "schema": "xiaoyi-new-port-joint-optimization-evaluation.v5",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": expected,
        "protocol_sha256": hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        "protocol_path": str(protocol_path.relative_to(BASE_DIR)),
        "holdout_scope": plan.get("holdout_scope", "New ports, 2026-05-18"),
        "sources": manifest,
        "cases": cases,
        "engineering_passed": all(all(r["checks"].values()) for r in cases),
        "case_count": len(cases),
        "optimality_proven_cases": sum(r["solver"]["optimality_proven"] for r in cases),
        "positive_gain_cases": sum(v > 1e-7 for v in gains),
        "no_gain_cases": sum(abs(v) <= 1e-7 for v in gains),
        "mean_objective_improvement_pct": statistics.mean(gains),
        "median_objective_improvement_pct": statistics.median(gains),
        "worst_objective_improvement_pct": min(gains),
        "maximum_objective_improvement_pct": max(gains),
        "notice": "32 predeclared new-port synthetic-order cases. Compare best of four feasible heuristics, retain no gains and solver timeouts. Same source/assumptions/price foresight. Percentage is proxy objective improvement, not RL/MPC superiority, field savings, confidence in real port dispatch or a third-party benchmark.",
        "production_authority": False,
    }
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in {"sources", "cases"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
