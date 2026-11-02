"""Actual restore-tool integration with explicit test-controller calls, no LLM."""
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".codex_artifacts/harness-v13-20261101/restore-adapter"
sys.path.insert(0, str(ROOT))
OUT.mkdir(exist_ok=False)
os.environ.update(XIAOYI_RUNTIME_DB=str(OUT / "runtime.sqlite"), XIAOYI_ENERGY_API_URL="http://127.0.0.1:18808")

from app.access_control import IdentityContext  # noqa: E402
from app.harness.contracts import CreateTask, digest, encoded  # noqa: E402
from app.harness.runner import Harness  # noqa: E402
from app.harness.store import HarnessStore  # noqa: E402
from app.harness import tools  # noqa: E402
from app import linked_agent  # noqa: E402

h = Harness(HarnessStore(OUT / "tasks.sqlite"))
run = None
try:
    task = h.create(CreateTask(goal="测试控制器验证恢复适配器，不是模型决策", request_id=uuid4().hex, driver="rules",
        allowed_tools=["linked.action","execution.verify","execution.restore"]), IdentityContext("v13-restore","admin",True,"integration-test"),schedule=False)
    arguments = {"action_id":"energy.clock","parameters":{"action":"stop"},"samples":1,"restore_after_observation":False}
    prepared = tools.prepare_action(task,arguments)
    result = tools.execute("linked.action",arguments,task,h.store,prepared=prepared,call_id="restore-probe-"+uuid4().hex)
    run = result["receipt"]
    raw = encoded(result)
    h.store.artifact(task["id"],"T1.json",raw)
    record = {"id":"T1","tool":"linked.action","ok":run["status"]=="completed","arguments":arguments,"artifact":"T1.json","sha256":digest(raw)}
    task = h.store.mutate(task["id"],lambda t:t.update(results=[record],inflight={}),"test_controller.recorded",record)
    first = tools.execute("execution.verify",{"source_ref":"T1"},task,h.store)
    restore_plan = tools.prepare_action(task,{"source_ref":"T1"},name="execution.restore",store=h.store)
    restored = tools.execute("execution.restore",{"source_ref":"T1"},task,h.store,prepared=restore_plan,call_id=uuid4().hex)
    final = tools.execute("execution.verify",{"source_ref":"T1"},task,h.store)
    checks = {"initial_pause_verified":first["status"]=="completed", "restore_completed":restored["status"]=="completed",
        "final_readback_verified":final["status"]=="completed", "production_disabled":final["production_authority"] is False}
    (OUT/"receipts.json").write_text(json.dumps({"initial":result,"first_check":first,"approved_restore":restore_plan,
        "restore":restored,"final_check":final},ensure_ascii=False,indent=2))
    (OUT/"result.json").write_text(json.dumps({"kind":"real adapters, explicit test-controller calls; no model decision",
        "checks":checks,"passed":all(checks.values())},ensure_ascii=False,indent=2))
    print(checks,flush=True)
finally:
    if run is not None and run.get("applied"):
        current = linked_agent.get_run(run["id"],tools.internal_request(task))
        if not current.get("restored"):
            linked_agent.rollback(run["id"],tools.internal_request(task))
    h.close()
