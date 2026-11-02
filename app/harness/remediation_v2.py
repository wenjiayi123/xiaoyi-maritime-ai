"""Current eight-gap assessment combines independent research and bounded engineering evidence."""

import copy
import hashlib
import json
from pathlib import Path

from app.config import BASE_DIR

REGISTRY = BASE_DIR / "config/remediation_evidence_registry.json"


def verify_registered_reports():
    if not REGISTRY.exists():
        raise ValueError("新一轮尚未完成封存，请查看原研究与实际进度")
    registry = json.loads(REGISTRY.read_text())
    if registry.get("schema") != "xiaoyi-remediation-evidence.v2":
        raise ValueError("整改证据登记版本不支持")
    for name, entry in registry["reports"].items():
        path = (BASE_DIR / entry["path"]).resolve()
        if not path.is_relative_to(BASE_DIR.resolve()) or not path.is_file():
            raise ValueError("整改证据文件缺失或路径不受支持：" + name)
        if (
            not path.is_relative_to(BASE_DIR.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]
        ):
            raise ValueError("整改报告摘要变化，停止采信：" + name)
    return registry


def report():
    try:
        from app.harness import crossport_v2, guided_rl_v2, physical_v2, operations_v2
    except ImportError as exc:
        raise ValueError("研究依赖未就绪，请安装requirements-research.lock后重启服务") from exc

    registry = verify_registered_reports()
    port = crossport_v2.report()
    guided = guided_rl_v2.report()
    physical = physical_v2.report()
    # Primary rows/manifests were already verified by port.report and physical.report
    # above. Bind the operations snapshot to those exact manifests, avoiding a
    # second parse of 144k measured rows on every UI read. No persistent cache.
    operations = json.loads((BASE_DIR / registry["reports"]["operations"]["path"]).read_text())
    operations["historical_only"] = (
        hashlib.sha256(Path(operations_v2.__file__).read_bytes()).hexdigest() != operations["source_sha256"]
        or operations["sources"]["demand"] != port["sources"]
        or operations["sources"]["physical"] != physical["sources"]
    )
    path = BASE_DIR / registry["reports"]["quality"]["path"]
    quality = json.loads(path.read_text())
    quality["historical_only"] = any(
        not (BASE_DIR / name).exists() or hashlib.sha256((BASE_DIR / name).read_bytes()).hexdigest() != expected
        for name, expected in quality["source_sha256"].items()
    )
    aggregate = copy.deepcopy(port["aggregate"] + guided["aggregate"])
    selected = guided["selection"]["global_selected_rl"]
    for row in aggregate:
        row["checks"]["selected_on_validation"] = row["algorithm"] == selected
        row["blockers"] = [k for k, v in row["checks"].items() if not v]
        row["research_admission"] = all(row["checks"].values())
    current = not any(r["historical_only"] for r in [port, guided, physical, operations, quality])
    return {
        "schema": "xiaoyi-eight-gap-remediation.v2",
        "registry": registry,
        "current": current,
        "selected_rl": selected,
        "selected_baseline": port["selection"]["selected_baseline"],
        "aggregate": aggregate,
        "crossport": port,
        "guided": guided,
        "physical": physical,
        "operations": operations,
        "quality": quality,
        "production_authority": False,
        "notice": "先前2024—2025研究及全部失败继续保留。本轮新增国际港口、2026时期、天文潮汐年度拟合、明确的物理/协同/恢复工程检查；现场证据不足仍不予放行。",
    }


