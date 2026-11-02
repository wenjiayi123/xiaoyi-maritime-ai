"""Freeze the provider's published CSV export and extract named-port cohorts locally."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/public/portwatch_crossport_20261030"
URL = "https://hub.arcgis.com/api/download/v1/items/83b1bbc7b3354c5fb1f40673bb8f852e/csv?layers=0"
EXPECTED = {
    "port1201": "Singapore",
    "port1114": "Rotterdam",
    "port1188": "Shanghai",
    "port664": "Los Angeles-Long Beach",
    "port57": "Antwerp",
    "port824": "Ningbo",
    "port744": "Jebel Ali",
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "manifest.json").exists():
        raise FileExistsError("do not overwrite frozen public evidence")
    raw = OUT / "raw"
    raw.mkdir(exist_ok=True)
    response = requests.get(URL, stream=True, timeout=60)
    response.raise_for_status()
    encoded = response.headers.get("Content-Encoding", "").lower() == "gzip"
    path = raw / ("published-daily-ports-export.csv.gz" if encoded else "published-daily-ports-export.csv")
    size = 0
    hashing = hashlib.sha256()
    with path.open("wb") as target:
        for chunk in response.raw.stream(1024 * 1024, decode_content=False):
            size += len(chunk)
            if size > 500_000_000:
                raise ValueError("provider export exceeds bounded download size")
            hashing.update(chunk)
            target.write(chunk)
    if response.headers.get("Content-Length") and size != int(response.headers["Content-Length"]):
        raise ValueError("incomplete primary CSV download")
    receipt = {
        "url": response.url,
        "requested_url": URL,
        "path": str(path.relative_to(ROOT)),
        "sha256": hashing.hexdigest(),
        "bytes": size,
        "http_content_encoding": response.headers.get("Content-Encoding"),
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
    }
    selected = {}
    names = {}
    scan = 0
    sg = {}
    with gzip.open(path, "rt", encoding="utf-8-sig") if encoded else path.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            scan += 1
            if row["ISO3"] == "SGP":
                sg[row["portid"]] = row["portname"]
            if row["portid"] not in EXPECTED and row["portname"].strip().lower() not in {"singapore", "hamburg"}:
                continue
            day = row["date"].replace("/", "-")[:10]
            if not "2019-01-01" <= day <= "2025-12-31":
                continue
            row["date"] = day
            pid = row["portid"]
            selected.setdefault(pid, []).append(row)
            names[pid] = row["portname"]
    print("scan", scan, "bytes", size, "Singapore source identities", sg, flush=True)
    entries = []
    for pid, rows in selected.items():
        rows.sort(key=lambda r: r["date"])
        if len({r["date"] for r in rows}) != len(rows):
            raise ValueError("duplicate provider date records")
        target = OUT / (pid + ".csv")
        with target.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        entry = {
            "id": pid,
            "expected_port_name": EXPECTED.get(pid, names[pid]),
            "port_name": names[pid],
            "country": rows[0]["country"],
            "iso3": rows[0]["ISO3"],
            "path": str(target.relative_to(ROOT)),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "rows": len(rows),
            "time_start": rows[0]["date"],
            "time_end": rows[-1]["date"],
            "missing_days_in_requested_period": 2557 - len(rows),
            "raw_pages": [receipt],
            "unit": "AIS-derived port calls/day; import/export are provider-estimated metric tons/day",
            "source_class": "primary_provider_AIS_derived_indicator; not terminal sensor ground truth",
            "landing_url": "https://portwatch.imf.org/datasets/83b1bbc7b3354c5fb1f40673bb8f852e_0/about",
        }
        entries.append(entry)
        print(pid, names[pid], len(rows), rows[0]["date"], rows[-1]["date"], flush=True)
    root_item = "https://www.arcgis.com/sharing/rest/content/items/83b1bbc7b3354c5fb1f40673bb8f852e"
    meta = requests.get(root_item, params={"f": "json"}, timeout=30)
    meta.raise_for_status()
    (raw / "export-item-metadata.json").write_bytes(meta.content)
    item = meta.json()
    item_receipt = {
        "url": meta.url,
        "path": str((raw / "export-item-metadata.json").relative_to(ROOT)),
        "sha256": hashlib.sha256(meta.content).hexdigest(),
    }
    manifest = {
        "schema": "xiaoyi-portwatch-crossport.v1",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "provider": "IMF PortWatch / University of Oxford; UN Global Platform AIS",
        "provider_owner": item.get("owner"),
        "service_url": item.get("url"),
        "service_metadata": item_receipt,
        "item_metadata": item_receipt,
        "published_csv_export": receipt,
        "source_rows_scanned": scan,
        "entries": entries,
        "excluded_sources": [
            {
                "port_id": p,
                "expected_name": n,
                "reason": "not in frozen provider CSV; not replaced with fabricated data",
            }
            for p, n in EXPECTED.items()
            if p not in selected
        ],
        "request_period": ["2019-01-01", "2025-12-31"],
        "terms_url": "https://www.imf.org/external/terms.htm",
        "license_text_from_provider": item.get("licenseInfo"),
        "production_authority": False,
        "limitations": [
            "Frozen retrieved vintage may contain historical revisions; not an as-published real-time archive.",
            "Daily calls are AIS-derived indicators; trade volumes are estimates, not customs/terminal truth.",
            "Operational queue, service capacity, equipment, energy and outages remain declared engineering assumptions.",
            "Earlier REST query failures retained in extraction logs; the final source is the official published CSV export.",
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    if encoded:
        partial = raw / "published-daily-ports-export.csv"
        if partial.exists():
            partial.unlink()


if __name__ == "__main__":
    main()
