"""Atomic energy-aware scheduling and official PC2-derived local contract/fault drills."""

import copy
import csv
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from app.harness import operations_v2 as old

OUT = old.BASE_DIR / ".codex_artifacts/remediation-v3-20261030/operations"
STANDARD = old.BASE_DIR / "data/public/port_standards_v3_20261030"


def schedule(calls, resource_outage=False):
    capacities = {"berth": 2, "pilot": 2, "tug": 2, "crane": 4, "transport": 6, "yard": 12}
    usage = {k: [0] * 96 for k in capacities}
    stages = [("pilotage", 2, {"pilot": 1, "tug": 1}),
              ("cargo", 8, {"berth": 1, "crane": 2, "transport": 3}),
              ("yard", 2, {"yard": 1, "transport": 1})]
    allocations, incomplete = [], []
    for call in range(calls):
        candidate_usage = copy.deepcopy(usage)
        pending, cursor = [], call * 2
        for stage, duration, needs in stages:
            found = None
            for start in range(cursor, 97 - duration):
                feasible = all(candidate_usage[r][t] + q <= (0 if resource_outage and r == "crane" and 24 <= t < 60 else capacities[r])
                               for r, q in needs.items() for t in range(start, start + duration))
                # Reserve only firm grid supply: solar and battery are not guaranteed for jobs.
                power_ok = all(200 + 1000 * (candidate_usage["crane"][t] + needs.get("crane", 0)) <= 3000
                               for t in range(start, start + duration))
                if feasible and power_ok:
                    found = start
                    break
            if found is None:
                incomplete.append({"synthetic_call": call, "blocked_stage": stage,
                                   "reason": "no complete resource+firm-energy slot; entire uncommitted call deferred"})
                break
            for resource, quantity in needs.items():
                for tick in range(found, found + duration):
                    candidate_usage[resource][tick] += quantity
            pending.append({"synthetic_call": call, "stage": stage, "start_tick": found,
                            "end_tick": found + duration, "requirements": needs})
            cursor = found + duration
        else:
            usage = candidate_usage
            allocations.extend(pending)
    return {"capacities_assumed": capacities, "allocations": allocations, "incomplete_calls": incomplete,
            "complete": not incomplete, "usage": usage,
            "resource_violations": [r for r, values in usage.items() if max(values) > capacities[r]],
            "atomic_call_reservation": True, "firm_grid_kw_assumed": 3000,
            "source_class": "public-indicator-driven synthetic orders, declared equipment and power assumptions"}


def schema_validate(value, schema, root, path="$"):
    """Validate the official schema subset used by these fixtures; no remote refs or code."""
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/components/schemas/"):
            raise ValueError("unsupported reference")
        schema_validate(value, root["components"]["schemas"][ref.split("/")[-1]], root, path)
    for sub in schema.get("allOf", []):
        schema_validate(value, sub, root, path)
    kind = schema.get("type")
    checks = {"object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list),
              "string": lambda x: isinstance(x, str), "boolean": lambda x: type(x) is bool,
              "number": lambda x: type(x) in [float, int] and math.isfinite(x),
              "integer": lambda x: type(x) is int}
    if kind in checks and not checks[kind](value):
        raise ValueError(path + ": invalid official schema type")
    if isinstance(value, dict):
        if not set(schema.get("required", [])) <= value.keys():
            raise ValueError(path + ": required property missing")
        for k, v in value.items():
            if k in schema.get("properties", {}):
                schema_validate(v, schema["properties"][k], root, path + "." + k)
    if isinstance(value, list):
        for item in value:
            schema_validate(item, schema.get("items", {}), root, path + "[]")
    if isinstance(value, str):
        if len(value) > schema.get("maxLength", float("inf")):
            raise ValueError(path + ": too long")
        if schema.get("format") == "uuid":
            uuid.UUID(value)
        if schema.get("format") == "date-time":
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError(path + ": timezone required")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(path + ": enum violation")


