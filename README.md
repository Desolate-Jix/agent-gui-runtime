# agent-gui-runtime

[中文](README.md) | [English](README.en.md)

Windows 本地 GUI 自动化运行时。它不是完整 Agent，而是给上层 Agent 提供稳定的本地 HTTP API，用来发现应用、绑定窗口、截图、OCR/视觉识别、生成点击计划、执行受控点击和验证结果。

核心链路：

```text
Agent -> local HTTP API -> GUI runtime -> bound Windows window
```

## 部署和启动

### 1. 环境要求

- Windows 10 / Windows 11
- Python 3.11
- `uv`
- 本地视觉模型可选；没有模型时仍可打开测试面板和测试基础 API

### 2. 安装依赖

```powershell
uv sync
```

`FastAPI` 和 `uvicorn[standard]` 已写在 `pyproject.toml` 的依赖列表里，执行 `uv sync` 会自动安装，不需要单独 `pip install fastapi`。

可选验证：

```powershell
uv run python -c "import fastapi, uvicorn; print('FastAPI runtime deps ok')"
```

### 3. 一键启动测试面板

双击根目录：

```text
start_test_panel.bat
```

当前默认打开浏览器测试面板：

```text
http://127.0.0.1:8000/panel
```

`start_test_panel.bat` 是纯 `.bat` 启动器，不依赖 `.ps1`。它会：

- 检查 `http://127.0.0.1:8000/health`
- 如果 runtime 不可用，在最小化 `cmd` 窗口中启动 FastAPI runtime
- 等待 runtime 就绪
- 打开浏览器测试面板
- 将 runtime 日志写入 `logs/test-panel-runtime.log`

### 4. 手动启动 runtime

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开接口文档：

```text
http://127.0.0.1:8000/docs
```

浏览器测试面板：

```text
http://127.0.0.1:8000/panel
```

### 5. 启动本地视觉模型

推荐通过测试面板启动：

1. 打开 `整屏理解` 或 `精准定位` 阶段
2. 选择模型 profile
3. 点击 `启动本地视觉模型`
4. 点击 `测试模型 /v1/models`

模型刚启动时，`/v1/models` 可能短暂返回 `Loading model`。测试面板会将其显示为“模型正在加载”而不是服务失败；在此期间调用整屏理解或精准定位，runtime 会等待模型可用后继续当前识别请求。

模型统一放在：

```text
configs/model_profiles/
```

启动脚本统一放在：

```text
scripts/model_servers/
```

当前已有 profile：

- `configs/model_profiles/qwen3_6_iq4_xs.json`
- `configs/model_profiles/qwen3_vl_8b_q4_k_m.json`

手动启动 llama.cpp 视觉模型：

```powershell
.\scripts\model_servers\start_llama_vision_server.ps1
```

停止本地视觉模型：

```powershell
.\scripts\model_servers\stop_local_vision_server.ps1
```

指定其他 GGUF 模型：

```powershell
.\scripts\model_servers\start_llama_vision_server.ps1 `
  -ModelPath .\models\some-model.gguf `
  -MmprojPath .\models\some-mmproj.gguf
```

## 测试面板

测试面板是当前最推荐的调试入口，基于浏览器：

```text
http://127.0.0.1:8000/panel
```

左侧栏按 Agent workflow 排列：

1. 打开/绑定
2. 截图
3. 整屏理解
4. 精准定位
5. 点击闸门
6. 输入
7. Trace 解析
8. 模型测试

主要能力：

- `GET /health` runtime 健康检查
- `GET /runtime/models` 模型状态
- `POST /runtime/prepare` runtime 准备
- `POST /runtime/models/start` / `POST /runtime/models/stop` 模型启动和停止
- `GET /apps` 应用发现
- `POST /apps/open` 打开应用
- `GET /session/windows` 自动读取当前打开窗口
- `POST /session/bind_window` 绑定窗口
- 窗口下拉选择 + 进程名/标题自动填入
- `POST /state/capture_window` 截图
- 拖拽图片作为测试截图
- `POST /vision/observe_screen` 整屏理解
- `POST /vision/locate_target` 精准定位
- 在精准定位阶段手动生成并预览候选框，用于核对模型定位结果
- `POST /action/execute_recognition_plan` dry-run 点击闸门
- `POST /action/execute_confirmed_point` 操作者确认坐标点击
- `POST /action/type_text` 文本输入
- 渲染识别 overlay
- 启动/停止本地视觉模型
- 修改附加视觉提示词
- 导航路径图，记录页面跳转和控件操作历史
- Trace 按阶段解析，点击阶段查看原始 JSON 和图片/坐标 overlay
- 模型直连测试，支持带图片和提示词直接调用视觉模型
- 查看每个阶段的原始 JSON 返回
- 语言切换按钮（中文 / English）

