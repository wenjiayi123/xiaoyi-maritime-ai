"""Bounded business-policy experiments. Training never changes a language model."""
from __future__ import annotations

import hashlib
import json
import statistics
import threading
import time
from pathlib import Path
from uuid import uuid4

from pydantic import Field, model_validator

from app.config import BASE_DIR
from app.harness.contracts import StrictModel, digest, now
from app.harness.store import Conflict
from app.harness.local_lock import ProcessLease
from app.harness import policy_assurance
from app.rl_lab.algorithms import ConfiguredBaselinePolicy, PIDPolicy, TrainedPolicy, evaluate_policy, train_tabular_policy
from app.rl_lab.contracts import environment_contract
from app.rl_lab.datasets import chronological_split, file_sha256, get_dataset, load_records
from app.rl_lab.environment import derive_parameters
from app.rl_lab.port_environment import derive_port_parameters
from app.runtime_store import runtime_store

ROOT = BASE_DIR / ".runtime" / "harness-research"
KIND = "harness_research_v1"
_lock = threading.RLock()
_active: set[str] = set()
_cancel: dict[str, threading.Event] = {}
_executor_lease = None


def source_hashes():
    root = Path(__file__).resolve().parents[2]
    return {name: file_sha256(root / "app" / name) for name in
            ["rl_lab/environment.py", "rl_lab/port_environment.py", "rl_lab/algorithms.py",
             "rl_lab/contracts.py", "rl_lab/datasets.py", "harness/research.py", "harness/local_lock.py",
             "harness/policy_assurance.py"]}


def dataset_contract(definition):
    metadata = definition.public_dict(inspect_file=False) if hasattr(definition, "public_dict") else {"environment_type": definition.environment_type}
    profile = getattr(definition, "profile_path", None)
    provenance = definition.path.with_suffix(".provenance.json")
    return {"metadata": metadata, "profile_sha256": file_sha256(profile) if profile else None,
            "provenance_sha256": file_sha256(provenance) if provenance.is_file() else None}


class ExperimentArgs(StrictModel):
    dataset_id: str = Field("noaa_la_lb_ais_2024_12_25_1min", min_length=1, max_length=100)
    algorithms: list[str] = Field(default_factory=lambda: ["q_learning", "double_q_learning"], min_length=1, max_length=4)
    seeds: list[int] = Field(default_factory=lambda: [29101, 29102, 29103, 29104, 29105], min_length=1, max_length=5)
    episodes: int = Field(160, ge=10, le=400)
    horizon_steps: int = Field(24, ge=12, le=72)
    max_seconds: int = Field(300, ge=10, le=900)

    @model_validator(mode="after")
    def check(self):
        supported = {"q_learning", "sarsa", "expected_sarsa", "double_q_learning"}
        if len(set(self.algorithms)) != len(self.algorithms) or not set(self.algorithms) <= supported:
            raise ValueError("select unique registered RL algorithms")
        if len(set(self.seeds)) != len(self.seeds) or any(s < 0 or s > 2_000_000_000 for s in self.seeds):
            raise ValueError("seeds must be unique bounded nonnegative integers")
        return self


class StartExperiment(ExperimentArgs):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")


class CompareArgs(StrictModel):
    experiment_id: str | None = Field(None, pattern=r"^hr-[a-f0-9]{32}$")


class ReplayArgs(CompareArgs):
    algorithm: str | None = Field(None, max_length=40)
    seed: int | None = Field(None, ge=0, le=2_000_000_000)


def _write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False))
    temporary.replace(path)


