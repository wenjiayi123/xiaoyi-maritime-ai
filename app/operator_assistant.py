from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.port_runtime import port_data_source


OPERATOR_SCENARIOS = [
    {"id": "berth-delay", "role": "调度员", "label": "这条船为什么还没靠？", "prompt": "工作台里 EASTERN HORIZON 为什么还没靠？给我先核对什么。"},
    {"id": "crane-alert", "role": "设备主管", "label": "3号岸桥怎么了？", "prompt": "工作台里 QC-03 当前告警是什么？按先安全后恢复给处置步骤。"},
    {"id": "shift-priority", "role": "值班长", "label": "这个班先处理什么？", "prompt": "根据工作台当前活动告警，按风险、影响和时效排出本班前三项。"},
    {"id": "gate-queue", "role": "闸口班组", "label": "南闸口要不要增开？", "prompt": "工作台里南闸口当前队列怎样？给出增开备用车道前的核对清单。"},
    {"id": "handover", "role": "交班人员", "label": "帮我整理交班", "prompt": "按船舶、设备、堆场、闸口、告警五部分生成当前工作台交班摘要。"},
    {"id": "sop", "role": "一线操作员", "label": "直接给处置步骤", "prompt": "岸桥单位作业能耗偏高怎么处理？给我现场可读的逐步 SOP，并标明需确认的岗位。"},
]


_REPLACEMENTS = (
    (r"咋回事|咋了", "是什么情况"),
    (r"咋办", "怎么处理"),
    (r"咋还没", "为什么还没有"),
    (r"干啥", "做什么"),
    (r"啥时候", "什么时候"),
    (r"啥", "什么"),
    (r"这船", "该船舶"),
    (r"三号桥吊|3号桥吊", "QC-03 岸桥"),
    (r"箱子", "集装箱"),
    (r"车堵了", "当前闸口车辆排队"),
)


def normalize_operator_question(question: str) -> str:
    normalized = re.sub(r"\s+", " ", question.strip())
    for pattern, replacement in _REPLACEMENTS:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    return normalized


def clarification_for(question: str) -> tuple[str, list[str]] | None:
    compact = re.sub(r"[\s，。！？、,.!?；;：:]+", "", question)
    if compact in {
        "怎么办",
        "怎么处理",
        "如何处理",
        "怎么优化",
        "如何优化",
        "怎么安排",
        "如何安排",
        "怎么降",
        "如何降低",
    }:
        return (
            "我可以继续，但还缺少要处理的业务对象。你是在问船舶靠泊、泊位计划、"
            "堆场、闸口、设备、能源负荷、单证，还是人员安排？给出其中一个对象，"
            "我会直接返回判断顺序、处置步骤和需要确认的岗位。",
            [
                "港口如何削峰？",
                "堆场快满了怎么处理？",
                "泊位冲突怎么协调？",
            ],
        )
    if any(term in compact for term in ("该船舶", "这条船", "那条船")) and not re.search(
        r"(?:IMO\s*\d{7}|[A-Z][A-Z\s-]{4,}|B\d{2}|泊位\d+)", question
    ):
        return (
            "我能继续查，但现在还缺少船舶标识，而且当前未连接实时 TOS、AIS/VTS 或船期系统，无法确认当前 ETA。请给我船名、IMO 编号或计划泊位中的任意一个；如果你指的是工作台等待引航的船，也可以直接说“工作台那条待靠船”。",
            ["工作台那条待靠船为什么还没靠？", "给我查 IMO 编号对应的靠泊计划", "按泊位列出待靠船"],
        )
    if any(term in compact for term in ("先处理什么", "先干什么", "优先处理")) and not any(
        scope in compact for scope in ("工作台", "当前告警", "本班", "设备", "船舶", "闸口")
    ):
        return (
            "可以排序。请补一个范围：本班全部活动告警，还是只看船舶、设备、堆场或闸口？我会按人员安全、生产影响、时间窗口三层排序。",
            ["按本班全部活动告警排序", "只看设备告警", "只看靠离泊风险"],
        )
    return None


