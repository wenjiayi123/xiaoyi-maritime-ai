from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import BASE_DIR  # noqa: E402
from app.rl_lab.algorithms import ALL_ALGORITHM_IDS  # noqa: E402
from app.rl_lab.datasets import dataset_catalog, file_sha256  # noqa: E402
from app.rl_lab.service import RLLabService  # noqa: E402


REPORT_JSON = BASE_DIR / "reports" / "rl_dataset_benchmark_v1.json"
REPORT_MARKDOWN = BASE_DIR / "reports" / "rl_dataset_benchmark_v1.md"
EVIDENCE_DIR = BASE_DIR / "reports" / "rl_evidence"
LEGACY_RUN_ID = "rl-20260724T120838-ecbd3029"
DATASET_IDS = (
    "uci_appliances_energy",
    "uci_household_power_5min",
    "noaa_la_lb_ais_2024_12_25_1min",
)
DEFAULT_SEEDS = (260726, 260727, 260728)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    return str(path.relative_to(BASE_DIR))


def _wait_for_training(service: RLLabService, run_id: str, timeout_seconds: int = 900) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        run = service.get_run(run_id)
        if run["status"] not in {"queued", "training", "cancelling"}:
            return run
        time.sleep(0.1)
    raise TimeoutError(f"training timeout: {run_id}")


def _run_one(
    service: RLLabService,
    dataset_id: str,
    *,
    episodes: int,
    horizon_steps: int,
    seed: int,
) -> dict[str, Any]:
    started = service.start_run(
        {
            "dataset_id": dataset_id,
            "algorithms": list(ALL_ALGORITHM_IDS),
            "episodes": episodes,
            "horizon_steps": horizon_steps,
            "seed": seed,
            "train_ratio": 0.70,
            "validation_ratio": 0.15,
        }
    )
    run = _wait_for_training(service, started["run_id"])
    if run["status"] != "trained":
        raise RuntimeError(f"{run['run_id']} failed: {run.get('error') or run['status']}")
    evaluation = service.evaluate_run(run["run_id"])
    final_run = service.get_run(run["run_id"])
    return {
        "run_id": run["run_id"],
        "seed": seed,
        "duration_seconds": final_run["duration_seconds"],
        "dataset_sha256": final_run["reproducibility"]["dataset_sha256"],
        "config_sha256": final_run["reproducibility"]["config_sha256"],
        "profile_sha256": final_run["reproducibility"].get("profile_sha256"),
        "split": final_run["dataset"]["split"],
        "training_render_mode": final_run["training"]["render_mode"],
        "training_rendering_performed": final_run["training"]["rendering_performed"],
        "test_render_mode": evaluation["render_mode"],
        "test_rendering_performed": evaluation["rendering_performed"],
        "test_artifact": evaluation["artifact"],
        "test_artifact_sha256": evaluation["artifact_sha256"],
        "validation_best_algorithm_id": final_run["validation"]["best_algorithm_id"],
        "test_best_algorithm_id": evaluation["best_algorithm_id"],
        "results": [
            {
                "algorithm_id": result["algorithm_id"],
                "metrics": result["metrics"],
                "frame_count": len(result.get("frames") or []),
            }
            for result in evaluation["results"]
        ],
    }


def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    algorithms = sorted(
        {
            result["algorithm_id"]
            for run in runs
            for result in run["results"]
        }
    )
    summaries: dict[str, Any] = {}
    for algorithm_id in algorithms:
        metrics = [
            result["metrics"]
            for run in runs
            for result in run["results"]
            if result["algorithm_id"] == algorithm_id
        ]
        numeric_fields = sorted(
            set.intersection(
                *[
                    {
                        key
                        for key, value in metric.items()
                        if isinstance(value, (int, float)) and not isinstance(value, bool)
                    }
                    for metric in metrics
                ]
            )
        )
        summaries[algorithm_id] = {
            field: {
                "mean": round(statistics.fmean(float(item[field]) for item in metrics), 6),
                "stddev": round(
                    statistics.pstdev(float(item[field]) for item in metrics),
                    6,
                ),
            }
            for field in numeric_fields
        }
    winner_counts = {
        algorithm_id: sum(run["test_best_algorithm_id"] == algorithm_id for run in runs)
        for algorithm_id in algorithms
    }
    best_by_mean_score = max(
        algorithms,
        key=lambda algorithm_id: summaries[algorithm_id]["score"]["mean"],
    )
    return {
        "seed_count": len(runs),
        "algorithm_metrics": summaries,
        "test_winner_counts": winner_counts,
        "best_algorithm_by_mean_test_score": best_by_mean_score,
    }


