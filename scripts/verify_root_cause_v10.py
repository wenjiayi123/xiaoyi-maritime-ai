"""Independent arithmetic, preserved gates, source identity and oracle action replay."""

import csv
import gzip
import hashlib
import json
import statistics as stats
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".codex_artifacts/root-cause-v10-20261031"
FACTORS = (0.65, 0.85, 1.0, 1.15, 1.35)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads((ROOT / path).read_text())


def close(x, y):
    assert abs(x - y) < 1e-8, (x, y)


def main():
    rl = read(".runtime/rl-v10-20261031/report.json")
    annual = read("data/public/annual_v10_20261031/report.json")
    for stem in ["rl", "annual"]:
        folder = ".runtime/rl-v10-20261031" if stem == "rl" else "data/public/annual_v10_20261031"
        sealed = read(folder + "/selection-before-test.json")
        for p, h in sealed["source_sha256"].items():
            assert sha(ROOT / p) == h, p
        report = rl if stem == "rl" else annual
        assert sha(ROOT / folder / "selection-before-test.json") == report["selection_sha256"]
        assert sha(ROOT / report["trace_path"]) == report["trace_sha256"]
        datafolder = "data/public/" + stem + "_v10_20261031"
        prior = read("data/public/" + stem + "_v9_20261031/protocol.json")
        new = read(datafolder + "/protocol.json")
        assert (
            new["limits"] == prior["limits"]
            if stem == "annual"
            else new["guard"] == prior["guard"] and new["acceptance"] == prior["acceptance"]
        )
    source_ports = set()
    for path in (ROOT / "data/public").glob("*/manifest.json"):
        if path.parent.name == "rl_v10_20261031":
            continue
        try:
            source_ports.update(e.get("id", "") for e in json.loads(path.read_text()).get("entries", []))
        except (ValueError, TypeError):
            pass
    manifest = read("data/public/rl_v10_20261031/manifest.json")
    assert not source_ports.intersection(e["id"] for e in manifest["entries"])
    assert manifest["selection_sha256"] == sha(ROOT / ".runtime/rl-v10-20261031/selection-before-test.json")
    oldstations = set()
    for path in (ROOT / "data/public").glob("*/*manifest.json"):
        if path.parent.name == "annual_v10_20261031":
            continue
        try:
            oldstations.update(str(e.get("station_id", "")) for e in json.loads(path.read_text()).get("entries", []))
        except (ValueError, TypeError):
            pass
    test = read("data/public/annual_v10_20261031/test-manifest.json")
    frozen = read("data/public/annual_v10_20261031/selection-before-test.json")
    rule = read("data/public/annual_v10_20261031/rule-before-new-sites.json")
    assert rule["frozen_at"] < frozen["frozen_at"]
    assert not oldstations.intersection(e["station_id"] for e in test["entries"])
    assert all(e["retrieved_at"] > frozen["frozen_at"] for e in test["entries"])
    observations = {}
    for e in test["entries"]:
        assert sha(ROOT / e["path"]) == e["sha256"]
        raw = json.loads(gzip.decompress((ROOT / e["path"]).read_bytes()))
        observations[e["station_id"]] = {
            r["t"]: float(r["v"]) for r in raw.get("data", []) if r.get("f") == "0,0" and r.get("q", "v") == "v"
        }
    annual_rows = 0
    point_predictions = {}
    with gzip.open(ROOT / annual["trace_path"], "rt") as f:
        for c in map(json.loads, f):
            assert len(c["rows"]) == 8760 and len({r["time"] for r in c["rows"]}) == 8760
            points = [r["prediction"] for r in c["rows"]]
            if c["station_id"] in point_predictions:
                assert points == point_predictions[c["station_id"]]
            point_predictions[c["station_id"]] = points
            for r in c["rows"]:
                time = datetime.fromisoformat(r["time"]).strftime("%Y-%m-%d %H:%M")
                assert r["actual"] == observations[c["station_id"]].get(time)
                annual_rows += 1
            for q in [None, "1", "2", "3", "4"]:
                rows = [r for r in c["rows"] if q is None or r["quarter"] == q]
                report = c["annual"] if q is None else c["quarters"][q]
                known = [r for r in rows if r["prediction"] is not None and r["actual"] is not None]
                close(len(known) / len(rows), report["availability"])
                if not known:
                    assert not report["passed"]
                    continue
                mae = stats.mean(abs(r["prediction"] - r["actual"]) for r in known)
                cover = stats.mean(r["lower"] <= r["actual"] <= r["upper"] for r in known)
                width = max(r["upper"] - r["lower"] for r in known)
                wis = stats.mean(
                    (
                        0.5 * abs(r["prediction"] - r["actual"])
                        + 0.05
                        * (
                            r["upper"]
                            - r["lower"]
                            + 20 * (max(0, r["lower"] - r["actual"]) + max(0, r["actual"] - r["upper"]))
                        )
                    )
                    / 1.5
                    for r in known
                )
                close(mae, report["mae_m"])
                close(cover, report["coverage90"])
                close(width, report["max_width90_m"])
                close(wis, report["wis90_m"])
                base = stats.mean(abs(r["baseline"] - r["actual"]) for r in known)
                assert report["passed"] == (
                    mae <= 0.2
                    and cover >= 0.8
                    and width <= 0.75
                    and len(known) / len(rows) >= 0.95
                    and mae <= base + 1e-9
                )
    oracle = {(r["window"], r["scenario"]): r for r in rl["oracle_diagnostics"]}
    baseline = read(".runtime/rl-v10-20261031/selection-before-test.json")["baseline"]
    runs, steps, checked_oracles = 0, 0, 0
    with gzip.open(ROOT / rl["trace_path"], "rt") as f:
        for r in map(json.loads, f):
            runs += 1
            steps += len(r["frames"])
            assert len(r["frames"]) == 90
            close(-sum(x["cost_proxy"] for x in r["frames"]) / 90, r["score"])
            assert sum(x["constraint_violation"] for x in r["frames"]) == r["constraint_violations"]
            for frame in r["frames"]:
                assert date.fromisoformat(frame["public_latest_day"]) <= date.fromisoformat(frame["date"]) - timedelta(
                    days=7
                )
            if r["algorithm"] == baseline:
                bound = oracle[r["window"], r["scenario"]]
                assert bound["status"] == 0 and bound["solved"] and bound["oracle_is_not_deployable"]
                q, cost, previous = 0.0, 0.0, 2
                for i, (a, frame) in enumerate(zip(bound["actions"], r["frames"])):
                    availability = frame["declared_availability"]
                    maximum = 2 if availability < 0.75 else 4
                    assert 0 <= a <= maximum
                    assert a == maximum or q + frame["guard_upper_normalized"] <= FACTORS[a] * availability + 1e-8
                    q = max(
                        0, q + frame["arrival_indicator"] / frame["capacity_scale_proxy"] - FACTORS[a] * availability
                    )
                    cost += (
                        q
                        + 0.5 * FACTORS[a] ** 2
                        + 0.05 * abs(FACTORS[a] - FACTORS[previous])
                        + 5 * max(0, q - 4)
                        + (2 * q if i == 89 else 0)
                    )
                    previous = a
                close(cost, bound["oracle_cost"])
                close(cost, bound["dual_lower_bound"])
                checked_oracles += 1
    for row in rl["aggregate"]:
        assert row["research_admission"] == all(row["checks"].values())
    result = {
        "passed": True,
        "new_port_ids_disjoint": True,
        "new_station_ids_disjoint": True,
        "test_truth_acquired_after_freeze": True,
        "unchanged_gates": True,
        "annual_point_predictions_unchanged_between_methods": True,
        "annual_rows": annual_rows,
        "rl_runs": runs,
        "rl_steps": steps,
        "exact_oracles_replayed": checked_oracles,
        "production_authority": False,
    }
    (OUT / "independent-readback.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
