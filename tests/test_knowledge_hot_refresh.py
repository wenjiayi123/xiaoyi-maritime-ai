import json

from app import retrieval


def _write_registry(path, sources: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "registry_version": "test",
                "expected_document_count": len(sources),
                "defaults": {
                    "provenance_type": "internal_curated",
                    "institution": "test",
                    "official": False,
                    "verification_status": "not_independently_verified",
                    "source_quality": "internal_curated",
                },
                "documents": {source: {} for source in sources},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_shared_knowledge_base_refreshes_when_document_inventory_changes(
    tmp_path,
    monkeypatch,
) -> None:
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    index_path = tmp_path / "index.json"
    registry_path = tmp_path / "source_registry.json"
    (kb_dir / "one.md").write_text("# 第一份\n\n港口知识一。", encoding="utf-8")
    _write_registry(registry_path, ["one.md"])

    monkeypatch.setattr(retrieval, "KB_DIR", kb_dir)
    monkeypatch.setattr(retrieval, "INDEX_PATH", index_path)
    monkeypatch.setattr(retrieval, "SOURCE_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(retrieval, "_SHARED_KNOWLEDGE_BASE", None)
    monkeypatch.setattr(retrieval, "_SHARED_KNOWLEDGE_SIGNATURE", None)

    first = retrieval.get_shared_knowledge_base()
    assert {chunk.source for chunk in first.chunks} == {"one.md"}

    (kb_dir / "two.md").write_text("# 第二份\n\n港航知识二。", encoding="utf-8")
    _write_registry(registry_path, ["one.md", "two.md"])
    second = retrieval.get_shared_knowledge_base()

    assert second is not first
    assert {chunk.source for chunk in second.chunks} == {"one.md", "two.md"}
