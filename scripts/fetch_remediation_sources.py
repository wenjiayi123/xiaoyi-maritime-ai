"""Acquire frozen international cohorts without silently filling or replacing missing data."""

import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def ports():
    folder = ROOT / "data/public/portwatch_v2_20261030"
    plan = json.loads((folder / "protocol.json").read_text())
    if (folder / "manifest.json").exists():
        raise ValueError("frozen source manifest already exists")
    old = json.loads((ROOT / "data/public/portwatch_crossport_20261030/manifest.json").read_text())
    raw = ROOT / old["published_csv_export"]["path"]
    if digest(raw) != old["published_csv_export"]["sha256"]:
        raise ValueError("original primary source changed")
    selected = {k: [] for k in plan["train_ports"] + list(plan["fresh_ports"])}
    scanned = 0
    with gzip.open(raw, "rt", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            scanned += 1
            if row["portid"] in selected:
                day = row["date"].replace("/", "-")[:10]
                if "2019-01-01" <= day <= "2026-09-30":
                    row["date"] = day
                    selected[row["portid"]].append(row)
    entries = []
    for pid, rows in selected.items():
        if not rows:
            raise ValueError("registered port absent: " + pid)
        rows.sort(key=lambda r: r["date"])
        if len({r["date"] for r in rows}) != len(rows):
            raise ValueError("duplicate provider dates")
        if pid in plan["fresh_ports"] and rows[0]["ISO3"] != plan["fresh_ports"][pid]["ISO3"]:
            raise ValueError("ambiguous port identity")
        path = folder / (pid + ".csv")
        with path.open("w", newline="") as h:
            writer = csv.DictWriter(h, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        entries.append(
            {
                "id": pid,
                "name": rows[0]["portname"],
                "country": rows[0]["country"],
                "iso3": rows[0]["ISO3"],
                "path": str(path.relative_to(ROOT)),
                "sha256": digest(path),
                "rows": len(rows),
                "start": rows[0]["date"],
                "end": rows[-1]["date"],
                "role": "training_and_temporal_holdout" if pid in plan["train_ports"] else "fresh_whole_port_holdout",
            }
        )
        print(pid, rows[0]["portname"], len(rows), rows[-1]["date"], flush=True)
    write(
        folder / "manifest.json",
        {
            "schema": "xiaoyi-portwatch-independent-cohort.v2",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "protocol_sha256": digest(folder / "protocol.json"),
            "primary_export": old["published_csv_export"],
            "primary_vintage_retrieved_at": old["retrieved_at"],
            "scanned": scanned,
            "entries": entries,
            "landing_url": old["entries"][0]["landing_url"],
            "terms_url": old["terms_url"],
            "license": old["license_text_from_provider"],
            "notice": "New ports and untouched 2026 periods extracted from the same pinned full official export, not a newly invented source vintage. AIS-derived indicators; historical revisions and publication times remain uncertain.",
            "production_authority": False,
        },
    )


def physical():
    folder = ROOT / "data/public/physical_twin_v2_20261030"
    plan = json.loads((folder / "protocol.json").read_text())
    if (folder / "manifest.json").exists():
        raise ValueError("frozen source manifest already exists")
    raw = folder / "raw"
    raw.mkdir(exist_ok=True)
    tasks = []
    for sid, site in plan["noaa_stations"].items():
        tasks.append(("noaa", sid, site, "fit", "20240101", "20241231", "hourly_height"))
        for split, periods in [("validation", plan["validation_blocks"]), ("test", plan["fresh_test_blocks"])]:
            for month in periods:
                first = month.replace("-", "") + "01"
                tasks.append(("noaa", sid, site, split, first, month.replace("-", "") + "08", "water_level"))
    for sid, site in plan["uhslc_stations"].items():
        tasks.append(("uhslc", sid, site, "all", "2024-01-01T00:00:00Z", "2026-09-01T00:00:00Z", "sea_level"))

    def download(task):
        provider, sid, site, split, begin, end, product = task
        if provider == "noaa":
            url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
            params = {
                "product": product,
                "application": "xiaoyi-public-research",
                "begin_date": begin,
                "end_date": end,
                "datum": "MLLW",
                "station": sid,
                "time_zone": "gmt",
                "units": "metric",
                "format": "json",
            }
        else:
            url = (
                "https://uhslc.soest.hawaii.edu/erddap/tabledap/global_hourly_fast.csv?time,sea_level,quality,reference_datum,record_id,latitude,station_name&uhslc_id="
                + sid
                + "&time>="
                + begin
                + "&time<"
                + end
            )
            params = None
        path = raw / (provider + "-" + sid + "-" + begin[:7].replace("-", "") + "-" + split + ".raw")
        if path.exists():
            raise ValueError("refuse to overwrite acquired raw data")
        response = requests.get(url, params=params, timeout=90)
        response.raise_for_status()
        path.write_bytes(response.content)
        if provider == "noaa":
            value = response.json()
            if "error" in value:
                raise ValueError(str(value["error"]))
            n = len(value["data"])
        else:
            n = max(0, len(list(csv.reader(io.StringIO(response.text)))) - 2)
        print(provider, sid, split, begin, n, flush=True)
        return {
            "provider": provider,
            "station_id": sid,
            "site": site,
            "split": split,
            "period": [begin, end],
            "product": product,
            "url": response.url,
            "path": str(path.relative_to(ROOT)),
            "sha256": digest(path),
            "rows": n,
            "units": "m MLLW" if provider == "noaa" else "mm local reference_datum; convert to m by /1000",
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        entries = list(pool.map(download, tasks))
    info = ROOT / ".codex_artifacts/remediation-20261030/uhslc-info.raw"
    target = raw / "uhslc-metadata.json"
    target.write_bytes(info.read_bytes())
    write(
        folder / "manifest.json",
        {
            "schema": "xiaoyi-international-physical-sources.v2",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "protocol_sha256": digest(folder / "protocol.json"),
            "entries": entries,
            "uhslc_metadata": {
                "path": str(target.relative_to(ROOT)),
                "sha256": digest(target),
                "url": "https://uhslc.soest.hawaii.edu/erddap/info/global_hourly_fast/index.json",
            },
            "landing_urls": ["https://api.tidesandcurrents.noaa.gov/api/prod/", "https://uhslc.soest.hawaii.edu/data/"],
            "notice": "NOAA verified local-datum observations and UHSLC FD/RQ hourly observations; UHSLC normally published 4-6 weeks later. Operational short-horizon replay is a declared hypothetical sensor-access experiment, not a live UHSLC service.",
            "production_authority": False,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["ports", "physical"])
    args = parser.parse_args()
    {"ports": ports, "physical": physical}[args.kind]()
