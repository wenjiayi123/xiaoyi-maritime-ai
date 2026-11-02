"""Frozen multi-port/time protocol; validation selection and one sealed future evaluation."""

from __future__ import annotations

import gzip
import hashlib
import json
import random
import statistics
import time
from datetime import date
from pathlib import Path

from pydantic import Field, model_validator

from app.config import BASE_DIR
from app.harness import (
    crossport_control as control,
    crossport_forecast as forecasting,
    portwatch_data as data,
    multisite_twin,
)
from app.harness.contracts import StrictModel, digest, now

ROOT = BASE_DIR / ".runtime/crossport-studies"
PROTOCOL = {
    "version": "crossport-control.v1",
    "train_years": [2019, 2020, 2021, 2022],
    "validation_years": [2023],
    "sealed_test_years": [2024, 2025],
    "train_port_ids": data.TRAIN_PORTS,
    "whole_port_holdout_ids": data.UNSEEN_PORTS,
    "horizon_days": 90,
    "context_history_days": 42,
    "public_observation_lag_days": 7,
    "quarters": [1, 4, 7, 10],
    "algorithms": ["double_dqn", "residual_double_dqn"],
    "baselines": ["pid", "mpc", "balanced", "max_capacity"],
    "scenarios": ["normal", "demand_surge", "resource_outage", "publication_delay"],
    "selection": "mean validation score across available training ports/windows/seeds only",
    "rl_training": {
        "hidden_units": 32,
        "replay_capacity": 20000,
        "batch": 64,
        "gamma": 0.97,
        "adam_learning_rate": 0.0008,
        "target_update_steps": 250,
        "gradient_norm_clip": 5,
        "training_reward_floor": -40,
        "bootstrap_target_clip": [-300, 20],
    },
    "objective": "negative normalized declared queue/resource/change/overflow/terminal costs; no measured financial or emission benefit",
    "objective_coefficients": {
        "backlog": 1.0,
        "resource_squared": 0.5,
        "action_change": 0.05,
        "backlog_overflow_above_4": 5.0,
        "terminal_backlog": 2.0,
    },
    "physical_twin_protocol": {
        "train": "2024-01",
        "validation": "2024-07-01..07",
        "sealed_test": "2024-12-01..07",
        "candidate_constituent_counts": [4, 6],
        "ridge": [0.0, 1.0, 100.0],
        "mae_limit_m": 0.2,
        "coverage_floor": 0.8,
        "width_limit_m": 0.75,
    },
    "capacity": "frozen mean of 28 public days available before episode, using 7-day publication lag; declared service proxy, not identified terminal capacity",
    "queue_observation": "simulated operational backlog state is observed; not derived as a measured real queue from PortWatch",
    "statistics": "port-cluster bootstrap of paired quarter means; seeds summarized within common cells; quarters/seeds are not independent field trials",
    "seed": 301030,
    "production_authority": False,
}


class Config(StrictModel):
    seeds: list[int] = Field(default_factory=lambda: [31101, 31102, 31103, 31104, 31105], min_length=5, max_length=10)
    training_steps: int = Field(20000, ge=2000, le=60000)
    max_seconds: int = Field(900, ge=60, le=3600)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.seeds)) != len(self.seeds) or any(s < 0 or s > 2_000_000_000 for s in self.seeds):
            raise ValueError("unique bounded seeds required")
        return self


