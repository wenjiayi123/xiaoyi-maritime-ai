"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const runtimeContract = require("../web/runtime_contract.js");

const source = fs.readFileSync(path.join(__dirname, "../web/app.js"), "utf8");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((accept, fail) => { resolve = accept; reject = fail; });
  return { promise, resolve, reject };
}

// Execute the production handlers with controlled I/O so response order and
// failures are deterministic. No second implementation of the handlers lives here.
function handlerSource(name) {
  const start = source.search(new RegExp(`^  (?:async )?function ${name}\\(`, "m"));
  assert.notEqual(start, -1, `missing production handler ${name}`);
  const end = source.indexOf("\n  }\n", start);
  assert.notEqual(end, -1, `missing handler boundary for ${name}`);
  return source.slice(start, end + "\n  }".length);
}

function energy(range, value = 1) {
  return {
    range,
    summary: { total_energy_mwh: value },
    series: [{ energy_mwh: value }],
    source_metadata: { source_type: "public_data_calibrated_simulation" },
  };
}

function harness(names, overrides = {}) {
  const notices = [];
  const draws = [];
  const controls = Array.from({ length: 2 }, () => ["today", "7d", "30d"].map((range) => {
    const button = { dataset: { range }, active: range === "today" };
    button.classList = { toggle: (_, active) => { button.active = active; } };
    return button;
  })).flat();
  const context = vm.createContext({
    state: {
      energy: energy("today"), energyRange: "today", energyRequest: 0, dashboardRequest: 0,
      taskAdvancing: new Set(), confirmedTaskIds: new Set(), tasks: [], drawerMode: "task",
      rlAdvisorMessages: [], sessionId: "runtime-test", topics: [],
    },
    runtimeContract,
    fallbackDashboard: { energy: energy("today", 0) },
    api: async () => { throw new Error("unexpected API request"); },
    $: () => ({ value: "", classList: { remove: () => {} } }),
    $$: () => controls,
    CSS: { escape: String },
    STORAGE: { topics: "topics", turns: "turns", favorites: "favorites", sessionId: "sessionId" },
    escapeHtml: String,
    toast: (...args) => notices.push(args),
    buildChart: (data) => draws.push(data),
    withoutUnverifiedOperationalValues: (data) => data,
    syncRuntimeBadge: () => {}, renderOverview: () => {}, renderAlerts: () => {},
    renderAnalytics: () => {}, applyEnergySummary: () => {}, renderDecisions: () => {},
    renderQuickKnowledge: () => {}, latestCompletedRun: (runs) => runs[0],
    renderRLAdvisorFeed: () => {}, guidedFocus: async () => {},
    sleep: async () => {},
    renderActiveTask: () => {}, renderTaskList: () => {}, updateCounts: () => {},
    setHeroState: () => {}, openModal: () => {}, closeModal: () => {}, persist: () => {},
    renderConversationTranscript: () => {}, showWelcome: () => {},
    createSessionId: () => "new-session",
    localStorage: { getItem: () => null, setItem: () => {} },
    ...overrides,
  });
  vm.runInContext(names.map(handlerSource).join("\n"), context, { filename: "app-handlers.js" });
  return { context, notices, draws, controls };
}

test("energy range: newest click wins even when an older response arrives last", async () => {
  const week = deferred();
  const month = deferred();
  const { context, controls, draws } = harness(["loadEnergy"], {
    api: (url) => url.endsWith("7d") ? week.promise : month.promise,
  });
  const older = context.loadEnergy("7d");
  const newer = context.loadEnergy("30d", "analytics");
  month.resolve(energy("30d", 300));
  assert.equal(await newer, true);
  week.resolve(energy("7d", 70));
  assert.equal(await older, false);
  assert.equal(context.state.energy.range, "30d");
  assert.equal(context.state.energy.summary.total_energy_mwh, 300);
  assert.equal(draws.length, 1);
  assert.equal(controls.filter((button) => button.active).length, 2);
  assert.ok(controls.filter((button) => button.active).every((button) => button.dataset.range === "30d"));
});

