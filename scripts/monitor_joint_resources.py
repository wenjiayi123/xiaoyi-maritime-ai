"""Bounded local resource sampling while actual demos run. No network export."""

import json
import time
import subprocess
import urllib.request
from pathlib import Path

root = Path(".codex_artifacts/joint-harness-phase2-20261029")
path = root / "resource-samples.ndjson"
stop = root / "stop-resource-monitor"
start = time.monotonic()
with path.open("a") as f:
    while time.monotonic() - start < 3600 and not stop.exists():
        stamp = time.time()
        timing = {}
        for service, url in [
            ("xiaoyi", "http://127.0.0.1:8010/api/harness/joint/capabilities"),
            ("policy", "http://127.0.0.1:11839/health"),
        ]:
            t = time.monotonic()
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    response.read()
                    timing[service] = {"ok": True, "seconds": time.monotonic() - t}
            except Exception as exc:
                timing[service] = {"ok": False, "error": str(exc)[:120]}
        ps = subprocess.check_output(["ps", "-axo", "pid=,rss=,pcpu=,command="], text=True)
        rows = [
            line.strip()
            for line in ps.splitlines()
            if any(
                s in line
                for s in ["uvicorn app.main", "Virtualization.VirtualMachine", "Godot --headless", "llama-server"]
            )
        ]
        f.write(
            json.dumps(
                {"epoch": stamp, "elapsed_seconds": time.monotonic() - start, "health": timing, "processes": rows}
            )
            + "\n"
        )
        f.flush()
        time.sleep(10)
