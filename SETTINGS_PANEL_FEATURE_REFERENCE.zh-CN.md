# 旧测试面板功能说明

更新日期：2026-06-02

本文给重构测试面板使用，记录旧 Tkinter 面板每个功能页的作用、对应 API、请求字段来源、返回内容读取方式，以及哪些字段会回填到后续步骤。

旧面板入口：

```text
scripts/settings_panel.py
app/settings_panel/desktop.py
```

配置来源：

```text
configs/settings_panel.json
configs/vision.json
configs/model_profiles/*.json
```

## 1. 总体结构

旧面板是按 agent workflow 分页的桌面测试面板，不是普通设置页。

左侧页面顺序：

```text
Workflow diagram
App Discovery
Open / Bind
Capture
Screen Understanding
Precise Localization
Click Gate
Model Settings
```

底部固定 Response 区：

- 显示最近一次 API JSON。
- 显示响应摘要。
- 根据 response 自动渲染动态 Action Path Graph。
- 支持复制 JSON。
- 支持从最近 response 读取 trace_path 并渲染 overlay。

核心状态变量：

| 变量 | 作用 |
| --- | --- |
| `runtime_base_url_var` | FastAPI runtime 地址，默认 `http://127.0.0.1:8000`。 |
| `app_id_var` | 要打开的 app id，例如 `edge`。 |
| `window_choice_var` | 当前窗口候选下拉框选中项。 |
| `window_title_var` | 绑定窗口标题。 |
| `process_name_var` | 绑定窗口进程名。 |
| `image_path_var` | 当前用于视觉识别的截图路径。 |
| `goal_var` | 精准定位或点击计划目标。 |
| `app_name_var` | 传给 API 的 app name，例如 `browser`。 |
| `state_hint_var` | 当前界面区域提示。 |
| `top_k_var` | 候选数量。 |
| `timeout_var` | 长视觉请求超时秒数。 |
| `box_x/y/w/h_var` | 人工候选框坐标。 |
| `click_x/y_var` | 人工确认点击坐标。 |
| `last_response` | 最近一次 API response。 |
| `last_overlay_path` | 最近一次 overlay 或手动画框图片路径。 |

HTTP 客户端：

- `RuntimeHttpClient.get(path, timeout)`
- `RuntimeHttpClient.post(path, payload, timeout)`
- JSON 用 `ensure_ascii=False` 发送。
- HTTP 错误会转换为 `Runtime API unreachable` 或 `HTTP xxx: body`。

## 2. 通用请求机制

### 2.1 同步请求

函数：

```text
request(method, path, payload, timeout, summary, workflow_step)
```

用途：

- 短请求。
- 不需要后台线程的请求。
- 例如 `/health`、`/apps`、`/session/windows`、`/session/bind_window`、`/state/capture_window`、overlay 渲染。

流程：

```text
mark_workflow(active)
-> RuntimeHttpClient.get/post
-> set_response(response)
-> mark_workflow(done/error)
```

### 2.2 异步请求

函数：

```text
request_async(method, path, payload, timeout, summary, workflow_step)
```

用途：

- 长时间视觉模型请求。
- 避免 Tkinter UI 卡死。
- 例如整屏理解、精准定位、dry-run 点击计划。

流程：

```text
pending_requests 加入 request_key
-> 后台线程调用 API
-> async_results queue
-> root.after 轮询
-> _finish_async_request
-> set_response
-> 自动回填 state_hint 或候选框
```

防重复：

- 同一个 `workflow_step` 已在 `pending_requests` 时，会显示 `request_already_running`，不再发第二个请求。

失败显示：

- 后台异常会被包装成：

```json
{
  "success": false,
  "message": "Request failed",
  "data": {"request": "..."},
  "error": {"code": "request_failed", "details": "..."}
}
```

## 3. Workflow Diagram 页面

构建函数：

```text
_build_workflow_page
draw_workflow
mark_workflow
```

