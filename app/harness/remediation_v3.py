"""Live verification of immutable new-port experiments and engineering evidence."""

import copy
import hashlib
import json
from pathlib import Path

from app.config import BASE_DIR

REGISTRY = BASE_DIR / "config/remediation_v3_evidence_registry.json"
DOCKER = BASE_DIR / ".codex_artifacts/remediation-v3-20261030/container-acceptance.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked(path, expected):
    target = (BASE_DIR / path).resolve()
    if not target.is_relative_to(BASE_DIR.resolve()) or not target.is_file() or digest(target) != expected:
        raise ValueError("新留出证据缺失或变化：" + str(path))
    return target


def report():
    if not REGISTRY.is_file():
        raise ValueError("新一轮实验与验收尚在封存中；旧失败和结果继续保留")
    registry = json.loads(REGISTRY.read_text())
    values = {name: json.loads(checked(entry["path"], entry["sha256"]).read_text())
              for name, entry in registry["reports"].items()}
    learning, physical, ops, quality = [values[k] for k in ["learning", "physical", "operations", "quality"]]
    issues = []
    files = dict(quality["source_sha256"])
    selected = learning["selection"]
    files.update({"app/harness/modelbased_v3.py": selected["source_sha256"],
                  "app/harness/learning_v3.py": selected["ablation_source_sha256"],
                  "app/harness/physical_v3.py": physical["selection"]["implementation_sha256"],
                  "app/harness/operations_v3.py": ops["source_sha256"]})
    files.update(selected["base_source_hashes"])
    files[learning["sources"]["primary_export"]["path"]] = learning["sources"]["primary_export"]["sha256"]
    for study in [learning, physical]:
        files[study["trace_path"]] = study["trace_sha256"]
    files["data/public/portwatch_v3_20261030/protocol.json"] = selected["protocol_sha256"]
    files["data/public/physical_twin_v3_20261030/protocol.json"] = physical["selection"]["protocol_sha256"]
    files["data/public/physical_twin_v3_20261030/manifest.json"] = physical["selection"]["manifest_sha256"]
    files[".runtime/modelbased-v3-20261030/selection-before-test.json"] = learning["selection_sha256"]
    files["data/public/physical_twin_v3_20261030/selection-before-test.json"] = physical["selection_sha256"]
    files[".runtime/learning-v3-20261030/ablation-development.json"] = selected["ablation_report_sha256"]
    for meta in selected["models"] + learning["ablation"]["models"] + learning["ablation"]["replays"]:
        files[meta["path"]] = meta["sha256"]
    for replay in learning["ablation"]["replays"]:
        seed = Path(replay["path"]).stem.split("-")[-1]
        files[f".runtime/guided-rl-v2-20261030/models/dueling_imitation_only-{seed}.json"] = replay["initial_weight_sha256"]
    for source in [learning["sources"], physical["sources"], ops["sources"]["standards"]]:
        for entry in source["entries"]:
            files[entry["path"]] = entry["sha256"]
    # Bind source manifests to the report values, not just individually valid CSV files.
    if json.loads((BASE_DIR / "data/public/portwatch_v3_20261030/manifest.json").read_text()) != learning["sources"]:
        issues.append("new port manifest changed")
    if ops["sources"]["ports"] != learning["sources"]:
        issues.append("operations port source mismatch")
    for path, expected in files.items():
        if not (BASE_DIR / path).is_file() or digest(BASE_DIR / path) != expected:
            issues.append(path)
    for model in physical["selection"]["models"]:
        for candidate in model["candidates"]:
            if digest(BASE_DIR / candidate["coefficient_path"]) != candidate["coefficient_sha256"]:
                issues.append(candidate["coefficient_path"])
    docker_entry = registry.get("container")
    docker = json.loads(checked(docker_entry["path"], docker_entry["sha256"]).read_text()) if docker_entry else {
        "passed": False, "status": "external_container_receipt_not_packaged", "production_authority": False}
    docker["current"] = bool(docker.get("passed")) and bool(docker.get("source_sha256")) and all(
        (BASE_DIR / path).is_file() and digest(BASE_DIR / path) == expected
        for path, expected in docker.get("source_sha256", {}).items())
    return {"schema": "xiaoyi-six-gap-remediation.v3", "registry": registry, "current": not issues,
            "validation_issues": issues, **values, "docker": docker, "production_authority": False,
            "notice": "固定回放单因素消融、八个未看过的港口及新2026年3/6/9月水位留出。保留平均收益集中、港口退化、约束违规、缺测和长期标定失败。工程及公开回放不代替现场授权、HIL、正式互操作与SLA。"}


