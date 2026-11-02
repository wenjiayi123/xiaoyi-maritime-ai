"""Isolated authenticated actors, atomic recovery and independent software safety worker.

HMAC transport is a local rehearsal layer, not DCSA certification or nonrepudiation.
Virtual actuators and injected calibration truth never establish field/HIL authority.
"""

import copy
import hashlib
import hmac
import json
import math
import multiprocessing as mp
import os
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import yaml

from app.harness import operations_v3 as standard
from app.harness.physical_v2 import sha

ROOT = standard.old.BASE_DIR


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sign(payload, actor, key, nonce=None, issued=None, fault=None):
    packet = {
        "actor": actor,
        "nonce": nonce or uuid.uuid4().hex,
        "issued_at": issued or time.time(),
        "payload": payload,
        "fault": fault,
    }
    return {**packet, "mac": hmac.new(key, canonical(packet), hashlib.sha256).hexdigest()}


def verify_envelope(packet, keys, clock):
    if set(packet) != {"actor", "nonce", "issued_at", "payload", "fault", "mac"}:
        raise ValueError("unexpected authentication envelope fields")
    if packet["actor"] not in keys or len(packet["nonce"]) != 32:
        raise PermissionError("unknown actor/nonce")
    body = {k: v for k, v in packet.items() if k != "mac"}
    expected = hmac.new(keys[packet["actor"]], canonical(body), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, packet["mac"]):
        raise PermissionError("signature mismatch")
    if (
        not isinstance(packet["issued_at"], (int, float))
        or not math.isfinite(packet["issued_at"])
        or abs(clock - packet["issued_at"]) > 300
    ):
        raise ValueError("expired/future authenticated transport clock")


def actor_server(database, keyfile, ready):
    keys = {k: bytes.fromhex(v) for k, v in json.loads(Path(keyfile).read_text()).items()}
    schema = yaml.safe_load((standard.STANDARD / "dcsa-pc200-openapi.yaml").read_text())
    db = sqlite3.connect(database)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE, body TEXT NOT NULL)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS inbox(nonce TEXT PRIMARY KEY, request_sha TEXT NOT NULL, response TEXT NOT NULL)"
    )
    db.commit()
    negotiation = standard.Negotiation(schema)
    for _, identity, body in db.execute("SELECT seq,event_id,body FROM events ORDER BY seq"):
        negotiation.events[identity] = json.loads(body)
        negotiation.latest = identity

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            status, result = 200, {}
            before = copy.deepcopy(negotiation.events), negotiation.latest
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("request size invalid")
                packet = json.loads(self.rfile.read(length))
                verify_envelope(packet, keys, time.time())
                digest = hashlib.sha256(canonical(packet)).hexdigest()
                prior = db.execute(
                    "SELECT request_sha,response FROM inbox WHERE nonce=?", (packet["nonce"],)
                ).fetchone()
                if prior:
                    if prior[0] != digest:
                        raise ValueError("nonce identity conflict")
                    result = {**json.loads(prior[1]), "transport_retry": True}
                else:
                    clock = datetime.now(timezone.utc)
                    outcome = negotiation.receive(packet["payload"], packet["actor"], clock)
                    if packet["fault"] == "before_commit":
                        os._exit(71)
                    db.execute("BEGIN IMMEDIATE")
                    if outcome != "duplicate":
                        db.execute(
                            "INSERT INTO events(event_id,body) VALUES (?,?)",
                            (packet["payload"]["eventID"], canonical(packet["payload"]).decode()),
                        )
                    result = {
                        "outcome": outcome,
                        "event_id": packet["payload"]["eventID"],
                        "effect_count": db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                        "production_authority": False,
                    }
                    db.execute(
                        "INSERT INTO inbox VALUES (?,?,?)", (packet["nonce"], digest, canonical(result).decode())
                    )
                    db.commit()
                    if packet["fault"] == "after_commit":
                        os._exit(72)
            except (ValueError, TypeError, KeyError, PermissionError, sqlite3.Error) as exc:
                db.rollback()
                negotiation.events, negotiation.latest = before
                status, result = (
                    (403 if isinstance(exc, PermissionError) else 422),
                    {"error": str(exc), "production_authority": False},
                )
            body = canonical(result)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    ready.send(server.server_port)
    ready.close()
    server.serve_forever()


