"""Read back immutable results; correct metadata without changing any science."""

import hashlib
import json
from pathlib import Path

from app.config import BASE_DIR
from app.harness import operations_v5 as ops
from app.harness.contracts import digest


def main():
    folder = ops.FOLDER
    output = folder / "report-qualified.json"
    if output.exists():
        raise ValueError("Never overwrite a qualified readback")
    source = folder / "report-final.json"
    report = json.loads(source.read_text())
    assert hashlib.sha256(Path(ops.__file__).read_bytes()).hexdigest() == report["source_sha256"]
    maximum = 0.0
    for row in report["cases"]:
        original = ops.problem(ops.OptimizeArgs.model_validate(row["problem"]["input"]))
        assert digest(original) == row["input_sha256"]
        for selected in [row["selected"], *row["baselines"]]:
            recomputed = ops.schedule_check(original, selected["schedule"])
            assert recomputed["passed"]
            for metric in [
                "objective_points",
                "grid_energy_kwh",
                "total_waiting_hours",
                "late_call_hours",
                "peak_grid_kw",
            ]:
                maximum = max(maximum, abs(selected[metric] - recomputed[metric]))
        assert row["selected"]["objective_points"] + 1e-5 >= row["solver"]["dual_bound_points"]
    assert maximum < 1e-7
    report["metadata_correction"] = {
        "original": str(source.relative_to(BASE_DIR)),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "scope": "Only clarify the final June temporal holdout wording; numeric cases, parameters, scores and solver output unchanged.",
        "unchanged_cases_content_sha256": digest(report["cases"]),
    }
    report["notice"] = (
        "32预注册未来日期2026-06-15的合成工单情景；八个港口已在5月首次新港评估中查看。本批是新时期复验，不重复声称整港未见。共享真实公开活动来源和全部假设，对比四个可行启发式中的最好值；保留零改善。代理目标改善不代表RL超过MPC、实测节能、现场物理标定或生产资格。"
    )
    report["execution_readback"] = {
        "passed": True,
        "cases": len(report["cases"]),
        "compared_schedules": len(report["cases"]) * 5,
        "maximum_numeric_error": maximum,
        "method": "Reload raw source rows and recreate frozen problem; use separately implemented schedule checker from solver matrix. Tiny-case optimum independently exhaustively unit-tested. Not external peer review.",
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["execution_readback"], ensure_ascii=False))


if __name__ == "__main__":
    main()
