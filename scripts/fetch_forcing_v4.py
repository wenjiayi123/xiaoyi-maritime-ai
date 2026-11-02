"""Freeze individual weather runs and genuinely observed July gauge targets."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/public/forecast_forcing_v4_20261030"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    if (OUT / "manifest.json").exists():
        raise ValueError("preserve frozen source manifest")
    plan = json.loads((OUT / "protocol.json").read_text())
    raw = OUT / "raw"
    raw.mkdir(exist_ok=True)
    stations = list(plan["stations"])
    tasks = []
    for role, field in [("fit", "fit_runs"), ("selection", "selection_runs"),
                        ("calibration", "calibration_runs"), ("test", "fresh_test_runs")]:
        for run in plan[field]:
            tasks.append(("weather", role, run))
    for station in stations:
        if len(station) == 7:
            tasks.append(("noaa_observed", "test", station))

    def acquire(task):
        kind, role, identity = task
        target = raw / f"{kind}-{identity}.json"
        receipt = target.with_suffix(".receipt.json")
        if target.exists() and receipt.exists():
            entry = json.loads(receipt.read_text())
            assert sha(target) == entry["sha256"]
            return entry
        if kind == "weather":
            url = plan["weather_endpoint"]
            params = {"latitude": ",".join(str(plan["stations"][s]["lat"]) for s in stations),
                      "longitude": ",".join(str(plan["stations"][s]["lon"]) for s in stations),
                      "hourly": ",".join(plan["weather_variables"]), "models": plan["weather_model"],
                      "run": identity + "T00:00", "forecast_days": 8, "timezone": "GMT", "wind_speed_unit": "ms"}
        else:
            url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
            params = {"product": "hourly_height", "station": identity, "begin_date": "20260701", "end_date": "20260731",
                      "application": "xiaoyi-frozen-research", "datum": "MLLW", "time_zone": "gmt", "units": "metric", "format": "json"}
        response = requests.get(url, params=params, timeout=120)
        target.write_bytes(response.content)
        try:
            value = response.json()
            provider_error = value.get("reason", value.get("error")) if isinstance(value, dict) else None
        except ValueError:
            value, provider_error = {}, "non_json_response"
        entry = {"kind": kind, "role": role, "id": identity, "url": response.url,
                 "path": str(target.relative_to(ROOT)), "sha256": sha(target), "http_status": response.status_code,
                 "provider_error": provider_error, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                 "stations_in_request_order": stations if kind == "weather" else [identity],
                 "initialization_utc": identity + "T00:00:00Z" if kind == "weather" else None,
                 "assumed_available_utc": identity + "T08:00:00Z" if kind == "weather" else None,
                 "units": "hPa,m/s,degrees" if kind == "weather" else "metres MLLW, verified hourly"}
        write(receipt, entry)
        print("ACQUIRED", kind, role, identity, response.status_code, provider_error, flush=True)
        return entry

    with ThreadPoolExecutor(max_workers=4) as pool:
        entries = list(pool.map(acquire, tasks))
    write(OUT / "manifest.json", {"schema": "xiaoyi-frozen-weather-run-sources.v4",
          "protocol_sha256": sha(OUT / "protocol.json"), "entries": entries,
          "water_history_manifest": {"path": "data/public/physical_twin_v3_20261030/manifest.json",
                                     "sha256": sha(ROOT / "data/public/physical_twin_v3_20261030/manifest.json")},
          "tide_selection": {"path": "data/public/physical_twin_v3_20261030/selection-before-test.json",
                             "sha256": sha(ROOT / "data/public/physical_twin_v3_20261030/selection-before-test.json")},
          "references": ["https://open-meteo.com/en/docs/single-runs-api", "https://open-meteo.com/en/licence",
                         "https://api.tidesandcurrents.noaa.gov/api/prod/", "https://uhslc.soest.hawaii.edu/data/"],
          "assumptions": plan["assumptions"], "production_authority": False})


if __name__ == "__main__":
    main()
