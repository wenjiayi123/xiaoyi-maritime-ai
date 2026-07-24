from __future__ import annotations

import csv
import hashlib
import io
import json
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "public"
OUTPUT_CSV = OUTPUT_DIR / "uci_appliances_energy.csv"
PROVENANCE_PATH = OUTPUT_DIR / "uci_appliances_energy.provenance.json"
SOURCE_URL = "https://archive.ics.uci.edu/static/public/374/appliances+energy+prediction.zip"
LANDING_PAGE = "https://archive.ics.uci.edu/dataset/374/appliances+energy+prediction"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download() -> bytes:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "Xiaoyi-RL-Dataset-Fetcher/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310 - fixed UCI HTTPS URL
        return response.read()


def convert(archive: bytes) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        member = next(name for name in bundle.namelist() if name.endswith("energydata_complete.csv"))
        with bundle.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
            reader = csv.DictReader(text)
            temporary = OUTPUT_CSV.with_suffix(".csv.tmp")
            with temporary.open("w", encoding="utf-8", newline="") as target:
                fields = [
                    "timestamp",
                    "load_kw",
                    "temperature_c",
                    "humidity_percent",
                    "wind_speed_mps",
                    "visibility_km",
                    "pressure_hpa",
                ]
                writer = csv.DictWriter(target, fieldnames=fields)
                writer.writeheader()
                row_count = 0
                for row in reader:
                    # UCI Appliances is energy used during a 10-minute interval in Wh.
                    # Average kW = Wh / (10/60 h) / 1000 = Wh * 0.006.
                    writer.writerow(
                        {
                            "timestamp": row["date"],
                            "load_kw": f"{float(row['Appliances']) * 0.006:.6f}",
                            "temperature_c": row["T_out"],
                            "humidity_percent": row["RH_out"],
                            "wind_speed_mps": row["Windspeed"],
                            "visibility_km": row["Visibility"],
                            "pressure_hpa": f"{float(row['Press_mm_hg']) * 1.333223874:.6f}",
                        }
                    )
                    row_count += 1
            temporary.replace(OUTPUT_CSV)
    return row_count


def main() -> None:
    archive = download()
    rows = convert(archive)
    provenance = {
        "schema_version": "xiaoyi-public-dataset-provenance.v1",
        "dataset_id": "uci_appliances_energy",
        "title": "Appliances Energy Prediction",
        "creator": "Luis Candanedo",
        "publisher": "UCI Machine Learning Repository",
        "landing_page": LANDING_PAGE,
        "download_url": SOURCE_URL,
        "doi": "10.24432/C5VC8G",
        "license": "Creative Commons Attribution 4.0 International (CC BY 4.0)",
        "citation": "Candanedo, L. (2017). Appliances Energy Prediction. UCI Machine Learning Repository. https://doi.org/10.24432/C5VC8G",
        "downloaded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_archive_sha256": sha256_bytes(archive),
        "derived_csv_sha256": sha256_file(OUTPUT_CSV),
        "row_count": rows,
        "transformations": [
            "Selected timestamp, appliance energy and outdoor weather columns.",
            "Converted Appliances Wh per 10-minute interval to average load_kw using Wh * 0.006.",
            "Converted Press_mm_hg to pressure_hpa using mmHg * 1.333223874.",
            "Renamed fields to the xiaoyi energy time-series contract; no interpolation or row synthesis.",
        ],
        "scope_notice": "This is real building-energy data used only as a public algorithm benchmark. It is not port, terminal, AGV or production data.",
    }
    PROVENANCE_PATH.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT_CSV), "rows": rows, "sha256": provenance["derived_csv_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
