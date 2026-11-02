import copy

from app.harness import port_readiness as p
from app.harness import model


def test_model_review_cannot_invent_opaque_study_identifiers():
    task = {"template_id": "crossport-review", "goal": "审阅最新研究", "inputs": [], "results": [],
            "required_tools": ["crossport.compare", "crossport.diagnosis"],
            "allowed_tools": ["crossport.compare", "crossport.diagnosis"], "plan": None}
    def variants():
        return model.wire_schema(task)["properties"]["action"]["anyOf"]
    v = next(v for v in variants() if v["properties"]["tool"]["const"] == "crossport.compare")
    assert v["properties"]["arguments"]["properties"]["study_id"] == {"type": "null"}
    assert "ask" not in [v["properties"]["kind"]["const"] for v in variants()]
    actual = "hc-" + "a" * 32
    task["goal"] += actual
    v = next(v for v in variants() if v["properties"]["tool"]["const"] == "crossport.compare")
    assert v["properties"]["arguments"]["properties"]["study_id"] == {"enum": [actual]}


def test_functional_passes_cannot_hide_research_physical_or_operational_gaps(monkeypatch):
    study = {
        "historical_only": False,
        "current_validation_issues": [],
        "aggregate": [{"research_admission": False}],
        "selected_algorithm": "mpc",
        "comparator_algorithm": "mpc",
        "runs": [{"maximum_flow_balance_error": 0}],
        "twin_calibration": {"all_cells_passed": False, "passed_cells": 14, "total_cells": 16},
        "multisite_physical_calibration": {
            "all_station_calibration_gates_passed": False,
            "results": [{"calibration_passed": False}] * 3,
        },
    }
    monkeypatch.setattr(p.crossport, "report", lambda *a: copy.deepcopy(study))
    monkeypatch.setattr(
        p.adaptive_twin,
        "report",
        lambda: {
            "historical_only": False,
            "all_research_gates_passed": False,
            "results": [{"research_gates_passed": True}],
        },
    )
    result = p.assess("fixture", "fixture")
    assert result["passed_items"] == 3
    assert result["top_port_full_acceptance"] is False and result["research_admission"] is False
    assert result["production_authority"] is False
    study["historical_only"] = True
    assert p.assess("fixture", "fixture")["passed_items"] == 0
