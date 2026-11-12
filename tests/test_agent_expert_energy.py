from copy import deepcopy

import pytest

from app.agent_training.expert_energy import API, ExpertEnergyBackend, digest


@pytest.fixture
def backend(tmp_path):
    context = {
        "schema": "expert-energy-source.v1",
        "production_authority": False,
        "legacy_context": {"source_version": "b" * 64},
    }
    context["source_version"] = digest(context)
    state = {"calls": [], "context": context, "receipt": None}

    def request(path, payload=None):
        state["calls"].append((path, deepcopy(payload)))
        if path == API + "/source-context":
            return deepcopy(state["context"])
        if payload:
            native_params = {**payload, "expected_source_version": "b" * 64}
            native_rows, rows = [], []
            for i, green in enumerate([payload["baseline_green_preference"], payload["green_preference"]]):
                params = {"green": green, "carbon": payload["carbon_price_cny_per_ton"]}
                raw = {"case": i}
                native_rows.append({"parameters": params, "raw": raw})
                facts = {
                    "status": "ready",
                    "issues": [],
                    "production_authority": False,
                    "raw_snapshot_sha256": digest(raw),
                    "dataset_sha256": "c" * 64,
                    "window_id": "w1",
                    "site_id": "offline-port",
                    "scenario_id": "case1",
                    "carbon_kg": 100 if i == 0 else 80,
                    "cost_cny": 100,
                    "service_pct": 99,
                    "units": {"carbon_kg": "kgCO2e", "cost_cny": "CNY", "service_pct": "%"},
                }
                rows.append({"parameters": params, "facts": facts})
            native = {"parameters": native_params, "request_sha256": digest(native_params), "alternatives": native_rows}
            native["receipt_sha256"] = digest(native)
            receipt = {
                "schema": "expert-energy-comparison.v1",
                "request_id": payload["request_id"],
                "request_sha256": digest(payload),
                "parameters": payload,
                "source_context": deepcopy(state["context"]),
                "production_authority": False,
                "native_receipt": native,
                "alternatives": rows,
            }
            receipt["receipt_sha256"] = digest(receipt)
            state["receipt"] = receipt
            return {"receipt": deepcopy(receipt), "duplicate": False}
        return {"receipt": deepcopy(state["receipt"]), "source_context_now": deepcopy(state["context"])}

    tool = ExpertEnergyBackend(tmp_path)
    tool.request = request
    return tool, state, request


PARAMETERS = {"baseline_green_preference": 0.5, "green_preference": 0.8, "carbon_price_cny_per_ton": 85.0}
REQUIREMENTS = {"min_carbon_reduction_pct": 10, "max_cost_cny": 110, "min_service_pct": 98}


def test_complete_trace_verifies_all_business_constraints(backend):
    tool, state, _ = backend
    tool.read_context()
    tool.compare(PARAMETERS, "expert-test-001")
    result = tool.verify(REQUIREMENTS)
    assert result["assessment"]["status"] == "meets_registered_requirements"
    assert result["adapter_model_calls"] == 0
    assert len([p for _, p in state["calls"] if p]) == 1


def test_lost_response_survives_restart_and_only_readback_recovers(backend):
    tool, state, request = backend
    tool.read_context()
    tool.compare(PARAMETERS, "expert-test-001", withhold_response=True)
    restarted = ExpertEnergyBackend(tool.folder)
    restarted.request = request
    with pytest.raises(RuntimeError, match="readback"):
        restarted.compare(PARAMETERS, "expert-test-002")
    with pytest.raises(ValueError, match="recover"):
        restarted.verify(REQUIREMENTS)
    restarted.recover()
    assert restarted.verify(REQUIREMENTS)["assessment"]["status"] == "meets_registered_requirements"
    assert len([p for _, p in state["calls"] if p]) == 1
    assert not restarted.state["pending"]


def test_changed_source_after_completion_prevents_reporting(backend):
    tool, state, _ = backend
    tool.read_context()
    tool.compare(PARAMETERS, "expert-test-001")
    state["context"]["legacy_context"]["source_version"] = "d" * 64
    state["context"]["source_version"] = digest({k: v for k, v in state["context"].items() if k != "source_version"})
    with pytest.raises(ValueError, match="source changed"):
        tool.verify(REQUIREMENTS)


def test_business_failure_is_not_execution_success(backend):
    tool, _, _ = backend
    tool.read_context()
    tool.compare(PARAMETERS, "expert-test-001")
    result = tool.verify({**REQUIREMENTS, "min_carbon_reduction_pct": 99})
    assert result["assessment"]["status"] == "does_not_meet_registered_requirements"


@pytest.mark.parametrize("field", ["site_id", "window_id", "scenario_id", "service_pct"])
def test_mismatching_or_missing_evidence_fails_closed(backend, field):
    tool, state, _ = backend
    tool.read_context()
    tool.compare(PARAMETERS, "expert-test-001")
    state["receipt"]["alternatives"][1]["facts"][field] = None
    state["receipt"]["receipt_sha256"] = digest({k: v for k, v in state["receipt"].items() if k != "receipt_sha256"})
    tool.accept(state["receipt"], tool.state["receipt"]["parameters"])
    assert tool.verify(REQUIREMENTS)["assessment"]["status"] == "needs_evidence"


def test_tampering_and_changed_endpoint_are_rejected(backend):
    tool, state, _ = backend
    tool.read_context()
    tool.compare(PARAMETERS, "expert-test-001")
    state["receipt"]["alternatives"][1]["facts"]["cost_cny"] = 1
    with pytest.raises(ValueError, match="readback differs"):
        tool.verify(REQUIREMENTS)
    with pytest.raises(ValueError, match="endpoint differs"):
        ExpertEnergyBackend(tool.folder, "http://localhost:18810")


def test_explicit_parameters_required(backend):
    tool, state, _ = backend
    with pytest.raises(ValueError, match="read context"):
        tool.compare(PARAMETERS, "expert-test-001")
    tool.read_context()
    with pytest.raises(ValueError, match="complete parameters"):
        tool.compare({"green_preference": 0.8}, "expert-test-001")
    assert not any(p for _, p in state["calls"])
