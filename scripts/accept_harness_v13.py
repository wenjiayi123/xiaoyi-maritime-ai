"""Actual model/adapter trials. Protocol saved before these requests; no fake drivers."""
import argparse
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".codex_artifacts/harness-v13-20261101"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--base", default="http://127.0.0.1:18019")
    parser.add_argument("--round", default="r1")
    args = parser.parse_args()
    case = next(c for c in json.loads((OUT / "protocol.json").read_text())["cases"] if c["id"] == args.case)
    folder = OUT / args.round / args.case
    folder.mkdir(parents=True, exist_ok=False)

    def api(path, payload=None):
        request = Request(args.base + path, data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type":"application/json"}, method="POST" if payload is not None else "GET")
        with urlopen(request, timeout=25) as response:
            return json.load(response)

    capabilities = api("/api/harness/capabilities")
    (folder / "capabilities.json").write_text(json.dumps(capabilities,ensure_ascii=False,indent=2))
    before_clock = None
    if case.get("expect_conditional"):
        with urlopen("http://127.0.0.1:18473/api/operations/snapshot", timeout=10) as response:
            before_clock = json.load(response)
        (folder / "before-clock.json").write_text(json.dumps(before_clock,ensure_ascii=False,indent=2))
    response = api("/api/harness/chat", {"text":case["goal"],"force_task":True,"request_id":"v13-" + uuid4().hex})
    task = response["task"]
    started = time.monotonic()
    approved = set()
    allowed = set(case.get("expect_actions", []))
    if case.get("expect_conditional"):
        allowed.add("malacca.clock")
    last = None
    while time.monotonic() - started < 1000:
        task = api("/api/harness/tasks/" + task["id"])
        (folder / "task.json").write_text(json.dumps(task,ensure_ascii=False,indent=2))
        state = (task["status"],len(task["results"]),task["usage"]["steps"])
        if state != last:
            print(args.case,state,flush=True)
            last = state
        if task["status"] == "waiting_approval":
            pending = task["pending"]
            if pending["id"] not in approved:
                action = pending["action"]
                accept = action["tool"] == "linked.action" and action["arguments"].get("action_id") in allowed
                if before_clock is not None:
                    accept = accept and before_clock["simulator"]["running"] and action["arguments"].get("parameters", {}).get("action", "stop") == "stop" and action["arguments"].get("restore_after_observation", True)
                (folder / (pending["id"] + ".json")).write_text(json.dumps({"approval":pending,"approved":accept,
                    "actor":"authorized test runner; not independent human approval"},ensure_ascii=False,indent=2))
                api(f"/api/harness/tasks/{task['id']}/approval", {"approval_id":pending["id"],"action_sha256":pending["action_sha256"],"approve":accept})
                approved.add(pending["id"])
        elif task["status"] not in {"running","queued"}:
            break
        time.sleep(2)
    else:
        api(f"/api/harness/tasks/{task['id']}/control/cancel", {})
    exported = api(f"/api/harness/tasks/{task['id']}/export")
    (folder / "export.json").write_text(json.dumps(exported,ensure_ascii=False,indent=2))
    successful = [r for r in task["results"] if r["ok"]]
    actions = [r["arguments"].get("action_id") for r in successful if r["tool"] == "linked.action"]
    resources = [[r["arguments"].get("target"),r["arguments"].get("resource")] for r in successful if r["tool"] == "systems.inspect"]
    checks = {"completed":task["status"] == "completed", "model":task["driver"] == "model",
        "adaptive":task.get("planning_mode") == "adaptive" and task.get("template_id") is None and not task["required_tools"],
        "expected_actions":set(case.get("expect_actions",[])) <= set(actions),
        "expected_tools":set(case.get("expect_tools",[])) <= {r["tool"] for r in successful},
        "expected_resources":all(r in resources for r in case.get("expect_resources",[])),
        "production_disabled":task["production_authority"] is False,
        "verified": bool(task.get("final",{})) and task["final"]["verification"]["passed"]}
    if case["id"] == "energy_compare":
        comparisons = [r for r in successful if r["tool"] == "linked.action" and r["arguments"].get("action_id") == "energy.compare"]
        checks["exact_parameters"] = bool(comparisons) and all(r["arguments"]["parameters"] == {
            "baseline_green_preference":0.5,"green_preference":0.72,"carbon_price_cny_per_ton":120}
            for r in comparisons)
    if before_clock is not None:
        with urlopen("http://127.0.0.1:18473/api/operations/snapshot", timeout=10) as response:
            after_clock = json.load(response)
        (folder / "after-clock.json").write_text(json.dumps(after_clock,ensure_ascii=False,indent=2))
        writes = [r for r in successful if r["tool"] == "linked.action"]
        was_running = before_clock["simulator"]["running"]
        checks["conditional_branch"] = (len(writes) == 1 and writes[0]["arguments"]["action_id"] == "malacca.clock"
            and writes[0]["arguments"]["parameters"].get("action", "stop") == "stop"
            and writes[0]["arguments"].get("restore_after_observation", True)) if was_running else not writes
        checks["clock_restored"] = after_clock["simulator"]["running"] == was_running and after_clock["simulator"]["scenario"] == before_clock["simulator"]["scenario"]
    result = {"case":case,"task_id":task["id"],"elapsed_seconds":round(time.monotonic()-started,2),"checks":checks,
              "passed":all(checks.values()),"tools":[r["tool"] for r in task["results"]],"actions":actions}
    (folder / "result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
