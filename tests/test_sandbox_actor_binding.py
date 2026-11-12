"""A caller may only sign as their authenticated identity in the port sandbox."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import realtime_port_simulator as sim
from app.access_control import IdentityContext


def test_verified_actor_cannot_supply_a_second_signer(monkeypatch):
    alice = IdentityContext("alice", "operator", True, "jwt")
    monkeypatch.setattr(sim, "request_identity", lambda request: alice)
    payload = sim.ApprovalRequest(approver_id="bob", approver_role="duty_manager", reason="模拟审批回归")
    with pytest.raises(HTTPException) as refused:
        sim.approve_decision("energy-peak-shave", payload, SimpleNamespace())
    assert refused.value.status_code == 403


@pytest.mark.parametrize(("authenticated", "supplied", "basis"), [
    (True, "alice", "authenticated_actor"), (False, "demo-manager", "simulated_persona")
])
def test_signer_provenance(monkeypatch, authenticated, supplied, basis):
    actor = IdentityContext("alice", "operator", authenticated, "jwt" if authenticated else "local_unverified_header")
    monkeypatch.setattr(sim, "request_identity", lambda request: actor)
    plant = sim.PortRealtimeSimulator(seed=20260813)
    plant.set_scenario("energy_peak", "模拟来源签注检查")
    monkeypatch.setattr(sim, "realtime_port_simulator", plant)
    monkeypatch.setattr(sim, "_audit", lambda *args: None)
    payload = sim.ApprovalRequest(approver_id=supplied, approver_role="dispatcher", reason="复核本次模拟动作")
    sim.approve_decision("energy-peak-shave", payload, SimpleNamespace())
    record = plant._approvals["energy-peak-shave"][0]
    assert record["identity_basis"] == basis and record["approver_id"] == supplied and record["simulation_only"]
