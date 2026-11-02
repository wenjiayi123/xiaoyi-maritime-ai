"""Freeze a new Shanghai public-data lab without modifying historical evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/public/shanghai_lab_v1_20261031"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def fetch(out, key, url, expected=()):
    path = out / "raw" / (key + (".json" if "archive-api" in url else ".html"))
    if not path.exists():
        with urlopen(Request(url, headers={"User-Agent": "ShanghaiPublicResearchLab/1.0"}), timeout=55) as response:
            raw = response.read(15_000_001)
        if len(raw) > 15_000_000:
            raise ValueError("source too large")
        path.write_bytes(raw)
    text = path.read_text(encoding="utf-8")
    for term in expected:
        if term not in text:
            raise ValueError(f"{key}: expected source value absent: {term}")
    return {
        "id": key,
        "url": url,
        "path": str(path.relative_to(out)),
        "sha256": sha(path),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "bytes": path.stat().st_size,
    }


def build(out, resume=False):
    if out.exists() and (not resume or (out / "manifest.json").exists()):
        raise FileExistsError("refusing to overwrite a frozen dataset; use a new version")
    (out / "raw").mkdir(parents=True, exist_ok=True)
    previous = ROOT / "data/public/portwatch_crossport_20261030"
    parent = json.loads((previous / "manifest.json").read_text())
    entry = next(x for x in parent["entries"] if x["id"] == "port1188")
    source = ROOT / entry["path"]
    if sha(source) != entry["sha256"]:
        raise ValueError("original Shanghai series hash mismatch")
    archive = ROOT / parent["published_csv_export"]["path"]
    if sha(archive) != parent["published_csv_export"]["sha256"]:
        raise ValueError("original official export hash mismatch")
    shutil.copy2(source, out / "shanghai_daily.csv")
    shutil.copy2(previous / "manifest.json", out / "raw/parent_manifest.json")
    shutil.copy2(previous / "raw/export-item-metadata.json", out / "raw/portwatch_metadata.json")
    sources = [
        {
            "id": "imf_portwatch_shanghai",
            "url": entry["landing_url"],
            "provider": parent["provider"],
            "path": "shanghai_daily.csv",
            "sha256": sha(out / "shanghai_daily.csv"),
            "retrieved_at": parent["retrieved_at"],
            "evidence_class": "public_provider_derived",
            "scope": "IMF PortWatch Shanghai port polygon; not SIPG terminal dispatch events",
            "granularity": "provider calendar day; source timezone not asserted",
            "time_start": entry["time_start"],
            "time_end": entry["time_end"],
            "rows": entry["rows"],
            "original_archive": parent["published_csv_export"],
            "license_url": "https://www.imf.org/external/terms.htm",
        }
    ]
    sources.append(
        {
            **fetch(
                out,
                "shanghai_2025_official",
                "https://fgw.sh.gov.cn/fgw_ndjh/20260212/0d0d16e6f34044888d1606faaae8f69f.html",
                ("5506.3",),
            ),
            "published_at": "2026-02-12",
            "evidence_class": "official_aggregate",
            "scope": "Shanghai port annual container throughput",
        }
    )
    sources.append(
        {
            **fetch(
                out,
                "shanghai_2024_energy_official",
                "https://jtw.sh.gov.cn/gsgg/20250220/60de6bcde5dc40acbf6d60a80fe13838.html",
                ("5524.35", "211.88", "868"),
            ),
            "published_at": "2025-02-20",
            "evidence_class": "official_aggregate",
            "scope": "Shanghai municipal shore-power platform; not a single SIPG terminal",
        }
    )
    weather_url = "https://archive-api.open-meteo.com/v1/archive?" + urlencode(
        {
            "latitude": 30.626,
            "longitude": 122.071,
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "hourly": "temperature_2m,wind_speed_10m,surface_pressure,shortwave_radiation",
            "models": "era5",
            "wind_speed_unit": "ms",
            "timezone": "Asia/Shanghai",
        }
    )
    weather_source = fetch(out, "yangshan_era5_2025", weather_url)
    weather = json.loads((out / weather_source["path"]).read_text())
    if weather.get("timezone") != "Asia/Shanghai" or len(weather["hourly"]["time"]) != 8760:
        raise ValueError("unexpected weather timezone or hourly coverage")
    sources.append(
        {
            **weather_source,
            "evidence_class": "public_reanalysis",
            "scope": "ERA5 grid near Yangshan; not on-site sensors",
            "requested_coordinates": [30.626, 122.071],
            "grid_coordinates": [weather["latitude"], weather["longitude"]],
            "documentation": "https://open-meteo.com/en/docs/historical-weather-api",
            "license_url": "https://open-meteo.com/en/license",
        }
    )
    with (out / "yangshan_weather_2025.csv").open("w", newline="") as stream:
        keys = list(weather["hourly"])
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for i in range(8760):
            writer.writerow({k: weather["hourly"][k][i] for k in keys})
    anchors = [
        {
            "id": "annual_container_teu",
            "value": 55063000,
            "unit": "TEU/year",
            "year": 2025,
            "source_id": "shanghai_2025_official",
            "scope": "Shanghai port",
            "use": "context_only_not_hourly_ground_truth",
        },
        {
            "id": "shore_energy_kwh",
            "value": 55243500,
            "unit": "kWh/year",
            "year": 2024,
            "source_id": "shanghai_2024_energy_official",
            "scope": "Shanghai municipal shore-power platform",
            "use": "context_only_not_terminal_load",
        },
        {
            "id": "shore_connected_hours",
            "value": 2118800,
            "unit": "vessel_hours/year",
            "year": 2024,
            "source_id": "shanghai_2024_energy_official",
            "scope": "Shanghai municipal shore-power platform",
            "use": "context_only_not_vessel_service_time",
        },
        {
            "id": "shore_facilities",
            "value": 868,
            "unit": "facilities",
            "year": 2024,
            "source_id": "shanghai_2024_energy_official",
            "scope": "Shanghai municipal shore-power platform excluding shipyards",
            "use": "context_only_not_lab_capacity",
        },
    ]
    write(out / "official_anchors.json", anchors)
    assumptions = {
        "scope": "CNSHA-LAB-YANGSHAN: an explicitly engineered terminal cell within a Shanghai-port study; not an existing terminal inventory",
        "terminals": ["CNSHA-LAB-YANGSHAN-A", "CNSHA-LAB-YANGSHAN-B"],
        "resources": {"berths": 3, "cranes": 8, "pilots": 2, "tugs": 4, "channel_concurrency": 1},
        "equipment": {
            "grid_limit_kw": 12000,
            "battery_capacity_kwh": 6000,
            "battery_power_kw": 2000,
            "battery_efficiency": 0.95,
            "battery_initial_soc": 0.5,
            "battery_min_soc": 0.15,
            "battery_max_soc": 0.9,
            "pv_peak_kw": 3000,
        },
        "economics": {
            "off_peak_cny_per_kwh": 0.38,
            "shoulder_cny_per_kwh": 0.78,
            "peak_cny_per_kwh": 1.22,
            "battery_wear_cny_per_kwh": 0.08,
            "grid_carbon_kg_per_kwh": 0.55,
            "delay_cny_per_vessel_hour": 2000,
        },
        "uncertainty_ranges": {
            "load_multiplier": [0.8, 1.2],
            "service_time_multiplier": [0.8, 1.3],
            "price_multiplier": [0.7, 1.3],
            "battery_wear_cny_per_kwh": [0.04, 0.18],
            "grid_carbon_kg_per_kwh": [0.35, 0.75],
        },
        "evidence_class": "declared_engineering_assumption",
        "rationale": "Bounded stress-test parameters for a representative multi-berth cell. No asset, tariff, carbon-factor, or operating-approval claim is made for SIPG.",
        "required_field_replacements": [
            "TOS vessel tasks and equipment inventory",
            "EMS/BMS power and state of charge",
            "meter and tariff contract",
            "approved emissions factors",
            "pilot/tug/channel restrictions",
        ],
        "production_authority": False,
    }
    write(out / "assumptions.json", assumptions)
    files = {
        str(p.relative_to(out)): {"sha256": sha(p), "bytes": p.stat().st_size}
        for p in sorted(out.rglob("*"))
        if p.is_file()
    }
    manifest = {
        "schema": "shanghai-public-lab-dataset.v1",
        "dataset_id": "shanghai_public_lab_v1_20261031",
        "port_id": "CNSHA",
        "name": "上海港公开数据校准联合试验",
        "timezone": "Asia/Shanghai",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "files": files,
        "training_boundary": {
            "2019-2023": "historical development",
            "2024": "validation",
            "2025": "retrospective evaluation; archive may have revisions; not historical availability proof",
        },
        "evidence_classes": [
            "official_aggregate",
            "public_provider_derived",
            "public_reanalysis",
            "declared_engineering_assumption",
            "simulation_output",
        ],
        "limitations": [
            "No Shanghai terminal telemetry, vessel identity, real task receipt or financial settlement.",
            "Annual totals are context; never divided into claimed measured hourly operations.",
            "Weather is reanalysis; a predictor cannot read future realized weather.",
            "Shared port identity does not establish physical model calibration or production authorization.",
        ],
        "preservation": "New version only; previous datasets, models, active pointers, metrics and demo defaults unchanged.",
        "production_authority": False,
    }
    write(out / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "output": str(out),
                "manifest_sha256": sha(out / "manifest.json"),
                "daily_rows": entry["rows"],
                "weather_hours": 8760,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--resume-unfrozen", action="store_true")
    args = parser.parse_args()
    build(args.output, args.resume_unfrozen)
