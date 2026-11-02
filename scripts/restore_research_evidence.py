"""Restore hash-pinned research reports/policies without overwriting local state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def restore(root=ROOT):
    root = root.resolve()
    folder = root / "reports/research-snapshots"
    manifest = json.loads((folder / "manifest.json").read_text())
    archive = folder / "registry-evidence-20261102.zip"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("frozen research archive hash mismatch")
    entries = manifest["files"]
    paths = [row["path"] for row in entries]
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate evidence path")
    pending = []
    with ZipFile(archive) as source:
        if sorted(source.namelist()) != sorted(paths):
            raise ValueError("archive/manifest file-set mismatch")
        for row in entries:
            relative = Path(row["path"])
            target = (root / relative).resolve()
            if (relative.parts[0] not in {".runtime", ".codex_artifacts"}
                    or relative.suffix not in {".json", ".npz"}
                    or not target.is_relative_to(root)):
                raise ValueError("unexpected research path")
            payload = source.read(row["path"])
            if len(payload) != row["bytes"] or hashlib.sha256(payload).hexdigest() != row["sha256"]:
                raise ValueError("research evidence mismatch: " + row["path"])
            if target.exists():
                if target.read_bytes() != payload:
                    raise ValueError("existing local evidence differs; refusing overwrite: " + row["path"])
            else:
                pending.append((target, payload))
        # Validate the complete archive and all existing files before writing.
        for target, payload in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(payload)
    return {"verified": len(entries), "restored": len(pending), "existing_files_overwritten": 0}


if __name__ == "__main__":
    print(json.dumps(restore(), ensure_ascii=False))
