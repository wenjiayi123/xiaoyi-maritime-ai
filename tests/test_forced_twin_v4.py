from datetime import datetime, timedelta, timezone

import pytest

from app.harness import forced_twin_v4 as f


def fixture(mode):
    initialization = datetime(2026, 7, 1, tzinfo=timezone.utc)
    issue = initialization + timedelta(hours=8)
    times = [issue + timedelta(hours=i) for i in range(169)]
    observed = {at: 1. for at in times}
    tide = {at: .5 for at in times}
    source = {("fixture", "2026-07-01"): {"initialization": initialization, "assumed_available": issue,
        "values": {at: [1013.25, 0, 0] for at in times}}}
    model = {"coefficients": [0.] * 6, "pressure_mean": 1013.25, "mode": mode, "decay_hours": 72 if mode.startswith("causal") else 0}
    return issue, observed, tide, source, model


@pytest.mark.parametrize("mode", ["no_test_water_initialization", "causal_initial_water_then_open_loop_7d"])
def test_forecast_does_not_read_target_or_future_water(mode):
    issue, observed, tide, weather, model = fixture(mode)
    before = f.run_predictions("fixture", "2026-07-01", model, observed, weather, tide)
    observed.update({at: 9999. for at in observed if at > issue})
    assert f.run_predictions("fixture", "2026-07-01", model, observed, weather, tide) == before
    assert len(before) == 168 and before[0]["at"] == issue + timedelta(hours=1)
    assert before[-1]["at"] == issue + timedelta(hours=168)


def test_initialization_is_not_publication_and_missing_gauge_is_not_filled():
    issue, observed, tide, weather, model = fixture("causal_initial_water_then_open_loop_7d")
    del observed[issue]
    assert f.run_predictions("fixture", "2026-07-01", model, observed, weather, tide) == []
    weather[("fixture", "2026-07-01")]["assumed_available"] = issue - timedelta(hours=8)
    with pytest.raises(AssertionError):
        f.run_predictions("fixture", "2026-07-01", model, observed, weather, tide)
