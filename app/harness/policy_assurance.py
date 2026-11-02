"""Predeclared, paired policy gates. Statistical units are training seeds, not frames."""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import replace

from app.harness.contracts import digest

PROTOCOL = {
    "version": "xiaoyi-policy-assurance.v1",
    "minimum_seeds": 5,
    "confidence": 0.95,
    "bootstrap_resamples": 2000,
    "bootstrap_seed": 301030,
    "selection": "mean_validation_score_only",
    "comparator": "best_baseline_on_validation_only",
    "gate": "selected_on_validation; paired_t_lower>0; worst_seed_delta>=0; no_observed_violation; stress_noninferiority",
    "stress_max_mean_regression": 0.0,
    "production_authority": False,
}


def _quantile(values, q):
    values = sorted(values)
    position = (len(values) - 1) * q
    a, b = math.floor(position), math.ceil(position)
    return values[a] + (values[b] - values[a]) * (position - a)


def paired_statistics(deltas):
    if not deltas or any(type(x) not in {float, int} or not math.isfinite(x) for x in deltas):
        raise ValueError("paired statistics require finite observations")
    n = len(deltas)
    mean = statistics.mean(deltas)
    # Two-sided 95% Student t critical values. Only up to 5 seeds are currently registered.
    critical = {2: 12.706205, 3: 4.302653, 4: 3.182447, 5: 2.776446}
    t_ci = None
    if n >= 2:
        if n not in critical:
            raise ValueError("unregistered seed count for t interval")
        radius = critical[n] * statistics.stdev(deltas) / math.sqrt(n)
        t_ci = [mean - radius, mean + radius]
    rng = random.Random(PROTOCOL["bootstrap_seed"])
    draws = [statistics.mean(rng.choices(deltas, k=n)) for _ in range(PROTOCOL["bootstrap_resamples"])]
    tail = sorted(deltas)[: max(1, math.ceil(n * 0.2))]
    return {
        "n": n,
        "paired_mean_delta": mean,
        "paired_t_ci95": t_ci,
        "paired_bootstrap_ci95": [_quantile(draws, 0.025), _quantile(draws, 0.975)],
        "worst_seed_delta": min(deltas),
        "lower_tail_mean_20pct": statistics.mean(tail),
        "win_fraction": sum(x > 0 for x in deltas) / n,
        "unit": "training_seed_conditional_on_fixed_test_windows",
        "limitation": "少样本t区间依赖种子差值分布假设；bootstrap仅为诊断。重复测试窗口不是独立现场样本。",
    }


def assess(rows, algorithms, stress_rows):
    names = ["sop_rule", "pid", *algorithms]
    by_name = {name: {r["seed"]: r for r in rows if r["algorithm"] == name} for name in names}
    seeds = sorted(by_name["sop_rule"])
    if not seeds or any(sorted(by_name[name]) != seeds for name in names):
        raise ValueError("policies require identical paired seeds")
    if any(len([r for r in rows if r["algorithm"] == name]) != len(seeds) for name in names):
        raise ValueError("duplicate seed result")

    def validation_mean(name):
        return statistics.mean(r["validation_metrics"]["score"] for r in by_name[name].values())

    selected = max(names, key=validation_mean)
    comparator = max(["sop_rule", "pid"], key=validation_mean)
    decisions = []
    for name in names:
        runs = list(by_name[name].values())
        stats = paired_statistics(
            [by_name[name][s]["test_metrics"]["score"] - by_name[comparator][s]["test_metrics"]["score"] for s in seeds]
        )
        observed = [v for r in runs for v in r.get("test_episodes", [])]
        no_violations = len(observed) == len(seeds) * 3 and all(
            type(e.get("constraint_violations")) in {int, float} and e["constraint_violations"] == 0 for e in observed
        )
        failed_seeds = sum(
            any(e.get("constraint_violations", 1) != 0 for e in r.get("test_episodes", [])) for r in runs
        )
        stress_checks = []
        for scenario in stress_scenarios_for_rows(stress_rows):
            pairs = {(r["algorithm"], r["seed"]): r for r in stress_rows if r["scenario"] == scenario}
            complete = all((a, s) in pairs for a in {name, comparator} for s in seeds)
            samples = [pairs[(name, s)] for s in seeds] if complete else []
            delta = (
                statistics.mean(
                    pairs[(name, s)]["metrics"]["score"] - pairs[(comparator, s)]["metrics"]["score"] for s in seeds
                )
                if complete
                else None
            )
            safe = complete and all(
                len(r.get("episodes", [])) == 3 and all(e.get("constraint_violations") == 0 for e in r["episodes"])
                for r in samples
            )
            stress_checks.append(
                {
                    "scenario": scenario,
                    "paired_mean_delta": delta,
                    "complete": complete,
                    "no_observed_violations": safe,
                    "passed": safe and delta >= -PROTOCOL["stress_max_mean_regression"],
                }
            )
        checks = {
            "rl_candidate": name in algorithms,
            "selected_on_validation": name == selected,
            "minimum_seeds": len(seeds) >= PROTOCOL["minimum_seeds"],
            "paired_improvement": stats["paired_t_ci95"] is not None and stats["paired_t_ci95"][0] > 0,
            "no_worst_seed_regression": stats["worst_seed_delta"] >= 0,
            "no_observed_violations": no_violations,
            "stress_complete_and_noninferior": len(stress_checks) == 3 and all(s["passed"] for s in stress_checks),
        }
        decisions.append(
            {
                "algorithm": name,
                "statistics": stats,
                "checks": checks,
                "blockers": [k for k, v in checks.items() if not v],
                "stress": stress_checks,
                "research_admission": all(checks.values()),
                "enterprise_admission": False,
                "observed_failed_seeds": failed_seeds,
                "zero_failure_seed_rate_upper95": 1 - 0.05 ** (1 / len(seeds))
                if failed_seeds == 0 and no_violations
                else None,
                "safety_bound_scope": "仅条件于固定测试窗口的随机训练种子失败率；不是碰撞率、现场事故率或认证风险上界。",
            }
        )
    return {
        "protocol": PROTOCOL,
        "protocol_sha256": digest(PROTOCOL),
        "selected_algorithm": selected,
        "comparator_algorithm": comparator,
        "decisions": decisions,
        "production_authority": False,
    }