def enrich(base):
    if not REGISTRY.exists():
        return base
    value = report()
    result = copy.deepcopy(base)
    rows = {r["id"]: r for r in result["criteria"]}
    current = value["current"]
    port, physical, operations, quality = [value[k] for k in ["crossport", "physical", "operations", "quality"]]

    def update(code, passed, evidence, remaining, engineering=None):
        rows[code].update(
            passed=bool(passed),
            status="所列研究检查通过" if passed else "未通过或待证明",
            evidence=evidence,
            remaining=remaining,
        )
        if engineering is not None:
            rows[code]["engineering_acceptance_passed"] = engineering

    update(
        "P01",
        current,
        f"12港新队列，八个新增国际港口；六个水位站，三份国际UHSLC来源。各源、模型、轨迹和发布证据已绑定。当前版本有效：{current}。",
        "公开归档有修订与发布延迟，非现场遥测；UHSLC通常延后4—6周。",
    )
    update(
        "P02",
        current,
        f"2019—2024四港拟合、2025选型、2026新留出；实际完整窗口{len(port['test_windows'])}，因公开源缺失排除{len(port['excluded_test_windows'])}。",
        "源导出仅到2026-07-24，未补齐第三季度；允许目标港历史上下文，非零上下文零样本。",
    )
    update(
        "P03",
        current and any(r["research_admission"] for r in value["aggregate"]),
        f"整定PID、MPC3、MPC14及稳健MPC比较；最终强基线{value['selected_baseline']}，验证选定RL {value['selected_rl']}。模仿与RL单独报告。",
        "只有新时间与新港口都胜出且通过风险/退化门禁才准入；容量不可行继续阻断现场应用。",
    )
    update(
        "P04",
        current and all(r["maximum_flow_error"] < 1e-8 for r in port["runs"] + value["guided"]["runs"]),
        f"新研究共{len(port['runs']) + len(value['guided']['runs'])}次完整运行，全部轨迹保留并检查流量守恒。",
        "代理模型守恒不证明真实容量、设备或成本已标定。",
    )
    forecast = port["demand_forecast"]
    update(
        "P05",
        current and all(r["passed"] for r in forecast),
        f"新2026年{sum(r['passed'] for r in forecast)}/{len(forecast)}港通过；按过去波动缩放区间，并限制区间宽度。",
        "区间校准仅用2025验证数据；失败与历史14/16结果同时保留，发布时刻仍未知。",
    )
    update(
        "P06",
        current and physical["long_passed"] == physical["long_total"],
        f"年度拟合与天文节点修正，新2026长期开环{physical['long_passed']}/{physical['long_total']}单元通过。",
        "不删除缺测、基线回退或宽度失败；Fremantle补充2023真实训练观测，变更理由已封存。",
    )
    update(
        "P07",
        current and physical["short_passed"] == physical["short_total"],
        f"六站新2026短期同化{physical['short_passed']}/{physical['short_total']}单元通过；逐点时钟、单位和质量可查。",
        "小时国际站与六分钟NOAA分别验收；归档回放依赖假定的本地传感器可用性，非实时UHSLC预报。",
    )
    field = operations["field_evidence"]
    engineering = current and operations["engineering_passed"]
    update(
        "P08",
        engineering
        and field["equipment_and_energy_calibration_received"]
        and field["bathymetry_and_vessel_parameters_received"],
        f"{len(operations['cases'])}个同日公开需求驱动工程案例；资源、功率、储能守恒和SOC检查，未知UKC/碳因子暂缓。工程检查通过：{engineering}。",
        "设备/能耗、测深、船舶实测标定资料仍缺失；工程一致性不折算为全港物理通过。",
        engineering,
    )
    update(
        "P09",
        engineering and field["port_msw_interoperability_signoff"] and field["ot_recovery_drill_received"],
        "实际测试了重复消息、内容冲突、过期和乱序拒绝；独立子进程提交后崩溃，恢复不重复生效并检测审计篡改。",
        "本地规范化消息与角色演练不等于正式MSW/DCSA互操作、多机构事故演练或OT恢复认证。",
        engineering,
    )
    update(
        "P10",
        engineering
        and field["hardware_in_loop_received"]
        and field["signed_port_dispatch_authorization"]
        and field["live_shadow_sla_received"],
        f"生产指令拒绝、双角色演练及缺参数暂缓已执行；本地恢复耗时{operations['resilience']['local_recovery_seconds']:.6f}秒，非现场SLA。",
        "仍须硬件在环、真实授权和现场影子/SLA证据；保留production_authority=false。",
        engineering,
    )
    update(
        "P11",
        quality["passed"] and not quality["historical_only"],
        quality["notice"],
        "真实复跑报告通过登记表选取，旧报告未改写；未来修改需重新验证指纹及相关测试。",
    )
    result.update(
        schema="xiaoyi-leading-port-gap-assessment.v2",
        passed_items=sum(r["passed"] for r in result["criteria"]),
        top_port_full_acceptance=all(r["passed"] for r in result["criteria"]),
        repository_quality=quality,
        research_admission=any(r["research_admission"] for r in value["aggregate"]),
        remediation_schema=value["schema"],
        notice="当前八项整改证据已合并；工程测试、研究绩效和现场证据分别检查。保留全部历史失败及新留出失败，不授予行业或超级智能认证。",
    )
    return result


def compact_review():
    from app.harness import remediation_v3, remediation_v4, research_v6

    if remediation_v4.REGISTRY.exists():
        verify_registered_reports()
        combined = (
            hashlib.sha256(REGISTRY.read_bytes()).hexdigest()
            + hashlib.sha256(remediation_v3.REGISTRY.read_bytes()).hexdigest()
        )
        value = remediation_v4.compact_review(combined)
        if research_v6.REGISTRY.is_file():
            value["latest_research"] = research_v6.review_summary()
            value["registry_sha256"] = hashlib.sha256(
                (value["registry_sha256"] + hashlib.sha256(research_v6.REGISTRY.read_bytes()).hexdigest()).encode()
            ).hexdigest()
            value["current"] = value["current"] and value["latest_research"]["current"]
        return value

    if remediation_v3.REGISTRY.exists():
        verify_registered_reports()
        return remediation_v3.compact_review(hashlib.sha256(REGISTRY.read_bytes()).hexdigest())
    value = report()
    physical = value["physical"]
    return {
        "schema": value["schema"],
        "registry_sha256": hashlib.sha256(REGISTRY.read_bytes()).hexdigest(),
        "current": value["current"],
        "selected_rl": value["selected_rl"],
        "selected_baseline": value["selected_baseline"],
        "aggregate": value["aggregate"],
        "counts": {
            "ports": len(value["crossport"]["sources"]["entries"]),
            "new_ports": len(value["crossport"]["protocol"]["fresh_ports"]),
            "test_windows": len(value["crossport"]["test_windows"]),
            "excluded_windows": len(value["crossport"]["excluded_test_windows"]),
            "forecast_passed": sum(r["passed"] for r in value["crossport"]["demand_forecast"]),
            "forecast_total": len(value["crossport"]["demand_forecast"]),
            "long_passed": physical["long_passed"],
            "long_total": physical["long_total"],
            "short_passed": physical["short_passed"],
            "short_total": physical["short_total"],
            "operational_cases": len(value["operations"]["cases"]),
        },
        "demand_forecast": value["crossport"]["demand_forecast"],
        "physical_results": physical["results"],
        "physical_assumptions": physical["protocol"]["assumptions"],
        "engineering_checks": value["operations"]["checks"],
        "field_evidence": value["operations"]["field_evidence"],
        "operations_assumptions": value["operations"]["assumptions"],
        "quality_passed": value["quality"]["passed"] and not value["quality"]["historical_only"],
        "registry": value["registry"],
        "production_authority": False,
        "notice": value["notice"],
    }
