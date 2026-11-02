"""View old failures for development, freeze rule, fit new sites, then fetch 2025."""

import argparse
import gzip
import json
import statistics as stats
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import utide

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.harness import seasonal_twin_v10 as study, annual_v9 as old  # noqa: E402
from app.harness.physical_v3 import decode, reconstruct  # noqa: E402

DATA = ROOT / "data/public/annual_v10_20261031"
OUT = ROOT / ".codex_artifacts/root-cause-v10-20261031"


def save(path, value):
    with path.open("x") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)


def source_hashes():
    files = [
        "app/harness/seasonal_twin_v10.py",
        "app/harness/annual_v9.py",
        "app/harness/twin_v7.py",
        "app/harness/long_twin_v6.py",
        "app/harness/physical_v2.py",
        "app/harness/physical_v3.py",
        "scripts/run_seasonal_twin_v10.py",
        "scripts/acquire_annual_v10.py",
        "data/public/annual_v10_20261031/protocol.json",
        "data/public/annual_v10_20261031/capacity-ablation-amendment.json",
    ]
    return {p: old.files.sha(ROOT / p) for p in files}


def develop_station(sid):
    plan = json.loads((DATA / "protocol.json").read_text())
    sealed = json.loads((old.DATA / "selection-before-test.json").read_text())
    station = next(r for r in sealed["stations"] if r["station_id"] == sid)
    if station["status"] != "ready":
        return {"station_id": sid, "status": "blocked", "reason": station["reason"]}
    _, groups = old.load("history", sid)
    g = groups[sid]
    _, tests = old.load("test", sid)
    observed = tests[sid]["observed"]
    version = station["versions"]["v9"]
    choice = version["choice"]
    errors = study.calibration(g, choice, plan)
    times = old.old.previous.hours(2025)
    pred = old.predict(times, decode(version["model"]), choice)
    baseline = old.predict(times, decode(version["baseline_model"]), version["baseline_choice"])
    results = []
    for method in study.METHODS:
        bands = study.bands_for_year(errors, method, 2025)
        records = study.rows(times, pred, baseline, observed, bands)
        results.append({"method": method, **study.score(records, plan)})
    # Independent complexity ablation: more physical constituents, not a larger LLM.
    training = sorted(t for t in g["observed"] if 2025 - choice["window_years"] <= t.year < 2025)
    coef = utide.solve(
        np.asarray([t.replace(tzinfo=None) for t in training], dtype="datetime64[ns]"),
        np.asarray([g["observed"][t] for t in training]),
        lat=g["lat"],
        constit=json.loads((DATA / "capacity-ablation-amendment.json").read_text())["expanded_utide_constituents"],
        method="ols",
        conf_int="none",
        trend=False,
        nodal=True,
        verbose=False,
    )
    harmonic37 = reconstruct(times, coef)
    errors37 = [abs(v - observed[t]) for t, v in zip(times, harmonic37) if t in observed]
    constant20 = reconstruct(times, decode(version["model"])["coef"])
    errors20 = [abs(v - observed[t]) for t, v in zip(times, constant20) if t in observed]
    print("DEVELOPED", sid, flush=True)
    return {
        "station_id": sid,
        "status": "ready",
        "results": results,
        "physical_capacity_ablation": {
            "expanded37_mae_m": stats.mean(errors37),
            "old_basis_mae_m": stats.mean(errors20),
            "point_model_was_not_changed_by_this_ablation": True,
        },
    }


def develop():
    assert not (DATA / "rule-before-new-sites.json").exists()
    stations = json.loads((old.DATA / "protocol.json").read_text())["stations"]
    with ProcessPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(develop_station, stations))
    summary = []
    for method in study.METHODS:
        cells = [r for site in rows if site["status"] == "ready" for r in site["results"] if r["method"] == method]
        blocked = sum(site["status"] != "ready" for site in rows)
        failed = (
            5 * blocked
            + sum(not c["annual"]["passed"] for c in cells)
            + sum(not q["passed"] for c in cells for q in c["quarters"].values())
        )
        summary.append(
            {
                "method": method,
                "failed_cells": failed,
                "mean_wis": stats.mean(c["annual"]["wis90_m"] for c in cells),
                "max_width": max(c["annual"]["max_width90_m"] for c in cells),
                "annual_passed": sum(c["annual"]["passed"] for c in cells),
                "quarters_passed": sum(q["passed"] for c in cells for q in c["quarters"].values()),
            }
        )
    selected = min(summary, key=lambda r: (r["failed_cells"], r["mean_wis"], r["max_width"]))["method"]
    save(
        DATA / "rule-before-new-sites.json",
        {
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "selected": selected,
            "summary": summary,
            "development": rows,
            "source_sha256": source_hashes(),
            "new_site_labels_used": False,
            "production_authority": False,
        },
    )
    print("FROZEN_INTERVAL_RULE", selected, summary, flush=True)


