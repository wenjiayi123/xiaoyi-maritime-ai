"""Resolve chart evidence to the sealed evaluation windows and the original CarbonOps dataset package."""
import csv
from functools import lru_cache
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
from statistics import fmean
from app.policy_release import ReleaseUnavailable

SOURCE_DIR = Path(__file__).resolve().parents[1] / "data/policy-figure-sources"
MANIFEST_SHA = "8762a4e274708f1be1e8d78f2eff417b0ee0c28c4c791fd733713b02f6f9a5b8"


def _digest(data):
    return hashlib.sha256(data).hexdigest()


@lru_cache(maxsize=4)
def _unpack(packed, packed_sha, raw_sha, size):
    if _digest(packed) != packed_sha:
        raise ReleaseUnavailable("图表来源包与登记版本不一致")
    raw = gzip.decompress(packed)
    if len(raw) != size or _digest(raw) != raw_sha:
        raise ReleaseUnavailable("图表来源文件校验失败")
    return raw


def _source(name, manifest):
    identity = manifest["files"][name]
    return _unpack((SOURCE_DIR/(name+".gz")).read_bytes(),identity["gzip_sha256"],identity["sha256"],identity["size"])


@lru_cache(maxsize=1)
def _test_rows(csv_bytes, metadata, expected):
    if _digest(csv_bytes+b"\0"+metadata) != expected:
        raise ReleaseUnavailable("历史输入数据与元数据的组合哈希不匹配")
    table = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig"),newline=""))
    return tuple((r["period"],r["timestamp_utc"],r["source_id"]) for r in table if r["split"]=="test")


@lru_cache(maxsize=2)
def _report(raw):
    return json.loads(raw)


def source_evidence(scene, figure, window):
    if scene not in ("evaluate","stress") or (window is not None and (type(window) is not int or not 0<=window<12)):
        raise ValueError("场景或窗口超出登记范围")
    manifest_bytes=(SOURCE_DIR/"manifest.json").read_bytes()
    if _digest(manifest_bytes)!=MANIFEST_SHA:
        raise ReleaseUnavailable("图表来源清单校验失败")
    manifest=json.loads(manifest_bytes)
    name=scene+".json"
    if manifest["files"][name]["sha256"]!=figure["source_file_sha256"] or manifest["package_sha256"]!=figure["dataset_sha256"]:
        raise ReleaseUnavailable("图表引用了不同的试验来源")
    report=_report(_source(name,manifest))
    dataset=_test_rows(_source("dataset.csv",manifest),_source("dataset.metadata.json",manifest),figure["dataset_sha256"])
    starts=report["starts"]
    if (report["split"]!="test" or report["dataset_sha256"]!=figure["dataset_sha256"] or len(starts)!=12
            or len(set(starts))!=12 or any(type(i) is not int or i<0 or i+24>len(dataset) for i in starts)):
        raise ReleaseUnavailable("留出窗口未绑定历史数据")
    metric=figure["metric"]
    means={}
    selected={}
    for policy,printed in figure["values"].items():
        summary=report["policies"][policy]
        rows=summary["rows"]
        if [r["start"] for r in rows]!=starts or any(len(r["trace"])!=24 or r["period"]!=dataset[r["start"]][0] for r in rows):
            raise ReleaseUnavailable("图中策略未在相同的十二个窗口比较")
        values=[r["metrics"][metric] for r in rows]
        mean=summary["mean"][metric]
        if (not all(type(v) in (int,float) and math.isfinite(v) for v in values)
                or mean!=printed or not math.isclose(fmean(values),mean,abs_tol=1e-9,rel_tol=1e-12)):
            raise ReleaseUnavailable("图表指标与逐窗口数值不一致")
        means[policy]=mean
        if window is not None:
            selected[policy]=values[window]
    evidence={"means":means,"window_count":len(starts),"steps_per_window":24,"metric":metric,"scope":"historical_simulation",
              "source_file_sha256":figure["source_file_sha256"],"dataset_package_sha256":figure["dataset_sha256"],
              "csv_sha256":manifest["files"]["dataset.csv"]["sha256"],"metadata_sha256":manifest["files"]["dataset.metadata.json"]["sha256"],
              "load_multiplier":report["load_multiplier"],"production_authority":False}
    if window is not None:
        start=starts[window]
        span=dataset[start:start+24]
        evidence["selected_window"]={"index":window,"start_row":start,"period":span[0][0],"first_hour":span[0][1],"last_hour":span[-1][1],
                                     "source_row_ids":[r[2] for r in span],"values":selected}
    return evidence
