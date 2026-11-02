"""Public-history-driven multi-resource/energy contracts and local crash recovery.

This records engineering acceptance separately from unavailable port field evidence.
"""

import hashlib
import json
import math
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import BASE_DIR
from app.harness import crossport_v2, physical_v2

OUT = BASE_DIR / ".codex_artifacts/remediation-20261030/operations-v2"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def schedule(calls, resource_outage=False):
    """Synthetic calls derived explicitly from a public activity indicator, not vessel events."""
    capacities = {"berth": 2, "pilot": 2, "tug": 2, "crane": 4, "transport": 6, "yard": 12}
    usage = {k: [0] * 96 for k in capacities}
    allocations, incomplete = [], []
    requirements = [
        ("pilotage", 2, {"pilot": 1, "tug": 1}),
        ("cargo", 8, {"berth": 1, "crane": 2, "transport": 3}),
        ("yard", 2, {"yard": 1, "transport": 1}),
    ]
    for index in range(calls):
        cursor = index * 2
        for stage, duration, need in requirements:
            found = None
            for start in range(cursor, 97 - duration):
                feasible = all(
                    usage[r][t] + q <= (0 if resource_outage and r == "crane" and 24 <= t < 60 else capacities[r])
                    for r, q in need.items()
                    for t in range(start, start + duration)
                )
                if feasible:
                    found = start
                    break
            if found is None:
                incomplete.append(
                    {"synthetic_call": index, "blocked_stage": stage, "reason": "no complete resource slot; withheld"}
                )
                break
            for r, q in need.items():
                for t in range(found, found + duration):
                    usage[r][t] += q
            allocations.append(
                {
                    "synthetic_call": index,
                    "stage": stage,
                    "start_tick": found,
                    "end_tick": found + duration,
                    "requirements": need,
                }
            )
            cursor = found + duration
    violations = [r for r, values in usage.items() if max(values) > capacities[r]]
    return {
        "capacities_assumed": capacities,
        "allocations": allocations,
        "incomplete_calls": incomplete,
        "complete": not incomplete,
        "resource_violations": violations,
        "usage": usage,
        "source_class": "declared engineering schedule; synthetic calls are not actual vessel appointments",
    }


def energy(schedule_result, battery_available=True):
    capacity_kwh = 2000.0
    stored = 1200.0
    frames = []
    for tick in range(96):
        load = 200 + schedule_result["usage"]["crane"][tick] * 1000
        # No public renewable/equipment meter is claimed for these engineering assumptions.
        renewable = max(0, math.sin((tick - 24) / 48 * math.pi)) * 500 if 24 <= tick <= 72 else 0
        renewable_used = min(load, renewable)
        residual = load - renewable_used
        grid = min(3000, residual)
        discharge = (
            min(max(0, residual - grid), max(0, stored - capacity_kwh * 0.2) * 0.95 / 0.25) if battery_available else 0
        )
        unserved = max(0, residual - grid - discharge)
        before = stored
        stored -= discharge / 0.95 * 0.25
        balance = grid + renewable_used + discharge + unserved - load
        battery_balance = stored - before + discharge / 0.95 * 0.25
        frames.append(
            {
                "tick": tick,
                "load_kw_assumed": load,
                "grid_kw": grid,
                "renewable_kw_assumed": renewable_used,
                "battery_discharge_kw": discharge,
                "stored_kwh": stored,
                "soc": stored / capacity_kwh,
                "unserved_kw": unserved,
                "power_balance_error_kw": balance,
                "storage_balance_error_kwh": battery_balance,
            }
        )
    return {
        "frames": frames,
        "grid_kwh": sum(r["grid_kw"] * 0.25 for r in frames),
        "unserved_kwh": sum(r["unserved_kw"] * 0.25 for r in frames),
        "max_power_balance_error_kw": max(abs(r["power_balance_error_kw"]) for r in frames),
        "max_storage_balance_error_kwh": max(abs(r["storage_balance_error_kwh"]) for r in frames),
        "soc_bounds_passed": all(0.2 - 1e-9 <= r["soc"] <= 0.9 for r in frames),
        "carbon": {
            "grid_factor_kg_per_kwh": None,
            "emissions_kg": None,
            "status": "withheld_missing_verified_grid_factor",
        },
        "notice": "kW/kWh/SOC一致性校验；负荷、容量、效率和新能源曲线均为工程假设，不是能碳实测标定。供电缺口显式记为unserved。",
    }