用途：

- 展示 agent 从应用发现到执行验证的流程。
- 每次 API 请求会高亮当前阶段。

节点：

```text
apps
open
capture
observe
decide
locate
gate
execute
```

状态颜色：

- `active`：正在运行。
- `done`：请求成功。
- `error`：请求失败。

重构建议：

- 保留 workflow 状态联动。
- 不一定沿用旧 canvas 画法，但要保留“哪个阶段正在跑/已完成/失败”的反馈。

## 4. App Discovery 页面

构建函数：

```text
_build_apps_page
call_apps_list
```

按钮：

```text
应用发现 GET /apps
```

调用：

```text
GET /apps
```

用途：

- 查看 runtime 已配置哪些 app。
- 查看当前 visible windows。
- 查看 app capabilities。

返回读取：

```python
windows = response["data"]["running_windows"]
```

后续动作：

- 如果 `running_windows` 非空，调用 `set_window_candidates(windows)`。
- 将窗口候选填入 Open / Bind 页面下拉框。

窗口候选字段通常包括：

```text
title
process_name
process_id / pid
handle
```

候选显示格式：

```text
{process_name}#{process_id} | {title} hwnd={handle}
```

## 5. Open / Bind 页面

构建函数：

```text
_build_open_bind_page
call_open_app
call_list_windows
call_bind_window
set_window_candidates
apply_selected_window
```

### 5.1 打开应用

按钮：

```text
打开应用 POST /apps/open
```

请求：

```json
{
  "app_id": "edge",
  "bind_after_open": true
}
```

字段来源：

- `app_id` 来自 `app_id_var`。
- `bind_after_open` 固定为 `true`。

返回读取：

```python
windows = response["data"]["running_windows"]
```

后续动作：

- 如果返回窗口列表，调用 `set_window_candidates`。
- 自动填 `window_title_var` 和 `process_name_var`。

### 5.2 刷新窗口

按钮：

```text
刷新窗口 GET /session/windows
```

调用：

```text
GET /session/windows
```

返回读取：

```python
candidates = response["data"]["candidates"]
```

后续动作：

- 填入窗口下拉框。
- 默认选第一个窗口。
- `apply_selected_window` 会把选中候选的 `title` 和 `process_name` 写入输入框。

自动刷新：

- 页面切到 `open_bind` 时，旧面板会 `root.after(100, auto_refresh_windows)`。
- 只有当前 active page 是 `open_bind` 时才调用刷新窗口。

### 5.3 绑定窗口

按钮：

```text
绑定窗口 POST /session/bind_window
```

请求：

```json
{
  "title": "Microsoft Edge",
  "process_name": "msedge.exe"
}
```

字段来源：

- `title` 来自 `window_title_var`。
- `process_name` 来自 `process_name_var`。
- 空字符串转成 `null`。

作用：

- runtime 后续截图、点击都基于这个 bound window。

## 6. Capture 页面

构建函数：

```text
_build_capture_page
call_capture_window
choose_image
handle_image_drop
ensure_image_path
load_preview
```

### 6.1 截图

按钮：

```text
截图 POST /state/capture_window
```

请求：

```json
{
  "save_image": true,
  "roi": {"x": 0, "y": 0, "width": 100, "height": 100}
}
```

字段来源：

- `save_image` 固定为 `true`。
- `roi` 来自 ROI 输入框。
- ROI 四个输入全空时不传 `roi`。

返回读取：

```python
image_path = response["data"]["image_path"]
```

后续动作：

- 写入 `image_path_var`。
- 调用 `load_preview(image_path)`。

### 6.2 选择/拖拽图片

用途：

- 不走 live capture，直接用已有截图测试视觉识别。

入口：

- `choose_image`：文件选择器。
- `handle_image_drop`：拖拽图片。

允许后缀：

```text
.png
.jpg
.jpeg
.bmp
```

后续动作：

