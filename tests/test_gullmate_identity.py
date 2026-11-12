import pytest
from fastapi.testclient import TestClient
from app.config import APP_NAME, GREETING
from app.main import app
from app.operator_assistant import normalize_operator_question


@pytest.mark.parametrize("question", ["小鸥", "小鸥，你好！", "你好，小鸥", "小鸥，你好", "Hello, GullMate"])
def test_nickname_greeting(question):
    response=TestClient(app).post("/api/chat",json={"question":question})
    assert response.status_code==200
    result=response.json()
    assert result["app"]==APP_NAME=="舷鸥 · GullMate"
    assert result["intent"]=="greeting"
    assert result["answer"]==GREETING
    assert result["question"]==question


@pytest.mark.parametrize("question", ["小鸥，岸电需要核验什么？","你好，小鸥，岸电需要核验什么？","GullMate, 岸电需要核验什么？"])
def test_address_preserves_business_question(question):
    assert normalize_operator_question(question)=="岸电需要核验什么？"
