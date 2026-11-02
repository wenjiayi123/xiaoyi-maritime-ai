"""Additional real-state branch probe; all setup and recovery receipts retained."""
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".codex_artifacts/harness-v13-20261101/paused-clock-setup"


def api(path, payload=None):
    request = Request("http://127.0.0.1:18018/api/linked-agent" + path,
        data=json.dumps(payload).encode() if payload is not None else None, headers={"Content-Type":"application/json"})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))


def main():
    OUT.mkdir(exist_ok=False)
    plan = api("/plans", {"action_id":"malacca.clock", "parameters":{"action":"stop"},
        "samples":1,"restore_after_observation":False})
    save("plan.json", plan)
    run = api("/plans/" + plan["id"] + "/execute", {"plan_sha256":plan["plan_sha256"],"request_id":"v13-"+uuid4().hex})
    while run["status"] == "running":
        time.sleep(.5)
        run = api("/runs/" + run["id"])
    save("setup-receipt.json",run)
    if run["status"] != "completed":
        raise RuntimeError("setup failed; inspect persisted receipt before any retry")
    try:
        subprocess.run([sys.executable,str(ROOT / "scripts/accept_harness_v13.py"),"--base","http://127.0.0.1:18018",
            "--case","conditional_clock","--round","paused-branch"],check=True,cwd=ROOT)
    finally:
        restored = api("/runs/" + run["id"] + "/rollback", {})
        save("restore-receipt.json",restored)
        after = api("/plans", {"action_id":"malacca.observe"})["before"]
        save("readback.json",after)
        assert restored["restored"] and after["config"] == plan["before"]["config"]


if __name__ == "__main__":
    main()
