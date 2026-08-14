from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import capability_hub, domain_context, evaluation, governance, orchestrator
from app import knowledge_intake
from app.main import app
from app.runtime_store import RuntimeStore


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_runtime_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RuntimeStore:
    store = RuntimeStore(tmp_path / "runtime.db")
    for module in (capability_hub, domain_context, evaluation, governance, orchestrator):
        monkeypatch.setattr(module, "runtime_store", store)
    monkeypatch.setattr(knowledge_intake, "KB_PENDING_DIR", tmp_path / "kb_pending")
    return store


def test_priority_1_capability_registry_is_isolated_and_read_only() -> None:
    systems = client.get("/api/hub/systems").json()
    capabilities = client.get("/api/hub/capabilities").json()

    assert systems["total"] == 4
    assert systems["isolation_mode"] is True
    assert capabilities["total"] >= 11
    assert capabilities["read_only"] is True
    assert {item["id"] for item in systems["items"]} == {
        "port-dt-multi", "energy-cockpit", "malacca-sandbox", "sailing-simulator"
    }

    preview = client.post(
        "/api/hub/capabilities/energy_linkage_health/invoke",
        json={"dry_run": True, "actor_id": "tester", "actor_role": "analyst"},
    )
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["status"] == "preview"
    assert payload["external_request_performed"] is False


def test_priority_2_context_resolves_and_inherits_canonical_fields() -> None:
    first = client.post(
        "/api/context/resolve",
        json={"session_id": "demo-ctx", "question": "分析 CNYTN 泊位 3 未来3小时风险"},
    ).json()
    assert first["context"]["port_code"] == "CNYTN"
    assert first["context"]["berth_id"] == "3"
    assert first["context"]["time_range"] == "next_3h"

    second = client.post(
        "/api/context/resolve",
        json={"session_id": "demo-ctx", "question": "再看一下岸电情况"},
    ).json()
    assert second["context"]["port_code"] == "CNYTN"
    assert "port_code" in second["inherited_fields"]