- 写入 `image_path_var`。
- 调用 `load_preview`。
- 拖拽成功时写一个简单 response：

```json
{
  "success": true,
  "message": "Image dropped",
  "data": {"image_path": "..."}
}
```

### 6.3 ensure_image_path

用途：

- 给需要图片的功能兜底。

逻辑：

```text
如果 image_path_var 有值 -> 返回
否则调用 call_capture_window
仍没有 image_path -> 弹 missing_image
```

## 7. Screen Understanding 页面

构建函数：

```text
_build_observe_page
call_observe_screen
populate_observed_state_hint
```

按钮：

```text
整屏理解 POST /vision/observe_screen
```

请求：

```json
{
  "task": "observe_screen",
  "app_name": "browser",
  "state_hint": "top navigation bar",
  "provider_mode": "local_understanding",
  "capture_live": true,
  "image_path": null,
  "metadata": {
    "ocr_anchors": {"enabled": true, "max_anchors": "all", "min_score": 0.0},
    "prompt_overrides": {"additional_rules": "..."},
    "settings_panel": {"language": "zh-CN"}
  }
}
```

字段来源：

- `app_name` 来自 `app_name_var`。
- `state_hint` 来自 `state_hint_var`。
- `provider_mode` 固定 `local_understanding`。
- 如果 `image_path_var` 为空，则 `capture_live=true`。
- 如果 `image_path_var` 有值，则 `capture_live=false` 并传 `image_path`。
- `metadata.prompt_overrides.additional_rules` 来自整屏理解页 prompt 文本框。

异步：

- 使用 `request_async`。
- timeout 使用 `vision_request_timeout()`，来自 `Timeout seconds`。

返回读取：

```python
result = response["data"]["result"]
hint = result["suggested_state_hint"]
```

兜底读取：

```python
nested = result["screen_reading"]
hint = result["state_guess"] or nested["state_guess"] or result["screen_summary"] or nested["screen_summary"]
```

后续动作：

- 如果成功，`populate_observed_state_hint` 自动把 hint 写入 `state_hint_var`。
- 这个值用于精准定位页面的 State hint。

设计目的：

- 小模型做快速整屏理解。
- 给 agent 决策提供可点击控件列表。
- 给下一步精准定位提供状态区域提示。
- 不执行点击。

## 8. Precise Localization 页面

构建函数：

```text
_build_locate_page
call_locate_target
call_analyze_api
populate_first_located_candidate
generate_manual_box
call_render_overlay
```

### 8.1 精准定位

按钮：

```text
精准定位 POST /vision/locate_target
```

请求：

```json
{
  "goal": "点击关闭按钮",
  "task": "click_target",
  "app_name": "browser",
  "state_hint": "title bar",
  "provider_mode": "local_grounding",
  "capture_live": false,
  "image_path": "D:\\...",
  "top_k": 5,
  "metadata": {
    "ocr_anchors": {"enabled": true, "max_anchors": "all", "min_score": 0.0},
    "prompt_overrides": {"additional_rules": "..."},
    "settings_panel": {"language": "zh-CN"}
  }
}
```

字段来源：

- `goal` 来自 `goal_var`。
- `app_name` 来自 `app_name_var`。
- `state_hint` 来自 `state_hint_var`。
- `top_k` 来自 `top_k_var`。
- `provider_mode` 固定 `local_grounding`。
- `capture_live` 逻辑同整屏理解。
- prompt 来自精准定位页 prompt 文本框。

返回读取：

优先读取：

```python
result = response["data"]["result"]
bbox = result["located_bbox"]
point = result["located_point"]
label = result["recommended_target"]["label"]
```

如果没有 `located_bbox`，旧面板会读取 recognition plan 中的候选：

