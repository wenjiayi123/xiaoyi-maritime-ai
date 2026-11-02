"""Train with safety, compare against equally constrained strong MPC, retain failures."""

import argparse
import csv
import gzip
import json
import statistics as stats
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.harness import constrained_rl_v9 as study, rl_v7 as old  # noqa: E402

DATA = ROOT / "data/public/rl_v9_20261031"
OUT = ROOT / ".runtime/rl-v9-20261031"


def save(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, allow_nan=False)


def train(model):
    path = OUT / f"actor-{model['seed']}.npz"
    assert not path.exists()
    table, info = study.bellman(np.asarray(model["centroids"]))
    np.savez_compressed(path, thresholds=table)
    print("TRAINED", model["seed"], flush=True)
    return {
        "seed": model["seed"],
        "path": str(path.relative_to(ROOT)),
        "sha256": old.c.sha(path),
        "centroids": model["centroids"],
        **info,
    }


def baselines(sealed, pooled):
    chosen = next(r for r in sealed["candidates"] if r["name"] == sealed["chosen_config"])
    means = np.asarray(chosen["centroids"]) @ old.WEIGHTS
    gains = tuple(sealed["gains"])
    path = ROOT / chosen["path"]
    assert old.c.sha(path) == chosen["sha256"]
    table = np.load(path)["thresholds"]
    return [old.mpc.MPC(h, 0, gains, means, f"mean_mpc{h}") for h in [28, 90]] + [
        old.Actor(table, "model", 0, 28),
        old.Actor(pooled, "constrained", 0, 28),
        old.c.Policy("max_capacity", gains=gains),
    ]


def develop():
    OUT.mkdir(exist_ok=True)
    assert not (OUT / "selection-before-test.json").exists()
    prior = json.loads((old.OUT / "selection-before-test.json").read_text())
    assert prior["source_hashes"] == old.sources()
    plan = json.loads((DATA / "protocol.json").read_text())
    selected = next(c for c in prior["candidates"] if c["name"] == prior["chosen_config"])
    jobs = [{"seed": 0, "centroids": selected["centroids"]}, *prior["models"]]
    with ProcessPoolExecutor(max_workers=2) as pool:
        models = list(pool.map(train, jobs))
    pooled = np.load(ROOT / models[0]["path"])["thresholds"]
    series, sources = old.load_development()
    previous_plan = json.loads((old.DATA / "protocol.json").read_text())
    windows, excluded = old.c.windows(series, previous_plan["train_ports"], [2025], previous_plan["validation_months"])
    policies = [old.Actor(pooled, "constrained"), *baselines(prior, pooled)]
    rows = []
    for raw in policies:
        policy = old.Controller(raw, plan["guard"], tuple(prior["gains"]))
        rows.extend(old.evaluate(policy, w, prior["forecast"]["selected"], s) for w in windows for s in old.c.SCENARIOS)
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
        "app/harness/constrained_rl_v9.py",
        "app/harness/rl_v7.py",
        "app/harness/rl_v6.py",
        "app/harness/mpc_exact_v7.py",
        "scripts/run_constrained_rl_v9.py",
        "data/public/rl_v9_20261031/protocol.json",
        ".runtime/rl-v7-20261031/selection-before-test.json",
    ]
    save(
        OUT / "selection-before-test.json",
        {
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "models": models,
            "baseline": baseline,
            "validation_summary": summary,
            "validation_rows": rows,
            "gains": prior["gains"],
            "forecast": prior["forecast"],
            "source_sha256": {p: old.c.sha(ROOT / p) for p in paths},
            "development_sources": sources,
            "excluded": excluded,
            "test_labels_used": False,
            "production_authority": False,
        },
    )
    print("FROZEN", baseline, flush=True)


