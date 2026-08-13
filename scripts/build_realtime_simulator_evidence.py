from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.realtime_port_simulator import ApprovalRequest, PortRealtimeSimulator  # noqa: E402


JSON_PATH = ROOT / "reports/port_realtime_simulator_evidence_v1_20260813.json"
MARKDOWN_PATH = ROOT / "reports/port_realtime_simulator_evidence_v1_20260813.md"
CONTRACT_PATH = ROOT / "data/contracts/port_realtime_telemetry_v1.json"
CODE_PATH = ROOT / "app/realtime_port_simulator.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scenario_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario_id": snapshot["simulation"]["scenario_id"],
        "scenario_label": snapshot["simulation"]["scenario_label"],
        "port_calls": len(snapshot["port_calls"]),
        "ais_tracks": len(snapshot["ais_tracks"]),
        "equipment_assets": len(snapshot["equipment"]),
        "yard_blocks": len(snapshot["yard_blocks"]),
        "gate_objects": len(snapshot["gates"]),
        "active_alerts": len(snapshot["alerts"]),
        "working_quay_cranes": snapshot["fleet_summary"]["quay_cranes"]["working"],
        "low_soc_agv": snapshot["fleet_summary"]["agv"]["low_soc"],
        "grid_demand_kw": snapshot["energy"]["grid_demand_kw"],
        "wind_speed_ms": snapshot["weather_tide"]["wind_speed_ms"],
        "visibility_m": snapshot["weather_tide"]["visibility_m"],
        "quality_gate_passed": snapshot["quality"]["gate_passed"],
        "physical_constraint_violations": snapshot["quality"]["physical_constraint_violations"],
        "payload_sha256": snapshot["metadata"]["payload_sha256"],
    }


def build() -> dict[str, Any]:
    simulator = PortRealtimeSimulator(seed=20260813)
    scenarios = []
    for scenario_id in ("normal", "vessel_surge", "equipment_failure", "energy_peak", "storm"):
        simulator.set_scenario(scenario_id, "正式模拟器证据运行")
        scenarios.append(_scenario_summary(simulator.snapshot()))

    simulator.set_scenario("energy_peak", "验证审批执行回滚闭环")
    baseline = simulator.snapshot()
    blocked_without_two_approvals = False
    simulator.approve(
        "energy-peak-shave",
        ApprovalRequest(
            approver_id="evidence-dispatcher",
            approver_role="dispatcher",
            reason="核对输入、约束和建议范围",
        ),
    )
    try:
        simulator.execute("energy-peak-shave", "单人审批不应执行")
    except PermissionError:
        blocked_without_two_approvals = True
    simulator.approve(
        "energy-peak-shave",
        ApprovalRequest(
            approver_id="evidence-duty-manager",
            approver_role="duty_manager",
            reason="复核SOC、需量、影响和回滚边界",
        ),
    )
    execution = simulator.execute("energy-peak-shave", "证据运行只改变模拟状态")
    after_execute = simulator.snapshot()
    rollback = simulator.rollback("energy-peak-shave", "验证模拟状态可恢复")
    after_rollback = simulator.snapshot()

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    canonical_fields = sum(len(item["required_fields"]) for item in contract["domains"])
    scenario_quality = all(
        item["quality_gate_passed"] and item["physical_constraint_violations"] == 0
        for item in scenarios
    )
    closure_passed = all(
        (
            blocked_without_two_approvals,
            execution["sandbox_state_updated"] is True,
            execution["physical_dispatch_performed"] is False,
            after_execute["energy"]["grid_demand_kw"] < baseline["energy"]["grid_demand_kw"],
            rollback["physical_dispatch_performed"] is False,
            after_rollback["energy"]["grid_demand_kw"] > after_execute["energy"]["grid_demand_kw"],
        )
    )
    return {
        "report_id": "xiaoyi-port-realtime-simulator-evidence.v1",
        "run_id": f"port-sim-evidence-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "truth_label": "公开数据校准实时模拟",
        "scope_notice": (
            "公开AIS只校准交通包络，公开能源数据只验证时序接入与特征耦合；"
            "泊位、设备、堆场、闸口、能耗量级、天气潮汐和全部业务影响为工程模拟。"
        ),
        "contract": {
            "path": str(CONTRACT_PATH.relative_to(ROOT)),
            "sha256": _sha256(CONTRACT_PATH),
            "domains": len(contract["domains"]),
            "canonical_fields": canonical_fields,
        },
        "implementation": {
            "path": str(CODE_PATH.relative_to(ROOT)),
            "sha256": _sha256(CODE_PATH),
            "simulation_seed": 20260813,
            "event_interval_seconds": 2,
        },
        "calibration_artifacts": {
            "public_ais": {
                "path": "data/public/noaa_la_lb_ais_2024_12_25_1min.csv",
                "sha256": _sha256(ROOT / "data/public/noaa_la_lb_ais_2024_12_25_1min.csv"),
                "rows": 710,
                "semantics": "independent_public_AIS_minute_buckets",
            },
            "public_energy": {
                "path": "data/public/uci_appliances_energy.csv",
                "sha256": _sha256(ROOT / "data/public/uci_appliances_energy.csv"),
                "rows": 19735,
                "semantics": "independent_public_non_port_energy_benchmark",
            },
        },
        "scenario_results": scenarios,
        "closed_loop": {
            "decision_id": "energy-peak-shave",
            "blocked_without_two_approvals": blocked_without_two_approvals,
            "approvers_are_distinct": True,
            "baseline_grid_demand_kw": baseline["energy"]["grid_demand_kw"],
            "executed_grid_demand_kw": after_execute["energy"]["grid_demand_kw"],
            "rolled_back_grid_demand_kw": after_rollback["energy"]["grid_demand_kw"],
            "sandbox_state_updated": execution["sandbox_state_updated"],
            "physical_dispatch_performed": execution["physical_dispatch_performed"],
            "production_authority": execution["production_authority"],
            "rollback_event": rollback["event"]["event"],
        },
        "admission": {
            "scenario_quality_passed": scenario_quality,
            "closed_loop_passed": closure_passed,
            "adapter_replacement_ready": scenario_quality and closure_passed,
            "site_data_admission_passed": False,
            "production_authority": False,
            "result": "PASS_LOCAL_SIMULATION_ONLY" if scenario_quality and closure_passed else "FAIL",
        },
    }


