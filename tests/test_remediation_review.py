import time

import pytest

from app.access_control import IdentityContext
from app.harness import contracts, crossport, remediation_v2
from app.harness.runner import Harness
from app.harness.store import HarnessStore


def test_long_readonly_review_reads_evidence_before_optional_planning(tmp_path):
    from app.harness import model

    harness = Harness(HarnessStore(tmp_path / "owned.sqlite"))
    try:
        task = harness.create(
            contracts.CreateTask(
                goal="核对RL强基线、独立留出、孪生失败、缺测、逐项评分和发布证据。" * 20,
                request_id="long-review-format-fixture",
                template_id="remediation-review",
                mode="research",
                driver="rules",
            ),
            IdentityContext("fixture", "admin", True, "test"),
            schedule=False,
        )
        variants = model.wire_schema(task)["properties"]["action"]["anyOf"]
        assert {v["properties"]["kind"]["const"] for v in variants} == {"tool"}
        assert {v["properties"]["tool"]["const"] for v in variants} == {
            "crossport.diagnosis", "remediation.review"
        }
        assert all(v["properties"]["steps"]["maxItems"] == 0 for v in variants)
    finally:
        harness.close()


def test_new_review_template_requires_research_mode(tmp_path):
    harness = Harness(HarnessStore(tmp_path / "owned.sqlite"))
    try:
        with pytest.raises(ValueError):
            harness.create(
                contracts.CreateTask(
                    goal="审阅最新整改证据",
                    request_id="wrong-mode-fixture",
                    template_id="remediation-review",
                    mode="enterprise",
                    driver="rules",
                ),
                IdentityContext("fixture", "admin", True, "test"),
                schedule=False,
            )
    finally:
        harness.close()


def test_missing_registered_evidence_is_a_visible_blocker(tmp_path, monkeypatch):
    import json

    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema": "xiaoyi-remediation-evidence.v2",
                "reports": {"missing": {"path": "not-present.json", "sha256": "0" * 64}},
            }
        )
    )
    monkeypatch.setattr(remediation_v2, "REGISTRY", registry)
    monkeypatch.setattr(remediation_v2, "BASE_DIR", tmp_path)
    with pytest.raises(ValueError, match="缺失"):
        remediation_v2.verify_registered_reports()


def test_review_reads_both_artifacts_and_compiles_verified_failures(tmp_path, monkeypatch):
    data = {
        "current": True,
        "registry_sha256": "a" * 64,
        "selected_rl": "fixture_rl",
        "selected_baseline": "fixture_mpc",
        "counts": {
            "forecast_passed": 1,
            "forecast_total": 2,
            "long_passed": 1,
            "long_total": 2,
            "short_passed": 1,
            "short_total": 2,
        },
        "quality_passed": True,
        "field_evidence": {"site_authorization": False},
        "aggregate": [
            {
                "algorithm": "fixture_rl",
                "test_score": -0.7,
                "research_admission": False,
                "blockers": ["both_holdouts_improve"],
            }
        ],
        "notice": "synthetic test fixture; production_authority=false",
        "production_authority": False,
    }
    monkeypatch.setattr(remediation_v2, "compact_review", lambda: data)
    monkeypatch.setattr(
        crossport,
        "diagnosis",
        lambda: {
            "observation_findings": ["synthetic test only"],
            "markov_alias_probe": {},
            "production_authority": False,
        },
    )
    harness = Harness(HarnessStore(tmp_path / "owned.sqlite"))
    try:
        task = harness.create(
            contracts.CreateTask(
                goal="审阅最新整改证据",
                request_id="review-fixture-contract",
                template_id="remediation-review",
                mode="research",
                driver="rules",
            ),
            IdentityContext("fixture", "admin", True, "test"),
        )
        until = time.monotonic() + 10
        while time.monotonic() < until:
            task = harness.store.get(task["id"])
            if task["status"] not in {"running", "queued"}:
                break
            time.sleep(0.01)
        assert task["status"] == "completed", task.get("stop_reason")
        assert {r["tool"] for r in task["results"] if r["ok"]} == {"crossport.diagnosis", "remediation.review"}
        assert task["output_policy"] == "verified_remediation_report"
        assert task["production_authority"] is False
    finally:
        harness.close()