test("energy range: a stale failure cannot roll back the current range or display an error", async () => {
  const older = deferred();
  const { context, notices } = harness(["loadEnergy"], {
    api: (url) => url.endsWith("7d") ? older.promise : Promise.resolve(energy("30d")),
  });
  const oldRequest = context.loadEnergy("7d");
  await context.loadEnergy("30d");
  older.reject(new Error("old request timed out"));
  await oldRequest;
  assert.equal(context.state.energyRange, "30d");
  assert.equal(notices.length, 0);
});

test("dashboard refresh preserves the selected range and fetches that range again", async () => {
  const refresh = deferred();
  const requested = [];
  const { context, draws } = harness(["loadDashboard", "loadEnergy"], {
    api: (url) => {
      requested.push(url);
      return url === "/api/dashboard"
        ? Promise.resolve({ energy: energy("today", 1), overview: {}, alerts: {} })
        : refresh.promise;
    },
  });
  context.state.energy = energy("7d", 70);
  context.state.energyRange = "7d";
  const running = context.loadDashboard(true);
  await new Promise(setImmediate);
  assert.equal(context.state.energy.range, "7d");
  assert.deepEqual(requested, ["/api/dashboard", "/api/energy?range=7d"]);
  refresh.resolve(energy("7d", 71));
  await running;
  assert.equal(context.state.energy.summary.total_energy_mwh, 71);
  assert.ok(draws.every((data) => data.range === "7d"));
});

test("a dashboard request started before a range click cannot replace that click", async () => {
  const dashboard = deferred();
  const selected = deferred();
  const requested = [];
  const { context } = harness(["loadDashboard", "loadEnergy"], {
    api: (url) => { requested.push(url); return url === "/api/dashboard" ? dashboard.promise : selected.promise; },
  });
  const background = context.loadDashboard(true);
  const click = context.loadEnergy("30d");
  selected.resolve(energy("30d", 300));
  await click;
  dashboard.resolve({ energy: energy("today", 1), overview: {}, alerts: {} });
  await background;
  assert.equal(context.state.energy.range, "30d");
  assert.deepEqual(requested, ["/api/dashboard", "/api/energy?range=30d"]);
});

test("advisor overlapping answers and errors stay paired with their own questions", async () => {
  const first = deferred();
  const second = deferred();
  let calls = 0;
  const { context } = harness(["askRLAdvisor"], {
    api: () => (++calls === 1 ? first.promise : second.promise),
  });
  const requestOne = context.askRLAdvisor("第一问");
  const requestTwo = context.askRLAdvisor("第二问");
  second.resolve({ answer: "第二问的结果", evidence: ["evidence-2"] });
  await requestTwo;
  first.reject(new Error("第一问暂时不可用"));
  await requestOne;
  const messages = context.state.rlAdvisorMessages;
  assert.equal(messages.length, 4);
  assert.equal(messages[0].text, "第一问");
  assert.match(messages[1].text, /第一问暂时不可用/);
  assert.equal(messages[2].text, "第二问");
  assert.equal(messages[3].text, "第二问的结果");
  assert.equal(messages[3].evidence[0], "evidence-2");
  assert.ok(messages.every((message) => !message.loading));
});

function runningTask(id) {
  return {
    id, status: "running", progress_percent: 0, requires_human_confirmation: false,
    steps: [{ id: `${id}-step-1`, order: 1, status: "running" }],
  };
}

test("task next: repeated clicks issue one request and unlock after completion", async () => {
  const response = deferred();
  let calls = 0;
  const { context } = harness(["advanceTask"], { api: () => { calls++; return response.promise; } });
  context.state.activeTask = runningTask("task-a");
  const first = context.advanceTask();
  assert.equal(await context.advanceTask(), false);
  await Promise.resolve();
  assert.equal(calls, 1);
  response.resolve({ task: { ...runningTask("task-a"), progress_percent: 20 }, visual_cue: "step-complete" });
  assert.equal(await first, true);
  assert.equal(context.state.activeTask.progress_percent, 20);
  assert.equal(context.state.taskAdvancing.size, 0);
});

