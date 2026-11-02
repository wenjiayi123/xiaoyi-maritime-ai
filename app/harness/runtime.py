"""Identify loaded code separately from files that may have changed on disk."""
from pathlib import Path
import hashlib
import os

ROOT = Path(__file__).resolve().parents[2]
RELEASE = "harness-v13-20261101"


def fingerprint():
    paths = sorted((ROOT / "app/harness").glob("*.py")) + [ROOT / name for name in
        ["app/main.py", "app/linked_agent.py", "app/linked_agent_catalog.py", "app/sailing_simulator_launcher.py",
         "web/app.js", "web/harness_chat.js", "web/index.html"]]
    paths += [ROOT / name for name in ["web/harness.js", "web/harness_chat.css", "web/linked_agent.js", "scripts/start_harness.py"]]
    h = hashlib.sha256()
    for path in paths:
        h.update(str(path.relative_to(ROOT)).encode())
        h.update(path.read_bytes() if path.exists() else b"missing")
    return h.hexdigest()


LOADED = fingerprint()


def build_info():
    current = fingerprint()
    return {"release": RELEASE, "loaded_sha256": LOADED, "disk_sha256": current,
            "restart_required": LOADED != current,
            "canonical_url": os.getenv("XIAOYI_CANONICAL_URL", ""),
            "database": str(Path(os.getenv("XIAOYI_RUNTIME_DB", str(ROOT / "data/xiaoyi_runtime.db"))).resolve()),
            "planning_modes": ["contract", "adaptive"], "weights_changed": False}