耗时的视觉请求在后台运行，调用整屏理解、精准定位或 dry-run 时测试面板仍可继续响应。整屏理解与精准定位分别保存提示词：整屏理解是快速候选发现阶段，只要求简短界面摘要和可操作控件候选框，不让小模型复述 OCR 坐标或生成详细关系证据；整屏理解现在还要求 `state_guess` 输出可直接传给精准定位 `state_hint` 的短区域提示，并在 `POST /vision/observe_screen` 返回 `suggested_state_hint`。测试面板收到成功的整屏理解结果后会自动把该提示填入精准定位的 State hint 输入框；旧的本地面板配置也会在加载时补上这条提示词规则。精准定位阶段只处理 agent 指定的目标，区分纯图标与含文字控件，并要求输出 OCR anchor 关系、四边约束、中心/尺寸/排除约束以及最终框理由。对不含文字的小图标，满足这些证据的大模型框会作为 `located_bbox` / `located_point` 返回供检查，但不会自动改点相邻 OCR 文字，也不会直接成为可执行坐标。

最新的同图测试中，`Qwen3-VL 8B Q4_K_M` 整屏理解从旧详细输出流程的约 `84.17s` 降至轻量候选流程的约 `16.08s`。新流程单次返回 `10` 个可操作候选和 `2` 个图标候选，没有触发模型重试。

精准定位现在对 `click_target` 使用单目标视觉模板，不再要求大模型枚举整屏控件。2026-05-26 的同图真实测试中，`Qwen3.6 35B A3B IQ4_XS` 对“`搜索游戏` 左侧的放大镜搜索图标”返回 `Search Icon`，`located_bbox={x:635,y:25,w:25,h:30}`，`text_inclusion_policy=exclude_text`，耗时约 `75.59s`；系统没有退回选择旁边的输入文字，且因图标尚无额外执行确认，`selected_click_point=null`。

同日的 QQ “关闭窗口”样例正确识别了语义目标，但在 `806px` 宽推理图上返回了越界横坐标 `965..985`，原结果因此被裁为空框并显示 `not_located`。运行时现在会在裁边前恢复这种 `0..1000` 比例坐标，使关闭按钮成为仍需人工确认的候选。测试面板会把定位返回的首候选自动填入“候选框校验”和“点击闸门”；操作者按下真实点击按钮后，`POST /action/execute_confirmed_point` 才向当前绑定窗口发送该窗口相对坐标。

修复后的同图真实复测在 `69.35s` 内返回 `close_window_button`、`located_bbox={x:797,y:13,w:17,h:26}`、`located_point={x:806,y:26}` 和 `location_status=requires_pre_click_confirmation`；`selected_click_point` 仍为空，因此复测没有触发点击。

2026-05-27 的后续工作压缩了精准定位输入：运行时仍保留全部 OCR 框用于 trace 与后验检查，`click_target` 当前默认按预算选择最多 `48` 个 anchor，使用 `relation_matrix_compact` 矩阵发送每个入选框的文字、坐标和目标匹配标记。矩阵还携带包含/排除关系策略，并要求在存在相关文字行时于 `anchor_relations` 中引用至少一个 anchor：关闭按钮这类纯视觉图标仍可利用附近文字定位边界，但最终 bbox 必须排除文字区域。此前不携带图标周围文字的 `geometry_compact` 试验已被这一契约替代。

最终 no-click 复测向模型发送了 `32` 行矩阵和 `32` 条文字（`prompt_goal_match_count=0`），模型输入为 `2735` tokens，低于当前 `4096` context；请求未 fallback，也未触发点击，返回 `located_bbox={x:783,y:5,w:27,h:27}`、`located_point={x:796,y:18}`。当前 Qwen 输出遵守了 `text_inclusion_policy=exclude_text`，但仍未回填 `anchor_relations`，因此显式关系引用仍作为已知模型限制继续观察。Trace: `logs/traces/vision/20260527-174308-069367__locate-target__browser.json`。