def compare(config: ExperimentArgs, folder: Path, *, cancelled=lambda: False, progress=lambda *_: None):
    """Select on validation, evaluate the sealed temporal holdout once per policy/seed."""
    started = time.monotonic()
    sources = source_hashes()
    if sources != _LOADED_SOURCE_HASHES:
        raise ValueError("研究实现已在服务启动后变化，请重启服务，避免使用旧内存代码生成新版本证据")
    definition = get_dataset(config.dataset_id)
    data_contract = dataset_contract(definition)
    data_hash = file_sha256(definition.path)
    train, validation, test = chronological_split(load_records(definition), train_ratio=.7, validation_ratio=.15)
    if min(map(len, [train, validation, test])) <= config.horizon_steps:
        raise ValueError("each chronological split must exceed the episode horizon")
    env_id = definition.environment_type
    contract = environment_contract(env_id)
    parameters = derive_port_parameters(train) if env_id == "port_operations" else derive_parameters(train)
    _write(folder / "protocol.json", {"config": config.model_dump(), "dataset_sha256": data_hash,
                                      "protocol": policy_assurance.PROTOCOL, "source_hashes": sources,
                                      "frozen_before_training_at": now()})
    models, rows, curves, trace, stress_rows = [], [], {}, [], []
    stresses = policy_assurance.stress_cases(env_id, test, parameters)

    def stopped():
        return cancelled() or time.monotonic() - started > config.max_seconds

    for seed in config.seeds:
        if stopped():
            raise InterruptedError("experiment cancelled or resource budget exceeded")
        policies = {"sop_rule": ConfiguredBaselinePolicy("sop_rule"), "pid": PIDPolicy()}
        for algorithm in config.algorithms:
            policy, curve = train_tabular_policy(
                algorithm, train, parameters, episodes=config.episodes, horizon_steps=config.horizon_steps,
                seed=seed, learning_rate=.12, discount_factor=.97, epsilon_start=1., epsilon_end=.05,
                progress=lambda episode, point, a=algorithm, s=seed: progress(a, s, episode),
                cancelled=stopped, environment_type=env_id,
            )
            policies[algorithm] = policy
            path = folder / "models" / f"{algorithm}-{seed}.json"
            _write(path, {"policy": policy.public_dict(), "environment_contract": contract,
                          "dataset_sha256": data_hash, "seed": seed, "algorithm": algorithm})
            models.append({"algorithm": algorithm, "seed": seed, "path": str(path.relative_to(BASE_DIR)),
                           "sha256": file_sha256(path), "environment_version": contract["version"]})
            curves[f"{algorithm}:{seed}"] = curve
        validation_results = {
            name: evaluate_policy(name, policy, validation, parameters, horizon_steps=config.horizon_steps,
                                  seed=seed + 50000, render=False, environment_type=env_id)
            for name, policy in policies.items()
        }
        chosen = max(validation_results, key=lambda name: validation_results[name]["metrics"]["score"])
        for name, policy in policies.items():
            if stopped():
                raise InterruptedError("experiment cancelled or resource budget exceeded")
            result = evaluate_policy(name, policy, test, parameters, horizon_steps=config.horizon_steps,
                                     seed=seed + 90000, render=True, environment_type=env_id)
            rows.append({"algorithm": name, "seed": seed, "selected_on_validation": name == chosen,
                         "validation_metrics": validation_results[name]["metrics"], "test_metrics": result["metrics"],
                         "test_episodes": result["episodes"]})
            if seed == config.seeds[0] and name in {chosen, config.algorithms[0], "sop_rule"}:
                trace.append({"algorithm": name, "seed": seed, "frames": result.get("frames", result.get("trace", []))})
            for scenario, stress_records, stress_parameters, overrides in stresses:
                if stopped():
                    raise InterruptedError("experiment cancelled or resource budget exceeded")
                stress = evaluate_policy(name, policy, stress_records, stress_parameters,
                                         horizon_steps=config.horizon_steps, seed=seed + 90000,
                                         render=True, environment_type=env_id)
                stress_rows.append({"algorithm": name, "seed": seed, "scenario": scenario,
                                    "synthetic_overrides": overrides, "metrics": stress["metrics"],
                                    "episodes": stress["episodes"], "data_mode": "synthetic_test_intervention"})
    if file_sha256(definition.path) != data_hash:
        raise ValueError("dataset changed during experiment")
    if source_hashes() != sources:
        raise ValueError("experiment sources changed during execution")
    if dataset_contract(get_dataset(config.dataset_id)) != data_contract:
        raise ValueError("dataset mapping or profile changed during execution")
    aggregate = []
    for name in ["sop_rule", "pid", *config.algorithms]:
        samples = [r for r in rows if r["algorithm"] == name]
        metrics = {key: round(statistics.mean(r["test_metrics"][key] for r in samples), 6)
                   for key, value in samples[0]["test_metrics"].items() if type(value) in {int, float}}
        scores = [r["test_metrics"]["score"] for r in samples]
        aggregate.append({"algorithm": name, "family": "rl" if name in config.algorithms else "baseline",
                          "metrics": metrics, "seeds": len(samples),
                          "score_stdev": round(statistics.stdev(scores), 6) if len(scores) > 1 else 0.,
                          "validation_score": statistics.mean(r["validation_metrics"]["score"] for r in samples)})
    assurance = policy_assurance.assess(rows, config.algorithms, stress_rows)
    selected = assurance["selected_algorithm"]
    baseline_score = max(r["metrics"]["score"] for r in aggregate if r["family"] == "baseline")
    for row in aggregate:
        row["delta_vs_best_baseline"] = round(row["metrics"]["score"] - baseline_score, 6)
        decision = next(d for d in assurance["decisions"] if d["algorithm"] == row["algorithm"])
        row["research_admission"] = decision["research_admission"]
        row["assurance"] = decision
        row["enterprise_admission"] = False
    report = {
        "schema": "xiaoyi-harness-research.v1", "created_at": now(), "config": config.model_dump(),
        "source_hashes": sources,
        "dataset_contract": data_contract, "dataset_contract_sha256": digest(data_contract),
        "environment": contract, "parameters": parameters.public_dict(), "dataset_id": config.dataset_id,
        "dataset_sha256": data_hash, "data_split": {"train": len(train), "validation": len(validation), "test": len(test)},
        "selection_basis": "validation_only", "selected_algorithm": selected,
        "observation_information": "current_and_past_only", "test_used_for_training": False,
        "aggregate": aggregate, "runs": rows, "models": models, "curves": curves, "traces": trace,
        "policy_assurance": assurance, "stress_runs": stress_rows,
        "data_support": policy_assurance.data_support(train, test, env_id),
        "evaluation_protocol_sha256": digest(policy_assurance.PROTOCOL),
        "duration_seconds": round(time.monotonic() - started, 3), "production_authority": False,
        "notice": "公开数据离线代理环境；验证集固定选型和基线，按种子配对区间、最差种子及三项合成压力门禁评估。统计推断条件于固定测试窗口，不证明现场收益或安全认证；研究准入不等于企业执行准入。",
    }
    _write(folder / "report.json", report)
    return report


