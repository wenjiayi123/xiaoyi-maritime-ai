from copy import deepcopy
from dataclasses import replace

import pytest

from app.agent_training.expert_energy import digest
from app.agent_training.expert_environment import (
    ExpertEnvironment,
    ExpertTask,
    RecordedEnergyProvider,
    reference_action,
)


def receipt(green, *, missing=False):
    context = {
        "schema": "expert-energy-source.v1",
        "production_authority": False,
        "legacy_context": {"source_version": "b" * 64},
    }
    context["source_version"] = digest(context)
    parameters = {
        "request_id": "fixture-" + str(green),
        "baseline_green_preference": 0.5,
        "green_preference": green,
        "carbon_price_cny_per_ton": 85.0,
        "expected_source_version": context["source_version"],
    }
    native_params = {**parameters, "expected_source_version": "b" * 64}
    raw_rows, alternatives = [], []
    for i, g in enumerate([0.5, green]):
        raw = {"index": i, "green": g}
        params = {"green": g, "carbon": 85.0}
        raw_rows.append({"parameters": params, "raw": raw})
        facts = {
            "status": "ready",
            "issues": [],
            "production_authority": False,
            "raw_snapshot_sha256": digest(raw),
            "dataset_sha256": "c" * 64,
            "window_id": "w1",
            "site_id": "offline-port",
            "scenario_id": "case1",
            "carbon_kg": 100 if i == 0 else (80 if green == 0.8 else 95),
            "cost_cny": 100 if i == 0 else (120 if green == 0.8 else 90),
            "service_pct": 99,
            "units": {"carbon_kg": "kgCO2e", "cost_cny": "CNY", "service_pct": "%"},
        }
        if missing and i == 1:
            facts["service_pct"] = None
            facts["status"] = "needs_evidence"
            facts["issues"].append("service_arrivals_missing")
        alternatives.append({"parameters": params, "facts": facts})
    native = {"parameters": native_params, "request_sha256": digest(native_params), "alternatives": raw_rows}
    native["receipt_sha256"] = digest(native)
    result = {
        "schema": "expert-energy-comparison.v1",
        "request_id": parameters["request_id"],
        "request_sha256": digest(parameters),
        "parameters": parameters,
        "source_context": context,
        "production_authority": False,
        "native_receipt": native,
        "alternatives": alternatives,
    }
    result["receipt_sha256"] = digest(result)
    return result


def task(**changes):
    fields = {
        "case_id": "fixture-task",
        "goal": "比较两个候选并按当前约束给出结论。",
        "candidate_green_preferences": (0.8, 0.6),
        "baseline_green_preference": 0.5,
        "carbon_price_cny_per_ton": 85.0,
        "requirements": {"min_carbon_reduction_pct": 10.0, "max_cost_cny": 130.0, "min_service_pct": 98.0},
    }
    fields.update(changes)
    return ExpertTask(**fields)


def env(t=None, receipts=None):
    return ExpertEnvironment(t or task(), RecordedEnergyProvider(receipts or [receipt(0.8), receipt(0.6)]))


def run(environment):
    while not environment.done:
        environment.step(reference_action(environment))
    return environment


def test_complete_comparison_selects_a_verified_feasible_candidate():
    e = run(env())
    assert e.success and e.business_complete
    assert e.report["recommendation_index"] == 0
    assert [row["label"] for row in e.steps] == list("DEFHIJ")


def test_infeasible_is_only_over_registered_candidates_not_business_success():
    e = run(env(task(requirements={"min_carbon_reduction_pct": 50.0})))
    assert e.success and not e.business_complete
    assert e.outcome == "no_registered_candidate_meets_requirements"
    assert e.report["candidate_count"] == 2


def test_clarification_reply_can_continue_but_waiting_is_not_task_completion():
    e = run(env(task(carbon_price_cny_per_ton=None, scripted_replies={"carbon_price_cny_per_ton": 85.0})))
    assert e.success and e.clarification_correct
    assert e.steps[0]["event"]["kind"] == "scripted_user_reply"
    waiting = run(env(task(carbon_price_cny_per_ton=None)))
    assert waiting.clarification_correct and not waiting.business_complete and not waiting.success
    assert waiting.outcome == "awaiting_user_clarification"


