"""Three port tide stations, disjoint seasons, official measured water-level records."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/public/multisite_tide_20261030"
STATIONS = {"9410660": "Los Angeles", "8518750": "The Battery, New York", "9447130": "Seattle"}
PERIODS = {
    "training": ("20240101", "20240131"),
    "validation": ("20240701", "20240707"),
    "sealed_test": ("20241201", "20241207"),
}


def main():
    OUT.mkdir(parents=True, exist_ok=False)

    def fetch(item):
        station, site, split, period = item
        params = {
            "product": "water_level",
            "application": "xiaoyi-public-research",
            "begin_date": period[0],
            "end_date": period[1],
            "datum": "MLLW",
            "station": station,
            "time_zone": "gmt",
            "units": "metric",
            "format": "json",
        }
        response = requests.get("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter", params=params, timeout=60)
        response.raise_for_status()
        value = response.json()
        path = OUT / (station + "-" + split + ".raw.json")
        path.write_bytes(response.content)
        if value.get("error"):
            raise ValueError(str(value["error"]))
        print(station, split, len(value["data"]), flush=True)
        return {
            "station_id": station,
            "site": site,
            "split": split,
            "period": period,
            "rows": len(value["data"]),
            "path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "url": response.url,
            "metadata": value.get("metadata"),
            "unit": "m relative to local station MLLW",
            "resolution": "6 minutes",
        }

    tasks = [(s, site, split, period) for s, site in STATIONS.items() for split, period in PERIODS.items()]
    with ThreadPoolExecutor(max_workers=3) as pool:
        entries = list(pool.map(fetch, tasks))
    manifest = {
        "schema": "xiaoyi-multisite-tide.v1",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "provider": "NOAA CO-OPS verified historical water-level observations",
        "entries": entries,
        "landing_url": "https://api.tidesandcurrents.noaa.gov/api/prod/",
        "harmonic_basis_source": "https://tidesandcurrents.noaa.gov/harcon.html?id=9410660",
        "limitations": [
            "Station MLLW is a local vertical datum; values cannot be compared as global elevation.",
            "Historical quality-verified observations may be revised. Actual historical publication timestamps are unavailable.",
            "Reduced-order tide calibration does not validate bathymetry, UKC, ship/terminal dynamics or control authorization.",
        ],
        "production_authority": False,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
