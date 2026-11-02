"""Freeze small official historical port datasets; keep raw responses and full provenance."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/public/port_evidence_20261030")
    args = parser.parse_args()
    folder = ROOT / args.out
    folder.mkdir(parents=True, exist_ok=False)
    fetched = datetime.now(timezone.utc).isoformat()
    entries = []

    def fetch(name, url, suffix="json"):
        with urlopen(
            Request(url, headers={"User-Agent": "Mozilla/5.0 Xiaoyi-public-research/1.0"}), timeout=45
        ) as response:
            raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise ValueError("public evidence response exceeds size budget")
            final_url = response.url
        path = folder / (name + ".raw." + suffix)
        path.write_bytes(raw)
        return raw, {
            "requested_url": url,
            "resolved_url": final_url,
            "raw_path": str(path.relative_to(ROOT)),
            "raw_sha256": sha(raw),
            "retrieved_at": fetched,
        }

    def save(name, rows, provenance, **metadata):
        if not rows:
            raise ValueError(name + " returned no rows")
        path = folder / (name + ".csv")
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        path.write_text(stream.getvalue())
        entries.append(
            {
                "id": name,
                "path": str(path.relative_to(ROOT)),
                "sha256": sha(path.read_bytes()),
                "rows": len(rows),
                **provenance,
                **metadata,
            }
        )

    for product in ["water_level", "wind", "air_pressure"]:
        query = {
            "application": "xiaoyi-public-research",
            "begin_date": "20241223",
            "end_date": "20241229",
            "station": "9410647" if product == "wind" else "9410660",
            "time_zone": "gmt",
            "units": "metric",
            "format": "json",
            "product": product,
        }
        if product == "water_level":
            query["datum"] = "MLLW"
        raw, provenance = fetch(
            "noaa_la_" + product, "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?" + urlencode(query)
        )
        data = json.loads(raw)
        if "error" in data:
            raise ValueError(str(data["error"]))
        rows = []
        for r in data["data"]:
            value_key = "s" if product == "wind" else "v"
            try:
                value = float(r[value_key])
            except (ValueError, KeyError):
                continue
            row = {
                "timestamp": datetime.strptime(r["t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).isoformat(),
                "value": value,
                "flags": r.get("f", ""),
                "quality": r.get("q", "not_provided"),
            }
            if product == "wind":
                row.update(direction_degrees=r.get("d", ""), gust_mps=r.get("g", ""))
            rows.append(row)
        save(
            "noaa_la_" + product,
            rows,
            provenance,
            provider="NOAA CO-OPS",
            site="Los Angeles " + query["station"],
            station=data.get("metadata"),
            unit={"water_level": "m MLLW", "wind": "m/s", "air_pressure": "hPa"}[product],
            temporal_resolution="6 minutes; gaps retained",
            source_rows=len(data["data"]),
            missing_or_invalid_value_rows=len(data["data"]) - len(rows),
            raw_observation_period=[data["data"][0]["t"], data["data"][-1]["t"]],
            time_start=rows[0]["timestamp"],
            time_end=rows[-1]["timestamp"],
            evidence_class="historical_station_measurement",
            license="U.S. Government public data; retain NOAA attribution",
            limitations="单站观测；不代表全港风场、水深或船舶UKC。历史观测按事件时间回放，不代表当时已完成质检。",
            landing_url="https://api.tidesandcurrents.noaa.gov/api/prod/",
        )

    url = "https://portoflosangeles.org/business/statistics/container-statistics/historical-teu-statistics-2024"
    raw, provenance = fetch("port_la_teu_2024", url, "html")
    tables = Tables()
    tables.feed(raw.decode())
    months = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    rows = []
    for cells in tables.rows:
        if len(cells) >= 8 and cells[0] in months:
            rows.append(
                {
                    "month": f"2024-{months.index(cells[0]) + 1:02d}",
                    "loaded_import_teu": float(cells[1].replace(",", "")),
                    "loaded_export_teu": float(cells[4].replace(",", "")),
                    "total_teu": float(cells[7].replace(",", "")),
                }
            )
    if len(rows) != 12:
        raise ValueError("official LA monthly table shape changed")
    save(
        "port_la_teu_2024",
        rows,
        provenance,
        provider="Port of Los Angeles",
        site="Port of Los Angeles",
        unit="TEU/month",
        time_start="2024-01",
        time_end="2024-12",
        temporal_resolution="calendar month",
        evidence_class="official_monthly_port_statistics",
        license="Free data; credit Port of Los Angeles",
        landing_url=url,
        limitations="月度汇总，只能支撑需求尺度和跨月压力推演；不能还原单船挂靠、实时队列或作业事件。",
    )

    dataset = "d_042dd8b935eab998f389adaf559c80de"
    raw, provenance = fetch(
        "singapore_cargo_monthly", f"https://data.gov.sg/api/action/datastore_search?resource_id={dataset}&limit=10000"
    )
    result = json.loads(raw)["result"]
    rows = [{"month": r["month"], "cargo_throughput": r["cargo_throughput"]} for r in result["records"]]
    if result["total"] != len(rows):
        raise ValueError("Singapore response is paginated; do not silently truncate")
    save(
        "singapore_cargo_monthly",
        rows,
        provenance,
        provider="MPA / data.gov.sg",
        site="Port of Singapore",
        unit="source published values; absolute unit scale unresolved",
        temporal_resolution="calendar month",
        evidence_class="official_monthly_port_statistics",
        license="Singapore Open Data Licence; retain dataset attribution",
        landing_url=f"https://data.gov.sg/datasets/{dataset}/view",
        limitations="新加坡月度汇总独立保留；不与洛杉矶AIS拼成同一个物理港口，也不代表逐设备实测。",
    )
    manifest = {
        "schema": "xiaoyi-public-port-evidence.v1",
        "retrieved_at": fetched,
        "entries": entries,
        "production_authority": False,
        "notice": "真实公开历史观测及统计；场景假设和模型输出另列，历史回放不是生产接入。",
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"folder": str(folder), "entries": [{"id": e["id"], "rows": e["rows"]} for e in entries]}))


if __name__ == "__main__":
    main()
