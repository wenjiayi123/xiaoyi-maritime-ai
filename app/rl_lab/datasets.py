from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from app.config import BASE_DIR, DATA_DIR


CATALOG_PATH = DATA_DIR / "rl_datasets.json"
PUBLIC_DATA_DIR = DATA_DIR / "public"

REQUIRED_CANONICAL_FIELDS = ("timestamp", "load_kw")
OPTIONAL_CANONICAL_FIELDS = (
    "temperature_c",
    "humidity_percent",
    "wind_speed_mps",
    "visibility_km",
    "pressure_hpa",
    "price_per_kwh",
    "carbon_kg_per_kwh",
)


class DatasetError(ValueError):
    """Raised when a dataset cannot satisfy the RL data contract."""


@dataclass(frozen=True)
class EnergyRecord:
    timestamp: datetime
    load_kw: float
    temperature_c: Optional[float] = None
    humidity_percent: Optional[float] = None
    wind_speed_mps: Optional[float] = None
    visibility_km: Optional[float] = None
    pressure_hpa: Optional[float] = None
    price_per_kwh: Optional[float] = None
    carbon_kg_per_kwh: Optional[float] = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "load_kw": self.load_kw,
            "temperature_c": self.temperature_c,
            "humidity_percent": self.humidity_percent,
            "wind_speed_mps": self.wind_speed_mps,
            "visibility_km": self.visibility_km,
            "pressure_hpa": self.pressure_hpa,
            "price_per_kwh": self.price_per_kwh,
            "carbon_kg_per_kwh": self.carbon_kg_per_kwh,
        }


@dataclass(frozen=True)
class DatasetDefinition:
    id: str
    label: str
    path: Path
    source_type: str
    source_url: str
    license: str
    citation: str
    description: str
    mapping: dict[str, str]
    timezone: str = "UTC"
    port_data: bool = False

    def public_dict(self, *, inspect_file: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "license": self.license,
            "citation": self.citation,
            "description": self.description,
            "timezone": self.timezone,
            "port_data": self.port_data,
            "available": self.path.is_file(),
            "path": str(self.path.relative_to(BASE_DIR)) if self.path.is_relative_to(BASE_DIR) else str(self.path),
            "required_fields": list(REQUIRED_CANONICAL_FIELDS),
            "optional_fields": list(OPTIONAL_CANONICAL_FIELDS),
            "mapping": self.mapping,
        }
        if inspect_file and self.path.is_file():
            payload.update(inspect_dataset(self))
        return payload


def _safe_project_path(value: str) -> Path:
    path = Path(os.path.expandvars(value)).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def _definition_from_dict(item: dict[str, Any]) -> DatasetDefinition:
    mapping = dict(item.get("mapping") or {})
    for field in REQUIRED_CANONICAL_FIELDS:
        mapping.setdefault(field, field)
    return DatasetDefinition(
        id=str(item["id"]),
        label=str(item.get("label") or item["id"]),
        path=_safe_project_path(str(item["path"])),
        source_type=str(item.get("source_type") or "configured_csv"),
        source_url=str(item.get("source_url") or ""),
        license=str(item.get("license") or "site-provided"),
        citation=str(item.get("citation") or ""),
        description=str(item.get("description") or ""),
        mapping=mapping,
        timezone=str(item.get("timezone") or "UTC"),
        port_data=bool(item.get("port_data", False)),
    )


def dataset_catalog() -> dict[str, DatasetDefinition]:
    if not CATALOG_PATH.is_file():
        raise DatasetError(f"RL dataset catalog is missing: {CATALOG_PATH}")
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    items = raw.get("datasets", []) if isinstance(raw, dict) else []
    definitions = {_definition_from_dict(item).id: _definition_from_dict(item) for item in items}

    configured_path = os.getenv("XIAOYI_RL_DATASET_PATH", "").strip()
    if configured_path:
        configured = _definition_from_dict(
            {
                "id": os.getenv("XIAOYI_RL_DATASET_ID", "site-port-energy"),
                "label": os.getenv("XIAOYI_RL_DATASET_LABEL", "站点港口能源时序数据"),
                "path": configured_path,
                "source_type": "site_csv",
                "source_url": os.getenv("XIAOYI_RL_DATASET_SOURCE_URL", ""),
                "license": "site-provided",
                "citation": os.getenv("XIAOYI_RL_DATASET_CITATION", "站点提供，需由部署方登记数据授权与血缘。"),
                "description": "通过环境变量挂载的站点数据；使用与公开基准相同的训练接口。",
                "mapping": json.loads(os.getenv("XIAOYI_RL_DATASET_MAPPING", "{}")),
                "timezone": os.getenv("XIAOYI_RL_DATASET_TIMEZONE", "UTC"),
                "port_data": True,
            }
        )
        definitions[configured.id] = configured
    return definitions