test("task next: switching tasks during focus prevents sending the old task request", async () => {
  const focus = deferred();
  let calls = 0;
  const { context } = harness(["advanceTask"], {
    guidedFocus: () => focus.promise,
    api: async () => { calls++; },
  });
  context.state.activeTask = runningTask("task-a");
  const first = context.advanceTask();
  context.state.activeTask = runningTask("task-b");
  focus.resolve();
  assert.equal(await first, false);
  assert.equal(calls, 0);
  assert.equal(context.state.activeTask.id, "task-b");
  assert.equal(context.state.taskAdvancing.size, 0);
});

test("task next: an old in-flight response updates its record without replacing the open task", async () => {
  const response = deferred();
  let activeRenders = 0;
  const { context } = harness(["advanceTask"], {
    api: () => response.promise,
    renderActiveTask: () => { activeRenders++; },
  });
  context.state.activeTask = runningTask("task-a");
  const first = context.advanceTask();
  await new Promise(setImmediate);
  context.state.activeTask = runningTask("task-b");
  response.resolve({ task: { ...runningTask("task-a"), progress_percent: 20 }, visual_cue: "step-complete" });
  await first;
  assert.equal(context.state.activeTask.id, "task-b");
  assert.equal(context.state.tasks[0].id, "task-a");
  assert.equal(context.state.tasks[0].progress_percent, 20);
  assert.equal(activeRenders, 0);
});

test("task next: failure preserves progress and permits a retry", async () => {
  const task = runningTask("task-a");
  let calls = 0;
  const { context, notices } = harness(["advanceTask"], {
    api: async () => {
      if (++calls === 1) throw new Error("source unavailable");
      return { task: { ...task, progress_percent: 20 }, visual_cue: "step-complete" };
    },
  });
  context.state.activeTask = task;
  assert.equal(await context.advanceTask(), false);
  assert.equal(context.state.activeTask, task);
  assert.equal(context.state.taskAdvancing.size, 0);
  assert.equal(notices[0][2], "warning");
  assert.equal(await context.advanceTask(), true);
  assert.equal(context.state.activeTask.progress_percent, 20);
});

test("task auto-run never transfers execution to a newly opened task", async () => {
  const response = deferred();
  const requested = [];
  const { context } = harness(["advanceTask", "autoRunTask"], {
    api: (url) => {
      requested.push(url);
      return url.includes("task-a/") ? response.promise : Promise.reject(new Error("unexpected other task"));
    },
  });
  context.state.activeTask = runningTask("task-a");
  const automatic = context.autoRunTask();
  await new Promise(setImmediate);
  context.state.activeTask = runningTask("task-b");
  response.resolve({ task: { ...runningTask("task-a"), progress_percent: 20 }, visual_cue: "step-complete" });
  await automatic;
  assert.deepEqual(requested, ["/api/tasks/task-a/next"]);
  assert.equal(context.state.activeTask.id, "task-b");
  assert.equal(context.state.activeTask.progress_percent, 0);
  assert.equal(context.state.autoRunning, false);
});

test("clear history: server failure preserves local history and leaves the dialog open", async () => {
  const topics = [{ question: "应保留的问题" }];
  const persisted = [];
  let closed = 0;
  const { context, notices } = harness(["handleModalAction"], {
    api: async () => { throw new Error("server unavailable"); },
    persist: (...args) => persisted.push(args),
    closeModal: () => { closed++; },
  });
  context.state.topics = topics;
  context.state.conversationTurns = topics;
  await context.handleModalAction("clear-history-confirmed");
  assert.equal(context.state.topics, topics);
  assert.equal(context.state.conversationTurns, topics);
  assert.equal(persisted.length, 0);
  assert.equal(closed, 0);
  assert.match(notices[0][1], /已保留历史/);
});

