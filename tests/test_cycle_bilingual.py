from app.cycle_evidence import Args,lookup
from app.cycle_english import scope_issue
from app.harness.model import local_final_limit


def test_response_language_respects_explicit_language_and_smaller_job_budget():
    assert local_final_limit({"goal":"Answer this case in English."})==900
    assert local_final_limit({"goal":"Answer this case in Chinese."})==400
    assert local_final_limit({"goal":"用英文回答","budget":{"max_output_chars":120}})==120


def test_english_baseline_projects_only_requested_reference_and_rejects_wrong_nonzero():
    goal="Read CYCLE-BESS-7COST. Did it qualify against fixed tariff recognition?"
    data=lookup(Args(case_id="CYCLE-BESS-7COST"),{"goal":goal})
    assert list(data["comparison"])==["fixed tariff recognition"]
    assert set(data["comparison"]["fixed tariff recognition"].values())=={0.0}
    assert scope_issue(goal,"All three gains against fixed tariff recognition were zero. It did not qualify.")==[]
    assert scope_issue(goal,"Against fixed tariff recognition the cost gain was 786.68 yuan. All other gains were zero. It did not qualify.")


def test_historical_observation_date_is_distinct_from_forecast_week_end():
    goal="Read CYCLE-US-20261120. Give the last input date and target-week observation."
    data=lookup(Args(case_id="CYCLE-US-20261120"),{"goal":goal})
    assert data["date_of_last_individual_input_observation"]=="2026-11-03"
    assert data["target_week_end"]=="2026-11-20" and data["target_week_observation_available"] is False
    assert scope_issue(goal,"An observation is available for the week ending November 3, 2026.")
