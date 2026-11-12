"""Create or restore an application SQLite snapshot against a pinned model catalogue."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile


def sha(path):
    with path.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest()


def validate(connection):
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("SQLite integrity check failed")
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    if not {"runtime_artifacts", "audit_events", "chat_turns"}.issubset(tables):
        raise ValueError("Database lacks the expected application tables")


def create(database, target, registry):
    created = False
    # An exclusive directory also prevents concurrent publishers from mixing files.
    target.mkdir(mode=0o700)
    try:
        with closing(sqlite3.connect(database.resolve(strict=True).as_uri()+"?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(target/"business.db")) as dest:
                src.backup(dest)
                validate(dest)
        summary = {"schema":1,"created_utc":datetime.now(timezone.utc).isoformat(),
                   "database_sha256":sha(target/"business.db"),"registry_sha256":sha(registry),
                   "scope":"application SQLite database; weights, external artifacts and credentials are provisioned separately"}
        pending=target/"manifest.pending"
        pending.write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
        pending.replace(target/"manifest.json")
        created=True
        return summary
    finally:
        if not created:
            for name in ("manifest.pending","business.db-journal","business.db-wal","business.db-shm","business.db"):
                (target/name).unlink(missing_ok=True)
            target.rmdir()


def restore(snapshot, database, registry):
    manifest=json.loads((snapshot/"manifest.json").read_text(encoding="utf-8"))
    if manifest["schema"]!=1 or sha(registry)!=manifest["registry_sha256"]:
        raise ValueError("Model catalogue differs from the snapshot")
    if database.exists() or any(Path(str(database)+s).exists() for s in ("-wal","-shm","-journal")):
        raise FileExistsError("Restore requires an unused database path")
    with tempfile.TemporaryDirectory(prefix="restore-",dir=database.parent) as work:
        copy=Path(work)/"business.db"
        shutil.copyfile(snapshot/"business.db",copy)
        if sha(copy)!=manifest["database_sha256"]:
            raise ValueError("Database snapshot digest mismatch")
        with closing(sqlite3.connect(copy.as_uri()+"?immutable=1&mode=ro",uri=True)) as con:
            validate(con)
        # Publish without overwriting a concurrently created database.
        os.link(copy,database)
    return manifest


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("create","restore"))
    parser.add_argument("--database",required=True,type=Path)
    parser.add_argument("--snapshot",required=True,type=Path)
    parser.add_argument("--registry",required=True,type=Path)
    args=parser.parse_args()
    if args.mode=="create":
        result=create(args.database,args.snapshot,args.registry)
    else:
        result=restore(args.snapshot,args.database.resolve(),args.registry)
    print(json.dumps(result))