当 OCR 中存在与目标强匹配的文字时，精准定位矩阵现在优先扩展该文字附近的排布证据：默认在总共 `48` 行以内，为强匹配文字最多优先加入 `12` 个同排左右或同列上下邻居，并写入紧凑 `focus_relation_rows=[focus_id,neighbor_id,L|R|A|B,gap_px]`。调用方可通过 `metadata.ocr_anchors.prompt_focus_neighbor_limit` 调整该局部份额；这不会对没有目标文字命中的关闭按钮伪造关系。

在同一张 QQ 截图上用画面内文字 `若只群` 构造精准定位 prompt 时，运行时找到 `2` 个强匹配 anchor，并在仍为 `32` 行的矩阵中优先写入 `9` 条邻域排布关系；与关闭焦点扩展相比，完整文本 prompt 从 `1697` 增到 `1866` tokens，仅增加 `169` tokens。

同目标的实际 `POST /vision/locate_target` no-click 调用在 trace 中记录了 `prompt_goal_match_count=2`、`prompt_focus_relation_count=9`，模型总输入为 `2963` tokens，未触发 OCR fallback 或真实点击。因为画面中 `若只群` 同时出现在标题和会话列表，该运行只验证焦点排布证据成功入模，不证明重复文字目标已唯一消歧。Trace: `logs/traces/vision/20260527-182704-779212__locate-target__browser.json`。

将默认矩阵预算提升到 `48` 后，QQ `关闭窗口` 的真实 no-click 回归记录了 `prompt_anchor_count=48`、`prompt_text_anchor_count=48`，模型输入 `3165` tokens、总处理 `3608` tokens，仍在当前 `4096` context 内且未截断或 fallback；定位结果为 `located_bbox={x:787,y:0,w:21,h:36}`、`located_point={x:798,y:18}`，动作保持未执行。Trace: `logs/traces/vision/20260527-183444-432196__locate-target__browser.json`。

## 模型管理

模型配置现在由 registry 管理：

```text
configs/model_profiles/*.json
```

一个 profile 描述一个模型：

- `profile_id`
- `label`
- `role`
- `provider_mode`
- `input_format`
- `model_name`
- `endpoint`
- `model_path`
- `mmproj_path`
- `server_path`
- `start_script`
- `stop_script`
- `port`
- `context_size`
- `gpu_layers`
- `image_min_tokens`
- `supports_ocr_anchors`
- `best_for`
- `limitations`

运行时当前选择写入：

```text
configs/vision.json
```

当前拆成两个本地视觉角色：

- `vision.local_understanding`：小模型，负责快速整屏理解和候选控件索引
- `vision.local_grounding`：大模型，负责精准定位

测试面板的模型下拉只读取 `configs/model_profiles/`，避免同一个模型从多个来源重复出现。

## Agent 工作流

上层 Agent 应该按 API-first 的流程操作，不直接使用模型返回的原始坐标点击。

推荐顺序：

```text
GET  /apps
POST /runtime/prepare            可选，启动/探活本地视觉模型
POST /apps/open                 可选
GET  /session/windows
POST /session/bind_window
POST /state/capture_window      可选，接口内部也可 live capture
POST /vision/observe_screen
POST /vision/locate_target
POST /action/execute_recognition_plan  dry_run=true
POST /action/execute_recognition_plan  dry_run=false，携带 approved_plan_id
```

关键原则：

- 先用整屏理解得到简短候选列表，再对选中的目标精准定位
- `observe_screen.suggested_state_hint` 是下一次 `locate_target.state_hint` 的默认建议；测试面板会自动填入，agent 仍可按目标覆盖
- 上层 Agent 应保留用户原文用于 trace，但发给视觉模型的 `goal` / `state_hint` / 排除约束建议规范化为英文；例如用户说“点击第一个自然搜索结果”，模型侧可写成 `Click the first organic Google search result title` 和 `main organic search results list below Google navigation tabs`
- OCR anchors 默认参与视觉定位；精准定位保留完整 OCR 结果用于校验，但向模型发送受预算控制的几何投影，只有目标文字高匹配时才附带文字
- `observe_screen` 只用于界面摘要和候选发现，不用于点击或最终坐标证明
- `locate_target` 只返回 no-click 定位结果
- `located_bbox` / `located_point` 是精准视觉模型建议的目标位置；只有 `selected_click_point` 表示已通过点击前闸门的可执行坐标
- 自主 agent 的真正点击只能走 `execute_recognition_plan`
- 测试面板的 `execute_confirmed_point` 仅用于操作者已查看候选框后的显式坐标点击，不是自动执行旁路
- 执行前必须通过 `pre_click_decision_v1`
- 成功 dry-run 会返回 `approved_plan_id`；真实点击应复用这个 ID，runtime 校验同一窗口和已批准点位后直接点击，不再第二次运行大视觉模型
- `learning_mode="instruction"` 是最简指令学习模式：成功真实点击并验证后，runtime 写入 `learned_instruction_v1`。后续调用带 `learned_instruction_id` 时，在验证 goal、窗口句柄、窗口尺寸和点坐标边界一致后复用点击点，仍会执行点击后验证
- 指令学习资产不是普通截图缓存。每条学习指令永久保存在 `artifacts/local-learning/instructions/{id}/` 下，含 `learned_instruction.json`、源窗口截图、点击前截图、点击后截图、diff 图和目标裁剪
- Agent 对外的 runtime、app、vision、识别执行路径现在均包含 `timings`，含 `total_ms` 和 `steps[]`，agent 可据此判断耗时花在模型启动、截图、OCR anchor 准备、视觉推理、排序、点击前闸门、点击派发还是点击后验证