def extract(sealed):
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
        for sid, port in ports.items():
            rows = sorted(port.pop("rows"), key=lambda r: r["date"])
            path = DATA / f"{sid}.csv"
            with path.open("x") as f:
                writer = csv.DictWriter(f, fieldnames=["date", "portcalls"])
                writer.writeheader()
                writer.writerows(rows)
            entries.append({**port, "path": str(path.relative_to(ROOT)), "sha256": old.c.sha(path), "rows": len(rows)})
        save(
            DATA / "manifest.json",
            {
                "entries": entries,
                "primary_export": primary,
                "selection_sha256": old.c.sha(OUT / "selection-before-test.json"),
                "production_authority": False,
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
    sealed = json.loads((OUT / "selection-before-test.json").read_text())
    for p, h in sealed["source_sha256"].items():
        assert old.c.sha(ROOT / p) == h, p
    plan = json.loads((DATA / "protocol.json").read_text())
    series = extract(sealed)
    windows, excluded = old.c.windows(series, list(series), plan["test_years"], plan["test_months"])
    prior = json.loads((old.OUT / "selection-before-test.json").read_text())
    tables = []
    for model in sealed["models"]:
        assert old.c.sha(ROOT / model["path"]) == model["sha256"]
        tables.append(np.load(ROOT / model["path"])["thresholds"])
    raws = [old.Actor(table, "constrained", model["seed"]) for table, model in zip(tables[1:], sealed["models"][1:])]
    # Preserve former policy and matched 28-step comparator for every bootstrap fit.
    for model, table in zip(prior["models"], tables[1:]):
        assert old.c.sha(ROOT / model["path"]) == model["sha256"]
        raws += [
            old.Actor(np.load(ROOT / model["path"])["thresholds"], "former", model["seed"]),
            old.Actor(table, "constrained_seed", model["seed"], 28),
        ]
    raws += baselines(prior, tables[0])
    rows, diagnosis = [], []
    trace = OUT / "trajectories.jsonl.gz"
    with gzip.open(trace, "xt") as handle:
        for raw in raws:
            policy = old.Controller(raw, plan["guard"], tuple(sealed["gains"]))
            for window in windows:
                for scenario in old.c.SCENARIOS:
                    result = old.evaluate(policy, window, sealed["forecast"]["selected"], scenario, True)
                    frames = result["frames"]
                    diagnosis.append(
                        {
                            "algorithm": policy.name,
                            "seed": policy.seed,
                            "window": window["id"],
                            "scenario": scenario,
                            "steps": len(frames),
                            "zero_or_one_feasible": sum(f["feasible_filter_action_count"] <= 1 for f in frames),
                            "overrides": sum(f["safety_override"] for f in frames),
                        }
                    )
                    handle.write(json.dumps(result, allow_nan=False) + "\n")
                    rows.append({k: v for k, v in result.items() if k != "frames"})
            print("TESTED", policy.name, policy.seed, flush=True)

    def average(name):
        grouped = {}
        for r in rows:
            if r["algorithm"] == name:
                grouped.setdefault((r["window"], r["scenario"]), []).append(r["score"])
        return {k: stats.mean(v) for k, v in grouped.items()}

    maximum = {
        (r["window"], r["scenario"]): r["constraint_violations"]
        for r in rows
        if r["algorithm"] == "max_capacity.reserve"
    }
    base = average(sealed["baseline"])
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
        d = [r for r in diagnosis if r["algorithm"] == name]
        aggregate.append(
            {
                "algorithm": name,
                "matched_baseline": sealed["baseline"],
                "relative_cost_interval": interval,
                "stress": stress,
                "checks": checks,
                "research_admission": study.admission(checks),
                "feasible_violations": feasible,
                "excess_over_max_capacity": excess,
                "all_constraint_violations": sum(r["constraint_violations"] for r in own),
                "positive_gain_max_port_share": share,
                "override_fraction": sum(r["overrides"] for r in d) / sum(r["steps"] for r in d),
                "zero_or_one_feasible_fraction": sum(r["zero_or_one_feasible"] for r in d) / sum(r["steps"] for r in d),
            }
        )
    save(
        OUT / "report.json",
        {
            "schema": "xiaoyi-constrained-rl-result.v9",
            "aggregate": aggregate,
            "runs": rows,
            "diagnosis": diagnosis,
            "windows": [{k: v for k, v in w.items() if k != "records"} for w in windows],
            "excluded": excluded,
            "selection_sha256": old.c.sha(OUT / "selection-before-test.json"),
            "manifest_sha256": old.c.sha(DATA / "manifest.json"),
            "trace_path": str(trace.relative_to(ROOT)),
            "trace_sha256": old.c.sha(trace),
            "production_authority": False,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["develop", "assess"])
    {"develop": develop, "assess": assess}[parser.parse_args().phase]()
