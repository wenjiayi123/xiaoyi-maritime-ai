"""Export observed decision transitions for later RL research; no trainer or reward claims."""
from app.harness.contracts import digest


def export_trajectory(task, store):
    events, cursor = [], 0
    while True:
        batch = store.events(task["id"], cursor, 200)
        if not batch:
            break
        events.extend(batch)
        cursor = batch[-1]["seq"]
    transitions, observed, pending = [], [], None
    previous = "0" * 64
    valid = True
    for event in events:
        value = {k: v for k, v in event.items() if k != "sha256"}
        valid = valid and event["previous_sha256"] == previous and digest(value) == event["sha256"]
        previous = event["sha256"]
        if event["event"] == "model.action":
            pending = {"seq": event["seq"], "at": event["at"], "observation_refs": list(observed),
                "action": event["detail"], "feedback": [], "origin": task["driver"]}
            transitions.append(pending)
        elif event["event"] == "verification.scheduled" and pending is not None:
            pending["feedback"].append({"kind":"runtime_postcondition", "detail":event["detail"]})
        elif event["event"] in {"tool.completed", "tool.failed"}:
            result = event["detail"]
            observed.append(result["id"])
            if pending is not None:
                pending["feedback"].append({"kind": event["event"], "result_ref": result["id"], "ok": result["ok"],
                    "tool": result["tool"], "elapsed_ms": result["elapsed_ms"], "artifact_sha256": result["sha256"]})
        elif pending is not None and event["event"] in {"tool.rejected", "approval.requested", "approval.decided", "completion.business_repair", "completion.numeric_repair", "completion.rejected", "task.finalized"}:
            pending["feedback"].append({"kind": event["event"], "detail": event["detail"]})
    integrity = []
    for record in task["results"]:
        artifact = store.artifact(task["id"], record["artifact"])
        integrity.append(bool(artifact and digest(artifact["content"]) == artifact["sha256"] == record["sha256"]))
    return {"schema": "xiaoyi-harness-observed-transitions.v1", "task_id": task["id"], "goal": task["goal"],
        "planning_mode": task.get("planning_mode", "contract"), "driver": task["driver"], "model": task["model"],
        "allowed_tools": task["allowed_tools"], "transitions": transitions,
        "outcome": {"status": task["status"], "recorded_final_verification": (task.get("final") or {}).get("verification"),
            "tool_calls": task["usage"]["tool_calls"], "tokens": task["usage"]["tokens"],
            "active_seconds": task["usage"]["active_seconds"], "failed_calls": sum(not r["ok"] for r in task["results"])},
        "integrity": {"event_chain": bool(events) and valid, "artifacts": all(integrity)},
        "training_performed": False, "reward_assigned": False,
        "notice": "实际决策与反馈轨迹，可用于后续RL环境和奖励设计；本导出没有训练Harness、分配奖励或证明策略提升。包含开发可见案例，不能直接冒充独立测试集。"}