class Negotiation:
    """One BERTH E-R-P-A rehearsal subset, never a production endpoint."""

    def __init__(self, schema):
        self.schema = schema
        self.events = {}
        self.latest = None

    def receive(self, event, actor, clock, connected=True):
        if not connected:
            raise ConnectionError("partition; no dispatch/effect")
        schema_validate(event, self.schema["components"]["schemas"]["Event"], self.schema)
        required = {"eventID", "eventUpdatedDateTime", "timestamp"}
        if not required <= event.keys() or not {"classifierCode", "serviceDateTime"} <= event["timestamp"].keys():
            raise ValueError("rehearsal required business fields missing")
        at = datetime.fromisoformat(event["eventUpdatedDateTime"].replace("Z", "+00:00"))
        if abs((clock - at).total_seconds()) > 300:
            raise ValueError("stale/future technical clock")
        identifier = event["eventID"]
        classifier = event["timestamp"]["classifierCode"]
        if classifier not in {"EST", "REQ", "PLN", "ACT"}:
            raise ValueError("unknown timestamp classifier")
        if actor != ("consumer" if classifier == "REQ" else "provider"):
            raise PermissionError("timestamp ownership mismatch")
        if identifier in self.events:
            if old.digest(event) == old.digest(self.events[identifier]):
                return "duplicate"
            raise ValueError("event identity conflict")
        previous = self.events.get(event.get("replyToEventID"))
        if classifier == "REQ" and (previous is None or previous["timestamp"]["classifierCode"] != "EST"):
            raise ValueError("request must reply to an estimate in this rehearsal")
        if classifier == "PLN":
            if previous is None or previous["timestamp"]["classifierCode"] != "REQ" or previous["eventID"] != self.latest:
                raise ValueError("plan must confirm latest request")
            if datetime.fromisoformat(event["timestamp"]["serviceDateTime"].replace("Z", "+00:00")) != datetime.fromisoformat(previous["timestamp"]["serviceDateTime"].replace("Z", "+00:00")):
                raise ValueError("planned timestamp differs from requested timestamp")
        if classifier == "ACT" and (self.latest is None or self.events[self.latest]["timestamp"]["classifierCode"] != "PLN"):
            raise ValueError("actual requires accepted plan in this rehearsal")
        if classifier == "ACT" and datetime.fromisoformat(event["timestamp"]["serviceDateTime"].replace("Z", "+00:00")) > clock:
            raise ValueError("actual event cannot describe a future execution")
        self.events[identifier] = copy.deepcopy(event)
        self.latest = identifier
        return "accepted_local_rehearsal"


def contract_drill():
    schema = yaml.safe_load((STANDARD / "dcsa-pc200-openapi.yaml").read_text())
    clock = datetime(2026, 2, 2, tzinfo=timezone.utc)
    negotiation = Negotiation(schema)
    events = []
    for code, actor in [("EST", "provider"), ("REQ", "consumer"), ("PLN", "provider"), ("ACT", "provider")]:
        event_clock = clock + timedelta(hours=2) if code == "ACT" else clock
        event = {"eventID": str(uuid.uuid5(uuid.NAMESPACE_URL, "xiaoyi-rehearsal-" + code)),
                 "eventUpdatedDateTime": event_clock.isoformat(),
                 "timestamp": {"classifierCode": code, "serviceDateTime": (clock + timedelta(hours=2)).isoformat()}}
        if events:
            event["replyToEventID"] = events[-1]["eventID"]
        negotiation.receive(event, actor, event_clock)
        events.append(event)
    checks = {"official_schema_fixture": True, "erpa_happy_path": True,
              "idempotent": negotiation.receive(events[-1], "provider", clock + timedelta(hours=2)) == "duplicate"}
    faults = [
        ("wrong_actor", {**events[0], "eventID": str(uuid.uuid4())}, "consumer", clock, True),
        ("identity_conflict", {**events[-1], "isFYI": True}, "provider", clock, True),
        ("missing_fields", {"eventID": str(uuid.uuid4())}, "provider", clock, True),
        ("invalid_uuid", {**events[0], "eventID": "not-a-uuid"}, "provider", clock, True),
        ("naive_clock", {**events[0], "eventUpdatedDateTime": "2026-02-02T00:00:00"}, "provider", clock, True),
        ("future_clock", {**events[0], "eventID": str(uuid.uuid4())}, "provider", clock - timedelta(hours=1), True),
        ("network_partition", {**events[0], "eventID": str(uuid.uuid4())}, "provider", clock, False),
        ("unknown_classifier", {**events[0], "eventID": str(uuid.uuid4()), "timestamp": {**events[0]["timestamp"], "classifierCode": "BAD"}}, "provider", clock, True),
        ("plan_wrong_time", {**events[2], "eventID": str(uuid.uuid4()), "timestamp": {**events[2]["timestamp"], "serviceDateTime": (clock + timedelta(hours=3)).isoformat()}}, "provider", clock, True),
        ("actual_without_plan", {**events[3], "eventID": str(uuid.uuid4())}, "provider", clock, True),
    ]
    for name, event, actor, now, connected in faults:
        before = len(negotiation.events)
        try:
            negotiation.receive(event, actor, now, connected)
            checks[name + "_rejected"] = False
        except (ValueError, PermissionError, ConnectionError):
            checks[name + "_rejected"] = len(negotiation.events) == before
    return {"checks": checks, "passed": all(checks.values()), "accepted_fixtures": events,
            "schema_version": schema["info"]["version"], "external_conformance_completed": False,
            "notice": "Official OpenAPI schema subset plus BERTH E-R-P-A business rehearsal. No external DCSA sandbox, MSW signoff, real actor authentication or production dispatch. Unknown schema constructs are not represented as fully validated."}