def get_dataset(dataset_id: str) -> DatasetDefinition:
    definition = dataset_catalog().get(dataset_id)
    if definition is None:
        raise DatasetError(f"Unknown dataset_id: {dataset_id}")
    if not definition.path.is_file():
        raise DatasetError(
            f"Dataset {dataset_id} is not installed at {definition.path}. "
            "Run scripts/fetch_public_rl_dataset.py or configure XIAOYI_RL_DATASET_PATH."
        )
    return definition


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    for parser in (
        datetime.fromisoformat,
        lambda text: datetime.strptime(text, "%Y-%m-%d %H:%M:%S"),
        lambda text: datetime.strptime(text, "%Y/%m/%d %H:%M:%S"),
    ):
        try:
            return parser(normalized)
        except ValueError:
            continue
    raise DatasetError(f"Unsupported timestamp value: {value!r}")


def _optional_float(row: dict[str, str], column: Optional[str]) -> Optional[float]:
    if not column:
        return None
    raw = str(row.get(column, "")).strip()
    if not raw:
        return None
    value = float(raw)
    if value != value or value in (float("inf"), float("-inf")):
        raise DatasetError(f"Non-finite value in column {column}")
    return value


def load_records(definition: DatasetDefinition) -> list[EnergyRecord]:
    records: list[EnergyRecord] = []
    with definition.path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = [definition.mapping[field] for field in REQUIRED_CANONICAL_FIELDS if definition.mapping[field] not in columns]
        if missing:
            raise DatasetError(f"Dataset {definition.id} is missing mapped columns: {missing}")
        for row_number, row in enumerate(reader, start=2):
            try:
                timestamp = _parse_timestamp(row[definition.mapping["timestamp"]])
                load_kw = _optional_float(row, definition.mapping["load_kw"])
                if load_kw is None or load_kw < 0:
                    raise DatasetError("load_kw must be a non-negative number")
                records.append(
                    EnergyRecord(
                        timestamp=timestamp,
                        load_kw=load_kw,
                        temperature_c=_optional_float(row, definition.mapping.get("temperature_c")),
                        humidity_percent=_optional_float(row, definition.mapping.get("humidity_percent")),
                        wind_speed_mps=_optional_float(row, definition.mapping.get("wind_speed_mps")),
                        visibility_km=_optional_float(row, definition.mapping.get("visibility_km")),
                        pressure_hpa=_optional_float(row, definition.mapping.get("pressure_hpa")),
                        price_per_kwh=_optional_float(row, definition.mapping.get("price_per_kwh")),
                        carbon_kg_per_kwh=_optional_float(row, definition.mapping.get("carbon_kg_per_kwh")),
                    )
                )
            except (KeyError, TypeError, ValueError, DatasetError) as exc:
                raise DatasetError(f"Invalid row {row_number} in {definition.id}: {exc}") from exc
    if len(records) < 200:
        raise DatasetError(f"Dataset {definition.id} has {len(records)} valid rows; at least 200 are required")
    records.sort(key=lambda item: item.timestamp)
    if any(current.timestamp <= previous.timestamp for previous, current in zip(records, records[1:])):
        raise DatasetError("Timestamps must be unique and strictly increasing after sorting")
    return records


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_step_minutes(records: list[EnergyRecord]) -> float:
    deltas = [
        (current.timestamp - previous.timestamp).total_seconds() / 60
        for previous, current in zip(records, records[1:])
    ]
    positive = sorted(value for value in deltas if value > 0)
    return positive[len(positive) // 2]


def inspect_dataset(definition: DatasetDefinition, records: Optional[list[EnergyRecord]] = None) -> dict[str, Any]:
    loaded = records if records is not None else load_records(definition)
    loads = sorted(item.load_kw for item in loaded)
    return {
        "row_count": len(loaded),
        "sha256": file_sha256(definition.path),
        "time_start": loaded[0].timestamp.isoformat(),
        "time_end": loaded[-1].timestamp.isoformat(),
        "step_minutes": round(infer_step_minutes(loaded), 3),
        "load_kw_min": round(loads[0], 6),
        "load_kw_median": round(loads[len(loads) // 2], 6),
        "load_kw_max": round(loads[-1], 6),
    }


def chronological_split(
    records: list[EnergyRecord],
    *,
    train_ratio: float,
    validation_ratio: float,
) -> tuple[list[EnergyRecord], list[EnergyRecord], list[EnergyRecord]]:
    if not 0.5 <= train_ratio <= 0.85:
        raise DatasetError("train_ratio must be between 0.50 and 0.85")
    if not 0.05 <= validation_ratio <= 0.25:
        raise DatasetError("validation_ratio must be between 0.05 and 0.25")
    if train_ratio + validation_ratio > 0.95:
        raise DatasetError("at least 5% of the rows must remain untouched for testing")
    train_end = int(len(records) * train_ratio)
    validation_end = train_end + int(len(records) * validation_ratio)
    train = records[:train_end]
    validation = records[train_end:validation_end]
    test = records[validation_end:]
    if min(len(train), len(validation), len(test)) < 24:
        raise DatasetError("each chronological split must contain at least 24 rows")
    return train, validation, test


def values_present(records: Iterable[EnergyRecord], field: str) -> int:
    return sum(getattr(item, field) is not None for item in records)
