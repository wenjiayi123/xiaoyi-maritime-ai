import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)

COMMAND = "启动RL训练实验，四种强化学习算法加PID和现场SOP规则基线，训练时不渲染，训练后才在测试集渲染。"


def _wait(run_id: str) -> dict:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        run = client.get(f"/api/rl-mission/training/{run_id}").json()
        if run["status"] not in {"queued", "training", "cancelling"}:
            return run
        time.sleep(0.02)
    raise AssertionError(f"training run {run_id} did not finish")


def test_rl_command_builds_real_training_and_holdout_workflow() -> None:
    plan = client.post("/api/automation/plans", json={"command": COMMAND}).json()
    assert plan["intent"] == "optimize_agv_energy_rl"
    assert [action["kind"] for action in plan["actions"]] == [
        "open_rl_mission", "check_rl_systems", "build_rl_scenario", "replay_rl_training",
        "run_rl_competition", "verify_rl_policy", "dispatch_rl_dry_run", "present_rl_mission",
    ]
    assert "真实训练" in plan["actions"][3]["label"]
    assert plan["actions"][-2]["requires_confirmation"] is True


def test_rl_mission_runs_locally_and_seals_test_data_until_training_finishes() -> None:
    health = client.get("/api/rl-mission/health").json()
    assert health["online_count"] == health["total"] == 4
    assert len(health["algorithms"]) == 6
    assert health["production_write_enabled"] is False

    payload = {
        "mission_id": "rlm-real-test",
        "command": COMMAND,
        "episodes": 10,
        "horizon_steps": 24,
        "seed": 712,
    }
    scenario = client.post("/api/rl-mission/scenario", json=payload).json()
    assert scenario["dataset"]["row_count"] == 19735
    assert scenario["dataset"]["port_data"] is False
    assert scenario["scenario"]["render_during_training"] is False

    started = client.post("/api/rl-mission/train", json=payload)
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    early_test = client.post("/api/rl-mission/simulate", json={**payload, "run_id": run_id})
    assert early_test.status_code in {200, 409}  # very small runs can finish before this request

    run = _wait(run_id)
    assert run["status"] in {"trained", "evaluated"}
    assert run["training"]["rendering_performed"] is False
    assert run["reproducibility"]["test_rows_touched_during_training"] is False
    assert set(run["training"]["algorithms"]) == {
        "q_learning", "sarsa", "expected_sarsa", "double_q_learning", "pid", "sop_rule",
    }

    if early_test.status_code == 200:
        evaluation = early_test.json()
    else:
        evaluation = client.post("/api/rl-mission/simulate", json={**payload, "run_id": run_id}).json()
    assert evaluation["rendering_performed"] is True
    assert evaluation["render_split"] == "test"
    assert len(evaluation["results"]) == 6
    assert all(result["frames"] for result in evaluation["results"])
    assert {frame["split"] for result in evaluation["results"] for frame in result["frames"]} == {"test"}

    verified = client.post("/api/rl-mission/verify", json={**payload, "run_id": run_id}).json()
    assert verified["ok"] is True
    assert verified["passed"] == verified["total"] == 6

    dispatched = client.post("/api/rl-mission/dispatch", json={**payload, "run_id": run_id}).json()
    assert dispatched["status"] == "dry_run_recorded"
    assert dispatched["production_executed"] is False


def test_port_traffic_mission_uses_port_scenario_and_port_metrics() -> None:
    payload = {
        "mission_id": "rlm-port-test",
        "command": COMMAND,
        "dataset_id": "noaa_la_lb_ais_2024_12_25_1min",
        "episodes": 10,
        "horizon_steps": 24,
        "seed": 713,
    }
    scenario = client.post("/api/rl-mission/scenario", json=payload).json()
    assert scenario["dataset"]["environment_type"] == "port_operations"
    assert scenario["dataset"]["source_type"] == "public_port_traffic"
    assert scenario["scenario"]["id"] == "measured-port-operations-coordination"
    assert "作业协同" in scenario["scenario"]["label"]
    assert "公开港区船舶自动识别系统交通观测" in scenario["data_notice"]
    assert "不是码头生产实绩" in scenario["data_notice"]

    started = client.post("/api/rl-mission/train", json=payload)
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    run = _wait(run_id)
    assert run["status"] == "trained"

    evaluation = client.post(
        "/api/rl-mission/simulate", json={**payload, "run_id": run_id}
    )
    assert evaluation.status_code == 200
    body = evaluation.json()
    assert body["environment_type"] == "port_operations"
    assert len(body["race"]) == 6
    assert all("served_units" in item for item in body["race"])
    assert all("average_backlog_units" in item for item in body["race"])
    assert all("wait_proxy_hours" in item for item in body["race"])
    assert all("cost_saving_percent" not in item for item in body["race"])
    assert all("peak_reduction_percent" not in item for item in body["race"])


def test_frontend_contains_real_rl_lab_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    javascript = (root / "web" / "app.js").read_text(encoding="utf-8")
    css = (root / "web" / "styles.css").read_text(encoding="utf-8")
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    assert "openRLLabConfig" in javascript
    assert "data-rl-algorithm" in javascript
    assert "/api/rl-mission/train" in javascript
    assert "/api/rl-mission/training/" in javascript
    assert "REAL TRAINING · NO RENDER" in javascript
    assert "HOLDOUT TEST RENDER" in javascript
    assert "确认归档本地测试 Dry-run" in javascript
    assert '"政策法规":"法规 合规 监管 交通运输部 海事管理机构"' in javascript
    assert "item.average_backlog_units" in javascript
    assert "item.wait_proxy_hours" in javascript
    assert ".rl-training-progress" in css
    assert "真实RL训练实验室" in html
