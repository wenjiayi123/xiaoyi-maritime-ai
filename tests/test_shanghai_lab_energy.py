import copy
import itertools

import pytest

from integrations.shanghai_lab_v1.data import digest, make_case, verified_dataset
from integrations.shanghai_lab_v1.energy import causal_actions, evaluate, optimize_lattice
from integrations.shanghai_lab_v1.protocol import energy_ledger, verify_energy
from test_shanghai_lab_protocol import node_plan


@pytest.fixture(scope="module")
def sample():
    c = make_case(dataset=verified_dataset())
    return c, node_plan(c)


def reseal(c):
    c["snapshot_sha256"] = digest({k: v for k, v in c.items() if k != "snapshot_sha256"})


def test_storage_moves_and_accounting_is_closed(sample):
    c, p = sample
    r = evaluate(c, p)
    assert r["totals"]["battery_charge_kwh"] > 0 and r["totals"]["battery_discharge_kwh"] > 0
    assert abs(r["totals"]["terminal_soc_difference_kwh"]) < 1e-5
    assert r["totals"]["wear_cny"] > 0
    assert r["comparison"]["deltas"]["cost_saving_cny"] > 0
    assert r["comparison"]["deltas"]["regret_to_hindsight_cny"] >= -1e-6
    verify_energy(c, p, r)


def test_future_realized_weather_cannot_change_first_action(sample):
    c, p = sample
    normal, _ = causal_actions(c, p)
    poisoned = copy.deepcopy(c)
    for h in range(1, 24):
        poisoned["energy"]["pv_kw"][h] = 0
        poisoned["energy"]["base_kw"][h] *= 1.05
    reseal(poisoned)
    pp = copy.deepcopy(p)
    pp["source_snapshot_sha256"] = poisoned["snapshot_sha256"]
    changed, _ = causal_actions(poisoned, pp)
    assert normal[0] == changed[0]


def test_short_horizon_dp_matches_exhaustive_enumeration(sample):
    c, p = copy.deepcopy(sample)
    b = c["battery"]
    b.update(capacity_kwh=1200, power_kw=400, initial_soc=0.5, min_soc=0.25, max_soc=0.75)
    loads = [4000.0] * 24
    solar = [0.0] * 24
    actions = optimize_lattice(c, loads, solar, 21, 600, step_kwh=300)
    result = sum(
        (loads[h] + a) * c["energy"]["price_cny_kwh"][h] + abs(a) * b["wear_cny_kwh"]
        for h, a in zip(range(21, 24), actions)
    )
    alternatives = []
    for middle in itertools.product([300, 600, 900], repeat=2):
        states = [600, *middle, 600]
        cost = 0
        valid = True
        for h, left, right in zip(range(21, 24), states, states[1:]):
            delta = right - left
            ac = delta / b["efficiency"] if delta >= 0 else delta * b["efficiency"]
            if abs(ac) > 400:
                valid = False
                break
            cost += (loads[h] + ac) * c["energy"]["price_cny_kwh"][h] + abs(ac) * b["wear_cny_kwh"]
        if valid:
            alternatives.append(cost)
    assert result == pytest.approx(min(alternatives))


def test_wrong_terminal_inventory_and_impossible_grid_are_rejected(sample):
    c, p = sample
    with pytest.raises(ValueError, match="terminal"):
        energy_ledger(c, p, [100] + [0] * 23)
    changed = copy.deepcopy(c)
    changed["energy"]["grid_limit_kw"] = [100] * 24
    reseal(changed)
    pp = copy.deepcopy(p)
    pp["source_snapshot_sha256"] = changed["snapshot_sha256"]
    with pytest.raises(ValueError):
        evaluate(changed, pp)


def test_flat_price_does_not_invent_storage_profit(sample):
    c, p = copy.deepcopy(sample)
    c["energy"]["price_cny_kwh"] = [0.7] * 24
    reseal(c)
    p["source_snapshot_sha256"] = c["snapshot_sha256"]
    r = evaluate(c, p)
    assert r["totals"]["battery_charge_kwh"] == 0
    assert abs(r["comparison"]["deltas"]["cost_saving_cny"]) < 1e-6
