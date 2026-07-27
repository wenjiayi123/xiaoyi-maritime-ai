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
    "docs/GENERATIVE_MODEL_STACK.md", "data/model_registry.json",
    "scripts/local_model.py", "scripts/build_lora_dataset.py",
    "scripts/build_vector_index.py", "app/vector_retrieval.py",
    "scripts/train_lora.py", "scripts/export_lora_gguf.py",
    "scripts/run_local_generation_probe.py",
    "scripts/run_rag_lora_probe.py",
    "scripts/run_dense_retrieval_probe.py",
    "requirements-lora.txt", "requirements-lora-intel-mac.lock",
    "data/finetuning/README.md",
    "reports/local_lora_inference_v2.json",
    "reports/local_rag_lora_e2e_v2.json",
    "reports/local_dense_retrieval_v1.json",
    "scripts/run_rag_benchmark.py", "reports/maritime_rag_benchmark_v1.json",
    "reports/maritime_rag_benchmark_v1.md",
    "data/evaluation/maritime_assistant_benchmark_v2.json",
    "scripts/run_assistant_benchmark.py",
    "reports/maritime_assistant_benchmark_v2.json",
    "reports/maritime_assistant_benchmark_v2.md",
    "data/evaluation/maritime_decision_readiness_benchmark_v3.json",
    "scripts/run_decision_benchmark.py",
    "reports/maritime_decision_readiness_benchmark_v3.json",
    "reports/maritime_decision_readiness_benchmark_v3.md",
    "data/evaluation/maritime_claim_alignment_benchmark_v4.json",
    "scripts/run_alignment_benchmark.py",
    "reports/maritime_claim_alignment_benchmark_v4.json",
    "reports/maritime_claim_alignment_benchmark_v4.md",
    "data/evaluation/maritime_daily_operations_benchmark_v5.json",
    "scripts/run_daily_operations_benchmark.py",
    "reports/maritime_daily_operations_benchmark_v5.json",
    "reports/maritime_daily_operations_benchmark_v5.md",
    "data/evaluation/port_question_universe_v1.json",
    "docs/PORT_QUESTION_UNIVERSE.md",
    "data/evaluation/maritime_question_universe_benchmark_v6.json",
    "scripts/build_port_question_universe.py",
    "scripts/run_question_universe_benchmark.py",
    "reports/maritime_question_universe_benchmark_v6.json",
    "reports/maritime_question_universe_benchmark_v6.md",
    "docs/TOP_TIER_MARITIME_ASSISTANT_ROADMAP.md",
    "web/index.html", "web/app.js",
    "docs/PORT_RL_DATA_CONTRACT.md", "docs/PORT_RL_LANDING_PLAN.md",
    "scripts/run_rl_dataset_benchmark.py", "reports/rl_dataset_benchmark_v1.json",
    "reports/rl_dataset_benchmark_v1.md",
    "docs/screenshots/rl-evidence-center.png",
    "docs/screenshots/rl-training-configuration.png",
    "docs/screenshots/rl-port-environment-contract.png",
    "docs/screenshots/xiaoyi-grounded-conversation.png",
)
EXCLUDED_PARTS = {
    ".git", ".venv", ".venv-lora", ".runtime", ".pytest_cache", "__pycache__",
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

    try:
        model_registry = json.loads(
            (ROOT / "data/model_registry.json").read_text(encoding="utf-8")
        )
        model_ids = {
            str(item.get("model_id")): item
            for item in model_registry.get("models", [])
        }
        selected_model = model_ids[model_registry["default_model_id"]]
        if selected_model.get("revision") in {None, "", "main"}:
            errors.append("本地生成模型未固定上游revision")
        if selected_model.get("license") != "Apache-2.0":
            errors.append("本地生成模型许可证不是Apache-2.0")
        if selected_model.get("sha256_env") != "XIAOYI_LOCAL_MODEL_SHA256":
            errors.append("本地生成模型缺少部署侧SHA-256环境变量契约")
        if selected_model.get("path_env") != "XIAOYI_LOCAL_MODEL_PATH":
            errors.append("本地生成模型缺少部署侧路径环境变量契约")
        if selected_model.get("download_url") or selected_model.get("license_url"):
            errors.append("公共模型清单不应内置权重供应商地址")
        if int(selected_model.get("expected_bytes", 0)) <= 0:
            errors.append("本地生成模型字节数清单无效")
        adapter_contract = model_registry["adapter_contract"]
        training_model = model_ids[model_registry["local_training_model_id"]]
        if adapter_contract.get("training_base") != training_model.get(
            "upstream_model"
        ):
            errors.append("LoRA训练基座与本地生成模型族不一致")
        if training_model.get("model_id") == selected_model.get("model_id"):
            errors.append("本机LoRA证明模型未与默认高质量生成模型明确分层")
        embedding_models = [
            item
            for item in model_ids.values()
            if item.get("role") == "local_dense_embedding"
        ]
        if len(embedding_models) != 1:
            errors.append("本地稠密向量模型清单不是1个")
        elif int(embedding_models[0].get("embedding_dimensions", 0)) != 1024:
            errors.append("本地稠密向量维度清单不是1024")
        runtime = model_registry["inference_runtime"]
        if not re.fullmatch(r"[0-9a-f]{64}", str(runtime.get("sha256", ""))):
            errors.append("llama.cpp运行时SHA-256清单无效")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"本地生成模型清单不可验证：{exc}")

    try:
        lora_report = json.loads(
            (ROOT / "reports/local_lora_inference_v2.json").read_text(
                encoding="utf-8"
            )
        )
        training = lora_report["training_summary"]
        if lora_report.get("status") != "completed" or lora_report.get(
            "profile"
        ) != "lora":
            errors.append("本机LoRA推理探针未完成")
        if training.get("status") != "completed":
            errors.append("本机LoRA训练报告未完成")
        if training["base_model"].get("model_id") != "xiaoyi-local-training-1.7b":
            errors.append("本机LoRA证据基座不是1.7B")
        if training["lora"].get("trainable_parameters") != 17_432_576:
            errors.append("本机LoRA可训练参数数目与固定证据不一致")
        if training["lora"].get("rank") != 16:
            errors.append("本机LoRA固定Rank不是16")
        if training["training"].get("max_steps") != 64:
            errors.append("本机LoRA固定工程步数不是64")
        if training["training"].get("final_validation_loss", 999) >= training[
            "training"
        ].get("initial_validation_loss", 0):
            errors.append("本机LoRA隔离验证loss未改善")
        if training["training"].get("final_test_loss", 999) >= training[
            "training"
        ].get("initial_test_loss", 0):
            errors.append("本机LoRA隔离测试loss未改善")
        if not lora_report["evidence"].get("lora_gguf"):
            errors.append("本机LoRA探针缺少GGUF适配器证据")
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"本机LoRA推理证据不可验证：{exc}")

    try:
        e2e_report = json.loads(
            (ROOT / "reports/local_rag_lora_e2e_v2.json").read_text(
                encoding="utf-8"
            )
        )
        response = e2e_report["response"]
        verification = response["answer_verification"]
        if e2e_report.get("status") != "completed":
            errors.append("RAG+LoRA端到端探针未完成")
        if response.get("generation_fallback") is not False:
            errors.append("RAG+LoRA端到端探针发生生成回退")
        if response.get("generation_model") != "xiaoyi-maritime-1.7b-lora":
            errors.append("RAG+LoRA端到端探针模型身份不一致")
        if response.get("grounded") is not True or verification.get(
            "status"
        ) != "passed":
            errors.append("RAG+LoRA端到端回答后门禁未通过")
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"RAG+LoRA端到端证据不可验证：{exc}")

    try:
        dense_report = json.loads(
            (ROOT / "reports/local_dense_retrieval_v1.json").read_text(
                encoding="utf-8"
            )
        )
        dense_status = dense_report["index_status"]
        if dense_report.get("status") != "completed":
            errors.append("本机稠密向量探针未完成")
        if dense_status.get("record_count") != 882:
            errors.append("本机稠密向量固定分块数不是882")
        if dense_status.get("dimensions") != 1024:
            errors.append("本机稠密向量维度不是1024")
        if not dense_report.get("top_results"):
            errors.append("本机稠密向量探针没有召回结果")
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"本机稠密向量证据不可验证：{exc}")

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
            "policy_safety_pass_rate",
            "unsupported_answer_block_rate",
            "jurisdiction_routing_accuracy",
            "temporal_applicability_accuracy",
            "live_data_boundary_pass_rate",
        ):
            if metrics.get(field) != 1.0:
                errors.append(f"RAG证据治理门禁未通过：{field}")
        if not benchmark.get("passed"):
            errors.append("RAG固定评测发布门禁未通过")
    except (KeyError, OSError, json.JSONDecodeError) as exc:
        errors.append(f"RAG基准报告不可验证：{exc}")

    assistant_report_path = ROOT / "reports/maritime_assistant_benchmark_v2.json"
    try:
        assistant_report = json.loads(
            assistant_report_path.read_text(encoding="utf-8")
        )
        for relative, expected_digest in assistant_report["evidence_sha256"].items():
            evidence_path = ROOT / relative
            if not evidence_path.is_file():
                errors.append(f"助手困难基准证据文件缺失：{relative}")
                continue
            if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != expected_digest:
                errors.append(f"助手困难基准证据哈希已变化，请重新运行benchmark：{relative}")
        assistant_benchmark = assistant_report["benchmark"]
        if assistant_benchmark.get("case_count") != 60:
            errors.append("助手困难基准题数不是60")
        if assistant_benchmark.get("combined_with_v1_case_count") != 120:
            errors.append("v1与v2固定基准合计题数不是120")
        for category in ("dialogue", "complex", "adversarial"):
            summary = assistant_benchmark[category]["summary"]
            if summary.get("case_count") != 20 or summary.get("pass_rate") != 1.0:
                errors.append(f"助手困难基准分类门禁未通过：{category}")
        if not assistant_benchmark.get("passed"):
            errors.append("助手困难基准发布门禁未通过")
    except (KeyError, OSError, json.JSONDecodeError) as exc:
        errors.append(f"助手困难基准报告不可验证：{exc}")

    decision_report_path = (
        ROOT / "reports/maritime_decision_readiness_benchmark_v3.json"
    )
    try:
        decision_report = json.loads(
            decision_report_path.read_text(encoding="utf-8")
        )
        for relative, expected_digest in decision_report["evidence_sha256"].items():
            evidence_path = ROOT / relative
            if not evidence_path.is_file():
                errors.append(f"决策保障基准证据文件缺失：{relative}")
                continue
            if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != expected_digest:
                errors.append(f"决策保障基准证据哈希已变化，请重新运行benchmark：{relative}")
        decision_benchmark = decision_report["benchmark"]
        if decision_benchmark.get("case_count") != 30:
            errors.append("决策保障基准题数不是30")
        if decision_benchmark.get("combined_case_count") != 150:
            errors.append("v1、v2与v3固定基准合计题数不是150")
        for category, expected_count in (("query", 14), ("assurance", 16)):
            summary = decision_benchmark[category]["summary"]
            if (
                summary.get("case_count") != expected_count
                or summary.get("pass_rate") != 1.0
            ):
                errors.append(f"决策保障基准分类门禁未通过：{category}")
        if not decision_benchmark.get("passed"):
            errors.append("决策保障固定基准发布门禁未通过")
    except (KeyError, OSError, json.JSONDecodeError) as exc:
        errors.append(f"决策保障基准报告不可验证：{exc}")

    alignment_report_path = (
        ROOT / "reports/maritime_claim_alignment_benchmark_v4.json"
    )
    try:
        alignment_report = json.loads(
            alignment_report_path.read_text(encoding="utf-8")
        )
        for relative, expected_digest in alignment_report[
            "evidence_sha256"
        ].items():
            evidence_path = ROOT / relative
            if not evidence_path.is_file():
                errors.append(f"主张证据对齐基准文件缺失：{relative}")
                continue
            if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != expected_digest:
                errors.append(
                    f"主张证据对齐基准哈希已变化，请重新运行benchmark：{relative}"
                )
        alignment_benchmark = alignment_report["benchmark"]
        if alignment_benchmark.get("case_count") != 20:
            errors.append("主张证据对齐基准题数不是20")
        if alignment_benchmark.get("combined_case_count") != 170:
            errors.append("v1、v2、v3与v4固定基准合计题数不是170")
        for category, expected_count in (
            ("citation", 6),
            ("alignment", 6),
            ("numeric", 8),
        ):
            summary = alignment_benchmark["categories"][category]["summary"]
            if (
                summary.get("case_count") != expected_count
                or summary.get("pass_rate") != 1.0
            ):
                errors.append(f"主张证据对齐分类门禁未通过：{category}")
        if not alignment_benchmark.get("passed"):
            errors.append("主张证据对齐固定基准发布门禁未通过")
    except (KeyError, OSError, json.JSONDecodeError) as exc:
        errors.append(f"主张证据对齐基准报告不可验证：{exc}")

    daily_report_path = (
        ROOT / "reports/maritime_daily_operations_benchmark_v5.json"
    )
    try:
        daily_report = json.loads(daily_report_path.read_text(encoding="utf-8"))
        for relative, expected_digest in daily_report["evidence_sha256"].items():
            evidence_path = ROOT / relative
            if not evidence_path.is_file():
                errors.append(f"日常问答基准文件缺失：{relative}")
                continue
            if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != expected_digest:
                errors.append(
                    f"日常问答基准哈希已变化，请重新运行benchmark：{relative}"
                )
        daily_benchmark = daily_report["benchmark"]
        if daily_benchmark.get("operational_case_count") != 60:
            errors.append("日常问答固定基准题数不是60")
        if daily_benchmark.get("boundary_case_count") != 3:
            errors.append("日常问答边界测试题数不是3")
        if daily_benchmark.get("combined_fixed_case_count") != 230:
            errors.append("v1至v5固定基准合计题数不是230")
        for category in (
            "documents",
            "energy",
            "equipment",
            "shift_coordination",
            "vessel_berth",
            "yard_gate",
        ):
            summary = daily_benchmark["categories"][category]
            if summary.get("case_count") != 10 or summary.get("pass_rate") != 1.0:
                errors.append(f"日常问答分类门禁未通过：{category}")
        if not daily_benchmark.get("passed"):
            errors.append("日常问答固定基准发布门禁未通过")
    except (KeyError, OSError, json.JSONDecodeError) as exc:
        errors.append(f"日常问答基准报告不可验证：{exc}")

    universe_report_path = (
        ROOT / "reports/maritime_question_universe_benchmark_v6.json"
    )
    try:
        universe_report = json.loads(
            universe_report_path.read_text(encoding="utf-8")
        )
        for relative, expected_digest in universe_report[
            "evidence_sha256"
        ].items():
            evidence_path = ROOT / relative
            if not evidence_path.is_file():
                errors.append(f"港口问题全集基准文件缺失：{relative}")
                continue
            if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != expected_digest:
                errors.append(
                    f"港口问题全集基准哈希已变化，请重新运行benchmark：{relative}"
                )
        universe_benchmark = universe_report["benchmark"]
        if universe_benchmark.get("operational_case_count") != 30:
            errors.append("港口问题全集固定基准题数不是30")
        if universe_benchmark.get("boundary_case_count") != 5:
            errors.append("港口问题全集边界测试题数不是5")
        if universe_benchmark.get("combined_fixed_case_count") != 260:
            errors.append("v1至v6固定基准合计题数不是260")
        domains = universe_benchmark.get("domains", {})
        if len(domains) != 15:
            errors.append("港口问题全集业务域不是15个")
        for domain, summary in domains.items():
            if summary.get("case_count") != 2 or summary.get("pass_rate") != 1.0:
                errors.append(f"港口问题全集分域门禁未通过：{domain}")
        if not universe_benchmark.get("passed"):
            errors.append("港口问题全集固定基准发布门禁未通过")
    except (KeyError, OSError, json.JSONDecodeError) as exc:
        errors.append(f"港口问题全集基准报告不可验证：{exc}")

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
        for marker in (
            "data.answer_verification",
            "主张词面对齐",
            "数字/日期/量值完整性",
        ):
            if marker not in web_js:
                errors.append(f"回答后证据门禁未在前端展示：{marker}")
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
    print("- fixed assistant challenge benchmark and evidence hashes verified")
    print("- fixed decision-assurance benchmark and evidence hashes verified")
    print("- fixed claim-evidence alignment benchmark and evidence hashes verified")
    print("- fixed daily-operations benchmark and evidence hashes verified")
    print("- fixed port-question-universe benchmark and evidence hashes verified")
    print("- fixed multi-dataset RL benchmark and evidence hashes verified")
    print("- no high-confidence credential patterns found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