```python
plan = result["recognition_plan"]
candidates = plan["candidate_result"]["candidates"]
if candidates 为空:
    candidates = plan["candidate_result"]["rejected"]
candidate = candidates[0]
element = candidate["element"]
bbox = candidate["refined_bbox"] or element["bbox"]
point = element["click_point"]
label = candidate["label"] or element["label"]
```

后续动作：

- 自动填入候选框：
  - `box_x_var`
  - `box_y_var`
  - `box_w_var`
  - `box_h_var`
  - `box_label_var`
- 自动填入点击坐标：
  - `click_x_var`
  - `click_y_var`
- 记录 `confirmed_point_source_trace_path`，用于人工确认点击时传 `source_trace_path`。

安全含义：

- `located_point` 是“可复核定位点”。
- `selected_click_point` 才是 autonomous gate 放行点。
- 如果 `location_status=requires_pre_click_confirmation`，说明测试面板可以人工确认，但 agent 不应自动点击。

### 8.2 API direct analyze

按钮：

```text
API 直出框 POST /vision/analyze
```

请求：

```json
{
  "image_path": "...",
  "task": "analyze_ui",
  "app_name": "browser",
  "goal": "...",
  "state_hint": "...",
  "provider_mode": "api",
  "metadata": {...}
}
```

用途：

- 调试底层视觉 provider 输出。
- 不应该作为点击路径。

注意：

- 调用前用 `ensure_image_path()` 确保有截图。
- 不自动执行点击。

### 8.3 手动候选框生成

按钮：

```text
生成候选框图
```

函数：

```text
generate_manual_box
```

字段来源：

- `image_path_var`
- `box_x/y/w/h_var`
- `box_label_var`

输出目录：

```text
artifacts/settings-panel/manual-box-YYYYMMDD-HHMMSS.png
```

作用：

- 在当前截图上画一个粉色 bbox 和 label。
- 加载到 preview。
- set_response 返回：

```json
{
  "manual_overlay_path": "...",
  "bbox": {"x": 0, "y": 0, "w": 120, "h": 60}
}
```

### 8.4 渲染识别 overlay

按钮：

```text
渲染 overlay
```

调用：

```text
POST /vision/render_recognition_plan_overlay
```

请求：

```json
{
  "trace_path": "...",
  "include_rejected": true,
  "include_points": true,
  "label_candidates": true,
  "label_reasons": true
}
```

trace_path 读取：

```python
extract_trace_path(last_response)
```

读取顺序：

```python
plan["trace_path"]
or result["recognition_plan_trace_path"]
or result["trace_path"]
```

返回读取：

```python
overlay = response["data"]["result"]["overlay_path"]
```

后续动作：

- 写入 `last_overlay_path`。
- 调用 `load_preview(overlay)`。

## 9. Click Gate 页面

构建函数：

```text
_build_execute_page
call_dry_run_click
call_confirmed_point
call_real_confirmed_point
```

### 9.1 Dry-run 点击计划

按钮：

```text
Dry-run 点击 POST /action/execute_recognition_plan
```

请求：

```json
{
  "goal": "...",
  "task": "click_target",
  "app_name": "browser",
  "state_hint": "...",
  "provider_mode": "local_grounding",
  "capture_live": true,
  "dry_run": true,
  "top_k": 5,
  "metadata": {...}
}
```

字段来源：

- goal/app/state/top_k 同精准定位。
- `capture_live` 固定 `true`。
- `dry_run` 固定 `true`。
- prompt 使用精准定位规则。

用途：

- 这是 agent 正式点击前应该走的闸门路径。
- 成功 dry-run 可能返回 `approved_plan_id`。
- 没有通过 pre-click gate 时不点击。

### 9.2 人工确认坐标 dry-run

按钮：

```text
校验坐标，不点击
```

调用：

```text
POST /action/execute_confirmed_point
```

请求：

```json
{
  "x": 100,
  "y": 200,
  "button": "left",
  "dry_run": true,
  "bbox": {"x": 90, "y": 180, "width": 50, "height": 30},
  "label": "target",
  "source_trace_path": "..."
}
```