def new_station(sid):
    old.DATA = DATA  # Worker-local binding, restored by process exit; no application mutation.
    plan = json.loads((DATA / "protocol.json").read_text())
    rule = json.loads((DATA / "rule-before-new-sites.json").read_text())
    station = old.choose(sid)
    if station["status"] == "ready":
        _, groups = old.load("history", sid)
        errors = study.calibration(groups[sid], station["versions"]["v9"]["choice"], plan)
        station["v10_bands"] = study.bands_for_year(errors, rule["selected"], 2025)
        station["selected_interval_rule"] = rule["selected"]
    return station


def freeze():
    assert not (DATA / "selection-before-test.json").exists()
    rule = json.loads((DATA / "rule-before-new-sites.json").read_text())
    assert rule["source_sha256"] == source_hashes()
    plan = json.loads((DATA / "protocol.json").read_text())
    with ProcessPoolExecutor(max_workers=2) as pool:
        stations = list(pool.map(new_station, plan["stations"]))
    sources = source_hashes()
    for p in [
        "data/public/annual_v10_20261031/rule-before-new-sites.json",
        "data/public/annual_v10_20261031/history-manifest.json",
    ]:
        sources[p] = old.files.sha(ROOT / p)
    save(
        DATA / "selection-before-test.json",
        {
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "stations": stations,
            "selected": rule["selected"],
            "source_sha256": sources,
            "test_labels_used": False,
            "production_authority": False,
        },
    )


def assess():
    assert not (DATA / "report.json").exists()
    frozen = json.loads((DATA / "selection-before-test.json").read_text())
    for p, h in frozen["source_sha256"].items():
        assert old.files.sha(ROOT / p) == h, p
    old.DATA = DATA
    plan = json.loads((DATA / "protocol.json").read_text())
    manifest, groups = old.load("test")
    assert all(e["retrieved_at"] > frozen["frozen_at"] for e in manifest["entries"])
    times = old.old.previous.hours(2025)
    cells = []
    trace = DATA / "trajectories.jsonl.gz"
    with gzip.open(trace, "xt") as f:
        for station in frozen["stations"]:
            sid = station["station_id"]
            observed = groups.get(sid, {}).get("observed", {})
            for method in ["v9_global", "v10_selected"]:
                if station["status"] == "ready":
                    v = station["versions"]["v9"]
                    pred = old.predict(times, decode(v["model"]), v["choice"])
                    base = old.predict(times, decode(v["baseline_model"]), v["baseline_choice"])
                    bands = (
                        station["v10_bands"]
                        if method == "v10_selected"
                        else {
                            t.date().isoformat(): [
                                -v["quarter_radii_m"][str((t.month - 1) // 3 + 1)],
                                v["quarter_radii_m"][str((t.month - 1) // 3 + 1)],
                            ]
                            for t in times
                        }
                    )
                    records = study.rows(times, pred, base, observed, bands)
                else:
                    records = [
                        {
                            "time": t.isoformat(),
                            "quarter": str((t.month - 1) // 3 + 1),
                            "actual": observed.get(t),
                            "prediction": None,
                            "baseline": None,
                            "lower": None,
                            "upper": None,
                        }
                        for t in times
                    ]
                cell = {
                    "station_id": sid,
                    "site": station["site"],
                    "method": method,
                    "model_status": station["status"],
                    **study.score(records, plan),
                }
                cells.append(cell)
                f.write(json.dumps({**cell, "rows": records}, allow_nan=False) + "\n")
            print("TESTED", sid, flush=True)
    summary = {}
    for method in ["v9_global", "v10_selected"]:
        own = [c for c in cells if c["method"] == method]
        summary[method] = {
            "annual_passed": sum(c["annual"]["passed"] for c in own),
            "annual_total": len(own),
            "quarters_passed": sum(q["passed"] for c in own for q in c["quarters"].values()),
            "quarters_total": 4 * len(own),
            "annual_and_all_quarters": sum(
                c["annual"]["passed"] and all(q["passed"] for q in c["quarters"].values()) for c in own
            ),
            "mean_wis": stats.mean(c["annual"]["wis90_m"] for c in own if c["annual"]["n"]),
        }
    save(
        DATA / "report.json",
        {
            "schema": "xiaoyi-seasonal-annual.v10",
            "summary": summary,
            "cells": cells,
            "selected": frozen["selected"],
            "selection_sha256": old.files.sha(DATA / "selection-before-test.json"),
            "manifest_sha256": old.files.sha(DATA / "test-manifest.json"),
            "trace_path": str(trace.relative_to(ROOT)),
            "trace_sha256": old.files.sha(trace),
            "production_authority": False,
            "protocol": plan,
        },
    )
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["develop", "freeze", "assess"])
    {"develop": develop, "freeze": freeze, "assess": assess}[parser.parse_args().phase]()
