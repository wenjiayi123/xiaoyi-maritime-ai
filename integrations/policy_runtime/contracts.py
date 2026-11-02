"""SI-unit transport contract and a validator independent of the neural models."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import random
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class Stop(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    x_m: float = Field(ge=0, le=10000)
    y_m: float = Field(ge=0, le=10000)
    demand: float = Field(ge=0, le=1000)
    service_seconds: float = Field(0, ge=0, le=3600)
    window_start_seconds: float = Field(0, ge=0, le=86400)
    window_end_seconds: float = Field(86400, ge=1, le=86400)


class Vehicle(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    capacity: float = Field(gt=0, le=10000)
    speed_mps: float = Field(5, gt=0, le=20)
    shift_end_seconds: float = Field(86400, ge=1, le=86400)
    energy_kwh_per_m: float = Field(.0004, ge=0, le=1)
    idle_kw: float = Field(1, ge=0, le=100)
    energy_budget_kwh: float = Field(100, gt=0, le=10000)


class TransportCase(Strict):
    schema_version: Literal["joint-transport.v1"] = "joint-transport.v1"
    case_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,100}$")
    seed: int = Field(44001, ge=0, le=2_000_000_000)
    site_id: str = "XIAOYI-JOINT-LAB"
    evidence_class: Literal["declared_engineering_fixture", "calibrated_simulation"] = "declared_engineering_fixture"
    objective: Literal["total_distance_m", "makespan_seconds"] = "total_distance_m"
    distance_model: Literal["euclidean_open_yard"] = "euclidean_open_yard"
    demand_unit: Literal["container_units"] = "container_units"
    allow_refill: bool = False
    depot: Stop
    jobs: list[Stop] = Field(min_length=2, max_length=100)
    vehicles: list[Vehicle] = Field(min_length=1, max_length=15)
    forbidden_edges: list[tuple[str, str]] = Field(default_factory=list, max_length=100)
    source_receipts: dict[str, str] = Field(default_factory=dict, max_length=10)

    @model_validator(mode="after")
    def valid(self):
        nodes = [self.depot, *self.jobs]
        ids = [node.id for node in nodes]
        if len(set(ids)) != len(ids) or len({v.id for v in self.vehicles}) != len(self.vehicles):
            raise ValueError("entity IDs must be unique")
        if self.depot.demand or any(n.demand <= 0 for n in self.jobs):
            raise ValueError("depot demand must be zero and every job demand positive")
        if any(n.window_start_seconds > n.window_end_seconds for n in nodes):
            raise ValueError("inverted time window")
        if any(a not in ids or b not in ids for a, b in self.forbidden_edges):
            raise ValueError("forbidden edge references an unknown entity")
        if max(n.demand for n in self.jobs) > max(v.capacity for v in self.vehicles):
            raise ValueError("a job exceeds every vehicle's capacity")
        if not self.allow_refill and sum(n.demand for n in self.jobs) > sum(v.capacity for v in self.vehicles):
            raise ValueError("fleet total capacity is insufficient without refills")
        return self


class Route(Strict):
    vehicle_id: str
    stops: list[str] = Field(min_length=2, max_length=400)


class SolveRequest(Strict):
    model: Literal["routefinder", "parco", "nearest_neighbor", "ortools"]
    case: TransportCase
    max_compute_ms: int = Field(1000, ge=50, le=5000)


def sha(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_routes(case: TransportCase, routes: list[Route | dict]):
    nodes = {n.id: n for n in [case.depot, *case.jobs]}
    vehicles = {v.id: v for v in case.vehicles}
    expected = Counter(n.id for n in case.jobs)
    seen, used = Counter(), set()
    violations, records = [], []
    forbidden = set(case.forbidden_edges)
    for raw in routes:
        route = raw if isinstance(raw, Route) else Route.model_validate(raw)
        if route.vehicle_id not in vehicles or route.vehicle_id in used:
            violations.append("unknown_or_repeated_vehicle")
            continue
        used.add(route.vehicle_id)
        vehicle = vehicles[route.vehicle_id]
        if route.stops[0] != case.depot.id or route.stops[-1] != case.depot.id:
            violations.append("route_not_closed_at_depot")
        if not case.allow_refill and case.depot.id in route.stops[1:-1]:
            violations.append("refill_not_allowed")
        if any(n not in nodes for n in route.stops):
            violations.append("unknown_stop")
            continue
        elapsed, distance, load, idle_seconds = 0., 0., 0., 0.
        events = []
        for a, b in zip(route.stops, route.stops[1:]):
            if (a, b) in forbidden:
                violations.append("forbidden_edge")
            first, second = nodes[a], nodes[b]
            length = math.hypot(second.x_m - first.x_m, second.y_m - first.y_m)
            distance += length
            elapsed += length / vehicle.speed_mps
            wait = max(0., second.window_start_seconds - elapsed)
            elapsed += wait
            if elapsed > second.window_end_seconds + 1e-4:
                violations.append("time_window")
            if b == case.depot.id:
                load = 0.
            else:
                load += second.demand
                seen[b] += 1
            if load > vehicle.capacity + 1e-4:
                violations.append("capacity")
            events.append({"job_id": b, "arrival_seconds": round(elapsed, 6), "trip_load": load})
            elapsed += second.service_seconds
            idle_seconds += wait + second.service_seconds
        energy = distance * vehicle.energy_kwh_per_m + idle_seconds / 3600 * vehicle.idle_kw
        if elapsed > vehicle.shift_end_seconds + 1e-4:
            violations.append("shift_end")
        if energy > vehicle.energy_budget_kwh + 1e-6:
            violations.append("vehicle_energy")
        records.append({"vehicle_id": vehicle.id, "distance_m": distance, "duration_seconds": elapsed,
                        "energy_kwh": energy, "events": events})
    if seen != expected:
        violations.append("each_job_exactly_once")
    distance = sum(r["distance_m"] for r in records)
    makespan = max((r["duration_seconds"] for r in records), default=0.)
    return {"feasible": not violations, "violations": sorted(set(violations)), "distance_m": distance,
            "makespan_seconds": makespan, "energy_kwh": sum(r["energy_kwh"] for r in records),
            "objective_value": distance if case.objective == "total_distance_m" else makespan,
            "vehicles_used": sum(any(e["job_id"] != case.depot.id for e in r["events"]) for r in records), "jobs_served": sum(seen.values()), "routes": records,
            "case_sha256": sha(case.model_dump()), "validator": "independent_si_contract.v1"}


def nearest_neighbor(case: TransportCase):
    pending = {node.id: node for node in case.jobs}
    routes = {v.id: [case.depot.id] for v in case.vehicles}
    rounds = 0
    while pending:
        rounds += 1
        count = len(pending)
        for vehicle in case.vehicles:
            order, current, load = routes[vehicle.id], case.depot, 0.
            while pending:
                eligible = [n for n in pending.values() if n.demand + load <= vehicle.capacity and (current.id, n.id) not in case.forbidden_edges]
                if not eligible:
                    break
                node = min(eligible, key=lambda n: (math.hypot(n.x_m-current.x_m, n.y_m-current.y_m), n.id))
                order.append(node.id)
                load += node.demand
                current = pending.pop(node.id)
            order.append(case.depot.id)
        if len(pending) == count:
            break
        if not case.allow_refill and rounds == 1:
            break
    return [Route(vehicle_id=key, stops=value if len(value) > 1 else [*value, case.depot.id]) for key, value in routes.items()]


def fixture(seed=44001, size=30, heterogeneous=False, source_receipts=None):
    rng = random.Random(seed)
    vehicles = [Vehicle(id=f"AGV-{i+1:02}", capacity=40 + (i % 3)*5 if heterogeneous else 40,
                        speed_mps=4+i%3 if heterogeneous else 5) for i in range(5)]
    jobs = [Stop(id=f"BOX-{i+1:03}", x_m=round(rng.uniform(0, 800), 3), y_m=round(rng.uniform(0, 800), 3),
                 demand=rng.randint(1, 6)) for i in range(size)]
    return TransportCase(case_id=f"joint-yard-{seed}-{size}", seed=seed,
                         depot=Stop(id="DEPOT", x_m=400, y_m=400, demand=0), jobs=jobs, vehicles=vehicles,
                         objective="makespan_seconds" if heterogeneous else "total_distance_m",
                         source_receipts=source_receipts or {})
