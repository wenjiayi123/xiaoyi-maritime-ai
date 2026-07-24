from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.config import SOURCE_REGISTRY_PATH


@dataclass(frozen=True)
class SourceProvenance:
    """Auditable metadata attached to every indexed source document."""

    source_id: str
    display_name: str
    provenance_type: str = "unregistered"
    institution: str | None = None
    source_url: str | None = None
    version: str | None = None
    official: bool = False
    verification_status: str = "unregistered"
    source_quality: str = "unverified"
    license: str | None = None
    notes: str | None = None
    jurisdictions: tuple[str, ...] = ("GLOBAL",)
    content_scope: str = "internal_curated"
    legal_force: str = "non_binding_internal"
    effective_from: str | None = None
    effective_to: str | None = None
    last_verified_at: str | None = None
    review_due_at: str | None = None
    update_frequency: str | None = None

    @property
    def review_status(self) -> str:
        """Return a conservative freshness label for policy and UI decisions."""

        if not self.official:
            return "not_applicable"
        if not self.review_due_at:
            return "review_date_missing"
        try:
            return "review_due" if date.fromisoformat(self.review_due_at) < date.today() else "current"
        except ValueError:
            return "review_date_invalid"


@dataclass(frozen=True)
class SourceRegistry:
    schema_version: str
    registry_version: str
    documents: dict[str, SourceProvenance]
    expected_document_count: int | None = None

    def get(self, source_id: str) -> SourceProvenance:
        return self.documents.get(
            source_id,
            SourceProvenance(source_id=source_id, display_name=source_id),
        )

    def validate_inventory(self, source_ids: set[str]) -> None:
        registered = set(self.documents)
        missing = sorted(source_ids - registered)
        extra = sorted(registered - source_ids)
        if missing or extra:
            details: list[str] = []
            if missing:
                details.append(f"unregistered sources: {', '.join(missing)}")
            if extra:
                details.append(f"registry entries without files: {', '.join(extra)}")
            raise ValueError("Source registry inventory mismatch: " + "; ".join(details))
        if self.expected_document_count is not None and len(source_ids) != self.expected_document_count:
            raise ValueError(
                "Source registry document count mismatch: "
                f"expected {self.expected_document_count}, found {len(source_ids)}"
            )


def _nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_tuple(value: Any, *, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return fallback
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        return fallback
    normalized = tuple(
        dict.fromkeys(str(item).strip().upper() for item in values if str(item).strip())
    )
    return normalized or fallback


def _inferred_jurisdictions(source_id: str) -> tuple[str, ...]:
    lowered = source_id.lower()
    if "_cn_" in lowered or lowered.startswith("cn_"):
        return ("CN",)
    if "_sg_" in lowered or lowered.startswith("sg_"):
        return ("SG",)
    if "_my_" in lowered or lowered.startswith("my_") or "port_klang" in lowered:
        return ("MY",)
    return ("GLOBAL",)


def load_source_registry(path: Path = SOURCE_REGISTRY_PATH) -> SourceRegistry:
    if not path.exists():
        return SourceRegistry(schema_version="1.0", registry_version="missing", documents={})

    payload = json.loads(path.read_text(encoding="utf-8"))
    defaults = payload.get("defaults", {})
    raw_documents = payload.get("documents", {})
    if not isinstance(raw_documents, dict):
        raise ValueError("source_registry.json documents must be an object keyed by file name")

    documents: dict[str, SourceProvenance] = {}
    for source_id, overrides in raw_documents.items():
        if not isinstance(overrides, dict):
            raise ValueError(f"Source registry entry must be an object: {source_id}")
        record = {**defaults, **overrides}
        official = bool(record.get("official", False))
        documents[source_id] = SourceProvenance(
            source_id=source_id,
            display_name=str(record.get("display_name") or source_id),
            provenance_type=str(record.get("provenance_type") or "unregistered"),
            institution=_nullable_text(record.get("institution")),
            source_url=_nullable_text(record.get("source_url")),
            version=_nullable_text(record.get("version")),
            official=official,
            verification_status=str(record.get("verification_status") or "unregistered"),
            source_quality=str(record.get("source_quality") or "unverified"),
            license=_nullable_text(record.get("license")),
            notes=_nullable_text(record.get("notes")),
            jurisdictions=_string_tuple(
                record.get("jurisdictions"),
                fallback=_inferred_jurisdictions(source_id),
            ),
            content_scope=str(
                record.get("content_scope")
                or ("official_summary" if official else "internal_curated")
            ),
            legal_force=str(
                record.get("legal_force")
                or ("jurisdiction_dependent" if official else "non_binding_internal")
            ),
            effective_from=_nullable_text(record.get("effective_from")),
            effective_to=_nullable_text(record.get("effective_to")),
            last_verified_at=_nullable_text(record.get("last_verified_at")),
            review_due_at=_nullable_text(record.get("review_due_at")),
            update_frequency=_nullable_text(record.get("update_frequency")),
        )

    expected_count = payload.get("expected_document_count")
    return SourceRegistry(
        schema_version=str(payload.get("schema_version") or "1.0"),
        registry_version=str(payload.get("registry_version") or "unversioned"),
        documents=documents,
        expected_document_count=int(expected_count) if expected_count is not None else None,
    )
