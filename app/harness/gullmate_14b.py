from functools import lru_cache
from hashlib import file_digest,sha256
import json,os
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError,URLError
from urllib.request import build_opener,ProxyHandler
from app.config import BASE_DIR
from app.gullmate_catalog_pin import CATALOG_SHA
from app.model_gateway import model_gateway

DEPLOY=BASE_DIR.parent.parent
STATIC=BASE_DIR/"web/14b-evaluations"
CATALOG=BASE_DIR/"data/14b-evaluations/catalog.json"
_hash_lock=Lock()

def signature(path):
    s=path.stat()
    return (s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_dev,s.st_ino)

@lru_cache(maxsize=80)
def checksum(path,identity):
    with path.open("rb") as source:value=file_digest(source,"sha256").hexdigest()
    if identity!=signature(path):raise OSError("file changed during verification")
    return value

def matches(path,digest):
    try:
        with _hash_lock:return checksum(path,signature(path))==digest
    except OSError:return False

def request_json(route):
    # Only the local managed inference port is queried, independent of browser input or configured proxies.
    with build_opener(ProxyHandler({})).open("http://127.0.0.1:11435"+route,timeout=4) as r:
        raw=r.read(1_000_001)
    if len(raw)>1_000_000:raise ValueError("unexpected inference response size")
    return json.loads(raw)

def runtime(selected,cfg,gateway,files_ok):
    state={"state":"unverified","observed":None,"weight_sha":None,"adapter_sha":None,"n_ctx":None}
    try:
        listing=request_json("/v1/models")["data"]
        if len(listing)!=1:return state
        model=listing[0];state.update(observed=model["id"],n_ctx=model.get("meta",{}).get("n_ctx"))
        props=request_json("/props");adapters=request_json("/lora-adapters")
        correct_adapters=(adapters==[]) if cfg is not None and cfg["adapter"] is None else False
        if cfg and cfg["adapter"] and isinstance(adapters,list) and len(adapters)==1:
            a=adapters[0];correct_adapters=(Path(a.get("path","")).resolve()==Path(cfg["adapter"]).resolve()
                and type(a.get("scale")) in (float,int) and a["scale"]==1)
        if (cfg and files_ok and cfg["alias"]==state["observed"]==gateway and state["n_ctx"]==cfg["ctx"]
            and Path(props["model_path"]).resolve()==Path(cfg["base"]).resolve() and correct_adapters
            and request_json("/health").get("status")=="ok"):
            state.update(state="verified",weight_sha=cfg["base_sha"],adapter_sha=cfg["adapter_sha"])
    except HTTPError:
        state["state"]="unverified" if state["observed"] else "unavailable"
    except (OSError,URLError) as exc:
        why=getattr(exc,"reason",exc)
        refused=isinstance(why,ConnectionRefusedError) or getattr(why,"errno",None) in (61,111,10061)
        state["state"]="offline" if refused and state["observed"] is None else "unavailable"
    except (KeyError,IndexError,ValueError,TypeError,AttributeError):pass
    return state

def inventory():
    raw=CATALOG.read_bytes()
    if sha256(raw).hexdigest()!=CATALOG_SHA:raise ValueError("模型登记册哈希不符")
    registry=json.loads(raw);profiles=registry["profiles"]
    registered=matches(DEPLOY/"generation_profiles.py",registry["manager_sha"])
    try:
        selection=json.loads((DEPLOY/"state/generation-profile.json").read_bytes())
        selected=selection["profile"]
        cfg=profiles.get(selected);registered=bool(registered and cfg and cfg["alias"]==selection["alias"] and cfg["base_sha"]==selection["sha256"])
    except FileNotFoundError:
        selected="4b" if registered else None;cfg=profiles.get(selected)
    except (OSError,ValueError,KeyError,TypeError):
        selected=None;cfg=None;registered=False
    items=[];verified={}
    for entry in registry["items"]:
        ok=matches(Path(entry["path"]),entry["sha256"]);verified[entry["sha256"]]=ok
        report=entry["report"]
        items.append({**{k:v for k,v in entry.items() if k!="path"},"verified":ok,
                      "report_url":"/web/14b-evaluations/"+report+".txt" if matches(STATIC/(report+".txt"),report) else None})
    files_ok=False
    if cfg and registered:
        files_ok=verified[cfg["base_sha"]] if cfg["base_sha"] in verified else matches(Path(cfg["base"]),cfg["base_sha"])
        if cfg["adapter"]:files_ok=files_ok and verified.get(cfg["adapter_sha"],False)
    gateway=model_gateway.status()["model"]
    if os.name=="nt" and (DEPLOY/"generation_profiles.py").is_file():
        live=runtime(selected,cfg,gateway,files_ok)
    else:
        live={"state":"not_configured" if model_gateway.status()["provider"]=="local_rules" else "unverified",
              "observed":None,"weight_sha":None,"adapter_sha":None,"n_ctx":None}
    return {"selected":selected,"selection_verified":registered,"selected_alias":cfg["alias"] if cfg else None,
            "selected_layers":cfg["gpu_layers"] if cfg else None,"gateway":gateway,"live":live,"items":items,
            "schema":"gullmate.14b.inventory.v1","production_authority":False}
