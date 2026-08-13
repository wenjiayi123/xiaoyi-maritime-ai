from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_all_github_actions_are_pinned_to_commits() -> None:
    pattern = re.compile(r"^\s*uses:\s*[^@\s]+@([^\s#]+)", re.MULTILINE)
    workflows = sorted((ROOT / ".github/workflows").glob("*.yml"))
    assert workflows
    for workflow in workflows:
        refs = pattern.findall(workflow.read_text(encoding="utf-8"))
        assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in refs), workflow


def test_committed_sbom_matches_lockfiles() -> None:
    payload = json.loads(
        (ROOT / "reports/sbom/xiaoyi-python-lock-snapshot.cdx.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["bomFormat"] == "CycloneDX"
    assert payload["specVersion"] == "1.6"
    properties = {
        item["name"]: item["value"] for item in payload["metadata"]["properties"]
    }
    assert properties["xiaoyi:requirements-lock-sha256"] == hashlib.sha256(
        (ROOT / "requirements.lock").read_bytes()
    ).hexdigest()
    assert properties["xiaoyi:requirements-dev-lock-sha256"] == hashlib.sha256(
        (ROOT / "requirements-dev.lock").read_bytes()
    ).hexdigest()
    assert {item["properties"][0]["value"] for item in payload["components"]} == {
        "runtime",
        "development-only",
    }