def _copy_run_bundle(run_id: str, destination: Path) -> list[Path]:
    source = BASE_DIR / "data" / "rl_runs" / run_id
    if not source.is_dir():
        raise FileNotFoundError(f"run evidence is missing: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    model_relatives = [
        path.relative_to(source)
        for path in sorted((source / "models").glob("*.json"))
    ]
    for relative in [Path("run.json"), *model_relatives]:
        source_path = source / relative
        if source_path.is_file():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
            copied.append(target)
    evaluations = sorted((source / "evaluations").glob("*.json"))
    if evaluations:
        target = destination / "evaluations" / evaluations[-1].name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(evaluations[-1], target)
        copied.append(target)
    return copied


def _export_evidence(
    experiments: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    selected_runs: dict[str, str] = {}
    copied_files: list[Path] = []
    legacy_destination = EVIDENCE_DIR / "legacy_uci_smoke_20260724"
    copied_files.extend(_copy_run_bundle(LEGACY_RUN_ID, legacy_destination))
    selected_runs["legacy_uci_smoke"] = LEGACY_RUN_ID

    for dataset_id, experiment in experiments.items():
        aggregate_winner = experiment["aggregate"]["best_algorithm_by_mean_test_score"]
        selected = max(
            experiment["runs"],
            key=lambda run: next(
                result["metrics"]["score"]
                for result in run["results"]
                if result["algorithm_id"] == aggregate_winner
            ),
        )
        selected_runs[dataset_id] = selected["run_id"]
        copied_files.extend(
            _copy_run_bundle(
                selected["run_id"],
                EVIDENCE_DIR / dataset_id / "selected_run",
            )
        )

    evidence_hashes = {_relative(path): _sha256(path) for path in sorted(copied_files)}
    for dataset_id in DATASET_IDS:
        definition = dataset_catalog()[dataset_id]
        evidence_hashes[_relative(definition.path)] = file_sha256(definition.path)
        provenance_path = definition.path.with_suffix(".provenance.json")
        if provenance_path.is_file():
            evidence_hashes[_relative(provenance_path)] = _sha256(provenance_path)
        if definition.profile_path is not None and definition.profile_path.is_file():
            evidence_hashes[_relative(definition.profile_path)] = _sha256(definition.profile_path)
    return selected_runs, dict(sorted(evidence_hashes.items()))


def _markdown(report: dict[str, Any]) -> str:
    rows = []
    for dataset_id, experiment in report["experiments"].items():
        dataset = experiment["dataset"]
        aggregate = experiment["aggregate"]
        winner = aggregate["best_algorithm_by_mean_test_score"]
        metrics = aggregate["algorithm_metrics"][winner]
        if dataset["environment_type"] == "energy_storage":
            headline = (
                f"平均测试节费代理 {metrics['cost_saving_percent']['mean']:.2f}%；"
                f"峰值变化 {metrics['peak_reduction_percent']['mean']:.2f}%；"
                f"终端SOC {metrics['terminal_soc']['mean']:.3f}；"
                f"平均约束违例 {metrics['constraint_violations']['mean']:.2f}"
            )
        else:
            headline = (
                f"平均校准场景积压 {metrics['average_backlog_units']['mean']:.2f}；"
                f"平均约束违例 {metrics['constraint_violations']['mean']:.2f}"
            )
        rows.append(
            f"| `{dataset_id}` | {dataset['row_count']:,} | {dataset['environment_type']} | "
            f"{winner} | {headline} |"
        )
    scale = report["dataset_comparison"]["large_to_original_row_ratio"]
    return f"""# 小懿 RL 公开数据对比证据 v1

生成时间：{report['generated_at']}

本报告使用固定时间顺序 70%/15%/15% 训练、验证、测试隔离，训练阶段不渲染；全部训练结束后才读取保留测试段并生成轨迹。每套数据使用 {report['configuration']['seed_count']} 个随机种子、4 种 RL 与 1 个 PID 控制基线。

| 数据集 | 行数 | 环境 | 多种子平均测试优选 | 保留测试摘要 |
|---|---:|---|---|---|
{chr(10).join(rows)}

## 可信度结论

- 新的大规模公开能源基准为 {report['dataset_comparison']['large_rows']:,} 行，是原 {report['dataset_comparison']['original_rows']:,} 行基准的 {scale:.2f} 倍。它提高的是算法规模、重复性与分布跨度证据，不是港口现场真实性。
- NOAA 港口场景来自 AIS 实测交通消息。船舶数量、航速、航行状态和船型来自公开观测；服务量、积压、等待和得分是校准仿真输出，不是洛杉矶或长滩码头生产 KPI。
- 多种子结果允许 PID 胜出。发布证据保留真实比较结果，不为了展示 RL 而隐藏控制基线。
- 接真实港口仍需提供 DCSA/TOS/VTS/EMS、泊位、堆场、设备、工班、潮汐、天气、闸口与授权字段，并在现场数据上重新标定和测试。

## 可复现与门禁

- 算法：Q-learning、SARSA、Expected SARSA、Double Q-learning、PID。
- 每种 RL：{report['configuration']['episodes']} 回合；单回合 {report['configuration']['horizon_steps']} 步。
- 固定种子：{', '.join(str(seed) for seed in report['configuration']['seeds'])}。
- 数据、端口配置、模型和测试结果均进入 SHA-256 证据清单。
- 旧的 2026-07-24 UCI 10 回合训练包原样保存在 `reports/rl_evidence/legacy_uci_smoke_20260724/`，并明确标注为烟雾级运行。

PASS 定义：{report['pass_definition']}

范围声明：{report['scope_notice']}
"""


def run_benchmark(episodes: int, horizon_steps: int, seeds: tuple[int, ...]) -> dict[str, Any]:
    definitions = dataset_catalog()
    missing = [dataset_id for dataset_id in DATASET_IDS if not definitions[dataset_id].path.is_file()]
    if missing:
        raise FileNotFoundError(f"datasets are not installed: {missing}")
    service = RLLabService()
    experiments: dict[str, Any] = {}
    for dataset_id in DATASET_IDS:
        definition = definitions[dataset_id]
        runs = [
            _run_one(
                service,
                dataset_id,
                episodes=episodes,
                horizon_steps=horizon_steps,
                seed=seed,
            )
            for seed in seeds
        ]
        dataset_public = definition.public_dict()
        experiments[dataset_id] = {
            "dataset": dataset_public,
            "runs": runs,
            "aggregate": _aggregate(runs),
        }

    selected_runs, evidence_hashes = _export_evidence(experiments)
    original_rows = experiments["uci_appliances_energy"]["dataset"]["row_count"]
    large_rows = experiments["uci_household_power_5min"]["dataset"]["row_count"]
    report = {
        "schema_version": "xiaoyi-rl-dataset-benchmark.v1",
        "generated_at": _now(),
        "passed": True,
        "pass_definition": (
            "All scheduled runs completed, temporal and rendering boundaries held, and evidence "
            "hashes were generated. PASS does not mean RL beat PID or production targets were met."
        ),
        "configuration": {
            "algorithms": list(ALL_ALGORITHM_IDS),
            "episodes": episodes,
            "horizon_steps": horizon_steps,
            "seeds": list(seeds),
            "seed_count": len(seeds),
            "split": "chronological_no_shuffle_70_15_15",
            "training_render_mode": None,
            "test_render_mode": "trace_after_training",
        },
        "dataset_comparison": {
            "original_rows": original_rows,
            "large_rows": large_rows,
            "large_to_original_row_ratio": round(large_rows / original_rows, 6),
            "recommendation": (
                "Use the large UCI dataset for algorithm-scale evidence and retain the original "
                "dataset for regression comparison. Use NOAA AIS for port-traffic relevance. "
                "None of them replaces site validation."
            ),
        },
        "experiments": experiments,
        "selected_evidence_runs": selected_runs,
        "evidence_sha256": evidence_hashes,
        "scope_notice": (
            "Public offline benchmark and calibrated planning sandbox only. "
            "No field productivity, live-control, safety-certification or production-SLA claim is made."
        ),
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    REPORT_MARKDOWN.write_text(_markdown(report), encoding="utf-8")
    return report


def verify() -> list[str]:
    errors: list[str] = []
    try:
        report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"benchmark report is unreadable: {exc}"]
    if report.get("schema_version") != "xiaoyi-rl-dataset-benchmark.v1":
        errors.append("unexpected benchmark schema")
    if len(report.get("configuration", {}).get("algorithms", [])) != 5:
        errors.append("benchmark does not contain five algorithms")
    if report.get("configuration", {}).get("seed_count", 0) < 3:
        errors.append("benchmark requires at least three seeds")
    for relative, expected in report.get("evidence_sha256", {}).items():
        path = BASE_DIR / relative
        if not path.is_file():
            errors.append(f"missing evidence file: {relative}")
        elif _sha256(path) != expected:
            errors.append(f"evidence hash changed: {relative}")
    for experiment in report.get("experiments", {}).values():
        for run in experiment.get("runs", []):
            if run.get("training_rendering_performed") is not False:
                errors.append(f"training rendered in {run.get('run_id')}")
            if run.get("test_rendering_performed") is not True:
                errors.append(f"test trace missing in {run.get('run_id')}")
            if run.get("split", {}).get("strategy") != "chronological_no_shuffle":
                errors.append(f"split boundary changed in {run.get('run_id')}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Run and verify the fixed Xiaoyi RL dataset benchmark")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--episodes", type=int, default=320)
    run_parser.add_argument("--horizon-steps", type=int, default=72)
    run_parser.add_argument("--seeds", nargs="+", type=int, default=list(DEFAULT_SEEDS))
    subparsers.add_parser("verify")
    args = parser.parse_args()
    if args.command == "run":
        report = run_benchmark(args.episodes, args.horizon_steps, tuple(args.seeds))
        print(json.dumps({"passed": report["passed"], "report": _relative(REPORT_JSON)}, ensure_ascii=False))
        return 0
    errors = verify()
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print("rl-dataset-benchmark: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
