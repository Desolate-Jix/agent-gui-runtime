const $ = (id) => document.getElementById(id);

let lastResponse = {};
let lastTracePath = "";
let lastObserveTracePath = "";
let currentImagePath = "";
let currentImageUrl = "";
let modelProfiles = [];
let windowCandidates = [];
let pendingRequests = new Set();
let currentLanguage = localStorage.getItem("agentPanelLanguage") || "zh-CN";
let currentAgentMode = localStorage.getItem("agentPanelMode") || "learn";
let currentLearnDepth = localStorage.getItem("agentLearnDepth") || "fast";
const BROWSER_APP_IDS = new Set(["browser", "edge", "msedge", "chrome", "firefox"]);

/* 鈹€鈹€ Navigation path graph state 鈹€鈹€ */
// Each page node:
//   { id, label, summary, stateGuess, imagePath, timestamp,
//     controls: [{ label, bbox, clickPoint, type, description, status, clickGoal, clickScreenshot, navigatedToPageId, possibleNav, candidateId }] }
let navPathNodes = [];
let navPathEdges = [];       // { from, to, goal, action }
let currentNavNodeId = null;
let pendingTransition = null; // { from, goal, action } waiting for next observe
let navPathCounter = 0;
let navPathAppName = "";
let navPathDirty = false;    // true when unsaved changes exist
let liveSessionSnapshot = null;  // saved live session when viewing history

const stageMeta = {
  open_bind: ["stage_open_bind_title", "stage_open_bind_subtitle"],
  capture: ["stage_capture_title", "stage_capture_subtitle"],
  observe: ["stage_observe_title", "stage_observe_subtitle"],
  locate: ["stage_locate_title", "stage_locate_subtitle"],
  execute: ["stage_execute_title", "stage_execute_subtitle"],
  model_test: ["stage_model_test_title", "stage_model_test_subtitle"],
  input: ["stage_input_title", "stage_input_subtitle"],
  trace: ["stage_trace_title", "stage_trace_subtitle"],
};

const translations = {
  "zh-CN": {
    language: "语言",
    nav_open_bind: "打开 / 绑定",
    nav_capture: "截图",
    nav_observe: "整屏理解",
    nav_locate: "精准定位",
    nav_execute: "点击闸门",
    nav_input: "输入",
    nav_trace: "Trace",
    nav_models: "模型测试",
    learn_mode: "学习模式",
    execute_mode: "执行模式",
    learn_fast: "快速学习",
    learn_deep: "深度学习",
    write_path_graph: "PathGraph",
    write_element_memory: "ElementMemory",
    write_trace: "Trace",
    health: "健康检查",
    model_test_title: "模型测试",
    model_test_subtitle: "直接向视觉模型发送提示词和图片，查看原始返回",
    model_test_prompt: "提示词",
    model_test_send: "发送",
    model_test_use_image: "附带当前图片",
    model_test_image_path: "图片路径",
    model_stage: "模型阶段",
    profile: "Profile",
    open_bind: "打开 / 绑定",
    app_id: "App ID",
    url: "URL",
    window_candidates: "打开的窗口",
    process_name: "进程名",
    title_contains: "标题包含",
    list_apps: "列出应用",
    open_app: "打开应用",
    list_windows: "列出窗口",
    bind_window: "绑定窗口",
    screenshot_saved_image: "截图和本地图片",
    image_path: "图片路径",
    save_screenshot: "保存截图",
    capture_bound_window: "截取绑定窗口",
    use_image_path: "使用图片路径",
    drop_image: "拖入或选择截图图片",
    observe_screen: "整屏理解",
    analyze_api: "API 直接分析",
    app_name: "应用名",
    state_hint: "状态提示",
    model_profile: "模型 Profile",
    provider_mode: "Provider mode",
    capture_live: "实时截图",
    observe_prompt: "整屏理解提示词规则",
    locate_target: "精准定位",
    goal: "目标",
    top_k: "Top K",
    locate_prompt: "精准定位提示词规则",
    render_overlay: "渲染覆盖图",
    type_text: "输入文本",
    text: "文本",
    click_before_typing: "输入前点击",
    clear_existing: "清空已有内容",
    submit_enter: "回车提交",
    dry_run: "Dry run",
    execute_recognition_plan: "执行识别计划",
    click_preview: "点击预览",
    execute_click: "执行点击",
    plan_click_preview: "识别点击预览",
    plan_execute_click: "识别执行点击",
    point_click_preview: "坐标点击预览",
    point_execute_click: "坐标执行点击",
    approved_plan_id: "批准计划 ID",
    learned_instruction_id: "学习指令 ID",
    instruction_learning: "指令学习",
    dry_run_plan: "Dry-run 计划",
    execute_gated_click: "执行闸门点击",
    manual_box: "候选框复核",
    manual_box_button: "生成候选框图",
    label: "标签",
    preview_box: "预览框",
    confirmed_point_dry_run: "确认点 Dry-run",
    execute_confirmed_point: "执行确认点",
    screenshot_preview: "截图预览",
    action_path_graph: "流程图",
    path_graph_title: "导航路径图",
    nav_path_detail: "页面详情",
    path_empty_hint: "整屏理解后开始生成导航路径",
    path_detail_empty: "点击导航路径节点查看页面概述",
    pending_next_observe: "等待下次整屏理解确认跳转",
    path_state_hint: "状态提示",
    path_from: "来源",
    path_action: "操作",
    path_screenshot: "截图",
    path_time: "时间",
    save_path: "保存路径",
    save_path_as: "路径另存为",
    save_file_name: "文件名",
    save: "保存",
    cancel: "取消",
    api_response: "API 响应",
    copy: "复制",
    stage_open_bind_title: "打开 / 绑定",
    stage_open_bind_subtitle: "打开软件、刷新窗口并绑定目标窗口",
    stage_capture_title: "截图",
    stage_capture_subtitle: "截取绑定窗口或载入本地截图",
    stage_observe_title: "整屏理解",
    stage_observe_subtitle: "输出界面用途、可交互元素和下一步状态提示",
    stage_locate_title: "精准定位",
    stage_locate_subtitle: "使用 OCR 与视觉模型定位目标坐标并复核候选框",
    stage_execute_title: "执行",
    stage_execute_subtitle: "支持识别计划点击和坐标点击：先预览，再执行真实点击",
    stage_input_title: "输入",
    stage_input_subtitle: "测试文本输入，不显示导航路径和页面详情",
    stage_trace_title: "Trace 解析",
    stage_trace_subtitle: "按阶段读取本地 trace，并查看每阶段原始内容",
    stage_model_test_title: "模型测试",
    stage_model_test_subtitle: "带图片和提示词直接测试视觉模型返回",
    trace_file: "Trace 文件",
    start_model: "启动模型",
    stop_model: "停止模型",
    test_model: "检查模型服务",
    apply_model_profile: "应用配置",
    running: "运行中",
    ok: "正常",
    failed: "失败",
    idle: "空闲",
    runtime_ready: "runtime 就绪",
    runtime_unavailable: "runtime 不可用",
    no_image: "无图片",
    no_response: "无响应",
    no_windows: "未发现窗口",
    no_models: "未发现模型 profile",
    request_already_running: "该请求正在运行"
  },
  "en-US": {
    language: "Language",
    nav_open_bind: "Open / Bind",
    nav_capture: "Capture",
    nav_observe: "Observe",
    nav_locate: "Locate",
    nav_execute: "Click Gate",
    nav_input: "Input",
    nav_trace: "Trace",
    nav_models: "Models",
    learn_mode: "Learn Mode",
    execute_mode: "Execute Mode",
    learn_fast: "Learn Fast",
    learn_deep: "Learn Deep",
    write_path_graph: "PathGraph",
    write_element_memory: "ElementMemory",
    write_trace: "Trace",
    health: "Health",
    model_test_title: "Model Test",
    model_test_subtitle: "Send a prompt and optional image directly to a vision model.",
    model_test_prompt: "Prompt",
    model_test_send: "Send",
    model_test_use_image: "Attach current image",
    model_test_image_path: "Image path",
    model_stage: "Model stage",
    profile: "Profile",
    open_bind: "Open / Bind",
    app_id: "App ID",
    url: "URL",
    window_candidates: "Open windows",
    process_name: "Process name",
    title_contains: "Title contains",
    list_apps: "List apps",
    open_app: "Open app",
    list_windows: "List windows",
    bind_window: "Bind window",
    screenshot_saved_image: "Screenshot and Saved Image",
    image_path: "Image path",
    save_screenshot: "Save screenshot",
    capture_bound_window: "Capture bound window",
    use_image_path: "Use image path",
    drop_image: "Drop or choose a screenshot image",
    observe_screen: "Observe screen",
    analyze_api: "API direct analyze",
    app_name: "App name",
    state_hint: "State hint",
    model_profile: "Model profile",
    provider_mode: "Provider mode",
    capture_live: "Capture live",
    observe_prompt: "Observe prompt rules",
    locate_target: "Locate target",
    goal: "Goal",
    top_k: "Top K",
    locate_prompt: "Locate prompt rules",
    render_overlay: "Render overlay",
    type_text: "Type text",
    text: "Text",
    click_before_typing: "Click before typing",
    clear_existing: "Clear existing",
    submit_enter: "Submit Enter",
    dry_run: "Dry run",
    execute_recognition_plan: "Execute Recognition Plan",
    click_preview: "Click Preview",
    execute_click: "Execute Click",
    plan_click_preview: "Plan Click Preview",
    plan_execute_click: "Plan Execute Click",
    point_click_preview: "Point Click Preview",
    point_execute_click: "Point Execute Click",
    approved_plan_id: "Approved plan ID",
    learned_instruction_id: "Learned instruction ID",
    instruction_learning: "Instruction learning",
    dry_run_plan: "Dry-run plan",
    execute_gated_click: "Execute gated click",
    manual_box: "Candidate box review",
    manual_box_button: "Generate candidate box",
    label: "Label",
    preview_box: "Preview box",
    confirmed_point_dry_run: "Confirmed point dry-run",
    execute_confirmed_point: "Execute confirmed point",
    screenshot_preview: "Screenshot Preview",
    action_path_graph: "Flow Diagram",
    path_graph_title: "Navigation Path",
    nav_path_detail: "Page Detail",
    path_empty_hint: "Observe a screen to start building the navigation path",
    path_detail_empty: "Click a page node to view its observe summary",
    pending_next_observe: "Waiting for next observe to confirm navigation",
    path_state_hint: "State hint",
    path_from: "From",
    path_action: "Action",
    path_screenshot: "Screenshot",
    path_time: "Time",
    save_path: "Save Path",
    save_path_as: "Save Path As",
    save_file_name: "File name",
    save: "Save",
    cancel: "Cancel",
    api_response: "API Response",
    copy: "Copy",
    stage_open_bind_title: "Open / Bind",
    stage_open_bind_subtitle: "Open software, refresh windows, and bind the target window",
    stage_capture_title: "Capture",
    stage_capture_subtitle: "Capture the bound window or load a saved screenshot",
    stage_observe_title: "Observe",
    stage_observe_subtitle: "Describe the page purpose, controls, and next state hint",
    stage_locate_title: "Locate",
    stage_locate_subtitle: "Use OCR and vision grounding to locate a target coordinate",
    stage_execute_title: "Execute",
    stage_execute_subtitle: "Preview or execute either a recognition-plan click or a coordinate click",
    stage_input_title: "Input",
    stage_input_subtitle: "Test text input without navigation path or page detail panels",
    stage_trace_title: "Trace Inspector",
    stage_trace_subtitle: "Read local traces by stage and inspect raw stage content",
    stage_model_test_title: "Model Test",
    stage_model_test_subtitle: "Talk directly to a vision model with prompt and image",
    trace_file: "Trace file",
    start_model: "Start model",
    stop_model: "Stop model",
    test_model: "Check model service",
    apply_model_profile: "Apply profile",
    running: "running",
    ok: "ok",
    failed: "failed",
    idle: "idle",
    runtime_ready: "runtime ready",
    runtime_unavailable: "runtime unavailable",
    no_image: "no image",
    no_response: "no response",
    no_windows: "No windows found",
    no_models: "No model profiles found",
    request_already_running: "This request is already running"
  }
};
function baseUrl() {
  const baseInput = $("baseUrl");
  const value = baseInput ? baseInput.value.trim() : "";
  return value || window.location.origin;
}

function t(key) {
  return translations[currentLanguage]?.[key] || translations["en-US"][key] || key;
}

function applyLanguage(language) {
  currentLanguage = translations[language] ? language : "zh-CN";
  localStorage.setItem("agentPanelLanguage", currentLanguage);
  document.documentElement.lang = currentLanguage;
  document.querySelectorAll(".language-option").forEach((button) => {
    button.classList.toggle("active", button.dataset.language === currentLanguage);
  });
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
  const activeStage = document.querySelector(".stage.active")?.dataset.stage || "runtime";
  showStage(activeStage);
  if (!currentImagePath) $("previewMeta").textContent = t("no_image");
  if (!$("responseText").textContent || $("responseText").textContent === "{}") $("graphMeta").textContent = t("no_response");
}

function defaultWritePolicyFor(mode, depth) {
  if (mode === "learn") {
    return { path_graph: true, element_memory: depth === "deep", trace: true };
  }
  return { path_graph: false, element_memory: true, trace: true };
}

function setWritePolicyControls(policy) {
  if ($("writePathGraph")) $("writePathGraph").checked = policy.path_graph !== false;
  if ($("writeElementMemory")) $("writeElementMemory").checked = policy.element_memory === true;
  if ($("writeTrace")) $("writeTrace").checked = policy.trace !== false;
}

function writePolicyPayload() {
  return {
    path_graph: $("writePathGraph")?.checked !== false,
    element_memory: $("writeElementMemory")?.checked === true,
    trace: $("writeTrace")?.checked !== false,
  };
}

function setAgentMode(mode, depth = currentLearnDepth, options = {}) {
  currentAgentMode = mode === "execute" ? "execute" : "learn";
  currentLearnDepth = depth === "deep" ? "deep" : "fast";
  localStorage.setItem("agentPanelMode", currentAgentMode);
  localStorage.setItem("agentLearnDepth", currentLearnDepth);
  document.querySelectorAll(".mode-option[data-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === currentAgentMode);
  });
  document.querySelectorAll(".mode-option[data-depth]").forEach((button) => {
    button.classList.toggle("active", button.dataset.depth === currentLearnDepth);
    button.disabled = currentAgentMode !== "learn";
  });
  if (!options.preservePolicy) {
    setWritePolicyControls(defaultWritePolicyFor(currentAgentMode, currentLearnDepth));
  }
}

function modePayload(stage) {
  const mode = stage === "observe" ? currentAgentMode : (currentAgentMode === "learn" && currentLearnDepth === "deep" ? "learn" : "execute");
  const depth = mode === "learn" ? currentLearnDepth : null;
  return {
    agent_mode: mode,
    learn_depth: depth,
    write_policy: writePolicyPayload(),
  };
}

function responseAllowsPathGraphWrite(result) {
  const policy = result?.write_policy || nestedGet(result, ["request", "write_policy"]);
  if (!policy || typeof policy !== "object") return true;
  return policy.path_graph !== false;
}

function setStatus(text, state = "neutral") {
  const el = $("requestStatus");
  el.textContent = t(text) || text;
  el.style.color = state === "error" ? "#b42318" : state === "ok" ? "#14804a" : "#344054";
}

function setRuntimeState(text, ok = true) {
  const el = $("runtimeState");
  el.textContent = t(text) || text;
  el.style.color = ok ? "#b8c0cc" : "#fda29b";
}

