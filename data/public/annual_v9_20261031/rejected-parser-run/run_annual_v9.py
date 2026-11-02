"""Freeze all annual models before downloading or evaluating 2025 truth."""

import argparse
import gzip
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.harness import annual_v9 as study  # noqa: E402
from app.harness.physical_v3 import decode  # noqa: E402

DATA = study.DATA


def save(path, value):
    with path.open("x") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def develop():
    assert not (DATA / "selection-before-test.json").exists()
    plan = json.loads((DATA / "protocol.json").read_text())
    with ProcessPoolExecutor(max_workers=2) as pool:
        stations = list(pool.map(study.choose, plan["stations"]))
    paths = [
        "app/harness/annual_v9.py",
        "app/harness/twin_v7.py",
        "app/harness/long_twin_v6.py",
        "app/harness/physical_v2.py",
        "app/harness/physical_v3.py",
        "scripts/run_annual_v9.py",
        "scripts/acquire_annual_v9.py",
        "data/public/annual_v9_20261031/protocol.json",
        "data/public/annual_v9_20261031/history-manifest.json",
    ]
    save(
        DATA / "selection-before-test.json",
        {
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "stations": stations,
            "source_sha256": {p: study.files.sha(ROOT / p) for p in paths},
            "test_labels_used": False,
            "production_authority": False,
        },
    )


def assess():
    sealed = json.loads((DATA / "selection-before-test.json").read_text())
    for path, expected in sealed["source_sha256"].items():
        assert study.files.sha(ROOT / path) == expected, path
    assert not (DATA / "report.json").exists()
    plan = json.loads((DATA / "protocol.json").read_text())
    manifest, groups = study.load("test")
    times = study.old.previous.hours(plan["test_year"])
    trace = DATA / "trajectories.jsonl.gz"
    cells = []
    with gzip.open(trace, "xt") as handle:
        for station in sealed["stations"]:
            sid = station["station_id"]
            observed = groups.get(sid, {}).get("observed", {})
            for label in ["v9", "legacy_v7_rule"]:
                version = station.get("versions", {}).get(label)
                if version:
                    model, baseline = decode(version["model"]), decode(version["baseline_model"])
                    pred = study.predict(times, model, version["choice"], label == "v9")
                    base = study.predict(times, baseline, version["baseline_choice"], label == "v9")
                rows = []
                for i, at in enumerate(times):
                    q = str((at.month - 1) // 3 + 1)
                    value = float(pred[i]) if version else None
                    radius = version["quarter_radii_m"][q] if version else None
                    rows.append(
                        {
                            "time": at.isoformat(),
                            "quarter": q,
                            "actual": observed.get(at),
                            "prediction": value,
                            "baseline": float(base[i]) if version else None,
                            "lower": value - radius if version else None,
                            "upper": value + radius if version else None,
                        }
                    )
                cell = {
                    "station_id": sid,
                    "site": station["site"],
                    "method": label,
                    "annual": study.summarize(rows, plan["limits"]),
                    "quarters": {
                        str(q): study.summarize([r for r in rows if r["quarter"] == str(q)], plan["limits"])
                        for q in range(1, 5)
                    },
                }
                cells.append(cell)
                handle.write(json.dumps({**cell, "rows": rows}, allow_nan=False) + "\n")
            print("ANNUAL_TESTED", sid, flush=True)
    summary = {}
    for label in ["v9", "legacy_v7_rule"]:
        own = [r for r in cells if r["method"] == label]
        summary[label] = {
            "annual_passed": sum(r["annual"]["passed"] for r in own),
            "annual_total": len(own),
            "quarters_passed": sum(q["passed"] for r in own for q in r["quarters"].values()),
            "quarters_total": 4 * len(own),
        }
    save(
        DATA / "report.json",
        {
            "schema": "xiaoyi-annual-stability.v9",
            "summary": summary,
            "cells": cells,
            "selection_sha256": study.files.sha(DATA / "selection-before-test.json"),
            "manifest_sha256": study.files.sha(DATA / "test-manifest.json"),
            "trace_path": str(trace.relative_to(ROOT)),
            "trace_sha256": study.files.sha(trace),
            "production_authority": False,
            "protocol": plan,
            "source_errors": {sid: g["errors"] for sid, g in groups.items()},
        },
    )
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["develop", "assess"])
    {"develop": develop, "assess": assess}[parser.parse_args().phase]()
