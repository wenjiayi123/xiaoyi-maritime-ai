"""Current risk, forcing, availability and capability score evidence; read only."""

import copy
import hashlib
import json
from pathlib import Path

from app.config import BASE_DIR
from app.harness import remediation_v3 as previous

REGISTRY = BASE_DIR / "config/remediation_v4_evidence_registry.json"


def report():
    try:
        return _report()
    except ValueError:
        raise
    except (OSError, KeyError, TypeError) as exc:
        raise ValueError("最新证据缺失或格式不完整，停止采信并保留历史结果") from exc


def _report():
    if not REGISTRY.is_file():
        raise ValueError("最新风险复验与能力评分尚在封存中，先前证据继续保留")
    registry = json.loads(REGISTRY.read_text())
    if registry.get("schema") != "xiaoyi-remediation-evidence.v4":
        raise ValueError("最新证据登记版本不支持")
    values = {name: json.loads(previous.checked(e["path"], e["sha256"]).read_text()) for name, e in registry["reports"].items()}
    legacy = previous.report()
    learning, physical, quality = [values[k] for k in ["learning", "physical", "quality"]]
    selection = learning["selection"]
    files = dict(quality["source_sha256"])
    files.update(selection["base_source_hashes"])
    files.update({"app/harness/robust_v4.py": selection["source_sha256"],
        "app/harness/modelbased_v3.py": selection["previous_mpc_implementation_sha256"],
        "app/harness/forced_twin_v4.py": physical["selection"]["source_sha256"],
        "app/harness/physical_v3.py": physical["selection"]["prior_implementation_sha256"],
        "data/public/portwatch_v4_20261030/protocol.json": selection["protocol_sha256"],
        "data/public/forecast_forcing_v4_20261030/protocol.json": physical["selection"]["protocol_sha256"],
        "data/public/forecast_forcing_v4_20261030/manifest.json": physical["selection"]["manifest_sha256"]})
    for study in [learning, physical]:
        files[study["trace_path"]] = study["trace_sha256"]
    files[learning["historical_shadow_path"]] = learning["historical_shadow_sha256"]
    files[".runtime/robust-v4-20261030/selection-before-test.json"] = learning["selection_sha256"]
    files["data/public/forecast_forcing_v4_20261030/selection-before-test.json"] = physical["selection_sha256"]
    files[".runtime/robust-v4-20261030/empirical-transition-model.json"] = selection["empirical_model_sha256"]
    for meta in selection["models"]:
        files[meta["path"]] = meta["sha256"]
    for source in [learning["sources"], physical["sources"], values["availability"]]:
        for entry in source["entries"]:
            files[entry["path"]] = entry["sha256"]
    issues = [p for p, expected in files.items() if not (BASE_DIR / p).is_file() or previous.digest(BASE_DIR / p) != expected]
    if json.loads((BASE_DIR / "data/public/portwatch_v4_20261030/manifest.json").read_text()) != learning["sources"]:
        issues.append("new port manifest mismatch")
    # Adding previously untested code invalidates a whole-repository claim too.
    tracked = {p for p in quality["source_sha256"] if p.startswith(("app/", "scripts/", "tests/", "web/"))}
    present = set()
    for folder, suffixes in [("app", {".py"}), ("scripts", {".py", ".cjs"}), ("tests", {".py", ".js"}), ("web", {".js", ".css", ".html"})]:
        present.update(str(p.relative_to(BASE_DIR)) for p in (BASE_DIR / folder).rglob("*")
                       if p.is_file() and p.suffix in suffixes and "__pycache__" not in p.parts)
    if present != tracked:
        issues.append("whole repository file inventory changed")
    docker_entry = registry.get("container")
    docker = json.loads(previous.checked(docker_entry["path"], docker_entry["sha256"]).read_text()) if docker_entry else {
        "passed": False, "status": "等待当前镜像的外部实建回执", "production_authority": False}
    docker["current"] = bool(docker.get("passed")) and bool(docker.get("source_sha256")) and all(
        (BASE_DIR / p).is_file() and previous.digest(BASE_DIR / p) == h for p, h in docker.get("source_sha256", {}).items())
    current = not issues and legacy["current"]
    return {"schema": "xiaoyi-current-capability-assurance.v4", "registry": registry, "current": current,
        "validation_issues": issues, **values, "docker": docker,
        "legacy_summary": {"long_passed": legacy["physical"]["long_passed"], "long_total": legacy["physical"]["long_total"],
            "short_passed": legacy["physical"]["short_passed"], "short_total": legacy["physical"]["short_total"],
            "prior_forecast_passed": 20, "prior_forecast_total": 20,
            "operational_cases": len(legacy["operations"]["cases"]), "engineering_passed": legacy["operations"]["engineering_passed"],
            "field_evidence": legacy["operations"]["field_evidence"]},
        "production_authority": False,
        "notice": "本轮20港开发、另八港新留出；共同安全过滤器的收益与RL收益分开。原年度、短期和新七日天气强迫模式分别报告；真实缺测不填成真值。能力分数为公开尺度下的本次证据审视，不是第三方排名、行业认证或现场权限。"}


