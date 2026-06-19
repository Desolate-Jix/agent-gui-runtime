const $ = (id) => document.getElementById(id);

let lastResponse = {};
let lastTracePath = "";
let lastObserveTracePath = "";
let currentImagePath = "";
let currentImageUrl = "";
let modelProfiles = [];
let appCatalog = [];

const DEFAULT_STAGE_PROFILE_IDS = {
  observe: "qwen3_vl_4b_q4_k_m",
  understanding: "qwen3_vl_4b_q4_k_m",
  locate: "vista_4b_transformers",
  grounding: "vista_4b_transformers",
};
let windowCandidates = [];
let pendingRequests = new Set();
let currentLanguage = localStorage.getItem("agentPanelLanguage") || "zh-CN";
let currentAgentMode = localStorage.getItem("agentPanelMode") || "learn";
let currentLearnDepth = "fast";
let activeCardDrag = null;
let activeCardDragFrame = null;
let pendingCardDrag = null;
let learnValidationRun = null;
let taskRunState = null;
const BROWSER_APP_IDS = new Set(["browser", "edge", "msedge", "chrome", "firefox"]);
const CARD_ORDER_STORAGE_KEY = "openclaw.panel.cardOrder.v1";
const CARD_DRAG_START_THRESHOLD_PX = 6;
const DEFAULT_SEEK_GRAPH_PATH = "artifacts/seek/runtime_path_graph_seek_mvp_20260617.json";
const DEFAULT_WIKIPEDIA_GRAPH_PATH = "artifacts/wikipedia/runtime_path_graph_wikipedia_search_v1.json";
const DEFAULT_GITHUB_ISSUES_GRAPH_PATH = "artifacts/github/runtime_path_graph_github_issues_v1.json";
const DEFAULT_PYTHON_DOCS_SEARCH_GRAPH_PATH = "artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json";
const DEFAULT_INPUT_DEMO_GRAPH_PATH = "artifacts/demo/runtime_path_graph_input_demo.json";
const DEFAULT_TABLE_DIRECTORY_GRAPH_PATH = "artifacts/table_directory/runtime_path_graph_table_directory_v1.json";
const DEFAULT_ARTIFACT_REPLAY_REGRESSION_PATH = "logs/smoke/artifact_replay_regression_20260619.json";
const DEFAULT_LEARN_SAMPLE_READINESS_PATH = "logs/smoke/learn_sample_readiness_gate_20260619.json";
let replayArtifact = null;
let replayRegressionReport = null;
let learnSampleReadinessGate = null;

/* Navigation path graph state */
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
let runtimePathGraphView = null; // learned artifact rendered into the shared PathGraph card

const stageMeta = {
  open_bind: ["stage_open_bind_title", "stage_open_bind_subtitle"],
  capture: ["stage_capture_title", "stage_capture_subtitle"],
  observe: ["stage_observe_title", "stage_observe_subtitle"],
  execute_actions: ["stage_execute_actions_title", "stage_execute_actions_subtitle"],
  locate: ["stage_locate_title", "stage_locate_subtitle"],
  execute: ["stage_execute_title", "stage_execute_subtitle"],
  model_test: ["stage_model_test_title", "stage_model_test_subtitle"],
  input: ["stage_input_title", "stage_input_subtitle"],
  trace: ["stage_trace_title", "stage_trace_subtitle"],
};

const PAGE_REGISTRY = {
  open_bind: {
    page: "open_bind",
    group: "system",
    titleKey: "stage_open_bind_title",
    subtitleKey: "stage_open_bind_subtitle",
    api: "/apps, /apps/open, /session/bind_window",
    sideEffectKey: "side_effect_no_page_action",
  },
  capture: {
    page: "capture",
    group: "system",
    titleKey: "stage_capture_title",
    subtitleKey: "stage_capture_subtitle",
    api: "/state/capture_window, /panel/upload_image",
    sideEffectKey: "side_effect_no_page_action",
  },
  observe: {
    page: "observe",
    group: "learn",
    agentMode: "learn",
    titleKey: "stage_learn_fast_title",
    subtitleKey: "stage_learn_fast_subtitle",
    api: "/vision/observe_screen",
    sideEffectKey: "side_effect_observe_only",
  },
  learn_locate: {
    page: "locate",
    group: "learn",
    agentMode: "learn",
    titleKey: "stage_learn_deep_title",
    subtitleKey: "stage_learn_deep_subtitle",
    api: "/vision/locate_target",
    sideEffectKey: "side_effect_calibration_only",
  },
  learn_validation: {
    page: "learn_validation",
    group: "learn",
    agentMode: "learn",
    titleKey: "stage_learn_validation_title",
    subtitleKey: "stage_learn_validation_subtitle",
    api: "/execute/available_actions, /execute/step",
    sideEffectKey: "side_effect_safe_validation",
    showPipeline: false,
  },
  learn_replay: {
    page: "learn_replay",
    group: "learn",
    agentMode: "learn",
    titleKey: "stage_learn_replay_title",
    subtitleKey: "stage_learn_replay_subtitle",
    api: "/panel/file, /execute/available_actions, /execute/step",
    sideEffectKey: "side_effect_safe_validation",
    showPipeline: false,
  },
  execute_actions: {
    page: "execute_actions",
    group: "execute",
    agentMode: "execute",
    titleKey: "stage_execute_actions_title",
    subtitleKey: "stage_execute_actions_subtitle",
    api: "/execute/available_actions",
    sideEffectKey: "side_effect_action_discovery",
    showPipeline: false,
  },
  locate: {
    page: "locate",
    group: "execute",
    agentMode: "execute",
    titleKey: "stage_execute_locate_title",
    subtitleKey: "stage_execute_locate_subtitle",
    api: "/vision/locate_target",
    sideEffectKey: "side_effect_preview_only",
  },
  execute_locate: {
    page: "locate",
    group: "execute",
    agentMode: "execute",
    titleKey: "stage_execute_locate_title",
    subtitleKey: "stage_execute_locate_subtitle",
    api: "/vision/locate_target",
    sideEffectKey: "side_effect_preview_only",
  },
  execute: {
    page: "execute",
    group: "execute",
    agentMode: "execute",
    titleKey: "stage_execute_title",
    subtitleKey: "stage_execute_subtitle",
    api: "/action/execute_recognition_plan, /action/execute_confirmed_point",
    sideEffectKey: "side_effect_click_when_execute",
    showPipeline: true,
  },
  execute_task_run: {
    page: "execute_task_run",
    group: "execute",
    agentMode: "execute",
    titleKey: "stage_execute_task_run_title",
    subtitleKey: "stage_execute_task_run_subtitle",
    api: "/execute/available_actions, /execute/step",
    sideEffectKey: "side_effect_task_harness",
    showPipeline: false,
  },
  input: {
    page: "input",
    group: "execute",
    agentMode: "execute",
    titleKey: "stage_input_title",
    subtitleKey: "stage_input_subtitle",
    api: "/action/type_text",
    sideEffectKey: "side_effect_keyboard_when_execute",
    showPipeline: true,
  },
  trace: {
    page: "trace",
    group: "system",
    titleKey: "stage_trace_title",
    subtitleKey: "stage_trace_subtitle",
    api: "/panel/list_traces, /panel/file",
    sideEffectKey: "side_effect_no_page_action",
  },
  model_test: {
    page: "model_test",
    group: "system",
    titleKey: "stage_model_test_title",
    subtitleKey: "stage_model_test_subtitle",
    api: "/panel/model_test, /runtime/models",
    sideEffectKey: "side_effect_model_only",
  },
};

function pageMetaForStage(stage) {
  return PAGE_REGISTRY[stage] || PAGE_REGISTRY.open_bind;
}

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
    nav_group_system: "会话 / 系统",
    nav_group_learn: "学习模式",
    nav_group_execute: "执行模式",
    nav_group_tools: "系统工具",
    workspace_switch: "工作区切换",
    workspace_hint_learn: "建图、校准坐标、写入路径图",
    workspace_hint_execute: "可用动作、定位、Gate、动作证据",
    workspace_hint_system: "绑定窗口、截图、Trace、模型",
    nav_group_learn_flow: "1 整屏理解 -> 2 坐标校准 -> PathGraph",
    nav_group_execute_flow: "1 可用动作 -> 2 精准定位 -> 3 点击 Gate -> 4 输入/验证",
    nav_trace_audit: "Trace 审计",
    nav_learn_observe: "整屏理解 / Learn Fast",
    nav_learn_locate: "坐标校准 / Learn Deep",
    nav_learn_replay: "学习产物回放",
    nav_learn_validation: "路径图安全验证",
    nav_execute_actions: "当前状态 / 可用动作",
    nav_execute_task_run: "路径图任务运行",
    nav_execute_locate: "精准定位",
    nav_execute_gate: "点击 Gate",
    nav_execute_input: "输入",
    nav_models: "模型测试",
    settings: "设置",
    learn_mode: "学习模式",
    execute_mode: "执行模式",
    system_mode: "系统工具",
    learn_fast: "快速学习",
    learn_deep: "深度学习",
    learn_fast_build_path: "快速建图",
    learn_deep_calibrate_path: "深度校准路径图",
    locate_current_target: "定位当前目标",
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
    app_catalog: "可启动应用",
    app_catalog_help: "配置里可由 runtime 打开的应用或浏览器入口，不代表当前已绑定窗口。",
    url: "URL",
    window_candidates: "可绑定窗口",
    window_candidates_help: "当前已经打开的窗口；绑定后截图、理解、定位和点击都使用这个窗口。",
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
    learn_workbench_hint: "学习模式：整屏理解负责快速建图，精准定位负责深度校准全部子路径；不真实点击。",
    execute_workbench_hint: "执行模式：先生成点击预览和坐标框图，再复用 approved_plan_id 执行真实点击。",
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
    plan_click_preview: "生成点击计划（不会操作窗口）",
    plan_execute_click: "真实执行识别点击",
    point_click_preview: "坐标点击预览（不会操作窗口）",
    point_execute_click: "真实执行坐标点击",
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
    action_path_graph: "运行管线",
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
    stage_learn_fast_title: "整屏理解 / Learn Fast",
    stage_learn_fast_subtitle: "学习模式：观察当前窗口，生成页面结构草稿和 PathGraph draft，不真实点击",
    stage_learn_deep_title: "坐标校准 / Learn Deep",
    stage_learn_deep_subtitle: "学习模式：校准 PathGraph 子节点坐标、补充遗漏节点，不真实点击",
    stage_learn_replay_title: "学习产物回放 / 路径图验证",
    stage_learn_replay_subtitle: "学习模式：查看 SEEK/Wikipedia 路径图产物、验证报告和连续 Execute 回放",
    stage_learn_validation_title: "路径图安全验证",
    stage_learn_validation_subtitle: "学习模式：用 read-only/no-write 安全动作验证候选路径图，不执行真实输入",
    stage_execute_actions_title: "当前状态 / 可用动作",
    stage_execute_actions_subtitle: "执行模式：基于已学习路径图和当前状态列出可执行动作，不跑全量学习",
    stage_execute_task_run_title: "路径图任务运行",
    stage_execute_task_run_subtitle: "执行模式：测试 harness 连续调用单步 Execute；输入 demo 仅 dry-run",
    stage_execute_locate_title: "精准定位",
    stage_execute_locate_subtitle: "执行模式：只定位当前目标并生成候选/覆盖图，不真实点击",
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
    trace_mode_filter: "Trace 模式",
    start_model: "启动模型",
    stop_model: "停止模型",
    test_model: "检查模型服务",
    apply_model_profile: "应用配置",
    workspace_system: "系统工具",
    workspace_learn: "学习模式",
    workspace_execute: "执行模式",
    side_effect_no_page_action: "不会操作目标窗口",
    side_effect_observe_only: "只观察和建图",
    side_effect_calibration_only: "只校准路径图",
    side_effect_safe_validation: "只验证安全动作",
    side_effect_action_discovery: "只读取路径图并生成动作列表",
    side_effect_task_harness: "连续调用测试 harness",
    side_effect_preview_only: "只预览定位",
    side_effect_click_when_execute: "执行按钮会真实点击",
    side_effect_keyboard_when_execute: "执行按钮会真实输入",
    side_effect_model_only: "只测试模型服务",
    drag_card: "拖动卡片",
    reset_layout: "重置布局",
    running: "运行中",
    ok: "正常",
    failed: "失败",
    idle: "空闲",
    runtime_ready: "runtime 就绪",
    runtime_unavailable: "runtime 不可用",
    no_image: "无图片",
    no_response: "无响应",
    no_apps: "未发现应用",
    no_windows: "未发现窗口",
    no_models: "未发现模型 profile",
    request_already_running: "该请求正在运行",
    path_graph_calibrated: "路径图已校准",
    execute_actions_title: "当前状态 / 可用动作",
    execute_actions_hint: "执行模式可以先理解当前页面给 agent 决策，但不写入学习路径图；随后用已学习 artifact 刷新可用动作，动作不限于点击，也包括滚动、输入等通用 skill。",
    runtime_graph_path: "Runtime PathGraph 路径",
    runtime_path_graph_json: "Runtime PathGraph JSON",
    screen_inventory_json: "当前屏幕清单 JSON",
    allow_apply_entry: "允许 Apply/申请入口（高风险）",
    allow_apply_entry_help: "只允许打开 Apply / Quick Apply 入口；最终提交始终由安全策略阻断。",
    execute_observe_current_screen: "理解当前页面",
    select_launch_app: "-- 选择可启动应用 --",
    refresh_available_actions: "刷新可用动作",
    learn_validation_title: "路径图安全验证",
    learn_validation_hint: "验证候选路径图是否能安全行走。只允许 read-only/no-write 动作；input、Apply、Submit、Delete、Save changes 会被过滤。",
    learn_replay_title: "学习产物回放 / 路径图验证",
    learn_replay_hint: "加载学习产物，查看路径图结构、动作模板、skill 和安全规则；多步回放只在面板 harness 串联，后端 Execute 仍一次只执行一步。",
    artifact_preset: "产物预设",
    load_artifact: "加载产物",
    regression_suite: "统一回归门禁",
    regression_report_path: "回归报告路径",
    load_regression_report: "加载回归报告",
    learn_sample_gate: "新学习样本门禁",
    learn_sample_gate_path: "新样本门禁路径",
    load_learn_sample_gate: "加载新样本门禁",
    ready_for_new_learn_sample: "可开始新学习样本",
    use_for_safe_validation: "带入安全验证",
    use_for_task_run: "带入任务运行",
    safe_validation_replay: "安全验证回放",
    task_run_replay: "任务运行回放",
    graph_structure: "路径图结构",
    safety_summary: "安全摘要",
    safety_mode: "安全模式",
    current_state_id: "当前状态 ID",
    dispatch_low_level: "派发低层动作",
    generate_validation_plan: "生成验证计划",
    dry_run_next_step: "Dry-run 下一步",
    execute_next_safe_action: "执行下一条安全动作",
    reset_timeline: "重置时间线",
    execute_task_run_title: "路径图任务运行",
    execute_task_run_hint: "模拟 agent 使用 verified 路径图连续调用 Execute。每一步仍然只执行一个 action；input demo 只做 dry-run，不真实输入。",
    task_template: "任务模板",
    max_items: "最大条目数",
    max_steps: "最大步数",
    demo_input_text: "Demo 输入文本",
    start_task_run: "开始任务",
    execute_next_step: "执行下一步",
    stop: "停止",
    allowed: "允许",
    forbidden: "禁止",
    pending: "待执行",
    passed: "通过",
    skipped: "跳过",
    planned_not_executed: "已计划但未执行",
    input_dry_run_only: "输入 dry-run only，不会调用 /action/type_text",
    codex_browser_reserved_for_gpt: "Codex 内置浏览器默认仅用于 ChatGPT 沟通；测试目标请绑定外部浏览器或应用窗口。"
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
    nav_group_system: "Session / System",
    nav_group_learn: "Learn Mode",
    nav_group_execute: "Execute Mode",
    nav_group_tools: "System Tools",
    workspace_switch: "Workspace Switch",
    workspace_hint_learn: "Build map, calibrate coordinates, write PathGraph",
    workspace_hint_execute: "Available actions, locate, gate, evidence",
    workspace_hint_system: "Bind windows, capture, traces, models",
    nav_group_learn_flow: "1 Observe -> 2 Coordinate calibration -> PathGraph",
    nav_group_execute_flow: "1 Available actions -> 2 Precise locate -> 3 Click Gate -> 4 Input/verify",
    nav_trace_audit: "Trace Audit",
    nav_learn_observe: "Observe / Learn Fast",
    nav_learn_locate: "Coordinate Calibration / Learn Deep",
    nav_learn_replay: "Artifact Replay",
    nav_learn_validation: "PathGraph Validation",
    nav_execute_actions: "Current State / Actions",
    nav_execute_task_run: "PathGraph Task Run",
    nav_execute_locate: "Precise Locate",
    nav_execute_gate: "Click Gate",
    nav_execute_input: "Input",
    nav_models: "Models",
    settings: "Settings",
    learn_mode: "Learn Mode",
    execute_mode: "Execute Mode",
    system_mode: "System Tools",
    learn_fast: "Learn Fast",
    learn_deep: "Learn Deep",
    learn_fast_build_path: "Fast Map Build",
    learn_deep_calibrate_path: "Deep Path Calibration",
    locate_current_target: "Locate Current Target",
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
    app_catalog: "Launchable apps",
    app_catalog_help: "Configured apps or browser entries the runtime can open; this is not the currently bound window.",
    url: "URL",
    window_candidates: "Bindable windows",
    window_candidates_help: "Already-open windows. After binding, screenshots, understanding, locating, and clicks use this window.",
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
    learn_workbench_hint: "Learn Mode: Observe builds the fast map, Locate calibrates every child path control; no real click.",
    execute_workbench_hint: "Execute Mode: preview the click plan and coordinate overlay first, then reuse the approved_plan_id for the real click.",
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
    plan_click_preview: "Build click plan (no window action)",
    plan_execute_click: "Real recognition click",
    point_click_preview: "Point click preview (no window action)",
    point_execute_click: "Real coordinate click",
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
    action_path_graph: "Runtime Pipeline",
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
    stage_learn_fast_title: "Observe / Learn Fast",
    stage_learn_fast_subtitle: "Learn Mode: observe the current window and build a page-structure and PathGraph draft; no real click",
    stage_learn_deep_title: "Coordinate Calibration / Learn Deep",
    stage_learn_deep_subtitle: "Learn Mode: calibrate PathGraph child-node coordinates and add missing nodes; no real click",
    stage_learn_replay_title: "Artifact Replay / PathGraph Validation",
    stage_learn_replay_subtitle: "Learn Mode: inspect SEEK/Wikipedia PathGraph artifacts, validation reports, and continuous Execute replay",
    stage_learn_validation_title: "PathGraph Safe Validation",
    stage_learn_validation_subtitle: "Learn Mode: validate candidate PathGraph with read-only/no-write safe actions; no real input",
    stage_execute_actions_title: "Current State / Available Actions",
    stage_execute_actions_subtitle: "Execute Mode: list possible actions from learned artifacts and current state without full learning",
    stage_execute_task_run_title: "PathGraph Task Run",
    stage_execute_task_run_subtitle: "Execute Mode: harness calls single-step Execute repeatedly; input demo is dry-run only",
    stage_execute_locate_title: "Precise Locate",
    stage_execute_locate_subtitle: "Execute Mode: locate the current target and render candidates/overlay only; no real click",
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
    trace_mode_filter: "Trace mode",
    start_model: "Start model",
    stop_model: "Stop model",
    test_model: "Check model service",
    apply_model_profile: "Apply profile",
    workspace_system: "System Tools",
    workspace_learn: "Learn Mode",
    workspace_execute: "Execute Mode",
    side_effect_no_page_action: "No target-window action",
    side_effect_observe_only: "Observe and map only",
    side_effect_calibration_only: "PathGraph calibration only",
    side_effect_safe_validation: "Safe action validation only",
    side_effect_action_discovery: "Read PathGraph and list actions only",
    side_effect_task_harness: "Multi-step test harness",
    side_effect_preview_only: "Preview/localize only",
    side_effect_click_when_execute: "Execute buttons can click for real",
    side_effect_keyboard_when_execute: "Execute buttons can type for real",
    side_effect_model_only: "Model service test only",
    drag_card: "Drag card",
    reset_layout: "Reset layout",
    running: "running",
    ok: "ok",
    failed: "failed",
    idle: "idle",
    runtime_ready: "runtime ready",
    runtime_unavailable: "runtime unavailable",
    no_image: "no image",
    no_response: "no response",
    no_apps: "No apps found",
    no_windows: "No windows found",
    no_models: "No model profiles found",
    request_already_running: "This request is already running",
    path_graph_calibrated: "Path graph calibrated",
    execute_actions_title: "Current State / Available Actions",
    execute_actions_hint: "Execute Mode can understand the current page for agent decisions without writing the learning PathGraph, then refresh available actions from learned artifacts. Actions are not limited to clicks; they may include learned scroll and input skills.",
    runtime_graph_path: "Runtime PathGraph path",
    runtime_path_graph_json: "Runtime PathGraph JSON",
    screen_inventory_json: "Screen inventory JSON",
    allow_apply_entry: "Allow Apply entry (high risk)",
    allow_apply_entry_help: "Allows opening Apply / Quick Apply only. Final submit remains blocked by safety policy.",
    execute_observe_current_screen: "Understand current screen",
    select_launch_app: "-- Select launchable app --",
    refresh_available_actions: "Refresh available actions",
    learn_validation_title: "PathGraph Safe Validation",
    learn_validation_hint: "Validate whether a candidate PathGraph can be walked safely. Only read-only/no-write actions are allowed; input, Apply, Submit, Delete, and Save changes are filtered.",
    learn_replay_title: "Artifact Replay / PathGraph Validation",
    learn_replay_hint: "Load a learned artifact, inspect PathGraph structure, action templates, skills, and safety rules. Multi-step replay is chained by the panel harness; backend Execute still performs one step at a time.",
    artifact_preset: "Artifact preset",
    load_artifact: "Load artifact",
    regression_suite: "Regression Suite",
    regression_report_path: "Regression report path",
    load_regression_report: "Load regression report",
    learn_sample_gate: "New Learn Sample Gate",
    learn_sample_gate_path: "Readiness gate path",
    load_learn_sample_gate: "Load readiness gate",
    ready_for_new_learn_sample: "Ready for new Learn sample",
    use_for_safe_validation: "Use for safe validation",
    use_for_task_run: "Use for task run",
    safe_validation_replay: "Safe validation replay",
    task_run_replay: "Task run replay",
    graph_structure: "Graph structure",
    safety_summary: "Safety summary",
    safety_mode: "Safety mode",
    current_state_id: "Current state ID",
    dispatch_low_level: "Dispatch low level",
    generate_validation_plan: "Generate validation plan",
    dry_run_next_step: "Dry-run next step",
    execute_next_safe_action: "Execute next safe action",
    reset_timeline: "Reset timeline",
    execute_task_run_title: "PathGraph Task Run",
    execute_task_run_hint: "Simulates an agent loop over a verified PathGraph. Each step still executes one action only; input demo is dry-run and never types for real.",
    task_template: "Task template",
    max_items: "Max items",
    max_steps: "Max steps",
    demo_input_text: "Demo input text",
    start_task_run: "Start task",
    execute_next_step: "Execute next step",
    stop: "Stop",
    allowed: "Allowed",
    forbidden: "Forbidden",
    pending: "Pending",
    passed: "Passed",
    skipped: "Skipped",
    planned_not_executed: "Planned but not executed",
    input_dry_run_only: "Input dry-run only; /action/type_text is not called",
    codex_browser_reserved_for_gpt: "Codex in-app browser is reserved for ChatGPT by default; bind an external browser or app window as the test target."
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
  const activeStage = document.querySelector(".stage.active")?.dataset.stage || "open_bind";
  showStage(activeStage);
  refreshDraggableCards();
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
  currentLearnDepth = "fast";
  localStorage.setItem("agentPanelMode", currentAgentMode);
  document.body.classList.toggle("agent-mode-execute", currentAgentMode === "execute");
  document.body.classList.toggle("agent-mode-learn", currentAgentMode === "learn");
  document.querySelectorAll(".workspace-option[data-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === currentAgentMode);
  });
  if (!options.preservePolicy) {
    setWritePolicyControls(defaultWritePolicyFor(currentAgentMode, currentLearnDepth));
  }
  syncStageLearningControls();
}