test("clear history: local deletion occurs only after server acknowledgement", async () => {
  const response = deferred();
  const persisted = [];
  const requested = [];
  const { context } = harness(["handleModalAction"], {
    api: (url, options) => { requested.push([url, options.method]); return response.promise; },
    persist: (...args) => persisted.push(args),
  });
  context.state.topics = [{ question: "待清空的问题" }];
  context.state.conversationTurns = context.state.topics;
  const clearing = context.handleModalAction("clear-history-confirmed");
  assert.equal(context.state.topics.length, 1);
  assert.equal(persisted.length, 0);
  response.resolve({ status: "cleared" });
  await clearing;
  assert.equal(context.state.topics.length, 0);
  assert.equal(context.state.conversationTurns.length, 0);
  assert.equal(context.state.sessionId, "new-session");
  assert.equal(persisted.length, 2);
  assert.deepEqual(persisted.map(([key]) => key), ["topics", "turns"]);
  assert.deepEqual(requested, [["/api/conversations/runtime-test", "DELETE"]]);
});

function preferenceEnvironment() {
  const elements = new Map();
  const values = new Map();
  const $ = (selector) => {
    if (!elements.has(selector)) elements.set(selector, { value: "", textContent: "", checked: false });
    return elements.get(selector);
  };
  return {
    $, values,
    localStorage: { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)) },
    sessionStorage: { removeItem: () => {}, setItem: () => {} },
    document: { body: { dataset: {}, classList: { toggle: () => {} } } },
    modeShort: (mode) => mode,
    toggleTheme: () => {}, toggleAgentMode: () => {},
  };
}

test("saved answer mode and evidence count survive preference restoration and new conversations", async () => {
  const environment = preferenceEnvironment();
  const { context } = harness(["handleModalAction", "restorePreferences", "beginNewConversation"], {
    ...environment,
    createSessionId: () => "new-session",
    showWelcome: () => { environment.$("#mode").value = "expert"; },
  });
  environment.$("#settingsMode").value = "brief";
  environment.$("#settingsTopK").value = "7";
  await context.handleModalAction("save-settings");
  environment.$("#mode").value = "expert";
  environment.$("#topK").value = "5";
  context.restorePreferences();
  assert.equal(environment.$("#mode").value, "brief");
  assert.equal(environment.$("#modeShortLabel").textContent, "brief");
  assert.equal(environment.$("#topK").value, "7");
  context.beginNewConversation();
  assert.equal(context.state.sessionId, "new-session");
  assert.equal(environment.$("#mode").value, "brief");
});

test("invalid stored answer preferences leave valid form defaults intact", () => {
  const environment = preferenceEnvironment();
  environment.values.set("xiaoyi_default_mode", "unsupported-mode");
  environment.values.set("xiaoyi_default_top_k", "999");
  environment.$("#mode").value = "expert";
  environment.$("#topK").value = "5";
  const { context } = harness(["restorePreferences"], environment);
  context.restorePreferences();
  assert.equal(environment.$("#mode").value, "expert");
  assert.equal(environment.$("#topK").value, "5");
});

test("a favorite retains grounding, verification and follow-up questions after history is removed", () => {
  const environment = preferenceEnvironment();
  let renderedGrounding;
  let renderedQuestions;
  const { context } = harness(["favoriteCurrent", "restoreTopic"], {
    ...environment,
    topicTitle: String, setView: () => {}, stopGeneration: () => {},
    renderStructuredAnswer: () => {}, intentTitle: String, modeLabel: String,
    updateGroundingState: (data) => { renderedGrounding = data; },
    renderNextQuestions: (questions) => { renderedQuestions = questions; },
  });
  const topic = {
    id: "answer-original", sessionId: "runtime-test", question: "核验岸电来源", answer: "有据回答 [1]",
    evidence: [{ id: "evidence-1", source_quality: "official_verified" }],
    answer_verification: { status: "passed", evidence_alignment: 1 },
    grounded: true, source_quality: "official_verified", coverage: 0.95,
    strict_evidence: true, next_questions: ["适用范围是什么？"],
    mode: "expert", intent: "knowledge", confidence: "high", createdAt: "2026-09-12T12:00:00Z",
  };
  Object.assign(context.state, {
    topics: [topic], favorites: [], currentQuestion: topic.question, currentAnswer: topic.answer,
    currentEvidence: topic.evidence, currentMode: topic.mode, currentIntent: topic.intent,
    currentConfidence: topic.confidence, currentVerification: topic.answer_verification,
  });
  context.favoriteCurrent();
  const favorite = context.state.favorites[0];
  assert.equal(favorite.answer_verification, topic.answer_verification);
  assert.equal(favorite.grounded, true);
  assert.equal(favorite.coverage, 0.95);
  context.state.topics = [{ ...favorite, id: "restored-favorite" }];
  context.state.currentEvidence = [];
  context.state.currentVerification = null;
  context.restoreTopic("restored-favorite");
  assert.equal(context.state.currentEvidence, topic.evidence);
  assert.equal(context.state.currentVerification.status, "passed");
  assert.equal(renderedGrounding.source_quality, "official_verified");
  assert.equal(renderedQuestions[0], "适用范围是什么？");
});

