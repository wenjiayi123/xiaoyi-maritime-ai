from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "public"
DEFAULT_OUTPUT = OUTPUT_DIR / "noaa_la_lb_ais_2024_12_25_1min.csv"
DEFAULT_PROVENANCE = OUTPUT_DIR / "noaa_la_lb_ais_2024_12_25_1min.provenance.json"
DEFAULT_URL = (
    "https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2024/"
    "AIS_2024_12_25.zip"
)
DEFAULT_BBOX = (-118.32, 33.65, -118.10, 33.82)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _float(row: dict[str, str], field: str) -> float | None:
    raw = str(row.get(field) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _integer(row: dict[str, str], field: str) -> int | None:
    value = _float(row, field)
    return int(value) if value is not None else None


def _minute(timestamp: datetime) -> datetime:
    return timestamp.replace(second=0, microsecond=0)


def _bucket() -> dict[str, Any]:
    return {
        "vessels": set(),
        "anchored": set(),
        "slow": set(),
        "cargo": set(),
        "tanker": set(),
        "passenger": set(),
        "tug": set(),
        "sog_sum": 0.0,
        "sog_count": 0,
    }


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Xiaoyi-NOAA-AIS-Fetcher/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=180) as response, target.open("wb") as output:  # nosec B310 - explicit HTTPS dataset URL
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)


def convert(
    archive_path: Path,
    output_path: Path,
    *,
    bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    west, south, east, north = bbox
    buckets: dict[datetime, dict[str, Any]] = defaultdict(_bucket)
    scanned_rows = 0
    matched_rows = 0
    with zipfile.ZipFile(archive_path) as bundle:
        member = next(name for name in bundle.namelist() if name.lower().endswith(".csv"))
        with bundle.open(member) as raw, io.TextIOWrapper(
            raw, encoding="utf-8-sig", newline=""
        ) as text:
            reader = csv.DictReader(text)
            required = {"MMSI", "BaseDateTime", "LAT", "LON", "SOG", "VesselType", "Status"}
            missing = sorted(required - set(reader.fieldnames or []))
            if missing:
                raise ValueError(f"NOAA AIS CSV is missing fields: {missing}")
            for row in reader:
                scanned_rows += 1
                lat = _float(row, "LAT")
                lon = _float(row, "LON")
                if lat is None or lon is None or not (west <= lon <= east and south <= lat <= north):
                    continue
                try:
                    timestamp = datetime.fromisoformat(str(row["BaseDateTime"]).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                mmsi = str(row.get("MMSI") or "").strip()
                if not mmsi:
                    continue
                matched_rows += 1
                bucket = buckets[_minute(timestamp)]
                bucket["vessels"].add(mmsi)
                sog = _float(row, "SOG")
                status = _integer(row, "Status")
                vessel_type = _integer(row, "VesselType")
                if status in {1, 5}:
                    bucket["anchored"].add(mmsi)
                if sog is not None and sog <= 1.0:
                    bucket["slow"].add(mmsi)
                if sog is not None and 0 <= sog < 102.3:
                    bucket["sog_sum"] += sog
                    bucket["sog_count"] += 1
                if vessel_type is not None:
                    if 70 <= vessel_type <= 79:
                        bucket["cargo"].add(mmsi)
                    elif 80 <= vessel_type <= 89:
                        bucket["tanker"].add(mmsi)
                    elif 60 <= vessel_type <= 69:
                        bucket["passenger"].add(mmsi)
                    elif vessel_type == 52:
                        bucket["tug"].add(mmsi)
    if not buckets:
        raise ValueError("no AIS rows matched the configured port bounding box")
    observed_minutes = sorted(buckets)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    fieldnames = [
        "timestamp",
        "vessel_count",
        "anchored_vessels",
        "slow_vessels",
        "avg_sog_knots",
        "cargo_vessels",
        "tanker_vessels",
        "passenger_vessels",
        "tug_vessels",
    ]
    with temporary.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        for timestamp in observed_minutes:
            item = buckets[timestamp]
            writer.writerow(
                {
                    "timestamp": timestamp.isoformat(),
                    "vessel_count": len(item["vessels"]),
                    "anchored_vessels": len(item["anchored"]),
                    "slow_vessels": len(item["slow"]),
                    "avg_sog_knots": (
                        f"{item['sog_sum'] / item['sog_count']:.6f}"
                        if item["sog_count"]
                        else "0.000000"
                    ),
                    "cargo_vessels": len(item["cargo"]),
                    "tanker_vessels": len(item["tanker"]),
                    "passenger_vessels": len(item["passenger"]),
                    "tug_vessels": len(item["tug"]),
                }
            )
    temporary.replace(output_path)
    return {
        "source_rows_scanned": scanned_rows,
        "source_rows_in_bbox": matched_rows,
        "derived_rows": len(observed_minutes),
        "time_start": observed_minutes[0].isoformat(),
        "time_end": observed_minutes[-1].isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a one-minute port traffic scenario from NOAA AIS")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        default=DEFAULT_BBOX,
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="xiaoyi-noaa-ais-") as directory:
        archive_path = Path(directory) / "ais.zip"
        download(args.url, archive_path)
        source_sha256 = file_sha256(archive_path)
        counts = convert(archive_path, args.output, bbox=tuple(args.bbox))
    provenance = {
        "schema_version": "xiaoyi-public-dataset-provenance.v1",
        "dataset_id": "noaa_la_lb_ais_2024_12_25_1min",
        "title": "NOAA MarineCadastre historical AIS point data",
        "providers": [
            "U.S. Coast Guard Nationwide AIS",
            "NOAA Office for Coastal Management",
            "Bureau of Ocean Energy Management",
        ],
        "landing_page": "https://coast.noaa.gov/digitalcoast/tools/ais.html",
        "download_url": args.url,
        "license": (
            "U.S. Government material; free for public use under the NOAA "
            "MarineCadastre AIS terms, with U.S. Government material notice"
        ),
        "downloaded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_archive_sha256": source_sha256,
        "derived_csv_sha256": file_sha256(args.output),
        "bbox_wgs84": {
            "west": args.bbox[0],
            "south": args.bbox[1],
            "east": args.bbox[2],
            "north": args.bbox[3],
        },
        **counts,
        "transformations": [
            "Filtered published AIS point records to the declared WGS84 bounding box.",
            "Grouped records into UTC one-minute buckets and counted unique MMSI values.",
            "Derived anchored counts from AIS navigation status 1 or 5 and slow counts from SOG <= 1 knot.",
            "Derived vessel-class counts from published AIS VesselType codes.",
            "Retained only minute buckets containing published AIS messages; no empty or vessel records were synthesized.",
        ],
        "scope_notice": (
            "Vessel counts, navigation status, vessel type and speed are derived from measured AIS messages. "
            "They are suitable for a public traffic-driven planning scenario, not regulatory enforcement. "
            "Berth, yard, equipment, cargo, tide, weather and energy production fields remain site-required."
        ),
    }
    args.provenance.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows": counts["derived_rows"],
                "source_rows_in_bbox": counts["source_rows_in_bbox"],
                "sha256": provenance["derived_csv_sha256"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
