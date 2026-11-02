"""Build a declared engineering site clock; original source clocks are kept separately."""

from datetime import datetime, timedelta, timezone
from copy import deepcopy
import math

RESOURCES = {
    "channel_slot": (1, "slot"),
    "berth": (2, "berth"),
    "pilot": (2, "person"),
    "tug": (2, "tug"),
    "quay_crane": (4, "crane"),
    "horizontal_transport": (5, "vehicle"),
    "yard_block": (120, "teu_slot"),
    "gate": (2, "lane"),
    "rail": (1, "train_slot"),
    "shore_power_bess": (6000, "kilowatt"),
    "maintenance_team": (1, "crew"),
}
REQUIRES = {
    "port_arrival": {"channel_slot": 1},
    "channel_transit": {"channel_slot": 1, "pilot": 1, "tug": 1},
    "berthing": {"berth": 1},
    "cargo_operation": {
        "berth": 1,
        "quay_crane": 2,
        "horizontal_transport": 3,
        "yard_block": 30,
        "shore_power_bess": 2500,
    },
    "yard_transfer": {"horizontal_transport": 3, "yard_block": 30},
    "yard_operation": {"yard_block": 30},
    "gate_release": {"gate": 1},
    "rail_release": {"rail": 1},
    "maintenance": {"maintenance_team": 1, "quay_crane": 1},
}
PREDS = {
    "port_arrival": [],
    "channel_transit": ["port_arrival"],
    "berthing": ["channel_transit"],
    "cargo_operation": ["berthing"],
    "yard_transfer": ["cargo_operation"],
    "yard_operation": ["yard_transfer"],
    "gate_release": ["yard_operation"],
    "rail_release": ["yard_operation"],
    "maintenance": ["cargo_operation"],
}
BINDINGS = [
    "site_twin_calibration_evidence_digest",
    "port_call_collaboration_evidence_digest",
    "forecast_uncertainty_evidence_digest",
    "execution_acceptance_evidence_digest",
    "business_benefit_attribution_evidence_digest",
]


def bundle(job):
    from app.harness.contracts import digest

    epoch = datetime(2026, 10, 29, tzinfo=timezone.utc)

    def iso(m):
        return (epoch + timedelta(minutes=m)).isoformat().replace("+00:00", "Z")

    result = job["results"]
    native = result["sailing"]["data"]["raw"]["validation"]
    seconds = native["simulatedDurationSeconds"]
    transport = result["transport"]["data"]
    route = transport["selected"]["validation"]
    durations = {
        "port_arrival": 15,
        "channel_transit": 30,
        "berthing": 30,
        "cargo_operation": 60,
        "yard_transfer": max(15, math.ceil(route["makespan_seconds"] / 900) * 15),
        "yard_operation": 30,
        "gate_release": 30,
        "rail_release": 30,
        "maintenance": 30,
    }
    requirements = deepcopy(REQUIRES)
    active_vehicles = route["vehicles_used"]
    if not 1 <= active_vehicles <= RESOURCES["horizontal_transport"][0]:
        raise ValueError("transport exceeds available native fleet resource capacity")
    requirements["yard_transfer"]["horizontal_transport"] = active_vehicles
    requirements["cargo_operation"]["horizontal_transport"] = active_vehicles
    tasks = []
    for c in [1, 2]:
        end = {}
        cursor = max(60, math.ceil(seconds / 900) * 15)
        for stage, needs in requirements.items():
            start = max([cursor, *[end[p] + 15 for p in PREDS[stage]]])
            duration = durations[stage]
            end[stage] = start + duration
            if stage not in ["gate_release", "rail_release", "maintenance"]:
                cursor = end[stage] + 15
            tasks.append(
                {
                    "task_id": f"task.{c:02}.{stage}",
                    "chain_id": f"chain.{c:02}",
                    "stage": stage,
                    "priority": 5 if c == 1 else 3,
                    "earliest_start": iso(start),
                    "baseline_start": iso(start),
                    "baseline_end": iso(start + duration),
                    "deadline": iso(1200),
                    "duration_minutes": duration,
                    "frozen": False,
                    "predecessor_ids": [f"task.{c:02}.{p}" for p in PREDS[stage]],
                    "resource_requirements": needs,
                    "baseline_allocations": [{"resource_id": "res." + r, "quantity": q} for r, q in needs.items()],
                    "source_reference": f"{job['id']}.declared.chain.{c}",
                    "forecast_receipt_id": "transport." + transport["case_sha256"][:24],
                    "baseline_plan_receipt_id": "plan." + job["plan_sha256"][:24],
                }
            )
    return {
        "schema_version": "end_to_end_coordination_dataset.v1",
        "site_id": "xiaoyi-joint-engineering-lab",
        "run_id": job["id"],
        "planning_revision": 1,
        "source": {
            "source_system": "xiaoyi-federated-engineering-mapping",
            "owner": "xiaoyi-local-simulation",
            "license": "local-declared-engineering-fixture",
            "timezone": "UTC",
            "extracted_at": iso(0),
            "evidence_class": "contract_test_only",
        },
        "bindings": {
            k: digest({"receipts": {s: r["sha256"] for s, r in result.items()}, "purpose": k, "site_authorized": False})
            for k in BINDINGS
        },
        "planning": {
            "plan_id": job["id"] + ".plan",
            "plan_system_reference": "xiaoyi.joint.lab.v2",
            "decision_at": iso(0),
            "horizon_start": iso(0),
            "horizon_end": iso(1440),
            "time_step_minutes": 15,
            "freeze_horizon_minutes": 30,
            "handoff_buffer_minutes": 15,
            "maximum_reschedule_minutes": 180,
            "objective_weights": {
                "vessel_and_cargo_delay": 0.35,
                "plan_stability": 0.20,
                "energy_peak": 0.15,
                "resource_balance": 0.15,
                "maintenance_risk": 0.15,
            },
        },
        "resources": [
            {
                "resource_id": "res." + r,
                "resource_type": r,
                "capacity": q,
                "capacity_unit": u,
                "available_from": iso(0),
                "available_to": iso(1440),
                "owner": "lab.owner." + r,
                "source_reference": "declared.lab.capacity." + r,
                "safety_interlock_reference": "native.capacity." + r,
            }
            for r, (q, u) in RESOURCES.items()
        ],
        "tasks": tasks,
        "safety_incident_count": 0,
        "unresolved_exception_ids": [],
    }
