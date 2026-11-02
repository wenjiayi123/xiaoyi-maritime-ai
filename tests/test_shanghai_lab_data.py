import copy

import pytest

from integrations.shanghai_lab_v1.data import SCENARIOS, digest, make_case, validate_case, verified_dataset


@pytest.fixture(scope="module")
def dataset():
    return verified_dataset()


def test_actual_source_coverage_and_scopes(dataset):
    manifest, daily, weather, assumptions = dataset
    assert len(daily) == 2557 and len(weather) == 8760
    assert daily[0]["date"] == "2019-01-01" and daily[-1]["date"] == "2025-12-31"
    assert {s["evidence_class"] for s in manifest["sources"]} == {
        "official_aggregate",
        "public_provider_derived",
        "public_reanalysis",
    }
    assert assumptions["production_authority"] is False


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_determinism_and_quality(scenario, dataset):
    a = make_case(scenario=scenario, dataset=dataset)
    assert a == make_case(scenario=scenario, dataset=dataset)
    assert validate_case(a)
    if scenario == "communications_loss":
        with pytest.raises(ValueError, match="quality"):
            validate_case(a, require_usable=True)
    else:
        assert validate_case(a, require_usable=True)


def test_all_365_dates_preserve_raw_values(dataset):
    for row in dataset[1]:
        if row["date"].startswith("2025-"):
            case = make_case(row["date"], dataset=dataset)
            assert case["public_context"]["container_calls"] == int(row["portcalls_container"])
            assert all(j["entity_class"] == "engineered_vessel_call_not_real_identity" for j in case["jobs"])


def test_tampering_units_and_missing_are_rejected(dataset):
    case = make_case(dataset=dataset)
    changed = copy.deepcopy(case)
    changed["public_context"]["container_calls"] += 1
    with pytest.raises(ValueError, match="hash"):
        validate_case(changed)
    changed = copy.deepcopy(case)
    changed["contract"]["field_contracts"]["energy.base_kw"]["unit"] = "MW"
    changed["snapshot_sha256"] = digest({k: v for k, v in changed.items() if k != "snapshot_sha256"})
    with pytest.raises(ValueError, match="units"):
        validate_case(changed)
    for value in [None, float("nan"), -1]:
        changed = copy.deepcopy(case)
        changed["energy"]["pv_kw"][0] = value
        with pytest.raises((ValueError, TypeError)):
            changed["snapshot_sha256"] = digest({k: v for k, v in changed.items() if k != "snapshot_sha256"})
            validate_case(changed)
    assert case["energy"]["pv_kw"][0] == 0  # real nighttime zero survives


def test_other_year_and_unknown_scenario_rejected(dataset):
    with pytest.raises(ValueError):
        make_case("2024-01-01", dataset=dataset)
    with pytest.raises(ValueError):
        make_case(scenario="unregistered", dataset=dataset)
