from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

from app.config import KB_PENDING_DIR


router = APIRouter(prefix="/api/knowledge/intake", tags=["知识资料待审核入库"])

MAX_CONTENT_CHARACTERS = 1_000_000
MAX_CONTENT_BYTES = 2_000_000
MAX_FILENAME_CHARACTERS = 160
ALLOWED_SUFFIXES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
}


class KnowledgeIntakeRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=MAX_CONTENT_CHARACTERS)
    source_url: Optional[AnyHttpUrl] = None
    institution: Optional[str] = Field(None, max_length=200)
    version: Optional[str] = Field(None, max_length=100)
    official_claim: bool = Field(
        False,
        description="仅保存提交者的官方性声明，不代表系统已核验",
    )

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("不允许包含控制字符")
        stripped = value.strip()
        if not stripped:
            raise ValueError("文件名不能为空")
        return stripped

    @field_validator("institution", "version")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("不允许包含控制字符")
        return value.strip() or None

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("资料内容不能为空")
        if "\x00" in value:
            raise ValueError("文本内容不能包含 NUL 字节")
        return value


class KnowledgeIntakeItem(BaseModel):
    id: str
    original_filename: str
    sanitized_filename: str
    stored_filename: str
    media_type: str
    source_url: Optional[str]
    institution: Optional[str]
    version: Optional[str]
    official_claim: bool
    official_claim_verified: bool = False
    official: bool = False
    verification_status: str = "pending_review"
    status: str = "pending_review"
    sha256: str
    content_characters: int
    content_bytes: int
    submitted_at: datetime
    indexed: bool = False
    eligible_for_index: bool = False
    storage_area: str = "kb_pending"
    review_notice: str


class KnowledgeIntakeListResponse(BaseModel):
    total: int
    status: str = "pending_review"
    indexed: bool = False
    notice: str
    items: list[KnowledgeIntakeItem]


def _sanitize_filename(filename: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", filename).replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1].strip()
    suffix = Path(basename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        supported = ", ".join(sorted(ALLOWED_SUFFIXES))
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"仅支持纯文本、Markdown 和 CSV 文件：{supported}",
        )

    stem = basename[: -len(Path(basename).suffix)]
    stem = re.sub(r"[^\w\-. ]+", "_", stem, flags=re.UNICODE)
    stem = re.sub(r"\s+", "_", stem)
    stem = re.sub(r"_+", "_", stem).strip("._-")
    if not stem:
        stem = "document"
    max_stem_length = MAX_FILENAME_CHARACTERS - len(suffix)
    sanitized = f"{stem[:max_stem_length]}{suffix}"
    return sanitized, ALLOWED_SUFFIXES[suffix]


def _normalize_content(content: str) -> str:
    return content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def _atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _pending_items() -> list[KnowledgeIntakeItem]:
    KB_PENDING_DIR.mkdir(parents=True, exist_ok=True)
    items: list[KnowledgeIntakeItem] = []
    for metadata_path in KB_PENDING_DIR.glob("*.json"):
        try:
            item = KnowledgeIntakeItem.model_validate_json(
                metadata_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue
        items.append(item)
    return sorted(items, key=lambda item: item.submitted_at, reverse=True)


@router.post("", response_model=KnowledgeIntakeItem, status_code=status.HTTP_202_ACCEPTED)
def submit_knowledge_intake(payload: KnowledgeIntakeRequest) -> KnowledgeIntakeItem:
    sanitized_filename, media_type = _sanitize_filename(payload.filename)
    normalized_content = _normalize_content(payload.content)
    encoded = normalized_content.encode("utf-8")
    if len(encoded) > MAX_CONTENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文本资料不得超过 {MAX_CONTENT_BYTES} 字节",
        )

    submitted_at = datetime.now(timezone.utc)
    intake_id = f"intake-{submitted_at:%Y%m%dT%H%M%S}-{uuid4().hex[:12]}"
    stored_filename = f"{intake_id}__{sanitized_filename}"
    digest = hashlib.sha256(encoded).hexdigest()
    notice = (
        "official_claim 仅是提交者声明，当前未核验；"
        "资料处于 pending_review，不会进入正式知识索引。"
    )
    item = KnowledgeIntakeItem(
        id=intake_id,
        original_filename=payload.filename,
        sanitized_filename=sanitized_filename,
        stored_filename=stored_filename,
        media_type=media_type,
        source_url=str(payload.source_url) if payload.source_url else None,
        institution=payload.institution,
        version=payload.version,
        official_claim=payload.official_claim,
        sha256=digest,
        content_characters=len(normalized_content),
        content_bytes=len(encoded),
        submitted_at=submitted_at,
        review_notice=notice,
    )

    KB_PENDING_DIR.mkdir(parents=True, exist_ok=True)
    content_path = KB_PENDING_DIR / stored_filename
    metadata_path = KB_PENDING_DIR / f"{intake_id}.json"
    try:
        _atomic_write_text(content_path, normalized_content)
        _atomic_write_text(
            metadata_path,
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False, indent=2),
        )
    except OSError as exc:
        if content_path.exists():
            content_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="待审核资料暂存失败",
        ) from exc
    return item


@router.get("", response_model=KnowledgeIntakeListResponse)
def list_knowledge_intake() -> KnowledgeIntakeListResponse:
    items = _pending_items()
    return KnowledgeIntakeListResponse(
        total=len(items),
        notice=(
            "仅列出待人工审核资料；列表中的官方性声明均未核验，"
            "且所有项目均未进入正式知识索引。"
        ),
        items=items,
    )