def is_sandbox_runtime_question(question: str) -> bool:
    compact = question.lower().replace(" ", "")
    if any(term in compact for term in ("常见原因", "一般原因", "一般流程", "是什么", "有哪些区别")) and not any(
        term in compact for term in ("工作台", "沙箱", "当前", "现在", "今天", "今日", "本班")
    ):
        return False
    has_scope = any(term in compact for term in ("工作台", "沙箱", "样板港区", "当前告警", "本班"))
    requests_runtime_handover = any(
        term in compact
        for term in (
            "帮我整理交班",
            "生成交班",
            "整理当前交班",
            "汇总本班交班",
        )
    )
    asks_generic_handover_knowledge = (
        "交班" in compact
        and not has_scope
        and not requests_runtime_handover
        and (
            bool(
                re.search(
                    r"(?:要|该|应|需要)?交(?:接)?(?:什么|哪些)"
                    r"|交班(?:内容|清单|事项|流程|要求|注意)"
                    r"|怎么(?:做)?交班",
                    compact,
                )
            )
            or any(
                term in compact
                for term in (
                    "包含什么",
                    "需要交接",
                    "哪些事项",
                    "注意什么",
                    "最少包含",
                    "不能漏",
                )
            )
        )
    )
    if asks_generic_handover_knowledge:
        # “交班要交什么”是在问通用岗位知识，不是在读取当前工作台。
        # 只有显式的当前/本班/沙箱范围或“帮我整理交班”类动作才进入运行态。
        return False
    has_known_sandbox_entity = any(
        term in compact
        for term in (
            "easternhorizon",
            "qc-03",
            "agv-023",
            "agv-041",
            "b05",
            "南闸口",
        )
    )
    has_supported_object = any(
        term in compact
        for term in (
            "easternhorizon", "待靠船", "在港", "港口忙", "吞吐量",
            "岸桥", "桥吊", "qc-", "agv", "闸口", "堆场", "岸电",
            "能耗", "当前告警", "告警", "交班", "先处理", "优先处理",
        )
    )
    has_runtime_intent = any(
        term in compact
        for term in (
            "当前", "现在", "今天", "今日", "本班", "要不要", "需不需要",
            "情况", "怎么样", "状态", "怎么了", "还没", "在线", "增开",
            "多少", "忙吗", "交班",
        )
    )
    named_vessel = bool(
        re.search(r"[\u4e00-\u9fff]{2,10}轮", question)
        or re.search(r"\b[A-Z][A-Z0-9 -]{2,24}\s+(?:VSL|VESSEL)\b", question)
    )
    explicitly_requests_live = (
        "实时" in compact
        or bool(
            re.search(
                r"\b(?:cn[a-z]{2,}|imo)\s*[-:]?\s*[a-z0-9-]{4,}\b",
                question,
                re.IGNORECASE,
            )
        )
        or (named_vessel and has_runtime_intent)
    )
    # Existing showcase questions without a production identifier continue to
    # use the visibly labelled sandbox. A request for an explicit live value or
    # production-like identifier fails through to the connector boundary unless
    # the caller deliberately selected the sandbox or a published sample entity.
    if explicitly_requests_live and not (has_scope or has_known_sandbox_entity):
        return False
    return has_supported_object and (has_scope or has_runtime_intent)


def operator_next_questions(question: str) -> list[str]:
    compact = question.lower().replace(" ", "")
    if "闸口" in compact:
        return ["按未来30分钟预约到车量判断触发条件", "生成南闸口增开前核对清单", "整理成值班长确认单"]
    if any(term in compact for term in ("qc-03", "岸桥", "桥吊")):
        return ["列出QC-03现场核对清单", "对应SOP的依据是什么", "整理成设备主管确认单"]
    if "agv" in compact:
        return ["AGV-023还能否继续派任务", "给出任务接替和充电步骤", "生成设备交班记录"]
    if any(term in compact for term in ("待靠", "easternhorizon", "还没靠")):
        return ["列出靠泊前五项核对", "B05衔接窗口有什么风险", "整理成调度员确认单"]
    if "交班" in compact:
        return ["只看未闭环事项", "按责任岗位重新整理", "生成管理层班次简报"]
    return ["给我本班前三项处置清单", "按责任岗位分派", "整理成完整交班摘要"]