function modePayload(stage) {
  const mode = stage === "observe" ? "learn" : (stage === "locate" && currentAgentMode === "learn" ? "learn" : "execute");
  const depth = stage === "observe" ? "fast" : (mode === "learn" ? "deep" : null);
  return {
    agent_mode: mode,
    learn_depth: depth,
    write_policy: writePolicyPayload(),
  };
}

function syncStageLearningControls(stage = document.querySelector(".stage.active")?.dataset.stage || "open_bind") {
  const meta = pageMetaForStage(stage);
  const isLearnLocate = meta.page === "locate" && meta.agentMode === "learn";
  const observeBtn = $("observeBtn");
  if (observeBtn) observeBtn.textContent = t("learn_fast_build_path");
  const locateBtn = $("locateBtn");
  if (locateBtn) locateBtn.textContent = isLearnLocate ? t("learn_deep_calibrate_path") : t("locate_current_target");
  const locateGoal = $("locateGoal");
  if (locateGoal) {
    locateGoal.disabled = isLearnLocate;
    locateGoal.placeholder = isLearnLocate ? "Learn Mode uses all PathGraph controls" : "";
  }
}

function responseAllowsPathGraphWrite(result) {
  const policy = result?.write_policy || nestedGet(result, ["request", "write_policy"]);
  if (!policy || typeof policy !== "object") return true;
  return policy.path_graph !== false;
}

function setStatus(text, state = "neutral") {
  const el = $("requestStatus");
  el.textContent = t(text) || text;
  const palette = {
    ok: { color: "#14804a", background: "#ecfdf3", border: "#a7f0ba" },
    warning: { color: "#71634e", background: "#f7f4ee", border: "#d8d0c1" },
    error: { color: "#725757", background: "#f7f1f1", border: "#d8c6c6" },
    neutral: { color: "#344054", background: "#f7f7f8", border: "#d5d8de" },
  };
  const tone = palette[state] || palette.neutral;
  el.style.color = tone.color;
  el.style.background = tone.background;
  el.style.borderColor = tone.border;
}

function setRuntimeState(text, ok = true) {
  const el = $("runtimeState");
  el.textContent = t(text) || text;
  el.style.color = ok ? "#667085" : "#344054";
}

function showStage(stage) {
  const meta = pageMetaForStage(stage);
  const page = meta.page || stage;
  const targetMode = meta.agentMode || null;
  if (targetMode && currentAgentMode !== targetMode) {
    setAgentMode(targetMode, targetMode === "learn" ? "fast" : currentLearnDepth);
  }
  document.body.dataset.workspace = meta.group || "system";
  document.querySelectorAll(".stage").forEach((button) => {
    button.classList.toggle("active", button.dataset.stage === stage);
  });
  document.querySelectorAll(".stage-page").forEach((page) => {
    page.classList.toggle("active", page.dataset.page === meta.page);
  });
  const [fallbackTitleKey, fallbackSubtitleKey] = stageMeta[page] || stageMeta.open_bind;
  $("stageTitle").textContent = t(meta.titleKey || fallbackTitleKey);
  $("stageSubtitle").textContent = t(meta.subtitleKey || fallbackSubtitleKey);
  updatePageMeta(meta);

  const flowStrip = document.querySelector(".flow-diagram-strip");
  const pathPanel = $("navPathPanel");
  const traceView = $("traceFullView");
  const contentGrid = document.querySelector(".content-grid");
  const responseSurface = document.querySelector(".response-surface");
  const previewPanel = document.querySelector(".preview-panel");
  const pathDetailPanel = $("pathDetailPanel");
  const responsePanel = document.querySelector(".response-panel");

  const needsPath = new Set(["observe", "locate", "execute_actions", "learn_replay", "learn_validation", "execute_task_run", "execute"]);
  const needsPreview = new Set(["capture", "observe", "locate", "execute"]);
  const needsResponse = new Set(["open_bind", "capture", "observe", "locate", "execute_actions", "learn_replay", "learn_validation", "execute_task_run", "execute", "input"]);
  const showsPipeline = meta.showPipeline === true;
  const singleColumn = page === "trace" || page === "model_test" || page === "input";
  const pathFocused = ["execute_actions", "learn_replay", "learn_validation", "execute_task_run"].includes(page);

  if (flowStrip) flowStrip.style.display = showsPipeline ? "" : "none";
  if (pathPanel) pathPanel.style.display = needsPath.has(page) ? "" : "none";
  if (previewPanel) previewPanel.style.display = needsPreview.has(page) ? "" : "none";
  if (pathDetailPanel) pathDetailPanel.style.display = needsPath.has(page) ? "" : "none";
  if (responsePanel) responsePanel.style.display = needsResponse.has(page) ? "" : "none";
  if (contentGrid) contentGrid.classList.toggle("single-column", singleColumn);
  if (contentGrid) contentGrid.classList.toggle("path-focused", pathFocused);
  if (responseSurface) responseSurface.style.display = page === "model_test" ? "none" : "";
  syncStageLearningControls(stage);

  if (traceView) {
    traceView.style.display = page === "trace" ? "block" : "none";
    const targetParent = page === "trace" ? document.querySelector(".control-surface") : document.querySelector(".response-surface");
    if (targetParent && traceView.parentElement !== targetParent) {
      targetParent.appendChild(traceView);
    }
  }
  if (page === "trace" && lastTracePath) inspectLatestTrace(lastTracePath);

  if (page === "open_bind") refreshWindows(false);
  if (page === "model_test") populateModelTestProfiles();
  refreshDraggableCards();
}

function updatePageMeta(meta) {
  const groupLabel = t(`workspace_${meta.group || "system"}`);
  const workspaceBadge = $("pageWorkspaceBadge");
  const apiBadge = $("pageApiBadge");
  const sideEffectBadge = $("pageSideEffectBadge");
  if (workspaceBadge) workspaceBadge.textContent = groupLabel;
  if (apiBadge) apiBadge.textContent = `API: ${meta.api || "-"}`;
  if (sideEffectBadge) {
    sideEffectBadge.textContent = t(meta.sideEffectKey || "side_effect_no_page_action");
    sideEffectBadge.dataset.sideEffect = meta.sideEffectKey || "side_effect_no_page_action";
  }
}

function cardRegionId(container) {
  if (!container) return "";
  if (container.classList.contains("control-surface")) return "control";
  if (container.classList.contains("response-surface")) return "response";
  return container.id || "";
}

function cardIdFor(card) {
  if (!card) return "";
  if (card.dataset.cardId) return card.dataset.cardId;
  const stagePage = card.dataset.page ? `stage_${card.dataset.page}` : "";
  const id = card.id || stagePage || [...card.classList].find((name) => name.endsWith("-panel")) || `card_${Math.random().toString(16).slice(2)}`;
  card.dataset.cardId = id;
  return id;
}

function sortableContainers() {
  return [
    document.querySelector(".control-surface"),
    document.querySelector(".response-surface"),
  ].filter(Boolean);
}

function cardCanMoveToContainer(card, container) {
  if (!card || !container) return false;
  if (container.classList.contains("control-surface") || container.classList.contains("response-surface")) {
    return card.classList.contains("panel");
  }
  return card.parentElement === container;
}

function sortableCardsIn(container) {
  return [...container.querySelectorAll(":scope > .panel")].filter((card) => !card.classList.contains("card-drag-placeholder"));
}

function readCardOrder() {
  try {
    return JSON.parse(localStorage.getItem(CARD_ORDER_STORAGE_KEY) || "{}");
  } catch (_error) {
    return {};
  }
}

function saveCardOrder() {
  const order = {};
  for (const container of sortableContainers()) {
    order[cardRegionId(container)] = sortableCardsIn(container).map(cardIdFor);
  }
  localStorage.setItem(CARD_ORDER_STORAGE_KEY, JSON.stringify(order));
}

function resetCardLayout() {
  localStorage.removeItem(CARD_ORDER_STORAGE_KEY);
  window.location.reload();
}

function applySavedCardOrder() {
  const order = readCardOrder();
  const allCardsById = new Map();
  for (const container of sortableContainers()) {
    for (const card of sortableCardsIn(container)) {
      allCardsById.set(cardIdFor(card), card);
    }
  }
  for (const container of sortableContainers()) {
    const region = cardRegionId(container);
    const ids = Array.isArray(order[region]) ? order[region] : [];
    for (const id of ids) {
      const card = allCardsById.get(id);
      if (card) container.appendChild(card);
    }
  }
}

function updateCardHandleLabel(card) {
  const handle = card?.querySelector(":scope > .card-drag-zone");
  if (!handle) return;
  const label = t("drag_card");
  handle.title = label;
}

function ensureCardHandle(card) {
  if (!card) return;
  if (card.dataset.dragReady === "true") {
    updateCardHandleLabel(card);
    return;
  }
  card.classList.add("draggable-card");
  cardIdFor(card);
  const handle = document.createElement("div");
  handle.className = "card-drag-zone";
  handle.title = t("drag_card");
  handle.setAttribute("aria-hidden", "true");
  handle.addEventListener("mousedown", (event) => preparePointerCardDrag(card, event));
  handle.addEventListener("pointerdown", (event) => preparePointerCardDrag(card, event));
  handle.addEventListener("mouseup", () => finishPointerCardDrag());
  card.prepend(handle);
  card.dataset.dragReady = "true";
}

function cardAfterDrag(container, x, y) {
  const cards = sortableCardsIn(container).filter((card) => {
    return card.offsetParent !== null && !card.classList.contains("dragging") && card !== activeCardDrag?.card;
  });
  return cards.reduce((closest, card) => {
    const box = card.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    if (offset < 0 && offset > closest.offset) return { offset, card };
    return closest;
  }, { offset: Number.NEGATIVE_INFINITY, card: null }).card;
}

function dragContainerAtPoint(card, x, y) {
  return sortableContainers().find((container) => {
    if (!cardCanMoveToContainer(card, container)) return false;
    const box = container.getBoundingClientRect();
    return x >= box.left && x <= box.right && y >= box.top && y <= box.bottom;
  }) || null;
}

function syncDraggedCardToPoint(x, y) {
  if (!activeCardDrag) return;
  const { card, placeholder, pointerOffsetX, pointerOffsetY } = activeCardDrag;
  card.style.left = `${x - pointerOffsetX}px`;
  card.style.top = `${y - pointerOffsetY}px`;
  const container = dragContainerAtPoint(card, x, y);
  document.querySelectorAll(".card-drop-active").forEach((dropZone) => {
    dropZone.classList.toggle("card-drop-active", dropZone === container);
  });
  if (!container) return;
  const after = cardAfterDrag(container, x, y);
  if (after && after !== placeholder.nextElementSibling) {
    container.insertBefore(placeholder, after);
  } else if (!after && placeholder.parentElement !== container) {
    container.appendChild(placeholder);
  } else if (!after && placeholder.nextElementSibling) {
    container.appendChild(placeholder);
  }
}

function preparePointerCardDrag(card, event) {
  if (!card || activeCardDrag) return;
  pendingCardDrag = {
    card,
    startX: event.clientX,
    startY: event.clientY,
  };
}

