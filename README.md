# agent-gui-runtime

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

### 3. 一键启动测试面板

双击根目录：

```text
start_test_panel.bat
```

它会调用 `scripts/start_test_panel.ps1`：

- 如果 `http://127.0.0.1:8000/health` 不可用，会自动启动 FastAPI runtime
- 然后打开桌面测试面板
- 如果 runtime 是脚本启动的，关闭面板后会自动停止该 runtime

命令行启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_test_panel.ps1
```

只检查启动路径：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_test_panel.ps1 -CheckOnly
```

### 4. 手动启动 runtime

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开接口文档：

```text
http://127.0.0.1:8000/docs
```

手动打开测试面板：

```powershell
uv run python scripts\settings_panel.py
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

测试面板是当前最推荐的调试入口。它不是网页，而是 Tkinter 桌面界面。

左侧栏按 Agent workflow 排列：

1. 流程图
2. 应用发现
3. 打开/绑定
4. 截图阶段
5. 整屏理解
6. 精准定位
7. 点击闸门
8. 模型设置

主要能力：

- `GET /apps` 应用发现
- `POST /apps/open` 打开应用
- `GET /session/windows` 自动读取当前打开窗口
- `POST /session/bind_window` 绑定窗口
- `POST /state/capture_window` 截图
- 拖拽图片作为测试截图
- `POST /vision/observe_screen` 整屏理解
- `POST /vision/locate_target` 精准定位
- 在精准定位阶段手动生成并预览候选框，用于核对模型定位结果
- `POST /action/execute_recognition_plan` dry-run 点击闸门
- 渲染识别 overlay
- 启动/停止本地视觉模型
- 检查模型服务 `/v1/models`（仅确认服务和已加载模型，不执行截图理解；结果会显示在模型卡片状态行和返回内容中）
- 修改附加视觉提示词
- 查看每个阶段的原始 JSON 返回

耗时的视觉请求在后台运行，调用整屏理解、精准定位或 dry-run 时测试面板仍可继续响应。整屏理解与精准定位分别保存提示词：整屏理解是快速候选发现阶段，只要求简短界面摘要和可操作控件候选框，不让小模型复述 OCR 坐标或生成详细关系证据；精准定位阶段只处理 agent 指定的目标，区分纯图标与含文字控件，并要求输出 OCR anchor 关系、四边约束、中心/尺寸/排除约束以及最终框理由。对不含文字的小图标，满足这些证据的大模型框会作为 `located_bbox` / `located_point` 返回供检查，但不会自动改点相邻 OCR 文字，也不会直接成为可执行坐标。

最新的同图测试中，`Qwen3-VL 8B Q4_K_M` 整屏理解从旧详细输出流程的约 `84.17s` 降至轻量候选流程的约 `16.08s`。新流程单次返回 `10` 个可操作候选和 `2` 个图标候选，没有触发模型重试。

精准定位现在对 `click_target` 使用单目标视觉模板，不再要求大模型枚举整屏控件。2026-05-26 的同图真实测试中，`Qwen3.6 35B A3B IQ4_XS` 对“`搜索游戏` 左侧的放大镜搜索图标”返回 `Search Icon`，`located_bbox={x:635,y:25,w:25,h:30}`，`text_inclusion_policy=exclude_text`，耗时约 `75.59s`；系统没有退回选择旁边的输入文字，且因图标尚无额外执行确认，`selected_click_point=null`。

同日的 QQ “关闭窗口”样例正确识别了语义目标，但在 `806px` 宽推理图上返回了越界横坐标 `965..985`，原结果因此被裁为空框并显示 `not_located`。运行时现在会在裁边前恢复这种 `0..1000` 比例坐标，使关闭按钮成为仍需人工确认的候选。测试面板会把定位返回的首候选自动填入“候选框校验”和“点击闸门”；操作者按下真实点击按钮后，`POST /action/execute_confirmed_point` 才向当前绑定窗口发送该窗口相对坐标。

修复后的同图真实复测在 `69.35s` 内返回 `close_window_button`、`located_bbox={x:797,y:13,w:17,h:26}`、`located_point={x:806,y:26}` 和 `location_status=requires_pre_click_confirmation`；`selected_click_point` 仍为空，因此复测没有触发点击。

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
POST /apps/open                 可选
GET  /session/windows
POST /session/bind_window
POST /state/capture_window      可选，接口内部也可 live capture
POST /vision/observe_screen
POST /vision/locate_target
POST /action/execute_recognition_plan  dry_run=true
POST /action/execute_recognition_plan  dry_run=false，仅在 pre_click_decision 允许时
```

关键原则：

- 先用整屏理解得到简短候选列表，再对选中的目标精准定位
- OCR anchors 默认参与视觉定位；整屏理解中它们只作为输入参考，不由模型重复输出
- `observe_screen` 只用于界面摘要和候选发现，不用于点击或最终坐标证明
- `locate_target` 只返回 no-click 定位结果
- `located_bbox` / `located_point` 是精准视觉模型建议的目标位置；只有 `selected_click_point` 表示已通过点击前闸门的可执行坐标
- 自主 agent 的真正点击只能走 `execute_recognition_plan`
- 测试面板的 `execute_confirmed_point` 仅用于操作者已查看候选框后的显式坐标点击，不是自动执行旁路
- 执行前必须通过 `pre_click_decision_v1`

完整 Agent API 调用规范见：

```text
AGENT_API_WORKFLOW.md
```

## 主要接口

应用和窗口：

- `GET /apps`
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
- `POST /action/execute_confirmed_point` (operator-reviewed coordinate click from the desktop panel)
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

重点：

- OCR 文字框会作为空间锚点传给视觉模型
- 图标和文字的关系会进入 grounding 证据
- 小图标定位优先参考 OCR anchors
- 候选点击点必须经过本地 ranking、narrow search 和 pre-click gate
- overlay 可用于人工复核

## 项目结构

```text
app/
  api/                FastAPI routes
  core/               window, screenshot, OCR, input, verifier
  settings_panel/     Tkinter desktop test panel
  vision/             local/API vision providers and prompting
  page_structure/     page structure and screen reading logic
  models/             request/response schemas
configs/
  app_catalog.json
  settings_panel.json
  vision.json
  model_profiles/     model registry
scripts/
  start_test_panel.ps1
  settings_panel.py
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
- 桌面测试面板
- 模型 registry 和统一模型启动脚本目录

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

最近针对测试面板、模型 registry、应用发现、视觉定位 wrapper 的检查：

```powershell
uv run pytest tests/test_settings_panel_modules.py tests/test_apps_route.py tests/test_vision_observe_locate.py tests/test_vision_normalizer.py
```

当前结果：

```text
14 passed
```

PowerShell 模型脚本也做过语法解析检查。

## 重要文档

- `AGENT_API_WORKFLOW.md`：Agent 调用 API 的标准流程
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
