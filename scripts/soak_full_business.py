"""Sequential native simulation load with independent receipt assertions.

Deliberately omits mobile ACK: successful backend runs remain `partial` and are
never presented as a Flutter completion. All business approvals are labeled
role rehearsals, and every cycle must confirm native compensations.
"""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import signal
import time
import urllib.error
import urllib.request
import uuid

SCENES = [
    "open_water",
    "harbor",
    "auto_berthing",
    "auto_unberthing",
    "narrow_channel_head_on",
    "crossing_starboard",
    "narrow_channel_overtaking",
]
BASE = "http://127.0.0.1:8010/api/harness/joint"
stopping = False


def call(path, body=None):
    data = None if body is None else json.dumps(body, allow_nan=False).encode()
    request = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=35) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=14)
    parser.add_argument("--research-report", default="hr-2b7870971f344c889ee7ccb2d55b1587")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    began = time.monotonic()

    def stop(*_):
        global stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    protocol = {
        "schema": "xiaoyi-native-business-soak.v1",
        "cycles": args.cycles,
        "scenes": SCENES,
        "modes": "alternating enterprise and research",
        "research_report": args.research_report,
        "mobile_ack": "omitted; backend result must remain partial",
        "approvals": "explicit role_rehearsal; never real human signatures",
        "per_cycle_budget_seconds": 900,
        "production_authority": False,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "started_epoch": time.time(),
    }
    (args.out / "protocol.json").write_text(json.dumps(protocol, indent=2))
    results = []
    with (args.out / "events.ndjson").open("w") as log:

        def event(kind, **detail):
            item = {"kind": kind, "epoch": time.time(), "elapsed_seconds": time.monotonic() - began, **detail}
            log.write(json.dumps(item, ensure_ascii=False) + "\n")
            log.flush()
            print(kind, detail.get("id", ""), detail.get("status", ""), flush=True)

        for index in range(args.cycles):
            if stopping:
                break
            # Preserve priority for an existing interactive run and avoid creating
            # an unapproved backlog or evicting unrelated user history.
            while any(
                j["status"] in ["running", "waiting_business_approval", "paused"] for j in call("/missions")["items"]
            ):
                if stopping:
                    break
                time.sleep(2)
            if stopping:
                break
            mode = "research" if index % 2 else "enterprise"
            scene = SCENES[index % len(SCENES)]
            body = {
                "request_id": "native-soak-" + uuid.uuid4().hex,
                "goal": f"稳定性真实业务链循环 {index + 1}：联动五系统，完整原生航次、运输、资源、模拟岗位审批、执行、核验和补偿；本轮不代替Flutter签收。",
                "mode": mode,
                "workflow": "full_business",
                "voyage_scenario": scene,
                "overtaking_agreement_confirmed": scene == "narrow_channel_overtaking",
                "require_mobile": False,
                "mutate_sandbox": False,
                "business_approval": "role_rehearsal",
                "max_seconds": 900,
            }
            if mode == "research":
                body["experiment_id"] = args.research_report
            try:
                job = call("/missions", body)
            except Exception as exc:
                detail = exc.read().decode() if isinstance(exc, urllib.error.HTTPError) else str(exc)
                event("create_failed", scene=scene, mode=mode, error=detail)
                results.append({"mode": mode, "scene": scene, "passed": False, "error": detail})
                break
            mid = job["id"]
            cycle_began = time.monotonic()
            event("created", id=mid, scene=scene, mode=mode, plan_sha256=job["plan_sha256"])
            try:
                while True:
                    try:
                        job = call("/missions/" + mid + "/approval", {"plan_sha256": job["plan_sha256"]})
                        break
                    except urllib.error.HTTPError as exc:
                        if exc.code != 409 or time.monotonic() - cycle_began > 120:
                            raise
                        event("busy_retry", id=mid, status=409, response=exc.read().decode()[:500])
                        time.sleep(2)
                last = None
                while True:
                    job = call("/missions/" + mid)
                    state = (job["status"], job.get("active_step"))
                    if state != last:
                        event("state", id=mid, status=state[0], step=state[1])
                        last = state
                    if stopping:
                        call("/missions/" + mid + "/control/cancel", {})
                        event("stop_requested", id=mid)
                        stopping_at = time.monotonic()
                        while job["status"] in ["running", "cancelling"] and time.monotonic() - stopping_at < 60:
                            time.sleep(0.5)
                            job = call("/missions/" + mid)
                        break
                    if job["status"] == "waiting_business_approval":
                        job = call(
                            "/missions/" + mid + "/business-approval",
                            {"bundle_sha256": job["business_approval_sha256"], "slot": "role_rehearsal"},
                        )
                    elif job["status"] != "running":
                        break
                    if time.monotonic() - cycle_began > 1000:
                        raise TimeoutError("native cycle exceeded independent wall-clock watchdog")
                    time.sleep(1)
                receipt = call("/missions/" + mid + "/export")
                (args.out / (mid + ".json")).write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
                result = {
                    "id": mid,
                    "mode": mode,
                    "scene": scene,
                    "status": job["status"],
                    "wall_seconds": time.monotonic() - cycle_began,
                    "passed": False,
                }
                if not stopping:
                    assert job["status"] == "partial", job.get("error") or job["status"]
                    assert all(
                        receipt["integrity"][k]
                        for k in ["event_chain_valid", "result_hashes_valid", "business_operation_hashes_valid"]
                    )
                    data = job["results"]
                    assert data["sailing"]["data"]["raw"]["validation"]["reachedDestination"] is True
                    assert data["sailing"]["data"]["raw"]["trajectory_teleporting"] is False
                    port = data["port_execute"]["data"]
                    assert port["native_totals"]["violations"] == 0 and port["forecast_matches_execution"]
                    assert port["resource_event_execution"]["tasks_completed"] == 18
                    assert all(
                        v["status"] in ["rolled_back", "rolled_back_simulation"]
                        for v in data["business_rollback"]["data"]["results"].values()
                    )
                    assert "mobile" not in data
                    transport = data["transport"]["data"]
                    assert transport["selected"]["host_revalidated"] and transport["selected"]["validation"]["feasible"]
                    assert transport["pretrained_selection_allowed"] is (mode == "research")
                    result.update(
                        passed=True,
                        selected_transport=transport["selected"]["model"],
                        integrity=receipt["integrity"],
                        active_seconds=job.get("active_seconds"),
                    )
                    # partial deliberately awaits a real client and therefore
                    # occupies an unfinished-job slot. Preserve its receipt,
                    # then close only this test's own run via normal cancel.
                    archived = call("/missions/" + mid + "/control/cancel", {})
                    assert archived["status"] == "cancelled"
                    result["test_cleanup_status"] = archived["status"]
                    closed = call("/missions/" + mid + "/export")
                    (args.out / (mid + "-closed.json")).write_text(json.dumps(closed, ensure_ascii=False, indent=2))
                    event("test_receipt_preserved_and_closed", id=mid, status=archived["status"])
                results.append(result)
                event("cycle_finished", **result)
                (args.out / "progress.json").write_text(
                    json.dumps(
                        {"results": results, "elapsed_seconds": time.monotonic() - began}, ensure_ascii=False, indent=2
                    )
                )
                if stopping:
                    break
            except Exception as exc:
                event("cycle_failed", id=mid, error=str(exc))
                # Request the normal cancel/compensation path; do not bypass a
                # needs_review gate or replay an unknown write.
                try:
                    cleanup = call("/missions/" + mid + "/control/cancel", {})
                    event("cleanup", id=mid, status=cleanup["status"])
                except Exception as cleanup_error:
                    event("cleanup_failed", id=mid, error=str(cleanup_error))
                results.append({"id": mid, "mode": mode, "scene": scene, "passed": False, "error": str(exc)})
                break
    summary = {
        "schema": "xiaoyi-native-business-soak-result.v1",
        "results": results,
        "requested_cycles": args.cycles,
        "cycles_passed": sum(x["passed"] for x in results),
        "complete": len(results) == args.cycles and all(x["passed"] for x in results),
        "actual_wall_seconds": time.monotonic() - began,
        "mobile_client_completions": 0,
        "native_gui_verified": False,
        "production_authority": False,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
