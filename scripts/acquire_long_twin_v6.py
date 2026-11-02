"""Acquire primary hourly history first; held-out truth only after selection freezes."""

import argparse
import gzip
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data/public/long_twin_v6_20261030"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["history", "test"])
    phase = parser.parse_args().phase
    protocol = json.loads((FOLDER / "protocol.json").read_text())
    target = FOLDER / (phase + "-manifest.json")
    if target.exists():
        raise ValueError("source manifest immutable; choose a new study")
    if phase == "test":
        selection = json.loads((FOLDER / "selection-before-test.json").read_text())
        assert selection["source_sha256"] == sha(ROOT / "app/harness/long_twin_v6.py")
        assert selection["protocol_sha256"] == sha(FOLDER / "protocol.json")
    raw = FOLDER / "raw"
    raw.mkdir(exist_ok=True)
    jobs, reused = [], []
    old = json.loads((ROOT / "data/public/physical_twin_v3_20261030/manifest.json").read_text())
    all_noaa = {**protocol["development_noaa"], **protocol["new_noaa"]}
    if phase == "history":
        for sid, name in all_noaa.items():
            for year in protocol["history_noaa_years"]:
                known = next(
                    (
                        e
                        for e in old["entries"]
                        if e["provider"] == "noaa" and e["station_id"] == sid and e.get("label") == str(year)
                    ),
                    None,
                )
                if known is None:
                    known = next(
                        (
                            e
                            for e in old["entries"]
                            if e["provider"] == "noaa"
                            and e["station_id"] == sid
                            and str(year) in e["path"]
                            and e["path"].endswith(str(year) + "-hourly_height.raw")
                        ),
                        None,
                    )
                if known:
                    assert sha(ROOT / known["path"]) == known["sha256"]
                    reused.append(
                        {**known, "phase": phase, "label": str(year), "compression": "none", "encoding": "utf-8"}
                    )
                else:
                    jobs.append(("noaa", sid, name, str(year), f"{year}0101", f"{year}1231"))
        for sid, name in protocol["new_uhslc"].items():
            jobs.append(("uhslc", sid, name, "2019-2024", "2019-01-01T00:00:00Z", "2024-12-31T23:00:00Z"))
    else:
        for sid, name in protocol["new_uhslc"].items():
            jobs.append(("uhslc", sid, name, "heldout-2025", "2025-01-01T00:00:00Z", "2025-12-31T23:00:00Z"))
        for sid, name in all_noaa.items():
            for begin, end in protocol["new_period_noaa_test"]["periods"]:
                jobs.append(("noaa", sid, name, "heldout-" + begin[:7], begin.replace("-", ""), end.replace("-", "")))

    def fetch(job):
        provider, sid, name, label, begin, end = job
        path = raw / f"{provider}-{sid}-{label}.raw.gz"
        if path.exists():
            raise ValueError("never overwrite a downloaded response")
        if provider == "noaa":
            url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
            params = {
                "product": "hourly_height",
                "station": sid,
                "begin_date": begin,
                "end_date": end,
                "application": "xiaoyi-frozen-long-horizon-v6",
                "datum": "MLLW",
                "time_zone": "gmt",
                "units": "metric",
                "format": "json",
            }
        else:
            url = "https://uhslc.soest.hawaii.edu/erddap/tabledap/global_hourly_fast.csv"
            query = f"time,sea_level,quality,reference_datum,record_id,latitude,longitude,station_name,last_rq_date&uhslc_id={sid}&time>={begin}&time<={end}"
            url += "?" + query
            params = None
        response = requests.get(url, params=params, timeout=150)
        path.write_bytes(gzip.compress(response.content, mtime=0))
        provider_error = response.status_code != 200
        if provider == "noaa":
            try:
                payload = response.json()
                provider_error = provider_error or "error" in payload or not payload.get("data")
            except ValueError:
                provider_error = True
        elif "Error {" in response.text:
            provider_error = True
        result = {
            "provider": provider,
            "station_id": sid,
            "site": name,
            "label": label,
            "phase": phase,
            "url": response.url,
            "requested_begin": begin,
            "requested_end": end,
            "http_status": response.status_code,
            "provider_error": bool(provider_error),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "path": str(path.relative_to(ROOT)),
            "sha256": sha(path),
            "decoded_body_sha256": hashlib.sha256(response.content).hexdigest(),
            "compression": "locally-gzipped-original-response-body",
            "encoding": response.encoding or "utf-8",
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
            "notice": "Primary returned response body preserved including errors. Local gzip is not claimed to be the original wire encoding.",
        }
        print(provider, sid, label, response.status_code, "error", provider_error, flush=True)
        return result

    with ThreadPoolExecutor(max_workers=3) as pool:
        entries = [*reused, *pool.map(fetch, jobs)]
    manifest = {
        "schema": "xiaoyi-long-openloop-primary-sources.v6",
        "phase": phase,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "protocol_sha256": sha(FOLDER / "protocol.json"),
        "entries": entries,
        "landing_urls": ["https://api.tidesandcurrents.noaa.gov/api/prod/", "https://uhslc.soest.hawaii.edu/data/"],
        "notice": "Historical calibration and independent held-out responses stored separately. FD and RQ are not conflated with live verified port telemetry.",
        "production_authority": False,
    }
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(phase, len(entries), "source responses", flush=True)


if __name__ == "__main__":
    main()