def enrich(base):
    if not REGISTRY.exists():
        return base
    data = report()
    result = copy.deepcopy(base)
    rows = {r["id"]: r for r in result["criteria"]}
    current = data["current"]
    learning, physical, ops = [data[k] for k in ["learning", "physical", "operations"]]

    def update(code, passed, evidence, remaining, engineering=None):
        rows[code].update(passed=bool(passed), status="所列研究检查通过" if passed else "未通过或待证明",
                          evidence=evidence, remaining=remaining)
        if engineering is not None:
            rows[code]["engineering_acceptance_passed"] = engineering

    chosen = next(r for r in learning["aggregate"] if r["algorithm"] == learning["selection"]["selected_rl"])
    update("P01", current, "新增八个整港留出、七个水位站新时段和DCSA PC2.0.0官方规范，原始文件与转换、模型及失败均可查。",
           "同一IMF归档版本，不冒充新供应商或现场遥测；延迟归档和假定发布时钟明确。")
    update("P02", current, f"先按2025开发选型封存，再评估八个从未拟合/评分的港口，共{len(learning['windows'])}个90天窗口；水位新时期先开发后测试。",
           "新港口共享宏观冲击；五种子是计算重复，不能当成独立港口样本。旧2026结果已视为看过。")
    update("P03", current and chosen["research_admission"],
           f"固定回放七条件×五种子；离线经验模型RL常态Score {chosen['test_score']:.6f}，强基线{learning['selection']['selected_baseline']}。",
           "平均优于MPC仍须通过港口簇区间、逐港退化与安全门禁；当前阻断：" + "、".join(k for k, v in chosen["checks"].items() if not v))
    update("P04", current and data["independent"]["passed"] and all(r["maximum_flow_error"] < 1e-8 for r in learning["runs"]),
           f"新增{len(learning['runs'])}次完整运行及全部逐步轨迹，独立输入、服务、成本及守恒回读。",
           "真实公开活动指标驱动代理队列，不证明现场吞吐、容量和设备参数已标定。")
    forecast = data["forecast"]
    update("P05", current and forecast["passed"] == forecast["total"] and base["criteria"][4]["passed"],
           f"旧12港研究保留；冻结模型与区间不重拟合，新八港补充核查{forecast['passed']}/{forecast['total']}通过。",
           "新八港预测检查为补充验证，未用于RL选型；发布时刻与修订历史仍未知，单元通过数不是预测准确率。")
    update("P06", current and physical["long_passed"] == physical["long_total"],
           f"两年天文拟合、分离的偏差开发/选型/区间标定，新留出长期开环{physical['long_passed']}/{physical['long_total']}。",
           "新增方法的长期泛化不佳；旧失败与新基线退化、区间失效、缺测全部保留，不改变阈值。")
    update("P07", current and physical["short_passed"] == physical["short_total"],
           f"短期因果残差与区间更新，新留出{physical['short_passed']}/{physical['short_total']}，所有可评价单元通过，缺测仍失败。",
           "归档数据不证明实时传感器可用性；缺测仍阻断整体资格，未通过单元不得删掉。")
    field = ops["field_evidence"]
    engineering = current and ops["engineering_passed"]
    update("P08", engineering and field["equipment_and_energy_calibration_received"] and field["bathymetry_and_vessel_parameters_received"],
           f"新增{len(ops['cases'])}个新港情景，原子全工单预留与可靠供电约束；服务、能源和暂缓逐项保留。",
           "合成工单与设备/功率假设不等于现场标定，未知UKC继续暂缓。", engineering)
    update("P09", engineering and field["port_msw_interoperability_signoff"] and field["ot_recovery_drill_received"],
           "按DCSA PC2.0.0官方OpenAPI子集及E-R-P-A语义测试；重复、冲突、角色、时钟、乱序和网络分区拒绝，重新执行真实进程崩溃恢复。",
           "本地契约子集未经过官方沙箱或跨机构签收，也不是MSW或OT认证。", engineering)
    update("P10", engineering and all(field[k] for k in ["hardware_in_loop_received", "signed_port_dispatch_authorization", "live_shadow_sla_received"]),
           "本地故障演练在错误角色、网络分区、陈旧/未来时钟及状态不一致时不产生新生效事件；无现场权限。",
           "HIL、签字授权和真实影子/SLA证据仍缺。", engineering)
    update("P11", current and data["quality"]["passed"] and data["docker"]["current"],
           data["quality"]["notice"] + "；Docker：" + data["docker"].get("status", "待外部构建回执"),
           "容器回执须与当前源码指纹一致；构建与本地运行不授予现场生产放行。")
    result.update(schema="xiaoyi-leading-port-gap-assessment.v3", remediation_schema=data["schema"],
                  passed_items=sum(r["passed"] for r in result["criteria"]),
                  top_port_full_acceptance=all(r["passed"] for r in result["criteria"]),
                  research_admission=chosen["research_admission"] and current,
                  production_authority=False, notice=data["notice"])
    return result


def compact_review(parent_registry_digest):
    data = report()
    learning, physical, ops = [data[k] for k in ["learning", "physical", "operations"]]
    aggregate = [{**r, "blockers": [k for k, v in r["checks"].items() if not v]} for r in learning["aggregate"]]
    return {"schema": data["schema"], "registry_sha256": hashlib.sha256(
            (parent_registry_digest + digest(REGISTRY)).encode()).hexdigest(),
        "current": data["current"], "selected_rl": learning["selection"]["selected_rl"],
        "selected_baseline": learning["selection"]["selected_baseline"], "aggregate": aggregate,
        "ablation_paired": learning["ablation"]["paired"],
        "counts": {"ports": 8, "new_ports": 8, "test_windows": len(learning["windows"]),
            "excluded_windows": len(learning["excluded_windows"]),
            "forecast_passed": data["forecast"]["passed"] + data["forecast"]["prior_passed"],
            "forecast_total": data["forecast"]["total"] + data["forecast"]["prior_total"],
            "long_passed": physical["long_passed"], "long_total": physical["long_total"],
            "short_passed": physical["short_passed"], "short_total": physical["short_total"], "operational_cases": len(ops["cases"])},
        "forecast_scope": "prior12-port plus supplemental8-new-port validation without refitting or model selection",
        "field_evidence": ops["field_evidence"], "quality_passed": data["quality"]["passed"] and data["docker"]["current"],
        "registry": data["registry"], "notice": data["notice"], "production_authority": False}
