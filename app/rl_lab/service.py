from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from app.config import BASE_DIR, DATA_DIR
from app.rl_lab.algorithms import (
    ALL_ALGORITHM_IDS,
    PIDPolicy,
    RL_ALGORITHM_IDS,
    TrainedPolicy,
    evaluate_policy,
    train_tabular_policy,
)
from app.rl_lab.datasets import (
    DatasetError,
    chronological_split,
    file_sha256,
    get_dataset,
    inspect_dataset,
    load_records,
)
from app.rl_lab.environment import derive_parameters


RUNS_DIR = DATA_DIR / "rl_runs"
RUN_SCHEMA_VERSION = "xiaoyi-rl-run.v1"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class RunNotFound(KeyError):
    pass


class RunConflict(RuntimeError):
    pass


class RLLabService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    def _load_existing(self) -> None:
        for path in sorted(RUNS_DIR.glob("*/run.json")):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if job.get("status") in {"queued", "training", "cancelling"}:
                job["status"] = "interrupted"
                job["finished_at"] = _now()
                job["error"] = "The previous process ended before the background training thread completed."
                _atomic_json(path, job)
            self._jobs[str(job.get("run_id") or path.parent.name)] = job

    def _run_dir(self, run_id: str) -> Path:
        return RUNS_DIR / run_id

    def _persist(self, job: dict[str, Any]) -> None:
        _atomic_json(self._run_dir(job["run_id"]) / "run.json", job)

    def _public(self, job: dict[str, Any]) -> dict[str, Any]:
        payload = deepcopy(job)
        payload["artifact_root"] = str(self._run_dir(job["run_id"]).relative_to(BASE_DIR))
        return payload

    def start_run(self, config: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(config.get("dataset_id") or "uci_appliances_energy")
        definition = get_dataset(dataset_id)
        records = load_records(definition)
        dataset_info = inspect_dataset(definition, records)
        algorithms = list(dict.fromkeys(str(item) for item in config.get("algorithms") or ALL_ALGORITHM_IDS))
        invalid = sorted(set(algorithms) - set(ALL_ALGORITHM_IDS))
        if invalid:
            raise ValueError(f"Unsupported algorithms: {invalid}")
        selected_rl_algorithms = [item for item in algorithms if item in RL_ALGORITHM_IDS]
        if not selected_rl_algorithms:
            raise ValueError("at least one registered RL algorithm must be selected")
        episodes = int(config.get("episodes") or 160)
        horizon_steps = int(config.get("horizon_steps") or 72)
        seed = int(config.get("seed") or 240520)
        train_ratio = float(config.get("train_ratio") or 0.70)
        validation_ratio = float(config.get("validation_ratio") or 0.15)
        train, validation, test = chronological_split(
            records,
            train_ratio=train_ratio,
            validation_ratio=validation_ratio,
        )
        if min(len(train), len(validation), len(test)) <= horizon_steps:
            raise DatasetError("horizon_steps must be shorter than every chronological split")
        run_id = f"rl-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
        normalized_config = {
            "dataset_id": dataset_id,
            "algorithms": algorithms,
            "episodes": episodes,
            "horizon_steps": horizon_steps,
            "seed": seed,
            "train_ratio": train_ratio,
            "validation_ratio": validation_ratio,
            "learning_rate": float(config.get("learning_rate") or 0.12),
            "discount_factor": float(config.get("discount_factor") or 0.97),
            "epsilon_start": float(config.get("epsilon_start") or 1.0),
            "epsilon_end": float(config.get("epsilon_end") or 0.05),
        }
        job = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "queued",
            "phase": "queued",
            "progress_percent": 0.0,
            "completed_training_episodes": 0,
            "total_training_episodes": episodes * len(selected_rl_algorithms),
            "current_algorithm_id": None,
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "duration_seconds": None,
            "config": normalized_config,
            "dataset": {
                **definition.public_dict(inspect_file=False),
                **dataset_info,
                "split": {
                    "strategy": "chronological_no_shuffle",
                    "train_rows": len(train),
                    "validation_rows": len(validation),
                    "test_rows": len(test),
                    "train_time_end": train[-1].timestamp.isoformat(),
                    "validation_time_end": validation[-1].timestamp.isoformat(),
                    "test_time_start": test[0].timestamp.isoformat(),
                },
            },
            "training": {
                "render_mode": None,
                "rendering_performed": False,
                "data_split": "train",
                "algorithms": {},
                "curve_tail": [],
            },
            "validation": {
                "data_split": "validation",
                "rendering_performed": False,
                "results": [],
                "best_algorithm_id": None,
            },
            "test_evaluation": None,
            "environment": None,
            "reproducibility": {
                "seed": seed,
                "dataset_sha256": dataset_info["sha256"],
                "config_sha256": _sha256_text(json.dumps(normalized_config, sort_keys=True)),
                "python_hash_seed": os.getenv("PYTHONHASHSEED", "not-set; algorithm RNG uses explicit random.Random seeds"),
                "training_render_disabled": True,
                "test_rows_touched_during_training": False,
            },
            "error": None,
        }
        with self._lock:
            self._jobs[run_id] = job
            cancel_event = threading.Event()
            self._cancel_events[run_id] = cancel_event
            self._persist(job)
            thread = threading.Thread(target=self._execute, args=(run_id,), name=f"xiaoyi-{run_id}", daemon=True)
            self._threads[run_id] = thread
            thread.start()
        return self._public(job)

    def _update(self, run_id: str, mutate: Any) -> None:
        with self._lock:
            job = self._jobs[run_id]
            mutate(job)
            self._persist(job)

    def _execute(self, run_id: str) -> None:
        started = time.monotonic()
        try:
            with self._lock:
                job = self._jobs[run_id]
                job["status"] = "training"
                job["phase"] = "training"
                job["started_at"] = _now()
                self._persist(job)
                config = deepcopy(job["config"])
            definition = get_dataset(config["dataset_id"])
            records = load_records(definition)
            train, validation, _ = chronological_split(
                records,
                train_ratio=config["train_ratio"],
                validation_ratio=config["validation_ratio"],
            )
            parameters = derive_parameters(train)
            self._update(run_id, lambda item: item.__setitem__("environment", parameters.public_dict()))
            cancel_event = self._cancel_events[run_id]
            policies: dict[str, TrainedPolicy | PIDPolicy] = {"pid": PIDPolicy()}
            completed_total = 0
            selected_rl_algorithms = [item for item in config["algorithms"] if item in RL_ALGORITHM_IDS]
            total = config["episodes"] * len(selected_rl_algorithms)
            for algorithm_index, algorithm_id in enumerate(selected_rl_algorithms):
                if cancel_event.is_set():
                    raise InterruptedError("training cancelled")
                self._update(run_id, lambda item, algorithm_id=algorithm_id: item.__setitem__("current_algorithm_id", algorithm_id))

                def report(episode: int, point: dict[str, Any]) -> None:
                    nonlocal completed_total
                    completed_total = algorithm_index * config["episodes"] + episode
                    if episode != config["episodes"] and episode % max(1, config["episodes"] // 50) != 0:
                        return

                    def mutate(item: dict[str, Any]) -> None:
                        item["completed_training_episodes"] = completed_total
                        item["progress_percent"] = round(completed_total / total * 100, 2)
                        item["training"]["curve_tail"] = (item["training"]["curve_tail"] + [{"algorithm_id": algorithm_id, **point}])[-120:]

                    self._update(run_id, mutate)

                policy, curve = train_tabular_policy(
                    algorithm_id,
                    train,
                    parameters,
                    episodes=config["episodes"],
                    horizon_steps=config["horizon_steps"],
                    seed=config["seed"] + algorithm_index * 1009,
                    learning_rate=config["learning_rate"],
                    discount_factor=config["discount_factor"],
                    epsilon_start=config["epsilon_start"],
                    epsilon_end=config["epsilon_end"],
                    progress=report,
                    cancelled=cancel_event.is_set,
                )
                policies[algorithm_id] = policy
                model_path = self._run_dir(run_id) / "models" / f"{algorithm_id}.json"
                model_payload = policy.public_dict()
                _atomic_json(model_path, model_payload)
                model_hash = file_sha256(model_path)

                def record_algorithm(item: dict[str, Any]) -> None:
                    item["training"]["algorithms"][algorithm_id] = {
                        "status": "trained",
                        "episodes": config["episodes"],
                        "final_reward": curve[-1]["reward"],
                        "final_reward_ema": curve[-1]["reward_ema"],
                        "state_count": model_payload["state_count"],
                        "artifact": str(model_path.relative_to(BASE_DIR)),
                        "artifact_sha256": model_hash,
                        "curve": curve,
                    }

                self._update(run_id, record_algorithm)

            if "pid" in config["algorithms"]:
                pid_path = self._run_dir(run_id) / "models" / "pid.json"
                _atomic_json(pid_path, policies["pid"].public_dict())
                self._update(
                    run_id,
                    lambda item: item["training"]["algorithms"].__setitem__(
                        "pid",
                        {
                            "status": "configured_control_baseline",
                            "episodes": 0,
                            "artifact": str(pid_path.relative_to(BASE_DIR)),
                            "artifact_sha256": file_sha256(pid_path),
                            "curve": [],
                        },
                    ),
                )
            validation_results = [
                evaluate_policy(
                    algorithm_id,
                    policies[algorithm_id],
                    validation,
                    parameters,
                    horizon_steps=config["horizon_steps"],
                    seed=config["seed"] + 50_000,
                    render=False,
                )
                for algorithm_id in config["algorithms"]
            ]
            winner = max(validation_results, key=lambda item: item["metrics"]["score"])["algorithm_id"]

            def complete(item: dict[str, Any]) -> None:
                item["status"] = "trained"
                item["phase"] = "awaiting_test"
                item["progress_percent"] = 100.0
                item["completed_training_episodes"] = total
                item["current_algorithm_id"] = None
                item["finished_at"] = _now()
                item["duration_seconds"] = round(time.monotonic() - started, 3)
                item["validation"]["results"] = [
                    {"algorithm_id": result["algorithm_id"], "metrics": result["metrics"]}
                    for result in validation_results
                ]
                item["validation"]["best_algorithm_id"] = winner
                item["reproducibility"]["test_rows_touched_during_training"] = False

            self._update(run_id, complete)
        except InterruptedError as exc:
            error_message = str(exc)
            self._update(
                run_id,
                lambda item: item.update(
                    status="cancelled",
                    phase="cancelled",
                    finished_at=_now(),
                    duration_seconds=round(time.monotonic() - started, 3),
                    error=error_message,
                ),
            )
        except Exception as exc:  # pragma: no cover - exercised through integration failure paths
            error_message = str(exc)
            detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-12000:]
            self._update(
                run_id,
                lambda item: item.update(
                    status="failed",
                    phase="failed",
                    finished_at=_now(),
                    duration_seconds=round(time.monotonic() - started, 3),
                    error=error_message,
                    error_trace=detail,
                ),
            )

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            if run_id not in self._jobs:
                raise RunNotFound(run_id)
            return self._public(self._jobs[run_id])

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: item.get("created_at", ""), reverse=True)
            return [self._public(job) for job in jobs[:limit]]

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            if run_id not in self._jobs:
                raise RunNotFound(run_id)
            job = self._jobs[run_id]
            if job["status"] not in {"queued", "training"}:
                raise RunConflict(f"run {run_id} cannot be cancelled from status {job['status']}")
            self._cancel_events[run_id].set()
            job["status"] = "cancelling"
            job["phase"] = "cancelling"
            self._persist(job)
            return self._public(job)

    def _load_policy(self, run_id: str, algorithm_id: str) -> TrainedPolicy | PIDPolicy:
        path = self._run_dir(run_id) / "models" / f"{algorithm_id}.json"
        if not path.is_file():
            raise RunConflict(f"model artifact is missing for {algorithm_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if algorithm_id == "pid":
            hyper = payload.get("hyperparameters", {})
            return PIDPolicy(
                kp=float(hyper.get("kp", 0.85)),
                ki=float(hyper.get("ki", 0.06)),
                kd=float(hyper.get("kd", 0.12)),
                soc_gain=float(hyper.get("soc_gain", 0.35)),
            )
        return TrainedPolicy.from_dict(payload)

    def evaluate_run(self, run_id: str, *, algorithms: Optional[list[str]] = None) -> dict[str, Any]:
        with self._lock:
            if run_id not in self._jobs:
                raise RunNotFound(run_id)
            job = deepcopy(self._jobs[run_id])
        if job["status"] not in {"trained", "evaluated"}:
            raise RunConflict("test rendering is available only after all training algorithms finish")
        selected = list(dict.fromkeys(algorithms or job["config"]["algorithms"]))
        invalid = sorted(set(selected) - set(job["config"]["algorithms"]))
        if invalid:
            raise ValueError(f"algorithms were not part of this run: {invalid}")
        definition = get_dataset(job["config"]["dataset_id"])
        records = load_records(definition)
        train, _, test = chronological_split(
            records,
            train_ratio=job["config"]["train_ratio"],
            validation_ratio=job["config"]["validation_ratio"],
        )
        parameters = derive_parameters(train)
        results = [
            evaluate_policy(
                algorithm_id,
                self._load_policy(run_id, algorithm_id),
                test,
                parameters,
                horizon_steps=job["config"]["horizon_steps"],
                seed=job["config"]["seed"] + 90_000,
                render=True,
            )
            for algorithm_id in selected
        ]
        winner = max(results, key=lambda item: item["metrics"]["score"])["algorithm_id"]
        evaluation = {
            "evaluation_id": f"eval-{uuid4().hex[:10]}",
            "run_id": run_id,
            "created_at": _now(),
            "data_split": "test",
            "test_rows": len(test),
            "rendering_performed": True,
            "render_mode": "trace",
            "results": results,
            "best_algorithm_id": winner,
            "production_execution": False,
            "notice": "测试轨迹仅在全部训练完成后由未参与训练的时间后段数据生成；未连接生产控制接口。",
        }
        evaluation_path = self._run_dir(run_id) / "evaluations" / f"{evaluation['evaluation_id']}.json"
        _atomic_json(evaluation_path, evaluation)
        evaluation["artifact"] = str(evaluation_path.relative_to(BASE_DIR))
        evaluation["artifact_sha256"] = file_sha256(evaluation_path)

        def mark(item: dict[str, Any]) -> None:
            item["status"] = "evaluated"
            item["phase"] = "test_rendered"
            item["test_evaluation"] = {
                "evaluation_id": evaluation["evaluation_id"],
                "created_at": evaluation["created_at"],
                "best_algorithm_id": winner,
                "artifact": evaluation["artifact"],
                "artifact_sha256": evaluation["artifact_sha256"],
                "rendering_performed": True,
            }
            item["reproducibility"]["test_rows_touched_during_training"] = False

        self._update(run_id, mark)
        return evaluation


rl_lab_service = RLLabService()
