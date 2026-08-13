from __future__ import annotations

import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "web" / "index.html"
APP_JS = ROOT / "web" / "app.js"
STYLES_CSS = ROOT / "web" / "styles.css"


class _IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.attributes_by_id: dict[str, dict[str, str | None]] = {}

    def _collect(self, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        node_id = attributes.get("id")
        if node_id is None:
            return
        self.ids.append(node_id)
        self.attributes_by_id.setdefault(node_id, attributes)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._collect(attrs)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._collect(attrs)


def _read_frontend() -> tuple[str, str]:
    return (
        INDEX_HTML.read_text(encoding="utf-8"),
        APP_JS.read_text(encoding="utf-8"),
    )


def _parse_ids(html: str) -> _IdCollector:
    parser = _IdCollector()
    parser.feed(html)
    parser.close()
    return parser


def test_required_frontend_dom_ids_exist_once() -> None:
    html, _ = _read_frontend()
    parser = _parse_ids(html)
    counts = Counter(parser.ids)
    required_ids = {
        "agentModeBtn",
        "strictEvidence",
        "groundingBadge",
        "answerTrustMeta",
        "knowledgeCount",
        "knowledgeChunkCount",
        "knowledgeOfficialCount",
        "connectorNavBadge",
        "systemLaunchHubBtn",
        "systemLaunchBadge",
        "rlCenterGate",
        "rlCenterEvidenceStrip",
        "rlCenterAlgorithmMatrix",
        "rlAdvisorFeed",
        "rlSystemLinkage",
    }

    missing = sorted(node_id for node_id in required_ids if counts[node_id] == 0)
    duplicated = sorted(node_id for node_id, count in counts.items() if count > 1)

    assert not missing, f"缺少前端契约 DOM ID: {missing}"
    assert not duplicated, f"HTML 中存在重复 DOM ID: {duplicated}"


def test_agent_and_strict_evidence_controls_default_to_enabled() -> None:
    html, _ = _read_frontend()
    nodes = _parse_ids(html).attributes_by_id

    agent = nodes["agentModeBtn"]
    strict = nodes["strictEvidence"]

    assert agent.get("data-action") == "toggle-agent-mode"
    assert agent.get("aria-pressed") == "true"
    assert "active" in (agent.get("class") or "").split()
    assert strict.get("type") == "checkbox"
    assert "checked" in strict


def test_frontend_displays_internal_evidence_ids_as_chinese_source_markers() -> None:
    _, javascript = _read_frontend()

    assert (
        'return String(value || "").replace(/\\[E(\\d+)\\]/g, "[来源$1]");'
        in javascript
    )
    assert "displayEvidenceMarkers(text.slice(0, index + chunk))" in javascript
    assert "displayEvidenceMarkers(expected)" in javascript
    assert "displayEvidenceMarkers(item.answer)" in javascript


def test_frontend_calls_required_backend_surfaces() -> None:
    _, javascript = _read_frontend()
    required_endpoints = {
        "/api/automation/plans",
        "/api/knowledge/status",
        "/api/knowledge/catalog",
        "/api/knowledge/search",
        "/api/knowledge/sources",
        "/api/knowledge/intake",
        "/api/connectors",
        "/api/hub/systems",
        "/api/hub/capabilities",
        "/api/orchestrator/run",
        "/api/evaluation/summary",
        "/api/evaluation/run",
        "/api/evaluation/feedback",
        "/api/governance/metrics",
        "/api/operator/scenarios",
        "/api/runtime/status",
        "/api/system/readiness",
        "/api/system/info",
        "/api/system/competitive-benchmark",
        "/api/system-linkage/overview",
        "/api/system-linkage/command",
        "/api/models",
        "/api/governance/identity",
        "/api/rl-lab/health",
        "/api/rl-lab/evidence",
        "/api/rl-lab/advisor",
    }

    missing = []
    for endpoint in sorted(required_endpoints):
        call_pattern = re.compile(
            rf"\bapi\(\s*['\"]{re.escape(endpoint)}['\"]"
        )
        if call_pattern.search(javascript) is None:
            missing.append(endpoint)

    assert not missing, f"app.js 尚未调用后端能力入口: {missing}"


def test_training_center_connects_matrix_advisor_and_system_actions() -> None:
    html, javascript = _read_frontend()

    assert 'data-view="rl"' in html
    assert "训练中心、算法矩阵、小懿训练顾问、全系统助手同屏联动" in html
    for action in ("refresh", "start-training", "show-contract", "show-evidence", "ask-advisor"):
        assert f'data-rl-center-action="{action}"' in html
    assert "loadRLCenter" in javascript
    assert "renderRLCenter" in javascript
    assert "askRLAdvisor" in javascript
    assert "handleRLCenterAction" in javascript


def test_intelligence_hub_has_visible_entry_and_seven_priority_runtime() -> None:
    html, javascript = _read_frontend()

    assert 'id="intelligenceHubBtn"' in html
    assert 'data-action="intelligence-hub"' in html
    assert 'data-agent-target="intelligence-hub"' in html
    assert 'id="ragEvaluationBtn"' in html
    assert 'data-action="rag-evaluation"' in html
    assert 'data-agent-target="rag-evaluation"' in html
    assert 'data-hub-section="evaluation"' in javascript
    assert "openIntelligenceHub" in javascript
    assert "runHubDemo" in javascript
    assert "runHubEvaluation" in javascript
    assert "submitHubFeedback" in javascript
    assert "seven_priorities" in javascript
    assert "BM25 Hit@5" in javascript
    assert "Hybrid Hit@5" in javascript
    assert "IMPLEMENTED" in javascript
    assert "固定发布报告（非本进程重跑）" in javascript


def test_frontend_does_not_present_missing_site_data_as_live_or_safe() -> None:
    html, javascript = _read_frontend()

    assert "实时运营概况" not in html
    assert "能耗实时指标" not in html
    assert "现场告警未接入 · 不计算健康分" in javascript
    assert 'waitingForPort ? "—"' in javascript
    assert "未用零告警冒充安全" in javascript
    assert "production_authority=false" in javascript
    assert "规则回退" in javascript
    assert "openCompetitiveBenchmark" in javascript


def test_frontend_exposes_calibrated_realtime_simulator_without_calling_it_live() -> None:
    html, javascript = _read_frontend()

    assert 'id="realtimeSimulatorPanel"' in html
    assert "公开数据校准实时模拟" in html
    assert "不是现场实测" in html
    assert "/api/port-simulator/snapshot" in javascript
    assert "/api/port-simulator/stream" in javascript
    assert "/api/port-simulator/contract" in javascript
    assert "physical_dispatch_performed" in javascript
    assert "production_authority" in javascript
    assert "connectSimulatorStream" in javascript



def test_four_system_linkage_has_visible_entry_and_execution_controls() -> None:
    html, javascript = _read_frontend()

    assert 'id="systemLaunchHubBtn"' in html
    assert 'data-action="system-linkage"' in html
    assert 'data-agent-target="system-linkage"' in html
    assert "SYSTEM_LINKAGE_CATALOG" in javascript
    assert 'data-linkage-run="all"' in javascript
    assert 'data-linkage-start="all"' in javascript
    assert "runSystemLinkage" in javascript
    assert "openLinkedSystem" in javascript


def test_professional_catalog_has_visible_entry_and_interactive_filters() -> None:
    html, javascript = _read_frontend()

    assert 'data-action="knowledge-catalog"' in html
    assert 'data-agent-target="knowledge-catalog"' in html
    assert "openKnowledgeCatalog" in javascript
    assert "renderKnowledgeCatalogResults" in javascript
    assert 'data-catalog-status="indexed"' in javascript
    assert 'data-catalog-status="partial"' in javascript
    assert 'data-catalog-status="planned"' in javascript
    assert "data-catalog-search" in javascript


def test_live_data_boundary_answer_is_not_replaced_by_generic_refusal() -> None:
    _, javascript = _read_frontend()

    assert 'data.refusal_reason === "live_data_connection_required"' in javascript
    assert "const answer = data.answer" in javascript
    assert "证据策略：" not in javascript
    assert "实时数据待接入" in javascript
    assert "未使用沙箱数值" in javascript


def test_chat_request_sends_strict_evidence_flag() -> None:
    _, javascript = _read_frontend()

    assert re.search(
        r"body\s*:\s*JSON\.stringify\(\{[^)]*\bstrict_evidence\s*:",
        javascript,
        flags=re.DOTALL,
    ), "聊天请求必须在 JSON body 中显式传递 strict_evidence"


def test_chat_surfaces_decision_readiness_and_evidence_conflict() -> None:
    _, javascript = _read_frontend()

    assert "readinessLabel" in javascript
    assert "data.decision_readiness" in javascript
    assert "data.evidence_health" in javascript
    assert "证据冲突·待裁决" in javascript
    assert "模型已正常回答；本地证据不足提醒已附在答案底部" in javascript


def test_chat_surfaces_claim_alignment_and_numeric_integrity() -> None:
    _, javascript = _read_frontend()

    assert "data.answer_verification" in javascript
    assert "主张对齐" in javascript
    assert "主张词面对齐" in javascript
    assert "数字/日期/量值完整性" in javascript
    assert "verification.scope_notice" in javascript


def test_frontend_uses_persistent_session_and_session_only_access_token() -> None:
    _, javascript = _read_frontend()

    assert "xiaoyi_session_id_v1" in javascript
    assert "session_id:state.sessionId" in javascript
    assert "/api/conversations/" in javascript
    assert 'sessionStorage.getItem("xiaoyi_access_token")' in javascript
    assert 'localStorage.setItem("xiaoyi_access_token"' not in javascript
    assert "response.body.getReader()" in javascript
    assert 'eventName === "token"' in javascript
    assert 'eventName === "done"' in javascript
    assert "xiaoyi_conversation_turns_v2" in javascript
    assert "conversationTranscript" in javascript
    assert "beginNewConversation" in javascript
    assert "data-conversation-id" in javascript


def test_all_new_chat_answers_use_visible_typewriter_rendering() -> None:
    html, javascript = _read_frontend()
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "function createAnswerTypewriter(runId)" in javascript
    assert "async function typeAnswer(text, runId, delayMs = 18)" in javascript
    assert "function startThinkingTicker(runId)" in javascript
    assert "已等待" not in javascript
    assert "performance.now() - startedAt" not in javascript
    assert "混合生成服务仍在运行" in javascript
    assert "调用本地生成模型进行综合分析" in javascript
    assert "持续接收模型结果并检查关键事实" in javascript
    assert "选择低延迟证据回答或本地生成模型" not in javascript
    assert "stopThinking()" in javascript
    assert "streamedAnswer += text" in javascript
    assert "answerWriter.push(text)" not in javascript
    assert "await answerWriter.finish(answer)" not in javascript
    assert "await typeAnswer(answer, runId, 24)" in javascript
    assert "await typeAnswer(planAnswer, runId)" in javascript
    assert "void typeAnswer(answer, state.generationId)" in javascript
    assert "function setAskButtonGenerating(active)" in javascript
    assert "function cancelGenerationOnServer(generationId)" in javascript
    assert 'headers.set("X-Xiaoyi-Generation-Id", generationId)' in javascript
    assert "/api/chat/generations/" in javascript
    assert "state.activeGenerationId = serverGenerationId" in javascript
    assert 'active ? "停止生成" : "发送"' in javascript
    assert "可以立即重新提问" in javascript
    assert 'id="responseStatus" hidden aria-hidden="true"' in html
    assert "stop-label" not in html
    assert re.search(
        r"\.answer\.thinking\{[^}]*min-height:104px;[^}]*overflow:hidden;"
        r"[^}]*contain:layout paint",
        styles,
    )
    assert re.search(
        r"\.send-button\{[^}]*width:36px;[^}]*height:36px;[^}]*"
        r"border-radius:50%",
        styles,
    )
    assert re.search(
        r"\.send-button\.generating\{[^}]*width:36px;[^}]*height:36px;[^}]*"
        r"background:linear-gradient\(145deg,#d94e61,#9e263b\)",
        styles,
    )
    assert "function scrollConversationToLatestAnswer" in javascript
    assert "scrollConversationToLatestAnswer({ settle:true })" in javascript
    assert 'latestAnswer.scrollIntoView({' in javascript
    assert 'block:"end"' in javascript
    assert "function renderStructuredAnswer" in javascript
    assert "function isUrgentEvidenceAnswer" in javascript
    assert "answer-evidence-line" in javascript
    assert ".answer-evidence-line.normal{color:#69e1ae" in styles
    assert ".answer-evidence-line.danger{color:#ff7f8d" in styles


def test_chat_buffers_stream_and_atomically_displays_verified_answer() -> None:
    _, javascript = _read_frontend()

    completed = javascript.index("const data = result.data;")
    intent_update = javascript.index("state.currentIntent = data.intent;", completed)
    finish = javascript.index("await typeAnswer(answer, runId, 24)", completed)

    assert completed < intent_update < finish
    assert "融合分析与证据校验已完成，正在统一输出完整答案" in javascript
    assert "证据检索已完成，正在生成并校验完整答案" in javascript
    assert "streamedAnswer += text" in javascript
    assert (
        'data.intent === "identity" ? "身份与能力介绍已完成 · 本机生成模型参与表达"'
        in javascript
    )


def test_submitted_chat_clears_input_and_hero_bubble_points_to_avatar() -> None:
    _, javascript = _read_frontend()
    styles = STYLES_CSS.read_text(encoding="utf-8")

    validation = javascript.index("if (question.length < 2)")
    clear_input = javascript.index('$("#question").value = "";', validation)
    begin_generation = javascript.index("stopGeneration(false);", validation)
    assert validation < clear_input < begin_generation
    assert re.search(
        r"\.voice-bubble::after\{[^}]*right:27px;[^}]*"
        r"border-right-color:#0c5388",
        styles,
    )
    assert not re.search(
        r"\.voice-bubble::after\{[^}]*left:27px",
        styles,
    )


def test_non_energy_operator_answer_hides_unrelated_energy_kpis() -> None:
    _, javascript = _read_frontend()

    assert '$("#responseKpis").hidden = !["energy_analysis", "energy_carbon"].includes(data.intent)' in javascript
    assert 'intent === "operator_runtime_assist"' in javascript
    assert 'return "当前运营态势研判"' in javascript


def test_legacy_simulation_and_hardcoded_knowledge_counts_are_gone() -> None:
    html, javascript = _read_frontend()

    for legacy_symbol in ("taskConfirmed", "createLocalTask", "localAdvance"):
        assert re.search(rf"\b{legacy_symbol}\b", javascript) is None, (
            f"app.js 不应残留旧模拟分支 {legacy_symbol}"
        )

    assert re.search(r"\|\|\s*46\b", javascript) is None, (
        "知识文件数量不得在失败分支回退为 46"
    )
    assert re.search(r"\b326\b", javascript) is None, (
        "app.js 不得硬编码知识片段数量 326"
    )
    assert re.search(r"\b326\b", html) is None, (
        "index.html 不得硬编码知识片段数量 326"
    )


def test_frontend_does_not_boot_with_showcase_only_business_results() -> None:
    html, javascript = _read_frontend()

    for hardcoded_result in ("1,235.6", "356.7", "预计降低峰值能耗 3.2%"):
        assert hardcoded_result not in html
        assert hardcoded_result not in javascript

    assert "生成泊位调度优化方案" not in html
    assert "生成泊位调度优化方案" not in javascript
    assert "生成泊位调度候选建议" in javascript


def test_backend_visual_target_is_not_used_as_a_selector() -> None:
    _, javascript = _read_frontend()

    visual_target_expression = (
        r"(?:action\s*(?:\.\s*(?:visual_target|visualTarget)"
        r"|\[\s*['\"]visual_target['\"]\s*\])"
        r"|(?:visual_target|visualTarget))"
    )
    selector_sinks = {
        "guidedFocus": rf"guidedFocus\s*\(\s*{visual_target_expression}",
        "querySelector": (
            rf"querySelector(?:All)?\s*\(\s*{visual_target_expression}"
        ),
        "DOM helper": rf"\$\$?\s*\(\s*{visual_target_expression}",
        "closest": rf"\.closest\s*\(\s*{visual_target_expression}",
    }

    violations = [
        sink
        for sink, pattern in selector_sinks.items()
        if re.search(pattern, javascript) is not None
    ]
    assert not violations, (
        "后端 visual_target 只能作为语义标识，不能直接进入 selector sink: "
        f"{violations}"
    )

    # Require a semantic action dispatcher with a meaningful local whitelist.
    assert "executeSemanticAction" in javascript
    allowed_kind_checks = set(
        re.findall(r"action\.kind\s*===\s*['\"]([^'\"]+)['\"]", javascript)
    )
    assert len(allowed_kind_checks) >= 5, (
        "智能操作应通过本地 action.kind 白名单分派，而不是执行后端选择器"
    )


def test_completed_automation_reveals_result_but_risky_action_keeps_confirmation() -> None:
    _, javascript = _read_frontend()

    assert "function revealCompletedAutomationResult(plan)" in javascript
    assert 'plan.status !== "completed"' in javascript
    assert "hasUnconfirmedRisk" in javascript
    assert "revealCompletedAutomationResult(state.automationPlan)" in javascript
    assert 'state.automationPlan.status === "awaiting_confirmation"' in javascript
    assert "await requestAutomationConfirmation()" in javascript
    assert 'openModal("审核生产操作建议"' in javascript


def test_system_status_exposes_site_admission_and_industry_gap_evidence() -> None:
    javascript = (ROOT / "web/app.js").read_text(encoding="utf-8")
    assert "/api/system/site-admission" in javascript
    assert "现场准入与漂移门禁" in javascript
    assert "dual_approval_verified=false" in javascript
    assert "/api/system/competitive-benchmark" in javascript


def test_simulator_and_linked_system_launchers_use_distinct_frontend_routes() -> None:
    _, javascript = _read_frontend()

    assert 'api("/api/sailing-simulator/launch"' in javascript
    assert 'target:"sailing-simulator"' in javascript
    assert 'api("/api/linked-systems/launch"' in javascript
    assert '"port-dt-multi":"港口数字孪生"' in javascript
    assert "window.location.assign(runtime.url)" in javascript
