"""Evidence-based gap assessment, never an invented 'superintelligence certificate'."""

import hashlib
import json

from app.config import BASE_DIR

from app.harness import adaptive_twin, crossport

REFERENCES = [
    {
        "name": "MPA Maritime Digital Twin",
        "url": "https://www.mpa.gov.sg/maritime-singapore/innovation-and-r-d/maritime-digital-twin",
        "checked_on": "2026-10-30",
        "relevance": "历史与实时数据、可运行模型、先模拟后部署的共享决策环境",
    },
    {
        "name": "MPA 2026 competitiveness and operational excellence",
        "url": "https://www.mpa.gov.sg/media-centre/details/strengthening-maritime-competitiveness-and-operational-excellence",
        "checked_on": "2026-10-30",
        "published_on": "2026-03-04",
        "relevance": "公告提出服务协同、事件协调、交通/气象/无人机/油化学扩散模型、开发工具及JIT；试点计划不等于全部部署完成",
    },
    {
        "name": "IMO Maritime Single Window",
        "url": "https://www.imo.org/en/ourwork/facilitation/pages/maritimesinglewindow-default.aspx",
        "checked_on": "2026-10-30",
        "relevance": "船港政务电子信息互通方向；本项目公开历史回放不是单一窗口系统接入或合规认证",
    },
    {
        "name": "IMO Maritime Cyber Risk",
        "url": "https://www.imo.org/en/ourwork/security/pages/cyber-security.aspx",
        "checked_on": "2026-10-30",
        "relevance": "韧性与风险管理；应用权限检查不能替代港口OT网络、组织及恢复演练证据",
    },
]


def assess(study_id, actor_id, admin=False):
    value = crossport.report(study_id, actor_id, admin)
    try:
        adaptive = adaptive_twin.report()
    except (OSError, ValueError) as exc:
        adaptive = {"historical_only": True, "results": [], "error": str(exc)}
    current = not value["historical_only"]
    forecast = value["twin_calibration"]
    physical = value["multisite_physical_calibration"]
    passed_adaptive = sum(r["research_gates_passed"] for r in adaptive["results"])
    quality_path = BASE_DIR / ".codex_artifacts/crossport-20261030/repository-quality.json"
    try:
        quality = json.loads(quality_path.read_text())
        quality["historical_only"] = any(
            not (BASE_DIR / path).exists() or hashlib.sha256((BASE_DIR / path).read_bytes()).hexdigest() != expected
            for path, expected in quality["source_sha256"].items()
        )
    except (OSError, ValueError, KeyError):
        quality = {"passed": False, "historical_only": True, "notice": "尚无可核查的全仓质量检查快照"}

    def item(code, capability, passed, evidence, remaining):
        return {
            "id": code,
            "capability": capability,
            "status": "所列研究检查通过" if passed else "未通过或待证明",
            "passed": bool(passed),
            "evidence": evidence,
            "remaining": remaining,
        }

    criteria = [
        item(
            "P01",
            "公开来源与版本可追溯",
            current,
            f"八港逐日指标；来源、代码、十个模型及完整轨迹摘要已核验。当前问题：{value['current_validation_issues']}",
            "历史发布时刻未知；不能把AIS衍生指标作为码头遥测。",
        ),
        item(
            "P02",
            "跨港、跨时段及验证集独立选型",
            current,
            "2019—2022四港拟合；2023选型；2024—2025时间及另四港整港留出，五种子。",
            "整港留出允许此前观测做上下文，非无上下文零样本；仅八港，少量港口簇限制推断。",
        ),
        item(
            "P03",
            "RL相对强基线收益和压力安全",
            current and any(r["research_admission"] for r in value["aggregate"]),
            f"验证集选择{value['selected_algorithm']}，强基线{value['comparator_algorithm']}；RL收益及约束失败详见逐窗口记录。",
            "须在新协议、新留出中胜过强基线，并通过压力与最差港口/季度门禁；本轮不准入RL。",
        ),
        item(
            "P04",
            "代理模型完整轨迹与流量守恒",
            current and all(r["maximum_flow_balance_error"] < 1e-8 for r in value["runs"]),
            f"{len(value['runs'])}次完整运行，逐步流量守恒；公开需求时钟与可行动作受约束。",
            "守恒只证明代理模型一致，不证明服务率、队列成本或真实容量已标定。",
        ),
        item(
            "P05",
            "跨港需求预测与区间标定",
            current and forecast["all_cells_passed"],
            f"{forecast['passed_cells']}/{forecast['total_cells']}港年单元通过；失败覆盖率保留。",
            "需发布时延实证、分港异方差与漂移标定，并用新留出复验。",
        ),
        item(
            "P06",
            "跨季长期开环物理标定",
            current and physical["all_station_calibration_gates_passed"],
            f"{sum(r['calibration_passed'] for r in physical['results'])}/3站通过；三港2024年独立季节留出。",
            "低阶分潮外推失败；需更长训练、节点修正及环境驱动，后续必须换新测试期。",
        ),
        item(
            "P07",
            "因果状态同化的新年度短期复验",
            not adaptive["historical_only"] and adaptive.get("all_research_gates_passed", False),
            f"{passed_adaptive}/{len(adaptive['results'])}站点×季节×提前量通过；2025新留出，逐点输入截止可查。",
            "保留失败区间，增加独立极端天气/国际测站；真实观测延迟未知，不能替代长期开环任务。",
        ),
        item(
            "P08",
            "全港物理与多业务闭环",
            False,
            "本轮可辨识：公开需求及站点水位。既有业务沙盘不等于设备实测标定。",
            "待证明：泊位/引航/拖轮/堆场联合容量、船舶与UKC、设备健康、岸电储能及能碳账本的实测误差与联动守恒。",
        ),
        item(
            "P09",
            "顶级港口多机构协同和韧性",
            False,
            "对标MPA 2026服务协同、事件协调、JIT与多源模型方向；本轮未重验所有外部联动系统。",
            "待证明：交通/气象/泄漏扩散联合事件、跨主体计划冲突、正式MSW互操作及OT灾备演练。",
        ),
        item(
            "P10",
            "现场运行与安全保障",
            False,
            "production_authority=false；本轮不建立真实现场连接。",
            "硬件在环、现场影子运行、人工接管、网络分区恢复、真实SLA与港方授权仍需独立验收。",
        ),
        item(
            "P11",
            "当前全仓发布与代码质量",
            quality["passed"] and not quality["historical_only"],
            quality.get("notice", "质量快照缺失"),
            "新增跨港文件检查通过不代表全仓通过；保留旧证据摘要漂移与全仓静态检查失败，不能改写旧哈希冒充复验。",
        ),
    ]
    return {
        "schema": "xiaoyi-leading-port-gap-assessment.v1",
        "study_id": study_id,
        "criteria": criteria,
        "passed_items": sum(r["passed"] for r in criteria),
        "total_items": len(criteria),
        "top_port_full_acceptance": all(r["passed"] for r in criteria),
        "research_admission": any(r["research_admission"] for r in value["aggregate"]),
        "references": REFERENCES,
        "repository_quality": quality,
        "production_authority": False,
        "notice": "这是依据本轮证据和国际港口方向建立的项目验收矩阵，不是法定、行业统一或超级智能认证。只读展示未达标项，不将功能测试通过折算为业务或现场通过。",
    }