function startPointerCardDrag(card, event) {
  if (!card || activeCardDrag) return;
  const box = card.getBoundingClientRect();
  const placeholder = document.createElement("div");
  placeholder.className = "card-drag-placeholder";
  placeholder.style.width = `${box.width}px`;
  placeholder.style.height = `${box.height}px`;
  card.parentElement.insertBefore(placeholder, card);
  activeCardDrag = {
    card,
    placeholder,
    pointerOffsetX: event.clientX - box.left,
    pointerOffsetY: event.clientY - box.top,
  };
  card.classList.add("dragging");
  card.style.width = `${box.width}px`;
  card.style.height = `${box.height}px`;
  card.style.left = `${box.left}px`;
  card.style.top = `${box.top}px`;
  card.dataset.dragHandleActive = "true";
  document.body.classList.add("card-dragging-active");
  event.preventDefault();
  syncDraggedCardToPoint(event.clientX, event.clientY);
}

function finishPointerCardDrag() {
  pendingCardDrag = null;
  if (!activeCardDrag) return;
  const { card, placeholder } = activeCardDrag;
  if (placeholder.parentElement) {
    placeholder.parentElement.insertBefore(card, placeholder);
    placeholder.remove();
  }
  card.classList.remove("dragging");
  card.dataset.dragHandleActive = "false";
  card.style.width = "";
  card.style.height = "";
  card.style.left = "";
  card.style.top = "";
  activeCardDrag = null;
  if (activeCardDragFrame) {
    cancelAnimationFrame(activeCardDragFrame);
    activeCardDragFrame = null;
  }
  document.body.classList.remove("card-dragging-active");
  document.querySelectorAll(".card-drop-active").forEach((container) => {
    container.classList.remove("card-drop-active");
  });
  saveCardOrder();
}

function initializeCardDrag(container) {
  if (!container || container.dataset.dragDropReady === "true") return;
  container.dataset.dragDropReady = "true";
}

function refreshDraggableCards() {
  for (const container of sortableContainers()) {
    initializeCardDrag(container);
    sortableCardsIn(container).forEach(ensureCardHandle);
  }
}

document.addEventListener("mousemove", (event) => {
  if (pendingCardDrag && !activeCardDrag) {
    const dx = event.clientX - pendingCardDrag.startX;
    const dy = event.clientY - pendingCardDrag.startY;
    if (Math.hypot(dx, dy) < CARD_DRAG_START_THRESHOLD_PX) return;
    startPointerCardDrag(pendingCardDrag.card, event);
    pendingCardDrag = null;
  }
  if (!activeCardDrag) return;
  const x = event.clientX;
  const y = event.clientY;
  if (activeCardDragFrame) cancelAnimationFrame(activeCardDragFrame);
  activeCardDragFrame = requestAnimationFrame(() => {
    activeCardDragFrame = null;
    syncDraggedCardToPoint(x, y);
  });
});

document.addEventListener("mouseup", () => finishPointerCardDrag());
document.addEventListener("mouseleave", () => finishPointerCardDrag());

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") finishPointerCardDrag();
});
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
    const ok = response.ok && data.success !== false;
    setStatus(ok ? statusTextForResponse(data) : "failed", ok ? "ok" : "error");
    markWorkflow(workflowStep, ok ? "done" : "error");
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

