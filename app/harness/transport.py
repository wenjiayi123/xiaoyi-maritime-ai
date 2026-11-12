"""Pinned local policy runtime; the host independently validates every proposed route."""

from __future__ import annotations
import os
import hashlib
import json
import math
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from app.config import BASE_DIR
from integrations.policy_runtime.contracts import TransportCase, Route, fixture, validate_routes, sha

URL = "http://127.0.0.1:11839"
PINS = {
    "routefinder": "eb09cee46108bac04012c2702f7cd4aac64341064167363255f02f2e63167f90",
    "parco": "820ec654d63886ec6e7ad7a39f470eb49bb155596ed9b6dfa6a580bfc9a1844c",
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("policy runtime redirects are forbidden")


def _call(path, body=None):
    data = None if body is None else json.dumps(body, allow_nan=False).encode()
    with build_opener(NoRedirect).open(
        Request(URL + path, data=data, headers={"Content-Type": "application/json"}), timeout=float(os.getenv("XIAOYI_POLICY_TIMEOUT", "35"))
    ) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("policy response too large")
    return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite policy response")))


def health():
    data = _call("/health")
    if data.get("schema") != "xiaoyi-policy-runtime.v1" or data.get("production_authority") is not False:
        raise ValueError("policy runtime contract mismatch")
    expected_packages = {
        "torchrl": "0.6.0",
        "tensordict": "0.6.2",
        "rl4co": "0.5.2",
        "routefinder": "0.4.0",
        "parco": "0.2.0",
    }
    if data.get("torch") != "2.5.1+cpu" or any(
        data.get("packages", {}).get(k) != v for k, v in expected_packages.items()
    ):
        raise ValueError("isolated policy package versions drifted from admitted runtime")
    for name in ["server", "contracts", "action_codec", "ortools_multitrip"]:
        expected = hashlib.sha256((BASE_DIR / f"integrations/policy_runtime/{name}.py").read_bytes()).hexdigest()
        if data.get(name + "_sha256") != expected:
            raise ValueError("policy runtime code changed; restart isolated service")
    if any(data.get("models", {}).get(k, {}).get("sha256") != v for k, v in PINS.items()):
        raise ValueError("policy weight version mismatch")
    return data


def solve(case: TransportCase, model: str, max_compute_ms=1000):
    health()
    data = _call("/solve", {"case": case.model_dump(), "model": model, "max_compute_ms": max_compute_ms})
    if (
        data.get("case_sha256") != sha(case.model_dump())
        or data.get("model") != model
        or data.get("production_authority") is not False
    ):
        raise ValueError("policy receipt is not bound to input/model")
    if model in PINS and (
        data.get("model_sha256") != PINS[model] or data.get("strict_policy_state_loading") is not True
    ):
        raise ValueError("trained checkpoint loading not verified")
    validation = validate_routes(case, [Route.model_validate(r) for r in data["routes"]])
    remote = data["validation"]
    if validation["feasible"] != remote["feasible"] or validation["violations"] != remote["violations"]:
        raise ValueError("independent host feasibility check disagrees")
    for k in ["distance_m", "makespan_seconds", "energy_kwh", "objective_value"]:
        if not math.isclose(validation[k], remote[k], rel_tol=1e-7, abs_tol=1e-5):
            raise ValueError("independent SI measurement mismatch: " + k)
    return {**data, "validation": validation, "host_revalidated": True, "runtime": health()}


def compare(case: TransportCase, include_pretrained=True, allow_pretrained_selection=True):
    """A rejected/poor neural candidate never replaces a better feasible baseline."""
    models = ["nearest_neighbor", "ortools"]
    if include_pretrained:
        models.append("parco" if case.objective == "makespan_seconds" else "routefinder")
    candidates = []
    for model in models:
        try:
            candidates.append(
                solve(case, model, max_compute_ms=5000 if case.allow_refill and model == "ortools" else 1000)
            )
        except Exception as exc:
            candidates.append({"model": model, "error": str(exc)[:500], "validation": {"feasible": False}})
    for candidate in candidates:
        candidate["selection_eligible"] = allow_pretrained_selection or candidate["model"] not in PINS
    feasible = [c for c in candidates if c["validation"]["feasible"] and c["selection_eligible"]]
    if not feasible:
        raise ValueError("all transport candidates rejected: " + json.dumps(candidates, ensure_ascii=False)[:1000])
    selected = min(feasible, key=lambda c: (c["validation"]["objective_value"], c["model"]))
    return {
        "schema": "xiaoyi-transport-comparison.v1",
        "case": case.model_dump(),
        "case_sha256": sha(case.model_dump()),
        "candidates": candidates,
        "selected": selected,
        "selection": "minimum independently verified objective among admitted feasible candidates",
        "pretrained_selection_allowed": allow_pretrained_selection,
        "production_authority": False,
        "evidence_class": case.evidence_class,
    }


def ensure_running():
    try:
        return health()
    except Exception as before:
        import subprocess
        import sys

        runner = BASE_DIR / "scripts/manage_policy_runtime.py"
        folder = BASE_DIR / ".runtime/joint-demo"
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "policy-runtime.log").open("a") as log:
            done = subprocess.run(
                [sys.executable, str(runner), "start"], cwd=BASE_DIR, stdout=log, stderr=subprocess.STDOUT, timeout=120
            )
        if done.returncode:
            raise ValueError(
                "隔离策略服务未就绪，原有功能仍可用；详见.runtime/joint-demo/policy-runtime.log"
            ) from before
        return health()
