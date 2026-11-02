"""Real local model, real read adapter, one explicitly injected pre-I/O timeout."""
import json
import argparse
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument("--round", default="r1")
args = parser.parse_args()
OUT = ROOT / (".codex_artifacts/harness-v13-20261101/recovery-model-" + args.round)
OUT.mkdir(exist_ok=False)
os.environ.update(XIAOYI_RUNTIME_DB=str(OUT / "runtime.sqlite"),
    XIAOYI_HARNESS_MODEL_BASE_URL="http://127.0.0.1:11435/v1",XIAOYI_HARNESS_MODEL_NAME="xiaoyi-local-4b",
    XIAOYI_ENERGY_API_URL="http://127.0.0.1:18808",XIAOYI_ENERGY_HEALTH_URL="http://127.0.0.1:18808/api/health",
    XIAOYI_ENERGY_UI_URL="http://127.0.0.1:18474")

from app.access_control import IdentityContext  # noqa: E402
from app.harness.contracts import Budget, CreateTask  # noqa: E402
from app.harness.runner import Harness  # noqa: E402
from app.harness.store import HarnessStore  # noqa: E402
from app.harness.trajectory import export_trajectory  # noqa: E402
from app import linked_agent  # noqa: E402

protocol = {"goal":"读取能碳运行快照并汇总模拟状态。如果只读接口临时失败，可重试一次；不要执行任何写操作。",
    "injection":"one timeout before the first energy snapshot HTTP request; later requests use real target",
    "acceptance":["actual model chooses retry", "original failed result retained", "successful retry resolves failure", "final completed"],
    "required_tools":[],"template_id":None,"fake_model":False}
(OUT / "protocol.json").write_text(json.dumps(protocol,ensure_ascii=False,indent=2))
original = linked_agent._request
calls = []


def fail_once(target,method,path,*args,**kwargs):
    calls.append({"target":target,"method":method,"path":path})
    if len(calls) == 1:
        raise TimeoutError("injected read timeout")
    return original(target,method,path,*args,**kwargs)


linked_agent._request = fail_once
h = Harness(HarnessStore(OUT / "tasks.sqlite"))
try:
    task = h.create(CreateTask(goal=protocol["goal"],request_id=uuid4().hex,planning_mode="adaptive",driver="model",
        allowed_tools=["systems.inspect"],required_tools=[],budget=Budget(max_steps=8,max_active_seconds=600,max_tokens=24000)),
        IdentityContext("v13-recovery","admin",True,"isolated-acceptance"))
    deadline = time.monotonic()+650
    while time.monotonic()<deadline:
        task=h.store.get(task["id"])
        (OUT/"task.json").write_text(json.dumps(task,ensure_ascii=False,indent=2))
        if task["status"] not in {"running","queued"}:
            break
        time.sleep(2)
    (OUT/"trajectory.json").write_text(json.dumps(export_trajectory(task,h.store),ensure_ascii=False,indent=2))
    (OUT/"calls.json").write_text(json.dumps(calls,ensure_ascii=False,indent=2))
    checks={"completed":task["status"]=="completed","real_model":task["driver"]=="model",
        "failure_retained":any(not r["ok"] for r in task["results"]),
        "recovered":any(not r["ok"] and r.get("resolved_by") for r in task["results"])}
    (OUT/"result.json").write_text(json.dumps({"checks":checks,"passed":all(checks.values())},indent=2))
    print(task["status"],checks,flush=True)
finally:
    linked_agent._request=original
    h.close()
