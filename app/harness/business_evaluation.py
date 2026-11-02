"""Independent business outcome checks kept separate from language-model intelligence."""

from __future__ import annotations

import copy
from datetime import timedelta

from app.harness import policy_assurance, portcall, public_port
from app.harness.contracts import digest, now


def run():
    rows = []

    def record(case_id, fn):
        try:
            checks = fn()
            rows.append({"id": case_id, "checks": checks, "passed": all(checks.values())})
        except Exception as exc:
            rows.append({"id": case_id, "passed": False, "error": type(exc).__name__ + ": " + str(exc)[:300]})

    catalog = public_port.catalog()
    record(
        "public-source-integrity",
        lambda: {
            "six_frozen_datasets": len(catalog["entries"]) == 6,
            "all_raw_and_derived_hashes": all(e["integrity_valid"] for e in catalog["entries"]),
        },
    )
    record(
        "water-level-causal-holdout",
        lambda: {
            "holdout_has_at_least_30_points": public_port.forecast_validation()["holdout"]["n"] >= 30,
            "site_release_disabled": public_port.forecast_validation()["operational_release"] is False,
        },
    )
    reports = []
    for site in ["los_angeles", "singapore"]:
        for scenario in ["historical_baseline", "peak_month_demand", "resource_outage"]:

            def evaluate(s=site, c=scenario):
                report = public_port.replay(public_port.ReplayArgs(site=s, scenario=c))
                reports.append(report)
                request = portcall.PlanRequest(**report["scenario_input"])
                releases, blockers, _ = portcall.arrivals(request)
                selected = report["plan"]["selected"]
                return {
                    "complete_feasible_plan": bool(selected)
                    and portcall.verify_schedule(request, selected["schedule"], releases)["feasible"],
                    "no_input_blockers": not blockers,
                    "all_calls_accounted": bool(selected) and len(selected["schedule"]) == len(request.calls),
                    "three_same_input_comparators": len(report["plan"]["candidates"]) == 3,
                    "explicit_synthetic_lineage": any(
                        r["class"] == "declared_engineering_assumption" for r in report["field_lineage"]
                    ),
                    "no_physical_release": report["plan"]["operational_release"] is False,
                }

            record(f"{site}.{scenario}", evaluate)
    if reports:
        base = reports[0]["scenario_input"]

        def intervention(change, check):
            modified = copy.deepcopy(base)
            change(modified)
            return check(portcall.plan(portcall.PlanRequest(**modified)))

        record(
            "future-information-excluded",
            lambda: intervention(
                lambda d: d["events"].append(
                    {
                        **d["events"][0],
                        "revision": 2,
                        "event_time": (portcall.PlanRequest(**base).as_of + timedelta(hours=6)).isoformat(),
                        "received_at": (portcall.PlanRequest(**base).as_of + timedelta(minutes=1)).isoformat(),
                    }
                ),
                lambda p: {
                    "same_selected_plan": p["selected"] == reports[0]["plan"]["selected"],
                    "update_disclosed": p["future_updates_excluded"] == 1,
                },
            ),
        )
        record(
            "total-channel-loss-fails-closed",
            lambda: intervention(
                lambda d: d.update(
                    closures=[
                        {
                            "resource": "channel",
                            "start_minutes": 0,
                            "end_minutes": d["horizon_minutes"],
                            "unavailable": 1,
                        }
                    ]
                ),
                lambda p: {
                    "withheld": p["recommendation_status"] == "withheld",
                    "no_selected_partial_plan": p["selected"] is None,
                },
            ),
        )
        record(
            "unsafe-frozen-plan-not-moved",
            lambda: intervention(
                lambda d: d["calls"][0].update(frozen_start_minutes=0),
                lambda p: {"no_silent_reschedule": p["selected"] is None},
            ),
        )
    for values, case_id in [
        ([1], "one-seed-is-inconclusive"),
        ([-1, 10, 10, 10, 10], "positive-mean-can-hide-worst-seed"),
    ]:

        def check_stats(v=values):
            stats = policy_assurance.paired_statistics(v)
            return {
                "insufficient_or_worst_seed_blocker": stats["n"] < 5 or stats["worst_seed_delta"] < 0,
                "no_invented_confidence_interval": stats["paired_t_ci95"] is None if len(v) == 1 else True,
            }

        record(case_id, check_stats)
    return {
        "schema": "xiaoyi-business-assurance-evaluation.v1",
        "at": now(),
        "rows": rows,
        "case_count": len(rows),
        "passed": all(r["passed"] for r in rows),
        "public_manifest_sha256": catalog["manifest_sha256"],
        "protocol_sha256": digest(policy_assurance.PROTOCOL),
        "scope": "公开历史数据与确定性业务门禁回归；不是模型自主规划准确率、独立盲测、现场安全认证或生产SLA。",
    }
