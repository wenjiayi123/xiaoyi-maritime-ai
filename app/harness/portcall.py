"""Bounded historical PortCDM/JIT experiments over a local normalized contract.

This is not a DCSA wire adapter or a vessel movement clearance.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from app.harness.contracts import StrictModel, digest

CAPACITIES = {"channel": 1, "pilot": 2, "tug": 2, "berth": 2, "crane": 4, "power_kw": 6000}


class Event(StrictModel):
    event_id: str = Field(min_length=1, max_length=100)
    call_id: str = Field(min_length=1, max_length=100)
    classifier: Literal["ESTIMATED", "REQUESTED", "PLANNED", "ACTUAL"]
    revision: int = Field(ge=1, le=10000)
    event_time: datetime
    received_at: datetime
    source_party: str = Field(min_length=1, max_length=100)
    source_reference: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def timezone(self):
        if self.event_time.tzinfo is None or self.received_at.tzinfo is None:
            raise ValueError("port call events require timezone")
        return self


class Call(StrictModel):
    call_id: str = Field(min_length=1, max_length=100)
    service_minutes: int = Field(60, ge=5, le=720, multiple_of=5)
    arrival_uncertainty_minutes: int = Field(15, ge=0, le=120, multiple_of=5)
    deadline_minutes: int = Field(720, ge=5, le=1440, multiple_of=5)
    crane_count: int = Field(2, ge=1, le=10)
    shore_power_kw: int = Field(1500, ge=0, le=50000)
    frozen_start_minutes: int | None = Field(None, ge=0, le=1440, multiple_of=5)


class Closure(StrictModel):
    resource: Literal["channel", "pilot", "tug", "berth", "crane", "power_kw"]
    start_minutes: int = Field(ge=0, le=1435, multiple_of=5)
    end_minutes: int = Field(ge=5, le=1440, multiple_of=5)
    unavailable: int = Field(ge=1, le=100000)

    @model_validator(mode="after")
    def ordered(self):
        if self.start_minutes >= self.end_minutes:
            raise ValueError("closure window must be nonempty")
        return self


class PlanRequest(StrictModel):
    site_id: str = Field(min_length=1, max_length=100)
    as_of: datetime
    horizon_minutes: int = Field(720, ge=60, le=1440, multiple_of=5)
    maximum_event_age_minutes: int = Field(120, ge=5, le=1440)
    capacities: dict[str, int] = Field(default_factory=lambda: dict(CAPACITIES))
    calls: list[Call] = Field(min_length=1, max_length=20)
    events: list[Event] = Field(min_length=1, max_length=160)
    closures: list[Closure] = Field(default_factory=list, max_length=20)
    evidence_class: Literal["declared_engineering_scenario", "historical_public_data_driven_scenario"] = (
        "declared_engineering_scenario"
    )

    @model_validator(mode="after")
    def coherent(self):
        if self.as_of.tzinfo is None:
            raise ValueError("as_of requires timezone")
        if set(self.capacities) != set(CAPACITIES) or any(
            type(v) is not int or not 1 <= v <= 100000 for v in self.capacities.values()
        ):
            raise ValueError("all registered resource capacities must be positive bounded integers")
        ids = {r.call_id for r in self.calls}
        if len(ids) != len(self.calls) or any(e.call_id not in ids for e in self.events):
            raise ValueError("calls must be unique and events must refer to declared calls")
        keys = [(e.event_id, e.revision) for e in self.events]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate event revision; conflicting updates cannot be overwritten")
        for event_id in {e.event_id for e in self.events}:
            revisions = [e for e in self.events if e.event_id == event_id]
            if len({(e.call_id, e.classifier, e.source_party) for e in revisions}) != 1:
                raise ValueError("event revision changed its identity, type or producer")
            ordered = sorted(revisions, key=lambda e: e.revision)
            if any(a.received_at > b.received_at for a, b in zip(ordered, ordered[1:])):
                raise ValueError("event revision reception time regressed")
        if any(
            c.end_minutes > self.horizon_minutes or c.unavailable > self.capacities[c.resource] for c in self.closures
        ):
            raise ValueError("closure must fit the horizon and registered resource capacity")
        return self


def arrivals(request):
    releases, blockers, receipts = {}, [], []
    available = [e for e in request.events if e.received_at <= request.as_of]
    for call in request.calls:
        matching = [e for e in available if e.call_id == call.call_id]
        latest = {}
        for e in matching:
            if e.event_id not in latest or e.revision > latest[e.event_id].revision:
                latest[e.event_id] = e
        matching = list(latest.values())
        event = None
        for classifier in ["ACTUAL", "PLANNED", "ESTIMATED"]:
            candidates = [e for e in matching if e.classifier == classifier]
            if not candidates:
                continue
            if len({e.event_time for e in candidates}) > 1:
                blockers.append(f"{call.call_id}:conflicting_{classifier.lower()}_times")
                break
            event = max(candidates, key=lambda e: (e.received_at, e.event_id))
            break
        if event is None:
            blockers.append(f"{call.call_id}:missing_agreed_arrival")
            continue
        if event.classifier == "ACTUAL" and event.event_time > request.as_of:
            blockers.append(f"{call.call_id}:future_actual_event")
            continue
        if (request.as_of - event.received_at).total_seconds() > request.maximum_event_age_minutes * 60:
            blockers.append(f"{call.call_id}:stale_event")
            continue
        eta = max(0.0, (event.event_time - request.as_of).total_seconds() / 60)
        upper = eta + (0 if event.classifier == "ACTUAL" else call.arrival_uncertainty_minutes)
        releases[call.call_id] = int(-(-upper // 5) * 5)
        receipts.append(
            {
                "call_id": call.call_id,
                "event_id": event.event_id,
                "revision": event.revision,
                "classifier": event.classifier,
                "robust_release_minutes": releases[call.call_id],
                "event_sha256": digest(event.model_dump(mode="json")),
            }
        )
    return releases, blockers, receipts


def allocations(call, start):
    end = start + 30 + call.service_minutes
    return [
        (start, start + 15, {"channel": 1, "pilot": 1, "tug": 1}),
        (start, end, {"berth": 1}),
        (start + 15, end - 15, {"crane": call.crane_count, "power_kw": call.shore_power_kw}),
        (end - 15, end, {"channel": 1, "pilot": 1, "tug": 1}),
    ]


def verify_schedule(request, schedule, releases):
    """Reconstruct allocations independently; never trust solver resource totals."""
    problems, usage, seen = [], {}, set()
    calls = {c.call_id: c for c in request.calls}
    for row in schedule:
        call_id, start = row["call_id"], row["start_minutes"]
        if call_id not in calls or call_id in seen:
            problems.append("unknown_or_duplicate_call")
            continue
        seen.add(call_id)
        call = calls[call_id]
        if row.get("end_minutes") != start + call.service_minutes + 30:
            problems.append(call_id + ":incorrect_end_time")
        if (
            type(start) is not int
            or start % 5
            or start < releases[call_id]
            or start + call.service_minutes + 30 > request.horizon_minutes
        ):
            problems.append(call_id + ":window")
            continue
        if call.frozen_start_minutes is not None and start != call.frozen_start_minutes:
            problems.append(call_id + ":freeze")
        for a, b, needs in allocations(call, start):
            for minute in range(a, b, 5):
                for resource, q in needs.items():
                    key = (minute, resource)
                    usage[key] = usage.get(key, 0) + q
    if seen != set(calls):
        problems.append("incomplete_schedule")
    for closure in request.closures:
        for minute in range(closure.start_minutes, closure.end_minutes, 5):
            key = (minute, closure.resource)
            usage[key] = usage.get(key, 0) + closure.unavailable
    if any(q > request.capacities[resource] for (_, resource), q in usage.items()):
        problems.append("resource_capacity_or_closure")
    return {"feasible": not problems, "issues": sorted(set(problems))}


def plan(request: PlanRequest):
    releases, blockers, event_receipts = arrivals(request)
    result = {
        "schema": "xiaoyi-portcall-plan.v1",
        "site_id": request.site_id,
        "input_sha256": digest(request.model_dump(mode="json")),
        "evidence_class": request.evidence_class,
        "as_of": request.as_of.isoformat(),
        "event_receipts": event_receipts,
        "future_updates_excluded": sum(e.received_at > request.as_of for e in request.events),
        "production_authority": False,
        "operational_release": False,
        "standard_alignment": "本地规范化事件语义参考DCSA Port Call v2；未实现完整DCSA API或通过其一致性测试。",
        "assumptions": {
            "time_step_minutes": 5,
            "transit_minutes_each_way": 15,
            "berths_interchangeable": True,
            "resources_pooled": True,
            "safety_exclusions": "未建模UKC、危险品隔离、缆绳、拖轮类型、引航资质和船舶尺度兼容；无船舶放行。",
        },
    }
    if blockers:
        return {**result, "recommendation_status": "withheld", "blockers": blockers, "candidates": [], "selected": None}
    candidates = []
    for method in ["fcfs", "earliest_deadline", "shortest_service"]:
        key = {
            "fcfs": lambda c: (releases[c.call_id], c.call_id),
            "earliest_deadline": lambda c: (c.deadline_minutes, releases[c.call_id], c.call_id),
            "shortest_service": lambda c: (c.service_minutes, releases[c.call_id], c.call_id),
        }[method]
        ordered = sorted(request.calls, key=lambda c: (c.frozen_start_minutes is None, key(c)))
        usage = {(m, r): 0 for m in range(0, request.horizon_minutes, 5) for r in CAPACITIES}
        for c in request.closures:
            for m in range(c.start_minutes, min(c.end_minutes, request.horizon_minutes), 5):
                usage[(m, c.resource)] += c.unavailable
        schedule = []
        for call in ordered:
            starts = (
                [call.frozen_start_minutes]
                if call.frozen_start_minutes is not None
                else range(releases[call.call_id], request.horizon_minutes - call.service_minutes - 29, 5)
            )
            for start in starts:
                if start < releases[call.call_id] or start + call.service_minutes + 30 > request.horizon_minutes:
                    continue
                alloc = allocations(call, start)
                if any(
                    usage[(m, r)] + q > request.capacities[r]
                    for a, b, needs in alloc
                    for m in range(a, b, 5)
                    for r, q in needs.items()
                ):
                    continue
                for a, b, needs in alloc:
                    for m in range(a, b, 5):
                        for r, q in needs.items():
                            usage[(m, r)] += q
                end = start + call.service_minutes + 30
                schedule.append(
                    {
                        "call_id": call.call_id,
                        "start_minutes": start,
                        "end_minutes": end,
                        "planned_arrival": (request.as_of + timedelta(minutes=start)).isoformat(),
                        "robust_wait_minutes": start - releases[call.call_id],
                        "late_minutes": max(0, end - call.deadline_minutes),
                    }
                )
                break
        validation = verify_schedule(request, schedule, releases)
        metrics = (
            {
                "total_wait_minutes": sum(r["robust_wait_minutes"] for r in schedule),
                "total_late_minutes": sum(r["late_minutes"] for r in schedule),
                "makespan_minutes": max((r["end_minutes"] for r in schedule), default=0),
            }
            if validation["feasible"]
            else None
        )
        candidates.append({"method": method, "schedule": schedule, "validation": validation, "metrics": metrics})
    feasible = [r for r in candidates if r["validation"]["feasible"]]
    selected = (
        min(
            feasible,
            key=lambda r: (
                r["metrics"]["total_late_minutes"],
                r["metrics"]["total_wait_minutes"],
                r["metrics"]["makespan_minutes"],
            ),
        )
        if feasible
        else None
    )
    for row in feasible:
        row["pareto_efficient"] = not any(
            all(other["metrics"][k] <= row["metrics"][k] for k in row["metrics"])
            and any(other["metrics"][k] < row["metrics"][k] for k in row["metrics"])
            for other in feasible
        )
    return {
        **result,
        "recommendation_status": "engineering_review" if selected else "withheld",
        "blockers": [] if selected else ["no_complete_feasible_schedule"],
        "candidates": candidates,
        "selected": selected,
        "selection_basis": "lexicographic: lateness, wait, makespan; feasible candidates only",
        "optimality": "三个确定性调度启发式对照，未证明全局最优；无燃油、碳或财务收益推断。",
    }
