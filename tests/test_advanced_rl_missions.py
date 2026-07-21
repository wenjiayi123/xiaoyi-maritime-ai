from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_unverifiable_advanced_rl_showcases_are_retired() -> None:
    health = client.get("/api/advanced-rl/health")
    assert health.status_code == 200
    assert health.json()["status"] == "retired"
    assert health.json()["replacement"] == "/api/rl-lab"

    for route in (
        "/api/advanced-rl/weather/scenario",
        "/api/advanced-rl/weather/inference",
        "/api/advanced-rl/weather/benchmark",
        "/api/advanced-rl/weather/replay",
        "/api/advanced-rl/weather/verify",
        "/api/advanced-rl/weather/dispatch",
        "/api/advanced-rl/marl/scenario",
        "/api/advanced-rl/marl/coordinate",
        "/api/advanced-rl/marl/verify",
        "/api/advanced-rl/marl/dispatch",
    ):
        response = client.post(route, json={"mission_id": "retired-test"})
        assert response.status_code == 410
        assert "/api/rl-lab" in response.json()["detail"]


def test_retired_showcases_are_not_exposed_as_frontend_launchers() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    launcher = html.split('<div class="rl-mission-launcher"', 1)[1].split("</div>", 1)[0]
    assert "真实RL训练实验室" in launcher
    assert "极端天气联合调度" not in launcher
    assert "多智能体协同优化" not in launcher