def source_hashes():
    paths = [
        Path(__file__),
        Path(control.__file__),
        Path(forecasting.__file__),
        Path(data.__file__),
        Path(multisite_twin.__file__),
        Path(__file__).with_name("crossport.py"),
        BASE_DIR / "config/crossport_evidence_registry.json",
    ]
    return {str(p.relative_to(BASE_DIR)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")


def windows(series, years, ports):
    included, excluded = [], []
    for port in ports:
        if port not in series:
            continue
        for year in years:
            for month in PROTOCOL["quarters"]:
                first = date(year, month, 1)
                rows = data.contiguous(series[port], first, 90)
                identity = {
                    "port_id": port,
                    "start": first.isoformat(),
                    "year": year,
                    "role": "temporal_holdout" if port in data.TRAIN_PORTS else "whole_port_holdout",
                }
                if rows is None:
                    excluded.append({**identity, "reason": "missing contiguous source dates; no interpolation"})
                else:
                    included.append({**identity, "records": rows, "id": f"{port}.{year}.{month:02}"})
    return included, excluded


def clustered_interval(values):
    # values maps a port to paired, non-overlapping quarter/seed means.
    rng = random.Random(PROTOCOL["seed"])
    ports = sorted(values)
    means = {p: statistics.mean(values[p]) for p in ports}
    draws = [statistics.mean(means[rng.choice(ports)] for _ in ports) for _ in range(2000)]
    draws.sort()
    return {
        "mean_delta": statistics.mean(means.values()),
        "port_cluster_ci95": [draws[49], draws[1949]],
        "ports": len(ports),
        "quarter_cells": sum(len(v) for v in values.values()),
        "per_port_mean_delta": means,
        "worst_port_mean_delta": min(means.values()),
        "worst_quarter_delta": min(x for v in values.values() for x in v),
        "lower_tail_mean_20pct": statistics.mean(
            sorted(x for v in values.values() for x in v)[: max(1, int(sum(len(v) for v in values.values()) * 0.2))]
        ),
        "limitation": "Few port clusters, common macro shocks and repeated training seeds; not a field-risk confidence bound.",
    }


def run(config: Config, folder: Path, cancelled=lambda: False, progress=lambda *_: None):
    started = time.monotonic()
    sources = source_hashes()
    manifest, series = data.load_all()
    manifest_hash = digest(manifest)
    physical_manifest = json.loads((multisite_twin.FOLDER / "manifest.json").read_text())
    physical_manifest_hash = digest(physical_manifest)
    folder.mkdir(parents=True, exist_ok=False)
    train, train_excluded = windows(series, PROTOCOL["train_years"], data.TRAIN_PORTS)
    validation, val_excluded = windows(series, [2023], data.TRAIN_PORTS)
    test, test_excluded = windows(series, [2024, 2025], list(series))
    if len(train) < 24 or len(validation) < 8 or len(test) < 24:
        raise ValueError("cross-port/time window coverage below frozen minimum")
    if len({r["port_id"] for r in test if r["role"] == "whole_port_holdout"}) < 2:
        raise ValueError("whole-port holdout cohort insufficient")
    split = {
        "training_windows": [{k: v for k, v in w.items() if k != "records"} for w in train],
        "validation_windows": [{k: v for k, v in w.items() if k != "records"} for w in validation],
        "sealed_test_windows": [{k: v for k, v in w.items() if k != "records"} for w in test],
        "excluded_windows": train_excluded + val_excluded + test_excluded,
    }
    write(
        folder / "protocol.json",
        {
            "protocol": PROTOCOL,
            "config": config.model_dump(),
            "splits": split,
            "source_hashes": sources,
            "manifest_sha256": manifest_hash,
            "physical_manifest_sha256": physical_manifest_hash,
            "frozen_before_training_at": now(),
        },
    )

    def stopped():
        return cancelled() or time.monotonic() - started > config.max_seconds

    def guard():
        if stopped():
            raise InterruptedError("cross-port study cancelled or elapsed budget exceeded")

    calibration = forecasting.fit(series)
    forecast = calibration["selected"]
    policies = [control.Policy(name) for name in PROTOCOL["baselines"]]
    models = []
    curves = {}
    for name in PROTOCOL["algorithms"]:
        for seed in config.seeds:
            guard()
            progress("training", name, seed)
            policy, curve = control.train_policy(
                name, [w["records"] for w in train], forecast, seed, config.training_steps, stopped
            )
            path = folder / "models" / f"{name}-{seed}.json"
            write(
                path,
                {
                    "algorithm": name,
                    "seed": seed,
                    "network": policy.network.payload(),
                    "features": control.FEATURES,
                    "residual": policy.residual,
                    "protocol_sha256": digest(PROTOCOL),
                    "source_hashes": sources,
                },
            )
            models.append(
                {
                    "algorithm": name,
                    "seed": seed,
                    "path": str(path.relative_to(BASE_DIR)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
            curves[f"{name}:{seed}"] = curve
            policies.append(policy)
    validation_rows = []
    for policy in policies:
        guard()
        progress("validation", policy.name, policy.seed)
        for window in validation:
            metrics = control.evaluate(policy, window["records"], forecast)
            metrics.pop("frames")
            validation_rows.append({"algorithm": policy.name, "seed": policy.seed, "window": window["id"], **metrics})
    names = PROTOCOL["baselines"] + PROTOCOL["algorithms"]
    validation_scores = {
        name: statistics.mean(r["score"] for r in validation_rows if r["algorithm"] == name) for name in names
    }
    comparator = max(PROTOCOL["baselines"], key=lambda n: validation_scores[n])
    selected = max(names, key=lambda n: validation_scores[n])
    write(
        folder / "selection-frozen.json",
        {
            "selected_algorithm": selected,
            "comparator_algorithm": comparator,
            "validation_scores": validation_scores,
            "before_test_at": now(),
            "test_accessed_for_training_or_selection": False,
        },
    )
    results = []
    trace_path = folder / "traces.jsonl.gz"
    with gzip.open(trace_path, "wt", encoding="utf-8") as traces:
        for scenario in PROTOCOL["scenarios"]:
            for window in test:
                guard()
                progress("sealed_test", scenario, window["id"])
                for policy in policies:
                    metrics = control.evaluate(policy, window["records"], forecast, scenario)
                    frames = metrics.pop("frames")
                    identity = {
                        "algorithm": policy.name,
                        "seed": policy.seed,
                        "window": window["id"],
                        "port_id": window["port_id"],
                        "role": window["role"],
                        "year": window["year"],
                        "start": window["start"],
                        "scenario": scenario,
                    }
                    traces.write(json.dumps({**identity, "frames": frames}, ensure_ascii=False) + "\n")
                    results.append({**identity, **metrics, "trace_sha256": digest(frames)})
    decisions = []
    for name in names:
        contexts = {}
        for role in ["temporal_holdout", "whole_port_holdout"]:
            deltas = {}
            for window in [w for w in test if w["role"] == role]:
                candidate = [
                    r
                    for r in results
                    if r["algorithm"] == name and r["window"] == window["id"] and r["scenario"] == "normal"
                ]
                base = next(
                    r
                    for r in results
                    if r["algorithm"] == comparator and r["window"] == window["id"] and r["scenario"] == "normal"
                )
                deltas.setdefault(window["port_id"], []).append(
                    statistics.mean(r["score"] for r in candidate) - base["score"]
                )
            contexts[role] = clustered_interval(deltas)
        rows = [r for r in results if r["algorithm"] == name]
        stress = []
        for scenario in PROTOCOL["scenarios"][1:]:
            paired = []
            for window in test:
                candidate = [r for r in rows if r["window"] == window["id"] and r["scenario"] == scenario]
                base = next(
                    r
                    for r in results
                    if r["algorithm"] == comparator and r["window"] == window["id"] and r["scenario"] == scenario
                )
                paired.append(statistics.mean(r["score"] for r in candidate) - base["score"])
            stress.append(
                {"scenario": scenario, "mean_delta": statistics.mean(paired), "worst_window_delta": min(paired)}
            )
        checks = {
            "rl_candidate": name in PROTOCOL["algorithms"],
            "selected_on_validation": name == selected,
            "both_holdouts_improve": all(c["port_cluster_ci95"][0] > 0 for c in contexts.values()),
            "no_port_mean_regression": all(c["worst_port_mean_delta"] >= 0 for c in contexts.values()),
            "no_quarter_regression": all(c["worst_quarter_delta"] >= 0 for c in contexts.values()),
            "zero_observed_constraint_violations": all(r["constraint_violations"] == 0 for r in rows),
            "flow_conservation": all(r["maximum_flow_balance_error"] < 1e-8 for r in rows),
            "stress_noninferiority": all(s["mean_delta"] >= 0 for s in stress),
            "learned_decisions_disclosed": name not in PROTOCOL["algorithms"]
            or statistics.mean(r["learned_action_fraction"] for r in rows) > 0.1,
        }
        decisions.append(
            {
                "algorithm": name,
                "family": "rl" if name in PROTOCOL["algorithms"] else "baseline",
                "validation_score": validation_scores[name],
                "nominal_test_score": statistics.mean(r["score"] for r in rows if r["scenario"] == "normal"),
                "mean_fallback_fraction": statistics.mean(r["fallback_fraction"] for r in rows),
                "contexts": contexts,
                "stress": stress,
                "checks": checks,
                "blockers": [k for k, v in checks.items() if not v],
                "research_admission": all(checks.values()),
                "enterprise_admission": False,
            }
        )
    guard()
    twin = forecasting.assess(series, calibration)
    physical = multisite_twin.study()
    current, _ = data.load_all()
    if (
        digest(current) != manifest_hash
        or source_hashes() != sources
        or physical["source_manifest_sha256"] != physical_manifest_hash
    ):
        raise ValueError("study implementation or source vintage changed")
    report = {
        "schema": "xiaoyi-crossport-study.v1",
        "created_at": now(),
        "config": config.model_dump(),
        "protocol": PROTOCOL,
        "protocol_sha256": digest(PROTOCOL),
        "manifest_sha256": manifest_hash,
        "source_hashes": sources,
        "sources": manifest,
        "splits": split,
        "selected_algorithm": selected,
        "comparator_algorithm": comparator,
        "validation_rows": validation_rows,
        "models": models,
        "curves": curves,
        "runs": results,
        "aggregate": decisions,
        "twin_calibration": twin,
        "multisite_physical_calibration": physical,
        "trace_file": str(trace_path.relative_to(BASE_DIR)),
        "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        "duration_seconds": time.monotonic() - started,
        "production_authority": False,
        "notice": "国际公开AIS衍生活动指标驱动的逐日服务代理环境；资源、队列、成本和故障为显式工程假设。跨港/未来期留出与既有分钟级旧协议分开，不推定现场收益或全港物理标定。",
    }
    write(folder / "report.json", report)
    return report
