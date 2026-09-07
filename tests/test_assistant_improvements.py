"""Regression cases from the September functionality/latency/linkage audit."""
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main, system_linkage, vector_retrieval
from app.model_gateway import ModelGateway
from app.query_intelligence import build_query_analysis
from app.settings import Settings
from app.vector_retrieval import DenseVectorIndex, EmbeddingClient, _normalize
from app.answer_verification import verify_response
from app.xiaoyi import XiaoyiAI


def test_dated_decision_benchmark_requires_expired_source_review():
    from app.decision_evaluation import run_decision_benchmark

    result = run_decision_benchmark()
    assert result["evaluation_date"] == "2026-09-07"
    assert result["passed"] is True
    for row in result["query"]["rows"]:
        if row["id"] in {"ready-query-007", "ready-query-008", "ready-query-014"}:
            assert row["freshness"] == "review_due"
            assert "source_review_due" in row["blockers"]


def test_benchmark_evaluation_date_reaches_retrieval(tmp_path, monkeypatch):
    from datetime import date
    from app import decision_evaluation

    payload = json.loads(decision_evaluation.BENCHMARK_PATH.read_text())
    payload["evaluation_date"] = "2027-01-01"
    path = tmp_path / "dated.json"
    path.write_text(json.dumps(payload))
    observed = []
    monkeypatch.setattr(decision_evaluation, "_evaluate_query_cases", lambda cases, engine, as_of_date: observed.append(as_of_date) or [])
    result = decision_evaluation.run_decision_benchmark(path)
    assert observed == [date(2027, 1, 1)]
    assert result["evaluation_date"] == "2027-01-01"


def test_followups_keep_original_topic_and_latest_scope_across_four_turns():
    history = []
    for question in ["中国船舶到港报告的官方入口在哪里？", "那在新加坡呢？", "那在马来西亚呢？", "具体需要哪些材料？"]:
        plan = build_query_analysis(question, history=history)
        assert "船舶到港报告" in plan.standalone_question
        assert len(plan.subquestions) == 1
        history.insert(0, {"id": str(len(history)), "question": question, "response": {"query_analysis": plan.model_dump()}})
    assert "马来西亚" in plan.standalone_question
    assert "中国" not in plan.standalone_question
    assert "新加坡" not in plan.standalone_question
    assert len(plan.context_topic) < 100


def test_followup_keeps_two_actual_new_questions():
    plan = build_query_analysis("那具体怎么申请，同时需要哪些材料？", history=[{"question": "新加坡船舶到港报告如何办理？"}])
    assert len(plan.subquestions) == 2
    assert all("新加坡船舶到港报告" in question for question in plan.subquestions)


@pytest.mark.parametrize("question", ["另外，TOS 是什么？", "还有，岸电有什么作用？", "具体船舶靠泊流程是什么？"])
def test_explicit_new_subject_does_not_inherit_previous_topic(question):
    plan = build_query_analysis(question, history=[{"question": "船员交接班如何办理？"}])
    assert plan.resolution == "independent"
    assert plan.standalone_question == question


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/stream"])
def test_missing_context_skips_retrieval_and_generation_and_reports_timing(monkeypatch, path):
    def unexpected(*args, **kwargs):
        raise AssertionError("Unresolved context must not perform retrieval or generation")

    gateway = ModelGateway(replace(Settings.from_env(), model_provider="openai_compatible", model_base_url="http://127.0.0.1:11435/v1", model_name="test"))
    monkeypatch.setattr(main, "model_gateway", gateway)
    monkeypatch.setattr(main.engine, "ask", unexpected)
    monkeypatch.setattr(gateway, "_request", unexpected)
    monkeypatch.setattr(gateway, "_request_stream", unexpected)
    with TestClient(main.app) as client:
        result = client.post(path, json={"question": "那这个要求呢？", "session_id": "missing-context-audit"})
    assert result.status_code == 200
    if path.endswith("stream"):
        data = json.loads(result.text.split("event: done\ndata: ")[1].strip())
    else:
        data = result.json()
    assert data["refusal_reason"] == "business_object_required"
    assert data["query_analysis"]["context_topic"] == ""
    assert "请补充" in data["answer"]
    assert data["evidence"] == []
    assert data["generation_provider"] == "local_rules"
    assert data["generation_fallback"] is False
    timing = data["timing"]
    assert timing["total_ms"] >= timing["preparation_ms"]
    assert abs(timing["total_ms"] - sum(timing[k] for k in ["preparation_ms", "generation_ms", "verification_ms"])) < 0.01


