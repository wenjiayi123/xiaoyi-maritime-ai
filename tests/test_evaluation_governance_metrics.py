from app.evaluation import _retrieval_summary


def test_global_scope_is_not_miscounted_as_failed_local_routing() -> None:
    rows = [
        {
            "official_required": True,
            "official_pass": True,
            "official_top_k_precision": 1.0,
            "top_k_hash_complete": True,
            "expected_jurisdictions": ["GLOBAL"],
            "jurisdiction_pass": True,
            "category": "international",
            "hybrid_rank": 1,
        },
        {
            "official_required": True,
            "official_pass": True,
            "official_top_k_precision": 1.0,
            "top_k_hash_complete": True,
            "expected_jurisdictions": ["SG"],
            "jurisdiction_pass": True,
            "category": "singapore",
            "hybrid_rank": 2,
        },
    ]

    summary = _retrieval_summary(rows, "hybrid_rank")

    assert summary["jurisdiction_routing_case_count"] == 1
    assert summary["jurisdiction_routing_accuracy"] == 1.0
    assert summary["global_scope_case_count"] == 1
    assert summary["global_scope_neutrality_accuracy"] == 1.0
    assert summary["official_top_k_precision"] == 1.0
    assert summary["evidence_hash_completeness_rate"] == 1.0
