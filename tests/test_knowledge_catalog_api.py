from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import knowledge_api
from app.main import app


client = TestClient(app)


def test_professional_catalog_exposes_governed_coverage_roadmap() -> None:
    response = client.get("/api/knowledge/catalog")

    assert response.status_code == 200
    payload = response.json()
    assert payload["category_count"] == 24
    assert payload["topic_count"] == 96
    assert len(payload["categories"]) == 24
    assert sum(len(item["topics"]) for item in payload["categories"]) == 96
    assert "覆盖路线图" in payload["roadmap_notice"]
    assert "不代表" in payload["roadmap_notice"]
    assert set(payload["coverage_summary"]["topics"]) == {
        "indexed",
        "partial",
        "planned",
    }
    assert {
        topic["coverage_status"]
        for category in payload["categories"]
        for topic in category["topics"]
    } <= {"indexed", "partial", "planned"}
    assert all(
        category["recommended_material_families"]
        for category in payload["categories"]
    )


def test_professional_catalog_missing_file_fails_without_leaking_path(
    monkeypatch, tmp_path: Path
) -> None:
    missing = tmp_path / "missing-catalog.json"
    monkeypatch.setattr(knowledge_api, "KNOWLEDGE_CATALOG_PATH", missing)

    response = client.get("/api/knowledge/catalog")

    assert response.status_code == 503
    assert response.json()["detail"] == "港航专业目录暂不可用：目录文件尚未部署。"
    assert str(missing) not in response.text


def test_professional_catalog_invalid_payload_fails_closed(
    monkeypatch, tmp_path: Path
) -> None:
    invalid = tmp_path / "knowledge-catalog.json"
    invalid.write_text('{"category_count": 24, "categories": []}', encoding="utf-8")
    monkeypatch.setattr(knowledge_api, "KNOWLEDGE_CATALOG_PATH", invalid)

    response = client.get("/api/knowledge/catalog")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "港航专业目录暂不可用：目录数据未通过完整性校验。"
    )
    assert "validation" not in response.text.lower()
