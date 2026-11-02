"""Extract a previously unused cohort from the pinned primary IMF export."""

import csv
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/public/operations_v5_20261030"
PORTS = {
    "port31": "ESP",
    "port387": "ITA",
    "port254": "LKA",
    "port777": "IND",
    "port434": "VNM",
    "port694": "PHL",
    "port118": "ESP",
    "port862": "JPN",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT / "manifest.json").exists():
        raise ValueError("Never overwrite an acquired source cohort")
    used = set()
    for name in [
        "portwatch_crossport_20261030",
        "portwatch_v2_20261030",
        "portwatch_v3_20261030",
        "portwatch_v4_20261030",
    ]:
        used.update(e["id"] for e in json.loads((ROOT / "data/public" / name / "manifest.json").read_text())["entries"])
    assert not used.intersection(PORTS), "Previously viewed port cannot be a new-port claim"
    old = json.loads((ROOT / "data/public/portwatch_v4_20261030/manifest.json").read_text())
    primary = old["primary_export"]
    raw = ROOT / primary["path"]
    assert sha(raw) == primary["sha256"]
    protocol = {
        "schema": "xiaoyi-joint-operations-protocol.v5",
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "new_ports": PORTS,
        "development": {"ports": ["port23", "port960", "port776", "port514"], "source_day": "2025-10-13"},
        "test": {"source_day": "2026-05-18", "scenarios": ["normal", "arrival_peak", "crane_outage", "grid_derating"]},
        "algorithm_source_sha256_before_test": sha(ROOT / "app/harness/operations_v5.py"),
        "metrics": [
            "objective_points",
            "waiting_hours",
            "late_hours",
            "completed_calls",
            "energy_kwh",
            "peak_kw",
            "mip_gap",
        ],
        "gate": "Independent schedule feasibility; no worse than the best of four declared heuristics. Zero improvement is retained; no minimum gain is promised.",
        "notice": "New public port identities for this task; same previously pinned official full export. Activity indicators are real, individual orders/resources/prices are explicitly synthetic assumptions. Not real port dispatch or physical calibration.",
    }
    write(OUT / "protocol.json", protocol)
    selected = {pid: [] for pid in PORTS}
    with gzip.open(raw, "rt", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["portid"] in selected:
                row["date"] = row["date"].replace("/", "-")[:10]
                selected[row["portid"]].append(row)
    entries = []
    for pid, iso in PORTS.items():
        rows = sorted(selected[pid], key=lambda r: r["date"])
        assert rows and all(r["ISO3"] == iso for r in rows) and len({r["date"] for r in rows}) == len(rows)
        f = OUT / (pid + ".csv")
        with f.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        entries.append(
            {
                "id": pid,
                "name": rows[0]["portname"],
                "country": rows[0]["country"],
                "iso3": iso,
                "path": str(f.relative_to(ROOT)),
                "sha256": sha(f),
                "rows": len(rows),
                "start": rows[0]["date"],
                "end": rows[-1]["date"],
            }
        )
    write(
        OUT / "manifest.json",
        {
            "schema": "xiaoyi-new-public-operations-cohort.v5",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "protocol_sha256": sha(OUT / "protocol.json"),
            "primary_export": primary,
            "entries": entries,
            "landing_url": "https://portwatch.imf.org/datasets/83b1bbc7b3354c5fb1f40673bb8f852e_0/about",
            "notice": protocol["notice"],
            "production_authority": False,
        },
    )
    print(json.dumps(entries, ensure_ascii=False))


if __name__ == "__main__":
    main()
