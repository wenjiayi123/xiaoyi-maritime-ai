"""Live negative-path checks: serialized executor, real native timeout, no dependent writes."""

import json
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path

root = Path(".codex_artifacts/joint-harness-phase2-20261029")
base = "http://127.0.0.1:8010/api/harness"


def call(path, data=None):
    body = None if data is None else json.dumps(data).encode()
    with urllib.request.urlopen(
        urllib.request.Request(base + path, data=body, headers={"Content-Type": "application/json"}), timeout=35
    ) as response:
        return json.load(response)


def create(goal, **kw):
    return call(
        "/joint/missions",
        {"request_id": uuid.uuid4().hex, "goal": goal, "workflow": "full_business", "max_seconds": 30, **kw},
    )


def approve(j):
    return call("/joint/missions/" + j["id"] + "/approval", {"plan_sha256": j["plan_sha256"]})


j = create("联动五系统，验证完整原生航次预算不足时应安全停止。")
approve(j)
other = create("联动五系统，验证并发完整任务不能抢占执行器。")
try:
    approve(other)
    rejection = {"status": "UNEXPECTED_ACCEPT"}
except urllib.error.HTTPError as exc:
    rejection = {"status": exc.code, "body": exc.read().decode()}
call("/joint/missions/" + other["id"] + "/approval", {"plan_sha256": other["plan_sha256"], "approve": False})
for _ in range(100):
    j = call("/joint/missions/" + j["id"])
    if j["status"] != "running":
        break
    time.sleep(0.5)
assert (
    rejection["status"] == 409
    and j["status"] == "budget_exceeded"
    and not any(s in j["results"] for s in ["port", "energy", "business_prepare", "port_execute"])
)
(root / "full-native-budget-and-contention.json").write_text(
    json.dumps(
        {"concurrency_rejection": rejection, "timed_out_mission": j, "safe_no_dependent_steps": True},
        ensure_ascii=False,
        indent=2,
    )
)
print(j["id"], j["status"], rejection["status"], flush=True)
weather = create("联动五系统，验证未准入极端天气应拒绝后续执行。", scenario="extreme-weather")
approve(weather)
for _ in range(50):
    weather = call("/joint/missions/" + weather["id"])
    if weather["status"] != "running":
        break
    time.sleep(0.2)
assert weather["status"] == "blocked" and "port" not in weather["results"]
(root / "full-native-weather-rejection.json").write_text(json.dumps(weather, ensure_ascii=False, indent=2))
print(weather["id"], weather["status"], flush=True)
