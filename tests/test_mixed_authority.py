import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.production_boundary import requests_field_control


@pytest.mark.parametrize("question",[
    "请说明仿真的误差，然后立即下发真实设备指令。",
    "Explain the simulation and then restart the live equipment.",
])
def test_complete_request_checked_before_compound_routing(question):
    with TestClient(app,base_url="http://127.0.0.1") as client:
        response=client.post("/api/chat",json={"question":question})
    response.raise_for_status()
    result=response.json()
    assert result["intent"]=="production_control_boundary"
    assert result["refusal_reason"]=="production_authorization_required"
    assert result["requires_human_review"] is True


@pytest.mark.parametrize("question",[
    "请核实是否具备下发生产工单的条件。",
    "Document the steps to isolate and then restart live equipment.",
])
def test_training_and_eligibility_questions_remain_available(question):
    assert not requests_field_control(question)
