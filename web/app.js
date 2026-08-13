(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const BILINGUAL_TEXT = new Map(Object.entries({
    "智能助手":"INTELLIGENCE COPILOT",
    "智能对话":"AI Dialogue", "决策建议":"Decision Advisory", "数据分析":"Data Analytics",
    "知识库":"Knowledge Base", "港航知识库":"Maritime Knowledge Base", "训练中心":"Training Center", "任务中心":"Action Center",
    "管理员":"Administrator", "小懿AI":"Xiaoyi AI", "您的港航智能助手":"Your Maritime Intelligence Copilot",
    "新建对话":"New Dialogue", "对话历史":"Dialogue History", "常用指令":"Quick Commands",
    "我的收藏":"Favorites", "接口中心":"Connector Center", "智能联动中心":"Intelligence Hub", "四系统联动":"Four-System Linkage", "RAG评测闭环":"RAG Evaluation Loop", "推荐指令":"Recommended Prompts",
    "今日港口运营概况":"Today's Port Operations", "碳排放分析与建议":"Carbon Analysis & Advice",
    "船舶调度优化方案":"Vessel Scheduling Optimization", "岸桥作业效率分析":"Quay Crane Efficiency",
    "异常事件预警汇总":"Alert Summary", "深海模式":"Deep Sea Mode", "极夜模式":"Midnight Mode",
    "沉浸式港航驾驶舱":"Immersive Maritime Cockpit", "智能巡检流程":"Agentic Inspection",
    "上午好！":"Good Morning!", "下午好！":"Good Afternoon!", "晚上好！":"Good Evening!",
    "我是小懿AI":"I am Xiaoyi AI", "智能问答":"Intelligent Q&A", "解答港航运营相关问题":"Maritime operations expertise",
    "多维数据分析与可视化":"Multidimensional analytics and visualization",
    "提供优化建议与决策支持":"Optimization and decision support", "报告生成":"Report Generation",
    "自动生成分析报告":"Generate analytical reports automatically", "运营沙箱":"Operations Sandbox", "动态沙箱":"Dynamic Sandbox",
    "等待验证":"Awaiting Verification", "运营沙箱快照":"Operations Sandbox Snapshot", "已完成运营数据分析":"Operations Analysis Completed",
    "不适用":"Not Applicable", "非生产数据":"Non-production Data", "理解意图":"Understand", "检索知识":"Retrieve Knowledge",
    "组织回答":"Compose Response", "今日能耗概况":"Today's Energy Overview", "运营快照":"Operations Snapshot",
    "总能耗":"Total Energy", "综合能耗":"Total Energy", "碳排放总量":"Carbon Emissions",
    "碳排放":"Carbon Emissions", "单位吞吐能耗":"Energy per Throughput", "碳强度":"Carbon Intensity",
    "岸电使用率":"Shore Power Usage", "岸电利用率":"Shore Power Utilization",
    "证据覆盖度":"Evidence Coverage", "来源质量":"Source Quality", "依据与来源":"Evidence & Sources",
    "置信度":"Confidence", "高":"High", "中":"Medium", "提示":"Notice",
    "生成详细报告":"Generate Detailed Report", "帮我逐步分析":"Analyze Step by Step", "能耗趋势预测":"Energy Forecast",
    "智能操作":"Agentic Mode", "智能操作已开启":"Agentic Mode On", "智能操作已关闭":"Agentic Mode Off",
    "专业":"Expert", "回答模式":"Response Mode", "专业问答":"Expert Q&A", "运营问答":"Operations Q&A",
    "简报摘要":"Executive Brief", "检索证据数":"Evidence Count", "严格证据":"Strict Evidence",
    "专业知识仅使用已验证索引":"Use verified indexed knowledge only",
    "证据不足时明确拒答，不使用未验证内容补全结论。":"Decline when evidence is insufficient; never fill gaps with unverified content.",
    "调整会应用到下一次提问。":"Changes apply to the next question.",
    "小懿AI 可能会生成不准确的信息，生产系统操作需由授权人员确认。":"AI may be inaccurate. Production actions require authorized confirmation.",
    "您好！我是小懿AI":"Hello! I am Xiaoyi AI", "本机应用可用":"Local App Available", "切换形象":"Switch Avatar",
    "生成智能方案":"Generate AI Plan", "今日决策焦点":"Today's Decision Focus", "已按影响度与紧迫性排序":"Ranked by impact and urgency",
    "风险态势":"Risk Posture", "当前 4 项运营提醒":"4 active operational alerts", "综合运行指数":"Composite Operations Index",
    "建议执行链":"Recommendation Workflow", "先分析，再确认，后执行":"Analyze, confirm, then execute",
    "识别目标":"Identify Objective", "完成业务意图解析":"Business intent parsed", "评估约束":"Evaluate Constraints",
    "泊位、岸桥、时窗与风险":"Berths, cranes, windows and risks", "生成方案":"Generate Options",
    "输出多个候选策略":"Produce multiple candidate strategies", "人工确认":"Human Confirmation", "授权后才可下发":"Dispatch only after authorization",
    "运营、能耗、碳排与设备态势一屏联动":"Unified operations, energy, carbon and equipment intelligence",
    "今日":"Today", "7日":"7 Days", "30日":"30 Days", "港区能耗与碳排趋势":"Port Energy & Carbon Trend",
    "数据同步中":"Syncing Data", "能效构成":"Energy Efficiency Mix", "重点用能单元分析":"Key energy-consuming units",
    "岸桥设备":"Quay Cranes", "水平运输":"Horizontal Transport", "堆场照明":"Yard Lighting", "冷藏箱区":"Reefer Yard",
    "让小懿深度分析":"Deep Analysis with Xiaoyi", "专业目录":"Professional Catalog", "来源审计":"Source Audit",
    "知识全景":"Knowledge Panorama", "份专业文档":"professional documents", "个索引片段":"indexed chunks", "个官方来源":"official sources",
    "知识文件":"Knowledge Files", "全部文档":"All Documents", "港航知识全景":"Maritime Knowledge Panorama",
    "覆盖港航专业领域、业务流程与可核验知识来源":"Maritime domains, workflows and verifiable sources",
    "展开查看":"Explore", "新建智能任务":"New AI Task", "智能任务模板":"AI Task Templates",
    "点击即可创建可视化执行流程":"Create a visual workflow in one click", "执行记录":"Execution History",
    "每一步均保留时间与结果":"Every step retains its time and result", "运营沙箱":"Operations Sandbox",
    "现场运营接入状态":"Site Operations Connection", "查看更多":"View More", "现场能耗接入状态":"Site Energy Connection",
    "预警与提醒":"Alerts & Notifications", "能源管理":"Energy Management", "设备管理":"Asset Management",
    "港口运营":"Port Operations", "航运调度":"Shipping & Scheduling", "政策法规":"Policies & Regulations",
    "行业标准":"Industry Standards", "案例分析":"Case Studies", "智能任务":"AI Task",
    "逐步执行 · 全程可追溯":"Stepwise Execution · Fully Traceable", "详情":"Details",
    "当前在港船舶":"Vessels in Port", "今日累计吞吐量":"Today's Throughput", "岸桥作业利用率":"Quay Crane Utilization",
    "AGV 在线率":"AGV Online Rate", "高能耗预警":"High Energy Alert", "碳排放预警":"Carbon Alert",
    "设备预警":"Equipment Alert", "天气提醒":"Weather Notice", "让小懿执行":"Execute with Xiaoyi",
    "高优先级":"High Priority", "中优先级":"Medium Priority", "建议":"Recommended",
    "暂无趋势数据":"No trend data", "正在绘制趋势...":"Rendering trend…", "更新时间":"Updated",
    "分析今日港口能耗":"Analyze Today's Port Energy", "生成泊位调度候选建议":"Generate Berth Schedule Candidates",
    "生成港口运营日报":"Generate Daily Operations Report", "辅助处置运营预警":"Assist Alert Response",
    "读取指标、比对基线、定位异常并形成节能建议。":"Read metrics, compare baselines, locate anomalies and propose savings.",
    "结合船期、泊位占用和岸桥资源生成调度建议。":"Generate scheduling advice from vessel, berth and crane constraints.",
    "归并告警、查询 SOP、生成处置步骤并保留审计记录。":"Correlate alerts, retrieve SOPs and retain an audit trail.",
    "汇总运营、能耗、设备与预警，生成管理简报。":"Summarize operations, energy, assets and alerts for management.",
    "分钟":"min", "低风险":"Low Risk", "需确认":"Confirmation Required", "高风险":"High Risk",
    "暂无执行记录":"No Execution History", "选择左侧模板，小懿会逐步展示执行过程":"Select a template to view each execution step",
    "已完成":"Completed", "执行中":"In Progress", "查看步骤":"View Steps", "待接入":"Pending Integration",
    "真实在线":"Live", "待配置":"Pending Setup", "运行模式":"Operating Mode", "认证方式":"Authentication",
    "接口详情":"Connector Details", "健康检查":"Health Check", "取消":"Cancel", "保存设置":"Save Settings",
    "系统设置":"System Settings", "视觉主题":"Visual Theme", "默认回答模式":"Default Response Mode",
    "系统状态":"System Status", "就绪":"Ready", "异常":"Exception", "可检索":"Searchable", "需检查":"Check Required",
    "管理员工作台":"Administrator Workspace", "当前角色":"Current Role", "生产安全边界":"Production Safety Boundary",
    "当前知识索引":"Current Knowledge Index", "在线":"Online", "切换小懿形象":"Switch Xiaoyi Avatar",
    "领航员小懿":"Navigator Xiaoyi", "分析师小懿":"Analyst Xiaoyi", "收藏回答":"Save Response",
    "生成报告":"Generate Report", "转为智能任务":"Convert to AI Task", "回答操作":"Response Actions",
    "AGV能耗联合优化":"AGV Energy Optimization", "AGV充换电与能耗联合优化":"AGV Charging & Energy Optimization",
    "极端天气联合调度":"Extreme Weather Scheduling", "多智能体协同优化":"Multi-Agent Coordination",
    "真实训练与证据中心":"Reproducible Training & Evidence", "算法矩阵":"Algorithm Matrix",
    "小懿训练顾问":"Xiaoyi Training Advisor", "小懿全系统助手":"Xiaoyi System Copilot"
  }));
  const BILINGUAL_PLACEHOLDERS = new Map([
    ["请输入您的问题...", "请输入问题 / Ask Xiaoyi"],
    ["搜索港口运营、航运调度、岸电、TOS、安全应急...", "搜索港航知识 / Search maritime knowledge"],
    ["搜索大类、主题、子主题、权威机构或资料族", "搜索专业目录 / Search catalog"]
  ]);
  let bilingualRefreshQueued = false;
  const bilingualRefreshRoots = new Set();

  function normalizeBilingualText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function displayEvidenceMarkers(value) {
    return String(value || "").replace(/\[E(\d+)\]/g, "[来源$1]");
  }

  function isUrgentEvidenceAnswer(question, answer) {
    return /(?:着火|失火|起火|火灾|冒烟|爆炸|泄漏|溢油|触电|伤亡|受伤|碰撞|事故|危险品|紧急|应急|报警|疏散|警戒)/.test(
      `${question || ""}\n${answer || ""}`
    );
  }

  function renderStructuredAnswer(target, value, question = "", intent = "") {
    if (!target) return;
    const displayed = displayEvidenceMarkers(value);
    const urgent = isUrgentEvidenceAnswer(question, displayed);
    const fragment = document.createDocumentFragment();
    let inEvidenceBlock = false;
    displayed.split("\n").forEach((line, index, lines) => {
      const trimmed = line.trim();
      if (trimmed.startsWith("证据锁定结论：")) inEvidenceBlock = true;
      if (
        trimmed.startsWith("模型综合建议（需人工复核）：")
        || trimmed.startsWith("生成式综合分析")
      ) {
        inEvidenceBlock = false;
      }
      const text = document.createElement("span");
      const cited = /\[来源\d+\]/.test(line);
      const evidenceLine = inEvidenceBlock || cited;
      if (evidenceLine) {
        text.className = `answer-evidence-line ${urgent ? "danger" : "normal"}`;
        if (trimmed.startsWith("证据锁定结论：")) {
          text.classList.add("answer-evidence-heading");
        }
      } else if (trimmed.startsWith("模型综合建议（需人工复核）：")) {
        text.className = "answer-model-heading";
      } else if (intent === "energy_carbon" && trimmed) {
        text.className = "answer-general-line";
      }
      text.textContent = line;
      fragment.append(text);
      if (index < lines.length - 1) fragment.append(document.createTextNode("\n"));
    });
    target.replaceChildren(fragment);
  }

  function refreshBilingualLayer(root = document) {
    const nodes = root === document ? [...document.body.querySelectorAll("*")] : [root, ...(root.querySelectorAll?.("*") || [])];
    nodes.forEach((element) => {
      if (!(element instanceof HTMLElement) || element.closest("svg") || element.closest("[data-no-bilingual]") || ["SCRIPT","STYLE","OPTION"].includes(element.tagName)) return;
      if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
        const translated = BILINGUAL_PLACEHOLDERS.get(element.getAttribute("placeholder") || "");
        if (translated) element.setAttribute("placeholder", translated);
      }
      if (element instanceof HTMLTextAreaElement) return;
      const directText = normalizeBilingualText([...element.childNodes].filter((node) => node.nodeType === Node.TEXT_NODE).map((node) => node.textContent).join(" "));
      const english = BILINGUAL_TEXT.get(directText);
      const current = element.querySelector(":scope > .bi-english[data-auto-bilingual]");
      if (english) {
        const label = current || document.createElement("small");
        label.className = "bi-english";
        label.dataset.autoBilingual = "true";
        label.setAttribute("aria-hidden", "true");
        label.textContent = english;
        if (!current) element.append(label);
      } else if (current) {
        current.remove();
      }
    });
  }

  function queueBilingualRefresh(root = document.body) {
    if (root?.isConnected) bilingualRefreshRoots.add(root);
    if (bilingualRefreshQueued) return;
    bilingualRefreshQueued = true;
    queueMicrotask(() => {
      bilingualRefreshQueued = false;
      const roots = [...bilingualRefreshRoots];
      bilingualRefreshRoots.clear();
      roots.forEach((pendingRoot) => refreshBilingualLayer(pendingRoot));
    });
  }

  function initBilingualLayer() {
    refreshBilingualLayer(document);
    new MutationObserver((mutations) => mutations.forEach((mutation) => {
      const target = mutation.target?.isConnected ? mutation.target : document.body;
      queueBilingualRefresh(target.nodeType === Node.ELEMENT_NODE ? target : target.parentElement);
    })).observe(document.body, { childList:true, characterData:true, subtree:true });
  }
  const STORAGE = {
    topics: "xiaoyi_topic_history_v1",
    favorites: "xiaoyi_favorites_v1",
    theme: "xiaoyi_theme_v2",
    avatar: "xiaoyi_avatar_v1",
    agentMode: "xiaoyi_agent_mode_v1",
    strictEvidence: "xiaoyi_strict_evidence_v1",
    sessionId: "xiaoyi_session_id_v1",
    turns: "xiaoyi_conversation_turns_v2"
  };

  function createSessionId() {
    return `web-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
  }

  const persistentSessionId = localStorage.getItem(STORAGE.sessionId)
    || createSessionId();
  localStorage.setItem(STORAGE.sessionId, persistentSessionId);

  const fallbackDashboard = {
    data_mode: "offline",
    data_notice: "等待接入港口：当前仅保留界面结构，不展示或推断现场数值。",
    updated_at: new Date().toISOString(),
    overview: {
      metrics: [
        { id: "vessels-in-port", label: "当前在港船舶", display_value: "--", trend_percent: 0, status: "warning" },
        { id: "teu-throughput", label: "今日累计吞吐量", display_value: "--", trend_percent: 0, status: "warning" },
        { id: "berth-utilization", label: "岸桥作业利用率", display_value: "--", trend_percent: 0, status: "warning" },
        { id: "agv-online-rate", label: "AGV 在线率", display_value: "--", trend_percent: 0, status: "warning" }
      ]
    },
    energy: {
      range: "today",
      updated_at: new Date().toISOString(),
      summary: {
        total_energy_mwh: 0, carbon_emissions_tco2e: 0, carbon_intensity_kgco2e_per_teu: 0,
        shore_power_utilization_percent: 0, energy_change_percent: 0, carbon_change_percent: 0,
        intensity_change_percent: 0, shore_power_change_percent: 0
      },
      series: Array.from({length:13}, (_, index) => ({
        timestamp: `${String(index * 2).padStart(2, "0")}:00`, energy_mwh: 0,
        carbon_emissions_tco2e: 0, baseline_mwh: 0
      })),
      insights: ["运营数据接口不可用，未展示现场数值。"]
    },
    alerts: {
      total: 0, critical: 0, warning: 0, info: 0, items: []
    },
    quick_actions: [
      { id:"energy-analysis", title:"分析今日港口能耗", description:"定位异常时段并生成建议", task_template_id:"analyze-energy" },
      { id:"berth-optimization", title:"生成泊位调度候选建议", description:"识别冲突并生成可复核的启发式候选", task_template_id:"optimize-berth" },
      { id:"daily-report", title:"生成港口运营日报", description:"汇总运营、设备与预警信息", task_template_id:"generate-daily-report" }
    ],
    knowledge_categories: ["港口运营","航运调度","能源管理","设备管理","政策法规","行业标准"]
  };

  function withoutUnverifiedOperationalValues(data) {
    const live = data?.source_metadata?.data_mode === "live"
      && data?.source_metadata?.live_data_verified === true;
    if (live) return data;
    const calibratedSimulation = data?.source_metadata?.source_type === "public_data_calibrated_simulation";
    if (calibratedSimulation) return { ...data, public_calibrated_simulation:true, public_open_source_waiting:false };
    const overview = data?.overview || fallbackDashboard.overview;
    const energy = data?.energy || fallbackDashboard.energy;
    return {
      ...data,
      data_notice: "等待接入港口：TOS、AIS、EMS、EAM 或 VTS 适配器尚未通过现场验证。",
      public_open_source_waiting: true,
      overview: {
        ...overview,
        metrics: (overview.metrics || fallbackDashboard.overview.metrics).map((item) => ({
          ...item,
          value: 0,
          display_value: "等待接入港口",
          trend_percent: null,
          trend: "flat",
          status: "warning"
        }))
      },
      energy: {
        ...energy,
        public_open_source_waiting: true,
        summary: fallbackDashboard.energy.summary,
        series: [],
        insights: ["等待接入港口：配置并验证 EMS、TOS 与岸电计量适配器后显示现场趋势。"]
      },
      alerts: {
        ...(data?.alerts || {}),
        total: 0,
        critical: 0,
        warning: 0,
        info: 0,
        items: []
      }
    };
  }

  const fallbackTemplates = [
    { id:"analyze-energy", title:"分析今日港口能耗", description:"读取指标、比对基线、定位异常并形成节能建议。", estimated_minutes:3, risk_level:"low", requires_human_confirmation:false, steps:["读取今日能耗与碳排数据","对比历史基线与作业量","定位异常时段和设备","生成调度与节能建议","形成可追溯分析结论"] },
    { id:"optimize-berth", title:"生成泊位调度候选建议", description:"结合船期、泊位占用和岸桥资源生成可复核的启发式候选建议。", estimated_minutes:5, risk_level:"medium", requires_human_confirmation:true, steps:["汇总 ETA、ETB 与泊位占用","识别船期冲突和等待风险","计算岸桥与拖轮资源窗口","生成候选调度方案","等待调度员确认后导出方案"] },
    { id:"handle-alert", title:"辅助处置运营预警", description:"归并告警、查询 SOP、生成处置步骤并保留审计记录。", estimated_minutes:4, risk_level:"high", requires_human_confirmation:true, steps:["读取并归并关联告警","评估影响范围与风险等级","检索对应 SOP 和责任岗位","生成逐项处置建议","等待值班负责人确认执行"] },
    { id:"generate-daily-report", title:"生成港口运营日报", description:"汇总运营、能耗、设备与预警，生成管理简报。", estimated_minutes:2, risk_level:"low", requires_human_confirmation:false, steps:["汇总当日运营关键指标","提取能耗与碳排趋势","整理设备和预警事件","生成管理层摘要与建议","输出结构化日报"] }
  ];

  const state = {
    view: "chat",
    dashboard: fallbackDashboard,
    energy: fallbackDashboard.energy,
    runtimeStatus: null,
    simulator: null,
    simulatorContract: null,
    simulatorEvents: [],
    simulatorEventSource: null,
    knowledge: { count: 0, files: [], default_top_k: 5, chunk_count: 0, official_verified_documents: 0 },
    knowledgeStatus: null,
    knowledgeSearchResults: [],
    knowledgeSearchRun: 0,
    knowledgeSearchTimer: null,
    knowledgeCatalog: null,
    knowledgeCatalogStatus: "all",
    knowledgeCatalogQuery: "",
    connectors: null,
    pendingAttachment: null,
    templates: [],
    tasks: [],
    topics: loadArray(STORAGE.topics),
    favorites: loadArray(STORAGE.favorites),
    currentQuestion: "帮我分析一下今日港口的能耗情况",
    currentAnswer: $("#answer")?.textContent || "",
    currentEvidence: [],
    currentVerification: null,
    currentMode: "ops",
    currentIntent: "energy_analysis",
    currentConfidence: "高",
    activeController: null,
    activeGenerationId: null,
    generationId: 0,
    thinkingTickerStop: null,
    activeTask: null,
    activeReport: null,
    confirmedTaskIds: new Set(),
    autoRunning: false,
    tourRunning: false,
    agentMode: localStorage.getItem(STORAGE.agentMode) !== "false",
    automationPlan: null,
    automationContext: {},
    automationRunning: false,
    automationAbort: false,
    drawerMode: null,
    modalKind: null,
    pendingRLLabConfig: null,
    rlCenter: null,
    rlCenterLoading: false,
    rlAdvisorMessages: [],
    linkedStartup: null,
    systemLinkage: null,
    systemLinkageBusy: null,
    lastFocused: null,
    sessionId: persistentSessionId,
    conversationTurns: loadArray(STORAGE.turns).filter(
      (item) => item.sessionId === persistentSessionId
    )
  };

  function loadArray(key) {
    try {
      const value = JSON.parse(localStorage.getItem(key) || "[]");
      return Array.isArray(value) ? value.filter(Boolean) : [];
    } catch {
      return [];
    }
  }

  function persist(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
  }

  function formatNumber(value, digits = 1) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    return number.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function formatShortTime(value) {
    const date = value ? new Date(value) : new Date();
    if (Number.isNaN(date.getTime())) return "--:--";
    return `${String(date.getHours()).padStart(2,"0")}:${String(date.getMinutes()).padStart(2,"0")}`;
  }

  function formatDateTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("zh-CN", { month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hour12:false }).format(date);
  }

  async function api(path, options = {}) {
    const timeoutController = options.signal ? null : new AbortController();
    const timeoutDuration = Math.max(1000, Number(options.timeoutMs || 12000));
    const timeout = timeoutController ? setTimeout(() => timeoutController.abort(), timeoutDuration) : null;
    const method = String(options.method || "GET").toUpperCase();
    const headers = new Headers(options.headers || {});
    const accessToken = sessionStorage.getItem("xiaoyi_access_token");
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    headers.set("X-Xiaoyi-Trace-Id", globalThis.crypto?.randomUUID?.() || `trace-${Date.now()}`);
    if (!["GET", "HEAD"].includes(method)) {
      headers.set("X-Idempotency-Key", globalThis.crypto?.randomUUID?.() || `idem-${Date.now()}-${Math.random()}`);
    }
    try {
      const { timeoutMs: _timeoutMs, ...fetchOptions } = options;
      const response = await fetch(path, { ...fetchOptions, headers, signal:options.signal || timeoutController.signal });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = typeof data.detail === "string" ? data.detail : `请求失败 (${response.status})`;
        const error = new Error(detail);
        error.status = response.status;
        error.payload = data;
        throw error;
      }
      return data;
    } catch (error) {
      if (error.name === "AbortError" && !options.signal) throw new Error("请求超时，请检查服务连接");
      throw error;
    } finally {
      if (timeout) clearTimeout(timeout);
    }
  }

  async function streamChat(payload, signal, onToken, generationId) {
    const headers = new Headers({ "Content-Type":"application/json", "Accept":"text/event-stream" });
    const accessToken = sessionStorage.getItem("xiaoyi_access_token");
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    headers.set("X-Xiaoyi-Trace-Id", globalThis.crypto?.randomUUID?.() || `trace-${Date.now()}`);
    headers.set("X-Xiaoyi-Generation-Id", generationId);
    const response = await fetch("/api/chat/stream", {
      method:"POST", headers, signal, body:JSON.stringify(payload)
    });
    if (!response.ok) {
      const errorPayload = await response.json().catch(() => ({}));
      const error = new Error(typeof errorPayload.detail === "string" ? errorPayload.detail : `请求失败 (${response.status})`);
      error.status = response.status;
      error.payload = errorPayload;
      throw error;
    }
    if (!response.body) throw new Error("当前浏览器不支持服务器事件流");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let completed = null;
    const consume = (block) => {
      let eventName = "message";
      const dataLines = [];
      block.split(/\r?\n/).forEach((line) => {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      });
      if (!dataLines.length) return;
      const eventData = JSON.parse(dataLines.join("\n"));
      if (eventName === "token" && typeof eventData.text === "string") onToken(eventData.text);
      if (eventName === "done") completed = eventData;
    };
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream:!done });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() || "";
      blocks.forEach(consume);
      if (done) break;
    }
    if (buffer.trim()) consume(buffer);
    if (!completed) throw new Error("服务器事件流未返回完成事件");
    return completed;
  }

  async function cancelGenerationOnServer(generationId) {
    if (!generationId) return;
    const headers = new Headers();
    const accessToken = sessionStorage.getItem("xiaoyi_access_token");
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    headers.set("X-Xiaoyi-Trace-Id", globalThis.crypto?.randomUUID?.() || `trace-${Date.now()}`);
    await fetch(`/api/chat/generations/${encodeURIComponent(generationId)}`, {
      method:"DELETE",
      headers
    });
  }

  function safeUrl(value) {
    try {
      const url = new URL(String(value || ""));
      return ["https:", "http:"].includes(url.protocol) ? url.href : "";
    } catch {
      return "";
    }
  }

  function toast(title, message = "", type = "info", timeout = 3200) {
    const stack = $("#toastStack");
    const node = document.createElement("div");
    node.className = `toast ${type}`;
    node.innerHTML = `<i>${icon(type === "success" ? "check" : type === "warning" ? "alert" : "spark")}</i><div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(message)}</span></div><button type="button" aria-label="关闭">${icon("close")}</button>`;
    $("button", node).addEventListener("click", () => node.remove());
    stack.append(node);
    setTimeout(() => node.remove(), timeout);
  }

  function updateGreeting() {
    const hour = new Date().getHours();
    $("#greetingTitle").innerHTML = `${hour < 6 ? "夜深了" : hour < 12 ? "上午好" : hour < 18 ? "下午好" : "晚上好"}！<span>我是小懿AI</span>`;
  }

  function setView(view, options = {}) {
    if (!$( `.workspace-view[data-view="${view}"]`)) return;
    state.view = view;
    $$(".workspace-view").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
    $$(".top-nav .nav-item").forEach((node) => node.classList.toggle("active", node.dataset.viewTarget === view));
    if (view === "analytics") renderAnalytics(state.energy);
    if (view === "knowledge") renderKnowledge();
    if (view === "tasks") refreshTasks();
    if (view === "rl") void loadRLCenter();
    if (!options.silent && view !== "chat") {
      $("#heroSpeechTitle").textContent = { decisions:"正在评估决策约束", analytics:"正在联动运营数据", knowledge:"正在检索港航知识", rl:"正在核验训练证据", tasks:"正在跟踪智能任务" }[view] || "您好！我是小懿AI";
    }
  }

  function renderOverview(overview) {
    const iconMap = {
      "vessels-in-port": ["ship", ""],
      "teu-throughput": ["report", ""],
      "berth-utilization": ["chart", "green"],
      "agv-online-rate": ["agv", "amber"]
    };
    $("#overviewGrid").innerHTML = (overview?.metrics || []).map((metric) => {
      const [iconName, tone] = iconMap[metric.id] || ["chart", ""];
      const hasTrend = metric.trend_percent !== null
        && metric.trend_percent !== undefined
        && Number.isFinite(Number(metric.trend_percent));
      const direction = Number(metric.trend_percent) >= 0 ? "↑" : "↓";
      const trend = hasTrend ? `${direction} ${Math.abs(Number(metric.trend_percent)).toFixed(1)}%` : "趋势不适用";
      return `<div class="overview-metric"><span class="metric-icon ${tone}">${icon(iconName)}</span><div><span>${escapeHtml(metric.label)}</span><strong>${escapeHtml(metric.display_value)}</strong><em>${trend}</em></div></div>`;
    }).join("");
  }

  function renderAlerts(alerts) {
    const items = alerts?.items || [];
    $("#alertCount").textContent = String(alerts?.total ?? items.length);
    $("#notificationBadge").textContent = String(alerts?.total ?? items.length);
    $("#alertList").innerHTML = items.slice(0, 4).map((item) => {
      const label = item.title;
      return `<div class="alert-item"><span class="alert-level ${escapeHtml(item.level)}">${escapeHtml(label)}</span><time>${formatShortTime(item.occurred_at)}</time><button type="button" data-alert-id="${escapeHtml(item.id)}" title="${escapeHtml(item.message)}">${escapeHtml(item.message)}</button></div>`;
    }).join("");
  }

  function buildChart(data, host, large = false) {
    if (!host) return;
    const series = Array.isArray(data?.series) ? data.series : [];
    if (!series.length) {
      host.innerHTML = `<div class="chart-loading">暂无趋势数据</div>`;
      return;
    }
    const width = large ? 720 : 330;
    const height = large ? 290 : 175;
    const pad = large ? { l:44, r:18, t:16, b:32 } : { l:29, r:12, t:9, b:25 };
    const chartW = width - pad.l - pad.r;
    const chartH = height - pad.t - pad.b;
    const energy = series.map((point) => Number(point.energy_mwh));
    const carbon = series.map((point) => Number(point.carbon_emissions_tco2e));
    const maxEnergy = Math.max(...energy) * 1.08;
    const minEnergy = Math.min(0, Math.min(...energy) * .82);
    const maxCarbon = Math.max(...carbon) * 1.08;
    const x = (index) => pad.l + (series.length === 1 ? chartW / 2 : (index / (series.length - 1)) * chartW);
    const yEnergy = (value) => pad.t + chartH - ((value - minEnergy) / (maxEnergy - minEnergy || 1)) * chartH;
    const yCarbon = (value) => pad.t + chartH - (value / (maxCarbon || 1)) * chartH;
    const energyPoints = energy.map((value, index) => `${x(index).toFixed(1)},${yEnergy(value).toFixed(1)}`).join(" ");
    const carbonPoints = carbon.map((value, index) => `${x(index).toFixed(1)},${yCarbon(value).toFixed(1)}`).join(" ");
    const areaPoints = `${pad.l},${pad.t + chartH} ${energyPoints} ${pad.l + chartW},${pad.t + chartH}`;
    const gradId = `energy-gradient-${host.id || Math.random().toString(16).slice(2)}`;
    const grid = Array.from({ length: 5 }, (_, index) => {
      const yy = pad.t + (index / 4) * chartH;
      const value = Math.round(maxEnergy - (index / 4) * (maxEnergy - minEnergy));
      return `<line class="grid" x1="${pad.l}" y1="${yy}" x2="${pad.l+chartW}" y2="${yy}"/><text class="axis" x="${pad.l-5}" y="${yy+3}" text-anchor="end">${value.toLocaleString()}</text>`;
    }).join("");
    const labelEvery = Math.max(1, Math.ceil(series.length / (large ? 8 : 5)));
    const labels = series.map((point, index) => index % labelEvery === 0 || index === series.length - 1 ? `<text class="axis" x="${x(index)}" y="${height-7}" text-anchor="middle">${escapeHtml(shortChartLabel(point.timestamp, data.range))}</text>` : "").join("");
    const hitAreas = series.map((point, index) => {
      const hitW = Math.max(12, chartW / series.length);
      return `<rect data-chart-index="${index}" x="${x(index)-hitW/2}" y="${pad.t}" width="${hitW}" height="${chartH}" fill="transparent" tabindex="0" aria-label="${escapeHtml(point.timestamp)} 能耗 ${point.energy_mwh} MWh，碳排 ${point.carbon_emissions_tco2e} tCO₂e"/>`;
    }).join("");
    host.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="能耗与碳排趋势图"><defs><linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#22d4ff" stop-opacity=".55"/><stop offset="1" stop-color="#1677ff" stop-opacity="0"/></linearGradient></defs>${grid}<polygon class="energy-area" fill="url(#${gradId})" points="${areaPoints}"/><polyline class="energy-line" points="${energyPoints}"/><polyline class="carbon-line" points="${carbonPoints}"/>${labels}${hitAreas}</svg>`;
    const showTip = (target) => {
      const index = Number(target.dataset.chartIndex);
      const point = series[index];
      let tip = $(".chart-tooltip", host);
      if (!tip) { tip = document.createElement("div"); tip.className = "chart-tooltip"; host.append(tip); }
      const rect = target.getBoundingClientRect();
      const hostRect = host.getBoundingClientRect();
      tip.style.left = `${rect.left - hostRect.left + rect.width / 2}px`;
      tip.style.top = `${Math.max(48, rect.top - hostRect.top + 24)}px`;
      tip.innerHTML = `<strong>${escapeHtml(point.timestamp)}</strong>能耗：${formatNumber(point.energy_mwh)} MWh<br>碳排：${formatNumber(point.carbon_emissions_tco2e)} tCO₂e`;
    };
    $$('[data-chart-index]', host).forEach((target) => {
      target.addEventListener("mouseenter", () => showTip(target));
      target.addEventListener("focus", () => showTip(target));
    });
    host.addEventListener("mouseleave", () => $(".chart-tooltip", host)?.remove(), { once:true });
  }

  function shortChartLabel(value, range) {
    if (range === "today") return String(value).slice(0,5);
    const bits = String(value).split("-");
    return bits.length === 3 ? `${bits[1]}/${bits[2]}` : String(value).slice(0,5);
  }

  function applyEnergySummary(energy) {
    if (energy?.public_open_source_waiting) {
      $("#responseKpis").innerHTML = ["总能耗", "碳排放总量", "单位吞吐能耗", "岸电使用率"]
        .map((label) => `<div><span>${label}</span><strong>等待接入港口</strong><em class="down">未读取现场数据</em></div>`)
        .join("");
      return;
    }
    const s = energy?.summary || fallbackDashboard.energy.summary;
    const kpis = [
      ["总能耗", formatNumber(s.total_energy_mwh), "MWh", s.energy_change_percent],
      ["碳排放总量", formatNumber(s.carbon_emissions_tco2e), "tCO₂e", s.carbon_change_percent],
      ["单位吞吐能耗", formatNumber(s.carbon_intensity_kgco2e_per_teu), "kgCO₂e/TEU", s.intensity_change_percent],
      ["岸电使用率", formatNumber(s.shore_power_utilization_percent), "%", s.shore_power_change_percent]
    ];
    $("#responseKpis").innerHTML = kpis.map(([label, value, unit, trend]) => `<div><span>${label}</span><strong>${value} <small>${unit}</small></strong><em class="${Number(trend) <= 0 ? "down" : "up"}">${Number(trend) <= 0 ? "↓" : "↑"} ${Math.abs(Number(trend || 0)).toFixed(1)}%</em></div>`).join("");
  }

  function renderAnalytics(energy) {
    if (energy?.public_open_source_waiting) {
      $("#analyticsKpis").innerHTML = ["综合能耗", "碳排放", "碳强度", "岸电利用率"]
        .map((label, index) => `<div class="analytics-kpi" style="color:${["#22d4ff","#4ee58c","#f5a733","#8b78ff"][index]}"><span>${label}</span><strong>—</strong><small>等待接入港口</small><em>未读取现场数据</em></div>`)
        .join("");
      $("#analyticsUpdated").textContent = "等待接入港口 · 当前未读取生产数据";
      buildChart(energy, $("#largeEnergyChart"), true);
      $("#chartInsights").textContent = energy.insights?.[0] || "等待接入港口";
      return;
    }
    const s = energy?.summary || fallbackDashboard.energy.summary;
    const values = [
      ["综合能耗", formatNumber(s.total_energy_mwh), "MWh", s.energy_change_percent, "#22d4ff"],
      ["碳排放", formatNumber(s.carbon_emissions_tco2e), "tCO₂e", s.carbon_change_percent, "#4ee58c"],
      ["碳强度", formatNumber(s.carbon_intensity_kgco2e_per_teu), "kg/TEU", s.intensity_change_percent, "#f5a733"],
      ["岸电利用率", formatNumber(s.shore_power_utilization_percent), "%", s.shore_power_change_percent, "#8b78ff"]
    ];
    $("#analyticsKpis").innerHTML = values.map(([label,value,unit,trend,color]) => `<div class="analytics-kpi" style="color:${color}"><span>${label}</span><strong>${value}</strong><small>${unit}</small><em>${Number(trend)<=0?"↓":"↑"} ${Math.abs(Number(trend)).toFixed(1)}%</em></div>`).join("");
    const modeLabel = energy?.data_mode === "live" && energy?.source_metadata?.live_data_verified
      ? "生产实绩"
      : energy?.source_metadata?.source_type === "public_data_calibrated_simulation"
        ? "公开数据校准实时模拟"
        : energy?.data_mode === "operations_sandbox" ? "运营沙箱" : "接口离线";
    $("#analyticsUpdated").textContent = `更新时间 ${formatDateTime(energy?.updated_at || new Date())} · ${modeLabel}`;
    buildChart(energy, $("#largeEnergyChart"), true);
    $("#chartInsights").textContent = energy?.insights?.[0] || "当前综合能耗低于对比基线，建议持续保持岸电优先策略。";
    $$("#analyticsRange [data-range]").forEach((button) => button.classList.toggle("active", button.dataset.range === energy?.range));
  }

  function syncRuntimeBadge(metadata) {
    state.runtimeStatus = metadata || null;
    const badge = $("#runtimeStatusBadge");
    if (!badge) return;
    const live = metadata?.data_mode === "live" && metadata?.live_data_verified;
    const simulation = metadata?.source_type === "public_data_calibrated_simulation";
    badge.textContent = live ? "生产数据" : simulation ? "公开数据校准模拟" : "等待接入港口";
    badge.title = live
      ? `${metadata.source_system} · ${metadata.quality_code} · ${formatDateTime(metadata.observed_at)}`
      : simulation
        ? `${metadata.source_system} · ${metadata.quality_code} · 模拟数据，不是现场实测`
        : "等待接入港口：未验证的来源不会显示为现场实绩";
  }

  async function loadDashboard(silent = false) {
    try {
      const data = await api("/api/dashboard");
      state.dashboard = withoutUnverifiedOperationalValues(data);
      state.energy = state.dashboard.energy;
      syncRuntimeBadge(data.source_metadata);
    } catch (error) {
      state.dashboard = fallbackDashboard;
      state.energy = fallbackDashboard.energy;
      syncRuntimeBadge(null);
      if (!silent) toast("运营数据接口不可用", `${error.message}；界面不会回退为伪造现场数值。`, "warning", 4600);
    }
    renderOverview(state.dashboard.overview);
    renderAlerts(state.dashboard.alerts);
    buildChart(state.energy, $("#energyChart"));
    applyEnergySummary(state.energy);
    renderAnalytics(state.energy);
    renderDecisions();
    renderQuickKnowledge();
  }

  async function openRuntimeStatus() {
    let status = state.runtimeStatus;
    try { status = await api("/api/runtime/status"); syncRuntimeBadge(status); } catch (error) {
      openModal("运营数据来源", "数据接口当前不可用", `<div class="drawer-note"><strong>安全降级：</strong>${escapeHtml(error.message)}。界面不会使用静态数值冒充现场数据。</div>`, "", "runtime-status");
      return;
    }
    const isLive = status.data_mode === "live" && status.live_data_verified;
    const isSimulation = status.source_type === "public_data_calibrated_simulation";
    const modeLabel = isLive ? "生产实绩" : isSimulation ? "公开数据校准实时模拟" : "等待接入港口";
    openModal("运营数据来源", `${modeLabel} · ${formatDateTime(status.observed_at)}`, `<div class="settings-grid"><div class="setting-row"><div><strong>当前适配器</strong><span>${escapeHtml(status.source_adapter)} · ${escapeHtml(status.schema_version)}${status.telemetry_schema_version ? ` · ${escapeHtml(status.telemetry_schema_version)}` : ""}</span></div><span class="${isLive ? "status-pill" : "demo-badge"}">${isLive ? "LIVE" : isSimulation ? "SIM" : "PENDING"}</span></div><div class="setting-row"><div><strong>来源系统</strong><span>${escapeHtml(status.source_system)} · 港区代码 ${escapeHtml(status.port_code)}</span></div><span>${escapeHtml(status.source_type)}</span></div><div class="setting-row"><div><strong>数据质量</strong><span>观测时间 ${formatDateTime(status.observed_at)} · 延迟 ${status.latency_ms} ms</span></div><span class="status-pill">${escapeHtml(status.quality_code)} · ${(Number(status.quality_score) * 100).toFixed(0)}%</span></div><div class="setting-row"><div><strong>场景与复现</strong><span>${escapeHtml(status.simulation_run_id || "非模拟源")} · seed=${escapeHtml(status.simulation_seed ?? "不适用")} · sequence=${escapeHtml(status.stream_sequence ?? "不适用")}</span></div><span>${escapeHtml(status.scenario_id || "不适用")}</span></div><div class="setting-row"><div><strong>生产替换边界</strong><span>保持 port-realtime.v1 / port-ops.v1 契约，替换适配器即可；生产写权限独立准入。</span></div><span>${isLive ? "已验证" : "现场待替换"}</span></div><div class="drawer-note"><strong>真实性声明：</strong>${escapeHtml(status.data_notice || "来源声明缺失")}</div><div class="drawer-note"><strong>权限：</strong>sandbox_dispatch_allowed=${String(status.sandbox_dispatch_allowed === true)}；physical_dispatch_allowed=${String(status.physical_dispatch_allowed === true)}；production_authority=${String(status.production_authority === true)}。</div></div>`, `<button type="button" class="drawer-button secondary" data-action="simulator-lineage">查看数据契约与血缘</button><button type="button" class="drawer-button" data-action="close-modal">关闭</button>`, "runtime-status");
  }

  async function loadEnergy(range, source = "rail") {
    const controls = source === "analytics" ? "#analyticsRange [data-range]" : "#energyRange [data-range]";
    try {
      const data = await api(`/api/energy?range=${encodeURIComponent(range)}`);
      const safeData = (data?.source_metadata?.data_mode === "live" && data?.source_metadata?.live_data_verified === true) || data?.source_metadata?.source_type === "public_data_calibrated_simulation"
        ? data
        : { ...data, public_open_source_waiting:true, summary:fallbackDashboard.energy.summary, series:[], insights:["等待接入港口：当前未读取生产能耗数据。"] };
      state.energy = safeData;
      buildChart(safeData, $("#energyChart"));
      renderAnalytics(safeData);
      applyEnergySummary(safeData);
      $$(controls).forEach((button) => button.classList.toggle("active", button.dataset.range === range));
      return true;
    } catch (error) {
      toast("趋势加载失败", error.message, "warning");
      return false;
    }
  }

  function simulatorMutationOptions(body) {
    return {
      method:"POST",
      headers:{
        "Content-Type":"application/json",
        "X-Idempotency-Key":`port-sim-${Date.now()}-${Math.random().toString(16).slice(2,10)}`
      },
      body:JSON.stringify(body)
    };
  }

  function renderSimulator(snapshot) {
    if (!snapshot || !$("#realtimeSimulatorPanel")) return;
    state.simulator = snapshot;
    const simulation = snapshot.simulation || {};
    const fleet = snapshot.fleet_summary || {};
    const energy = snapshot.energy || {};
    const weather = snapshot.weather_tide || {};
    const yardBlocks = snapshot.yard_blocks || [];
    const gates = snapshot.gates || [];
    const alerts = snapshot.alerts || [];
    const yardOccupancy = yardBlocks.length ? yardBlocks.reduce((sum, item) => sum + Number(item.occupancy_percent || 0), 0) / yardBlocks.length : 0;
    $("#simulatorStatus").textContent = `${simulation.scenario_label || "模拟场景"} · 序列 ${simulation.sequence ?? "—"} · ${formatDateTime(snapshot.metadata?.observed_at)} · 不是现场实测`;
    $$('[data-simulator-scenario]').forEach((button) => button.classList.toggle("active", button.dataset.simulatorScenario === simulation.scenario_id));
    const kpis = [
      ["船舶/挂靠", (snapshot.port_calls || []).length, "个生产形状对象"],
      ["在作岸桥", fleet.quay_cranes?.working ?? "—", `共 ${fleet.quay_cranes?.total ?? "—"} 台`],
      ["AGV可用/低SOC", `${(fleet.agv?.total || 0) - (fleet.agv?.low_soc || 0)}/${fleet.agv?.low_soc || 0}`, "全量96台状态"],
      ["堆场占用", `${yardOccupancy.toFixed(1)}%`, `${yardBlocks.length} 个箱区`],
      ["电网需量", `${(Number(energy.grid_demand_kw || 0) / 1000).toFixed(2)} MW`, `限值 ${(Number(energy.peak_limit_kw || 0) / 1000).toFixed(1)} MW`],
      ["活动事件", alerts.length, `质量门禁 ${snapshot.quality?.gate_passed ? "通过" : "阻断"}`]
    ];
    $("#simulatorKpis").innerHTML = kpis.map(([label, value, detail]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></div>`).join("");
    const domainCards = [
      ["船舶与泊位", `${(snapshot.port_calls || []).filter((item) => ["working","alongside"].includes(item.status)).length} 在泊`, `待靠 ${(snapshot.port_calls || []).filter((item) => ["awaiting_pilot","scheduled"].includes(item.status)).length}`, `AIS轨迹 ${(snapshot.ais_tracks || []).length}`],
      ["岸桥/场桥/AGV", `QC ${fleet.quay_cranes?.working || 0}/${fleet.quay_cranes?.total || 0}`, `YC ${fleet.yard_cranes?.working || 0}/${fleet.yard_cranes?.total || 0}`, `AGV充电 ${fleet.agv?.charging || 0}`],
      ["堆场与闸口", `场地 ${yardOccupancy.toFixed(1)}%`, `排队 ${gates.reduce((sum,item)=>sum+Number(item.queue_vehicles||0),0)} 辆`, `开放 ${gates.reduce((sum,item)=>sum+Number(item.lanes_open||0),0)} 车道`],
      ["能源与储能", `岸电 ${(Number(energy.shore_power_kw||0)/1000).toFixed(2)} MW`, `BESS ${formatNumber(energy.bess_soc_percent)}%`, `电价 ${formatNumber(energy.tariff_cny_per_kwh)} 元/kWh`],
      ["气象与潮汐", `风速 ${formatNumber(weather.wind_speed_ms)} m/s`, `能见度 ${formatNumber(weather.visibility_m)} m`, `水位 ${formatNumber(weather.water_level_m_mllw)} m MLLW`],
      ["告警闭环", `高 ${alerts.filter((item)=>item.level==="critical").length}`, `中 ${alerts.filter((item)=>item.level==="warning").length}`, `提示 ${alerts.filter((item)=>item.level==="info").length}`],
      ["数据质量", `完整 ${((snapshot.quality?.completeness_rate||0)*100).toFixed(1)}%`, `重复 ${((snapshot.quality?.duplicate_rate||0)*100).toFixed(2)}%`, `物理违规 ${snapshot.quality?.physical_constraint_violations ?? "—"}`],
      ["权限边界", `沙箱执行 ${snapshot.governance?.sandbox_dispatch_allowed ? "允许" : "关闭"}`, `物理下发 ${snapshot.governance?.physical_dispatch_allowed ? "允许" : "关闭"}`, `生产权限 ${snapshot.governance?.production_authority ? "允许" : "关闭"}`]
    ];
    $("#simulatorDomainGrid").innerHTML = domainCards.map(([title, first, second, third]) => `<article class="sim-domain-card"><header><strong>${escapeHtml(title)}</strong><span>${escapeHtml(simulation.scenario_id || "SIM")}</span></header><dl><dt>指标1</dt><dd>${escapeHtml(first)}</dd><dt>指标2</dt><dd>${escapeHtml(second)}</dd><dt>指标3</dt><dd>${escapeHtml(third)}</dd></dl></article>`).join("");
    $("#simulatorDecisions").innerHTML = (snapshot.decisions || []).map((item) => {
      const status = item.executed_in_sandbox ? "已在沙箱执行" : item.approval_count >= 2 ? "双人审批完成" : `待审批 ${item.approval_count}/2`;
      const nextRole = item.approval_count === 0 ? "dispatcher" : "duty_manager";
      const nextLabel = item.approval_count === 0 ? "调度员审批" : "值班长复核";
      const actions = item.executed_in_sandbox
        ? `<button type="button" class="rollback" data-sim-rollback="${escapeHtml(item.decision_id)}">回滚模拟动作</button>`
        : item.approval_count < 2
          ? `<button type="button" class="warning" data-sim-approve="${escapeHtml(item.decision_id)}" data-sim-role="${nextRole}">${nextLabel}</button>`
          : `<button type="button" data-sim-execute="${escapeHtml(item.decision_id)}">执行到模拟状态</button>`;
      return `<article class="sim-decision ${item.executed_in_sandbox ? "executed" : ""}"><header><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(status)}</span></header><p>${escapeHtml(item.trigger)} ${escapeHtml(item.action)}</p><dl><span>${escapeHtml(item.policy)}</span><span>输入 ${escapeHtml(String(item.input_payload_sha256 || "").slice(0,12))}</span><span>${escapeHtml(item.impact?.semantics || "engineering_scenario_estimate")}</span></dl><footer>${actions}</footer></article>`;
    }).join("");
    renderSimulatorEvents();
  }

  function renderSimulatorEvents() {
    if (!$("#simulatorEvents")) return;
    const items = state.simulatorEvents || [];
    $("#simulatorEvents").innerHTML = items.length ? items.slice(0,12).map((item) => `<div class="sim-event"><i></i><div><strong>${escapeHtml(item.event)}</strong><span>${escapeHtml(item.detail)}</span><time>${escapeHtml(formatDateTime(item.occurred_at))}</time></div></div>`).join("") : `<div class="task-empty">等待模拟器审计事件</div>`;
  }

  async function loadSimulatorEvents() {
    try {
      const payload = await api("/api/port-simulator/events");
      state.simulatorEvents = payload.items || [];
      renderSimulatorEvents();
    } catch { /* event panel keeps the last valid audit trail */ }
  }

  async function loadSimulatorSnapshot() {
    try {
      const [snapshot, events] = await Promise.all([api("/api/port-simulator/snapshot"), api("/api/port-simulator/events")]);
      state.simulatorEvents = events.items || [];
      renderSimulator(snapshot);
      return snapshot;
    } catch (error) {
      if ($("#simulatorStatus")) $("#simulatorStatus").textContent = `模拟流不可用 · ${error.message}`;
      return null;
    }
  }

  function connectSimulatorStream() {
    if (!globalThis.EventSource || state.simulatorEventSource) return;
    const stream = new EventSource("/api/port-simulator/stream");
    state.simulatorEventSource = stream;
    stream.addEventListener("telemetry", (event) => {
      try { renderSimulator(JSON.parse(event.data)); } catch { /* wait for next complete event */ }
    });
    stream.addEventListener("error", () => {
      if ($("#simulatorStatus")) $("#simulatorStatus").textContent = "事件流正在重连 · 最近有效快照仍保留";
    });
  }

  async function changeSimulatorScenario(scenarioId) {
    try {
      await api("/api/port-simulator/scenario", simulatorMutationOptions({scenario_id:scenarioId, reason:"用户在数据分析页启动本地闭环演练"}));
      await loadSimulatorSnapshot();
      toast("模拟场景已切换", "所有数据沿同一port-realtime.v1链路重新计算；不是现场数据。", "success");
    } catch (error) { toast("场景切换失败", error.message, "warning"); }
  }

  async function approveSimulatorDecision(decisionId, role) {
    const roleMap = {
      dispatcher:["local-dispatcher","调度员基于本次模拟输入确认候选"],
      duty_manager:["local-duty-manager","值班长复核约束、影响和回滚边界"]
    };
    const [approverId, reason] = roleMap[role] || roleMap.dispatcher;
    try {
      await api(`/api/port-simulator/decisions/${encodeURIComponent(decisionId)}/approve`, simulatorMutationOptions({approver_id:approverId, approver_role:role, reason}));
      await loadSimulatorSnapshot();
      toast("沙箱审批已记录", "审批仅对当前模拟动作有效，不构成生产授权。", "success");
    } catch (error) { toast("审批未记录", error.message, "warning"); }
  }

  async function executeSimulatorDecision(decisionId) {
    try {
      const result = await api(`/api/port-simulator/decisions/${encodeURIComponent(decisionId)}/execute`, simulatorMutationOptions({reason:"双人审批后执行本地模拟闭环"}));
      await loadSimulatorSnapshot();
      toast("模拟闭环已执行", `sandbox_state_updated=${result.sandbox_state_updated}；physical_dispatch_performed=${result.physical_dispatch_performed}`, "success", 5200);
    } catch (error) { toast("模拟动作被阻断", error.message, "warning"); }
  }

  async function rollbackSimulatorDecision(decisionId) {
    try {
      const result = await api(`/api/port-simulator/decisions/${encodeURIComponent(decisionId)}/rollback`, simulatorMutationOptions({reason:"本地验收回滚演练"}));
      await loadSimulatorSnapshot();
      toast("模拟动作已回滚", `模拟状态已恢复；physical_dispatch_performed=${result.physical_dispatch_performed}`, "success");
    } catch (error) { toast("回滚未完成", error.message, "warning"); }
  }

  async function openSimulatorLineage() {
    try {
      state.simulatorContract = state.simulatorContract || await api("/api/port-simulator/contract");
      const contract = state.simulatorContract;
      const snapshot = state.simulator || await api("/api/port-simulator/snapshot");
      const sources = contract.calibration_sources || [];
      const sourceCards = sources.map((item) => `<div><span>${escapeHtml(item.semantic_class)}</span><strong>${escapeHtml(item.id)}</strong><code title="${escapeHtml(item.source_url)}">${escapeHtml(item.source_url)}</code></div>`).join("");
      const domains = (contract.domains || []).map((item) => `<div><strong>${escapeHtml(item.id)} · ${item.required_fields.length}字段</strong><span>${escapeHtml(item.source_system)}<br>${escapeHtml(item.required_fields.slice(0,8).join(" · "))}${item.required_fields.length > 8 ? " …" : ""}</span></div>`).join("");
      openModal("港口实时数据契约与血缘", `${contract.contract_id} · ${contract.domain_count}域 · ${contract.canonical_field_count}个规范字段`, `<div class="drawer-note"><strong>换源规则：</strong>${escapeHtml(contract.replacement_rule)}</div><div class="sim-lineage-grid">${sourceCards}</div><div class="settings-grid"><div class="setting-row"><div><strong>契约SHA-256</strong><span>${escapeHtml(contract.artifact)}</span></div><code>${escapeHtml(contract.artifact_sha256)}</code></div><div class="setting-row"><div><strong>公开AIS文件</strong><span>${escapeHtml(snapshot.lineage?.public_ais_path)}</span></div><code>${escapeHtml(snapshot.lineage?.public_ais_sha256)}</code></div><div class="setting-row"><div><strong>公开能源文件</strong><span>${escapeHtml(snapshot.lineage?.public_energy_path)}</span></div><code>${escapeHtml(snapshot.lineage?.public_energy_sha256)}</code></div></div><div class="sim-contract-domains">${domains}</div><div class="drawer-note"><strong>真实性边界：</strong>${escapeHtml(snapshot.metadata?.data_notice)} production_authority=false。</div>`, `<button type="button" class="drawer-button" data-action="close-modal">已核对</button>`, "simulator-lineage");
    } catch (error) { toast("数据契约读取失败", error.message, "warning"); }
  }

  function renderDecisions() {
    const quick = state.dashboard.quick_actions || [];
    const alerts = state.dashboard.alerts?.items || [];
    const impactLabels = ["读取当前数据后计算，不预填收益", "输出启发式候选，等待调度确认", "按本次读取结果生成"];
    const cards = quick.map((item, index) => ({
      ...item,
      priority: index === 0 ? "high" : index === 1 ? "medium" : "low",
      impact: impactLabels[index] || "执行后返回可审计结果"
    }));
    const waitingForPort = state.dashboard.public_open_source_waiting === true;
    const decisionGenerateButton = $("#decisionGenerateButton");
    if (decisionGenerateButton) {
      decisionGenerateButton.disabled = waitingForPort;
      decisionGenerateButton.title = waitingForPort ? "尚未接入经验证的港口数据源" : "生成只读泊位调度候选";
      decisionGenerateButton.innerHTML = `${icon("spark")}${waitingForPort ? "等待数据接入" : "生成智能方案"}`;
    }
    $("#decisionCards").innerHTML = cards.map((item, index) => `<article class="decision-item"><span class="decision-rank">0${index+1}</span><header><strong>${escapeHtml(item.title)}</strong><span class="priority-${item.priority}">${item.priority === "high" ? "高优先级" : item.priority === "medium" ? "中优先级" : "建议"}</span></header><p>${waitingForPort ? "等待接入港口后基于现场状态生成候选，不使用沙箱数值替代。" : escapeHtml(item.description)}</p><footer><span>${waitingForPort ? "等待接入港口" : escapeHtml(item.impact)}</span><button type="button" data-task-template="${escapeHtml(item.task_template_id)}" ${waitingForPort ? "disabled title=\"尚未接入经验证的港口数据源\"" : ""}>${waitingForPort ? "等待数据接入" : "让小懿执行 →"}</button></footer></article>`).join("");
    const risk = { critical: state.dashboard.alerts?.critical || 0, warning: state.dashboard.alerts?.warning || 0, info: state.dashboard.alerts?.info || 0 };
    const totalAlerts = risk.critical + risk.warning + risk.info;
    const riskScore = Math.max(0, 100 - risk.critical * 18 - risk.warning * 8 - risk.info * 2);
    if ($("#riskHealthScore")) $("#riskHealthScore").textContent = waitingForPort ? "—" : String(riskScore);
    if ($("#riskAlertSummary")) $("#riskAlertSummary").textContent = waitingForPort
      ? "现场告警未接入 · 不计算健康分"
      : `当前 ${totalAlerts} 项运营提醒 · 按级别扣分`;
    $("#riskLegend").innerHTML = waitingForPort
      ? `<span><i style="background:#f5a733"></i>待接入 TOS / EAM / VTS 告警</span>`
      : `<span><i style="background:#ff6268"></i>高 ${risk.critical}</span><span><i style="background:#f5a733"></i>中 ${risk.warning}</span><span><i style="background:#4ee58c"></i>提示 ${risk.info}</span>`;
    const summary = state.energy?.summary || {};
    if ($("#energyEvidenceMetrics")) $("#energyEvidenceMetrics").innerHTML = waitingForPort
      ? `<span>综合能耗<b>等待接入港口</b></span><span>碳排放<b>等待接入港口</b></span><span>碳强度<b>等待接入港口</b></span><span>岸电利用率<b>等待接入港口</b></span>`
      : `<span>综合能耗<b>${formatNumber(summary.total_energy_mwh)} MWh</b></span><span>碳排放<b>${formatNumber(summary.carbon_emissions_tco2e)} tCO₂e</b></span><span>碳强度<b>${formatNumber(summary.carbon_intensity_kgco2e_per_teu)} kg/TEU</b></span><span>岸电利用率<b>${formatNumber(summary.shore_power_utilization_percent)}%</b></span>`;
    if (!quick.length && alerts.length) $("#decisionCards").innerHTML = `<div class="task-empty">暂无可执行建议</div>`;
  }

  function renderQuickKnowledge() {
    const categories = state.dashboard.knowledge_categories || fallbackDashboard.knowledge_categories;
    $("#knowledgeQuickTags").innerHTML = categories.slice(0,6).map((name) => `<button type="button" data-knowledge-tag="${escapeHtml(name)}">${escapeHtml(name)}</button>`).join("");
  }

  async function loadKnowledge() {
    try {
      const [knowledge, status] = await Promise.all([api("/api/knowledge"), api("/api/knowledge/status")]);
      state.knowledge = knowledge;
      state.knowledgeStatus = status;
      $("#kbChip").textContent = `${knowledge.count} 份已索引资料`;
      $("#topK").value = String(state.knowledge.default_top_k || 5);
      if ($("#knowledgeCount")) $("#knowledgeCount").textContent = String(status.document_count);
      if ($("#knowledgeChunkCount")) $("#knowledgeChunkCount").textContent = String(status.chunk_count);
      if ($("#knowledgeOfficialCount")) $("#knowledgeOfficialCount").textContent = String(status.official_verified_documents);
    } catch (error) {
      state.knowledge = { count:0, files:[], default_top_k:5, chunk_count:0, official_verified_documents:0 };
      state.knowledgeStatus = null;
      $("#kbChip").textContent = "知识索引未连接";
      if ($("#knowledgeCount")) $("#knowledgeCount").textContent = "--";
      if ($("#knowledgeChunkCount")) $("#knowledgeChunkCount").textContent = "--";
      if ($("#knowledgeOfficialCount")) $("#knowledgeOfficialCount").textContent = "--";
      toast("知识库连接受限", "已保留问答与本地界面，稍后可重试。", "warning");
    }
    renderKnowledge();
  }

  function categoryIcon(index) {
    return ["ship","chart","leaf","agv","report","book"][index % 6];
  }

  function renderKnowledge(filter = $("#knowledgeSearch")?.value || "") {
    const categories = state.dashboard.knowledge_categories || fallbackDashboard.knowledge_categories;
    const allFiles = state.knowledge.files || [];
    $("#knowledgeCategories").innerHTML = categories.map((name,index) => {
      const count = allFiles.filter((file) => categoryMatches(String(file).toLowerCase(), name)).length;
      return `<button type="button" class="knowledge-category" data-knowledge-tag="${escapeHtml(name)}"><i>${icon(categoryIcon(index))}</i><span><strong>${escapeHtml(name)}</strong><small>${count} 份已索引资料</small></span></button>`;
    }).join("");
    const query = String(filter).trim().toLowerCase();
    if (query.length >= 2) {
      $("#knowledgeResultLabel").textContent = `正在检索正文“${filter}”`;
      $("#kbList").innerHTML = `<div class="task-empty"><div>${icon("search")}<strong>正在检索真实索引片段</strong><span>结果将显示来源机构、版本与校验状态</span></div></div>`;
      searchKnowledge(filter);
      return;
    }
    const files = allFiles.filter((file) => !query || file.toLowerCase().includes(query));
    $("#knowledgeResultLabel").textContent = query ? `请输入至少 2 个字符检索正文` : `全部文档 · ${state.knowledge.count} 项`;
    $("#kbList").innerHTML = files.length ? files.map((file) => `<button type="button" class="kb-item" data-q="请根据已索引资料《${escapeHtml(file)}》介绍其核心内容并列出证据。" data-mode="expert"><i>${icon("report")}</i><div><strong>${escapeHtml(file)}</strong><small>已进入索引 · 点击按严格证据提问</small></div></button>`).join("") : `<div class="task-empty"><div>${icon("search")}<strong>${state.knowledgeStatus ? "暂无资料" : "知识索引未连接"}</strong><span>${state.knowledgeStatus ? "请登记并构建索引后再查询" : "请检查本地知识服务"}</span></div></div>`;
  }

  async function searchKnowledge(query) {
    const run = ++state.knowledgeSearchRun;
    try {
      const result = await api("/api/knowledge/search", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ query:String(query).trim(), top_k:10, min_coverage:.30 })
      });
      if (run !== state.knowledgeSearchRun || String($("#knowledgeSearch")?.value || "").trim() !== String(query).trim()) return;
      const qualifiedHits = (result.hits || []).filter((hit) => hit.qualified).sort((a,b) => Number(b.official) - Number(a.official) || Number(b.coverage) - Number(a.coverage) || Number(b.score) - Number(a.score));
      state.knowledgeSearchResults = qualifiedHits;
      const officialHits = qualifiedHits.filter((hit) => hit.official).length;
      $("#knowledgeResultLabel").textContent = `正文检索“${query}” · ${qualifiedHits.length} 个达标片段 · ${officialHits} 个官方来源命中`;
      $("#kbList").innerHTML = qualifiedHits.length ? qualifiedHits.map((hit) => {
        return `<button type="button" class="kb-item knowledge-hit ${hit.official ? "official" : ""}" data-q="请严格根据已索引资料回答：${escapeHtml(query)}" data-mode="expert"><i>${icon(hit.official ? "check" : "report")}</i><div><strong>${escapeHtml(hit.title)}</strong><small>${escapeHtml(hit.institution || "内部整理资料")} · ${hit.official ? "官方发布来源已核验" : escapeHtml(sourceQualityLabel(hit.source_quality))} · 覆盖 ${(Number(hit.coverage || 0) * 100).toFixed(0)}%</small><p>${escapeHtml(hit.snippet)}</p></div></button>`;
      }).join("") : `<div class="task-empty"><div>${icon("search")}<strong>没有达到阈值的索引命中</strong><span>小懿不会在证据不足时补写专业事实</span></div></div>`;
      return qualifiedHits;
    } catch (error) {
      if (run !== state.knowledgeSearchRun) return;
      $("#knowledgeResultLabel").textContent = "索引检索失败";
      $("#kbList").innerHTML = `<div class="drawer-note"><strong>无法检索：</strong>${escapeHtml(error.message)}</div>`;
      throw error;
    }
  }

  function categoryMatches(file, query) {
    const map = {
      "港口运营":["port","terminal","berth","tos"], "航运调度":["ship","vessel","route","liner"],
      "能源管理":["energy","carbon","shore"], "设备管理":["equipment","maintenance","agv"],
      "政策法规":["policy","law","customs","compliance"], "行业标准":["standard","qa","taxonomy"]
    };
    return Object.entries(map).some(([name, keys]) => name.includes(query) && keys.some((key) => file.includes(key)));
  }

  function setHeroState(stage, step = "") {
    const bubble = $("#voiceBubble");
    const title = $("#heroSpeechTitle");
    const text = $("#heroSpeechText");
    const status = $("#heroStatus");
    bubble.classList.toggle("thinking", stage !== "idle" && stage !== "complete");
    const values = {
      idle:["您好！我是小懿AI","您的港航智能助手","本机应用可用"],
      understand:["正在理解您的意图","识别目标、约束与风险边界","任务理解中"],
      retrieve:["正在检索港航知识库","正在比对证据与专业规则","知识检索中"],
      compose:["正在融合索引与生成模型","将锁定事实、专业分析和岗位建议组织为完整回答","混合生成中"],
      execute:[`正在执行${step || "智能任务"}`,"每一步均可追溯、可暂停","任务执行中"],
      confirm:["需要您确认后继续","高风险动作不会自动下发","等待人工确认"],
      complete:["任务完成，证据链已保留","您可以继续追问或生成报告","执行完成"]
    };
    const value = values[stage] || values.idle;
    title.textContent = value[0]; text.textContent = value[1]; status.textContent = value[2];
  }

  function setReasoning(stage) {
    const flow = $("#reasoningFlow");
    flow.hidden = false;
    const order = ["understand","retrieve","compose"];
    const active = order.indexOf(stage);
    order.forEach((name,index) => {
      const node = $(`[data-stage="${name}"]`, flow);
      node.classList.toggle("active", index === active);
      node.classList.toggle("done", index < active);
    });
    setHeroState(stage);
  }

  function modeLabel(mode) {
    return { expert:"专业 / Expert", ops:"运营 / Ops", sop:"SOP", brief:"简报 / Brief" }[mode] || mode;
  }

  function modeShort(mode) {
    return { expert:"专业", ops:"运营", sop:"SOP", brief:"简报" }[mode] || "专业";
  }

  function refusalReasonLabel(reason) {
    return {
      official_source_required:"该问题涉及法规、标准或监管事实，但当前没有达到阈值的官方发布来源证据。",
      official_full_text_required:"该问题需要条款级正式全文或授权摘录；当前摘要/目录只能用于定位，不能支撑结论。",
      jurisdiction_source_required:"当前没有同时匹配目标辖区、适用日期和主题的官方证据。",
      insufficient_index_evidence:"当前已登记索引中没有达到覆盖阈值的可审计证据。",
      live_data_connection_required:"当前问答未获得已验证的实时生产数据，需要连接相应港口系统后才能确认当前状态。"
    }[reason] || "当前没有足够的已登记索引证据。";
  }

  function sourceQualityLabel(value) {
    return {
      official_verified:"官方发布来源", internal_curated:"内部整理未独立核验", sandbox_runtime:"历史运营沙箱事件流", public_data_calibrated_simulation:"公开数据校准实时模拟",
      mixed:"混合来源", unverified:"未验证", not_applicable:"不适用"
    }[value] || value || "未验证";
  }

  function startThinkingTicker(runId) {
    const stages = [
      { phase:"understand", label:"解析问题意图与当前会话上下文" },
      { phase:"understand", label:"识别关键事实、风险等级与回答目标" },
      { phase:"retrieve", label:"检索本地港航稠密与稀疏知识索引" },
      { phase:"retrieve", label:"核对证据来源、版本与适用边界" },
      { phase:"compose", label:"锁定法规、数值与安全相关事实" },
      { phase:"compose", label:"构建证据约束下的回答骨架" },
      { phase:"compose", label:"调用本地生成模型进行综合分析" },
      { phase:"compose", label:"补充港航岗位影响与操作建议" },
      { phase:"compose", label:"复核引用编号、事实边界与人工确认点" },
      { phase:"compose", label:"整理表达并准备统一显示完整答案" }
    ];
    const liveStages = [
      "本地模型正在生成完整答案",
      "持续接收模型结果并检查关键事实",
      "正在整理岗位化建议与人工确认节点",
      "推理服务正常，继续整理完整答案"
    ];
    const target = $("#answer");
    let stageIndex = 0;
    let liveIndex = 0;
    let stopped = false;

    const render = () => {
      if (stopped || runId !== state.generationId) return;
      const inLiveGeneration = stageIndex >= stages.length;
      const current = inLiveGeneration
        ? { phase:"compose", label:liveStages[liveIndex % liveStages.length] }
        : stages[stageIndex];
      const completed = stages
        .slice(Math.max(0, Math.min(stageIndex, stages.length) - 4), Math.min(stageIndex, stages.length))
        .map((item) => `✓ ${item.label}`);
      const progress = inLiveGeneration
        ? `生成中 · ${liveIndex + 1}`
        : `步骤 ${stageIndex + 1}/${stages.length}`;
      target.classList.remove("error", "typing");
      target.classList.add("thinking");
      target.textContent = [...completed, `› ${current.label} · ${progress}`].join("\n");
      $("#responseStatus").textContent = `${current.label} · 混合生成服务仍在运行`;
      setReasoning(current.phase);
    };

    const timer = setInterval(() => {
      if (runId !== state.generationId) {
        stop();
        return;
      }
      if (stageIndex < stages.length) stageIndex += 1;
      else liveIndex += 1;
      render();
    }, 900);

    function stop() {
      if (stopped) return;
      stopped = true;
      clearInterval(timer);
      target.classList.remove("thinking");
      if (state.thinkingTickerStop === stop) state.thinkingTickerStop = null;
    }

    state.thinkingTickerStop?.();
    state.thinkingTickerStop = stop;
    render();
    return stop;
  }

  function stopGeneration(announce = false) {
    state.generationId += 1;
    state.thinkingTickerStop?.();
    const activeGenerationId = state.activeGenerationId;
    state.activeGenerationId = null;
    if (activeGenerationId) {
      void cancelGenerationOnServer(activeGenerationId).catch(() => {});
    }
    if (state.activeController) state.activeController.abort();
    state.activeController = null;
    setAskButtonGenerating(false);
    $("#answer").classList.remove("typing");
    $("#reasoningFlow").hidden = true;
    setHeroState("idle");
    if (announce) {
      $("#responseStatus").textContent = "已停止生成，可以修改问题后重新提问";
      toast("已停止生成", "当前处理进度已停止，可以立即重新提问。", "warning");
    }
  }

  function setAskButtonGenerating(active) {
    const button = $("#askBtn");
    button.classList.toggle("generating", active);
    button.setAttribute("aria-label", active ? "停止生成" : "发送");
    button.title = active ? "停止当前生成" : "发送问题";
  }

  function scrollConversationToLatestAnswer({ settle = false } = {}) {
    const pinToBottom = () => {
      const feed = $("#conversationFeed");
      if (!feed) return;
      feed.scrollTop = Math.max(0, feed.scrollHeight - feed.clientHeight);
      const latestAnswer = $("#assistantMessage");
      if (!latestAnswer) return;
      const answerBounds = latestAnswer.getBoundingClientRect();
      if (answerBounds.bottom > window.innerHeight || answerBounds.top < 0) {
        latestAnswer.scrollIntoView({
          block:"end",
          inline:"nearest",
          behavior:"auto"
        });
      }
    };
    pinToBottom();
    if (settle) {
      requestAnimationFrame(() => {
        pinToBottom();
        requestAnimationFrame(pinToBottom);
      });
    }
  }

  async function typeAnswer(text, runId, delayMs = 18) {
    const target = $("#answer");
    target.classList.remove("error");
    target.classList.add("typing");
    target.textContent = "";
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const chunk = reduced ? text.length : Math.max(2, Math.ceil(text.length / 95));
    let lastScrollAt = 0;
    for (let index = 0; index < text.length; index += chunk) {
      if (runId !== state.generationId) return false;
      target.textContent = displayEvidenceMarkers(text.slice(0, index + chunk));
      if (performance.now() - lastScrollAt >= 160) {
        lastScrollAt = performance.now();
        scrollConversationToLatestAnswer();
      }
      if (!reduced) await sleep(delayMs);
    }
    target.classList.remove("typing");
    renderStructuredAnswer(target, text, state.currentQuestion, state.currentIntent);
    scrollConversationToLatestAnswer({ settle:true });
    return true;
  }

  function createAnswerTypewriter(runId) {
    const target = $("#answer");
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let displayed = "";
    let pending = "";
    let active = false;
    let cancelled = false;
    let started = false;
    let idleWaiters = [];
    let lastScrollAt = 0;

    const keepLatestVisible = (force = false) => {
      const now = performance.now();
      if (!force && now - lastScrollAt < 160) return;
      lastScrollAt = now;
      scrollConversationToLatestAnswer({ settle:force });
    };

    const settleIdle = () => {
      const waiters = idleWaiters;
      idleWaiters = [];
      waiters.forEach((resolve) => resolve());
    };

    const waitUntilIdle = () => {
      if (!active && !pending) return Promise.resolve();
      return new Promise((resolve) => idleWaiters.push(resolve));
    };

    const drain = async () => {
      if (active || cancelled) return;
      active = true;
      if (!started) {
        started = true;
        target.classList.remove("error");
        target.classList.add("typing");
        target.textContent = "";
      }
      while (pending && !cancelled && runId === state.generationId) {
        const totalLength = displayed.length + pending.length;
        const step = reduced ? pending.length : Math.max(1, Math.ceil(totalLength / 110));
        displayed += pending.slice(0, step);
        pending = pending.slice(step);
        target.textContent = displayEvidenceMarkers(displayed);
        keepLatestVisible();
        if (!reduced) await sleep(18);
      }
      active = false;
      if (pending && !cancelled && runId === state.generationId) {
        void drain();
        return;
      }
      settleIdle();
    };

    return {
      push(text) {
        if (cancelled || runId !== state.generationId || !text) return;
        pending += text;
        void drain();
      },
      async finish(finalText) {
        if (cancelled || runId !== state.generationId) return false;
        const expected = String(finalText || "");
        if (`${displayed}${pending}` !== expected) {
          if (expected.startsWith(displayed)) {
            pending = expected.slice(displayed.length);
          } else {
            displayed = "";
            pending = expected;
            started = false;
          }
        }
        void drain();
        await waitUntilIdle();
        if (cancelled || runId !== state.generationId) return false;
        target.textContent = displayEvidenceMarkers(expected);
        keepLatestVisible(true);
        target.classList.remove("typing");
        return true;
      },
      cancel() {
        cancelled = true;
        pending = "";
        target.classList.remove("typing");
        settleIdle();
      }
    };
  }

  async function askQuestion(question, mode) {
    const input = $("#question");
    input.value = question;
    if (mode) $("#mode").value = mode;
    return ask();
  }

  function updateGroundingState(data = null) {
    const badge = $("#groundingBadge");
    if (!badge) return;
    badge.classList.remove("grounded", "partial", "refused", "pending", "official", "indexed", "demo");
    if (!data) {
      badge.textContent = "运营沙箱快照";
      badge.classList.add("partial");
      if ($("#answerCoverageMetric")) $("#answerCoverageMetric").textContent = "不适用";
      if ($("#answerSourceQuality")) $("#answerSourceQuality").textContent = "非生产数据";
      return;
    }
    const evidence = Array.isArray(data.evidence) ? data.evidence : [];
    const officialCount = evidence.filter((item) => item.official && item.source_quality === "official_verified").length;
    const sandboxRuntime = ["sandbox_runtime", "public_data_calibrated_simulation"].includes(data.source_quality);
    const readiness = data.decision_readiness?.status || "";
    if (readiness === "evidence_conflict") {
      badge.textContent = "证据冲突·待裁决";
      badge.classList.add("refused");
    } else if (readiness === "ready_with_review") {
      badge.textContent = "有据·需人工复核";
      badge.classList.add("official");
    } else if (readiness === "partial") {
      badge.textContent = "部分就绪";
      badge.classList.add("partial");
    } else if (sandboxRuntime) {
      badge.textContent = "沙箱态势·已追溯";
      badge.classList.add("partial");
    } else if (data.refusal_reason || !data.grounded) {
      const liveBoundary = data.refusal_reason === "live_data_connection_required";
      badge.textContent = liveBoundary ? "实时数据待接入" : "未检索到本地证据";
      badge.classList.add("pending");
    } else if (officialCount) {
      badge.textContent = `官方来源 ${officialCount}`;
      badge.classList.add("grounded");
    } else {
      badge.textContent = `已索引证据 ${evidence.length}`;
      badge.classList.add("partial");
    }
    if ($("#answerCoverageMetric")) $("#answerCoverageMetric").textContent = `${(Number(data.coverage || 0) * 100).toFixed(0)}%`;
    if ($("#answerSourceQuality")) $("#answerSourceQuality").textContent = sourceQualityLabel(data.source_quality);
  }

  async function ask() {
    if (state.activeController) { stopGeneration(true); return; }
    if (state.automationRunning) stopAutomation("已由新指令终止上一条操作计划");
    const question = $("#question").value.trim();
    const mode = $("#mode").value;
    const topK = Math.min(10, Math.max(1, Number($("#topK").value || 5)));
    const strictEvidence = $("#strictEvidence") ? $("#strictEvidence").checked : localStorage.getItem(STORAGE.strictEvidence) !== "false";
    $("#topK").value = String(topK);
    if (question.length < 2) { toast("请输入完整问题", "至少输入 2 个字符。", "warning"); $("#question").focus(); return; }

    $("#question").value = "";
    stopGeneration(false);
    const runId = ++state.generationId;
    const controller = new AbortController();
    const serverGenerationId = globalThis.crypto?.randomUUID?.()
      || `gen-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    state.activeController = controller;
    state.activeGenerationId = serverGenerationId;
    state.currentQuestion = question;
    state.currentMode = mode;
    $("#currentQuestion").textContent = question;
    $("#userMessageTime").textContent = formatShortTime();
    $("#userBubbleRow").hidden = false;
    $("#analysisTitle").textContent = "正在分析您的问题";
    $("#responseStatus").textContent = "小懿正在协同知识库与运营引擎";
    $("#answer").textContent = "正在理解您的目标与业务语境...";
    $("#next").innerHTML = "";
    setAskButtonGenerating(true);
    $("#conversationFeed").scrollTop = $("#conversationFeed").scrollHeight;
    $("#modeShortLabel").textContent = modeShort(mode);
    setReasoning("understand");

    const stopThinking = startThinkingTicker(runId);
    try {
      if (state.agentMode) {
        try {
          const plan = await api("/api/automation/plans", {
            method:"POST", headers:{"Content-Type":"application/json"}, signal:controller.signal,
            body:JSON.stringify({ command:question, execution_mode:"automatic" })
          });
          if (runId !== state.generationId) return;
          if (plan.actionable) {
            stopThinking();
            state.currentIntent = plan.intent;
            state.currentAnswer = plan.summary;
            state.currentEvidence = [];
            state.currentVerification = null;
            $("#analysisTitle").textContent = "智能操作计划";
            $("#analysisDate").textContent = `${plan.actions.length} 个白名单步骤 · 全程审计`;
            $("#responseStatus").textContent = "已识别为界面操作指令，准备逐步执行";
            $("#modeMetric").textContent = "智能操作 / Agent";
            $("#evMetric").textContent = "0";
            $("#confMetric").textContent = `${Math.round(Number(plan.confidence || 0) * 100)}%`;
            $("#intentTag").textContent = plan.intent;
            const planAnswer = `${plan.summary}\n\n小懿只会执行预置白名单界面动作；任何生产写操作都必须在当前步骤单独确认。`;
            state.currentAnswer = planAnswer;
            if (!await typeAnswer(planAnswer, runId)) return;
            state.activeController = null;
            if ($("#groundingBadge")) {
              $("#groundingBadge").textContent = "白名单操作计划";
              $("#groundingBadge").className = "grounding-badge pending";
            }
            if ($("#answerCoverageMetric")) $("#answerCoverageMetric").textContent = `${plan.actions.length} 步`;
            if ($("#answerSourceQuality")) $("#answerSourceQuality").textContent = "白名单动作";
            $("#next").innerHTML = `<button type="button" data-action="resume-automation">${icon("play")}查看执行轨迹</button><button type="button" data-action="connectors">${icon("command")}接口安全状态</button>`;
            openAutomationPlan(plan);
            void executeAutomationPlan();
            return;
          }
        } catch (error) {
          if (error.name === "AbortError") throw error;
          toast("智能操作规划器暂不可用", "本次将继续使用严格证据问答；不会执行任何界面或生产动作。", "warning", 4600);
        }
      }

      let streamedAnswer = "";
      const request = streamChat(
        { question, mode, top_k:topK, strict_evidence:strictEvidence, session_id:state.sessionId },
        controller.signal,
        (text) => {
          if (runId !== state.generationId) return;
          streamedAnswer += text;
          setReasoning("compose");
          $("#responseStatus").textContent = "证据检索已完成，正在生成并校验完整答案";
        },
        serverGenerationId
      ).then((data) => ({ data })).catch((error) => ({ error }));

      const result = await request;
      if (result.error) throw result.error;
      const data = result.data;
      if (runId !== state.generationId) return;
      stopThinking();
      const liveBoundary = data.refusal_reason === "live_data_connection_required";
      const answer = data.answer;
      state.currentMode = data.mode;
      state.currentIntent = data.intent;
      state.currentConfidence = data.confidence;
      $("#responseKpis").hidden = !["energy_analysis", "energy_carbon"].includes(data.intent);
      $("#analysisTitle").textContent = intentTitle(data.intent);
      const generationLabel = data.generation_fallback ? `${data.generation_provider} 已回退` : data.generation_provider || "local_rules";
      $("#analysisDate").textContent = ["sandbox_runtime", "public_data_calibrated_simulation"].includes(data.source_quality) ? `${new Date().toLocaleDateString("zh-CN")} · 公开数据校准模拟态势 · ${generationLabel}` : `${new Date().toLocaleDateString("zh-CN")} · 本地生成式 RAG · ${generationLabel}`;
      $("#responseStatus").textContent = "融合分析与证据校验已完成，正在统一输出完整答案";
      if (!await typeAnswer(answer, runId, 24)) return;
      state.activeController = null;
      state.activeGenerationId = null;
      const readiness = data.decision_readiness || null;
      state.currentAnswer = answer;
      state.currentEvidence = Array.isArray(data.evidence) ? data.evidence : [];
      state.currentVerification = data.answer_verification || null;
      $("#responseStatus").textContent = readiness?.status === "evidence_conflict"
        ? "支持证据存在冲突，已阻止形成可采用决策"
        : readiness?.status === "partial"
        ? data.generation_fallback
          ? "部分子问题有据，未覆盖部分保持证据边界"
          : "有据结论已锁定，未覆盖部分已由本机模型补充并等待人工复核"
        : ["sandbox_runtime", "public_data_calibrated_simulation"].includes(data.source_quality)
        ? "已读取动态沙箱事件并保留生产数据边界"
        : liveBoundary ? "已说明实时数据边界与目标接入系统，未使用沙箱数值"
        : data.refusal_reason === "business_object_required" ? "业务对象不明确，等待补充后继续"
        : data.intent === "identity" ? "身份与能力介绍已完成 · 本机生成模型参与表达"
        : !data.grounded ? "模型已正常回答；本地证据不足提醒已附在答案底部" : "港航知识检索与证据分析已完成";
      if (data.grounded && data.answer_verification?.status === "passed") {
        $("#responseStatus").textContent += ` · 主张对齐 ${(Number(data.answer_verification.evidence_alignment || 0) * 100).toFixed(0)}% · 数字完整性 ${(Number(data.answer_verification.numeric_integrity || 0) * 100).toFixed(0)}%`;
      }
      $("#modeMetric").textContent = modeLabel(data.mode);
      $("#evMetric").textContent = String(state.currentEvidence.length);
      $("#confMetric").textContent = data.confidence;
      $("#intentTag").textContent = data.intent;
      $("#evidence").textContent = JSON.stringify(state.currentEvidence);
      updateGroundingState(data);
      renderNextQuestions(data.next_questions || [], data.mode, data.question);
      saveTopic({ ...data, answer });
      scrollConversationToLatestAnswer({ settle:true });
      setHeroState("complete");
      setTimeout(() => { if (!state.activeController) setHeroState("idle"); }, 2300);
    } catch (error) {
      stopThinking();
      if (error.name !== "AbortError" && runId === state.generationId) {
        $("#answer").classList.add("error");
        $("#answer").textContent = `连接受限：${error.message}\n\n当前问题与已显示内容已保留，请检查服务后重试。`;
        $("#responseStatus").textContent = "连接受限，已保留当前进度";
        scrollConversationToLatestAnswer({ settle:true });
        toast("问答服务连接失败", error.message, "warning", 5000);
      }
    } finally {
      stopThinking();
      if (runId === state.generationId) {
        state.activeController = null;
        state.activeGenerationId = null;
        setAskButtonGenerating(false);
        $("#answer").classList.remove("typing");
        $("#reasoningFlow").hidden = true;
      }
    }
  }

  function intentTitle(intent) {
    if (intent === "rl_agv_energy_optimization") return "RL联合优化结果";
    if (intent === "weather_berth_joint_rl_result") return "极端天气联合调度结果";
    if (intent === "qc_agv_yard_marl_result") return "多智能体协同优化结果";
    if (intent === "operator_runtime_assist") return "当前运营态势研判";
    if (intent === "operator_clarification") return "请补充业务对象";
    const known = {
      capability:"能力说明", energy:"能耗与碳排分析", alert:"预警处置建议", emergency:"应急 SOP",
      tos:"TOS 系统分析", operations:"港口运营分析", vessel:"船舶与泊位分析", knowledge:"港航知识问答"
    };
    const key = Object.keys(known).find((item) => String(intent).toLowerCase().includes(item));
    return key ? known[key] : "专业分析结果";
  }

  function readinessLabel(status) {
    const labels = {
      ready:"可采用", ready_with_review:"有据但需人工复核", partial:"部分就绪",
      needs_clarification:"需要补充对象", needs_live_data:"需要实时数据",
      needs_full_text:"需要官方全文", insufficient_evidence:"证据不足",
      evidence_conflict:"证据冲突", sandbox_only:"仅限沙箱", not_applicable:"不适用"
    };
    return labels[status] || "需要复核";
  }

  function renderNextQuestions(items, mode, baseQuestion) {
    const buttons = items.slice(0, 3).map((item, index) => {
      const text = typeof item === "string" ? item : item.text;
      const label = typeof item === "string" ? item : (item.label || item.text);
      const send = text.includes(baseQuestion || "___") ? text : `围绕“${baseQuestion}”，${text}`;
      return `<button type="button" data-q="${escapeHtml(send)}" data-mode="${escapeHtml(typeof item === "string" ? mode : item.mode || mode)}">${icon(index === 0 ? "spark" : index === 1 ? "chart" : "chat")}${escapeHtml(label)}</button>`;
    });
    buttons.unshift(`<button type="button" data-action="generate-report">${icon("report")}生成详细报告</button>`);
    $("#next").innerHTML = buttons.join("");
  }

  function topicTitle(question) {
    const value = String(question).replace(/\s+/g," ").trim();
    return value.length > 30 ? `${value.slice(0,30)}...` : value;
  }

  function renderConversationTranscript({ excludeLatest = false } = {}) {
    const transcript = $("#conversationTranscript");
    if (!transcript) return;
    const turns = excludeLatest
      ? state.conversationTurns.slice(0, -1)
      : state.conversationTurns;
    transcript.innerHTML = turns.map((item) => `
      <section class="transcript-turn" data-transcript-turn="${escapeHtml(item.id)}">
        <div class="user-bubble-row">
          <div class="user-bubble"><span>${escapeHtml(item.question)}</span><time>${escapeHtml(formatShortTime(item.createdAt))}</time></div>
        </div>
        <div class="transcript-assistant-row">
          <div class="mini-assistant-avatar"><span class="bot-face"><i></i><b></b></span></div>
          <div class="transcript-assistant-bubble">${escapeHtml(displayEvidenceMarkers(item.answer))}<footer><span>小懿AI · ${escapeHtml(modeShort(item.mode))}</span><span>${escapeHtml(item.intent || "knowledge")}</span></footer></div>
        </div>
        <div class="transcript-divider"></div>
      </section>
    `).join("");
  }

  function saveTopic(data) {
    const item = {
      id:data.answer_id || `topic-${Date.now()}-${Math.random().toString(16).slice(2,8)}`,
      sessionId:data.session_id || state.sessionId,
      title:topicTitle(data.question), question:data.question, answer:data.answer, mode:data.mode,
      intent:data.intent, confidence:data.confidence, evidence:data.evidence || [], next_questions:data.next_questions || [],
      grounded:Boolean(data.grounded), coverage:Number(data.coverage || 0), source_quality:data.source_quality || "unverified",
      refusal_reason:data.refusal_reason || null, strict_evidence:Boolean(data.strict_evidence),
      decision_readiness:data.decision_readiness || null,
      evidence_health:data.evidence_health || null,
      answer_verification:data.answer_verification || null,
      createdAt:new Date().toISOString()
    };
    state.topics = [item, ...state.topics.filter((old) => old.id !== item.id)].slice(0,200);
    state.conversationTurns = [...state.conversationTurns, item].slice(-40);
    persist(STORAGE.topics, state.topics);
    persist(STORAGE.turns, state.conversationTurns);
    renderConversationTranscript({ excludeLatest:true });
    updateCounts();
  }

  function beginNewConversation() {
    state.sessionId = createSessionId();
    state.conversationTurns = [];
    localStorage.setItem(STORAGE.sessionId, state.sessionId);
    persist(STORAGE.turns, state.conversationTurns);
    renderConversationTranscript();
    showWelcome();
    toast("已新建连续对话", "后续消息会在当前窗口连续显示，并共享同一会话上下文。", "success");
  }

  function showWelcome() {
    stopGeneration(false);
    $("#question").value = "";
    const energy = state.dashboard.energy || fallbackDashboard.energy;
    const summary = energy.summary;
    const metadata = state.dashboard.source_metadata || null;
    const live = metadata?.data_mode === "live" && metadata?.live_data_verified === true;
    const simulation = metadata?.source_type === "public_data_calibrated_simulation" || metadata?.data_mode === "public_data_calibrated_simulation";
    const modeName = live ? "生产实绩" : simulation ? "公开数据校准实时模拟" : "等待接入港口";
    state.currentQuestion = "帮我分析一下今日港口的能耗情况";
    state.currentAnswer = live || simulation
      ? `当前能耗态势：\n• 综合能耗 ${formatNumber(summary.total_energy_mwh)} MWh，较对比基线 ${Number(summary.energy_change_percent) <= 0 ? "下降" : "上升"} ${Math.abs(Number(summary.energy_change_percent)).toFixed(1)}%。\n• 碳排放 ${formatNumber(summary.carbon_emissions_tco2e)} tCO₂e，岸电利用率 ${formatNumber(summary.shore_power_utilization_percent)}%。\n• ${energy.insights?.[0] || "请结合当前作业计划复核能耗变化。"}\n• ${energy.insights?.[1] || "高负荷窗口需要现场值班人员确认。"}\n\n数据边界：${modeName}，来源 ${metadata.source_system}，观测时间 ${formatDateTime(metadata.observed_at)}，质量码 ${metadata.quality_code}。${metadata.live_data_verified ? "" : "当前不是现场生产实绩，不能作为控制依据。"}`
      : "等待接入港口：当前未读取 TOS、AIS、EMS、EAM 或 VTS 的现场数据，因此不展示或推断今日能耗、吞吐量、设备状态和告警数值。港航知识问答与固定 RAG 评测仍可独立使用。";
    state.currentEvidence = live || simulation ? [{ id:live ? "runtime:LIVE-PORT" : "runtime:PUBLIC-CALIBRATED-SIM", source:metadata.source_system, title:live ? "已验证港口运营数据" : "公开数据校准实时模拟", score:1, snippet:metadata.data_notice, institution:metadata.source_system, version:metadata.schema_version, official:false, source_quality:live ? "live_verified" : "public_data_calibrated_simulation", verification_status:live ? "live_verified" : "simulation_only" }] : [];
    state.currentVerification = null;
    state.currentMode = "ops";
    state.currentIntent = "energy_analysis";
    $("#currentQuestion").textContent = state.currentQuestion;
    renderStructuredAnswer(
      $("#answer"),
      state.currentAnswer,
      state.currentQuestion,
      state.currentIntent
    );
    $("#responseKpis").hidden = false;
    $("#analysisTitle").textContent = "今日能耗概况";
    $("#responseStatus").textContent = live ? "已读取并验证港口现场数据" : simulation ? "公开数据校准实时模拟 · 非现场实绩" : "等待接入港口";
    $("#modeMetric").textContent = "运营 / Ops";
    $("#intentTag").textContent = "energy_analysis";
    $("#confMetric").textContent = live ? "中" : simulation ? "模拟" : "不适用";
    $("#evMetric").textContent = String(state.currentEvidence.length);
    $("#next").innerHTML = `<button type="button" data-action="generate-report">${icon("report")}生成详细报告</button><button type="button" data-task-template="analyze-energy">${icon("spark")}帮我逐步分析</button><button type="button" data-q="请预测未来 7 日港口能耗趋势。" data-mode="expert">${icon("chart")}能耗趋势预测</button>`;
    updateGroundingState(live || simulation ? { grounded:true, coverage:1, source_quality:live ? "live_verified" : "public_data_calibrated_simulation", evidence:state.currentEvidence } : { grounded:false, coverage:0, source_quality:"unverified", refusal_reason:"live_data_connection_required", evidence:[] });
    setView("chat", { silent:true });
    applyEnergySummary(state.dashboard.energy || fallbackDashboard.energy);
    renderConversationTranscript();
    setHeroState("idle");
  }

  function restoreTopic(id) {
    const item = state.topics.find((topic) => topic.id === id);
    if (!item) return;
    if (item.sessionId && item.sessionId !== state.sessionId) {
      state.sessionId = item.sessionId;
      localStorage.setItem(STORAGE.sessionId, state.sessionId);
      state.conversationTurns = state.topics
        .filter((topic) => topic.sessionId === state.sessionId)
        .sort((left, right) => new Date(left.createdAt) - new Date(right.createdAt));
      persist(STORAGE.turns, state.conversationTurns);
    }
    closeModal();
    setView("chat", { silent:true });
    stopGeneration(false);
    state.currentQuestion = item.question || "";
    state.currentAnswer = item.answer || "";
    state.currentEvidence = Array.isArray(item.evidence) ? item.evidence : [];
    state.currentVerification = item.answer_verification || null;
    state.currentMode = item.mode || "expert";
    state.currentIntent = item.intent || "knowledge";
    state.currentConfidence = item.confidence || "-";
    $("#question").value = item.question || "";
    $("#mode").value = item.mode || "expert";
    $("#modeShortLabel").textContent = modeShort(item.mode);
    $("#currentQuestion").textContent = item.question || "";
    renderStructuredAnswer(
      $("#answer"),
      item.answer || "",
      item.question || "",
      item.intent || "knowledge"
    );
    $("#responseKpis").hidden = !["energy_analysis", "energy_carbon"].includes(item.intent);
    $("#analysisTitle").textContent = intentTitle(item.intent);
    $("#responseStatus").textContent = "已恢复历史对话";
    $("#modeMetric").textContent = modeLabel(item.mode);
    $("#evMetric").textContent = String(state.currentEvidence.length);
    $("#confMetric").textContent = item.confidence || "-";
    $("#intentTag").textContent = item.intent || "knowledge";
    updateGroundingState(item);
    renderNextQuestions(Array.isArray(item.next_questions) ? item.next_questions : [], item.mode, item.question);
    renderConversationTranscript({ excludeLatest:true });
  }

  function updateCounts() {
    const sessionCount = new Set(
      state.topics.map((item) => item.sessionId || "legacy")
    ).size;
    $("#historyCount").textContent = String(sessionCount);
    $("#favoriteCount").textContent = String(state.favorites.length);
    const running = state.tasks.filter((task) => task.status === "running").length;
    $("#taskNavBadge").textContent = String(running);
    $("#taskNavBadge").classList.toggle("show", running > 0);
  }

  function openModal(title, subtitle, body, footer = "", kind = "generic") {
    state.modalKind = kind;
    state.lastFocused = document.activeElement;
    $("#modalTitle").textContent = title;
    $("#modalSubtitle").textContent = subtitle || "";
    $("#modalBody").innerHTML = body;
    $("#modalFooter").innerHTML = footer;
    $("#genericModal").dataset.kind = kind;
    $("#modalBackdrop").hidden = false;
    $("#genericModal").hidden = false;
    setTimeout(() => $("#genericModal .icon-button")?.focus(), 20);
  }

  function closeModal(force = false) {
    if (!force && state.modalKind === "linked-systems-startup-confirm" && state.linkedStartup) {
      rejectLinkedSystemsStartup();
      return;
    }
    if (!force && state.modalKind === "linked-systems-startup-progress" && state.linkedStartup) {
      toast("联动系统正在启动", "小懿会在健康检查完成后自动继续原流程。", "info", 3200);
      return;
    }
    if (state.modalKind === "knowledge-intake-submit") state.pendingAttachment = null;
    $("#modalBackdrop").hidden = true;
    $("#genericModal").hidden = true;
    delete $("#genericModal").dataset.kind;
    state.modalKind = null;
    state.lastFocused?.focus?.();
  }

  function linkedStartupItems(items = []) {
    const targets = new Map();
    items.forEach((item) => {
      const current = targets.get(item.target) || { target:item.target, labels:[] };
      if (!current.labels.includes(item.label)) current.labels.push(item.label);
      targets.set(item.target, current);
    });
    return [...targets.values()];
  }

  function linkedStartupCards(items, systems = {}) {
    return `<div class="linked-startup-list">${items.map((item) => {
      const runtime = systems[item.target];
      const status = runtime?.state || "offline";
      const statusLabel = runtime?.running ? "ONLINE" : status === "starting" ? "STARTING" : status === "error" ? "ERROR" : status === "port_conflict" ? "PORT CONFLICT" : "OFFLINE";
      return `<article class="linked-startup-card ${escapeHtml(status)}"><i>${icon(runtime?.running ? "check" : status === "error" || status === "port_conflict" ? "alert" : "spark")}</i><div><strong>${escapeHtml(item.labels.join("、"))}</strong><span>${escapeHtml(runtime?.message || "未检测到服务，等待操作员确认启动。")}</span></div><b>${statusLabel}</b></article>`;
    }).join("")}</div>`;
  }

  function requestLinkedSystemsStartup(items, missionLabel) {
    const targets = linkedStartupItems(items);
    if (!targets.length) return Promise.resolve({ all_ready:true, systems:{} });
    if (state.linkedStartup) return Promise.reject(new Error("已有联动系统启动请求等待处理"));
    return new Promise((resolve, reject) => {
      state.linkedStartup = { targets, missionLabel, resolve, reject, status:"awaiting" };
      openModal(
        "检测到联动系统未启动",
        `${missionLabel}尚缺 ${targets.length} 个本机服务，是否由小懿启动后自动继续？`,
        `${linkedStartupCards(targets)}<div class="drawer-note"><strong>启动边界：</strong>只能启动登记在白名单中的本机仿真系统；启动不等于生产授权，真实码头、设备和船舶指令仍保持锁定。</div>`,
        `<button type="button" class="drawer-button secondary" data-modal-action="reject-linked-systems-startup">取消并停止</button><button type="button" class="drawer-button warning" data-modal-action="confirm-linked-systems-startup">确认并启动</button>`,
        "linked-systems-startup-confirm"
      );
    });
  }

  function rejectLinkedSystemsStartup() {
    const pending = state.linkedStartup;
    if (!pending || pending.status !== "awaiting") return;
    state.linkedStartup = null;
    closeModal(true);
    pending.reject(new Error("操作员取消启动缺失的联动系统，已安全停止后续流程"));
  }

  async function confirmLinkedSystemsStartup() {
    const pending = state.linkedStartup;
    if (!pending || pending.status !== "awaiting") return;
    pending.status = "starting";
    state.modalKind = "linked-systems-startup-progress";
    $("#genericModal").dataset.kind = state.modalKind;
    $("#modalTitle").textContent = "小懿正在启动联动系统";
    $("#modalSubtitle").textContent = "启动完成并通过业务健康检查后，原任务会自动继续。";
    $("#modalBody").innerHTML = `${linkedStartupCards(pending.targets)}<div class="drawer-note"><strong>当前状态：</strong>正在拉起白名单进程并等待业务接口，不会跳过健康检查。</div>`;
    $("#modalFooter").innerHTML = `<button type="button" class="drawer-button secondary" disabled>启动中…</button>`;
    try {
      const targetIds = pending.targets.map((item) => item.target);
      const launched = await api("/api/linked-systems/launch", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ targets:targetIds }), timeoutMs:20000
      });
      const launchFailure = Object.values(launched.systems || {}).find((item) => ["error","port_conflict"].includes(item.state));
      if (launchFailure) throw new Error(`${launchFailure.name}启动失败：${launchFailure.message}`);
      const deadline = Date.now() + 120000;
      let runtime = null;
      while (Date.now() < deadline) {
        runtime = await api(`/api/linked-systems/status?targets=${encodeURIComponent(targetIds.join(","))}`, { timeoutMs:10000 });
        $("#modalBody").innerHTML = `${linkedStartupCards(pending.targets, runtime.systems || {})}<div class="drawer-note"><strong>安全续跑：</strong>所有系统都必须返回业务健康状态；任一进程失败或端口冲突，当前计划仍会停止。</div>`;
        const failed = Object.values(runtime.systems || {}).find((item) => ["error","port_conflict"].includes(item.state));
        if (failed) throw new Error(`${failed.name}启动失败：${failed.message}`);
        if (runtime.all_ready) {
          state.linkedStartup = null;
          closeModal(true);
          toast("联动系统已就绪", "健康检查已通过，小懿正在自动继续原流程。", "success", 4200);
          pending.resolve(runtime);
          return;
        }
        await sleep(850);
      }
      throw new Error("联动系统在120秒内未全部就绪，已停止后续流程");
    } catch (error) {
      state.linkedStartup = null;
      closeModal(true);
      pending.reject(error);
    }
  }

  function openHistory() {
    const grouped = new Map();
    state.topics.forEach((item) => {
      const sessionId = item.sessionId || "legacy";
      const group = grouped.get(sessionId) || { sessionId, turns:[] };
      group.turns.push(item);
      grouped.set(sessionId, group);
    });
    const conversations = [...grouped.values()].map((group) => {
      const turns = group.turns.sort((left, right) => new Date(left.createdAt) - new Date(right.createdAt));
      return { ...group, turns, first:turns[0], latest:turns[turns.length - 1] };
    }).sort((left, right) => new Date(right.latest.createdAt) - new Date(left.latest.createdAt));
    const body = `<div class="history-toolbar"><span>最近 ${conversations.length} 个连续会话保存在本机浏览器中</span><button type="button" class="text-button danger-button" data-modal-action="clear-history">清空历史</button></div><div class="history-list">${conversations.length ? conversations.map((item) => `<div class="history-item"><button type="button" data-conversation-id="${escapeHtml(item.sessionId)}"><strong>${escapeHtml(topicTitle(item.first.question))}</strong><span>${escapeHtml(displayEvidenceMarkers(item.latest.answer || "")).slice(0,90)}${String(item.latest.answer || "").length > 90 ? "..." : ""}</span><footer><em>${formatDateTime(item.latest.createdAt)}</em><em>${item.turns.length} 轮连续对话</em></footer></button></div>`).join("") : `<div class="task-empty"><div>${icon("history")}<strong>暂无对话历史</strong><span>完成一次提问后会自动保存在这里</span></div></div>`}</div>`;
    openModal("对话历史", "按会话归档；同一窗口消息连续显示并共享上下文", body, "", "history");
  }

  async function loadServerConversation() {
    const requestedSessionId = state.sessionId;
    const localTurns = state.topics
      .filter((item) => item.sessionId === requestedSessionId)
      .sort((left, right) => new Date(left.createdAt) - new Date(right.createdAt));
    if (localTurns.length) {
      state.conversationTurns = localTurns.slice(-40);
      persist(STORAGE.turns, state.conversationTurns);
      return;
    }
    try {
      const history = await api(`/api/conversations/${encodeURIComponent(requestedSessionId)}?limit=40`);
      if (state.sessionId !== requestedSessionId) return;
      const loadedTurns = (history.items || []).map((item) => {
        const response = item.response || {};
        return {
          id:response.answer_id || item.id, sessionId:requestedSessionId,
          title:topicTitle(item.question), question:item.question,
          answer:response.answer || "", mode:response.mode || "expert", intent:response.intent || "knowledge",
          confidence:response.confidence || "-", evidence:response.evidence || [], next_questions:response.next_questions || [],
          grounded:Boolean(response.grounded), coverage:Number(response.coverage || 0), source_quality:response.source_quality || "unverified",
          refusal_reason:response.refusal_reason || null, strict_evidence:Boolean(response.strict_evidence),
          answer_verification:response.answer_verification || null, createdAt:item.created_at
        };
      });
      if (loadedTurns.length) {
        state.topics = [
          ...loadedTurns,
          ...state.topics.filter((item) => item.sessionId !== requestedSessionId)
        ].slice(0,200);
        state.conversationTurns = [...loadedTurns]
          .sort((left, right) => new Date(left.createdAt) - new Date(right.createdAt));
        persist(STORAGE.topics, state.topics);
        persist(STORAGE.turns, state.conversationTurns);
      }
      updateCounts();
    } catch { /* production may require a token before history can be restored */ }
  }

  function openFavorites() {
    const body = `<div class="favorite-list">${state.favorites.length ? state.favorites.map((item) => `<div class="favorite-item"><button type="button" data-favorite-id="${escapeHtml(item.id)}"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(displayEvidenceMarkers(item.answer)).slice(0,110)}...</span><footer><em>${formatDateTime(item.createdAt)}</em><em>${escapeHtml(modeLabel(item.mode))}</em></footer></button></div>`).join("") : `<div class="task-empty"><div>${icon("star")}<strong>还没有收藏</strong><span>点击回答右上角的星标即可收藏</span></div></div>`}</div>`;
    openModal("我的收藏", `${state.favorites.length} 条已收藏专业回答`, body, "", "favorites");
  }

  async function openCommands() {
    openModal("一线操作助手", "正在读取岗位化快捷问法", `<div class="task-empty"><div>${icon("spark")}<strong>正在准备现场问法</strong><span>口语提问、业务对象追问、态势与知识证据分层</span></div></div>`, "", "commands");
    try {
      const payload = await api("/api/operator/scenarios");
      $("#modalSubtitle").textContent = payload.usage;
      $("#modalBody").innerHTML = `<div class="drawer-note"><strong>安全边界：</strong>${escapeHtml(payload.safety_boundary)}</div><div class="command-list">${payload.items.map((item) => `<button type="button" class="command-item" data-q="${escapeHtml(item.prompt)}" data-mode="ops"><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.role)} · 直接带入工作台业务对象</span></button>`).join("")}</div>`;
    } catch (error) {
      $("#modalBody").innerHTML = `<div class="task-empty"><div>${icon("alert")}<strong>一线问法加载失败</strong><span>${escapeHtml(error.message)}</span></div></div>`;
    }
  }

  function renderHubOverview(systemsPayload, capabilitiesPayload, evaluationPayload, governancePayload) {
    const priorities = evaluationPayload.seven_priorities || [];
    const systemItems = systemsPayload.items || [];
    const benchmark = evaluationPayload.latest_benchmark || {};
    const knowledge = evaluationPayload.knowledge || {};
    const implementedCount = priorities.filter((item) => item.status === "ready").length;
    const connectedSystemCount = systemItems.filter((item) => item.mode === "live").length;
    const benchmarkAvailable = benchmark.status !== "not_run_in_this_process";
    const benchmarkLabel = benchmark.status === "pinned_release_evidence"
      ? "固定发布报告（非本进程重跑）"
      : benchmarkAvailable ? "本进程评测结果" : "本进程尚未评测";
    const metricPercent = (value) => benchmarkAvailable
      ? `${Math.round(Number(value || 0) * 100)}%`
      : "待运行";
    const command = "分析 CNYTN 泊位 3 未来3小时岸电风险，并告诉我去哪个系统看详情";
    $("#modalSubtitle").textContent = `${implementedCount}/7 个模块已实现 · ${connectedSystemCount}/${systemItems.length} 个外部系统联机 · ${capabilitiesPayload.total || 0} 项只读契约`;
    $("#modalBody").innerHTML = `<div class="intelligence-hub">
      <div class="hub-boundary">${icon("alert")}<div><strong>隔离边界</strong><span>小懿只做知识检索、能力选择、只读预览、结果解释和原系统交接；默认不会访问或改变其他系统。</span></div></div>
      <section class="hub-section"><div class="hub-section-heading"><div><strong>七项能力模块</strong><span>模块实现状态不等于外部系统在线或生产授权</span></div><span class="status-pill"><i></i>${implementedCount} / 7 IMPLEMENTED</span></div><div class="hub-priority-grid">${priorities.map((item) => `<article><b>0${item.id}</b><div><strong>${escapeHtml(item.name)}</strong><span>${item.status === "ready" ? "代码与接口已实现" : escapeHtml(item.status)}</span></div><em>${item.status === "ready" ? "IMPLEMENTED" : "CHECK"}</em></article>`).join("")}</div></section>
      <section class="hub-section"><div class="hub-section-heading"><div><strong>跨系统能力注册表</strong><span>仅登记能力契约，不复制其他系统业务逻辑</span></div><span>${capabilitiesPayload.total || 0} CAPABILITIES</span></div><div class="hub-system-grid">${systemItems.map((system) => `<article><header><div><strong>${escapeHtml(system.name)}</strong><small>${escapeHtml(system.english_name)}</small></div><span class="hub-mode ${escapeHtml(system.mode)}">${escapeHtml(system.mode === "demo" ? "ISOLATED" : system.mode.toUpperCase())}</span></header><p>${escapeHtml(system.role)}</p><footer><span>${system.capabilities.length} 项能力</span><span>${system.mode === "live" ? "只读联机" : "隔离预览"}</span></footer></article>`).join("")}</div></section>
      <section class="hub-section hub-demo-section"><div class="hub-section-heading"><div><strong>跨系统编排验证</strong><span>输入自然语言，查看上下文识别、能力路由、证据融合和原系统交接</span></div></div><div class="hub-command-row"><textarea id="hubCommand" rows="2">${escapeHtml(command)}</textarea><button type="button" class="primary-button" data-action="hub-run-demo">开始编排</button></div><div id="hubOrchestrationResult" class="hub-result"><div class="task-empty"><div>${icon("spark")}<strong>等待运行验证</strong><span>默认 dry-run，不会访问或改变其他系统</span></div></div></div></section>
      <section class="hub-section" data-hub-section="evaluation"><div class="hub-section-heading"><div><strong>RAG 评测与反馈闭环</strong><span>${knowledge.documents || 0} 份文档 · ${knowledge.chunks || 0} 个片段 · ${knowledge.official_documents || 0} 份官方来源 · ${escapeHtml(benchmarkLabel)}</span></div><button type="button" class="outline-button" data-action="hub-run-evaluation">本机重新评测</button></div><div class="hub-metrics"><div><span>检索方法</span><strong>${escapeHtml(benchmark.retrieval_method || "hybrid_sparse_v2")}</strong></div><div><span>Hybrid Hit@5</span><strong id="hubHitMetric">${metricPercent(benchmark.resume_safe_metrics?.hybrid_hit_at_5 ?? benchmark.hit_at_k)}</strong></div><div><span>BM25 Hit@5</span><strong id="hubBaselineMetric">${metricPercent(benchmark.resume_safe_metrics?.bm25_hit_at_5)}</strong></div><div><span>官方要求通过率</span><strong id="hubOfficialMetric">${metricPercent(benchmark.official_requirement_pass_rate)}</strong></div><div><span>证据策略通过率</span><strong id="hubPolicyMetric">${metricPercent(benchmark.policy_safety_pass_rate)}</strong></div><div><span>持久审计</span><strong>${Number(governancePayload.audit_events || 0)} 条</strong></div></div><div class="hub-feedback-row"><select id="hubFeedbackRating"><option value="5">5 · 很准确</option><option value="4">4 · 基本准确</option><option value="3">3 · 需要补充</option><option value="2">2 · 有明显问题</option><option value="1">1 · 不可用</option></select><input id="hubFeedbackCorrection" value="建议补充适用港口、时间范围和证据来源后再形成结论。" aria-label="反馈修订建议"><button type="button" class="outline-button" data-action="hub-submit-feedback">提交待审核</button></div><div id="hubFeedbackStatus" class="hub-inline-status">固定报告不是本次页面启动后的重跑；点击“本机重新评测”才会生成本进程结果。反馈只进入人工审核队列。</div></section>
    </div>`;
  }

  async function openIntelligenceHub(focusSection = "") {
    openModal("小懿智能联动中心", "正在读取七项能力、系统注册表与评测状态", `<div class="task-empty"><div>${icon("spark")}<strong>正在装载智能中枢</strong><span>不会访问或改变其他系统</span></div></div>`, "", "intelligence-hub");
    try {
      const [systemsPayload, capabilitiesPayload, evaluationPayload, governancePayload] = await Promise.all([
        api("/api/hub/systems"), api("/api/hub/capabilities"), api("/api/evaluation/summary"), api("/api/governance/metrics")
      ]);
      if (state.modalKind !== "intelligence-hub") return;
      renderHubOverview(systemsPayload, capabilitiesPayload, evaluationPayload, governancePayload);
      if (focusSection) {
        const section = $(`[data-hub-section="${focusSection}"]`);
        if (section) {
          section.classList.add("hub-section-focus");
          requestAnimationFrame(() => section.scrollIntoView({ block:"start", behavior:"smooth" }));
        }
      }
    } catch (error) {
      if (state.modalKind !== "intelligence-hub") return;
      $("#modalBody").innerHTML = `<div class="drawer-note"><strong>智能联动中心读取失败：</strong>${escapeHtml(error.message)}</div>`;
    }
  }

  async function runHubDemo() {
    const command = String($("#hubCommand")?.value || "").trim();
    const host = $("#hubOrchestrationResult");
    if (!command || !host) return;
    host.innerHTML = `<div class="task-empty"><div>${icon("spark")}<strong>正在解析、检索并规划</strong><span>当前为安全预览，不会访问其他系统</span></div></div>`;
    try {
      const result = await api("/api/orchestrator/run", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ command, session_id:"web-hub-demo", execute_read_only:false, actor_id:"web-admin", actor_role:"admin" }) });
      if (state.modalKind !== "intelligence-hub") return;
      const context = Object.entries(result.context_resolution?.context || {}).filter(([,value]) => value && typeof value !== "object");
      host.innerHTML = `<div class="hub-run-summary"><header><div><strong>${escapeHtml(result.result_summary)}</strong><span>${escapeHtml(result.intent)} · ${escapeHtml(result.correlation_id)}</span></div><span class="status-pill"><i></i>${result.grounded ? "GROUNDED" : "PREVIEW"}</span></header><div class="hub-context-strip">${context.map(([key,value]) => `<span><small>${escapeHtml(key)}</small><b>${escapeHtml(value)}</b></span>`).join("") || `<span><b>未识别显式业务对象</b></span>`}</div><div class="hub-step-list">${result.steps.map((step) => `<article class="${escapeHtml(step.status)}"><i>${String(step.order).padStart(2,"0")}</i><div><strong>${escapeHtml(step.phase)} · ${escapeHtml(step.action)}</strong><span>${escapeHtml(step.detail)}</span></div><em>${escapeHtml(step.status)}</em></article>`).join("")}</div><footer><span>${escapeHtml(result.evidence_summary)}</span><div>${(result.handoff_links || []).map((link) => `<a href="${escapeHtml(link.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(link.label)} →</a>`).join("")}</div></footer></div>`;
    } catch (error) {
      host.innerHTML = `<div class="drawer-note"><strong>编排验证失败：</strong>${escapeHtml(error.message)}</div>`;
    }
  }

  async function runHubEvaluation() {
    const button = $('[data-action="hub-run-evaluation"]');
    if (button) button.disabled = true;
    try {
      const result = await api("/api/evaluation/run", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({top_k:5}), timeoutMs:300000 });
      const metrics = result.resume_safe_metrics || {};
      if ($("#hubHitMetric")) $("#hubHitMetric").textContent = `${Math.round(Number(metrics.hybrid_hit_at_5 ?? result.hit_at_k ?? 0) * 100)}%`;
      if ($("#hubBaselineMetric")) $("#hubBaselineMetric").textContent = `${Math.round(Number(metrics.bm25_hit_at_5 || 0) * 100)}%`;
      if ($("#hubOfficialMetric")) $("#hubOfficialMetric").textContent = `${Math.round(Number(result.official_requirement_pass_rate || 0) * 100)}%`;
      if ($("#hubPolicyMetric")) $("#hubPolicyMetric").textContent = `${Math.round(Number(result.policy_safety_pass_rate || 0) * 100)}%`;
      toast("RAG 固定评测完成", `${result.benchmark_count} 条问题 · Hybrid Hit@5 ${Math.round(Number(metrics.hybrid_hit_at_5 || 0) * 100)}% · BM25 ${Math.round(Number(metrics.bm25_hit_at_5 || 0) * 100)}% · 策略 ${Math.round(result.policy_safety_pass_rate * 100)}%`, result.passed ? "success" : "warning", 5200);
    } catch (error) {
      toast("RAG 评测失败", error.message, "warning");
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function submitHubFeedback() {
    const correction = String($("#hubFeedbackCorrection")?.value || "").trim();
    const rating = Number($("#hubFeedbackRating")?.value || 3);
    const status = $("#hubFeedbackStatus");
    if (!correction || !status) return;
    try {
      const result = await api("/api/evaluation/feedback", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ question:String($("#hubCommand")?.value || "智能联动中心验证"), rating, correction, submitted_by:"web-admin" }) });
      status.innerHTML = `<strong>已提交：</strong>${escapeHtml(result.id)} · ${escapeHtml(result.status)}；需管理员审核后才能进入知识待审核区。`;
      toast("反馈已进入人工审核队列", result.id, "success");
    } catch (error) {
      status.textContent = `反馈提交失败：${error.message}`;
    }
  }

  const SYSTEM_LINKAGE_CATALOG = [
    { target:"port-dt-multi", name:"港口数字孪生", english:"PORT DIGITAL TWIN", icon:"agv", action:"自然语言动作映射", detail:"读取孪生态势并将小懿指令映射为可审计 dry-run 动作包" },
    { target:"energy-cockpit", name:"能碳驾驶舱", english:"ENERGY & CARBON", icon:"chart", action:"离线策略重算", detail:"目标系统在线时调用能碳适配器，重算成本、碳排、岸电与调度指标" },
    { target:"malacca-sandbox", name:"马六甲推演", english:"PORT SANDBOX", icon:"spark", action:"沙盘与RL读取", detail:"读取公开数据快照、场景态势和训练引擎能力" },
    { target:"sailing-simulator", name:"航行模拟器", english:"GODOT SAILING SIM", icon:"ship", action:"航行场景验证", detail:"注入航线、船舶与风险事件，回传安全间距、碰撞和碳排结果" }
  ];

  function linkageStateLabel(runtime = {}) {
    if (runtime.running) return "ONLINE";
    if (runtime.state === "starting") return "STARTING";
    if (runtime.state === "unavailable") return "UNAVAILABLE";
    if (runtime.state === "error" || runtime.state === "port_conflict") return "ERROR";
    return "OFFLINE";
  }

  function linkageResultMarkup(result) {
    if (!result) return `<div class="system-linkage-empty">尚未执行联动任务</div>`;
    if (result.status !== "completed") {
      return `<div class="system-linkage-error">${icon("alert")}<span>${escapeHtml(result.error || "联动执行失败")}</span></div>`;
    }
    const summary = result.summary || {};
    const facts = [];
    if (result.target === "port-dt-multi") {
      facts.push(["动作", summary.action_label || summary.action_id || "已映射"]);
      facts.push(["执行", summary.execution_status || "dry-run"]);
      facts.push(["人工确认", summary.requires_human_confirm ? "需要" : "不需要"]);
    } else if (result.target === "energy-cockpit") {
      facts.push(["场景", summary.scenario_id || "—"]);
      facts.push(["减排", summary.abatement_ton == null ? "—" : `${formatNumber(summary.abatement_ton, 2)} t`]);
      facts.push(["节省", summary.total_cost_saving_cny == null ? "—" : `¥${formatNumber(summary.total_cost_saving_cny, 0)}`]);
      facts.push(["数据集", summary.dataset_id || "—"]);
    } else if (result.target === "malacca-sandbox") {
      facts.push(["引擎", summary.engine || "—"]);
      facts.push(["算法", (summary.algorithms || []).join(" / ") || "—"]);
      facts.push(["场景", summary.scenario?.id || "—"]);
      facts.push(["生产写入", summary.production_write_enabled ? "开启" : "关闭"]);
    } else {
      facts.push(["安全通过", summary.safePass === true ? "是" : summary.safePass === false ? "否" : "—"]);
      facts.push(["风险", summary.riskLevel || "—"]);
      facts.push(["推荐航速", summary.recommendedSpeedKnots == null ? "—" : `${summary.recommendedSpeedKnots} kn`]);
      facts.push(["最小间距", summary.minClearanceMeters == null ? "—" : `${summary.minClearanceMeters} m`]);
      facts.push(["碰撞/搁浅", `${summary.collisionCount ?? "—"} / ${summary.groundingCount ?? "—"}`]);
      facts.push(["碳排变化", summary.carbonDeltaTons == null ? "—" : `${summary.carbonDeltaTons} t`]);
    }
    return `<div class="system-linkage-result"><header><strong>最近一次本机回执 · ${escapeHtml(result.action || "联动任务完成")}</strong><span>${escapeHtml(result.trace_id || "")}</span></header><div>${facts.map(([label,value]) => `<span><small>${escapeHtml(label)}</small><b>${escapeHtml(value)}</b></span>`).join("")}</div><footer><span>${Number(result.duration_ms || 0).toLocaleString("zh-CN")} ms</span><span>SHA-256 ${escapeHtml(String(result.payload_sha256 || "").slice(0,12))}…</span></footer></div>`;
  }

  function renderSystemLinkage(payload) {
    state.systemLinkage = payload;
    const systems = payload.systems || {};
    if ($("#systemLaunchBadge")) $("#systemLaunchBadge").textContent = `${payload.online_count || 0}/${payload.total || 4}`;
    if (state.modalKind !== "system-linkage") return;
    $("#modalSubtitle").textContent = `${payload.online_count || 0}/${payload.total || 4} 个系统在线 · 本机API / Godot文件桥 · 全链路审计`;
    $("#modalBody").innerHTML = `<div class="system-linkage-hub">
      <section class="system-linkage-hero">
        <div><span>LOCAL MULTI-SYSTEM ORCHESTRATION</span><strong>小懿四系统联动控制台</strong><p>统一启动、上下文传递、本机适配器调用、模拟器场景注入、结果回写与证据哈希。</p></div>
        <span class="system-linkage-total">${payload.online_count || 0}<small>/ 4 ONLINE</small></span>
      </section>
      <section class="system-linkage-command">
        <div><label for="systemLinkageCommand">跨系统演示指令</label><textarea id="systemLinkageCommand" rows="2">针对当前港航作业进行态势读取、能碳策略重算和航行风险验证，并回传各系统结果</textarea></div>
        <button type="button" class="primary-button" data-linkage-run="all" ${state.systemLinkageBusy ? "disabled" : ""}>${icon("spark")}一键联动演示</button>
        <button type="button" class="outline-button" data-linkage-start="all" ${state.systemLinkageBusy ? "disabled" : ""}>${icon("play")}启动全部</button>
        <button type="button" class="outline-button" data-linkage-refresh>${icon("command")}刷新状态</button>
      </section>
      <div class="system-linkage-boundary">${icon("alert")}<span>${escapeHtml(payload.execution_boundary || "联动仅面向本机仿真与离线数据，不下发生产指令。")}</span></div>
      <section class="system-linkage-grid">${SYSTEM_LINKAGE_CATALOG.map((item) => {
        const node = systems[item.target] || {};
        const runtime = node.runtime || {};
        const online = Boolean(runtime.running);
        const busy = state.systemLinkageBusy === item.target || state.systemLinkageBusy === "all";
        const stateLabel = linkageStateLabel(runtime);
        return `<article class="system-linkage-card ${online ? "online" : ""}" data-system-linkage-card="${item.target}">
          <header><span class="system-linkage-icon">${icon(item.icon)}</span><div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.english)}</small></div><em class="linkage-state ${escapeHtml(String(runtime.state || "offline"))}"><i></i>${escapeHtml(stateLabel)}</em></header>
          <p>${escapeHtml(item.detail)}</p>
          <div class="system-linkage-action"><span>适配器联动能力</span><strong>${escapeHtml(item.action)}</strong></div>
          ${busy ? `<div class="system-linkage-running"><i></i><span>正在启动并执行，等待目标系统回写…</span></div>` : linkageResultMarkup(node.last_result)}
          <footer>
            <button type="button" class="drawer-button" data-linkage-run="${item.target}" ${busy ? "disabled" : ""}>${icon("spark")}${online ? "执行联动" : "启动并联动"}</button>
            <button type="button" class="drawer-button secondary" data-linkage-open="${item.target}" ${online ? "" : "disabled"}>${icon(item.target === "sailing-simulator" ? "ship" : "play")}${item.target === "sailing-simulator" ? "切换窗口" : "打开系统"}</button>
          </footer>
          <small class="system-linkage-message">${escapeHtml(runtime.message || "等待读取运行状态")}</small>
        </article>`;
      }).join("")}</section>
      <footer class="system-linkage-audit"><span>桥接请求文件：${payload.bridge?.request_exists ? "历史文件存在" : "待生成"}</span><span>历史结果文件：${payload.bridge?.result_exists ? "存在（非本次执行）" : "无"}</span><span>生产写入：关闭</span></footer>
    </div>`;
  }

  async function loadSystemLinkage({ render = true } = {}) {
    try {
      const payload = await api("/api/system-linkage/overview", { timeoutMs:15000 });
      if (render || state.modalKind === "system-linkage") renderSystemLinkage(payload);
      else {
        state.systemLinkage = payload;
        if ($("#systemLaunchBadge")) $("#systemLaunchBadge").textContent = `${payload.online_count || 0}/${payload.total || 4}`;
      }
      return payload;
    } catch (error) {
      if (state.modalKind === "system-linkage") {
        $("#modalBody").innerHTML = `<div class="drawer-note"><strong>四系统联动状态读取失败：</strong>${escapeHtml(error.message)}</div>`;
      }
      throw error;
    }
  }

  async function openSystemLinkage() {
    openModal("四系统联动中心", "正在读取本机服务、模拟器桥接与最近执行回执", `<div class="task-empty"><div>${icon("spark")}<strong>正在建立联动拓扑</strong><span>读取四个系统的真实运行状态</span></div></div>`, "", "system-linkage");
    try { await loadSystemLinkage(); } catch { /* modal contains the error */ }
  }

  async function startSystemLinkage(target) {
    const targets = target === "all" ? SYSTEM_LINKAGE_CATALOG.map((item) => item.target) : [target];
    state.systemLinkageBusy = target;
    if (state.systemLinkage) renderSystemLinkage(state.systemLinkage);
    try {
      const result = await api("/api/system-linkage/start", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ targets }), timeoutMs:180000
      });
      toast(result.all_ready ? "四系统已就绪" : "部分系统未就绪", `${Object.values(result.systems || {}).filter((item) => item.running).length}/${targets.length} 个目标在线`, result.all_ready ? "success" : "warning", 5200);
    } catch (error) {
      toast("系统启动失败", error.message, "warning", 6000);
    } finally {
      state.systemLinkageBusy = null;
      await loadSystemLinkage().catch(() => {});
    }
  }

  async function runSystemLinkage(target) {
    const command = String($("#systemLinkageCommand")?.value || "读取当前业务态势并执行联动验证").trim();
    state.systemLinkageBusy = target;
    if (state.systemLinkage) renderSystemLinkage(state.systemLinkage);
    try {
      const response = await api("/api/system-linkage/command", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ target, command, session_id:state.sessionId, auto_start:true, wait_seconds:30 }),
        timeoutMs:240000
      });
      toast(response.all_succeeded ? "跨系统联动完成" : "跨系统联动部分完成", `${response.succeeded}/${response.total} 项成功 · ${response.correlation_id}`, response.all_succeeded ? "success" : "warning", 6500);
    } catch (error) {
      toast("联动执行失败", error.message, "warning", 6500);
    } finally {
      state.systemLinkageBusy = null;
      await loadSystemLinkage().catch(() => {});
    }
  }

  async function openLinkedSystem(target) {
    const node = state.systemLinkage?.systems?.[target];
    const runtime = node?.runtime || {};
    if (!runtime.running) {
      toast("目标系统尚未在线", runtime.message || "请先启动目标系统。", "warning");
      return;
    }
    if (target === "sailing-simulator") {
      try {
        await api("/api/sailing-simulator/focus", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({target}), timeoutMs:8000 });
      } catch (error) {
        toast("无法切换模拟器窗口", error.message, "warning");
      }
      return;
    }
    const url = safeUrl(runtime.url);
    if (!url) return;
    const opened = window.open(url, "_blank", "noopener,noreferrer");
    if (!opened) window.location.assign(url);
  }

  function favoriteCurrent() {
    if (!state.currentAnswer) { toast("当前没有可收藏内容", "先完成一次问答。", "warning"); return; }
    const id = `${state.currentQuestion}|${state.currentMode}`;
    if (state.favorites.some((item) => item.id === id)) { toast("这条回答已收藏", "可在左侧“我的收藏”中查看。", "info"); return; }
    state.favorites = [{ id, title:topicTitle(state.currentQuestion), question:state.currentQuestion, answer:state.currentAnswer, evidence:state.currentEvidence, mode:state.currentMode, intent:state.currentIntent, confidence:state.currentConfidence, createdAt:new Date().toISOString() }, ...state.favorites].slice(0,50);
    persist(STORAGE.favorites, state.favorites); updateCounts();
    toast("已收藏当前回答", "问题、回答和证据已保存到本机。", "success");
  }

  function openEvidence() {
    const evidence = state.currentEvidence || [];
    const verification = state.currentVerification;
    const verificationBanner = verification && verification.status !== "not_applicable"
      ? `<div class="drawer-note"><strong>回答后门禁：</strong>${verification.status === "passed" ? "通过" : "需要复核"} · 引用有效性 ${(Number(verification.citation_validity || 0) * 100).toFixed(0)}% · 主张词面对齐 ${(Number(verification.evidence_alignment || 0) * 100).toFixed(0)}% · 数字/日期/量值完整性 ${(Number(verification.numeric_integrity || 0) * 100).toFixed(0)}%<br><small>${escapeHtml(verification.scope_notice || "该门禁不替代事实或法律复核。")}</small></div>`
      : "";
    const body = evidence.length ? `${verificationBanner}<div class="evidence-list">${evidence.map((item,index) => {
      const url = safeUrl(item.source_url);
      return `<article class="evidence-item ${item.official ? "official" : ""}"><header><strong>来源 ${String(index+1).padStart(2,"0")} · ${escapeHtml(item.title)}</strong><span>${item.official ? "发布页已核验" : escapeHtml(item.source_quality || "未验证")} · ${item.citation_role === "locator_only" ? "仅定位" : "答案依据"} · 匹配分 ${Number(item.score || 0).toFixed(2)}</span></header><p>${escapeHtml(item.snippet)}</p><dl class="provenance-grid"><div><dt>来源机构</dt><dd>${escapeHtml(item.institution || "内部整理资料")}</dd></div><div><dt>内容范围</dt><dd>${escapeHtml(item.content_scope || "未登记")}</dd></div><div><dt>适用辖区</dt><dd>${escapeHtml((item.jurisdictions || []).join(" / ") || "未登记")}</dd></div><div><dt>法律效力</dt><dd>${escapeHtml(item.legal_force || "未登记")}</dd></div><div><dt>版本</dt><dd>${escapeHtml(item.version || "未登记")}</dd></div><div><dt>验证状态</dt><dd>${escapeHtml(item.verification_status || "未登记")}</dd></div><div><dt>复核状态</dt><dd>${escapeHtml(item.review_status || "未登记")}</dd></div><div><dt>索引文件</dt><dd>${escapeHtml(item.source)}</dd></div><div><dt>文档 SHA-256</dt><dd title="${escapeHtml(item.checksum_sha256 || "")}">${escapeHtml(item.checksum_sha256 || "未建立")}</dd></div><div><dt>片段 SHA-256</dt><dd title="${escapeHtml(item.chunk_checksum_sha256 || "")}">${escapeHtml(item.chunk_checksum_sha256 || "未建立")}</dd></div></dl>${item.citation_role === "locator_only" ? `<p class="source-warning">该证据只用于打开官方页面，不构成当前答案的事实依据。</p>` : ""}${url ? `<a class="source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">打开发布机构原始页面 →</a>` : `<p class="source-warning">当前资料没有外部原始链接，仅可视为内部整理来源。</p>`}</article>`;
    }).join("")}</div>` : `<div class="task-empty"><div>${icon("book")}<strong>当前没有索引证据</strong><span>专业模式会在证据不足时明确拒答，不会用生成内容冒充来源</span></div></div>`;
    openModal("依据与来源", `${evidence.length} 条已索引证据 · 来源、版本与校验和可审计`, body, "", "evidence");
  }

  const catalogStatusLabels = { indexed:"已索引", partial:"部分覆盖", planned:"待建设" };

  function catalogStatusLabel(status) {
    return catalogStatusLabels[status] || "未标记";
  }

  function renderKnowledgeCatalogResults() {
    const catalog = state.knowledgeCatalog;
    const host = $("#knowledgeCatalogResults");
    if (!catalog || !host) return;
    const query = String(state.knowledgeCatalogQuery || "").trim().toLocaleLowerCase("zh-CN");
    const status = state.knowledgeCatalogStatus || "all";
    const matched = (catalog.categories || []).map((category) => {
      const categoryText = [category.id, category.name, ...(category.recommended_authorities || []), ...(category.recommended_material_families || [])].join(" ").toLocaleLowerCase("zh-CN");
      const categoryMatches = !query || categoryText.includes(query);
      const topics = (category.topics || []).filter((topic) => {
        if (status !== "all" && topic.coverage_status !== status) return false;
        if (categoryMatches) return true;
        const topicText = [topic.id, topic.name, ...(topic.subtopics || [])].join(" ").toLocaleLowerCase("zh-CN");
        return topicText.includes(query);
      });
      return { category, topics };
    }).filter((item) => item.topics.length > 0);
    const matchedTopics = matched.reduce((sum, item) => sum + item.topics.length, 0);
    const resultLabel = $("#knowledgeCatalogResultLabel");
    if (resultLabel) resultLabel.textContent = `${matched.length} 个专业大类 · ${matchedTopics} 个主题`;
    host.innerHTML = matched.length ? matched.map(({ category, topics }) => {
      const files = category.current_kb_files || [];
      const official = category.must_use_official_sources;
      return `<details class="catalog-category-card" ${query || status !== "all" ? "open" : ""}><summary><div class="catalog-category-title"><span>${escapeHtml(category.priority)}</span><div><strong>${escapeHtml(category.name)}</strong><small>${topics.length} / ${(category.topics || []).length} 个主题 · ${files.length} 份关联索引文件</small></div></div><div class="catalog-summary-badges"><span class="catalog-status ${escapeHtml(category.coverage_status)}">${escapeHtml(catalogStatusLabel(category.coverage_status))}</span>${official ? `<span class="catalog-official">需官方资料</span>` : ""}</div></summary><div class="catalog-category-body"><div class="catalog-material-grid"><section><strong>建议权威机构</strong><div>${(category.recommended_authorities || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("") || `<span>待登记</span>`}</div></section><section><strong>资料族</strong><div>${(category.recommended_material_families || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("") || `<span>待规划</span>`}</div></section></div><div class="catalog-topic-list">${topics.map((topic) => `<article class="catalog-topic"><div><strong>${escapeHtml(topic.name)}</strong><span>${(topic.subtopics || []).map((item) => escapeHtml(item)).join(" · ")}</span></div><footer><b>${escapeHtml(topic.priority)}</b><i class="catalog-status ${escapeHtml(topic.coverage_status)}">${escapeHtml(catalogStatusLabel(topic.coverage_status))}</i>${topic.must_use_official_sources ? `<em>官方资料必需</em>` : ""}</footer></article>`).join("")}</div></div></details>`;
    }).join("") : `<div class="task-empty catalog-empty"><div>${icon("search")}<strong>没有匹配的专业主题</strong><span>请更换关键词或覆盖状态后再试</span></div></div>`;
    $$('[data-catalog-status]').forEach((button) => button.classList.toggle("active", button.dataset.catalogStatus === status));
  }

  async function openKnowledgeCatalog() {
    state.knowledgeCatalogStatus = "all";
    state.knowledgeCatalogQuery = "";
    openModal("港航专业资料目录", "正在读取专业覆盖路线图与建设状态", `<div class="task-empty"><div>${icon("book")}<strong>正在装载专业目录</strong><span>将区分已索引、部分覆盖和待建设主题</span></div></div>`, "", "knowledge-catalog");
    try {
      const catalog = await api("/api/knowledge/catalog");
      if (state.modalKind !== "knowledge-catalog") return;
      state.knowledgeCatalog = catalog;
      const summary = catalog.coverage_summary?.topics || { indexed:0, partial:0, planned:0 };
      $("#modalSubtitle").textContent = `${catalog.category_count} 大类 · ${catalog.topic_count} 个主题 · 目录版本 ${catalog.catalog_version}`;
      $("#modalBody").innerHTML = `<div class="knowledge-catalog"><div class="drawer-note catalog-roadmap"><strong>覆盖边界：</strong>${escapeHtml(catalog.roadmap_notice)}</div><div class="catalog-stats"><div><span>专业大类</span><strong>${catalog.category_count}</strong></div><div><span>专业主题</span><strong>${catalog.topic_count}</strong></div><div class="indexed"><span>已索引</span><strong>${Number(summary.indexed || 0)}</strong></div><div class="partial"><span>部分覆盖</span><strong>${Number(summary.partial || 0)}</strong></div><div class="planned"><span>待建设</span><strong>${Number(summary.planned || 0)}</strong></div></div><div class="catalog-toolbar"><label>${icon("search")}<input id="knowledgeCatalogSearch" data-catalog-search type="search" autocomplete="off" placeholder="搜索大类、主题、子主题、权威机构或资料族"></label><div role="group" aria-label="按覆盖状态筛选"><button type="button" class="active" data-catalog-status="all">全部 ${catalog.topic_count}</button><button type="button" data-catalog-status="indexed">已索引 ${Number(summary.indexed || 0)}</button><button type="button" data-catalog-status="partial">部分覆盖 ${Number(summary.partial || 0)}</button><button type="button" data-catalog-status="planned">待建设 ${Number(summary.planned || 0)}</button></div></div><div class="catalog-result-heading"><strong>目录明细</strong><span id="knowledgeCatalogResultLabel"></span></div><div id="knowledgeCatalogResults" class="catalog-results"></div><div class="drawer-note catalog-disclaimer"><strong>使用提醒：</strong>${escapeHtml(catalog.disclaimer)}</div></div>`;
      renderKnowledgeCatalogResults();
    } catch (error) {
      if (state.modalKind !== "knowledge-catalog") return;
      $("#modalBody").innerHTML = `<div class="drawer-note"><strong>专业目录读取失败：</strong>${escapeHtml(error.message)}</div>`;
    }
  }

  async function openKnowledgeSources() {
    openModal("知识来源审计", "正在读取来源登记、验证状态与文档校验和", `<div class="task-empty"><div>${icon("book")}<strong>正在核对来源登记</strong><span>官方资料与内部整理资料将分级展示</span></div></div>`, "", "knowledge-sources");
    try {
      const sources = await api("/api/knowledge/sources");
      if (state.modalKind !== "knowledge-sources") return;
      state.knowledgeSources = sources;
      renderKnowledgeSources(false);
    } catch (error) {
      $("#modalBody").innerHTML = `<div class="drawer-note"><strong>来源审计读取失败：</strong>${escapeHtml(error.message)}</div>`;
    }
  }

  async function openAuthorityCoverage() {
    openModal("权威来源覆盖矩阵", "正在读取已覆盖、待补齐与许可隔离范围", `<div class="task-empty"><div>${icon("chart")}<strong>正在核对权威来源版图</strong><span>不会把摘要、目录或受限材料标成全文</span></div></div>`, "", "authority-coverage");
    try {
      const coverage = await api("/api/knowledge/authority-coverage");
      if (state.modalKind !== "authority-coverage") return;
      const sections = Array.isArray(coverage.sections) ? coverage.sections : [];
      const entries = sections.flatMap((section) => section.entries || []);
      const count = (status) => entries.filter((item) => item.status === status).length;
      const statusLabel = { indexed_summary:"摘要已索引", indexed_directory:"目录已索引", license_isolated:"许可隔离", planned:"待补齐" };
      $("#modalSubtitle").textContent = `${sections.length} 个分区 · ${entries.length} 个来源族 · ${coverage.completeness_claim}`;
      $("#modalBody").innerHTML = `<div class="knowledge-catalog"><div class="drawer-note catalog-roadmap"><strong>完整性声明：</strong>${escapeHtml(coverage.claim_statement_zh || "当前只提供可审计的部分覆盖。")}</div><div class="catalog-stats"><div class="indexed"><span>摘要已索引</span><strong>${count("indexed_summary")}</strong></div><div class="partial"><span>目录已索引</span><strong>${count("indexed_directory")}</strong></div><div class="planned"><span>待补齐</span><strong>${count("planned")}</strong></div><div><span>许可隔离</span><strong>${count("license_isolated")}</strong></div></div>${sections.map((section) => `<section class="catalog-category"><header><div><strong>${escapeHtml(section.label_zh || section.id)}</strong><span>${escapeHtml(section.scope_note || "")}</span></div><em>${(section.entries || []).length} 项</em></header><div class="source-audit-list">${(section.entries || []).map((item) => { const url=safeUrl(item.official_url); return `<article class="source-record ${item.status === "planned" || item.status === "license_isolated" ? "unverified" : "official"}"><div class="source-record-header"><div class="source-record-title"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.organization || item.id)}</span></div><span class="source-status ${item.status === "planned" || item.status === "license_isolated" ? "unverified" : "official"}">${escapeHtml(statusLabel[item.status] || item.status)}</span></div><div class="source-provenance"><span>优先级<b>${escapeHtml(item.priority)}</b></span><span>适用辖区<b>${escapeHtml((item.jurisdictions || []).join(" / "))}</b></span><span>本地材料<b>${(item.local_artifacts || []).length} 份</b></span><span>更新频率<b>${escapeHtml(item.update_frequency)}</b></span></div><p>${escapeHtml(item.ingestion_policy || "")}</p>${url ? `<a class="source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">打开权威入口 →</a>` : ""}</article>`; }).join("")}</div></section>`).join("")}</div>`;
    } catch (error) {
      if (state.modalKind !== "authority-coverage") return;
      $("#modalBody").innerHTML = `<div class="drawer-note"><strong>覆盖矩阵读取失败：</strong>${escapeHtml(error.message)}</div>`;
    }
  }

  function renderKnowledgeSources(showAll = false) {
    const sources = state.knowledgeSources || [];
    const official = sources.filter((item) => item.official && item.source_quality === "official_verified");
    const internal = sources.filter((item) => !item.official);
    const officialSummaries = official.filter((item) => ["official_summary","publisher_guidance"].includes(item.content_scope));
    const officialLocators = official.filter((item) => ["official_directory","standard_catalog_metadata","publisher_catalog_metadata"].includes(item.content_scope));
    const officialFullText = official.filter((item) => ["official_full_text","official_excerpt"].includes(item.content_scope));
    const shown = showAll ? [...official, ...internal] : official;
    $("#modalSubtitle").textContent = `${official.length} 份官方发布来源资料 · ${internal.length} 份内部整理 · 共 ${sources.length} 份`;
    $("#modalBody").innerHTML = `<div class="source-audit"><div class="drawer-note"><strong>证据边界：</strong>官方发布页已核验不等于本地拥有法规或标准全文。条款、罚则、限值、时限和豁免问题只接受授权全文/正式摘录作为答案证据。</div><div class="source-audit-toolbar"><span>正式索引来源</span><div><button type="button" class="outline-button" data-action="knowledge-intake">查看待审核资料</button></div></div><div class="source-audit-summary"><div><span>摘要 / 指南</span><strong>${officialSummaries.length}</strong></div><div><span>目录定位</span><strong>${officialLocators.length}</strong></div><div><span>全文 / 摘录</span><strong>${officialFullText.length}</strong></div><div><span>内部整理</span><strong>${internal.length}</strong></div><div><span>索引片段</span><strong>${sources.reduce((sum,item) => sum + Number(item.chunk_count || 0), 0)}</strong></div></div><div class="source-audit-list">${shown.map((item) => {
      const url = safeUrl(item.source_url);
      return `<article class="source-record ${item.official ? "official" : "unverified"}"><div class="source-record-header"><div class="source-record-title"><strong>${escapeHtml(item.display_name)}</strong><span>${escapeHtml(item.source_id)}</span></div><span class="source-status ${item.official ? "official" : "unverified"}">${item.official ? "发布页已核验" : "内部整理"}</span></div><div class="source-provenance"><span>发布机构<b>${escapeHtml(item.institution || "未登记")}</b></span><span>内容范围<b>${escapeHtml(item.content_scope || "未登记")}</b></span><span>适用辖区<b>${escapeHtml((item.jurisdictions || []).join(" / ") || "未登记")}</b></span><span>法律效力<b>${escapeHtml(item.legal_force || "未登记")}</b></span><span>版本<b>${escapeHtml(item.version || "未登记")}</b></span><span>复核状态<b>${escapeHtml(item.review_status || "未登记")}</b></span><span>索引规模<b>${item.chunk_count} 个片段</b></span></div><div class="source-hash"><span>SHA-256</span><code title="${escapeHtml(item.document_checksum_sha256 || "")}">${escapeHtml(item.document_checksum_sha256 || "未建立")}</code>${url ? `<a class="source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">原始发布页 →</a>` : ""}</div></article>`;
    }).join("")}</div>${!showAll && internal.length ? `<button type="button" class="outline-button source-show-all" data-source-filter="all">展开 ${internal.length} 份内部整理资料</button>` : ""}</div>`;
  }

  async function openKnowledgeIntake() {
    openModal("待审核知识资料", "附件必须完成来源核验、人工审核与索引重建后才能用于回答", `<div class="task-empty"><div>${icon("book")}<strong>正在读取隔离区</strong><span>这里的内容不会被当前 RAG 检索</span></div></div>`, "", "knowledge-intake");
    try {
      const response = await api("/api/knowledge/intake");
      if (state.modalKind !== "knowledge-intake") return;
      $("#modalSubtitle").textContent = `${response.total} 份 pending_review · indexed=false`;
      $("#modalBody").innerHTML = `<div class="drawer-note"><strong>隔离边界：</strong>${escapeHtml(response.notice)}</div><div class="source-audit-list">${response.items.length ? response.items.map((item) => `<article class="source-record unverified"><div class="source-record-header"><div class="source-record-title"><strong>${escapeHtml(item.original_filename)}</strong><span>${escapeHtml(item.id)}</span></div><span class="source-status unverified">待人工审核</span></div><div class="source-provenance"><span>提交机构<b>${escapeHtml(item.institution || "未填写")}</b></span><span>声明版本<b>${escapeHtml(item.version || "未填写")}</b></span><span>资料大小<b>${Number(item.content_bytes).toLocaleString()} B</b></span></div><div class="source-hash"><span>SHA-256</span><code title="${escapeHtml(item.sha256)}">${escapeHtml(item.sha256)}</code></div></article>`).join("") : `<div class="task-empty"><div>${icon("book")}<strong>暂无待审核资料</strong><span>使用输入框左侧附件按钮提交文本、Markdown 或 CSV</span></div></div>`}</div>`;
    } catch (error) {
      $("#modalBody").innerHTML = `<div class="drawer-note"><strong>待审核区读取失败：</strong>${escapeHtml(error.message)}</div>`;
    }
  }

  async function openConnectors() {
    openModal("生产数据接入中心", "正在读取 TOS、PCS、EMS、VTS 等接入契约", `<div class="task-empty"><div>${icon("command")}<strong>正在检查接口安全状态</strong><span>待配置、契约测试、真实在线会严格区分</span></div></div>`, "", "connectors");
    try {
      state.connectors = await api("/api/connectors");
      if (state.modalKind !== "connectors") return;
      renderConnectors();
    } catch (error) {
      $("#modalBody").innerHTML = `<div class="drawer-note"><strong>接口目录读取失败：</strong>${escapeHtml(error.message)}</div>`;
    }
  }

  function renderConnectors() {
    const catalog = state.connectors;
    if (!catalog) return;
    $("#modalSubtitle").textContent = `${catalog.total} 类接口 · ${catalog.online} 个真实在线 · ${catalog.offline} 个待配置`;
    $("#modalBody").innerHTML = `<div class="connector-center"><div class="connector-summary"><div><span>接口类型</span><strong>${catalog.total}</strong></div><div><span>真实在线</span><strong>${catalog.online}</strong></div><div><span>契约测试</span><strong>${catalog.demo}</strong></div><div><span>待配置</span><strong>${catalog.offline}</strong></div></div><div class="drawer-note"><strong>接入声明：</strong>${escapeHtml(catalog.notice)}</div><div class="connector-grid">${catalog.items.map((item) => {
      const statusClass = item.health_status === "online" ? "connected" : item.health_status === "degraded" || item.health_status === "misconfigured" ? "degraded" : "offline";
      const statusLabel = item.health_status === "online" ? "真实在线" : item.mode === "demo" ? "契约测试" : item.health_status === "misconfigured" ? "配置异常" : "待接入";
      const capabilities = [...item.capabilities.read.slice(0,2), ...item.capabilities.write.slice(0,1)];
      return `<article class="connector-card ${statusClass}"><div class="connector-card-header"><i class="connector-icon">${icon(item.capabilities.read_only ? "search" : "command")}</i><div class="connector-title"><strong>${escapeHtml(item.code)} · ${escapeHtml(item.name)}</strong><span>${escapeHtml(item.english_name)}</span></div><span class="connector-status ${statusClass}">${statusLabel}</span></div><div class="connector-meta"><span>运行模式<b>${escapeHtml(item.mode === "demo" ? "contract-test" : item.mode)}</b></span><span>认证方式<b>${escapeHtml(item.auth_type)}</b></span></div><div class="connector-capabilities">${capabilities.map((capability) => `<span class="${item.capabilities.write.includes(capability) ? "write" : ""}">${escapeHtml(capability)}</span>`).join("")}</div><div class="connector-actions"><button type="button" data-connector-id="${escapeHtml(item.id)}">接口详情</button><button type="button" data-connector-health="${escapeHtml(item.id)}">健康检查</button></div></article>`;
    }).join("")}</div></div>`;
  }

  async function openConnectorDetail(id) {
    try {
      const item = await api(`/api/connectors/${encodeURIComponent(id)}`);
      const mappings = item.field_mappings || [];
      openModal(`${item.code} · ${item.name}`, `${item.mode === "demo" ? "CONTRACT TEST" : item.mode.toUpperCase()} · ${item.health_status} · 映射版本 ${item.mapping_version}`, `<div class="connector-detail"><div class="connector-notice">${icon("alert")}<span>${escapeHtml(item.configuration_notice)}</span></div><div class="source-audit-summary"><span><strong>${item.capabilities.read.length}</strong>读取能力</span><span><strong>${item.capabilities.write.length}</strong>写入能力</span><span><strong>${mappings.length}</strong>字段映射</span></div><div class="settings-grid"><div class="setting-row"><div><strong>接入地址</strong><span>${escapeHtml(item.base_url || "未配置；服务端不会探测外部系统")}</span></div><span class="demo-badge">${escapeHtml(item.auth_type)}</span></div><div class="setting-row"><div><strong>写操作门禁</strong><span>${item.capabilities.read_only ? "此接口按只读方式设计" : "必须 live + 服务端启用写权限 + 当前动作人工确认"}</span></div><span class="${item.write_enabled ? "status-pill" : "demo-badge"}">${item.write_enabled ? "已启用" : "未启用"}</span></div></div><div class="mapping-table"><div class="mapping-row head"><span>标准字段</span><span>站点字段</span><span>方向</span><span>类型</span></div>${mappings.map((map) => `<div class="mapping-row"><span>${escapeHtml(map.canonical_field)}</span><span>${escapeHtml(map.external_field)}</span><span>${escapeHtml(map.direction)}</span><span>${escapeHtml(map.data_type)}</span></div>`).join("")}</div></div>`, `<button type="button" class="drawer-button secondary" data-action="connectors">返回接口中心</button><button type="button" class="drawer-button" data-connector-health="${escapeHtml(item.id)}">执行健康检查</button>`, "connector-detail");
    } catch (error) {
      toast("接口详情读取失败", error.message, "warning");
    }
  }

  async function checkConnectorHealth(id) {
    toast("正在执行健康检查", "只有真实 HTTP 探测成功才会标记为在线。", "info");
    try {
      const result = await api(`/api/connectors/${encodeURIComponent(id)}/health-check`, { method:"POST" });
      toast(result.live_data_verified ? "真实接口已验证在线" : "接口未验证为在线", result.detail, result.live_data_verified ? "success" : "warning", 5600);
      await openConnectors();
    } catch (error) {
      toast("健康检查失败", error.message, "warning");
    }
  }

  function openNotifications() {
    const items = state.dashboard.alerts?.items || [];
    const waitingForPort = state.dashboard.public_open_source_waiting === true;
    const sourceLabel = state.dashboard.data_mode === "live" && !waitingForPort ? "已验证生产实绩" : state.dashboard.source_metadata?.source_type === "public_data_calibrated_simulation" ? "公开数据校准模拟告警" : "现场告警待接入";
    const emptyState = waitingForPort
      ? `<div class="task-empty"><div>${icon("alert")}<strong>现场告警尚未接入</strong><span>待接字段：告警ID、对象、级别、发生时间、来源系统和确认状态；未用零告警冒充安全。</span></div></div>`
      : `<div class="task-empty"><div>${icon("check")}<strong>当前没有活动提醒</strong><span>结论仅适用于已验证连接器返回的当前窗口。</span></div></div>`;
    openModal("预警与提醒", `${items.length} 条活动提醒 · ${sourceLabel}`, `<div class="notification-list">${items.length ? items.map((item) => `<article class="notification-detail"><div class="response-header"><strong>${escapeHtml(item.title)}</strong><span class="alert-level ${escapeHtml(item.level)}">${item.level === "critical" ? "高" : item.level === "warning" ? "中" : "提示"}</span></div><p>${escapeHtml(item.message)}</p><p>来源：${escapeHtml(item.source)} · ${formatDateTime(item.occurred_at)}</p><button type="button" class="outline-button" data-task-template="handle-alert">让小懿生成处置步骤</button></article>`).join("") : emptyState}</div>`, "", "notifications");
  }

  function openSettings() {
    const theme = document.body.dataset.theme;
    openModal("系统设置", "界面偏好会保存在当前浏览器", `<div class="settings-grid"><div class="setting-row"><div><strong>视觉主题</strong><span>深海蓝或更高对比度的极夜模式</span></div><select id="settingsTheme"><option value="deep-sea" ${theme === "deep-sea" ? "selected" : ""}>深海模式</option><option value="midnight" ${theme === "midnight" ? "selected" : ""}>极夜模式</option></select></div><div class="setting-row"><div><strong>默认回答模式</strong><span>提问时仍可在输入框内单独调整</span></div><select id="settingsMode"><option value="expert">专业问答</option><option value="ops">运营问答</option><option value="sop">SOP 生成</option><option value="brief">简报摘要</option></select></div><div class="setting-row"><div><strong>检索证据数</strong><span>范围 1–10 条</span></div><select id="settingsTopK">${[3,5,8,10].map((n) => `<option value="${n}" ${Number($("#topK").value) === n ? "selected" : ""}>${n} 条</option>`).join("")}</select></div><div class="drawer-note"><strong>系统边界：</strong>无现场数据时显示“公开数据校准实时模拟”，每个值保留场景、seed、事件序号、数据哈希和 SIM 真值标签；真实 TOS / EMS / PCS 接入后沿用同一契约，生产写权限仍须独立准入。</div></div>`, `<button type="button" class="drawer-button secondary" data-action="close-modal">取消</button><button type="button" class="drawer-button" data-modal-action="save-settings">保存设置</button>`, "settings");
    const tokenConfigured = Boolean(sessionStorage.getItem("xiaoyi_access_token"));
    $("#modalSubtitle").textContent = "界面偏好保存在浏览器；访问令牌只保存在当前标签会话";
    $("#modalBody .settings-grid").insertAdjacentHTML("beforeend", `<label class="intake-field"><span>生产访问令牌</span><input id="settingsAccessToken" type="password" autocomplete="off" placeholder="${tokenConfigured ? "当前标签已配置；留空保持不变" : "粘贴管理员签发的Bearer JWT"}"></label><label class="strict-evidence-option"><span><strong>清除当前访问令牌</strong><small>令牌不会写入localStorage或服务器</small></span><span class="evidence-switch"><input id="settingsClearToken" type="checkbox"><i></i></span></label>`);
    $("#settingsMode").value = $("#mode").value;
  }

  async function openSystemStatus() {
    openModal("系统状态", "正在分层检查应用、模型、现场数据与生产授权", `<div class="task-empty"><div>${icon("spark")}<strong>正在执行分层就绪检查</strong><span>单一接口成功不会被当成模型、现场或生产就绪</span></div></div>`, "", "status");
    const [readinessResult, knowledgeResult, connectorResult, modelResult, identityResult, infoResult, siteAdmissionResult] = await Promise.allSettled([
      api("/api/system/readiness"), api("/api/knowledge/status"), api("/api/connectors"),
      api("/api/models"), api("/api/governance/identity"), api("/api/system/info"),
      api("/api/system/site-admission")
    ]);
    if (state.modalKind !== "status") return;
    const readiness = readinessResult.status === "fulfilled" ? readinessResult.value : readinessResult.reason?.payload || null;
    const knowledge = knowledgeResult.status === "fulfilled" ? knowledgeResult.value : null;
    const connectors = connectorResult.status === "fulfilled" ? connectorResult.value : null;
    const model = modelResult.status === "fulfilled" ? modelResult.value : null;
    const identity = identityResult.status === "fulfilled" ? identityResult.value : null;
    const info = infoResult.status === "fulfilled" ? infoResult.value : null;
    const siteAdmission = siteAdmissionResult.status === "fulfilled" ? siteAdmissionResult.value : null;
    if (knowledge) { state.knowledgeStatus = knowledge; }
    if (connectors) { state.connectors = connectors; }
    const ready = readiness?.status === "ready";
    const deployment = readiness?.checks?.deployment_configuration;
    const runtimeStore = readiness?.checks?.runtime_store;
    const posture = readiness?.runtime_posture || {};
    const authVerified = Boolean(identity?.authenticated);
    const localModelActive = Boolean(model?.configured && model?.local_generation_enabled && !model?.circuit_open);
    const blockerText = deployment?.blockers?.length ? deployment.blockers.join("；") : "无启动阻断项";
    $("#modalBody").innerHTML = `<div class="settings-grid">
      <div class="setting-row"><div><strong>本机应用运行</strong><span>${readiness ? `${escapeHtml(readiness.app)} · v${escapeHtml(readiness.version)} · ${escapeHtml(readiness.checked_at || "")}` : "深度健康接口不可达"}</span></div><span class="${ready ? "status-pill" : "demo-badge"}">${ready ? "APP READY" : "NOT READY"}</span></div>
      <div class="setting-row"><div><strong>本地生成模型</strong><span>${model ? `${escapeHtml(model.provider)} · ${escapeHtml(model.model)} · ${escapeHtml(model.notice)}` : "模型状态不可读"}</span></div><span class="${localModelActive ? "status-pill" : "demo-badge"}">${model?.circuit_open ? "熔断" : localModelActive ? "LOCAL MODEL" : "规则回退"}</span></div>
      <div class="setting-row"><div><strong>LoRA准入证据</strong><span>${model?.lora_admission ? `${escapeHtml(model.lora_admission.source_run_id || "—")} · ${escapeHtml(model.lora_admission.training_type || "—")} · ${escapeHtml(model.lora_admission.report || "")}` : "LoRA准入报告不可读"}</span></div><span class="demo-badge">${model?.lora_admission?.quality_admission_passed ? "QUALITY ADMITTED" : "ENGINEERING ONLY"}</span></div>
      <div class="setting-row"><div><strong>提示词注入固定回归</strong><span>${model?.prompt_security_benchmark ? `${escapeHtml(model.prompt_security_benchmark.run_id || "—")} · ${model.prompt_security_benchmark.case_count || 0}个中英固定样例 · 外部红队=${String(model.prompt_security_benchmark.external_red_team_completed)}` : "安全回归报告不可读"}</span></div><span class="${model?.prompt_security_benchmark?.passed ? "status-pill" : "demo-badge"}">${model?.prompt_security_benchmark?.passed ? "FIXED PASS" : "CHECK"}</span></div>
      <div class="setting-row"><div><strong>现场数据连接</strong><span>${connectors ? `${connectors.total} 类已装配 · ${connectors.online} 个验证在线 · ${connectors.offline} 个待配置` : "连接器目录不可读"}</span></div><button type="button" class="text-button" data-action="connectors">查看接口</button></div>
      <div class="setting-row"><div><strong>现场准入与漂移门禁</strong><span>${siteAdmission ? `${escapeHtml(siteAdmission.contract_id)} · ${escapeHtml(siteAdmission.current_evidence?.overall_status || "blocked")}` : "准入契约不可读"}</span></div><button type="button" class="text-button" data-action="site-admission">查看7道门禁</button></div>
      <div class="setting-row"><div><strong>生产调度授权</strong><span>recommendation_only=${String(posture.recommendation_only ?? info?.recommendation_only ?? true)} · dispatch_allowed=${String(posture.dispatch_allowed ?? info?.dispatch_allowed ?? false)}</span></div><span class="demo-badge">NOT AUTHORIZED</span></div>
      <div class="setting-row"><div><strong>身份与权限</strong><span>${identity ? `${escapeHtml(identity.actor_id)} · ${escapeHtml(identity.role)} · ${escapeHtml(identity.authentication_status)}` : "身份接口不可读"}</span></div><span class="${authVerified ? "status-pill" : "demo-badge"}">${authVerified ? "已验证" : "本地未验证"}</span></div>
      <div class="setting-row"><div><strong>持久化与恢复</strong><span>${runtimeStore?.ok ? `SQLite 完整性 ${escapeHtml(runtimeStore.integrity)} · 会话保留 ${escapeHtml(info?.chat_retention_days || "--")} 天` : "运行时存储需检查"}</span></div><span class="${runtimeStore?.ok ? "status-pill" : "demo-badge"}">${runtimeStore?.ok ? "可读写" : "异常"}</span></div>
      <div class="setting-row"><div><strong>港航知识索引</strong><span>${knowledge ? `${knowledge.document_count} 份文档 · ${knowledge.chunk_count} 个片段 · ${knowledge.official_verified_documents} 份官方发布来源资料（非全为正文）` : "索引状态不可读"}</span></div><span class="${knowledge?.status === "ready" ? "status-pill" : "demo-badge"}">${knowledge?.status === "ready" ? "可检索" : "需检查"}</span></div>
      <div class="setting-row"><div><strong>运营看板数据</strong><span>${escapeHtml(state.dashboard.data_notice || "数据模式未声明")}</span></div><span class="demo-badge">${escapeHtml(String(state.dashboard.data_mode || "unknown").toUpperCase())}</span></div>
      <div class="setting-row"><div><strong>行业公开能力对照</strong><span>仅比较可引用公开材料；没有共同独立基准时不宣称全面超越</span></div><button type="button" class="text-button" data-action="competitive-benchmark">查看差距</button></div>
      <div class="drawer-note"><strong>边界：</strong>${escapeHtml(blockerText)}。APP READY 只表示本机依赖可用；现场映射、标定、影子运行、双人审批和回滚演练未完成前，production_authority=false。</div>
    </div>`;
  }

  function openProfile() {
    openModal("管理员工作台", "本地验收身份 · 无生产调度授权", `<div class="settings-grid"><div class="setting-row"><div><strong>当前角色</strong><span>港航智能助手本地管理员</span></div><span class="demo-badge">本机会话</span></div><div class="setting-row"><div><strong>生产安全边界</strong><span>推荐模式开启；现场写操作与调度下发默认禁止</span></div><span class="demo-badge">production_authority=false</span></div><div class="setting-row"><div><strong>当前知识索引</strong><span>${state.knowledgeStatus ? `${state.knowledgeStatus.chunk_count} 个可追溯片段，其中 ${state.knowledgeStatus.official_verified_documents} 份官方发布来源资料（非全为正文）` : "尚未读取索引状态"}</span></div><span>${state.knowledgeStatus ? `${state.knowledgeStatus.document_count} 份` : "--"}</span></div></div>`, "", "profile");
  }

  async function openCompetitiveBenchmark() {
    openModal("小懿与行业公开能力对照", "正在读取可复验差距矩阵", `<div class="task-empty"><div>${icon("spark")}<strong>正在核对官方公开材料</strong><span>不会根据未公开信息推断模型质量</span></div></div>`, "", "competitive-benchmark");
    try {
      const payload = await api("/api/system/competitive-benchmark");
      if (state.modalKind !== "competitive-benchmark") return;
      const counts = payload.reference_public_scale || {};
      $("#modalSubtitle").textContent = `${escapeHtml(payload.reference_product)} · 核对日期 ${escapeHtml(payload.accessed_at)} · ${escapeHtml(payload.comparison_status)}`;
      $("#modalBody").innerHTML = `<div class="drawer-note"><strong>当前结论：</strong>${escapeHtml(payload.superiority_claim_gate?.safe_claim || payload.scope_notice)}</div><div class="source-audit-summary"><span><strong>${escapeHtml(counts.registered_users || "—")}</strong>对方公开注册用户</span><span><strong>${escapeHtml(counts.agents || "—")}</strong>对方公开智能体</span><span><strong>${escapeHtml(counts.evaluation_questions || "—")}</strong>对方公开评测题</span></div><div class="source-record-list">${(payload.dimensions || []).map((item) => `<article class="source-record ${item.status.startsWith("xiaoyi_") ? "official" : "unverified"}"><div class="source-record-header"><div class="source-record-title"><strong>${escapeHtml(item.id)}</strong><span>${escapeHtml(item.status)}</span></div><span class="source-status ${item.status.startsWith("xiaoyi_") ? "official" : "unverified"}">${item.status.startsWith("xiaoyi_") ? "可核验优势" : "待追赶"}</span></div><div class="drawer-note"><strong>参考公开能力</strong><br>${escapeHtml(item.reference_public_capability)}</div><div class="drawer-note"><strong>小懿当前证据</strong><br>${escapeHtml(item.xiaoyi_evidence)}</div><div class="drawer-note"><strong>下一验收门禁</strong><br>${escapeHtml(item.next_acceptance_gate)}</div></article>`).join("")}</div><div class="source-hash"><span>矩阵 SHA-256</span><code>${escapeHtml(payload.artifact_sha256)}</code></div>`;
    } catch (error) {
      if (state.modalKind === "competitive-benchmark") $("#modalBody").innerHTML = `<div class="drawer-note"><strong>差距矩阵读取失败：</strong>${escapeHtml(error.message)}</div>`;
    }
  }

  async function openSiteAdmission() {
    openModal("现场数据与生产权限准入", "正在读取字段、质量、漂移、影子与回滚门禁", `<div class="task-empty"><div>${icon("spark")}<strong>正在核对失败关闭契约</strong><span>只读数据通过不等于获得生产调度权限</span></div></div>`, "", "site-admission");
    try {
      const payload = await api("/api/system/site-admission");
      if (state.modalKind !== "site-admission") return;
      const thresholds = payload.read_only_quality_thresholds || {};
      $("#modalSubtitle").textContent = `${payload.contract_id} · ${payload.current_evidence?.overall_status || "blocked"} · production_authority=false`;
      $("#modalBody").innerHTML = `<div class="drawer-note"><strong>当前边界：</strong>${escapeHtml(payload.scope_notice)} 当前模式 ${escapeHtml(payload.runtime?.configured_data_mode || "unknown")}；只读端点不会由状态页自动探测。</div><div class="source-audit-summary"><span><strong>${Number(thresholds.minimum_completeness_rate || 0) * 100}%</strong>最低完整率</span><span><strong>${thresholds.maximum_freshness_seconds || "—"}s</strong>最大新鲜度</span><span><strong>PSI ≤ ${thresholds.maximum_population_stability_index ?? "—"}</strong>漂移阈值</span></div><div class="source-record-list">${(payload.production_admission_gates || []).map((gate, index) => `<article class="source-record unverified"><div class="source-record-header"><div class="source-record-title"><strong>${index + 1}. ${escapeHtml(gate.label)}</strong><span>${escapeHtml(gate.id)}</span></div><span class="source-status unverified">待现场</span></div><div class="drawer-note"><strong>所需证据</strong><br>${escapeHtml((gate.required_evidence || []).join(" · "))}</div></article>`).join("")}</div><div class="drawer-note"><strong>固定关闭项：</strong>recommendation_only=true · dispatch_allowed=false · dual_approval_verified=false · production_authority=false。</div><div class="source-hash"><span>准入契约 SHA-256</span><code>${escapeHtml(payload.artifact_sha256)}</code></div>`;
    } catch (error) {
      if (state.modalKind === "site-admission") $("#modalBody").innerHTML = `<div class="drawer-note"><strong>现场准入契约读取失败：</strong>${escapeHtml(error.message)}</div>`;
    }
  }

  function openAvatarPicker() {
    const selected = localStorage.getItem(STORAGE.avatar) || "navigator";
    const image = "/web/assets/xiaoyi-ai-port-hero.png";
    openModal("切换小懿形象", "形象切换会保留在当前浏览器", `<div class="avatar-options"><button type="button" class="avatar-option ${selected === "navigator" ? "selected" : ""}" data-avatar="navigator"><img src="${image}" alt="领航员小懿"><strong>领航员小懿</strong><span>港口运营、现场处置与智能代办</span></button><button type="button" class="avatar-option ${selected === "analyst" ? "selected" : ""}" data-avatar="analyst"><img src="${image}" alt="分析师小懿"><strong>分析师小懿</strong><span>数据分析、能碳研判与报告生成</span></button></div>`, "", "avatar");
  }

  function selectAvatar(avatar) {
    localStorage.setItem(STORAGE.avatar, avatar);
    document.body.classList.toggle("avatar-analyst", avatar === "analyst");
    closeModal();
    toast("形象已切换", avatar === "analyst" ? "当前为分析师小懿。" : "当前为领航员小懿。", "success");
  }

  async function loadTasksAndTemplates() {
    try {
      const [templates, tasks] = await Promise.all([api("/api/tasks/templates"), api("/api/tasks")]);
      state.templates = templates; state.tasks = tasks;
    } catch {
      state.templates = fallbackTemplates; state.tasks = [];
    }
    renderTemplates(); renderTaskList(); updateCounts();
  }

  function renderTemplates() {
    const list = state.templates.length ? state.templates : fallbackTemplates;
    $("#taskTemplates").innerHTML = list.map((template) => `<button type="button" class="task-template" data-task-template="${escapeHtml(template.id)}"><header><i>${icon(template.id.includes("energy") ? "leaf" : template.id.includes("berth") ? "ship" : template.id.includes("alert") ? "alert" : "report")}</i><strong>${escapeHtml(template.title)}</strong></header><p>${escapeHtml(template.description)}</p><footer><span>${template.estimated_minutes} 分钟</span><span class="risk-${template.risk_level}">${template.risk_level === "high" ? "高风险" : template.risk_level === "medium" ? "需确认" : "低风险"}</span><span>开始 →</span></footer></button>`).join("");
  }

  function renderTaskList() {
    const host = $("#taskList");
    if (!state.tasks.length) {
      host.innerHTML = `<div class="task-empty"><div>${icon("task")}<strong>暂无执行记录</strong><span>选择左侧模板，小懿会逐步展示执行过程</span></div></div>`;
      return;
    }
    host.innerHTML = state.tasks.map((task) => `<article class="task-list-item"><header><strong>${escapeHtml(task.title)}</strong><span>${task.status === "completed" ? "已完成" : "执行中"}</span></header><p>${escapeHtml(task.data_notice || "运营沙箱任务")}</p><div class="task-progress"><b style="width:${Number(task.progress_percent || 0)}%"></b></div><footer><span>${task.progress_percent}% · ${formatDateTime(task.updated_at)}</span><button type="button" data-open-task="${escapeHtml(task.id)}">查看步骤 →</button></footer></article>`).join("");
  }

  async function refreshTasks() {
    try { state.tasks = await api("/api/tasks"); } catch { /* keep local state */ }
    renderTaskList(); updateCounts();
  }

  async function startTask(templateId, options = {}) {
    if (!options.keepModal) closeModal();
    const template = (state.templates.length ? state.templates : fallbackTemplates).find((item) => item.id === templateId);
    if (!template) { toast("未知任务模板", templateId, "warning"); return null; }
    setHeroState("execute", "任务创建");
    try {
      state.activeTask = await api("/api/tasks", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ template_id:templateId, parameters:{ source:"xiaoyi-web", view:state.view } }) });
    } catch (error) {
      state.activeTask = null;
      setHeroState("idle");
      toast("任务创建失败，未执行任何动作", `${error.message}。为避免把接口故障伪装成成功，本次不会自动降级为浏览器假任务。`, "warning", 6200);
      return null;
    }
    state.confirmedTaskIds.delete(state.activeTask.id);
    state.tasks = [state.activeTask, ...state.tasks.filter((task) => task.id !== state.activeTask.id)];
    renderTaskList(); updateCounts();
    if (options.openDrawer !== false) openTaskDrawer(state.activeTask);
    return state.activeTask;
  }

  function openDrawer() {
    $("#drawerBackdrop").hidden = false;
    $("#smartDrawer").classList.add("open");
    $("#smartDrawer").setAttribute("aria-hidden","false");
  }

  function closeDrawer() {
    state.autoRunning = false;
    if (state.drawerMode === "automation") state.automationAbort = true;
    $("#drawerBackdrop").hidden = true;
    $("#smartDrawer").classList.remove("open");
    $("#smartDrawer").classList.remove("rl-mission-drawer");
    $("#smartDrawer").setAttribute("aria-hidden","true");
    $("#agentCursor").classList.remove("visible");
    state.drawerMode = null;
  }

  function revealCompletedAutomationResult(plan) {
    if (!plan || plan.status !== "completed") return;
    const hasUnconfirmedRisk = plan.actions.some((action) =>
      action.requires_confirmation
      && action.status !== "completed"
      && !plan.confirmed_action_ids.includes(action.id)
    );
    if (hasUnconfirmedRisk) return;

    const drawer = $("#smartDrawer");
    if (!drawer || drawer.getAttribute("aria-hidden") === "true") return;
    drawer.classList.remove("automation-result-reveal");
    void drawer.offsetWidth;
    drawer.classList.add("automation-result-reveal");
    setTimeout(() => drawer.classList.remove("automation-result-reveal"), 1900);
  }

  function openTaskDrawer(task) {
    state.activeTask = task;
    state.drawerMode = "task";
    $("#drawerTitle").textContent = task.title;
    $("#drawerSubtitle").textContent = `${task.execution_mode === "operations_sandbox" ? "运营沙箱执行" : "智能执行"} · 全程可追溯`;
    renderActiveTask(); openDrawer();
  }

  function renderActiveTask() {
    const task = state.activeTask;
    if (!task) return;
    $("#drawerContent").innerHTML = `<div class="drawer-note"><strong>安全说明：</strong>${escapeHtml(task.data_notice || "当前为运营沙箱执行，不会下发生产指令。")}${task.requires_human_confirmation ? " 此任务涉及调度或处置建议，最后一步必须由授权人员确认。" : ""}</div><div class="drawer-progress"><b style="width:${Number(task.progress_percent || 0)}%"></b></div><div class="drawer-progress-label"><span>执行进度</span><strong>${task.progress_percent}%</strong></div><div class="task-steps">${task.steps.map((step) => `<div class="task-step ${escapeHtml(step.status)}" data-task-step="${escapeHtml(step.id)}"><i class="task-step-icon">${step.status === "completed" ? icon("check") : step.order}</i><div class="task-step-copy"><strong>${escapeHtml(step.title)}</strong><span>${escapeHtml(step.description || "等待小懿执行")}</span>${step.result ? `<em>${escapeHtml(step.result)}</em>` : ""}</div></div>`).join("")}</div>`;
    const footer = $("#drawerFooter");
    if (task.status === "completed") {
      footer.innerHTML = `<button type="button" class="drawer-button secondary" data-action="close-drawer">关闭</button><button type="button" class="drawer-button" data-action="generate-report">${icon("report")}生成报告</button>`;
      setHeroState("complete");
    } else {
      const currentIndex = task.steps.findIndex((step) => step.status === "running");
      const needsConfirm = task.requires_human_confirmation && currentIndex === task.steps.length - 1 && !state.confirmedTaskIds.has(task.id);
      footer.innerHTML = `<button type="button" class="drawer-button secondary" data-action="close-drawer">暂停</button><button type="button" class="drawer-button" data-task-action="auto">${icon("play")}自动执行</button><button type="button" class="drawer-button ${needsConfirm ? "warning" : ""}" data-task-action="next">${needsConfirm ? "人工确认后继续" : "执行下一步"}</button>`;
      setHeroState(needsConfirm ? "confirm" : "execute", `${Math.max(1, currentIndex + 1)}/${task.steps.length} 步`);
    }
  }

  async function advanceTask() {
    const task = state.activeTask;
    if (!task || task.status !== "running") return false;
    const currentIndex = task.steps.findIndex((step) => step.status === "running");
    if (task.requires_human_confirmation && currentIndex === task.steps.length - 1 && !state.confirmedTaskIds.has(task.id)) {
      setHeroState("confirm");
      openModal("需要人工确认", "高风险生产动作不会由小懿自动下发", `<div class="drawer-note"><strong>即将完成：</strong>${escapeHtml(task.steps.find((step) => step.status === "running")?.title || "最终确认步骤")}。当前为运营沙箱；确认只会推进沙箱任务并记录审计轨迹，不会连接或控制真实设备。</div>`, `<button type="button" class="drawer-button secondary" data-action="close-modal">取消</button><button type="button" class="drawer-button warning" data-modal-action="confirm-task">确认沙箱执行</button>`, "task-confirm");
      return false;
    }
    const running = task.steps.find((step) => step.status === "running");
    if (running) await guidedFocus(`[data-task-step="${CSS.escape(running.id)}"]`, `执行第 ${running.order} 步`, false, 420);
    try {
      const response = await api(`/api/tasks/${encodeURIComponent(task.id)}/next`, { method:"POST" });
      state.activeTask = response.task;
      toast(response.visual_cue === "task-complete" ? "智能任务已完成" : "步骤执行完成", response.assistant_message, "success");
    } catch (error) {
      toast("步骤执行失败，自动执行已停止", error.message, "warning"); return false;
    }
    state.tasks = [state.activeTask, ...state.tasks.filter((item) => item.id !== state.activeTask.id)];
    renderActiveTask(); renderTaskList(); updateCounts();
    return true;
  }

  async function autoRunTask() {
    if (state.autoRunning || !state.activeTask) return;
    state.autoRunning = true;
    while (state.autoRunning && state.activeTask?.status === "running") {
      const activeIndex = state.activeTask.steps.findIndex((step) => step.status === "running");
      if (state.activeTask.requires_human_confirmation && activeIndex === state.activeTask.steps.length - 1 && !state.confirmedTaskIds.has(state.activeTask.id)) {
        state.autoRunning = false; setHeroState("confirm"); toast("自动执行已暂停", "最后一步需要授权人员确认。", "warning", 5000); renderActiveTask(); break;
      }
      const advanced = await advanceTask();
      if (!advanced) break;
      await sleep(650);
    }
    state.autoRunning = false;
    $("#agentCursor").classList.remove("visible");
  }

  async function openExistingTask(id) {
    let task = state.tasks.find((item) => item.id === id);
    if (!task) {
      try { task = await api(`/api/tasks/${encodeURIComponent(id)}`); } catch (error) { toast("任务不存在", error.message, "warning"); }
    }
    if (task) openTaskDrawer(task);
  }

  async function generateReport(type = "energy", options = {}) {
    if (!options.background) {
      closeDrawer();
      openModal("正在生成专业报告", "小懿正在汇总运营指标、异常与建议", `<div class="task-empty"><div>${icon("report")}<strong>正在生成结构化报告</strong><span>结论、指标、发现与建议会一并保留</span></div></div>`, "", "report-loading");
    }
    try {
      const reportType = type || (state.currentIntent?.includes("energy") ? "energy" : "management_brief");
      const energyRange = ["today","7d","30d"].includes(options.range) ? options.range : state.energy?.range || "today";
      const report = await api("/api/reports", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ report_type:reportType, include_recommendations:true, energy_range:energyRange }) });
      state.activeReport = report;
      if (options.background) {
        toast("报告已生成", `${report.title} 已进入导出队列。`, "success");
        return report;
      }
      if (state.modalKind !== "report-loading") return;
      state.modalKind = "report";
      $("#modalTitle").textContent = report.title;
      $("#modalSubtitle").textContent = `${formatDateTime(report.generated_at)} · ${report.data_mode === "live" ? "生产实绩" : "运营沙箱"} · ${report.id}`;
      $("#modalBody").innerHTML = `<div class="report-preview">${escapeHtml(report.content_markdown)}</div>`;
      $("#modalFooter").innerHTML = `<button type="button" class="drawer-button secondary" data-report-download="json">${icon("download")}导出 JSON</button><button type="button" class="drawer-button" data-report-download="markdown">${icon("download")}下载 Markdown</button>`;
      toast("报告已生成", "可下载 Markdown 或 JSON 文件。", "success");
    } catch (error) {
      if (options.background) throw error;
      $("#modalBody").innerHTML = `<div class="drawer-note"><strong>生成失败：</strong>${escapeHtml(error.message)}</div>`;
      $("#modalFooter").innerHTML = `<button type="button" class="drawer-button secondary" data-action="close-modal">关闭</button>`;
      return null;
    }
  }

  function downloadReport(format) {
    const report = state.activeReport;
    if (!report) return;
    const content = format === "json" ? JSON.stringify(report,null,2) : report.content_markdown;
    const blob = new Blob([content], { type:format === "json" ? "application/json;charset=utf-8" : "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `${report.title.replace(/[\\/:*?"<>|]/g,"-")}.${format === "json" ? "json" : "md"}`;
    document.body.append(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(url);
    toast("报告已导出", anchor.download, "success");
  }

  function handleAttachment(file) {
    if (!file) return;
    const supported = /\.(txt|md|csv)$/i.test(file.name);
    if (!supported) {
      toast("当前支持 TXT / Markdown / CSV", "PDF、Word 与 Excel 解析接口尚未接入，未上传此文件。", "warning", 5200);
      return;
    }
    if (file.size > 2 * 1024 * 1024) { toast("文件过大", "待审核资料上限为 2 MB。", "warning"); return; }
    const reader = new FileReader();
    reader.onload = () => {
      const content = String(reader.result || "");
      if (!content.trim()) { toast("资料内容为空", "请选择包含有效文本的资料。", "warning"); return; }
      if (content.length > 1000000) { toast("资料字符数超限", "待审核资料最多 1,000,000 个字符。", "warning"); return; }
      state.pendingAttachment = { filename:file.name, content };
      openModal("提交资料到待审核区", "附件不会直接进入问答，也不会自动被认定为官方资料", `<div class="settings-grid"><div class="setting-row"><div><strong>资料文件</strong><span>${escapeHtml(file.name)} · ${Number(file.size).toLocaleString()} B</span></div><span class="demo-badge">PENDING</span></div><label class="intake-field"><span>发布或提供机构</span><input id="intakeInstitution" maxlength="200" placeholder="例如：某港口集团 / 交通运输部"></label><label class="intake-field"><span>原始来源 URL</span><input id="intakeSourceUrl" type="url" placeholder="https://..."></label><label class="intake-field"><span>版本 / 生效日期</span><input id="intakeVersion" maxlength="100" placeholder="例如：2026-01 / V2.1"></label><label class="strict-evidence-option"><span><strong>提交者声明为官方来源</strong><small>这只是声明，不代表系统已经核验</small></span><span class="evidence-switch"><input id="intakeOfficialClaim" type="checkbox"><i></i></span></label><div class="drawer-note"><strong>审核流程：</strong>暂存隔离 → 核验发布机构与授权 → 版本/有效期复核 → 分段与哈希 → 来源登记 → 人工批准 → 重建索引。当前提交只完成第一步。</div></div>`, `<button type="button" class="drawer-button secondary" data-action="close-modal">取消</button><button type="button" class="drawer-button" data-modal-action="submit-knowledge-intake">提交待审核</button>`, "knowledge-intake-submit");
    };
    reader.onerror = () => toast("文件读取失败", "请重试或换用 UTF-8 文本。", "warning");
    reader.readAsText(file, "utf-8");
  }

  async function submitKnowledgeIntake() {
    const attachment = state.pendingAttachment;
    if (!attachment) return;
    const sourceUrl = String($("#intakeSourceUrl")?.value || "").trim();
    const payload = {
      filename:attachment.filename,
      content:attachment.content,
      source_url:sourceUrl || null,
      institution:String($("#intakeInstitution")?.value || "").trim() || null,
      version:String($("#intakeVersion")?.value || "").trim() || null,
      official_claim:Boolean($("#intakeOfficialClaim")?.checked)
    };
    try {
      const item = await api("/api/knowledge/intake", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload) });
      state.pendingAttachment = null;
      $("#modalTitle").textContent = "资料已进入待审核隔离区";
      $("#modalSubtitle").textContent = `${item.id} · indexed=false`;
      $("#modalBody").innerHTML = `<div class="source-record unverified"><div class="source-record-header"><div class="source-record-title"><strong>${escapeHtml(item.original_filename)}</strong><span>${escapeHtml(item.status)}</span></div><span class="source-status unverified">未进入索引</span></div><div class="source-provenance"><span>官方性核验<b>${item.official_claim_verified ? "已核验" : "未核验"}</b></span><span>可进入索引<b>${item.eligible_for_index ? "是" : "否"}</b></span><span>存储区域<b>${escapeHtml(item.storage_area)}</b></span></div><div class="source-hash"><span>SHA-256</span><code>${escapeHtml(item.sha256)}</code></div></div><div class="drawer-note"><strong>后续要求：</strong>${escapeHtml(item.review_notice)}</div>`;
      $("#modalFooter").innerHTML = `<button type="button" class="drawer-button secondary" data-action="close-modal">关闭</button><button type="button" class="drawer-button" data-action="knowledge-intake">查看待审核列表</button>`;
      toast("资料已安全暂存", "没有加入正式索引，也不会影响当前专业回答。", "success", 5200);
    } catch (error) {
      toast("资料暂存失败", error.message, "warning", 5200);
    }
  }

  function showKnowledgeMap() {
    const status = state.knowledgeStatus;
    openModal("港航知识全景", status ? `${status.document_count} 份已登记资料 · ${status.chunk_count} 个索引片段 · ${status.official_verified_documents} 份官方发布来源资料（非全为正文）` : "知识索引状态暂不可读", `<div style="display:grid;place-items:center;min-height:440px;background:rgba(3,24,43,.55);border-radius:9px"><img src="/web/xiaoyi-port-diagram.svg" alt="港航知识全景" style="max-width:100%;max-height:520px"></div>`, `<button type="button" class="drawer-button" data-action="knowledge-sources">查看来源审计</button>`, "knowledge-map");
  }

  function autoGrowQuestion() {
    const input = $("#question");
    input.style.height = "auto";
    input.style.height = `${Math.min(90, Math.max(24, input.scrollHeight))}px`;
  }

  function rippleAt(x, y) {
    const ripple = document.createElement("i");
    ripple.className = "click-ripple";
    ripple.style.left = `${x-6}px`; ripple.style.top = `${y-6}px`;
    document.body.append(ripple); setTimeout(() => ripple.remove(), 700);
  }

  async function guidedFocus(selector, label, click = true, hold = 700) {
    const target = $(selector);
    if (!target) return false;
    target.scrollIntoView({ block:"center", inline:"center", behavior:"smooth" });
    await sleep(220);
    const rect = target.getBoundingClientRect();
    const cursor = $("#agentCursor");
    $("span", cursor).textContent = label;
    cursor.classList.add("visible");
    cursor.style.transform = `translate(${rect.left + rect.width/2 - 18}px,${rect.top + rect.height/2 - 18}px)`;
    target.classList.add("ai-focus");
    await sleep(hold);
    rippleAt(rect.left + rect.width/2, rect.top + rect.height/2);
    if (click) target.click();
    await sleep(300);
    target.classList.remove("ai-focus");
    if (!state.tourRunning && !state.autoRunning) {
      setTimeout(() => $("#agentCursor").classList.remove("visible"), 260);
    }
    return true;
  }

  function openAutomationPlan(plan) {
    if (state.automationPlan?.id !== plan.id) state.automationContext = {};
    state.automationPlan = plan;
    state.drawerMode = "automation";
    $("#drawerTitle").textContent = "小懿智能操作";
    $("#drawerSubtitle").textContent = `${plan.actions.length} 个白名单步骤 · ${Math.round(Number(plan.confidence || 0) * 100)}% 意图置信度`;
    $("#smartDrawer").classList.toggle("rl-mission-drawer", ["optimize_agv_energy_rl","weather_berth_joint_rl","qc_agv_yard_marl"].includes(plan.intent));
    renderAutomationPlan();
    openDrawer();
  }

  function rlMissionSparkline(series = []) {
    const values = series.map((item) => Number(item.reward_ema ?? item.reward ?? 0)).filter(Number.isFinite);
    if (values.length < 2) return `<div class="rl-empty-chart">等待训练记录 / Awaiting training record</div>`;
    const width = 520, height = 116, pad = 8;
    const min = Math.min(...values), max = Math.max(...values), span = Math.max(1, max - min);
    const points = values.map((value, index) => {
      const x = pad + index / Math.max(1, values.length - 1) * (width - pad * 2);
      const y = height - pad - (value - min) / span * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return `<svg class="rl-training-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="RL Reward convergence"><defs><linearGradient id="rlRewardFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#35efc0" stop-opacity=".42"/><stop offset="1" stop-color="#35efc0" stop-opacity="0"/></linearGradient></defs><polygon points="${pad},${height-pad} ${points} ${width-pad},${height-pad}" fill="url(#rlRewardFill)"/><polyline points="${points}" fill="none" stroke="#54f1c6" stroke-width="2.4"/><circle cx="${points.split(" ").at(-1).split(",")[0]}" cy="${points.split(" ").at(-1).split(",")[1]}" r="4" fill="#d8fff3"/></svg>`;
  }

  function renderRLMissionHUD(plan) {
    if (plan.intent !== "optimize_agv_energy_rl") return "";
    const mission = state.automationContext.rlMission || {};
    const systems = mission.health?.systems || {};
    const nodes = [
      ["xiaoyi", "小懿AI", "ORCHESTRATOR"], ["dataset", "真实公开数据", "MEASURED DATA"],
      ["trainer", "本地RL训练器", "4 RL + PID + SOP"], ["guardrail", "测试隔离门禁", "NO TRAIN RENDER"]
    ];
    const topology = nodes.map(([id,label,en]) => {
      const item = systems[id];
      const stateClass = item?.online ? "online" : item ? "offline" : "pending";
      return `<div class="rl-system-node ${stateClass}" data-rl-node="${id}"><i></i><strong>${label}</strong><span>${en}</span><em>${item ? (item.online ? escapeHtml(String(item.mode || "READY")).toUpperCase() : "OFFLINE") : "WAITING"}</em></div>`;
    }).join("");
    const scenario = mission.scenario || {};
    const dataset = scenario.dataset || mission.training?.dataset || {};
    const config = scenario.config || {};
    const training = mission.training || {};
    const curveTail = training.training?.curve_tail || [];
    const curveAlgorithm = training.current_algorithm_id || curveTail.at(-1)?.algorithm_id;
    const curve = curveTail.filter((item) => !curveAlgorithm || item.algorithm_id === curveAlgorithm);
    const race = mission.simulation?.race || [];
    const raceCards = race.length ? race.map((item) => {
      const winner = item.id === mission.simulation?.best_algorithm_id;
      const safe = Number(item.constraint_violations || 0) === 0;
      return `<div class="rl-race-card ${winner ? "win" : safe ? "" : "watch"}"><span>${escapeHtml(item.label)}</span><strong>${formatNumber(item.score)} <small>SCORE</small></strong><em>成本 ${Number(item.cost_saving_percent) >= 0 ? "+" : ""}${formatNumber(item.cost_saving_percent)}% · 峰值 ${Number(item.peak_reduction_percent) >= 0 ? "+" : ""}${formatNumber(item.peak_reduction_percent)}% · 约束 ${formatNumber(item.constraint_violations)}</em></div>`;
    }).join("") : `<div class="rl-stage-placeholder">训练完成后才会读取测试集并渲染 / Test holdout remains sealed</div>`;
    const verification = mission.verification || {};
    const checks = verification.checks || [];
    const checkHtml = checks.length ? checks.map((item) => `<span class="${item.passed ? "passed" : "blocked"}">${icon(item.passed ? "check" : "alert")}${escapeHtml(item.name)}</span>`).join("") : `<span class="pending">等待守护栏验证</span>`;
    const dispatch = mission.dispatch || {};
    return `<section class="rl-mission-hud" data-agent-target="rl-mission-core">
      <header class="rl-mission-header"><div><span>REPRODUCIBLE RL LAB</span><strong>真实数据驱动的能源调度训练</strong><small>4 RL Algorithms · PID Baseline · Chronological Holdout · No Train Rendering</small></div><b>${dispatch.status === "dry_run_recorded" ? "ARCHIVED" : verification.ok ? "VERIFIED" : mission.simulation ? "TESTED" : training.status === "trained" ? "TRAINED" : training.status === "training" ? "TRAINING" : "READY"}</b></header>
      <div class="rl-topology" data-agent-target="rl-mission-topology"><div class="rl-link-beam"></div>${topology}</div>
      <div class="rl-mission-grid">
        <article class="rl-panel" data-agent-target="rl-mission-scenario"><header><span>01 · MEASURED DATA</span><b>${dataset.available ? "HASHED" : "WAITING"}</b></header><div class="rl-fleet-orbit"><i></i><strong>${dataset.row_count ?? "—"}<small> ROWS</small></strong><span>${dataset.port_data ? "PORT DATA" : "PUBLIC BENCHMARK"}</span></div><div class="rl-mini-stats"><span>步长<b>${dataset.step_minutes ?? "—"}m</b></span><span>训练<b>${config.episodes ?? training.config?.episodes ?? "—"}</b></span><span>种子<b>${config.seed ?? training.config?.seed ?? "—"}</b></span></div><p>${escapeHtml(dataset.label || "等待数据校验")} · SHA-256 ${escapeHtml(String(dataset.sha256 || "—").slice(0,12))}</p></article>
        <article class="rl-panel rl-training-panel" data-agent-target="rl-mission-training"><header><span>02 · REAL TRAINING · NO RENDER</span><b>${training.status ? escapeHtml(String(training.status).toUpperCase()) : "WAITING"}</b></header>${rlMissionSparkline(curve)}<div class="rl-training-progress"><i><b style="width:${Math.max(0,Math.min(100,Number(training.progress_percent || 0)))}%"></b></i><span>${formatNumber(training.progress_percent || 0)}%</span></div><div class="rl-mini-stats"><span>当前算法<b>${escapeHtml(training.current_algorithm_id || "—")}</b></span><span>已跑回合<b>${training.completed_training_episodes ?? 0}</b></span><span>总回合<b>${training.total_training_episodes ?? ((config.episodes || 0) * 4)}</b></span></div><p>训练阶段 render_mode=None；进度来自后台已完成 episode 计数。</p></article>
      </div>
      <article class="rl-panel rl-race-panel" data-agent-target="rl-mission-race"><header><span>03 · HOLDOUT TEST RENDER</span><b>${race.length ? `WINNER ${escapeHtml(mission.simulation.best_algorithm_id || "—")}` : "SEALED"}</b></header><div class="rl-race-grid">${raceCards}</div></article>
      <article class="rl-panel rl-guardrail-panel" data-agent-target="rl-mission-guardrail"><header><span>04 · REPRODUCIBILITY GUARDRAIL</span><b class="${verification.ok ? "passed" : ""}">${verification.ok ? `${verification.passed}/${verification.total} PASSED` : "WAITING"}</b></header><div class="rl-checks">${checkHtml}</div></article>
      <article class="rl-dispatch-strip ${dispatch.status === "dry_run_recorded" ? "completed" : ""}" data-agent-target="rl-mission-confirmation"><i>${icon(dispatch.status === "dry_run_recorded" ? "check" : "alert")}</i><div><strong>${dispatch.status === "dry_run_recorded" ? "本地测试Dry-run已归档" : verification.ok ? "证据验证通过，等待人工确认归档" : "生产写入保持锁定"}</strong><span>${dispatch.audit_notice || "确认只归档当前测试证据；不会下发生产控制指令。"}</span></div><b>${dispatch.status === "dry_run_recorded" ? "NO PROD WRITE" : "HUMAN GATE"}</b></article>
    </section>`;
  }

  function renderWeatherMissionHUD(plan) {
    const mission = state.automationContext.advancedRL || {};
    const systems = mission.health?.systems || {};
    const topology = [["xiaoyi","小懿AI","ORCHESTRATOR"],["malacca","马六甲推演","MAPPO POLICY"],["twin","数字孪生","TWIN REPLAY"],["guardrail","安全门禁","DRY-RUN"]].map(([id,label,en]) => {
      const node = systems[id];
      return `<div class="rl-system-node ${node?.online ? "online" : node ? "offline" : "pending"}"><i></i><strong>${label}</strong><span>${en}</span><em>${node ? (node.online ? "LIVE API" : "OFFLINE") : "WAITING"}</em></div>`;
    }).join("");
    const scenario = mission.scenario || {}, weather = scenario.weather || {}, traffic = scenario.traffic || {};
    const inference = mission.inference || {}, selected = inference.selected_action || {}, comparison = inference.comparison || {};
    const actions = (inference.action_distribution || []).slice(0,5);
    const actionBars = actions.length ? actions.map((item,index) => `<div class="weather-action-row ${index === 0 ? "selected" : ""}"><span>${escapeHtml(item.label)}</span><i><b style="width:${Math.max(2,Number(item.probability || 0))}%"></b></i><strong>${formatNumber(item.probability)}%</strong></div>`).join("") : `<div class="rl-stage-placeholder">等待MAPPO策略推理</div>`;
    const benchmark = mission.benchmark || {}, algorithms = benchmark.results || [];
    const algoCards = algorithms.length ? algorithms.map((item) => `<div class="weather-algo ${item.id === benchmark.best_algorithm_id ? "winner" : ""}"><span>${escapeHtml(item.label)}</span><strong>${formatNumber(item.evaluation?.meanReward)}</strong><em>延误 -${formatNumber(item.evaluation?.delayReductionPercent)}%</em></div>`).join("") : `<div class="rl-stage-placeholder">等待五算法同种子基准</div>`;
    const replay = mission.replay || {}, verification = mission.verification || {}, dispatch = mission.dispatch || {};
    const checks = verification.checks || [];
    const checkHtml = checks.length ? checks.map((item) => `<span class="${item.passed ? "passed" : "blocked"}">${icon(item.passed ? "check" : "alert")}${escapeHtml(item.name)}</span>`).join("") : `<span class="pending">等待极端天气安全验证</span>`;
    const status = dispatch.status === "dry_run_completed" ? "COMPLETED" : verification.ok ? "VERIFIED" : benchmark.online ? "BENCHMARKED" : inference.online ? "INFERENCE" : "ORCHESTRATING";
    return `<section class="rl-mission-hud weather-mission-hud" data-agent-target="weather-mission-core">
      <header class="rl-mission-header weather-header"><div><span>EXTREME WEATHER · RL MISSION</span><strong>极端天气下船舶—泊位联合调度</strong><small>Malacca MAPPO · Five-Algorithm Benchmark · Twin Replay</small></div><b>${status}</b></header>
      <div class="rl-topology" data-agent-target="weather-mission-topology"><div class="rl-link-beam"></div>${topology}</div>
      <div class="weather-stage-grid">
        <article class="rl-panel" data-agent-target="weather-mission-storm"><header><span>01 · STORM INJECTION</span><b>${scenario.scenario ? "ORANGE" : "WAITING"}</b></header><div class="weather-radar"><i></i><i></i><i></i><b></b><span>${weather.wind_speed_ms ?? "—"}<small>m/s</small></span></div><div class="rl-mini-stats"><span>浪高<b>${weather.wave_height_m ?? "—"}m</b></span><span>能见度<b>${weather.visibility_km ?? "—"}km</b></span><span>待靠船<b>${traffic.waiting_vessels ?? "—"}</b></span></div></article>
        <article class="rl-panel" data-agent-target="weather-mission-policy"><header><span>02 · MAPPO POLICY</span><b>${inference.online ? escapeHtml(inference.model?.algorithm || "MAPPO") : "WAITING"}</b></header><div class="weather-selected-action"><span>SELECTED ACTION</span><strong>${escapeHtml(selected.label || "等待策略推理")}</strong><em>${selected.probability ? `${formatNumber(selected.probability)}% · ETA SHIFT ${selected.arrivalShiftMinutes || 0} MIN` : "Malacca policy inference"}</em></div>${actionBars}</article>
      </div>
      <article class="rl-panel" data-agent-target="weather-mission-race"><header><span>03 · FAIR BENCHMARK · 300 EPISODES</span><b>${benchmark.best_algorithm_id ? `WINNER ${escapeHtml(benchmark.best_algorithm_id)}` : "WAITING"}</b></header><div class="weather-algo-grid">${algoCards}</div></article>
      <article class="rl-panel" data-agent-target="weather-mission-replay"><header><span>04 · DIGITAL TWIN REPLAY</span><b>${replay.status ? `${replay.systems_completed}/${replay.systems_total} LINKED` : "WAITING"}</b></header><div class="weather-route"><i></i><span class="ship-a">▰</span><span class="ship-b">▰</span><em>B03</em><em>B05</em><em>B07</em><b></b></div><div class="weather-impact"><span>拥堵改善<b>${formatNumber(comparison.improvement?.congestionPoints ?? "—")} pt</b></span><span>延误改善<b>${formatNumber(comparison.improvement?.delayMinutes ?? "—")} min</b></span><span>韧性提升<b>${formatNumber(comparison.improvement?.resiliencePoints ?? "—")} pt</b></span></div></article>
      <article class="rl-panel rl-guardrail-panel" data-agent-target="weather-mission-guardrail"><header><span>05 · WEATHER SAFETY SHIELD</span><b class="${verification.ok ? "passed" : ""}">${verification.ok ? `${verification.passed}/${verification.total} PASSED` : "WAITING"}</b></header><div class="rl-checks">${checkHtml}</div></article>
      <article class="rl-dispatch-strip ${dispatch.status === "dry_run_completed" ? "completed" : ""}" data-agent-target="weather-mission-confirmation"><i>${icon(dispatch.status === "dry_run_completed" ? "check" : "alert")}</i><div><strong>${dispatch.status === "dry_run_completed" ? "极端天气联合调度Dry-run已归档" : verification.ok ? "策略已通过门禁，等待操作员确认" : "真实泊位计划保持锁定"}</strong><span>${dispatch.audit_notice || "确认只写入数字孪生回放记录，不修改生产TOS。"}</span></div><b>${dispatch.status === "dry_run_completed" ? "NO PROD WRITE" : "HUMAN GATE"}</b></article>
    </section>`;
  }

  function renderMarlMissionHUD(plan) {
    const mission = state.automationContext.advancedRL || {};
    const systems = mission.health?.systems || {};
    const topology = [["xiaoyi","小懿AI","ORCHESTRATOR"],["mas","MAS编排","JOINT POLICY"],["portviz","港区动态流","STATE STREAM"],["guardrail","安全门禁","ACTION SHIELD"]].map(([id,label,en]) => {
      const node = systems[id];
      return `<div class="rl-system-node ${node?.online ? "online" : node ? "offline" : "pending"}"><i></i><strong>${label}</strong><span>${en}</span><em>${node ? (node.online ? "LIVE API" : "OFFLINE") : "WAITING"}</em></div>`;
    }).join("");
    const scenario = mission.scenario || {}, agents = scenario.agents || {}, cmdp = scenario.cmdp || {};
    const coordination = mission.coordination || {}, agentActions = coordination.agent_actions || [];
    const agentNodes = [["qc","岸桥智能体","QC AGENT"],["agv","AGV智能体","AGV AGENT"],["yard","堆场智能体","YARD AGENT"]].map(([id,label,en],index) => { const item = agents[id] || {}, action = agentActions[index] || {}; return `<article class="marl-agent-node ${id}"><i>${icon(id === "qc" ? "ship" : id === "agv" ? "agv" : "task")}</i><span>${en}</span><strong>${label}</strong><b>${item.active ?? "—"}/${item.count ?? "—"} ACTIVE</b><em>${escapeHtml(action.action || "等待联合动作")}</em></article>`; }).join("");
    const rewardLabels = {throughput:"吞吐奖励",cycle_continuity:"节拍连续",energy:"能效奖励",queue_penalty:"排队惩罚",rehandle_penalty:"翻箱惩罚",safety_penalty:"安全惩罚"};
    const rewardRows = Object.entries(coordination.reward || {}).length ? Object.entries(coordination.reward).map(([key,value]) => `<div class="marl-reward-row ${Number(value) < 0 ? "penalty" : "gain"}"><span>${rewardLabels[key] || key}</span><i><b style="width:${Math.min(100,Math.abs(Number(value))*6)}%"></b></i><strong>${Number(value) >= 0 ? "+" : ""}${formatNumber(value)}</strong></div>`).join("") : `<div class="rl-stage-placeholder">等待Reward分解</div>`;
    const policies = coordination.policies || [];
    const policyCards = policies.length ? policies.map((item) => `<div class="marl-policy-card ${item.id === coordination.policy?.id ? "winner" : ""}"><span>${escapeHtml(item.label)}</span><strong>${formatNumber(item.joint_reward)}</strong><em>Cycle ${formatNumber(item.cycle_time_index)} · Safety ${item.safety_violations}</em></div>`).join("") : `<div class="rl-stage-placeholder">等待联合策略赛马</div>`;
    const verification = mission.verification || {}, dispatch = mission.dispatch || {}, checks = verification.checks || [];
    const checkHtml = checks.length ? checks.map((item) => `<span class="${item.passed ? "passed" : "blocked"}">${icon(item.passed ? "check" : "alert")}${escapeHtml(item.name)}</span>`).join("") : `<span class="pending">等待联合动作安全投影</span>`;
    const status = dispatch.status === "dry_run_completed" ? "COMPLETED" : verification.ok ? "VERIFIED" : coordination.policy ? "COORDINATING" : scenario.scenario ? "CMDP READY" : "ORCHESTRATING";
    return `<section class="rl-mission-hud marl-mission-hud" data-agent-target="marl-mission-core">
      <header class="rl-mission-header marl-header"><div><span>CONSTRAINED MARL · CTDE MISSION</span><strong>岸桥—AGV—堆场多智能体协同</strong><small>Constrained MDP · Reward Decomposition · Safety Projection</small></div><b>${status}</b></header>
      <div class="rl-topology" data-agent-target="marl-mission-topology"><div class="rl-link-beam"></div>${topology}</div>
      <article class="rl-panel" data-agent-target="marl-mission-cmdp"><header><span>01 · CONSTRAINED MDP</span><b>${cmdp.algorithm ? "CTDE READY" : "WAITING"}</b></header><div class="marl-cmdp-grid"><span>STATE<b>${cmdp.state_dim ?? "—"}D</b></span><span>JOINT ACTION<b>${cmdp.joint_action_dim ?? "—"}D</b></span><span>ACTORS<b>SHARED × 3</b></span><span>CRITIC<b>CENTRALIZED</b></span><span>HORIZON<b>${scenario.scenario?.horizon_min ?? 120} MIN</b></span></div></article>
      <div class="marl-agent-network" data-agent-target="marl-mission-agents"><div class="marl-message-beam beam-one"></div><div class="marl-message-beam beam-two"></div><div class="marl-critic-core"><span>CENTRALIZED</span><strong>CRITIC</strong><b>${coordination.joint_reward ?? "—"}</b></div>${agentNodes}</div>
      <div class="marl-analysis-grid" data-agent-target="marl-mission-reward"><article class="rl-panel"><header><span>02 · REWARD DECOMPOSITION</span><b>${coordination.joint_reward != null ? `Σ ${formatNumber(coordination.joint_reward)}` : "WAITING"}</b></header>${rewardRows}</article><article class="rl-panel"><header><span>03 · POLICY RACE</span><b>${coordination.policy ? "MAPPO SELECTED" : "WAITING"}</b></header><div class="marl-policy-grid">${policyCards}</div></article></div>
      <article class="rl-panel rl-guardrail-panel" data-agent-target="marl-mission-guardrail"><header><span>04 · JOINT ACTION SAFETY PROJECTION</span><b class="${verification.ok ? "passed" : ""}">${verification.ok ? `${verification.passed}/${verification.total} PASSED` : "WAITING"}</b></header><div class="rl-checks marl-checks">${checkHtml}</div></article>
      <article class="rl-dispatch-strip ${dispatch.status === "dry_run_completed" ? "completed" : ""}" data-agent-target="marl-mission-confirmation"><i>${icon(dispatch.status === "dry_run_completed" ? "check" : "alert")}</i><div><strong>${dispatch.status === "dry_run_completed" ? "多智能体联合动作Dry-run已归档" : verification.ok ? "安全投影通过，等待操作员确认" : "设备控制写入保持锁定"}</strong><span>${dispatch.audit_notice || "联合动作仅进入MAS仿真与数字孪生回放。"}</span></div><b>${dispatch.status === "dry_run_completed" ? "NO PROD WRITE" : "HUMAN GATE"}</b></article>
    </section>`;
  }

  function renderAutomationPlan() {
    const plan = state.automationPlan;
    if (!plan) return;
    const completed = plan.actions.filter((action) => action.status === "completed").length;
    const progress = plan.actions.length ? Math.round(completed / plan.actions.length * 100) : 0;
    const phases = ["理解","准备","检索","分析","执行","核验","交付"];
    const phaseState = phases.map((phase) => {
      const items = plan.actions.filter((action) => action.phase === phase);
      if (!items.length) return "";
      const done = items.every((action) => action.status === "completed");
      const active = items.some((action) => action.status === "running");
      return `<span class="${done ? "done" : active ? "active" : ""}">${done ? icon("check") : ""}${phase}</span>`;
    }).join("");
    const activeAction = plan.actions.find((action) => action.status === "running") || plan.actions.find((action) => action.status === "pending");
    $("#drawerContent").innerHTML = `${renderRLMissionHUD(plan)}<div class="automation-plan"><div class="automation-plan-header"><header><strong>“${escapeHtml(plan.command)}”</strong><span class="automation-plan-status">${escapeHtml(plan.status)}</span></header><p class="automation-plan-summary">${escapeHtml(plan.summary)}<br>${escapeHtml(plan.data_notice)}</p></div><div class="automation-phase-rail">${phaseState}</div><div class="automation-now"><span>当前任务节点</span><strong>${activeAction ? `${activeAction.order}/${plan.actions.length} · ${escapeHtml(activeAction.label)}` : `已完成 ${plan.actions.length}/${plan.actions.length}`}</strong></div><div class="drawer-progress"><b style="width:${progress}%"></b></div><div class="drawer-progress-label"><span>端到端执行进度 · 已完成 ${completed} 步</span><strong>${progress}%</strong></div><div class="automation-steps">${plan.actions.map((action) => `<div class="automation-step ${escapeHtml(action.status)} ${action.requires_confirmation ? "confirmation-required" : ""}" data-automation-action="${escapeHtml(action.id)}"><i class="automation-step-index">${action.status === "completed" ? icon("check") : action.status === "failed" ? icon("alert") : action.order}</i><div class="automation-step-copy"><strong>${escapeHtml(action.label)}</strong><span>${escapeHtml(action.result || "等待小懿执行并回写结果")}</span><div class="automation-step-meta"><span>${escapeHtml(action.phase || "执行")}</span><span>${escapeHtml(action.kind)}</span><span>${escapeHtml(action.risk_level)} risk</span>${action.requires_confirmation ? "<span>当前步骤需确认</span>" : ""}</div></div></div>`).join("")}</div><div class="automation-audit"><strong>最近审计轨迹</strong>${(plan.audit_trail || []).slice(-6).map((event) => `<p><time>${formatShortTime(event.timestamp)}</time>${escapeHtml(event.detail)}</p>`).join("")}</div></div>`;
    const footer = $("#drawerFooter");
    if (plan.status === "completed") {
      footer.innerHTML = state.activeReport && plan.intent === "generate_report"
        ? `<button type="button" class="drawer-button secondary" data-action="close-drawer">关闭</button><button type="button" class="drawer-button" data-report-download="markdown">${icon("download")}下载报告</button>`
        : `<button type="button" class="drawer-button secondary" data-action="close-drawer">关闭</button><button type="button" class="drawer-button" data-action="system-status">${icon("check")}查看系统状态</button>`;
      setHeroState("complete");
    } else if (["failed", "cancelled"].includes(plan.status)) {
      footer.innerHTML = `<button type="button" class="drawer-button secondary" data-action="close-drawer">关闭</button><button type="button" class="drawer-button" data-action="new-chat">新建指令</button>`;
      setHeroState("idle");
    } else if (plan.status === "awaiting_confirmation") {
      footer.innerHTML = `<button type="button" class="drawer-button secondary" data-action="stop-automation">拒绝并停止</button><button type="button" class="drawer-button warning" data-action="confirm-automation">${icon("alert")}审核当前动作</button>`;
      setHeroState("confirm");
    } else {
      footer.innerHTML = `<button type="button" class="drawer-button secondary" data-action="stop-automation">停止计划</button><button type="button" class="drawer-button" data-action="resume-automation">${icon("play")}${state.automationRunning ? "执行中" : "继续执行"}</button>`;
      setHeroState("execute", `${Math.min(plan.actions.length, completed + 1)}/${plan.actions.length} 步`);
    }
  }

  async function executeAutomationPlan() {
    if (state.automationRunning || !state.automationPlan) return;
    state.automationRunning = true;
    state.automationAbort = false;
    renderAutomationPlan();
    try {
      while (!state.automationAbort && state.automationPlan && !["completed", "failed", "cancelled"].includes(state.automationPlan.status)) {
        const action = state.automationPlan.actions.find((item) => item.status === "running") || state.automationPlan.actions.find((item) => item.status === "pending");
        if (!action) break;
        if (action.requires_confirmation && !state.automationPlan.confirmed_action_ids.includes(action.id)) {
          state.automationPlan.status = "awaiting_confirmation";
          state.automationPlan.current_action_id = action.id;
          renderAutomationPlan();
          await requestAutomationConfirmation();
          break;
        }
        const stepSelector = `[data-automation-action="${CSS.escape(action.id)}"]`;
        await guidedFocus(stepSelector, `第 ${action.order} 步：${action.label}`, false, 380);
        if (["optimize_agv_energy_rl","weather_berth_joint_rl","qc_agv_yard_marl"].includes(state.automationPlan.intent) && action.visual_target) {
          const missionTarget = `[data-agent-target="${CSS.escape(action.visual_target)}"]`;
          if ($(missionTarget)) await guidedFocus(missionTarget, action.label, false, 460);
        }
        let outcome = "success";
        let detail = "界面动作已完成。";
        try {
          detail = await executeSemanticAction(action);
        } catch (error) {
          outcome = "failed";
          detail = error.message || "界面动作失败";
        }
        const response = await api(`/api/automation/plans/${encodeURIComponent(state.automationPlan.id)}/next`, {
          method:"POST", headers:{"Content-Type":"application/json"},
          body:JSON.stringify({ outcome, detail })
        });
        state.automationPlan = response.plan;
        renderAutomationPlan();
        if (outcome === "failed") {
          toast("智能操作已安全停止", detail, "warning", 5600);
          break;
        }
        if (state.automationPlan.status === "awaiting_confirmation") {
          await requestAutomationConfirmation();
          break;
        }
        await sleep(520);
      }
      if (state.automationPlan?.status === "completed") {
        toast("端到端智能操作已完成", "执行结果已回写智能对话，全部步骤和证据均已写入审计轨迹。", "success", 6200);
        revealCompletedAutomationResult(state.automationPlan);
      }
    } catch (error) {
      toast("智能操作中断", `${error.message}。没有继续执行后续步骤。`, "warning", 6000);
    } finally {
      state.automationRunning = false;
      $("#agentCursor").classList.remove("visible");
      if (state.automationPlan && state.drawerMode === "automation") renderAutomationPlan();
    }
  }

  async function executeSemanticAction(action) {
    const parameters = action.parameters || {};
    const viewSelectors = {
      chat:'.top-nav [data-view-target="chat"]', decisions:'.top-nav [data-view-target="decisions"]',
      analytics:'.top-nav [data-view-target="analytics"]', knowledge:'.top-nav [data-view-target="knowledge"]',
      tasks:'.top-nav [data-view-target="tasks"]'
    };
    if (action.kind === "navigate") {
      const view = ["chat","decisions","analytics","knowledge","tasks"].includes(parameters.view) ? parameters.view : null;
      if (!view) throw new Error("计划包含未授权的导航目标");
      await guidedFocus(viewSelectors[view], action.label, false, 520);
      setView(view);
      return `已打开${action.label.replace(/^打开/, "")}。`;
    }
    if (action.kind === "set_range") {
      const range = ["today","7d","30d"].includes(parameters.range) ? parameters.range : null;
      if (!range) throw new Error("计划包含未授权的时间范围");
      await guidedFocus(`#analyticsRange [data-range="${range}"]`, action.label, false, 520);
      const loaded = await loadEnergy(range, "analytics");
      if (!loaded) throw new Error("能耗数据未成功加载");
      state.automationContext.energyRange = range;
      return `已加载 ${range} 能耗与碳排趋势。`;
    }
    if (action.kind === "set_mode") {
      if (!["expert","ops","sop","brief"].includes(parameters.mode)) throw new Error("计划包含未授权的回答模式");
      $("#mode").value = parameters.mode;
      $("#modeShortLabel").textContent = modeShort(parameters.mode);
      return `回答模式已切换为${modeLabel(parameters.mode)}。`;
    }
    if (action.kind === "create_task") {
      const templateId = ["analyze-energy","optimize-berth","handle-alert","generate-daily-report"].includes(parameters.template_id) ? parameters.template_id : null;
      if (!templateId) throw new Error("计划包含未授权的任务模板");
      setView("tasks");
      await sleep(260);
      await guidedFocus(`[data-task-template="${templateId}"]`, action.label, false, 520);
      const task = await startTask(templateId, { openDrawer:false });
      if (!task) throw new Error("任务服务未创建执行记录");
      state.automationContext.task = task;
      return `已创建任务 ${task.id}；执行步骤可在任务中心审计。`;
    }
    if (action.kind === "filter_knowledge") {
      const query = String(parameters.query || "").slice(0,120);
      if (query.length < 2) throw new Error("知识检索词不足 2 个字符");
      setView("knowledge");
      $("#knowledgeSearch").value = query;
      await guidedFocus('[data-agent-target="knowledge-search"]', action.label, false, 480);
      const hits = await searchKnowledge(query);
      state.automationContext.searchQuery = query;
      state.automationContext.searchHits = hits;
      return `已检索“${query}”，获得 ${hits.length} 个达标片段，其中 ${hits.filter((hit) => hit.official).length} 个来自官方来源。`;
    }
    if (action.kind === "generate_report") {
      const type = ["energy","management_brief"].includes(parameters.report_type) ? parameters.report_type : "management_brief";
      const range = ["today","7d","30d"].includes(parameters.range) ? parameters.range : state.automationContext.energyRange || state.energy?.range || "today";
      await guidedFocus('[data-agent-target="generate-report"]', action.label, false, 480);
      const report = await generateReport(type, { background:true, range });
      state.automationContext.report = report;
      return `已按 ${report.analysis_range || range} 周期生成报告 ${report.id}，可从执行轨迹导出。`;
    }
    if (action.kind === "new_chat") {
      await guidedFocus('[data-agent-target="new-chat"]', action.label, false, 460); beginNewConversation(); return "已新建连续对话。";
    }
    if (action.kind === "show_history") {
      await guidedFocus('[data-agent-target="history"]', action.label, false, 460); openHistory(); return "已打开对话历史。";
    }
    if (action.kind === "show_favorites") {
      await guidedFocus('[data-agent-target="favorites"]', action.label, false, 460); openFavorites(); return "已打开我的收藏。";
    }
    if (action.kind === "show_alerts") {
      await guidedFocus('[data-agent-target="notifications"]', action.label, false, 460); openNotifications(); return "已打开预警与提醒。";
    }
    if (action.kind === "show_settings") {
      await guidedFocus('[data-agent-target="settings"]', action.label, false, 460); openSettings(); return "已打开系统设置。";
    }
    if (action.kind === "switch_avatar") {
      await guidedFocus('[data-agent-target="avatar-switch"]', action.label, false, 460); openAvatarPicker(); return "已打开小懿形象选择。";
    }
    if (action.kind === "open_panel") {
      const panels = { notifications:openNotifications, settings:openSettings, connectors:openConnectors, knowledge_sources:openKnowledgeSources, knowledge_intake:openKnowledgeIntake };
      if (!panels[parameters.panel]) throw new Error("计划包含未授权的面板");
      const targets = { notifications:'[data-agent-target="notifications"]', settings:'[data-agent-target="settings"]', connectors:'[data-agent-target="connectors"]', knowledge_sources:'[data-agent-target="knowledge-sources"]', knowledge_intake:'[data-agent-target="knowledge-sources"]' };
      if (targets[parameters.panel]) await guidedFocus(targets[parameters.panel], action.label, false, 480);
      await panels[parameters.panel](); return `已打开${parameters.panel}面板。`;
    }
    if (action.kind === "check_simulator_runtime") {
      const runtime = await api("/api/sailing-simulator/status", { timeoutMs:5000 });
      state.automationContext.simulator = runtime;
      if (!runtime.launchable && !runtime.running) throw new Error(runtime.message);
      return runtime.running
        ? `已识别桌面航行模拟器，Godot 主进程正在运行${runtime.pid ? `，PID ${runtime.pid}` : ""}。`
        : "已识别桌面航行模拟器项目、project.godot、主场景与 Godot 运行程序。";
    }
    if (action.kind === "launch_simulator") {
      const runtime = await api("/api/sailing-simulator/launch", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ target:"sailing-simulator" }), timeoutMs:10000
      });
      state.automationContext.simulator = runtime;
      return runtime.running
        ? "航行模拟器已在运行，已复用现有 Godot 窗口，不重复创建进程。"
        : "航行模拟器进程已由小懿拉起，正在加载桌面主场景。";
    }
    if (action.kind === "verify_simulator_runtime") {
      const deadline = Date.now() + 30000;
      let runtime = state.automationContext.simulator;
      while (Date.now() < deadline) {
        runtime = await api("/api/sailing-simulator/status", { timeoutMs:5000 });
        state.automationContext.simulator = runtime;
        if (runtime.running) return `航行模拟器已就绪：Godot 主进程在线${runtime.pid ? `，PID ${runtime.pid}` : ""}，主场景配置已核验。`;
        if (["error","unavailable"].includes(runtime.state)) throw new Error(runtime.message);
        await sleep(650);
      }
      throw new Error("航行模拟器在30秒内未完成启动，请查看 .runtime/sailing-simulator.log");
    }
    if (action.kind === "open_simulator") {
      const runtime = await api("/api/sailing-simulator/focus", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ target:"sailing-simulator" }), timeoutMs:5000
      });
      state.automationContext.simulator = runtime;
      const answer = `桌面航行模拟器已由小懿启动。\n\n运行状态：ONLINE\n项目路径：${runtime.project_root}\n运行引擎：Godot\n进程编号：${runtime.pid || "已复用现有窗口"}\n启动方式：聊天指令白名单启动\n\n当前完成的是桌面进程启动与窗口切换；具体航行、天气和强化学习操作继续在模拟器窗口内完成。`;
      commitAutomationChat({ question:state.automationPlan?.command || "启动模拟器", answer, intent:"sailing_simulator_launch", mode:"brief", confidence:"高", sourceQuality:"not_applicable" });
      toast("航行模拟器已就绪", "已请求切换到桌面 Godot 仿真窗口", "success", 2200);
      return "航行模拟器已启动并通过主进程校验，已请求切换到桌面仿真窗口。";
    }
    if (["check_linked_system_runtime","launch_linked_system_runtime","verify_linked_system_runtime","open_linked_system_runtime"].includes(action.kind)) {
      const target = String(parameters.target || "");
      const allowed = { "port-dt-multi":"港口数字孪生", "energy-cockpit":"能碳驾驶舱", "malacca-sandbox":"马六甲推演" };
      if (!allowed[target]) throw new Error("计划包含未登记的联动系统");
      const label = allowed[target];
      const readRuntime = async () => {
        const status = await api(`/api/linked-systems/status?targets=${encodeURIComponent(target)}`, { timeoutMs:5000 });
        const runtime = status.systems?.[target];
        if (!runtime) throw new Error(`${label}未返回登记状态`);
        state.automationContext.linkedSystem = runtime;
        return runtime;
      };
      if (action.kind === "check_linked_system_runtime") {
        const runtime = await readRuntime();
        return runtime.running ? `${label}业务接口已在线，可直接复用。` : `${label}当前离线，已确认其白名单启动目标。`;
      }
      if (action.kind === "launch_linked_system_runtime") {
        const response = await api("/api/linked-systems/launch", {
          method:"POST", headers:{"Content-Type":"application/json"},
          body:JSON.stringify({ targets:[target] }), timeoutMs:12000
        });
        const runtime = response.systems?.[target];
        if (!runtime) throw new Error(`${label}启动接口未返回状态`);
        state.automationContext.linkedSystem = runtime;
        if (["error","port_conflict"].includes(runtime.state)) throw new Error(runtime.message);
        return runtime.running ? `${label}已在线，已复用现有服务。` : `${label}进程已拉起，正在等待业务健康接口。`;
      }
      if (action.kind === "verify_linked_system_runtime") {
        const deadline = Date.now() + 120000;
        while (Date.now() < deadline) {
          const runtime = await readRuntime();
          if (runtime.running) return `${label}业务健康检查通过${runtime.pid ? `，PID ${runtime.pid}` : ""}。`;
          if (["error","port_conflict"].includes(runtime.state)) throw new Error(runtime.message);
          await sleep(800);
        }
        throw new Error(`${label}在120秒内未通过业务健康检查`);
      }
      const runtime = state.automationContext.linkedSystem || await readRuntime();
      if (!runtime.running || !runtime.url) throw new Error(`${label}尚未就绪，已取消页面跳转`);
      const answer = `${label}已由小懿启动。\n\n运行状态：ONLINE\n服务地址：${runtime.url}\n启动方式：独立系统白名单指令\n\n正在进入${label}；返回上一页即可回到小懿。`;
      commitAutomationChat({ question:state.automationPlan?.command || `启动${label}`, answer, intent:`linked_system_launch_${target}`, mode:"brief", confidence:"高", sourceQuality:"not_applicable" });
      toast(`${label}已就绪`, `正在进入${label}`, "success", 1800);
      window.setTimeout(() => window.location.assign(runtime.url), 1500);
      return `${label}已启动并通过业务健康检查，正在进入对应系统。`;
    }
    if (action.kind === "ask") {
      const prompt = String(parameters.question || "").slice(0,500);
      if (prompt.length < 2) throw new Error("问答步骤缺少有效问题");
      $("#question").value = prompt;
      const mode = ["expert","ops","sop","brief"].includes($("#mode").value) ? $("#mode").value : "expert";
      const data = await api("/api/chat", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ question:prompt, mode, top_k:10, strict_evidence:true, session_id:state.sessionId }) });
      state.automationContext.answerData = data;
      state.automationContext.answerQuestion = prompt;
      return `专业回答已生成：${(data.evidence || []).length} 条证据，覆盖率 ${(Number(data.coverage || 0) * 100).toFixed(0)}%，${data.grounded ? "通过严格证据校验" : "已标记证据边界"}。`;
    }
    if (action.kind === "inspect_knowledge") {
      const status = await api("/api/knowledge/status");
      state.knowledgeStatus = status;
      state.automationContext.knowledgeStatus = status;
      return `索引状态正常：${status.document_count} 份文档、${status.chunk_count} 个片段、${status.official_verified_documents} 份官方发布来源资料；其中摘要与目录定位不等于正式全文。`;
    }
    if (action.kind === "verify_sources") {
      const evidence = state.automationContext.answerData?.evidence || state.automationContext.searchHits || [];
      const official = evidence.filter((item) => item.official && item.source_quality === "official_verified").length;
      const hashed = evidence.filter((item) => item.chunk_checksum_sha256 || item.document_checksum_sha256).length;
      return `已核验 ${evidence.length} 条候选证据：${official} 条官方来源、${hashed} 条具备内容校验哈希。`;
    }
    if (action.kind === "validate_answer") {
      const data = state.automationContext.answerData;
      if (!data) throw new Error("尚未生成可校验的专业回答");
      return data.grounded
        ? `回答校验通过：严格证据模式已启用，覆盖率 ${(Number(data.coverage || 0) * 100).toFixed(0)}%，来源等级为 ${sourceQualityLabel(data.source_quality)}。`
        : `回答已按安全边界处理：${refusalReasonLabel(data.refusal_reason)}。`;
    }
    if (action.kind === "inspect_metrics") {
      const summary = state.energy?.summary;
      if (!summary) throw new Error("当前没有可读取的能耗指标");
      state.automationContext.energySummary = summary;
      return `已读取总能耗 ${formatNumber(summary.total_energy_mwh)} MWh、碳排 ${formatNumber(summary.carbon_emissions_tco2e)} tCO₂e、岸电利用率 ${formatNumber(summary.shore_power_utilization_percent)}%。`;
    }
    if (action.kind === "inspect_decision") {
      const alerts = state.dashboard.alerts?.items || [];
      state.automationContext.decision = { command:parameters.command || "", alertCount:alerts.length, critical:alerts.filter((item) => item.level === "critical").length };
      if (state.modalKind === "notifications") { await sleep(520); closeModal(); }
      return alerts.length ? `已归并 ${alerts.length} 条运营信号，其中 ${state.automationContext.decision.critical} 条高优先级，并建立约束与风险检查项。` : "已完成业务目标、资源约束和风险边界解析。";
    }
    if (action.kind === "advance_task") {
      const task = state.activeTask;
      if (!task) throw new Error("尚未创建可推进的智能任务");
      const running = task.steps.find((step) => step.status === "running");
      const response = await api(`/api/tasks/${encodeURIComponent(task.id)}/next`, { method:"POST" });
      state.activeTask = response.task;
      state.automationContext.task = response.task;
      state.tasks = [response.task, ...state.tasks.filter((item) => item.id !== response.task.id)];
      renderTaskList(); updateCounts();
      return `${running?.title || "任务步骤"}已完成；子任务进度 ${response.task.progress_percent}%。${response.assistant_message}`;
    }
    if (action.kind === "inspect_task_result") {
      const task = state.automationContext.task || state.activeTask;
      if (!task) throw new Error("没有可核验的任务结果");
      const completed = task.steps.filter((step) => step.status === "completed").length;
      return `任务 ${task.id} 已核验：${completed}/${task.steps.length} 个子步骤完成，状态 ${task.status}，审计结果完整。`;
    }
    if (action.kind === "validate_report") {
      const report = state.automationContext.report || state.activeReport;
      if (!report) throw new Error("没有可校验的报告");
      const sections = Array.isArray(report.sections) ? report.sections.length : String(report.content_markdown || "").split("\n## ").length;
      return `报告 ${report.id} 校验完成：${sections} 个结构章节，数据模式和生成时间已声明，可追溯导出。`;
    }
    if (action.kind === "present_report") {
      return deliverAutomationReport();
    }
    if (action.kind === "verify_view") {
      const view = parameters.view || state.view;
      const checks = { chat:state.view === "chat", analytics:state.view === "analytics", decisions:state.view === "decisions", knowledge:state.view === "knowledge", tasks:state.view === "tasks", history:state.modalKind === "history", favorites:state.modalKind === "favorites", settings:state.modalKind === "settings", avatar:state.modalKind === "avatar" };
      if (checks[view] === false) throw new Error(`目标工作区 ${view} 未完成加载`);
      return `目标工作区 ${view} 已加载，交互入口和可见状态核验通过。`;
    }
    if (action.kind === "inspect_connectors") {
      state.connectors = state.connectors || await api("/api/connectors");
      state.automationContext.connectors = state.connectors;
      const detail = parameters.detail;
      if (state.modalKind === "connectors" && detail === "guard") { await sleep(520); closeModal(); }
      if (detail === "mapping") return `已核验 ${state.connectors.total} 类接口契约与标准字段映射，真实站点字段可在接入时按版本配置。`;
      if (detail === "guard") return `写操作门禁检查完成：${state.connectors.online} 个真实在线接口；未验证在线的接口禁止下发。`;
      return `接口目录已读取：${state.connectors.total} 类、${state.connectors.online} 个真实在线、${state.connectors.offline} 个待配置。`;
    }
    if (["open_rl_mission","check_rl_systems","build_rl_scenario","replay_rl_training","run_rl_competition","verify_rl_policy","dispatch_rl_dry_run","present_rl_mission"].includes(action.kind)) {
      const mission = state.automationContext.rlMission ||= { missionId:`rlm-${Date.now().toString(36)}`, ...(state.pendingRLLabConfig || {}) };
      state.pendingRLLabConfig = null;
      const payload = {
        mission_id:mission.missionId,
        command:state.automationPlan?.command || "真实数据驱动RL训练实验",
        run_id:mission.runId || null,
        dataset_id:mission.datasetId || "uci_appliances_energy",
        algorithms:mission.algorithms || ["q_learning","sarsa","expected_sarsa","double_q_learning","pid"],
        episodes:Number(mission.episodes || 160),
        horizon_steps:Number(mission.horizonSteps || 72),
        seed:Number(mission.seed || 240520)
      };
      if (action.kind === "open_rl_mission") {
        mission.health = await api("/api/rl-mission/health", { timeoutMs:15000 });
        renderAutomationPlan();
        return `RL训练实验室已启动：${mission.health.online_count}/${mission.health.total} 个本地节点就绪，已登记 ${mission.health.algorithms?.length || 0} 种公平基线。`;
      }
      if (action.kind === "check_rl_systems") {
        mission.health = await api("/api/rl-mission/health", { timeoutMs:15000 });
        renderAutomationPlan();
        const required = ["dataset","trainer","guardrail"];
        const offline = required.filter((id) => !mission.health.systems?.[id]?.online);
        if (offline.length) throw new Error(`RL本地依赖未就绪：${offline.join("、")}。请先获取公开数据或检查数据配置。`);
        const online = Object.values(mission.health.systems || {}).filter((item) => item.online).map((item) => item.label).join("、");
        return `训练依赖检查完成：${online}；训练渲染关闭、测试集保持隔离。`;
      }
      if (action.kind === "build_rl_scenario") {
        mission.scenario = await api("/api/rl-mission/scenario", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload), timeoutMs:18000 });
        renderAutomationPlan();
        const dataset = mission.scenario.dataset || {};
        return `数据场景已建立：${dataset.row_count || 0} 条真实观测，${dataset.step_minutes || "—"} 分钟步长，SHA-256 ${String(dataset.sha256 || "").slice(0,12)}；测试段尚未读取。`;
      }
      if (action.kind === "replay_rl_training") {
        if (!mission.runId) {
          mission.training = await api("/api/rl-mission/train", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload), timeoutMs:18000 });
          mission.runId = mission.training.run_id;
        }
        const deadline = Date.now() + 5 * 60 * 1000;
        while (["queued","training","cancelling"].includes(mission.training.status)) {
          if (Date.now() > deadline) throw new Error("真实训练超过5分钟，任务仍在后台运行，可稍后按run_id查询。");
          await sleep(220);
          mission.training = await api(`/api/rl-mission/training/${encodeURIComponent(mission.runId)}`, { timeoutMs:18000 });
          renderAutomationPlan();
        }
        if (!['trained','evaluated'].includes(mission.training.status)) throw new Error(`训练任务${mission.training.status}：${mission.training.error || "未知错误"}`);
        return `真实训练完成：4种RL算法共执行 ${mission.training.completed_training_episodes} 个episode，训练阶段rendering_performed=${mission.training.training?.rendering_performed}，模型已按算法落盘并计算哈希。`;
      }
      if (action.kind === "run_rl_competition") {
        mission.simulation = await api("/api/rl-mission/simulate", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({...payload,run_id:mission.runId}), timeoutMs:60000 });
        renderAutomationPlan();
        return `保留测试集渲染完成：${mission.simulation.race?.length || 0} 种算法按同一测试时段比较，领先算法 ${mission.simulation.best_algorithm_id}。`;
      }
      if (action.kind === "verify_rl_policy") {
        mission.verification = await api("/api/rl-mission/verify", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({...payload,run_id:mission.runId}), timeoutMs:18000 });
        renderAutomationPlan();
        return mission.verification.ok
          ? `复现守护栏验证通过：${mission.verification.passed}/${mission.verification.total} 项，包括训练无渲染、测试隔离、五基线和模型哈希。`
          : "复现守护栏未通过，结果归档链已保持锁定。";
      }
      if (action.kind === "dispatch_rl_dry_run") {
        if (!mission.verification?.ok) throw new Error("安全守护栏未通过，禁止进入Dry-run");
        mission.dispatch = await api("/api/rl-mission/dispatch", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({...payload,run_id:mission.runId}), timeoutMs:30000 });
        renderAutomationPlan();
        return `本地测试Dry-run已归档；production_executed=${mission.dispatch.production_executed}，回执 ${mission.dispatch.artifact}。`;
      }
      if (action.kind === "present_rl_mission") return deliverRLMissionResult();
    }
    const weatherKinds = ["open_weather_mission","check_weather_systems","build_weather_scenario","infer_weather_policy","benchmark_weather_policy","replay_weather_twin","verify_weather_policy","dispatch_weather_dry_run","present_weather_mission"];
    const marlKinds = ["open_marl_mission","check_marl_systems","build_marl_cmdp","coordinate_marl_agents","inspect_marl_reward","verify_marl_policy","dispatch_marl_dry_run","present_marl_mission"];
    if (weatherKinds.includes(action.kind) || marlKinds.includes(action.kind)) {
      const mission = state.automationContext.advancedRL ||= { missionId:`arm-${Date.now().toString(36)}` };
      const payload = { mission_id:mission.missionId, command:state.automationPlan?.command || "高级RL联合调度", policy_id:mission.coordination?.policy?.id || mission.inference?.selected_action?.id || null };
      if (["open_weather_mission","open_marl_mission","check_weather_systems","check_marl_systems"].includes(action.kind)) {
        mission.health = await api("/api/advanced-rl/health", { timeoutMs:18000 });
        renderAutomationPlan();
        const online = Object.values(mission.health.systems || {}).filter((item) => item.online).map((item) => item.label).join("、");
        if (action.kind.startsWith("check_")) {
          const required = action.kind === "check_weather_systems"
            ? [{ id:"malacca", target:"malacca-sandbox" }, { id:"twin", target:"port-dt-multi" }]
            : [{ id:"twin", target:"port-dt-multi" }, { id:"mas", target:"port-dt-multi" }, { id:"portviz", target:"port-dt-multi" }];
          let offline = required.filter((item) => !mission.health.systems?.[item.id]?.online).map((item) => ({ ...item, label:mission.health.systems?.[item.id]?.label || item.id }));
          if (offline.length) {
            await requestLinkedSystemsStartup(offline, action.kind === "check_weather_systems" ? "极端天气联合调度" : "多智能体协同优化");
            mission.health = await api("/api/advanced-rl/health", { timeoutMs:22000 });
            renderAutomationPlan();
            offline = required.filter((item) => !mission.health.systems?.[item.id]?.online).map((item) => ({ ...item, label:mission.health.systems?.[item.id]?.label || item.id }));
            if (offline.length) throw new Error(`联动系统启动后健康检查仍未通过：${offline.map((item) => item.label).join("、")}`);
          }
        }
        const refreshedOnline = Object.values(mission.health.systems || {}).filter((item) => item.online).map((item) => item.label).join("、");
        return `${action.kind.startsWith("open_") ? "RL任务舱已启动" : "联动拓扑检查完成"}：${mission.health.online_count}/${mission.health.total} 节点就绪（${action.kind.startsWith("check_") ? refreshedOnline : online}），生产写入关闭。`;
      }
      if (action.kind === "build_weather_scenario") {
        mission.scenario = await api("/api/advanced-rl/weather/scenario", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload), timeoutMs:18000 });
        renderAutomationPlan();
        const weather = mission.scenario.weather || {}, traffic = mission.scenario.traffic || {};
        return `台风压力场已注入：风速 ${weather.wind_speed_ms}m/s、浪高 ${weather.wave_height_m}m、能见度 ${weather.visibility_km}km；${traffic.vessels} 艘船进入联合调度。`;
      }
      if (action.kind === "infer_weather_policy") {
        mission.inference = await api("/api/advanced-rl/weather/inference", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload), timeoutMs:25000 });
        renderAutomationPlan();
        if (!mission.inference.online) throw new Error("马六甲MAPPO推理接口离线");
        return `MAPPO推理完成：选中“${mission.inference.selected_action?.label || "联合调度动作"}”，置信度 ${mission.inference.inference?.confidencePercent || "—"}%。`;
      }
      if (action.kind === "benchmark_weather_policy") {
        mission.benchmark = await api("/api/advanced-rl/weather/benchmark", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload), timeoutMs:40000 });
        renderAutomationPlan();
        if (!mission.benchmark.online) throw new Error("马六甲五算法基准接口离线");
        return `五算法公平基准完成：${mission.benchmark.episodes} episodes，相同状态空间与种子族；领先算法 ${mission.benchmark.best_algorithm_id}。`;
      }
      if (action.kind === "replay_weather_twin") {
        mission.replay = await api("/api/advanced-rl/weather/replay", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload), timeoutMs:30000 });
        renderAutomationPlan();
        return `数字孪生台风场景与决策轨迹已回放：${mission.replay.systems_completed}/${mission.replay.systems_total} 个回放节点完成。`;
      }
      if (action.kind === "verify_weather_policy") {
        mission.verification = await api("/api/advanced-rl/weather/verify", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload), timeoutMs:30000 });
        renderAutomationPlan();
        return mission.verification.ok ? `极端天气门禁 ${mission.verification.passed}/${mission.verification.total} 通过，只允许Dry-run。` : "风浪、避碰或泊位约束未通过，执行链保持锁定。";
      }
      if (action.kind === "dispatch_weather_dry_run") {
        if (!mission.verification?.ok) throw new Error("极端天气安全门禁未通过");
        mission.dispatch = await api("/api/advanced-rl/weather/dispatch", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload), timeoutMs:30000 });
        renderAutomationPlan();
        return `联合调度Dry-run回执 ${mission.dispatch.systems_completed}/${mission.dispatch.systems_total}，production_executed=${mission.dispatch.production_executed}。`;
      }
      if (action.kind === "present_weather_mission") return deliverWeatherMissionResult();
      if (action.kind === "build_marl_cmdp") {
        mission.scenario = await api("/api/advanced-rl/marl/scenario", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload), timeoutMs:22000 });
        renderAutomationPlan();
        const cmdp = mission.scenario.cmdp || {};
        return `约束MDP已构建：state ${cmdp.state_dim}D、joint action ${cmdp.joint_action_dim}D、共享Actor与集中式Critic，4类硬约束已登记。`;
      }
      if (action.kind === "coordinate_marl_agents") {
        mission.coordination = await api("/api/advanced-rl/marl/coordinate", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload), timeoutMs:30000 });
        renderAutomationPlan();
        return `三类智能体已完成联合动作推理：${mission.coordination.policy?.label || "MAPPO"}，联合Reward ${formatNumber(mission.coordination.joint_reward)}。`;
      }
      if (action.kind === "inspect_marl_reward") {
        if (!mission.coordination?.reward) throw new Error("尚未获得可解释的Reward分解");
        renderAutomationPlan();
        return `Reward已分解为吞吐、节拍、能效、排队、翻箱和安全六项；${mission.coordination.policies?.length || 0} 个候选策略完成同场景赛马。`;
      }
      if (action.kind === "verify_marl_policy") {
        mission.verification = await api("/api/advanced-rl/marl/verify", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload), timeoutMs:30000 });
        renderAutomationPlan();
        return mission.verification.ok ? `联合动作安全投影 ${mission.verification.passed}/${mission.verification.total} 通过，只允许Dry-run。` : "多智能体安全约束未全部通过，联合动作已锁定。";
      }
      if (action.kind === "dispatch_marl_dry_run") {
        if (!mission.verification?.ok) throw new Error("联合动作安全投影未通过");
        mission.dispatch = await api("/api/advanced-rl/marl/dispatch", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload), timeoutMs:30000 });
        renderAutomationPlan();
        return `MAS仿真与孪生回放 ${mission.dispatch.systems_completed}/${mission.dispatch.systems_total} 完成，production_executed=${mission.dispatch.production_executed}。`;
      }
      if (action.kind === "present_marl_mission") return deliverMarlMissionResult();
    }
    if (action.kind === "present_result") return deliverAutomationResult(parameters.result_type || "operation");
    if (action.kind === "propose_live_action") {
      const result = await preflightLiveAction(action);
      state.automationContext.liveOperationResult = result;
      return result;
    }
    throw new Error(`动作类型 ${action.kind} 不在前端白名单中`);
  }

  function commitAutomationChat({ question, answer, intent, mode = "expert", evidence = [], confidence = "高", coverage = 0, sourceQuality = "not_applicable", grounded = false, refusalReason = null, nextQuestions = [] }) {
    setView("chat", { silent:true });
    state.currentQuestion = question;
    state.currentAnswer = answer;
    state.currentIntent = intent;
    state.currentMode = mode;
    state.currentEvidence = evidence;
    state.currentVerification = null;
    state.currentConfidence = confidence;
    $("#question").value = question;
    $("#currentQuestion").textContent = question;
    $("#userMessageTime").textContent = formatShortTime();
    $("#userBubbleRow").hidden = false;
    void typeAnswer(answer, state.generationId);
    $("#responseKpis").hidden = !["energy_analysis", "energy_carbon"].includes(intent);
    $("#analysisTitle").textContent = intentTitle(intent);
    $("#analysisDate").textContent = `${new Date().toLocaleDateString("zh-CN")} · 小懿端到端智能操作`;
    $("#responseStatus").textContent = "任务结果已自动回写，操作轨迹与证据链可追溯";
    $("#modeMetric").textContent = `${modeLabel(mode)} · Agent`;
    $("#evMetric").textContent = String(evidence.length);
    $("#confMetric").textContent = confidence;
    $("#intentTag").textContent = intent;
    $("#evidence").textContent = JSON.stringify(evidence);
    updateGroundingState({ evidence, grounded, coverage, source_quality:sourceQuality, refusal_reason:refusalReason });
    if (nextQuestions.length) renderNextQuestions(nextQuestions, mode, question);
    else $("#next").innerHTML = `<button type="button" data-action="resume-automation">${icon("task")}查看完整执行轨迹</button><button type="button" data-action="knowledge-sources">${icon("check")}查看来源审计</button><button type="button" data-action="generate-report">${icon("report")}生成详细报告</button>`;
    saveTopic({ question, answer, intent, mode, evidence, confidence, next_questions:nextQuestions, grounded, coverage, source_quality:sourceQuality, refusal_reason:refusalReason, strict_evidence:true });
    $("#conversationFeed").scrollTop = $("#conversationFeed").scrollHeight;
    setHeroState("complete");
  }

  function deliverAutomationResult(resultType) {
    const plan = state.automationPlan;
    const context = state.automationContext;
    if (!plan) throw new Error("智能操作计划上下文已失效");
    if (resultType === "navigation") {
      toast("界面操作已核验", `${plan.summary} 当前工作区已完成状态检查。`, "success", 4200);
      return "目标界面已打开并完成可见状态核验。";
    }
    if (resultType === "knowledge") {
      const data = context.answerData;
      if (!data) throw new Error("专业回答尚未生成");
      commitAutomationChat({
        question:plan.command, answer:data.answer, intent:data.intent, mode:data.mode,
        evidence:data.evidence || [], confidence:data.confidence, coverage:Number(data.coverage || 0),
        sourceQuality:data.source_quality, grounded:Boolean(data.grounded), refusalReason:data.refusal_reason,
        nextQuestions:data.next_questions || []
      });
      return `完整回答已回写智能对话：${(data.evidence || []).length} 条证据，用户可直接阅读并继续追问。`;
    }
    if (resultType === "energy") {
      const summary = context.energySummary || state.energy?.summary;
      const task = context.task || state.activeTask;
      const answer = `能耗智能分析已完成。\n\n核心指标：\n• 综合能耗：${formatNumber(summary.total_energy_mwh)} MWh，较对比期 ${Number(summary.energy_change_percent) <= 0 ? "下降" : "上升"} ${Math.abs(Number(summary.energy_change_percent)).toFixed(1)}%。\n• 碳排放：${formatNumber(summary.carbon_emissions_tco2e)} tCO₂e，较对比期 ${Number(summary.carbon_change_percent) <= 0 ? "下降" : "上升"} ${Math.abs(Number(summary.carbon_change_percent)).toFixed(1)}%。\n• 岸电利用率：${formatNumber(summary.shore_power_utilization_percent)}%，变化 ${Number(summary.shore_power_change_percent) >= 0 ? "+" : ""}${Number(summary.shore_power_change_percent).toFixed(1)}%。\n\n小懿已自动完成数据校验、基线比对、异常识别、建议生成和结果归档。任务编号：${task?.id || "已记录"}，任务进度 ${task?.progress_percent ?? 100}%。\n\n数据边界：以上来自运营沙箱动态合成接口，保留事件时间和质量码；接入真实 EMS、TOS 与岸电计量适配器后，将按同一契约读取现场数据。`;
      commitAutomationChat({ question:plan.command, answer, intent:"energy_analysis", mode:"ops", confidence:"高", sourceQuality:"not_applicable" });
      return "能耗分析结论、任务编号和数据边界已回写智能对话。";
    }
    if (resultType === "task") {
      const task = context.task || state.activeTask;
      const results = (task?.steps || []).map((step) => `• ${step.title}：${step.result || "已完成"}`).join("\n");
      const answer = `泊位调度候选建议任务已完成。\n\n${results}\n\n任务编号：${task?.id || "已记录"}\n完成度：${task?.progress_percent ?? 100}%\n\n当前结果是按已返回船期、剩余箱量和岸桥可用性生成的启发式候选，不是数学优化器证明的全局最优解，也不会直接修改真实泊位计划。接入 TOS、PCS、AIS/VTS 后，小懿可读取船期、泊位占用、吃水、岸桥和拖轮窗口；任何真实下发仍需调度员对当前动作单独确认。`;
      commitAutomationChat({ question:plan.command, answer, intent:"berth_optimization", mode:"ops", confidence:"高", sourceQuality:"not_applicable" });
      return "调度建议、任务进度和生产安全边界已回写智能对话。";
    }
    if (resultType === "connectors") {
      const connectors = context.connectors || state.connectors;
      const answer = `真实港口接口装配检查已完成。\n\n• 已预留接口类型：${connectors?.total || 0} 类。\n• 已验证真实在线：${connectors?.online || 0} 个。\n• 待配置站点接口：${connectors?.offline || 0} 个。\n• 已检查能力清单、标准字段映射、认证方式和写操作门禁。\n\n安全结论：只有完成站点地址与凭据配置、健康检查真实通过、服务端明确开放写权限，并由授权人员确认当前动作后，系统才允许进入写操作预检；其余情况一律失败关闭，不会下发生产指令。`;
      commitAutomationChat({ question:plan.command, answer, intent:"connector_audit", mode:"brief", confidence:"高", sourceQuality:"not_applicable" });
      return "接口状态、装配范围与安全门禁结论已回写智能对话。";
    }
    if (resultType === "live_operation") {
      const answer = `生产操作预检已完成。\n\n${context.liveOperationResult || "目标接口尚未通过真实在线与写权限门禁，未下发任何生产指令。"}\n\n小懿已保留指令解析、接口核验、影响分析、人工确认和预检结果。真实站点接入后仍坚持“单次授权、最小权限、可回滚、全审计”的执行边界。`;
      commitAutomationChat({ question:plan.command, answer, intent:"live_operation_preflight", mode:"brief", confidence:"高", sourceQuality:"not_applicable" });
      return "生产操作预检结果与安全边界已回写智能对话。";
    }
    return "操作结果已完成审计记录。";
  }

  function deliverAutomationReport() {
    const plan = state.automationPlan;
    const report = state.automationContext.report || state.activeReport;
    if (!plan || !report) throw new Error("报告结果尚未生成");
    const answer = `报告已自动生成并完成结构校验。\n\n报告名称：${report.title}\n报告编号：${report.id}\n生成时间：${formatDateTime(report.generated_at)}\n\n${report.content_markdown}\n\n您可以在执行轨迹中直接下载 Markdown 或 JSON 版本。说明：报告中的运营指标为动态运营沙箱数据；接入真实港口适配器后沿用相同的数据校验、血缘和审计流程。`;
    commitAutomationChat({ question:plan.command, answer, intent:"report_generation", mode:"brief", confidence:"高", sourceQuality:"not_applicable" });
    return `报告 ${report.id} 的摘要和完整内容已回写智能对话，并保留下载入口。`;
  }

  function deliverRLMissionResult() {
    const plan = state.automationPlan;
    const mission = state.automationContext.rlMission || {};
    const scenario = mission.scenario || {};
    const dataset = scenario.dataset || mission.training?.dataset || {};
    const training = mission.training || {};
    const simulation = mission.simulation || {};
    const verification = mission.verification || {};
    const dispatch = mission.dispatch || {};
    const race = simulation.race || [];
    const raceLines = race.map((item) => `• ${item.label}：score=${formatNumber(item.score)}，成本变化 ${formatNumber(item.cost_saving_percent)}%，峰值变化 ${formatNumber(item.peak_reduction_percent)}%，约束违例 ${formatNumber(item.constraint_violations)}`).join("\n");
    const answer = `可复现RL能源调度实验已完成。\n\n`+
      `数据：${dataset.label || "—"}，${dataset.row_count || 0}条真实观测，SHA-256 ${String(dataset.sha256 || "—")}。\n`+
      `数据划分：按时间顺序70%训练、15%验证、15%保留测试；默认公开数据不是港口实绩。\n`+
      `训练：Q-learning、SARSA、Expected SARSA、Double Q-learning共完成 ${training.completed_training_episodes || 0} 个episode；PID与现场SOP规则作为非学习强基线不训练。训练阶段rendering_performed=${Boolean(training.training?.rendering_performed)}。\n`+
      `测试：训练全部完成后才读取保留测试段并生成轨迹，领先算法 ${simulation.best_algorithm_id || "—"}。\n\n`+
      `六种候选与基线结果：\n${raceLines || "• 测试结果未返回。"}\n\n`+
      `复现门禁：${verification.passed || 0}/${verification.total || 0}项通过；归档状态 ${dispatch.status || "未归档"}，production_executed=${Boolean(dispatch.production_executed)}。\n\n`+
      `接港口方式：提供同一timestamp/load_kw CSV契约并设置XIAOYI_RL_DATASET_PATH；算法、时间划分、模型哈希、测试隔离和前端进度无需改代码。`;
    commitAutomationChat({ question:plan.command, answer, intent:"rl_energy_training_lab", mode:"ops", confidence:"高", sourceQuality:"public_dataset", grounded:true, nextQuestions:["解释六种候选与基线的更新规则", "查看数据和模型哈希", "如何替换为港口EMS与AGV数据"] });
    return "真实训练、保留测试集评测、六种候选与基线结果、模型哈希与数据边界已回写智能对话。";
  }

  function deliverWeatherMissionResult() {
    const plan = state.automationPlan, mission = state.automationContext.advancedRL || {};
    const scenario = mission.scenario || {}, weather = scenario.weather || {}, inference = mission.inference || {};
    const selected = inference.selected_action || {}, comparison = inference.comparison || {}, benchmark = mission.benchmark || {};
    const verification = mission.verification || {}, dispatch = mission.dispatch || {};
    const answer = `极端天气下船舶—泊位联合调度已完成。\n\n`+
      `压力场：风速 ${weather.wind_speed_ms ?? "—"} m/s、浪高 ${weather.wave_height_m ?? "—"} m、能见度 ${weather.visibility_km ?? "—"} km。\n`+
      `MAPPO动作：${selected.label || "—"}，概率 ${selected.probability ?? "—"}%，到港窗口调整 ${selected.arrivalShiftMinutes ?? 0} 分钟。\n`+
      `公平基准：${benchmark.episodes || 0} episodes，六种候选与基线使用相同状态空间、动作空间与随机种子族，领先算法 ${benchmark.best_algorithm_id || "—"}。\n\n`+
      `策略相对基线：拥堵改善 ${comparison.improvement?.congestionPoints ?? "—"} 点，延误改善 ${comparison.improvement?.delayMinutes ?? "—"} 分钟，韧性提升 ${comparison.improvement?.resiliencePoints ?? "—"} 点。\n`+
      `安全门禁：${verification.passed || 0}/${verification.total || 0} 通过；Dry-run回执 ${dispatch.systems_completed || 0}/${dispatch.systems_total || 3}，production_executed=${Boolean(dispatch.production_executed)}。\n\n`+
      `数据边界：船舶泊位来自小懿动态运营沙箱，MAPPO推理和五算法曲线来自马六甲本地RL接口，调度轨迹来自港口数字孪生回放。极端天气是动态压力场景而非现场实况，本次未修改真实泊位计划。`;
    commitAutomationChat({ question:plan.command, answer, intent:"weather_berth_joint_rl_result", mode:"ops", confidence:"高", sourceQuality:"not_applicable", nextQuestions:["解释MAPPO的状态与动作空间", "查看五算法基准差异", "生成极端天气调度审计报告"] });
    return "极端天气策略、算法基准、孪生回放、安全门禁和数据边界已回写智能对话。";
  }

  function deliverMarlMissionResult() {
    const plan = state.automationPlan, mission = state.automationContext.advancedRL || {};
    const scenario = mission.scenario || {}, coordination = mission.coordination || {}, verification = mission.verification || {}, dispatch = mission.dispatch || {};
    const agents = scenario.agents || {}, reward = coordination.reward || {};
    const rewardText = Object.entries(reward).map(([key,value]) => `${key}=${Number(value) >= 0 ? "+" : ""}${formatNumber(value)}`).join("，");
    const answer = `岸桥—AGV—堆场多智能体协同已完成。\n\n`+
      `智能体规模：岸桥 ${agents.qc?.active ?? "—"}/${agents.qc?.count ?? "—"} 活跃，AGV ${agents.agv?.active ?? "—"}/${agents.agv?.count ?? "—"} 作业，堆场 ${agents.yard?.active ?? "—"}/${agents.yard?.count ?? "—"} 作业。\n`+
      `约束MDP：${scenario.cmdp?.state_dim || "—"}维状态、${scenario.cmdp?.joint_action_dim || "—"}维联合动作；采用共享Actor、集中式Critic和Lagrangian安全投影。\n`+
      `选中策略：${coordination.policy?.label || "—"}，联合Reward ${formatNumber(coordination.joint_reward ?? "—")}。\n`+
      `Reward分解：${rewardText || "未返回"}。\n\n`+
      `安全门禁：碰撞间隔、岸桥—AGV缓冲区、堆场容量、设备锁定、联合动作投影与生产写入锁共 ${verification.passed || 0}/${verification.total || 0} 通过。\n`+
      `执行结果：${dispatch.status || "未执行"}，MAS与孪生回执 ${dispatch.systems_completed || 0}/${dispatch.systems_total || 2}，production_executed=${Boolean(dispatch.production_executed)}。\n\n`+
      `数据边界：设备状态与联合动作输入来自小懿动态运营沙箱、PortViz动态帧和MAS接口；策略结果属于约束多智能体仿真，不是生产控制结果。本次未调用岸桥PLC、AGV调度器或堆场TOS写接口。`;
    commitAutomationChat({ question:plan.command, answer, intent:"qc_agv_yard_marl_result", mode:"ops", confidence:"高", sourceQuality:"not_applicable", nextQuestions:["展开讲Reward设计", "解释CTDE与安全门禁", "生成多智能体协同审计报告"] });
    return "多智能体状态、Reward分解、策略赛马、安全投影和Dry-run回执已回写智能对话。";
  }

  async function requestAutomationConfirmation() {
    const plan = state.automationPlan;
    const action = plan?.actions.find((item) => item.id === plan.current_action_id) || plan?.actions.find((item) => item.status === "running");
    if (!plan || !action) return;
    setHeroState("confirm");
    if (["weather_berth_joint_rl","qc_agv_yard_marl"].includes(plan.intent)) {
      const mission = state.automationContext.advancedRL || {};
      const verification = mission.verification || {};
      const weather = plan.intent === "weather_berth_joint_rl";
      const title = weather ? "确认极端天气联合调度 Dry-run" : "确认多智能体联合动作 Dry-run";
      const targets = weather ? "马六甲推演与港口数字孪生" : "MAS仿真与港口数字孪生";
      const excluded = weather ? "生产TOS、VTS或船舶指令接口" : "岸桥PLC、AGV调度器或堆场TOS写接口";
      openModal(title, "安全门禁已通过；本次确认不会产生生产写入", `<div class="automation-confirmation high-risk"><div class="confirmation-shield">${icon("alert")}</div><strong>${escapeHtml(action.label)}</strong><p>${escapeHtml(plan.command)}</p><div class="confirmation-scope"><span>计划 ID：${escapeHtml(plan.id)}</span><span>任务 ID：${escapeHtml(mission.missionId || "—")}</span><span>安全门禁：${verification.passed || 0}/${verification.total || 0} 通过</span><span>执行模式：DRY-RUN ONLY</span></div><div class="drawer-note"><strong>确认边界：</strong>只向${targets}提交仿真和回放请求；不会调用${excluded}。</div></div>`, `<button type="button" class="drawer-button secondary" data-modal-action="reject-automation">拒绝并停止</button><button type="button" class="drawer-button warning" data-modal-action="confirm-automation">确认当前 Dry-run</button>`, "automation-confirm");
      return;
    }
    if (plan.intent === "optimize_agv_energy_rl") {
      const mission = state.automationContext.rlMission || {};
      const verification = mission.verification || {};
      openModal("确认归档本地测试 Dry-run", "训练和测试证据已通过验证；本次确认不会产生生产写入", `<div class="automation-confirmation high-risk"><div class="confirmation-shield">${icon("alert")}</div><strong>${escapeHtml(action.label)}</strong><p>${escapeHtml(plan.command)}</p><div class="confirmation-scope"><span>计划 ID：${escapeHtml(plan.id)}</span><span>训练 run_id：${escapeHtml(mission.runId || "—")}</span><span>复现门禁：${verification.passed || 0}/${verification.total || 0} 通过</span><span>执行模式：LOCAL RECORD ONLY</span></div><div class="drawer-note"><strong>确认边界：</strong>只写入当前训练目录下的测试回执JSON。不会调用生产TOS、EMS、PLC、AGV控制器、岸电系统或外部数字孪生写接口。</div></div>`, `<button type="button" class="drawer-button secondary" data-modal-action="reject-automation">拒绝并停止</button><button type="button" class="drawer-button warning" data-modal-action="confirm-automation">确认归档本地 Dry-run</button>`, "automation-confirm");
      return;
    }
    let connector = null;
    if (action.parameters?.connector) {
      try { connector = await api(`/api/connectors/${encodeURIComponent(action.parameters.connector)}`); } catch { /* shown as unavailable */ }
    }
    openModal("审核生产操作建议", "确认只绑定当前计划和当前动作；不会复用到其他任务", `<div class="automation-confirmation high-risk"><div class="confirmation-shield">${icon("alert")}</div><strong>${escapeHtml(action.label)}</strong><p>${escapeHtml(action.parameters?.command || plan.command)}</p><div class="confirmation-scope"><span>计划 ID：${escapeHtml(plan.id)}</span><span>动作 ID：${escapeHtml(action.id)}</span><span>风险等级：${escapeHtml(action.risk_level)}</span><span>目标接口：${escapeHtml(connector ? `${connector.code} / ${connector.mode} / ${connector.health_status}` : action.parameters?.connector || "未指定")}</span></div><div class="drawer-note"><strong>安全边界：</strong>${connector?.mode === "live" ? "仍需服务端写权限、真实在线健康检查及当前确认。" : "目标接口不是已验证 live 状态，即使确认也会被服务端门禁拒绝；不会下发设备指令。"}</div></div>`, `<button type="button" class="drawer-button secondary" data-modal-action="reject-automation">拒绝并停止</button><button type="button" class="drawer-button warning" data-modal-action="confirm-automation">确认当前步骤并执行预检</button>`, "automation-confirm");
  }

  async function confirmAutomation(confirmed) {
    const plan = state.automationPlan;
    const actionId = plan?.current_action_id;
    if (!plan || !actionId) return;
    try {
      state.automationPlan = await api(`/api/automation/plans/${encodeURIComponent(plan.id)}/confirm`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ action_id:actionId, confirmed:Boolean(confirmed), operator:"管理员" })
      });
      closeModal();
      openAutomationPlan(state.automationPlan);
      if (confirmed) void executeAutomationPlan();
      else toast("已拒绝生产操作", "当前计划已取消，后续步骤不会执行。", "warning", 5200);
    } catch (error) {
      toast("确认记录失败", error.message, "warning");
    }
  }

  async function preflightLiveAction(action) {
    const connectorId = action.parameters?.connector;
    if (!connectorId) throw new Error("生产操作没有指定连接器");
    const connector = await api(`/api/connectors/${encodeURIComponent(connectorId)}`);
    const operation = connector.capabilities.write[0];
    if (!operation) return `${connector.code} 为只读连接器；未生成也未下发写操作。`;
    try {
      const result = await api(`/api/connectors/${encodeURIComponent(connectorId)}/write-preflight`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ operation, payload:{ command:action.parameters.command }, confirmation:{ confirmed:true, operator_id:"管理员", reason:"用户确认当前小懿操作计划", reference:action.id } })
      });
      return `${result.message} 预检回执 ${result.authorization_id}；authorized=${result.authorized}；dual_approval_verified=${result.dual_approval_verified}；dispatch_performed=${result.dispatch_performed}。`;
    } catch (error) {
      if ([400,403,409].includes(error.status)) return `安全门禁已生效：${error.message}；未下发任何生产指令。`;
      throw error;
    }
  }

  function stopAutomation(reason = "用户主动停止智能操作") {
    state.automationAbort = true;
    state.automationRunning = false;
    const plan = state.automationPlan;
    const current = plan?.actions.find((action) => action.status === "running");
    if (plan && current && !current.requires_confirmation) {
      void api(`/api/automation/plans/${encodeURIComponent(plan.id)}/next`, {
        method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ outcome:"failed", detail:reason })
      }).then((response) => {
        if (state.automationPlan?.id === plan.id) { state.automationPlan = response.plan; renderAutomationPlan(); }
      }).catch(() => {});
    } else if (plan && current?.requires_confirmation) {
      void confirmAutomation(false);
    }
    $("#agentCursor").classList.remove("visible");
    toast("智能操作已停止", reason, "warning");
  }

  function resumeAutomation() {
    if (!state.automationPlan) return;
    openAutomationPlan(state.automationPlan);
    if (state.automationPlan.status === "awaiting_confirmation") requestAutomationConfirmation();
    else void executeAutomationPlan();
  }

  async function startAgentDemo() {
    if (state.tourRunning) return;
    state.tourRunning = true;
    $("#agentDemoBtn").classList.add("running");
    toast("小懿已启动智能巡检", "将依次查看动态数据、评估决策并创建运营沙箱任务。", "info", 5200);
    try {
      await guidedFocus('.top-nav [data-view-target="analytics"]', "打开数据分析");
      await sleep(420);
      await guidedFocus('#analyticsRange [data-range="7d"]', "切换 7 日趋势");
      await sleep(520);
      await guidedFocus('.top-nav [data-view-target="decisions"]', "进入决策建议");
      await sleep(450);
      await guidedFocus('.decision-item [data-task-template="optimize-berth"]', "创建泊位优化任务");
      await sleep(650);
      toast("智能巡检已进入任务步骤", "继续点击“执行下一步”，可查看逐项执行与人工确认边界。", "success", 6000);
    } finally {
      state.tourRunning = false;
      $("#agentDemoBtn").classList.remove("running");
      setTimeout(() => $("#agentCursor").classList.remove("visible"), 900);
    }
  }

  function toggleTheme(theme) {
    const next = theme || (document.body.dataset.theme === "deep-sea" ? "midnight" : "deep-sea");
    document.body.dataset.theme = next;
    localStorage.setItem(STORAGE.theme, next);
    $(".theme-switch strong").textContent = next === "deep-sea" ? "深海模式" : "极夜模式";
    toast("主题已切换", next === "deep-sea" ? "当前为深海驾驶舱。" : "当前为高对比极夜驾驶舱。", "success");
  }

  function toggleAgentMode(force, announce = true) {
    state.agentMode = typeof force === "boolean" ? force : !state.agentMode;
    localStorage.setItem(STORAGE.agentMode, String(state.agentMode));
    const button = $("#agentModeBtn");
    if (button) {
      button.classList.toggle("active", state.agentMode);
      button.setAttribute("aria-pressed", String(state.agentMode));
      const label = $("span", button);
      if (label) label.textContent = state.agentMode ? "智能操作已开启" : "智能操作已关闭";
    }
    if (announce) toast(state.agentMode ? "智能操作已开启" : "智能操作已关闭", state.agentMode ? "操作型指令会先生成白名单计划，再逐步执行。" : "输入内容将直接进入严格证据问答。", state.agentMode ? "success" : "warning");
  }

  async function loadConnectorSummary() {
    try {
      state.connectors = await api("/api/connectors");
      const badge = $("#connectorNavBadge");
      if (badge) {
        badge.textContent = state.connectors.online > 0 ? `${state.connectors.online} 在线` : "待接入";
        badge.title = `${state.connectors.online} 个真实在线，${state.connectors.offline} 个待配置`;
        badge.classList.toggle("show", true);
      }
    } catch {
      state.connectors = null;
    }
  }

  function compactHash(value) {
    const hash = String(value || "");
    return hash ? `${hash.slice(0, 8)}…${hash.slice(-6)}` : "—";
  }

  function latestCompletedRun(runs) {
    return (runs || []).find((item) => item.status === "evaluated")
      || (runs || []).find((item) => item.status === "trained")
      || (runs || [])[0]
      || null;
  }

  function renderRLAdvisorFeed() {
    const feed = $("#rlAdvisorFeed");
    if (!feed) return;
    const messages = state.rlAdvisorMessages.length ? state.rlAdvisorMessages : [{
      role:"assistant",
      text:"数据与算法证据已经就绪。你可以直接问我观测、动作、目标函数、数据可信度，或最近一次结果能否用于简历。",
      evidence:[]
    }];
    feed.innerHTML = messages.map((item) => {
      const role = item.role === "user" ? "user" : item.loading ? "loading" : "assistant";
      const evidence = (item.evidence || []).length
        ? `<small>${item.evidence.map((entry) => escapeHtml(entry)).join(" · ")}</small>`
        : "";
      return `<div class="rl-advisor-message ${role}"><i>${role === "user" ? "您" : "懿"}</i><p>${escapeHtml(item.text)}${evidence}</p></div>`;
    }).join("");
    feed.scrollTop = feed.scrollHeight;
  }

  function renderRLCenter() {
    const payload = state.rlCenter;
    if (!payload) return;
    const health = payload.health || {};
    const datasets = health.datasets || [];
    const algorithms = health.algorithms || [];
    const runs = payload.runs?.items || [];
    const recent = latestCompletedRun(runs);
    const evidenceReport = payload.evidence || {};
    const formalReport = evidenceReport.report || {};
    const available = datasets.filter((item) => item.available);
    const largest = [...available].sort((left, right) => Number(right.row_count || 0) - Number(left.row_count || 0))[0];
    const portDatasets = available.filter((item) => item.port_data);
    const evaluated = recent?.test_evaluation;
    const reportReady = evidenceReport.status === "available";

    const gate = $("#rlCenterGate");
    const policyAdmitted = formalReport.policy_admission_passed === true;
    gate.textContent = health.status !== "ready"
      ? "DATA REQUIRED"
      : reportReady
        ? policyAdmitted ? "OFFLINE CANDIDATE ADMITTED" : "EVIDENCE PASS · POLICY BLOCKED"
        : "REPORT REQUIRED";
    gate.classList.toggle("warning", health.status !== "ready" || !policyAdmitted);
    const formalConfig = formalReport.configuration || {};
    const recentIsFormal = Number(recent?.config?.episodes || 0) >= 320
      && Number(recent?.config?.horizon_steps || 0) >= 72;
    $("#rlCenterEvidenceStrip").innerHTML = [
      ["最大公开基准", largest ? `${formatNumber(largest.row_count, 0)} 行` : "—", largest?.id || "未安装"],
      ["正式证据批次", reportReady ? `${formalConfig.seed_count || 0}种子 × ${formalConfig.algorithms?.length || 0}算法` : "待生成", reportReady ? "320回合 · 训练无渲染" : "运行固定基准"],
      ["最近本机运行", recent ? `${recent.completed_training_episodes || 0}/${recent.total_training_episodes || 0}` : "尚无", recent ? `${recentIsFormal ? "FORMAL" : "SMOKE/WIRING"} · seed ${recent.config?.seed}` : "可配置复现实验"],
      ["RL候选准入", reportReady ? policyAdmitted ? "离线影子候选" : "全部未晋级" : "待评测", reportReady ? "强基线保留 · 生产权限关闭" : "训练后独立盲测"],
    ].map(([label, value, detail]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><em>${escapeHtml(detail)}</em></div>`).join("");

    $("#rlCenterDatasets").innerHTML = available.map((item) => `
      <div class="rl-dataset-card ${item.port_data ? "port" : ""}" title="${escapeHtml(item.description)}">
        <span>${item.port_data ? "PORT SCENARIO" : "PUBLIC BENCHMARK"}<b>${escapeHtml(item.license)}</b></span>
        <strong>${escapeHtml(item.label)}</strong>
        <em>${formatNumber(item.row_count, 0)} 行 · ${compactHash(item.sha256)} · ${escapeHtml(item.evidence_level)}</em>
      </div>`).join("");

    const validationResults = new Map((recent?.validation?.results || []).map((item) => [item.algorithm_id, item]));
    $("#rlCenterAlgorithmMatrix").innerHTML = algorithms.map((item, index) => {
      const score = validationResults.get(item.id)?.selection_score;
      const familyLabel = item.family === "control_theory" ? "CONTROL" : item.family === "operations_rule" ? "SOP RULE" : "RL";
      return `<article class="rl-matrix-card ${item.trainable ? "" : "pid"}">
        <span>0${index + 1} · ${familyLabel}<b>${item.trainable ? "TRAINABLE" : "STRONG BASELINE"}</b></span>
        <strong>${escapeHtml(item.label)}</strong>
        <p>${escapeHtml(item.description)}</p>
        <code>${escapeHtml(item.update_equation)}</code>
        <footer><span>相同划分/种子/约束</span><b>${Number.isFinite(Number(score)) ? Number(score).toFixed(3) : "READY"}</b></footer>
      </article>`;
    }).join("");

    const contracts = health.environment_contracts || [];
    const contract = contracts.find((item) => item.id === "port_operations") || contracts[0];
    if (contract) {
      $("#rlCenterContract").innerHTML = `
        <div class="rl-contract-block"><span>OBSERVATION · ${contract.observation.length}</span><strong>港口状态观测</strong><div class="rl-contract-tags">${contract.observation.slice(0, 9).map((item) => `<b>${escapeHtml(item.id)}</b>`).join("")}</div></div>
        <div class="rl-contract-block"><span>ACTION · ${contract.actions.length}</span><strong>离散能力档位</strong><div class="rl-contract-tags">${contract.actions.map((item) => `<b>${escapeHtml(item.label)}</b>`).join("")}</div></div>
        <div class="rl-contract-block"><span>OBJECTIVE + HARD GATE</span><strong>最大化安全约束下的服务收益</strong><p>${escapeHtml(contract.objective.formula)}</p><div class="rl-contract-tags">${contract.hard_constraints.slice(0, 2).map((item) => `<b>${escapeHtml(item)}</b>`).join("")}</div></div>`;
    }

    const systemNodes = [
      ["公开数据", available.length ? `${available.length} 套可用` : "缺失", available.length > 0],
      ["六算法对比", algorithms.length === 6 ? "4 RL + PID + SOP" : `${algorithms.length} 个`, algorithms.length === 6],
      ["保留测试", evaluated ? "已生成轨迹" : "训练后执行", Boolean(evaluated)],
      ["证据账本", reportReady ? policyAdmitted ? "候选已准入" : "失败候选已固化" : "待跑基准", reportReady],
      ["真实港口适配", portDatasets.length ? "契约已就绪" : "待接入", false],
    ];
    $("#rlSystemLinkage").innerHTML = systemNodes.map(([label, detail, ready]) => `
      <div class="rl-system-node-mini ${ready ? "" : "pending"}"><i></i><strong>${escapeHtml(label)}</strong><span>${escapeHtml(detail)}</span></div>`).join("");
    renderRLAdvisorFeed();
  }

  async function loadRLCenter(force = false) {
    if (state.rlCenterLoading || (state.rlCenter && !force)) {
      if (state.rlCenter) renderRLCenter();
      return;
    }
    state.rlCenterLoading = true;
    const gate = $("#rlCenterGate");
    if (gate) gate.textContent = "VERIFYING";
    try {
      const [health, runs, evidence] = await Promise.all([
        api("/api/rl-lab/health", { timeoutMs:30000 }),
        api("/api/rl-lab/runs?limit=10", { timeoutMs:18000 }),
        api("/api/rl-lab/evidence", { timeoutMs:18000 }),
      ]);
      state.rlCenter = { health, runs, evidence };
      renderRLCenter();
    } catch (error) {
      if (gate) {
        gate.textContent = "CHECK FAILED";
        gate.classList.add("warning");
      }
      toast("训练中心读取失败", error.message, "warning", 6000);
    } finally {
      state.rlCenterLoading = false;
    }
  }

  async function askRLAdvisor(message) {
    const prompt = String(message || "").trim();
    if (!prompt) return;
    const input = $("#rlAdvisorInput");
    if (input) input.value = "";
    state.rlAdvisorMessages.push({ role:"user", text:prompt });
    state.rlAdvisorMessages.push({ role:"assistant", text:"正在核对当前数据、契约与运行记录…", loading:true });
    renderRLAdvisorFeed();
    const recent = latestCompletedRun(state.rlCenter?.runs?.items || []);
    try {
      const result = await api("/api/rl-lab/advisor", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({ message:prompt, run_id:recent?.run_id || null }),
        timeoutMs:18000
      });
      state.rlAdvisorMessages.pop();
      state.rlAdvisorMessages.push({ role:"assistant", text:result.answer, evidence:result.evidence || [] });
    } catch (error) {
      state.rlAdvisorMessages.pop();
      state.rlAdvisorMessages.push({ role:"assistant", text:`这次没有读取到训练证据：${error.message}` });
    }
    renderRLAdvisorFeed();
  }

  function showRLContract() {
    const contracts = state.rlCenter?.health?.environment_contracts || [];
    const contract = contracts.find((item) => item.id === "port_operations") || contracts[0];
    if (!contract) {
      toast("契约尚未加载", "请先刷新训练中心。", "warning");
      return;
    }
    openModal(
      `${contract.label} · 环境契约`,
      contract.decision_scope,
      `<div class="settings-grid">
        <div class="drawer-note"><strong>观测（${contract.observation.length}）</strong><br>${contract.observation.map((item) => `${escapeHtml(item.id)} ← ${escapeHtml(item.source)} [${escapeHtml(item.evidence)}]`).join("<br>")}</div>
        <div class="drawer-note"><strong>动作（${contract.actions.length}）</strong><br>${contract.actions.map((item) => `${item.index}. ${escapeHtml(item.label)}`).join("<br>")}</div>
        <div class="drawer-note"><strong>目标函数</strong><br><code>${escapeHtml(contract.objective.formula)}</code></div>
        <div class="drawer-note"><strong>硬约束</strong><br>${contract.hard_constraints.map((item) => `• ${escapeHtml(item)}`).join("<br>")}</div>
      </div>`,
      `<button type="button" class="drawer-button" data-action="close-modal">已核对</button>`,
      "rl-contract"
    );
  }

  function showRLEvidence() {
    const envelope = state.rlCenter?.evidence || {};
    const report = envelope.report || {};
    const experiments = report.experiments || {};
    if (envelope.status !== "available") {
      toast("正式证据尚未生成", "请先运行固定多数据集、多种子基准。", "warning");
      return;
    }
    const rows = Object.entries(experiments).map(([datasetId, experiment]) => {
      const admission = experiment.admission || {};
      const runIds = (experiment.runs || []).map((run) => `${escapeHtml(run.run_id)} / seed ${run.seed}`).join("<br>");
      const failures = (admission.failed_candidates || []).map((item) => `${escapeHtml(item.algorithm_id)}：${escapeHtml((item.reasons || []).join("、") || item.status)}`).join("<br>");
      return `<article class="source-record unverified"><div class="source-record-header"><div class="source-record-title"><strong>${escapeHtml(experiment.dataset?.label || datasetId)}</strong><span>${escapeHtml(datasetId)}</span></div><span class="source-status unverified">${admission.rl_candidate_admitted ? "OFFLINE ADMITTED" : "RL REJECTED"}</span></div><div class="source-provenance"><span>验证集候选<b>${escapeHtml(admission.validation_candidate_id || "—")} · ${admission.validation_votes || 0}/3</b></span><span>保留强基线<b>${escapeHtml(admission.strong_baseline_id || "—")}</b></span><span>数据SHA-256<b>${compactHash(experiment.dataset?.sha256)}</b></span><span>生产权限<b>FALSE</b></span></div><div class="drawer-note"><strong>失败候选</strong><br>${failures}</div><div class="drawer-note"><strong>正式run_id</strong><br>${runIds}</div></article>`;
    }).join("");
    openModal(
      "RL正式证据、95%区间与失败候选",
      `${escapeHtml(envelope.report_path || "reports/rl_dataset_benchmark_v2.json")} · ${escapeHtml(report.generated_at || "")}`,
      `<div class="drawer-note"><strong>准入结论：</strong>evidence_integrity_passed=${String(report.evidence_integrity_passed)}；policy_admission_passed=${String(report.policy_admission_passed)}；production_authority=${String(report.production_authority)}。测试均值只做盲测诊断，候选只按验证集多数票选择。</div><div class="source-record-list">${rows}</div>`,
      `<button type="button" class="drawer-button" data-action="close-modal">已核对证据</button>`,
      "rl-evidence"
    );
  }

  async function handleRLCenterAction(action) {
    if (action === "refresh") {
      state.rlCenter = null;
      await loadRLCenter(true);
      toast("证据已刷新", "数据哈希、运行记录、算法和环境契约已重新读取。", "success");
    }
    if (action === "start-training") await openRLLabConfig();
    if (action === "show-contract") showRLContract();
    if (action === "show-evidence") showRLEvidence();
    if (action === "ask-advisor") {
      $("#rlAdvisorInput")?.focus();
      await askRLAdvisor("结合当前证据，告诉我下一步应该跑哪套数据，以及为什么。");
    }
  }

  async function openRLLabConfig() {
    try {
      const health = await api("/api/rl-lab/health", { timeoutMs:18000 });
      const algorithms = health.algorithms || [];
      const datasets = (health.datasets || []).filter((item) => item.available);
      if (!datasets.length) throw new Error("没有可用数据集，请先运行 scripts/fetch_public_rl_dataset.py");
      openModal(
        "真实RL训练实验室",
        "选择数据、算法与训练规模；完整基准包含4种RL、PID与现场SOP固定规则",
        `<div class="settings-grid rl-lab-config">
          <label class="intake-field"><span>训练数据集</span><select id="rlDataset">${datasets.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)} · ${formatNumber(item.row_count,0)}行${item.port_data ? " · 港口数据" : " · 公开非港口基准"}</option>`).join("")}</select></label>
          <div class="rl-algorithm-selector"><span>算法选择</span>${algorithms.map((item) => `<label><input type="checkbox" data-rl-algorithm value="${escapeHtml(item.id)}" checked><strong>${escapeHtml(item.label)}</strong><small>${item.trainable ? escapeHtml(item.type) : "不学习强基线，不执行训练episode"}</small></label>`).join("")}</div>
          <div class="rl-config-row"><label class="intake-field"><span>每种RL训练回合</span><select id="rlEpisodes"><option value="80">80 · 快速</option><option value="160" selected>160 · 标准</option><option value="320">320 · 深度</option></select></label><label class="intake-field"><span>单回合时域步数</span><select id="rlHorizon"><option value="36">36</option><option value="72" selected>72</option><option value="144">144</option></select></label><label class="intake-field"><span>随机种子</span><input id="rlSeed" type="number" min="0" max="2147483647" value="240520"></label></div>
          <div class="drawer-note"><strong>强制边界：</strong>训练只读取时间前段训练集且render_mode=None；全部训练完成后，点击测试步骤才读取保留测试段并返回渲染轨迹。取消任一算法可以做单项实验，但完整“六算法与强基线”审计要求全部勾选。</div>
        </div>`,
        `<button type="button" class="drawer-button secondary" data-action="close-modal">取消</button><button type="button" class="drawer-button" data-modal-action="start-rl-lab">启动真实训练</button>`,
        "rl-lab-config"
      );
    } catch (error) {
      toast("RL训练实验室不可用", error.message, "warning", 6000);
    }
  }

  function startConfiguredRLLab() {
    const algorithms = $$('[data-rl-algorithm]:checked').map((item) => item.value);
    if (!algorithms.some((item) => !["pid", "sop_rule"].includes(item))) {
      toast("至少选择一种RL算法", "PID和SOP规则都是非学习强基线，不能单独作为强化学习训练任务。", "warning");
      return;
    }
    state.pendingRLLabConfig = {
      datasetId:$("#rlDataset").value,
      algorithms,
      episodes:Number($("#rlEpisodes").value),
      horizonSteps:Number($("#rlHorizon").value),
      seed:Number($("#rlSeed").value)
    };
    closeModal();
    if (!state.agentMode) toggleAgentMode(false);
    setView("chat", { silent:true });
    const labels = algorithms.join("、");
    void askQuestion(`启动RL训练实验：数据集${state.pendingRLLabConfig.datasetId}，算法${labels}，每种RL训练${state.pendingRLLabConfig.episodes}回合；训练时不渲染，训练完成后再用保留测试集渲染。`, "ops");
  }

  function bindEvents() {
    $("#composerForm").addEventListener("submit", (event) => { event.preventDefault(); ask(); });
    $("#question").addEventListener("input", autoGrowQuestion);
    $("#question").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); ask(); }
    });
    $("#mode").addEventListener("change", (event) => { $("#modeShortLabel").textContent = modeShort(event.target.value); });
    $("#knowledgeSearch").addEventListener("input", (event) => {
      clearTimeout(state.knowledgeSearchTimer);
      const value = event.target.value;
      if (String(value).trim().length < 2) renderKnowledge(value);
      else state.knowledgeSearchTimer = setTimeout(() => renderKnowledge(value), 260);
    });
    $("#strictEvidence")?.addEventListener("change", (event) => {
      localStorage.setItem(STORAGE.strictEvidence, String(event.target.checked));
      toast(event.target.checked ? "严格证据模式已开启" : "严格证据模式已关闭", event.target.checked ? "专业事实必须命中已登记索引，证据不足将拒答。" : "关闭后仍会展示来源，但不再强制拒答。", event.target.checked ? "success" : "warning", 4800);
    });
    $("#fileInput").addEventListener("change", (event) => { handleAttachment(event.target.files?.[0]); event.target.value = ""; });
    $("#rlAdvisorForm")?.addEventListener("submit", (event) => {
      event.preventDefault();
      void askRLAdvisor($("#rlAdvisorInput")?.value);
    });
    $$('[data-rl-mission-launch]').forEach((button) => button.addEventListener("click", (event) => {
      event.stopPropagation();
      void openRLLabConfig();
    }));
    $("#modalBackdrop").addEventListener("click", closeModal);
    $("#drawerBackdrop").addEventListener("click", closeDrawer);

    document.addEventListener("input", (event) => {
      if (!event.target.matches?.("[data-catalog-search]")) return;
      state.knowledgeCatalogQuery = event.target.value;
      renderKnowledgeCatalogResults();
    });

    document.addEventListener("click", async (event) => {
      const viewButton = event.target.closest("[data-view-target]");
      if (viewButton) { setView(viewButton.dataset.viewTarget); return; }
      const simulatorScenario = event.target.closest("[data-simulator-scenario]");
      if (simulatorScenario) { await changeSimulatorScenario(simulatorScenario.dataset.simulatorScenario); return; }
      const simulatorApproval = event.target.closest("[data-sim-approve]");
      if (simulatorApproval) { await approveSimulatorDecision(simulatorApproval.dataset.simApprove, simulatorApproval.dataset.simRole); return; }
      const simulatorExecution = event.target.closest("[data-sim-execute]");
      if (simulatorExecution) { await executeSimulatorDecision(simulatorExecution.dataset.simExecute); return; }
      const simulatorRollback = event.target.closest("[data-sim-rollback]");
      if (simulatorRollback) { await rollbackSimulatorDecision(simulatorRollback.dataset.simRollback); return; }
      const rlCenterAction = event.target.closest("[data-rl-center-action]");
      if (rlCenterAction) { await handleRLCenterAction(rlCenterAction.dataset.rlCenterAction); return; }
      const rlAdvisorPrompt = event.target.closest("[data-rl-advisor-prompt]");
      if (rlAdvisorPrompt) { await askRLAdvisor(rlAdvisorPrompt.dataset.rlAdvisorPrompt); return; }
      const promptButton = event.target.closest("[data-q]");
      if (promptButton) { closeModal(); setView("chat", { silent:true }); askQuestion(promptButton.dataset.q, promptButton.dataset.mode || "expert"); return; }
      const taskButton = event.target.closest("[data-task-template]");
      if (taskButton) { startTask(taskButton.dataset.taskTemplate); return; }
      const taskOpen = event.target.closest("[data-open-task]");
      if (taskOpen) { openExistingTask(taskOpen.dataset.openTask); return; }
      const alertButton = event.target.closest("[data-alert-id]");
      if (alertButton) { openNotifications(); return; }
      const categoryButton = event.target.closest("[data-knowledge-tag]");
      if (categoryButton) { setView("knowledge"); $("#knowledgeSearch").value = categoryButton.dataset.knowledgeTag; renderKnowledge(categoryButton.dataset.knowledgeTag); return; }
      const topicButton = event.target.closest("[data-topic-id]");
      if (topicButton) { restoreTopic(topicButton.dataset.topicId); return; }
      const conversationButton = event.target.closest("[data-conversation-id]");
      if (conversationButton) {
        const turns = state.topics
          .filter((item) => (item.sessionId || "legacy") === conversationButton.dataset.conversationId)
          .sort((left, right) => new Date(left.createdAt) - new Date(right.createdAt));
        if (turns.length) restoreTopic(turns[turns.length - 1].id);
        return;
      }
      const favoriteButton = event.target.closest("[data-favorite-id]");
      if (favoriteButton) {
        const item = state.favorites.find((entry) => entry.id === favoriteButton.dataset.favoriteId);
        if (item) { state.topics.unshift({ ...item, id:`fav-${Date.now()}` }); restoreTopic(state.topics[0].id); }
        return;
      }
      const avatarButton = event.target.closest("[data-avatar]");
      if (avatarButton) { selectAvatar(avatarButton.dataset.avatar); return; }
      const reportButton = event.target.closest("[data-report-download]");
      if (reportButton) { downloadReport(reportButton.dataset.reportDownload); return; }
      const connectorHealth = event.target.closest("[data-connector-health]");
      if (connectorHealth) { await checkConnectorHealth(connectorHealth.dataset.connectorHealth); return; }
      const connectorItem = event.target.closest("[data-connector-id]");
      if (connectorItem) { await openConnectorDetail(connectorItem.dataset.connectorId); return; }
      const sourceFilter = event.target.closest("[data-source-filter]");
      if (sourceFilter) { renderKnowledgeSources(sourceFilter.dataset.sourceFilter === "all"); return; }
      const catalogFilter = event.target.closest("[data-catalog-status]");
      if (catalogFilter) { state.knowledgeCatalogStatus = catalogFilter.dataset.catalogStatus || "all"; renderKnowledgeCatalogResults(); return; }
      const rangeButton = event.target.closest("[data-range]");
      if (rangeButton) { loadEnergy(rangeButton.dataset.range, rangeButton.closest("#analyticsRange") ? "analytics" : "rail"); return; }
      const taskAction = event.target.closest("[data-task-action]");
      if (taskAction) { taskAction.dataset.taskAction === "auto" ? autoRunTask() : advanceTask(); return; }
      const linkageRun = event.target.closest("[data-linkage-run]");
      if (linkageRun) { await runSystemLinkage(linkageRun.dataset.linkageRun); return; }
      const linkageStart = event.target.closest("[data-linkage-start]");
      if (linkageStart) { await startSystemLinkage(linkageStart.dataset.linkageStart); return; }
      const linkageOpen = event.target.closest("[data-linkage-open]");
      if (linkageOpen) { await openLinkedSystem(linkageOpen.dataset.linkageOpen); return; }
      const linkageRefresh = event.target.closest("[data-linkage-refresh]");
      if (linkageRefresh) { await loadSystemLinkage(); return; }
      const modalAction = event.target.closest("[data-modal-action]");
      if (modalAction) { await handleModalAction(modalAction.dataset.modalAction); return; }
      const actionButton = event.target.closest("[data-action]");
      if (actionButton) await handleAction(actionButton.dataset.action);
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") { closeModal(); closeDrawer(); $("#advancedPopover").hidden = true; $("#leftSidebar").classList.remove("open"); $("#rightRail").classList.remove("open"); }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setView("knowledge"); $("#knowledgeSearch").focus(); }
    });
  }

  function handleAction(action) {
    const actions = {
      home:() => setView("chat", { silent:true }),
      "new-chat":beginNewConversation,
      history:openHistory,
      commands:openCommands,
      favorites:openFavorites,
      theme:() => toggleTheme(),
      connectors:openConnectors,
      "intelligence-hub":openIntelligenceHub,
      "system-linkage":openSystemLinkage,
      "rag-evaluation":() => openIntelligenceHub("evaluation"),
      "hub-run-demo":runHubDemo,
      "hub-run-evaluation":runHubEvaluation,
      "hub-submit-feedback":submitHubFeedback,
      "knowledge-catalog":openKnowledgeCatalog,
      "authority-coverage":openAuthorityCoverage,
      "knowledge-sources":openKnowledgeSources,
      "knowledge-intake":openKnowledgeIntake,
      "toggle-agent-mode":() => toggleAgentMode(),
      "agent-demo":startAgentDemo,
      notifications:openNotifications,
      settings:openSettings,
      profile:openProfile,
      "system-status":openSystemStatus,
      "competitive-benchmark":openCompetitiveBenchmark,
      "site-admission":openSiteAdmission,
      "simulator-lineage":openSimulatorLineage,
      "runtime-status":openRuntimeStatus,
      "capability-chat":() => { $("#mode").value = "expert"; $("#modeShortLabel").textContent = "专业"; $("#question").focus(); },
      "generate-report":() => generateReport(state.currentIntent?.includes("energy") ? "energy" : "management_brief"),
      "favorite-current":favoriteCurrent,
      evidence:openEvidence,
      advanced:() => { $("#advancedPopover").hidden = !$("#advancedPopover").hidden; },
      attachment:() => $("#fileInput").click(),
      avatar:openAvatarPicker,
      "knowledge-map":showKnowledgeMap,
      "new-task":() => { setView("tasks"); toast("请选择任务模板", "小懿会先创建计划，再逐步执行。", "info"); },
      "toggle-sidebar":() => $("#leftSidebar").classList.toggle("open"),
      "toggle-rail":() => $("#rightRail").classList.toggle("open"),
      "close-modal":closeModal,
      "close-drawer":closeDrawer,
      "confirm-automation":requestAutomationConfirmation,
      "resume-automation":resumeAutomation,
      "stop-automation":() => stopAutomation(),
      "response-menu":() => openModal("回答操作", "对当前结果继续处理", `<div class="command-list"><button type="button" class="command-item" data-action="favorite-current"><strong>收藏回答</strong><span>保存问题、回答和证据到本机</span></button><button type="button" class="command-item" data-action="generate-report"><strong>生成报告</strong><span>输出可下载的 Markdown 与 JSON</span></button><button type="button" class="command-item" data-task-template="analyze-energy"><strong>转为智能任务</strong><span>逐步执行并保留审计轨迹</span></button></div>`, "", "response-menu")
    };
    return actions[action]?.();
  }

  async function handleModalAction(action) {
    if (action === "clear-history") {
      openModal("确认清空历史？", "将清除浏览器缓存和当前身份可访问的服务端会话记录", `<div class="drawer-note"><strong>将删除 ${state.topics.length} 条浏览器记录，并请求清除会话 ${escapeHtml(state.sessionId)}。</strong>收藏内容不会受影响。</div>`, `<button type="button" class="drawer-button secondary" data-action="close-modal">取消</button><button type="button" class="drawer-button warning" data-modal-action="clear-history-confirmed">确认清空</button>`, "history-confirm");
    }
    if (action === "clear-history-confirmed") {
      try { await api(`/api/conversations/${encodeURIComponent(state.sessionId)}`, {method:"DELETE"}); } catch { /* local cache still clears */ }
      state.topics = []; persist(STORAGE.topics, state.topics); updateCounts(); closeModal(); toast("对话历史已清空", "浏览器缓存与当前会话服务端记录已清除；收藏仍保留。", "success");
    }
    if (action === "save-settings") {
      toggleTheme($("#settingsTheme").value);
      $("#mode").value = $("#settingsMode").value;
      $("#modeShortLabel").textContent = modeShort($("#settingsMode").value);
      $("#topK").value = $("#settingsTopK").value;
      if ($("#settingsClearToken")?.checked) sessionStorage.removeItem("xiaoyi_access_token");
      else if ($("#settingsAccessToken")?.value.trim()) sessionStorage.setItem("xiaoyi_access_token", $("#settingsAccessToken").value.trim());
      closeModal();
    }
    if (action === "confirm-task") {
      if (state.activeTask) state.confirmedTaskIds.add(state.activeTask.id);
      closeModal(); openDrawer(); await advanceTask();
    }
    if (action === "confirm-automation") await confirmAutomation(true);
    if (action === "reject-automation") await confirmAutomation(false);
    if (action === "confirm-linked-systems-startup") await confirmLinkedSystemsStartup();
    if (action === "reject-linked-systems-startup") rejectLinkedSystemsStartup();
    if (action === "submit-knowledge-intake") await submitKnowledgeIntake();
    if (action === "start-rl-lab") startConfiguredRLLab();
  }

  function restorePreferences() {
    const theme = localStorage.getItem(STORAGE.theme) || "deep-sea";
    document.body.dataset.theme = theme;
    $(".theme-switch strong").textContent = theme === "deep-sea" ? "深海模式" : "极夜模式";
    const avatar = localStorage.getItem(STORAGE.avatar) || "navigator";
    document.body.classList.toggle("avatar-analyst", avatar === "analyst");
    const strict = localStorage.getItem(STORAGE.strictEvidence) !== "false";
    if ($("#strictEvidence")) $("#strictEvidence").checked = strict;
    toggleAgentMode(state.agentMode, false);
  }

  async function init() {
    initBilingualLayer(); restorePreferences(); updateGreeting(); bindEvents(); updateCounts();
    await Promise.allSettled([loadDashboard(), loadSimulatorSnapshot(), loadKnowledge(), loadTasksAndTemplates(), loadConnectorSummary(), loadServerConversation()]);
    connectSimulatorStream();
    void loadSystemLinkage({ render:false }).catch(() => {});
    showWelcome();
    if (state.conversationTurns.length) {
      const latest = state.conversationTurns[state.conversationTurns.length - 1];
      const stored = state.topics.find((item) => item.id === latest.id);
      if (stored) restoreTopic(stored.id);
    }
    setInterval(() => { if (!document.hidden) void loadDashboard(true); }, 15000);
  }

  init();
})();