字段来源：

- `x/y` 来自 `click_x_var/click_y_var`。
- `bbox` 来自 `box_x/y/w/h_var`。
- `label` 来自 `box_label_var`。
- `source_trace_path` 来自最近定位 response。

用途：

- 人工确认候选点是否格式正确。
- 不发送真实点击。

### 9.3 人工确认真实点击

按钮：

```text
真实点击该坐标
```

流程：

```text
弹确认框
-> 用户确认
-> POST /action/execute_confirmed_point dry_run=false
```

重要边界：

- 这是测试面板的人类复核路径。
- 不应该被上层 agent 当成自主点击路径。
- agent 自主点击应使用 `execute_recognition_plan` + pre-click gate / approved plan。

## 10. Model Settings 页面

构建函数：

```text
_build_models_page
load_model_profiles
apply_model_profile
start_model_server
stop_model_server
test_model_endpoint
write_model_config
_persist_panel_config
```

### 10.1 模型 profile 来源

读取顺序：

1. `configs/model_profiles/*.json`
2. `configs/settings_panel.json` 中 legacy `model_profiles`
3. `configs/vision.json` 中当前配置
4. 扫描 `models/**/*.gguf`

去重逻辑：

- 按 `label` 去重。

当前两个角色：

| stage | provider_mode | 变量 |
| --- | --- | --- |
| observe | `local_understanding` | `small_model_var` / `small_endpoint_var` |
| locate | `local_grounding` | `large_model_var` / `large_endpoint_var` |

### 10.2 应用模型配置

函数：

```text
apply_model_profile(stage)
```

作用：

- 从选中的 profile 读取 `model_name`、`endpoint`。
- 写入 small 或 large model 输入框。
- 调用 `write_model_config` 写入 `configs/vision.json`。
- 调用 `_persist_panel_config` 写入 `configs/settings_panel.json`。

### 10.3 启动本地模型服务

函数：

```text
start_model_server(stage)
```

流程：

```text
selected_model_profile
-> probe_model_endpoint
-> 如果 endpoint 已运行或 loading，不重复启动
-> 检查 start script
-> 写 config
-> powershell -File start script
-> 写 pid file
-> set_response 显示 pid/log/script/profile
```

脚本默认：

```text
scripts/model_servers/start_llama_vision_server.ps1
```

会传入 profile 字段：

```text
model_path
mmproj_path
server_path
port
context_size
gpu_layers
image_min_tokens
```

日志：

```text
logs/local-vision-server-YYYYMMDD-HHMMSS.log
```

PID：

```text
logs/{profile_id}-server.pid
```

### 10.4 停止本地模型服务

函数：

```text
stop_model_server(stage)
```

调用：

```text
powershell -File stop script -Port ... -PidFile ...
```

脚本默认：

```text
scripts/model_servers/stop_local_vision_server.ps1
```

返回显示：

- returncode
- stdout
- stderr

### 10.5 检查模型服务

函数：

```text
test_model_endpoint(stage)
```

调用：

```text
GET {base_url}/models
```

base_url 推导：

- 从 endpoint 去掉 `/chat/completions` 或 `/completions`。
- 默认 `http://127.0.0.1:1234/v1`。

返回读取：

```python
response["data"][0]["id"]
```

或：

```python
response["models"][0]["name" or "model"]
```

特殊状态：

- 如果错误文本包含 `loading model`，显示模型正在加载，不当作普通失败。

### 10.6 保存配置

`configs/vision.json` 写入：

```json
{
  "vision": {
    "mode": "local",
    "timeout_seconds": 600,
    "local_understanding": {"model_name": "...", "endpoint": "..."},
    "local_grounding": {"model_name": "...", "endpoint": "..."},
    "local": {"model_name": "...", "endpoint": "..."},
    "api": {"provider": "...", "model": "...", "endpoint": "..."}
  }
}
```

