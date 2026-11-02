"""Actual 4B Harness trials on isolated, explicit semantic fault-injection data.

Production sources are not changed. This is integration testing, not a field trial.
The independent checks below never import the summary/semantic verifier helpers.
"""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--protocol", default=".codex_artifacts/harness-v12-20261031/protocol.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        parser.error("Use a new output directory; evidence cannot be overwritten.")
    output.mkdir(parents=True)
    protocol = json.loads(Path(args.protocol).read_text())
    spec = protocol["stages"][args.stage]
    os.environ["XIAOYI_RUNTIME_DB"] = str(output.resolve() / "control.db")
    os.environ["XIAOYI_MODEL_PROVIDER"] = "openai_compatible"
    os.environ["XIAOYI_MODEL_BASE_URL"] = "http://127.0.0.1:11435/v1"
    os.environ["XIAOYI_MODEL_NAME"] = "xiaoyi-local-4b"
    os.environ["XIAOYI_MODEL_EXTERNAL_DATA_ALLOWED"] = "false"

    from fastapi.encoders import jsonable_encoder
    from app.access_control import IdentityContext
    from app.harness.contracts import CreateTask, Budget, digest
    from app.harness.model import CompatibleDriver
    from app.harness.runner import Harness
    from app.harness.store import HarnessStore
    from app import realtime_port_simulator as source

    def save(name, data):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2))

    source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT / "app/harness").glob("*.py"))}
    save("frozen-implementation.json", {"at": datetime.now(timezone.utc).isoformat(), "source_sha256": source_hashes, "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "protocol_sha256": hashlib.sha256(Path(args.protocol).read_bytes()).hexdigest()})
    rows = []
    for index, kind in enumerate(spec["cases"]):
        identity = f"V12-{spec['seed']}-{index}"
        asset = f"QC-{21 + index + spec['seed'] % 7:02d}"
        vessel = f"澄海{spec['seed'] % 100}轮"
        port_name = f"核验样板港{spec['seed'] % 100}"
        if kind == "risk":
            goal = "读取本次模拟港区快照，给出港区名称和编号、主要告警，以及现场接入缺项，不调整设备。"
        elif kind == "nullable":
            goal = f"读取快照，说明{vessel}的 ETA、ATB 各有哪些值或空项，并说明岸电负荷。不得把空值当零，不调整设备。"
        elif kind == "source_gap":
            goal = "读取快照，说明港区名称和编号哪些已提供、哪些缺失，概括主要告警，不调整设备。"
        else:
            goal = "先检索岸电SOP核验资料，再读取本次模拟港区快照，说明港区名称和编号、主要告警与资料适用边界，不调整设备。"
        required = ["runtime.snapshot"] + (["knowledge.search"] if kind == "rag_risk" else [])
        save(f"{index}-case.json", {"kind": kind, "goal": goal, "required_tools": required, "expected_identity": identity, "asset": asset, "vessel": vessel, "port_name": None if kind == "source_gap" else port_name})
        captured = []
        sim = source.PortRealtimeSimulator(seed=spec["seed"] + index)

        def read_fixture():
            # Capture now, once when the registered tool actually asks for data.
            # Explicit injected fields are part of the source fixture, not hidden truth.
            at = datetime.now(timezone.utc).replace(microsecond=0)
            s = jsonable_encoder(sim.snapshot_at(sequence=spec["seed"] + index, observed_at=at))
            s["port"].update(code=identity, name=None if kind == "source_gap" else port_name)
            s["overview"]["port_name"] = s["port"]["name"]
            s["metadata"]["fixture_scope"] = "isolated controlled semantic input; not field measurements or a physical-validation case"
            s["metadata"]["port_code"] = identity
            s["metadata"]["source_adapter"] = "IsolatedSemanticProbeSource"
            s["metadata"]["original_payload_sha256_before_injection"] = s["metadata"]["payload_sha256"]
            s["alerts"] = [{"event_id": identity + "-alert", "asset_id": asset, "severity": "critical", "status": "active", "title": "吊具锁销状态异常", "message": "锁销传感器状态不一致，需现场复核。", "occurred_at": at.isoformat()}]
            s["port_calls"][0].update(vessel_name=vessel, eta=None, atb=(at - timedelta(hours=1)).isoformat())
            if kind == "nullable":
                old_shore = s["energy"]["shore_power_kw"]
                s["energy"]["shore_power_kw"] = 0.0
                s["energy"]["shore_power_connections"] = 0
                s["energy"]["grid_demand_kw"] = round(s["energy"]["grid_demand_kw"] - old_shore, 1)
            # Keep the original simulator's documented hash scope (pre-metadata,
            # pre-decision payload); the fixture must not retain a stale source hash.
            body = {k:v for k,v in s.items() if k not in {"metadata", "decisions"}}
            s["metadata"]["payload_sha256"] = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
            s["decisions"] = []  # Old action proposals are not valid for injected data.
            captured.append(copy.deepcopy(s))
            save(f"{index}-snapshot-{len(captured)}.json", s)
            return s

        source.simulator_snapshot = read_fixture
        calls = []

        class MeasuredDriver(CompatibleDriver):
            def next(self, task, messages):
                n = len(calls)
                started = time.monotonic()
                row = {"number": n + 1, "started_at": datetime.now(timezone.utc).isoformat(), "input_chars": sum(len(m["content"]) for m in messages), "messages": messages}
                calls.append(row)
                try:
                    action, usage = super().next(task, messages)
                    row.update(action=action.model_dump(mode="json"), usage=usage)
                    return action, usage
                except Exception as exc:
                    row.update(error=str(exc), validation_error=getattr(exc, "validation_error", None))
                    raise
                finally:
                    row["seconds"] = round(time.monotonic() - started, 3)
                    save(f"{index}-model-calls.json", calls)

        store = HarnessStore(output / f"task-{index}.db")
        h = Harness(store, model_driver=MeasuredDriver(), workers=1)
        started = time.monotonic()
        t = h.create(CreateTask(goal=goal, driver="model", request_id="v12-" + uuid4().hex, allowed_tools=required, required_tools=required, budget=Budget(max_active_seconds=360, max_tokens=16000)), IdentityContext("v12-evaluator", "operator", True, "isolated-test"))
        print(json.dumps({"case": kind, "task_id": t["id"], "stage": args.stage}), flush=True)
        while t["status"] in {"running", "queued"} and time.monotonic() - started < 500:
            time.sleep(0.4)
            t = store.get(t["id"])
        text = (t.get("final") or {}).get("text", "")
        # Independent, fixed outcome checks: not the runtime's verification flag.
        semantic = {"model_authored": (t.get("final") or {}).get("synthesis", {}).get("model_authored") is True, "simulation_boundary": bool(re.search("模拟|现场.*(?:未|不)|(?:未|不).*现场", text))}
        if protocol.get("additional_checks"):
            semantic["simulation_boundary"] = bool(re.search("模拟|仿真", text))
            semantic["no_false_read_permission_cause"] = not any("权限" in c and re.search(r"(?:无法|不能).{0,8}(?:读取|获取|采集).{0,12}数据", c) for c in re.split("[。；;\\n]", text))
        if kind in {"risk", "source_gap", "rag_risk"}:
            semantic["identity"] = identity in text
            semantic["critical_alert"] = asset in text and bool(re.search("锁销|吊具", text))
            if kind == "source_gap":
                semantic["actual_name_gap"] = bool(re.search(r"名称[^。；\n]{0,24}(?:缺|空|未提供|未知)|(?:缺|空|未提供|未知)[^。；\n]{0,24}名称", text))
            else:
                semantic["known_name"] = port_name in text
                semantic["no_false_identity_gap"] = not bool(re.search(r"(?:缺少|缺失|未提供)(?:具体)?(?:港口|港区|对象|日期)", text))
        if kind == "nullable":
            semantic["entity"] = vessel in text
            semantic["eta_null"] = bool(re.search(r"ETA[^。；;\n]{0,28}(?:空|未提供|未填|未报告|未知|null)", text, re.I))
            atb = captured[-1]["port_calls"][0]["atb"] if captured else "NO_SOURCE"
            semantic["atb_present"] = "ATB" in text and atb[11:16] in text
            semantic["shore_zero"] = bool(re.search(r"岸电[^。；;\n]{0,24}(?<!\d)0(?:\.0)?\s*(?:kW|千瓦)", text, re.I))
        refs = {r["tool"] for r in t["results"] if r["ok"]}
        events = store.events(t["id"], limit=10000)
        previous = "0" * 64
        event_ok = True
        for e in events:
            event_ok &= e["previous_sha256"] == previous and digest({k:v for k,v in e.items() if k != "sha256"}) == e["sha256"]
            previous = e["sha256"]
        artifacts = [store.artifact(t["id"], a["name"]) for a in store.artifacts(t["id"])]
        elapsed = time.monotonic() - started
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(captured[-1]["metadata"]["observed_at"])).total_seconds() if captured else None
        # Prefer the gate's actual delivery timestamp over the polling timestamp.
        readiness = (t.get("final") or {}).get("verification", {}).get("delivery_readiness") or {}
        age = readiness.get("age_seconds", age)
        checks = {"completed": t["status"] == "completed", "required_tools": set(required).issubset(refs), "event_chain": event_ok, "artifact_integrity": all(a["sha256"] == digest(a["content"]) for a in artifacts), "production_disabled": t["production_authority"] is False, **semantic}
        if args.stage.startswith("latency"):
            checks["fresh_at_delivery"] = age is not None and -5 <= age <= 120 and readiness.get("analysis_usable") is True
        row = {"kind":kind, "task":t, "checks":checks, "passed":all(checks.values()), "elapsed_seconds":round(elapsed,3), "snapshot_age_seconds":age, "model_calls":len(calls), "events":events, "artifacts":artifacts}
        save(f"{index}-receipt.json", row)
        rows.append({k:v for k,v in row.items() if k not in {"events","artifacts"}})
        save("report.json", {"stage":args.stage,"rows":rows,"passed":all(r["passed"] for r in rows),"scope":protocol["scope"]})
        print(json.dumps({"case":kind,"status":t['status'],"checks":checks,"elapsed_seconds":round(elapsed,3),"snapshot_age_seconds":age,"text":text},ensure_ascii=False),flush=True)
        h.close()
    raise SystemExit(0 if all(r["passed"] for r in rows) else 1)


if __name__ == "__main__":
    main()