def test_missing_parameter_does_not_silently_default_or_compute():
    e = env(task(baseline_green_preference=None))
    e.step("D")
    result = e.step("E")
    assert result["error"] and not e.provider.receipts
    assert e.known["baseline_green_preference"] is None


def test_lost_result_requires_readback_and_blocks_another_comparison():
    e = env(task(lose_response_candidates=(0,)))
    for label in "DE":
        e.step(label)
    assert e.pending == 0
    assert e.step("F")["error"]
    assert not e.provider.receipts
    e.step("G")
    assert 0 in e.calculated and e.pending is None
    assert run(e).success


def test_real_transport_exception_exposes_durable_pending_state(monkeypatch):
    e = env()
    original = e.provider.calculate

    def fail(index, parameters, **kwargs):
        original(index, parameters, lose_response=True)
        raise OSError("socket response lost")

    monkeypatch.setattr(e.provider, "calculate", fail)
    e.step("D")
    e.step("E")
    assert e.pending == 0 and reference_action(e) == "G"


def test_goal_change_invalidates_old_verification_and_changes_recommendation():
    changed = {"min_carbon_reduction_pct": 0.0, "max_cost_cny": 95.0, "min_service_pct": 98.0}
    e = env(task(changed_requirements=changed, change_after_calculations=2))
    for label in "DEHF":
        e.step(label)
    assert e.goal_version == 2
    assert e.verifications[0]["goal_version"] == 1
    assert reference_action(e) == "H"
    assert run(e).report["recommendation_index"] == 1


@pytest.mark.parametrize("label", ["J", "K", "L", "M"])
def test_report_without_evidence_is_terminal_failure(label):
    e = env()
    e.step(label)
    assert e.done and not e.success and not e.business_complete


def test_missing_evidence_is_not_infeasibility():
    records = [receipt(0.8, missing=True), receipt(0.6, missing=True)]
    e = run(env(receipts=records))
    assert e.success and not e.business_complete and e.outcome == "evidence_gap_reported"
    e = env(receipts=records)
    for label in "DEFHIL":
        e.step(label)
    assert not e.success


def test_prompt_never_exposes_future_shock_or_user_answer():
    a = task(carbon_price_cny_per_ton=None)
    b = replace(
        a,
        scripted_replies={"carbon_price_cny_per_ton": 350.0},
        lose_response_candidates=(0,),
        changed_requirements={"max_cost_cny": 123456.0},
    )
    assert env(a).prompt() == env(b).prompt()
    assert "123456" not in env(b).prompt()


def test_replay_cannot_invent_unrecorded_parameter_result():
    e = env(task(carbon_price_cny_per_ton=200.0))
    e.step("D")
    assert e.step("E")["error"]["message"] == "no native evidence for these parameters"
    assert not e.calculated


def test_loop_is_bounded_and_does_not_turn_into_success():
    e = env(task(max_steps=3))
    for _ in range(3):
        e.step("A")
    assert e.done and not e.success and e.outcome == "step_limit"


def test_stale_source_error_clears_old_verifications(monkeypatch):
    e = env()
    for label in "DEFH":
        e.step(label)
    monkeypatch.setattr(e.provider, "verify", lambda *args: (_ for _ in ()).throw(ValueError("source changed")))
    e.step("I")
    assert not e.context_read and not e.calculated and not e.verifications


def test_invalid_requirement_or_candidate_rejected_before_episode():
    with pytest.raises(ValueError):
        task(requirements={"max_cost_cny": True})
    with pytest.raises(ValueError):
        task(candidate_green_preferences=(0.8, float("nan")))
    with pytest.raises(ValueError):
        task(scripted_replies={"carbon_price_cny_per_ton": -1.0})


def test_receipt_content_and_source_mixup_rejected():
    bad = deepcopy(receipt(0.8))
    bad["alternatives"][0]["facts"]["cost_cny"] = -100
    with pytest.raises(ValueError, match="checksum"):
        RecordedEnergyProvider([bad])
