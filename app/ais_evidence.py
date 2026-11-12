"""Read a single UTC minute from the registered historical AIS source."""
import csv
import hashlib
import io
import json
from datetime import datetime, timezone

from app.rl_lab.datasets import get_dataset


def observed_minute(at: datetime) -> dict:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("UTC offset required for AIS evidence")
    instant = at.astimezone(timezone.utc)
    if instant.second or instant.microsecond:
        raise ValueError("Select an exact observed minute")
    dataset = get_dataset("noaa_la_lb_ais_2024_12_25_1min")
    manifest = json.loads(dataset.path.with_suffix(".provenance.json").read_bytes())
    raw = dataset.path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != manifest["derived_csv_sha256"] or dataset.id != manifest["dataset_id"]:
        raise ValueError("AIS evidence identity or content hash differs from registry")
    stamp = instant.isoformat()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    for row in reader:
        if row["timestamp"] == stamp:
            return {"dataset": dataset.id, "timestamp": stamp, "csv_line": reader.line_num,
                    "fields": row, "sha256": digest, "source_url": manifest["download_url"],
                    "mode": "historical_observation", "production_authority": False}
    raise LookupError("No published AIS record for the requested minute")
