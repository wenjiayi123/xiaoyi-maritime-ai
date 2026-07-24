import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import knowledge_intake as intake_module
from app.config import INDEX_PATH, KB_DIR
from app.main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_pending_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    pending = tmp_path / "kb_pending"
    monkeypatch.setattr(intake_module, "KB_PENDING_DIR", pending)
    return pending


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_intake_stores_untrusted_material_outside_search_index(
    isolated_pending_directory: Path,
) -> None:
    index_hash_before = _file_sha256(INDEX_PATH)
    indexed_files_before = {path.name for path in KB_DIR.glob("*.md")}
    content = "\ufeff# 待审核港口资料\r\n\r\nINTAKEONLYZXCVBNM 只存入待审核区。"

    response = client.post(
        "/api/knowledge/intake",
        json={
            "filename": "../../港口 待审核资料.MD",
            "content": content,
            "source_url": "https://example.org/reference/port-note",
            "institution": "提交方示例机构",
            "version": "draft-1",
            "official_claim": True,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    normalized = "# 待审核港口资料\n\nINTAKEONLYZXCVBNM 只存入待审核区。"
    assert payload["status"] == "pending_review"
    assert payload["verification_status"] == "pending_review"
    assert payload["sanitized_filename"] == "港口_待审核资料.md"
    assert "/" not in payload["sanitized_filename"]
    assert ".." not in payload["sanitized_filename"]
    assert payload["sha256"] == hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    assert payload["official_claim"] is True
    assert payload["official_claim_verified"] is False
    assert payload["official"] is False
    assert payload["indexed"] is False
    assert payload["eligible_for_index"] is False
    assert "未核验" in payload["review_notice"]
    assert "不会进入正式知识索引" in payload["review_notice"]

    stored = isolated_pending_directory / payload["stored_filename"]
    metadata = isolated_pending_directory / f"{payload['id']}.json"
    assert stored.read_text(encoding="utf-8") == normalized
    assert metadata.exists()
    assert stored.parent == isolated_pending_directory
    assert _file_sha256(INDEX_PATH) == index_hash_before
    assert {path.name for path in KB_DIR.glob("*.md")} == indexed_files_before

    search = client.post(
        "/api/knowledge/search",
        json={"query": "INTAKEONLYZXCVBNM", "top_k": 5},
    )
    assert search.status_code == 200
    assert search.json()["result_count"] == 0
    assert search.json()["grounded"] is False


def test_intake_list_returns_pending_metadata_without_document_body(
    isolated_pending_directory: Path,
) -> None:
    created = client.post(
        "/api/knowledge/intake",
        json={
            "filename": "berth_notes.csv",
            "content": "berth,status\n3,planned\n",
            "official_claim": False,
        },
    )
    assert created.status_code == 202

    response = client.get("/api/knowledge/intake")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["status"] == "pending_review"
    assert payload["indexed"] is False
    assert "未进入正式知识索引" in payload["notice"]
    assert payload["items"][0]["id"] == created.json()["id"]
    assert payload["items"][0]["media_type"] == "text/csv"
    assert "content" not in payload["items"][0]
    assert len(list(isolated_pending_directory.glob("*.json"))) == 1


def test_intake_rejects_unsupported_or_oversized_documents() -> None:
    unsupported = client.post(
        "/api/knowledge/intake",
        json={"filename": "unsafe.pdf", "content": "not accepted"},
    )
    assert unsupported.status_code == 415

    oversized = client.post(
        "/api/knowledge/intake",
        json={
            "filename": "too-large.txt",
            "content": "x" * (intake_module.MAX_CONTENT_CHARACTERS + 1),
        },
    )
    assert oversized.status_code == 422


def test_intake_exposes_no_auto_publish_or_official_verification_route() -> None:
    paths = app.openapi()["paths"]
    assert "/api/knowledge/intake" in paths
    assert not any(
        path.startswith("/api/knowledge/intake/")
        and any(word in path for word in ("publish", "approve", "official", "verify"))
        for path in paths
    )
