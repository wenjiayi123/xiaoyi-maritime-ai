"""Read saved weights and independently reconstruct neural argmax decisions."""

import gzip
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.harness import crossport_control as c, portwatch_data as d  # noqa: E402


def main():
    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / ".codex_artifacts/crossport-20261030/confirmed-http/report.json").read_text())
    _, series = d.load_all()
    networks = {}
    for meta in report["models"]:
        model = json.loads((root / meta["path"]).read_text())
        networks[(model["algorithm"], model["seed"])] = model
    checks = []
    seen = set()
    with gzip.open(root / report["trace_file"], "rt") as handle:
        for line in handle:
            run = json.loads(line)
            key = (run["algorithm"], run["seed"])
            identity = (*key, run["scenario"])
            if key not in networks or run["scenario"] not in {"normal", "publication_delay"} or identity in seen:
                continue
            seen.add(identity)
            model = networks[key]
            w, b, v, bias = [np.asarray(a) for a in model["network"]]
            records = d.contiguous(series[run["port_id"]], date.fromisoformat(run["start"]), 90)
            env = c.ServiceEpisode(
                records, report["twin_calibration"]["calibration"]["selected"], scenario=run["scenario"]
            )
            mismatches = 0
            fallback = 0
            for frame in run["frames"]:
                features, mask, pid = env.features()
                if model["residual"] and (env.context()[1] != 7 or max(abs(z) for z in features[:10]) > 4):
                    action = pid
                    fallback += 1
                else:
                    q = np.maximum(0, np.asarray(features) @ w + b) @ v + bias
                    mapped = [max(0, min(4, pid + a - 2)) if model["residual"] else a for a in range(5)]
                    valid = [i for i, a in enumerate(mapped) if mask[a]]
                    action = mapped[max(valid, key=lambda i: q[i])]
                mismatches += action != frame["action"]
                env.step(action)
            checks.append(
                {
                    "algorithm": key[0],
                    "seed": key[1],
                    "scenario": run["scenario"],
                    "actions": 90,
                    "mismatches": mismatches,
                    "fallback_actions": fallback,
                }
            )
    result = {
        "passed": len(checks) == 20 and all(r["mismatches"] == 0 for r in checks),
        "checks": checks,
        "scope": "Independent NumPy forward/argmax from ten persisted trained networks, normal and delayed-publication replay; no retraining.",
        "production_authority": False,
    }
    (root / ".codex_artifacts/crossport-20261030/weight-readback.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