function showStage(stage) {
  document.querySelectorAll(".stage").forEach((button) => {
    button.classList.toggle("active", button.dataset.stage === stage);
  });
  document.querySelectorAll(".stage-page").forEach((page) => {
    page.classList.toggle("active", page.dataset.page === stage);
  });
  const [titleKey, subtitleKey] = stageMeta[stage] || stageMeta.open_bind;
  $("stageTitle").textContent = t(titleKey);
  $("stageSubtitle").textContent = t(subtitleKey);

  const flowStrip = document.querySelector(".flow-diagram-strip");
  const pathPanel = $("navPathPanel");
  const traceView = $("traceFullView");
  const contentGrid = document.querySelector(".content-grid");
  const responseSurface = document.querySelector(".response-surface");
  const previewPanel = document.querySelector(".preview-panel");
  const pathDetailPanel = $("pathDetailPanel");
  const responsePanel = document.querySelector(".response-panel");

  const needsPath = new Set(["observe", "locate", "execute"]);
  const needsPreview = new Set(["capture", "observe", "locate", "execute"]);
  const needsResponse = new Set(["open_bind", "capture", "observe", "locate", "execute", "input"]);
  const singleColumn = stage === "trace" || stage === "model_test" || stage === "input";

  if (flowStrip) flowStrip.style.display = stage === "trace" ? "none" : "";
  if (pathPanel) pathPanel.style.display = needsPath.has(stage) ? "" : "none";
  if (previewPanel) previewPanel.style.display = needsPreview.has(stage) ? "" : "none";
  if (pathDetailPanel) pathDetailPanel.style.display = needsPath.has(stage) ? "" : "none";
  if (responsePanel) responsePanel.style.display = needsResponse.has(stage) ? "" : "none";
  if (contentGrid) contentGrid.classList.toggle("single-column", singleColumn);
  if (responseSurface) responseSurface.style.display = stage === "model_test" ? "none" : "";

  if (traceView) {
    traceView.style.display = stage === "trace" ? "block" : "none";
    const targetParent = stage === "trace" ? document.querySelector(".control-surface") : document.querySelector(".response-surface");
    if (targetParent && traceView.parentElement !== targetParent) {
      targetParent.appendChild(traceView);
    }
  }
  if (stage === "trace" && lastTracePath) inspectLatestTrace(lastTracePath);

  if (stage === "open_bind") refreshWindows(false);
  if (stage === "model_test") populateModelTestProfiles();
}
async function api(method, path, payload = null, options = {}) {
  const workflowStep = options.workflowStep || null;
  const requestKey = workflowStep || `${method} ${path}`;
  if (pendingRequests.has(requestKey)) {
    renderResponse({ success: false, message: t("request_already_running"), data: { request: requestKey } }, requestKey);
    return { success: false, message: t("request_already_running") };
  }
  pendingRequests.add(requestKey);
  markWorkflow(workflowStep, "active");
  setStatus("running");
  const controller = new AbortController();
  const timeoutMs = Number(options.timeoutSeconds || requestTimeoutSeconds()) * 1000;
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  const request = {
    method,
    headers: payload ? { "Content-Type": "application/json" } : {},
    signal: controller.signal,
  };
  if (payload) {
    request.body = JSON.stringify(payload);
  }
  try {
    const response = await fetch(`${baseUrl()}${path}`, request);
    const text = await response.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch (_error) {
      data = { success: response.ok, message: text };
    }
    if (!options.skipRender) renderResponse(data, options.summary || `${method} ${path}`);
    setStatus(response.ok && data.success !== false ? "ok" : "failed", response.ok && data.success !== false ? "ok" : "error");
    markWorkflow(workflowStep, response.ok && data.success !== false ? "done" : "error");
    return data;
  } catch (error) {
    const data = { success: false, message: "Request failed", error: String(error) };
    if (!options.skipRender) renderResponse(data, options.summary || `${method} ${path}`);
    setStatus("failed", "error");
    markWorkflow(workflowStep, "error");
    return data;
  } finally {
    window.clearTimeout(timeoutId);
    pendingRequests.delete(requestKey);
  }
}

function requestTimeoutSeconds() {
  const value = Number($("timeoutSeconds")?.value || 600);
  return Number.isFinite(value) && value > 0 ? value : 600;
}

function markWorkflow(step, status) {
  // No-op: the old workflow strip is replaced by the nav path graph.
  // Kept for backward compatibility with api() call sites.
}

function resultOf(response) {
  const data = response && typeof response.data === "object" ? response.data : {};
  const result = data && typeof data.result === "object" ? data.result : {};
  return Object.keys(result).length ? result : response;
}

function nestedGet(source, path) {
  let current = source;
  for (const key of path) {
    if (!current || typeof current !== "object") return undefined;
    current = current[key];
  }
  return current;
}

function profileLabel(profile) {
  const label = profile?.label || profile?.profile_id || "";
  const port = profile?.port ? `:${profile.port}` : "";
  return `${label}${port}`;
}

function profileById(profileId) {
  return modelProfiles.find((profile) => profile.profile_id === profileId) || null;
}

function defaultProfileId(stage) {
  const stageText = String(stage || "").toLowerCase();
  const expected = stageText === "observe" ? "understanding" : stageText === "locate" ? "grounding" : stageText;
  const byRole = modelProfiles.find((profile) => (profile.role || []).map((item) => String(item).toLowerCase()).includes(expected));
  return (byRole || modelProfiles[0] || {}).profile_id || "";
}

function selectProfileForStage(stage, selectId) {
  const select = $(selectId);
  const current = select.value;
  const next = current && profileById(current) ? current : defaultProfileId(stage);
  select.value = next;
  return profileById(select.value);
}

function fillModelSelect(selectId, stage) {
  const select = $(selectId);
  const previous = select.value;
  select.innerHTML = "";
  if (!modelProfiles.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = t("no_models");
    select.appendChild(option);
    return null;
  }
  for (const profile of modelProfiles) {
    const option = document.createElement("option");
    option.value = profile.profile_id || "";
    option.textContent = profileLabel(profile);
    select.appendChild(option);
  }
  if (previous && profileById(previous)) select.value = previous;
  return selectProfileForStage(stage, selectId);
}

/* 鈹€鈹€ Model test page 鈹€鈹€ */

function populateModelTestProfiles() {
  const sel = $("modelTestProfile");
  if (!sel) return;
  sel.innerHTML = modelProfiles.map((p) => {
    const label = profileLabel(p);
    return `<option value="${p.profile_id || ""}">${label}</option>`;
  }).join("") || '<option value="">-- none --</option>';
}

async function sendModelTest() {
  const profileId = $("modelTestProfile").value;
  const stage = $("modelTestStage").value;
  const prompt = $("modelTestPrompt").value.trim();
  const useImage = $("modelTestUseImage").checked;
  const explicitImage = ($("modelTestImagePath")?.value || "").trim();
  const imagePath = useImage ? (explicitImage || currentImagePath || "") : "";
  if (!prompt) return;
  if (!profileId) {
    $("modelTestResponse").innerHTML = '<p class="trace-idle" style="color:#f04438;">Select a model profile first.</p>';
    return;
  }

  $("modelTestResponse").innerHTML = '<p class="trace-idle">Sending...</p>';
  try {
    const response = await api("POST", "/panel/model_test", {
      profile_id: profileId,
      stage,
      prompt,
      image_path: imagePath || null,
      max_tokens: 2048,
      temperature: 0.1,
    }, { summary: "POST /panel/model_test", skipRender: true, timeoutSeconds: requestTimeoutSeconds() });
    if (response.success === false) {
      const detail = response.error?.details || response.message || "request failed";
      $("modelTestResponse").innerHTML = `<p class="trace-idle" style="color:#f04438;">${escapeHtml(String(detail))}</p>`;
      return;
    }
    const data = response.data || {};
    const content = data.content || JSON.stringify(data.raw_response || data, null, 2);
    $("modelTestResponse").innerHTML = `<div class="model-test-meta">${escapeHtml(data.model || profileId)}${data.image_attached ? " | image attached" : ""}</div><pre class="model-test-output">${escapeHtml(String(content))}</pre>`;
  } catch (e) {
    $("modelTestResponse").innerHTML = `<p class="trace-idle" style="color:#f04438;">Request failed: ${escapeHtml(e.message)}</p>`;
  }
}
function syncModelControls() {
  const stageEl = $("modelStage");
  const profileEl = $("modelProfileId");
  if (!stageEl || !profileEl) return;
  const selected = selectProfileForStage(stageEl.value, "modelProfileId");
  if ($("modelStartScript")) $("modelStartScript").value = selected?.start_script || "";
  if ($("modelStopScript")) $("modelStopScript").value = selected?.stop_script || "";
}

function syncStageProvider(stage) {
  const profile = stage === "observe" ? selectProfileForStage("observe", "observeModelProfile") : selectProfileForStage("locate", "locateModelProfile");
  if (stage === "observe" && profile?.provider_mode) $("observeProvider").value = profile.provider_mode;
  return profile;
}

function populateModelProfiles(models) {
  modelProfiles = (models || []).map((item) => item.profile || item).filter((profile) => profile && typeof profile === "object");
  fillModelSelect("observeModelProfile", "observe");
  fillModelSelect("locateModelProfile", "locate");
  syncStageProvider("observe");
  syncStageProvider("locate");
  populateModelTestProfiles();
}