def test_priority_3_fuses_knowledge_and_external_evidence_without_blurring_boundary() -> None:
    response = client.post(
        "/api/evidence/fuse",
        json={
            "query": "岸电安全操作规程",
            "external_evidence": [
                {
                    "source_type": "capability_contract",
                    "source_id": "preview-1",
                    "system_id": "energy-cockpit",
                    "capability_id": "energy_linkage_health",
                    "title": "能碳联动预览",
                    "payload": {"status": "preview"},
                    "verification_status": "preview_only"
                }
            ]
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["knowledge_count"] >= 1
    assert any(item["source_type"] == "capability_contract" for item in payload["evidence"])
    assert "不能作为已验证生产事实" in payload["boundary_notice"]


def test_client_cannot_self_attest_external_result_as_live_read() -> None:
    response = client.post(
        "/api/evidence/fuse",
        json={
            "query": "当前泊位状态",
            "include_knowledge": False,
            "external_evidence": [
                {
                    "source_type": "system_result",
                    "source_id": "spoofed-live-result",
                    "system_id": "untrusted-client",
                    "title": "客户端自报实时结果",
                    "payload": {"status": "all-clear"},
                    "verification_status": "live_read",
                    "fetched_at": "2026-07-15T00:00:00Z",
                    "correlation_id": "client-controlled",
                }
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["grounded"] is False
    assert payload["evidence"][0]["verification_status"] == "client_supplied"
    assert payload["evidence"][0]["source_quality"] == "unverified_external"


def test_evidence_fusion_does_not_treat_summary_as_clause_level_grounding() -> None:
    response = client.post(
        "/api/evidence/fuse",
        json={
            "query": "《港口危险货物安全管理规定》第三十五条原文是什么？",
            "include_knowledge": True,
            "top_k": 8,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["grounded"] is False
    assert payload["evidence_requirement"] == "official_full_text"
    assert payload["jurisdictions"] == ["CN"]
    assert payload["evidence"]
    assert all(item["citation_role"] == "locator_only" for item in payload["evidence"])


def test_priority_4_rag_returns_hybrid_scores_and_metadata_filters() -> None:
    response = client.post(
        "/api/knowledge/search",
        json={"query": "IMO 海事单一窗口 2024", "official_only": True, "top_k": 5},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["retrieval_method"] == "hybrid_sparse_v2"
    assert payload["hits"]
    assert all(item["official"] for item in payload["hits"])
    assert all(item["rerank_score"] >= item["semantic_score"] for item in payload["hits"])


def test_priority_5_orchestrator_routes_but_does_not_touch_other_systems() -> None:
    response = client.post(
        "/api/orchestrator/run",
        json={
            "command": "分析 CNYTN 未来3小时岸电风险，并告诉我去哪个系统看详情",
            "session_id": "orchestrator-demo",
            "execute_read_only": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "energy_linkage_health" in payload["selected_capabilities"]
    assert payload["handoff_links"]
    assert "调用预览" in payload["execution_boundary"]
    audit = client.get("/api/governance/audit").json()
    assert audit["persistent"] is True
    assert audit["total"] >= 1


def test_priority_6_permissions_deny_viewer_invoke() -> None:
    decision = client.post(
        "/api/governance/authorize",
        json={"actor_id": "viewer-01", "role": "viewer", "permission": "capability.invoke_read"},
    ).json()
    assert decision["authorized"] is False
    blocked = client.post(
        "/api/orchestrator/run",
        json={
            "command": "查看港区实时态势",
            "actor_id": "viewer-01",
            "actor_role": "viewer",
            "execute_read_only": True,
        },
    )
    assert blocked.status_code == 403


def test_priority_7_benchmark_and_feedback_review_loop(tmp_path: Path) -> None:
    benchmark = client.post("/api/evaluation/run", json={"top_k": 5})
    assert benchmark.status_code == 200
    payload = benchmark.json()
    assert payload["benchmark_count"] == 60
    assert payload["retrieval_method"] == "hybrid_sparse_v2"
    assert payload["retrieval"]["baseline_method"] == "bm25_only_v1"
    assert payload["retrieval_benchmark_count"] == 40
    assert payload["policy_benchmark_count"] == 20
    assert payload["verified_metrics"]["fixed_test_case_count"] == 35
    assert payload["verified_metrics"]["hybrid_hit_at_5"] == 1.0
    assert payload["verified_metrics"]["bm25_hit_at_5"] == 0.9583
    assert payload["verified_metrics"]["hit_at_5_lift_percentage_points"] == 4.17
    assert payload["retrieval"]["test"]["hybrid"]["hit_at_1"] == 1.0
    assert payload["retrieval"]["test"]["baseline"]["hit_at_1"] == 0.9583
    assert payload["verified_metrics"]["hybrid_mrr"] == 1.0
    assert payload["verified_metrics"]["bm25_mrr"] == 0.9583
    assert payload["verified_metrics"]["unsupported_answer_block_rate"] == 1.0
    assert payload["policy"]["test"]["temporal_applicability_accuracy"] == 1.0
    assert payload["policy"]["test"]["live_data_boundary_pass_rate"] == 1.0
    assert payload["policy_safety_pass_rate"] == 1.0
    assert payload["hit_at_k"] == 1.0
    assert payload["official_requirement_pass_rate"] == 1.0
    assert payload["passed"] is True

    created = client.post(
        "/api/evaluation/feedback",
        json={
            "question": "岸电告警怎么处理？",
            "rating": 2,
            "correction": "应先确认告警来源、时间和适用设备，再按现场SOP处置。",
            "evidence_ids": ["64_cn_port_ship_shore_power_rules.md"],
            "submitted_by": "tester",
        },
    )
    assert created.status_code == 201
    feedback_id = created.json()["id"]
    reviewed = client.post(
        f"/api/evaluation/feedback/{feedback_id}/review",
        json={"decision": "approve", "reviewed_by": "reviewer"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "submitted_to_knowledge_intake"
    assert reviewed.json()["intake_id"]
    assert list((tmp_path / "kb_pending").glob("*.json"))


def test_evaluation_summary_labels_committed_report_as_pinned_not_live() -> None:
    evaluation._LATEST_BENCHMARK = None
    payload = client.get("/api/evaluation/summary").json()
    benchmark = payload["latest_benchmark"]

    assert benchmark["status"] == "pinned_release_evidence"
    assert benchmark["evidence_source"] == "reports/maritime_rag_benchmark_v1_20260814_r3.json"
    assert benchmark["live_rerun"] is False
    assert benchmark["report_sha256"]
    assert benchmark["verified_metrics"]["fixed_test_case_count"] == 35
    assert "not untouched held-out data" in benchmark["required_qualifier"]
