"""Frozen primary-source international daily indicators. Never silently impute dates."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from datetime import date, timedelta

from app.config import BASE_DIR
from app.harness.contracts import digest

FOLDER = BASE_DIR / "data/public/portwatch_crossport_20261030"
TRAIN_PORTS = ["port1201", "port1114", "port1188", "port664"]
UNSEEN_PORTS = ["port57", "port824", "port744", "port446"]


def verified(path, checksum):
    path = (BASE_DIR / path).resolve()
    if not path.is_relative_to(FOLDER.resolve()):
        raise ValueError("cross-port evidence path is outside registered directory")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != checksum:
        raise ValueError("跨港公开源摘要变化，停止使用旧实验")
    return raw


def load_all():
    manifest = json.loads((FOLDER / "manifest.json").read_text())
    if manifest["schema"] != "xiaoyi-portwatch-crossport.v1":
        raise ValueError("unsupported cross-port source contract")
    for key in ["service_metadata", "item_metadata"]:
        verified(manifest[key]["path"], manifest[key]["sha256"])
    series = {}
    checked = set()
    for entry in manifest["entries"]:
        for page in entry["raw_pages"]:
            if page["path"] not in checked:
                verified(page["path"], page["sha256"])
                checked.add(page["path"])
        raw = verified(entry["path"], entry["sha256"])
        rows = list(csv.DictReader(io.StringIO(raw.decode())))
        if len(rows) != entry["rows"]:
            raise ValueError("cross-port row count changed")
        parsed = []
        for row in rows:
            value = float(row["portcalls"])
            if not math.isfinite(value) or value < 0 or value != int(value) or row["portid"] != entry["id"]:
                raise ValueError("invalid daily activity value or port binding")
            parsed.append({"date": date.fromisoformat(row["date"]), "calls": value})
        if len({r["date"] for r in parsed}) != len(parsed):
            raise ValueError("duplicate daily observation")
        series[entry["id"]] = sorted(parsed, key=lambda r: r["date"])
    if len(set(series) & set(TRAIN_PORTS)) < 3 or len(set(series) & set(UNSEEN_PORTS)) < 2:
        raise ValueError("insufficient independently sourced training/whole-port holdout cohort")
    return manifest, series


def catalog():
    try:
        manifest, series = load_all()
        return {
            **manifest,
            "available": True,
            "manifest_sha256": digest(manifest),
            "entries": [
                {
                    **e,
                    "integrity_valid": True,
                    "role": "training_ports" if e["id"] in TRAIN_PORTS else "whole_port_holdout",
                    "years": {str(y): sum(r["date"].year == y for r in series[e["id"]]) for y in range(2019, 2026)},
                }
                for e in manifest["entries"]
            ],
        }
    except (OSError, ValueError) as exc:
        return {"available": False, "error": str(exc), "entries": [], "production_authority": False}


def contiguous(rows, first, days, history=42):
    mapping = {r["date"]: r["calls"] for r in rows}
    dates = [first + timedelta(days=i) for i in range(-history, days)]
    if any(d not in mapping for d in dates):
        return None
    return [(d, mapping[d]) for d in dates]
