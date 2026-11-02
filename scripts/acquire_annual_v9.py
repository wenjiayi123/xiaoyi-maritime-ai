"""NOAA hourly, station-bound, verified observations; freeze before test fetch."""

import argparse
import gzip
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/public/annual_v9_20261031"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(phase):
    target = DATA / (phase + "-manifest.json")
    if target.exists():
        raise ValueError("append-only source manifest")
    plan = json.loads((DATA / "protocol.json").read_text())
    if phase == "test":
        sealed = json.loads((DATA / "selection-before-test.json").read_text())
        for p, h in sealed["source_sha256"].items():
            assert sha(ROOT / p) == h, p
    years = plan["history_years"] if phase == "history" else [plan["test_year"]]

    def fetch(job):
        sid, site, year = job
        path = DATA / "raw" / f"{sid}-{year}.json.gz"
        if path.exists():
            raise ValueError("original response already exists")
        params = {
            "product": "hourly_height",
            "station": sid,
            "begin_date": f"{year}0101",
            "end_date": f"{year}1231",
            "application": "xiaoyi-annual-v9",
            "datum": "MLLW",
            "time_zone": "gmt",
            "units": "metric",
            "format": "json",
        }
        url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
        try:
            response = requests.get(url, params=params, timeout=90)
            body, status, resolved = response.content, response.status_code, response.url
            error = status != 200 or not response.json().get("data")
        except (requests.RequestException, ValueError) as exc:
            body, status, resolved, error = str(exc).encode(), 0, url, True
        path.write_bytes(gzip.compress(body, mtime=0))
        print(sid, year, status, "error", bool(error), flush=True)
        return {
            "station_id": sid,
            "site": site,
            "year": year,
            "phase": phase,
            "provider": "noaa",
            "url": resolved,
            "http_status": status,
            "provider_error": bool(error),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "path": str(path.relative_to(ROOT)),
            "sha256": sha(path),
            "datum": "MLLW",
            "units": "m",
            "compression": "locally gzipped original response body",
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        entries = list(pool.map(fetch, [(sid, name, y) for sid, name in plan["stations"].items() for y in years]))
    with target.open("x") as handle:
        json.dump(
            {"protocol_sha256": sha(DATA / "protocol.json"), "entries": entries, "production_authority": False},
            handle,
            indent=2,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["history", "test"])
    main(parser.parse_args().phase)
