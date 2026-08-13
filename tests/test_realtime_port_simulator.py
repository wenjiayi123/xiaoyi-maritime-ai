from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.realtime_port_simulator import ApprovalRequest, PortRealtimeSimulator


client = TestClient(app)


def test_contract_covers_replaceable_port_data_plane() -> None:
    response = client.get("/api/port-simulator/contract")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_id"] == "xiaoyi-port-realtime-telemetry.v1"
    assert payload["domain_count"] == 10
    assert payload["canonical_field_count"] >= 140
    assert payload["production_authority"] is False
    assert {item["id"] for item in payload["domains"]} >= {
        "port_call", "ais_vts", "equipment", "yard_inventory", "gate_intermodal",
        "energy_carbon", "weather_tide", "safety_maintenance", "governance",
    }


def test_snapshot_has_full_entities_lineage_and_physical_quality_gates() -> None:
    simulator = PortRealtimeSimulator(seed=20260813)
    snapshot = simulator.snapshot()

    assert snapshot["metadata"]["source_type"] == "public_data_calibrated_simulation"
    assert snapshot["metadata"]["live_data_verified"] is False
    assert snapshot["governance"] == {
        "decision_mode": "recommendation_only",
        "sandbox_dispatch_allowed": True,
        "physical_dispatch_allowed": False,
        "production_authority": False,
        "site_replacement": "replace adapter only; keep port-realtime.v1 and port-ops.v1 contracts",
    }
    assert len(snapshot["port_calls"]) == 5
    assert len(snapshot["ais_tracks"]) == 12
    assert len(snapshot["berths"]) == 6
    assert len(snapshot["equipment"]) == 18 + 96 + 54
    assert len(snapshot["yard_blocks"]) == 12
    assert len(snapshot["gates"]) == 2
    assert snapshot["quality"]["gate_passed"] is True
    assert snapshot["quality"]["physical_constraint_violations"] == 0
    assert snapshot["energy"]["power_balance_error_kw"] == 0.0
    assert 20 <= snapshot["energy"]["bess_soc_percent"] <= 90
    assert all(item["occupied_teu"] <= item["capacity_teu"] for item in snapshot["yard_blocks"])
    assert all(item["lanes_open"] <= item["lanes_total"] for item in snapshot["gates"])
    assert len(snapshot["lineage"]["public_ais_sha256"]) == 64
    assert len(snapshot["lineage"]["public_energy_sha256"]) == 64


def test_scenarios_change_causal_operating_state_not_only_labels() -> None:
    simulator = PortRealtimeSimulator(seed=20260813)
    normal = simulator.snapshot()
    simulator.set_scenario("storm", "验证气象停机和人工接管闭环")
    storm = simulator.snapshot()

    assert storm["weather_tide"]["wind_speed_ms"] >= 18
    assert storm["fleet_summary"]["quay_cranes"]["working"] < normal["fleet_summary"]["quay_cranes"]["working"]
    assert any(item["event_id"] == "SIM-METOC-WIND" for item in storm["alerts"])
    assert any(item["status"] == "weather_hold" for item in storm["equipment"] if item["asset_type"] == "quay_crane")


def test_two_distinct_approvals_execute_and_rollback_sandbox_only() -> None:
    simulator = PortRealtimeSimulator(seed=20260813)
    simulator.set_scenario("energy_peak", "验证储能削峰、审批和回滚链路")
    before = simulator.snapshot()
    decision_id = "energy-peak-shave"

    simulator.approve(
        decision_id,
        ApprovalRequest(
            approver_id="dispatcher-a",
            approver_role="dispatcher",
            reason="确认当前模拟输入与建议范围",
        ),
    )
    with pytest.raises(PermissionError):
        simulator.execute(decision_id, "审批不足时必须失败关闭")
    with pytest.raises(ValueError):
        simulator.approve(
            decision_id,
            ApprovalRequest(
                approver_id="dispatcher-a",
                approver_role="dispatcher",
                reason="重复审批应被拒绝记录",
            ),
        )
    simulator.approve(
        decision_id,
        ApprovalRequest(
            approver_id="duty-manager-b",
            approver_role="duty_manager",
            reason="复核SOC、功率和回滚约束",
        ),
    )
    executed = simulator.execute(decision_id, "仅执行到本地模拟状态")
    after = simulator.snapshot()

    assert executed["sandbox_state_updated"] is True
    assert executed["physical_dispatch_performed"] is False
    assert executed["production_authority"] is False
    assert after["energy"]["grid_demand_kw"] < before["energy"]["grid_demand_kw"]
    assert next(item for item in after["decisions"] if item["decision_id"] == decision_id)["status"] == "executed_in_sandbox"

    rolled_back = simulator.rollback(decision_id, "验证可恢复到执行前规则")
    restored = simulator.snapshot()
    assert rolled_back["physical_dispatch_performed"] is False
    assert restored["energy"]["grid_demand_kw"] > after["energy"]["grid_demand_kw"]


def test_api_requires_two_approvals_before_sandbox_execution() -> None:
    scenario = client.post(
        "/api/port-simulator/scenario",
        headers={"X-Idempotency-Key": "port-sim-api-scenario-001"},
        json={"scenario_id": "energy_peak", "reason": "API闭环回归测试"},
    )
    assert scenario.status_code == 200
    blocked = client.post(
        "/api/port-simulator/decisions/energy-peak-shave/execute",
        headers={"X-Idempotency-Key": "port-sim-api-execute-block-001"},
        json={"reason": "缺少审批时验证失败关闭"},
    )
    assert blocked.status_code == 409
    assert "两名不同审批人" in blocked.json()["detail"]

    # Reset shared API state so unrelated tests keep the documented default.
    reset = client.post(
        "/api/port-simulator/scenario",
        headers={"X-Idempotency-Key": "port-sim-api-reset-001"},
        json={"scenario_id": "normal", "reason": "回归结束恢复默认常态"},
    )
    assert reset.status_code == 200
