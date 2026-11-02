"""Scientific contracts: causal clocks, censoring, missingness and held-out ownership."""

import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest
from scipy.stats import truncnorm

from app.harness import rl_v6 as rl, long_twin_v6 as twin
from app.harness import proof_v5, research_v6


@pytest.mark.parametrize("mean,sigma,upper", [(1, 0.2, 1.1), (10, 0.2, 1), (-5, 0.3, 2), (1, 1, 0), (0, 1, 3)])
def test_censored_posterior_matches_independent_scipy(mean, sigma, upper):
    actual = float(rl.censored_mean(mean, sigma, upper))
    expected = float(truncnorm.mean(-mean / sigma, (upper - mean) / sigma, loc=mean, scale=sigma)) if upper else 0
    assert actual == pytest.approx(expected, abs=1e-8)
    assert 0 <= actual <= upper


def window():
    first = date(2025, 1, 1)
    return [(first + timedelta(days=i), float(10 + i % 3)) for i in range(132)]


def test_capacity_calibration_cannot_read_unpublished_week():
    records = window()
    altered = [(day, value * 100 if 29 <= i <= 41 else value) for i, (day, value) in enumerate(records)]
    a = rl.Episode(records, {"kind": "mean7"}, "publication_delay")
    b = rl.Episode(altered, {"kind": "mean7"}, "publication_delay")
    assert a.scale == b.scale
    assert a.scale_latest_day == records[28][0]
    assert a.context()[2] == b.context()[2]


def test_policy_does_not_read_current_or_future_actual_arrivals():
    records = window()
    changed = [(day, value * 20 if i >= 42 else value) for i, (day, value) in enumerate(records)]
    policy = rl.Controller(
        rl.planners.MPC(14, 0, (0.2, 0.02, 0.02)),
        {"name": "old_reserve", "sigma": 1, "queue_budget": 0},
        (0.2, 0.02, 0.02),
    )
    a, b = [rl.Episode(r, {"kind": "mean7"}) for r in [records, changed]]
    assert policy.action(a) == policy.action(b)
    a.step(policy.action(a))
    b.step(policy.action(b))
    assert a.frames[-1]["capacity_scale_input_latest_day"] < a.frames[-1]["date"]
    assert a.innovation != b.innovation  # next step may use the observed queue, not hidden arrivals


def test_empirical_probability_bins_keep_tail_means():
    values = np.arange(1000, dtype=float)
    assert np.dot(rl.bin_centroids(values), rl.WEIGHTS) == pytest.approx(np.mean(values))
    assert rl.bin_centroids(values)[-1] > np.quantile(values, 0.975)


def test_frozen_actor_uses_every_remaining_horizon_and_masks_outage():
    table = np.full((len(rl.legacy.DEMAND), len(rl.legacy.VOL), 2, 91, 5, 4), 999.0)
    table[:, :, :, 89, :, :] = 0
    env = rl.Episode(window(), {"kind": "mean7"})
    assert rl.FrozenPolicy(table, 1).action(env) == 4
    env.step(4)
    assert rl.FrozenPolicy(table, 1).action(env) == 0
    env.index = 72
    env.scenario = "resource_outage"
    env.cache = None
    table[:] = 0
    assert rl.FrozenPolicy(table, 1).action(env) == 2


def test_fresh_port_protocol_has_no_overlap_with_development():
    plan = json.loads((rl.DATA / "protocol.json").read_text())
    known, _ = rl.load_development()
    assert not set(known) & {p["id"] for p in plan["new_ports"]}
    assert len(known) == 40
    assert max(plan["train_years"]) < plan["validation_year"] < plan["test_year"]


def test_full_calendar_includes_every_hour_and_leap_day():
    assert len(twin.hours(2025)) == 8760
    assert len(twin.hours(2024)) == 8784
    assert twin.hours(2025)[-1] == datetime(2025, 12, 31, 23, tzinfo=timezone.utc)


