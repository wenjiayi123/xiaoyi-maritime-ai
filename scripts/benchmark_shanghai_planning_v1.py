"""Actual four-service study of the coupled reference and preserved heuristics."""

from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean
import sys
from uuid import uuid4
from urllib.request import Request, urlopen
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from accept_shanghai_lab_v1 import request
from integrations.shanghai_lab_v1.protocol import packed


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    cases = [(f"2025-{m:02}-15", "normal") for m in range(1, 13)]
    cases += [
        (d, s)
        for d in ["2025-01-15", "2025-04-15", "2025-07-15", "2025-10-15"]
        for s in ["arrival_surge", "berth_outage", "grid_derating", "weather_closure"]
    ]
    cases.append(("2025-07-30", "weather_closure"))
    protocol = {
        "schema": "shanghai-planning-protocol.v1",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
        "acceptance": [
            "complete task coverage",
            "native and independent resource checks",
            "same input for heuristics and MILP",
            "no worse declared objective",
            "no worse total waiting or overdue service",
            "energy accounting and isolated restoration",
            "failure retained",
        ],
        "external_event_context": {
            "url": "https://sh.weather.com.cn/gdtp/07/4278214.shtml",
            "observed": "Co-May made landfall near Fengxian on 2025-07-30; official public report",
            "not_observed": "The lab 06:00-10:00 channel closure is an engineering sensitivity, not the actual Shanghai port closure timetable; no measured recovery KPI available",
        },
    }
    (out / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2))
    with urlopen(
        Request(protocol["external_event_context"]["url"], headers={"User-Agent": "Mozilla/5.0"}), timeout=30
    ) as response:
        raw = response.read()
    (out / "official-event.html").write_bytes(raw)
    if "16时40分" not in raw.decode("utf-8"):
        raise ValueError("official event source changed")
    (out / "source.json").write_text(
        json.dumps(
            {
                "url": protocol["external_event_context"]["url"],
                "sha256": hashlib.sha256(raw).hexdigest(),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    results = []
    for i, (day, scenario) in enumerate(cases):
        status, r = request(
            "http://127.0.0.1:18018/api/harness/shanghai/trials",
            {"request_id": "plan-v1-" + uuid4().hex, "day": day, "scenario": scenario, "seed": 17},
        )
        (out / f"case-{i:02}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2))
        ok = status == 200 and r.get("status") == "completed_simulation_pending_mobile"
        entry = {"day": day, "scenario": scenario, "passed": ok, "error": r.get("error")}
        if ok:
            comparison = r["plan"]["comparison"]
            ok = (
                comparison["improvement_cny"] >= -1e-6
                and r["native_selected_plan_review"]["reviewed"]
                and r["execution"]["restore_verified"]
            )
            packet = packed(r["snapshot"], "snapshot") | packed(r["native_heuristic_plan"], "plan")
            code, base = request("http://127.0.0.1:18808/api/shanghai-lab/v1/evaluate", packet)
            (out / f"baseline-energy-{i:02}.json").write_text(json.dumps(base, ensure_ascii=False, indent=2))
            ok = ok and code == 200
            if code == 200:
                entry.update(
                    resource_objective_improvement_cny=comparison["improvement_cny"],
                    actual_cost_change_cny=r["energy"]["totals"]["total_cny"] - base["totals"]["total_cny"],
                    waiting_change_hours=r["energy"]["operations"]["wait_vessel_hours"]
                    - base["operations"]["wait_vessel_hours"],
                    solver_gap=comparison["strong_reference"]["solver"]["gap"],
                    elapsed_seconds=r["elapsed_seconds"],
                )
                ok = (
                    ok
                    and entry["waiting_change_hours"] <= 0
                    and r["energy"]["operations"]["late_vessel_hours"] <= base["operations"]["late_vessel_hours"]
                )
        entry["passed"] = ok
        results.append(entry)
        if i % 5 == 0 or not ok:
            print(json.dumps(entry, ensure_ascii=False), flush=True)
    summary = {
        "schema": "shanghai-planning-results.v1",
        "passed": all(r["passed"] for r in results),
        "cases": len(results),
        "results": results,
        "global_tradeoff": "Reported actual cost and waiting changes may have different signs. The proxy MILP objective is not the full coupled storage optimum.",
        "real_disruption_calibration": "Official event/date plus actual public reanalysis; service delays and channel restrictions remain engineered, not field-validated.",
        "legacy_rl_unchanged": True,
        "production_authority": False,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
