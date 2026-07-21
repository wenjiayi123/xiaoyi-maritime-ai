from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md", "LICENSE", "SECURITY.md", "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md",
    "CHANGELOG.md", "Dockerfile", "compose.yaml", "requirements.lock", "pyproject.toml",
    "CODE_OF_CONDUCT.md", "GOVERNANCE.md", "SUPPORT.md", "CITATION.cff",
    "VERSION", "RELEASE_CHECKLIST.md",
    ".github/workflows/ci.yml", ".github/workflows/dependency-review.yml",
    ".github/dependabot.yml", ".github/CODEOWNERS", "docs/DEPLOYMENT.md", "docs/ARCHITECTURE.md",
    "docs/OPEN_SOURCE_READINESS.md", "docs/assets/xiaoyi-console.png", "docs/assets/rl-lab.png",
    "docs/assets/social-preview.png",
)
EXCLUDED_PARTS = {
    ".git", ".venv", ".pytest_cache", ".ruff_cache", ".runtime", ".integrations", "__pycache__",
    "软著申请材料工作区", "rl_runs", "kb_pending",
}
SECRET_PATTERNS = (
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"ASIA[0-9A-Z]{16}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(rb"glpat-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
)
LOCAL_PATH_PATTERNS = (
    re.compile(rb"/" + rb"Users/[^/\s]+/"),
    re.compile(rb"/var/" + rb"folders/"),
    re.compile(rb"[A-Za-z]:\\\\" + rb"Users\\\\[^\\\s]+\\\\"),
)
FORBIDDEN_TRACKED_EXACT = {
    ".env", ".DS_Store", "录制台词.rtf", "港航小懿AI_国际化专业版_完整录制台词.md",
    "data/xiaoyi_index.json", "data/xiaoyi_runtime.db", "data/xiaoyi_runtime.db-shm", "data/xiaoyi_runtime.db-wal",
}
FORBIDDEN_TRACKED_PARTS = {".runtime", ".integrations", ".venv", "软著申请材料工作区", "__pycache__"}
FORBIDDEN_TRACKED_SUFFIXES = {".db", ".db-shm", ".db-wal", ".key", ".pem", ".p12"}


def _candidate_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path.name.startswith(".env") and path.name not in {".env.example", ".env.connectors.example"}:
            continue
        if path.stat().st_size <= 2_000_000:
            yield path


def _tracked_files() -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def _forbidden_tracked(relative: Path) -> bool:
    normalized = relative.as_posix()
    if normalized in FORBIDDEN_TRACKED_EXACT:
        return True
    if any(part in FORBIDDEN_TRACKED_PARTS for part in relative.parts):
        return True
    if any(normalized.endswith(suffix) for suffix in FORBIDDEN_TRACKED_SUFFIXES):
        return True
    if normalized.startswith("data/rl_runs/") and normalized != "data/rl_runs/.gitkeep":
        return True
    if normalized.startswith("data/kb_pending/") and normalized != "data/kb_pending/.gitkeep":
        return True
    return False


def main() -> int:
    errors: list[str] = []
    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            errors.append(f"缺少发布文件：{relative}")

    provenance_path = ROOT / "data/public/uci_appliances_energy.provenance.json"
    dataset_path = ROOT / "data/public/uci_appliances_energy.csv"
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        if provenance.get("derived_csv_sha256") != digest:
            errors.append("公开RL数据的派生SHA-256与血缘记录不一致")
        if "CC BY 4.0" not in str(provenance.get("license") or ""):
            errors.append("公开RL数据许可证声明不是CC BY 4.0")
        with dataset_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            required_columns = {"timestamp", "load_kw"}
            if not required_columns.issubset(reader.fieldnames or []):
                errors.append("公开RL数据缺少 timestamp 或 load_kw 必填列")
            row_count = sum(1 for _ in reader)
        if provenance.get("row_count") != row_count:
            errors.append("公开RL数据行数与血缘记录不一致")
    except (OSError, json.JSONDecodeError, csv.Error) as exc:
        errors.append(f"公开RL数据血缘不可验证：{exc}")

    try:
        registry = json.loads((ROOT / "data/source_registry.json").read_text(encoding="utf-8"))
        documents = registry.get("documents") or {}
        expected = registry.get("expected_document_count")
        kb_files = {path.name for path in (ROOT / "data/kb").glob("*.md")}
        if expected != len(documents) or set(documents) != kb_files:
            errors.append("知识来源登记数量、登记文件名与 data/kb 不一致")
        coverage = json.loads((ROOT / "data/authority_coverage.json").read_text(encoding="utf-8"))
        for section in coverage.get("sections") or []:
            for entry in section.get("entries") or []:
                missing = {
                    key for key in ("status", "priority", "jurisdictions", "local_artifacts", "official_url", "ingestion_policy", "update_frequency")
                    if key not in entry
                }
                if missing:
                    errors.append(f"权威覆盖条目 {entry.get('id', '<unknown>')} 缺少字段：{', '.join(sorted(missing))}")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"知识治理登记不可验证：{exc}")

    try:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        version_surfaces = {
            "app/config.py": f'APP_VERSION = "{version}"',
            "CITATION.cff": f"version: {version}",
            "compose.yaml": f"xiaoyi-ai:{version}",
            "Makefile": f"xiaoyi-ai:{version}",
            "README.md": f"version-{version}",
        }
        for relative, marker in version_surfaces.items():
            if marker not in (ROOT / relative).read_text(encoding="utf-8"):
                errors.append(f"版本号未同步：{relative}")
    except OSError as exc:
        errors.append(f"版本一致性不可验证：{exc}")

    for path in _tracked_files():
        relative = path.relative_to(ROOT)
        if _forbidden_tracked(relative):
            errors.append(f"禁止发布的本机或运行文件已被Git跟踪：{relative}")
        try:
            if path.stat().st_size > 10_000_000:
                errors.append(f"Git跟踪文件超过10MB发布门限：{relative}")
        except OSError:
            continue

    for path in _candidate_files():
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        if any(pattern.search(payload) for pattern in SECRET_PATTERNS):
            errors.append(f"疑似凭据进入发布候选：{path.relative_to(ROOT)}")
        if any(pattern.search(payload) for pattern in LOCAL_PATH_PATTERNS):
            errors.append(f"本机绝对路径进入发布候选：{path.relative_to(ROOT)}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("release-check: PASS")
    print("- required governance and deployment files present")
    print("- public dataset license, provenance hash, schema and row count verified")
    print("- knowledge registry and authority-coverage structure verified")
    print("- version markers and tracked-file hygiene verified")
    print("- no high-confidence credential or local-path patterns found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