def test_missing_gauge_hours_fail_availability_and_are_not_interpolated():
    points = [
        {"actual_m": 1, "predicted_m": 1, "baseline_m": 1, "radius_m": 0.1},
        {"actual_m": None, "predicted_m": 1, "baseline_m": 1, "radius_m": 0.1},
    ]
    limits = json.loads((twin.DATA / "protocol.json").read_text())["research_limits"]
    result = twin.metrics(points, limits)
    assert result["availability"] == 0.5
    assert result["blockers"] == ["availability"]
    points[0]["actual_m"] = None
    assert twin.metrics(points, limits)["n"] == 0


def test_wide_intervals_cannot_pass_by_covering_all_truth():
    limits = json.loads((twin.DATA / "protocol.json").read_text())["research_limits"]
    result = twin.metrics([{"actual_m": 1, "predicted_m": 1.05, "baseline_m": 1.05, "radius_m": 0.5}], limits)
    assert result["coverage"] == 1
    assert result["blockers"] == ["interval_width"]


def test_proof_parameters_reject_unregistered_seed_and_extra_inputs():
    with pytest.raises(ValueError):
        proof_v5.RlV6Args(seed=1)
    with pytest.raises(ValueError):
        proof_v5.LongTwinArgs(cell=100)
    with pytest.raises(ValueError):
        proof_v5.RlV6Args(test_truth={"arrival": 1})


def test_research_source_path_and_digest_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(research_v6, "BASE_DIR", tmp_path)
    file = tmp_path / "source.json"
    file.write_text("{}")
    with pytest.raises(ValueError):
        research_v6.checked("source.json", "0" * 64)
    assert research_v6.checked("source.json", twin.old.sha(file)) == file
    with pytest.raises(ValueError):
        research_v6.checked("../elsewhere.json", "0" * 64)


def test_current_review_compiler_uses_only_source_bound_numbers(monkeypatch):
    from app.harness import remediation_v2
    from app.harness.contracts import digest
    from app.harness.runner import Harness
    from app.harness.verification import verify

    data = {
        "registry_sha256": "same",
        "selected_baseline": "baseline",
        "selected_rl": "candidate",
        "aggregate": [],
        "counts": {
            "forecast_passed": 0,
            "forecast_total": 0,
            "long_passed": 0,
            "long_total": 0,
            "short_passed": 0,
            "short_total": 0,
        },
        "quality_passed": True,
        "field_evidence": {},
        "current": True,
        "notice": "仅离线研究",
        "latest_research": {
            "selected_rl": {
                "new_port_relative_cost_interval": {"mean_delta": 0.0123456789},
                "research_admission": False,
                "blockers": [],
            },
            "selected_cost_baseline": "baseline",
            "annual": {"passed": 3, "total": 8},
            "quarters": {"passed": 13, "total": 32},
            "new_periods": {"passed": 5, "total": 16},
            "notice": "来源可查",
        },
    }
    content = json.dumps(data, ensure_ascii=False)
    artifact = {"content": content, "sha256": digest(content)}
    record = {
        "id": "T1",
        "tool": "remediation.review",
        "ok": True,
        "artifact": "T1.json",
        "sha256": artifact["sha256"],
        "summary": "正式来源",
    }

    class ReadStore:
        def artifact(self, task_id, name):
            assert name == "T1.json"
            return artifact

    store = ReadStore()
    task = {
        "id": "readonly",
        "output_policy": "verified_remediation_report",
        "driver": "rules",
        "required_tools": ["remediation.review"],
        "results": [record],
    }
    monkeypatch.setattr(remediation_v2, "compact_review", lambda: data)
    harness, captured = Harness(store), []

    def capture(current, action, **kwargs):
        captured.append(verify(current, action, store))
        return True

    monkeypatch.setattr(harness, "_finalize", capture)
    try:
        assert harness._publish_report(task)
        assert captured[0]["passed"]
        assert captured[0]["unsupported_numbers"] == []
    finally:
        harness.close()
