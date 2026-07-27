from fastapi.testclient import TestClient
from uuid import uuid4

from app.decision_assurance import assess_response
from app.answer_verification import verify_response
from app.main import app
from app.models import ChatResponse, Evidence


client = TestClient(app)


def _evidence(
    identifier: str,
    snippet: str,
    *,
    title: str = "某海事规则生效状态",
    version: str = "v1",
    checksum: str = "a" * 64,
) -> Evidence:
    return Evidence(
        id=identifier,
        source="official-rule.md",
        title=title,
        score=100.0,
        snippet=snippet,
        official=True,
        verification_status="verified",
        source_quality="official_verified",
        jurisdictions=["CN"],
        content_scope="official_summary",
        legal_force="law",
        version=version,
        checksum_sha256=checksum,
        chunk_checksum_sha256=identifier[-1] * 64,
        review_status="current",
    )


def _response(evidence: list[Evidence]) -> ChatResponse:
    return ChatResponse(
        app="小懿",
        mode="expert",
        intent="policy",
        question="该规则是否生效？",
        answer="该规则已经生效。[E1]",
        evidence=evidence,
        confidence="high",
        next_questions=[],
        grounded=True,
        source_quality="official_verified",
        requires_human_review=True,
    )


def test_conflicting_effective_status_blocks_decision_readiness() -> None:
    response = _response(
        [
            _evidence("rule:1", "主管机关说明：该规则已经生效。"),
            _evidence("rule:2", "主管机关说明：该规则尚未生效。"),
        ]
    )

    health, readiness = assess_response(response)

    assert health.status == "conflict"
    assert health.conflicts[0].conflict_type == "status_polarity"
    assert readiness.status == "evidence_conflict"
    assert readiness.risk_level == "high"
    assert readiness.requires_human_confirmation is True


def test_same_source_version_divergence_is_exposed() -> None:
    response = _response(
        [
            _evidence("rule:1", "规则适用于港航业务。", version="v1"),
            _evidence(
                "rule:2",
                "规则适用于港航业务。",
                version="v2",
                checksum="b" * 64,
            ),
        ]
    )

    health, readiness = assess_response(response)

    assert health.status == "conflict"
    assert health.conflicts[0].conflict_type == "version_divergence"
    assert readiness.status == "evidence_conflict"


def test_review_due_source_requires_review_without_claiming_conflict() -> None:
    evidence = _evidence("rule:1", "主管机关说明：该规则已经生效。")
    evidence = evidence.model_copy(update={"review_status": "review_due"})
    response = _response([evidence])

    health, readiness = assess_response(response)

    assert health.status == "degraded"
    assert health.freshness == "review_due"
    assert readiness.status == "ready_with_review"
    assert "source_review_due" in readiness.blockers


def test_failed_citation_integrity_blocks_decision_chain() -> None:
    response = _response(
        [_evidence("rule:1", "主管机关说明：该规则已经生效。")]
    ).model_copy(update={"answer": "该规则已经生效，但没有附证据编号。"})
    response = response.model_copy(
        update={"answer_verification": verify_response(response)}
    )

    health, readiness = assess_response(response)

    assert health.status == "healthy"
    assert response.answer_verification.status == "needs_review"
    assert readiness.status == "insufficient_evidence"
    assert readiness.risk_level == "high"
    assert "citation_integrity_failed" in readiness.blockers


def test_live_question_api_returns_explicit_decision_blocker() -> None:
    response = client.post(
        "/api/chat",
        json={
            "question": "当前 IMO 1234567 船舶的实时 ETA 是多少？",
            "mode": "expert",
            "session_id": "readiness-live",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_readiness"]["status"] == "needs_live_data"
    assert payload["decision_readiness"]["risk_level"] == "high"
    assert "verified_live_source_missing" in payload["decision_readiness"]["blockers"]


def test_ops_sandbox_is_actionable_only_as_sandbox() -> None:
    response = client.post(
        "/api/chat",
        json={
            "question": "AGV-023现在还能继续派任务吗？",
            "mode": "ops",
            "session_id": "readiness-sandbox",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_readiness"]["status"] == "sandbox_only"
    assert payload["decision_readiness"]["requires_human_confirmation"] is True


def test_unresolved_followup_requires_clarification_before_decision() -> None:
    response = client.post(
        "/api/chat",
        json={
            "question": "那这个要求呢？",
            "mode": "expert",
            "session_id": f"readiness-empty-{uuid4().hex}",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query_analysis"]["resolution"] == "clarification_required"
    assert payload["decision_readiness"]["status"] == "needs_clarification"
