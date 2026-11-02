"""Freeze rollout improvements and strongest matched baseline before eight new ports."""

import argparse
import csv
import gzip
import json
import statistics as stats
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.harness import root_control_v10 as study, rl_v7 as old, constrained_rl_v9 as gates  # noqa: E402

DATA = ROOT / "data/public/rl_v10_20261031"
OUT = ROOT / ".runtime/rl-v10-20261031"


def save(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, allow_nan=False)


def inputs():
    frozen = json.loads((ROOT / ".runtime/rl-v9-20261031/selection-before-test.json").read_text())
    prior = json.loads((old.OUT / "selection-before-test.json").read_text())
    for selection in [frozen]:
        for p, h in selection["source_sha256"].items():
            assert old.c.sha(ROOT / p) == h, p
    assert prior["source_hashes"] == old.sources()
    for model in frozen["models"]:
        assert old.c.sha(ROOT / model["path"]) == model["sha256"]
    return frozen, prior


def policies(frozen, prior, seeds):
    pool = frozen["models"][0]
    table = np.load(ROOT / pool["path"])["thresholds"]
    means = np.asarray(pool["centroids"]) @ old.WEIGHTS
    raw = [old.mpc.MPC(h, 0, tuple(frozen["gains"]), means, f"mean_mpc{h}") for h in [28, 90]]
    raw += [
        old.Actor(table, "constrained", 0, 28),
        study.Rollout(table, pool["centroids"], 28),
        old.c.Policy("max_capacity", gains=tuple(frozen["gains"])),
    ]
    for model in frozen["models"][1:] if seeds else [pool]:
        raw.append(study.Rollout(np.load(ROOT / model["path"])["thresholds"], model["centroids"], 7, model["seed"]))
    return raw


def develop():
    OUT.mkdir(exist_ok=True)
    assert not (OUT / "selection-before-test.json").exists()
    frozen, prior = inputs()
    series, sources = old.load_development()
    old_plan = json.loads((old.DATA / "protocol.json").read_text())
    plan = json.loads((DATA / "protocol.json").read_text())
    windows, excluded = old.c.windows(series, old_plan["train_ports"], [2025], old_plan["validation_months"])
    rows = []
    for raw in policies(frozen, prior, False):
        policy = old.Controller(raw, plan["guard"], tuple(frozen["gains"]))
        rows.extend(
            old.evaluate(policy, w, frozen["forecast"]["selected"], s) for w in windows for s in old.c.SCENARIOS
        )
        print("VALIDATED", policy.name, flush=True)
    floor = {
        (r["window"], r["scenario"]): r["constraint_violations"]
        for r in rows
        if r["algorithm"] == "max_capacity.reserve"
    }
    summary = old.summarize(rows, floor)
    pool = [r for r in summary if r["algorithm"].removesuffix(".reserve") in plan["baseline_pool"]]
    baseline = max(pool, key=lambda r: r["normal_score"])["algorithm"]
    paths = [
        "app/harness/root_control_v10.py",
        "scripts/run_root_rl_v10.py",
        "data/public/rl_v10_20261031/protocol.json",
        ".runtime/rl-v9-20261031/selection-before-test.json",
        ".runtime/rl-v7-20261031/selection-before-test.json",
    ]
    hashes = {p: old.c.sha(ROOT / p) for p in paths}
    hashes.update(frozen["source_sha256"])
    save(
        OUT / "selection-before-test.json",
        {
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "baseline": baseline,
            "validation_summary": summary,
            "validation_rows": rows,
            "source_sha256": hashes,
            "forecast": frozen["forecast"],
            "gains": frozen["gains"],
            "models": frozen["models"],
            "test_labels_used": False,
            "production_authority": False,
        },
    )
    print("FROZEN", baseline, summary, flush=True)


