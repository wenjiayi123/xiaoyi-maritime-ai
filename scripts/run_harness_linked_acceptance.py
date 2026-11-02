"""Opt-in local simulation write acceptance; previews, approves, verifies restoration."""

import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    def api(base, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        with urlopen(
            Request(base.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"}), timeout=15
        ) as r:
            return json.load(r)

    def snapshot():
        return api(args.target_url, "/api/operations/snapshot")

    before = snapshot()
    assert before["authority"]["simulation_mode"] is True and before["authority"]["production_authority"] is False
    original = {key: before["simulator"][key] for key in ["scenario", "running"]}
    task = api(
        args.base_url,
        "/api/harness/tasks",
        {
            "goal": "马六甲切换集中到港并观测",
            "request_id": "linked-accept-" + uuid4().hex,
            "driver": "rules",
            "allowed_tools": ["linked.action"],
            "required_tools": ["linked.action"],
        },
    )
    deadline = time.monotonic() + 30
    while task["status"] in {"running", "queued"} and time.monotonic() < deadline:
        time.sleep(0.15)
        task = api(args.base_url, "/api/harness/tasks/" + task["id"])
    assert task["status"] == "waiting_approval", task
    pending = task["pending"]
    unchanged = snapshot()
    assert all(unchanged["simulator"][key] == value for key, value in original.items())
    try:
        api(
            args.base_url,
            f"/api/harness/tasks/{task['id']}/approval",
            {"approval_id": pending["id"], "action_sha256": "0" * 64, "approve": True},
        )
        raise AssertionError("Mismatched approval unexpectedly accepted")
    except HTTPError as exc:
        assert exc.code == 409
    api(
        args.base_url,
        f"/api/harness/tasks/{task['id']}/approval",
        {"approval_id": pending["id"], "action_sha256": pending["action_sha256"], "approve": True},
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        task = api(args.base_url, "/api/harness/tasks/" + task["id"])
        if task["status"] not in {"running", "queued"}:
            break
        time.sleep(0.2)
    receipt = api(args.base_url, f"/api/harness/tasks/{task['id']}/export")
    after = snapshot()
    result = json.loads(next(a["content"] for a in receipt["artifacts"] if a["name"] == "T1.json"))
    approval = next(e["detail"] for e in receipt["events"] if e["event"] == "approval.decided")
    checks = {
        "completed": task["status"] == "completed",
        "approval_bound": True,
        "approval_identity_persisted": bool(approval.get("approver_id"))
        and approval.get("action_sha256") == pending["action_sha256"]
        and approval.get("approval_id") == pending["id"],
        "no_write_before_approval": True,
        "restored": result["receipt"]["restored"] is True,
        "configuration_restored": all(after["simulator"][key] == value for key, value in original.items()),
        "production_disabled": after["authority"]["production_authority"] is False,
        "event_chain_valid": receipt["integrity"]["event_chain_valid"],
    }
    report = {
        "passed": all(checks.values()),
        "checks": checks,
        "before_config": original,
        "after_config": {key: after["simulator"][key] for key in original},
        "receipt": receipt,
        "scope": "实际本机马六甲模拟接口；恢复配置不倒放模拟时间，不涉及现场生产授权",
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"passed": report["passed"], "checks": checks}, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