`configs/settings_panel.json` 写入：

```json
{
  "runtime_base_url": "...",
  "language": "zh-CN",
  "prompt_overrides": {
    "observe_additional_rules": "...",
    "locate_additional_rules": "..."
  },
  "model_scripts": {"start": "...", "stop": "..."},
  "observe_model_profile": "...",
  "locate_model_profile": "..."
}
```

## 11. Response 面板

构建函数：

```text
_build_response_panel
set_response
copy_response
build_runtime_path_graph
extract_trace_path
open_path
```

### 11.1 set_response

每次 API 返回后统一调用：

```text
set_response(response, summary, workflow_step)
```

它会：

- 更新 `last_response`。
- 更新 summary 文本。
- 调用 `update_path_graph(response)`。
- 把 JSON 写入 response text 区。
- 标记 workflow done/error。

### 11.2 Action Path Graph

旧面板不是读取独立图文件，而是从最新 response 确定性抽取节点。

抽取来源：

```text
response.data.result
result.recognition_plan
parse_result.ocr_result
parse_result.screen_reading
candidate_result
narrow_search_result
pre_click_decision
execution_path
timings
trace_path
learned_instruction_artifacts
```

可能节点：

```text
goal
screen
ocr
uia
vision
candidate
narrow
gate
approved
learning
learning_assets
target
click
verify
timings
trace
```

重要读取规则：

- OCR 数量优先读 `parse_result.ocr_result.metadata.match_count`。
- 没有 OCR result 时，从 `screen_reading.texts` 数量兜底。
- pre-click 优先读 `result.pre_click_decision`，否则读 `plan.pre_click_decision`。
- target point 优先级：

```text
result.selected_click_point
or result.located_point
or pre_click.selected_click_point
```

- trace_path 优先级：

```text
result.trace_path
or plan.trace_path
or result.recognition_plan_trace_path
```

### 11.3 Overlay 打开

- `open_overlay` 调用 `open_path(last_overlay_path)`。
- `open_path` 用 `os.startfile` 打开本地文件。

## 12. Prompt 策略

旧面板有两个独立 prompt 文本框：

| 页面 | prompt 来源 |
| --- | --- |
| Screen Understanding | `prompt_texts["observe"]` |
| Precise Localization / Click Gate | `prompt_texts["locate"]` |

metadata 统一生成：

```json
{
  "ocr_anchors": {"enabled": true, "max_anchors": "all", "min_score": 0.0},
  "prompt_overrides": {"additional_rules": "..."},
  "settings_panel": {"language": "zh-CN"}
}
```

整屏理解 prompt 关键规则：

- 简要说明界面目的。
- 返回可操作控件候选。
- 不复述 OCR 坐标。
- 输出可传给精准定位的 `state_guess`。

精准定位 prompt 关键规则：

- 只定位目标，不枚举全屏控件。
- 区分视觉图标和含文字控件。
- 视觉图标最终 bbox 排除文字。
- 含文字控件最终 bbox 包含引用文字。
- 输出 OCR anchor 关系、边界约束、中心/尺寸/排除约束和最终理由。

## 13. 重构时不要漏的行为

1. 长视觉请求必须异步，不能卡 UI。
2. 长视觉请求 timeout 必须读 `Timeout seconds`，不能再写死 300 秒。
3. `observe_screen` 成功后要自动填 `state_hint`。
4. `locate_target` 成功后要自动填候选框和点击坐标。
5. `locate_target` 即使只有 rejected review candidate，也要能填入人工复核框。
6. `selected_click_point` 和 `located_point` 语义不同，不能混成自动点击。
7. `execute_confirmed_point` 是人工复核路径，不是 agent 自主路径。
8. Response 区要保留原始 JSON、trace_path、overlay、path graph。
9. 手动读取中文 trace 时用 UTF-8。
10. 模型服务 `Loading model` 是加载中状态，不应当作普通失败。

