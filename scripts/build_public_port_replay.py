"""Causal as-of join of the existing AIS observations and frozen NOAA station records."""

from __future__ import annotations

import bisect
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data/public/port_evidence_20261030"


def main():
    manifest_path = FOLDER / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entries = {e["id"]: e for e in manifest["entries"]}
    base = ROOT / "data/public/noaa_la_lb_ais_2024_12_25_1min.csv"
    provenance = json.loads(base.with_suffix(".provenance.json").read_text())
    base_sha = hashlib.sha256(base.read_bytes()).hexdigest()
    if base_sha != provenance["derived_csv_sha256"]:
        raise ValueError("AIS provenance mismatch")
    columns = {"wind_speed_mps": "noaa_la_wind", "pressure_hpa": "noaa_la_air_pressure"}
    indexes = {}
    for field, name in columns.items():
        path = ROOT / entries[name]["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entries[name]["sha256"]:
            raise ValueError("station evidence changed")
        with path.open() as handle:
            rows = [r for r in csv.DictReader(handle) if all(flag == "0" for flag in r["flags"].split(","))]
        indexes[field] = ([datetime.fromisoformat(r["timestamp"]) for r in rows], rows)
    with base.open() as handle:
        rows = list(csv.DictReader(handle))
    counts = {field: 0 for field in columns}
    for row in rows:
        at = datetime.fromisoformat(row["timestamp"])
        for field, (times, observations) in indexes.items():
            i = bisect.bisect_right(times, at) - 1
            valid = i >= 0 and 0 <= (at - times[i]).total_seconds() <= 360
            row[field] = observations[i]["value"] if valid else ""
            counts[field] += valid
    name = "noaa_la_lb_ais_weather_2024_12_25"
    path = FOLDER / (name + ".csv")
    if path.exists():
        raise FileExistsError("do not overwrite an existing frozen replay")
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    entry = {
        "id": name,
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rows": len(rows),
        "provider": "USCG / NOAA / BOEM; NOAA CO-OPS",
        "site": "Los Angeles–Long Beach bbox; Angels Gate wind station 9410647",
        "landing_url": provenance["landing_page"],
        "time_start": rows[0]["timestamp"],
        "time_end": rows[-1]["timestamp"],
        "evidence_class": "historical_ais_and_station_asof_join",
        "unit": "AIS counts, knots; wind m/s; pressure hPa",
        "temporal_resolution": "AIS observed one-minute buckets; last station record at most six minutes earlier",
        "source_bindings": [
            {"path": str(base.relative_to(ROOT)), "sha256": base_sha},
            *[{"path": entries[n]["path"], "sha256": entries[n]["sha256"]} for n in columns.values()],
        ],
        "joined_nonmissing_counts": counts,
        "license": provenance["license"],
        "transformations": [
            "Latest station observation at or before each AIS timestamp; maximum lag 360s.",
            "Reject flagged station observations; retain missing values, no interpolation or future joins.",
        ],
        "limitations": "风速为附近单站；AIS状态仅为排队代理。设备、泊位、堆场、货物量和能源实绩仍未知；观测事件时间对齐不证明当时数据发布时间。",
    }
    manifest["entries"].append(entry)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    provenance = {
        **entry,
        "schema_version": "xiaoyi-public-dataset-provenance.v1",
        "derived_csv_sha256": entry["sha256"],
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }
    path.with_suffix(".provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"id": name, "rows": len(rows), "joined_nonmissing_counts": counts}))


if __name__ == "__main__":
    main()
