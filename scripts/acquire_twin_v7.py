"""Primary sources; history first, untouched truth only after model freeze."""

import argparse
import gzip
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/public/twin_v7_20261031"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["history", "test"])
    phase = parser.parse_args().phase
    target = DATA / (phase + "-manifest.json")
    if target.exists():
        raise ValueError("never overwrite original responses or manifests")
    plan = json.loads((DATA / "protocol.json").read_text())
    jobs, entries = [], []
    if phase == "history":
        for file in ["history-manifest.json", "test-manifest.json"]:
            old = json.loads((ROOT / "data/public/long_twin_v6_20261030" / file).read_text())
            for e in old["entries"]:
                if file.startswith("test") and not (e["provider"] == "uhslc" and e["label"] == "heldout-2025"):
                    continue
                if sha(ROOT / e["path"]) != e["sha256"]:
                    raise ValueError("old immutable primary response changed")
                entries.append({**e, "phase": "history", "previously_viewed": True})
        for sid, site in plan["new_annual_stations"].items():
            jobs.append(("uhslc", sid, site, "history2018-2024", "2018-01-01T00:00:00Z", "2024-12-31T23:00:00Z"))
        for sid, site in plan["previous_uhslc"].items():
            jobs.append(("uhslc", sid, site, "history2018", "2018-01-01T00:00:00Z", "2018-12-31T23:00:00Z"))
    else:
        sealed = json.loads((DATA / "selection-before-test.json").read_text())
        assert sealed["source_sha256"] == sha(ROOT / "app/harness/twin_v7.py")
        assert sealed["protocol_sha256"] == sha(DATA / "protocol.json")
        for sid, site in plan["new_annual_stations"].items():
            jobs.append(("uhslc", sid, site, "newstation2025", "2025-01-01T00:00:00Z", "2025-12-31T23:00:00Z"))
        for provider, stations in [("noaa", plan["noaa"]), ("uhslc", plan["previous_uhslc"])]:
            for sid, site in stations.items():
                jobs.append((provider, sid, site, "newperiod2026July", "2026-07-01T00:00:00Z", "2026-07-31T23:00:00Z"))

    def fetch(job):
        provider, sid, site, label, begin, end = job
        path = DATA / "raw" / f"{provider}-{sid}-{label}.raw.gz"
        if path.exists():
            raise ValueError("download response exists; do not replace a failure")
        url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
        params = None
        if provider == "noaa":
            params = {
                "product": "hourly_height",
                "station": sid,
                "begin_date": begin[:10].replace("-", ""),
                "end_date": end[:10].replace("-", ""),
                "application": "xiaoyi-registered-v7",
                "datum": "MLLW",
                "time_zone": "gmt",
                "units": "metric",
                "format": "json",
            }
        else:
            url = (
                "https://uhslc.soest.hawaii.edu/erddap/tabledap/global_hourly_fast.csv?"
                + f"time,sea_level,quality,reference_datum,record_id,latitude,longitude,station_name,last_rq_date&uhslc_id={sid}&time>={begin}&time<={end}"
            )
        try:
            response = requests.get(url, params=params, timeout=150)
            body, status, resolved = response.content, response.status_code, response.url
            encoding = response.encoding or "utf-8"
            error = status != 200 or body.lstrip().startswith(b"Error {")
            if provider == "noaa":
                payload = response.json()
                error = error or "error" in payload or not payload.get("data")
            etag, modified = response.headers.get("ETag"), response.headers.get("Last-Modified")
        except (requests.RequestException, ValueError) as exc:
            body, status, resolved, encoding = str(exc).encode(), 0, url, "utf-8"
            error, etag, modified = True, None, None
        path.write_bytes(gzip.compress(body, mtime=0))
        print(provider, sid, label, status, "error", error, flush=True)
        return {
            "provider": provider,
            "station_id": sid,
            "site": site,
            "label": label,
            "phase": phase,
            "url": resolved,
            "requested_begin": begin,
            "requested_end": end,
            "http_status": status,
            "provider_error": bool(error),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "path": str(path.relative_to(ROOT)),
            "sha256": sha(path),
            "decoded_body_sha256": hashlib.sha256(body).hexdigest(),
            "compression": "locally-gzipped-original-response-body",
            "encoding": encoding,
            "etag": etag,
            "last_modified": modified,
            "previously_viewed": False,
        }

    with ThreadPoolExecutor(max_workers=3) as pool:
        entries.extend(pool.map(fetch, jobs))
    target.write_text(
        json.dumps(
            {
                "schema": "xiaoyi-primary-twin-sources.v7",
                "phase": phase,
                "protocol_sha256": sha(DATA / "protocol.json"),
                "entries": entries,
                "notice": "Reused viewed history and new source requests distinguished. Errors retained; no interpolation, neighboring-station or model truth substitution.",
                "production_authority": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
