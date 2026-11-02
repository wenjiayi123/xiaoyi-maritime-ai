"""Only public, hash-pinned policies run in the isolated Linux guest."""
from __future__ import annotations

import os
os.environ.setdefault("WANDB_MODE", "offline")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("DO_NOT_TRACK", "1")

import hashlib
import importlib.metadata
import threading
import time
from pathlib import Path

import torch
from fastapi import FastAPI, HTTPException
from tensordict import TensorDict

from contracts import Route, SolveRequest, TransportCase, nearest_neighbor, sha, validate_routes
from action_codec import parco_stops

torch.set_num_threads(2)
torch.set_num_interop_threads(1)
app = FastAPI(title="Xiaoyi isolated open transport policy runtime", version="1")
LOCK = threading.Lock()
MODELS = {}
SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
FILES = {
    "routefinder": ("/opt/xiaoyi/models/routefinder/rf-transformer.ckpt", "eb09cee46108bac04012c2702f7cd4aac64341064167363255f02f2e63167f90"),
    "parco": ("/opt/xiaoyi/models/parco/parco.ckpt", "820ec654d63886ec6e7ad7a39f470eb49bb155596ed9b6dfa6a580bfc9a1844c"),
}


def load(name):
    if name not in MODELS:
        path, expected = FILES[name]
        with open(path, "rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("official checkpoint hash mismatch")
        # These specific upstream files are trusted only after verifying their pinned hashes.
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        policy = checkpoint["hyper_parameters"]["policy"]
        state = {key.removeprefix("policy."): value for key, value in checkpoint["state_dict"].items() if key.startswith("policy.")}
        policy.load_state_dict(state, strict=True)
        policy = policy.to("cpu").eval()
        for parameter in policy.parameters():
            parameter.requires_grad_(False)
        MODELS[name] = policy
    return MODELS[name]


def routefinder(case: TransportCase):
    from routefinder.envs.mtvrp.env import MTVRPEnv
    if case.objective != "total_distance_m":
        raise ValueError("RouteFinder checkpoint optimizes total route distance")
    if len({(v.capacity, v.speed_mps) for v in case.vehicles}) != 1:
        raise ValueError("RouteFinder requires homogeneous vehicles; use PARCO for heterogeneous HCVRP")
    nodes = [case.depot, *case.jobs]
    offset_x, offset_y = min(n.x_m for n in nodes), min(n.y_m for n in nodes)
    scale = max(max(n.x_m for n in nodes)-offset_x, max(n.y_m for n in nodes)-offset_y, 1.)
    vehicle = case.vehicles[0]
    time_scale = vehicle.speed_mps / scale
    env = MTVRPEnv(generator_params={"num_loc": len(case.jobs), "variant_preset": "cvrp"}, check_solution=True)
    td = env.generator([1])
    td["locs"] = torch.tensor([[[(n.x_m-offset_x)/scale, (n.y_m-offset_y)/scale] for n in nodes]], dtype=torch.float32)
    td["demand_linehaul"] = torch.tensor([[n.demand/vehicle.capacity for n in case.jobs]], dtype=torch.float32)
    td["demand_backhaul"] = torch.zeros_like(td["demand_linehaul"])
    td["vehicle_capacity"] = torch.ones((1, 1))
    td["capacity_original"] = torch.full((1, 1), vehicle.capacity)
    # Preserve the upstream CVRP absence-of-time-windows encoding (0, infinity).
    # Finite windows are supplied only when the caller actually declares them.
    hard_windows = any(n.window_start_seconds or n.window_end_seconds != 86400 or n.service_seconds for n in nodes)
    if hard_windows:
        td["time_windows"] = torch.tensor([[[n.window_start_seconds*time_scale, min(n.window_end_seconds, vehicle.shift_end_seconds)*time_scale] for n in nodes]], dtype=torch.float32)
        td["service_time"] = torch.tensor([[n.service_seconds*time_scale for n in nodes]], dtype=torch.float32)
    td["distance_limit"] = torch.full((1, 1), float("inf"))
    td["open_route"] = torch.zeros((1, 1), dtype=torch.bool)
    td["speed"] = torch.ones((1, 1))
    with torch.inference_mode():
        out = load("routefinder")(env.reset(td), env, phase="test", num_starts=1, decode_type="greedy", return_actions=True, max_steps=4*len(case.jobs)+20)
    raw = out["actions"][0].tolist()
    trips, trip = [], []
    for index in [*raw, 0]:
        if index == 0:
            if trip:
                trips.append(trip)
                trip = []
        else:
            trip.append(nodes[index].id)
    routes = [[case.depot.id] for v in case.vehicles]
    duration = [0.] * len(routes)
    for trip in trips:
        selected = min(range(len(routes)), key=lambda i: duration[i])
        routes[selected].extend([*trip, case.depot.id])
        interim = validate_routes(case, [Route(vehicle_id=case.vehicles[selected].id, stops=routes[selected])])
        duration[selected] = interim["makespan_seconds"]
    converted = [Route(vehicle_id=v.id, stops=row if len(row) > 1 else [*row, case.depot.id]) for v, row in zip(case.vehicles, routes)]
    return converted, {"raw_actions": raw, "upstream_reward": out["reward"].flatten().tolist(),
                    "coordinate_scale_m": scale, "time_scale": time_scale, "depot_closure": "upstream implicit depot made explicit",
                    "trip_assignment": "earliest_free_homogeneous_vehicle; independent time-window recheck"}


def parco(case: TransportCase):
    from parco.envs.hcvrp.env import HCVRPEnv
    if case.objective != "makespan_seconds":
        raise ValueError("PARCO HCVRP checkpoint optimizes the maximum vehicle travel time")
    if any(n.service_seconds or n.window_start_seconds or n.window_end_seconds != 86400 for n in [case.depot, *case.jobs]):
        raise ValueError("this PARCO HCVRP checkpoint does not model time windows or service times")
    nodes = case.jobs
    m = len(case.vehicles)
    scale = max(max(n.x_m for n in [case.depot, *nodes]), max(n.y_m for n in [case.depot, *nodes]), 1.)
    speed_scale = max(v.speed_mps for v in case.vehicles)
    env = HCVRPEnv(generator_params={"num_loc": len(nodes), "num_agents": m}, check_solution=True)
    td = TensorDict({"locs": torch.tensor([[[n.x_m/scale, n.y_m/scale] for n in nodes]], dtype=torch.float32),
                     "depot": torch.tensor([[case.depot.x_m/scale, case.depot.y_m/scale]], dtype=torch.float32),
                     "num_agents": torch.tensor([m]), "demand": torch.tensor([[n.demand for n in nodes]], dtype=torch.float32),
                     "capacity": torch.tensor([[v.capacity for v in case.vehicles]], dtype=torch.float32),
                     "speed": torch.tensor([[v.speed_mps/speed_scale for v in case.vehicles]], dtype=torch.float32)}, batch_size=[1])
    with torch.inference_mode():
        out = load("parco")(env.reset(td), env, phase="test", decode_type="greedy", return_actions=True, max_steps=4*len(case.jobs)+20)
    raw = out["actions"][0].tolist()
    routes, wait_actions = [], []
    for agent, row in enumerate(raw):
        stops, waits = parco_stops(agent, row, case.depot.id, [n.id for n in nodes], m)
        routes.append(Route(vehicle_id=case.vehicles[agent].id, stops=stops))
        wait_actions.append({"agent": agent, "waits": waits})
    return routes, {"raw_actions": raw, "upstream_reward": out["reward"].flatten().tolist(),
                    "coordinate_scale_m": scale, "speed_scale_mps": speed_scale, "native_wait_actions": wait_actions,
                    "action_semantics": "upstream HCVRPEnv stay_flag; consecutive same-node actions are waits, nonconsecutive revisits retained"}


def ortools(case, milliseconds):
    if case.allow_refill:
        from ortools_multitrip import solve_multitrip
        return solve_multitrip(case, milliseconds)
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    nodes = [case.depot, *case.jobs]
    manager = pywrapcp.RoutingIndexManager(len(nodes), len(case.vehicles), 0)
    routing = pywrapcp.RoutingModel(manager)
    forbidden = set(case.forbidden_edges)
    def distance(a, b):
        first, second = nodes[manager.IndexToNode(a)], nodes[manager.IndexToNode(b)]
        if (first.id, second.id) in forbidden:
            return 1_000_000_000
        return round(((first.x_m-second.x_m)**2+(first.y_m-second.y_m)**2)**.5*1000)
    dist_index = routing.RegisterTransitCallback(distance)
    routing.SetArcCostEvaluatorOfAllVehicles(dist_index)
    demand_index = routing.RegisterUnaryTransitCallback(lambda a: round(nodes[manager.IndexToNode(a)].demand*1000))
    routing.AddDimensionWithVehicleCapacity(demand_index, 0, [round(v.capacity*1000) for v in case.vehicles], True, "Capacity")
    # OR-Tools reference is a one-tour-per-vehicle CVRP/VRPTW baseline.
    # Refilling instances can remain infeasible; the independent validator reports that outcome.
    time_callbacks = []
    for vehicle in case.vehicles:
        def travel(a, b, speed=vehicle.speed_mps):
            return round(distance(a, b)/1000/speed + nodes[manager.IndexToNode(a)].service_seconds)
        time_callbacks.append(routing.RegisterTransitCallback(travel))
    routing.AddDimensionWithVehicleTransitAndCapacity(time_callbacks, 86400, [round(v.shift_end_seconds) for v in case.vehicles], False, "Time")
    timing = routing.GetDimensionOrDie("Time")
    for index, node in enumerate(nodes):
        if index:
            timing.CumulVar(manager.NodeToIndex(index)).SetRange(round(node.window_start_seconds), round(node.window_end_seconds))
    for v in range(len(case.vehicles)):
        timing.CumulVar(routing.Start(v)).SetValue(0)
    if case.objective == "makespan_seconds":
        routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(lambda *_: 0))
        timing.SetGlobalSpanCostCoefficient(100)
    options = pywrapcp.DefaultRoutingSearchParameters()
    options.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    options.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    options.time_limit.FromMilliseconds(milliseconds)
    options.log_search = False
    solution = routing.SolveWithParameters(options)
    if solution is None:
        return [], {"solver_status": routing.status(), "compute_budget_ms": milliseconds}
    routes = []
    for v, vehicle in enumerate(case.vehicles):
        index, stops = routing.Start(v), []
        while not routing.IsEnd(index):
            stops.append(nodes[manager.IndexToNode(index)].id)
            index = solution.Value(routing.NextVar(index))
        stops.append(case.depot.id)
        routes.append(Route(vehicle_id=vehicle.id, stops=stops))
    return routes, {"solver_status": routing.status(), "compute_budget_ms": milliseconds}


