"""Freeze from exposed 2024 development, acquire new NOAA 2025 periods, evaluate once."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.harness import adaptive_twin as twin  # noqa: E402


def fetch():
    plan = json.loads(twin.PLAN.read_text())
    if (twin.FOLDER / "manifest.json").exists():
        raise ValueError("source manifest already exists; preserve the original vintage")

    def download(item):
        station, season, period = item
        response = requests.get(
            "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter",
            params={
                "product": "water_level",
                "application": "xiaoyi-public-research",
                "begin_date": period[0],
                "end_date": period[1],
                "datum": "MLLW",
                "station": station["station_id"],
                "time_zone": "gmt",
                "units": "metric",
                "format": "json",
            },
            timeout=60,
        )
        response.raise_for_status()
        raw = response.json()
        if "error" in raw:
            raise ValueError(str(raw["error"]))
        path = twin.FOLDER / f"{station['station_id']}-{season}.raw.json"
        if path.exists():
            raise ValueError("refuse to overwrite source")
        path.write_bytes(response.content)
        print(station["station_id"], season, len(raw["data"]), flush=True)
        return {
            "station_id": station["station_id"],
            "site": station["site"],
            "season": season,
            "period": period,
            "path": str(path.relative_to(twin.BASE_DIR)),
            "sha256": twin.sha(path),
            "url": response.url,
            "metadata": raw.get("metadata"),
            "rows": len(raw["data"]),
            "units": "m local MLLW",
            "resolution": "6 minutes",
        }

    tasks = [(s, season, period) for s in plan["stations"] for season, period in plan["fresh_holdout_periods"].items()]
    with ThreadPoolExecutor(max_workers=3) as pool:
        entries = list(pool.map(download, tasks))
    twin.write(
        twin.FOLDER / "manifest.json",
        {
            "schema": "xiaoyi-noaa-fresh-2025.v1",
            "frozen_protocol_sha256": twin.sha(twin.PLAN),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "provider": "NOAA CO-OPS",
            "entries": entries,
            "landing_url": "https://api.tidesandcurrents.noaa.gov/api/prod/",
            "vintage_notice": "Retrieved historical verified records, may be revised; historical release times unavailable.",
            "production_authority": False,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["freeze", "fetch", "evaluate"])
    parser.add_argument("--legacy-report", type=Path)
    args = parser.parse_args()
    if args.phase == "freeze":
        print(json.dumps(twin.freeze(args.legacy_report.resolve()), ensure_ascii=False))
    elif args.phase == "fetch":
        fetch()
    else:
        result = twin.evaluate()
        print(
            json.dumps(
                {"all_research_gates_passed": result["all_research_gates_passed"], "results": result["results"]},
                ensure_ascii=False,
            )
        )