def study():
    if (OUT / "report.json").exists():
        raise ValueError("immutable operations evidence")
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = old.BASE_DIR / "data/public/portwatch_v3_20261030/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    cases = []
    for entry in manifest["entries"]:
        with (old.BASE_DIR / entry["path"]).open() as handle:
            row = next(r for r in csv.DictReader(handle) if r["date"] == "2026-01-26")
        public = float(row["portcalls"])
        for scenario in ["normal", "crane_outage", "battery_outage", "demand_surge"]:
            calls = max(1, math.ceil(public / 10 * (1.5 if scenario == "demand_surge" else 1)))
            before = old.schedule(calls, scenario == "crane_outage")
            after = schedule(calls, scenario == "crane_outage")
            old_energy = old.energy(before, scenario != "battery_outage")
            new_energy = old.energy(after, scenario != "battery_outage")
            complete_ids = {a["synthetic_call"] for a in after["allocations"] if a["stage"] == "yard"}
            checks = {"no_resource_overallocation": not after["resource_violations"],
                      "no_unserved_energy": new_energy["unserved_kwh"] <= 1e-9,
                      "all_committed_calls_complete": all(a["synthetic_call"] in complete_ids for a in after["allocations"]),
                      "deferred_calls_conserved": len(complete_ids) + len(after["incomplete_calls"]) == calls,
                      "power_conserved": new_energy["max_power_balance_error_kw"] < 1e-8,
                      "storage_conserved": new_energy["max_storage_balance_error_kwh"] < 1e-8,
                      "soc_safe": new_energy["soc_bounds_passed"]}
            cases.append({"port_id": entry["id"], "port": entry["name"], "scenario": scenario,
                          "public_day": "2026-01-26", "decision_day": "2026-02-02", "public_indicator": public,
                          "synthetic_calls": calls, "completed_calls": len(complete_ids),
                          "before_unserved_kwh": old_energy["unserved_kwh"], "after_unserved_kwh": new_energy["unserved_kwh"],
                          "old_incomplete_calls": len(before["incomplete_calls"]), "deferred_calls": after["incomplete_calls"],
                          "schedule": after, "energy": new_energy, "checks": checks,
                          "ukc": old.ukc_gate(None, None, None, None, False, False, False)})
    contracts = contract_drill()
    resilience = old.resilience(OUT)
    result = {"schema": "xiaoyi-operational-remediation.v3", "source_sha256": __import__("hashlib").sha256(Path(__file__).read_bytes()).hexdigest(),
        "sources": {"ports": manifest, "standards": json.loads((STANDARD / "manifest.json").read_text())},
        "cases": cases, "contracts": contracts, "resilience": resilience,
        "engineering_passed": all(all(r["checks"].values()) for r in cases) and contracts["passed"] and resilience["passed"],
        "field_evidence": {k: False for k in ["equipment_and_energy_calibration_received", "bathymetry_and_vessel_parameters_received",
            "port_msw_interoperability_signoff", "ot_recovery_drill_received", "hardware_in_loop_received",
            "signed_port_dispatch_authorization", "live_shadow_sla_received"]},
        "assumptions": ["Public indicators map to synthetic calls at1order/10indicator, minimum1; no real vessel appointments.",
            "Equipment/stage durations,200kWbase,1000kW/crane,3000kWfirmgrid and battery/solar are declared engineering assumptions.",
            "Atomic whole-call reservations prevent orphan work; firm-power gating may defer more calls. Deferrals remain unmet service, not completed cargo.",
            "PC2 official schema subset and local actor roles do not establish full OpenAPI conformance, signed institutional identity or formal MSW interoperability.",
            "Network partition and crash drills affect owned local state only. No HIL/OT or live-port authority is inferred."],
        "production_authority": False}
    from app.harness.crossport_v2 import write
    write(OUT / "report.json", result)
    print("OPERATIONS_V3", result["engineering_passed"], "cases", len(cases),
          "deferred_cases", sum(bool(r["deferred_calls"]) for r in cases), flush=True)


if __name__ == "__main__":
    study()