def client_worker(port, packet, receipt):
    try:
        with urlopen(
            Request(f"http://127.0.0.1:{port}", data=canonical(packet), headers={"Content-Type": "application/json"}),
            timeout=3,
        ) as response:
            result = {"status": response.status, "body": json.load(response)}
    except HTTPError as exc:
        result = {"status": exc.code, "body": json.loads(exc.read())}
    except (URLError, OSError, ValueError) as exc:
        result = {"status": 0, "error": type(exc).__name__}
    receipt.send({**result, "actor_process_id": os.getpid()})
    receipt.close()


def planner_crash_worker(channel, command):
    channel.send(command)
    time.sleep(0.05)
    os._exit(73)


def safety_worker(channel, receipt):
    approved = sha(ROOT / "app/harness/modelbased_v3.py")
    active, stopped, last, sequence = 0.0, False, time.monotonic(), 0
    trace = []
    deadline = time.monotonic() + 4
    channel.send({"ready": True})
    while time.monotonic() < deadline:
        if channel.poll(0.02):
            command = channel.recv()
            if command["kind"] == "finish":
                break
            if command["kind"] == "stop":
                active, stopped = 0.0, True
                trace.append({"kind": "manual_stop", "accepted": True, "actuator": 0.0})
                continue
            valid = (
                command.get("kind") == "action"
                and command.get("policy_sha256") == approved
                and command.get("candidate_kind") == "baseline"
                and command.get("mode") == "software_simulation"
                and command.get("sequence") == sequence + 1
                and isinstance(command.get("observed_at"), (int, float))
                and math.isfinite(command["observed_at"])
                and abs(time.time() - command.get("observed_at", 0)) <= 1
                and command.get("model_admitted") is True
            )
            accepted = bool(
                valid
                and not stopped
                and isinstance(command.get("action"), (int, float))
                and math.isfinite(command["action"])
                and 0 <= command["action"] <= 4
            )
            if accepted:
                sequence += 1
                last = time.monotonic()
                active = float(command["action"])
            trace.append(
                {"kind": command["kind"], "accepted": accepted, "mode": command.get("mode"), "actuator": active}
            )
        if active and time.monotonic() - last > 0.25:
            active, stopped = 0.0, True
            trace.append({"kind": "independent_watchdog_stop", "accepted": True, "actuator": 0.0})
    receipt.send({"process_id": os.getpid(), "trace": trace, "final_actuator": active, "production_authority": False})
    receipt.close()


def identify_capacity(rows, source_class):
    if not rows or any(
        not {"before", "arrival", "served", "after", "factor", "availability"} <= r.keys() for r in rows
    ):
        return {
            "status": "unidentifiable",
            "reason": "public arrival indicators do not observe service, queues or capacity",
            "field_calibrated": False,
        }
    for r in rows:
        values = [r[k] for k in ["before", "arrival", "served", "after", "factor", "availability"]]
        if (
            not all(isinstance(v, (int, float)) and np.isfinite(v) for v in values)
            or min(values) < 0
            or r["factor"] <= 0
            or not 0 < r["availability"] <= 1
            or abs(r["before"] + r["arrival"] - r["served"] - r["after"]) > 0.25
        ):
            return {
                "status": "rejected",
                "reason": "nonphysical or nonfinite service observations",
                "field_calibrated": False,
            }
    saturated = [r for r in rows if r["after"] > 1e-6]
    lower = max(r["served"] / (r["factor"] * r["availability"]) for r in rows)
    if len(saturated) < 3 or len({r["factor"] for r in saturated}) < 2:
        return {
            "status": "unidentifiable",
            "capacity_lower_bound": lower,
            "capacity_upper_bound": None,
            "reason": "cleared queues only give a lower bound; no upper-bound identification",
            "field_calibrated": False,
        }
    x = np.asarray([r["factor"] * r["availability"] for r in saturated])
    y = np.asarray([r["served"] for r in saturated])
    estimate = float(x @ y / (x @ x))
    radius = 1.96 * 0.1 / math_sqrt(float(x @ x))
    return {
        "status": "identified_in_declared_source",
        "estimate": estimate,
        "interval": [estimate - radius, estimate + radius],
        "measurement_sigma_assumed": 0.1,
        "observed_saturated_rows": len(saturated),
        "source_class": source_class,
        "field_calibrated": False,
        "notice": "Statistical model conditional on known actuation and measurement noise; not a field certificate.",
    }