def enrich(base):
    if not REGISTRY.exists():
        return base
    data = report()
    result = copy.deepcopy(base)
    rows = {r["id"]: r for r in result["criteria"]}
    current = data["current"]
    learning, diagnosis, legacy = data["learning"], data["diagnostics"], data["legacy_summary"]
    chosen = next(r for r in learning["aggregate"] if r["algorithm"] == learning["selection"]["selected_rl"])

    def update(code, passed, evidence, remaining):
        rows[code].update(passed=bool(passed), status="所列研究检查通过" if passed else "未通过或待证明",
                          evidence=evidence, remaining=remaining)

    update("P01", current, "新增八港及逐次初始化天气预报归档，水位、模式、时间、单位和最新缺测核查均绑定；累计28港研究队列分批保留。",
           "港口活动为AIS衍生量；天气为模式输出。历史版本、发布时刻与本地传感器可用性假设不可混同实测。")
    update("P02", current, "20个已看过港口仅作开发；另外八港16个90天新窗口，2025选型后才评分；七日气象强迫另用新7月窗口。",
           "所有已评分港口/时期均不再作为未来未查看留出；同源宏观冲击和有限港口簇限制置信推断。")
    update("P03", current and chosen["research_admission"],
           f"历史4步违规回放降为{diagnosis['historical_four_step_new_violations']}；新港可行窗口违规{diagnosis['feasible_window_violations']}，与安全MPC动作差{diagnosis['action_mismatches_vs_safe_mpc']}；收益准入仍{chosen['research_admission']}。",
           f"全部违规{diagnosis['all_violations']}步与最大能力基线相同，限于代理容量不可行。过滤器干预与额外RL收益不能混算；逐港退化、集中收益和相对成本仍失败。")
    update("P04", current and data["independent"]["passed"],
           f"新增{len(learning['runs'])}次完整运行，115200帧；因果队列创新、过滤器、原始动作、成本和流量逐步复核。",
           "物理输入仍含代理容量与假定可观察队列；执行一致性不证明真实港口物理正确。")
    update("P05", current and data["forecast"]["passed"] == data["forecast"]["total"],
           f"20港训练/验证后冻结模型，新八港补充需求预测{data['forecast']['passed']}/{data['forecast']['total']}通过，先前20港结果保留。",
           "不同批次模型不混算为一个统一模型的准确率；预测检查未用于事后调整RL。")
    forced = data["physical"]["modes"]
    update("P06", current and rows["P06"]["passed"] and all(x["passed"] == x["total"] for x in forced.values()),
           f"原年度开环{legacy['long_passed']}/{legacy['long_total']}仍失败；新增无测试水位初始化的天气强迫七日{forced['no_test_water_initialization']['passed']}/{forced['no_test_water_initialization']['total']}，起始水位后开环七日另列。",
           "七日模式不替代年度资格；基线退化、区间覆盖、部分可用率及Fremantle无7月公开观测继续阻断。")
    update("P07", current and legacy["short_passed"] == legacy["short_total"],
           f"原短期{legacy['short_passed']}/{legacy['short_total']}；最新官方Fremantle归档仅到2026-06-30，7月合格小时为0，缺测原因和替代来源政策已封存。",
           "当年官方数据须另行申请；未提交外部请求，未拿邻站、月均或预报值代替同站小时真值。")
    for code in ["P08", "P09", "P10"]:
        rows[code]["passed"] = bool(rows[code]["passed"] and current)
        rows[code]["remaining"] += " 本轮缺测与气象强迫证据不替代现场签字、HIL或OT认证。"
    update("P11", current and data["quality"]["passed"] and data["docker"]["current"],
           data["quality"]["notice"] + "；" + data["docker"].get("status", "当前构建待验收"),
           "当前源码、数据、容器和回执分别封存；不包含现场生产授权。")
    result.update(schema="xiaoyi-leading-port-gap-assessment.v4", passed_items=sum(r["passed"] for r in result["criteria"]),
        top_port_full_acceptance=all(r["passed"] for r in result["criteria"]), production_authority=False,
        research_admission=chosen["research_admission"] and current, notice=data["notice"])
    return result


def compact_review(parent_digest):
    d = report()
    s, legacy = d["learning"]["selection"], d["legacy_summary"]
    return {"schema": d["schema"], "registry_sha256": hashlib.sha256((parent_digest + previous.digest(REGISTRY)).encode()).hexdigest(),
        "current": d["current"], "selected_rl": s["selected_rl"], "selected_baseline": s["selected_cost_mpc"],
        "aggregate": [{**r, "blockers": [k for k, v in r["checks"].items() if not v]} for r in d["learning"]["aggregate"]],
        "counts": {"ports": 8, "new_ports": 8, "test_windows": len(d["learning"]["windows"]), "excluded_windows": 0,
            "forecast_passed": d["forecast"]["passed"], "forecast_total": d["forecast"]["total"],
            "long_passed": legacy["long_passed"], "long_total": legacy["long_total"],
            "short_passed": legacy["short_passed"], "short_total": legacy["short_total"], "operational_cases": legacy["operational_cases"]},
        "diagnostics": d["diagnostics"], "weekly_forcing": d["physical"]["modes"],
        "capability_scores": [{"name": r["name"], "score": r["score"], "boundary": r["boundary"]} for r in d["scorecard"]["components"]],
        "score_rubric": d["scorecard"]["rubric"],
        "quality_passed": d["quality"]["passed"] and d["docker"]["current"], "field_evidence": legacy["field_evidence"],
        "notice": d["notice"], "production_authority": False}
