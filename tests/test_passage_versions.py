from dataclasses import replace
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app import knowledge_passage as service
from app.provenance import SourceProvenance
from app.retrieval import _split_markdown
from app.maritime_terms import indexed_query
from app.knowledge_policy import detect_jurisdictions


def test_citation_refuses_missing_modified_and_re_registered_source(tmp_path,monkeypatch):
    href="https://example.org/port"
    file=tmp_path/"berth.md";file.write_text("# Berth\n\n## Operating note\nDraft in metres.",encoding="utf-8")
    source=SourceProvenance(source_id=file.name,display_name="Berth note",version="1",source_url=href)
    chunk,=_split_markdown(file,file.read_bytes(),source)
    index=SimpleNamespace(chunks=[chunk])
    monkeypatch.setattr(service,"get_shared_knowledge_base",lambda:index)
    monkeypatch.setattr(service,"KB_DIR",tmp_path)
    metadata={file.name:source}
    monkeypatch.setattr(service,"load_source_registry",lambda _:metadata)
    key=service.reference(chunk)
    assert service.resolve(chunk.id,key)["body"]==chunk.text
    for name,pin,expected in [(chunk.id,"0"*64,409),("unregistered:999",key,404)]:
        with pytest.raises(HTTPException) as err:service.resolve(name,pin)
        assert err.value.status_code==expected
    metadata[file.name]=replace(source,version="2")
    with pytest.raises(HTTPException) as err:service.resolve(chunk.id,key)
    assert err.value.status_code==409
    metadata[file.name]=source
    file.write_text("Changed locally",encoding="utf-8")
    with pytest.raises(HTTPException) as err:service.resolve(chunk.id,key)
    assert err.value.status_code==409
    file.unlink()
    with pytest.raises(HTTPException) as err:service.resolve(chunk.id,key)
    assert err.value.status_code==409


def test_query_bridge_preserves_untranslated_constraints_and_word_boundaries():
    translated=indexed_query("Do collision avoidance rules exclude AB-CX990/23 at 12 knots?")
    assert "COLREG" in translated and all(item in translated for item in ("exclude","AB-CX990/23","12","knots"))
    assert indexed_query("Portland permit AB-CX990")== "Portland permit AB-CX990"
    assert "CN" in detect_jurisdictions("Chinese port pollution law") and "CN" not in detect_jurisdictions("Indochina port rules")