function windowCandidateLabel(candidate) {
  const title = String(candidate.title || "");
  const process = String(candidate.process_name || "");
  const processId = candidate.process_id || candidate.pid || "";
  const handle = candidate.handle || "";
  const prefix = `${process}#${processId}`.replace(/#$/, "");
  const suffix = handle ? ` hwnd=${handle}` : "";
  return `${prefix} | ${title}${suffix}`.trim();
}

function appIdFromProcessName(processName) {
  const process = String(processName || "").trim().replace(/\.exe$/i, "").toLowerCase();
  if (!process) return "";
  if (process === "msedge") return "edge";
  if (process === "googlechrome") return "chrome";
  return process;
}

function setWindowCandidates(candidates) {
  windowCandidates = Array.isArray(candidates) ? candidates : [];
  const select = $("windowSelect");
  select.innerHTML = "";
  if (!windowCandidates.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = t("no_windows");
    select.appendChild(option);
    return;
  }
  for (const candidate of windowCandidates) {
    const option = document.createElement("option");
    option.value = windowCandidateLabel(candidate);
    option.textContent = option.value;
    select.appendChild(option);
  }
  select.value = windowCandidateLabel(windowCandidates[0]);
  applySelectedWindow();
}

function applySelectedWindow() {
  const selected = $("windowSelect").value;
  const candidate = windowCandidates.find((item) => windowCandidateLabel(item) === selected);
  if (!candidate) return;
  if (candidate.process_name) $("bindProcess").value = String(candidate.process_name);
  if (candidate.title) $("bindTitle").value = String(candidate.title);
  const inferredAppId = appIdFromProcessName(candidate.process_name);
  if (inferredAppId) $("appId").value = inferredAppId;
  syncWindowAppAndState(candidate);
}

function appNameFromUrl(urlValue) {
  const rawUrl = String(urlValue || "").trim();
  if (!rawUrl) return "";
  try {
    const parsed = new URL(rawUrl);
    const host = parsed.hostname.replace(/^www\./i, "");
    if (!host) return "";
    if (/mousetester\.cn$/i.test(host)) return "MouseTesterWeb";
    const base = host.split(".")[0] || host;
    return base
      .split(/[-_]+/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join("");
  } catch {
    return "";
  }
}

function stripBrowserTitleSuffix(titleValue) {
  return String(titleValue || "")
    .trim()
    .replace(/\s*[-|–—]\s*(Microsoft Edge|Google Chrome|Mozilla Firefox)$/i, "")
    .trim();
}

function canonicalAppNameFromTitle(titleValue) {
  const cleanTitle = stripBrowserTitleSuffix(titleValue);
  if (!cleanTitle) return "";
  const firstSegment = cleanTitle.split(/\s*[-|–—]\s*/)[0]?.trim() || cleanTitle;
  if (/mousetester/i.test(firstSegment)) return "MouseTesterWeb";
  return firstSegment;
}

function appNameFromWindow(candidate = null) {
  const appId = String($("appId")?.value || "").trim();
  if (appId && !BROWSER_APP_IDS.has(appId.toLowerCase())) return appId;
  const urlAppName = appNameFromUrl($("appUrl")?.value);
  if (urlAppName) return urlAppName;
  const title = stripBrowserTitleSuffix(candidate?.title || $("bindTitle")?.value || "");
  const titleAppName = canonicalAppNameFromTitle(title);
  if (titleAppName && !/^(microsoft edge|google chrome|mozilla firefox)$/i.test(titleAppName)) {
    return titleAppName;
  }
  const processName = String(candidate?.process_name || $("bindProcess")?.value || "").trim();
  return processName.replace(/\.exe$/i, "");
}

function stateHintFromWindow(candidate = null, appName = "") {
  const cleanTitle = stripBrowserTitleSuffix(candidate?.title || $("bindTitle")?.value || "");
  const normalizedAppName = String(appName || "").trim();
  if (!cleanTitle || !normalizedAppName) return "";

  const parts = cleanTitle.split(/\s*[-|–—]\s*/).map((part) => part.trim()).filter(Boolean);
  if (parts.length > 1) {
    const firstPartApp = canonicalAppNameFromTitle(parts[0]);
    if (firstPartApp.toLowerCase() === normalizedAppName.toLowerCase()) {
      return parts.slice(1).join(" - ");
    }
  }

  const lowerTitle = cleanTitle.toLowerCase();
  const lowerApp = normalizedAppName.toLowerCase();
  if (lowerTitle.startsWith(lowerApp)) {
    return cleanTitle.slice(normalizedAppName.length).replace(/^\s*[-|–—:：]?\s*/, "").trim();
  }

  if (normalizedAppName === "MouseTesterWeb" && /mousetester/i.test(cleanTitle)) {
    return cleanTitle;
  }
  if (cleanTitle.toLowerCase() !== normalizedAppName.toLowerCase()) {
    return cleanTitle;
  }
  return "";
}

function syncWindowAppAndState(candidate = null) {
  const appName = appNameFromWindow(candidate);
  syncAppAndStateFields({
    appName,
    stateHint: stateHintFromWindow(candidate, appName),
  });
}

function syncAppAndStateFields({ appName = "", stateHint = "" } = {}) {
  const normalizedAppName = String(appName || "").trim();
  const normalizedStateHint = String(stateHint || "").trim();
  if (normalizedAppName) {
    ["observeApp", "locateApp", "executeApp"].forEach((id) => {
      const el = $(id);
      if (el) el.value = normalizedAppName;
    });
    navPathAppName = normalizedAppName;
    updatePathAppLabel();
  }
  if (normalizedStateHint) {
    ["observeState", "locateState"].forEach((id) => {
      const el = $(id);
      if (el) el.value = normalizedStateHint;
    });
  }
}

async function refreshWindows(showResponse = true) {
  const response = await api("GET", "/session/windows", null, {
    summary: "GET /session/windows",
    workflowStep: "open",
  });
  setWindowCandidates(nestedGet(response, ["data", "candidates"]) || []);
  if (!showResponse && response?.success === false) {
    setStatus("idle");
  }
  return response;
}

async function refreshModels() {
  const response = await api("GET", "/runtime/models", null, { summary: "GET /runtime/models" });
  populateModelProfiles(nestedGet(response, ["data", "models"]) || []);
  return response;
}

async function callModelAction(action, stage, profileId) {
  const waitControl = $("prepareWait");
  const waitUntilReady = action === "start" ? Boolean(waitControl?.checked) : false;
  const waitSeconds = waitUntilReady ? 30 : 0;
  renderResponse({
    success: true,
    message: `${action === "start" ? "Starting" : "Stopping"} ${stage} model...`,
    data: {
      contract_version: "panel_model_action_v1",
      action,
      stage,
      profile_id: profileId || null,
      wait_until_ready: waitUntilReady,
    },
  }, `${action} ${stage} model`);
  return api("POST", `/runtime/models/${action}`, {
    stage,
    profile_id: profileId || null,
    wait_until_ready: waitUntilReady,
    wait_seconds: waitSeconds,
  }, { summary: `POST /runtime/models/${action} ${stage}`, timeoutSeconds: waitSeconds + 30 });
}

function selectedModelStatus(models, stage, profileId) {
  return (models || []).find((item) => item.profile?.profile_id === profileId)
    || (models || []).find((item) => (item.profile?.role || []).includes(stage));
}

async function ensureStageModelReady(stage, profileId) {
  const profile = profileById(profileId);
  const providerMode = String(profile?.provider_mode || "").toLowerCase();
  if (!providerMode.startsWith("local")) return true;

  setStatus(`checking ${stage} model`);
  const statusResponse = await api("GET", "/runtime/models", null, { summary: "GET /runtime/models", skipRender: true });
  const models = nestedGet(statusResponse, ["data", "models"]) || [];
  const selected = selectedModelStatus(models, stage, profileId);
  if (selected?.status?.status === "running") return true;

  if (profile?.launchable === false) {
    renderResponse({
      success: false,
      message: `${stage} model is not running`,
      data: {
        contract_version: "panel_model_preflight_v1",
        stage,
        profile_id: profileId,
        status: selected?.status || null,
        next_step: "Start the selected model service before running this stage.",
      },
    }, `${stage} model not ready`);
    return false;
  }

  setStatus(`starting ${stage} model`);
  const waitSeconds = Math.min(Math.max(45, requestTimeoutSeconds()), 180);
  const startResponse = await api("POST", "/runtime/models/start", {
    stage,
    profile_id: profileId || null,
    wait_until_ready: true,
    wait_seconds: waitSeconds,
  }, { summary: `POST /runtime/models/start ${stage}`, skipRender: true, timeoutSeconds: waitSeconds + 10 });

  const afterStatus = nestedGet(startResponse, ["data", "after", "status"])
    || nestedGet(startResponse, ["data", "before", "status"])
    || nestedGet(startResponse, ["data", "status", "status"]);
  if (startResponse.success !== false && afterStatus === "running") {
    setStatus("ok", "ok");
    return true;
  }

  renderResponse({
    success: false,
    message: `${stage} model is not ready`,
    data: {
      contract_version: "panel_model_preflight_v1",
      stage,
      profile_id: profileId,
      model_status: startResponse.data || null,
      next_step: "The model was started or checked, but /v1/models is still not running. Wait for loading to finish, then retry.",
    },
    error: startResponse.error || null,
  }, `${stage} model not ready`);
  setStatus("failed", "error");
  return false;
}

async function applyModelProfile(stage, profileId) {
  return api(
    "POST",
    "/panel/apply_model_profile",
    {
      stage,
      profile_id: profileId || null,
      timeout_seconds: requestTimeoutSeconds(),
      language: currentLanguage,
      observe_prompt: $("observePrompt").value,
      locate_prompt: $("locatePrompt").value,
    },
    { summary: "POST /panel/apply_model_profile" },
  );
}

async function testModelService(stage, profileId) {
  const response = await refreshModels();
  const models = nestedGet(response, ["data", "models"]) || [];
  const selected = models.find((item) => item.profile?.profile_id === profileId) || models.find((item) => (item.profile?.role || []).includes(stage));
  if (selected) {
    renderResponse(
      {
        success: selected.status?.status === "running",
        message: `Model service ${selected.status?.status || "unknown"}`,
        data: { contract_version: "runtime_model_service_test_v1", stage, model: selected },
      },
      "model service test",
    );
  }
  return response;
}

/* 鈹€鈹€ Flow diagram: ALL stages visible from start, completed ones light up 鈹€鈹€ */

const ALL_FLOW_STAGES = [
  { id: "request", label: "Request" },
  { id: "capture", label: "Capture" },
  { id: "ocr", label: "OCR" },
  { id: "vision", label: "Vision" },
  { id: "candidates", label: "Candidates" },
  { id: "gate", label: "Gate" },
  { id: "action", label: "Action" },
  { id: "verify", label: "Verify" },
];

let flowStageStatus = Object.fromEntries(ALL_FLOW_STAGES.map((s) => [s.id, "inactive"]));

function updateFlowStage(stageId, status) {
  // status: "inactive" | "active" | "done" | "error" | "blocked"
  if (flowStageStatus[stageId] === "done" || flowStageStatus[stageId] === "error") return; // don't downgrade
  flowStageStatus[stageId] = status;
}

function detectFlowStagesFromResponse(response) {
  const result = resultOf(response);
  const plan = result.recognition_plan && typeof result.recognition_plan === "object" ? result.recognition_plan : result;
  const parseResult = plan.parse_result || {};
  const candidateResult = plan.candidate_result || {};
  const preClick = result.pre_click_decision || plan.pre_click_decision || {};
  const executionPath = result.execution_path || {};

  if (response.request || result.request || result.goal || plan.goal || response.message) updateFlowStage("request", "done");

  const hasCapture = result.image_path || plan.image_path || nestedGet(result, ["live_capture", "image_path"]) || nestedGet(result, ["data", "image_path"]);
  if (hasCapture) updateFlowStage("capture", "done");

  const ocrMatches = nestedGet(parseResult, ["ocr_result", "matches"]);
  const ocrCount = nestedGet(parseResult, ["ocr_result", "metadata", "match_count"]);
  if (Array.isArray(ocrMatches) || ocrCount !== undefined) updateFlowStage("ocr", "done");

  const visionUsed = executionPath.vision_model_used === true || parseResult.vision_regions || result.screen_summary || result.screen_reading;
  if (visionUsed) updateFlowStage("vision", "done");

  if (Object.keys(candidateResult).length) {
    const hasRecommendation = candidateResult.has_recommendation ?? nestedGet(candidateResult, ["summary", "has_recommendation"]);
    updateFlowStage("candidates", hasRecommendation ? "done" : "active");
  }

  if (Object.keys(preClick).length) {
    updateFlowStage("gate", preClick.allowed ? "done" : "blocked");
  }

  if (result.click_result || executionPath.action_executed !== undefined || result.located_point || preClick.selected_click_point) {
    updateFlowStage("action", executionPath.action_executed === false ? "active" : "done");
  }

  const verification = result.post_click_verification || result.semantic_post_click_verification;
  if (verification) {
    const ok = !(verification.verified === false || verification.success === false);
    updateFlowStage("verify", ok ? "done" : "error");
  }

  const anyDone = Object.values(flowStageStatus).some((s) => s !== "inactive");
  if (!anyDone) updateFlowStage("request", "active");
}
function renderFlowGraph(response) {
  const svg = $("flowDiagram");
  if (!svg) return;

  if (response && Object.keys(response).length > 1) {
    detectFlowStagesFromResponse(response);
  }

  const doneCount = Object.values(flowStageStatus).filter((s) => s === "done").length;
  $("graphMeta").textContent = `${doneCount}/${ALL_FLOW_STAGES.length} done`;

  svg.innerHTML = "";
  svg.setAttribute("viewBox", "0 0 1120 56");

  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  defs.innerHTML = `
    <filter id="flowShadow"><feDropShadow dx="0" dy="1" stdDeviation="1.5" flood-opacity="0.08"/></filter>
    <marker id="flowArr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#c4cdd9"/></marker>
    <marker id="flowArrDone" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#12b76a"/></marker>
    <marker id="flowArrActive" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#155eef"/></marker>
  `;
  svg.appendChild(defs);

  const N = ALL_FLOW_STAGES.length;
  const w = 1120;
  const h = 56;
  const nodeW = 88;
  const nodeH = 34;
  const gap = (w - 20 - N * nodeW) / (N - 1);
  const top = (h - nodeH) / 2;

  ALL_FLOW_STAGES.forEach((stage, i) => {
    const x = 10 + i * (nodeW + gap);
    const y = top;
    const status = flowStageStatus[stage.id] || "inactive";

    // Pill background
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");

    const pill = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    pill.setAttribute("x", x);
    pill.setAttribute("y", y);
    pill.setAttribute("width", nodeW);
    pill.setAttribute("height", nodeH);
    pill.setAttribute("rx", "17");
    pill.setAttribute("ry", "17");
    pill.setAttribute("filter", "url(#flowShadow)");

    if (status === "done") {
      pill.setAttribute("fill", "#ecfdf3");
      pill.setAttribute("stroke", "#6ce9a6");
      pill.setAttribute("stroke-width", "1.5");
    } else if (status === "active") {
      pill.setAttribute("fill", "#eff6ff");
      pill.setAttribute("stroke", "#93c5fd");
      pill.setAttribute("stroke-width", "1.8");
    } else if (status === "error") {
      pill.setAttribute("fill", "#fff1f3");
      pill.setAttribute("stroke", "#fda4af");
      pill.setAttribute("stroke-width", "1.5");
    } else if (status === "blocked") {
      pill.setAttribute("fill", "#fffcf5");
      pill.setAttribute("stroke", "#fcd34d");
      pill.setAttribute("stroke-width", "1.5");
    } else {
      pill.setAttribute("fill", "#f9fafb");
      pill.setAttribute("stroke", "#e4e7ec");
      pill.setAttribute("stroke-width", "1");
    }
    g.appendChild(pill);

    // Step number circle
    const cx = x + 17;
    const cy = y + nodeH / 2;
    const circ = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circ.setAttribute("cx", cx);
    circ.setAttribute("cy", cy);
    circ.setAttribute("r", "10");
    if (status === "done") {
      circ.setAttribute("fill", "#12b76a");
    } else if (status === "active") {
      circ.setAttribute("fill", "#155eef");
    } else if (status === "error") {
      circ.setAttribute("fill", "#f04438");
    } else if (status === "blocked") {
      circ.setAttribute("fill", "#f79009");
    } else {
      circ.setAttribute("fill", "#c4cdd9");
    }
    g.appendChild(circ);

    // Number or checkmark
    const num = document.createElementNS("http://www.w3.org/2000/svg", "text");
    num.setAttribute("x", cx);
    num.setAttribute("y", cy + 1);
    num.setAttribute("text-anchor", "middle");
    num.setAttribute("dominant-baseline", "middle");
    num.setAttribute("fill", "#fff");
    num.setAttribute("font-size", "10");
    num.setAttribute("font-weight", "700");
    num.setAttribute("font-family", "system-ui, -apple-system, sans-serif");
    num.textContent = status === "done" ? "OK" : String(i + 1);
    g.appendChild(num);

    // Label
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", x + 31);
    label.setAttribute("y", cy + 1);
    label.setAttribute("text-anchor", "start");
    label.setAttribute("dominant-baseline", "middle");
    label.setAttribute("font-size", "11.5");
    label.setAttribute("font-weight", status === "inactive" ? "500" : "600");
    label.setAttribute("font-family", "system-ui, -apple-system, sans-serif");
    label.setAttribute("fill", status === "inactive" ? "#98a2b3" : status === "done" ? "#027a48" : status === "active" ? "#155eef" : "#344054");
    label.textContent = stage.label;
    g.appendChild(label);

    svg.appendChild(g);

    // Connector
    if (i < N - 1) {
      const nextStatus = flowStageStatus[ALL_FLOW_STAGES[i + 1].id] || "inactive";
      const connColor = status === "done" && (nextStatus === "done" || nextStatus === "active") ? "#12b76a"
        : status === "active" ? "#155eef"
        : "#c4cdd9";
      const marker = status === "done" && (nextStatus === "done" || nextStatus === "active") ? "url(#flowArrDone)"
        : status === "active" ? "url(#flowArrActive)"
        : "url(#flowArr)";

      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", x + nodeW + 2);
      line.setAttribute("y1", cy);
      line.setAttribute("x2", x + nodeW + gap - 3);
      line.setAttribute("y2", cy);
      line.setAttribute("stroke", connColor);
      line.setAttribute("stroke-width", "1.4");
      line.setAttribute("stroke-dasharray", status === "done" && nextStatus === "inactive" ? "3,3" : "none");
      line.setAttribute("marker-end", marker);
      svg.appendChild(line);
    }
  });
}

function renderResponse(response, summary) {
  lastResponse = response || {};
  const result = resultOf(lastResponse);
  lastTracePath = result.trace_path || result.recognition_plan_trace_path || nestedGet(result, ["recognition_plan", "trace_path"]) || lastTracePath;
  if (result.contract_version === "screen_observation_v1" || result.screen_map?.contract_version === "screen_map_v1") {
    lastObserveTracePath = result.trace_path || lastObserveTracePath;
  }
  if (lastTracePath) inspectLatestTrace(lastTracePath);
  $("responseText").textContent = JSON.stringify(lastResponse, null, 2);
  renderFlowGraph(lastResponse);
  if (responseAllowsPathGraphWrite(result)) {
    ingestNavPathFromResponse(lastResponse);
  }
  const imagePath = result.image_path || nestedGet(lastResponse, ["data", "image_path"]) || nestedGet(result, ["capture", "image_path"]) || nestedGet(result, ["live_capture", "image_path"]);
  if (imagePath) setCurrentImage(imagePath);
  const overlayPath = result.overlay_path || result.manual_overlay_path || nestedGet(lastResponse, ["data", "manual_overlay_path"]) || nestedGet(result, ["recognition_plan_overlay", "overlay_path"]);
  if (overlayPath) setCurrentImage(overlayPath);
  const suggestedState = nestedGet(result, ["suggested_state_hint"]);
  if (suggestedState) {
    syncAppAndStateFields({ stateHint: suggestedState });
  }
  populateReviewCandidate(result);
  const locatedPoint = result.located_point || nestedGet(result, ["pre_click_decision", "selected_click_point"]);
  if (locatedPoint && result.goal) {
    $("executeGoal").value = result.goal;
  }
}

function metadataWithPrompt(stage) {
  const prompt = stage === "observe" ? $("observePrompt").value.trim() : $("locatePrompt").value.trim();
  return {
    ocr_anchors: { enabled: true, max_anchors: "all", min_score: 0.0 },
    prompt_overrides: { additional_rules: prompt },
    settings_panel: { language: currentLanguage },
  };
}

function roiPayload() {
  const values = [$("roiX").value, $("roiY").value, $("roiW").value, $("roiH").value];
  if (!values.some((item) => String(item || "").trim())) return null;
  return {
    x: Number($("roiX").value || 0),
    y: Number($("roiY").value || 0),
    width: Number($("roiW").value || 0),
    height: Number($("roiH").value || 0),
  };
}

function panelFileUrl(path) {
  return `${baseUrl()}/panel/file?path=${encodeURIComponent(path)}`;
}

function setCurrentImage(path, url = "") {
  currentImagePath = path || "";
  currentImageUrl = url || (path ? panelFileUrl(path) : "");
  $("imagePath").value = currentImagePath;
  $("previewMeta").textContent = currentImagePath ? basename(currentImagePath) : t("no_image");
  const img = $("previewImage");
  const overlay = $("bboxOverlay");
  overlay.style.display = "none";
  if (!currentImageUrl) {
    img.style.display = "none";
    img.removeAttribute("src");
    return;
  }
  img.onload = () => {
    img.style.display = "block";
    previewBox();
  };
  img.src = currentImageUrl;
}

function bboxFromInputs() {
  const x = Number($("bboxX").value || 0);
  const y = Number($("bboxY").value || 0);
  const width = Number($("bboxW").value || 0);
  const height = Number($("bboxH").value || 0);
  if (!width || !height) return null;
  return { x, y, width, height };
}

function pointFromInputsOrBox() {
  const px = $("pointX").value;
  const py = $("pointY").value;
  if (px !== "" && py !== "") return { x: Number(px), y: Number(py) };
  const bbox = bboxFromInputs();
  if (!bbox) return null;
  return { x: Math.round(bbox.x + bbox.width / 2), y: Math.round(bbox.y + bbox.height / 2) };
}

function previewBox() {
  const img = $("previewImage");
  const overlay = $("bboxOverlay");
  const bbox = bboxFromInputs();
  if (!bbox || !img.naturalWidth || img.style.display === "none") {
    overlay.style.display = "none";
    return;
  }
  const scaleX = img.clientWidth / img.naturalWidth;
  const scaleY = img.clientHeight / img.naturalHeight;
  const rect = img.getBoundingClientRect();
  const host = $("imagePreview").getBoundingClientRect();
  overlay.style.left = `${rect.left - host.left + bbox.x * scaleX}px`;
  overlay.style.top = `${rect.top - host.top + bbox.y * scaleY}px`;
  overlay.style.width = `${bbox.width * scaleX}px`;
  overlay.style.height = `${bbox.height * scaleY}px`;
  overlay.style.display = "block";
}

function normalizeBbox(source) {
  if (!source || typeof source !== "object") return null;
  const width = source.width ?? source.w;
  const height = source.height ?? source.h;
  if (width === undefined || height === undefined) return null;
  return { x: Number(source.x || 0), y: Number(source.y || 0), width: Number(width), height: Number(height) };
}

function populateReviewCandidate(result) {
  const plan = result.recognition_plan && typeof result.recognition_plan === "object" ? result.recognition_plan : result;
  let candidate = result.recommended_target && typeof result.recommended_target === "object" ? result.recommended_target : null;
  let bbox = normalizeBbox(result.located_bbox);
  if (!bbox && candidate) bbox = normalizeBbox(candidate.refined_bbox) || normalizeBbox(nestedGet(candidate, ["element", "bbox"]));
  if (!bbox) {
    let candidates = nestedGet(plan, ["candidate_result", "candidates"]) || [];
    if (!Array.isArray(candidates) || !candidates.length) candidates = nestedGet(plan, ["candidate_result", "rejected"]) || [];
    candidate = Array.isArray(candidates) && candidates.length && typeof candidates[0] === "object" ? candidates[0] : candidate;
    bbox = normalizeBbox(candidate?.refined_bbox) || normalizeBbox(nestedGet(candidate || {}, ["element", "bbox"]));
  }
  const point = result.located_point || result.selected_click_point || nestedGet(plan, ["pre_click_decision", "selected_click_point"]) || nestedGet(candidate || {}, ["element", "click_point"]);
  if (bbox) {
    $("bboxX").value = Math.round(bbox.x);
    $("bboxY").value = Math.round(bbox.y);
    $("bboxW").value = Math.round(bbox.width);
    $("bboxH").value = Math.round(bbox.height);
    if (!point) {
      $("pointX").value = Math.round(bbox.x + bbox.width / 2);
      $("pointY").value = Math.round(bbox.y + bbox.height / 2);
    }
  }
  if (point) {
    $("pointX").value = Math.round(Number(point.x || 0));
    $("pointY").value = Math.round(Number(point.y || 0));
  }
  if (candidate?.label || candidate?.text) $("reviewLabel").value = String(candidate.label || candidate.text);
  previewBox();
}

/* 鈹€鈹€ Navigation path graph 鈹€鈹€ */

function basename(path) {
  return String(path || "").split(/[\\/]/).pop() || "";
}

function formatPathTime() {
  const now = new Date();
  const h = String(now.getHours()).padStart(2, "0");
  const m = String(now.getMinutes()).padStart(2, "0");
  const s = String(now.getSeconds()).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function addNavPathNode(summary, stateGuess, imagePath) {
  navPathCounter += 1;
  const id = `page-${navPathCounter}`;
  const label = stateGuess || summary?.slice(0, 30) || `Page ${navPathCounter}`;
  const node = {
    id,
    label: String(label).slice(0, 40),
    summary: String(summary || ""),
    stateGuess: String(stateGuess || ""),
    imagePath: imagePath || currentImagePath || "",
    timestamp: formatPathTime(),
    controls: [],
  };
  navPathNodes.push(node);

  // Connect pending transition edge and mark the source control as navigated
  if (pendingTransition && currentNavNodeId) {
    navPathEdges.push({
      from: pendingTransition.from,
      to: id,
      goal: pendingTransition.goal || "",
      action: pendingTransition.action || "",
    });
    // Mark the clicked control on the source page
    const sourcePage = navPathNodes.find((n) => n.id === pendingTransition.from);
    if (sourcePage && pendingTransition.controlLabel) {
      const ctrl = sourcePage.controls.find((c) => c.label === pendingTransition.controlLabel);
      if (ctrl) {
        ctrl.status = "clicked";
        ctrl.navigatedToPageId = id;
      }
    }
  }

  pendingTransition = null;
  currentNavNodeId = id;
  navPathDirty = true;
  liveSessionSnapshot = null;  // modifications invalidate history view
  renderNavPath();
  return node;
}

/* 鈹€鈹€ Controls management 鈹€鈹€ */

const PATH_CANVAS_FONT = '"Segoe UI", "Microsoft YaHei", Arial, sans-serif';

function normalizeBBox(bbox) {
  if (!bbox || typeof bbox !== "object") return null;
  const x = Number(bbox.x ?? bbox.left ?? bbox.x1 ?? bbox[0]);
  const y = Number(bbox.y ?? bbox.top ?? bbox.y1 ?? bbox[1]);
  const right = Number(bbox.right ?? bbox.x2);
  const bottom = Number(bbox.bottom ?? bbox.y2);
  const width = Number(bbox.width ?? bbox.w ?? (Number.isFinite(right) ? right - x : bbox[2]));
  const height = Number(bbox.height ?? bbox.h ?? (Number.isFinite(bottom) ? bottom - y : bbox[3]));
  if (![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) return null;
  return { x, y, width, height };
}

function normalizePoint(point, bbox = null) {
  if (point && typeof point === "object") {
    const x = Number(point.x ?? point[0]);
    const y = Number(point.y ?? point[1]);
    if (Number.isFinite(x) && Number.isFinite(y)) return { x, y };
  }
  const box = normalizeBBox(bbox);
  return box ? { x: box.x + box.width / 2, y: box.y + box.height / 2 } : null;
}

function compactText(value, limit = 80) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, limit);
}

function firstText(...values) {
  for (const value of values) {
    if (Array.isArray(value)) {
      const joined = value.map((item) => typeof item === "string" ? item : JSON.stringify(item)).filter(Boolean).join("; ");
      if (joined) return joined;
    } else if (value !== undefined && value !== null && String(value).trim()) {
      return String(value);
    }
  }
  return "";
}

function controlLabel(ctrl) {
  return firstText(
    ctrl.label,
    ctrl.text,
    ctrl.name,
    ctrl.title,
    ctrl.accessible_name,
    ctrl.ocr_text,
    ctrl.role_guess,
    ctrl.role,
    ctrl.type,
  );
}

function controlPossibleNav(ctrl) {
  return firstText(
    ctrl.possibleNav,
    ctrl.possible_navigation,
    ctrl.possible_destinations,
    ctrl.destination,
    ctrl.next_state,
    ctrl.expected_result,
    ctrl.expected_changes,
    ctrl.verification_hints?.expected_changes,
    ctrl.evidence?.verification_hints?.expected_changes,
  );
}

function collectArray(value) {
  return Array.isArray(value) ? value : [];
}

function collectControlsFromResult(result) {
  const sources = [
    collectArray(result.screen_map?.candidates),
    collectArray(result.controls),
    collectArray(result.elements),
    collectArray(result.regions),
    collectArray(result.targets),
    collectArray(result.ui?.elements),
    collectArray(result.ui?.controls),
    collectArray(result.screen_reading?.controls),
    collectArray(result.screen_reading?.elements),
    collectArray(result.screen_reading?.regions),
    collectArray(result.screen_reading?.ui?.elements),
    collectArray(result.parse_result?.screen_reading?.controls),
    collectArray(result.parse_result?.screen_reading?.elements),
    collectArray(result.parse_result?.screen_reading?.ui?.elements),
    collectArray(result.parse_result?.page_structure?.elements),
    collectArray(result.parse_result?.vision_regions?.regions),
    collectArray(result.parse_result?.vision_regions?.targets),
  ];

  const seen = new Set();
  const controls = [];
  for (const source of sources) {
    for (const ctrl of source) {
      if (!ctrl || typeof ctrl !== "object") continue;
      const label = compactText(controlLabel(ctrl), 80);
      if (!label) continue;
      const bbox = normalizeBBox(ctrl.bbox || ctrl.bounding_box || ctrl.bounds || ctrl.rect || ctrl.region);
      const key = `${label}|${bbox ? [Math.round(bbox.x), Math.round(bbox.y), Math.round(bbox.width), Math.round(bbox.height)].join(",") : ""}`;
      if (seen.has(key)) continue;
      seen.add(key);
      controls.push(ctrl);
    }
  }
  return controls;
}

function addControlToCurrentPage(label, bbox, point, type, description, extra = {}) {
  if (!currentNavNodeId) return;
  const page = navPathNodes.find((n) => n.id === currentNavNodeId);
  if (!page) return;

  const normalizedLabel = compactText(label, 80);
  if (!normalizedLabel) return;
  const normalizedBbox = normalizeBBox(bbox);
  const normalizedPoint = normalizePoint(point, normalizedBbox);
  const normalizedDescription = compactText(description || extra.description, 160);

  // Avoid duplicate controls on same page
  const existing = page.controls.find((c) => c.label === normalizedLabel);
  if (existing) {
    // Update with latest coordinates
    if (normalizedBbox) existing.bbox = normalizedBbox;
    if (normalizedPoint) existing.clickPoint = normalizedPoint;
    if (normalizedDescription) existing.description = normalizedDescription;
    if (extra.possibleNav) existing.possibleNav = extra.possibleNav;
    if (extra.action) existing.action = extra.action;
    if (extra.confidence !== undefined) existing.confidence = extra.confidence;
    if (extra.sectionId) existing.sectionId = extra.sectionId;
    if (extra.candidateId) existing.candidateId = extra.candidateId;
    if (extra.pathMapReview) existing.pathMapReview = extra.pathMapReview;
    return;
  }

  page.controls.push({
    label: normalizedLabel,
    bbox: normalizedBbox,
    clickPoint: normalizedPoint,
    type: type || "button",
    description: normalizedDescription,
    status: "unclicked",
    clickGoal: null,
    clickScreenshot: null,
    navigatedToPageId: null,
    possibleNav: compactText(extra.possibleNav, 160),
    action: compactText(extra.action, 80),
    source: compactText(extra.source, 60),
    sectionId: compactText(extra.sectionId, 80),
    confidence: extra.confidence ?? null,
    candidateId: compactText(extra.candidateId, 100),
    pathMapReview: extra.pathMapReview || null,
  });
  navPathDirty = true;
  liveSessionSnapshot = null;
}

function applyPathMapReview(review) {
  if (!review || review.contract_version !== "path_map_review_v1" || review.status !== "ready") return;
  if (!currentNavNodeId) return;
  const page = navPathNodes.find((n) => n.id === currentNavNodeId);
  if (!page || !Array.isArray(page.controls)) return;

  let changed = false;
  for (const removal of collectArray(review.removals)) {
    const before = page.controls.length;
    page.controls = page.controls.filter((control) => !pathReviewRemovalMatchesControl(removal, control));
    if (page.controls.length !== before) changed = true;
  }

  for (const addition of collectArray(review.additions)) {
    const label = addition.label || addition.candidate_id || "";
    if (!label) continue;
    addControlToCurrentPage(label, addition.bbox, addition.click_point, addition.role || addition.type || "button", addition.expected_effect || "", {
      action: "click",
      candidateId: addition.candidate_id,
      confidence: addition.confidence,
      pathMapReview: { action: "add", source: review.review_source, stateId: review.state_id },
      possibleNav: controlPossibleNav(addition) || addition.expected_effect,
      sectionId: addition.section_id,
      source: addition.source || "locate_path_review",
    });
    changed = true;
  }

  page.pathMapReview = {
    sourceTracePath: review.source_trace_path || "",
    stateId: review.state_id || "",
    summary: review.summary || {},
    scope: review.scope || "",
    updatedAt: new Date().toISOString(),
  };
  if (changed) {
    navPathDirty = true;
    liveSessionSnapshot = null;
    renderNavPath();
  }
}

function pathReviewRemovalMatchesControl(removal, control) {
  if (!removal || !control) return false;
  if (control.status === "clicked" || control.navigatedToPageId) return false;
  const source = String(control.source || "");
  const removableSource = !source || ["observe", "screen_map", "locate_path_review", "locate_candidate"].includes(source);
  if (!removableSource) return false;

  const removalId = compactText(removal.candidate_id || removal.id, 100);
  if (removalId && control.candidateId && removalId === control.candidateId) return true;

  const labelMatch = pathReviewLabelKey(removal.label) && pathReviewLabelKey(removal.label) === pathReviewLabelKey(control.label);
  if (!labelMatch) return false;
  const removalBox = normalizeBBox(removal.bbox);
  const controlBox = normalizeBBox(control.bbox);
  if (!removalBox || !controlBox) return true;
  return pathReviewBboxSimilarity(removalBox, controlBox) >= 0.45;
}

function pathReviewBboxSimilarity(a, b) {
  const x1 = Math.max(a.x, b.x);
  const y1 = Math.max(a.y, b.y);
  const x2 = Math.min(a.x + a.width, b.x + b.width);
  const y2 = Math.min(a.y + a.height, b.y + b.height);
  const overlap = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  const union = a.width * a.height + b.width * b.height - overlap;
  const iou = union > 0 ? overlap / union : 0;
  const acx = a.x + a.width / 2;
  const acy = a.y + a.height / 2;
  const bcx = b.x + b.width / 2;
  const bcy = b.y + b.height / 2;
  const distance = Math.hypot(acx - bcx, acy - bcy);
  const maxSize = Math.max(a.width, a.height, b.width, b.height, 1);
  return Math.max(iou, Math.max(0, 1 - distance / maxSize) * 0.8);
}

function pathReviewLabelKey(value) {
  return String(value || "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
}

function markControlClicked(goal, success, screenshot) {
  if (!currentNavNodeId) return;
  const page = navPathNodes.find((n) => n.id === currentNavNodeId);
  if (!page) return;

  // Find the most recently added unclicked control that matches the goal
  const ctrl = page.controls.findLast((c) => c.status === "unclicked" && (c.label === goal || c.description?.includes(goal) || goal?.includes(c.label)));
  if (ctrl) {
    ctrl.status = "clicked";
    ctrl.clickGoal = goal || "";
    ctrl.clickScreenshot = screenshot || currentImagePath || "";
    navPathDirty = true;
    return ctrl;
  }
  return null;
}

/* 鈹€鈹€ Save / Load 鈹€鈹€ */

const PATH_STORAGE_PREFIX = "navPath_";

function buildPathGraphPayload() {
  if (!navPathAppName) {
    navPathAppName = $("locateApp")?.value || $("observeApp")?.value || "unknown";
  }
  return {
    format_version: "nav_path_graph_v1",
    app_name: navPathAppName,
    saved_at: new Date().toISOString(),
    summary: `${navPathNodes.length} pages, ${navPathEdges.length} transitions`,
    pages: navPathNodes.map((n) => ({
      id: n.id,
      label: n.label,
      screen_summary: n.summary,
      state_guess: n.stateGuess,
      screenshot_path: n.imagePath,
      timestamp: n.timestamp,
      controls: (n.controls || []).map((c) => ({
        label: c.label,
        type: c.type,
        description: c.description,
        bbox: c.bbox,
        click_point: c.clickPoint,
        status: c.status,
        click_goal: c.clickGoal || null,
        click_screenshot: c.clickScreenshot || null,
        navigated_to_page_id: c.navigatedToPageId || null,
        possible_navigation: c.possibleNav || "",
        section_id: c.sectionId || "",
        action: c.action || "",
        source: c.source || "",
        candidate_id: c.candidateId || "",
        confidence: c.confidence,
      })),
      path_map_review: n.pathMapReview || null,
    })),
    transitions: navPathEdges.map((e) => ({
      from_page: e.from,
      to_page: e.to,
      goal: e.goal,
      action: e.action,
    })),
  };
}

function savePathGraph() {
  if (!navPathNodes.length) return;
  // Show Save-As dialog
  const defaultName = safeFileStem(navPathAppName) || "path_graph";
  $("saveAsFileName").value = defaultName;
  $("saveAsOverlay").style.display = "flex";
  $("saveAsFileName").focus();
  $("saveAsFileName").select();
}

function confirmSaveAs() {
  let name = $("saveAsFileName").value.trim();
  if (!name) {
    name = safeFileStem(navPathAppName) || "path_graph";
  }
  // Ensure .json extension
  if (!name.endsWith(".json")) name += ".json";

  const payload = buildPathGraphPayload();
  const json = JSON.stringify(payload, null, 2);

  // POST to backend and save to artifacts/path-graphs/<name>.
  api("POST", "/panel/save_path_graph", { file_name: name, payload }, { summary: "save path graph" })
    .then(() => {
      // Also persist to localStorage for history dropdown
      const key = PATH_STORAGE_PREFIX + navPathAppName;
      try { localStorage.setItem(key, json); } catch (e) { /* ignore */ }
      populatePathHistory();
      navPathDirty = false;
      const btn = $("savePathBtn");
      if (btn) { btn.classList.add("saved"); setTimeout(() => btn.classList.remove("saved"), 2000); }
    });

  $("saveAsOverlay").style.display = "none";
}

function cancelSaveAs() {
  $("saveAsOverlay").style.display = "none";
}

function loadPathGraph(appName) {
  if (!appName) return null;
  const key = PATH_STORAGE_PREFIX + appName;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const data = JSON.parse(raw);
    return normalizePathData(data);
  } catch (e) {
    return null;
  }
}

function normalizePathData(data) {
  // Support both legacy format (nodes/edges) and new format (pages/transitions)
  if (data.pages && !data.nodes) {
    data.nodes = data.pages;
    delete data.pages;
  }
  if (data.transitions && !data.edges) {
    data.edges = data.transitions;
    delete data.transitions;
  }
  if (data.app_name && !data.appName) {
    data.appName = data.app_name;
  }
  if (Array.isArray(data.nodes)) {
    data.nodes = data.nodes.map((node) => ({
      ...node,
      controls: Array.isArray(node.controls)
        ? node.controls.map((control) => ({
            ...control,
            candidateId: control.candidateId || control.candidate_id || "",
            clickPoint: control.clickPoint || control.click_point || null,
            navigatedToPageId: control.navigatedToPageId || control.navigated_to_page_id || null,
            possibleNav: control.possibleNav || control.possible_navigation || "",
            sectionId: control.sectionId || control.section_id || "",
          }))
        : [],
      pathMapReview: node.pathMapReview || node.path_map_review || null,
    }));
  }
  return data;
}

function restorePathGraph(appName) {
  const data = loadPathGraph(appName);
  if (!data || !data.nodes?.length) return false;

  navPathNodes = data.nodes || [];
  navPathEdges = data.edges || [];
  navPathCounter = data.counter || navPathNodes.length;
  navPathAppName = data.appName || appName;
  currentNavNodeId = navPathNodes.length ? navPathNodes[navPathNodes.length - 1].id : null;
  pendingTransition = null;
  navPathDirty = false;
  renderNavPath();
  updatePathAppLabel();
  return true;
}

function updatePathAppLabel() {
  const label = $("pathAppLabel");
  if (label) {
    label.textContent = navPathAppName || "";
  }
  const saveBtn = $("savePathBtn");
  if (saveBtn) {
    saveBtn.classList.toggle("saved", !navPathDirty);
  }
}

function markPendingTransition(goal, action, controlLabel) {
  if (!currentNavNodeId) return;
  pendingTransition = { from: currentNavNodeId, goal: goal || "", action: action || "", controlLabel: controlLabel || "" };
  renderNavPath();
}

function clearNavPath() {
  navPathNodes = [];
  navPathEdges = [];
  currentNavNodeId = null;
  pendingTransition = null;
  navPathCounter = 0;
  navPathAppName = "";
  navPathDirty = false;
  liveSessionSnapshot = null;
  pathNodePositions = [];
  pathHoveredNode = null;
  updatePathAppLabel();
  renderNavPath();
  // Clear the detail panel too
  const content = $("pathDetailContent");
  if (content) content.innerHTML = `<p class="path-detail-empty">${t("path_detail_empty")}</p>`;
  const meta = $("pathDetailMeta");
  if (meta) meta.textContent = "";
}

/* 鈹€鈹€ Trace inspector 鈹€鈹€ */

let traceFileList = [];
let traceStageData = [];

function refreshTraceList() {
  fetch(`${baseUrl()}/panel/list_traces?limit=60`).then((r) => r.json()).then((resp) => {
    const data = resp.data || resp;
    traceFileList = (data && data.traces) ? data.traces : [];
    populateTraceSelect();
  }).catch(() => {});
}

function populateTraceSelect() {
  const sel = $("traceFileSelect");
  if (!sel) return;
  const currentVal = sel.value;
  sel.innerHTML = '<option value="">-- auto latest --</option>';
  for (const t of traceFileList) {
    const opt = document.createElement("option");
    opt.value = t.path;
    const cat = t.category ? `[${t.category}] ` : "";
    opt.textContent = `${cat}${t.name}`;
    sel.appendChild(opt);
  }
  // Restore previous selection or set to latest trace path
  if (currentVal && traceFileList.some((t) => t.path === currentVal)) {
    sel.value = currentVal;
  } else if (lastTracePath && traceFileList.some((t) => t.path === lastTracePath)) {
    sel.value = lastTracePath;
  }
}

function inspectLatestTrace(tracePath) {
  if (!tracePath) return;
  const url = `${baseUrl()}/panel/inspect_trace?path=${encodeURIComponent(tracePath)}`;
  fetch(url).then((r) => r.json()).then((resp) => {
    const data = resp.data || resp;
    if (!data || resp.success === false) {
      renderTraceDetail(data, { error: resp.message || "parse failed" });
      return;
    }
    renderTraceDetail(data);
    // Update the dropdown to match
    const sel = $("traceFileSelect");
    if (sel && sel.value !== tracePath && traceFileList.some((t) => t.path === tracePath)) {
      sel.value = tracePath;
    }
  }).catch((e) => {
    renderTraceDetail(null, { error: e.message });
  });
}

function loadSelectedTrace() {
  const path = $("traceFileSelect").value;
  if (!path) {
    if (lastTracePath) { inspectLatestTrace(lastTracePath); return; }
    renderTraceDetail(null, {});
    return;
  }
  inspectLatestTrace(path);
}

function traceDisplayValue(value, fallback = "未记录") {
  if (value === undefined || value === null) return fallback;
  const text = String(value).trim();
  return text && text !== "?" ? text : fallback;
}

function isTraceImagePath(key, value) {
  if (typeof value !== "string" || !value.trim()) return false;
  const lowerKey = String(key || "").toLowerCase();
  const lowerValue = value.toLowerCase();
  const imageLikeKey = /(image|screenshot|capture|overlay|crop|frame).*path$|^output_path$/.test(lowerKey);
  const imageLikeValue = /\.(png|jpe?g|webp|bmp)$/i.test(lowerValue);
  return imageLikeKey && imageLikeValue;
}

function traceImageUrl(path) {
  const text = String(path || "");
  if (/^https?:\/\//i.test(text) || text.startsWith("data:")) return text;
  return `${baseUrl()}/panel/file?path=${encodeURIComponent(text)}`;
}

function collectTraceStageVisuals(raw) {
  const images = [];
  const boxes = [];
  const points = [];
  const seenImages = new Set();

  function visit(value, key = "", trail = "", depth = 0) {
    if (depth > 8 || value === null || value === undefined) return;
    if (isTraceImagePath(key, value)) {
      const path = String(value);
      if (!seenImages.has(path)) {
        seenImages.add(path);
        images.push({ path, label: trail || key || basename(path) });
      }
      return;
    }
    if (Array.isArray(value)) {
      value.slice(0, 200).forEach((item, index) => visit(item, key, `${trail}[${index}]`, depth + 1));
      return;
    }
    if (typeof value !== "object") return;

    const lowerKey = String(key || "").toLowerCase();
    const box = normalizeBBox(value);
    if (box && /(bbox|box|rect|bounds|region|located|target|candidate)/.test(lowerKey)) {
      boxes.push({ ...box, label: trail || key || "bbox" });
    }
    const point = normalizePoint(value, null);
    if (point && /(point|click|coordinate|selected|center)/.test(lowerKey)) {
      points.push({ ...point, label: trail || key || "point" });
    }

    for (const [childKey, childValue] of Object.entries(value)) {
      const childTrail = trail ? `${trail}.${childKey}` : childKey;
      visit(childValue, childKey, childTrail, depth + 1);
    }
  }

  visit(raw);
  return images.map((image) => ({ ...image, boxes, points }));
}

function traceStageVisualsHtml(visuals) {
  if (!visuals.length) return "";
  return `
    <div class="tf-stage-visuals">
      <h5>图片 / 坐标预览</h5>
      ${visuals.map((visual, index) => `
        <div class="tf-stage-visual" data-visual-index="${index}">
          <div class="tf-stage-visual-head">
            <span>${escapeHtml(basename(visual.path))}</span>
            <a href="${escapeHtml(traceImageUrl(visual.path))}" target="_blank" rel="noreferrer">Open</a>
          </div>
          <div class="tf-stage-image-wrap">
            <img class="tf-stage-image" src="${escapeHtml(traceImageUrl(visual.path))}" alt="${escapeHtml(basename(visual.path))}" data-visual-index="${index}">
            <canvas class="tf-stage-overlay" data-visual-index="${index}"></canvas>
            <div class="tf-stage-image-missing">图片不存在：${escapeHtml(visual.path)}</div>
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function drawTraceVisualOverlay(wrapper, visual) {
  const img = wrapper.querySelector(".tf-stage-image");
  const canvas = wrapper.querySelector(".tf-stage-overlay");
  if (!img || !canvas || !img.naturalWidth || !img.naturalHeight) return;

  const displayWidth = img.clientWidth;
  const displayHeight = img.clientHeight;
  if (!displayWidth || !displayHeight) return;

  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(displayWidth * dpr);
  canvas.height = Math.round(displayHeight * dpr);
  canvas.style.width = `${displayWidth}px`;
  canvas.style.height = `${displayHeight}px`;

  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, displayWidth, displayHeight);
  const sx = displayWidth / img.naturalWidth;
  const sy = displayHeight / img.naturalHeight;

  for (const box of (visual.boxes || []).slice(0, 120)) {
    const x = box.x * sx;
    const y = box.y * sy;
    const w = box.width * sx;
    const h = box.height * sy;
    ctx.fillStyle = "rgba(21, 94, 239, 0.12)";
    ctx.strokeStyle = "rgba(21, 94, 239, 0.98)";
    ctx.lineWidth = 3;
    ctx.fillRect(x, y, w, h);
    ctx.strokeRect(x, y, w, h);
    const label = String(box.label || "bbox").split(".").slice(-2).join(".");
    if (label) {
      ctx.font = "12px Microsoft YaHei, Arial, sans-serif";
      const textWidth = Math.min(ctx.measureText(label).width + 10, 220);
      const labelY = Math.max(0, y - 19);
      ctx.fillStyle = "rgba(21, 94, 239, 0.96)";
      ctx.fillRect(x, labelY, textWidth, 18);
      ctx.fillStyle = "#fff";
      ctx.fillText(label.slice(0, 28), x + 5, labelY + 13);
    }
  }

  for (const point of (visual.points || []).slice(0, 80)) {
    const x = point.x * sx;
    const y = point.y * sy;
    ctx.beginPath();
    ctx.arc(x, y, 7, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(244, 63, 94, 0.95)";
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 3;
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x - 14, y);
    ctx.lineTo(x + 14, y);
    ctx.moveTo(x, y - 14);
    ctx.lineTo(x, y + 14);
    ctx.strokeStyle = "rgba(244, 63, 94, 0.9)";
    ctx.lineWidth = 2;
    ctx.stroke();
    const label = String(point.label || "point").split(".").slice(-2).join(".");
    ctx.font = "12px Microsoft YaHei, Arial, sans-serif";
    ctx.fillStyle = "rgba(244, 63, 94, 0.96)";
    ctx.fillRect(x + 10, Math.max(0, y - 22), Math.min(ctx.measureText(label).width + 10, 220), 18);
    ctx.fillStyle = "#fff";
    ctx.fillText(label.slice(0, 28), x + 15, Math.max(13, y - 9));
  }
}

function activateTraceStageVisuals(visuals, root) {
  if (!visuals.length || !root) return;
  root.querySelectorAll(".tf-stage-visual").forEach((wrapper) => {
    const index = Number(wrapper.dataset.visualIndex || 0);
    const visual = visuals[index];
    const img = wrapper.querySelector(".tf-stage-image");
    const missing = wrapper.querySelector(".tf-stage-image-missing");
    if (!img || !visual) return;
    const draw = () => {
      wrapper.classList.remove("missing");
      if (missing) missing.style.display = "none";
      drawTraceVisualOverlay(wrapper, visual);
    };
    img.addEventListener("load", draw);
    img.addEventListener("error", () => {
      wrapper.classList.add("missing");
      if (missing) missing.style.display = "grid";
    });
    if (img.complete && img.naturalWidth) draw();
  });
}

function renderTraceDetail(data, opts = {}) {
  const leftEl = $("traceDetail");
  const fullEl = $("traceFullContent");
  const metaEl = $("traceFullMeta");
  traceStageData = [];

  if (opts.error || (data && data.error)) {
    const errMsg = opts.error || (data && data.error) || "unknown";
    if (leftEl) leftEl.innerHTML = `<p class="trace-idle" style="color:#f04438;">${escapeHtml(String(errMsg))}</p>`;
    if (fullEl) fullEl.innerHTML = `<p class="trace-idle" style="color:#f04438;">${escapeHtml(String(errMsg))}</p>`;
    return;
  }

  if (!data) {
    if (leftEl) leftEl.innerHTML = '<p class="trace-idle">Select a trace file or run an API request to auto-load the latest trace</p>';
    if (fullEl) fullEl.innerHTML = '<p class="trace-idle">No trace loaded</p>';
    return;
  }

  const flowStages = Array.isArray(data.flow_stages) ? data.flow_stages : [];
  traceStageData = flowStages;
  if (leftEl) {
    const summaryParts = [];
    if (data.file) summaryParts.push(`<strong>${escapeHtml(data.file)}</strong>`);
    if (data.contract) summaryParts.push(`<span>${escapeHtml(data.contract)}</span>`);
    if (data.total_time) summaryParts.push(`<span>${escapeHtml(data.total_time)}</span>`);
    if (data.goal) summaryParts.push(`<span>${escapeHtml(String(data.goal).slice(0, 48))}</span>`);
    leftEl.innerHTML = `<div class="trace-summary-compact">${summaryParts.join("") || '<span>Trace loaded</span>'}</div>`;
  }

  if (!fullEl || !metaEl) return;
  metaEl.textContent = data.file || "";
  let html = '<div class="trace-flow">';
  html += '<div class="trace-flow-line">';
  if (flowStages.length) {
    flowStages.forEach((stage, i) => {
      const statusClass = stage.status === "blocked" ? "tf-block" : stage.status === "error" ? "tf-err" : "tf-ok";
      html += `<button type="button" class="tf-node ${statusClass}" data-tf-stage="${escapeHtml(stage.id)}" title="Click for details">
        <span class="tf-label">${escapeHtml(stage.label || stage.id)}</span>
        <span class="tf-val">${escapeHtml(stage.value || "")}</span>
      </button>`;
      if (i < flowStages.length - 1) html += '<div class="tf-arrow">-&gt;</div>';
    });
  } else {
    html += '<p class="trace-idle">This trace has no parsed stages.</p>';
  }
  html += '</div>';
  html += '<div class="tf-stage-details" id="tfStageDetails" style="display:none;"></div>';

  if (data.stages && data.stages.length) {
    const maxMs = Math.max(1, ...data.stages.map((s) => s.ms || 0));
    html += '<div class="tf-section"><h5>Stage timings</h5><div class="tf-bars">';
    for (const s of data.stages) {
      const ms = s.ms || 0;
      const pct = Math.max(2, Math.round(ms / maxMs * 100));
      html += `<div class="tf-bar-row">
        <span class="tf-bar-name">${escapeHtml(String(s.name).slice(0, 28))}</span>
        <span class="tf-bar-track"><span class="tf-bar-fill" style="width:${pct}%"></span></span>
        <span class="tf-bar-ms">${ms}ms</span>
      </div>`;
    }
    html += '</div></div>';
  }

  if (data.screen_summary) html += `<div class="tf-section"><h5>Screen understanding</h5><p>${escapeHtml(String(data.screen_summary).slice(0, 800))}</p></div>`;
  if (data.state_guess) html += `<div class="tf-section"><h5>State guess</h5><code>${escapeHtml(data.state_guess)}</code></div>`;
  if (data.gate_reason) html += `<div class="tf-section"><h5>Gate decision</h5><p>${escapeHtml(String(data.gate_reason).slice(0, 600))}</p></div>`;
  if (data.errors && data.errors.length) {
    html += '<div class="tf-section tf-errors"><h5>Errors</h5>';
    html += data.errors.map((e) => `<p class="tf-err-item">${escapeHtml(String(e).slice(0, 500))}</p>`).join("");
    html += '</div>';
  }
  html += `<div class="tf-section tf-meta">
    <span>Total: ${escapeHtml(traceDisplayValue(data.total_time))}</span>
    <span>Contract: ${escapeHtml(traceDisplayValue(data.contract))}</span>
    <span>Provider: ${escapeHtml(traceDisplayValue(data.provider || data.model_provider))}</span>
    <span>File: ${escapeHtml(traceDisplayValue(data.file))}</span>
  </div>`;
  html += '</div>';
  fullEl.innerHTML = html;
  fullEl.querySelectorAll(".tf-node").forEach((node) => node.addEventListener("click", toggleTraceStageDetail));
}
let _pathResizeObserver = null;

function startPathResizeObserver() {
  if (_pathResizeObserver) return;
  if (!pathCanvas) return;
  _pathResizeObserver = new ResizeObserver(() => {
    resizePathCanvas();
  });
  _pathResizeObserver.observe(pathCanvas.parentElement);
}

/* 鈹€鈹€ Canvas spider-web path graph 鈹€鈹€ */

const PATH_NODE_R = 20;
const PATH_GLOW_R = 32;
const PATH_LABEL_DY = 34;

let pathCanvas = null;
let pathCtx = null;
let pathAnimId = 0;
let pathAnimT = 0;
let pathHoveredNode = null;
let pathNodePositions = [];
let pathZoom = 1.0;
let pathPanX = 0;
let pathPanY = 0;
let pathDragging = false;
let pathDragStart = { x: 0, y: 0 };
let pathDragPanStart = { x: 0, y: 0 };

let pathContextNode = null;  // node id under right-click

function ensurePathCanvas() {
  if (!pathCanvas) {
    pathCanvas = $("navPathCanvas");
    if (!pathCanvas) return false;
    pathCtx = pathCanvas.getContext("2d");
    pathCanvas.addEventListener("mousemove", onPathCanvasMouse);
    pathCanvas.addEventListener("mousedown", onPathCanvasDown);
    pathCanvas.addEventListener("mouseup", onPathCanvasUp);
    pathCanvas.addEventListener("mouseleave", onPathCanvasLeave);
    pathCanvas.addEventListener("wheel", onPathCanvasWheel, { passive: false });
    pathCanvas.addEventListener("contextmenu", onPathCanvasContext);
  }
  return true;
}

function onPathCanvasContext(e) {
  e.preventDefault();
  if (!pathHoveredNode || pathHoveredNode === "__pending__") return;
  pathContextNode = pathHoveredNode;
  showPathContextMenu(e.clientX, e.clientY);
}

function showPathContextMenu(x, y) {
  removePathContextMenu();
  const menu = document.createElement("div");
  menu.id = "pathContextMenu";
  menu.className = "path-context-menu";
  menu.style.left = x + "px";
  menu.style.top = y + "px";
  menu.innerHTML = '<button id="ctxDeleteNode">Delete node</button>';
  document.body.appendChild(menu);
  menu.querySelector("#ctxDeleteNode").addEventListener("click", () => {
    deletePathNode(pathContextNode);
    removePathContextMenu();
  });
  // Close on click outside
  setTimeout(() => {
    document.addEventListener("click", removePathContextMenu, { once: true });
  }, 0);
}

function removePathContextMenu() {
  const menu = document.getElementById("pathContextMenu");
  if (menu) menu.remove();
}

function deletePathNode(nodeId) {
  const idx = navPathNodes.findIndex((n) => n.id === nodeId);
  if (idx === -1) return;
  // Remove edges connected to this node
  navPathEdges = navPathEdges.filter((e) => e.from !== nodeId && e.to !== nodeId);
  // Remove the node
  navPathNodes.splice(idx, 1);
  // Update current node
  if (currentNavNodeId === nodeId) {
    currentNavNodeId = navPathNodes.length ? navPathNodes[navPathNodes.length - 1].id : null;
  }
  // Clear pending transition if source was deleted
  if (pendingTransition && pendingTransition.from === nodeId) {
    pendingTransition = null;
  }
  navPathDirty = true;
  renderNavPath();
  // Clear detail panel
  const content = $("pathDetailContent");
  if (content) content.innerHTML = `<p class="path-detail-empty">${t("path_detail_empty")}</p>`;
}

function updateZoomLabel() {
  const label = $("pathZoomLabel");
  if (label) label.textContent = Math.round(pathZoom * 100) + "%";
}

function resizePathCanvas() {
  if (!pathCanvas) return;
  const wrap = pathCanvas.parentElement;
  if (!wrap) return;
  const rect = wrap.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = rect.width;
  const h = rect.height;
  if (w <= 0 || h <= 0) return;
  if (pathCanvas.width === w * dpr && pathCanvas.height === h * dpr) return; // no change
  pathCanvas.width = w * dpr;
  pathCanvas.height = h * dpr;
  if (pathCtx) pathCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function onPathCanvasWheel(e) {
  e.preventDefault();
  const oldZoom = pathZoom;
  pathZoom = Math.max(0.3, Math.min(3.0, pathZoom - e.deltaY * 0.002));
  // Zoom toward mouse position
  const rect = pathCanvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  pathPanX = mx - (mx - pathPanX) * (pathZoom / oldZoom);
  pathPanY = my - (my - pathPanY) * (pathZoom / oldZoom);
}

function onPathCanvasDown(e) {
  pathDragging = true;
  pathDragStart = { x: e.clientX, y: e.clientY };
  pathDragPanStart = { x: pathPanX, y: pathPanY };
  pathCanvas.style.cursor = "grabbing";
}

function onPathCanvasUp(e) {
  if (pathDragging) {
    const dx = e.clientX - pathDragStart.x;
    const dy = e.clientY - pathDragStart.y;
    // If barely moved, treat as click
    if (Math.abs(dx) < 3 && Math.abs(dy) < 3 && pathHoveredNode && pathHoveredNode !== "__pending__") {
      showNavNodeDetail(pathHoveredNode);
    }
  }
  pathDragging = false;
  pathCanvas.style.cursor = pathHoveredNode ? "pointer" : "grab";
}

function onPathCanvasLeave() {
  pathDragging = false;
  pathHoveredNode = null;
  pathCanvas.style.cursor = "grab";
}

function onPathCanvasMouse(e) {
  const rect = pathCanvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  if (pathDragging) {
    pathPanX = pathDragPanStart.x + (e.clientX - pathDragStart.x);
    pathPanY = pathDragPanStart.y + (e.clientY - pathDragStart.y);
    return;
  }

  if (!pathNodePositions.length) return;
  // Transform screen coords to world coords
  const wx = (mx - pathPanX) / pathZoom;
  const wy = (my - pathPanY) / pathZoom;

  let found = null;
  for (const pos of pathNodePositions) {
    const dx = wx - pos.x;
    const dy = wy - pos.y;
    if (Math.sqrt(dx * dx + dy * dy) < PATH_GLOW_R / pathZoom) {
      found = pos.id;
      break;
    }
  }
  pathHoveredNode = found;
  pathCanvas.style.cursor = found && found !== "__pending__" ? "pointer" : pathDragging ? "grabbing" : "grab";
}

function layoutPathNodes() {
  const w = pathCanvas ? pathCanvas.clientWidth : 600;
  const h = pathCanvas ? pathCanvas.clientHeight : 300;
  const cx = w / 2;
  const cy = h / 2;
  const margin = 60;

  const count = navPathNodes.length + (pendingTransition ? 1 : 0);
  if (!count) return [];

  const allNodes = navPathNodes.map((n, i) => ({
    id: n.id,
    index: i,
    x: margin + ((w - margin * 2) / Math.max(1, count - 1)) * i + (Math.sin(i * 1.9) * 35),
    y: cy + Math.cos(i * 2.1) * 40 + Math.sin(i * 0.7) * 25,
    vx: 0, vy: 0,
    isCurrent: n.id === currentNavNodeId,
    isPending: false,
  }));

  if (pendingTransition && currentNavNodeId) {
    const i = allNodes.length;
    allNodes.push({
      id: "__pending__",
      index: i,
      x: margin + ((w - margin * 2) / Math.max(1, count - 1)) * i,
      y: cy + Math.cos(i * 2.1) * 35,
      vx: 0, vy: 0,
      isCurrent: false,
      isPending: true,
    });
  }

  // Force relaxation
  for (let iter = 0; iter < 30; iter++) {
    for (let i = 0; i < allNodes.length; i++) {
      const a = allNodes[i];
      for (let j = i + 1; j < allNodes.length; j++) {
        const b = allNodes[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
        const force = 2200 / (dist * dist);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx -= fx; a.vy -= fy;
        b.vx += fx; b.vy += fy;
      }
      if (i > 0) {
        const prev = allNodes[i - 1];
        const dx = prev.x - a.x;
        const dy = prev.y - a.y;
        const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
        const target = a.isPending ? 90 : 130;
        const force = (dist - target) * 0.05;
        a.vx += (dx / dist) * force;
        prev.vx -= (dx / dist) * force;
      }
      a.vy += (cy - a.y) * 0.006;
    }
    for (const node of allNodes) {
      node.x += node.vx * 0.3;
      node.y += node.vy * 0.3;
      node.vx *= 0.5;
      node.x = Math.max(margin, Math.min(w - margin, node.x));
      node.y = Math.max(margin / 2, Math.min(h - margin / 2, node.y));
    }
  }
  return allNodes;
}

function drawPathGraphFrame() {
  if (!pathCanvas || !pathCtx) return;
  const w = pathCanvas.clientWidth;
  const h = pathCanvas.clientHeight;
  const ctx = pathCtx;

  ctx.clearRect(0, 0, w, h);

  // Background
  ctx.fillStyle = "#0b1120";
  ctx.fillRect(0, 0, w, h);

  // Dot grid (world-space)
  ctx.save();
  ctx.translate(pathPanX, pathPanY);
  ctx.scale(pathZoom, pathZoom);
  ctx.fillStyle = "rgba(255, 255, 255, 0.025)";
  const gs = 24;
  for (let gx = gs; gx < w / pathZoom + gs; gx += gs) {
    for (let gy = gs; gy < h / pathZoom + gs; gy += gs) {
      ctx.beginPath();
      ctx.arc(gx - pathPanX / pathZoom, gy - pathPanY / pathZoom, 0.7, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();

  const overlay = $("pathEmptyOverlay");
  if (!navPathNodes.length && !pendingTransition) {
    if (overlay) overlay.style.display = "flex";
    ctx.fillStyle = "rgba(148, 163, 184, 0.4)";
    ctx.font = `italic 13px ${PATH_CANVAS_FONT}`;
    ctx.textAlign = "center";
    ctx.fillText(t("path_empty_hint") || "", w / 2, h / 2);
    return;
  }
  if (overlay) overlay.style.display = "none";

  const nodePositions = layoutPathNodes();
  pathNodePositions = nodePositions;

  // Apply zoom/pan
  ctx.save();
  ctx.translate(pathPanX, pathPanY);
  ctx.scale(pathZoom, pathZoom);

  // Edges
  const edges = [];
  for (let i = 1; i < nodePositions.length; i++) {
    const from = nodePositions[i - 1];
    const to = nodePositions[i];
    const edgeData = navPathEdges[i - 1] || (to.isPending && pendingTransition ? { goal: pendingTransition.goal } : null);
    edges.push({ from, to, goal: edgeData?.goal || "", isPending: to.isPending });
  }

  for (const edge of edges) {
    const { from, to, isPending } = edge;
    const mx = (from.x + to.x) / 2;
    const my = (from.y + to.y) / 2;
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
    const nx = -dy / dist;
    const ny = dx / dist;
    const cpx = mx + nx * Math.min(dist * 0.3, 50) * 0.4;
    const cpy = my + ny * Math.min(dist * 0.3, 50) * 0.4;

    // Edge
    const grad = ctx.createLinearGradient(from.x, from.y, to.x, to.y);
    grad.addColorStop(0, isPending ? "rgba(251,191,36,0.5)" : "rgba(99,160,255,0.6)");
    grad.addColorStop(1, isPending ? "rgba(251,191,36,0.1)" : "rgba(168,130,255,0.3)");
    ctx.strokeStyle = grad;
    ctx.lineWidth = isPending ? 1.6 : 2;
    ctx.setLineDash(isPending ? [7, 5] : []);
    if (isPending) ctx.lineDashOffset = -pathAnimT * 25;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.quadraticCurveTo(cpx, cpy, to.x, to.y);
    ctx.stroke();
    ctx.setLineDash([]);

    // Particles
    for (let p = 0; p < (isPending ? 2 : 3); p++) {
      const t = ((pathAnimT * 0.35 + p / (isPending ? 2 : 3)) % 1 + 1) % 1;
      const px = (1 - t) * (1 - t) * from.x + 2 * (1 - t) * t * cpx + t * t * to.x;
      const py = (1 - t) * (1 - t) * from.y + 2 * (1 - t) * t * cpy + t * t * to.y;
      ctx.beginPath();
      ctx.arc(px, py, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = isPending ? "rgba(251,191,36,0.85)" : "rgba(168,220,255,0.85)";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(px, py, 5, 0, Math.PI * 2);
      ctx.fillStyle = isPending ? "rgba(251,191,36,0.1)" : "rgba(99,160,255,0.08)";
      ctx.fill();
    }

    if (edge.goal) {
      ctx.fillStyle = "rgba(148,163,184,0.55)";
      ctx.font = `9px ${PATH_CANVAS_FONT}`;
      ctx.textAlign = "center";
      ctx.fillText(String(edge.goal).slice(0, 14), mx, my - 10);
    }
  }

  // Nodes
  for (const pos of nodePositions) {
    const node = pos.isPending ? null : navPathNodes.find((n) => n.id === pos.id);
    const isHovered = pathHoveredNode === pos.id;
    const r = isHovered ? PATH_NODE_R + 3 : PATH_NODE_R;
    const glowR = isHovered ? PATH_GLOW_R + 6 : PATH_GLOW_R;

    // Glow
    const gg = ctx.createRadialGradient(pos.x, pos.y, r * 0.5, pos.x, pos.y, glowR);
    if (pos.isCurrent) { gg.addColorStop(0, "rgba(59,130,246,0.5)"); gg.addColorStop(0.5, "rgba(59,130,246,0.12)"); gg.addColorStop(1, "rgba(59,130,246,0)"); }
    else if (pos.isPending) { gg.addColorStop(0, "rgba(251,191,36,0.4)"); gg.addColorStop(0.5, "rgba(251,191,36,0.1)"); gg.addColorStop(1, "rgba(251,191,36,0)"); }
    else { gg.addColorStop(0, "rgba(99,160,255,0.25)"); gg.addColorStop(1, "rgba(99,160,255,0)"); }
    ctx.beginPath(); ctx.arc(pos.x, pos.y, glowR, 0, Math.PI * 2); ctx.fillStyle = gg; ctx.fill();

    // Pulse ring
    if (pos.isCurrent) {
      const pr = r + 7 + Math.sin(pathAnimT * 3) * 3;
      ctx.beginPath(); ctx.arc(pos.x, pos.y, pr, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(59,130,246,${0.2 + Math.sin(pathAnimT*3)*0.1})`;
      ctx.lineWidth = 1.5; ctx.stroke();
    }
    if (pos.isPending) {
      ctx.beginPath(); ctx.arc(pos.x, pos.y, r + 6, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(251,191,36,0.3)"; ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]); ctx.lineDashOffset = -pathAnimT * 35; ctx.stroke(); ctx.setLineDash([]);
    }

    // Body
    const bg = ctx.createRadialGradient(pos.x - r * 0.3, pos.y - r * 0.3, r * 0.1, pos.x, pos.y, r);
    if (pos.isCurrent) { bg.addColorStop(0, "#60a5fa"); bg.addColorStop(0.6, "#2563eb"); bg.addColorStop(1, "#1d4ed8"); }
    else if (pos.isPending) { bg.addColorStop(0, "#fcd34d"); bg.addColorStop(0.6, "#f59e0b"); bg.addColorStop(1, "#b45309"); }
    else { bg.addColorStop(0, "#94a3b8"); bg.addColorStop(0.6, "#475569"); bg.addColorStop(1, "#1e293b"); }
    ctx.beginPath(); ctx.arc(pos.x, pos.y, r, 0, Math.PI * 2); ctx.fillStyle = bg; ctx.fill();
    ctx.strokeStyle = pos.isCurrent ? "rgba(147,197,253,0.7)" : pos.isPending ? "rgba(252,211,77,0.6)" : "rgba(148,163,184,0.35)";
    ctx.lineWidth = 1.3; ctx.stroke();

    // Number
    ctx.fillStyle = "#fff"; ctx.font = `bold ${pos.isPending ? 13 : 12}px ${PATH_CANVAS_FONT}`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(pos.isPending ? "?" : String(pos.index + 1), pos.x, pos.y);

    // Label
    const lbl = pos.isPending ? (pendingTransition?.goal?.slice(0, 22) || "") : (node?.label || "").slice(0, 22);
    ctx.fillStyle = pos.isCurrent ? "rgba(191,219,254,0.95)" : "rgba(203,213,225,0.75)";
    ctx.font = `${pos.isCurrent ? "bold " : ""}11px ${PATH_CANVAS_FONT}`;
    ctx.fillText(lbl, pos.x, pos.y + PATH_LABEL_DY);

    if (!pos.isPending && node?.summary) {
      ctx.fillStyle = "rgba(148,163,184,0.5)";
      ctx.font = `10px ${PATH_CANVAS_FONT}`;
      ctx.fillText(String(node.summary).slice(0, 26), pos.x, pos.y + PATH_LABEL_DY + 14);
    }
  }

  ctx.restore();
}

/* 鈹€鈹€ Path history 鈹€鈹€ */

function populatePathHistory() {
  const sel = $("pathHistorySelect");
  if (!sel) return;
  // Keep first option
  sel.innerHTML = '<option value="">-- live session --</option>';
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith(PATH_STORAGE_PREFIX)) continue;
      const appName = key.slice(PATH_STORAGE_PREFIX.length);
      const opt = document.createElement("option");
      opt.value = appName;
      opt.textContent = appName;
      sel.appendChild(opt);
    }
  } catch (e) { /* ignore localStorage errors */ }
}

function renderNavPath() {
  if (!ensurePathCanvas()) return;
  resizePathCanvas();
  // Reset zoom/pan
  pathZoom = 1.0;
  pathPanX = 0;
  pathPanY = 0;

  if (!pathAnimId) {
    function tick(ts) {
      pathAnimT = ts * 0.001;
      drawPathGraphFrame();
      pathAnimId = requestAnimationFrame(tick);
    }
    pathAnimId = requestAnimationFrame(tick);
  }
}

/* 鈹€鈹€ Fake test data 鈹€鈹€ */

function generateFakePathData() {
  navPathCounter = 0;
  navPathNodes = [];
  navPathEdges = [];
  currentNavNodeId = null;
  pendingTransition = null;
  navPathAppName = "MouseTesterWeb";

  const p1 = addNavPathNode(
    "A minimal mouse-testing utility. The main area shows mouse coordinates and click counts. A large button in the center labeled '鐐瑰嚮姝ゅ娴嬭瘯' triggers the test dialog. The title bar has minimize/maximize/close controls.",
    "MouseTester main page",
    ""
  );
  p1.controls = [
    { label: "鐐瑰嚮姝ゅ娴嬭瘯", bbox: { x: 320, y: 240, width: 160, height: 48 }, clickPoint: { x: 400, y: 264 }, type: "button", description: "Main test trigger button", status: "clicked", clickGoal: "鐐瑰嚮姝ゅ娴嬭瘯", clickScreenshot: "", navigatedToPageId: null },
    { label: "Mouse position display", bbox: { x: 100, y: 60, width: 600, height: 80 }, clickPoint: null, type: "label", description: "Shows current mouse X, Y and click count", status: "unclicked", possibleNav: "" },
    { label: "Reset counter", bbox: { x: 500, y: 310, width: 100, height: 30 }, clickPoint: { x: 550, y: 325 }, type: "button", description: "Resets the click counter to zero", status: "unclicked", possibleNav: "Refreshes the counter display" },
    { label: "Minimize", bbox: { x: 740, y: 4, width: 28, height: 24 }, clickPoint: { x: 754, y: 16 }, type: "titlebar-button", description: "Minimize window to taskbar", status: "unclicked", possibleNav: "Window minimized" },
    { label: "Close", bbox: { x: 770, y: 4, width: 28, height: 24 }, clickPoint: { x: 784, y: 16 }, type: "titlebar-button", description: "Close the application", status: "unclicked", possibleNav: "Application exits" },
  ];

  // Simulate click on "鐐瑰嚮姝ゅ娴嬭瘯"
  const ctrl = p1.controls[0];
  ctrl.navigatedToPageId = "page-2";
  markPendingTransition(ctrl.label, "click", ctrl.label);

  const p2 = addNavPathNode(
    "A test dialog overlaying the main window. Shows a round mouse-testing area with concentric circles. Has Start/Cancel buttons at the bottom. A status bar shows test progress.",
    "Mouse test dialog",
    ""
  );
  p2.controls = [
    { label: "Start test", bbox: { x: 300, y: 380, width: 120, height: 36 }, clickPoint: { x: 360, y: 398 }, type: "button", description: "Begins the mouse accuracy test", status: "clicked", clickGoal: "Start test", clickScreenshot: "", navigatedToPageId: null },
    { label: "Cancel", bbox: { x: 440, y: 380, width: 100, height: 36 }, clickPoint: { x: 490, y: 398 }, type: "button", description: "Closes the dialog without testing", status: "unclicked", possibleNav: "Returns to main page" },
    { label: "Test area", bbox: { x: 200, y: 60, width: 400, height: 300 }, clickPoint: null, type: "canvas", description: "Circular mouse testing target zone", status: "unclicked", possibleNav: "" },
    { label: "Status bar", bbox: { x: 50, y: 430, width: 700, height: 20 }, clickPoint: null, type: "label", description: "Shows 'Ready', 'Testing...', or results", status: "unclicked", possibleNav: "" },
  ];

  const ctrl2 = p2.controls[0];
  ctrl2.navigatedToPageId = "page-3";
  markPendingTransition(ctrl2.label, "click", ctrl2.label);

  const p3 = addNavPathNode(
    "Test results screen. Shows accuracy metrics: hit count, miss count, average distance from center, and a score chart. 'Retry' and 'Back to main' buttons at the bottom.",
    "Test results",
    ""
  );
  p3.controls = [
    { label: "Retry", bbox: { x: 280, y: 400, width: 100, height: 34 }, clickPoint: { x: 330, y: 417 }, type: "button", description: "Run the test again", status: "unclicked", possibleNav: "Restarts the test dialog" },
    { label: "Back to main", bbox: { x: 400, y: 400, width: 120, height: 34 }, clickPoint: { x: 460, y: 417 }, type: "button", description: "Return to the main page", status: "unclicked", possibleNav: "Returns to MouseTester main page" },
    { label: "Score chart", bbox: { x: 120, y: 100, width: 560, height: 260 }, clickPoint: null, type: "image", description: "Visual chart of click accuracy distribution", status: "unclicked", possibleNav: "" },
  ];

  navPathDirty = true;
  updatePathAppLabel();
  renderNavPath();
}

function showNavNodeDetail(nodeId) {
  const node = navPathNodes.find((n) => n.id === nodeId);
  if (!node) return;

  const content = $("pathDetailContent");
  const meta = $("pathDetailMeta");
  if (!content) return;

  const edge = navPathEdges.find((e) => e.to === nodeId);
  const fromNode = edge ? navPathNodes.find((n) => n.id === edge.from) : null;
  const controls = Array.isArray(node.controls) ? node.controls : [];
  const clickableControls = controls.filter((ctrl) => {
    const type = String(ctrl.type || "").toLowerCase();
    return ctrl.clickPoint || ["button", "icon_button", "tab", "menu", "menuitem", "input", "textbox", "link", "switch", "checkbox", "titlebar-button"].includes(type);
  });
  const possibleEntries = controls.filter((ctrl) => ctrl.possibleNav || ctrl.navigatedToPageId || ctrl.action || ctrl.description);
  const operationItems = clickableControls.slice(0, 12).map((ctrl) => {
    const action = ctrl.action || (String(ctrl.type || "").includes("input") ? "输入/编辑" : "点击");
    const coords = ctrl.clickPoint ? `(${Math.round(ctrl.clickPoint.x)}, ${Math.round(ctrl.clickPoint.y)})` : "";
    return `<li><strong>${escapeHtml(action)}</strong> ${escapeHtml(ctrl.label)} ${coords ? `<span>${coords}</span>` : ""}</li>`;
  }).join("");
  const entryItems = possibleEntries.slice(0, 12).map((ctrl) => {
    const navText = ctrl.navigatedToPageId
      ? `跳转到 ${(navPathNodes.find((n) => n.id === ctrl.navigatedToPageId) || {}).label || "未知页面"}`
      : (ctrl.possibleNav || ctrl.description || ctrl.action || "可能入口");
    return `<li><strong>${escapeHtml(ctrl.label)}</strong><span>${escapeHtml(navText)}</span></li>`;
  }).join("");

  const controlsHtml = controls.length ? `
    <div class="controls-list">
      <h4>按钮 / 输入 / 控件 (${controls.length})</h4>
      ${controls.map((ctrl) => {
        const statusIcon = ctrl.status === "clicked" ? "clicked" : "open";
        const statusClass = ctrl.status === "clicked" ? "ctrl-clicked" : "ctrl-unclicked";
        const coords = ctrl.clickPoint ? `(${Math.round(ctrl.clickPoint.x)}, ${Math.round(ctrl.clickPoint.y)})` : (ctrl.bbox ? `${Math.round(ctrl.bbox.x)},${Math.round(ctrl.bbox.y)} ${Math.round(ctrl.bbox.width)}x${Math.round(ctrl.bbox.height)}` : "");
        const navInfo = ctrl.navigatedToPageId ? ` -> ${(navPathNodes.find((n) => n.id === ctrl.navigatedToPageId) || {}).label || "?"}` : "";
        const typeInfo = [ctrl.type, ctrl.sectionId, ctrl.source, ctrl.confidence !== null && ctrl.confidence !== undefined ? `conf ${Number(ctrl.confidence).toFixed(2)}` : ""].filter(Boolean).join(" | ");
        return `
          <div class="control-item ${statusClass}">
            <span class="ctrl-status">${statusIcon}</span>
            <div class="ctrl-info">
              <span class="ctrl-label">${escapeHtml(ctrl.label)}</span>
              ${typeInfo ? `<span class="ctrl-type">${escapeHtml(typeInfo)}</span>` : ""}
              ${ctrl.description ? `<span class="ctrl-desc">${escapeHtml(ctrl.description)}</span>` : ""}
              ${coords ? `<span class="ctrl-coords">${coords}${navInfo}</span>` : ""}
              ${ctrl.possibleNav ? `<span class="ctrl-possible">-> ${escapeHtml(ctrl.possibleNav)}</span>` : ""}
            </div>
          </div>`;
      }).join("")}
    </div>
  ` : `<div class="path-detail-empty">当前页面还没有收录控件。先运行整屏理解或精准定位后，这里会显示按钮、输入框、可能入口和坐标。</div>`;

  content.innerHTML = `
    <div class="path-detail-card">
      <h4>${escapeHtml(node.label)}</h4>
      ${node.summary ? `<div class="summary-block">${escapeHtml(node.summary)}</div>` : ""}
      <div class="path-detail-sections">
        <div class="path-detail-section">
          <h5>可能操作</h5>
          ${operationItems ? `<ul>${operationItems}</ul>` : `<p>暂无可点击/可输入操作。运行整屏理解后会自动补充。</p>`}
        </div>
        <div class="path-detail-section">
          <h5>可能入口 / 跳转</h5>
          ${entryItems ? `<ul>${entryItems}</ul>` : `<p>暂无推测入口。精准定位或点击验证后会记录跳转关系。</p>`}
        </div>
      </div>
      <div class="meta-row">
        ${node.stateGuess ? `<span><strong>${t("path_state_hint") || "State hint"}:</strong> ${escapeHtml(node.stateGuess)}</span>` : ""}
        ${fromNode ? `<span><strong>${t("path_from") || "From"}:</strong> ${escapeHtml(fromNode.label)}</span>` : ""}
        ${edge?.goal ? `<span><strong>${t("path_action") || "Action"}:</strong> ${escapeHtml(edge.goal)}</span>` : ""}
        ${node.imagePath ? `<span><strong>${t("path_screenshot") || "Screenshot"}:</strong> ${escapeHtml(basename(node.imagePath))}</span>` : ""}
        <span><strong>${t("path_time") || "Time"}:</strong> ${node.timestamp}</span>
      </div>
      ${controlsHtml}
    </div>
  `;

  if (meta) meta.textContent = `${controls.length} controls | ${navPathNodes.length} pages`;
}

function tracePathMapHtml(raw) {
  if (!raw || raw.contract_version !== "screen_map_v1" || !Array.isArray(raw.candidates)) return "";
  const sections = Array.isArray(raw.sections) ? raw.sections : [];
  const candidates = raw.candidates;
  if (!candidates.length) return "";
  return `
    <div class="tf-path-map">
      ${traceDynamicPathGraphHtml(raw, candidates, sections)}
      ${sections.length ? `
        <h5>路径分区</h5>
        <div class="tf-path-sections">
          ${sections.map((section) => {
            const box = normalizeBBox(section.bbox);
            const boxText = box ? `${Math.round(box.x)},${Math.round(box.y)} ${Math.round(box.width)}×${Math.round(box.height)}` : "";
            const meta = [section.section_id, section.role, boxText, `${section.text_count || 0} texts`].filter(Boolean).join(" · ");
            return `
              <div class="tf-path-section">
                <strong>${escapeHtml(section.label || section.section_id || "section")}</strong>
                <span>${escapeHtml(meta)}</span>
              </div>
            `;
          }).join("")}
        </div>
      ` : ""}
      <h5>路径候选</h5>
      ${candidates.map((candidate) => {
        const point = normalizePoint(candidate.click_point, candidate.bbox);
        const box = normalizeBBox(candidate.bbox);
        const pointText = point ? `(${Math.round(point.x)}, ${Math.round(point.y)})` : "";
        const boxText = box ? `${Math.round(box.x)},${Math.round(box.y)} ${Math.round(box.width)}×${Math.round(box.height)}` : "";
        const rule = candidate.screen_map_rule || candidate.evidence?.screen_map_rule || "";
        const meta = [candidate.section_id, candidate.role, candidate.source, rule, candidate.risk_class, pointText, boxText].filter(Boolean).join(" · ");
        return `
          <div class="tf-path-candidate">
            <strong>${escapeHtml(candidate.label || candidate.candidate_id || "candidate")}</strong>
            <span>${escapeHtml(meta)}</span>
            ${candidate.expected_effect ? `<p>${escapeHtml(candidate.expected_effect)}</p>` : ""}
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function traceDynamicPathGraphHtml(raw, candidates, sections) {
  const sectionById = new Map();
  sections.forEach((section) => {
    if (section?.section_id) sectionById.set(section.section_id, section);
  });

  const grouped = new Map();
  candidates.forEach((candidate) => {
    const sectionId = candidate.section_id || "unassigned";
    if (!grouped.has(sectionId)) grouped.set(sectionId, []);
    grouped.get(sectionId).push(candidate);
  });

  const orderedSectionIds = [];
  sections.forEach((section) => {
    if (section?.section_id) orderedSectionIds.push(section.section_id);
  });
  grouped.forEach((_, sectionId) => {
    if (!orderedSectionIds.includes(sectionId)) orderedSectionIds.push(sectionId);
  });

  const stateLabel = raw.state_hint || raw.state_id || "observed screen";
  const summary = raw.screen_summary || raw.summary || "";
  const stateMeta = [
    raw.state_id,
    raw.app_name,
    `${candidates.length} candidates`,
    sections.length ? `${sections.length} sections` : "",
  ].filter(Boolean).join(" · ");

  return `
    <div class="tf-path-graph" aria-label="Dynamic path graph from screen map">
      <div class="tf-path-state-node">
        <span>整屏理解路径图</span>
        <strong>${escapeHtml(stateLabel)}</strong>
        ${stateMeta ? `<em>${escapeHtml(stateMeta)}</em>` : ""}
        ${summary ? `<p>${escapeHtml(summary)}</p>` : ""}
      </div>
      <div class="tf-path-lanes">
        ${orderedSectionIds.map((sectionId) => {
          const section = sectionById.get(sectionId) || { section_id: sectionId, label: sectionId };
          const sectionCandidates = grouped.get(sectionId) || [];
          const box = normalizeBBox(section.bbox);
          const boxText = box ? `${Math.round(box.x)},${Math.round(box.y)} ${Math.round(box.width)}×${Math.round(box.height)}` : "";
          const sectionMeta = [section.role, boxText, `${sectionCandidates.length} candidates`].filter(Boolean).join(" · ");
          return `
            <div class="tf-path-lane">
              <div class="tf-path-section-node">
                <strong>${escapeHtml(section.label || section.section_id || "section")}</strong>
                ${sectionMeta ? `<span>${escapeHtml(sectionMeta)}</span>` : ""}
              </div>
              <div class="tf-path-candidate-nodes">
                ${sectionCandidates.length ? sectionCandidates.map((candidate) => {
                  const point = normalizePoint(candidate.click_point, candidate.bbox);
                  const rule = candidate.screen_map_rule || candidate.evidence?.screen_map_rule || "";
                  const pointText = point ? `(${Math.round(point.x)}, ${Math.round(point.y)})` : "";
                  const nodeMeta = [candidate.role, candidate.source, rule, candidate.risk_class, pointText].filter(Boolean).join(" · ");
                  return `
                    <div class="tf-path-graph-node" data-candidate-id="${escapeHtml(candidate.candidate_id || "")}">
                      <strong>${escapeHtml(candidate.label || candidate.candidate_id || "candidate")}</strong>
                      ${nodeMeta ? `<span>${escapeHtml(nodeMeta)}</span>` : ""}
                    </div>
                  `;
                }).join("") : `<div class="tf-path-graph-empty">No mapped candidate in this section yet</div>`}
              </div>
            </div>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

function toggleTraceStageDetail(event) {
  const node = event.currentTarget || event.target.closest(".tf-node");
  if (!node) return;
  const stageId = node.dataset.tfStage;
  const data = traceStageData.find((s) => s.id === stageId);
  const el = document.getElementById("tfStageDetails");
  if (!data || !el) return;

  if (node.classList.contains("tf-active") && el.style.display !== "none") {
    el.style.display = "none";
    node.classList.remove("tf-active");
    return;
  }

  const rawJson = data.raw ? JSON.stringify(data.raw, null, 2) : "";
  const summary = data.summary || data.value || "No summary for this stage.";
  const visuals = collectTraceStageVisuals(data.raw || {});
  el.style.display = "block";
  el.innerHTML = `
    <div class="tf-stage-detail-card">
      <div class="tf-stage-detail-head">
        <strong>${escapeHtml(data.label || data.id)}</strong>
        <span class="tf-stage-summary">${escapeHtml(String(summary).slice(0, 120))}</span>
        <button type="button" class="tf-stage-close" aria-label="Close">×</button>
      </div>
      <p class="tf-stage-detail-summary">${escapeHtml(summary)}</p>
      ${tracePathMapHtml(data.raw)}
      ${traceStageVisualsHtml(visuals)}
      ${rawJson ? `<pre class="tf-stage-detail-body">${escapeHtml(rawJson.slice(0, 12000))}</pre>` : ""}
    </div>
  `;
  el.querySelector(".tf-stage-close")?.addEventListener("click", () => {
    el.style.display = "none";
    node.classList.remove("tf-active");
  });
  document.querySelectorAll(".tf-node.tf-active").forEach((n) => n.classList.remove("tf-active"));
  node.classList.add("tf-active");
  activateTraceStageVisuals(visuals, el);
}
function escapeHtml(str) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(str).replace(/[&<>"']/g, (ch) => map[ch] || ch);
}

function safeFileStem(value) {
  return String(value || "")
    .trim()
    .replace(/[^\p{L}\p{N}_-]+/gu, "_")
    .replace(/^_+|_+$/g, "");
}

/* 鈹€鈹€ Hook observe / execute responses into nav path 鈹€鈹€ */

function ingestNavPathFromResponse(response) {
  const result = resultOf(response);
  if (!result || typeof result !== "object") return;

  // Derive app name from the response or current binding
  const respAppName = result.app_name || nestedGet(result, ["recognition_plan", "app_name"]) || "";
  if (respAppName && !navPathAppName) {
    navPathAppName = respAppName;
    // Try to restore saved path for this app
    const restored = restorePathGraph(respAppName);
    if (!restored) updatePathAppLabel();
  }

  // Detect observe_screen response with screen_summary or screen_reading.
  const screenSummary =
    result.screen_summary ||
    nestedGet(result, ["screen_map", "summary", "screen_summary"]) ||
    nestedGet(result, ["screen_reading", "screen_summary"]) ||
    nestedGet(result, ["parse_result", "screen_reading", "screen_summary"]) ||
    nestedGet(result, ["parse_result", "vision_regions", "screen_summary"]);
  const stateGuess =
    result.state_guess ||
    nestedGet(result, ["screen_map", "state_hint"]) ||
    nestedGet(result, ["screen_reading", "state_guess"]) ||
    nestedGet(result, ["parse_result", "screen_reading", "state_guess"]) ||
    result.suggested_state_hint;
  const taskType = result.task || nestedGet(result, ["request", "task"]) || "";

  if (screenSummary || (taskType === "observe_screen" && (stateGuess || result.screen_reading || result.ui))) {
    const summary = screenSummary || result.message || "";
    const guess = stateGuess || "";
    const imagePath = result.image_path || nestedGet(result, ["capture", "image_path"]) || "";
    syncAppAndStateFields({
      appName: result.app_name || nestedGet(result, ["request", "app_name"]) || navPathAppName,
      stateHint: guess,
    });
    addNavPathNode(summary, guess, imagePath);

    // Capture discovered controls from all known observe/screen-reading structures.
    const controls = collectControlsFromResult(result);
    for (const ctrl of controls) {
      const ctrlLabel = controlLabel(ctrl);
      const ctrlBbox = ctrl.bbox || ctrl.bounding_box || ctrl.bounds || ctrl.rect || ctrl.region || null;
      const ctrlPoint = ctrl.click_point || ctrl.clickPoint || ctrl.locator_hints?.coordinate?.click_point || null;
      const ctrlType = ctrl.type || ctrl.role || ctrl.kind || ctrl.control_type || "control";
      const ctrlDesc = firstText(ctrl.description, ctrl.expected_effect, ctrl.action, ctrl.purpose, ctrl.meaning, ctrl.summary, ctrl.reason);
      addControlToCurrentPage(ctrlLabel, ctrlBbox, ctrlPoint, ctrlType, ctrlDesc, {
        possibleNav: controlPossibleNav(ctrl) || ctrl.expected_effect,
        action: firstText(ctrl.action, ctrl.interaction, ctrl.interaction_type, ctrl.click_action, ctrl.goal_hint),
        candidateId: ctrl.candidate_id || ctrl.id || ctrl.element_id,
        source: ctrl.source || (ctrl.contract_version === "screen_map_candidate_v1" ? "screen_map" : "observe"),
        sectionId: ctrl.section_id,
        confidence: ctrl.confidence,
      });
    }
  }

  // Detect locate_target response and capture candidates as controls.
  applyPathMapReview(result.path_map_review);
  const locateResult = result.located_bbox || result.located_point || result.recommended_target;
  const planGoal = nestedGet(result, ["recognition_plan", "goal"]) || result.goal || "";
  if (locateResult && planGoal && currentNavNodeId) {
    const bbox = result.located_bbox || nestedGet(result, ["recommended_target", "refined_bbox"]);
    const point = result.located_point || nestedGet(result, ["recommended_target", "element", "click_point"]);
    const desc = nestedGet(result, ["recommended_target", "reason"]) || nestedGet(result, ["recommended_target", "label"]) || "";
    addControlToCurrentPage(planGoal, bbox, point, "button", desc, {
      candidateId: nestedGet(result, ["recommended_target", "candidate_id"]),
      source: "locate",
      action: "click",
    });

    // Also capture candidate list
    const candidates = nestedGet(result, ["recognition_plan", "candidate_result", "candidates"]) || [];
    if (Array.isArray(candidates)) {
      for (const cand of candidates) {
        const candLabel = cand.label || cand.text || cand.name || "";
        if (!candLabel || candLabel === planGoal) continue;
        const candBbox = cand.refined_bbox || cand.element?.bbox || cand.bbox || null;
        const candPoint = cand.element?.click_point || cand.click_point || null;
        addControlToCurrentPage(candLabel, candBbox, candPoint, cand.type || "button", cand.reason || cand.purpose || "", {
          possibleNav: controlPossibleNav(cand),
          action: cand.action || "click",
          candidateId: cand.candidate_id || cand.id,
          source: "locate_candidate",
          confidence: cand.confidence,
        });
      }
    }
  }

  // Detect successful click execution and mark pending transition.
  const clickResult = result.click_result;
  const actionExecuted = nestedGet(result, ["execution_path", "action_executed"]);
  const verified = result.post_click_verification || result.semantic_post_click_verification;
  const verificationOk = verified && (verified.verified !== false && verified.success !== false);

  if ((clickResult || actionExecuted) && (verificationOk || !verified)) {
    const goal = result.goal || nestedGet(result, ["recognition_plan", "goal"]) || "";
    const screenshot = result.image_path || nestedGet(result, ["capture", "image_path"]) || currentImagePath;
    if (goal && currentNavNodeId) {
      // Mark the clicked control
      const ctrl = markControlClicked(goal, true, screenshot);
      markPendingTransition(goal, "click", ctrl?.label || goal);
    }
  }

  // Detect confirmed_point execution too
  const confirmedClick = result.confirmed_click_result;
  if (confirmedClick && !result.dry_run) {
    const goal = result.goal || "confirmed click";
    if (currentNavNodeId) {
      markControlClicked(goal, true, currentImagePath);
      markPendingTransition(goal, "confirmed_click", goal);
    }
  }
}

function payloadFromShared(stage) {
  const goal = stage === "execute" ? $("executeGoal").value : $("locateGoal").value;
  const profile = syncStageProvider("locate");
  return {
    ...modePayload(stage),
    goal,
    task: "click_target",
    app_name: stage === "execute" ? $("executeApp").value : $("locateApp").value,
    state_hint: stage === "execute" ? $("locateState").value : $("locateState").value,
    provider_mode: profile?.provider_mode || null,
    metadata: metadataWithPrompt("locate"),
    top_k: Number($("locateTopK").value || 5),
    capture_live: true,
    observe_trace_path: lastObserveTracePath || null,
  };
}

function savedImagePayload(payload, liveCheckboxId) {
  const captureLive = $(liveCheckboxId).checked;
  payload.capture_live = captureLive;
  if (!captureLive && currentImagePath) {
    payload.image_path = currentImagePath;
  }
  return payload;
}

async function ensureImagePath() {
  if (currentImagePath) return currentImagePath;
  const payload = { save_image: true };
  const roi = roiPayload();
  if (roi) payload.roi = roi;
  const response = await api("POST", "/state/capture_window", payload, { summary: "POST /state/capture_window", workflowStep: "capture" });
  return nestedGet(response, ["data", "image_path"]) || currentImagePath || "";
}

async function callAnalyzeApi() {
  const imagePath = await ensureImagePath();
  if (!imagePath) {
    renderResponse({ success: false, message: "Missing image path." }, "missing image");
    return;
  }
  api(
    "POST",
    "/vision/analyze",
    {
      image_path: imagePath,
      task: "analyze_ui",
      app_name: $("observeApp").value || $("locateApp").value || null,
      goal: $("locateGoal").value || null,
      state_hint: $("observeState").value || $("locateState").value || null,
      provider_mode: "api",
      metadata: metadataWithPrompt("observe"),
    },
    { summary: "POST /vision/analyze", workflowStep: "observe", timeoutSeconds: requestTimeoutSeconds() },
  );
}

function generateManualBox() {
  if (!currentImagePath) {
    renderResponse({ success: false, message: "Missing image path." }, "manual box missing image");
    return;
  }
  const bbox = bboxFromInputs();
  if (!bbox) {
    renderResponse({ success: false, message: "Candidate bbox is missing." }, "manual box missing bbox");
    return;
  }
  api(
    "POST",
    "/panel/manual_box",
    {
      image_path: currentImagePath,
      x: bbox.x,
      y: bbox.y,
      width: bbox.width,
      height: bbox.height,
      label: $("reviewLabel").value || "target",
    },
    { summary: "POST /panel/manual_box", workflowStep: "locate" },
  );
}

async function uploadImageFile(file) {
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
  const contentBase64 = dataUrl.split(",", 2)[1] || "";
  const response = await api("POST", "/panel/upload_image", {
    filename: file.name,
    content_base64: contentBase64,
    content_type: file.type || null,
  });
  const imagePath = nestedGet(response, ["data", "image_path"]);
  const imageUrl = nestedGet(response, ["data", "image_url"]);
  if (imagePath) setCurrentImage(imagePath, imageUrl ? `${baseUrl()}${imageUrl}` : "");
}

function on(id, eventName, handler) {
  const el = $(id);
  if (el) el.addEventListener(eventName, handler);
}

function bindEvents() {
  document.querySelectorAll(".stage").forEach((button) => {
    button.addEventListener("click", () => showStage(button.dataset.stage));
  });
  document.querySelectorAll(".language-option").forEach((button) => {
    button.addEventListener("click", () => applyLanguage(button.dataset.language));
  });
  on("agentModeLearnBtn", "click", () => setAgentMode("learn", currentLearnDepth));
  on("agentModeExecuteBtn", "click", () => setAgentMode("execute"));
  on("learnFastBtn", "click", () => setAgentMode("learn", "fast"));
  on("learnDeepBtn", "click", () => setAgentMode("learn", "deep"));
  on("healthBtn", "click", () => api("GET", "/health"));
  on("observeModelProfile", "change", () => syncStageProvider("observe"));
  on("locateModelProfile", "change", () => syncStageProvider("locate"));
  on("appId", "input", () => syncWindowAppAndState());
  on("appUrl", "input", () => syncWindowAppAndState());

  on("listAppsBtn", "click", async () => {
    const response = await api("GET", "/apps", null, { summary: "GET /apps", workflowStep: "open" });
    setWindowCandidates(nestedGet(response, ["data", "running_windows"]) || []);
  });
  on("openAppBtn", "click", () => {
    api("POST", "/apps/open", {
      app_id: $("appId").value || null,
      url: $("appUrl").value || null,
      bind_after_open: true,
    wait_seconds: 1.5,
    }, { summary: "POST /apps/open", workflowStep: "open" }).then((response) => {
      setWindowCandidates(nestedGet(response, ["data", "running_windows"]) || []);
      syncWindowAppAndState();
    });
  });
  on("listWindowsBtn", "click", () => refreshWindows(true));
  on("windowSelect", "change", applySelectedWindow);
  on("bindWindowBtn", "click", () => {
    syncWindowAppAndState();
    if (navPathAppName) {
      const restored = restorePathGraph(navPathAppName);
      if (!restored) updatePathAppLabel();
    }
    api("POST", "/session/bind_window", {
      process_name: $("bindProcess").value || null,
      title: $("bindTitle").value || null,
    }, { summary: "POST /session/bind_window", workflowStep: "open" });
  });

  on("captureBtn", "click", () => {
    const payload = { save_image: $("captureSave").checked };
    const roi = roiPayload();
    if (roi) payload.roi = roi;
    api("POST", "/state/capture_window", payload, { summary: "POST /state/capture_window", workflowStep: "capture" });
  });
  on("useImagePathBtn", "click", () => setCurrentImage($("imagePath").value.trim()));
  on("imageFile", "change", (event) => {
    const file = event.target.files && event.target.files[0];
    if (file) uploadImageFile(file);
  });
  const dropZone = $("dropZone");
  if (dropZone) {
    dropZone.addEventListener("dragover", (event) => {
      event.preventDefault();
      dropZone.classList.add("dragover");
    });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
    dropZone.addEventListener("drop", (event) => {
      event.preventDefault();
      dropZone.classList.remove("dragover");
      const file = event.dataTransfer.files && event.dataTransfer.files[0];
      if (file) uploadImageFile(file);
    });
  }

  on("observeBtn", "click", async () => {
    const profile = syncStageProvider("observe");
    if (!(await ensureStageModelReady("observe", profile?.profile_id || $("observeModelProfile").value))) return;
    const payload = savedImagePayload({
      ...modePayload("observe"),
      task: "observe_screen",
      app_name: $("observeApp").value || null,
      state_hint: $("observeState").value || null,
      provider_mode: profile?.provider_mode || $("observeProvider").value || null,
      metadata: metadataWithPrompt("observe"),
    }, "observeLive");
    api("POST", "/vision/observe_screen", payload, { summary: "POST /vision/observe_screen", workflowStep: "observe", timeoutSeconds: requestTimeoutSeconds() });
  });
  on("analyzeBtn", "click", callAnalyzeApi);
  on("applyObserveModelBtn", "click", () => applyModelProfile("observe", $("observeModelProfile").value));
  on("startObserveModelBtn", "click", () => callModelAction("start", "observe", $("observeModelProfile").value));
  on("stopObserveModelBtn", "click", () => callModelAction("stop", "observe", $("observeModelProfile").value));
  on("testObserveModelBtn", "click", () => testModelService("observe", $("observeModelProfile").value));

  on("locateBtn", "click", async () => {
    const profile = syncStageProvider("locate");
    if (!(await ensureStageModelReady("locate", profile?.profile_id || $("locateModelProfile").value))) return;
    api("POST", "/vision/locate_target", savedImagePayload(payloadFromShared("locate"), "locateLive"), { summary: "POST /vision/locate_target", workflowStep: "locate", timeoutSeconds: requestTimeoutSeconds() });
  });
  on("applyLocateModelBtn", "click", () => applyModelProfile("locate", $("locateModelProfile").value));
  on("startLocateModelBtn", "click", () => callModelAction("start", "locate", $("locateModelProfile").value));
  on("stopLocateModelBtn", "click", () => callModelAction("stop", "locate", $("locateModelProfile").value));
  on("testLocateModelBtn", "click", () => testModelService("locate", $("locateModelProfile").value));
  on("overlayBtn", "click", () => {
    if (!lastTracePath) {
      renderResponse({ success: false, message: "No trace path is available for overlay rendering." }, "overlay unavailable");
      return;
    }
    api("POST", "/vision/render_recognition_plan_overlay", {
      trace_path: lastTracePath,
      include_rejected: true,
      include_points: true,
      label_candidates: true,
      label_reasons: true,
    }, { summary: "POST /vision/render_recognition_plan_overlay" });
  });

  on("typeTextBtn", "click", () => {
    const x = $("typeX").value;
    const y = $("typeY").value;
    api("POST", "/action/type_text", {
      text: $("typeTextValue").value,
      x: x === "" ? null : Number(x),
      y: y === "" ? null : Number(y),
      click_before_typing: $("typeClickFirst").checked,
      clear_existing: $("typeClear").checked,
      submit: $("typeSubmit").checked,
      restore_clipboard: true,
      dry_run: $("typeDryRun").checked,
    });
  });

  on("dryRunBtn", "click", () => {
    const payload = payloadFromShared("execute");
    payload.dry_run = true;
    payload.approved_plan_id = $("approvedPlanId").value || null;
    payload.learned_instruction_id = $("learnedInstructionId").value || null;
    payload.learning_mode = $("learningMode").checked ? "instruction" : null;
    api("POST", "/action/execute_recognition_plan", payload, { summary: "Click preview", workflowStep: "gate", timeoutSeconds: requestTimeoutSeconds() });
  });
  on("executeBtn", "click", () => {
    const payload = payloadFromShared("execute");
    payload.dry_run = false;
    payload.approved_plan_id = $("approvedPlanId").value || null;
    payload.learned_instruction_id = $("learnedInstructionId").value || null;
    payload.learning_mode = $("learningMode").checked ? "instruction" : null;
    api("POST", "/action/execute_recognition_plan", payload, { summary: "Execute click", workflowStep: "execute", timeoutSeconds: requestTimeoutSeconds() });
  });
  on("previewBoxBtn", "click", previewBox);
  on("manualBoxBtn", "click", generateManualBox);
  on("confirmedDryRunBtn", "click", () => callConfirmedPoint(true));
  on("confirmedClickBtn", "click", () => callConfirmedPoint(false));
  on("copyResponseBtn", "click", () => navigator.clipboard?.writeText($("responseText").textContent));

  on("traceFileSelect", "change", loadSelectedTrace);
  on("refreshTracesBtn", "click", refreshTraceList);
  on("openTraceFolderBtn", "click", () => api("POST", "/panel/open_trace_folder", {}, { summary: "open trace folder" }));
  on("modelTestSendBtn", "click", sendModelTest);
  on("savePathBtn", "click", savePathGraph);
  on("saveAsConfirmBtn", "click", confirmSaveAs);
  on("saveAsCancelBtn", "click", cancelSaveAs);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && $("saveAsOverlay")?.style.display === "flex") cancelSaveAs();
  });
  on("openPathFolderBtn", "click", () => api("POST", "/panel/open_path_folder", {}, { summary: "open folder" }));
  on("pathZoomInBtn", "click", () => { pathZoom = Math.min(3, Math.round((pathZoom * 1.25) * 100) / 100); updateZoomLabel(); });
  on("pathZoomOutBtn", "click", () => { pathZoom = Math.max(0.3, Math.round((pathZoom / 1.25) * 100) / 100); updateZoomLabel(); });
  on("pathZoomResetBtn", "click", () => { pathZoom = 1.0; pathPanX = 0; pathPanY = 0; updateZoomLabel(); });
  on("pathHistorySelect", "change", () => {
    const appName = $("pathHistorySelect").value;
    if (!appName) {
      if (liveSessionSnapshot) {
        navPathNodes = liveSessionSnapshot.nodes;
        navPathEdges = liveSessionSnapshot.edges;
        navPathCounter = liveSessionSnapshot.counter;
        navPathAppName = liveSessionSnapshot.appName;
        currentNavNodeId = liveSessionSnapshot.currentNode;
        pendingTransition = liveSessionSnapshot.pending;
        navPathDirty = liveSessionSnapshot.dirty;
        liveSessionSnapshot = null;
        updatePathAppLabel();
        renderNavPath();
      }
      return;
    }
    if (!liveSessionSnapshot) {
      liveSessionSnapshot = {
        nodes: navPathNodes.slice(),
        edges: navPathEdges.slice(),
        counter: navPathCounter,
        appName: navPathAppName,
        currentNode: currentNavNodeId,
        pending: pendingTransition ? { ...pendingTransition } : null,
        dirty: navPathDirty,
      };
    }
    const data = loadPathGraph(appName);
    if (data && data.nodes) {
      navPathNodes = data.nodes;
      navPathEdges = data.edges || [];
      navPathCounter = data.counter || navPathNodes.length;
      navPathAppName = data.appName || appName;
      currentNavNodeId = navPathNodes.length ? navPathNodes[navPathNodes.length - 1].id : null;
      pendingTransition = null;
      navPathDirty = false;
      updatePathAppLabel();
      renderNavPath();
    }
  });
}
function callConfirmedPoint(dryRun) {
  const point = pointFromInputsOrBox();
  const bbox = bboxFromInputs();
  if (!point) {
    renderResponse({ success: false, message: "Confirmed point is missing." }, "confirmed point missing");
    return;
  }
  api("POST", "/action/execute_confirmed_point", {
    x: point.x,
    y: point.y,
    bbox,
    label: $("reviewLabel").value || null,
    source_trace_path: lastTracePath || null,
    dry_run: dryRun,
  }, { summary: dryRun ? "Point click preview" : "Point execute click", workflowStep: dryRun ? "gate" : "execute" });
}

async function boot() {
  bindEvents();
  setAgentMode(currentAgentMode, currentLearnDepth);
  applyLanguage(currentLanguage);
  syncWindowAppAndState();
  renderFlowGraph({ message: "idle" });
  renderNavPath();
  populatePathHistory();
  refreshTraceList();
  startPathResizeObserver();
  const response = await api("GET", "/health", null, { summary: "GET /health" });
  setRuntimeState(response.success ? "runtime_ready" : "runtime_unavailable", response.success);
  await refreshModels();
}

boot();








