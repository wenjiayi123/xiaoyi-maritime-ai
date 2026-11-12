from pathlib import Path
from fastapi.testclient import TestClient
from app.access_control import IdentityContext
from app.harness import api
from app.harness.contracts import CreateTask, TERMINAL, WAITING
from app.harness.runner import Harness
from app.harness.store import HarnessStore
from app.main import app


def exercise(path, bind):
    # Inject terminal states in a private store; all decisions use the normal HTTP route.
    h = Harness(HarnessStore(path))
    group = "pc-" + "a"*24
    actor = IdentityContext("council-check", "operator", True, "test")
    roles = ("operations","energy","safety")
    tasks = {}
    for role in roles:
        task = h.create(CreateTask(goal="核对模拟策略回执",request_id=group+"-"+role,driver="rules",
                                   allowed_tools=["policy."+role]),actor,schedule=False)
        tasks[role] = task["id"]
    bind(h)
    body = {"group":group,"tasks":tasks,"selection":{"scenario":"stress","strategy":"joint","seed":17,"baseline":"fixed","window":0}}
    statuses = sorted((TERMINAL - {"completed"}) | WAITING | {"queued","running","expired"})
    results = {}
    with TestClient(app,headers={"X-Xiaoyi-Actor":actor.actor_id,"X-Xiaoyi-Role":actor.role}) as client:
        for status in statuses:
            h.store.mutate(tasks["energy"],lambda t:t.update(status=status),"test.injected_status")
            res=client.post("/api/harness/policy-council/status",json=body)
            res.raise_for_status()
            result=res.json()
            assert result["production_authority"] is False and not result["all_evidence_present"]
            results[status]=result["decision"]
    h.close()
    return results


def test_all_unrecoverable_role_states_require_review(tmp_path,monkeypatch):
    results=exercise(tmp_path/"council.sqlite",lambda h:monkeypatch.setattr(api,"get_harness",lambda:h))
    for s,d in results.items():
        assert d==("needs_review" if s in TERMINAL or s=="expired" else "awaiting_evidence")