def math_sqrt(value):
    return value**0.5


def identify_energy(rows, source_class):
    if len(rows) < 5 or any(not {"cranes", "power_kw"} <= r.keys() for r in rows):
        return {
            "status": "unidentifiable",
            "reason": "missing measured equipment/power pairs",
            "field_calibrated": False,
        }
    if any(
        not all(isinstance(r[k], (int, float)) and np.isfinite(r[k]) and r[k] >= 0 for k in ["cranes", "power_kw"])
        for r in rows
    ):
        return {
            "status": "rejected",
            "reason": "nonphysical or nonfinite equipment/power observations",
            "field_calibrated": False,
        }
    x = np.asarray([[1, r["cranes"]] for r in rows], dtype=float)
    y = np.asarray([r["power_kw"] for r in rows])
    if np.linalg.matrix_rank(x) < 2:
        return {
            "status": "unidentifiable",
            "reason": "unexcited equipment states; intercept and crane power alias",
            "field_calibrated": False,
        }
    coef = np.linalg.lstsq(x, y, rcond=None)[0]
    return {
        "status": "identified_in_declared_source",
        "base_power_kw": float(coef[0]),
        "per_crane_kw": float(coef[1]),
        "condition_number": float(np.linalg.cond(x)),
        "source_class": source_class,
        "field_calibrated": False,
    }


