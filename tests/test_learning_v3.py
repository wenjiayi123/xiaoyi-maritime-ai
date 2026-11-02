import copy
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
import yaml

from app.harness import learning_v3 as learning, modelbased_v3 as model, operations_v3 as ops, physical_v3 as physical
from tests.test_remediation_v2 import records


def test_td_off_keeps_value_head_and_frozen_encoder_stays_exact():
    rng = np.random.default_rng(18)
    x = rng.normal(size=(64, 25))
    actions = np.zeros(64, dtype=int)
    target = np.ones(64) * -4
    expert = np.full(64, 3)
    net = learning.Network(4)
    value_before = [p.copy() for p in net.params[4:]]
    learning.fit(net, x, actions, target, expert, td=False)
    assert all(np.array_equal(a, b) for a, b in zip(value_before, net.params[4:]))
    encoder_before = [p.copy() for p in net.params[:2]]
    net.m = [np.zeros_like(p) for p in net.params]
    net.v = [np.zeros_like(p) for p in net.params]
    learning.fit(net, x, actions, target, expert, freeze_encoder=True)
    assert all(np.array_equal(a, b) for a, b in zip(encoder_before, net.params[:2]))


def test_reference_single_factor_fit_matches_original_dueling_optimizer():
    rng = np.random.default_rng(29)
    x = rng.normal(size=(64, 25))
    actions, expert = rng.integers(5, size=64), rng.integers(5, size=64)
    target = rng.normal(size=64)
    original = learning.Network(7)
    paired = copy.deepcopy(original)
    original.fit(x, actions, target, expert, imitation_weight=.1)
    learning.fit(paired, x, actions, target, expert)
    assert all(np.allclose(a, b, atol=1e-14) for a, b in zip(original.params, paired.params))


def test_frozen_policy_cannot_call_mpc_or_read_future_arrivals(monkeypatch):
    values = np.zeros((len(model.DEMAND), len(model.VOLATILITY), 2, len(model.HORIZONS), len(model.QUEUE), 5, 5), dtype=np.float32)
    values[..., 3] = -1
    policy = model.EmpiricalPolicy("fixture", values, (.2, .02, .02))
    monkeypatch.setattr(model.c, "mpc_q", lambda *_: pytest.fail("online teacher called"))
    a = model.c.Episode(records(), {"kind": "mean7"})
    b = model.c.Episode([(d, v if i < 36 else 90000) for i, (d, v) in enumerate(records())], {"kind": "mean7"})
    assert policy.action(a) == policy.action(b) == 3
    a.scenario = "resource_outage"
    a.index = 42 + 30
    a.cache = None
    assert policy.action(a) <= 2


def test_variable_interval_cannot_hide_one_overwide_prediction():
    limits = {"mae_m": .2, "coverage": .8, "width_m": .75}
    result = physical.evaluate([.01] * 168, [.1] * 167 + [.5], 168, limits, [.1] * 168)
    assert not result["passed"] and result["blockers"] == ["interval_width"]
    assert not physical.evaluate([], [], 168, limits, [])["passed"]


def test_atomic_energy_reservations_conserve_deferred_jobs_without_orphans():
    scheduled = ops.schedule(100, resource_outage=True)
    ids = {a["synthetic_call"] for a in scheduled["allocations"] if a["stage"] == "yard"}
    assert len(ids) + len(scheduled["incomplete_calls"]) == 100
    assert scheduled["incomplete_calls"]
    assert all(a["synthetic_call"] in ids for a in scheduled["allocations"])
    assert ops.old.energy(scheduled, battery_available=False)["unserved_kwh"] == 0
    assert not scheduled["resource_violations"]


def fixture_sequence():
    schema = yaml.safe_load((ops.STANDARD / "dcsa-pc200-openapi.yaml").read_text())
    negotiation = ops.Negotiation(schema)
    clock = datetime(2026, 2, 2, tzinfo=timezone.utc)
    previous = None
    for index, code in enumerate(["EST", "REQ"]):
        event = {"eventID": str(ops.uuid.UUID(int=index + 1)), "eventUpdatedDateTime": clock.isoformat(),
                 "timestamp": {"classifierCode": code, "serviceDateTime": (clock + timedelta(hours=2)).isoformat()}}
        if previous:
            event["replyToEventID"] = previous["eventID"]
        negotiation.receive(event, "consumer" if code == "REQ" else "provider", clock)
        previous = event
    return negotiation, previous, clock


def test_plan_confirms_latest_request_time_and_actual_cannot_be_future():
    negotiation, request, clock = fixture_sequence()
    plan = {**request, "eventID": str(ops.uuid.UUID(int=3)), "replyToEventID": request["eventID"],
            "timestamp": {"classifierCode": "PLN", "serviceDateTime": (clock + timedelta(hours=3)).isoformat()}}
    with pytest.raises(ValueError, match="differs"):
        negotiation.receive(plan, "provider", clock)
    plan["timestamp"]["serviceDateTime"] = request["timestamp"]["serviceDateTime"].replace("+00:00", "Z")
    negotiation.receive(plan, "provider", clock)
    actual = {**plan, "eventID": str(ops.uuid.UUID(int=4)), "timestamp": {**plan["timestamp"], "classifierCode": "ACT"}}
    with pytest.raises(ValueError, match="future execution"):
        negotiation.receive(actual, "provider", clock)
    with pytest.raises(PermissionError, match="ownership"):
        negotiation.receive(request, "provider", clock)


def test_official_contract_subset_and_fault_drills_are_not_certification():
    result = ops.contract_drill()
    assert result["passed"]
    assert not result["external_conformance_completed"]
    assert result["checks"]["network_partition_rejected"]