@app.get("/health")
def health():
    return {"schema": "xiaoyi-policy-runtime.v1", "runtime": "isolated_linux_cpu", "torch": torch.__version__,
            "server_sha256": SOURCE_SHA256, "contracts_sha256": hashlib.sha256(Path(__file__).with_name("contracts.py").read_bytes()).hexdigest(), "action_codec_sha256": hashlib.sha256(Path(__file__).with_name("action_codec.py").read_bytes()).hexdigest(), "ortools_multitrip_sha256": hashlib.sha256(Path(__file__).with_name("ortools_multitrip.py").read_bytes()).hexdigest(),
            "packages": {n: importlib.metadata.version(n) for n in ["torchrl", "tensordict", "rl4co", "routefinder", "parco"]},
            "models": {name: {"sha256": value[1], "loaded": name in MODELS} for name, value in FILES.items()},
            "original_environments_modified": False, "production_authority": False}


@app.post("/solve")
def solve(payload: SolveRequest):
    if not LOCK.acquire(blocking=False):
        raise HTTPException(409, "policy runtime is busy; requests are bounded and serialized")
    try:
        began = time.monotonic()
        if payload.model == "nearest_neighbor":
            routes, detail = nearest_neighbor(payload.case), {}
        elif payload.model == "ortools":
            routes, detail = ortools(payload.case, payload.max_compute_ms)
        else:
            load(payload.model)
            began = time.monotonic()
            routes, detail = globals()[payload.model](payload.case)
        return {"model": payload.model, "model_sha256": FILES.get(payload.model, (None, None))[1],
                "strict_policy_state_loading": payload.model in FILES, "case_sha256": sha(payload.case.model_dump()),
                "routes": [r.model_dump() for r in routes], "validation": validate_routes(payload.case, routes),
                "compute_seconds": time.monotonic()-began, "detail": detail, "production_authority": False}
    except (ValueError, AssertionError, RuntimeError, KeyError) as exc:
        raise HTTPException(422, str(exc)[:600]) from exc
    finally:
        LOCK.release()
