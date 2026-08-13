from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_original_routes_remain_available() -> None:
    paths = app.openapi()["paths"]
    assert "/health" in paths
    assert "/api/knowledge" in paths
    assert "/api/chat" in paths

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ready"


def test_dashboard_returns_production_shaped_sandbox_data() -> None:
    response = client.get("/api/dashboard")
    assert response.status_code == 200

    payload = response.json()
    assert payload["data_mode"] == "operations_sandbox"
    assert payload["source_metadata"]["quality_code"] == "PUBLIC_CALIBRATED_SIMULATION_VALIDATED"
    assert payload["source_metadata"]["source_type"] == "public_data_calibrated_simulation"
    assert payload["source_metadata"]["production_ready"] is False
    assert payload["source_metadata"]["live_data_verified"] is False
    assert payload["source_metadata"]["schema_version"] == "port-ops.v1"
    assert len(payload["overview"]["metrics"]) == 4
    assert payload["energy"]["range"] == "today"
    assert len(payload["energy"]["series"]) == 12
    assert payload["energy"]["series_semantics"] == "non_overlapping_interval_energy"
    assert payload["energy"]["interval_minutes"] == 120
    assert payload["energy"]["series"][-1]["timestamp"] == "22:00"
    assert round(sum(item["energy_mwh"] for item in payload["energy"]["series"]), 1) == payload["energy"]["summary"]["total_energy_mwh"]
    assert payload["alerts"]["total"] == 4
    assert {item["task_template_id"] for item in payload["quick_actions"]} >= {
        "analyze-energy",
        "generate-daily-report",
    }


def test_energy_ranges_and_alert_filters() -> None:
    weekly = client.get("/api/energy", params={"range": "7d"})
    assert weekly.status_code == 200
    assert weekly.json()["range"] == "7d"
    assert len(weekly.json()["series"]) == 7
    assert weekly.json()["interval_minutes"] == 1440
    assert round(sum(item["energy_mwh"] for item in weekly.json()["series"]), 1) == weekly.json()["summary"]["total_energy_mwh"]

    monthly = client.get("/api/energy", params={"period": "30d"})
    assert monthly.status_code == 200
    assert monthly.json()["range"] == "30d"
    assert len(monthly.json()["series"]) == 30

    invalid = client.get("/api/energy", params={"range": "year"})
    assert invalid.status_code == 422

    warnings = client.get("/api/alerts", params={"level": "warning"})
    assert warnings.status_code == 200
    assert warnings.json()["total"] == 2
    assert all(item["level"] == "warning" for item in warnings.json()["items"])


def test_task_can_be_advanced_one_visual_step_at_a_time() -> None:
    created = client.post(
        "/api/tasks",
        json={"template_id": "analyze-energy", "parameters": {"scope": "today"}},
    )
    assert created.status_code == 201
    task = created.json()
    task_id = task["id"]
    assert task["status"] == "running"
    assert task["execution_mode"] == "operations_sandbox"
    assert task["progress_percent"] == 0
    assert [step["status"] for step in task["steps"]].count("running") == 1

    for expected_progress in (20, 40, 60, 80, 100):
        advanced = client.post(f"/api/tasks/{task_id}/next")
        assert advanced.status_code == 200
        task = advanced.json()["task"]
        assert task["progress_percent"] == expected_progress

    assert task["status"] == "completed"
    assert task["current_step_id"] is None
    assert all(step["status"] == "completed" for step in task["steps"])

    repeated = client.post(f"/api/tasks/{task_id}/next")
    assert repeated.status_code == 200
    assert repeated.json()["visual_cue"] == "no-change"

    fetched = client.get(f"/api/tasks/{task_id}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "completed"


def test_unknown_task_template_is_rejected() -> None:
    response = client.post("/api/tasks", json={"template_id": "not-a-template"})
    assert response.status_code == 404


def test_report_generation_returns_retrievable_structured_report() -> None:
    generated = client.post(
        "/api/reports",
        json={"report_type": "energy", "include_recommendations": True, "energy_range": "7d"},
    )
    assert generated.status_code == 201
    report = generated.json()
    assert report["status"] == "generated"
    assert report["data_mode"] == "operations_sandbox"
    assert report["source_metadata"]["source_adapter"] == "SandboxPortDataSource"
    assert report["analysis_range"] == "7d"
    assert "分析周期：最近7日" in report["content_markdown"]
    assert any(item["label"] == "最近7日综合能耗" for item in report["kpis"])
    assert report["recommendations"]
    assert report["content_markdown"].startswith("# 港口能耗与碳排分析报告")

    fetched = client.get(f"/api/reports/{report['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == report
