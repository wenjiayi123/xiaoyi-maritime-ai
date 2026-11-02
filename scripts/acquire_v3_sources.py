"""Acquire untouched whole-port and tide periods; preserve HTTP/raw provenance."""

import argparse
import csv
import gzip
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from app.harness.crossport_v2 import BASE_DIR, sha, write


def ports():
    folder = BASE_DIR / "data/public/portwatch_v3_20261030"
    plan = json.loads((folder / "protocol.json").read_text())
    assert not (folder / "manifest.json").exists()
    old = json.loads((BASE_DIR / "data/public/portwatch_crossport_20261030/manifest.json").read_text())
    raw = BASE_DIR / old["published_csv_export"]["path"]
    assert sha(raw) == old["published_csv_export"]["sha256"]
    selected = {pid: [] for pid in plan["fresh_ports"]}
    with gzip.open(raw, "rt", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["portid"] in selected:
                row["date"] = row["date"].replace("/", "-")[:10]
                selected[row["portid"]].append(row)
    entries = []
    for pid, rows in selected.items():
        rows.sort(key=lambda r: r["date"])
        assert rows and rows[0]["ISO3"] == plan["fresh_ports"][pid]["ISO3"]
        assert len({r["date"] for r in rows}) == len(rows)
        path = folder / f"{pid}.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        entries.append({"id": pid, "name": rows[0]["portname"], "country": rows[0]["country"],
                        "iso3": rows[0]["ISO3"], "rows": len(rows), "start": rows[0]["date"],
                        "end": rows[-1]["date"], "path": str(path.relative_to(BASE_DIR)), "sha256": sha(path)})
    write(folder / "manifest.json", {"schema": "xiaoyi-unseen-port-sources.v3",
          "extracted_at": datetime.now(timezone.utc).isoformat(), "protocol_sha256": sha(folder / "protocol.json"),
          "primary_export": old["published_csv_export"], "entries": entries, "landing_url": old["entries"][0]["landing_url"],
          "terms_url": old["terms_url"], "license": old["license_text_from_provider"],
          "notice": "Previously unscored ports, same pinned official source vintage; no operational ground truth.",
          "production_authority": False})
    print("NEW_PORTS", [(e["name"], e["rows"], e["end"]) for e in entries], flush=True)


def physical():
    folder = BASE_DIR / "data/public/physical_twin_v3_20261030"
    plan = json.loads((folder / "protocol.json").read_text())
    assert not (folder / "manifest.json").exists()
    raw = folder / "raw"
    raw.mkdir(exist_ok=True)
    jobs = []
    for sid, site in plan["noaa_stations"].items():
        for year in [2023, 2024, 2025]:
            jobs.append(("noaa", sid, site, str(year), f"{year}0101", f"{year}1231", "hourly_height"))
        for month in plan["test_months"] + plan["six_minute_development_months"]:
            start = datetime.fromisoformat(month + "-01") - timedelta(days=21)
            end = datetime.fromisoformat(month + "-08")
            jobs.append(("noaa", sid, site, month, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), "water_level"))
    for sid, site in plan["uhslc_stations"].items():
        jobs.append(("uhslc", sid, site, "2023-2026", "2023-01-01T00:00:00Z", "2026-10-01T00:00:00Z", "sea_level"))

    def download(job):
        provider, sid, site, label, begin, end, product = job
        path = raw / f"{provider}-{sid}-{label}-{product}.raw"
        if provider == "noaa":
            url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
            params = {"product": product, "station": sid, "begin_date": begin, "end_date": end,
                      "application": "xiaoyi-frozen-research", "datum": "MLLW", "time_zone": "gmt", "units": "metric", "format": "json"}
        else:
            url = ("https://uhslc.soest.hawaii.edu/erddap/tabledap/global_hourly_fast.csv?time,sea_level,quality,reference_datum,record_id,latitude,station_name&uhslc_id="
                   + sid + "&time>=" + begin + "&time<" + end)
            params = None
        receipt_path = path.with_suffix(".receipt.json")
        if path.exists() and receipt_path.exists():
            entry = json.loads(receipt_path.read_text())
            assert sha(path) == entry["sha256"]
            return entry
        response = requests.get(url, params=params, timeout=100)
        response.raise_for_status()
        path.write_bytes(response.content)
        error = response.json().get("error") if provider == "noaa" else None
        entry = {"provider": provider, "station_id": sid, "site": site, "label": label,
                 "product": product, "period": [begin, end], "path": str(path.relative_to(BASE_DIR)),
                 "sha256": sha(path), "url": response.url, "http_date": response.headers.get("Date"),
                 "retrieved_at": datetime.now(timezone.utc).isoformat(), "provider_error": error,
                 "units": "m MLLW" if provider == "noaa" else "mm local datum, /1000 to m"}
        write(receipt_path, entry)
        print("ACQUIRED", provider, sid, label, "provider_error", error, flush=True)
        return entry

    with ThreadPoolExecutor(max_workers=4) as pool:
        entries = list(pool.map(download, jobs))
    write(folder / "manifest.json", {"schema": "xiaoyi-unseen-tide-sources.v3",
          "protocol_sha256": sha(folder / "protocol.json"), "entries": entries,
          "landing_urls": ["https://api.tidesandcurrents.noaa.gov/api/prod/", "https://uhslc.soest.hawaii.edu/data/"],
          "quality": "Same strict v2 quality filters. Overlapping NOAA hourly/six-minute products must agree to1mm; conflict raises, no outcome-driven version selection.",
          "archive_latency": "NOAA monthly verification; UHSLC FD normally4-6weeks. Event-time replay assumes separate local sensor availability.",
          "production_authority": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["ports", "physical"])
    args = parser.parse_args()
    {"ports": ports, "physical": physical}[args.kind]()
