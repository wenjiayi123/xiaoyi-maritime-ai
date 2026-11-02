from datetime import datetime, timezone

import numpy as np
import pytest

from app.harness import operations_v2 as o, guided_rl_v2 as g


@pytest.mark.parametrize("outage", [False, True])
def test_scheduler_never_overallocates_and_reports_incomplete_calls(outage):
    result = o.schedule(100, outage)
    assert not result["resource_violations"]
    assert result["complete"] is False and result["incomplete_calls"]
    for row in result["allocations"]:
        if outage and row["stage"] == "cargo":
            assert row["end_tick"] <= 24 or row["start_tick"] >= 60


def test_energy_units_conservation_and_battery_outage_deficit_are_explicit():
    result = o.energy(o.schedule(20), battery_available=False)
    assert result["unserved_kwh"] > 0
    assert result["soc_bounds_passed"]
    assert result["max_power_balance_error_kw"] < 1e-8
    assert result["max_storage_balance_error_kwh"] < 1e-8
    assert result["carbon"]["emissions_kg"] is None


def test_unknown_depth_datum_and_authority_withhold_ukc():
    result = o.ukc_gate(1.0, None, None, None, False, False, False)
    assert result["status"] == "withheld" and result["ukc_m"] is None
    assert {"missing_depth", "unmatched_vertical_datum", "no_verified_site_authorization"} <= set(result["blockers"])


def message():
    clock = datetime(2026, 2, 2, tzinfo=timezone.utc)
    return clock, {
        "id": "fixture",
        "event_at": clock.isoformat(),
        "revision": 1,
        "scope": "engineering_replay",
        "production_authority": False,
    }


def test_ledger_rejects_same_actor_two_roles_and_changed_approved_payload(tmp_path):
    ledger = o.Ledger(tmp_path / "owned.sqlite")
    clock, body = message()
    ledger.receive(body, clock)
    ledger.approve("fixture", "dispatcher", "a")
    with pytest.raises(PermissionError):
        ledger.approve("fixture", "duty_manager", "a")
    ledger.approve("fixture", "duty_manager", "b")
    with ledger.db:
        ledger.db.execute("UPDATE inbox SET payload='{}'")
    with pytest.raises(ValueError, match="changed"):
        ledger.execute("fixture")
    ledger.close()


@pytest.mark.parametrize(
    "change", [{"production_authority": True}, {"scope": "production"}, {"revision": True}, {"revision": 0}]
)
def test_untrusted_message_cannot_enable_production_or_forge_revision(tmp_path, change):
    ledger = o.Ledger(tmp_path / "owned.sqlite")
    clock, body = message()
    with pytest.raises(ValueError):
        ledger.receive({**body, **change}, clock)
    ledger.close()


def test_actual_owned_worker_crash_replay_and_audit_tampering(tmp_path):
    result = o.resilience(tmp_path)
    assert result["passed"] and result["committed_effects_lost"] == 0


def test_dueling_value_head_does_not_change_action_order_and_training_is_real():
    net = g.Network(9)
    x = np.zeros((64, 25))
    before = net.forward(x)
    net.params[5][0] = 10
    assert np.allclose(net.forward(x) - before, 10)
    for _ in range(200):
        net.fit(x, None, expert=np.full(64, 3), imitation_weight=1)
    assert np.all(net.forward(x).argmax(axis=1) == 3)
    assert net.updates == 200