def sandbox_runtime_answer(question: str) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    snapshot = port_data_source.runtime_snapshot(now)
    metadata = snapshot["metadata"]
    alerts = port_data_source.alerts(now)
    overview = port_data_source.overview(now)
    energy = port_data_source.energy("today", now)
    compact = question.lower().replace(" ", "")
    truth_label = metadata.get("truth_label") or "运营沙箱"
    boundary = (
        f"\n\n数据边界：以上来自 {metadata['source_system']} 的{truth_label}事件流，"
        f"观测时间 {metadata['observed_at'].isoformat()}，质量码 {metadata['quality_code']}；"
        "公开AIS只校准交通包络，其余港区对象与影响属于物理约束工程模拟，不是现场生产实绩。"
        "如用于现场决策，需要接入并核验 TOS、PCS、EMS、EAM、VTS/AIS、METOC 等生产系统，"
        "再由 port-realtime.v1 / port-ops.v1 同一契约替换模拟适配器。"
    )

    if "交班" in compact:
        working = [call for call in snapshot["berth_calls"] if call["status"] in {"working", "alongside"}]
        waiting = [call for call in snapshot["berth_calls"] if call["status"] == "awaiting_pilot"]
        return (
            "当前班次交班摘要：\n\n"
            f"1. 船舶：{len(working)} 艘在泊作业；{len(waiting)} 艘等待引航，待靠船为 {waiting[0]['vessel_name']}，计划约 {waiting[0]['eta']} 到港。\n"
            f"2. 设备：岸桥 {snapshot['equipment']['quay_cranes']['working']}/{snapshot['equipment']['quay_cranes']['total']} 台作业；AGV {snapshot['equipment']['agv']['online']}/{snapshot['equipment']['agv']['total']} 台在线。\n"
            f"3. 堆场：占用率 {snapshot['yard']['occupancy_percent']}%，冷藏箱位使用 {snapshot['yard']['reefer_slots_used']} 个。\n"
            f"4. 闸口：排队 {snapshot['gate']['queue_vehicles']} 辆，平均周转 {snapshot['gate']['average_turn_time_minutes']} 分钟。\n"
            f"5. 待跟进：{alerts[0]['title']}、{alerts[1]['title']}、{alerts[2]['title']}。交班前请逐项确认责任人、最后更新时间和未完成动作。"
            + boundary
        )
    if any(term in compact for term in ("easternhorizon", "待靠", "还没靠", "等待引航")):
        call = next(item for item in snapshot["berth_calls"] if item["status"] == "awaiting_pilot")
        return (
            f"直接结论：{call['vessel_name']} 当前状态是等待引航，沙箱 ETA 为 {call['eta']}。"
            "在判断延误前，调度员应依次核对：引航计划、B05 前船剩余作业量、拖轮到位、航道窗口、船方 ready 状态。"
            "当前 B05 的衔接窗口只有 42 分钟，属于优先关注项，但不能仅凭这一项认定已经延误。"
            + boundary
        )
    if any(term in compact for term in ("qc-03", "岸桥", "桥吊")):
        alert = alerts[0]
        steps = "\n".join(f"{index}. {item}" for index, item in enumerate(alert["recommended_actions"], 1))
        return (
            f"直接结论：{alert['message']}\n\n建议先安全、后诊断、再恢复：\n{steps}\n"
            "涉及停机、旁路或转检修工单时，必须由设备主管按现场制度确认，小懿不自动下发控制。"
            + boundary
        )
    if "agv" in compact:
        fleet = snapshot["equipment"]["agv"]
        alert = next(item for item in alerts if item["category"] == "equipment")
        return (
            f"直接结论：AGV车队当前在线 {fleet['online']}/{fleet['total']} 台、作业 {fleet['working']} 台、充电 {fleet['charging']} 台。"
            f"AGV-023 当前需要关注：{alert['message']}\n\n"
            "当前建议完成在途任务后停止派发新任务，由AGV-041接替，并引导AGV-023前往C2充电位；"
            "最终调度由车队或设备值班人员确认。"
            + boundary
        )
    if "闸口" in compact:
        gate = snapshot["gate"]
        should_prepare = gate["queue_vehicles"] >= 22 or gate["average_turn_time_minutes"] >= 25
        decision = (
            "当前暂不立即增开，但建议启动备用车道准备，由闸口值班长核对未来30分钟预约到车和场内接纳能力后决定是否正式增开。"
            if should_prepare
            else "当前建议暂不立即增开，保持备用车道和人员待命；若排队达到22辆、平均周转接近25分钟，或预约到车波峰继续上升，再由闸口值班长确认增开。"
        )
        return (
            f"直接结论：南闸口当前排队 {gate['queue_vehicles']} 辆，开放 {gate['open_lanes']} 条车道，平均周转 {gate['average_turn_time_minutes']} 分钟。{decision}\n\n"
            "增开前核对：预约到车曲线、备用车道人员、场内接纳能力、单车处理时间和场外排队长度。"
            + boundary
        )
    if "堆场" in compact:
        yard = snapshot["yard"]
        return (
            f"直接结论：当前堆场占用率 {yard['occupancy_percent']}%，冷藏箱位使用 {yard['reefer_slots_used']} 个，"
            f"危险品区占用率 {yard['dangerous_goods_zone_percent']}%。整体仍在可控区间，但应继续关注高密度箱区、冷藏箱位和闸口到车波峰。\n\n"
            "建议先核对各箱区占用率、未来提装箱计划、翻箱任务和闸口预约量，再决定是否调整箱区或作业顺序。"
            + boundary
        )
    if any(term in compact for term in ("岸电", "能耗", "碳排")):
        summary = energy["summary"]
        return (
            f"直接结论：当前综合能耗 {summary['total_energy_mwh']:,.1f} MWh，碳排放 {summary['carbon_emissions_tco2e']:,.1f} tCO₂e，"
            f"岸电利用率 {summary['shore_power_utilization_percent']:.1f}%，单位吞吐碳强度 {summary['carbon_intensity_kgco2e_per_teu']:.1f} kgCO₂e/TEU。\n\n"
            f"重点研判：{energy['insights'][0]} {energy['insights'][1]}"
            + boundary
        )
    if any(term in compact for term in ("港口忙", "在港", "吞吐量")):
        metrics = {item["id"]: item for item in overview["metrics"]}
        vessels = metrics["vessels-in-port"]
        throughput = metrics["teu-throughput"]
        cranes = metrics["berth-utilization"]
        yard = snapshot["yard"]
        load_label = "中高负荷" if cranes["value"] >= 78 or yard["occupancy_percent"] >= 70 else "平稳负荷"
        return (
            f"直接结论：当前港区处于{load_label}运行。在港船舶 {vessels['display_value']}，今日累计吞吐量 {throughput['display_value']}，"
            f"岸桥作业利用率 {cranes['display_value']}，堆场占用率 {yard['occupancy_percent']}%。\n\n"
            "需要重点关注泊位衔接、QC-03能耗告警和南闸口到车波峰；值班长可据此安排下一轮现场核对。"
            + boundary
        )
    ordered = sorted(alerts, key=lambda item: {"critical": 0, "warning": 1, "info": 2}[item["level"]])
    return (
        "本班建议优先级：\n"
        + "\n".join(f"{index}. {item['title']}：{item['message']}" for index, item in enumerate(ordered[:3], 1))
        + "\n\n排序依据：先人员与设备安全，再靠离泊时间窗，最后效率优化；值班负责人确认后才进入现场动作。"
        + boundary
    )


def operator_scenarios() -> list[dict[str, Any]]:
    return OPERATOR_SCENARIOS
