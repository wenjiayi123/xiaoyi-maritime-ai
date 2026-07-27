from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_knowledge_status_reports_real_inventory() -> None:
    response = client.get("/api/knowledge/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["document_count"] == 129
    assert payload["chunk_count"] == 882
    assert payload["official_verified_documents"] == 68
    assert payload["official_full_text_documents"] == 0
    assert payload["official_summary_documents"] > 0
    assert payload["official_locator_documents"] > 0
    assert payload["internal_curated_documents"] == 61
    assert payload["completeness_claim"] == "partial_auditable_coverage"
    assert len(payload["index_sha256"]) == 64
    assert payload["strict_evidence_default"] is True


def test_official_search_returns_auditable_source() -> None:
    response = client.post(
        "/api/knowledge/search",
        json={"query": "IMO 海事单一窗口 2024", "official_only": True, "top_k": 8},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["grounded"] is True
    assert payload["official_result_count"] >= 1
    hit = payload["hits"][0]
    assert hit["official"] is True
    assert hit["source_quality"] == "official_verified"
    assert hit["source_url"].startswith("https://www.imo.org/")
    assert len(hit["document_checksum_sha256"]) == 64
    assert len(hit["chunk_checksum_sha256"]) == 64


def test_source_catalog_separates_official_and_internal_material() -> None:
    all_sources = client.get("/api/knowledge/sources")
    official = client.get("/api/knowledge/sources", params={"official_only": True})
    assert all_sources.status_code == 200
    assert official.status_code == 200
    assert len(all_sources.json()) == 129
    assert len(official.json()) == 68
    assert all(item["official"] for item in official.json())
    assert all(item["content_scope"] for item in official.json())
    assert all(item["jurisdictions"] for item in official.json())


def test_authority_coverage_exposes_known_gaps_and_license_isolation() -> None:
    response = client.get("/api/knowledge/authority-coverage")
    assert response.status_code == 200
    payload = response.json()
    assert payload["completeness_claim"] == "partial_auditable_coverage"
    entries = [item for section in payload["sections"] for item in section["entries"]]
    assert len(entries) == 41
    assert any(item["status"] == "planned" for item in entries)
    assert any(item["status"] == "license_isolated" for item in entries)
