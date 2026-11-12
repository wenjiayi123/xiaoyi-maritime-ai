import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app import file_lease as lease
from app.agent_training import registered_receipts as archive


def test_real_processes_share_exclusive_lease_and_preserve_payload(tmp_path):
    path=tmp_path/"训练.lock"
    path.write_bytes(b"receipt")
    root=Path(__file__).resolve().parents[1]
    child=("from app import file_lease as l\nfrom pathlib import Path\nimport sys\n"
           "with Path(sys.argv[1]).open('r+b') as f:\n"
           " try: l.flock(f,l.LOCK_EX|l.LOCK_NB)\n except BlockingIOError: print('busy')\n"
           " else: print('acquired');l.flock(f,l.LOCK_UN)\n")
    def attempt():
        return subprocess.run([sys.executable,"-X","utf8","-c",child,str(path)],cwd=root,check=True,
                              capture_output=True,text=True,timeout=12).stdout.strip()
    with path.open("r+b") as owner:
        owner.seek(2)
        lease.flock(owner,lease.LOCK_EX|lease.LOCK_NB)
        assert owner.tell()==2 and attempt()=="busy"
        lease.flock(owner,lease.LOCK_UN)
        assert owner.tell()==2 and attempt()=="acquired"
    assert path.read_bytes()==b"receipt"


def test_relocated_journal_still_requires_the_original_content_sha(tmp_path,monkeypatch):
    old=archive.ROOT
    for name in archive.LOCKS:
        dest=tmp_path/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(old/name,dest)
    data=json.loads((old/next(iter(archive.LOCKS))).read_bytes())
    entry=next(name for name in data["files"] if name.endswith("/energy-journal.json"))
    rel=archive.relative_name(entry)
    target=tmp_path/rel;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(old/rel,target);monkeypatch.setattr(archive,"ROOT",tmp_path)
    assert archive.read_receipt(entry)["production_authority"] is False
    target.write_bytes(target.read_bytes()+b" ")
    with pytest.raises(ValueError,match="changed"):archive.read_receipt(entry)
    with pytest.raises(ValueError):archive.read_receipt(entry.replace("corpus-001","../corpus-001"))
