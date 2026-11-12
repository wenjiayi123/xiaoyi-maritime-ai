import io
import json
from dataclasses import replace

import pytest
from app.exercise_records import ExerciseRecord
from app.model_gateway import ModelGateway
from app.settings import settings
from app.models import ChatRequest


def local_gateway():
    return ModelGateway(replace(settings,model_provider="openai_compatible",model_name="local-test",
                                model_base_url="http://127.0.0.1:11435/v1"))


def record(facts="两台起重机各吊 3 箱。"):
    return ExerciseRecord(kind="general",scope="exercise",source="demo",facts=facts)


def response(model="local-test",content=None,finish="stop"):
    data={"model":model,"choices":[{"message":{"content":content,"reasoning_content":"private-scratch-test"},
          "finish_reason":finish}],"usage":{"completion_tokens":33}}
    return io.BytesIO(json.dumps(data).encode())


def test_reasoning_command_routes_supported_exercises_to_their_verifiers():
    value=ChatRequest(question="/演练推理 a\n事实：岸桥负荷 300 kW，并网限额 290 kW。\n问题：并网功率是多少 kW，能否满足上限？")
    assert value.exercise_record.kind=="power"
    plain=ChatRequest(question="/演练推理 a\n事实：每台吊 3 箱，共两台。\n问题：能否完成 4 箱？共吊多少箱？")
    assert plain.exercise_record.kind=="general"


def test_result_marks_model_estimate_and_never_returns_internal_reasoning(monkeypatch):
    gateway=local_gateway()
    def send(body,stream):
        assert body["chat_template_kwargs"]["enable_thinking"] and body["max_tokens"]==1024 and not stream
        assert "共吊多少箱" in body["messages"][-1]["content"]
        return response(content='{"source":"demo","decision":"ALLOW","value":6}')
    monkeypatch.setattr(gateway,"_send_completion",send)
    out=gateway.reason_about_exercise(record(),"共吊多少箱？")
    assert out["value"]==6 and out["verification"]=="model_estimate_only" and out["production_authority"] is False
    assert "private-scratch" not in json.dumps(out) and out["model"]=="local-test"


@pytest.mark.parametrize(("content","model","finish"),[
    ('{"source":"other","decision":"ALLOW","value":6}',"local-test","stop"),
    ('{"source":"demo","decision":"ALLOW","value":true}',"local-test","stop"),
    ('{"source":"demo","decision":"ALLOW","value":6}',"unexpected","stop"),
    ('{"source":"demo","decision":"ALLOW","value":6}',"local-test","length"),
    ("<think>unfinished","local-test","stop"),("","local-test","stop"),
])
def test_incomplete_or_wrong_identity_abstains(monkeypatch,content,model,finish):
    gateway=local_gateway()
    monkeypatch.setattr(gateway,"_send_completion",lambda *a,**kw:response(model=model,content=content,finish=finish))
    out=gateway.reason_about_exercise(record(),"共吊多少箱？")
    assert out["decision"]=="UNKNOWN" and out["value"] is None and not out["production_authority"]


def test_missing_values_nonlocal_endpoints_and_unavailable_service_abstain(monkeypatch):
    gateway=local_gateway()
    assert gateway.reason_about_exercise(record("记录没有任何观测。"),"多少箱？")["reason"]=="missing_quantities"
    external=ModelGateway(replace(gateway.settings,model_base_url="https://example.invalid/v1"))
    assert external.reason_about_exercise(record(),"多少箱？")["reason"]=="local_model_required"
    def down(*a,**kw):raise ConnectionError("unavailable")
    monkeypatch.setattr(gateway,"_send_completion",down)
    assert gateway.reason_about_exercise(record(),"多少箱？")["reason"]=="local_model_unavailable"