test("clearing history invalidates a delayed restore response and gives the next question a fresh session", async () => {
  const oldHistory = deferred();
  const persistedSessions = [];
  const { context } = harness(["loadServerConversation", "handleModalAction"], {
    api: (_, options) => options?.method === "DELETE" ? Promise.resolve({ status: "cleared" }) : oldHistory.promise,
    localStorage: { setItem: (key, value) => persistedSessions.push([key, value]) },
    topicTitle: String,
  });
  const loading = context.loadServerConversation();
  await context.handleModalAction("clear-history-confirmed");
  oldHistory.resolve({ items: [{ id: "old-turn", question: "已删除的上下文", response: { answer: "旧回答" } }] });
  await loading;
  assert.equal(context.state.sessionId, "new-session");
  assert.equal(context.state.topics.length, 0);
  assert.equal(context.state.conversationTurns.length, 0);
  assert.deepEqual(persistedSessions, [["sessionId", "new-session"]]);
});

test("explicit RL training enables the action planner and retains zero seed", () => {
  const environment = preferenceEnvironment();
  for (const [selector, value] of [["#rlDataset", "uci_appliances_energy"], ["#rlEpisodes", "80"], ["#rlHorizon", "36"], ["#rlSeed", "0"]]) {
    Object.assign(environment.$(selector), { value, reportValidity: () => true });
  }
  let closed = 0;
  const questions = [];
  const plannerModes = [];
  const { context } = harness(["startConfiguredRLLab"], {
    ...environment,
    $$: () => [{ value: "q_learning" }, { value: "pid" }],
    closeModal: () => { closed++; }, setView: () => {},
    toggleAgentMode: (enabled) => plannerModes.push(enabled),
    askQuestion: (...args) => { questions.push(args); },
  });
  context.state.agentMode = false;
  context.startConfiguredRLLab();
  assert.equal(context.state.pendingRLLabConfig.seed, 0);
  assert.equal(context.state.pendingRLLabConfig.episodes, 80);
  assert.deepEqual(plannerModes, [true]);
  assert.equal(closed, 1);
  assert.equal(questions.length, 1);
  assert.match(questions[0][0], /启动RL训练实验/);
});

test("invalid RL form input stays open and starts no work", () => {
  const environment = preferenceEnvironment();
  for (const selector of ["#rlEpisodes", "#rlHorizon", "#rlSeed"]) {
    Object.assign(environment.$(selector), { value: "80", reportValidity: () => selector !== "#rlSeed" });
  }
  let closed = 0;
  let questions = 0;
  const { context } = harness(["startConfiguredRLLab"], {
    ...environment,
    closeModal: () => { closed++; },
    askQuestion: () => { questions++; },
  });
  context.startConfiguredRLLab();
  assert.equal(closed, 0);
  assert.equal(questions, 0);
  assert.equal(context.state.pendingRLLabConfig, undefined);
});