def make_index(tmp_path):
    path = tmp_path / "vectors.json"
    path.write_text(json.dumps({"manifest": {"dimensions": 2}, "records": [
        {"chunk_id": "a", "content_hash": "hash-a", "vector": [1.0, 0.0]},
    ]}))
    return DenseVectorIndex(path, base_url="http://127.0.0.1:11436/v1", model="test", timeout_seconds=1)


def chunks(content_hash="hash-a"):
    return [SimpleNamespace(id="a", content_hash=content_hash)]


def test_embedding_cache_avoids_repeated_calls_but_checks_current_chunk_hash(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(EmbeddingClient, "embed", lambda self, texts, **kw: calls.append(texts) or [[1., 0.]])
    index = make_index(tmp_path)
    assert index.scores("泊位冲突", chunks()) == {"a": 1.0}
    assert index.scores("泊位冲突", chunks()) == {"a": 1.0}
    assert index.scores("泊位冲突", chunks("changed-hash")) == {}
    assert len(calls) == 1
    assert index.status()["query_cache_hits"] == 1
    assert all("泊位冲突" not in key for key in index._query_cache)


def test_embedding_failure_cools_down_then_recovers(tmp_path, monkeypatch):
    now = [1.]
    calls = []
    monkeypatch.setattr(vector_retrieval.time, "monotonic", lambda: now[0])
    def embed(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("secret upstream url")
        return [[1., 0.]]
    monkeypatch.setattr(EmbeddingClient, "embed", embed)
    index = make_index(tmp_path)
    assert index.scores("一", chunks()) == {}
    assert index.scores("二", chunks()) == {}
    assert len(calls) == 1
    assert index.status()["circuit_open"] is True
    assert "secret" not in json.dumps(index.status())
    now[0] += 31
    assert index.scores("二", chunks()) == {"a": 1.0}
    assert index.status()["circuit_open"] is False
    assert index.status()["last_error"] is None
    now[0] += 301
    index.scores("二", chunks())
    assert len(calls) == 3


def test_simultaneous_identical_queries_share_one_embedding_request(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def embed(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(2)
        return [[1., 0.]]
    monkeypatch.setattr(EmbeddingClient, "embed", embed)
    index = make_index(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(index.scores, "相同问题", chunks())
        assert entered.wait(2)
        second = pool.submit(index.scores, "相同问题", chunks())
        release.set()
        assert first.result() == second.result() == {"a": 1.0}
    assert len(calls) == 1


@pytest.mark.parametrize("vector", [[], [float("nan"), 0], [float("inf"), 0], [0., 0.]])
def test_invalid_embeddings_are_rejected(vector):
    with pytest.raises(ValueError):
        _normalize(vector)


def test_incompatible_embedding_dimension_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(EmbeddingClient, "embed", lambda *a, **kw: [[1., 0., 0.]])
    index = make_index(tmp_path)
    assert index.scores("问题", chunks()) == {}
    assert index.status()["last_error"] == "embedding_upstream_unavailable"


@pytest.mark.parametrize("url,local", [
    ("http://127.0.0.1:11435/v1", True), ("http://localhost:11435/v1", True),
    ("http://[::1]:11435/v1", True), ("http://localhost.attacker.test/v1", False),
    ("http://127.0.0.1.attacker.test/v1", False), ("http://localhost" + "@" + "attacker.test/v1", False),
    ("https://example.test/v1", False),
])
def test_model_locality_uses_exact_host(url, local):
    configuration = replace(Settings.from_env(), model_base_url=url)
    assert configuration.model_endpoint_is_local is local


@pytest.mark.parametrize("matched,status,missing,expected", [
    (False, "ready", [], "needs_clarification"),
    (True, "ready", ["vessel_id"], "needs_clarification"),
    (True, "blocked", [], "failed"), (True, None, [], "failed"),
    (True, "ready", [], "completed"),
])
def test_linkage_uses_actual_business_receipt(monkeypatch, matched, status, missing, expected):
    monkeypatch.setattr(system_linkage, "_runtime", lambda target: {"target": target, "running": True, "url": "http://127.0.0.1:8000/"})
    def request(method, url, **kwargs):
        if method == "POST":
            assert kwargs["payload"]["dry_run"] is True
            return {"ok": True, "matched": matched, "missing_parameters": missing,
                    "action": {"id": "open_rl_panel"}, "execution_result": {"status": status}}
        return {"ok": True}
    monkeypatch.setattr(system_linkage, "_local_json", request)
    result = system_linkage._execute_target("port-dt-multi", system_linkage.LinkageCommandRequest(target="port-dt-multi", command="打开强化学习面板", auto_start=False), "audit-trace")
    assert result["status"] == expected
    assert result["summary"]["execution_status"] == status
    assert result["production_write_enabled"] is False


def test_linkage_status_probes_are_independent(monkeypatch):
    barrier = threading.Barrier(4)
    def runtime(target):
        barrier.wait(timeout=3)
        return {"target": target, "running": target != "energy-cockpit"}
    monkeypatch.setattr(system_linkage, "_runtime", runtime)
    result = system_linkage.linkage_overview()
    assert result["online_count"] == 3
    assert result["all_ready"] is False
    assert all(item["error"] is None for item in result["systems"].values())


def test_truncated_upstream_stream_is_not_treated_as_completed(monkeypatch):
    gateway = ModelGateway(Settings.from_env())
    monkeypatch.setattr(gateway, "_open_request", lambda *a, **kw: io.BytesIO(b'data: {"choices":[{"delta":{"content":"unfinished"}}]}\n\n'))
    with pytest.raises(ValueError, match="提前中断"):
        list(gateway._request_stream("question", None))


def test_completed_upstream_stream_is_accepted(monkeypatch):
    gateway = ModelGateway(Settings.from_env())
    monkeypatch.setattr(gateway, "_open_request", lambda *a, **kw: io.BytesIO(b'data: {"choices":[{"delta":{"content":"complete"}}]}\n\ndata: [DONE]\n\n'))
    assert list(gateway._request_stream("question", None)) == ["complete"]


def test_local_linkage_transport_builds_a_real_http_request(monkeypatch):
    def open_request(request, *, timeout):
        assert request.get_method() == "POST"
        assert request.full_url == "http://127.0.0.1:8000/test"
        assert json.loads(request.data) == {"dry_run": True}
        return io.BytesIO(b'{"ok":true}')
    monkeypatch.setattr(system_linkage, "urlopen", open_request)
    assert system_linkage._local_json("POST", "http://127.0.0.1:8000/test", payload={"dry_run": True}) == {"ok": True}


def test_official_locator_returns_indexed_links_instead_of_scope_boilerplate():
    response = XiaoyiAI().ask("新加坡船舶到港报告的官方入口在哪里？", top_k=5)
    assert "https://www.mpa.gov.sg/port-marine-ops/arrivals-and-departures/vessels-arriving-in-singapore" in response.answer
    assert response.evidence[0].title == "来源定位"
    assert verify_response(response).status == "passed"
    gateway = ModelGateway(replace(Settings.from_env(), model_provider="openai_compatible", model_base_url="http://127.0.0.1:11435/v1", model_name="test"))
    result = gateway.enhance(response.question, response)
    assert result.generation_provider == "local_rules"
    assert result.generation_fallback is False
    assert result.answer == response.answer


@pytest.mark.parametrize("body", [{"choices": []}, {"choices": None}, {"choices": [{"message": "invalid"}]}])
def test_malformed_model_reply_becomes_safe_fallback(monkeypatch, body):
    gateway = ModelGateway(replace(Settings.from_env(), model_provider="openai_compatible", model_base_url="http://127.0.0.1:11435/v1", model_name="test", model_max_retries=0))
    monkeypatch.setattr(gateway, "_open_request", lambda *a, **kw: io.BytesIO(json.dumps(body).encode()))
    local = XiaoyiAI().ask("TOS 是什么？")
    result = gateway.enhance(local.question, local)
    assert result.generation_fallback is True
    assert result.answer == local.answer
