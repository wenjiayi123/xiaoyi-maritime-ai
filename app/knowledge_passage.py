"""Resolve the exact version of a passage referenced by a search result."""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from fastapi import HTTPException
from app.config import KB_DIR, SOURCE_REGISTRY_PATH
from app.provenance import load_source_registry
from app.retrieval import _split_markdown, get_shared_knowledge_base


def reference(chunk):
    payload=[chunk.id,chunk.content_hash,chunk.document_hash,asdict(chunk.provenance)]
    return sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def reprints(chunk):
    from app.knowledge_reprints import COPIES
    offered=COPIES.get(chunk.source)
    if offered and chunk.document_hash==offered["document"] and chunk.provenance.version==offered["version"]:
        return [offered["publisher"]]
    return []


def resolve(chunk_id,citation):
    chunk=next((c for c in get_shared_knowledge_base().chunks if c.id==chunk_id),None)
    if chunk is None:
        raise HTTPException(404,"未找到登记片段 / Passage not found")
    path=(KB_DIR/chunk.source).resolve()
    if path.parent!=KB_DIR.resolve() or not path.is_file():
        raise HTTPException(409,"来源文件已变更 / Source changed")
    raw=path.read_bytes()
    provenance=load_source_registry(SOURCE_REGISTRY_PATH).get(chunk.source)
    if (reference(chunk)!=citation or sha256(raw).hexdigest()!=chunk.document_hash or
        asdict(provenance)!=asdict(chunk.provenance)):
        raise HTTPException(409,"所引版本已变更，请重新检索 / Citation changed. Search again.")
    actual=next((c for c in _split_markdown(path,raw,provenance) if c.id==chunk_id),None)
    if actual is None or reference(actual)!=citation or actual.text!=chunk.text:
        raise HTTPException(409,"所引片段已变更 / Passage changed")
    return {"id":chunk.id,"source":chunk.source,"title":chunk.title,"body":chunk.text,"citation":citation,
            "source_url":provenance.source_url,"version":provenance.version,"institution":provenance.institution,
            "content_scope":provenance.content_scope,"effective_from":provenance.effective_from,"effective_to":provenance.effective_to,
            "document_sha256":chunk.document_hash,"passage_sha256":chunk.content_hash,"reprints":reprints(chunk)}
