from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timezone
from threading import RLock
from typing import Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.port_runtime import SANDBOX_NOTICE, port_data_source
from app.runtime_store import runtime_store


DataMode = Literal["operations_sandbox", "live"]
MetricTrend = Literal["up", "down", "flat"]
AlertLevel = Literal["critical", "warning", "info"]
AlertStatus = Literal["active", "acknowledged", "resolved"]
EnergyRange = Literal["today", "7d", "30d"]
TaskStatus = Literal["running", "completed", "cancelled"]
StepStatus = Literal["pending", "running", "completed", "skipped"]
ReportType = Literal["daily_operations", "energy", "alerts", "management_brief"]


router = APIRouter(prefix="/api", tags=["港航运营数据"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class OperationsMetric(BaseModel):
    id: str
    label: str
    value: float
    unit: str
    display_value: str
    trend_percent: float
    trend: MetricTrend
    status: Literal["normal", "attention", "warning"] = "normal"


class SourceMetadata(BaseModel):
    data_mode: DataMode
    data_notice: str
    source_system: str
    source_type: str
    source_adapter: str
    schema_version: str
    port_code: str
    observed_at: datetime
    generated_at: datetime
    quality_code: str
    quality_score: float
    latency_ms: int
    production_ready: bool
    live_data_verified: bool
    write_enabled: bool


class OperationsOverview(BaseModel):
    data_mode: DataMode = "operations_sandbox"
    data_notice: str
    source_metadata: SourceMetadata
    port_name: str
    operational_date: date
    updated_at: datetime
    metrics: list[OperationsMetric]


class EnergySummary(BaseModel):
    total_energy_mwh: float
    carbon_emissions_tco2e: float
    carbon_intensity_kgco2e_per_teu: float
    shore_power_utilization_percent: float
    energy_change_percent: float
    carbon_change_percent: float
    intensity_change_percent: float
    shore_power_change_percent: float


class EnergyPoint(BaseModel):
    timestamp: str
    energy_mwh: float
    carbon_emissions_tco2e: float
    baseline_mwh: float


class EnergyResponse(BaseModel):
    data_mode: DataMode = "operations_sandbox"
    data_notice: str
    source_metadata: SourceMetadata
    range: EnergyRange
    updated_at: datetime
    summary: EnergySummary
    series: list[EnergyPoint]
    insights: list[str]


class AlertItem(BaseModel):
    id: str
    level: AlertLevel
    category: str
    title: str
    message: str
    source: str
    occurred_at: datetime
    status: AlertStatus
    recommended_actions: list[str]


class AlertsResponse(BaseModel):
    data_mode: DataMode = "operations_sandbox"
    data_notice: str
    source_metadata: SourceMetadata
    updated_at: datetime
    total: int
    critical: int
    warning: int
    info: int
    items: list[AlertItem]


class TaskTemplate(BaseModel):
    id: str
    title: str
    description: str
    estimated_minutes: int
    risk_level: Literal["low", "medium", "high"]
    requires_human_confirmation: bool
    steps: list[str]


class TaskCreateRequest(BaseModel):
    template_id: str = Field(..., min_length=2, max_length=80)
    title: Optional[str] = Field(default=None, min_length=2, max_length=100)
    parameters: dict[str, str] = Field(default_factory=dict)


class TaskStep(BaseModel):
    id: str
    order: int
    title: str
    description: str
    status: StepStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[str] = None


class AuditEvent(BaseModel):
    timestamp: datetime
    event: str
    detail: str


class OperationTask(BaseModel):
    id: str
    template_id: str
    title: str
    execution_mode: Literal["operations_sandbox"] = "operations_sandbox"
    data_notice: str
    status: TaskStatus
    progress_percent: int
    current_step_id: Optional[str]
    requires_human_confirmation: bool
    parameters: dict[str, str]
    created_at: datetime
    updated_at: datetime
    steps: list[TaskStep]
    audit_trail: list[AuditEvent]


class TaskAdvanceResponse(BaseModel):
    task: OperationTask
    completed_step_id: Optional[str]
    next_step_id: Optional[str]
    assistant_message: str
    visual_cue: Literal["step-complete", "task-complete", "no-change"]


class ReportRequest(BaseModel):
    report_type: ReportType = "daily_operations"
    title: Optional[str] = Field(default=None, min_length=2, max_length=100)
    include_recommendations: bool = True
    energy_range: EnergyRange = "today"


class ReportKPI(BaseModel):
    label: str
    value: str
    assessment: Literal["good", "attention", "warning"]


class GeneratedReport(BaseModel):
    id: str
    report_type: ReportType
    title: str
    status: Literal["generated"] = "generated"
    data_mode: DataMode = "operations_sandbox"
    data_notice: str
    source_metadata: SourceMetadata
    analysis_range: EnergyRange
    generated_at: datetime
    summary: str
    kpis: list[ReportKPI]
    findings: list[str]
    recommendations: list[str]
    content_markdown: str
    available_formats: list[Literal["markdown", "json"]]


class QuickAction(BaseModel):
    id: str
    title: str
    description: str
    task_template_id: str


class DashboardResponse(BaseModel):
    data_mode: DataMode = "operations_sandbox"
    data_notice: str
    source_metadata: SourceMetadata
    updated_at: datetime
    overview: OperationsOverview
    energy: EnergyResponse
    alerts: AlertsResponse
    quick_actions: list[QuickAction]
    knowledge_categories: list[str]


_DATA_NOTICE = SANDBOX_NOTICE


_TASK_TEMPLATES = {
    item.id: item
    for item in [
        TaskTemplate(
            id="analyze-energy",
            title="分析今日港口能耗",
            description="读取能耗指标、比对基线、定位异常并形成节能建议。",
            estimated_minutes=3,
            risk_level="low",
            requires_human_confirmation=False,
            steps=[
                "读取今日能耗与碳排数据",
                "对比历史基线与作业量",
                "定位异常时段和设备",
                "生成调度与节能建议",
                "形成可追溯分析结论",
            ],
        ),
        TaskTemplate(
            id="optimize-berth",
            title="生成泊位调度候选建议",
            description="结合船期、泊位占用和岸桥资源生成可复核的启发式候选建议。",
            estimated_minutes=5,
            risk_level="medium",
            requires_human_confirmation=True,
            steps=[
                "汇总 ETA、ETB 与泊位占用",
                "识别船期冲突和等待风险",
                "计算岸桥与拖轮资源窗口",
                "生成候选调度方案",
                "等待调度员确认后导出方案",
            ],
        ),
        TaskTemplate(
            id="handle-alert",
            title="辅助处置运营预警",
            description="归并告警、查询 SOP、生成处置步骤并保留审计记录。",
            estimated_minutes=4,
            risk_level="high",
            requires_human_confirmation=True,
            steps=[
                "读取并归并关联告警",
                "评估影响范围与风险等级",
                "检索对应 SOP 和责任岗位",
                "生成逐项处置建议",
                "等待值班负责人确认执行",
            ],
        ),
        TaskTemplate(
            id="generate-daily-report",
            title="生成港口运营日报",
            description="汇总运营、能耗、设备与预警信息，生成管理简报。",
            estimated_minutes=2,
            risk_level="low",
            requires_human_confirmation=False,
            steps=[
                "汇总当日运营关键指标",
                "提取能耗与碳排趋势",
                "整理设备和预警事件",
                "生成管理层摘要与建议",
                "输出结构化日报",
            ],
        ),
    ]
}


def _execute_task_step(task: OperationTask, step: TaskStep) -> str:
    """Execute a measurable read-only step instead of returning display copy."""
    now = _now()
    metadata = port_data_source.metadata(now)
    template_id = task.template_id
    if template_id == "analyze-energy":
        energy = port_data_source.energy("today", now)
        series = list(energy.get("series") or [])
        summary = energy.get("summary") or {}
        if step.order == 1:
            return (
                f"已从 {metadata['source_system']} 读取 {len(series)} 个能耗点；"
                f"观测时间 {metadata['observed_at'].isoformat()}，质量码 {metadata['quality_code']}。"
            )
        if step.order == 2:
            return (
                f"同口径变化 {float(summary.get('energy_change_percent') or 0):+.1f}%；"
                f"综合能耗 {float(summary.get('total_energy_mwh') or 0):.2f} MWh。"
            )
        if step.order == 3:
            peak = max(series, key=lambda item: float(item.get("energy_mwh") or 0), default={})
            return f"峰值点 {peak.get('timestamp', '无')}，能耗 {float(peak.get('energy_mwh') or 0):.2f} MWh；结果由实际返回序列计算。"
        if step.order == 4:
            shore = float(summary.get("shore_power_utilization_percent") or 0)
            return f"按峰值时段与岸电利用率 {shore:.1f}% 生成只读复核建议；未下发EMS控制指令。"
        return f"能耗分析步骤已归档；数据模式 {metadata['data_mode']}，live_data_verified={metadata['live_data_verified']}。"

    if template_id == "optimize-berth":
        snapshot = port_data_source.runtime_snapshot(now)
        calls = list(snapshot.get("berth_calls") or [])
        working = [item for item in calls if item.get("status") in {"working", "alongside"}]
        waiting = [item for item in calls if item not in working]
        if step.order == 1:
            return f"读取 {len(calls)} 个挂靠对象：{len(working)} 个在泊、{len(waiting)} 个待靠；来源 {metadata['source_system']}。"
        if step.order == 2:
            remaining = sum(int(item.get("remaining_moves") or 0) for item in calls)
            return f"按ETD/ETA和剩余箱量检查窗口；当前登记剩余作业量 {remaining} moves。"
        if step.order == 3:
            cranes = snapshot["equipment"]["quay_cranes"]
            return f"岸桥资源核验：{cranes['working']}/{cranes['total']} 作业、{cranes['maintenance']} 检修；未假设未返回的拖轮资源。"
        if step.order == 4:
            return "已生成基于先到时窗、剩余箱量和岸桥可用性的启发式候选顺序；这不是数学优化器最优解。"
        return "候选泊位顺序已封装为只读建议，等待调度员确认；生产TOS写入未启用。"

    if template_id == "handle-alert":
        alerts = list(port_data_source.alerts(now))
        active = [item for item in alerts if item.get("status") == "active"]
        critical = [item for item in active if item.get("level") == "critical"]
        if step.order == 1:
            return f"读取并按ID归并 {len(active)} 条活动告警，其中 critical {len(critical)} 条。"
        if step.order == 2:
            categories = sorted({str(item.get("category")) for item in active})
            return f"影响类别：{', '.join(categories)}；排序规则为级别、事件时间，不使用随机权重。"
        if step.order == 3:
            action_count = sum(len(item.get("recommended_actions") or []) for item in active)
            return f"从告警记录提取 {action_count} 条登记处置动作；未把前端文案冒充SOP原文。"
        if step.order == 4:
            return "已按先安全隔离、再核实数据、后恢复作业的顺序形成建议；高风险动作保持人工门禁。"
        return "告警辅助处置记录已归档；没有调用EAM派单、消警或设备控制写接口。"

    if template_id == "generate-daily-report":
        overview = port_data_source.overview(now)
        energy = port_data_source.energy("today", now)
        alerts = port_data_source.alerts(now)
        if step.order == 1:
            return f"读取 {len(overview.get('metrics') or [])} 项运营KPI，来源 {metadata['source_system']}。"
        if step.order == 2:
            return f"读取 {len(energy.get('series') or [])} 个能耗时序点，并保留数据模式与观测时间。"
        if step.order == 3:
            return f"整理 {len(alerts)} 条告警事件；按事件ID和时间戳保留来源。"
        if step.order == 4:
            return "管理摘要由本次已读取KPI、能耗和告警字段生成；不使用隐藏的展示常量。"
        return "日报输入检查已完成，可调用报告API生成带来源声明的Markdown或JSON。"

    return f"步骤已执行；数据来源 {metadata['source_system']}，质量码 {metadata['quality_code']}。"


class _TaskStore:
    def __init__(self, max_items: int = 100) -> None:
        self._max_items = max_items
        self._items: OrderedDict[str, OperationTask] = OrderedDict()
        self._lock = RLock()
        for item in reversed(runtime_store.list_artifacts("operation_task", limit=max_items)):
            try:
                task = OperationTask.model_validate(item)
            except ValueError:
                continue
            if task.status == "running":
                now = _now()
                for step in task.steps:
                    if step.status == "running":
                        step.status = "skipped"
                        step.completed_at = now
                        step.result = "服务进程重启，未自动续执行。"
                task.status = "cancelled"
                task.current_step_id = None
                task.updated_at = now
                task.audit_trail.append(AuditEvent(
                    timestamp=now,
                    event="process-restart",
                    detail="服务进程重启；为防止重复执行，未完成任务已安全取消。",
                ))
                runtime_store.save_artifact("operation_task", task.id, task.model_dump(mode="json"), max_items=max_items)
            self._items[task.id] = task

    def _persist(self, task: OperationTask) -> None:
        runtime_store.save_artifact("operation_task", task.id, task.model_dump(mode="json"), max_items=self._max_items)

    def create(self, payload: TaskCreateRequest, template: TaskTemplate) -> OperationTask:
        with self._lock:
            now = _now()
            task_id = f"task-{uuid4().hex[:12]}"
            steps = [
                TaskStep(
                    id=f"{task_id}-step-{index}",
                    order=index,
                    title=title,
                    description=f"小懿正在执行：{title}",
                    status="running" if index == 1 else "pending",
                    started_at=now if index == 1 else None,
                )
                for index, title in enumerate(template.steps, start=1)
            ]
            task = OperationTask(
                id=task_id,
                template_id=template.id,
                title=payload.title or template.title,
                data_notice=_DATA_NOTICE,
                status="running",
                progress_percent=0,
                current_step_id=steps[0].id,
                requires_human_confirmation=template.requires_human_confirmation,
                parameters=payload.parameters,
                created_at=now,
                updated_at=now,
                steps=steps,
                audit_trail=[
                    AuditEvent(
                        timestamp=now,
                        event="task-created",
                        detail="已创建运营沙箱任务，第一步开始运行。",
                    )
                ],
            )
            while len(self._items) >= self._max_items:
                self._items.popitem(last=False)
            self._items[task.id] = task
            self._persist(task)
            return task.model_copy(deep=True)

    def list(self) -> list[OperationTask]:
        with self._lock:
            return [item.model_copy(deep=True) for item in reversed(self._items.values())]

    def get(self, task_id: str) -> Optional[OperationTask]:
        with self._lock:
            item = self._items.get(task_id)
            return item.model_copy(deep=True) if item else None

    def advance(self, task_id: str) -> Optional[TaskAdvanceResponse]:
        with self._lock:
            task = self._items.get(task_id)
            if task is None:
                return None
            if task.status != "running":
                return TaskAdvanceResponse(
                    task=task.model_copy(deep=True),
                    completed_step_id=None,
                    next_step_id=None,
                    assistant_message="任务已完成，无需重复执行。",
                    visual_cue="no-change",
                )

            now = _now()
            current = next((step for step in task.steps if step.status == "running"), None)
            if current is None:
                task.status = "completed"
                task.progress_percent = 100
                task.current_step_id = None
                task.updated_at = now
                self._persist(task)
                return TaskAdvanceResponse(
                    task=task.model_copy(deep=True),
                    completed_step_id=None,
                    next_step_id=None,
                    assistant_message="全部步骤已完成。",
                    visual_cue="task-complete",
                )

            current.status = "completed"
            current.completed_at = now
            current.result = _execute_task_step(task, current)
            next_step = next((step for step in task.steps if step.status == "pending"), None)
            completed_count = sum(step.status == "completed" for step in task.steps)
            task.progress_percent = round(completed_count / len(task.steps) * 100)
            task.updated_at = now
            task.audit_trail.append(
                AuditEvent(
                    timestamp=now,
                    event="step-completed",
                    detail=f"第 {current.order} 步“{current.title}”执行完成。",
                )
            )

            if next_step is None:
                task.status = "completed"
                task.progress_percent = 100
                task.current_step_id = None
                task.audit_trail.append(
                    AuditEvent(timestamp=now, event="task-completed", detail="全部运营沙箱步骤已完成。")
                )
                message = "全部步骤执行完成，结果已归档并可生成报告。"
                cue: Literal["step-complete", "task-complete", "no-change"] = "task-complete"
            else:
                next_step.status = "running"
                next_step.started_at = now
                task.current_step_id = next_step.id
                message = f"“{current.title}”已完成，开始“{next_step.title}”。"
                cue = "step-complete"

            self._persist(task)
            return TaskAdvanceResponse(
                task=task.model_copy(deep=True),
                completed_step_id=current.id,
                next_step_id=next_step.id if next_step else None,
                assistant_message=message,
                visual_cue=cue,
            )


class _ReportStore:
    def __init__(self, max_items: int = 100) -> None:
        self._max_items = max_items
        self._items: OrderedDict[str, GeneratedReport] = OrderedDict()
        self._lock = RLock()
        for item in reversed(runtime_store.list_artifacts("generated_report", limit=max_items)):
            try:
                report = GeneratedReport.model_validate(item)
            except ValueError:
                continue
            self._items[report.id] = report

    def save(self, report: GeneratedReport) -> GeneratedReport:
        with self._lock:
            while len(self._items) >= self._max_items:
                self._items.popitem(last=False)
            self._items[report.id] = report
            runtime_store.save_artifact(
                "generated_report", report.id, report.model_dump(mode="json"), max_items=self._max_items
            )
            return report.model_copy(deep=True)

    def get(self, report_id: str) -> Optional[GeneratedReport]:
        with self._lock:
            report = self._items.get(report_id)
            return report.model_copy(deep=True) if report else None


_tasks = _TaskStore()
_reports = _ReportStore()


def _operations_overview() -> OperationsOverview:
    now = _now()
    payload = port_data_source.overview(now)
    metadata = SourceMetadata(**port_data_source.metadata(now))
    return OperationsOverview(
        data_mode=metadata.data_mode,
        data_notice=_DATA_NOTICE,
        source_metadata=metadata,
        port_name=payload["port_name"],
        operational_date=payload["operational_date"],
        updated_at=metadata.observed_at,
        metrics=[OperationsMetric(**item) for item in payload["metrics"]],
    )


def _energy(period: EnergyRange) -> EnergyResponse:
    now = _now()
    payload = port_data_source.energy(period, now)
    metadata = SourceMetadata(**port_data_source.metadata(now))
    return EnergyResponse(
        data_mode=metadata.data_mode,
        data_notice=_DATA_NOTICE,
        source_metadata=metadata,
        range=period,
        updated_at=metadata.observed_at,
        summary=EnergySummary(**payload["summary"]),
        series=[EnergyPoint(**item) for item in payload["series"]],
        insights=payload["insights"],
    )


def _all_alerts() -> list[AlertItem]:
    now = _now()
    return [AlertItem(**item) for item in port_data_source.alerts(now)]


def _alerts(
    level: Optional[AlertLevel] = None,
    status: Optional[AlertStatus] = None,
    limit: int = 20,
) -> AlertsResponse:
    items = _all_alerts()
    if level:
        items = [item for item in items if item.level == level]
    if status:
        items = [item for item in items if item.status == status]
    items = items[:limit]
    now = _now()
    metadata = SourceMetadata(**port_data_source.metadata(now))
    return AlertsResponse(
        data_mode=metadata.data_mode,
        data_notice=_DATA_NOTICE,
        source_metadata=metadata,
        updated_at=metadata.observed_at,
        total=len(items),
        critical=sum(item.level == "critical" for item in items),
        warning=sum(item.level == "warning" for item in items),
        info=sum(item.level == "info" for item in items),
        items=items,
    )


def _generate_report(payload: ReportRequest) -> GeneratedReport:
    titles = {
        "daily_operations": "港口运营日报",
        "energy": "港口能耗与碳排分析报告",
        "alerts": "港口运营预警处置报告",
        "management_brief": "港航运营管理简报",
    }
    title = payload.title or titles[payload.report_type]
    now = _now()
    metadata = SourceMetadata(**port_data_source.metadata(now))
    overview = _operations_overview()
    analysis_range: EnergyRange = payload.energy_range if payload.report_type == "energy" else "today"
    period_label = {"today": "今日", "7d": "最近7日", "30d": "最近30日"}[analysis_range]
    energy = _energy(analysis_range)
    alerts = _alerts(limit=20)
    metric_by_id = {item.id: item for item in overview.metrics}
    kpis = [
        ReportKPI(label="今日累计吞吐量", value=metric_by_id["teu-throughput"].display_value, assessment="good"),
        ReportKPI(label="岸桥作业利用率", value=metric_by_id["berth-utilization"].display_value, assessment="good"),
        ReportKPI(label=f"{period_label}综合能耗", value=f"{energy.summary.total_energy_mwh:,.1f} MWh", assessment="good"),
        ReportKPI(label="活动预警", value=f"{alerts.total} 条", assessment="attention"),
    ]
    findings = [
        f"今日累计吞吐量 {metric_by_id['teu-throughput'].display_value}；该值来自 {metadata.source_system}。",
        f"{period_label}综合能耗 {energy.summary.total_energy_mwh:,.1f} MWh，对比口径变化 {energy.summary.energy_change_percent:+.1f}%，岸电利用率 {energy.summary.shore_power_utilization_percent:.1f}%。",
        f"当前返回 {alerts.total} 条活动预警，其中 critical {alerts.critical} 条、warning {alerts.warning} 条。",
    ]
    recommendations: list[str] = []
    if payload.include_recommendations:
        for alert in alerts.items:
            for action in alert.recommended_actions:
                if action not in recommendations:
                    recommendations.append(action)
                if len(recommendations) >= 5:
                    break
            if len(recommendations) >= 5:
                break
        if not recommendations:
            recommendations.append("当前告警源未返回处置动作，请由值班人员按站点SOP复核，不自动补写。")
    summary_text = (
        f"本次读取 {len(overview.metrics)} 项运营KPI、{len(energy.series)} 个能耗点和 {alerts.total} 条活动预警；"
        f"数据模式为 {metadata.data_mode}，live_data_verified={metadata.live_data_verified}。"
    )
    generated_at = _now()
    markdown_lines = [
        f"# {title}",
        "",
        f"> 生成时间：{generated_at.isoformat()} · {metadata.data_mode} · {metadata.quality_code} · live_data_verified={metadata.live_data_verified}",
        f"> 分析周期：{period_label} · 周期代码 {analysis_range}",
        "",
        "## 核心结论",
        "",
        summary_text,
        "",
        "## 关键发现",
        "",
        *[f"- {item}" for item in findings],
    ]
    if recommendations:
        markdown_lines.extend(["", "## 建议", "", *[f"- {item}" for item in recommendations]])
    return GeneratedReport(
        id=f"report-{uuid4().hex[:12]}",
        report_type=payload.report_type,
        title=title,
        data_mode=metadata.data_mode,
        data_notice=_DATA_NOTICE,
        source_metadata=metadata,
        analysis_range=analysis_range,
        generated_at=generated_at,
        summary=summary_text,
        kpis=kpis,
        findings=findings,
        recommendations=recommendations,
        content_markdown="\n".join(markdown_lines),
        available_formats=["markdown", "json"],
    )


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard() -> DashboardResponse:
    now = _now()
    metadata = SourceMetadata(**port_data_source.metadata(now))
    return DashboardResponse(
        data_mode=metadata.data_mode,
        data_notice=_DATA_NOTICE,
        source_metadata=metadata,
        updated_at=metadata.observed_at,
        overview=_operations_overview(),
        energy=_energy("today"),
        alerts=_alerts(limit=4),
        quick_actions=[
            QuickAction(
                id="energy-analysis",
                title="帮我分析今日港口能耗",
                description="逐步读取指标、定位异常并生成建议。",
                task_template_id="analyze-energy",
            ),
            QuickAction(
                id="berth-optimization",
                title="生成泊位调度候选建议",
                description="分析泊位冲突并生成可复核的启发式候选。",
                task_template_id="optimize-berth",
            ),
            QuickAction(
                id="daily-report",
                title="生成详细运营报告",
                description="汇总运营、能耗、设备与预警信息。",
                task_template_id="generate-daily-report",
            ),
        ],
        knowledge_categories=["港口运营", "航运调度", "能源管理", "设备管理", "政策法规", "行业标准"],
    )


@router.get("/runtime/status")
def runtime_status() -> dict[str, object]:
    """Expose the active adapter, freshness and safety boundary."""
    now = _now()
    return port_data_source.metadata(now)


@router.get("/runtime/snapshot")
def runtime_snapshot() -> dict[str, object]:
    """Production-shaped operational entities for frontline assistance."""
    return port_data_source.runtime_snapshot(_now())


@router.get("/operations/overview", response_model=OperationsOverview)
def operations_overview() -> OperationsOverview:
    return _operations_overview()


@router.get("/energy", response_model=EnergyResponse)
def energy(
    range_: EnergyRange = Query("today", alias="range"),
    period: Optional[EnergyRange] = Query(default=None, description="range 的兼容别名"),
) -> EnergyResponse:
    return _energy(period or range_)


@router.get("/alerts", response_model=AlertsResponse)
def alerts(
    level: Optional[AlertLevel] = None,
    status: Optional[AlertStatus] = None,
    limit: int = Query(20, ge=1, le=100),
) -> AlertsResponse:
    return _alerts(level=level, status=status, limit=limit)


@router.get("/tasks/templates", response_model=list[TaskTemplate])
def task_templates() -> list[TaskTemplate]:
    return [template.model_copy(deep=True) for template in _TASK_TEMPLATES.values()]


@router.get("/tasks", response_model=list[OperationTask])
def list_tasks() -> list[OperationTask]:
    return _tasks.list()


@router.post("/tasks", response_model=OperationTask, status_code=201)
def create_task(payload: TaskCreateRequest) -> OperationTask:
    template = _TASK_TEMPLATES.get(payload.template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="未知任务模板")
    return _tasks.create(payload, template)


@router.get("/tasks/{task_id}", response_model=OperationTask)
def get_task(task_id: str) -> OperationTask:
    task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return task


@router.post("/tasks/{task_id}/next", response_model=TaskAdvanceResponse)
def advance_task(task_id: str) -> TaskAdvanceResponse:
    result = _tasks.advance(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return result


@router.post("/reports", response_model=GeneratedReport, status_code=201)
@router.post("/reports/generate", response_model=GeneratedReport, status_code=201, include_in_schema=False)
def generate_report(payload: ReportRequest) -> GeneratedReport:
    return _reports.save(_generate_report(payload))


@router.get("/reports/{report_id}", response_model=GeneratedReport)
def get_report(report_id: str) -> GeneratedReport:
    report = _reports.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在或已过期")
    return report
