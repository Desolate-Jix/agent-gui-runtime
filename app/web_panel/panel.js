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
const DEFAULT_SEEK_INTERFACE_MAP_PATH = "artifacts/visual-match-smoke/live_seek_20260624/learned_interface_map_calibrated_real_crops.json";
const DEFAULT_ARTIFACT_REPLAY_REGRESSION_PATH = "logs/smoke/artifact_replay_regression_20260619.json";
const DEFAULT_LEARN_SAMPLE_READINESS_PATH = "logs/smoke/learn_sample_readiness_gate_20260620.json";
const DEFAULT_SEEK_APPLICATION_RECORD_PATH = "logs/smoke/seek_apply_live_92822270_20260620_b/application_fill_record.json";
const DEFAULT_SEEK_APPLICATION_AUDIT_PATH = "logs/smoke/seek_apply_live_92822270_20260620_b/final_review_audit.json";
const DEFAULT_SEEK_APPLICATION_ARTIFACT_PATH = "artifacts/seek/learned_seek_application_flow_92822270_20260620.json";
const DEFAULT_INTERFACE_CALIBRATION_REPORT_PATH = "artifacts/visual-match-smoke/live_seek_20260624/visual_asset_calibration_report.json";
let replayArtifact = null;
let replayInterfaceMap = null;
let replayInterfaceMapPath = "";
let replayInterfaceCalibrationReport = null;
let replayInterfaceCalibrationPath = "";
let selectedInterfaceMapRef = "";
let replayRegressionReport = null;
let learnSampleReadinessGate = null;
let seekApplicationEvidence = null;

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
    interface_map_path: "Interface Map 路径",
    interface_calibration_report_path: "校准报告路径",
    interface_map_save_name: "编辑后 Interface Map 文件",
    use_current_app_map: "使用当前应用地图",
    load_interface_map: "加载界面地图",
    load_interface_calibration: "加载校准报告",
    save_interface_map: "保存界面地图",
    interface_map_title: "学习界面地图",
    interface_regions: "区域",
    interface_fixed_assets: "固定按钮截图",
    interface_dynamic_areas: "变动 ROI 区",
    interface_danger_zones: "高危区",
    interface_inspector: "节点详情",
    interface_editor_hint: "可编辑区域名称/类型，以及固定按钮的动作、危险等级和所属区域；保存时会写 edit trace。",
    replay_page_summary: "页面摘要",
    replay_page_summary_hint: "这是页面级节点；点击下方区域、按钮截图或 ROI，右侧节点详情会显示可调用 workflow / skill。",
    replay_child_states: "子状态",
    replay_regions: "区域",
    replay_page_nodes: "页面节点",
    replay_possible_actions: "可能操作",
    replay_possible_actions_split: "操作已按页面节点和具体区域拆分。点击当前节点或下方区域、按钮、ROI 后，会在右侧节点详情显示可调用 workflow / skill。",
    replay_possible_actions_hint: "本页收录了基础控件；点击控件或区域后在右侧节点详情查看具体动作。",
    replay_possible_actions_empty: "暂无可点击/可输入操作。运行整屏理解后会自动补充。",
    replay_possible_entries: "可能入口 / 跳转",
    replay_possible_entries_empty: "暂无推测入口。精准定位或点击验证后会记录跳转关系。",
    replay_no_interface_map: "先加载 interface map 后，这里会显示节点字段、截图证据和编辑入口。",
    replay_inspect_hint: "点击左侧区域、按钮截图或 ROI 查看详情。",
    replay_screen_regions: "界面区域",
    replay_screen_regions_empty: "当前节点没有绑定区域",
    replay_screen_regions_empty_hint: "这个路径节点暂时没有写入 region_refs。重新导出学习产物后，这里会显示该页面的区域结构。",
    replay_main_regions: "主区域",
    replay_button_screenshots: "按钮截图",
    replay_dynamic_regions: "动态区域",
    replay_danger_regions: "高危区域",
    replay_no_image_evidence: "无图片证据",
    replay_empty_region_lane: "该区域暂无资产",
    replay_source_tight_crop: "源按钮截图",
    replay_source_context_crop: "源上下文截图",
    replay_current_match: "当前匹配截图",
    replay_current_roi: "当前 ROI",
    replay_fast_lane: "快速通道",
    replay_matched: "已匹配",
    replay_ambiguous: "有歧义",
    replay_no_controls_hint: "当前页面还没有收录控件。先运行整屏理解或精准定位后，这里会显示按钮、输入框、可能入口和坐标。",
    replay_jump_to: "跳转到",
    replay_unknown_page: "未知页面",
    replay_inspect: "查看",
    replay_no_crop: "无截图",
    replay_scroll_region: "滚动区域",
    replay_visual_evidence: "视觉证据",
    replay_evidence_not_authorization: "证据，不是授权",
    replay_evidence_not_authorization_hint: "来源 bbox / 点击点不能直接执行；只有当前截图匹配出的候选才能进入 Gate。",
    replay_region_contents: "区域内容",
    replay_region_structure_only: "这个区域当前只记录结构，没有可直接调用的按钮或 ROI。",
    replay_visual_calibration: "视觉校准",
    replay_visual_calibration_hint: "加载校准报告，对比已学习按钮截图和当前截图匹配结果。",
    replay_state_flow: "软件路径 / state flow",
    replay_states: "状态",
    replay_transitions: "跳转",
    replay_current_child_path: "当前子路径",
    replay_controls_title: "按钮 / 输入 / 控件",
    replay_workflow_skill: "Workflow / 可调用 skill",
    replay_gate_confirm: "需确认",
    replay_callable: "可调用",
    replay_region_policy: "编辑区域 / region policy",
    replay_visual_policy: "编辑节点策略 / visual asset policy",
    replay_recrop_visual_asset: "重新裁剪按钮截图 / recrop visual asset",
    replay_source_image_preview: "源截图预览",
    replay_source_image: "源截图",
    replay_recrop_button: "重新裁剪按钮截图",
    replay_no_button_crop: "结构节点 / no button crop",
    replay_no_button_crop_hint: "这个节点是滚动区域或视觉证据，不是可点击按钮截图；学习地图只保留它的结构和可调用 skill，不提供按钮裁剪。",
    learn_replay_advanced_tools: "高级诊断（可选）",
    learn_replay_advanced_tools_hint: "用于开发排查 trace、回归报告和学习样本；日常查看路径图时可以保持收起。",
    seek_application_evidence: "申请填写检查",
    seek_application_evidence_hint: "可选：检查填了什么、最终审核看到什么，以及流程是否停在最终提交前。",
    application_fill_record_path: "填写记录文件",
    final_review_audit_path: "最终审核文件",
    application_flow_artifact_path: "申请流程地图",
    load_application_evidence: "加载填写检查",
    regression_suite: "回归检查",
    regression_report_path: "回归报告文件",
    load_regression_report: "加载回归检查",
    learn_sample_gate: "新样本检查",
    learn_sample_gate_path: "样本检查文件",
    load_learn_sample_gate: "加载样本检查",
    ready_for_new_learn_sample: "可开始新学习样本",
    use_for_safe_validation: "带入安全验证",
    use_for_task_run: "带入任务运行",
    safe_validation_replay: "安全回放结果",
    task_run_replay: "任务回放结果",
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
    interface_map_path: "Interface Map path",
    interface_calibration_report_path: "Calibration report path",
    interface_map_save_name: "Edited Interface Map file",
    use_current_app_map: "Use current app map",
    load_interface_map: "Load interface map",
    load_interface_calibration: "Load calibration",
    save_interface_map: "Save interface map",
    interface_map_title: "Learned Interface Map",
    interface_regions: "Regions",
    interface_fixed_assets: "Fixed visual assets",
    interface_dynamic_areas: "Dynamic ROI areas",
    interface_danger_zones: "Danger zones",
    interface_inspector: "Node Inspector",
    interface_editor_hint: "Edit region labels/types and fixed button action, danger, and region. Saving writes an edit trace.",
    replay_page_summary: "Page Summary",
    replay_page_summary_hint: "This is a page-level node. Click a region, button crop, or ROI below to show callable workflow / skill details in the inspector.",
    replay_child_states: "Child states",
    replay_regions: "Regions",
    replay_page_nodes: "Page nodes",
    replay_possible_actions: "Possible actions",
    replay_possible_actions_split: "Actions are split by page node and concrete region. Click the current node or a region, button, or ROI below to inspect callable workflow / skill details.",
    replay_possible_actions_hint: "This page has basic controls. Click a control or region to inspect the concrete action in the node inspector.",
    replay_possible_actions_empty: "No clickable or input actions yet. Run screen understanding to populate them.",
    replay_possible_entries: "Possible entries / navigation",
    replay_possible_entries_empty: "No inferred entries yet. Precise locating or click verification will record navigation links.",
    replay_no_interface_map: "Load an interface map first. Node fields, screenshot evidence, and edit controls will appear here.",
    replay_inspect_hint: "Click a region, button crop, or ROI on the left to inspect details.",
    replay_screen_regions: "Screen regions",
    replay_screen_regions_empty: "Current node has no bound regions",
    replay_screen_regions_empty_hint: "This path node has no region_refs yet. Re-export the learned artifact to show this page's region structure.",
    replay_main_regions: "main regions",
    replay_button_screenshots: "Button screenshots",
    replay_dynamic_regions: "Dynamic regions",
    replay_danger_regions: "Danger regions",
    replay_no_image_evidence: "No image evidence",
    replay_empty_region_lane: "Empty region lane",
    replay_source_tight_crop: "Source tight crop",
    replay_source_context_crop: "Source context crop",
    replay_current_match: "Current match",
    replay_current_roi: "Current ROI",
    replay_fast_lane: "Fast lane",
    replay_matched: "Matched",
    replay_ambiguous: "Ambiguous",
    replay_no_controls_hint: "This page has no collected controls yet. Run screen understanding or precise locating to show buttons, inputs, possible entries, and coordinates here.",
    replay_jump_to: "Navigate to",
    replay_unknown_page: "unknown page",
    replay_inspect: "Inspect",
    replay_no_crop: "No crop",
    replay_scroll_region: "Scroll region",
    replay_visual_evidence: "Visual evidence",
    replay_evidence_not_authorization: "Evidence, not authorization",
    replay_evidence_not_authorization_hint: "Source bbox/click point cannot execute directly; only current-capture match candidates may enter Gate.",
    replay_region_contents: "Region contents",
    replay_region_structure_only: "This region currently records structure only; no directly callable button or ROI is available.",
    replay_visual_calibration: "Visual calibration",
    replay_visual_calibration_hint: "Load a calibration report to compare learned button crops against a current screenshot.",
    replay_state_flow: "Software path / state flow",
    replay_states: "states",
    replay_transitions: "transitions",
    replay_current_child_path: "Current child path",
    replay_controls_title: "Buttons / Inputs / Controls",
    replay_workflow_skill: "Workflow / callable skill",
    replay_gate_confirm: "Needs review",
    replay_callable: "Callable",
    replay_region_policy: "Edit region / region policy",
    replay_visual_policy: "Edit node policy / visual asset policy",
    replay_recrop_visual_asset: "Recrop button screenshot / visual asset",
    replay_source_image_preview: "Source image preview",
    replay_source_image: "Source image",
    replay_recrop_button: "Recrop button screenshot",
    replay_no_button_crop: "Structure node / no button crop",
    replay_no_button_crop_hint: "This node is a scroll region or visual evidence, not a clickable button crop. The learned map keeps its structure and callable skill only.",
    learn_replay_advanced_tools: "Advanced diagnostics",
    learn_replay_advanced_tools_hint: "Optional trace, regression, and learning-sample debugging tools. Keep this closed for daily map review.",
    seek_application_evidence: "Application fill check",
    seek_application_evidence_hint: "Optional: inspect what was filled, what the final review saw, and whether the flow stopped before final submit.",
    application_fill_record_path: "Filled form record",
    final_review_audit_path: "Final review file",
    application_flow_artifact_path: "Application flow map",
    load_application_evidence: "Load fill check",
    regression_suite: "Regression check",
    regression_report_path: "Regression report file",
    load_regression_report: "Load regression check",
    learn_sample_gate: "New sample check",
    learn_sample_gate_path: "Sample check file",
    load_learn_sample_gate: "Load sample check",
    ready_for_new_learn_sample: "Ready for new Learn sample",
    use_for_safe_validation: "Use for safe validation",
    use_for_task_run: "Use for task run",
    safe_validation_replay: "Safety replay result",
    task_run_replay: "Task replay result",
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

function panelQueryParams() {
  try {
    return new URLSearchParams(window.location.search || "");
  } catch (error) {
    return new URLSearchParams();
  }
}

function panelQueryFlag(name) {
  const params = panelQueryParams();
  if (!params.has(name)) return false;
  const value = String(params.get(name) || "").trim().toLowerCase();
  return value === "" || value === "1" || value === "true" || value === "yes";
}

function initialStageFromQuery() {
  const params = panelQueryParams();
  const requested = String(params.get("stage") || params.get("page") || "").trim();
  if (!requested) return "";
  const stageButton = Array.from(document.querySelectorAll(".stage")).find((button) => button.dataset.stage === requested);
  return stageButton ? requested : "";
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
  syncInterfaceMapPathSuggestion();
}