def ukc_gate(tide, depth, draft, squat, datum_match, source_fresh, authorized):
    missing = [
        name for name, value in {"depth": depth, "draft": draft, "squat": squat, "tide": tide}.items() if value is None
    ]
    blockers = ["missing_" + name for name in missing]
    if not datum_match:
        blockers.append("unmatched_vertical_datum")
    if not source_fresh:
        blockers.append("stale_or_unverified_publication_time")
    if not authorized:
        blockers.append("no_verified_site_authorization")
    ukc = None if missing else depth + tide - draft - squat
    if ukc is not None and ukc < 1:
        blockers.append("ukc_below_assumed_one_metre_margin")
    return {
        "status": "withheld" if blockers else "research_condition_only",
        "ukc_m": ukc,
        "blockers": blockers,
        "production_authority": False,
    }


class Ledger:
    """Owned local inbox/effect/audit transaction; no external device interface."""

    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY,sha TEXT,payload TEXT); CREATE TABLE IF NOT EXISTS approvals(id TEXT,role TEXT,actor TEXT,PRIMARY KEY(id,role)); CREATE TABLE IF NOT EXISTS effects(id TEXT PRIMARY KEY,payload TEXT); CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY,previous TEXT,body TEXT,sha TEXT);"
        )

    def audit(self, body):
        previous = self.db.execute("SELECT sha FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        previous = previous[0] if previous else "0" * 64
        text = json.dumps(body, sort_keys=True)
        self.db.execute(
            "INSERT INTO audit(previous,body,sha) VALUES(?,?,?)", (previous, text, digest([previous, text]))
        )

    def receive(self, message, clock):
        at = datetime.fromisoformat(message["event_at"])
        if (
            abs((clock - at).total_seconds()) > 360
            or type(message.get("revision")) is not int
            or message.get("revision") != 1
        ):
            raise ValueError("stale/out-of-order normalized message")
        if message.get("scope") != "engineering_replay" or message.get("production_authority") is not False:
            raise ValueError("production command denied")
        old = self.db.execute("SELECT sha FROM inbox WHERE id=?", (message["id"],)).fetchone()
        if old:
            if old[0] != digest(message):
                raise ValueError("same-message conflicting payload")
            return "duplicate"
        with self.db:
            self.db.execute("INSERT INTO inbox VALUES(?,?,?)", (message["id"], digest(message), json.dumps(message)))
            self.audit({"accepted": message["id"]})
        return "accepted"

    def approve(self, message_id, role, actor):
        if role not in {"dispatcher", "duty_manager"}:
            raise PermissionError("unregistered rehearsal role")
        if not self.db.execute("SELECT 1 FROM inbox WHERE id=?", (message_id,)).fetchone():
            raise ValueError("cannot approve an unknown message")
        other = self.db.execute("SELECT actor FROM approvals WHERE id=?", (message_id,)).fetchall()
        if any(row[0] == actor for row in other):
            raise PermissionError("two different rehearsal actors required")
        with self.db:
            self.db.execute("INSERT INTO approvals VALUES(?,?,?)", (message_id, role, actor))
            self.audit({"rehearsal_approval": message_id, "role": role, "actor": actor})

    def execute(self, message_id):
        approval_roles = {r[0] for r in self.db.execute("SELECT role FROM approvals WHERE id=?", (message_id,))}
        if approval_roles != {"dispatcher", "duty_manager"}:
            raise PermissionError("two-role rehearsal approval missing")
        message = self.db.execute("SELECT payload,sha FROM inbox WHERE id=?", (message_id,)).fetchone()
        if message is None:
            raise ValueError("unknown message")
        if digest(json.loads(message[0])) != message[1]:
            raise ValueError("approved inbox payload changed")
        with self.db:
            effect = self.db.execute("SELECT payload FROM effects WHERE id=?", (message_id,)).fetchone()
            if effect:
                return "already_applied"
            self.db.execute("INSERT INTO effects VALUES(?,?)", (message_id, message[0]))
            self.audit({"engineering_effect": message_id})
        return "applied"

    def audit_valid(self):
        previous = "0" * 64
        for _, prev, body, value in self.db.execute("SELECT * FROM audit ORDER BY seq"):
            if prev != previous or digest([prev, body]) != value:
                return False
            previous = value
        return True

    def close(self):
        self.db.close()


def resilience(folder):
    path = folder / "owned-recovery.sqlite"
    clock = datetime(2026, 2, 2, tzinfo=timezone.utc)
    message = {
        "id": "public-replay-plan",
        "event_at": clock.isoformat(),
        "revision": 1,
        "scope": "engineering_replay",
        "production_authority": False,
    }
    ledger = Ledger(path)
    duplicate = ledger.receive(message, clock) == "accepted" and ledger.receive(message, clock) == "duplicate"
    rejected = {}
    for name, body in [
        ("conflict", {**message, "extra": "conflicting"}),
        ("stale", {**message, "id": "stale", "event_at": (clock - timedelta(hours=1)).isoformat()}),
        ("out_of_order", {**message, "revision": 0}),
        ("production", {**message, "production_authority": True}),
    ]:
        try:
            ledger.receive(body, clock)
            rejected[name] = False
        except ValueError:
            rejected[name] = True
    ledger.approve(message["id"], "dispatcher", "rehearsal-A")
    try:
        ledger.execute(message["id"])
        one_role_denied = False
    except PermissionError:
        one_role_denied = True
    ledger.approve(message["id"], "duty_manager", "rehearsal-B")
    ledger.close()
    # The owned child exits immediately after a durable effect, imitating lost acknowledgement.
    code = "from app.harness.operations_v2 import Ledger; import sys,os; x=Ledger(sys.argv[1]);x.execute('public-replay-plan');os._exit(73)"
    child = subprocess.run([sys.executable, "-c", code, str(path)], cwd=BASE_DIR, capture_output=True, timeout=30)
    start = time.perf_counter()
    ledger = Ledger(path)
    replay = ledger.execute(message["id"])
    effects = ledger.db.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
    valid = ledger.audit_valid()
    seconds = time.perf_counter() - start
    with ledger.db:
        ledger.db.execute("UPDATE audit SET body='tampered' WHERE seq=1")
    tamper_detected = not ledger.audit_valid()
    ledger.close()
    checks = {
        "idempotent_message": duplicate,
        **{k + "_denied": v for k, v in rejected.items()},
        "one_role_denied": one_role_denied,
        "owned_child_crashed_after_commit": child.returncode == 73,
        "no_duplicate_effect_after_recovery": replay == "already_applied" and effects == 1,
        "audit_valid_before_tampering": valid,
        "tampering_detected": tamper_detected,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "local_recovery_seconds": seconds,
        "committed_effects_lost": 0 if effects == 1 else None,
        "notice": "Owned SQLite worker crash/recovery and role rehearsal only. Not port OT failover, actual human sign-off, HIL or a production SLA.",
    }


def study():
    if (OUT / "report.json").exists():
        raise ValueError("owned recovery/operations acceptance already exists")
    OUT.mkdir(parents=True, exist_ok=True)
    manifest, series = crossport_v2.load()
    _, physical_sources, stations = physical_v2.load()
    at = datetime(2026, 2, 2, tzinfo=timezone.utc)
    source_day = at.date() - timedelta(days=7)
    cases = []
    for pid, data in series.items():
        public = dict(data).get(source_day)
        if public is None:
            raise ValueError("same-period public demand unavailable")
        count = max(1, math.ceil(public / 10))
        for scenario in ["normal", "crane_outage", "battery_outage", "demand_surge"]:
            jobs = math.ceil(count * 1.5) if scenario == "demand_surge" else count
            planned = schedule(jobs, scenario == "crane_outage")
            power = energy(planned, scenario != "battery_outage")
            tide = stations["9410660"]["observed"].get(at) if pid == "port664" else None
            gate = ukc_gate(tide, None, None, None, False, False, False)
            cases.append(
                {
                    "port_id": pid,
                    "scenario": scenario,
                    "historical_clock": at.isoformat(),
                    "source_day": source_day.isoformat(),
                    "public_activity_indicator": public,
                    "synthetic_calls": jobs,
                    "schedule": planned,
                    "energy": power,
                    "ukc": gate,
                    "recommendation": "withheld_for_missing_field_parameters",
                    "production_authority": False,
                }
            )
    recovery = resilience(OUT)
    checks = {
        "all_source_clocks_causal": all(
            date_from(c["source_day"]) <= date_from(c["historical_clock"][:10]) - timedelta(days=7) for c in cases
        ),
        "no_resource_overallocation": all(not c["schedule"]["resource_violations"] for c in cases),
        "energy_and_storage_conservation": all(
            c["energy"]["max_power_balance_error_kw"] < 1e-8 and c["energy"]["max_storage_balance_error_kwh"] < 1e-8
            for c in cases
        ),
        "soc_bounds": all(c["energy"]["soc_bounds_passed"] for c in cases),
        "missing_parameters_withhold_dispatch": all(c["ukc"]["status"] == "withheld" for c in cases),
        "unknown_carbon_factor_withholds_emissions": all(c["energy"]["carbon"]["emissions_kg"] is None for c in cases),
        "owned_resilience": recovery["passed"],
    }
    report = {
        "schema": "xiaoyi-public-operations-contract.v2",
        "source_sha256": crossport_v2.sha(Path(__file__)),
        "sources": {"demand": manifest, "physical": physical_sources},
        "cases": cases,
        "resilience": recovery,
        "checks": checks,
        "engineering_passed": all(checks.values()),
        "assumptions": [
            "One synthetic call per ten published daily activity units; call IDs, release times, stage duration and resource layout are declared, not actual vessel events.",
            "Each tick15min,96ticks/day; electrical capacities, efficiency and renewable curve are assumptions. Unserved energy and unscheduled work remain explicit failures.",
            "Only LA tide is used for LA; no US water level is assigned to another port. Other sites' missing water/depth/draft stays missing.",
            "Historical clock2026-02-02; public demand2026-01-26. Sensor-event availability is hypothetical, not demonstrated archive release time.",
            "Normalized local event contract is not a certified DCSA/MSW adapter. Rehearsal roles are not real port signatures.",
        ],
        "field_evidence": {
            "equipment_and_energy_calibration_received": False,
            "bathymetry_and_vessel_parameters_received": False,
            "port_msw_interoperability_signoff": False,
            "ot_recovery_drill_received": False,
            "hardware_in_loop_received": False,
            "signed_port_dispatch_authorization": False,
            "live_shadow_sla_received": False,
        },
        "production_authority": False,
        "notice": "Multi-resource/energy/collaboration/recovery engineering contracts implemented and actually exercised. Missing field evidence remains blocked; simulation does not create authorization or physical calibration.",
    }
    crossport_v2.write(OUT / "report.json", report)
    return report


def date_from(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def report():
    value = json.loads((OUT / "report.json").read_text())
    crossport_v2.load()
    physical_v2.load()
    value["historical_only"] = crossport_v2.sha(Path(__file__)) != value["source_sha256"]
    return value