完整 Agent API 调用规范见：

```text
AGENT_API_WORKFLOW.md
```

每个 API 的字段含义、设计目的、返回结构见：

```text
API_FIELD_REFERENCE.zh-CN.md
```

### Text-Card Localization Safety

Text-bearing clickable cards now have a conservative review path. A `card` region is retained only when it declares `include_referenced_text`, a destination, complete edge evidence, and bindable OCR text. Its proposed bbox and point come from matched OCR text rather than a drifting visual card boundary, and it is not an autonomous click approval.

A 2026-05-27 saved Seek localization for Serato showed that a dense page can overflow the anchor-enriched 48-row attempt and use the existing OCR-anchor fallback. Downstream OCR binding still corrected the reviewed candidate to `{x:58,y:649,w:276,h:51}` / `{x:196,y:674}` without clicking.

For list-style text targets, fusion also records an `unreferenced_text_contamination` from OCR text inside the visual bounding box that wasn't explicitly referenced by the vision model. If the model's semantic card bbox contains unreferenced OCR text, the target is forced into confirmation-only review mode while its OCR-derived candidate bbox remains usable for inspection.

## 主要接口

应用和窗口：

- `GET /apps`
- `POST /runtime/prepare`
- `GET /runtime/models`
- `POST /runtime/models/start`
- `POST /runtime/models/stop`
- `POST /apps/open`
- `GET /session/windows`
- `POST /session/bind_window`
- `GET /state`
- `POST /state/capture_window`

`POST /state/capture_window` uses screen-coordinate capture, so it lightly restores the bound window and attempts to bring it to the foreground before grabbing pixels.

视觉：

- `POST /vision/analyze`
- `POST /vision/page_structure`
- `POST /vision/screen_reading`
- `POST /vision/observe_screen`
- `POST /vision/locate_target`
- `POST /vision/recognition_plan`
- `POST /vision/render_recognition_plan_overlay`

动作：

- `POST /action/execute_recognition_plan`
- `POST /action/execute_confirmed_point`（操作者确认坐标点击）
- `POST /action/type_text`
- `POST /action/click_text`
- `POST /action/click_mouse_tester_left_region`

## 识别管线

当前主路径：

```text
screenshot
-> OCR anchors
-> vision_regions_v1 + OCR
-> page_structure_v1
-> screen_reading_v1
-> candidate_rank_v1
-> narrow_search_v1
-> pre_click_decision_v1
-> gated action
```

主要 agent 路径现在会返回 `timings`：其中 `total_ms` 是整次调用耗时，`steps[]` 会拆出模型启动、截图、OCR anchor 准备、视觉推理、候选排序、点击前闸门、真实点击和点击后验证等阶段。它只用于性能诊断和 trace 复盘；是否允许点击仍以 `pre_click_decision_v1` 为准。

重点：

- OCR 文字框会作为空间锚点传给视觉模型；`click_target` 默认发送 `relation_matrix_compact` 文字坐标与包含/排除策略矩阵，并按预算选择 anchor 而非注入整页冗长结构
- 图标和文字的关系会进入 grounding 证据
- 小图标定位优先参考 OCR anchors
- 候选点击点必须经过本地 ranking、narrow search 和 pre-click gate
- overlay 可用于人工复核

## 项目结构

