"""Identify loaded code separately from files that may have changed on disk."""
from pathlib import Path
import hashlib
import os

ROOT = Path(__file__).resolve().parents[2]
RELEASE = "harness-v13.2-gullmate-20261106"


def fingerprint():
    paths = sorted((ROOT / "app/harness").glob("*.py")) + [ROOT / name for name in
        ["app/main.py", "app/linked_agent.py", "app/linked_agent_catalog.py", "app/sailing_simulator_launcher.py",
         "app/ais_evidence.py", "app/visual_evidence.py", "app/knowledge_api.py",
         "app/policy_release.py", "app/policy_board.py", "app/exercise_records.py", "app/batch_emissions.py", "app/maintenance_hours.py", "app/monthly_energy_rule.py", "app/quantity_dialogue.py",
         "data/monthly_energy_20250208/source-lock.json", "app/port_activity.py", "app/professional_methods.py",
         "data/public/portwatch_crossport_20261030/manifest.json", "web/actor-transfer.html", "web/actor-transfer-compare.js",
         "app/shore_history.py", "app/shore_changes.py", "data/shore_case_20250701/source-notes.json", "data/shore_case_20250701/shanghai.html",
         "app/production_boundary.py", "app/query_intelligence.py", "app/model_gateway.py", "app/models.py",
         "app/xiaoyi.py", "web/actor-policy-replay.js", "web/actor-policy-replay.html",
         "app/rl_lab/api.py", "app/retrieval.py", "web/policy-evidence/figures.json",
         "web/app.js", "web/harness_chat.js", "web/index.html", "web/policy-replay.html",
         "web/gullmate-policy-replay.js", "web/gullmate-policy-replay.css"]]
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