def _run_drill(children):
    ctx = mp.get_context("spawn")
    checks, cases = {}, []
    with tempfile.TemporaryDirectory(prefix="xiaoyi-v7-isolated-") as directory:
        folder = Path(directory)
        dbpath = folder / "actors.sqlite"
        keyfile = folder / "test-keys.json"
        keys = {k: os.urandom(32) for k in ["provider", "consumer"]}
        keyfile.write_text(json.dumps({k: v.hex() for k, v in keys.items()}))
        keyfile.chmod(0o600)

        def start():
            parent, child = ctx.Pipe(False)
            process = ctx.Process(target=actor_server, args=(str(dbpath), str(keyfile), child))
            process.start()
            children.append(process)
            if not parent.poll(10):
                raise RuntimeError("isolated actor service did not start")
            return process, parent.recv()

        def send(port, packet):
            parent, child = ctx.Pipe(False)
            process = ctx.Process(target=client_worker, args=(port, packet, child))
            process.start()
            children.append(process)
            if not parent.poll(10):
                raise RuntimeError("isolated client timed out")
            value = parent.recv()
            process.join(2)
            return value

        def count():
            with sqlite3.connect(dbpath) as db:
                return db.execute("SELECT COUNT(*) FROM events").fetchone()[0]

        def event(code, reply=None):
            now = datetime.now(timezone.utc).replace(microsecond=0)
            body = {
                "eventID": str(uuid.uuid4()),
                "eventUpdatedDateTime": now.isoformat(),
                "timestamp": {"classifierCode": code, "serviceDateTime": now.isoformat()},
            }
            if reply:
                body["replyToEventID"] = reply
            return body

        server, port = start()
        estimate = event("EST")
        packet = sign(estimate, "provider", keys["provider"])
        first = send(port, packet)
        retry = send(port, packet)
        checks["separate_actor_processes"] = first["actor_process_id"] != server.pid != os.getpid()
        checks["authenticated_estimate"] = first["status"] == 200 and count() == 1
        checks["idempotent_transport_retry"] = retry["body"].get("transport_retry") is True and count() == 1
        forged = copy.deepcopy(packet)
        forged["mac"] = "0" * 64
        wrong_role = sign(event("EST"), "consumer", keys["consumer"])
        stale = sign(event("EST"), "provider", keys["provider"], issued=time.time() - 600)
        future = sign(event("EST"), "provider", keys["provider"], issued=time.time() + 600)
        conflict = sign(event("EST"), "provider", keys["provider"], nonce=packet["nonce"])
        out_of_order = sign(event("PLN", str(uuid.uuid4())), "provider", keys["provider"])
        for name, fault in [
            ("forged_signature", forged),
            ("wrong_signed_role", wrong_role),
            ("expired_transport", stale),
            ("future_transport", future),
            ("nonce_conflict", conflict),
            ("out_of_order_plan", out_of_order),
        ]:
            before = count()
            response = send(port, fault)
            checks[name + "_blocked"] = response["status"] in [403, 422] and count() == before
            cases.append({"name": name, "response": response, "effect_count_unchanged": count() == before})
        request = event("REQ", estimate["eventID"])
        response = send(port, sign(request, "consumer", keys["consumer"]))
        planned = event("PLN", request["eventID"])
        planned["timestamp"]["serviceDateTime"] = request["timestamp"]["serviceDateTime"]
        response2 = send(port, sign(planned, "provider", keys["provider"]))
        checks["signed_erpa_negotiation"] = response["status"] == response2["status"] == 200 and count() == 3
        # Each crash request uses a valid fresh estimate, so a rejection cannot masquerade as crash recovery.
        before = count()
        crash = sign(event("EST"), "provider", keys["provider"], fault="before_commit")
        response = send(port, crash)
        server.join(3)
        checks["actual_precommit_process_crash"] = (
            server.exitcode == 71 and response["status"] == 0 and count() == before
        )
        server, port = start()
        crash = sign(event("EST"), "provider", keys["provider"], fault="after_commit")
        before = count()
        lost = send(port, crash)
        server.join(3)
        checks["actual_postcommit_lost_ack"] = server.exitcode == 72 and lost["status"] == 0 and count() == before + 1
        server, port = start()
        recovered = send(port, crash)
        checks["restart_retry_exactly_one_effect"] = (
            recovered["status"] == 200 and recovered["body"].get("transport_retry") is True and count() == before + 1
        )
        server.terminate()
        server.join(3)
        partition = send(port, sign(event("EST"), "provider", keys["provider"]))
        checks["network_partition_no_effect"] = partition["status"] == 0 and count() == before + 1
        # Independent virtual actuator worker. No real connector, production authority or HIL.
        parent, child = ctx.Pipe()
        recv, output = ctx.Pipe(False)
        worker = ctx.Process(target=safety_worker, args=(child, output))
        worker.start()
        children.append(worker)
        if not parent.poll(10):
            raise RuntimeError("safety worker not ready")
        assert parent.recv()["ready"]
        base = {
            "kind": "action",
            "mode": "software_simulation",
            "sequence": 1,
            "observed_at": time.time(),
            "action": 2,
            "model_admitted": True,
            "candidate_kind": "baseline",
            "policy_sha256": sha(ROOT / "app/harness/modelbased_v3.py"),
        }
        for altered in [
            {**base, "mode": "production"},
            {**base, "model_admitted": False},
            {**base, "observed_at": time.time() - 30},
            {**base, "sequence": 7},
            {**base, "action": 9},
            {**base, "policy_sha256": "0" * 64},
            {**base, "kind": "unknown"},
            {**base, "candidate_kind": "rl"},
        ]:
            parent.send(altered)
        planner = ctx.Process(target=planner_crash_worker, args=(parent, base))
        planner.start()
        children.append(planner)
        planner.join(3)
        checks["actual_planner_process_crash"] = planner.exitcode == 73
        time.sleep(0.4)
        parent.send({"kind": "finish"})
        if not recv.poll(5):
            raise RuntimeError("independent safety worker failed")
        safety = recv.recv()
        worker.join(2)
        checks["independent_governor_rejects_all_eight_faults"] = (
            len(safety["trace"]) >= 9
            and all(not r["accepted"] for r in safety["trace"][:8])
            and safety["trace"][8]["accepted"]
        )
        checks["independent_watchdog_stops_without_planner"] = safety["final_actuator"] == 0 and any(
            r["kind"] == "independent_watchdog_stop" for r in safety["trace"]
        )
        parent2, child2 = ctx.Pipe()
        recv2, output2 = ctx.Pipe(False)
        worker2 = ctx.Process(target=safety_worker, args=(child2, output2))
        worker2.start()
        children.append(worker2)
        if not parent2.poll(10):
            raise RuntimeError("manual-stop worker not ready")
        assert parent2.recv()["ready"]
        parent2.send({**base, "observed_at": time.time()})
        parent2.send({"kind": "stop"})
        parent2.send({**base, "observed_at": time.time(), "sequence": 2})
        parent2.send({"kind": "finish"})
        if not recv2.poll(5):
            raise RuntimeError("manual stop receipt absent")
        manual = recv2.recv()
        worker2.join(2)
        checks["manual_stop_latched_and_unconditional"] = (
            manual["final_actuator"] == 0
            and manual["trace"][1]["kind"] == "manual_stop"
            and not manual["trace"][2]["accepted"]
        )
        event_count = count()
        for child in children:
            if child.is_alive():
                child.terminate()
            child.join(2)
    # Public source provides arrivals only; the following calibration truth is injected and labelled.
    manifest_path = ROOT / "data/public/rl_v6_20261030/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    source = manifest["entries"][0]
    traffic_only = identify_capacity([{"arrival": 10}], "public_AIS_activity")
    saturated = [
        {"before": 100, "arrival": 30, "factor": f, "availability": 1, "served": 20 * f, "after": 130 - 20 * f}
        for f in [0.65, 0.85, 1.0, 1.15, 1.35]
    ]
    calibrated = identify_capacity(saturated, "injected_simulator_truth")
    energy_rows = [{"cranes": i % 4, "power_kw": 200 + 1000 * (i % 4)} for i in range(12)]
    power = identify_energy(energy_rows, "injected_simulator_truth")
    aliased = identify_energy([{"cranes": 2, "power_kw": 2200}] * 6, "injected_simulator_truth")
    checks["arrival_only_capacity_identification_blocked"] = traffic_only["status"] == "unidentifiable"
    checks["injected_capacity_and_energy_recovered_without_field_claim"] = (
        abs(calibrated["estimate"] - 20) < 1e-8
        and abs(power["per_crane_kw"] - 1000) < 1e-8
        and not calibrated["field_calibrated"]
        and not power["field_calibrated"]
    )
    checks["unexcited_power_parameters_blocked"] = aliased["status"] == "unidentifiable"
    return {
        "schema": "xiaoyi-assurance-rehearsal.v7",
        "passed": all(checks.values()),
        "checks": checks,
        "authenticated_cases": cases,
        "first_authentication_response": first,
        "persisted_event_count": event_count,
        "actor_key_fingerprints": {k: hashlib.sha256(v).hexdigest() for k, v in keys.items()},
        "safety_worker": safety,
        "manual_stop_worker": manual,
        "calibration": {
            "public_arrival_only": traffic_only,
            "synthetic_capacity": calibrated,
            "synthetic_energy": power,
            "unexcited_energy": aliased,
        },
        "source_public_activity": {
            "path": source["path"],
            "sha256": source["sha256"],
            "notice": "Traceable arrival-only source, never treated as observed queues, capacity or power.",
        },
        "official_standard_source": {
            "path": str((standard.STANDARD / "dcsa-pc200-openapi.yaml").relative_to(ROOT)),
            "sha256": sha(standard.STANDARD / "dcsa-pc200-openapi.yaml"),
        },
        "implementation": {"path": str(Path(__file__).relative_to(ROOT)), "sha256": sha(Path(__file__))},
        "external_institution_signoff": False,
        "field_calibration_completed": False,
        "hil_or_ot_certification": False,
        "production_authority": False,
        "notice": "Actual separate local client/server/safety processes, authenticated messages, SQLite transaction/crash/retry and virtual actuators. HMAC is a nonstandard local rehearsal transport, not DCSA conformance, public-key nonrepudiation or institutional independence. Injected calibration truth proves software recovery only; no actual terminal equipment or energy calibration.",
    }


def run_drill():
    children = []
    try:
        return _run_drill(children)
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
            child.join(2)