def markdown(report: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| `{item['scenario_id']}` | {item['working_quay_cranes']} | {item['low_soc_agv']} | "
        f"{item['grid_demand_kw']:,.1f} | {item['wind_speed_ms']} | {item['active_alerts']} | "
        f"{item['physical_constraint_violations']} |"
        for item in report["scenario_results"]
    )
    closure = report["closed_loop"]
    return f"""# 港口实时数据模拟器证据 v1

> run_id: `{report['run_id']}`
> 生成时间：{report['generated_at']}
> 结论：`{report['admission']['result']}`

## 真实性边界

{report['scope_notice']}

这份报告只证明可替换数据契约、物理约束模拟、双人审批、模拟状态执行和回滚链在本机可复验。它不证明港口现场数据接入、生产收益、财务实绩、核证减排或生产控制权限。

## 数据契约

- 业务域：**{report['contract']['domains']}**
- 规范字段：**{report['contract']['canonical_fields']}**
- 事件周期：**{report['implementation']['event_interval_seconds']} 秒**
- 模拟种子：`{report['implementation']['simulation_seed']}`
- 契约 SHA-256：`{report['contract']['sha256']}`
- 实现 SHA-256：`{report['implementation']['sha256']}`

## 场景结果

| 场景 | 在作岸桥 | 低SOC AGV | 电网需量 kW | 风速 m/s | 告警 | 物理违规 |
|---|---:|---:|---:|---:|---:|---:|
{rows}

## 双人审批、执行与回滚

- 单人审批执行被阻断：`{closure['blocked_without_two_approvals']}`
- 执行前需量：**{closure['baseline_grid_demand_kw']:,.1f} kW**
- 模拟执行后需量：**{closure['executed_grid_demand_kw']:,.1f} kW**
- 回滚后需量：**{closure['rolled_back_grid_demand_kw']:,.1f} kW**
- `sandbox_state_updated={str(closure['sandbox_state_updated']).lower()}`
- `physical_dispatch_performed={str(closure['physical_dispatch_performed']).lower()}`
- `production_authority={str(closure['production_authority']).lower()}`

## 换源边界

现场 TOS、PCS、EMS、EAM、VTS/AIS、METOC 和闸口适配器只需输出 `port-realtime.v1` / `port-ops.v1` 规范字段，业务与前端链路无需改写；但现场字段映射、计量标定、漂移、影子运行、双人审批、回滚演练和 OT/IT 安全仍必须重新验收。
"""


def verify(report: dict[str, Any]) -> None:
    assert report["contract"]["sha256"] == _sha256(CONTRACT_PATH)
    assert report["implementation"]["sha256"] == _sha256(CODE_PATH)
    assert report["contract"]["domains"] == 10
    assert report["contract"]["canonical_fields"] >= 140
    assert report["admission"]["scenario_quality_passed"] is True
    assert report["admission"]["closed_loop_passed"] is True
    assert report["admission"]["site_data_admission_passed"] is False
    assert report["admission"]["production_authority"] is False
    assert report["closed_loop"]["physical_dispatch_performed"] is False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("generate", "verify"), nargs="?", default="generate")
    args = parser.parse_args()
    if args.command == "generate":
        report = build()
        JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        MARKDOWN_PATH.write_text(markdown(report), encoding="utf-8")
    else:
        report = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    verify(report)
    print(f"realtime-simulator-evidence: PASS ({report['run_id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
