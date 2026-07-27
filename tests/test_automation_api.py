from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_energy_command_builds_safe_visual_sequence() -> None:
    response = client.post(
        "/api/automation/plans",
        json={"command": "帮我查看未来7日能耗趋势并分析", "execution_mode": "automatic"},
    )
    assert response.status_code == 201
    plan = response.json()
    assert plan["actionable"] is True
    assert plan["intent"] == "analyze_energy"
    assert [action["kind"] for action in plan["actions"]] == [
        "navigate",
        "set_range",
        "inspect_metrics",
        "create_task",
        "advance_task",
        "advance_task",
        "advance_task",
        "advance_task",
        "advance_task",
        "inspect_task_result",
        "present_result",
    ]
    assert plan["actions"][1]["parameters"]["range"] == "7d"
    assert all(action["visual_target"] for action in plan["actions"])


def test_unknown_command_falls_back_to_knowledge_chat() -> None:
    response = client.post("/api/automation/plans", json={"command": "量子港口是什么"})
    assert response.status_code == 201
    plan = response.json()
    assert plan["actionable"] is False
    assert plan["actions"] == []
    assert plan["intent"] == "general_question"


def test_operational_questions_do_not_become_ui_commands() -> None:
    questions = [
        "岸电 THDi 超标告警应该先检查什么？",
        "为什么打不开数据分析？",
        "如何生成能耗报告？",
        "是否应该关闭岸电？",
    ]
    for question in questions:
        response = client.post("/api/automation/plans", json={"command": question})
        assert response.status_code == 201
        plan = response.json()
        assert plan["intent"] == "general_question"
        assert plan["actionable"] is False
        assert plan["actions"] == []


def test_launch_simulator_command_builds_whitelisted_runtime_sequence() -> None:
    response = client.post("/api/automation/plans", json={"command": "启动模拟器"})

    assert response.status_code == 201
    plan = response.json()
    assert plan["intent"] == "launch_sailing_simulator"
    assert plan["actionable"] is True
    assert [action["kind"] for action in plan["actions"]] == [
        "check_simulator_runtime",
        "launch_simulator",
        "verify_simulator_runtime",
        "open_simulator",
    ]
    assert all(action["risk_level"] == "low" for action in plan["actions"])
    assert all(action["requires_confirmation"] is False for action in plan["actions"])
    assert "航行模拟器" in plan["actions"][1]["label"]
    assert "Godot" in plan["actions"][0]["label"]


def test_explicit_system_launch_commands_keep_separate_targets() -> None:
    cases = {
        "启动港口数字孪生": ("launch_port_digital_twin", "port-dt-multi"),
        "启动孪生": ("launch_port_digital_twin", "port-dt-multi"),
        "启动能碳驾驶舱": ("launch_energy_cockpit", "energy-cockpit"),
        "启动能碳": ("launch_energy_cockpit", "energy-cockpit"),
        "启动马六甲推演": ("launch_malacca_sandbox", "malacca-sandbox"),
        "启动沙盘": ("launch_malacca_sandbox", "malacca-sandbox"),
    }

    for command, (intent, target) in cases.items():
        response = client.post("/api/automation/plans", json={"command": command})
        assert response.status_code == 201
        plan = response.json()
        assert plan["intent"] == intent
        assert [action["kind"] for action in plan["actions"]] == [
            "check_linked_system_runtime",
            "launch_linked_system_runtime",
            "verify_linked_system_runtime",
            "open_linked_system_runtime",
        ]
        assert all(action["parameters"]["target"] == target for action in plan["actions"])


def test_live_write_action_requires_confirmation() -> None:
    created = client.post(
        "/api/automation/plans",
        json={"command": "把3号泊位计划修改后下发"},
    )
    assert created.status_code == 201
    plan = created.json()
    risky = next(action for action in plan["actions"] if action["kind"] == "propose_live_action")
    assert risky["kind"] == "propose_live_action"
    assert risky["risk_level"] == "high"
    assert risky["requires_confirmation"] is True

    first = None
    for detail in ["已打开任务中心", "接口状态已核验", "影响与回滚检查完成"]:
        first = client.post(
            f"/api/automation/plans/{plan['id']}/next",
            json={"outcome": "success", "detail": detail},
        )
        assert first.status_code == 200
    assert first is not None
    assert first.json()["plan"]["status"] == "awaiting_confirmation"

    blocked = client.post(
        f"/api/automation/plans/{plan['id']}/next",
        json={"outcome": "success", "detail": "不应执行"},
    )
    assert blocked.status_code == 409

    confirmed = client.post(
        f"/api/automation/plans/{plan['id']}/confirm",
        json={"action_id": risky["id"], "confirmed": True, "operator": "测试管理员"},
    )
    assert confirmed.status_code == 200
    assert risky["id"] in confirmed.json()["confirmed_action_ids"]


def test_plan_advances_and_preserves_audit_trail() -> None:
    created = client.post("/api/automation/plans", json={"command": "打开对话历史"}).json()
    payload = None
    for detail in ["历史面板已打开", "历史记录已核验", "操作结果已交付"]:
        result = client.post(
            f"/api/automation/plans/{created['id']}/next",
            json={"outcome": "success", "detail": detail},
        )
        assert result.status_code == 200
        payload = result.json()
    assert payload is not None
    assert payload["plan"]["status"] == "completed"
    assert all(action["status"] == "completed" for action in payload["plan"]["actions"])
    assert len(payload["plan"]["audit_trail"]) >= 4


def test_energy_report_command_keeps_requested_range_in_sequence() -> None:
    plan = client.post(
        "/api/automation/plans",
        json={"command": "打开最近30日能耗趋势并生成报告"},
    ).json()

    assert [action["kind"] for action in plan["actions"]] == [
        "navigate",
        "set_range",
        "inspect_metrics",
        "generate_report",
        "validate_report",
        "present_report",
    ]
    assert plan["actions"][1]["parameters"]["range"] == "30d"
    assert plan["actions"][3]["parameters"]["range"] == "30d"


def test_connector_center_command_uses_whitelisted_panel_action() -> None:
    plan = client.post(
        "/api/automation/plans",
        json={"command": "帮我打开真实港口接口中心"},
    ).json()

    assert plan["intent"] == "show_connectors"
    assert plan["actions"][0]["kind"] == "open_panel"
    assert plan["actions"][0]["parameters"] == {"panel": "connectors"}


def test_knowledge_search_command_builds_end_to_end_answer_delivery() -> None:
    plan = client.post(
        "/api/automation/plans",
        json={"command": "帮我在知识库中搜索岸电安全操作规程。"},
    ).json()

    assert plan["intent"] == "search_knowledge"
    assert [action["kind"] for action in plan["actions"]] == [
        "navigate",
        "inspect_knowledge",
        "filter_knowledge",
        "verify_sources",
        "set_mode",
        "ask",
        "validate_answer",
        "present_result",
    ]
    assert plan["actions"][-1]["phase"] == "交付"
