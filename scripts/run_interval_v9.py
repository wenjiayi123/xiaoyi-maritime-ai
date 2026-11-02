"""Select interval methods on viewed ports, then extract and score new ports."""

import argparse
import csv
import gzip
import hashlib
import json
import statistics as stats
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.harness import interval_v9 as study, predictive_v8 as old  # noqa: E402

DATA = ROOT / "data/public/interval_v9_20261031"
OUT = ROOT / ".codex_artifacts/priority-v9-20261031"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open("x") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)


def load_entry(entry):
    path = ROOT / entry["path"]
    assert sha(path) == entry["sha256"]
    with path.open() as f:
        return old.validated([{"date": r["date"], "calls": float(r["portcalls"])} for r in csv.DictReader(f)])


def models():
    p = ROOT / ".codex_artifacts/capability-review-v8-20261031/experiment-qualified/selection-before-audit.json"
    return json.loads(p.read_text())["model"]["horizons"]


def develop():
    assert not (DATA / "selection-before-test.json").exists()
    manifest = json.loads((ROOT / "data/public/operations_v5_20261030/manifest.json").read_text())
    rows = []
    for e in manifest["entries"]:
        mapping = load_entry(e)
        for h in old.HORIZONS:
            cache = study.point_cache(mapping, h)
            for method in study.METHODS:
                result = study.replay(cache, models()[str(h)], h, method, 2025, keep=False)
                rows.append({"port_id": e["id"], "name": e["name"], **result})
        print("DEVELOPED", e["name"], flush=True)
    summaries = []
    for method in study.METHODS:
        own = [r for r in rows if r["method"] == method]
        failed = 0
        for r in own:
            failed += not (r["summary"]["coverage_gate"] and r["summary"]["width_gate"])
            failed += sum(
                not (q["coverage_gate"] and q["width_gate"])
                for q in r["summary"]["quarters"].values()
                if q["expected"] >= 45
            )
        summaries.append(
            {
                "method": method,
                "failed_year_or_quarter_cells": failed,
                "mean_normalized_wis": stats.mean(r["summary"]["normalized_wis"] for r in own),
                "mean_width": stats.mean(r["summary"]["mean_width90_normalized"] for r in own),
                "retained": sum(r["summary"]["retained"] for r in own),
            }
        )
    selected = min(
        summaries, key=lambda r: (r["failed_year_or_quarter_cells"], r["mean_normalized_wis"], r["mean_width"])
    )["method"]
    source_paths = [
        "app/harness/interval_v9.py",
        "app/harness/predictive_v8.py",
        "scripts/run_interval_v9.py",
        "data/public/interval_v9_20261031/protocol.json",
    ]
    save(
        DATA / "selection-before-test.json",
        {
            "selected": selected,
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "source_sha256": {p: sha(ROOT / p) for p in source_paths},
            "validation_summary": summaries,
            "validation_rows": rows,
            "point_models": models(),
            "test_labels_used": False,
            "production_authority": False,
        },
    )
    print("FROZEN", selected, json.dumps(summaries), flush=True)


def assess():
    sealed = json.loads((DATA / "selection-before-test.json").read_text())
    for p, h in sealed["source_sha256"].items():
        assert sha(ROOT / p) == h, p
    plan = json.loads((DATA / "protocol.json").read_text())
    if not (DATA / "manifest.json").exists():
        prior = json.loads((ROOT / "data/public/operations_v5_20261030/manifest.json").read_text())
        primary = prior["primary_export"]
        assert sha(ROOT / primary["path"]) == primary["sha256"]
        ports = {p["id"]: {**p, "rows": []} for p in plan["new_ports"]}
        with gzip.open(ROOT / primary["path"], "rt", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r["portid"] in ports:
                    ports[r["portid"]]["rows"].append(
                        {"date": r["date"].replace("/", "-"), "portcalls": r["portcalls"]}
                    )
        entries = []
        for identity, p in ports.items():
            rows = sorted(p.pop("rows"), key=lambda r: r["date"])
            path = DATA / (identity + ".csv")
            with path.open("x") as f:
                w = csv.DictWriter(f, fieldnames=["date", "portcalls"])
                w.writeheader()
                w.writerows(rows)
            entries.append({**p, "path": str(path.relative_to(ROOT)), "sha256": sha(path), "rows": len(rows)})
        save(
            DATA / "manifest.json",
            {
                "entries": entries,
                "primary_export": primary,
                "selection_sha256": sha(DATA / "selection-before-test.json"),
                "production_authority": False,
            },
        )
    manifest = json.loads((DATA / "manifest.json").read_text())
    rows = []
    trace = DATA / "traces.jsonl.gz"
    assert not trace.exists()
    with gzip.open(trace, "wt") as handle:
        for entry in manifest["entries"]:
            mapping = load_entry(entry)
            for horizon in old.HORIZONS:
                cache = study.point_cache(mapping, horizon)
                for method in sorted({sealed["selected"], "global_v8", "local_frozen"}):
                    result = study.replay(cache, sealed["point_models"][str(horizon)], horizon, method, 2026)
                    handle.write(
                        json.dumps({"port_id": entry["id"], "name": entry["name"], **result}, allow_nan=False) + "\n"
                    )
                    rows.append(
                        {
                            "port_id": entry["id"],
                            "name": entry["name"],
                            **{k: v for k, v in result.items() if k != "rows"},
                        }
                    )
            print("NEW_PORT_SCORED", entry["name"], flush=True)
    summary = []
    for method in sorted({r["method"] for r in rows}):
        own = [r for r in rows if r["method"] == method]
        summary.append(
            {
                "method": method,
                "cells": len(own),
                "coverage_pass": sum(r["summary"]["coverage_gate"] for r in own),
                "width_pass": sum(r["summary"]["width_gate"] for r in own),
                "joint_pass": sum(
                    r["summary"]["coverage_gate"]
                    and r["summary"]["width_gate"]
                    and r["summary"]["n"] / r["summary"]["expected"] >= 0.95
                    for r in own
                ),
                "expected": sum(r["summary"]["expected"] for r in own),
                "retained": sum(r["summary"]["retained"] for r in own),
                "mean_normalized_wis": stats.mean(r["summary"]["normalized_wis"] for r in own),
                "mean_width": stats.mean(r["summary"]["mean_width90_normalized"] for r in own),
                "worst_coverage": min(r["summary"]["coverage90"] for r in own),
            }
        )
    save(
        DATA / "report.json",
        {
            "schema": "xiaoyi-adaptive-interval.v9",
            "selection": sealed,
            "protocol": plan,
            "summary": summary,
            "cells": rows,
            "trace": {"path": str(trace.relative_to(ROOT)), "sha256": sha(trace)},
            "manifest_sha256": sha(DATA / "manifest.json"),
            "production_authority": False,
        },
    )
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["develop", "assess"])
    args = parser.parse_args()
    {"develop": develop, "assess": assess}[args.phase]()
