"""Persistent bounded study jobs; shared research lease prevents competing trainers."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from uuid import uuid4

from pydantic import Field

from app.config import BASE_DIR
from app.harness import crossport_benchmark as benchmark, portwatch_data, multisite_twin
from app.harness.contracts import StrictModel, digest, now
from app.harness.local_lock import ProcessLease
from app.harness.store import Conflict
from app.runtime_store import runtime_store

KIND = "harness_crossport_study_v1"
_lock = threading.RLock()
_active = {}
LOADED_HASHES = benchmark.source_hashes()


class Start(benchmark.Config):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")


class CompareArgs(StrictModel):
    study_id: str | None = Field(None, pattern=r"^hc-[a-f0-9]{32}$")


def compare(args, actor_id, admin=False):
    job = (
        get(args.study_id, actor_id, admin)
        if args.study_id
        else next((j for j in list_jobs(actor_id, admin) if j["status"] == "completed"), None)
    )
    if not job:
        raise ValueError("请先在跨港工作台显式运行研究；不会静默训练或伪造结果")
    value = report(job["id"], actor_id, admin)
    return {
        "study_id": job["id"],
        "report_sha256": job["report_sha256"],
        **{
            k: value[k]
            for k in [
                "schema",
                "protocol",
                "selected_algorithm",
                "comparator_algorithm",
                "aggregate",
                "twin_calibration",
                "multisite_physical_calibration",
                "source_hashes",
                "manifest_sha256",
                "historical_only",
                "current_validation_issues",
                "notice",
                "production_authority",
            ]
        },
    }


def get(job_id, actor_id, admin=False):
    job = runtime_store.get_artifact(KIND, job_id)
    if not job:
        raise ValueError("跨港研究任务不存在")
    if job["actor_id"] != actor_id and not admin:
        raise PermissionError("只能读取自己的跨港研究任务")
    return job


def save(job):
    runtime_store.save_artifact(KIND, job["id"], job, max_items=100)


def list_jobs(actor_id, admin=False):
    return [r for r in runtime_store.list_artifacts(KIND, limit=100) if admin or r["actor_id"] == actor_id]


def start(payload, actor_id):
    import importlib.metadata

    try:
        importlib.metadata.version("numpy")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ValueError("请先安装 requirements-research.txt 中的固定研究依赖") from exc
    if benchmark.source_hashes() != LOADED_HASHES:
        raise ValueError("跨港实现已改变，请重启服务后冻结新协议")
    if not portwatch_data.catalog()["available"]:
        raise ValueError("跨港公开源尚未完整校验，不能训练")
    with _lock:
        for old in list_jobs(actor_id):
            if old["request_id"] == payload.request_id:
                if old["request_sha256"] != digest(payload.model_dump()):
                    raise Conflict("同一研究请求不能改写配置")
                return old
        lease = ProcessLease(runtime_store.path.with_suffix(".research.lock")).acquire()
        job = {
            "id": "hc-" + uuid4().hex,
            "actor_id": actor_id,
            "request_id": payload.request_id,
            "request_sha256": digest(payload.model_dump()),
            "config": payload.model_dump(exclude={"request_id"}),
            "status": "running",
            "created_at": now(),
            "progress": {},
            "production_authority": False,
        }
        save(job)
        _active[job["id"]] = {"cancel": threading.Event(), "lease": lease}
    threading.Thread(target=run, args=(job["id"],), name="crossport-study", daemon=True).start()
    return job


def run(job_id):
    try:
        job = get(job_id, None, True)

        def progress(stage, item, detail):
            with _lock:
                current = get(job_id, None, True)
                current["progress"] = {"stage": stage, "item": item, "detail": detail, "at": now()}
                save(current)

        report = benchmark.run(
            benchmark.Config(**job["config"]),
            benchmark.ROOT / job_id,
            cancelled=_active[job_id]["cancel"].is_set,
            progress=progress,
        )
        path = benchmark.ROOT / job_id / "report.json"
        with _lock:
            current = get(job_id, None, True)
            current.update(
                status="completed",
                finished_at=now(),
                report_path=str(path.relative_to(BASE_DIR)),
                report_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                summary={
                    k: report[k]
                    for k in ["selected_algorithm", "comparator_algorithm", "aggregate", "duration_seconds", "notice"]
                },
            )
            save(current)
    except Exception as exc:
        with _lock:
            current = get(job_id, None, True)
            current.update(
                status="cancelled" if isinstance(exc, InterruptedError) else "failed",
                error=type(exc).__name__ + ": " + str(exc)[:500],
                finished_at=now(),
            )
            save(current)
    finally:
        with _lock:
            state = _active.pop(job_id, None)
            if state:
                state["lease"].release()


def cancel(job_id, actor_id, admin=False):
    with _lock:
        job = get(job_id, actor_id, admin)
        if job_id in _active:
            _active[job_id]["cancel"].set()
            job["status"] = "cancelling"
            save(job)
        return job


def report(job_id, actor_id, admin=False):
    job = get(job_id, actor_id, admin)
    if job["status"] != "completed":
        raise ValueError("跨港研究尚未完成")
    path = BASE_DIR / job["report_path"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != job["report_sha256"]:
        raise ValueError("跨港报告摘要不一致")
    value = json.loads(path.read_text())
    issues = []
    if value["source_hashes"] != benchmark.source_hashes():
        issues.append("实现版本已变化")
    try:
        manifest, _ = portwatch_data.load_all()
        if digest(manifest) != value["manifest_sha256"]:
            issues.append("公开数据版本变化")
        for m in value["models"]:
            if hashlib.sha256((BASE_DIR / m["path"]).read_bytes()).hexdigest() != m["sha256"]:
                issues.append("策略工件变化")
        if hashlib.sha256((BASE_DIR / value["trace_file"]).read_bytes()).hexdigest() != value["trace_sha256"]:
            issues.append("轨迹工件变化")
        physical_manifest, _ = multisite_twin.load()
        if digest(physical_manifest) != value["multisite_physical_calibration"]["source_manifest_sha256"]:
            issues.append("物理标定源版本变化")
    except (OSError, ValueError) as exc:
        issues.append(str(exc))
    return {**value, "historical_only": bool(issues), "current_validation_issues": issues}


def diagnosis():
    registry = json.loads((BASE_DIR / "config/crossport_evidence_registry.json").read_text())["legacy_diagnosis"]
    path = (BASE_DIR / registry["path"]).resolve()
    if (
        not path.is_relative_to(BASE_DIR.resolve())
        or hashlib.sha256(path.read_bytes()).hexdigest() != registry["sha256"]
    ):
        raise ValueError("旧RL诊断工件校验失败，保留历史不继续引用")
    return json.loads(path.read_text())


def recover():
    if _active:
        return
    try:
        lease = ProcessLease(runtime_store.path.with_suffix(".research.lock")).acquire()
    except Conflict:
        return
    try:
        for job in runtime_store.list_artifacts(KIND, limit=100):
            if job["status"] in {"running", "cancelling"}:
                job.update(status="interrupted", finished_at=now(), error="服务重启，未自动重训")
                save(job)
    finally:
        lease.release()
