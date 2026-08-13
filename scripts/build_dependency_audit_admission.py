from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RAW_REPORTS = {
    "initial_runtime_failed": ROOT / "reports/dependency_audit_20260813.json",
    "fixed_runtime": ROOT / "reports/dependency_audit_20260813_fixed_runtime.json",
    "intermediate_dev_failed": ROOT / "reports/dependency_audit_20260813_fixed_dev.json",
    "fixed_dev_v2": ROOT / "reports/dependency_audit_20260813_fixed_dev_v2.json",
    "current_runtime_r2": ROOT / "reports/dependency_audit_20260813_r2_runtime.json",
    "current_dev_r2": ROOT / "reports/dependency_audit_20260813_r2_dev.json",
}
OUTPUT = ROOT / "reports/dependency_audit_admission_v2.json"
MARKDOWN = ROOT / "reports/dependency_audit_admission_v2.md"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _vulnerabilities(payload: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for dependency in payload.get("dependencies", []):
        for vulnerability in dependency.get("vulns") or []:
            findings.append(
                {
                    "package": str(dependency.get("name")),
                    "version": str(dependency.get("version")),
                    "id": str(vulnerability.get("id")),
                    "fix_versions": ",".join(vulnerability.get("fix_versions") or []),
                }
            )
    return findings


def build_payload() -> dict[str, Any]:
    stages: dict[str, Any] = {}
    evidence_hashes: dict[str, str] = {}
    for stage, path in RAW_REPORTS.items():
        findings = _vulnerabilities(_load(path))
        relative = str(path.relative_to(ROOT))
        evidence_hashes[relative] = _sha256(path)
        stages[stage] = {
            "report": relative,
            "known_vulnerability_count": len(findings),
            "affected_package_count": len({item["package"] for item in findings}),
            "findings": findings,
        }
    current_lock_hashes = {
        "requirements.lock": _sha256(ROOT / "requirements.lock"),
        "requirements-dev.lock": _sha256(ROOT / "requirements-dev.lock"),
    }
    identity = ":".join([*evidence_hashes.values(), *current_lock_hashes.values()])
    return {
        "schema_version": "xiaoyi.dependency-audit-admission.v2",
        "run_id": f"depaudit-v2-20260813-{hashlib.sha256(identity.encode()).hexdigest()[:12]}",
        "audit_tool": {"name": "pip-audit", "version": "2.9.0", "vulnerability_service": "PyPI"},
        "python_version": "3.12.13",
        "stages": stages,
        "current_lock_sha256": current_lock_hashes,
        "evidence_sha256": evidence_hashes,
        "admission_passed": (
            stages["current_runtime_r2"]["known_vulnerability_count"] == 0
            and stages["current_dev_r2"]["known_vulnerability_count"] == 0
        ),
        "production_security_certification": False,
        "boundary": (
            "A zero-known-vulnerability result is a point-in-time advisory-database scan, "
            "not proof that dependencies are vulnerability-free. Scheduled CI must rerun it."
        ),
    }


def _render_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _render_markdown(payload: dict[str, Any]) -> str:
    stages = payload["stages"]
    return "\n".join(
        [
            "# Dependency vulnerability admission v2",
            "",
            f"- Run ID: `{payload['run_id']}`",
            f"- Tool: pip-audit {payload['audit_tool']['version']} / {payload['audit_tool']['vulnerability_service']}",
            f"- Initial runtime: **{stages['initial_runtime_failed']['known_vulnerability_count']} findings** (retained failure evidence)",
            f"- Fixed runtime: **{stages['fixed_runtime']['known_vulnerability_count']} findings**",
            f"- Intermediate dev: **{stages['intermediate_dev_failed']['known_vulnerability_count']} finding** (retained failure evidence)",
            f"- Fixed dev v2: **{stages['fixed_dev_v2']['known_vulnerability_count']} findings**",
            f"- Current runtime r2: **{stages['current_runtime_r2']['known_vulnerability_count']} findings**",
            f"- Current dev r2: **{stages['current_dev_r2']['known_vulnerability_count']} findings**",
            f"- Admission: **{'PASS' if payload['admission_passed'] else 'BLOCKED'}**",
            "",
            payload["boundary"],
            "",
            "The initial runtime report found 7 advisories across Click, Starlette and python-dotenv. ",
            "The intermediate development report then found one pytest advisory. Lockfiles were regenerated ",
            "with Python 3.12. The current r2 reports rerun both lockfiles after the final code audit; ",
            "the full application test count is reported separately by the reproducible pytest command.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    args = parser.parse_args()
    payload = build_payload()
    rendered = _render_json(payload)
    if args.command == "build":
        OUTPUT.write_text(rendered, encoding="utf-8")
        MARKDOWN.write_text(_render_markdown(payload), encoding="utf-8")
        print(f"dependency admission: {'PASS' if payload['admission_passed'] else 'BLOCKED'} {payload['run_id']}")
        return 0 if payload["admission_passed"] else 1
    if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != rendered:
        print("dependency admission: FAIL (report is stale)", file=sys.stderr)
        return 1
    print(f"dependency admission: PASS {payload['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