function statusTextForResponse(response) {
  const result = resultOf(response);
  if (
    result?.location_status === "learn_all_targets_ready"
    || result?.learn_all_targets?.status === "ready"
    || (result?.agent_mode === "learn" && result?.learn_depth === "deep" && result?.mode_contract_version === "learn_screen_deep_v1")
  ) {
    return "path_graph_calibrated";
  }
  return "ok";
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

function isOperationalProfile(profile) {
  return profile?.launchable !== false;
}

function defaultProfileId(stage) {
  const stageText = String(stage || "").toLowerCase();
  const preferred = DEFAULT_STAGE_PROFILE_IDS[stageText];
  if (preferred && isOperationalProfile(profileById(preferred))) return preferred;
  const expected = stageText === "observe" ? "understanding" : stageText === "locate" ? "grounding" : stageText;
  const availableProfiles = modelProfiles.filter(isOperationalProfile);
  const byRole = availableProfiles.find((profile) => (profile.role || []).map((item) => String(item).toLowerCase()).includes(expected));
  return (byRole || availableProfiles[0] || {}).profile_id || "";
}

function selectProfileForStage(stage, selectId) {
  const select = $(selectId);
  const current = select.value;
  const currentProfile = profileById(current);
  const next = current && isOperationalProfile(currentProfile) ? current : defaultProfileId(stage);
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
  for (const profile of modelProfiles.filter(isOperationalProfile)) {
    const option = document.createElement("option");
    option.value = profile.profile_id || "";
    option.textContent = profileLabel(profile);
    select.appendChild(option);
  }
  const previousProfile = profileById(previous);
  select.value = previous && isOperationalProfile(previousProfile) ? previous : defaultProfileId(stage);
  return profileById(select.value);
}

/* 鈹€鈹€ Model test page 鈹€鈹€ */

function populateModelTestProfiles() {
  const sel = $("modelTestProfile");
  if (!sel) return;
  sel.innerHTML = modelProfiles.map((p) => {
    const label = profileLabel(p);
    return `<option value="${p.profile_id || ""}">${label}</option>`;
  }).join("") || '<option value="">-- none --</option>';
  syncModelTestProfile();
}

function syncModelTestProfile() {
  const sel = $("modelTestProfile");
  const stageEl = $("modelTestStage");
  if (!sel || !stageEl) return null;
  const current = sel.value;
  const preferred = defaultProfileId(stageEl.value);
  if (!current || !profileById(current) || profileById(current)?.provider_mode !== profileById(preferred)?.provider_mode) {
    sel.value = preferred;
  }
  return profileById(sel.value);
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
    $("modelTestResponse").innerHTML = '<p class="trace-idle" style="color:#344054;">Select a model profile first.</p>';
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
      $("modelTestResponse").innerHTML = `<p class="trace-idle" style="color:#344054;">${escapeHtml(String(detail))}</p>`;
      return;
    }
    const data = response.data || {};
    const content = data.content || JSON.stringify(data.raw_response || data, null, 2);
    $("modelTestResponse").innerHTML = `<div class="model-test-meta">${escapeHtml(data.model || profileId)}${data.image_attached ? " | image attached" : ""}</div><pre class="model-test-output">${escapeHtml(String(content))}</pre>`;
  } catch (e) {
    $("modelTestResponse").innerHTML = `<p class="trace-idle" style="color:#344054;">Request failed: ${escapeHtml(e.message)}</p>`;
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

function appCatalogLabel(app) {
  const appId = String(app.app_id || "");
  const name = String(app.name || appId || "");
  const process = String(app.process_name || "");
  return [appId, name, process].filter(Boolean).join(" | ");
}

function setAppCatalog(apps) {
  appCatalog = Array.isArray(apps) ? apps.filter((item) => item && typeof item === "object") : [];
  const select = $("appCatalogSelect");
  const list = $("appCatalogOptions");
  if (!select || !list) return;
  select.innerHTML = "";
  list.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = t("select_launch_app");
  select.appendChild(placeholder);
  if (!appCatalog.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = t("no_apps");
    select.appendChild(option);
    return;
  }
  for (const app of appCatalog) {
    const option = document.createElement("option");
    option.value = String(app.app_id || "");
    option.textContent = appCatalogLabel(app);
    select.appendChild(option);

    const dataOption = document.createElement("option");
    dataOption.value = String(app.app_id || "");
    dataOption.label = appCatalogLabel(app);
    list.appendChild(dataOption);
  }
  const current = $("appId")?.value || "";
  if (current && appCatalog.some((app) => app.app_id === current)) {
    select.value = current;
  } else {
    select.value = "";
  }
}

function applySelectedCatalogApp() {
  const selected = $("appCatalogSelect")?.value || "";
  const app = appCatalog.find((item) => String(item.app_id || "") === selected);
  if (!app) return;
  $("appId").value = String(app.app_id || "");
  if (app.process_name) $("bindProcess").value = String(app.process_name);
  if (app.title_hint) $("bindTitle").value = String(app.title_hint);
  syncWindowAppAndState();
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

function selectedWindowCandidate() {
  const selected = $("windowSelect")?.value || "";
  return windowCandidates.find((item) => windowCandidateLabel(item) === selected) || null;
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
    .replace(/[\u200B-\u200D\uFEFF]/g, "")
    .replace(/\u00A0/g, " ")
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
  const hasCandidate = candidate && typeof candidate === "object";
  const processName = String(candidate?.process_name || $("bindProcess")?.value || "").trim();
  const inferredAppId = appIdFromProcessName(processName);
  const urlAppName = appNameFromUrl($("appUrl")?.value);
  const title = stripBrowserTitleSuffix(candidate?.title || $("bindTitle")?.value || "");
  const titleAppName = canonicalAppNameFromTitle(title);

  if (hasCandidate) {
    if (inferredAppId && !BROWSER_APP_IDS.has(inferredAppId.toLowerCase())) return inferredAppId;
    if (titleAppName && !/^(microsoft edge|google chrome|mozilla firefox)$/i.test(titleAppName)) {
      return titleAppName;
    }
    if (urlAppName) return urlAppName;
    return inferredAppId || processName.replace(/\.exe$/i, "");
  }

  const appId = String($("appId")?.value || "").trim();
  if (appId && !BROWSER_APP_IDS.has(appId.toLowerCase())) return appId;
  if (urlAppName) return urlAppName;
  if (titleAppName && !/^(microsoft edge|google chrome|mozilla firefox)$/i.test(titleAppName)) {
    return titleAppName;
  }
  return inferredAppId || processName.replace(/\.exe$/i, "");
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
    const tail = cleanTitle.slice(normalizedAppName.length).replace(/^\s*[-|–—:：]?\s*/, "").trim();
    if (tail) return tail;
  }

  if (normalizedAppName === "MouseTesterWeb" && /mousetester/i.test(cleanTitle)) {
    return cleanTitle;
  }
  return cleanTitle;
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
    ["observeApp", "locateApp", "executeApp", "executeActionsApp"].forEach((id) => {
      const el = $(id);
      if (el) el.value = normalizedAppName;
    });
    navPathAppName = normalizedAppName;
    updatePathAppLabel();
  }
  if (normalizedStateHint) {
    ["observeState", "locateState", "executeActionsState"].forEach((id) => {
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
  if (!selected) {
    renderResponse(
      {
        success: false,
        message: `Model service not found for ${stage}`,
        data: { contract_version: "runtime_model_service_test_v1", stage, profile_id: profileId || null },
      },
      "model service test",
    );
    setStatus("model service not found", "error");
    return response;
  }
  const serviceStatus = selected.status?.status || "unknown";
  const ok = serviceStatus === "running";
  renderResponse(
    {
      success: ok,
      message: `Model service ${serviceStatus}`,
      data: { contract_version: "runtime_model_service_test_v1", stage, model: selected },
    },
    "model service test",
  );
  if (ok) {
    setStatus("ok", "ok");
  } else if (serviceStatus === "loading") {
    setStatus("model service loading", "warning");
  } else {
    setStatus(`model service ${serviceStatus}`, "error");
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
  svg.setAttribute("viewBox", "0 0 1120 62");

  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  defs.innerHTML = `
    <filter id="flowShadow"><feDropShadow dx="0" dy="1" stdDeviation="1.2" flood-opacity="0.06"/></filter>
    <marker id="flowArr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="4" markerHeight="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#cbd5e1"/></marker>
    <marker id="flowArrDone" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="4" markerHeight="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#14804a"/></marker>
    <marker id="flowArrActive" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="4" markerHeight="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#111827"/></marker>
  `;
  svg.appendChild(defs);

  const N = ALL_FLOW_STAGES.length;
  const w = 1120;
  const h = 62;
  const nodeW = 104;
  const nodeH = 44;
  const gap = (w - 20 - N * nodeW) / (N - 1);
  const top = (h - nodeH) / 2;

  ALL_FLOW_STAGES.forEach((stage, i) => {
    const x = 10 + i * (nodeW + gap);
    const y = top;
    const status = flowStageStatus[stage.id] || "inactive";

    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");

    const pill = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    pill.setAttribute("x", x);
    pill.setAttribute("y", y);
    pill.setAttribute("width", nodeW);
    pill.setAttribute("height", nodeH);
    pill.setAttribute("rx", "10");
    pill.setAttribute("ry", "10");

    if (status === "done") {
      pill.setAttribute("fill", "#ecfdf3");
      pill.setAttribute("stroke", "#a7f0ba");
      pill.setAttribute("stroke-width", "1");
    } else if (status === "active") {
      pill.setAttribute("fill", "#f8fafc");
      pill.setAttribute("stroke", "#111827");
      pill.setAttribute("stroke-width", "1.2");
      pill.setAttribute("filter", "url(#flowShadow)");
    } else if (status === "error") {
      pill.setAttribute("fill", "#f7f1f1");
      pill.setAttribute("stroke", "#d8c6c6");
      pill.setAttribute("stroke-width", "1");
    } else if (status === "blocked") {
      pill.setAttribute("fill", "#f7f4ee");
      pill.setAttribute("stroke", "#d8d0c1");
      pill.setAttribute("stroke-width", "1");
    } else {
      pill.setAttribute("fill", "#ffffff");
      pill.setAttribute("stroke", "#e5ebf3");
      pill.setAttribute("stroke-width", "1");
    }
    g.appendChild(pill);

    // Step number circle
    const cx = x + 18;
    const cy = y + nodeH / 2;
    const circ = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circ.setAttribute("cx", cx);
    circ.setAttribute("cy", cy);
    circ.setAttribute("r", "11");
    if (status === "done") {
      circ.setAttribute("fill", "#14804a");
    } else if (status === "active") {
      circ.setAttribute("fill", "#111827");
    } else if (status === "error") {
      circ.setAttribute("fill", "#725757");
    } else if (status === "blocked") {
      circ.setAttribute("fill", "#71634e");
    } else {
      circ.setAttribute("fill", "#cbd5e1");
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
    num.textContent = status === "done" ? "✓" : String(i + 1);
    g.appendChild(num);

    // Label
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", x + 36);
    label.setAttribute("y", cy + 1);
    label.setAttribute("text-anchor", "start");
    label.setAttribute("dominant-baseline", "middle");
    label.setAttribute("font-size", "11");
    label.setAttribute("font-weight", status === "inactive" ? "500" : "700");
    label.setAttribute("font-family", "system-ui, -apple-system, sans-serif");
    label.setAttribute("fill", status === "inactive" ? "#98a2b3" : status === "done" ? "#14804a" : status === "active" ? "#111827" : status === "blocked" ? "#71634e" : status === "error" ? "#725757" : "#344054");
    label.textContent = stage.label;
    g.appendChild(label);

    svg.appendChild(g);

    // Connector
    if (i < N - 1) {
      const nextStatus = flowStageStatus[ALL_FLOW_STAGES[i + 1].id] || "inactive";
      const connColor = status === "done" && (nextStatus === "done" || nextStatus === "active") ? "#14804a"
        : status === "active" ? "#111827"
        : "#cbd5e1";
      const marker = status === "done" && (nextStatus === "done" || nextStatus === "active") ? "url(#flowArrDone)"
        : status === "active" ? "url(#flowArrActive)"
        : "url(#flowArr)";

      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", x + nodeW + 2);
      line.setAttribute("y1", cy);
      line.setAttribute("x2", x + nodeW + gap - 3);
      line.setAttribute("y2", cy);
      line.setAttribute("stroke", connColor);
      line.setAttribute("stroke-width", "1.2");
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
  const overlayPath = result.coordinate_overlay_path
    || nestedGet(result, ["learn_all_targets", "overlay_path"])
    || nestedGet(result, ["learn_all_targets", "overlay", "output_path"])
    || result.overlay_path
    || result.output_path
    || result.manual_overlay_path
    || nestedGet(lastResponse, ["data", "manual_overlay_path"])
    || nestedGet(result, ["recognition_plan_overlay", "overlay_path"])
    || nestedGet(result, ["recognition_plan_overlay", "output_path"])
    || nestedGet(result, ["recognition_plan_overlay", "data", "result", "output_path"]);
  if (overlayPath) setCurrentImage(overlayPath);
  const suggestedState = nestedGet(result, ["suggested_state_hint"]);
  if (suggestedState) {
    syncAppAndStateFields({ stateHint: suggestedState });
  }
  populateReviewCandidate(result);
  const approvedPlanId = result.approved_plan_id
    || nestedGet(result, ["agent_execution_guidance", "next_request", "body", "approved_plan_id"]);
  if (approvedPlanId && $("approvedPlanId")) {
    $("approvedPlanId").value = approvedPlanId;
  }
  const learnedInstructionId = result.learned_instruction_id;
  if (learnedInstructionId && $("learnedInstructionId")) {
    $("learnedInstructionId").value = learnedInstructionId;
  }
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
  runtimePathGraphView = null;
  setPathGraphBadges({ mode: "learn graph", state: "live observe" });
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
  expandedPathNodeId = null;
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
  const normalizedCandidateId = compactText(extra.candidateId, 100);

  // Avoid duplicate controls on same page
  const existing = page.controls.find((c) => (normalizedCandidateId && c.candidateId === normalizedCandidateId) || c.label === normalizedLabel);
  if (existing) {
    // Update with latest semantics and coordinates.
    existing.label = normalizedLabel;
    if (type) existing.type = type;
    if (normalizedBbox) existing.bbox = normalizedBbox;
    if (normalizedPoint) existing.clickPoint = normalizedPoint;
    if (normalizedDescription) existing.description = normalizedDescription;
    if (extra.possibleNav) existing.possibleNav = extra.possibleNav;
    if (extra.action) existing.action = extra.action;
    if (extra.confidence !== undefined) existing.confidence = extra.confidence;
    if (extra.sectionId) existing.sectionId = extra.sectionId;
    if (normalizedCandidateId) existing.candidateId = normalizedCandidateId;
    if (extra.source) existing.source = compactText(extra.source, 60);
    if (extra.pathMapReview) existing.pathMapReview = extra.pathMapReview;
    navPathDirty = true;
    liveSessionSnapshot = null;
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
    candidateId: normalizedCandidateId,
    pathMapReview: extra.pathMapReview || null,
  });
  navPathDirty = true;
  liveSessionSnapshot = null;
}

function applyPathMapReview(review) {
  if (!review || review.contract_version !== "path_map_review_v1" || !["ready", "learn_all_targets"].includes(review.status)) return;
  if (!currentNavNodeId) return;
  const page = navPathNodes.find((n) => n.id === currentNavNodeId);
  if (!page || !Array.isArray(page.controls)) return;

  let changed = false;
  for (const removal of collectArray(review.removals)) {
    const before = page.controls.length;
    page.controls = page.controls.filter((control) => !pathReviewRemovalMatchesControl(removal, control));
    if (page.controls.length !== before) changed = true;
  }

  for (const update of collectArray(review.updates)) {
    if (applyPathReviewUpdate(page, update, review)) changed = true;
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

function applyPathReviewUpdate(page, update, review) {
  const candidateId = compactText(update.candidate_id || update.id, 100);
  const fields = update.fields && typeof update.fields === "object" ? update.fields : update;
  const control = page.controls.find((item) => {
    if (candidateId && item.candidateId === candidateId) return true;
    return pathReviewLabelKey(update.label) && pathReviewLabelKey(update.label) === pathReviewLabelKey(item.label);
  });
  if (!control) return false;
  const nextLabel = compactText(fields.label || update.label, 80);
  const nextBbox = normalizeBBox(fields.bbox || update.bbox);
  const nextPoint = normalizePoint(fields.click_point || fields.clickPoint || update.click_point || update.clickPoint, nextBbox || control.bbox);
  if (nextLabel) control.label = nextLabel;
  if (fields.role || fields.type) control.type = compactText(fields.role || fields.type, 60);
  if (fields.description || fields.expected_effect) control.description = compactText(fields.description || fields.expected_effect, 160);
  if (fields.section_id || fields.sectionId) control.sectionId = compactText(fields.section_id || fields.sectionId, 80);
  if (nextBbox) control.bbox = nextBbox;
  if (nextPoint) control.clickPoint = nextPoint;
  if (fields.confidence !== undefined) control.confidence = fields.confidence;
  control.source = compactText(fields.source || update.source || "learn_locate_model_review", 60);
  control.pathMapReview = { action: "update", source: review.review_source || review.source, stateId: review.state_id };
  return true;
}

function pathReviewRemovalMatchesControl(removal, control) {
  if (!removal || !control) return false;
  if (control.status === "clicked" || control.navigatedToPageId) return false;
  const source = String(control.source || "");
  const removableSource = !source || ["observe", "screen_map", "locate_path_review", "locate_candidate", "learn_all_targets", "learn_locate_model_review"].includes(source);
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

  runtimePathGraphView = null;
  setPathGraphBadges({ mode: "live/history", state: appName || "loaded" });
  navPathNodes = data.nodes || [];
  navPathEdges = data.edges || [];
  navPathCounter = data.counter || navPathNodes.length;
  navPathAppName = data.appName || appName;
  currentNavNodeId = navPathNodes.length ? navPathNodes[navPathNodes.length - 1].id : null;
  expandedPathNodeId = null;
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
  runtimePathGraphView = null;
  setPathGraphBadges({ mode: "live", state: "idle" });
  navPathNodes = [];
  navPathEdges = [];
  currentNavNodeId = null;
  expandedPathNodeId = null;
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
  const mode = $("traceModeFilter")?.value || "";
  const query = new URLSearchParams({ limit: "60" });
  if (mode) query.set("mode", mode);
  fetch(`${baseUrl()}/panel/list_traces?${query.toString()}`).then((r) => r.json()).then((resp) => {
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
    const mode = t.agent_mode ? `[${t.agent_mode}] ` : "";
    const op = t.operation ? `${t.operation} | ` : "";
    opt.textContent = `${cat}${mode}${op}${t.name}`;
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
    if (leftEl) leftEl.innerHTML = `<p class="trace-idle" style="color:#344054;">${escapeHtml(String(errMsg))}</p>`;
    if (fullEl) fullEl.innerHTML = `<p class="trace-idle" style="color:#344054;">${escapeHtml(String(errMsg))}</p>`;
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
let expandedPathNodeId = null;
let pathSectionLayouts = [];

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
  if (!pathHoveredNode || pathHoveredNode === "__pending__" || isPathControlNodeId(pathHoveredNode)) return;
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
  if (expandedPathNodeId === nodeId) {
    expandedPathNodeId = null;
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
      handlePathNodeClick(pathHoveredNode);
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
    const hitRadius = pos.isControl ? 18 : PATH_GLOW_R;
    if (Math.sqrt(dx * dx + dy * dy) < hitRadius / pathZoom) {
      found = pos.id;
      break;
    }
  }
  pathHoveredNode = found;
  pathCanvas.style.cursor = found && found !== "__pending__" ? "pointer" : pathDragging ? "grabbing" : "grab";
}

function isPathControlNodeId(nodeId) {
  return String(nodeId || "").startsWith("control:");
}

function pathControlNodeId(pageId, index) {
  return `control:${pageId}:${index}`;
}

function parsePathControlNodeId(nodeId) {
  const text = String(nodeId || "");
  if (!text.startsWith("control:")) return null;
  const lastColon = text.lastIndexOf(":");
  if (lastColon <= "control:".length) return null;
  const pageId = text.slice("control:".length, lastColon);
  const index = Number(text.slice(lastColon + 1));
  if (!Number.isInteger(index) || index < 0) return null;
  return { pageId, index };
}

function handlePathNodeClick(nodeId) {
  const controlRef = parsePathControlNodeId(nodeId);
  if (controlRef) {
    currentNavNodeId = controlRef.pageId;
    expandedPathNodeId = controlRef.pageId;
    showNavNodeDetail(controlRef.pageId, controlRef.index);
    renderNavPath();
    $("pathDetailContent")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    return;
  }
  if (!navPathNodes.some((n) => n.id === nodeId)) return;
  expandedPathNodeId = expandedPathNodeId === nodeId ? null : nodeId;
  currentNavNodeId = nodeId;
  showNavNodeDetail(nodeId);
}

function layoutPathNodes() {
  const w = pathCanvas ? pathCanvas.clientWidth : 600;
  const h = pathCanvas ? pathCanvas.clientHeight : 300;
  if (isRuntimeGraphViewActive()) return layoutRuntimePathGraphNodes(w, h);
  const cx = w / 2;
  const cy = expandedPathNodeId ? h * 0.66 : h / 2;
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
  const expandedId = expandedPathNodeId;
  const expandedPage = expandedId ? navPathNodes.find((n) => n.id === expandedId) : null;
  const parent = expandedPage ? allNodes.find((n) => n.id === expandedPage.id) : null;
  pathSectionLayouts = [];
  const controls = Array.isArray(expandedPage?.controls) ? expandedPage.controls : [];
  if (parent && controls.length) {
    const visibleControls = controls.slice(0, 32);
    const groups = groupPathControlsBySection(visibleControls);
    const childAreaLeft = parent.x < w * 0.42 ? Math.min(w - 220, parent.x + 112) : 48;
    const laneLeft = Math.max(44, Math.min(w - 220, childAreaLeft));
    const laneWidth = Math.max(180, w - laneLeft - 44);
    const rowGap = 68;
    const laneGap = 20;
    const headerH = 26;
    const minLaneH = 92;
    const lanePlans = groups.map((group) => {
      const grid = computePathControlGrid(group.controls, laneWidth, { compact: true });
      const rows = Math.ceil(group.controls.length / grid.cols);
      return {
        group,
        grid,
        rows,
        height: Math.max(minLaneH, headerH + rows * rowGap + 16),
      };
    });
    const totalHeight = lanePlans.reduce((sum, plan) => sum + plan.height, 0) + Math.max(0, lanePlans.length - 1) * laneGap;
    const startY = Math.max(36, Math.min(Math.max(36, h - totalHeight - 28), parent.y - totalHeight / 2));
    let cursorY = startY;
    for (const plan of lanePlans) {
      const panel = {
        key: plan.group.key,
        label: plan.group.label,
        count: plan.group.controls.length,
        x: laneLeft,
        y: cursorY,
        w: laneWidth,
        h: plan.height,
      };
      pathSectionLayouts.push(panel);
      plan.group.controls.forEach(({ ctrl, originalIndex }, localIndex) => {
        const col = localIndex % plan.grid.cols;
        const row = Math.floor(localIndex / plan.grid.cols);
        allNodes.push({
          id: pathControlNodeId(expandedPage.id, originalIndex),
          parentId: expandedPage.id,
          controlIndex: originalIndex,
          label: ctrl.label || ctrl.type || "control",
          type: ctrl.type || "control",
          sectionId: ctrl.sectionId || ctrl.section_id || "",
          index: originalIndex,
          x: panel.x + plan.grid.left + plan.grid.colWidth * (col + 0.5),
          y: panel.y + headerH + 24 + row * rowGap,
          labelMaxWidth: Math.max(54, plan.grid.colWidth - 14),
          isCurrent: false,
          isPending: false,
          isControl: true,
        });
      });
      cursorY += plan.height + laneGap;
    }
  }
  return allNodes;
}

function layoutRuntimePathGraphNodes(w, h) {
  const marginX = 92;
  const marginY = 70;
  const nodes = navPathNodes;
  if (!nodes.length) return [];
  const outgoing = new Map();
  const indegree = new Map(nodes.map((node) => [node.id, 0]));
  for (const edge of navPathEdges) {
    if (!outgoing.has(edge.from)) outgoing.set(edge.from, []);
    outgoing.get(edge.from).push(edge.to);
    if (edge.from !== edge.to && indegree.has(edge.to)) indegree.set(edge.to, (indegree.get(edge.to) || 0) + 1);
  }
  const queue = nodes.filter((node) => (indegree.get(node.id) || 0) === 0).map((node) => node.id);
  if (!queue.length && nodes[0]) queue.push(nodes[0].id);
  const depth = new Map(queue.map((id) => [id, 0]));
  for (let qi = 0; qi < queue.length; qi++) {
    const id = queue[qi];
    const nextDepth = (depth.get(id) || 0) + 1;
    for (const next of outgoing.get(id) || []) {
      if (next === id) continue;
      if (!depth.has(next) || nextDepth > depth.get(next)) {
        depth.set(next, nextDepth);
        queue.push(next);
      }
    }
  }
  nodes.forEach((node, index) => {
    if (!depth.has(node.id)) depth.set(node.id, Math.min(index, 4));
  });
  const columns = new Map();
  nodes.forEach((node) => {
    const d = Math.min(5, Math.max(0, depth.get(node.id) || 0));
    if (!columns.has(d)) columns.set(d, []);
    columns.get(d).push(node);
  });
  const colKeys = Array.from(columns.keys()).sort((a, b) => a - b);
  const usableW = Math.max(320, w - marginX * 2);
  const colGap = colKeys.length <= 1 ? 0 : usableW / (colKeys.length - 1);
  const positions = [];
  colKeys.forEach((colKey, colIndex) => {
    const colNodes = columns.get(colKey) || [];
    const x = colKeys.length <= 1 ? w / 2 : marginX + colGap * colIndex;
    const usableH = Math.max(160, h - marginY * 2);
    const rowGap = colNodes.length <= 1 ? 0 : Math.min(132, usableH / (colNodes.length - 1));
    const totalH = rowGap * Math.max(0, colNodes.length - 1);
    const startY = h / 2 - totalH / 2;
    colNodes.forEach((node, rowIndex) => {
      positions.push({
        id: node.id,
        index: nodes.findIndex((item) => item.id === node.id),
        x,
        y: startY + rowGap * rowIndex,
        isCurrent: node.id === currentNavNodeId,
        isPending: false,
        isRuntime: true,
        labelMaxWidth: Math.max(120, Math.min(190, colGap ? colGap - 24 : 180)),
      });
    });
  });
  return positions;
}

function computePathControlGrid(controls, canvasWidth, options = {}) {
  const visibleCount = Math.max(1, controls.length);
  const horizontalPad = options.compact ? 24 : 96;
  const usableWidth = Math.max(180, canvasWidth - horizontalPad);
  const longestUnits = Math.max(
    8,
    ...controls.map((ctrl) => visualTextUnits(ctrl.label || ctrl.type || "control")),
  );
  const preferredColWidth = Math.max(84, Math.min(154, 34 + longestUnits * 6.2));
  const maxCols = Math.max(1, Math.floor(usableWidth / preferredColWidth));
  const cols = Math.max(1, Math.min(8, visibleCount, maxCols));
  const colWidth = usableWidth / cols;
  return {
    cols,
    colWidth,
    left: (canvasWidth - usableWidth) / 2,
  };
}

function groupPathControlsBySection(controls) {
  const order = ["page_header", "main_content", "right_sidebar", "promo_strip", "lower_content", "floating_overlay", "other"];
  const groups = new Map();
  controls.forEach((ctrl, originalIndex) => {
    const key = normalizePathSectionId(ctrl.sectionId || ctrl.section_id || ctrl.section || "");
    if (!groups.has(key)) groups.set(key, { key, label: pathSectionLabel(key), controls: [] });
    groups.get(key).controls.push({ ctrl, originalIndex });
  });
  return Array.from(groups.values()).sort((a, b) => {
    const ai = order.indexOf(a.key);
    const bi = order.indexOf(b.key);
    return (ai === -1 ? order.length : ai) - (bi === -1 ? order.length : bi);
  });
}

function normalizePathSectionId(sectionId) {
  const value = String(sectionId || "").trim().toLowerCase();
  if (!value) return "other";
  if (value.includes("header") || value.includes("nav")) return "page_header";
  if (value.includes("right") || value.includes("sidebar")) return "right_sidebar";
  if (value.includes("promo")) return "promo_strip";
  if (value.includes("lower") || value.includes("bottom")) return "lower_content";
  if (value.includes("float") || value.includes("overlay")) return "floating_overlay";
  if (value.includes("main") || value.includes("content") || value.includes("body")) return "main_content";
  return value;
}

function pathSectionLabel(sectionId) {
  const labels = {
    page_header: "Top navigation",
    main_content: "Main content",
    right_sidebar: "Right sidebar",
    promo_strip: "Promo / feature strip",
    lower_content: "Lower content",
    floating_overlay: "Floating overlay",
    other: "Other controls",
  };
  return labels[sectionId] || sectionId.replace(/_/g, " ");
}

function visualTextUnits(value) {
  return Array.from(String(value || "")).reduce((total, char) => total + (char.charCodeAt(0) > 255 ? 1.7 : 1), 0);
}

function setPathGraphBadges({ mode = "live", state = "idle" } = {}) {
  const modeBadge = $("pathGraphModeBadge");
  const stateBadge = $("pathGraphStateBadge");
  if (modeBadge) modeBadge.textContent = mode;
  if (stateBadge) stateBadge.textContent = state;
}

function runtimeGraphStateLabel(state) {
  return String(state?.label || state?.state_id || "state").replace(/_/g, " ");
}

function runtimeGraphActionLabel(edge) {
  return String(edge?.label || edge?.action_template_id || edge?.action_id || "action").replace(/_/g, " ");
}

function runtimeGraphTemplateMap(graph) {
  const map = new Map();
  for (const item of Array.isArray(graph?.action_templates) ? graph.action_templates : []) {
    if (!item || typeof item !== "object") continue;
    const id = String(item.action_template_id || item.action_id || "");
    if (id) map.set(id, item);
  }
  return map;
}

function runtimeTransitionId(edge) {
  return String(edge?.transition_id || `${edge?.from_state_id || ""}->${edge?.to_state_id || ""}:${edge?.action_template_id || ""}`);
}

function isRuntimeGraphViewActive() {
  return !!runtimePathGraphView?.graph;
}

function renderRuntimePathGraph(graph, options = {}) {
  if (!graph || typeof graph !== "object") return;
  const states = Array.isArray(graph.states) ? graph.states.filter((item) => item && typeof item === "object") : [];
  const transitions = Array.isArray(graph.transitions) ? graph.transitions.filter((item) => item && typeof item === "object") : [];
  const templates = runtimeGraphTemplateMap(graph);
  const stateIds = new Set(states.map((state) => String(state.state_id || "")).filter(Boolean));
  for (const edge of transitions) {
    if (edge.from_state_id) stateIds.add(String(edge.from_state_id));
    if (edge.to_state_id) stateIds.add(String(edge.to_state_id));
  }
  const stateList = states.length
    ? states
    : Array.from(stateIds).map((stateId) => ({ state_id: stateId, label: stateId }));
  navPathNodes = stateList.map((state, index) => ({
    id: String(state.state_id || `state-${index + 1}`),
    label: runtimeGraphStateLabel(state),
    summary: state.description || state.page_type || graph.page_type || "",
    stateGuess: state.page_type || state.state_id || "",
    imagePath: "",
    timestamp: "",
    controls: [],
    runtimeGraphNode: true,
  }));
  const knownNodeIds = new Set(navPathNodes.map((node) => node.id));
  navPathEdges = transitions
    .filter((edge) => knownNodeIds.has(String(edge.from_state_id || "")) && knownNodeIds.has(String(edge.to_state_id || "")))
    .map((edge) => {
      const actionId = String(edge.action_template_id || edge.action_id || "");
      const template = templates.get(actionId) || {};
      const transitionId = runtimeTransitionId(edge);
      return {
        from: String(edge.from_state_id || ""),
        to: String(edge.to_state_id || ""),
        goal: runtimeGraphActionLabel({ ...template, ...edge }),
        action: actionId,
        transitionId,
        actionTemplateId: actionId,
        skillRef: template.learned_skill_ref || template.skill_ref || "",
        lowLevelActionType: inferTemplateLowLevel(actionId, template),
        forbidden: edge.default_available === false || template?.availability_policy?.default_available === false,
      };
    });
  const firstState = options.currentStateId || graph.initial_state_id || navPathEdges[0]?.from || navPathNodes[0]?.id || null;
  currentNavNodeId = firstState;
  pendingTransition = null;
  expandedPathNodeId = null;
  navPathCounter = navPathNodes.length;
  navPathAppName = graph.app_id || options.path || "runtime_path_graph";
  runtimePathGraphView = {
    graph,
    path: options.path || "",
    mode: options.mode || "replay",
    currentStateId: firstState,
    currentTransitionId: options.currentTransitionId || null,
    completedTransitionIds: new Set(options.completedTransitionIds || []),
    failedTransitionIds: new Set(options.failedTransitionIds || []),
    forbiddenActionIds: new Set(navPathEdges.filter((edge) => edge.forbidden).map((edge) => edge.actionTemplateId)),
  };
  updatePathAppLabel();
  setPathGraphBadges({
    mode: `${runtimePathGraphView.mode} graph`,
    state: firstState || "no state",
  });
  renderNavPath();
}

function updateRuntimePathGraphHighlight({ currentStateId = null, action = null, response = null, success = true } = {}) {
  if (!runtimePathGraphView?.graph) return;
  const runtimeState =
    nestedGet(response, ["data", "path_graph_runtime_state_v1"]) ||
    nestedGet(response, ["data", "result", "path_graph_runtime_state_v1"]) ||
    nestedGet(response, ["path_graph_runtime_state_v1"]) ||
    {};
  const actionId = String(
    runtimeState.action_template_id ||
    action?.action_template_id ||
    action?.action_id ||
    "",
  );
  const edge = navPathEdges.find((item) =>
    (runtimeState.transition_id && item.transitionId === runtimeState.transition_id) ||
    (actionId && item.actionTemplateId === actionId && (!currentStateId || item.from === currentStateId)) ||
    (actionId && item.actionTemplateId === actionId)
  );
  const afterState = runtimeState.after_state_id || action?.to_state_id || edge?.to || currentStateId || runtimePathGraphView.currentStateId;
  const beforeState = runtimeState.before_state_id || currentStateId || runtimePathGraphView.currentStateId;
  const transitionId = runtimeState.transition_id || edge?.transitionId || null;
  runtimePathGraphView.currentStateId = afterState || beforeState || runtimePathGraphView.currentStateId;
  runtimePathGraphView.currentTransitionId = transitionId;
  if (transitionId) {
    if (success) runtimePathGraphView.completedTransitionIds.add(transitionId);
    else runtimePathGraphView.failedTransitionIds.add(transitionId);
  }
  currentNavNodeId = runtimePathGraphView.currentStateId;
  setPathGraphBadges({
    mode: `${runtimePathGraphView.mode} graph`,
    state: `${runtimePathGraphView.currentStateId || "unknown"}${actionId ? ` / ${actionId}` : ""}`,
  });
  renderNavPath();
}

function expandedPathControls() {
  if (!expandedPathNodeId) return [];
  const page = navPathNodes.find((node) => node.id === expandedPathNodeId);
  return Array.isArray(page?.controls) ? page.controls.slice(0, 32) : [];
}

function updatePathCanvasHeight() {
  const wrap = pathCanvas?.parentElement;
  if (!wrap) return;
  if (isRuntimeGraphViewActive()) {
    wrap.classList.add("runtime-graph");
    wrap.classList.remove("expanded");
    const nodeCount = Math.max(1, navPathNodes.length);
    wrap.style.height = `${Math.max(480, Math.min(760, 420 + nodeCount * 22))}px`;
    return;
  }
  wrap.classList.remove("runtime-graph");
  const controls = expandedPathControls();
  if (!controls.length) {
    wrap.classList.remove("expanded");
    wrap.style.height = "";
    return;
  }
  const width = wrap.getBoundingClientRect().width || pathCanvas.clientWidth || 600;
  const groupCount = groupPathControlsBySection(controls).length;
  const grid = computePathControlGrid(controls, Math.max(180, width - 160), { compact: true });
  const rows = Math.ceil(controls.length / grid.cols);
  const targetHeight = Math.max(400, Math.min(760, 300 + rows * 58 + groupCount * 74));
  wrap.classList.add("expanded");
  wrap.style.height = `${targetHeight}px`;
}

function truncateCanvasText(ctx, text, maxWidth) {
  const value = String(text || "");
  if (!ctx || !maxWidth || ctx.measureText(value).width <= maxWidth) return value;
  const ellipsis = "...";
  let low = 0;
  let high = value.length;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (ctx.measureText(value.slice(0, mid) + ellipsis).width <= maxWidth) low = mid;
    else high = mid - 1;
  }
  return value.slice(0, Math.max(0, low)) + ellipsis;
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
  const mainNodePositions = nodePositions.filter((pos) => !pos.isControl);
  const childNodePositions = nodePositions.filter((pos) => pos.isControl);
  const edges = [];
  if (isRuntimeGraphViewActive()) {
    for (const edgeData of navPathEdges) {
      const from = mainNodePositions.find((pos) => pos.id === edgeData.from);
      const to = mainNodePositions.find((pos) => pos.id === edgeData.to);
      if (!from || !to) continue;
      const transitionId = edgeData.transitionId || "";
      const isCurrentTransition = transitionId && runtimePathGraphView?.currentTransitionId === transitionId;
      const isCompleted = transitionId && runtimePathGraphView?.completedTransitionIds?.has(transitionId);
      const isFailed = transitionId && runtimePathGraphView?.failedTransitionIds?.has(transitionId);
      edges.push({
        from,
        to,
        goal: edgeData.goal || edgeData.actionTemplateId || "",
        isPending: false,
        isRuntime: true,
        runtimeEdgeIndex: edges.length,
        isSelfLoop: from.id === to.id,
        isCurrentTransition,
        isCompleted,
        isFailed,
        isForbidden: edgeData.forbidden || runtimePathGraphView?.forbiddenActionIds?.has(edgeData.actionTemplateId),
      });
    }
  } else {
    for (let i = 1; i < mainNodePositions.length; i++) {
      const from = mainNodePositions[i - 1];
      const to = mainNodePositions[i];
      const edgeData = navPathEdges[i - 1] || (to.isPending && pendingTransition ? { goal: pendingTransition.goal } : null);
      edges.push({ from, to, goal: edgeData?.goal || "", isPending: to.isPending });
    }
  }
  for (const child of childNodePositions) {
    const parent = mainNodePositions.find((pos) => pos.id === child.parentId);
    if (parent) edges.push({ from: parent, to: child, goal: "", isPending: false, isChild: true });
  }

  for (const edge of edges) {
    const { from, to, isPending, isChild, isRuntime, isCurrentTransition, isCompleted, isFailed, isForbidden, isSelfLoop } = edge;
    if (isSelfLoop) {
      const loopR = 34;
      const labelYOffset = 52 + ((edge.runtimeEdgeIndex || 0) % 3) * 14;
      ctx.beginPath();
      ctx.arc(from.x - 18, from.y - 18, loopR, Math.PI * 0.15, Math.PI * 1.68);
      ctx.strokeStyle = isCompleted ? "rgba(34,197,94,0.78)" : isCurrentTransition ? "rgba(250,204,21,0.9)" : "rgba(229,231,235,0.34)";
      ctx.lineWidth = isCurrentTransition ? 2.8 : 2;
      ctx.setLineDash(isForbidden ? [4, 7] : []);
      ctx.stroke();
      ctx.setLineDash([]);
      if (edge.goal) {
        ctx.fillStyle = "rgba(203,213,225,0.72)";
        ctx.font = `9px ${PATH_CANVAS_FONT}`;
        ctx.textAlign = "center";
        ctx.fillText(`${isForbidden ? "lock " : ""}${truncateCanvasText(ctx, edge.goal, 118)}`, from.x - 46, from.y - labelYOffset);
      }
      continue;
    }
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
    if (isFailed) {
      grad.addColorStop(0, "rgba(248,113,113,0.85)");
      grad.addColorStop(1, "rgba(127,29,29,0.35)");
    } else if (isCompleted) {
      grad.addColorStop(0, "rgba(34,197,94,0.85)");
      grad.addColorStop(1, "rgba(21,128,61,0.32)");
    } else if (isCurrentTransition) {
      grad.addColorStop(0, "rgba(250,204,21,0.92)");
      grad.addColorStop(1, "rgba(161,98,7,0.36)");
    } else {
      grad.addColorStop(0, isChild ? "rgba(209,213,219,0.34)" : isPending ? "rgba(209,213,219,0.42)" : "rgba(229,231,235,0.45)");
      grad.addColorStop(1, isChild ? "rgba(209,213,219,0.08)" : isPending ? "rgba(209,213,219,0.12)" : "rgba(107,114,128,0.26)");
    }
    ctx.strokeStyle = grad;
    ctx.lineWidth = isChild ? 1 : isCurrentTransition ? 3 : isCompleted || isFailed ? 2.7 : isPending ? 1.6 : 2;
    ctx.setLineDash(isForbidden ? [4, 7] : isPending ? [7, 5] : isChild ? [2, 6] : []);
    if (isPending || isCurrentTransition) ctx.lineDashOffset = -pathAnimT * 25;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.quadraticCurveTo(cpx, cpy, to.x, to.y);
    ctx.stroke();
    ctx.setLineDash([]);

    // Particles
    if (isChild || isForbidden) continue;
    for (let p = 0; p < (isPending ? 2 : 3); p++) {
      const t = ((pathAnimT * 0.35 + p / (isPending ? 2 : 3)) % 1 + 1) % 1;
      const px = (1 - t) * (1 - t) * from.x + 2 * (1 - t) * t * cpx + t * t * to.x;
      const py = (1 - t) * (1 - t) * from.y + 2 * (1 - t) * t * cpy + t * t * to.y;
      ctx.beginPath();
      ctx.arc(px, py, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = isCompleted ? "rgba(34,197,94,0.82)" : isCurrentTransition ? "rgba(250,204,21,0.86)" : isFailed ? "rgba(248,113,113,0.82)" : isPending ? "rgba(209,213,219,0.82)" : "rgba(229,231,235,0.82)";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(px, py, 5, 0, Math.PI * 2);
      ctx.fillStyle = isCompleted ? "rgba(34,197,94,0.1)" : isCurrentTransition ? "rgba(250,204,21,0.1)" : isFailed ? "rgba(248,113,113,0.1)" : isPending ? "rgba(209,213,219,0.1)" : "rgba(229,231,235,0.08)";
      ctx.fill();
    }

    if (edge.goal) {
      ctx.fillStyle = "rgba(148,163,184,0.55)";
      ctx.font = `9px ${PATH_CANVAS_FONT}`;
      ctx.textAlign = "center";
      const labelOffset = isRuntime ? -12 - ((edge.runtimeEdgeIndex || 0) % 3) * 12 : -10;
      const label = `${isForbidden ? "lock " : ""}${truncateCanvasText(ctx, edge.goal, isRuntime ? 128 : 84)}`;
      ctx.fillText(label, mx, my + labelOffset);
    }
  }

  drawPathSectionPanels(ctx);

  // Nodes
  for (const pos of nodePositions) {
    const node = pos.isPending || pos.isControl ? null : navPathNodes.find((n) => n.id === pos.id);
    const isHovered = pathHoveredNode === pos.id;
    const baseR = pos.isControl ? 10 : PATH_NODE_R;
    const baseGlowR = pos.isControl ? 18 : PATH_GLOW_R;
    const r = isHovered ? baseR + 3 : baseR;
    const glowR = isHovered ? baseGlowR + 6 : baseGlowR;

    // Glow
    const gg = ctx.createRadialGradient(pos.x, pos.y, r * 0.5, pos.x, pos.y, glowR);
    if (pos.isControl) { gg.addColorStop(0, "rgba(229,231,235,0.36)"); gg.addColorStop(0.55, "rgba(229,231,235,0.12)"); gg.addColorStop(1, "rgba(229,231,235,0)"); }
    else if (pos.isCurrent) { gg.addColorStop(0, "rgba(255,255,255,0.34)"); gg.addColorStop(0.5, "rgba(255,255,255,0.1)"); gg.addColorStop(1, "rgba(255,255,255,0)"); }
    else if (pos.isPending) { gg.addColorStop(0, "rgba(209,213,219,0.32)"); gg.addColorStop(0.5, "rgba(209,213,219,0.1)"); gg.addColorStop(1, "rgba(209,213,219,0)"); }
    else { gg.addColorStop(0, "rgba(148,163,184,0.22)"); gg.addColorStop(1, "rgba(148,163,184,0)"); }
    ctx.beginPath(); ctx.arc(pos.x, pos.y, glowR, 0, Math.PI * 2); ctx.fillStyle = gg; ctx.fill();

    // Pulse ring
    if (pos.isCurrent) {
      const pr = r + 7 + Math.sin(pathAnimT * 3) * 3;
      ctx.beginPath(); ctx.arc(pos.x, pos.y, pr, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(255,255,255,${0.18 + Math.sin(pathAnimT*3)*0.08})`;
      ctx.lineWidth = 1.5; ctx.stroke();
    }
    if (pos.isPending) {
      ctx.beginPath(); ctx.arc(pos.x, pos.y, r + 6, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(209,213,219,0.28)"; ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]); ctx.lineDashOffset = -pathAnimT * 35; ctx.stroke(); ctx.setLineDash([]);
    }

    // Body
    const bg = ctx.createRadialGradient(pos.x - r * 0.3, pos.y - r * 0.3, r * 0.1, pos.x, pos.y, r);
    if (pos.isControl) { bg.addColorStop(0, "#e5e7eb"); bg.addColorStop(0.65, "#6b7280"); bg.addColorStop(1, "#111827"); }
    else if (pos.isCurrent) { bg.addColorStop(0, "#fef3c7"); bg.addColorStop(0.6, "#6b7280"); bg.addColorStop(1, "#111827"); }
    else if (pos.isPending) { bg.addColorStop(0, "#e5e7eb"); bg.addColorStop(0.6, "#9ca3af"); bg.addColorStop(1, "#4b5563"); }
    else { bg.addColorStop(0, "#94a3b8"); bg.addColorStop(0.6, "#475569"); bg.addColorStop(1, "#1e293b"); }
    ctx.beginPath(); ctx.arc(pos.x, pos.y, r, 0, Math.PI * 2); ctx.fillStyle = bg; ctx.fill();
    ctx.strokeStyle = pos.isControl ? "rgba(229,231,235,0.55)" : pos.isCurrent ? "rgba(255,255,255,0.55)" : pos.isPending ? "rgba(209,213,219,0.55)" : "rgba(148,163,184,0.35)";
    ctx.lineWidth = 1.3; ctx.stroke();

    // Number
    ctx.fillStyle = "#fff"; ctx.font = `bold ${pos.isControl ? 8 : pos.isPending ? 13 : 12}px ${PATH_CANVAS_FONT}`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(pos.isControl ? String(pos.index + 1) : pos.isPending ? "?" : String(pos.index + 1), pos.x, pos.y);

    // Label
    const rawLabel = pos.isControl
      ? String(pos.label || "").slice(0, 14)
      : pos.isPending ? (pendingTransition?.goal?.slice(0, 22) || "") : (node?.label || "").slice(0, 22);
    ctx.fillStyle = pos.isControl ? "rgba(229,231,235,0.86)" : pos.isCurrent ? "rgba(255,255,255,0.9)" : "rgba(203,213,225,0.75)";
    ctx.font = `${pos.isCurrent ? "bold " : ""}${pos.isControl ? 9 : 11}px ${PATH_CANVAS_FONT}`;
    const lbl = pos.isControl || pos.isRuntime ? truncateCanvasText(ctx, rawLabel, pos.labelMaxWidth || 72) : rawLabel;
    ctx.fillText(lbl, pos.x, pos.y + (pos.isControl ? 22 : PATH_LABEL_DY));

    if (!pos.isPending && node?.summary) {
      ctx.fillStyle = "rgba(148,163,184,0.5)";
      ctx.font = `10px ${PATH_CANVAS_FONT}`;
      ctx.fillText(String(node.summary).slice(0, 26), pos.x, pos.y + PATH_LABEL_DY + 14);
    }
  }

  ctx.restore();
}

function drawPathSectionPanels(ctx) {
  if (!pathSectionLayouts.length) return;
  ctx.save();
  ctx.textBaseline = "middle";
  for (const panel of pathSectionLayouts) {
    const gradient = ctx.createLinearGradient(panel.x, panel.y, panel.x + panel.w, panel.y);
    gradient.addColorStop(0, "rgba(255, 255, 255, 0.08)");
    gradient.addColorStop(1, "rgba(148, 163, 184, 0.08)");
    ctx.fillStyle = gradient;
    pathRoundRect(ctx, panel.x, panel.y, panel.w, panel.h, 14);
    ctx.fill();
    ctx.strokeStyle = "rgba(229, 231, 235, 0.16)";
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.fillStyle = "rgba(229, 231, 235, 0.88)";
    ctx.font = `bold 11px ${PATH_CANVAS_FONT}`;
    ctx.textAlign = "left";
    ctx.fillText(`${panel.label} (${panel.count})`, panel.x + 14, panel.y + 15);
  }
  ctx.restore();
}

function pathRoundRect(ctx, x, y, w, h, radius) {
  const r = Math.min(radius, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
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
  updatePathCanvasHeight();
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

function showNavNodeDetail(nodeId, focusControlIndex = null) {
  const node = navPathNodes.find((n) => n.id === nodeId);
  if (!node) return;

  const content = $("pathDetailContent");
  const meta = $("pathDetailMeta");
  if (!content) return;

  const edge = navPathEdges.find((e) => e.to === nodeId);
  const fromNode = edge ? navPathNodes.find((n) => n.id === edge.from) : null;
  const controls = Array.isArray(node.controls) ? node.controls : [];
  const focusedControl = Number.isInteger(focusControlIndex) ? controls[focusControlIndex] : null;
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

  const controlsHtml = controls.length ? renderGroupedControlDetails(controls, focusControlIndex) : `<div class="path-detail-empty">当前页面还没有收录控件。先运行整屏理解或精准定位后，这里会显示按钮、输入框、可能入口和坐标。</div>`;

  content.innerHTML = `
    <div class="path-detail-card">
      <h4>${escapeHtml(node.label)}</h4>
      ${node.summary ? `<div class="summary-block">${escapeHtml(node.summary)}</div>` : ""}
      ${focusedControl ? renderFocusedControlDetail(focusedControl, focusControlIndex) : ""}
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

function renderFocusedControlDetail(ctrl, index) {
  const point = ctrl.clickPoint ? `(${Math.round(ctrl.clickPoint.x)}, ${Math.round(ctrl.clickPoint.y)})` : "";
  const box = ctrl.bbox ? `${Math.round(ctrl.bbox.x)},${Math.round(ctrl.bbox.y)} ${Math.round(ctrl.bbox.width)}x${Math.round(ctrl.bbox.height)}` : "";
  const meta = [
    ctrl.type,
    ctrl.sectionId,
    ctrl.source,
    ctrl.candidateId,
    ctrl.confidence !== null && ctrl.confidence !== undefined ? `conf ${Number(ctrl.confidence).toFixed(2)}` : "",
    point ? `point ${point}` : "",
    box ? `box ${box}` : "",
  ].filter(Boolean).join(" | ");
  return `
    <div class="focused-control-card">
      <h5>当前子路径 #${index + 1}</h5>
      <strong>${escapeHtml(ctrl.label || "control")}</strong>
      ${meta ? `<span>${escapeHtml(meta)}</span>` : ""}
      ${ctrl.description ? `<p>${escapeHtml(ctrl.description)}</p>` : ""}
      ${ctrl.possibleNav ? `<p>${escapeHtml(ctrl.possibleNav)}</p>` : ""}
    </div>
  `;
}

function renderGroupedControlDetails(controls, focusControlIndex = null) {
  const groups = groupPathControlsBySection(controls);
  return `
    <div class="controls-list">
      <h4>按钮 / 输入 / 控件 (${controls.length})</h4>
      ${groups.map((group) => `
        <section class="control-section">
          <h5>${escapeHtml(group.label)} <span>${group.controls.length}</span></h5>
          ${group.controls.map(({ ctrl, originalIndex }) => renderControlDetailItem(ctrl, originalIndex, focusControlIndex)).join("")}
        </section>
      `).join("")}
    </div>
  `;
}

function renderControlDetailItem(ctrl, index, focusControlIndex = null) {
  const statusIcon = ctrl.status === "clicked" ? "clicked" : "open";
  const statusClass = ctrl.status === "clicked" ? "ctrl-clicked" : "ctrl-unclicked";
  const coords = ctrl.clickPoint ? `(${Math.round(ctrl.clickPoint.x)}, ${Math.round(ctrl.clickPoint.y)})` : (ctrl.bbox ? `${Math.round(ctrl.bbox.x)},${Math.round(ctrl.bbox.y)} ${Math.round(ctrl.bbox.width)}x${Math.round(ctrl.bbox.height)}` : "");
  const navInfo = ctrl.navigatedToPageId ? ` -> ${(navPathNodes.find((n) => n.id === ctrl.navigatedToPageId) || {}).label || "?"}` : "";
  const typeInfo = [ctrl.type, ctrl.sectionId, ctrl.source, ctrl.confidence !== null && ctrl.confidence !== undefined ? `conf ${Number(ctrl.confidence).toFixed(2)}` : ""].filter(Boolean).join(" | ");
  return `
    <div class="control-item ${statusClass} ${focusControlIndex === index ? "ctrl-focused" : ""}">
      <span class="ctrl-status">${statusIcon}</span>
      <div class="ctrl-info">
        <span class="ctrl-label">${escapeHtml(ctrl.label)}</span>
        ${typeInfo ? `<span class="ctrl-type">${escapeHtml(typeInfo)}</span>` : ""}
        ${ctrl.description ? `<span class="ctrl-desc">${escapeHtml(ctrl.description)}</span>` : ""}
        ${coords ? `<span class="ctrl-coords">${coords}${navInfo}</span>` : ""}
        ${ctrl.possibleNav ? `<span class="ctrl-possible">-> ${escapeHtml(ctrl.possibleNav)}</span>` : ""}
      </div>
    </div>`;
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
    const canWritePathGraph = responseAllowsPathGraphWrite(result);
    syncAppAndStateFields({
      appName: result.app_name || nestedGet(result, ["request", "app_name"]) || navPathAppName,
      stateHint: guess,
    });
    const screenInventory =
      result.screen_inventory ||
      nestedGet(result, ["screen_reading", "screen_inventory"]) ||
      nestedGet(result, ["parse_result", "screen_reading", "screen_inventory"]) ||
      nestedGet(result, ["parse_result", "screen_inventory"]);
    if (screenInventory && $("executeActionsInventoryJson")) {
      $("executeActionsInventoryJson").value = JSON.stringify(screenInventory, null, 2);
    }
    if (!canWritePathGraph && taskType === "observe_screen") return;
    if (!canWritePathGraph) {
      // Execute responses may carry screen-reading evidence; do not let it create
      // learned path nodes, but keep parsing later click/gate evidence.
    } else {

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
  }

  // Detect locate_target response and capture candidates as controls.
  applyPathMapReview(result.path_map_review);
  const learnTargets = nestedGet(result, ["learn_all_targets", "targets"]) || [];
  if (Array.isArray(learnTargets) && learnTargets.length && currentNavNodeId) {
    for (const target of learnTargets) {
      const targetLabel = target.label || target.text || target.name || "";
      const targetBbox = target.bbox || target.refined_bbox || null;
      const targetPoint = target.click_point || target.clickPoint || null;
      addControlToCurrentPage(targetLabel, targetBbox, targetPoint, target.role || target.type || "control", target.description || target.meaning || "", {
        possibleNav: controlPossibleNav(target),
        action: target.action || target.interaction || "",
        candidateId: target.candidate_id || target.id,
        source: target.source || "learn_all_targets",
        sectionId: target.section_id,
        confidence: target.confidence,
      });
    }
    renderNavPath();
  }
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
  const mode = modePayload(stage);
  const learnLocate = stage === "locate" && currentAgentMode === "learn";
  const metadata = metadataWithPrompt("locate");
  if (learnLocate) {
    metadata.learn_all_targets = true;
    metadata.learn_all_targets_reason = "Learn Mode locates every current PathGraph child control instead of a single command target.";
  }
  return {
    ...mode,
    agent_mode: learnLocate ? "learn" : mode.agent_mode,
    learn_depth: learnLocate ? "deep" : mode.learn_depth,
    goal: learnLocate ? "learn all visible controls" : goal,
    task: "click_target",
    app_name: stage === "execute" ? $("executeApp").value : $("locateApp").value,
    state_hint: stage === "execute" ? $("locateState").value : $("locateState").value,
    provider_mode: profile?.provider_mode || null,
    metadata,
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

function parseOptionalJsonField(id, fallback = {}) {
  const el = $(id);
  const raw = String(el?.value || "").trim();
  if (!raw) return fallback;
  return JSON.parse(raw);
}

function buildAvailableActionsPayload() {
  const runtimeGraphPath = String($("executeActionsGraphPath")?.value || "").trim();
  const runtimePathGraph = parseOptionalJsonField("executeActionsGraphJson", {});
  const screenInventory = parseOptionalJsonField("executeActionsInventoryJson", {});
  if (!runtimeGraphPath && !Object.keys(runtimePathGraph).length) {
    throw new Error("runtime_graph_path or runtime_path_graph is required");
  }
  const allowApplyEntry = $("executeActionsAllowApply")?.checked === true;
  const stateHint = String($("executeActionsState")?.value || "").trim();
  return {
    contract_version: "available_actions_request_v1",
    runtime_graph_path: runtimeGraphPath || null,
    runtime_path_graph: runtimePathGraph,
    capture_live: false,
    include_screen_inventory: true,
    include_scroll_containers: true,
    current_state_id: null,
    screen_inventory: screenInventory,
    task_context: {
      app_name: String($("executeActionsApp")?.value || "").trim() || null,
      state_hint: stateHint || null,
    },
    safety: {
      forbid_final_submit: true,
      allow_apply_entry: allowApplyEntry,
      allow_safe_fill: false,
    },
  };
}

function callAvailableActions() {
  let payload;
  try {
    payload = buildAvailableActionsPayload();
  } catch (error) {
    renderResponse({
      success: false,
      message: "Available actions request is invalid",
      error: { code: "invalid_available_actions_request", details: String(error.message || error) },
    }, "POST /execute/available_actions");
    setStatus("failed", "error");
    return;
  }
  api("POST", "/execute/available_actions", payload, { summary: "POST /execute/available_actions", workflowStep: "available_actions" });
}

async function callExecuteObserve() {
  const profile = syncStageProvider("observe");
  const profileId = profile?.profile_id || $("observeModelProfile")?.value || "";
  if (!(await ensureStageModelReady("observe", profileId))) return;
  const payload = {
    task: "observe_screen",
    app_name: $("executeActionsApp")?.value || $("observeApp")?.value || null,
    state_hint: $("executeActionsState")?.value || $("observeState")?.value || null,
    provider_mode: profile?.provider_mode || $("observeProvider")?.value || null,
    agent_mode: "execute",
    learn_depth: "fast",
    write_policy: { path_graph: false, element_memory: false, trace: true },
    metadata: {
      ...metadataWithPrompt("observe"),
      execute_observation: true,
      purpose: "agent_current_state_decision",
    },
    capture_live: true,
  };
  api("POST", "/vision/observe_screen", payload, { summary: "POST /vision/observe_screen execute observation", workflowStep: "observe", timeoutSeconds: requestTimeoutSeconds() });
}

function extractAvailableActions(response) {
  const actions =
    nestedGet(response, ["data", "available_actions", "actions"]) ||
    nestedGet(response, ["data", "result", "available_actions", "actions"]) ||
    [];
  return Array.isArray(actions) ? actions : [];
}

function extractPathGraphResolution(response) {
  return (
    nestedGet(response, ["data", "path_graph_resolution"]) ||
    nestedGet(response, ["data", "result", "path_graph_resolution"]) ||
    {}
  );
}

function tracePathFromResponse(response, fallbackKeys = []) {
  for (const path of [
    ["data", "trace_path"],
    ["data", "execute_step_trace_path"],
    ["data", "result", "trace_path"],
    ["data", "result", "execute_step_trace_path"],
    ...fallbackKeys,
  ]) {
    const value = nestedGet(response, path);
    if (value) return value;
  }
  return "";
}

function selectedActionSummary(action) {
  return {
    action_template_id: action?.action_template_id || action?.action_id || "",
    action_id: action?.action_id || action?.action_template_id || "",
    skill_ref: action?.skill_ref || action?.learned_skill_ref || "",
    action_kind: action?.action_kind || "",
    low_level_action_type: action?.low_level_action_type || "",
    target_container_id: action?.target_container_id || action?.scroll_container_id || "",
    from_state_id: action?.from_state_id || "",
    to_state_id: action?.to_state_id || "",
    transition_id: action?.transition_id || "",
  };
}

function actionLabel(action) {
  return action?.label || action?.action_template_id || action?.action_id || "action";
}

function forbiddenActionReason(action) {
  const actionId = String(action?.action_template_id || action?.action_id || "").toLowerCase();
  const label = String(action?.label || "").toLowerCase();
  const lowLevel = String(action?.low_level_action_type || "").toLowerCase();
  const kind = String(action?.action_kind || "").toLowerCase();
  const skill = String(action?.skill_ref || action?.learned_skill_ref || "").toLowerCase();
  const text = `${actionId} ${label} ${lowLevel} ${kind} ${skill}`;
  if (lowLevel === "input" || kind === "input" || text.includes("input") || text.includes("fill")) return "input_write_action_forbidden_in_learn_validation";
  if (/(apply|quick_apply|submit|send|complete|delete|save_changes|post_comment|create|upload|login_confirm|write|blocked|forbidden)/.test(text)) return "high_risk_or_write_action_forbidden";
  return "";
}

function isLearnValidationAllowedAction(action) {
  const reason = forbiddenActionReason(action);
  if (reason) return { allowed: false, reason };
  const lowLevel = String(action?.low_level_action_type || "").toLowerCase();
  const kind = String(action?.action_kind || "").toLowerCase();
  const actionId = String(action?.action_template_id || action?.action_id || "").toLowerCase();
  if (["scroll", "read", "navigation"].includes(lowLevel) || ["scroll", "read", "navigation"].includes(kind)) {
    return { allowed: true, reason: "read_only_safe_action" };
  }
  if (lowLevel === "click" && /(open|card|list|detail|return|select)/.test(actionId)) {
    return { allowed: true, reason: "read_only_navigation_click" };
  }
  return { allowed: false, reason: "not_in_learn_safe_validation_allowlist" };
}

function safeModePayload(mode = "read_only") {
  return {
    mode,
    forbid_final_submit: true,
    allow_apply_entry: false,
    allow_safe_fill: false,
    allow_write_actions: false,
    allow_live_input: false,
  };
}

function buildHarnessAvailableActionsPayload({ graphPath, currentStateId = "", taskContext = {}, screenInventory = {} } = {}) {
  return {
    contract_version: "available_actions_request_v1",
    runtime_graph_path: graphPath || null,
    runtime_path_graph: {},
    capture_live: false,
    include_screen_inventory: true,
    include_scroll_containers: true,
    current_state_id: currentStateId || null,
    screen_inventory: screenInventory,
    task_context: {
      app_name: taskContext.app_name || $("executeActionsApp")?.value || $("observeApp")?.value || null,
      state_hint: taskContext.state_hint || $("executeActionsState")?.value || $("observeState")?.value || null,
      goal: taskContext.goal || null,
    },
    safety: safeModePayload(taskContext.mode || "read_only"),
  };
}

function buildExecuteStepPayload({ graphPath, resolution, action, dryRun = true, dispatchLowLevel = false, safetyMode = "read_only" } = {}) {
  return {
    contract_version: "execute_step_request_v1",
    runtime_graph_path: graphPath || null,
    runtime_path_graph: {},
    path_graph_resolution: resolution || {},
    selected_action: action || {},
    safety: safeModePayload(safetyMode),
    dry_run: dryRun,
    dispatch_low_level: dispatchLowLevel,
  };
}

function replayPresetPath(preset) {
  if (preset === "wikipedia") return DEFAULT_WIKIPEDIA_GRAPH_PATH;
  if (preset === "github_issues") return DEFAULT_GITHUB_ISSUES_GRAPH_PATH;
  if (preset === "python_docs_search") return DEFAULT_PYTHON_DOCS_SEARCH_GRAPH_PATH;
  if (preset === "table_directory") return DEFAULT_TABLE_DIRECTORY_GRAPH_PATH;
  if (preset === "input_demo") return DEFAULT_INPUT_DEMO_GRAPH_PATH;
  return DEFAULT_SEEK_GRAPH_PATH;
}

function replayPresetTemplate(preset) {
  if (preset === "wikipedia") return "read_article_page";
  if (preset === "github_issues") return "read_issue_thread";
  if (preset === "python_docs_search") return "input_dry_run_demo";
  if (preset === "table_directory") return "read_n_list_details";
  if (preset === "input_demo") return "input_dry_run_demo";
  return "read_n_list_details";
}

function replayPresetStateId(preset) {
  if (preset === "wikipedia") return "wikipedia_article";
  if (preset === "github_issues") return "github_issues_list";
  if (preset === "python_docs_search") return "docs:search_page";
  if (preset === "table_directory") return "table:list_page";
  if (preset === "input_demo") return "demo_input_form";
  return "";
}

function applyReplayPreset() {
  const preset = $("replayPreset")?.value || "seek";
  if ($("replayGraphPath")) $("replayGraphPath").value = replayPresetPath(preset);
  if ($("replayTaskTemplate")) $("replayTaskTemplate").value = replayPresetTemplate(preset);
  if ($("replayStateId")) $("replayStateId").value = replayPresetStateId(preset);
}

async function readArtifactJson(path) {
  const response = await fetch(`${baseUrl()}/panel/file?path=${encodeURIComponent(path)}`);
  const text = await response.text();
  if (!response.ok) throw new Error(text || `failed to read artifact: ${path}`);
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`artifact is not valid JSON: ${path}: ${String(error.message || error)}`);
  }
}

function inferTemplateLowLevel(actionId, template = {}) {
  const declared = String(template.low_level_action_type || template.action_type || template.kind || template.operation || "").toLowerCase();
  if (["click", "scroll", "input", "observe", "verify"].includes(declared)) return declared;
  const id = String(actionId || "").toLowerCase();
  const skill = String(template.learned_skill_ref || template.skill_ref || "").toLowerCase();
  if (template.input_policy || template.input_target || /input|type|fill|search/.test(`${id} ${skill}`)) return "input";
  if (template.scroll_target || /scroll|read|load_more/.test(`${id} ${skill}`)) return "scroll";
  return "click";
}

function actionRowsFromGraph(graph) {
  const templates = Array.isArray(graph?.action_templates) ? graph.action_templates : [];
  return templates.map((template) => {
    const actionTemplateId = template.action_template_id || template.action_id || "";
    const lowLevel = inferTemplateLowLevel(actionTemplateId, template);
    const row = {
      action_template_id: actionTemplateId,
      action_id: actionTemplateId,
      action_kind: actionTemplateId.startsWith("read_") ? "read" : lowLevel,
      low_level_action_type: lowLevel,
      skill_ref: template.learned_skill_ref || template.skill_ref || "",
      scroll_container_id: template.scroll_target?.target_container_id || "",
      target_entity_id: template.target_entity || template.target_entity_id || "",
      input_target: template.input_target || {},
    };
    const reason = forbiddenActionReason(row);
    return {
      ...row,
      allowed: !reason,
      reason: reason || "safe_or_reviewable_path_graph_action",
    };
  });
}

function renderReplayGraph(graph, path) {
  const summary = $("replayGraphSummary");
  const actionTable = $("replayGraphActions");
  if (!summary || !actionTable) return;
  if (!graph) {
    summary.innerHTML = `<p class="trace-idle">${t("no_response")}</p>`;
    actionTable.innerHTML = "";
    return;
  }
  const count = (key) => Array.isArray(graph[key]) ? graph[key].length : 0;
  const safety = graph.safety_policy && typeof graph.safety_policy === "object" ? graph.safety_policy : {};
  const items = [
    ["path", path || ""],
    ["contract", graph.contract_version || ""],
    ["app_id", graph.app_id || ""],
    ["page_type", graph.page_type || ""],
    ["states", count("states")],
    ["regions", count("regions")],
    ["scroll_containers", count("scroll_containers")],
    ["entities", count("entities")],
    ["action_templates", count("action_templates")],
    ["learned_skills", count("learned_skill_refs")],
    ["visual_assets", count("visual_asset_refs")],
    ["verification_rules", count("verification_rules")],
    ["final_submit_forbidden", String(safety.forbid_final_submit ?? safety.final_submit === "forbidden" ?? true)],
    ["artifact_is_authorization", "false"],
  ];
  summary.innerHTML = `
    <h4>${t("graph_structure")}</h4>
    <div class="summary-grid summary-grid-pairs">
      ${items.map(([label, value]) => `
        <div class="summary-item${label === "path" ? " summary-item-wide" : ""}">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(String(value))}</strong>
        </div>`).join("")}
    </div>`;
  renderActionTable("replayGraphActions", actionRowsFromGraph(graph));
}

function firstDefined(...values) {
  return values.find((value) => value !== undefined && value !== null && value !== "");
}

function baselineCounterValue(baseline, key) {
  const reportSummary = baseline?.report_summary || {};
  const summary = reportSummary.summary && typeof reportSummary.summary === "object" ? reportSummary.summary : {};
  const accuracy = reportSummary.accuracy_summary && typeof reportSummary.accuracy_summary === "object" ? reportSummary.accuracy_summary : {};
  return firstDefined(summary[key], accuracy[key], 0);
}

function renderReplayRegressionReport(report, path) {
  const summary = $("replayRegressionSummary");
  const baselineTable = $("replayRegressionBaselines");
  if (!summary || !baselineTable) return;
  if (!report) {
    summary.innerHTML = `<p class="trace-idle">${t("pending")}</p>`;
    baselineTable.innerHTML = "";
    return;
  }
  const reportSummary = report.summary || {};
  const baselines = Array.isArray(report.baselines) ? report.baselines : [];
  summary.innerHTML = `
    <div class="summary-grid">
      <span>path</span><strong>${escapeHtml(path || "")}</strong>
      <span>contract</span><strong>${escapeHtml(report.contract_version || "")}</strong>
      <span>status</span><strong><span class="run-badge ${report.status === "pass" ? "ok" : "blocked"}">${escapeHtml(report.status || "unknown")}</span></strong>
      <span>baseline_count</span><strong>${escapeHtml(String(reportSummary.baseline_count ?? baselines.length))}</strong>
      <span>passed</span><strong>${escapeHtml(String(reportSummary.passed ?? 0))}</strong>
      <span>failed</span><strong>${escapeHtml(String(reportSummary.failed ?? 0))}</strong>
    </div>`;
  if (!baselines.length) {
    baselineTable.innerHTML = `<p class="trace-idle">${t("no_response")}</p>`;
    return;
  }
  baselineTable.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Baseline</th>
          <th>Status</th>
          <th>Graph</th>
          <th>Smoke report</th>
          <th>Actions</th>
          <th>Safety counters</th>
          <th>Failed checks</th>
        </tr>
      </thead>
      <tbody>
        ${baselines.map((baseline) => {
          const graph = baseline.graph_summary || {};
          const actions = Array.isArray(graph.action_templates) ? graph.action_templates : [];
          const failedChecks = (baseline.checks || [])
            .filter((item) => item?.status !== "pass")
            .map((item) => item?.check_id || "")
            .filter(Boolean);
          const counters = {
            wrong_scope_scroll_count: baselineCounterValue(baseline, "wrong_scope_scroll_count"),
            write_actions_clicked: baselineCounterValue(baseline, "write_actions_clicked"),
            submit_clicks: baselineCounterValue(baseline, "submit_clicks"),
            final_submissions: baselineCounterValue(baseline, "final_submissions"),
            high_risk_actions_executed: baselineCounterValue(baseline, "high_risk_actions_executed"),
          };
          return `
            <tr>
              <td>${escapeHtml(baseline.baseline_id || "")}</td>
              <td><span class="run-badge ${baseline.status === "pass" ? "ok" : "blocked"}">${escapeHtml(baseline.status || "unknown")}</span></td>
              <td><code>${escapeHtml(baseline.graph_path || "")}</code></td>
              <td><code>${escapeHtml(baseline.report_path || "")}</code></td>
              <td>${escapeHtml(actions.join(", "))}</td>
              <td><code>${escapeHtml(JSON.stringify(counters))}</code></td>
              <td>${escapeHtml(failedChecks.join(", ") || "none")}</td>
            </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

function renderLearnSampleReadinessGate(gate, path) {
  const summary = $("learnSampleGateSummary");
  if (!summary) return;
  if (!gate) {
    summary.innerHTML = `<p class="trace-idle">${t("pending")}</p>`;
    return;
  }
  const gateSummary = gate.summary && typeof gate.summary === "object" ? gate.summary : {};
  const policy = gate.next_sample_policy && typeof gate.next_sample_policy === "object" ? gate.next_sample_policy : {};
  const failures = Array.isArray(gate.blocking_failures) ? gate.blocking_failures : [];
  const ready = gate.ready_for_new_learn_sample === true && gate.status === "pass";
  summary.innerHTML = `
    <div class="summary-grid readiness-grid">
      <span>path</span><strong>${escapeHtml(path || "")}</strong>
      <span>contract</span><strong>${escapeHtml(gate.contract_version || "")}</strong>
      <span>${t("ready_for_new_learn_sample")}</span><strong><span class="run-badge ${ready ? "ok" : "blocked"}">${ready ? "true" : "false"}</span></strong>
      <span>status</span><strong><span class="run-badge ${gate.status === "pass" ? "ok" : "blocked"}">${escapeHtml(gate.status || "unknown")}</span></strong>
      <span>baselines</span><strong>${escapeHtml(String(gateSummary.passed_baselines ?? 0))}/${escapeHtml(String(gateSummary.baseline_count ?? 0))}</strong>
      <span>skills</span><strong>${escapeHtml(String(gateSummary.skill_count ?? ""))}</strong>
      <span>coverage</span><strong>${escapeHtml([
        gateSummary.covers_click ? "click" : "",
        gateSummary.covers_scroll ? "scroll" : "",
        gateSummary.covers_input ? "input" : "",
        gateSummary.covers_read ? "read" : "",
        gateSummary.covers_guarded_actions ? "guard" : "",
      ].filter(Boolean).join(", "))}</strong>
      <span>codex browser</span><strong>${escapeHtml(policy.codex_in_app_browser || "chatgpt_only")}</strong>
      <span>test target</span><strong>${escapeHtml(policy.test_panel_target || "external_browser_or_native_app")}</strong>
      <span>write/final</span><strong>${escapeHtml(`${gateSummary.write_actions_clicked ?? 0}/${gateSummary.final_submissions ?? 0}`)}</strong>
      <span>blocking</span><strong>${escapeHtml(failures.map((item) => item?.check_id || "").filter(Boolean).join(", ") || "none")}</strong>
    </div>`;
}

async function loadReplayRegressionReport() {
  const path = String($("replayRegressionPath")?.value || DEFAULT_ARTIFACT_REPLAY_REGRESSION_PATH).trim();
  if (!path) {
    renderResponse({ success: false, message: "regression_report_path is required" }, "Artifact replay regression");
    return null;
  }
  try {
    replayRegressionReport = await readArtifactJson(path);
    renderReplayRegressionReport(replayRegressionReport, path);
    renderResponse({
      success: true,
      message: "Regression report loaded",
      data: {
        contract_version: "artifact_replay_regression_panel_load_v1",
        path,
        status: replayRegressionReport.status,
        summary: replayRegressionReport.summary,
      },
    }, "Artifact replay regression");
    return replayRegressionReport;
  } catch (error) {
    renderReplayRegressionReport(null, path);
    renderResponse({ success: false, message: "Regression report load failed", error: String(error.message || error) }, "Artifact replay regression");
    return null;
  }
}

async function loadLearnSampleReadinessGate() {
  const path = String($("learnSampleGatePath")?.value || DEFAULT_LEARN_SAMPLE_READINESS_PATH).trim();
  if (!path) {
    renderResponse({ success: false, message: "learn_sample_gate_path is required" }, "Learn sample readiness gate");
    return null;
  }
  try {
    learnSampleReadinessGate = await readArtifactJson(path);
    renderLearnSampleReadinessGate(learnSampleReadinessGate, path);
    renderResponse({
      success: true,
      message: "Learn sample readiness gate loaded",
      data: {
        contract_version: "learn_sample_readiness_panel_load_v1",
        path,
        status: learnSampleReadinessGate.status,
        ready_for_new_learn_sample: learnSampleReadinessGate.ready_for_new_learn_sample,
        summary: learnSampleReadinessGate.summary,
      },
    }, "Learn sample readiness gate");
    return learnSampleReadinessGate;
  } catch (error) {
    renderLearnSampleReadinessGate(null, path);
    renderResponse({ success: false, message: "Learn sample readiness gate load failed", error: String(error.message || error) }, "Learn sample readiness gate");
    return null;
  }
}

async function loadReplayArtifact() {
  const path = String($("replayGraphPath")?.value || "").trim();
  if (!path) {
    renderResponse({ success: false, message: "runtime_graph_path is required" }, "Artifact replay");
    return null;
  }
  try {
    replayArtifact = await readArtifactJson(path);
    renderReplayGraph(replayArtifact, path);
    renderRuntimePathGraph(replayArtifact, {
      path,
      mode: currentAgentMode === "execute" ? "execute" : "learn/replay",
      currentStateId: String($("replayStateId")?.value || "").trim(),
    });
    renderResponse({
      success: true,
      message: "Artifact loaded",
      data: {
        contract_version: "artifact_replay_load_v1",
        path,
        graph_id: replayArtifact.graph_id,
        app_id: replayArtifact.app_id,
        action_template_count: Array.isArray(replayArtifact.action_templates) ? replayArtifact.action_templates.length : 0,
      },
    }, "Artifact replay");
    return replayArtifact;
  } catch (error) {
    renderReplayGraph(null, path);
    renderResponse({ success: false, message: "Artifact load failed", error: String(error.message || error) }, "Artifact replay");
    return null;
  }
}

function useReplayForValidation() {
  const path = String($("replayGraphPath")?.value || "").trim();
  if ($("learnValidationGraphPath")) $("learnValidationGraphPath").value = path;
  if ($("learnValidationStateId")) $("learnValidationStateId").value = String($("replayStateId")?.value || "").trim();
}

function useReplayForTaskRun() {
  const path = String($("replayGraphPath")?.value || "").trim();
  if ($("taskRunGraphPath")) $("taskRunGraphPath").value = path;
  if ($("taskRunTemplate")) $("taskRunTemplate").value = $("replayTaskTemplate")?.value || replayPresetTemplate($("replayPreset")?.value || "seek");
}

async function runReplayValidationPlan() {
  if (!replayArtifact) await loadReplayArtifact();
  useReplayForValidation();
  await generateLearnValidationPlan();
}

async function runReplayTaskStep() {
  if (!replayArtifact) await loadReplayArtifact();
  useReplayForTaskRun();
  const template = $("taskRunTemplate")?.value || "";
  const path = String($("taskRunGraphPath")?.value || "").trim();
  if (!taskRunState || taskRunState.runtime_graph_path !== path || taskRunState.task_template !== template) {
    await startTaskRun();
  }
  await executeTaskRunNextStep();
}

function createLearnValidationRun() {
  const mode = $("learnValidationSafetyMode")?.value || "read_only";
  return {
    contract_version: "path_graph_safe_action_validation_v1",
    runtime_graph_path: String($("learnValidationGraphPath")?.value || "").trim(),
    mode: "safe_action_validation",
    safety_mode: mode,
    status: "candidate",
    allowed_action_templates: [],
    forbidden_action_templates: [],
    actions: [],
    next_index: 0,
    steps: [],
    summary: {
      attempts: 0,
      passed: 0,
      failed: 0,
      write_actions_clicked: 0,
      submit_clicks: 0,
      final_submissions: 0,
    },
    decision: "candidate",
  };
}

function renderActionTable(containerId, actions = []) {
  const container = $(containerId);
  if (!container) return;
  if (!actions.length) {
    container.innerHTML = `<p class="trace-idle">${t("no_response")}</p>`;
    return;
  }
  container.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Action</th>
          <th>Kind</th>
          <th>Skill</th>
          <th>Low-level</th>
          <th>Target</th>
          <th>Status</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        ${actions.map((item) => `
          <tr>
            <td>${escapeHtml(item.action_template_id || item.action_id || "")}</td>
            <td>${escapeHtml(item.action_kind || item.low_level_action_type || "")}</td>
            <td>${escapeHtml(item.skill_ref || item.learned_skill_ref || "")}</td>
            <td>${escapeHtml(item.low_level_action_type || item.action_kind || "")}</td>
            <td>${escapeHtml(item.scroll_container_id || item.target_entity_id || item.input_target?.role || "")}</td>
            <td><span class="run-badge ${item.allowed ? "ok" : "blocked"}">${item.allowed ? t("allowed") : t("forbidden")}</span></td>
            <td>${escapeHtml(item.reason || "")}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>`;
}

function renderRunTimeline(containerId, steps = []) {
  const container = $(containerId);
  if (!container) return;
  if (!steps.length) {
    container.innerHTML = `<p class="trace-idle">${t("pending")}</p>`;
    return;
  }
  container.innerHTML = steps.map((step) => {
    const action = step.selected_action || {};
    const trace = step.execute_step_trace_path || step.available_actions_trace_path || "";
    return `
      <div class="timeline-step">
        <div class="timeline-step-head">
          <strong>#${step.step_index} ${escapeHtml(step.agent_intent || action.action_template_id || "step")}</strong>
          <span class="run-badge ${step.result?.status === "failed" ? "blocked" : "ok"}">${escapeHtml(step.result?.status || step.status || "planned")}</span>
        </div>
        <div class="timeline-grid">
          <span>skill</span><code>${escapeHtml(action.skill_ref || "")}</code>
          <span>low-level</span><code>${escapeHtml(action.low_level_action_type || "")}</code>
          <span>from -> to</span><code>${escapeHtml([action.from_state_id, action.to_state_id].filter(Boolean).join(" -> "))}</code>
          <span>container</span><code>${escapeHtml(action.target_container_id || "")}</code>
          <span>trace</span><code>${escapeHtml(trace)}</code>
        </div>
      </div>`;
  }).join("");
}

function renderRunSummary(containerId, run) {
  const container = $(containerId);
  if (!container || !run) return;
  const summary = run.summary || {};
  const actionCounts = run.steps?.reduce((acc, step) => {
    const actionType = String(step?.selected_action?.low_level_action_type || step?.selected_action?.action_kind || "unknown").toLowerCase();
    acc[actionType] = (acc[actionType] || 0) + 1;
    return acc;
  }, {}) || {};
  container.innerHTML = `
    <div class="summary-grid">
      <span>status</span><strong>${escapeHtml(run.status || run.decision || "candidate")}</strong>
      <span>steps</span><strong>${summary.steps_total ?? summary.attempts ?? run.steps?.length ?? 0}</strong>
      <span>passed</span><strong>${summary.steps_success ?? summary.passed ?? 0}</strong>
      <span>failed</span><strong>${summary.failed ?? 0}</strong>
      <span>click</span><strong>${summary.click_steps ?? actionCounts.click ?? 0}</strong>
      <span>scroll</span><strong>${summary.scroll_steps ?? actionCounts.scroll ?? 0}</strong>
      <span>input</span><strong>${summary.input_steps ?? actionCounts.input ?? 0}</strong>
      <span>items_read</span><strong>${summary.items_read ?? 0}</strong>
      <span>final_submissions</span><strong>${summary.final_submissions ?? 0}</strong>
    </div>`;
}

function updateLearnValidationView() {
  renderRunSummary("learnValidationSummary", learnValidationRun);
  renderActionTable("learnValidationActions", learnValidationRun?.actions || []);
  renderRunTimeline("learnValidationTimeline", learnValidationRun?.steps || []);
  renderRunSummary("replayValidationSummary", learnValidationRun);
  renderActionTable("replayValidationActions", learnValidationRun?.actions || []);
  renderRunTimeline("replayValidationTimeline", learnValidationRun?.steps || []);
}

async function generateLearnValidationPlan() {
  learnValidationRun = createLearnValidationRun();
  if (!learnValidationRun.runtime_graph_path) {
    renderResponse({ success: false, message: "runtime_graph_path is required" }, "PathGraph validation");
    updateLearnValidationView();
    return;
  }
  try {
    const graph = await readArtifactJson(learnValidationRun.runtime_graph_path);
    renderRuntimePathGraph(graph, {
      path: learnValidationRun.runtime_graph_path,
      mode: "learn/validation",
      currentStateId: String($("learnValidationStateId")?.value || "").trim(),
    });
  } catch (error) {
    renderResponse({ success: false, message: "Validation graph load failed", error: String(error.message || error) }, "PathGraph validation");
  }
  const response = await api(
    "POST",
    "/execute/available_actions",
    buildHarnessAvailableActionsPayload({
      graphPath: learnValidationRun.runtime_graph_path,
      currentStateId: String($("learnValidationStateId")?.value || "").trim(),
      taskContext: { mode: learnValidationRun.safety_mode },
    }),
    { summary: "POST /execute/available_actions validation plan", workflowStep: "available_actions", skipRender: false },
  );
  const actions = extractAvailableActions(response).map((action) => {
    const decision = isLearnValidationAllowedAction(action);
    return { ...selectedActionSummary(action), ...action, allowed: decision.allowed, reason: decision.reason };
  });
  learnValidationRun.actions = actions;
  learnValidationRun.allowed_action_templates = actions.filter((item) => item.allowed).map((item) => item.action_template_id);
  learnValidationRun.forbidden_action_templates = actions.filter((item) => !item.allowed).map((item) => item.action_template_id);
  learnValidationRun.available_actions_trace_path = tracePathFromResponse(response);
  updateLearnValidationView();
}

function nextLearnValidationAction() {
  const actions = (learnValidationRun?.actions || []).filter((item) => item.allowed);
  if (!actions.length) return null;
  const index = Math.min(learnValidationRun.next_index || 0, actions.length - 1);
  return actions[index] || null;
}

async function runLearnValidationStep({ previewOnly = false } = {}) {
  if (!learnValidationRun || !learnValidationRun.actions?.length) await generateLearnValidationPlan();
  const action = nextLearnValidationAction();
  if (!action) {
    renderResponse({ success: false, message: "No safe validation action available" }, "PathGraph validation");
    return;
  }
  const dispatchRequested = !previewOnly && $("learnValidationDispatch")?.checked === true;
  const response = await api(
    "POST",
    "/execute/step",
    buildExecuteStepPayload({
      graphPath: learnValidationRun.runtime_graph_path,
      resolution: { state_id: String($("learnValidationStateId")?.value || "").trim() || null },
      action,
      dryRun: !dispatchRequested,
      dispatchLowLevel: dispatchRequested,
      safetyMode: learnValidationRun.safety_mode,
    }),
    { summary: "POST /execute/step validation", workflowStep: "execute", skipRender: false },
  );
  const success = response?.success !== false;
  updateRuntimePathGraphHighlight({
    currentStateId: String($("learnValidationStateId")?.value || "").trim(),
    action,
    response,
    success,
  });
  learnValidationRun.summary.attempts += 1;
  learnValidationRun.summary[success ? "passed" : "failed"] += 1;
  if (!previewOnly && success) learnValidationRun.next_index = (learnValidationRun.next_index || 0) + 1;
  learnValidationRun.steps.push({
    contract_version: "agent_task_step_v1",
    step_index: learnValidationRun.steps.length + 1,
    phase: previewOnly ? "dry_run_preview" : "safe_action_validation",
    agent_intent: previewOnly ? "preview safe validation action" : "execute one safe validation action",
    selected_action: selectedActionSummary(action),
    available_actions_trace_path: learnValidationRun.available_actions_trace_path || "",
    execute_step_trace_path: tracePathFromResponse(response),
    result: {
      status: success ? (dispatchRequested ? "passed" : "planned") : "failed",
      dispatch_low_level: dispatchRequested,
      verification_passed: nestedGet(response, ["data", "verification", "low_level_success"]) ?? null,
    },
  });
  learnValidationRun.decision = learnValidationRun.summary.failed ? "rejected" : "candidate";
  updateLearnValidationView();
}

function resetLearnValidation() {
  learnValidationRun = createLearnValidationRun();
  updateLearnValidationView();
}

function createTaskRunState() {
  const template = $("taskRunTemplate")?.value || "read_n_list_details";
  const configuredGraphPath = String($("taskRunGraphPath")?.value || "").trim();
  const graphPath = template === "input_dry_run_demo"
    ? DEFAULT_INPUT_DEMO_GRAPH_PATH
    : (template === "read_issue_thread" ? (configuredGraphPath || DEFAULT_GITHUB_ISSUES_GRAPH_PATH) : configuredGraphPath);
  if (template === "input_dry_run_demo" && $("taskRunGraphPath")) $("taskRunGraphPath").value = graphPath;
  if (template === "read_issue_thread" && $("taskRunGraphPath") && !String($("taskRunGraphPath").value || "").trim()) $("taskRunGraphPath").value = graphPath;
  const replayStateId = String($("replayStateId")?.value || "").trim();
  const replayGraphPath = String($("replayGraphPath")?.value || "").trim();
  const currentStateId = replayStateId && replayGraphPath === graphPath
    ? replayStateId
    : template === "input_dry_run_demo"
      ? "demo_input_form"
      : (template === "read_article_page" ? "wikipedia_article" : (template === "read_issue_thread" ? "github_issues_list" : ""));
  return {
    contract_version: "agent_task_run_v1",
    goal: String($("taskRunGoal")?.value || "").trim(),
    task_template: template,
    runtime_graph_path: graphPath,
    current_state_id: currentStateId,
    mode: template === "input_dry_run_demo" ? "demo_dry_run" : "read_only",
    status: "running",
    current_item_open: false,
    current_detail_read: false,
    steps: [],
    summary: {
      items_read: 0,
      steps_total: 0,
      steps_success: 0,
      wrong_scope_scroll_count: 0,
      post_click_layout_drift_count: 0,
      click_steps: 0,
      scroll_steps: 0,
      input_steps: 0,
      write_actions_clicked: 0,
      submit_clicks: 0,
      final_submissions: 0,
    },
  };
}

function chooseTaskRunAction(actions, state) {
  if (state.task_template === "input_dry_run_demo") {
    return actions.find((action) => String(action.low_level_action_type || "").toLowerCase() === "input") || actions[0] || null;
  }
  if (state.task_template === "read_article_page") {
    return actions.find((action) => String(action.action_kind || "").toLowerCase() === "read" || String(action.low_level_action_type || "").toLowerCase() === "scroll") || actions[0] || null;
  }
  if (state.task_template === "read_issue_thread") {
    const lowered = (action) => String(action?.action_template_id || action?.action_id || "").toLowerCase();
    if (!state.current_item_open) {
      return actions.find((action) => lowered(action).includes("open_issue") || lowered(action).includes("open")) || actions[0] || null;
    }
    return actions.find((action) => lowered(action).includes("read_issue") || String(action.low_level_action_type || "").toLowerCase() === "scroll") || actions[0] || null;
  }
  const lowered = (action) => String(action?.action_template_id || action?.action_id || "").toLowerCase();
  if (!state.current_item_open) {
    return actions.find((action) => lowered(action).includes("open") || lowered(action).includes("card")) || actions[0] || null;
  }
  if (!state.current_detail_read) {
    return actions.find((action) => lowered(action).includes("read") || String(action.low_level_action_type || "").toLowerCase() === "scroll") || actions[0] || null;
  }
  return actions.find((action) => lowered(action).includes("load") || lowered(action).includes("scroll")) || actions[0] || null;
}

function taskRunActionIntent(action, state) {
  if (state.task_template === "input_dry_run_demo") return "preview input skill without typing";
  if (state.task_template === "read_article_page") return "read article page by scrolling";
  if (state.task_template === "read_issue_thread") return state.current_item_open ? "read issue thread by page scrolling" : "open issue row from list";
  const id = String(action?.action_template_id || action?.action_id || "").toLowerCase();
  if (id.includes("read")) return "read current detail";
  if (id.includes("load") || id.includes("scroll")) return "load more list items";
  return "open next list item";
}

async function startTaskRun() {
  taskRunState = createTaskRunState();
  if (taskRunState.runtime_graph_path) {
    try {
      const graph = await readArtifactJson(taskRunState.runtime_graph_path);
      renderRuntimePathGraph(graph, {
        path: taskRunState.runtime_graph_path,
        mode: "execute",
        currentStateId: taskRunState.current_state_id,
      });
    } catch (error) {
      renderResponse({ success: false, message: "Task graph load failed", error: String(error.message || error) }, "PathGraph task run");
    }
  }
  updateTaskRunView();
}

async function executeTaskRunNextStep() {
  if (!taskRunState) await startTaskRun();
  const maxSteps = Number($("taskRunMaxSteps")?.value || 20);
  const maxItems = Number($("taskRunMaxItems")?.value || 3);
  if (!taskRunState.runtime_graph_path) {
    renderResponse({ success: false, message: "runtime_graph_path is required" }, "PathGraph task run");
    return;
  }
  if (taskRunState.summary.steps_total >= maxSteps || taskRunState.summary.items_read >= maxItems) {
    taskRunState.status = "complete";
    updateTaskRunView();
    return;
  }
  const availableResponse = await api(
    "POST",
    "/execute/available_actions",
    buildHarnessAvailableActionsPayload({
      graphPath: taskRunState.runtime_graph_path,
      currentStateId: taskRunState.current_state_id,
      taskContext: { goal: taskRunState.goal, mode: taskRunState.mode },
    }),
    { summary: "POST /execute/available_actions task run", workflowStep: "available_actions", skipRender: false },
  );
  const actions = extractAvailableActions(availableResponse);
  const action = chooseTaskRunAction(actions, taskRunState);
  if (!action) {
    taskRunState.status = "blocked";
    updateTaskRunView();
    return;
  }
  const selectedAction = {
    ...action,
    input_text: taskRunState.task_template === "input_dry_run_demo" ? String($("taskRunInputText")?.value || "") : undefined,
  };
  const currentStateBeforeStep = taskRunState.current_state_id || action.from_state_id || runtimePathGraphView?.currentStateId || "";
  const isInputDemo = taskRunState.task_template === "input_dry_run_demo";
  const dispatchLowLevel = !isInputDemo;
  const stepResponse = await api(
    "POST",
    "/execute/step",
    buildExecuteStepPayload({
      graphPath: taskRunState.runtime_graph_path,
      resolution: extractPathGraphResolution(availableResponse),
      action: selectedAction,
      dryRun: isInputDemo,
      dispatchLowLevel,
      safetyMode: taskRunState.mode,
    }),
    { summary: "POST /execute/step task run", workflowStep: "execute", skipRender: false },
  );
  const success = stepResponse?.success !== false;
  const lowLevel = String(action.low_level_action_type || "").toLowerCase();
  updateRuntimePathGraphHighlight({
    currentStateId: currentStateBeforeStep,
    action,
    response: stepResponse,
    success,
  });
  if (success && action.to_state_id) taskRunState.current_state_id = action.to_state_id;
  if (success && !isInputDemo) {
    if (!taskRunState.current_item_open && lowLevel === "click") taskRunState.current_item_open = true;
    else if (taskRunState.current_item_open && !taskRunState.current_detail_read) {
      taskRunState.current_detail_read = true;
      taskRunState.summary.items_read += 1;
      taskRunState.current_item_open = false;
      taskRunState.current_detail_read = false;
    }
  }
  taskRunState.summary.steps_total += 1;
  if (success) taskRunState.summary.steps_success += 1;
  if (lowLevel === "click") taskRunState.summary.click_steps += 1;
  else if (lowLevel === "scroll") taskRunState.summary.scroll_steps += 1;
  else if (lowLevel === "input") taskRunState.summary.input_steps += 1;
  taskRunState.steps.push({
    contract_version: "agent_task_step_v1",
    step_index: taskRunState.steps.length + 1,
    phase: "execute_step",
    agent_intent: taskRunActionIntent(action, taskRunState),
    selected_action: selectedActionSummary(action),
    available_actions_trace_path: tracePathFromResponse(availableResponse),
    execute_step_trace_path: tracePathFromResponse(stepResponse),
    result: {
      status: isInputDemo ? "planned_not_executed" : (success ? "success" : "failed"),
      dispatch_low_level: dispatchLowLevel,
      type_text_called: lowLevel === "input" && dispatchLowLevel,
      verification_passed: nestedGet(stepResponse, ["data", "verification", "low_level_success"]) ?? null,
    },
  });
  if (isInputDemo || taskRunState.summary.items_read >= maxItems) taskRunState.status = "complete";
  updateTaskRunView();
}

function stopTaskRun() {
  if (taskRunState) taskRunState.status = "stopped";
  updateTaskRunView();
}

function resetTaskRun() {
  taskRunState = null;
  updateTaskRunView();
}

function updateTaskRunView() {
  renderRunSummary("taskRunSummary", taskRunState);
  renderRunTimeline("taskRunTimeline", taskRunState?.steps || []);
  renderRunSummary("replayTaskRunSummary", taskRunState);
  renderRunTimeline("replayTaskRunTimeline", taskRunState?.steps || []);
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
  on("agentModeLearnBtn", "click", () => showStage("observe"));
  on("agentModeExecuteBtn", "click", () => showStage("execute_actions"));
  on("settingsBtn", "click", () => showStage("model_test"));
  on("resetLayoutBtn", "click", resetCardLayout);
  on("healthBtn", "click", () => api("GET", "/health"));
  on("observeModelProfile", "change", () => syncStageProvider("observe"));
  on("locateModelProfile", "change", () => syncStageProvider("locate"));
  on("appId", "input", () => syncWindowAppAndState());
  on("appUrl", "input", () => syncWindowAppAndState());
  on("appCatalogSelect", "change", applySelectedCatalogApp);

  on("listAppsBtn", "click", async () => {
    const response = await api("GET", "/apps", null, { summary: "GET /apps", workflowStep: "open" });
    setAppCatalog(nestedGet(response, ["data", "catalog", "apps"]) || []);
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
      const app = nestedGet(response, ["data", "app"]);
      if (app && !appCatalog.some((item) => item.app_id === app.app_id)) {
        setAppCatalog([app, ...appCatalog]);
      }
      syncWindowAppAndState();
    });
  });
  on("listWindowsBtn", "click", () => refreshWindows(true));
  on("windowSelect", "change", applySelectedWindow);
  on("bindWindowBtn", "click", () => {
    syncWindowAppAndState(selectedWindowCandidate());
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
  on("executeObserveBtn", "click", callExecuteObserve);
  on("availableActionsBtn", "click", callAvailableActions);
  on("learnValidationPlanBtn", "click", generateLearnValidationPlan);
  on("learnValidationPreviewBtn", "click", () => runLearnValidationStep({ previewOnly: true }));
  on("learnValidationStepBtn", "click", () => runLearnValidationStep({ previewOnly: false }));
  on("learnValidationResetBtn", "click", resetLearnValidation);
  on("replayPreset", "change", applyReplayPreset);
  on("replayLoadBtn", "click", loadReplayArtifact);
  on("replayRegressionLoadBtn", "click", loadReplayRegressionReport);
  on("learnSampleGateLoadBtn", "click", loadLearnSampleReadinessGate);
  on("replayUseValidationBtn", "click", useReplayForValidation);
  on("replayUseTaskBtn", "click", useReplayForTaskRun);
  on("replayValidationPlanBtn", "click", runReplayValidationPlan);
  on("replayTaskStepBtn", "click", runReplayTaskStep);
  on("taskRunStartBtn", "click", startTaskRun);
  on("taskRunNextBtn", "click", executeTaskRunNextStep);
  on("taskRunStopBtn", "click", stopTaskRun);
  on("taskRunResetBtn", "click", resetTaskRun);
  on("taskRunTemplate", "change", () => {
    if ($("taskRunTemplate")?.value === "input_dry_run_demo" && $("taskRunGraphPath")) {
      $("taskRunGraphPath").value = DEFAULT_INPUT_DEMO_GRAPH_PATH;
    } else if ($("taskRunTemplate")?.value === "read_issue_thread" && $("taskRunGraphPath") && !String($("taskRunGraphPath").value || "").trim()) {
      $("taskRunGraphPath").value = DEFAULT_GITHUB_ISSUES_GRAPH_PATH;
    }
  });
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
  on("modelTestStage", "change", () => syncModelTestProfile());

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
    payload.approved_plan_id = null;
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
  on("traceModeFilter", "change", refreshTraceList);
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
        expandedPathNodeId = null;
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
      expandedPathNodeId = null;
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
  applySavedCardOrder();
  refreshDraggableCards();
  resetLearnValidation();
  resetTaskRun();
  applyReplayPreset();
  if ($("replayRegressionPath") && !String($("replayRegressionPath").value || "").trim()) {
    $("replayRegressionPath").value = DEFAULT_ARTIFACT_REPLAY_REGRESSION_PATH;
  }
  if ($("learnSampleGatePath") && !String($("learnSampleGatePath").value || "").trim()) {
    $("learnSampleGatePath").value = DEFAULT_LEARN_SAMPLE_READINESS_PATH;
  }
  renderReplayGraph(null, "");
  renderReplayRegressionReport(null, "");
  renderLearnSampleReadinessGate(null, "");
  if ($("taskRunTemplate")?.value === "input_dry_run_demo" && $("taskRunGraphPath")) {
    $("taskRunGraphPath").value = DEFAULT_INPUT_DEMO_GRAPH_PATH;
  } else if ($("taskRunTemplate")?.value === "read_issue_thread" && $("taskRunGraphPath") && !String($("taskRunGraphPath").value || "").trim()) {
    $("taskRunGraphPath").value = DEFAULT_GITHUB_ISSUES_GRAPH_PATH;
  }
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








