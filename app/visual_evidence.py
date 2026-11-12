"""Search registered figure captions and OCR, then follow edges to the underlying metrics."""
import hashlib
import json
import re
from pathlib import Path

from app.config import WEB_DIR
from app.figure_sources import source_evidence
from app.policy_release import ReleaseUnavailable

CATALOG_SHA256="fbab0acdf67d48e3d096a3eab70f7c2d805401f5c7aa37090f0827b961275133"


def checked(path: Path, expected: str) -> bytes:
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=expected:
        raise ReleaseUnavailable("图表与登记版本不一致")
    return data


def terms(text):
    tokens=set(re.findall(r"[a-z0-9]+",text.lower()))
    for block in re.findall(r"[\u4e00-\u9fff]+",text):
        tokens.update(block[i:i+2] for i in range(len(block)-1))
    return tokens


def search_figures(query: str, window: int | None = None) -> dict:
    folder=WEB_DIR/"policy-evidence"
    catalog=json.loads(checked(folder/"figures.json",CATALOG_SHA256))
    requested=terms(query)
    metrics = set()
    if re.search(r"延误|延迟分钟|\bdelay\b",query,re.I):metrics.add("delay_minutes")
    if re.search(r"成本|费用|\bcost\b",query,re.I):metrics.add("cost")
    hits=[]
    for key,figure in catalog.items():
        if metrics and figure["metric"] not in metrics:
            continue
        ocr=json.loads(checked(folder/(key+".ocr.json"),figure["ocr_sha256"]))
        checked(folder/(key+".png"),figure["asset_sha256"])
        if ocr["image_sha256"]!=figure["asset_sha256"]:
            raise ReleaseUnavailable("OCR 未绑定此次图像")
        caption=terms(figure["title"]+" "+figure["caption_zh"])
        lines=[line for line in ocr["lines"] if requested.intersection(terms(line["text"]))]
        score=len(caption.intersection(requested))*3+sum(len(requested.intersection(terms(line["text"]))) for line in lines)
        if not score:continue
        verified=source_evidence(key, figure, window)
        figure_id="sha256:"+figure["asset_sha256"]
        source_id="sha256:"+figure["source_file_sha256"]
        data_id="sha256:"+figure["dataset_sha256"]
        hits.append({"score":score,"id":key,"title":figure["title"],"caption":figure["caption_zh"],"url":figure["url"],
                     "matched_ocr_lines":lines,"figure_sha256":figure["asset_sha256"],
                     "source_metric":figure["metric"],"values_from_source":verified["means"],"source_evidence":verified,
                     "edges":[{"from":"sha256:"+figure["ocr_sha256"],"relation":"read_pixels_of","to":figure_id},
                              {"from":figure_id,"relation":"rendered_from","to":source_id},
                              {"from":source_id,"relation":"evaluates_dataset","to":data_id}]})
    hits.sort(key=lambda h:(-h["score"],h["id"]))
    return {"query":query,"scope":"registered policy figures","hits":hits,"production_authority":False}


def figure_summary(result):
    """Render scoped measurements ahead of OCR coordinates and lineage hashes."""
    selected = []
    for hit in result["hits"]:
        source = hit["source_evidence"]
        window = source.get("selected_window")
        values = window["values"] if window else source["means"]
        selected.append({"figure":hit["id"],"metric":source["metric"],
                         "period":window["period"] if window else "12 paired windows",
                         "scope":"selected window" if window else "mean",
                         "values":values,"display":{k:format(v,".2f") for k,v in values.items()},
                         "source_sha256":source["source_file_sha256"]})
    return json.dumps(selected,ensure_ascii=False,separators=(",",":"))
