import copy
import json
from pathlib import Path

import pytest

from integrations.shanghai_lab_v1.briefing import check_claims, compile_briefing
from integrations.shanghai_lab_v1.data import digest


@pytest.fixture(scope="module")
def result():
    # Frozen actual four-service run; no generated expected-response stub.
    path = Path(__file__).resolve().parent / "fixtures/shanghai_lab_reference.json"
    return json.loads(path.read_text())


def test_valid_zeros_are_not_missing_and_official_year_is_not_publication(result):
    b = compile_briefing(result)
    assert check_claims(b, b["facts"])["accepted"]
    facts = {f["id"]: f for f in b["facts"]}
    assert facts["late_vessel_hours"]["value"] == 0
    assert facts["annual_container_teu"]["time_basis"] == "2025"
    assert facts["annual_container_teu"]["published_at"].startswith("2026")
    assert facts["storage_carbon_change"]["value"] > 0
    assert "增加" in b["text"]


@pytest.mark.parametrize(
    "field,bad",
    [
        ("unit", "kWh"),
        ("time_basis", "2026"),
        ("scope", "SIPG Yangshan terminal measured"),
        ("source_sha256", "0" * 64),
        ("evidence_class", "field_measured"),
        ("value", None),
        ("value", False),
        ("value", float("nan")),
        ("id", "real_world_rl_gain"),
    ],
)
def test_misleading_structured_claim_rejected(result, field, bad):
    b = compile_briefing(result)
    claim = {**b["facts"][0], field: bad}
    assert not check_claims(b, [claim])["accepted"]


def test_tamper_and_rehashed_false_delta_rejected(result):
    bad = copy.deepcopy(result)
    bad["energy"]["comparison"]["deltas"]["cost_saving_cny"] += 1000
    with pytest.raises(ValueError, match="integrity"):
        compile_briefing(bad)
    bad["result_sha256"] = digest({k: v for k, v in bad.items() if k not in {"result_sha256", "mobile_ack"}})
    with pytest.raises(ValueError, match="arithmetic"):
        compile_briefing(bad)


def test_opt_in_tool_keeps_default_catalog_unchanged():
    from app.harness.tools import catalog, validate

    assert "shanghai.evidence" not in {r["name"] for r in catalog("admin")}
    assert [r["name"] for r in catalog("admin", ["shanghai.evidence"])] == ["shanghai.evidence"]
    with pytest.raises(PermissionError):
        validate("shanghai.evidence", {"run_id": "sjt-" + "a" * 24}, {"allowed_tools": [], "actor_role": "admin"})
