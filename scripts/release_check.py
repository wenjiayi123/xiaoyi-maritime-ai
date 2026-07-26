from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md", "LICENSE", "SECURITY.md", "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md",
    "CHANGELOG.md", "Dockerfile", "compose.yaml", "requirements.lock", "pyproject.toml",
    "CODE_OF_CONDUCT.md", "GOVERNANCE.md", "SUPPORT.md", "CITATION.cff",
    ".github/workflows/ci.yml", ".github/workflows/dependency-review.yml",
    ".github/dependabot.yml", "docs/DEPLOYMENT.md", "docs/ARCHITECTURE.md",
    "docs/RESUME_CLAIMS.md", "data/evaluation/maritime_qa_benchmark_v1.json",
    "scripts/run_rag_benchmark.py", "reports/maritime_rag_benchmark_v1.json",
    "reports/maritime_rag_benchmark_v1.md", "web/index.html", "web/app.js",
    "docs/PORT_RL_DATA_CONTRACT.md", "docs/PORT_RL_LANDING_PLAN.md",
    "scripts/run_rl_dataset_benchmark.py", "reports/rl_dataset_benchmark_v1.json",
    "reports/rl_dataset_benchmark_v1.md",
    "docs/screenshots/rl-evidence-center.png",
    "docs/screenshots/rl-training-configuration.png",
    "docs/screenshots/rl-port-environment-contract.png",
    "docs/screenshots/xiaoyi-grounded-conversation.png",
)
EXCLUDED_PARTS = {
    ".git", ".venv", ".pytest_cache", "__pycache__",
    "软著申请材料工作区", "rl_runs",
}
SECRET_PATTERNS = (
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"sk-[A-Za-z0-9]{20,}"),
)


def _candidate_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path.name.startswith(".env") and path.name not in {".env.example", ".env.connectors.example"}:
            continue
        if path.stat().st_size <= 2_000_000:
            yield path


def main() -> int:
    errors: list[str] = []
    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            errors.append(f"缺少发布文件：{relative}")

    public_datasets = (
        ("uci_appliances_energy", 19735, "CC BY 4.0"),
        ("uci_household_power_5min", 409887, "CC BY 4.0"),
        ("noaa_la_lb_ais_2024_12_25_1min", 710, "U.S. Government"),
    )
    for dataset_id, expected_rows, license_marker in public_datasets:
        provenance_path = ROOT / "data/public" / f"{dataset_id}.provenance.json"
        dataset_path = ROOT / "data/public" / f"{dataset_id}.csv"
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
            if provenance.get("derived_csv_sha256") != digest:
                errors.append(f"公开RL数据的派生SHA-256与血缘记录不一致：{dataset_id}")
            if license_marker not in str(provenance.get("license") or ""):
                errors.append(f"公开RL数据许可证声明缺失：{dataset_id}")
            row_count = provenance.get("row_count", provenance.get("derived_rows"))
            if row_count != expected_rows:
                errors.append(f"公开RL数据行数变化：{dataset_id}")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"公开RL数据血缘不可验证：{dataset_id}: {exc}")

    benchmark_report_path = ROOT / "reports/maritime_rag_benchmark_v1.json"
    try:
        benchmark_report = json.loads(
            benchmark_report_path.read_text(encoding="utf-8")
        )
        evidence_hashes = benchmark_report["evidence_sha256"]
        for relative, expected_digest in evidence_hashes.items():
            evidence_path = ROOT / relative
            if not evidence_path.is_file():
                errors.append(f"RAG基准证据文件缺失：{relative}")
                continue
            if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != expected_digest:
                errors.append(f"RAG基准证据哈希已变化，请重新运行benchmark：{relative}")
        benchmark = benchmark_report["benchmark"]
        metrics = benchmark["resume_safe_metrics"]
        if metrics.get("fixed_case_count") != 60:
            errors.append("RAG固定评测题数不是60")
        if metrics.get("fixed_test_case_count") != 35:
            errors.append("RAG固定测试分区题数不是35")
        for field in (
            "official_top_k_precision",
            "evidence_hash_completeness_rate",
            "retrieval_jurisdiction_routing_accuracy",
            "global_scope_neutrality_accuracy",
        ):
            if metrics.get(field) != 1.0:
                errors.append(f"RAG证据治理门禁未通过：{field}")
        if not benchmark.get("passed"):
            errors.append("RAG固定评测发布门禁未通过")
    except (KeyError, OSError, json.JSONDecodeError) as exc:
        errors.append(f"RAG基准报告不可验证：{exc}")

    rl_report_path = ROOT / "reports/rl_dataset_benchmark_v1.json"
    try:
        rl_report = json.loads(rl_report_path.read_text(encoding="utf-8"))
        if not rl_report.get("passed"):
            errors.append("RL多数据集基准门禁未通过")
        configuration = rl_report["configuration"]
        if len(configuration.get("algorithms", [])) != 5:
            errors.append("RL基准不是4种RL加1种PID")
        if configuration.get("seed_count", 0) < 3:
            errors.append("RL基准随机种子少于3个")
        if configuration.get("training_render_mode") is not None:
            errors.append("RL基准训练阶段启用了渲染")
        for relative, expected_digest in rl_report["evidence_sha256"].items():
            evidence_path = ROOT / relative
            if not evidence_path.is_file():
                errors.append(f"RL基准证据文件缺失：{relative}")
                continue
            if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != expected_digest:
                errors.append(f"RL基准证据哈希已变化：{relative}")
    except (KeyError, OSError, json.JSONDecodeError) as exc:
        errors.append(f"RL基准报告不可验证：{exc}")

    try:
        web_html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        web_js = (ROOT / "web/app.js").read_text(encoding="utf-8")
        for marker in (
            "等待接入港口",
            "withoutUnverifiedOperationalValues",
            "未验证的沙箱或本地数据不会显示为现场实绩",
        ):
            if marker not in f"{web_html}\n{web_js}":
                errors.append(f"开源界面的港口接入边界缺失：{marker}")
        for marker in (
            'data-view="rl"',
            "rlCenterAlgorithmMatrix",
            "rlAdvisorFeed",
            "rlSystemLinkage",
            "/api/rl-lab/advisor",
        ):
            if marker not in f"{web_html}\n{web_js}":
                errors.append(f"训练中心前后端契约缺失：{marker}")
        if ">动态沙箱<" in web_html or ">运营沙箱<" in web_html:
            errors.append("开源首页仍把沙箱状态作为默认港口运营数据展示")
    except OSError as exc:
        errors.append(f"开源界面真实性门禁不可验证：{exc}")

    for path in _candidate_files():
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        if any(pattern.search(payload) for pattern in SECRET_PATTERNS):
            errors.append(f"疑似凭据进入发布候选：{path.relative_to(ROOT)}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("release-check: PASS")
    print("- required governance and deployment files present")
    print("- public dataset provenance hash verified")
    print("- fixed RAG benchmark report and evidence hashes verified")
    print("- fixed multi-dataset RL benchmark and evidence hashes verified")
    print("- no high-confidence credential patterns found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