```text
app/
  api/                FastAPI routes
  core/               window, screenshot, OCR, input, verifier
  web_panel/          浏览器测试面板 (HTML/JS/CSS)
  vision/             local/API vision providers and prompting
  page_structure/     page structure and screen reading logic
  models/             request/response schemas
configs/
  app_catalog.json
  settings_panel.json
  vision.json
  model_profiles/     model registry
scripts/
  start_test_panel.bat
  model_servers/      model server start/stop scripts
tests/
artifacts/
logs/
```

详细目录说明见：

```text
PROJECT_STRUCTURE.md
```

## 当前状态

已具备：

- 本地 FastAPI runtime
- Windows 窗口发现和绑定
- 截图和 ROI 截图
- OCR anchors
- local/API 视觉 provider 抽象
- `observe_screen` 整屏理解接口
- `locate_target` 精准定位接口
- no-click recognition plan
- pre-click decision gate
- gated click execution
- recognition overlay
- MouseTester 真实点击基线
- 浏览器测试面板（含 Trace 阶段解析、模型直连测试、导航路径图）
- 指令学习模式（instruction learning），可复用已学习的点击
- 模型 registry 和统一模型启动/停止脚本目录

最新重点模型实验：

- 模型：`Qwen-Qwen3.6-35B-A3B-IQ4_XS.gguf`
- mmproj：`mmproj-Qwen3.6-35B-A3B-Q6_K.gguf`
- 后端：llama.cpp CUDA
- 结论：OCR anchors 对浏览器 Back 这类小图标帮助明显；大图标形状完整性仍需要 crop/ROI 或其他模型继续对比

当前边界：

- 还不是生产级通用桌面 Agent
- 还需要更多页面、更多负例、更多窗口尺寸/DPI/缩放变化测试
- 学习写回还未成为主线能力

## 验证

浏览器面板路由测试、runtime 路由测试和执行识别计划测试：

```powershell
uv run pytest tests/test_web_panel_route.py tests/test_runtime_route.py tests/test_execute_recognition_plan_route.py -q
```

全量测试：

```powershell
uv run pytest -q
```

前端语法检查：

```powershell
node --check app\web_panel\panel.js
```
```

## 重要文档

- `README.en.md`：英文版 README
- `AGENT_API_WORKFLOW.md`：Agent 调用 API 的标准流程
- `API_FIELD_REFERENCE.zh-CN.md`：每个 API 的字段级中文设计参考
- `PROJECT_STRUCTURE.md`：文件结构、配置、产物位置
- `PROJECT_SUMMARY.md`：项目摘要
- `CURRENT_STATE.md`：当前状态
- `NEXT_STEPS.md`：下一步计划
- `ACCURACY_EVALUATION_STANDARD.md`：准确率评估标准
- `RUNTIME_STATE_GRAPH.md` / `RUNTIME_STATE_GRAPH.zh-CN.md`：状态图设计

## 开发规则

本仓库要求代码和文档同步。行为、API、架构、配置、进度或限制发生变化时，需要同步更新相关文档。

实现代码时遵循：

```text
skills/code-implementation-loop/SKILL.md
```

最小闭环：

1. 做最小有意义改动
2. 跑最窄验证
3. 看结果
4. 修失败
5. 重跑直到通过或记录真实 blocker

## 维护备注

- Windows only
- local-only HTTP API
- 单 session / 单绑定窗口优先
- 不允许直接从模型原始 bbox 点击
- 所有真实点击都应走 gated action API
- 历史细节不要继续塞进 README，放到专门文档里

## 浏览器面板状态 (2026-06-02)

`/panel` 是当前唯一保留的本地测试面板入口。旧的 Tkinter 桌面面板代码、启动器、测试和 `tkinterdnd2` 依赖已移除。`start_test_panel.bat` 会在需要时启动 FastAPI runtime，然后打开 `http://127.0.0.1:8000/panel`。

浏览器面板现已使用分段语言切换按钮、按 Trace 分组的顶部流程条、按阶段显示/隐藏卡片的布局、基于 `/panel/inspect_trace` 的 Trace 阶段解析页面，以及通过 `POST /panel/model_test` 直接向视觉模型发送 prompt 和图片的模型测试页面。

### Trace UTF-8 兼容性更新 (2026-06-02)

浏览器面板 `/panel` 返回 `text/html; charset=utf-8`；Trace JSON 读取使用 `utf-8-sig` 兼容带 BOM 的文件。`/panel/inspect_trace` 支持当前 recognition/screen-reading trace，也支持旧版 overlay trace 和 `vision_layer_trace_v1` 层 trace，按阶段输出 `flow_stages` 并提供每阶段原始 JSON 供 Trace Flow UI 点击查看。