def extract():
    plan = json.loads((DATA / "protocol.json").read_text())
    if not (DATA / "manifest.json").exists():
        primary = json.loads((ROOT / "data/public/operations_v5_20261030/manifest.json").read_text())["primary_export"]
        assert old.c.sha(ROOT / primary["path"]) == primary["sha256"]
        ports = {p["id"]: {**p, "rows": []} for p in plan["new_ports"]}
        with gzip.open(ROOT / primary["path"], "rt", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r["portid"] in ports:
                    ports[r["portid"]]["rows"].append(
                        {"date": r["date"].replace("/", "-"), "portcalls": r["portcalls"]}
                    )
        entries = []
        for sid, p in ports.items():
            rows = sorted(p.pop("rows"), key=lambda r: r["date"])
            path = DATA / f"{sid}.csv"
            with path.open("x") as f:
                writer = csv.DictWriter(f, fieldnames=["date", "portcalls"])
                writer.writeheader()
                writer.writerows(rows)
            entries.append({**p, "path": str(path.relative_to(ROOT)), "sha256": old.c.sha(path), "rows": len(rows)})
        save(
            DATA / "manifest.json",
            {
                "entries": entries,
                "primary_export": primary,
                "selection_sha256": old.c.sha(OUT / "selection-before-test.json"),
            },
        )
    manifest = json.loads((DATA / "manifest.json").read_text())
    assert manifest["selection_sha256"] == old.c.sha(OUT / "selection-before-test.json")
    series = {}
    for e in manifest["entries"]:
        assert old.c.sha(ROOT / e["path"]) == e["sha256"]
        with (ROOT / e["path"]).open() as f:
            series[e["id"]] = [(date.fromisoformat(r["date"]), float(r["portcalls"])) for r in csv.DictReader(f)]
    return series


def assess():
    assert not (OUT / "report.json").exists()
    selected = json.loads((OUT / "selection-before-test.json").read_text())
    for p, h in selected["source_sha256"].items():
        assert old.c.sha(ROOT / p) == h, p
    frozen, prior = inputs()
    series = extract()
    plan = json.loads((DATA / "protocol.json").read_text())
    windows, excluded = old.c.windows(series, list(series), plan["test_years"], plan["test_months"])
    rows = []
    trace = OUT / "trajectories.jsonl.gz"
    oracle = []
    with gzip.open(trace, "xt") as f:
        for raw in policies(frozen, prior, True):
            policy = old.Controller(raw, plan["guard"], tuple(frozen["gains"]))
            for w in windows:
                for scenario in old.c.SCENARIOS:
                    r = old.evaluate(policy, w, frozen["forecast"]["selected"], scenario, True)
                    if policy.name == selected["baseline"]:
                        for i, frame in enumerate(r["frames"]):
                            lag = 14 if scenario == "publication_delay" else 7
                            history = w["records"][: 42 + i - lag + 1]
                            frame["guard_upper_normalized"] = (
                                frame["public_forecast_proxy"] + old.c.uncertainty_scale(history)
                            ) / frame["capacity_scale_proxy"]
                        oracle.append({"window": w["id"], "scenario": scenario, **study.hindsight_bound(r["frames"])})
                    f.write(json.dumps(r, allow_nan=False) + "\n")
                    rows.append({k: v for k, v in r.items() if k != "frames"})
            print("TESTED", policy.name, policy.seed, flush=True)

    def average(name):
        groups = {}
        for r in rows:
            if r["algorithm"] == name:
                groups.setdefault((r["window"], r["scenario"]), []).append(r["score"])
        return {k: stats.mean(v) for k, v in groups.items()}

    base = average(selected["baseline"])
    maximum = {
        (r["window"], r["scenario"]): r["constraint_violations"]
        for r in rows
        if r["algorithm"] == "max_capacity.reserve"
    }
    aggregate = []
    for name in sorted({r["algorithm"] for r in rows}):
        own_mean = average(name)
        own = [r for r in rows if r["algorithm"] == name]
        paired = {
            p: [
                (own_mean[w["id"], "normal"] - base[w["id"], "normal"]) / abs(base[w["id"], "normal"])
                for w in windows
                if w["port_id"] == p
            ]
            for p in series
        }
        interval = old.c.clustered_interval(paired)
        positive = [max(0, stats.mean(v)) for v in paired.values()]
        share = max(positive) / sum(positive) if sum(positive) > 1e-12 else None
        stress = {
            s: stats.mean((own_mean[w["id"], s] - base[w["id"], s]) / abs(base[w["id"], s]) for w in windows)
            for s in old.c.SCENARIOS[1:]
        }
        feasible = sum(r["constraint_violations"] for r in own if maximum[r["window"], r["scenario"]] == 0)
        excess = sum(max(0, r["constraint_violations"] - maximum[r["window"], r["scenario"]]) for r in own)
        checks = {
            "positive_port_cluster_ci": interval["port_cluster_ci95"][0] > 0,
            "no_mean_port_regression": interval["worst_port_mean_delta"] >= -1e-9,
            "stress_noninferiority": all(v >= -1e-9 for v in stress.values()),
            "no_feasible_window_violation": feasible == 0,
            "no_excess_over_max_capacity": excess == 0,
            "gain_not_concentrated": share is not None and share <= 0.5,
        }
        aggregate.append(
            {
                "algorithm": name,
                "matched_baseline": selected["baseline"],
                "relative_cost_interval": interval,
                "stress": stress,
                "checks": checks,
                "research_admission": gates.admission(checks),
                "feasible_violations": feasible,
                "excess_over_max_capacity": excess,
                "all_constraint_violations": sum(r["constraint_violations"] for r in own),
            }
        )
    save(
        OUT / "report.json",
        {
            "schema": "xiaoyi-root-rl.v10",
            "aggregate": aggregate,
            "runs": rows,
            "oracle_diagnostics": oracle,
            "excluded": excluded,
            "trace_path": str(trace.relative_to(ROOT)),
            "trace_sha256": old.c.sha(trace),
            "selection_sha256": old.c.sha(OUT / "selection-before-test.json"),
            "manifest_sha256": old.c.sha(DATA / "manifest.json"),
            "production_authority": False,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["develop", "assess"])
    {"develop": develop, "assess": assess}[parser.parse_args().phase]()