test("the RL scenario request carries the configured zero seed to the backend", async () => {
  const requests = [];
  const { context } = harness(["executeSemanticAction"], {
    api: async (url, options) => { requests.push([url, JSON.parse(options.body)]); return { dataset: { row_count: 710 } }; },
    renderAutomationPlan: () => {},
  });
  context.state.automationContext = {};
  context.state.pendingRLLabConfig = { seed: 0, episodes: 80, horizonSteps: 36, algorithms: ["q_learning"] };
  await context.executeSemanticAction({ kind: "build_rl_scenario" });
  assert.equal(requests[0][0], "/api/rl-mission/scenario");
  assert.equal(requests[0][1].seed, 0);
  assert.equal(requests[0][1].episodes, 80);
});

test("server-restored answers retain the same decision and evidence gates as local history", async () => {
  const response = {
    answer: "两份证据冲突，需要复核。", grounded: false,
    decision_readiness: { status: "evidence_conflict" },
    evidence_health: { status: "conflict", blocking_reasons: ["contradictory_sources"] },
    answer_verification: { status: "needs_review" },
  };
  const { context } = harness(["loadServerConversation"], {
    topicTitle: String,
    api: async () => ({ items: [{ id: "answer-conflict", question: "核对冲突条款", response, created_at: "2026-09-12T12:00:00Z" }] }),
  });
  await context.loadServerConversation();
  const restored = context.state.topics[0];
  assert.equal(restored.decision_readiness, response.decision_readiness);
  assert.equal(restored.evidence_health, response.evidence_health);
  assert.equal(restored.answer_verification, response.answer_verification);
});

test("training completion states the selected RL count and excludes non-learning baselines", async () => {
  const { context } = harness(["executeSemanticAction"]);
  context.state.automationContext = { rlMission: {
    runId: "run-single-rl", algorithms: ["q_learning", "pid", "sop_rule"],
    training: { status: "trained", completed_training_episodes: 80, config: { algorithms: ["q_learning", "pid", "sop_rule"] }, training: { rendering_performed: false } },
  } };
  const message = await context.executeSemanticAction({ kind: "replay_rl_training" });
  assert.match(message, /1种RL算法共执行 80 个episode/);
  assert.doesNotMatch(message, /4种RL算法/);
});

test("training result names its environment and actual candidate count", () => {
  let reply;
  const { context } = harness(["deliverRLMissionResult"], {
    formatNumber: String,
    commitAutomationChat: (data) => { reply = data.answer; },
  });
  context.state.automationPlan = { command: "测试所选候选" };
  context.state.automationContext = { rlMission: {
    training: { completed_training_episodes: 80, dataset: { environment_type: "port_operations" } },
    simulation: { race: [{ algorithm_id: "q_learning", label: "Q-learning" }, { algorithm_id: "pid", label: "PID" }] },
  } };
  const receipt = context.deliverRLMissionResult();
  assert.match(reply, /强化学习港口作业协同实验/);
  assert.match(reply, /本次 2 种候选与基线结果/);
  assert.match(reply, /训练：Q-learning共完成 80/);
  assert.match(receipt, /2/);
  context.state.automationContext.rlMission.training.dataset.environment_type = "energy_storage";
  context.deliverRLMissionResult();
  assert.match(reply, /强化学习能源调度实验/);
});

test("returning to the training center reloads completed runs instead of reusing its cached list", async () => {
  const requests = [];
  const rendered = [];
  const { context } = harness(["setView", "loadRLCenter"], {
    api: async (url) => {
      requests.push(url);
      return url.includes("/runs?") ? { items: [{ run_id: "newly-completed-run", status: "evaluated" }] } : {};
    },
    renderRLCenter: () => { rendered.push(context.state.rlCenter.runs.items[0].run_id); },
  });
  context.state.rlCenter = { runs: { items: [{ run_id: "cached-old-run" }] } };
  context.setView("chat", { silent: true });
  context.setView("rl");
  await new Promise(setImmediate);
  assert.equal(requests.length, 3);
  assert.ok(requests.includes("/api/rl-lab/runs?limit=10"));
  assert.equal(context.state.rlCenter.runs.items[0].run_id, "newly-completed-run");
  assert.deepEqual(rendered, ["newly-completed-run"]);
});