def stress_scenarios_for_rows(rows):
    return sorted({r["scenario"] for r in rows})


def stress_cases(environment_type, records, parameters):
    """Synthetic interventions on sealed test data; never calibrate on the holdout."""
    if environment_type == "port_operations":
        return [
            (
                "demand_surge",
                [
                    replace(
                        r,
                        vessel_count=r.vessel_count * 1.5,
                        anchored_vessels=r.anchored_vessels * 1.5,
                        moves_demand=r.moves_demand * 1.5 if r.moves_demand is not None else None,
                    )
                    for r in records
                ],
                parameters,
                {"vessel_count_factor": 1.5, "anchored_vessels_factor": 1.5, "moves_demand_factor_if_present": 1.5},
            ),
            (
                "equipment_outage",
                [replace(r, equipment_availability_ratio=0.35) for r in records],
                parameters,
                {"equipment_availability_ratio": 0.35},
            ),
            (
                "severe_weather",
                [replace(r, wind_speed_mps=25.0, visibility_km=0.5, tide_window_open=0.0) for r in records],
                parameters,
                {"wind_speed_mps": 25.0, "visibility_km": 0.5, "tide_window_open": 0.0},
            ),
        ]
    return [
        ("load_surge", [replace(r, load_kw=r.load_kw * 1.5) for r in records], parameters, {"load_kw_factor": 1.5}),
        (
            "power_derating",
            records,
            replace(parameters, max_power_kw=parameters.max_power_kw * 0.5),
            {"max_power_kw_factor": 0.5},
        ),
        ("price_spike", [replace(r, price_per_kwh=1.0) for r in records], parameters, {"price_per_kwh": 1.0}),
    ]


def data_support(train, test, environment_type):
    fields = (
        ["vessel_count", "anchored_vessels", "avg_sog_knots", "wind_speed_mps", "equipment_availability_ratio"]
        if environment_type == "port_operations"
        else ["load_kw", "price_per_kwh", "carbon_kg_per_kwh"]
    )
    rows = []
    for field in fields:
        reference = [getattr(r, field) for r in train if getattr(r, field) is not None]
        observed = [getattr(r, field) for r in test if getattr(r, field) is not None]
        low, high = (min(reference), max(reference)) if reference else (None, None)
        outside = sum(v < low or v > high for v in observed) if reference else None
        rows.append(
            {
                "field": field,
                "training_range": [low, high],
                "test_count": len(observed),
                "missing_fraction": 1 - len(observed) / len(test),
                "outside_training_range_fraction": outside / len(observed)
                if outside is not None and observed
                else None,
            }
        )
    return {
        "method": "training_minmax_support_diagnostic.v1",
        "fields": rows,
        "scope": "缺测与训练支持域诊断；不是自动补传感器、校准证明或通用OOD检测。",
    }
