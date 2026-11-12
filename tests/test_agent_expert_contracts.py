"""Meaningful input-unit and business-outcome regressions; zero model/API calls."""
import copy

import pytest

from app.agent_training.expert_contracts import inspect_energy_request, assess_energy_option


def request(base="0.5", green="0.8", carbon="100元/吨"):
    return f"比较能碳方案，基准绿色偏好{base}，候选绿色偏好{green}，碳价{carbon}。"


def test_preserves_explicit_parameters_and_zero():
    r = inspect_energy_request(request("0", "0", "0元/吨"))
    assert r["status"] == "ready_for_context_check"
    assert set(r["parameters"].values()) == {0}
    assert r["execution_authorized"] is False


@pytest.mark.parametrize("base,green,carbon,expected", [
    ("50%", "80%", "100元/吨", 100), ("0.5", "0.8", "0.1千元/吨", 100),
    ("0.5", "0.8", "0.1元/千克", 100), ("50％", "80％", "100CNY/t", 100),
])
def test_normalizes_explicit_units(base, green, carbon, expected):
    r = inspect_energy_request(request(base, green, carbon))
    assert r["status"] == "ready_for_context_check"
    assert r["parameters"] == {"baseline_green_preference": .5, "green_preference": .8, "carbon_price_cny_per_ton": expected}


@pytest.mark.parametrize("text", [
    "读取能碳系统，比较方案并报告。", request(carbon="100美元/吨"), request(carbon="100"),
    request(green="0.8和0.6"), request(green="0.8，候选绿色偏好0.6"),
    request() + "碳排放降低10%，服务满足率不得低于98%。",
    "读取能碳，不要试算。", "比较能碳，不要使用默认参数。", request(green="80"),
])
def test_does_not_silently_drop_missing_conflicting_or_unsupported_conditions(text):
    assert inspect_energy_request(text)["status"] == "needs_clarification"


def test_defaults_are_explicit_and_recorded():
    r = inspect_energy_request("比较能碳，采用登记默认参数。")
    assert r["status"] == "ready_for_context_check"
    assert r["parameters"]["carbon_price_cny_per_ton"] == 85
    assert len(r["normalizations"]) == 3


def test_foreign_currency_is_not_published_as_cny():
    r = inspect_energy_request(request(carbon="100美元/吨"))
    assert "carbon_price_cny_per_ton" not in r["parameters"]


@pytest.fixture
def options():
    base = {"site_id": "SIM-A", "window_id": "day-01", "dataset_sha256": "dataset-a", "carbon_kg": 1000,
            "cost_cny": 10000, "service_pct": 99, "units": {"carbon_kg": "kgCO2e", "cost_cny": "CNY", "service_pct": "%"}}
    candidate = copy.deepcopy(base)
    candidate.update(carbon_kg=850, cost_cny=9500, service_pct=98.5)
    return base, candidate


def test_checks_all_business_requirements(options):
    r = assess_energy_option(*options, {"min_carbon_reduction_pct": 10, "max_cost_cny": 10000, "min_service_pct": 98})
    assert r["status"] == "meets_registered_requirements"
    assert r["deltas"]["carbon_reduction_pct"] == 15


def test_cheaper_does_not_mean_lower_carbon(options):
    base, candidate = options
    candidate["carbon_kg"] = 1100
    r = assess_energy_option(base, candidate, {"min_carbon_reduction_pct": 10, "max_cost_cny": 10000})
    assert r["status"] == "does_not_meet_registered_requirements"
    assert r["checks"] == {"carbon_target": False, "cost_limit": True}


@pytest.mark.parametrize("mutation", ["site", "window", "units", "service", "nan", "bool"])
def test_incomparable_or_missing_metrics_do_not_pass(options, mutation):
    base, candidate = options
    if mutation == "site":
        candidate["site_id"] = "SIM-B"
    if mutation == "window":
        candidate["window_id"] = "day-02"
    if mutation == "units":
        candidate["units"]["carbon_kg"] = "tonCO2e"
    if mutation == "service":
        candidate.pop("service_pct")
    if mutation == "nan":
        candidate["carbon_kg"] = float("nan")
    if mutation == "bool":
        candidate["cost_cny"] = False
    assert assess_energy_option(base, candidate, {"min_service_pct": 98})["status"] == "needs_evidence"


def test_undefined_percent_and_unknown_constraints_are_not_success(options):
    base, candidate = options
    base["carbon_kg"] = 0
    assert assess_energy_option(base, candidate, {"min_carbon_reduction_pct": 10})["status"] == "needs_evidence"
    assert assess_energy_option(base, candidate, {"unimplemented_tide_constraint": 1})["status"] == "needs_evidence"
