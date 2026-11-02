import json
import time
import uuid
import urllib.request
from pathlib import Path

root = Path(".codex_artifacts/joint-harness-phase2-20261029")
base = "http://127.0.0.1:8010/api/harness"


def call(path, data=None):
    raw = None if data is None else json.dumps(data).encode()
    with urllib.request.urlopen(
        urllib.request.Request(base + path, data=raw, headers={"Content-Type": "application/json"}), timeout=35
    ) as response:
        return json.load(response)


for _ in range(60):
    try:
        call("/joint/capabilities")
        break
    except Exception:
        time.sleep(0.5)
j = call(
    "/joint/missions",
    {"request_id": uuid.uuid4().hex, "goal": "联动五系统，复核原有联合评估功能保持可用。", "max_seconds": 180},
)
assert j["config"]["workflow"] == "assessment"
j = call("/joint/missions/" + j["id"] + "/approval", {"plan_sha256": j["plan_sha256"]})
print(j["id"], flush=True)
for _ in range(180):
    j = call("/joint/missions/" + j["id"])
    (root / "legacy-smoke-state.json").write_text(json.dumps(j, ensure_ascii=False, indent=2))
    if j["status"] != "running":
        break
    time.sleep(1)
assert j["status"] == "waiting_mobile", j.get("error")
print(j["status"], flush=True)
