"""Verify archived research receipts after relocating the project to another drive."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path, PurePosixPath

RELEASE="agent-rl-expert-expansion-20261102"
ROOT=Path(__file__).resolve().parents[2]/".codex_artifacts"/RELEASE
LOCKS={"tasks-002/DATA_LOCK.json":"25d74eb68f8abc8bbfb8043dd21dc8b3bcb100b4ef8fb921b492b1385cf66a5f",
       "continuation-002/tasks-003/DATA_LOCK.json":"7aff1c35ee06273830d1db5cd46bd1f3669a17afb4267bf40f51b5d04340faa6"}


def relative_name(path):
    parts=PurePosixPath(str(path).replace("\\","/")).parts
    hits=[i for i in range(len(parts)-1) if parts[i:i+2]==(".codex_artifacts",RELEASE)]
    if len(hits)!=1 or ".." in parts:raise ValueError("Unregistered archive path")
    rest=parts[hits[0]+2:]
    if not rest or any(":" in item for item in rest):raise ValueError("Invalid archive entry")
    return "/".join(rest)


@lru_cache(maxsize=2)
def index_from_bytes(contents):
    entries={}
    for raw in contents:
        for old,sha in json.loads(raw)["files"].items():
            if not str(old).replace("\\","/").endswith("/energy-journal.json"):
                continue
            name=relative_name(old)
            if name in entries and entries[name]!=sha:raise ValueError("Conflicting receipt identities")
            entries[name]=sha
    return entries


def read_receipt(path):
    raw_locks=[]
    for name,expected in LOCKS.items():
        content=(ROOT/name).read_bytes()
        if hashlib.sha256(content).hexdigest()!=expected:raise ValueError("Research manifest hash changed")
        raw_locks.append(content)
    rel=relative_name(path)
    if not rel.endswith("/energy-journal.json"):raise ValueError("Expected a registered energy journal")
    expected=index_from_bytes(tuple(raw_locks)).get(rel)
    if expected is None:raise ValueError("Journal is absent from the frozen releases")
    local=(ROOT/rel).resolve()
    if not local.is_relative_to(ROOT.resolve()):raise ValueError("Journal escaped its archive")
    raw=local.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError("Registered receipt file has changed")
    return json.loads(raw)["receipt"]