function syncInterfaceMapPathSuggestion() {
  const inferred = inferInterfaceMapPresetForCurrentApp();
  if (!inferred) return;
  const mapInput = $("replayInterfaceMapPath");
  const calibrationInput = $("replayInterfaceCalibrationPath");
  const replaceableMapPaths = new Set([
    "",
    "artifacts/visual-match-smoke/local_seek_buttons/learned_interface_map.json",
    "artifacts/visual-match-smoke/live_seek_20260624/learned_interface_map_calibrated.json",
    DEFAULT_SEEK_INTERFACE_MAP_PATH,
  ]);
  const replaceableCalibrationPaths = new Set([
    "",
    "artifacts/visual-match-smoke/local_seek_buttons/visual_asset_calibration_report_cli.json",
    DEFAULT_INTERFACE_CALIBRATION_REPORT_PATH,
  ]);
  if (mapInput && replaceableMapPaths.has(String(mapInput.value || "").trim())) {
    mapInput.value = inferred.mapPath;
  }
  if (calibrationInput && replaceableCalibrationPaths.has(String(calibrationInput.value || "").trim())) {
    calibrationInput.value = inferred.calibrationPath;
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
  const imageLikeKey = /(image|screenshot|capture|overlay|crop|frame).*(path|ref)$|^output_path$|^(template_path|current_roi_ref|current_match_ref)$/.test(lowerKey);
  const imageLikeValue = /\.(png|jpe?g|webp|bmp)$/i.test(lowerValue);
  return imageLikeKey && imageLikeValue;
}

function traceImageUrl(path) {
  const text = String(path || "");
  if (/^https?:\/\//i.test(text) || text.startsWith("data:")) return text;
  return `${baseUrl()}/panel/file?path=${encodeURIComponent(text)}`;
}

function panelImageHtml(path, alt, className = "") {
  const source = String(path || "");
  const safeAlt = escapeHtml(alt || "image preview");
  if (!source) return `<em>no image</em>`;
  return `
    <span class="panel-image-frame${className ? ` ${escapeHtml(className)}` : ""}">
      <img src="${escapeHtml(traceImageUrl(source))}" alt="${safeAlt}" loading="eager" decoding="async" onerror="this.closest('.panel-image-frame').classList.add('image-missing')" />
      <em>image missing</em>
    </span>`;
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
const PATH_CARD_W = 174;
const PATH_CARD_H = 68;
const PATH_CONTROL_CARD_W = 118;
const PATH_CONTROL_CARD_H = 46;

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
    const size = pathNodeCardSize(pos);
    const inCard = wx >= pos.x - size.w / 2 && wx <= pos.x + size.w / 2 && wy >= pos.y - size.h / 2 && wy <= pos.y + size.h / 2;
    if (inCard) {
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
  expandedPathNodeId = isRuntimeGraphViewActive() ? nodeId : (expandedPathNodeId === nodeId ? null : nodeId);
  currentNavNodeId = nodeId;
  if (isRuntimeGraphViewActive() && runtimePathGraphView) {
    runtimePathGraphView.currentStateId = nodeId;
    setPathGraphBadges({
      mode: `${runtimePathGraphView.mode || "replay"} graph`,
      state: nodeId,
    });
  }
  showNavNodeDetail(nodeId);
  renderNavPath();
}

function layoutPathNodes() {
  const w = pathCanvas ? pathCanvas.clientWidth : 600;
  const h = pathCanvas ? pathCanvas.clientHeight : 300;
  if (isRuntimeGraphViewActive()) return layoutRuntimePathGraphNodes(w, h);
  const cx = w / 2;
  const cy = expandedPathNodeId ? h * 0.66 : h / 2;
  const margin = 120;

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
  const marginX = 140;
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

function isSeekRuntimePathGraph(graph = {}) {
  const graphId = String(graph.graph_id || graph.app_id || "").toLowerCase();
  const stateIds = Array.isArray(graph.states) ? graph.states.map((state) => String(state?.state_id || "")) : [];
  return graphId.includes("seek") || stateIds.some((stateId) => stateId.startsWith("seek_"));
}

function seekDisplayStatesFallback() {
  return [
    {
      state_id: "seek_home_page",
      label: "SEEK 首页 / 搜索与详情页",
      page_type: "seek_search_results_with_detail",
      description: "搜索栏、筛选区、岗位卡片列表、右侧岗位详情和详情滚动区域。",
      region_refs: ["top_search_area", "results_list", "job_detail", "job_card", "detail_header", "detail_body"],
      child_state_ids: [
        "seek_search_results_empty_detail",
        "seek_search_results_with_selected_job",
        "seek_detail_scrolled",
        "seek_results_list_scrolled",
      ],
    },
    {
      state_id: "seek_application_page",
      label: "SEEK 申请页",
      page_type: "seek_station_internal_application",
      description: "站内申请表单、文档选择、雇主问题、资料更新和最终审核提交边界。",
      region_refs: [
        "application_progress",
        "application_form",
        "application_documents",
        "application_questions",
        "application_profile",
        "application_review",
      ],
      child_state_ids: ["seek_apply_entry_form", "seek_external_or_blocked"],
      safety: { final_submit: "forbidden" },
    },
  ];
}

function seekStateDisplayMapFallback() {
  return {
    seek_search_results_empty_detail: "seek_home_page",
    seek_search_results_with_selected_job: "seek_home_page",
    seek_detail_scrolled: "seek_home_page",
    seek_results_list_scrolled: "seek_home_page",
    seek_apply_entry_form: "seek_application_page",
    seek_external_or_blocked: "seek_application_page",
  };
}

function seekDisplayTransitionsFallback() {
  return [
    {
      transition_id: "seek:display_transition:browse_jobs",
      action_template_id: "browse_and_read_jobs",
      from_state_id: "seek_home_page",
      to_state_id: "seek_home_page",
      verification_refs: ["open_job_card_detail_match", "read_detail_scroll_scope"],
    },
    {
      transition_id: "seek:display_transition:open_apply_flow",
      action_template_id: "open_apply_flow",
      from_state_id: "seek_home_page",
      to_state_id: "seek_application_page",
      verification_refs: ["final_submit_forbidden"],
      default_available: false,
    },
  ];
}

function runtimeGraphDisplayStates(graph = {}) {
  const displayStates = Array.isArray(graph.display_states) ? graph.display_states.filter((item) => item && typeof item === "object") : [];
  if (displayStates.length) return displayStates;
  if (isSeekRuntimePathGraph(graph)) return seekDisplayStatesFallback();
  return Array.isArray(graph.states) ? graph.states.filter((item) => item && typeof item === "object") : [];
}

function runtimeGraphDisplayTransitions(graph = {}) {
  const displayTransitions = Array.isArray(graph.display_transitions) ? graph.display_transitions.filter((item) => item && typeof item === "object") : [];
  if (displayTransitions.length) return displayTransitions;
  if (isSeekRuntimePathGraph(graph)) return seekDisplayTransitionsFallback();
  return Array.isArray(graph.transitions) ? graph.transitions.filter((item) => item && typeof item === "object") : [];
}

function runtimeGraphDisplayStateId(graph = {}, stateId = "") {
  const raw = String(stateId || "");
  if (!raw) return raw;
  const stateDisplayMap = graph.state_display_map && typeof graph.state_display_map === "object" ? graph.state_display_map : {};
  const seekFallback = isSeekRuntimePathGraph(graph) ? seekStateDisplayMapFallback() : {};
  return String(stateDisplayMap[raw] || seekFallback[raw] || raw);
}

function renderRuntimePathGraph(graph, options = {}) {
  if (!graph || typeof graph !== "object") return;
  const states = runtimeGraphDisplayStates(graph);
  const transitions = runtimeGraphDisplayTransitions(graph);
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
    regionRefs: Array.isArray(state.region_refs) ? state.region_refs.map((item) => String(item)).filter(Boolean) : [],
    requiredRegions: Array.isArray(state.required_regions) ? state.required_regions.map((item) => String(item)).filter(Boolean) : [],
    childStateIds: Array.isArray(state.child_state_ids) ? state.child_state_ids.map((item) => String(item)).filter(Boolean) : [],
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
  const firstState = runtimeGraphDisplayStateId(graph, options.currentStateId || graph.initial_state_id || navPathEdges[0]?.from || navPathNodes[0]?.id || null);
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
    stateDisplayMap: graph.state_display_map && typeof graph.state_display_map === "object" ? graph.state_display_map : {},
  };
  updatePathAppLabel();
  setPathGraphBadges({
    mode: `${runtimePathGraphView.mode} graph`,
    state: firstState || "no state",
  });
  renderNavPath();
  if (firstState && navPathNodes.some((node) => node.id === firstState)) {
    expandedPathNodeId = firstState;
    currentNavNodeId = firstState;
    showNavNodeDetail(firstState);
  }
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
  const afterState = runtimeGraphDisplayStateId(runtimePathGraphView.graph, runtimeState.after_state_id || action?.to_state_id || edge?.to || currentStateId || runtimePathGraphView.currentStateId);
  const beforeState = runtimeGraphDisplayStateId(runtimePathGraphView.graph, runtimeState.before_state_id || currentStateId || runtimePathGraphView.currentStateId);
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

  const bg = ctx.createLinearGradient(0, 0, 0, h);
  bg.addColorStop(0, "#f7fbff");
  bg.addColorStop(1, "#eef6ff");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);

  // Dot grid (world-space)
  ctx.save();
  ctx.translate(pathPanX, pathPanY);
  ctx.scale(pathZoom, pathZoom);
  ctx.fillStyle = "rgba(37, 99, 235, 0.10)";
  const gs = 28;
  for (let gx = gs; gx < w / pathZoom + gs; gx += gs) {
    for (let gy = gs; gy < h / pathZoom + gs; gy += gs) {
      ctx.beginPath();
      ctx.arc(gx - pathPanX / pathZoom, gy - pathPanY / pathZoom, 0.8, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();

  const overlay = $("pathEmptyOverlay");
  if (!navPathNodes.length && !pendingTransition) {
    if (overlay) overlay.style.display = "flex";
    ctx.fillStyle = "#64748b";
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
      ctx.strokeStyle = isCompleted ? "rgba(22,163,74,0.68)" : isCurrentTransition ? "rgba(37,99,235,0.9)" : "rgba(148,163,184,0.48)";
      ctx.lineWidth = isCurrentTransition ? 2.8 : 2;
      ctx.setLineDash(isForbidden ? [4, 7] : []);
      ctx.stroke();
      ctx.setLineDash([]);
      if (edge.goal) {
        drawPathEdgeLabel(ctx, `${isForbidden ? "lock " : ""}${edge.goal}`, from.x - 46, from.y - labelYOffset, { forbidden: isForbidden, maxWidth: 118 });
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
      grad.addColorStop(0, "rgba(239,68,68,0.78)");
      grad.addColorStop(1, "rgba(252,165,165,0.32)");
    } else if (isCompleted) {
      grad.addColorStop(0, "rgba(22,163,74,0.72)");
      grad.addColorStop(1, "rgba(134,239,172,0.32)");
    } else if (isCurrentTransition) {
      grad.addColorStop(0, "rgba(37,99,235,0.88)");
      grad.addColorStop(1, "rgba(147,197,253,0.36)");
    } else {
      grad.addColorStop(0, isChild ? "rgba(148,163,184,0.34)" : isPending ? "rgba(59,130,246,0.34)" : "rgba(37,99,235,0.38)");
      grad.addColorStop(1, isChild ? "rgba(148,163,184,0.10)" : isPending ? "rgba(147,197,253,0.18)" : "rgba(147,197,253,0.24)");
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
      ctx.fillStyle = isCompleted ? "rgba(22,163,74,0.72)" : isCurrentTransition ? "rgba(37,99,235,0.78)" : isFailed ? "rgba(239,68,68,0.72)" : isPending ? "rgba(59,130,246,0.62)" : "rgba(37,99,235,0.52)";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(px, py, 5, 0, Math.PI * 2);
      ctx.fillStyle = isCompleted ? "rgba(22,163,74,0.08)" : isCurrentTransition ? "rgba(37,99,235,0.10)" : isFailed ? "rgba(239,68,68,0.08)" : isPending ? "rgba(59,130,246,0.08)" : "rgba(37,99,235,0.07)";
      ctx.fill();
    }

    if (edge.goal) {
      const labelOffset = isRuntime ? -12 - ((edge.runtimeEdgeIndex || 0) % 3) * 12 : -10;
      drawPathEdgeLabel(ctx, `${isForbidden ? "lock " : ""}${edge.goal}`, mx, my + labelOffset, { forbidden: isForbidden, maxWidth: isRuntime ? 128 : 96 });
    }
  }

  drawPathSectionPanels(ctx);

  // Nodes
  for (const pos of nodePositions) {
    const node = pos.isPending || pos.isControl ? null : navPathNodes.find((n) => n.id === pos.id);
    drawPathWorkflowNode(ctx, pos, node);
  }

  ctx.restore();
}

function drawPathSectionPanels(ctx) {
  if (!pathSectionLayouts.length) return;
  ctx.save();
  ctx.textBaseline = "middle";
  for (const panel of pathSectionLayouts) {
    const gradient = ctx.createLinearGradient(panel.x, panel.y, panel.x + panel.w, panel.y);
    gradient.addColorStop(0, "rgba(239, 246, 255, 0.86)");
    gradient.addColorStop(1, "rgba(255, 255, 255, 0.92)");
    ctx.fillStyle = gradient;
    pathRoundRect(ctx, panel.x, panel.y, panel.w, panel.h, 18);
    ctx.fill();
    ctx.strokeStyle = "rgba(147, 197, 253, 0.42)";
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.fillStyle = "#1e3a8a";
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

function pathNodeCardSize(pos = {}) {
  if (pos.isControl) return { w: PATH_CONTROL_CARD_W, h: PATH_CONTROL_CARD_H };
  if (pos.isRuntime) return { w: Math.max(150, Math.min(210, pos.labelMaxWidth || PATH_CARD_W)), h: PATH_CARD_H };
  return { w: PATH_CARD_W, h: PATH_CARD_H };
}

function drawPathEdgeLabel(ctx, text, x, y, options = {}) {
  const label = truncateCanvasText(ctx, text, options.maxWidth || 132);
  if (!label) return;
  ctx.save();
  ctx.font = `10px ${PATH_CANVAS_FONT}`;
  const metrics = ctx.measureText(label);
  const padX = 9;
  const w = Math.min((options.maxWidth || 132) + padX * 2, metrics.width + padX * 2);
  const h = 22;
  pathRoundRect(ctx, x - w / 2, y - h / 2, w, h, 999);
  ctx.fillStyle = options.forbidden ? "rgba(255, 247, 247, 0.96)" : "rgba(255, 255, 255, 0.94)";
  ctx.fill();
  ctx.strokeStyle = options.forbidden ? "rgba(248, 113, 113, 0.42)" : "rgba(147, 197, 253, 0.5)";
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.fillStyle = options.forbidden ? "#b42318" : "#2563eb";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, x, y + 0.5);
  ctx.restore();
}

function drawPathWorkflowNode(ctx, pos, node) {
  const { w, h } = pathNodeCardSize(pos);
  const x = pos.x - w / 2;
  const y = pos.y - h / 2;
  const isHovered = pathHoveredNode === pos.id;
  const isCurrent = pos.isCurrent;
  const isPending = pos.isPending;
  const isControl = pos.isControl;
  const radius = isControl ? 13 : 16;

  ctx.save();
  ctx.shadowColor = isCurrent ? "rgba(37, 99, 235, 0.22)" : "rgba(15, 23, 42, 0.10)";
  ctx.shadowBlur = isHovered ? 18 : 10;
  ctx.shadowOffsetY = isHovered ? 8 : 5;
  pathRoundRect(ctx, x, y, w, h, radius);
  ctx.fillStyle = isPending ? "#f8fafc" : "#ffffff";
  ctx.fill();
  ctx.shadowColor = "transparent";
  ctx.lineWidth = isCurrent ? 2 : 1;
  ctx.strokeStyle = isCurrent ? "#2563eb" : isHovered ? "#93c5fd" : "#d8e3f3";
  ctx.stroke();

  if (isPending) {
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = "#93c5fd";
    ctx.lineWidth = 1.3;
    pathRoundRect(ctx, x + 4, y + 4, w - 8, h - 8, radius - 3);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  const badgeR = isControl ? 11 : 14;
  const badgeX = x + 18;
  const badgeY = y + 19;
  ctx.beginPath();
  ctx.arc(badgeX, badgeY, badgeR, 0, Math.PI * 2);
  ctx.fillStyle = isCurrent ? "#2563eb" : isPending ? "#bfdbfe" : isControl ? "#e0f2fe" : "#eff6ff";
  ctx.fill();
  ctx.strokeStyle = isCurrent ? "#1d4ed8" : "#bfdbfe";
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.fillStyle = isCurrent ? "#ffffff" : "#1d4ed8";
  ctx.font = `700 ${isControl ? 9 : 11}px ${PATH_CANVAS_FONT}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(pos.isPending ? "?" : String(pos.index + 1), badgeX, badgeY + 0.5);

  const titleX = x + (isControl ? 36 : 42);
  const titleMax = w - (isControl ? 48 : 54);
  const rawTitle = isControl
    ? String(pos.label || "control")
    : isPending
      ? (pendingTransition?.goal || "Pending")
      : (node?.label || pos.id || "State");
  ctx.fillStyle = "#0f172a";
  ctx.font = `700 ${isControl ? 10 : 12}px ${PATH_CANVAS_FONT}`;
  ctx.textAlign = "left";
  ctx.fillText(truncateCanvasText(ctx, rawTitle, titleMax), titleX, y + (isControl ? 18 : 21));

  const summary = isControl
    ? String(pos.type || "control")
    : isPending
      ? "waiting for next state"
      : String(node?.summary || pos.stateGuess || "");
  if (summary) {
    ctx.fillStyle = "#64748b";
    ctx.font = `${isControl ? 9 : 10}px ${PATH_CANVAS_FONT}`;
    ctx.fillText(truncateCanvasText(ctx, summary, titleMax), titleX, y + (isControl ? 33 : 39));
  }

  if (isCurrent && !isControl) {
    ctx.fillStyle = "#dbeafe";
    pathRoundRect(ctx, x + w - 58, y + 10, 44, 20, 999);
    ctx.fill();
    ctx.fillStyle = "#1d4ed8";
    ctx.font = `700 9px ${PATH_CANVAS_FONT}`;
    ctx.textAlign = "center";
    ctx.fillText("current", x + w - 36, y + 20.5);
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

function showNavNodeDetail(nodeId, focusControlIndex = null, options = {}) {
  const node = navPathNodes.find((n) => n.id === nodeId);
  if (!node) return;
  currentNavNodeId = nodeId;
  if (isRuntimeGraphViewActive() && runtimePathGraphView) {
    runtimePathGraphView.currentStateId = nodeId;
    setPathGraphBadges({
      mode: `${runtimePathGraphView.mode || "replay"} graph`,
      state: nodeId,
    });
  }

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
  const runtimeOperationItems = runtimeNodeOperationItemsHtml(node);
  const operationItems = node.runtimeGraphNode ? "" : clickableControls.slice(0, 12).map((ctrl) => {
    const action = ctrl.action || (String(ctrl.type || "").includes("input") ? "输入/编辑" : "点击");
    const coords = ctrl.clickPoint ? `(${Math.round(ctrl.clickPoint.x)}, ${Math.round(ctrl.clickPoint.y)})` : "";
    return `<li><strong>${escapeHtml(action)}</strong> ${escapeHtml(ctrl.label)} ${coords ? `<span>${coords}</span>` : ""}</li>`;
  }).join("");
  const entryItems = node.runtimeGraphNode ? "" : possibleEntries.slice(0, 12).map((ctrl) => {
    const navText = ctrl.navigatedToPageId
      ? `${t("replay_jump_to")} ${(navPathNodes.find((n) => n.id === ctrl.navigatedToPageId) || {}).label || t("replay_unknown_page")}`
      : (ctrl.possibleNav || ctrl.description || ctrl.action || t("replay_possible_entries"));
    return `<li><strong>${escapeHtml(ctrl.label)}</strong><span>${escapeHtml(navText)}</span></li>`;
  }).join("");

  const controlsHtml = controls.length ? renderGroupedControlDetails(controls, focusControlIndex) : `<div class="path-detail-empty">${escapeHtml(t("replay_no_controls_hint"))}</div>`;
  if (!options.preserveInterfaceSelection) {
    const stateRef = interfaceStateRefForPathNode(node);
    if (stateRef) selectedInterfaceMapRef = stateRef;
  }
  const screenRegionsHtml = pathDetailScreenRegionsHtml(node);
  const runtimeNodeHtml = runtimeNodeDetailHtml(node);
  const interfaceInspector = pathDetailInterfaceInspectorHtml(node);

  content.innerHTML = `
    <div class="path-detail-card">
      <h4>${escapeHtml(node.label)}</h4>
      ${node.summary ? `<div class="summary-block">${escapeHtml(node.summary)}</div>` : ""}
      ${runtimeNodeHtml}
      ${focusedControl ? renderFocusedControlDetail(focusedControl, focusControlIndex) : ""}
      <div class="path-detail-sections">
        <div class="path-detail-section">
          <h5>${escapeHtml(t("replay_possible_actions"))}</h5>
          <p>${node.runtimeGraphNode ? escapeHtml(t("replay_possible_actions_split")) : ((operationItems || runtimeOperationItems) ? escapeHtml(t("replay_possible_actions_hint")) : escapeHtml(t("replay_possible_actions_empty")))}</p>
          ${runtimeOperationItems ? `<ul>${runtimeOperationItems}</ul>` : ""}
        </div>
        <div class="path-detail-section">
          <h5>${escapeHtml(t("replay_possible_entries"))}</h5>
          ${entryItems ? `<ul>${entryItems}</ul>` : `<p>${escapeHtml(t("replay_possible_entries_empty"))}</p>`}
        </div>
      </div>
      <div class="meta-row">
        ${node.stateGuess ? `<span><strong>${t("path_state_hint") || "State hint"}:</strong> ${escapeHtml(node.stateGuess)}</span>` : ""}
        ${fromNode ? `<span><strong>${t("path_from") || "From"}:</strong> ${escapeHtml(fromNode.label)}</span>` : ""}
        ${edge?.goal ? `<span><strong>${t("path_action") || "Action"}:</strong> ${escapeHtml(edge.goal)}</span>` : ""}
        ${node.imagePath ? `<span><strong>${t("path_screenshot") || "Screenshot"}:</strong> ${escapeHtml(basename(node.imagePath))}</span>` : ""}
        <span><strong>${t("path_time") || "Time"}:</strong> ${node.timestamp}</span>
      </div>
      <div class="path-detail-interface-workbench">
        <section class="path-detail-interface-regions">
          ${screenRegionsHtml}
        </section>
        <aside class="path-detail-interface-inspector" id="pathDetailInterfaceInspector">
          ${interfaceInspector}
        </aside>
      </div>
      ${controlsHtml}
    </div>
  `;
  bindPathDetailInterfaceControls(content, nodeId);

  if (meta) meta.textContent = `${controls.length} controls | ${navPathNodes.length} pages`;
}

function bindPathDetailInterfaceControls(content, nodeId) {
  content.querySelectorAll("[data-path-detail-inspect], [data-interface-inspect]").forEach((control) => {
    control.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (typeof event.stopImmediatePropagation === "function") event.stopImmediatePropagation();
      selectedInterfaceMapRef = String(control.dataset.pathDetailInspect || control.dataset.interfaceInspect || "");
      showNavNodeDetail(nodeId, null, { preserveInterfaceSelection: true });
      $("pathDetailInterfaceInspector")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  });
  bindInterfaceMapEditor(content);
}

function interfaceStateRefForPathNode(node = {}) {
  const map = replayInterfaceMap && typeof replayInterfaceMap === "object" ? replayInterfaceMap : null;
  if (!map || !Array.isArray(map.states)) return "";
  const state = interfaceStateForPathNode(node, map.states);
  const index = map.states.findIndex((item) => item === state || String(item?.state_id || "") === String(state?.state_id || ""));
  return index >= 0 ? `state:${index}` : "";
}

function pathDetailInterfaceInspectorHtml(node = {}) {
  const map = replayInterfaceMap && typeof replayInterfaceMap === "object" ? replayInterfaceMap : null;
  if (!map) {
    return `
      <h5>${escapeHtml(t("interface_inspector"))}</h5>
      <p class="trace-idle">${escapeHtml(t("replay_no_interface_map"))}</p>`;
  }
  const states = Array.isArray(map.states) ? map.states : [];
  const regions = Array.isArray(map.regions) ? map.regions : [];
  const state = interfaceStateForPathNode(node, states);
  const regionIds = interfaceRegionRefsForState(state, regions);
  const html = interfaceInspectorHtml(map, regionIds);
  if (!html || html.includes(escapeHtml(t("pending")))) {
    return `
      <h5>${escapeHtml(t("interface_inspector"))}</h5>
      <p class="trace-idle">${escapeHtml(t("replay_inspect_hint"))}</p>`;
  }
  return html;
}

function runtimeNodeOperationItemsHtml(node = {}) {
  if (!node.runtimeGraphNode || !runtimePathGraphView?.graph) return "";
  const nodeId = String(node.id || "");
  const graph = runtimePathGraphView.graph;
  const graphTransitions = Array.isArray(graph.transitions) ? graph.transitions : [];
  const templateItems = (Array.isArray(graph.action_templates) ? graph.action_templates : [])
    .filter((template) => {
      const actionId = String(template.action_template_id || template.action_id || "");
      const transition = graphTransitions.find((item) =>
        String(item.transition_id || "") === String(template.transition_ref || "") ||
        String(item.action_template_id || "") === actionId ||
        String(item.action_id || "") === actionId
      );
      if (!transition) return nodeId === runtimeGraphDisplayStateId(graph, graph.initial_state_id || nodeId);
      const from = runtimeGraphDisplayStateId(graph, transition.from_state_id || "");
      const to = runtimeGraphDisplayStateId(graph, transition.to_state_id || "");
      return from === nodeId || to === nodeId;
    })
    .map((template) => {
      const actionId = template.action_template_id || template.action_id || "operation";
      const target = template.scroll_target?.target_container_id || template.candidate_constraints?.required_container_id || template.target_entity || "";
      const skill = template.learned_skill_ref || template.skill_ref || "";
      const lowLevel = inferTemplateLowLevel(actionId, template);
      const available = template.availability_policy?.default_available === false ? t("replay_gate_confirm") : t("replay_callable");
      return `
        <li>
          <strong>${escapeHtml(actionId)}</strong>
          <span>${escapeHtml([skill, lowLevel, target, available].filter(Boolean).join(" · "))}</span>
        </li>`;
    });
  if (templateItems.length) return templateItems.join("");
  return navPathEdges
    .filter((edge) => edge.from === nodeId)
    .map((edge) => {
      const action = edge.goal || edge.actionTemplateId || edge.action || "operation";
      const skill = edge.skillRef ? `skill: ${edge.skillRef}` : "";
      const lowLevel = edge.lowLevelActionType ? `低层动作: ${edge.lowLevelActionType}` : "";
      const target = edge.actionTemplateId ? `目标: ${edge.actionTemplateId}` : "";
      const status = edge.forbidden ? t("replay_gate_confirm") : t("replay_callable");
      return `
        <li>
          <strong>${escapeHtml(action)}</strong>
          <span>${escapeHtml([skill, lowLevel, target, status].filter(Boolean).join(" · "))}</span>
        </li>`;
    })
    .join("");
}

function runtimeNodeDetailHtml(node = {}) {
  if (!node.runtimeGraphNode || !runtimePathGraphView?.graph) return "";
  const graph = runtimePathGraphView.graph;
  const nodeId = String(node.id || "");
  const childIds = Array.isArray(node.childStateIds) ? node.childStateIds : [];
  const rawStates = Array.isArray(graph.states) ? graph.states : [];
  const childStateCards = childIds
    .map((stateId) => rawStates.find((state) => String(state?.state_id || "") === String(stateId)) || { state_id: stateId })
    .map((state) => `
      <span>
        <strong>${escapeHtml(runtimeGraphStateLabel(state))}</strong>
        <small>${escapeHtml(state.page_type || state.state_id || "")}</small>
      </span>`)
    .join("");
  const regionRefs = [
    ...(Array.isArray(node.regionRefs) ? node.regionRefs : []),
    ...(Array.isArray(node.requiredRegions) ? node.requiredRegions : []),
  ].filter(Boolean);
  return `
    <section class="runtime-node-detail">
      <div>
        <h5>${escapeHtml(t("replay_page_summary"))}</h5>
        <p>${escapeHtml(t("replay_page_summary_hint"))}</p>
      </div>
      <div class="runtime-node-meta">
        <span><strong>${childIds.length}</strong><small>${escapeHtml(t("replay_child_states"))}</small></span>
        <span><strong>${regionRefs.length}</strong><small>${escapeHtml(t("replay_regions"))}</small></span>
        <span><strong>${navPathNodes.length}</strong><small>${escapeHtml(t("replay_page_nodes"))}</small></span>
      </div>
      ${childStateCards ? `<div class="runtime-child-states">${childStateCards}</div>` : ""}
    </section>`;
}

function pathDetailScreenRegionsHtml(node = {}) {
  const map = replayInterfaceMap && typeof replayInterfaceMap === "object" ? replayInterfaceMap : null;
  if (!map) return "";
  const states = Array.isArray(map.states) ? map.states : [];
  const regions = Array.isArray(map.regions) ? map.regions : [];
  if (!regions.length) return "";
  const state = interfaceStateForPathNode(node, states);
  const regionRefs = interfaceRegionRefsForState(state, regions);
  if (!regionRefs.length) {
    return `
      <section class="path-screen-regions">
        <div class="path-screen-regions-head">
          <h5>${escapeHtml(t("replay_screen_regions"))}</h5>
          <span>${escapeHtml(t("replay_screen_regions_empty"))}</span>
        </div>
        <p class="path-detail-empty">${escapeHtml(t("replay_screen_regions_empty_hint"))}</p>
      </section>`;
  }
  const regionIds = new Set(regionRefs);
  let changed = true;
  while (changed) {
    changed = false;
    regions.forEach((region) => {
      const parentId = String(region.parent_region_id || "");
      const regionId = String(region.region_id || "");
      if (parentId && regionId && regionIds.has(parentId) && !regionIds.has(regionId)) {
        regionIds.add(regionId);
        changed = true;
      }
    });
  }
  const stateRegionIds = new Set(regionRefs);
  const childRegionIds = new Set([...regionIds].filter((regionId) => !stateRegionIds.has(regionId)));
  const visibleIds = regionIds;
  const regionEntries = regions
    .map((region, index) => ({ region, index, regionId: String(region.region_id || "") }))
    .filter(({ regionId }) => visibleIds.has(regionId));
  const assets = Array.isArray(map.fixed_visual_assets) ? map.fixed_visual_assets : [];
  const dynamicAreas = Array.isArray(map.dynamic_areas) ? map.dynamic_areas : [];
  const dangerZones = Array.isArray(map.danger_zones) ? map.danger_zones : [];
  const transitions = Array.isArray(map.transitions) ? map.transitions : [];
  const regionEntriesForLayout = regionEntries.map((entry) => ({ ...entry, id: entry.regionId }));
  const knownSeekLayout = interfaceKnownSeekRegionLayoutHtml(
    regionEntriesForLayout,
    assets,
    dynamicAreas,
    dangerZones,
    states,
    transitions,
  );
  const knownApplicationLayout = knownSeekLayout ? "" : interfaceKnownSeekApplicationRegionLayoutHtml(
    regionEntriesForLayout,
    assets,
    dynamicAreas,
    dangerZones,
    states,
    transitions,
  );
  const knownLayout = knownSeekLayout || knownApplicationLayout;
  const regionCards = knownLayout || regionEntries.map((entry) => pathDetailRegionCardHtml(entry)).join("");
  return `
    <section class="path-screen-regions">
      <div class="path-screen-regions-head">
        <h5>${escapeHtml(t("replay_screen_regions"))}</h5>
        <span>${escapeHtml(state?.label || state?.state_id || node.id || "")} · ${regionRefs.length} ${escapeHtml(t("replay_main_regions"))}</span>
      </div>
      ${knownLayout ? regionCards : `<div class="path-screen-region-grid">${regionCards}</div>`}
    </section>`;
}

function interfaceStateForPathNode(node = {}, states = []) {
  const nodeId = String(node.id || "");
  const nodeLabel = String(node.label || "");
  const nodeType = String(node.stateGuess || "");
  const displayNodeId = runtimePathGraphView?.graph ? runtimeGraphDisplayStateId(runtimePathGraphView.graph, nodeId) : nodeId;
  const nodeRegionRefs = [
    ...(Array.isArray(node.regionRefs) ? node.regionRefs : []),
    ...(Array.isArray(node.requiredRegions) ? node.requiredRegions : []),
  ].map((item) => String(item)).filter(Boolean);
  const exactState = states.find((state) => String(state.state_id || "") === displayNodeId)
    || states.find((state) => String(state.state_id || "") === nodeId);
  if (exactState && Array.isArray(exactState.region_refs) && exactState.region_refs.length) return exactState;
  if (nodeRegionRefs.length) {
    return {
      state_id: displayNodeId || nodeId,
      label: nodeLabel || displayNodeId || nodeId,
      page_type: nodeType,
      region_refs: nodeRegionRefs,
    };
  }
  return exactState
    || states.find((state) => String(state.label || "") === nodeLabel)
    || states.find((state) => nodeType && String(state.page_type || "") === nodeType)
    || (states.length === 1 ? states[0] : null);
}

function interfaceRegionRefsForState(state, regions = []) {
  const explicit = [
    ...(Array.isArray(state?.region_refs) ? state.region_refs : []),
    ...(Array.isArray(state?.required_regions) ? state.required_regions : []),
  ].map(String).filter(Boolean);
  if (explicit.length) return explicit;
  if (!state && regions.length <= 6) {
    return regions
      .filter((region) => !region.parent_region_id)
      .map((region) => String(region.region_id || ""))
      .filter(Boolean);
  }
  return [];
}

function pathDetailRegionCardHtml(entry = {}) {
  const region = entry.region || {};
  const regionId = entry.regionId || String(region.region_id || "");
  const assets = Array.isArray(replayInterfaceMap?.fixed_visual_assets) ? replayInterfaceMap.fixed_visual_assets : [];
  const dynamicAreas = Array.isArray(replayInterfaceMap?.dynamic_areas) ? replayInterfaceMap.dynamic_areas : [];
  const dangerZones = Array.isArray(replayInterfaceMap?.danger_zones) ? replayInterfaceMap.danger_zones : [];
  const regionAssets = assets
    .map((asset, assetIndex) => ({ asset, assetIndex }))
    .filter(({ asset }) => interfaceAssetBelongsToRegion(asset, regionId));
  const regionDynamics = dynamicAreas
    .map((area, dynamicIndex) => ({ area, dynamicIndex }))
    .filter(({ area }) => String(area.region_id || "") === regionId);
  const regionDangerZones = dangerZones
    .map((zone, dangerIndex) => ({ zone, dangerIndex }))
    .filter(({ zone }) => {
      const asset = assets.find((item) => String(item.asset_id || "") === String(zone.asset_id || ""));
      return interfaceAssetBelongsToRegion(asset || {}, regionId);
    });
  const thumbs = regionAssets.filter(({ asset }) => interfaceAssetShouldShowThumb(asset)).slice(0, 4).map(({ asset }) => {
    const crop = interfaceAssetImageRefs(asset)[0]?.[1] || "";
    return crop
      ? `<img src="${escapeHtml(traceImageUrl(crop))}" alt="${escapeHtml(asset.label || asset.asset_id || "asset")}" loading="lazy" />`
      : `<span>${escapeHtml(asset.label || asset.asset_id || "asset")}</span>`;
  }).join("");
  const assetItems = regionAssets.map(({ asset, assetIndex }) => `
    <li data-path-detail-inspect="asset:${assetIndex}">
      <strong>${escapeHtml(asset.label || asset.asset_id || "button")}</strong>
      <span>${escapeHtml(asset.semantic_action || asset.role || "fixed visual asset")}</span>
    </li>`).join("");
  const dynamicItems = regionDynamics.map(({ area, dynamicIndex }) => `
    <li data-path-detail-inspect="dynamic:${dynamicIndex}">
      <strong>${escapeHtml(area.label || area.area_id || "dynamic ROI")}</strong>
      <span>${escapeHtml(area.semantic_role || area.role || area.area_type || "ROI")}</span>
    </li>`).join("");
  const dangerItems = regionDangerZones.map(({ zone, dangerIndex }) => `
    <li data-path-detail-inspect="danger:${dangerIndex}">
      <strong>${escapeHtml(zone.label || zone.zone_id || "danger")}</strong>
      <span>${escapeHtml(zone.semantic_action || zone.danger_level || "manual review")}</span>
    </li>`).join("");
  return `
    <details class="path-screen-region-card">
      <summary data-path-detail-inspect="region:${entry.index}">
        <div>
          <strong>${escapeHtml(region.label || regionId)}</strong>
          <span>${escapeHtml(regionId)} · ${escapeHtml(region.region_type || region.role || "region")}</span>
        </div>
      </summary>
      ${thumbs ? `<div class="path-screen-region-thumbs">${thumbs}</div>` : ""}
      <div class="path-screen-region-counts">
        <span>${regionAssets.length} button</span>
        <span>${regionDynamics.length} ROI</span>
        <span>${regionDangerZones.length} danger</span>
      </div>
      ${(assetItems || dynamicItems || dangerItems) ? `
        <div class="path-screen-region-detail">
          ${assetItems ? `<section><h6>${escapeHtml(t("replay_button_screenshots"))}</h6><ul>${assetItems}</ul></section>` : ""}
          ${dynamicItems ? `<section><h6>${escapeHtml(t("replay_dynamic_regions"))}</h6><ul>${dynamicItems}</ul></section>` : ""}
          ${dangerItems ? `<section><h6>${escapeHtml(t("replay_danger_regions"))}</h6><ul>${dangerItems}</ul></section>` : ""}
        </div>` : ""}
    </details>`;
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
      <h5>${escapeHtml(t("replay_current_child_path"))} #${index + 1}</h5>
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
      <h4>${escapeHtml(t("replay_controls_title"))} (${controls.length})</h4>
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

function replayPresetInterfaceMapPath(preset) {
  if (preset === "seek") return DEFAULT_SEEK_INTERFACE_MAP_PATH;
  return "";
}

function interfaceMapCurrentAppKey() {
  return [
    $("appId")?.value,
    $("observeApp")?.value,
    $("locateApp")?.value,
    $("executeApp")?.value,
    $("executeActionsApp")?.value,
    $("bindProcess")?.value,
    $("bindTitle")?.value,
    $("windowSelect")?.selectedOptions?.[0]?.textContent,
  ].map((value) => String(value || "").trim()).filter(Boolean).join(" | ");
}

function inferInterfaceMapPresetForCurrentApp() {
  const key = interfaceMapCurrentAppKey().toLowerCase();
  if (/\bseek\b|nz\.seek\.com|seek\.com/.test(key)) {
    return {
      preset: "seek",
      mapPath: DEFAULT_SEEK_INTERFACE_MAP_PATH,
      calibrationPath: DEFAULT_INTERFACE_CALIBRATION_REPORT_PATH,
    };
  }
  return null;
}

async function useCurrentAppInterfaceMap() {
  const inferred = inferInterfaceMapPresetForCurrentApp();
  if (!inferred) {
    renderResponse({
      success: false,
      message: "No interface map matched current app/window",
      data: {
        contract_version: "interface_map_app_match_v1",
        current_app: interfaceMapCurrentAppKey(),
      },
    }, "Interface map");
    return;
  }
  if ($("replayPreset")) $("replayPreset").value = inferred.preset;
  if ($("replayInterfaceMapPath")) $("replayInterfaceMapPath").value = inferred.mapPath;
  if ($("replayInterfaceCalibrationPath")) $("replayInterfaceCalibrationPath").value = inferred.calibrationPath;
  await loadReplayInterfaceMap();
  await loadReplayInterfaceCalibrationReport();
  renderResponse({
    success: true,
    message: "Interface map selected for current app",
    data: {
      contract_version: "interface_map_app_match_v1",
      current_app: interfaceMapCurrentAppKey(),
      preset: inferred.preset,
      interface_map_path: inferred.mapPath,
      calibration_report_path: inferred.calibrationPath,
    },
  }, "Interface map");
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
  if ($("replayInterfaceMapPath")) $("replayInterfaceMapPath").value = replayPresetInterfaceMapPath(preset);
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

function renderInterfaceMap(map, path) {
  const panel = $("replayInterfaceMapPanel");
  if (!panel) return;
  if (!map) {
    panel.innerHTML = `<p class="trace-idle">${t("no_response")}</p>`;
    return;
  }
  const regions = Array.isArray(map.regions) ? map.regions : [];
  const assets = Array.isArray(map.fixed_visual_assets) ? map.fixed_visual_assets : [];
  const dynamicAreas = Array.isArray(map.dynamic_areas) ? map.dynamic_areas : [];
  const dangerZones = Array.isArray(map.danger_zones) ? map.danger_zones : [];
  const states = Array.isArray(map.states) ? map.states : [];
  const transitions = Array.isArray(map.transitions) ? map.transitions : [];
  const calibration = replayInterfaceCalibrationReport && typeof replayInterfaceCalibrationReport === "object" ? replayInterfaceCalibrationReport : null;
  const summary = map.summary && typeof map.summary === "object" ? map.summary : {};
  const regionIds = regions.map((region) => String(region.region_id || "")).filter(Boolean);
  if (!selectedInterfaceMapRef) {
    selectedInterfaceMapRef = assets.length ? "asset:0" : (regions.length ? "region:0" : "");
  }
  const appKey = interfaceMapCurrentAppKey();
  panel.innerHTML = `
    <div class="interface-map-heading">
      <div>
        <h4>${escapeHtml(t("interface_map_title"))}</h4>
        <p class="form-help">${escapeHtml(t("interface_editor_hint"))}</p>
      </div>
      <div class="interface-safety-note">
        <strong>Current match required</strong>
        <span>source bbox is learning evidence only</span>
      </div>
    </div>
    <div class="summary-grid summary-grid-pairs">
      ${[
        ["path", path || ""],
        ["contract", map.contract_version || ""],
        ["app_id", map.app_id || ""],
        ["current_app", appKey || ""],
        ["page_type", map.page_type || ""],
        ["states", summary.state_count ?? states.length],
        ["regions", summary.region_count ?? regions.length],
        ["fixed_assets", summary.fixed_visual_asset_count ?? assets.length],
        ["dynamic_areas", summary.dynamic_area_count ?? dynamicAreas.length],
        ["danger_zones", summary.danger_zone_count ?? dangerZones.length],
      ].map(([label, value]) => `
        <div class="summary-item${label === "path" ? " summary-item-wide" : ""}">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(String(value ?? ""))}</strong>
        </div>`).join("")}
    </div>
    ${interfaceStateFlowHtml(states, transitions)}
    <div class="interface-workbench interface-workbench-summary-only">
      <section class="interface-canvas" aria-label="learned interface map canvas">
        ${interfaceCalibrationSummaryHtml(calibration)}
        ${interfaceRegionsMovedToPathDetailHtml(states, regions)}
      </section>
    </div>`;
  bindInterfaceMapEditor(panel);
}

function interfaceRegionsMovedToPathDetailHtml(states = [], regions = []) {
  return `
    <div class="interface-regions-moved-note">
      <strong>${escapeHtml(t("replay_screen_regions"))}</strong>
      <span>${escapeHtml(t("replay_page_summary_hint"))}</span>
      <div>
        <i>${escapeHtml(String(states.length))} ${escapeHtml(t("replay_page_nodes"))}</i>
        <i>${escapeHtml(String(regions.length))} ${escapeHtml(t("replay_regions"))}</i>
      </div>
    </div>`;
}

function interfaceCalibrationSummaryHtml(report) {
  if (!report) {
    return `
      <div class="interface-calibration-summary interface-calibration-empty">
        <strong>${escapeHtml(t("replay_visual_calibration"))}</strong>
        <span>${escapeHtml(t("replay_visual_calibration_hint"))}</span>
      </div>`;
  }
  const summary = report.summary && typeof report.summary === "object" ? report.summary : {};
  const status = String(summary.status || "unknown");
  return `
    <div class="interface-calibration-summary">
      <div>
        <strong>${escapeHtml(t("replay_visual_calibration"))}</strong>
        <span>${escapeHtml(replayInterfaceCalibrationPath || report.target_image_path || "")}</span>
      </div>
      <div class="interface-calibration-metrics">
        ${[
          ["status", status],
          ["matched", `${summary.matched_count ?? 0}/${summary.case_count ?? report.case_count ?? 0}`],
          ["fast lane", summary.fast_lane_success_count ?? 0],
          ["high risk", summary.high_risk_match_count ?? 0],
          ["final submit fast", summary.final_submit_fast_lane_count ?? 0],
          ["median ms", summary.median_visual_recall_ms ?? ""],
        ].map(([label, value]) => `<span class="${label === "status" ? (status === "pass" ? "ok" : "blocked") : ""}"><b>${escapeHtml(label)}</b>${escapeHtml(String(value))}</span>`).join("")}
      </div>
    </div>`;
}

function interfaceStateFlowHtml(states = [], transitions = []) {
  if (!states.length) return `<div class="interface-state-flow interface-state-flow-empty"><p class="trace-idle">${t("no_response")}</p></div>`;
  const transitionLabels = new Map();
  transitions.forEach((transition) => {
    if (!transition || typeof transition !== "object") return;
    const from = String(transition.from_state_id || "");
    const label = String(transition.action_template_id || transition.transition_id || "");
    if (!from || !label) return;
    const labels = transitionLabels.get(from) || [];
    labels.push(label);
    transitionLabels.set(from, labels);
  });
  return `
    <div class="interface-state-flow">
      <div class="interface-flow-title">
        <strong>${escapeHtml(t("replay_state_flow"))}</strong>
        <span>${states.length} ${escapeHtml(t("replay_states"))}, ${transitions.length} ${escapeHtml(t("replay_transitions"))}</span>
      </div>
      <div class="interface-state-track">
        ${states.map((state, index) => {
          const ref = `state:${index}`;
          const labels = transitionLabels.get(String(state.state_id || "")) || [];
          return `
            <button class="interface-state-node${selectedInterfaceMapRef === ref ? " interface-selected" : ""}" type="button" data-interface-inspect="${ref}">
              <strong>${escapeHtml(state.label || state.state_id || "")}</strong>
              <span>${escapeHtml(state.page_type || "")}</span>
              ${labels.length ? `<em>${escapeHtml(labels.slice(0, 2).join(" / "))}</em>` : ""}
            </button>`;
        }).join("")}
      </div>
    </div>`;
}

function interfaceRegionMapHtml(regions = [], assets = [], dynamicAreas = [], dangerZones = [], states = [], transitions = []) {
  if (!regions.length) return `<p class="trace-idle">${t("no_response")}</p>`;
  const regionEntries = regions.map((region, index) => ({ region, index, id: String(region.region_id || "") }));
  const indexById = new Map(regionEntries.map((entry) => [entry.id, entry]));
  const knownRegionIds = new Set(regionEntries.map((entry) => entry.id).filter(Boolean));
  const unmappedAssets = assets
    .map((asset, assetIndex) => ({ asset, assetIndex }))
    .filter(({ asset }) => {
      const ids = new Set([String(asset.region_id || ""), ...(Array.isArray(asset.allowed_region_ids) ? asset.allowed_region_ids.map(String) : [])].filter(Boolean));
      return !ids.size || !Array.from(ids).some((id) => knownRegionIds.has(id));
    });
  const childrenByParent = new Map();
  regionEntries.forEach((entry) => {
    const parentId = String(entry.region.parent_region_id || "");
    if (!parentId || !indexById.has(parentId)) return;
    const children = childrenByParent.get(parentId) || [];
    children.push(entry);
    childrenByParent.set(parentId, children);
  });
  const roots = regionEntries.filter((entry) => {
    const parentId = String(entry.region.parent_region_id || "");
    return !parentId || !indexById.has(parentId);
  });
  return `
    <div class="interface-region-map">
      <div class="interface-map-title">
        <strong>${escapeHtml(t("replay_screen_regions"))}</strong>
        <span>${escapeHtml(t("replay_possible_actions_split"))}</span>
      </div>
      <div class="interface-region-tree">
        ${interfaceKnownSeekRegionLayoutHtml(regionEntries, assets, dynamicAreas, dangerZones, states, transitions) || interfaceSpatialRegionMapHtml(regionEntries, assets, dynamicAreas, dangerZones) || roots.map((entry) => interfaceRegionCardHtml(entry, childrenByParent, assets, dynamicAreas, dangerZones, 0)).join("")}
      </div>
      ${unmappedAssets.length ? `
        <div class="interface-unmapped-assets">
          <h6>${escapeHtml(t("replay_screen_regions_empty"))}</h6>
          <p>${escapeHtml(t("replay_screen_regions_empty_hint"))}</p>
          <div class="interface-node-row">
            ${unmappedAssets.map(({ asset, assetIndex }) => interfaceVisualNodeHtml(asset, assetIndex)).join("")}
          </div>
        </div>` : ""}
    </div>`;
}

function interfaceKnownSeekRegionLayoutHtml(regionEntries = [], assets = [], dynamicAreas = [], dangerZones = [], states = [], transitions = []) {
  const byId = new Map(regionEntries.map((entry) => [entry.id, entry]));
  const required = ["top_search_area", "results_list", "job_detail"];
  if (!required.every((id) => byId.has(id))) return "";
  const regionPanel = (regionId, className = "", childRegionIds = []) => {
    const entry = byId.get(regionId);
    if (!entry) return "";
    const childEntries = childRegionIds.map((id) => byId.get(id)).filter(Boolean);
    return interfaceLayoutRegionPanelHtml(entry, assets, dynamicAreas, dangerZones, className, childEntries, states, transitions);
  };
  return `
    <div class="interface-known-layout interface-known-layout-seek">
      <div class="interface-known-region top">${regionPanel("top_search_area")}</div>
      <div class="interface-known-region left">
        ${regionPanel("results_list", "", ["job_card"])}
      </div>
      <div class="interface-known-region right">
        ${regionPanel("job_detail", "", ["detail_header", "detail_body"])}
      </div>
    </div>`;
}

function interfaceKnownSeekApplicationRegionLayoutHtml(regionEntries = [], assets = [], dynamicAreas = [], dangerZones = [], states = [], transitions = []) {
  const byId = new Map(regionEntries.map((entry) => [entry.id, entry]));
  if (!byId.has("application_form")) return "";
  const nestedEntry = (regionId, childRegionIds = []) => {
    const entry = byId.get(regionId);
    if (!entry) return null;
    return {
      ...entry,
      childEntries: childRegionIds.map((id) => nestedEntry(id)).filter(Boolean),
    };
  };
  const regionPanel = (regionId, className = "", childRegionIds = []) => {
    const entry = byId.get(regionId);
    if (!entry) return "";
    const childEntries = childRegionIds.map((id) => {
      if (id === "application_review_step") return nestedEntry(id, ["application_review"]);
      return nestedEntry(id);
    }).filter(Boolean);
    return interfaceLayoutRegionPanelHtml(entry, assets, dynamicAreas, dangerZones, className, childEntries, states, transitions);
  };
  return `
    <div class="interface-known-layout interface-known-layout-seek-application">
      <div class="interface-known-region app-shell">
        ${regionPanel("application_form", "application-shell", [
          "application_progress",
          "application_documents",
          "application_questions",
          "application_profile",
          "application_review_step",
        ])}
      </div>
    </div>`;
}

function interfaceWorkflowActionsForRegion(regionId = "") {
  const graph = runtimePathGraphView?.graph || replayArtifact || {};
  const templates = Array.isArray(graph.action_templates) ? graph.action_templates : [];
  const normalizedRegion = String(regionId || "");
  const graphActions = templates
    .filter((template) => interfaceActionTemplateTargetsRegion(template, normalizedRegion))
    .map((template) => {
      const actionId = String(template.action_template_id || template.action_id || "action");
      const lowLevel = inferTemplateLowLevel(actionId, template);
      const skill = String(template.learned_skill_ref || template.skill_ref || "");
      const target = String(template.scroll_target?.target_container_id || template.candidate_constraints?.required_container_id || template.target_entity || "");
      const gated = template.availability_policy?.default_available === false || actionId.includes("apply");
      return { actionId, lowLevel, skill, target, gated };
    });
  const fallbackActions = interfaceKnownRegionWorkflowActions(normalizedRegion);
  fallbackActions.forEach((action) => {
    if (!graphActions.some((existing) => existing.actionId === action.actionId && existing.target === action.target)) {
      graphActions.push(action);
    }
  });
  return graphActions;
}

function interfaceActionTemplateTargetsRegion(template = {}, regionId = "") {
  const actionId = String(template.action_template_id || template.action_id || "").toLowerCase();
  const targetEntity = String(template.target_entity || "").toLowerCase();
  const targetPane = String(template.scroll_target?.target_pane || "").toLowerCase();
  const targetContainer = String(template.scroll_target?.target_container_id || template.candidate_constraints?.required_container_id || "").toLowerCase();
  const id = String(regionId || "").toLowerCase();
  if (!id) return false;
  if (id === "job_card") return actionId.includes("open_job_card") || targetEntity === "job_card";
  if (id === "results_list") return targetContainer.includes("results_list") || targetPane === "results_list";
  if (id === "job_detail") return targetContainer.includes("job_detail") || targetPane === "job_detail";
  if (id === "detail_header") return targetEntity.includes("apply") || actionId.includes("apply");
  if (id === "detail_body") return actionId.includes("read_detail") || targetEntity.includes("detail");
  return targetEntity === id || targetPane === id || targetContainer.endsWith(`:${id}`);
}

function interfaceKnownRegionWorkflowActions(regionId = "") {
  const id = String(regionId || "").toLowerCase();
  const known = {
    top_search_area: [
      { actionId: "search_keyword_submit", lowLevel: "input", skill: "skill.search_by_keyboard_submit", target: "seek:top_search_area", gated: false },
    ],
    application_progress: [
      { actionId: "detect_application_step", lowLevel: "read", skill: "skill.read_application_progress", target: "seek:application_progress", gated: false },
    ],
    application_documents: [
      { actionId: "keep_default_resume", lowLevel: "review", skill: "skill.keep_existing_document", target: "seek:application_documents", gated: false },
      { actionId: "continue_next_step", lowLevel: "click", skill: "skill.continue_application_flow", target: "seek:application_documents", gated: true },
    ],
      application_questions: [
        { actionId: "fill_employer_questions", lowLevel: "input", skill: "skill.answer_employer_questions_from_profile", target: "seek:application_questions", gated: true },
        { actionId: "continue_next_step", lowLevel: "click", skill: "skill.continue_application_flow", target: "seek:application_questions", gated: true },
      ],
      application_profile: [
        { actionId: "continue_without_profile_mutation", lowLevel: "click", skill: "skill.skip_profile_mutation", target: "seek:application_profile", gated: true },
      ],
      application_review_step: [
        { actionId: "extract_final_review", lowLevel: "read", skill: "skill.review_before_submit_reconciliation", target: "seek:application_review", gated: true },
      ],
      application_review: [
        { actionId: "extract_final_review", lowLevel: "read", skill: "skill.review_before_submit_reconciliation", target: "seek:application_review", gated: true },
        { actionId: "final_submit", lowLevel: "blocked", skill: "skill.block_final_submit", target: "seek:application_review", gated: true },
      ],
    application_form: [
      { actionId: "read_application_flow", lowLevel: "read", skill: "skill.read_current_application_step", target: "seek:application_form", gated: false },
    ],
  };
  return known[id] ? known[id].map((item) => ({ ...item })) : [];
}

function interfaceRegionSummaryText(region = {}, assets = [], dynamicAreas = [], dangerZones = []) {
  const id = String(region.region_id || "").toLowerCase();
  const summariesByLanguage = {
    "zh-CN": {
      top_search_area: "搜索关键词、地点和筛选条件所在区域，通常用于快速进入岗位结果页。",
      results_list: "左侧滚动岗位列表。这里会不断出现岗位卡片，适合使用 open_job_card 打开卡片，或用 load_more_results 加载更多结果。",
      job_card: "单个岗位卡片模板区域。卡片内容会变化，但标题、公司、地点和摘要通常在这里出现，点击后会更新右侧详情。",
      job_detail: "右侧岗位详情容器。这里包含岗位标题、申请入口、详情正文和独立滚动条。",
      detail_header: "岗位标题、公司、保存按钮和 Apply / Quick Apply 入口所在区域。Apply 只是进入申请流程，不等于最终提交。",
      detail_body: "岗位正文阅读区域。这里适合批量截图/OCR 读取详情，直到到达正文底部。",
      application_form: "SEEK 站内申请流程容器，包含步骤进度、文档、问题、Profile 和最终审核页。",
      application_progress: "申请步骤进度条，用来判断当前处于 Choose documents、Questions、Profile 还是 Review。",
      application_documents: "选择简历和求职信的步骤。默认简历通常保留，求职信可按岗位改写。",
      application_questions: "雇主问题填写区域。这里需要从个人 profile 和岗位详情生成回答，并在继续前复核。",
      application_profile: "SEEK Profile 更新步骤。默认策略是避免修改长期 profile，只继续到下一步。",
      application_review_step: "Review and submit 步骤。这里读取申请摘要并准备最终审核，但不授权提交。",
      application_review: "最终 Review and submit 边界。这里可以读取最终审核信息，但 Submit application 必须强制阻断。",
    },
    "en-US": {
      top_search_area: "Search keyword, location, and filter controls. This area usually drives the transition into job results.",
      results_list: "Left scrolling job-results list. Job cards appear here; use open_job_card to open a card or load_more_results to reveal more results.",
      job_card: "Repeatable job-card template. The content changes, but title, company, location, and summary usually appear here and update the detail pane when clicked.",
      job_detail: "Right job-detail container. It includes job title, application entry, body text, and its own scrollbar.",
      detail_header: "Header area for job title, company, save control, and Apply / Quick Apply entry. Apply opens a flow; it is not final submit.",
      detail_body: "Job-description reading area. Batch screenshots/OCR should read this region until the body reaches the bottom.",
      application_form: "SEEK internal application-flow container with progress, documents, questions, profile, and final review steps.",
      application_progress: "Application progress tracker used to decide whether the flow is on documents, questions, profile, or review.",
      application_documents: "Resume and cover-letter step. The default resume is usually kept; the cover letter can be rewritten for the job.",
      application_questions: "Employer question area. Answers should come from the personal profile plus job detail, then be reviewed before continuing.",
      application_profile: "SEEK Profile update step. The default policy avoids mutating the long-lived profile and continues to the next step.",
      application_review_step: "Review and submit step. Read the application summary and prepare final review without authorizing submission.",
      application_review: "Final Review and submit boundary. The agent may read the final review, but Submit application remains hard-blocked.",
    },
  };
  const summaries = summariesByLanguage[currentLanguage] || summariesByLanguage["en-US"];
  if (summaries[id]) return summaries[id];
  const pieces = [];
  if (assets.length) pieces.push(`${assets.length} ${t("replay_button_screenshots")}`);
  if (dynamicAreas.length) pieces.push(`${dynamicAreas.length} ${t("replay_dynamic_regions")}`);
  if (dangerZones.length) pieces.push(`${dangerZones.length} ${t("replay_danger_regions")}`);
  if (pieces.length) return currentLanguage === "zh-CN" ? `该区域包含 ${pieces.join("、")}。` : `This region contains ${pieces.join(", ")}.`;
  return String(region.description || region.summary || "");
}

function interfaceLayoutRegionPanelHtml(entry, assets = [], dynamicAreas = [], dangerZones = [], className = "", childEntries = [], states = [], transitions = []) {
  const region = entry.region || {};
  const regionId = entry.id || String(region.region_id || "");
  const ref = `region:${entry.index}`;
  const regionAssets = assets
    .map((asset, assetIndex) => ({ asset, assetIndex }))
    .filter(({ asset }) => interfaceAssetBelongsToRegion(asset, regionId));
  const regionDynamics = dynamicAreas
    .map((area, dynamicIndex) => ({ area, dynamicIndex }))
    .filter(({ area }) => String(area.region_id || "") === regionId);
  const regionDangerZones = dangerZones
    .map((zone, dangerIndex) => ({ zone, dangerIndex }))
    .filter(({ zone }) => {
      const asset = assets.find((item) => String(item.asset_id || "") === String(zone.asset_id || ""));
      return interfaceAssetBelongsToRegion(asset || {}, regionId);
    });
  const summary = interfaceRegionSummaryText(region, regionAssets, regionDynamics, regionDangerZones);
  return `
    <article class="interface-layout-region ${escapeHtml(className)}${selectedInterfaceMapRef === ref ? " interface-selected" : ""}" data-region-id="${escapeHtml(regionId)}">
      <header>
        <button type="button" data-interface-inspect="${ref}">
          <strong>${escapeHtml(region.label || regionId)}</strong>
          <span>${escapeHtml(regionId)} · ${escapeHtml(region.region_type || region.role || "region")}</span>
        </button>
      </header>
      ${summary ? `<p class="interface-region-summary">${escapeHtml(summary)}</p>` : ""}
      ${childEntries.length ? `
        <div class="interface-layout-children">
          ${childEntries.map((childEntry) => interfaceLayoutChildRegionHtml(childEntry, assets, dynamicAreas, dangerZones, states, transitions, childEntry.childEntries || [])).join("")}
        </div>` : ""}
      <div class="interface-layout-assets">
        ${interfaceRegionContentNodesHtml(regionAssets, regionDynamics, regionDangerZones)}
      </div>
    </article>`;
}

function interfaceLayoutChildRegionHtml(entry, assets = [], dynamicAreas = [], dangerZones = [], states = [], transitions = [], childEntries = []) {
  const region = entry.region || {};
  const regionId = entry.id || String(region.region_id || "");
  const ref = `region:${entry.index}`;
  const regionAssets = assets
    .map((asset, assetIndex) => ({ asset, assetIndex }))
    .filter(({ asset }) => interfaceAssetBelongsToRegion(asset, regionId));
  const regionDynamics = dynamicAreas
    .map((area, dynamicIndex) => ({ area, dynamicIndex }))
    .filter(({ area }) => String(area.region_id || "") === regionId);
  const regionDangerZones = dangerZones
    .map((zone, dangerIndex) => ({ zone, dangerIndex }))
    .filter(({ zone }) => {
      const asset = assets.find((item) => String(item.asset_id || "") === String(zone.asset_id || ""));
      return interfaceAssetBelongsToRegion(asset || {}, regionId);
    });
  const summary = interfaceRegionSummaryText(region, regionAssets, regionDynamics, regionDangerZones);
  const content = `
    ${summary ? `<p class="interface-region-summary">${escapeHtml(summary)}</p>` : ""}
    ${childEntries.length ? `
      <div class="interface-layout-children">
        ${childEntries.map((childEntry) => interfaceLayoutChildRegionHtml(childEntry, assets, dynamicAreas, dangerZones, states, transitions, childEntry.childEntries || [])).join("")}
      </div>` : ""}
    <div class="interface-layout-assets">
      ${interfaceRegionContentNodesHtml(regionAssets, regionDynamics, regionDangerZones)}
      ${!regionAssets.length && !regionDynamics.length && !regionDangerZones.length ? `<p class="trace-idle">empty child region</p>` : ""}
    </div>`;
  return `
    <details class="interface-child-region${selectedInterfaceMapRef === ref ? " interface-selected" : ""}" data-region-id="${escapeHtml(regionId)}"${childEntries.length ? " open" : ""}>
      <summary>
        <button type="button" data-interface-inspect="${ref}">
          <strong>${escapeHtml(region.label || regionId)}</strong>
          <span>${escapeHtml(regionId)} · ${escapeHtml(region.region_type || region.role || "region")}</span>
        </button>
      </summary>
      ${content}
    </details>`;
}

function interfaceRegionContentNodesHtml(regionAssets = [], regionDynamics = [], regionDangerZones = []) {
  const visualAssets = [...regionAssets].sort(({ asset: left }, { asset: right }) => {
    const leftHasThumb = interfaceAssetShouldShowThumb(left);
    const rightHasThumb = interfaceAssetShouldShowThumb(right);
    if (leftHasThumb !== rightHasThumb) return leftHasThumb ? -1 : 1;
    return String(left?.label || left?.asset_id || "").localeCompare(String(right?.label || right?.asset_id || ""));
  });
  return `
    ${regionDynamics.map(({ area, dynamicIndex }) => interfaceDynamicNodeHtml(area, dynamicIndex)).join("")}
    ${visualAssets.map(({ asset, assetIndex }) => interfaceVisualNodeHtml(asset, assetIndex)).join("")}
    ${regionDangerZones.map(({ zone, dangerIndex }) => interfaceDangerNodeHtml(zone, dangerIndex)).join("")}`;
}

function interfaceStateRefsForRegion(regionId = "", states = []) {
  if (!regionId) return [];
  return states
    .filter((state) => Array.isArray(state.region_refs) && state.region_refs.map(String).includes(regionId))
    .map((state) => ({
      stateId: String(state.state_id || ""),
      label: String(state.label || state.state_id || ""),
    }))
    .filter((state) => state.stateId || state.label);
}

function interfaceTransitionActionKeysForItem(item = {}, regionId = "") {
  const semantic = String(item.semantic_action || item.action || "");
  const role = String(item.role || item.entity_type || "");
  const keys = new Set();
  if (semantic === "open_apply_flow") keys.add("apply_entry");
  if (semantic === "open_detail" || role === "job_card" || String(item.area_id || "").includes("job_card")) keys.add("open_job_card");
  if (semantic === "scroll_container" && regionId === "results_list") keys.add("load_more_results");
  if (semantic === "scroll_container" && ["job_detail", "detail_body"].includes(regionId)) keys.add("read_detail");
  if (String(item.entity_type || "") === "detail_content") keys.add("read_detail");
  if (semantic === "final_submit") keys.add("final_submit");
  return Array.from(keys);
}

function interfaceTransitionsForActionKeys(actionKeys = [], transitions = []) {
  const keys = new Set(actionKeys.filter(Boolean).map(String));
  if (!keys.size) return [];
  return transitions
    .filter((transition) => keys.has(String(transition.action_template_id || "")))
    .map((transition) => ({
      action: String(transition.action_template_id || ""),
      from: String(transition.from_state_id || ""),
      to: String(transition.to_state_id || ""),
      transitionId: String(transition.transition_id || ""),
    }));
}

function interfaceTransitionsForAsset(asset = {}, regionId = "", transitions = []) {
  return interfaceTransitionsForActionKeys(interfaceTransitionActionKeysForItem(asset, regionId), transitions);
}

function interfaceTransitionsForDynamicArea(area = {}, regionId = "", transitions = []) {
  return interfaceTransitionsForActionKeys(interfaceTransitionActionKeysForItem(area, regionId), transitions);
}

function interfaceTransitionsForRegion(regionId = "", assets = [], dynamicAreas = [], transitions = []) {
  const actionKeys = new Set();
  assets.forEach((asset) => interfaceTransitionActionKeysForItem(asset, regionId).forEach((key) => actionKeys.add(key)));
  dynamicAreas.forEach((area) => interfaceTransitionActionKeysForItem(area, regionId).forEach((key) => actionKeys.add(key)));
  return interfaceTransitionsForActionKeys(Array.from(actionKeys), transitions);
}

function interfaceRegionStateLinksHtml(stateRefs = [], transitions = []) {
  const stateText = stateRefs.length
    ? `<span class="interface-state-link">state: ${escapeHtml(stateRefs.slice(0, 2).map((state) => state.label || state.stateId).join(" / "))}${stateRefs.length > 2 ? ` +${stateRefs.length - 2}` : ""}</span>`
    : "";
  const transitionText = transitions.length
    ? transitions.slice(0, 3).map((transition) => `
        <span class="interface-transition-link">
          ${escapeHtml(transition.action || "action")} → ${escapeHtml(transition.to || "next_state")}
        </span>`).join("")
    : "";
  return `<div class="interface-state-links">${stateText}${transitionText}</div>`;
}

function interfaceNodeTransitionsHtml(transitions = []) {
  if (!transitions.length) return "";
  return `
    <span class="interface-node-transitions">
      ${transitions.slice(0, 2).map((transition) => `
        <i>${escapeHtml(transition.action || "action")} → ${escapeHtml(transition.to || "next")}</i>
      `).join("")}
    </span>`;
}

function interfaceRegionBbox(region = {}) {
  const bbox = region.bbox_hint?.bbox || region.bbox || null;
  if (!bbox || typeof bbox !== "object") return null;
  const x = Number(bbox.x);
  const y = Number(bbox.y);
  const w = Number(bbox.w ?? bbox.width);
  const h = Number(bbox.h ?? bbox.height);
  if (![x, y, w, h].every(Number.isFinite) || w <= 0 || h <= 0) return null;
  return { x, y, w, h };
}

function interfaceSpatialRegionMapHtml(regionEntries = [], assets = [], dynamicAreas = [], dangerZones = []) {
  const entries = regionEntries
    .map((entry) => ({ ...entry, bbox: interfaceRegionBbox(entry.region) }))
    .filter((entry) => entry.bbox);
  if (entries.length < 2) return "";
  const minX = Math.min(...entries.map((entry) => entry.bbox.x));
  const minY = Math.min(...entries.map((entry) => entry.bbox.y));
  const maxX = Math.max(...entries.map((entry) => entry.bbox.x + entry.bbox.w));
  const maxY = Math.max(...entries.map((entry) => entry.bbox.y + entry.bbox.h));
  const width = Math.max(1, maxX - minX);
  const height = Math.max(1, maxY - minY);
  const sorted = entries.sort((a, b) => {
    const areaA = a.bbox.w * a.bbox.h;
    const areaB = b.bbox.w * b.bbox.h;
    return areaB - areaA;
  });
  return `
    <div class="interface-spatial-canvas" style="aspect-ratio: ${width} / ${height};">
      ${sorted.map((entry, order) => interfaceSpatialRegionCardHtml(entry, assets, dynamicAreas, dangerZones, {
        minX,
        minY,
        width,
        height,
        order,
      })).join("")}
    </div>`;
}

function interfaceSpatialRegionCardHtml(entry, assets = [], dynamicAreas = [], dangerZones = [], layout = {}) {
  const region = entry.region || {};
  const bbox = entry.bbox;
  const regionId = entry.id || String(region.region_id || "");
  const ref = `region:${entry.index}`;
  const left = ((bbox.x - layout.minX) / layout.width) * 100;
  const top = ((bbox.y - layout.minY) / layout.height) * 100;
  const width = (bbox.w / layout.width) * 100;
  const height = (bbox.h / layout.height) * 100;
  const regionAssets = assets
    .map((asset, assetIndex) => ({ asset, assetIndex }))
    .filter(({ asset }) => interfaceAssetBelongsToRegion(asset, regionId));
  const regionDynamics = dynamicAreas
    .map((area, dynamicIndex) => ({ area, dynamicIndex }))
    .filter(({ area }) => String(area.region_id || "") === regionId);
  const regionDangerZones = dangerZones
    .map((zone, dangerIndex) => ({ zone, dangerIndex }))
    .filter(({ zone }) => {
      const asset = assets.find((item) => String(item.asset_id || "") === String(zone.asset_id || ""));
      return interfaceAssetBelongsToRegion(asset || {}, regionId);
    });
  return `
    <article class="interface-spatial-region${selectedInterfaceMapRef === ref ? " interface-selected" : ""}" style="left:${left.toFixed(3)}%;top:${top.toFixed(3)}%;width:${width.toFixed(3)}%;height:${height.toFixed(3)}%;z-index:${10 + layout.order};">
      <header>
        <button type="button" data-interface-inspect="${ref}">
          <strong>${escapeHtml(region.label || regionId)}</strong>
          <span>${escapeHtml(regionId)}</span>
        </button>
      </header>
      <div class="interface-spatial-assets">
        ${regionAssets.slice(0, 4).map(({ asset, assetIndex }) => interfaceVisualNodeHtml(asset, assetIndex)).join("")}
        ${regionDynamics.slice(0, 2).map(({ area, dynamicIndex }) => interfaceDynamicNodeHtml(area, dynamicIndex)).join("")}
        ${regionDangerZones.slice(0, 2).map(({ zone, dangerIndex }) => interfaceDangerNodeHtml(zone, dangerIndex)).join("")}
      </div>
    </article>`;
}

function interfaceRegionCardHtml(entry, childrenByParent, assets = [], dynamicAreas = [], dangerZones = [], depth = 0) {
  const region = entry.region || {};
  const regionId = entry.id || String(region.region_id || "");
  const ref = `region:${entry.index}`;
  const children = childrenByParent.get(regionId) || [];
  const regionAssets = assets
    .map((asset, assetIndex) => ({ asset, assetIndex }))
    .filter(({ asset }) => interfaceAssetBelongsToRegion(asset, regionId));
  const regionDynamics = dynamicAreas
    .map((area, dynamicIndex) => ({ area, dynamicIndex }))
    .filter(({ area }) => String(area.region_id || "") === regionId);
  const regionDangerZones = dangerZones
    .map((zone, dangerIndex) => ({ zone, dangerIndex }))
    .filter(({ zone }) => {
      const asset = assets.find((item) => String(item.asset_id || "") === String(zone.asset_id || ""));
      return interfaceAssetBelongsToRegion(asset || {}, regionId);
    });
  return `
    <article class="interface-region-card depth-${Math.min(depth, 3)}${selectedInterfaceMapRef === ref ? " interface-selected" : ""}">
      <header class="interface-region-header">
        <button class="interface-lane-title" type="button" data-interface-inspect="${ref}">
          <strong>${escapeHtml(region.label || regionId)}</strong>
          <span>${escapeHtml(regionId)} · ${escapeHtml(region.region_type || region.role || "region")}</span>
        </button>
        <div class="interface-lane-meta">
          ${region.container_id ? `<span>${escapeHtml(region.container_id)}</span>` : ""}
          <span>${region.visual_policy?.fixed_assets_use_template_match ? "template match" : "ROI model"}</span>
          ${region.default_collapsed ? "<span>子路径默认隐藏</span>" : ""}
        </div>
      </header>
      <div class="interface-region-layout">
        <span>${escapeHtml(interfaceRegionLayoutSummary(region))}</span>
      </div>
      ${regionAssets.length ? `
        <div class="interface-node-group">
          <h6>截图按钮 / fixed visual assets</h6>
          <div class="interface-node-row">
            ${regionAssets.map(({ asset, assetIndex }) => interfaceVisualNodeHtml(asset, assetIndex)).join("")}
          </div>
        </div>` : ""}
      ${regionDynamics.length ? `
        <div class="interface-node-group">
          <h6>变动区 / dynamic ROI</h6>
          <div class="interface-node-row">
            ${regionDynamics.map(({ area, dynamicIndex }) => interfaceDynamicNodeHtml(area, dynamicIndex)).join("")}
          </div>
        </div>` : ""}
      ${regionDangerZones.length ? `
        <div class="interface-node-group">
          <h6>${escapeHtml(t("replay_danger_regions"))}</h6>
          <div class="interface-node-row">
            ${regionDangerZones.map(({ zone, dangerIndex }) => interfaceDangerNodeHtml(zone, dangerIndex)).join("")}
          </div>
        </div>` : ""}
      ${children.length ? `
        <details class="interface-child-regions"${region.default_collapsed ? "" : " open"}>
          <summary>子区域 / child regions (${children.length})</summary>
          <div class="interface-region-children">
            ${children.map((child) => interfaceRegionCardHtml(child, childrenByParent, assets, dynamicAreas, dangerZones, depth + 1)).join("")}
          </div>
        </details>` : ""}
      ${!regionAssets.length && !regionDynamics.length && !regionDangerZones.length && !children.length ? `<p class="trace-idle">empty region</p>` : ""}
    </article>`;
}

function interfaceRegionLayoutSummary(region = {}) {
  const bbox = region.bbox_hint?.bbox || region.bbox || null;
  if (bbox && typeof bbox === "object") {
    const width = bbox.w ?? bbox.width ?? "";
    const height = bbox.h ?? bbox.height ?? "";
    return `布局: bbox x=${bbox.x ?? ""}, y=${bbox.y ?? ""}, w=${width}, h=${height}`;
  }
  return "布局: learned region hint，执行前需要当前截图 re-observe";
}

function interfaceRegionLaneHtml(region = {}, index = 0, assets = [], dynamicAreas = [], dangerZones = []) {
  const regionId = String(region.region_id || "");
  const ref = `region:${index}`;
  const regionAssets = assets
    .map((asset, assetIndex) => ({ asset, assetIndex }))
    .filter(({ asset }) => interfaceAssetBelongsToRegion(asset, regionId));
  const regionDynamics = dynamicAreas
    .map((area, dynamicIndex) => ({ area, dynamicIndex }))
    .filter(({ area }) => String(area.region_id || "") === regionId);
  const regionDangerZones = dangerZones
    .map((zone, dangerIndex) => ({ zone, dangerIndex }))
    .filter(({ zone }) => {
      const asset = assets.find((item) => String(item.asset_id || "") === String(zone.asset_id || ""));
      return interfaceAssetBelongsToRegion(asset || {}, regionId);
    });
  return `
    <article class="interface-lane interface-lane-${escapeHtml(String(region.region_type || "region").replace(/[^a-z0-9_-]/gi, "-"))}${selectedInterfaceMapRef === ref ? " interface-selected" : ""}">
      <header class="interface-lane-header">
        <button class="interface-lane-title" type="button" data-interface-inspect="${ref}">
          <strong>${escapeHtml(region.label || regionId)}</strong>
          <span>${escapeHtml(region.region_type || region.role || "")}</span>
        </button>
        <div class="interface-lane-meta">
          ${region.container_id ? `<span>${escapeHtml(region.container_id)}</span>` : ""}
          <span>${region.visual_policy?.fixed_assets_use_template_match ? "template match" : "ROI model"}</span>
          ${region.default_collapsed ? "<span>collapsed by default</span>" : ""}
        </div>
      </header>
      <div class="interface-lane-body">
        ${regionAssets.length ? `
          <div class="interface-node-group">
            <h6>固定按钮 / visual assets</h6>
            <div class="interface-node-row">
              ${regionAssets.map(({ asset, assetIndex }) => interfaceVisualNodeHtml(asset, assetIndex)).join("")}
            </div>
          </div>` : ""}
        ${regionDynamics.length ? `
          <div class="interface-node-group">
            <h6>变动区 / dynamic ROI</h6>
            <div class="interface-node-row">
              ${regionDynamics.map(({ area, dynamicIndex }) => interfaceDynamicNodeHtml(area, dynamicIndex)).join("")}
            </div>
          </div>` : ""}
        ${regionDangerZones.length ? `
          <div class="interface-node-group">
            <h6>${escapeHtml(t("replay_danger_regions"))}</h6>
            <div class="interface-node-row">
              ${regionDangerZones.map(({ zone, dangerIndex }) => interfaceDangerNodeHtml(zone, dangerIndex)).join("")}
            </div>
          </div>` : ""}
        ${!regionAssets.length && !regionDynamics.length && !regionDangerZones.length ? `<p class="trace-idle">${escapeHtml(t("replay_empty_region_lane"))}</p>` : ""}
      </div>
    </article>`;
}

function interfaceAssetBelongsToRegion(asset = {}, regionId = "") {
  if (!regionId) return false;
  if (String(asset.region_id || "") === regionId) return true;
  return Array.isArray(asset.allowed_region_ids) && asset.allowed_region_ids.map(String).includes(regionId);
}

function interfaceAssetImageRefs(asset = {}) {
  const refs = asset.template_refs && typeof asset.template_refs === "object" ? asset.template_refs : {};
  const evidence = asset.last_match_evidence && typeof asset.last_match_evidence === "object" ? asset.last_match_evidence : {};
  const calibrationMatch = interfaceCalibrationMatchForAsset(asset.asset_id);
  return [
    [t("replay_source_tight_crop"), refs.tight_crop_ref],
    [t("replay_source_context_crop"), refs.context_crop_ref],
    [t("replay_current_match"), calibrationMatch?.current_match_ref || refs.current_match_ref || evidence.current_match_ref],
    [t("replay_current_roi"), calibrationMatch?.current_roi_ref || refs.current_roi_ref || evidence.current_roi_ref],
    [t("replay_source_image"), refs.source_image_path],
  ].filter(([, path]) => path);
}

function interfaceVisualNodeHtml(asset = {}, index = 0) {
  const evidence = asset.last_match_evidence && typeof asset.last_match_evidence === "object" ? asset.last_match_evidence : {};
  const calibrationMatch = interfaceCalibrationMatchForAsset(asset.asset_id);
  const calibrationDecision = calibrationMatch?.calibration && typeof calibrationMatch.calibration === "object" ? calibrationMatch.calibration : {};
  const policyMeta = interfaceClickPermissionMeta(asset);
  const highRisk = policyMeta.level === "blocked";
  const decisionBadge = interfaceDecisionBadgeMeta(policyMeta);
  const matched = calibrationMatch ? calibrationMatch.matched === true : evidence.matched === true;
  const ambiguous = calibrationMatch ? calibrationMatch.ambiguous === true : evidence.ambiguous === true;
  const fast = policyMeta.fastLaneEligible && (calibrationDecision.fast_lane_allowed === true || asset.fast_lane_allowed === true || asset.fast_lane_eligible === true) && !highRisk && !ambiguous;
  const showThumb = interfaceAssetShouldShowThumb(asset);
  const imageRef = showThumb ? interfaceAssetImageRefs(asset)[0] : null;
  const crop = imageRef?.[1] || "";
  const compact = !showThumb && !crop;
  const ref = `asset:${index}`;
  return `
    <button class="interface-visual-node${compact ? " interface-visual-node-compact" : ""}${highRisk ? " interface-node-danger" : ""}${matched ? " interface-node-matched" : ""}${ambiguous ? " interface-node-ambiguous" : ""}${selectedInterfaceMapRef === ref ? " interface-selected" : ""}" type="button" data-interface-inspect="${ref}">
      ${compact ? "" : `
        <span class="interface-node-thumb">
          ${crop ? panelImageHtml(crop, asset.label || asset.asset_id || "visual asset") : `<em>${escapeHtml(interfaceAssetPlaceholderLabel(asset))}</em>`}
        </span>`}
      <strong>${escapeHtml(asset.label || asset.asset_id || "")}</strong>
      <small>${escapeHtml(asset.semantic_action || "visual_evidence")}</small>
      ${imageRef ? `<small class="interface-image-source">${escapeHtml(imageRef[0])}</small>` : ""}
      <span class="interface-node-badges">
        <i class="${escapeHtml(decisionBadge.className)}">${escapeHtml(decisionBadge.label)}</i>
        ${matched ? `<i class="ok">${escapeHtml(t("replay_matched"))}</i>` : ""}
        ${ambiguous ? `<i class="blocked">${escapeHtml(t("replay_ambiguous"))}</i>` : ""}
        ${(calibrationMatch?.match_score ?? evidence.match_score) !== undefined ? `<i>score ${escapeHtml(String(calibrationMatch?.match_score ?? evidence.match_score))}</i>` : ""}
      </span>
    </button>`;
}

function interfaceAssetShouldShowThumb(asset = {}) {
  const action = String(asset.semantic_action || "").toLowerCase();
  const role = String(asset.role || "").toLowerCase();
  const label = String(asset.label || asset.asset_id || "").toLowerCase();
  if (action === "scroll_container" || role.includes("scrollbar") || label.includes("scrollbar")) return false;
  if (action === "visual_evidence" || role === "visual_evidence") return false;
  return true;
}

function interfaceAssetPlaceholderLabel(asset = {}) {
  const action = String(asset.semantic_action || "").toLowerCase();
  const role = String(asset.role || "").toLowerCase();
  if (action === "scroll_container" || role.includes("scrollbar")) return t("replay_scroll_region");
  if (action === "visual_evidence" || role === "visual_evidence") return t("replay_visual_evidence");
  return t("replay_no_crop");
}

function interfaceCalibrationMatchForAsset(assetId) {
  const matches = Array.isArray(replayInterfaceCalibrationReport?.matches) ? replayInterfaceCalibrationReport.matches : [];
  return matches.find((match) => String(match?.asset_id || "") === String(assetId || "")) || null;
}

function interfaceDynamicNodeHtml(area = {}, index = 0) {
  const ref = `dynamic:${index}`;
  const summary = interfaceDynamicAreaSummary(area);
  return `
    <button class="interface-dynamic-node${selectedInterfaceMapRef === ref ? " interface-selected" : ""}" type="button" data-interface-inspect="${ref}">
      <strong>${escapeHtml(area.area_id || "")}</strong>
      <span>${escapeHtml(area.entity_type || "dynamic_area")}</span>
      ${summary ? `<small class="interface-dynamic-summary">${escapeHtml(summary)}</small>` : ""}
      <small>${area.model_budget?.avoid_full_screen_grounding ? "ROI-only first" : "model assisted"}</small>
    </button>`;
}

function interfaceDynamicAreaSummary(area = {}) {
  const areaId = String(area.area_id || "").toLowerCase();
  const regionId = String(area.region_id || "").toLowerCase();
  const entityType = String(area.entity_type || "").toLowerCase();
  if (entityType === "job_card" || areaId.includes("job_cards")) {
    return "这里会出现岗位卡片；点击卡片后更新右侧岗位详情。";
  }
  if (entityType === "detail_content" || regionId === "detail_body") {
    return "这里是详情正文变动区；执行时按 ROI 批量截图/阅读。";
  }
  if (areaId.includes("cover_letter")) {
    return "这里是求职信编辑区；填写前需要结合岗位详情生成内容。";
  }
  if (areaId.includes("question")) {
    return "这里会出现雇主问题；需要读取题目后逐项回答。";
  }
  if (areaId.includes("profile")) {
    return "这里是 SEEK Profile 复核区；默认避免修改长期资料。";
  }
  if (areaId.includes("final_review")) {
    return "这里是最终审核摘要；只能读取，最终提交必须阻断。";
  }
  return String(area.description || area.label || "");
}

function interfaceDangerNodeHtml(zone = {}, index = 0) {
  const ref = `danger:${index}`;
  const policyMeta = interfaceClickPermissionMeta(zone);
  return `
    <button class="interface-danger-node${selectedInterfaceMapRef === ref ? " interface-selected" : ""}" type="button" data-interface-inspect="${ref}">
      <strong>${escapeHtml(zone.label || zone.zone_id || "")}</strong>
      <span>${escapeHtml(zone.semantic_action || "")}</span>
      <small>${escapeHtml(policyMeta.actionLabel)}</small>
    </button>`;
}

function interfaceReviewPolicyForAsset(item = {}) {
  if (item.review_policy && typeof item.review_policy === "object") return item.review_policy;
  const action = String(item.semantic_action || "").toLowerCase();
  const danger = String(item.danger_level || "").toLowerCase();
  const text = `${action} ${danger} ${item.label || ""}`.toLowerCase();
  if (/(final_submit|submit|send|confirm|payment|complete application)/.test(text)) {
    return {
      contract_version: "visual_asset_review_policy_v1",
      risk_tier: "high",
      click_permission: "manual_review_required",
      requires_manual_review_before_click: true,
      requires_structured_authorization: true,
      fast_lane_eligible: false,
      reason: "high_risk_visual_asset",
    };
  }
  if (danger === "flow_entry" || danger === "continue_step" || action === "open_apply_flow" || action === "continue_next_step") {
    return {
      contract_version: "visual_asset_review_policy_v1",
      risk_tier: "medium",
      click_permission: "gate_required",
      requires_manual_review_before_click: false,
      requires_structured_authorization: false,
      fast_lane_eligible: false,
      reason: `${danger || action}_requires_scope_and_gate`,
    };
  }
  return {
    contract_version: "visual_asset_review_policy_v1",
    risk_tier: "low",
    click_permission: "low_risk_fast_lane_eligible",
    requires_manual_review_before_click: false,
    requires_structured_authorization: false,
    fast_lane_eligible: true,
    reason: "safe_fixed_control",
  };
}

function interfaceClickPermissionMeta(item = {}) {
  const policy = interfaceReviewPolicyForAsset(item);
  const permission = String(item.click_permission || policy.click_permission || "");
  if (permission === "manual_review_required") {
    return {
      permission,
      level: "blocked",
      className: "blocked",
      shortLabel: "manual review",
      actionLabel: "review required",
      fastLaneEligible: false,
      policy,
    };
  }
  if (permission === "gate_required") {
    return {
      permission,
      level: "warn",
      className: "warn",
      shortLabel: "gate required",
      actionLabel: "gate",
      fastLaneEligible: false,
      policy,
    };
  }
  return {
    permission: permission || "low_risk_fast_lane_eligible",
    level: "ok",
    className: "ok",
    shortLabel: "low risk",
    actionLabel: "fast lane",
    fastLaneEligible: policy.fast_lane_eligible !== false,
    policy,
  };
}

function interfaceDecisionBadgeMeta(policyMeta = {}) {
  if (policyMeta.level === "blocked") {
    return { className: "blocked", label: "禁止" };
  }
  if (policyMeta.level === "warn") {
    return { className: "warn", label: "需确认" };
  }
  return { className: "ok", label: "可调用" };
}

function interfaceSelectOptions(options, selected) {
  return options.map((option) => {
    const value = typeof option === "string" ? option : option.value;
    const label = typeof option === "string" ? option : option.label;
    return `<option value="${escapeHtml(value)}"${String(value) === String(selected || "") ? " selected" : ""}>${escapeHtml(label)}</option>`;
  }).join("");
}

function interfaceRegionHtml(region = {}, index = 0) {
  const type = region.region_type || region.role || "";
  const ref = `region:${index}`;
  return `
    <article class="interface-chip${selectedInterfaceMapRef === ref ? " interface-selected" : ""}">
      <button class="interface-inspect-btn" type="button" data-interface-inspect="${ref}">${escapeHtml(t("replay_inspect"))}</button>
      <strong>${escapeHtml(region.region_id || "")}</strong>
      <label>
        <span>label</span>
        <input data-interface-edit="region.label" data-index="${index}" value="${escapeHtml(region.label || region.region_id || "")}" />
      </label>
      <label>
        <span>type</span>
        <select data-interface-edit="region.region_type" data-index="${index}">
          ${interfaceSelectOptions(["navigation", "fixed_controls", "dynamic_collection", "detail_content", "form_flow", "danger_zone"], type)}
        </select>
      </label>
      <span>${escapeHtml(region.region_id || "")}</span>
      ${region.container_id ? `<span>${escapeHtml(region.container_id)}</span>` : ""}
    </article>`;
}

function interfaceDynamicAreaHtml(area = {}, index = 0) {
  const ref = `dynamic:${index}`;
  return `
    <article class="interface-chip${selectedInterfaceMapRef === ref ? " interface-selected" : ""}">
      <button class="interface-inspect-btn" type="button" data-interface-inspect="${ref}">${escapeHtml(t("replay_inspect"))}</button>
      <strong>${escapeHtml(area.area_id || "")}</strong>
      <span>${escapeHtml(area.region_id || "")}</span>
      <span>${escapeHtml(area.entity_type || "")}</span>
      <span>${area.model_budget?.avoid_full_screen_grounding ? "ROI model" : "model"}</span>
    </article>`;
}

function interfaceDangerZoneHtml(zone = {}, index = 0) {
  const ref = `danger:${index}`;
  return `
    <article class="interface-chip interface-chip-danger${selectedInterfaceMapRef === ref ? " interface-selected" : ""}">
      <button class="interface-inspect-btn" type="button" data-interface-inspect="${ref}">${escapeHtml(t("replay_inspect"))}</button>
      <strong>${escapeHtml(zone.label || zone.zone_id || "")}</strong>
      <span>${escapeHtml(zone.semantic_action || "")}</span>
      <span>${escapeHtml(zone.danger_level || "")}</span>
      <span>${zone.fast_lane_allowed ? "fast" : "blocked"}</span>
    </article>`;
}

function interfaceAssetHtml(asset = {}, index = 0, regionIds = []) {
  const refs = asset.template_refs && typeof asset.template_refs === "object" ? asset.template_refs : {};
  const crop = refs.tight_crop_ref || refs.context_crop_ref || refs.source_image_path || "";
  const highRisk = asset.is_high_risk || String(asset.danger_level || "").toLowerCase().includes("submit");
  const region = Array.isArray(asset.allowed_region_ids) && asset.allowed_region_ids.length ? asset.allowed_region_ids[0] : (asset.region_id || "");
  const regionOptions = regionIds.length ? regionIds : [region].filter(Boolean);
  const ref = `asset:${index}`;
  return `
    <article class="interface-asset${highRisk ? " interface-asset-danger" : ""}${selectedInterfaceMapRef === ref ? " interface-selected" : ""}">
      <button class="interface-inspect-btn" type="button" data-interface-inspect="${ref}">${escapeHtml(t("replay_inspect"))}</button>
      <div class="interface-asset-thumb">
        ${crop ? `<img src="${escapeHtml(traceImageUrl(crop))}" alt="${escapeHtml(asset.label || asset.asset_id || "visual asset")}" loading="lazy" />` : `<span>${escapeHtml(t("replay_no_crop"))}</span>`}
      </div>
      <div class="interface-asset-body">
        <strong>${escapeHtml(asset.label || asset.asset_id || "")}</strong>
        <span>${escapeHtml(asset.asset_id || "")}</span>
        <span class="run-badge ${highRisk ? "blocked" : "ok"}">${escapeHtml(asset.danger_level || "low")}</span>
        <div class="interface-edit-grid">
          <label>
            <span>action</span>
            <select data-interface-edit="asset.semantic_action" data-index="${index}">
              ${interfaceSelectOptions(["safe_navigation", "open_detail", "open_apply_flow", "external_apply_flow", "fill_field", "continue_next_step", "scroll_container", "scroll", "input", "read", "visual_evidence", "final_submit"], asset.semantic_action || "")}
            </select>
          </label>
          <label>
            <span>danger</span>
            <select data-interface-edit="asset.danger_level" data-index="${index}">
              ${interfaceSelectOptions(["low", "medium", "high", "flow_entry", "external_flow_entry", "final_submit"], asset.danger_level || "low")}
            </select>
          </label>
          <label>
            <span>region</span>
            <select data-interface-edit="asset.region_id" data-index="${index}">
              ${interfaceSelectOptions(regionOptions, region)}
            </select>
          </label>
        </div>
      </div>
    </article>`;
}

function bindInterfaceMapEditor(panel) {
  panel.querySelectorAll("[data-interface-inspect]").forEach((control) => {
    control.addEventListener("click", () => {
      selectedInterfaceMapRef = String(control.dataset.interfaceInspect || "");
      const pathNodeId = interfacePathNodeIdForStateRef(selectedInterfaceMapRef);
      if (pathNodeId) {
        showNavNodeDetail(pathNodeId, null, { preserveInterfaceSelection: true });
      }
      renderInterfaceMap(replayInterfaceMap, replayInterfaceMapPath);
    });
  });
  panel.querySelectorAll("[data-interface-edit]").forEach((control) => {
    control.addEventListener("change", () => {
      applyInterfaceMapEdit(control.dataset.interfaceEdit, Number(control.dataset.index || 0), control.value);
    });
  });
  panel.querySelectorAll("[data-interface-recrops-asset]").forEach((control) => {
    control.addEventListener("click", () => {
      recropInterfaceAsset(Number(control.dataset.interfaceRecropsAsset || 0));
    });
  });
}

function interfaceMapSelectedItem(map, ref) {
  const [kind, indexText] = String(ref || "").split(":");
  const index = Number(indexText || 0);
  if (kind === "state") return { kind, index, item: map.states?.[index], title: "State" };
  if (kind === "region") return { kind, item: map.regions?.[index], title: "Region" };
  if (kind === "asset") return { kind, item: map.fixed_visual_assets?.[index], title: "Fixed visual asset" };
  if (kind === "dynamic") return { kind, item: map.dynamic_areas?.[index], title: "Dynamic ROI area" };
  if (kind === "danger") return { kind, item: map.danger_zones?.[index], title: "Danger zone" };
  return { kind: "", item: null, title: "" };
}

function interfacePathNodeIdForStateRef(ref = "") {
  const selected = interfaceMapSelectedItem(replayInterfaceMap || {}, ref);
  if (selected.kind !== "state" || !selected.item) return "";
  const stateId = String(selected.item.state_id || "");
  if (!stateId || !Array.isArray(navPathNodes)) return "";
  const direct = navPathNodes.find((node) => String(node.id || "") === stateId);
  if (direct) return String(direct.id || "");
  const byStateGuess = navPathNodes.find((node) => String(node.stateGuess || "") === stateId);
  return byStateGuess ? String(byStateGuess.id || "") : "";
}

function interfaceInspectorHtml(map, regionIds = []) {
  const selected = interfaceMapSelectedItem(map, selectedInterfaceMapRef);
  const item = selected.item;
  if (!item) return `<p class="trace-idle">${escapeHtml(t("pending"))}</p>`;
  const refs = item.template_refs && typeof item.template_refs === "object" ? item.template_refs : {};
  const geometry = item.source_geometry && typeof item.source_geometry === "object" ? item.source_geometry : {};
  const matchPolicy = item.match_policy && typeof item.match_policy === "object" ? item.match_policy : {};
  const lastMatch = item.last_match_evidence && typeof item.last_match_evidence === "object" ? item.last_match_evidence : {};
  const calibrationMatch = selected.kind === "asset" ? interfaceCalibrationMatchForAsset(item.asset_id) : null;
  const calibrationDecision = calibrationMatch?.calibration && typeof calibrationMatch.calibration === "object" ? calibrationMatch.calibration : {};
  const policyMeta = interfaceClickPermissionMeta(item);
  const reviewPolicy = policyMeta.policy || {};
  const imageRefs = selected.kind === "asset" ? (interfaceAssetShouldShowThumb(item) ? interfaceAssetImageRefs(item) : []) : [
    [t("replay_source_image"), refs.source_image_path],
    [t("replay_current_roi"), calibrationMatch?.current_roi_ref || refs.current_roi_ref || lastMatch.current_roi_ref],
    [t("replay_current_match"), calibrationMatch?.current_match_ref || refs.current_match_ref || lastMatch.current_match_ref],
  ].filter(([, path]) => path);
  const regionContentsHtml = selected.kind === "region" ? interfaceInspectorRegionContentsHtml(map, item) : "";
  const selectedRegion = selected.kind === "region"
    ? item
    : (Array.isArray(map.regions) ? map.regions.find((region) => String(region.region_id || "") === String(item.region_id || "")) : null);
  const selectedRegionSummary = selectedRegion ? interfaceRegionSummaryText(
    selectedRegion,
    (Array.isArray(map.fixed_visual_assets) ? map.fixed_visual_assets : []).filter((asset) => interfaceAssetBelongsToRegion(asset, String(selectedRegion.region_id || ""))),
    (Array.isArray(map.dynamic_areas) ? map.dynamic_areas : []).filter((area) => String(area.region_id || "") === String(selectedRegion.region_id || "")),
    (Array.isArray(map.danger_zones) ? map.danger_zones : []).filter((zone) => String(zone.region_id || "") === String(selectedRegion.region_id || "")),
  ) : "";
  const stateWorkflowHtml = selected.kind === "state"
    ? interfaceInspectorStateWorkflowHtml(item, map)
    : "";
  const stateRegionsHtml = selected.kind === "state"
    ? interfaceInspectorStateRegionsHtml(item, map)
    : "";
  const regionWorkflowHtml = selected.kind === "region"
    ? interfaceInspectorRegionWorkflowHtml(String(item.region_id || ""))
    : "";
  const pairs = [
    ["kind", selected.title],
    ["id", item.asset_id || item.region_id || item.area_id || item.zone_id || ""],
    ["label", item.label || ""],
    ["role", item.role || item.region_type || ""],
    ["semantic_action", item.semantic_action || ""],
    ["danger_level", item.danger_level || ""],
    ["click_permission", item.click_permission || reviewPolicy.click_permission || ""],
    ["review_policy", policyMeta.shortLabel],
    ["review_reason", reviewPolicy.reason || ""],
    ["requires_manual_review", String(reviewPolicy.requires_manual_review_before_click === true)],
    ["requires_structured_authorization", String(reviewPolicy.requires_structured_authorization === true)],
    ["fast_lane_eligible", String(policyMeta.fastLaneEligible === true)],
    ["fast_lane_allowed", String(calibrationDecision.fast_lane_allowed ?? item.fast_lane_allowed ?? policyMeta.fastLaneEligible)],
    ["calibration_matched", calibrationMatch ? String(calibrationMatch.matched === true) : ""],
    ["calibration_ambiguous", calibrationMatch ? String(calibrationMatch.ambiguous === true) : ""],
    ["calibration_reason", calibrationDecision.reason || ""],
    ["requires_gate", String(item.requires_gate ?? true)],
    ["can_authorize_click", String(item.can_authorize_click === true)],
    ["region", item.region_id || (Array.isArray(item.allowed_region_ids) ? item.allowed_region_ids.join(", ") : "")],
    ["bbox", JSON.stringify(geometry.bbox || item.bbox_hint || item.bbox || "")],
    ["click_point", JSON.stringify(geometry.click_point || item.click_point || "")],
    ["current_bbox", JSON.stringify(calibrationMatch?.bbox || lastMatch.bbox || "")],
    ["current_click_point", JSON.stringify(calibrationMatch?.click_point || lastMatch.click_point || "")],
    ["match_score", calibrationMatch?.match_score ?? item.match_score ?? item.score ?? lastMatch.match_score ?? ""],
    ["score_gap_to_second", calibrationMatch?.score_gap_to_second ?? item.score_gap_to_second ?? matchPolicy.score_gap_to_second ?? lastMatch.score_gap_to_second ?? ""],
    ["elapsed_ms", calibrationMatch?.elapsed_ms ?? lastMatch.elapsed_ms ?? ""],
    ["match_method", calibrationMatch?.match_method || item.match_method || matchPolicy.match_method || lastMatch.match_method || ""],
    ["scale_used", calibrationMatch?.scale ?? item.scale_used ?? matchPolicy.scale_used ?? lastMatch.scale_used ?? ""],
    ["freshness", calibrationMatch?.candidate_freshness?.freshness || lastMatch.candidate_freshness?.freshness || ""],
    ["min_similarity", matchPolicy.minimum_similarity ?? ""],
    ["scope", JSON.stringify(item.allowed_region_ids || item.scope || item.container_id || "")],
  ];
  return `
    <h5>${escapeHtml(t("interface_inspector"))}</h5>
    <div class="interface-inspector-warning">
      <strong>${escapeHtml(t("replay_evidence_not_authorization"))}</strong>
      <span>${escapeHtml(t("replay_evidence_not_authorization_hint"))}</span>
    </div>
    ${selectedRegionSummary ? `<div class="interface-inspector-summary">${escapeHtml(selectedRegionSummary)}</div>` : ""}
    ${stateRegionsHtml}
    ${stateWorkflowHtml}
    ${regionWorkflowHtml}
    ${regionContentsHtml}
    ${interfaceInspectorEditorHtml(selected, regionIds)}
    <div class="summary-grid summary-grid-pairs">
      ${pairs.map(([label, value]) => `
        <div class="summary-item">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(String(value ?? ""))}</strong>
        </div>`).join("")}
    </div>
    ${imageRefs.length ? `
        <div class="interface-evidence-grid">
        ${imageRefs.map(([label, path]) => `
          <figure>
            <figcaption>${escapeHtml(label)}</figcaption>
            ${panelImageHtml(path, label)}
            <code>${escapeHtml(String(path))}</code>
          </figure>`).join("")}
      </div>` : `<p class="trace-idle">${escapeHtml(t("replay_no_image_evidence"))}</p>`}
    <pre class="interface-json">${escapeHtml(JSON.stringify(item, null, 2))}</pre>`;
}

function interfaceInspectorStateRegionsHtml(state = {}, map = {}) {
  const regions = Array.isArray(map.regions) ? map.regions : [];
  const assets = Array.isArray(map.fixed_visual_assets) ? map.fixed_visual_assets : [];
  const dynamicAreas = Array.isArray(map.dynamic_areas) ? map.dynamic_areas : [];
  const dangerZones = Array.isArray(map.danger_zones) ? map.danger_zones : [];
  const regionIds = interfaceRegionRefsForState(state, regions);
  if (!regionIds.length) return "";
  const regionCards = regionIds.map((regionId) => {
    const region = regions.find((item) => String(item.region_id || "") === String(regionId));
    if (!region) return "";
    const regionAssets = assets.filter((asset) => interfaceAssetBelongsToRegion(asset, regionId));
    const regionDynamics = dynamicAreas.filter((area) => String(area.region_id || "") === String(regionId));
    const regionDangerZones = dangerZones.filter((zone) => {
      const asset = assets.find((item) => String(item.asset_id || "") === String(zone.asset_id || ""));
      return String(zone.region_id || "") === String(regionId) || interfaceAssetBelongsToRegion(asset || {}, regionId);
    });
    const workflowActions = interfaceWorkflowActionsForRegion(regionId);
    const summary = interfaceRegionSummaryText(region, regionAssets, regionDynamics, regionDangerZones);
    return `
      <li>
        <button type="button" data-interface-inspect="region:${regions.indexOf(region)}">
          <strong>${escapeHtml(region.label || regionId)}</strong>
          <span>${escapeHtml(summary || region.description || region.region_type || "")}</span>
        </button>
        <small>
          ${regionAssets.length} ${escapeHtml(t("replay_button_screenshots"))} ·
          ${regionDynamics.length} ${escapeHtml(t("replay_dynamic_regions"))} ·
          ${workflowActions.length} ${escapeHtml(t("replay_workflow_skill"))}
        </small>
      </li>`;
  }).filter(Boolean).join("");
  if (!regionCards) return "";
  return `
    <div class="interface-inspector-page-regions">
      <strong>${escapeHtml(t("replay_screen_regions"))}</strong>
      <ul>${regionCards}</ul>
    </div>`;
}

function interfaceInspectorStateWorkflowHtml(state = {}, map = {}) {
  const regions = Array.isArray(map.regions) ? map.regions : [];
  const regionIds = interfaceRegionRefsForState(state, regions);
  if (!regionIds.length) return "";
  const labelByRegion = new Map(regions.map((region) => [
    String(region.region_id || ""),
    String(region.label || region.region_id || ""),
  ]));
  const roleByRegion = new Map(regions.map((region) => [
    String(region.region_id || ""),
    String(region.region_type || region.role || "region"),
  ]));
  const seen = new Set();
  const actionGroups = regionIds.map((regionId) => {
    const actionItems = interfaceWorkflowActionsForRegion(regionId).map((action) => {
      const actionId = action.actionId || "action";
      const target = action.target || regionId;
      const key = `${regionId}:${actionId}:${target}`;
      if (seen.has(key)) return "";
      seen.add(key);
      const detail = [action.skill, action.lowLevel, target, action.gated ? t("replay_gate_confirm") : t("replay_callable")].filter(Boolean).join(" · ");
      return `
        <li>
          <strong>${escapeHtml(actionId)}</strong>
          <span>${escapeHtml(detail)}</span>
        </li>`;
    }).filter(Boolean).join("");
    if (!actionItems) return "";
    const regionLabel = labelByRegion.get(regionId) || regionId;
    const regionRole = roleByRegion.get(regionId) || "region";
    return `
      <li class="interface-inspector-region-action-group">
        <strong>${escapeHtml(regionLabel)}</strong>
        <span>${escapeHtml(regionId)} · ${escapeHtml(regionRole)}</span>
        <ul>${actionItems}</ul>
      </li>`;
  }).filter(Boolean).join("");
  if (!actionGroups) return "";
  return `
    <div class="interface-inspector-workflow">
      <strong>${escapeHtml(t("replay_workflow_skill"))}</strong>
      <ul>${actionGroups}</ul>
    </div>`;
}

function interfaceInspectorRegionWorkflowHtml(regionId = "") {
  const workflowActions = interfaceWorkflowActionsForRegion(regionId);
  if (!workflowActions.length) return "";
  const actionItems = workflowActions.map((action) => {
    const actionId = action.actionId || "action";
    const detail = [action.skill, action.lowLevel, action.target, action.gated ? t("replay_gate_confirm") : t("replay_callable")].filter(Boolean).join(" · ");
    return `
      <li>
        <strong>${escapeHtml(actionId)}</strong>
        <span>${escapeHtml(detail)}</span>
      </li>`;
  }).join("");
  return `
    <div class="interface-inspector-workflow">
      <strong>${escapeHtml(t("replay_workflow_skill"))}</strong>
      <ul>${actionItems}</ul>
    </div>`;
}

function interfaceInspectorEditorHtml(selected, regionIds = []) {
  const item = selected.item || {};
  if (selected.kind === "region") {
    const regionIndex = Number(String(selectedInterfaceMapRef || "").split(":")[1] || 0);
    return `
      <div class="interface-policy-editor">
        <h6>${escapeHtml(t("replay_region_policy"))}</h6>
        <label>
          <span>label</span>
          <input data-interface-edit="region.label" data-index="${regionIndex}" value="${escapeHtml(item.label || item.region_id || "")}" />
        </label>
        <label>
          <span>type</span>
          <select data-interface-edit="region.region_type" data-index="${regionIndex}">
            ${interfaceSelectOptions(["navigation", "fixed_controls", "dynamic_collection", "detail_content", "form_flow", "danger_zone"], item.region_type || item.role || "")}
          </select>
        </label>
      </div>`;
  }
  if (selected.kind === "asset") {
    const assetIndex = Number(String(selectedInterfaceMapRef || "").split(":")[1] || 0);
    const region = Array.isArray(item.allowed_region_ids) && item.allowed_region_ids.length ? item.allowed_region_ids[0] : (item.region_id || "");
    const regionOptions = regionIds.length ? regionIds : [region].filter(Boolean);
    const refs = item.template_refs && typeof item.template_refs === "object" ? item.template_refs : {};
    const source = item.source && typeof item.source === "object" ? item.source : {};
    const geometry = item.source_geometry && typeof item.source_geometry === "object" ? item.source_geometry : {};
    const bbox = geometry.bbox && typeof geometry.bbox === "object" ? geometry.bbox : {};
    const sourceImage = refs.source_image_path || source.source_image_path || geometry.source_image_path || "";
    const canRecrop = interfaceAssetShouldShowThumb(item);
    return `
      <div class="interface-policy-editor">
        <h6>${escapeHtml(t("replay_visual_policy"))}</h6>
        <label>
          <span>action</span>
          <select data-interface-edit="asset.semantic_action" data-index="${assetIndex}">
            ${interfaceSelectOptions(["safe_navigation", "open_detail", "open_apply_flow", "external_apply_flow", "fill_field", "continue_next_step", "scroll_container", "scroll", "input", "read", "visual_evidence", "final_submit"], item.semantic_action || "")}
          </select>
        </label>
        <label>
          <span>danger</span>
          <select data-interface-edit="asset.danger_level" data-index="${assetIndex}">
            ${interfaceSelectOptions(["low", "medium", "high", "flow_entry", "external_flow_entry", "final_submit"], item.danger_level || "low")}
          </select>
        </label>
        <label>
          <span>region</span>
          <select data-interface-edit="asset.region_id" data-index="${assetIndex}">
            ${interfaceSelectOptions(regionOptions, region)}
          </select>
        </label>
      </div>
      ${canRecrop ? `<div class="interface-crop-editor">
        <h6>${escapeHtml(t("replay_recrop_visual_asset"))}</h6>
        ${sourceImage ? `
          <figure class="interface-crop-source-preview">
            <figcaption>${escapeHtml(t("replay_source_image_preview"))}</figcaption>
            ${panelImageHtml(sourceImage, t("replay_source_image_preview"))}
          </figure>` : ""}
        <label class="wide-control">
          <span>${escapeHtml(t("replay_source_image"))}</span>
          <input data-interface-crop="source_image_path" data-index="${assetIndex}" value="${escapeHtml(sourceImage)}" />
        </label>
        <label><span>x</span><input type="number" data-interface-crop="x" data-index="${assetIndex}" value="${escapeHtml(String(bbox.x ?? 0))}" /></label>
        <label><span>y</span><input type="number" data-interface-crop="y" data-index="${assetIndex}" value="${escapeHtml(String(bbox.y ?? 0))}" /></label>
        <label><span>w</span><input type="number" data-interface-crop="w" data-index="${assetIndex}" value="${escapeHtml(String(bbox.w ?? bbox.width ?? 1))}" /></label>
        <label><span>h</span><input type="number" data-interface-crop="h" data-index="${assetIndex}" value="${escapeHtml(String(bbox.h ?? bbox.height ?? 1))}" /></label>
        <button type="button" data-interface-recrops-asset="${assetIndex}">${escapeHtml(t("replay_recrop_button"))}</button>
      </div>` : `
      <div class="interface-crop-editor interface-crop-disabled">
        <h6>${escapeHtml(t("replay_no_button_crop"))}</h6>
        <p>${escapeHtml(t("replay_no_button_crop_hint"))}</p>
      </div>`}`;
  }
  return "";
}

function interfaceInspectorRegionContentsHtml(map = {}, region = {}) {
  const regionId = String(region.region_id || "");
  if (!regionId) return "";
  const assets = Array.isArray(map.fixed_visual_assets) ? map.fixed_visual_assets : [];
  const dynamicAreas = Array.isArray(map.dynamic_areas) ? map.dynamic_areas : [];
  const dangerZones = Array.isArray(map.danger_zones) ? map.danger_zones : [];
  const regionAssets = assets
    .map((asset, assetIndex) => ({ asset, assetIndex }))
    .filter(({ asset }) => interfaceAssetBelongsToRegion(asset, regionId));
  const regionDynamics = dynamicAreas
    .map((area, dynamicIndex) => ({ area, dynamicIndex }))
    .filter(({ area }) => String(area.region_id || "") === regionId);
  const regionDangerZones = dangerZones
    .map((zone, dangerIndex) => ({ zone, dangerIndex }))
    .filter(({ zone }) => {
      const asset = assets.find((item) => String(item.asset_id || "") === String(zone.asset_id || ""));
      return interfaceAssetBelongsToRegion(asset || {}, regionId);
    });
  const assetItems = regionAssets.map(({ asset, assetIndex }) => `
    <li data-path-detail-inspect="asset:${assetIndex}">
      <strong>${escapeHtml(asset.label || asset.asset_id || "button")}</strong>
      <span>${escapeHtml(asset.semantic_action || asset.role || "fixed visual asset")}</span>
    </li>`).join("");
  const dynamicItems = regionDynamics.map(({ area, dynamicIndex }) => `
    <li data-path-detail-inspect="dynamic:${dynamicIndex}">
      <strong>${escapeHtml(area.label || area.area_id || "dynamic ROI")}</strong>
      <span>${escapeHtml(area.semantic_role || area.role || area.area_type || "ROI")}</span>
    </li>`).join("");
  const dangerItems = regionDangerZones.map(({ zone, dangerIndex }) => `
    <li data-path-detail-inspect="danger:${dangerIndex}">
      <strong>${escapeHtml(zone.label || zone.zone_id || "danger")}</strong>
      <span>${escapeHtml(zone.semantic_action || zone.danger_level || "manual review")}</span>
    </li>`).join("");
  return `
    <div class="interface-inspector-contents">
      <h6>${escapeHtml(t("replay_region_contents"))}</h6>
      ${assetItems ? `<section><strong>${escapeHtml(t("replay_button_screenshots"))}</strong><ul>${assetItems}</ul></section>` : ""}
      ${dynamicItems ? `<section><strong>${escapeHtml(t("replay_dynamic_regions"))}</strong><ul>${dynamicItems}</ul></section>` : ""}
      ${dangerItems ? `<section><strong>${escapeHtml(t("replay_danger_regions"))}</strong><ul>${dangerItems}</ul></section>` : ""}
      ${(!assetItems && !dynamicItems && !dangerItems) ? `<p class="trace-idle">${escapeHtml(t("replay_region_structure_only"))}</p>` : ""}
    </div>`;
}

function applyInterfaceMapEdit(field, index, value) {
  if (!replayInterfaceMap || !field) return;
  if (field.startsWith("region.")) {
    const key = field.split(".")[1];
    const region = replayInterfaceMap.regions?.[index];
    if (!region) return;
    region[key] = value;
    if (key === "region_type") region.role = value;
  } else if (field.startsWith("asset.")) {
    const key = field.split(".")[1];
    const asset = replayInterfaceMap.fixed_visual_assets?.[index];
    if (!asset) return;
    if (key === "region_id") {
      asset.region_id = value;
      asset.allowed_region_ids = value ? [value] : [];
    } else {
      asset[key] = value;
    }
    refreshInterfaceAssetReviewPolicy(asset);
    syncInterfaceMapDangerZones(replayInterfaceMap);
  }
  renderInterfaceMap(replayInterfaceMap, replayInterfaceMapPath);
}

function refreshInterfaceAssetReviewPolicy(asset = {}) {
  const danger = String(asset.danger_level || "").toLowerCase();
  const action = String(asset.semantic_action || "").toLowerCase();
  if (action === "final_submit" || danger.includes("submit") || danger === "final_submit") {
    asset.semantic_action = "final_submit";
    asset.danger_level = "final_submit";
  }
  asset.review_policy = interfaceReviewPolicyForAsset({ ...asset, review_policy: null });
  asset.click_permission = asset.review_policy.click_permission;
  asset.fast_lane_eligible = asset.review_policy.fast_lane_eligible === true;
  asset.is_high_risk = asset.click_permission === "manual_review_required";
  asset.fast_lane_allowed = asset.fast_lane_eligible === true ? asset.fast_lane_allowed === true : false;
  asset.requires_gate = true;
  asset.can_authorize_click = false;
}

function ensureInterfaceAssetReviewPolicy(asset = {}) {
  const policy = interfaceReviewPolicyForAsset(asset);
  asset.review_policy = policy;
  asset.click_permission = policy.click_permission;
  asset.fast_lane_eligible = policy.fast_lane_eligible === true;
  asset.is_high_risk = policy.click_permission === "manual_review_required";
  asset.fast_lane_allowed = asset.fast_lane_eligible === true ? asset.fast_lane_allowed === true : false;
  asset.requires_gate = true;
  asset.can_authorize_click = false;
}

function normalizeInterfaceMapReviewPolicies(map = {}) {
  if (!map || typeof map !== "object") return map;
  if (Array.isArray(map.fixed_visual_assets)) {
    map.fixed_visual_assets.forEach((asset) => {
      if (!asset || typeof asset !== "object") return;
      ensureInterfaceAssetReviewPolicy(asset);
    });
  }
  syncInterfaceMapDangerZones(map);
  return map;
}

function syncInterfaceMapDangerZones(map = {}) {
  const assets = Array.isArray(map.fixed_visual_assets) ? map.fixed_visual_assets : [];
  map.danger_zones = assets
    .filter((asset) => asset && typeof asset === "object" && asset.is_high_risk)
    .map((asset) => ({
      zone_id: `danger:${asset.asset_id || asset.label || "asset"}`,
      asset_id: asset.asset_id,
      label: asset.label,
      semantic_action: asset.semantic_action,
      danger_level: asset.danger_level,
      review_policy: asset.review_policy,
      click_permission: asset.click_permission,
      review_required: true,
      fast_lane_allowed: false,
    }));
  map.summary = map.summary && typeof map.summary === "object" ? map.summary : {};
  map.summary.danger_zone_count = map.danger_zones.length;
}

async function recropInterfaceAsset(index) {
  const asset = replayInterfaceMap?.fixed_visual_assets?.[index];
  if (!asset) {
    renderResponse({ success: false, message: "No visual asset selected for recrop" }, "Interface asset crop");
    return null;
  }
  const panel = $("replayInterfaceMapPanel");
  const readCropValue = (name) => panel?.querySelector(`[data-interface-crop="${name}"][data-index="${index}"]`)?.value || "";
  const request = {
    source_image_path: String(readCropValue("source_image_path") || asset.template_refs?.source_image_path || ""),
    asset_id: String(asset.asset_id || `asset_${index}`),
    label: String(asset.label || ""),
    x: Number(readCropValue("x") || 0),
    y: Number(readCropValue("y") || 0),
    width: Number(readCropValue("w") || 1),
    height: Number(readCropValue("h") || 1),
    padding_px: 6,
    context_padding_px: 16,
  };
  if (!request.source_image_path) {
    renderResponse({ success: false, message: "source_image_path is required for recrop" }, "Interface asset crop");
    return null;
  }
  const response = await api("POST", "/panel/crop_interface_asset", request, { summary: "crop interface asset" });
  if (!response?.success || !response.data) {
    renderResponse(response, "Interface asset crop");
    return response;
  }
  asset.template_refs = asset.template_refs && typeof asset.template_refs === "object" ? asset.template_refs : {};
  asset.template_refs.tight_crop_ref = response.data.tight_crop_ref;
  asset.template_refs.context_crop_ref = response.data.context_crop_ref;
  asset.template_refs.source_image_path = response.data.source_image_path;
  asset.template_refs.current_roi_ref = null;
  asset.template_refs.current_match_ref = null;
  asset.source_geometry = asset.source_geometry && typeof asset.source_geometry === "object" ? asset.source_geometry : {};
  asset.source_geometry.bbox = response.data.bbox;
  asset.source_geometry.click_point = response.data.click_point;
  asset.source_geometry.coordinate_space = "source_capture_px";
  asset.source_geometry.source_is_authorization = false;
  asset.last_match_evidence = null;
  asset.fast_lane_allowed = false;
  asset.can_authorize_click = false;
  asset.requires_gate = true;
  renderInterfaceMap(replayInterfaceMap, replayInterfaceMapPath);
  renderResponse({
    success: true,
    message: "Interface asset recropped",
    data: {
      contract_version: "interface_map_panel_recrop_v1",
      asset_id: asset.asset_id,
      tight_crop_ref: response.data.tight_crop_ref,
      context_crop_ref: response.data.context_crop_ref,
      trace_path: response.data.trace_path,
      can_authorize_click: false,
    },
  }, "Interface asset crop");
  return response;
}

function interfaceMapEditSummary(map) {
  const assets = Array.isArray(map?.fixed_visual_assets) ? map.fixed_visual_assets : [];
  const highRisk = assets.filter((asset) => asset.is_high_risk || asset.semantic_action === "final_submit" || String(asset.danger_level || "").includes("submit"));
  return {
    contract_version: "learned_interface_map_panel_edit_summary_v1",
    region_count: Array.isArray(map?.regions) ? map.regions.length : 0,
    fixed_visual_asset_count: assets.length,
    high_risk_asset_count: highRisk.length,
    edited_in_panel: true,
    authorization_changed: false,
  };
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

function renderSeekApplicationEvidence(evidence) {
  const summary = $("seekApplicationEvidenceSummary");
  const fields = $("seekApplicationFilledFields");
  if (!summary || !fields) return;
  if (!evidence) {
    summary.innerHTML = `<p class="trace-idle">${t("pending")}</p>`;
    fields.innerHTML = "";
    return;
  }
  const { record = {}, audit = {}, artifact = {}, paths = {} } = evidence;
  const recordEvidence = record.evidence && typeof record.evidence === "object" ? record.evidence : {};
  const filledContent = record.filled_content && typeof record.filled_content === "object" ? record.filled_content : {};
  const safety = artifact.safety_policy && typeof artifact.safety_policy === "object" ? artifact.safety_policy : {};
  const artifactSummary = artifact.filled_content_summary && typeof artifact.filled_content_summary === "object" ? artifact.filled_content_summary : {};
  const screenshots = Array.isArray(recordEvidence.screenshots) ? recordEvidence.screenshots : [];
  const actionTraces = Array.isArray(recordEvidence.action_traces) ? recordEvidence.action_traces : [];
  const visionTraces = Array.isArray(recordEvidence.vision_traces) ? recordEvidence.vision_traces : [];
  const employerQuestionCount = Number(record.employer_question_total ?? artifactSummary.employer_question_count ?? 0);
  const auditPassed = audit.decision === "pass_stopped_before_final_submit";
  const artifactNotAuthorization = artifact.milestone?.artifact_is_authorization === false && safety.artifact_is_authorization === false;
  const finalSubmitForbidden = safety.final_submit_forbidden === true;
  const finalSubmissions = Number(record.final_submissions ?? safety.final_submissions ?? 0);
  const submitClicks = Number(record.submit_clicks ?? safety.submit_clicks ?? 0);
  const reviewSafe = auditPassed && artifactNotAuthorization && finalSubmitForbidden && finalSubmissions === 0;
  const pairs = [
    ["record", paths.record || ""],
    ["audit", paths.audit || ""],
    ["artifact", paths.artifact || ""],
    ["record_contract", record.contract_version || ""],
    ["audit_decision", audit.decision || ""],
    ["artifact_contract", artifact.contract_version || ""],
    ["job", [record.job_title || record.job?.title || "", record.job?.company || ""].filter(Boolean).join(" / ")],
    ["status", record.status || ""],
    ["employer_questions", `${employerQuestionCount}/${employerQuestionCount}`],
    ["cover_letter_length", artifactSummary.cover_letter_length ?? String(filledContent.cover_letter || "").length],
    ["screenshots", screenshots.length],
    ["action_traces", actionTraces.length],
    ["vision_traces", visionTraces.length],
    ["audit_passed", auditPassed],
    ["artifact_is_authorization", !artifactNotAuthorization],
    ["final_submit_forbidden", finalSubmitForbidden],
    ["submit_clicks", submitClicks],
    ["final_submissions", finalSubmissions],
  ];
  summary.innerHTML = `
    <div class="summary-grid summary-grid-pairs">
      ${pairs.map(([label, value]) => `
        <div class="summary-item${["record", "audit", "artifact"].includes(label) ? " summary-item-wide" : ""}">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(String(value))}</strong>
        </div>`).join("")}
    </div>
    <div class="evidence-note">
      <span class="run-badge ${reviewSafe ? "ok" : "blocked"}">${reviewSafe ? "safe review boundary" : "needs review"}</span>
      <code>${escapeHtml(recordEvidence.review_before_submit_screenshot || "")}</code>
    </div>`;

  const filledFields = Array.isArray(record.filled_fields) ? record.filled_fields : [];
  if (!filledFields.length) {
    fields.innerHTML = `<p class="trace-idle">${t("no_response")}</p>`;
    return;
  }
  fields.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Step</th>
          <th>Field</th>
          <th>Value / policy</th>
          <th>Evidence</th>
        </tr>
      </thead>
      <tbody>
        ${filledFields.map((item) => {
          const value = String(item.value || item.policy || "");
          const shortened = value.length > 260 ? `${value.slice(0, 260)}...` : value;
          return `
            <tr>
              <td>${escapeHtml(item.step || "")}</td>
              <td>${escapeHtml(item.field || "")}</td>
              <td>${escapeHtml(shortened)}</td>
              <td>${escapeHtml(item.evidence || item.policy || "")}</td>
            </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

async function loadSeekApplicationEvidence() {
  const recordPath = String($("seekApplicationRecordPath")?.value || DEFAULT_SEEK_APPLICATION_RECORD_PATH).trim();
  const auditPath = String($("seekApplicationAuditPath")?.value || DEFAULT_SEEK_APPLICATION_AUDIT_PATH).trim();
  const artifactPath = String($("seekApplicationArtifactPath")?.value || DEFAULT_SEEK_APPLICATION_ARTIFACT_PATH).trim();
  if (!recordPath || !auditPath || !artifactPath) {
    renderResponse({ success: false, message: "application evidence paths are required" }, "SEEK application evidence");
    return null;
  }
  try {
    const [record, audit, artifact] = await Promise.all([
      readArtifactJson(recordPath),
      readArtifactJson(auditPath),
      readArtifactJson(artifactPath),
    ]);
    seekApplicationEvidence = { record, audit, artifact, paths: { record: recordPath, audit: auditPath, artifact: artifactPath } };
    renderSeekApplicationEvidence(seekApplicationEvidence);
    renderResponse({
      success: true,
      message: "SEEK application evidence loaded",
      data: {
        contract_version: "seek_application_evidence_panel_load_v1",
        record_contract: record.contract_version,
        audit_decision: audit.decision,
        artifact_contract: artifact.contract_version,
        job_title: record.job_title || record.job?.title,
        employer_question_count: Number(record.employer_question_total ?? artifact.filled_content_summary?.employer_question_count ?? 0),
        final_submissions: Number(record.final_submissions ?? artifact.safety_policy?.final_submissions ?? 0),
        artifact_is_authorization: artifact.milestone?.artifact_is_authorization !== false,
      },
    }, "SEEK application evidence");
    return seekApplicationEvidence;
  } catch (error) {
    renderSeekApplicationEvidence(null);
    renderResponse({ success: false, message: "SEEK application evidence load failed", error: String(error.message || error) }, "SEEK application evidence");
    return null;
  }
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
    const interfaceMapLoad = await ensureReplayInterfaceMapForRuntimeGraph(replayArtifact, path);
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
        interface_map_path: interfaceMapLoad.path || "",
        interface_map_loaded: interfaceMapLoad.loaded === true,
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

async function ensureReplayInterfaceMapForRuntimeGraph(graph = {}, graphPath = "") {
  const result = { loaded: false, path: replayInterfaceMapPath || "" };
  if (!graph || typeof graph !== "object") return result;
  const inferred = inferInterfaceMapPresetForGraph(graph, graphPath);
  if (!inferred?.mapPath) return result;
  const currentPath = String(replayInterfaceMapPath || "").trim();
  const currentMatches = currentPath && currentPath === inferred.mapPath && replayInterfaceMap;
  if (currentMatches) return { loaded: true, path: currentPath };
  try {
    const interfaceMap = await readArtifactJson(inferred.mapPath);
    replayInterfaceMap = JSON.parse(JSON.stringify(interfaceMap));
    normalizeInterfaceMapReviewPolicies(replayInterfaceMap);
    replayInterfaceMapPath = inferred.mapPath;
    selectedInterfaceMapRef = "";
    if ($("replayInterfaceMapPath")) $("replayInterfaceMapPath").value = inferred.mapPath;
    if ($("replayInterfaceCalibrationPath") && inferred.calibrationPath) {
      $("replayInterfaceCalibrationPath").value = inferred.calibrationPath;
    }
    renderInterfaceMap(replayInterfaceMap, replayInterfaceMapPath);
    return { loaded: true, path: replayInterfaceMapPath };
  } catch (error) {
    console.warn("interface map auto-load failed", error);
    return { loaded: false, path: inferred.mapPath, error: String(error.message || error) };
  }
}

function inferInterfaceMapPresetForGraph(graph = {}, graphPath = "") {
  if (isSeekRuntimePathGraph(graph) || String(graphPath || "").toLowerCase().includes("seek")) {
    return {
      mapPath: DEFAULT_SEEK_INTERFACE_MAP_PATH,
      calibrationPath: DEFAULT_INTERFACE_CALIBRATION_REPORT_PATH,
    };
  }
  return null;
}

async function loadReplayInterfaceMap() {
  const path = String($("replayInterfaceMapPath")?.value || "").trim();
  if (!path) {
    renderResponse({ success: false, message: "interface_map_path is required" }, "Interface map");
    return null;
  }
  try {
    const interfaceMap = await readArtifactJson(path);
    replayInterfaceMap = JSON.parse(JSON.stringify(interfaceMap));
    normalizeInterfaceMapReviewPolicies(replayInterfaceMap);
    replayInterfaceMapPath = path;
    selectedInterfaceMapRef = "";
    renderInterfaceMap(replayInterfaceMap, path);
    if (runtimePathGraphView?.graph) {
      renderRuntimePathGraph(runtimePathGraphView.graph, {
        path: runtimePathGraphView.path,
        mode: runtimePathGraphView.mode,
        currentStateId: runtimePathGraphView.currentStateId,
        currentTransitionId: runtimePathGraphView.currentTransitionId,
        completedTransitionIds: Array.from(runtimePathGraphView.completedTransitionIds || []),
        failedTransitionIds: Array.from(runtimePathGraphView.failedTransitionIds || []),
      });
    }
    renderResponse({
      success: true,
      message: "Interface map loaded",
      data: {
        contract_version: "interface_map_panel_load_v1",
        path,
        map_contract: replayInterfaceMap.contract_version,
        region_count: Array.isArray(replayInterfaceMap.regions) ? replayInterfaceMap.regions.length : 0,
        fixed_visual_asset_count: Array.isArray(replayInterfaceMap.fixed_visual_assets) ? replayInterfaceMap.fixed_visual_assets.length : 0,
        dynamic_area_count: Array.isArray(replayInterfaceMap.dynamic_areas) ? replayInterfaceMap.dynamic_areas.length : 0,
      },
    }, "Interface map");
    return replayInterfaceMap;
  } catch (error) {
    replayInterfaceMap = null;
    replayInterfaceMapPath = path;
    renderInterfaceMap(null, path);
    renderResponse({ success: false, message: "Interface map load failed", error: String(error.message || error) }, "Interface map");
    return null;
  }
}

async function loadReplayInterfaceCalibrationReport() {
  const path = String($("replayInterfaceCalibrationPath")?.value || DEFAULT_INTERFACE_CALIBRATION_REPORT_PATH).trim();
  if (!path) {
    renderResponse({ success: false, message: "interface_calibration_report_path is required" }, "Interface calibration");
    return null;
  }
  try {
    const report = await readArtifactJson(path);
    replayInterfaceCalibrationReport = report && typeof report === "object" ? report : null;
    replayInterfaceCalibrationPath = path;
    if (replayInterfaceMap) {
      renderInterfaceMap(replayInterfaceMap, replayInterfaceMapPath);
    }
    const summary = replayInterfaceCalibrationReport?.summary || {};
    renderResponse({
      success: true,
      message: "Interface calibration loaded",
      data: {
        contract_version: "interface_map_calibration_panel_load_v1",
        path,
        report_contract: replayInterfaceCalibrationReport?.contract_version,
        status: summary.status,
        case_count: summary.case_count ?? replayInterfaceCalibrationReport?.case_count ?? 0,
        matched_count: summary.matched_count ?? 0,
        fast_lane_success_count: summary.fast_lane_success_count ?? 0,
        high_risk_match_count: summary.high_risk_match_count ?? 0,
        final_submit_fast_lane_count: summary.final_submit_fast_lane_count ?? 0,
      },
    }, "Interface calibration");
    return replayInterfaceCalibrationReport;
  } catch (error) {
    replayInterfaceCalibrationReport = null;
    replayInterfaceCalibrationPath = path;
    if (replayInterfaceMap) {
      renderInterfaceMap(replayInterfaceMap, replayInterfaceMapPath);
    }
    renderResponse({ success: false, message: "Interface calibration load failed", error: String(error.message || error) }, "Interface calibration");
    return null;
  }
}

async function saveReplayInterfaceMap() {
  if (!replayInterfaceMap) {
    renderResponse({ success: false, message: "Load an interface map before saving" }, "Interface map");
    return null;
  }
  const fileName = String($("replayInterfaceMapSaveName")?.value || "learned_interface_map_edited.json").trim() || "learned_interface_map_edited.json";
  const payload = JSON.parse(JSON.stringify(replayInterfaceMap));
  normalizeInterfaceMapReviewPolicies(payload);
  payload.editor_policy = payload.editor_policy && typeof payload.editor_policy === "object" ? payload.editor_policy : {};
  payload.editor_policy.manual_edits_write_trace = true;
  payload.editor_policy.artifact_is_authorization = false;
  payload.summary = payload.summary && typeof payload.summary === "object" ? payload.summary : {};
  payload.summary.fixed_visual_asset_count = Array.isArray(payload.fixed_visual_assets) ? payload.fixed_visual_assets.length : 0;
  payload.summary.region_count = Array.isArray(payload.regions) ? payload.regions.length : 0;
  payload.summary.dynamic_area_count = Array.isArray(payload.dynamic_areas) ? payload.dynamic_areas.length : 0;
  payload.summary.danger_zone_count = Array.isArray(payload.danger_zones) ? payload.danger_zones.length : 0;
  if (Array.isArray(payload.fixed_visual_assets)) {
    payload.fixed_visual_assets.forEach((asset) => {
      if (!asset || typeof asset !== "object") return;
      ensureInterfaceAssetReviewPolicy(asset);
    });
  }
  try {
    const response = await api("POST", "/panel/save_interface_map", {
      file_name: fileName,
      source_path: replayInterfaceMapPath,
      payload,
      edit_summary: interfaceMapEditSummary(payload),
    }, { summary: "save interface map" });
    if (response?.data?.path && $("replayInterfaceMapPath")) {
      $("replayInterfaceMapPath").value = response.data.path;
      replayInterfaceMapPath = response.data.path;
    }
    renderResponse(response, "Interface map saved");
    return response;
  } catch (error) {
    renderResponse({ success: false, message: "Interface map save failed", error: String(error.message || error) }, "Interface map saved");
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
  on("replayUseCurrentAppMapBtn", "click", useCurrentAppInterfaceMap);
  on("replayInterfaceMapLoadBtn", "click", loadReplayInterfaceMap);
  on("replayInterfaceCalibrationLoadBtn", "click", loadReplayInterfaceCalibrationReport);
  on("replayInterfaceMapSaveBtn", "click", saveReplayInterfaceMap);
  on("seekApplicationEvidenceLoadBtn", "click", loadSeekApplicationEvidence);
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
  const initialStage = initialStageFromQuery();
  if (initialStage) {
    document.querySelectorAll(".stage").forEach((button) => {
      button.classList.toggle("active", button.dataset.stage === initialStage);
    });
  }
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
  if ($("seekApplicationRecordPath") && !String($("seekApplicationRecordPath").value || "").trim()) {
    $("seekApplicationRecordPath").value = DEFAULT_SEEK_APPLICATION_RECORD_PATH;
  }
  if ($("seekApplicationAuditPath") && !String($("seekApplicationAuditPath").value || "").trim()) {
    $("seekApplicationAuditPath").value = DEFAULT_SEEK_APPLICATION_AUDIT_PATH;
  }
  if ($("seekApplicationArtifactPath") && !String($("seekApplicationArtifactPath").value || "").trim()) {
    $("seekApplicationArtifactPath").value = DEFAULT_SEEK_APPLICATION_ARTIFACT_PATH;
  }
  if ($("replayInterfaceCalibrationPath") && !String($("replayInterfaceCalibrationPath").value || "").trim()) {
    $("replayInterfaceCalibrationPath").value = DEFAULT_INTERFACE_CALIBRATION_REPORT_PATH;
  }
  renderReplayGraph(null, "");
  renderReplayRegressionReport(null, "");
  renderLearnSampleReadinessGate(null, "");
  renderSeekApplicationEvidence(null);
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
  if (!panelQueryFlag("skip_boot_models")) {
    await refreshModels();
  }
}

boot();