test("task step copy reflects actual status for both stored legacy and new descriptions", () => {
  const environment = preferenceEnvironment();
  const { context } = harness(["renderActiveTask"], { ...environment, icon: String });
  context.state.activeTask = {
    ...runningTask("task-status"), progress_percent: 25,
    steps: [
      { id: "completed", order: 1, title: "完成步骤", status: "completed", description: "小懿正在执行：读取指标", result: "读取成功" },
      { id: "current", order: 2, title: "当前步骤", status: "running", description: "步骤内容：核对来源" },
      { id: "pending", order: 3, title: "后续步骤", status: "pending", description: "小懿正在执行：生成报告" },
      { id: "skipped", order: 4, title: "跳过步骤", status: "skipped", description: "步骤内容：导出报告" },
    ],
  };
  context.renderActiveTask();
  const html = environment.$("#drawerContent").innerHTML;
  assert.match(html, /<span>已完成：读取指标<\/span>/);
  assert.match(html, /<span>当前待执行：核对来源<\/span>/);
  assert.match(html, /<span>等待执行：生成报告<\/span>/);
  assert.match(html, /<span>已跳过：导出报告<\/span>/);
  assert.doesNotMatch(html, /小懿正在执行|步骤内容/);
});

test("range changes keep all four energy KPIs aligned across summary, analytics and evidence detail", async () => {
  const environment = preferenceEnvironment();
  const snapshots = {
    "7d": { total_energy_mwh: 70, carbon_emissions_tco2e: 21, carbon_intensity_kgco2e_per_teu: 4.5, shore_power_utilization_percent: 60 },
    "30d": { total_energy_mwh: 300, carbon_emissions_tco2e: 90, carbon_intensity_kgco2e_per_teu: 4.2, shore_power_utilization_percent: 66 },
  };
  const { context } = harness(["loadEnergy", "renderAnalytics", "applyEnergySummary"], {
    ...environment, formatNumber: String, formatDateTime: String,
    api: async (url) => {
      const range = url.split("=")[1];
      return { ...energy(range), summary: snapshots[range], source_metadata: range === "today" ? {} : energy(range).source_metadata };
    },
  });
  for (const range of ["7d", "30d"]) {
    await context.loadEnergy(range);
    const expected = Object.values(snapshots[range]).map(String);
    const analytics = [...environment.$("#analyticsKpis").innerHTML.matchAll(/<strong>([^<]+)<\/strong>/g)].map((match) => match[1]);
    const evidence = [...environment.$("#energyEvidenceMetrics").innerHTML.matchAll(/<b>([^<]+)<\/b>/g)].map((match) => match[1].split(" ")[0].replace("%", ""));
    const summary = [...environment.$("#responseKpis").innerHTML.matchAll(/<strong>([^<]+)<small>/g)].map((match) => match[1].trim());
    assert.deepEqual(analytics, expected);
    assert.deepEqual(evidence, expected);
    assert.deepEqual(summary, expected);
  }
  await context.loadEnergy("today");
  assert.equal((environment.$("#energyEvidenceMetrics").innerHTML.match(/等待接入港口/g) || []).length, 4);
  assert.equal((environment.$("#analyticsKpis").innerHTML.match(/等待接入港口/g) || []).length, 4);
  assert.equal((environment.$("#responseKpis").innerHTML.match(/等待接入港口/g) || []).length, 4);
});

test("a submitted simulator rollback with no state readback is reported as awaiting verification", async () => {
  const { context, notices } = harness(["rollbackSimulatorDecision"], {
    api: async () => ({ physical_dispatch_performed: false }),
    simulatorMutationOptions: (payload) => ({ method: "POST", body: JSON.stringify(payload) }),
    loadSimulatorSnapshot: async () => null,
  });
  await context.rollbackSimulatorDecision("decision-a");
  assert.equal(notices.length, 1);
  assert.equal(notices[0][0], "操作已提交，画面待核验");
  assert.equal(notices[0][2], "warning");
});