def _save(job):
    runtime_store.save_artifact(KIND, job["id"], job, max_items=100)


def get(experiment_id, actor_id=None, admin=False):
    job = runtime_store.get_artifact(KIND, experiment_id)
    if not job:
        raise ValueError("研究任务不存在")
    if actor_id is not None and job["actor_id"] != actor_id and not admin:
        raise PermissionError("只能访问自己的研究任务")
    return job


def list_jobs(actor_id, admin=False):
    return [j for j in runtime_store.list_artifacts(KIND, limit=100) if admin or j["actor_id"] == actor_id]


def start(payload: StartExperiment, actor_id: str):
    global _executor_lease
    with _lock:
        for old in list_jobs(actor_id):
            if old["request_id"] == payload.request_id:
                if old["request_sha256"] != digest(payload.model_dump()):
                    raise Conflict("同一研究请求编号不能改变配置")
                return old
        if _active:
            raise Conflict("已有研究任务运行，训练串行执行以保留业务资源")
        _executor_lease = ProcessLease(runtime_store.path.with_suffix(".research.lock")).acquire()
        job = {"id": "hr-" + uuid4().hex, "actor_id": actor_id, "request_id": payload.request_id,
               "request_sha256": digest(payload.model_dump()), "status": "running", "created_at": now(),
               "config": payload.model_dump(exclude={"request_id"}), "progress": {}, "production_authority": False}
        _save(job)
        _active.add(job["id"])
        _cancel[job["id"]] = threading.Event()
    threading.Thread(target=_run, args=(job["id"],), daemon=True, name="harness-research").start()
    return job


def _run(job_id):
    try:
        job = get(job_id)
        def progress(algorithm, seed, episode):
            if episode % 10 == 0:
                with _lock:
                    current = get(job_id)
                    current["progress"] = {"algorithm": algorithm, "seed": seed, "episode": episode}
                    _save(current)
        folder = ROOT / job_id
        report = compare(ExperimentArgs(**job["config"]), folder, cancelled=_cancel[job_id].is_set, progress=progress)
        with _lock:
            job = get(job_id)
            job.update(status="completed", finished_at=now(), report_path=str((folder / "report.json").relative_to(BASE_DIR)),
                       report_sha256=file_sha256(folder / "report.json"), summary={k:report[k] for k in
                        ["dataset_id", "environment", "aggregate", "selected_algorithm", "policy_assurance", "data_support", "duration_seconds", "notice"]})
            _save(job)
    except Exception as exc:
        with _lock:
            job = get(job_id)
            job.update(status="cancelled" if isinstance(exc, InterruptedError) else "failed", error=str(exc)[:500], finished_at=now())
            _save(job)
    finally:
        with _lock:
            _active.discard(job_id)
            _cancel.pop(job_id, None)
            if _executor_lease is not None:
                _executor_lease.release()


def cancel(job_id, actor_id, admin=False):
    with _lock:
        job = get(job_id, actor_id, admin)
        if job_id in _cancel:
            _cancel[job_id].set()
            job["status"] = "cancelling"
            _save(job)
        return job


