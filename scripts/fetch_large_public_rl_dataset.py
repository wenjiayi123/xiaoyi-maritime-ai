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
OUTPUT_CSV = OUTPUT_DIR / "uci_household_power_5min.csv"
PROVENANCE_PATH = OUTPUT_DIR / "uci_household_power_5min.provenance.json"
SOURCE_URL = (
    "https://archive.ics.uci.edu/static/public/235/"
    "individual+household+electric+power+consumption.zip"
)
LANDING_PAGE = (
    "https://archive.ics.uci.edu/dataset/235/"
    "individual+household+electric+power+consumption"
)


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
        headers={"User-Agent": "Xiaoyi-RL-Dataset-Fetcher/2.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310 - fixed UCI HTTPS URL
        return response.read()


def _bucket_start(timestamp: datetime) -> datetime:
    return timestamp.replace(minute=(timestamp.minute // 5) * 5, second=0, microsecond=0)


def convert(archive: bytes) -> dict[str, int]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source_rows = 0
    valid_rows = 0
    missing_rows = 0
    derived_rows = 0
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        member = next(
            name for name in bundle.namelist()
            if name.endswith("household_power_consumption.txt")
        )
        with bundle.open(member) as raw, io.TextIOWrapper(
            raw, encoding="utf-8-sig", newline=""
        ) as text:
            reader = csv.DictReader(text, delimiter=";")
            temporary = OUTPUT_CSV.with_suffix(".csv.tmp")
            with temporary.open("w", encoding="utf-8", newline="") as target:
                writer = csv.DictWriter(target, fieldnames=["timestamp", "load_kw"])
                writer.writeheader()
                active_bucket: datetime | None = None
                bucket_sum = 0.0
                bucket_count = 0

                def flush() -> None:
                    nonlocal derived_rows, bucket_sum, bucket_count
                    if active_bucket is None or bucket_count == 0:
                        return
                    writer.writerow(
                        {
                            "timestamp": active_bucket.isoformat(sep=" "),
                            "load_kw": f"{bucket_sum / bucket_count:.6f}",
                        }
                    )
                    derived_rows += 1
                    bucket_sum = 0.0
                    bucket_count = 0

                for row in reader:
                    source_rows += 1
                    raw_power = str(row.get("Global_active_power") or "").strip()
                    if not raw_power or raw_power == "?":
                        missing_rows += 1
                        continue
                    timestamp = datetime.strptime(
                        f"{row['Date']} {row['Time']}", "%d/%m/%Y %H:%M:%S"
                    )
                    bucket = _bucket_start(timestamp)
                    if active_bucket is not None and bucket != active_bucket:
                        flush()
                    active_bucket = bucket
                    bucket_sum += float(raw_power)
                    bucket_count += 1
                    valid_rows += 1
                flush()
            temporary.replace(OUTPUT_CSV)
    return {
        "source_rows": source_rows,
        "valid_source_rows": valid_rows,
        "missing_source_rows": missing_rows,
        "derived_rows": derived_rows,
    }


def main() -> None:
    archive = download()
    counts = convert(archive)
    provenance = {
        "schema_version": "xiaoyi-public-dataset-provenance.v1",
        "dataset_id": "uci_household_power_5min",
        "title": "Individual Household Electric Power Consumption",
        "creators": ["Georges Hebrail", "Alice Berard"],
        "publisher": "UCI Machine Learning Repository",
        "landing_page": LANDING_PAGE,
        "download_url": SOURCE_URL,
        "doi": "10.24432/C58K54",
        "license": "Creative Commons Attribution 4.0 International (CC BY 4.0)",
        "citation": (
            "Hebrail, G. & Berard, A. (2006). Individual Household Electric Power "
            "Consumption [Dataset]. UCI Machine Learning Repository. "
            "https://doi.org/10.24432/C58K54"
        ),
        "downloaded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_archive_sha256": sha256_bytes(archive),
        "derived_csv_sha256": sha256_file(OUTPUT_CSV),
        "row_count": counts["derived_rows"],
        **counts,
        "transformations": [
            "Parsed the published one-minute Date, Time and Global_active_power fields.",
            "Skipped source rows whose published active-power value is missing.",
            "Aggregated valid observations into five-minute buckets using the arithmetic mean.",
            "Renamed the measured global active power value to load_kw; no interpolation or synthetic rows were added.",
        ],
        "scope_notice": (
            "This is real household power data used as a large public algorithm benchmark. "
            "It is not port, terminal, AGV or production data."
        ),
    }
    PROVENANCE_PATH.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT_CSV),
                "rows": counts["derived_rows"],
                "sha256": provenance["derived_csv_sha256"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