def report_for(args: CompareArgs, actor_id, admin=False):
    if args.experiment_id:
        job = get(args.experiment_id, actor_id, admin)
    else:
        job = next((j for j in list_jobs(actor_id, admin) if j["status"] == "completed"), None)
        if job is None:
            raise ValueError("尚无已完成研究实验，请先显式创建训练或评测任务")
    if job["status"] != "completed":
        raise ValueError("研究实验尚未完成")
    path = BASE_DIR / job["report_path"]
    if file_sha256(path) != job["report_sha256"]:
        raise ValueError("研究报告哈希不一致")
    report = json.loads(path.read_text())
    if report.get("source_hashes") != source_hashes():
        raise ValueError("实验执行源码版本变化或缺少指纹；原报告保留为历史结果")
    definition = get_dataset(report["dataset_id"])
    if report.get("dataset_contract_sha256") != digest(dataset_contract(definition)):
        raise ValueError("数据字段映射、时区或港口profile版本变化")
    if file_sha256(definition.path) != report["dataset_sha256"]:
        raise ValueError("研究源数据已变化，结果仅可作为历史工件")
    if report["environment"]["version"] != environment_contract(definition.environment_type)["version"]:
        raise ValueError("研究环境版本已变化")
    for model in report["models"]:
        if file_sha256(BASE_DIR / model["path"]) != model["sha256"]:
            raise ValueError("策略工件哈希不一致")
    return {"experiment_id": job["id"], "report_sha256": job["report_sha256"],
            **{k:report[k] for k in ["schema", "environment", "dataset_id", "dataset_sha256", "data_split",
                "selection_basis", "selected_algorithm", "aggregate", "models", "source_hashes", "notice", "production_authority"]},
            **{k: report[k] for k in ["policy_assurance", "data_support", "evaluation_protocol_sha256"] if k in report}}


def recover():
    with _lock:
        if _active:
            return
        lease = _executor_lease
        try:
            if lease is None or lease.handle is None:
                lease = ProcessLease(runtime_store.path.with_suffix(".research.lock")).acquire()
        except Conflict:
            return
        try:
            for job in runtime_store.list_artifacts(KIND, limit=100):
                if job["status"] in {"running", "cancelling"}:
                    job.update(status="interrupted", finished_at=now(), error="服务重启；旧实验保留，未自动重训")
                    _save(job)
        finally:
            lease.release()


def replay(args: ReplayArgs, actor_id, admin=False):
    verified = report_for(CompareArgs(experiment_id=args.experiment_id), actor_id, admin)
    job = get(verified["experiment_id"], actor_id, admin)
    algorithm = args.algorithm or verified["selected_algorithm"]
    if algorithm not in {r["algorithm"] for r in verified["aggregate"]}:
        raise ValueError("策略不属于此实验")
    seed = args.seed if args.seed is not None else job["config"]["seeds"][0]
    if seed not in job["config"]["seeds"]:
        raise ValueError("种子不属于此实验")
    if algorithm == "sop_rule":
        policy = ConfiguredBaselinePolicy("sop_rule")
        model_hash = digest(policy.public_dict())
    elif algorithm == "pid":
        policy = PIDPolicy()
        model_hash = digest(policy.public_dict())
    else:
        entry = next(r for r in verified["models"] if r["algorithm"] == algorithm and r["seed"] == seed)
        policy = TrainedPolicy.from_dict(json.loads((BASE_DIR / entry["path"]).read_text())["policy"])
        model_hash = entry["sha256"]
    definition = get_dataset(verified["dataset_id"])
    train, _, test = chronological_split(load_records(definition), train_ratio=.7, validation_ratio=.15)
    env_id = definition.environment_type
    parameters = derive_port_parameters(train) if env_id == "port_operations" else derive_parameters(train)
    result = evaluate_policy(algorithm, policy, test, parameters, horizon_steps=job["config"]["horizon_steps"],
                             seed=seed + 90000, render=True, environment_type=env_id)
    return {"experiment_id": job["id"], "seed": seed, "model_sha256": model_hash,
            "environment_version": verified["environment"]["version"], "dataset_sha256": verified["dataset_sha256"],
            "source_report_sha256": verified["report_sha256"], "result": result,
            "production_authority": False, "notice": "按已封存模型与数据重新推理的离线测试回放；不是在线训练或现场执行。"}


# Bind the actual imported implementation, not just whatever happens to be on disk later.
_LOADED_SOURCE_HASHES = source_hashes()
