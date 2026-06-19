# API 字段设计参考

本文档解释每个 HTTP API 的设计目的、请求字段、返回字段以及使用边界。  
它和 `AGENT_API_WORKFLOW.md` 的分工不同：

- `AGENT_API_WORKFLOW.md`：说明上层 Agent 应该按什么顺序调用 API。
- `API_FIELD_REFERENCE.zh-CN.md`：说明每个 API 里每个字段是干什么的、为什么存在、应该返回什么。

核心原则：上层 Agent 不应该直接拿视觉模型原始坐标点击。所有真实点击都必须经过 runtime 的候选排序、点击前闸门和动作接口。

## 通用返回 Envelope

所有接口都返回同一个外壳：

```json
{
  "success": true,
  "message": "...",
  "data": {},
  "error": null
}
```

字段说明：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `success` | boolean | 本次 API 调用是否成功。注意：动作类接口中，`success=false` 可能表示安全闸门拒绝点击，而不是服务崩溃。 |
| `message` | string | 给人看的简短状态说明。Agent 不应只靠它做决策。 |
| `data` | object/null | 成功结果或失败时的辅助信息。不同接口的核心 payload 都在这里。 |
| `error` | object/null | 失败时的结构化错误。成功时为 `null`。 |
| `error.code` | string | 机器可读错误码，例如 `image_not_found`、`pre_click_rejected`。Agent 应优先读这个。 |
| `error.details` | any | 错误细节，可能是字符串、对象或列表。 |

## 通用字段

这些字段会在多个接口中重复出现。

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 当前 payload 的契约版本。用于判断返回结构是否符合预期。 |
| `trace_path` | string | 本次调用写出的 trace 文件路径。用于复盘模型输入、OCR、候选、点击闸门和错误。 |
| `execution_path` | object | 标记本次请求实际经过了哪些层，例如视觉模型、OCR、page structure、candidate rank、pre-click decision。 |
| `image_path` | string | 截图文件路径。视觉接口会读取它；live capture 接口会返回它。 |
| `app_name` | string/null | 调用方提供的应用上下文，例如 `browser`、`seek`、`qq`。用于 trace 命名、提示词上下文和部分验证逻辑。 |
| `goal` | string/null | 用户真正想完成的目标，例如 `打开serato的职业界面`、`关闭窗口`。精准定位和执行接口必须有明确 goal。 |
| `task` | string | 视觉任务类型。常见值：`observe_screen`、`click_target`、`analyze_ui`。 |
| `state_hint` | string/null | 当前界面区域或状态提示，例如 `top navigation bar`、`job results list`。它不是目标，只是帮模型缩小语境。 |
| `provider_mode` | string/null | 选择视觉 provider/profile。常见值：`local_understanding` 用于整屏理解，`local_grounding` 用于精准定位。 |
| `metadata` | object | 扩展选项。用于传 prompt override、OCR anchor 预算、调试参数等。 |
| `top_k` | integer | 返回或排序的候选数量上限。默认通常是 `5`。 |
| `capture_live` | boolean | 是否从当前绑定窗口实时截图。为 `false` 时通常需要提供 `image_path`。 |
| `live_capture` | object/null | live capture 产生的截图信息。用于证明识别基于当前绑定窗口，而不是旧图片。 |

模型输入语言建议：

- `goal_original`：保留用户原文，放在 `metadata` 里用于 trace 和审计。
- `goal` / `metadata.goal_model`：建议由上层 Agent 转成简洁英文后再发给视觉模型。
- `state_hint` / `metadata.state_hint_model`：建议使用英文空间区域约束，例如 `main organic search results list below Google navigation tabs`。
- `metadata.negative_constraints`：建议用英文列出排除项，例如 `exclude search box`、`exclude AI Overview`、`exclude ads`。
- 不要把最醒目的排除词放成主目标。比如目标是“第一条自然结果”时，`goal` 不应以 `AI Overview` 为最清晰的词。

## 坐标字段约定

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `x`, `y` | integer | 相对当前截图或绑定窗口左上角的坐标。 |
| `width`, `height` | integer | 矩形宽高。请求里的 ROI 使用这两个字段。 |
| `w`, `h` | integer | OCR/page structure 中常见的紧凑宽高字段。 |
| `left`, `top`, `right`, `bottom` | integer | Windows 窗口矩形的屏幕坐标。 |
| `bbox` | object | 候选框，通常形如 `{x,y,w,h}` 或 `{x,y,width,height}`，具体看接口说明。 |
| `located_point` | object/null | 精准定位模型建议的点，不能直接点击。 |
| `selected_click_point` | object/null | 已通过点击前闸门的可执行点。只有它代表可自动执行坐标。 |

## 通用耗时字段 `timings`

部分 agent 主路径接口会在 `data` 或 `data.result` 中返回 `timings`，并把同一份数据写入 trace。它用于复盘“慢在哪里”，不用于判断能不能点击。

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `runtime_timing_v1`。 |
| `total_ms` | number | 本次 API 从入口到返回前的总耗时，单位毫秒。 |
| `started_at` / `ended_at` | string | 本次 API 计时开始和结束时间。 |
| `steps` | array | 分段耗时列表。 |

`timings.steps[]` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `name` | string | 阶段名，例如 `resolve_image_source`、`vision_provider_analyze`、`rank_candidates`、`pre_click_decision`、`click_point`。 |
| `elapsed_ms` | number | 该阶段耗时，单位毫秒。 |
| `started_at` / `ended_at` | string | 该阶段开始和结束时间。 |
| 其他字段 | any | 阶段上下文，例如 `stage`、`attempt`、`candidate_count`、`provider_mode`。 |

读取建议：
- `total_ms` 用来判断整次调用是否超时或变慢。
- `steps` 用来定位慢在模型启动、截图、OCR anchor 准备、视觉推理、候选排序、点击前闸门、真实点击还是点击后验证。
- `timings` 只是性能诊断证据；是否允许真实点击仍然只看 `pre_click_decision_v1` 和动作接口返回。

## GET /health

设计目的：检查 runtime 是否启动，不涉及窗口、视觉模型或点击。

请求：无。

返回 `data` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `status` | string | 健康状态，正常为 `ok`。 |
| `service` | string | 服务名，正常为 `agent-gui-runtime`。 |

使用注意：只能证明 FastAPI 服务可用，不能证明本地视觉模型、窗口绑定或 OCR 可用。

## POST /execute/available_actions

设计目的：在已有 `runtime_path_graph_v1` 时，根据当前页面证据生成给上层 agent 选择的单步动作菜单。这个接口不点击、不滚动、不调用模型，只输出 `available_actions_response_v1` 和 trace。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `contract_version` | string | `available_actions_request_v1` | 请求合同版本。 |
| `runtime_graph_path` | string/null | null | 要加载的 `runtime_path_graph_v1` 文件路径。和 `runtime_path_graph` 二选一。 |
| `runtime_path_graph` | object | `{}` | 直接内联传入的 runtime graph。 |
| `capture_live` | boolean | false | 当前 slice 只记录请求意图，尚未在此接口内执行真实 Observe。 |
| `current_state_id` | string/null | null | 调用方已知的当前状态；为空时 resolver 会按可见 action 粗略推断。 |
| `screen_inventory` | object | `{}` | 当前页面可操作元素/文本/卡片证据，用于状态匹配和安全拒绝。 |
| `scroll_containers` | object/array/null | null | 当前页面滚动容器证据。 |
| `task_context` | object | `{}` | 上层 agent 的任务上下文，例如 visited entity、no-apply 模式。 |
| `safety` | object | forbid final submit / 不允许 apply / 不允许 safe fill | 安全策略。当前默认不暴露 guarded Apply。 |

返回 `data` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `available_actions_response_v1`。 |
| `path_graph_resolution` | object | `path_graph_resolution_v1`，说明 graph 是否匹配当前状态、证据和拒绝原因。 |
| `available_actions` | object | `available_actions_v1`，给 agent 选择的单步 action 列表。 |
| `trace_path` | string | 写入 `logs/traces/execute/...available-actions...json` 的 trace。 |

使用注意：`available_actions_v1.artifact_is_authorization=false`。动作菜单只是 guidance，不授权点击。

## POST /execute/step

设计目的：把 agent 选择的一个 `available_actions_v1` 动作转换成一次低层 click/scroll 请求计划，并写出 `execute_step_response_v1` trace。这个接口是单步，不负责编排多步 traversal。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `contract_version` | string | `execute_step_request_v1` | 请求合同版本。 |
| `runtime_graph_path` | string/null | null | 要加载的 `runtime_path_graph_v1` 文件路径。和 `runtime_path_graph` 二选一。 |
| `runtime_path_graph` | object | `{}` | 直接内联传入的 runtime graph。 |
| `available_actions_trace_path` | string/null | null | 上一步 `/execute/available_actions` 的 trace，便于串联审计。 |
| `path_graph_resolution` | object | `{}` | 上一步的 `path_graph_resolution_v1`。 |
| `selected_action` | object | `{}` | agent 从 `available_actions.actions[]` 中选中的一个动作。 |
| `safety` | object | forbid final submit / 不允许 apply / 不允许 safe fill | 本步安全策略。 |
| `dry_run` | boolean | true | 是否让低层 action 只做预览/验证，不真实执行。 |
| `dispatch_low_level` | boolean | false | 为 true 时，`/execute/step` 会把本步生成的一个低层请求调度到现有 gated `/action/scroll` 或 `/action/execute_recognition_plan`。 |

返回 `data` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `execute_step_response_v1`。 |
| `action_template_id` | string | 例如 `open_job_card`、`read_detail`、`load_more_results`。 |
| `low_level_action_type` | string | `click`、`scroll` 或 `unsupported`。 |
| `path_graph_action_context` | object | `path_graph_action_context_v1`，写明 graph、state、action、skill、container、verification 和 safety 引用。 |
| `low_level_request` | object/null | 交给 `/action/execute_recognition_plan` 或 `/action/scroll` 的请求计划。 |
| `dispatch_low_level_requested` | boolean | 调用方是否要求本接口调度低层 action。 |
| `dispatch_low_level_executed` | boolean | 是否已经调度低层 action。 |
| `low_level_response` | object/null | 低层 action 的完整 APIResponse，包含其自身 trace/result/error。 |
| `low_level_trace_path` | string/null | 低层 action 写出的 trace 路径。 |
| `execute_step_trace_path` | string | 写入 `logs/traces/execute/...execute-step...json` 的 trace。 |

使用注意：`/execute/step` 不允许从 graph 直接点击。即使 `dispatch_low_level=true`，真实点击仍走 `/action/execute_recognition_plan` 并通过 `pre_click_decision_v1`；真实滚动仍走 `/action/scroll` 并通过 `scroll_precondition_decision_v1`。路径图只提供 guidance 和 trace 上下文，不能单独授权动作。

## POST /runtime/prepare

设计目的：给上层 Agent 一个“执行前准备”入口。调用它可以确认 runtime 本身可用，并按阶段检查/启动本地视觉模型服务。它不绑定窗口、不截图、不点击。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `start_models` | boolean | true | 是否自动启动不可达的模型服务。为 false 时只做状态检查。 |
| `stages` | array | `["observe","locate"]` | 要检查的阶段。`observe` 默认对应整屏理解小模型，`locate` 默认对应精准定位大模型。 |
| `wait_until_ready` | boolean | false | 启动模型后是否等待 `/v1/models` 变为可用。 |
| `wait_seconds` | number | 0 | 最大等待秒数，范围 `0..180`。 |

返回 `data` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `runtime_prepare_v1`。 |
| `runtime` | object | runtime 自身健康状态。 |
| `start_models` | boolean | 本次是否尝试自动启动模型。 |
| `stages` | array | 每个阶段的 profile、启动前状态、是否启动、启动进程和可选等待结果。 |
| `trace_path` | string | 准备过程 trace。 |

## GET /runtime/models

设计目的：列出本地模型 profile，并探测每个 profile 的 `/v1/models` 当前状态。

返回字段：`data.models[]` 中包含 `profile` 和 `status`。`status.status` 常见值为 `running`、`loading`、`unreachable`。

## POST /runtime/models/start

设计目的：按单个阶段或 profile 启动本地视觉模型服务。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `stage` | string | `locate` | 要启动的阶段，例如 `observe` 或 `locate`。 |
| `profile_id` | string/null | null | 明确指定模型 profile；为空时由 stage 映射。 |
| `wait_until_ready` | boolean | false | 是否等待模型可用。 |
| `wait_seconds` | number | 0 | 最大等待秒数，范围 `0..180`。 |

返回字段：与 `/runtime/prepare` 的单个 stage 结果相同。

## GET /apps

设计目的：给 Agent 一个启动入口，让它知道哪些应用可以打开、当前有哪些可见窗口、是否已经绑定窗口。

返回 `data` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `app_discovery_v1`。 |
| `catalog` | object | 可启动应用目录。 |
| `catalog.contract_version` | string | 应用目录契约，当前为 `app_catalog_v1`。 |
| `catalog.apps` | array | 可启动应用列表，来自 `configs/app_catalog.json` 或默认目录。 |
| `catalog.apps[].app_id` | string | 应用 id，例如 `edge`、`notepad`。 |
| `catalog.apps[].name` | string | 人类可读应用名。 |
| `catalog.apps[].description` | string | 应用用途说明。 |
| `catalog.apps[].launch_command` | array | 启动命令，例如 `["msedge.exe"]`。 |
| `catalog.apps[].executable_candidates` | array | 当 `launch_command[0]` 不在 PATH 时的候选可执行文件路径。 |
| `catalog.apps[].process_name` | string | 绑定窗口时优先匹配的进程名。 |
| `catalog.apps[].title_hint` | string | 绑定窗口时优先匹配的标题片段。 |
| `catalog.apps[].capabilities` | array | 应用能力标签，例如 `web_navigation`、`text_editing`。 |
| `running_windows` | array | 当前可见窗口列表。结构同 `GET /session/windows`。 |
| `bound_window` | object/null | 当前已绑定窗口；没有绑定时为 `null`。 |
| `window_status` | string | 窗口枚举状态，通常为 `ok`，失败时为 `unavailable`。 |
| `window_error` | string | 窗口枚举失败原因，仅失败时出现。 |
| `agent_next_steps` | array | 建议 Agent 下一步动作。 |

使用注意：这个接口只发现应用和窗口，不打开、不截图、不识别、不点击。

## POST /apps/open

设计目的：按应用目录或显式命令打开应用，并可选择自动绑定匹配窗口。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `app_id` | string/null | null | 从 app catalog 里选择应用。 |
| `command` | array/null | null | 显式启动命令。没有 `app_id` 时可用。 |
| `url` | string/null | null | 可选 URL。用于浏览器时会追加到启动命令末尾，例如直接打开 Google 搜索页。 |
| `process_name` | string/null | null | 覆盖目录里的进程名，用于启动后绑定。 |
| `title` | string/null | null | 覆盖目录里的标题提示，用于启动后绑定。 |
| `bind_after_open` | boolean | true | 启动后是否尝试自动绑定窗口。 |
| `wait_seconds` | number | 1.5 | 启动后等待窗口出现的秒数，范围 `0..10`。 |

返回 `data` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `app_open_result_v1`。 |
| `app` | object | 实际解析到的 app 配置。 |
| `command` | array | 实际执行的启动命令。 |
| `process_id` | integer | 新启动进程的 PID。 |
| `bind_after_open` | boolean | 本次是否尝试自动绑定。 |
| `bound_window` | object/null | 自动绑定成功时的窗口信息。 |
| `bind_error` | string/null | 自动绑定失败原因。启动成功但绑定失败时可能有值。 |
| `running_windows` | array | 启动后看到的可见窗口列表。 |
| `trace_path` | string | 打开应用 trace。 |

使用注意：启动成功不等于窗口已绑定。继续视觉流程前应确认 `bound_window` 或调用 `POST /session/bind_window`。

## GET /session/windows

设计目的：列出当前所有可见顶层窗口，供用户或 Agent 选择绑定目标。

返回 `data.candidates[]` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `handle` | integer | Windows 窗口句柄。 |
| `title` | string | 窗口标题。 |
| `process_id` | integer | 窗口所属进程 PID。 |
| `process_name` | string | 窗口所属进程名。 |
| `rect` | object | 窗口屏幕矩形。 |
| `rect.left/top/right/bottom` | integer | 屏幕坐标中的窗口边界。 |

使用注意：如果多个窗口都像目标，应让用户确认，不要靠列表顺序猜。

## POST /session/bind_window

设计目的：把 runtime 绑定到一个真实窗口。后续截图、live capture、点击都以这个窗口为对象。

请求字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `process_name` | string/null | 按进程名筛选，例如 `msedge.exe`。 |
| `title` | string/null | 按窗口标题片段筛选，例如 `SEEK`。 |

返回 `data` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `bound` | boolean | 是否已绑定。成功时为 `true`。 |
| `handle` | integer | 绑定窗口句柄。 |
| `window_title` | string | 绑定窗口标题。 |
| `process_id` | integer | 绑定窗口进程 PID。 |
| `process_name` | string | 绑定窗口进程名。 |
| `rect` | object | 绑定窗口屏幕矩形。 |
| `is_active` | boolean | 调用时窗口是否处于活动状态。 |
| `candidates` | array | 调用时的可见窗口列表，用于失败或复核。 |

使用注意：`title` 和 `process_name` 可以只传一个，但越具体越安全。

## GET /state

设计目的：读取当前 runtime 绑定状态，不截图、不识别。

返回 `data` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `bound` | boolean | 是否已有绑定窗口。 |
| `handle` | integer/null | 已绑定窗口句柄。 |
| `window_title` | string/null | 已绑定窗口标题。 |
| `process_id` | integer/null | 已绑定窗口 PID。 |
| `process_name` | string/null | 已绑定窗口进程名。 |
| `rect` | object/null | 已绑定窗口矩形。 |
| `is_active` | boolean | 已绑定窗口是否活动。 |
| `scene_name` | string/null | 预留场景名，目前通常为 `null`。 |

使用注意：这是状态查询，不保证窗口内容已经是 Agent 想操作的页面。

## POST /state/capture_window

设计目的：保存当前绑定窗口截图，作为视觉识别、人工复核或 trace 的输入。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `roi` | object/null | null | 可选截图区域，坐标相对绑定窗口左上角。 |
| `roi.x` | integer | 必填 | ROI 左上角 x。 |
| `roi.y` | integer | 必填 | ROI 左上角 y。 |
| `roi.width` | integer | 必填 | ROI 宽度。 |
| `roi.height` | integer | 必填 | ROI 高度。 |
| `save_image` | boolean | true | 是否保存截图文件。 |

返回 `data` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `image_path` | string/null | 保存的截图路径。 |
| `image_width` | integer | 输出截图宽度。 |
| `image_height` | integer | 输出截图高度。 |
| `roi` | object/null | 实际使用的 ROI。 |
| `roi_adjusted` | boolean | ROI 是否被修正到窗口范围内。 |
| `window_size` | object/null | 绑定窗口宽高。 |

使用注意：如果后续要手动测试视觉接口，可把 `image_path` 传给 `/vision/*`。

## POST /vision/ocr_region

设计目的：对当前绑定窗口的某个 ROI 做 OCR，用于调试文字识别和坐标。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `roi` | object | 必填 | OCR 区域，坐标相对绑定窗口。 |
| `save_image` | boolean | true | 当前实现会保存 ROI 截图供 OCR 和 trace 使用。 |
| `debug` | boolean | false | 调试开关，当前主要保留为扩展字段。 |

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `execution_path` | object | 标记未使用视觉模型，坐标来源为 OCR bbox。 |
| `ocr_result` | object | OCR 结果。 |
| `ocr_result.matches[]` | array | 识别出的文字框。 |
| `matches[].text` | string | OCR 文本。 |
| `matches[].score` | number | OCR 置信度。 |
| `matches[].bbox` | object | 文本框坐标。 |
| `metadata` | object | OCR 引擎、ROI、窗口尺寸等辅助信息。 |
| `trace_path` | string | OCR trace。 |

使用注意：这是 OCR 调试接口，不产生点击计划。

## POST /vision/analyze

设计目的：直接调用视觉 provider，得到标准化 `vision_regions_v1`。这是底层分析接口，适合调试模型输出。

请求字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `image_path` | string | 要分析的截图路径。 |
| `task` | string | 任务名，默认 `analyze_ui`。 |
| `app_name` | string/null | 应用上下文。 |
| `goal` | string/null | 目标，普通分析可为空。 |
| `state_hint` | string/null | 界面状态提示。 |
| `provider_mode` | string/null | 视觉 provider 模式。 |
| `metadata` | object | prompt override、OCR refine 等扩展。 |

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 通常为 `vision_regions_v1`。 |
| `provider` | string | 实际视觉 provider。 |
| `image_size` | object | 图像尺寸。 |
| `screen_summary` | string | 模型给出的界面摘要。 |
| `state_guess` | string | 模型给出的状态/区域猜测。 |
| `regions` | array | 视觉模型识别出的区域。 |
| `targets` | array | 预留目标列表。 |
| `observers` | array | 预留观察列表。 |
| `notes` | array | 标准化或 provider 备注。 |
| `artifacts` | object | 裁剪图等调试产物。 |
| `ocr_result` | object | 如果启用了 OCR refine，包含 OCR 结果。 |
| `execution_path` | object | 标记 provider、是否 OCR refine、是否 page structure。 |
| `trace_path` | string | 视觉分析 trace。 |

使用注意：不要从 `/vision/analyze` 的原始 `regions` 直接点击。

## POST /vision/page_structure

设计目的：把视觉区域和 OCR 文本融合成 `page_structure_v1`，用于后续 screen reading 和候选排序。

请求字段：同 `/vision/analyze`。

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `page_structure_v1`。 |
| `image_size` | object | 图像尺寸。 |
| `screen_summary` | string | 界面摘要。 |
| `state_guess` | string | 状态/区域猜测。 |
| `regions` | array | 标准化视觉区域。 |
| `elements` | array | 融合后的页面元素。 |
| `texts` | array | OCR 文本列表。 |
| `links` | array | 视觉区域、元素和 OCR 文本之间的关系。 |
| `execution_path` | object | provider、OCR、page structure 使用情况。 |
| `trace_path` | string | page structure trace。 |

使用注意：这是结构层，不直接执行动作。

## POST /vision/screen_reading

设计目的：生成面向 Agent 读取的 UI 描述层 `screen_reading_v1`，融合视觉、OCR、page structure、Windows UIA 和图标候选。

请求字段：同 `/vision/analyze`。

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `screen_reading_v1`。 |
| `image_path` | string | 分析的图片。 |
| `app_name` | string/null | 应用上下文。 |
| `image_size` | object | 图像尺寸。 |
| `screen_summary` | string | 屏幕摘要。 |
| `state_guess` | string | 屏幕状态/区域猜测。 |
| `texts` | array | OCR 文本。 |
| `ui.elements` | array | 可读 UI 元素。 |
| `ui.modules` | array | 模块分组。 |
| `ui.icon_candidates` | array | 图标候选。 |
| `ui.provider_slots` | object | UIA、browser accessibility、icon library、learned memory 等 provider 槽位状态。 |
| `relationships` | array | 文本、元素、区域之间的关系。 |
| `execution_relevance` | object | 哪些候选可能安全、危险或未知。 |
| `source_layers` | object | 每个来源层的统计和状态。 |
| `execution_path` | object | 构建路径。 |
| `trace_path` | string | screen reading trace。 |

使用注意：它帮助 Agent 理解页面，但仍不代表可点击坐标。

## POST /vision/observe_screen

设计目的：整屏理解入口。它可以实时截图或读取图片，用小模型快速理解当前界面，并给下一步精准定位提供 `suggested_state_hint`。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `task` | string | `observe_screen` | 任务名。 |
| `app_name` | string/null | null | 应用上下文。 |
| `state_hint` | string/null | null | 调用方已有的状态提示。 |
| `provider_mode` | string/null | null | 推荐传 `local_understanding`。 |
| `metadata` | object | `{}` | prompt override、OCR anchor、Learn Deep 模型审查等扩展。`learn_deep_model_review=false` 可禁用第二阶段模型审查；也可传 `{enabled, provider_mode, max_candidates, max_texts, max_output_tokens}`。 |
| `capture_live` | boolean | true | 是否从绑定窗口实时截图。 |
| `image_path` | string/null | null | `capture_live=false` 时使用的截图路径。 |

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `screen_observation_v1`。 |
| `screen_reading` | object | 读取层结果，结构同 `/vision/screen_reading`。 |
| `screen_map` | object | `screen_map_v1` 页面/动作地图，含 `state_id`、状态摘要、页面分区 `sections`、候选控件、风险等级、预期效果和观察阶段 bbox/point 提示。测试面板导航路径图会消费它。 |
| `live_capture` | object/null | 实时截图信息。 |
| `suggested_state_hint` | string | 从模型 `state_guess` 压缩出的下一步定位提示。面板会自动填入精准定位 State hint。 |
| `agent_next_steps` | array | 建议下一步：选择具体目标、调用 `/vision/locate_target`、不要直接点击。 |
| `execution_path` | object | 是否使用视觉模型、page structure、screen reading。 |
| `degraded_reason` | object/null | 当本地视觉模型返回非法 JSON 或 `screen_reading` 失败时出现。Observe 会用 OCR/UIA 降级生成 `screen_map_v1`，并把原始失败原因写在这里。 |
| `trace_path` | string | observe trace。 |

使用注意：

- `suggested_state_hint` 不是最终目标，只是下一步 `locate_target.state_hint` 的默认建议。
- `screen_map` 用于把整屏理解整理成路径图入口；其中 bbox/click_point 只是观察证据，不能作为真实点击坐标。
- `screen_map.sections[]` 区分页面区域，例如 browser chrome、顶部导航、推广条、正文、下方内容和浮层；`screen_map.candidates[].section_id` 指向所属区域。
- 当视觉模型只返回顶部导航控件时，runtime 会从高置信 OCR 正文文本补充 `ocr_text_actions` 候选，例如卡片标题、开始按钮和鼠标按键文本，供后续 Locate 精准验证。
- 顶部导航区的有效 OCR 文字会被提升为 `nav_text_action`，用于补齐模型漏掉的导航按钮。
- 正文、推广区和下方内容中的相关标题/说明文字会被聚合为 `source="ocr_card_groups"` 的 `content_card`，bbox 覆盖整张卡片而不是只覆盖标题文字。
- `learn_depth="deep"` 时，runtime 会先做确定性 PathGraph 审查，再默认调用第二阶段本地模型做语义 review。模型输出的 `learn_deep_model_review_v1` 会写入 `path_graph_deep_review.model_review`，并保守合并 add/remove/update 到 `path_graph_delta_v1`；模型失败会回退到确定性结果。
- 如果本地视觉模型返回非法 JSON 导致 `screen_reading` 失败，Observe 不再直接失败；它会降级为 OCR/UIA-only 观察，返回 `success=true`、`status="degraded"`、`degraded_reason` 和一份可阅读的 `screen_map_v1`。这些候选仍然只是观察证据，执行前必须 Locate/RecognitionPlan/Gate。
- observe trace 会保存 `screen_map`；`/panel/inspect_trace` 会把它解析为 `Path Map` 阶段，便于阅读 trace 时直接查看路径候选和 overlay 证据。
- 这个接口只能用于理解和候选发现，不能用于点击。

## POST /vision/locate_target

设计目的：对一个已经明确的目标做精准 no-click 定位，返回模型建议位置和点击闸门状态。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `goal` | string | 必填 | 明确目标，例如 `打开serato的职业界面`、`关闭窗口`。 |
| `task` | string | `click_target` | 精准定位任务类型。 |
| `app_name` | string/null | null | 应用上下文。 |
| `state_hint` | string/null | null | 当前区域提示，通常来自 `observe_screen.suggested_state_hint`。 |
| `provider_mode` | string/null | null | 推荐传 `local_grounding`。 |
| `metadata` | object | `{}` | OCR anchor 预算、prompt override 等扩展。 |
| `top_k` | integer | 5 | 候选数量上限。 |
| `capture_live` | boolean | true | 是否实时截图。 |
| `image_path` | string/null | null | `capture_live=false` 时使用的截图路径。 |
| `observe_trace_path` | string/null | null | 可选。传入前一次 `/vision/observe_screen` trace 后，若截图匹配，精准定位会复用其中的 `ocr_anchors`，避免同图重复 OCR。 |

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `target_location_v1`。 |
| `goal` | string | 本次定位目标。 |
| `image_path` | string | 实际分析图片。 |
| `live_capture` | object/null | 实时截图信息。 |
| `recognition_plan` | object | 内部生成的完整 no-click 识别计划。 |
| `pre_click_decision` | object | 点击前闸门结果。 |
| `selected_click_point` | object/null | 若闸门允许，才会有可执行点击点。通常精准定位接口不会直接放行。 |
| `recommended_target` | object | 推荐目标对象，可能来自可执行候选，也可能来自 `candidate_result.rejected[0]` 中的 review 候选。 |
| `located_bbox` | object/null | 精准定位建议的目标框，仅供复核。文本目标优先使用 OCR 收紧后的候选框，而不是漂移的大语义框。 |
| `located_point` | object/null | 精准定位建议的中心点，仅供复核。 |
| `location_status` | string | 定位状态，例如 `not_located`、`requires_pre_click_confirmation`。 |
| `path_map_review` | object | `path_map_review_v1` 路径图核对结果。基于本次 Locate 的 AI/候选理解和上一条 Observe `screen_map` 生成 `additions`、`removals`、`kept`，供测试面板修正当前路径图。 |
| `execution_path` | object | provider、OCR、candidate rank、pre-click 等路径信息。 |
| `trace_path` | string | locate trace。 |

使用注意：

- `located_bbox` / `located_point` 不代表可自动点击；只有 `selected_click_point` 非空才是闸门批准的执行点。
- 对 `include_referenced_text` 的文本目标，如果视觉语义框里包含未引用 OCR 文本，融合层会写入 `unreferenced_text_contamination` 并将候选保持为 `precise_text_target` review 状态。
- `locate_target` 会把最佳 review 候选也带回给测试面板填候选框，方便人工生成 overlay 和确认坐标。
- 如果请求携带可复用的 `observe_trace_path`，Locate 会返回 `path_map_review`。测试面板会加入缺失的精准定位候选，并删除同标签或高度重叠且被 Locate 替换的旧路径候选；不会删除已经点击过或已连接到下一页面的控件。

使用注意：

- `located_point` 不是自动点击点。
- 自动执行只能信任 `selected_click_point`，且一般应通过 `/action/execute_recognition_plan` 完成。

## POST /vision/recognition_plan

设计目的：生成完整 no-click 识别计划。它比 `/vision/locate_target` 更底层，暴露 OCR、视觉、page structure、screen reading、candidate rank、narrow search 和 pre-click decision。

请求字段：继承 `/vision/analyze` 字段，额外有：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `top_k` | integer | 5 | 候选数量上限。 |
| `observe_trace_path` | string/null | null | 可选。传入前一次 `/vision/observe_screen` trace 后，若截图匹配，会复用 OCR anchors，并基于 `screen_map_v1` 生成 `path_graph_recall_v1`。 |

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `recognition_plan_v1`。 |
| `goal` | string/null | 目标。 |
| `vision_regions` | object | 视觉模型原始/标准化区域。 |
| `ocr_result` | object | OCR 结果。 |
| `ocr_anchors` | object/null | OCR anchors 证据。 |
| `observe_trace_reuse` | object | Observe trace 复用状态。 |
| `path_graph_recall` | object | `path_graph_recall_v1`。执行模式的状态匹配与 PathGraph top-k 召回结果，包含候选、分数和 `local_ocr_roi` 提示；安全召回候选会合并进 `candidate_result`，继续经过局部 OCR grounding 和 `pre_click_decision_v1`。 |
| `page_structure` | object | 页面结构层。 |
| `screen_reading` | object | 读取层。 |
| `candidate_result` | object | 候选排序结果。 |
| `narrow_search_result` | object | 局部 OCR 精查结果。 |
| `pre_click_decision` | object | 点击前闸门结果。 |
| `recommended_target` | object/null | 推荐候选。 |
| `trace_path` | string | recognition trace。 |

关键子字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `candidate_result.candidates[]` | array | 排序后的候选。 |
| `candidate_result.recommended_candidate_id` | string/null | 推荐候选 id。 |
| `pre_click_decision.allowed` | boolean | 是否允许点击。 |
| `pre_click_decision.selected_click_point` | object/null | 允许点击时的最终点。 |
| `pre_click_decision.reasons` | array | 拒绝或允许的原因。 |

使用注意：这个接口不点击。它是执行接口内部会调用的计划生成阶段。

## POST /vision/layer_trace

设计目的：调试视觉管线各层输出，检查哪一层失败或契约不一致。

请求字段：同 `/vision/analyze`。

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `vision_layer_trace_v1`。 |
| `request` | object | 本次请求摘要。 |
| `layers` | object | 各层输出和校验结果。 |
| `failures` | array | 失败层或警告。 |
| `trace_path` | string | layer trace 文件。 |

使用注意：这是诊断接口，不参与正常点击链路。

## POST /vision/render_review_overlay

设计目的：从视觉 trace 渲染人工复核 overlay，帮助看模型框、OCR 框和区域标签是否对齐。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `trace_path` | string | 必填 | 要渲染的视觉 trace。 |
| `region_layer` | string | `vision_provider_raw` | 选择渲染哪一层区域。 |
| `include_regions` | boolean | true | 是否画视觉区域。 |
| `include_ocr` | boolean | true | 是否画 OCR 框。 |
| `label_regions` | boolean | true | 是否标注区域标签。 |
| `label_ocr` | boolean | false | 是否标注 OCR 文本。 |

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `overlay_path` | string | 生成的 overlay 图片路径。 |
| `trace_path` | string | 来源 trace。 |
| `region_layer` | string | 实际渲染层。 |

使用注意：只生成图片，不改变识别结果。

## POST /vision/render_recognition_plan_overlay

设计目的：从 recognition plan trace 渲染候选、点位、拒绝原因等复核 overlay。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `trace_path` | string | 必填 | recognition plan trace。 |
| `include_rejected` | boolean | true | 是否显示被拒候选。 |
| `include_points` | boolean | true | 是否显示点位。 |
| `label_candidates` | boolean | true | 是否标注候选标签。 |
| `label_reasons` | boolean | true | 是否标注拒绝/通过原因。 |

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `overlay_path` | string | 生成的 overlay 图片路径。 |
| `trace_path` | string | 来源 trace。 |

使用注意：用于人工复核，不执行点击。

## POST /action/execute_recognition_plan

设计目的：唯一推荐给自主 Agent 使用的真实点击入口。它内部先生成 recognition plan，再检查 pre-click decision，只有通过闸门才会点击。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `goal` | string | 必填 | 用户目标。 |
| `approved_plan_id` | string/null | null | 成功 dry-run 返回的短期批准计划 ID，用于真实点击复用。 |
| `learned_instruction_id` | string/null | null | 指令学习记录 ID，用于复用已验证过的同窗口同目标点击点。 |
| `learning_mode` | string/null | null | `instruction` 时，成功真实点击并验证后写入 `learned_instruction_v1`。 |
| `task` | string | `click_target` | 识别任务。 |
| `app_name` | string/null | null | 应用上下文。 |
| `state_hint` | string/null | null | 界面区域提示。 |
| `provider_mode` | string/null | null | 视觉 provider。 |
| `metadata` | object | `{}` | OCR/prompt/调试扩展。 |
| `top_k` | integer | 5 | 候选数量上限。 |
| `image_path` | string/null | null | `capture_live=false` 时使用的图片。 |
| `observe_trace_path` | string/null | null | 可选。传入最新 Observe trace 后，会透传给内部 recognition plan，用于 OCR anchors 复用和 PathGraph recall。 |
| `capture_live` | boolean | true | 是否从绑定窗口实时截图。 |
| `allow_saved_image_execution` | boolean | false | 是否允许对保存图片执行真实点击。默认禁止。 |
| `enable_post_click_verification` | boolean | true | 点击后是否验证。 |
| `max_execution_attempts` | integer | 2 | 最大点击尝试次数，范围 `1..3`。 |
| `dry_run` | boolean | false | 为 `true` 时只验证计划，不点击。 |

返回 `data` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `action` | string | 固定为 `execute_recognition_plan`。成功 dry-run 或真实点击时出现。 |
| `result` | object | 执行结果。 |

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `execute_recognition_plan_v1`。 |
| `goal` | string | 本次目标。 |
| `image_path` | string | 实际分析图片。 |
| `live_capture` | object/null | 实时截图信息。 |
| `recognition_plan` | object | 内部 no-click 识别计划。 |
| `recognition_plan_trace_path` | string/null | 计划 trace。 |
| `recognition_plan_overlay` | object/null | 自动生成的复核 overlay。 |
| `pre_click_decision` | object | 点击前闸门。 |
| `selected_click_point` | object/null | 通过闸门后的最终点击点。 |
| `approved_plan_id` | string/null | 复用或新生成的批准计划 ID。 |
| `learned_instruction_id` | string/null | 复用或新生成的指令学习记录 ID。 |
| `learned_instruction_reuse_validation` | object/null | 指令学习复用校验结果。 |
| `learned_instruction_bundle_dir` | string/null | 新生成的永久学习资产目录，例如 `artifacts/local-learning/instructions/{id}/`。 |
| `learned_instruction_artifacts` | object/null | 永久学习资产清单，包含源窗口截图、点击前截图、点击后截图、diff 图和目标裁剪图路径。 |
| `learning_mode` | string/null | 本次学习模式。 |
| `click_result` | object | 真实点击结果，仅实际点击后出现。 |
| `post_click_verification` | object | 通用点击后验证。 |
| `semantic_post_click_verification` | object | 语义验证，例如 MouseTester 特化验证。 |
| `attempts` | array | 每次点击尝试详情。 |
| `execution_path` | object | 计划、闸门、点击、验证、重试路径。 |
| `element_memory_writeback` | object/null | `execute_transition_memory_v1`。验证成功的真实点击会在 `write_policy.element_memory=true` 时写入 transition memory；dry-run、闸门拒绝、未验证成功或未绑定窗口不会写入。 |
| `fallback_plan` | object/null | `execute_fallback_plan_v1`。失败时给出局部重扫、PathGraph review、全屏 OCR 刷新或重新 grounding 的下一步计划；它不授予自动点击权限。 |
| `trace_path` | string | action trace。 |

安全语义：

- `dry_run=true` 且闸门通过：`success=true`，但 `execution_path.action_executed=false`。
- 闸门拒绝：`success=false`，`error.code=pre_click_rejected`，不会点击。
- 真实点击后验证失败：`success=false`，但 `execution_path.action_executed=true`，需要读验证字段。
- 只有验证成功的真实点击会写 `execute_transition_memory_v1`；执行经验归 ElementMemory，不反向污染 PathGraph 结构判断。
- 失败响应应读 `fallback_plan`，但下一次尝试仍必须重新经过 `pre_click_decision_v1`。如果 `steps[]` 包含 `request_scroll`，上层 agent 可先调用 `POST /action/scroll` 露出更多内容，再用同一个 goal 重跑 `POST /action/execute_recognition_plan`。
- Action trace 会保留 `element_memory_writeback` 或 `fallback_plan`，面板 Trace Inspector 分别显示为 `Memory` / `Fallback` 阶段。

Approved plan 复用：
- `dry_run=true` 且闸门通过时，`data.result.approved_plan_id` 会返回一个短期有效的已批准计划 ID。
- 后续真实点击应传入同一个 `goal` 和 `approved_plan_id`，并设置 `dry_run=false`。
- 复用时 runtime 会校验同一绑定窗口、窗口尺寸、目标文本、有效期和 `selected_click_point` 是否仍在窗口内；校验通过后直接点击，不再重新运行大视觉模型。
- 如果不传 `approved_plan_id`，`dry_run=false` 仍会走旧路径：重新截图、重新识别、重新过闸门，然后点击。

Instruction learning 复用：
- `learning_mode="instruction"` 且真实点击验证成功时，runtime 写入 `artifacts/local-learning/instructions/{id}/learned_instruction.json`，contract 为 `learned_instruction_v1`。
- 同一目录还永久保存学习证据图片，不使用滚动清理的普通截图缓存：`source_window.png`、`pre_action.png`、`post_action.png`、`post_action_diff.png`、`target_crop.png`。
- 后续请求可传入同一 `goal`、`app_name` 和 `learned_instruction_id`。
- 复用时 runtime 校验同一绑定窗口句柄、窗口尺寸和点击点边界；校验通过后直接使用学习记录中的 `selected_click_point`，不重新运行视觉模型。
- 指令学习复用仍会执行真实点击后的验证。第一版策略是 `same_window_exact`，只用于稳定性测试和 MouseTester 这类低风险重复界面。
- 复用成功不会再写一条新的学习记录；如果需要刷新记录，应先走普通识别执行并重新学习。

## POST /action/execute_confirmed_point

设计目的：桌面测试面板的人类复核路径。操作者看过候选框和点位后，手动确认一个窗口相对坐标。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `x` | integer | 必填 | 人工确认点 x，窗口相对坐标。 |
| `y` | integer | 必填 | 人工确认点 y，窗口相对坐标。 |
| `bbox` | object/null | null | 人工复核的候选框。若提供，点必须在框内。 |
| `label` | string/null | null | 人类标签，用于 trace 命名和复核。 |
| `source_trace_path` | string/null | null | 来源定位/识别 trace。 |
| `dry_run` | boolean | true | 默认只检查坐标，不点击。 |

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `execute_confirmed_point_v1`。 |
| `label` | string/null | 人工标签。 |
| `confirmed_point` | object | 人工确认点。 |
| `candidate_bbox` | object/null | 人工复核框。 |
| `source_trace_path` | string/null | 来源 trace。 |
| `bound_window` | object | 当前绑定窗口摘要。 |
| `execution_path` | object | 坐标来源为 `human_confirmed_candidate_center`。 |
| `click_result` | object | `dry_run=false` 且点击成功时出现。 |
| `trace_path` | string | action trace。 |

使用注意：这不是自主 Agent 的主路径。自主执行仍应使用 `/action/execute_recognition_plan`。

## POST /action/type_text

设计目的：向当前绑定窗口发送真实文本输入。它用于“搜索词输入”“表单填写”等场景，不做视觉定位；如果需要先聚焦输入框，可以传入窗口相对坐标并设置 `click_before_typing=true`。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `text` | string | 必填 | 要输入的文本。trace 不写入明文，只记录长度。 |
| `x`, `y` | integer/null | null | 可选窗口相对坐标。 |
| `click_before_typing` | boolean | false | 输入前是否先点击 `x,y` 聚焦。 |
| `clear_existing` | boolean | false | 输入前是否发送 Ctrl+A 清空现有内容。 |
| `submit` | boolean | false | 输入后是否按 Enter。 |
| `restore_clipboard` | boolean | true | 使用剪贴板粘贴后是否恢复原文本剪贴板内容。 |
| `dry_run` | boolean | false | 只校验请求，不发送输入。 |

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `type_text_result_v1`。 |
| `text_length` | integer | 输入文本长度，不包含明文。 |
| `type_result` | object | 真实输入时的 SendInput/clipboard 执行结果。 |
| `execution_path.action_executed` | boolean | 是否真的发送了输入。 |
| `trace_path` | string | 动作 trace。 |

## POST /action/scroll

设计目的：在当前绑定窗口内执行上下滚动，让 agent 在信息不全时先露出更多内容，再重新走执行模式识别与点击闸门。它不做视觉定位，也不授予点击权限。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `direction` | string | `down` | 滚动方向，取值 `down` 或 `up`。 |
| `wheel_clicks` | integer | `4` | 鼠标滚轮档数，范围 `1..20`。 |
| `x`, `y` | integer/null | null | 可选窗口相对坐标。为空时滚动点为当前绑定窗口中心；只有已确认具体可滚动 pane 时才建议传入。 |
| `scroll_scope` | string | `window` | 滚动范围。旧路径为 `window`；SEEK MVP 可用 `container`。 |
| `target_pane` | string/null | null | 目标 pane，例如 `results_list` 或 `job_detail`。 |
| `target_container_id` | string/null | null | 目标容器 id，例如 `seek:results_list` 或 `seek:job_detail`。 |
| `container_bbox` | object/null | null | 可选目标容器 bbox。为空时 SEEK MVP 会按当前窗口尺寸解析 `seek:page/results_list/job_detail`。 |
| `coordinate_window_size` | object/null | null | 调用方认为坐标所属的截图尺寸。若传入且与当前窗口坐标空间不匹配，会拒绝滚动。 |
| `goal_id`, `task_chain_id` | string/null | null | 用于把滚动和同一个上层任务串起来。 |
| `reason` | string/null | null | 为什么要滚动，例如 `required_detail_section_not_visible`。 |
| `missing_evidence` | array | [] | 当前缺失的证据，例如 `Requirements`。 |
| `expected_effect` | object | {} | 期望滚动效果，例如目标容器内容变化、非目标 pane 基本稳定。 |
| `scroll_history` | array | [] | 同一任务链之前的滚动记录。 |
| `dry_run` | boolean | false | 只校验窗口、坐标和 trace，不发送滚轮输入。 |
| `enable_verification` | boolean | true | 真实滚动后是否捕获前后状态并做通用变化验证。 |

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 旧窗口滚动为 `scroll_action_v1`；container-aware 滚动为 `scroll_action_v2`。 |
| `direction` | string | 实际请求方向。 |
| `wheel_clicks` | integer | 实际滚轮档数。 |
| `point` | object | 窗口相对滚动点。 |
| `scroll_containers` | object/null | `scroll_containers_v1`。SEEK container-aware 请求会包含 `seek:page`、`seek:results_list`、`seek:job_detail`。 |
| `target_container` | object/null | 实际解析出的目标容器。 |
| `precondition_decision` | object | `scroll_precondition_decision_v1`，记录坐标尺寸、容器、点位和方向是否允许滚动。 |
| `scroll_effect_validation` | object/null | `scroll_effect_validation_v1`，真实滚动后记录目标容器是否变化。 |
| `outcome` | object | 是否建议用同一个 goal 重跑 Execute。 |
| `bound_window` | object | 当前绑定窗口摘要。 |
| `scroll_result` | object | `dry_run=false` 时的 SendInput 滚轮执行结果，包含窗口点、屏幕点和滚轮 delta。 |
| `post_scroll_verification` | object/null | 真实滚动后的前后截图/差异验证结果。 |
| `execution_path.action_executed` | boolean | 是否真的发送了滚轮输入。 |
| `trace_path` | string | action trace。 |

安全语义：

- `POST /action/scroll` 是 reveal/navigation 动作，不是点击动作。
- Execute Mode 的 `fallback_plan.request_scroll` 只是建议“先滚动再重试同一目标”；滚动后仍必须重新调用 `POST /action/execute_recognition_plan` 并通过 `pre_click_decision_v1`。
- 如果滚动点超出当前绑定窗口，会返回 `error.code=scroll_point_outside_window`，不会发送输入。
- 如果 container-aware 请求未通过前置条件，会返回 `error.code=scroll_precondition_rejected`，不会发送输入。
- SEEK MVP 里不要默认滚窗口中心：职位列表相关目标滚 `seek:results_list`，职位详情相关目标滚 `seek:job_detail`。

## SEEK extraction contracts

这些 contract 当前由 `app/seek/extraction.py` 生成，用于 SEEK MVP 的岗位遍历、详情读取、匹配打分和最终报告。它们目前描述“当前可见证据”，不等于已经读完整个详情 pane。

### seek_job_cards_v1 / seek_job_card_v1

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 集合为 `seek_job_cards_v1`，单个岗位卡片为 `seek_job_card_v1`。 |
| `image_size` | object | 生成该集合时使用的截图尺寸。runner 会用它判断卡片点击点是否位于安全垂直带内；底边卡片会暂缓，等滚动后再点击。 |
| `jobs` | array | 可见职位卡片列表。 |
| `summary.jobs_seen` | integer | 当前可见并被识别为岗位卡片的数量。 |
| `job_id` | string | 由标题、公司、地点生成的稳定本地 id。 |
| `title` | string/null | 职位标题，通常来自卡片主 action label。 |
| `company` | string/null | 公司名候选。 |
| `location` | string/null | 地点文本候选。 |
| `posted_at_text` | string/null | 发布日期/时间文本。 |
| `work_type` | string/null | Full time / Part time / Contract 等工作类型。 |
| `salary_text` | string/null | 薪资文本候选。 |
| `classification` | string/null | 分类文本候选。 |
| `card_bbox` | object/null | 卡片 bbox。 |
| `click_point` | object/null | 卡片主点击点，只是 evidence；真实点击仍必须走 `execute_recognition_plan` gate。 |
| `source_url` | string/null | 卡片里可见的 URL。 |
| `source_card_id`, `primary_action_id`, `child_action_ids`, `child_page_element_ids` | string/array | 来源 inventory id，便于 trace 回溯。 |
| `evidence` | object | 原始可见文本和来源 contract。 |

### seek_job_detail_v1

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `seek_job_detail_v1`。 |
| `job_id` | string | 由详情标题、公司、地点生成的稳定本地 id。 |
| `title`, `company`, `location`, `work_type`, `classification`, `salary_text` | string/null | 当前右侧详情 pane 可见的岗位信息。 |
| `description_sections` | array | 当前可见详情文本段落，带 `role=body` 或 `section_hint`。 |
| `requirements`, `responsibilities`, `benefits` | array | 根据可见文本关键词提取的初始 section hint。 |
| `apply_button_state` | object | Apply / Quick Apply 可见状态、label、bbox、click point。真实点击仍必须走 gate。 |
| `save_button_state` | object | Save 按钮可见状态、label、bbox。 |
| `detail_container` | object/null | 用于抽取的 `seek:job_detail` 容器。 |
| `detail_read_bbox` | object/null | 实际读取详情文本/action 的 bbox。它会在 `detail_container` 基础上向上扩展，以包含 SEEK 详情 header 中的标题、公司、地点和 Quick Apply / Save。 |
| `detail_scroll_history` | array | 后续 traversal runner 合并多屏详情时写入；每个滚动项应带 `scroll_scope=container`、`target_pane=job_detail`、`target_container_id=seek:job_detail`。 |
| `trace_paths` | array | 后续 runner 写入相关 trace。 |
| `evidence` | object | 当前可见文本数量、action 数量、文本列表和来源 contract。 |

### seek_job_detail_completeness_v1

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `seek_job_detail_completeness_v1`。 |
| `complete` | boolean | 当前合并后的详情是否满足默认完整度要求。 |
| `should_scroll` | boolean | 是否应该继续滚动右侧 `seek:job_detail`。 |
| `missing_evidence` | array | 缺失证据，如 `title`、`company`、`location`、`description_sections` 或 `responsibilities`。 |
| `scroll_count` | integer | 当前岗位详情已滚动次数。 |
| `max_scrolls` | integer | 当前岗位详情允许的最大滚动次数。达到后必须停止并报告缺失证据。 |
| `stop_reason` | string | `complete`、`missing_evidence` 或 `max_scrolls_reached`。 |
| `next_scroll_request` | object/null | `should_scroll=true` 时给出的 `scroll_request_v2`，目标固定为 `seek:job_detail`。 |

### candidate_profile_v1

`scripts/seek_mvp_traversal_runner.py --candidate-profile` 可读取本地 JSON profile。当前最小匹配器要求至少有 `skills` 或 `target_roles`，否则岗位会返回 `need_user_review`，不会臆造候选人经验。

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 推荐为 `candidate_profile_v1`。缺省时 loader 会补上。 |
| `skills` | array | 候选人真实技能关键词。 |
| `target_roles` | array | 目标岗位标题/方向。 |
| `location_constraints` | array | 可接受地点，例如 `Auckland`。 |
| `experience_summary` | string/array | 真实经历摘要，后续求职信生成会使用。当前打分器不从这里编造技能。 |
| `risk_do_not_invent` | boolean | 建议为 `true`，提醒后续生成不得夸大经验。 |

### seek_job_match_decision_v1

由 `app/seek/matching.py` 针对已打开且读取到详情的岗位生成。

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `seek_job_match_decision_v1`。 |
| `decision` | string | `strong_apply`、`maybe_apply`、`skip` 或 `need_user_review`。 |
| `score` | number | `0..1` 匹配分。 |
| `job_id`, `title`, `company` | string/null | 被评分岗位摘要。 |
| `positive_evidence` | array | 匹配技能、角色、地点等正证据。 |
| `negative_evidence` | array | 地点不匹配等负证据。 |
| `unknowns` | array | profile 缺失、岗位信息不足等未知项。 |
| `risk_flags` | array | 至少包含 `do_not_invent_experience`，提醒不得夸大经历；详情不完整时还会包含 `detail_incomplete_do_not_apply`。 |
| `saved_job_path` | string/null | runner 保存 strong/maybe 记录后附加的本地路径。 |

匹配器现在会读取 profile 排除项和偏好：`avoid_roles`、`excluded_roles`、`avoid_companies`、`do_not_apply_to` 命中时直接 `skip`，并写入 `candidate_profile_exclusion_matched`，不会保存岗位记录。`preferred_work_modes` 只在岗位详情可见匹配时增加正证据，不会绕过安全规则。岗位详情中出现 visa、sponsorship、citizenship、residency、security clearance、background check 等工作权利/背景审查风险词时，决策转为 `need_user_review`，并写入 `work_rights_or_background_check_requires_review`。

### saved_seek_job_record_v1

只为 `strong_apply` / `maybe_apply` 保存，默认在 `artifacts/seek/saved-jobs/`，JSON 使用 UTF-8 和 `ensure_ascii=false`。

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `saved_seek_job_record_v1`。 |
| `job_id` | string | 本地稳定岗位 id。 |
| `decision` | object | 对应的 `seek_job_match_decision_v1`。 |
| `card` | object | 原始 `seek_job_card_v1`。 |
| `detail` | object | 合并后的 `seek_job_detail_v1`。 |

### seek_mvp_run_report_v1

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `seek_mvp_run_report_v1`。 |
| `jobs_seen`, `jobs_opened`, `jobs_fully_read` | integer | 岗位遍历、打开和完整读取计数。 |
| `strong_apply`, `maybe_apply`, `skip`, `need_user_review` | integer | 匹配决策计数。 |
| `application_flows_started` | integer | 已进入申请流程的次数。 |
| `cover_letters_generated` | integer | 已生成 draft-only 求职信次数；blocked draft 不计入。 |
| `forms_filled_until_review` | integer | 填写到人工/风险复核前的次数。 |
| `form_fields_filled` | integer | 本轮实际填写的字段数。Apply Entry 阶段必须为 `0`。 |
| `continue_clicks` | integer | 本轮 Continue / Next / Review 类推进点击次数。Apply Entry 只读阶段必须为 `0`。 |
| `final_submissions` | integer | 必须恒为 `0`。 |
| `submit_clicks` | integer | 本轮最终提交类点击次数。必须恒为 `0`。 |
| `jobs` | array | 每个岗位的 card、detail 和 match decision。 |
| `match_decisions` | array | runner 针对已打开详情生成的 `seek_job_match_decision_v1` 列表。 |
| `results_list_scrolls` | array | 左侧岗位列表滚动记录；每项包含 `scroll_scope`、`target_pane`、`target_container_id`、trace 和效果验证摘要。SEEK runner 中 `target_container_id` 应为 `seek:results_list`。 |
| `candidate_profile_loaded` | boolean | 本次 runner 是否加载了 profile。 |
| `candidate_profile_readiness` | object | `candidate_profile_readiness_v1`，说明当前 profile 是否可用于真实求职信和单字段 safe-fill。 |
| `saved_jobs` | array | 已保存的 strong/maybe 岗位记录路径。 |
| `apply_entry_enabled` | boolean | runner 是否启用 `--apply-entry`。默认关闭。 |
| `allow_maybe_apply` | boolean | 是否允许 `maybe_apply` 岗位进入 Apply Entry。默认 `false`，即只允许 `strong_apply`。 |
| `apply_entries` | array | `seek_apply_entry_attempt_v1` 列表，记录 Apply / Quick Apply dry-run、真实点击、申请状态检测和停止原因。 |
| `cover_letter_drafts` | array | `cover_letter_draft_v1` 列表；当前只记录 draft/blocked artifact，不粘贴 UI。 |
| `application_answer_plans` | array | `application_answer_plan_v1` 列表；当前只记录只读答题计划，不填写 UI。 |
| `safe_form_fill_enabled` | boolean | runner 是否启用 `--fill-safe-fields`。默认 `false`。 |
| `safe_form_fill_attempts` | array | `safe_form_fill_attempt_v1` 列表；记录 safe-fill 预览或真实尝试。 |
| `final_submit_guard_active` | boolean | 是否启用了 Apply Entry 的最终提交守门链路。 |
| `accuracy_summary` | object | `seek_mvp_accuracy_summary_v1`，结构化准确率和安全 invariant 摘要。 |
| `accuracy_notes` | array | runner 写入的准确率/缺失证据说明。 |
| `traversal_trace_path` | string/null | 独立 `seek_mvp_traversal_trace_v1` trace 路径，用于审计岗位遍历、滚动、详情读取、匹配、Apply Entry、答题计划、safe-fill 尝试和安全计数。 |
| `elapsed_ms` | number/null | 本次 run 总耗时。 |

当前 runner 行为说明：

- `scripts/seek_mvp_traversal_runner.py` 默认 `--max-detail-scrolls=6`、`--max-results-scrolls=8`。
- 传入 `--execute-clicks` 时，`--max-jobs` 表示目标“成功打开并读取”的岗位数；runner 会保留有界尝试上限，避免连续坏卡片导致无限循环。
- 每次职位卡真实点击后，runner 会重新 observe，并生成 `seek_post_click_layout_check_v1`：要求右侧详情标题与点击卡片标题匹配；不匹配时记为 `post_click_layout_drift`，不会计入 `jobs_opened`。
- 传入 `--apply-entry` 时，runner 只对 `strong_apply` 岗位默认点击 Apply / Quick Apply；`maybe_apply` 需要显式 `--allow-maybe-apply`。Apply 点击仍必须走 `POST /action/execute_recognition_plan` dry-run + approved-plan 真实执行，metadata 带 `forbid_final_submit=true` 和 `required_container_id=seek:job_detail`，目标中也包含“不点击 Submit / Send application / Complete application”的负约束。
- 最新真实 SEEK no-apply smoke：`logs\smoke\seek_mvp_traversal_real_5_profile_smoke_rerun12.json`，`jobs_seen=5`、`jobs_opened=5`、`jobs_fully_read=5`、`final_submissions=0`。

### seek_mvp_traversal_trace_v1

由 `scripts\seek_mvp_traversal_runner.py` 在生成 `seek_mvp_run_report_v1` 后写入，路径回填到 `report.traversal_trace_path`。它是比 report 更适合人工审计的时间线，不授权任何额外动作。

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `seek_mvp_traversal_trace_v1`。 |
| `source_report_contract` | string/null | 来源 report 合同名，通常是 `seek_mvp_run_report_v1`。 |
| `mode` | string/null | runner 模式，例如 no-apply traversal 或 Apply Entry traversal。 |
| `source_url` | string/null | 本次 SEEK URL。 |
| `execute_clicks` | boolean/null | 本次是否允许真实职位卡点击。 |
| `candidate_profile_readiness` | object/null | 本次 profile readiness 摘要。 |
| `apply_entry_profile_gate` | object/null | Apply Entry / safe-fill profile gate 摘要。 |
| `summary` | object | jobs、match、application、submit、elapsed 等顶层计数。 |
| `traversal_events` | array | 每个岗位步骤的卡片、card-click trace、detail-read trace、完整性、滚动、匹配、Apply Entry 和 search restore 摘要。 |
| `scroll_events` | array | 左侧 results-list 滚动记录。右侧详情滚动保留在各 `traversal_events[].detail_read.scrolls` 中。 |
| `match_decisions` | array | 本次匹配判断列表。 |
| `saved_jobs` | array | 本次保存的 strong/maybe 岗位记录。 |
| `apply_entries` | array | Apply / Quick Apply 尝试摘要，包括 pre-Apply verification、final guard、application state、answer plan 和 safe-fill attempt。 |
| `application_answer_plans` | array | 本次生成的只读答题计划。 |
| `safe_form_fill_attempts` | array | 本次 safe-fill 预览或真实尝试。 |
| `accuracy_summary` | object/null | `seek_mvp_accuracy_summary_v1`。 |
| `safety` | object | `continue_clicks`、`submit_clicks`、`form_fields_filled`、`final_submissions` 和 `final_submit_guard_active`。 |

审计顺序建议：先看 `accuracy_summary.status` 和 `safety.final_submissions`，再看失败岗位的 `traversal_events[].card_click.trace_path`、`recognition_plan_trace_path`、`detail_read.trace_paths` 和滚动容器。

### seek_mvp_run_audit_v1

由 `scripts\seek_mvp_run_audit.py` 生成，用于在继续 Apply Entry / safe-fill / GPT 复审前，对 `seek_mvp_run_report_v1` 和 `seek_mvp_traversal_trace_v1` 做只读审计。它不会截图、点击、滚动、调用模型或写记忆。

```powershell
uv run python scripts\seek_mvp_run_audit.py --report logs\smoke\seek_mvp_traversal_report.json --mode readonly --out logs\smoke\seek_mvp_run_audit.json
```

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `seek_mvp_run_audit_v1`。 |
| `stage` | string | `no_apply`、`apply_entry` 或 `full_mvp`；CLI 也接受 `--mode readonly` 和 `--mode safe_fill` 作为别名。 |
| `decision` | string | `pass` 或 `needs_review`。 |
| `report_path` | string/null | 被审计的 report 路径。 |
| `traversal_trace_path` | string/null | 使用的 traversal trace 路径。 |
| `summary` | object | jobs、matching、application、cover-letter、fill、final submission 和耗时摘要。 |
| `counts` | object | checks/passed/warnings/failed 计数。 |
| `checks` | array | 每条审计规则，包含 `id`、`status`、`message`、`actual`、`expected`。 |
| `next_step` | string | 对上层 agent 的下一步建议。 |

硬失败包括：`final_submissions != 0`、`submit_clicks != 0`、滚错 SEEK 容器、缺少 traversal trace、已打开岗位缺匹配判断、已打开卡片缺 click trace、或 blocked profile 仍进入 Apply/填字段。当前没有真实 `candidate_profile_v1` 时，`blocked_need_real_candidate_profile` 本身不是失败；只有当系统绕过该 gate 去点击 Apply、生成 live cover letter 或填写字段时才失败。

### cv_text_extraction_v1 / candidate_profile_from_cv_summary_v1

These contracts are produced by the reusable CV helper, not by the SEEK-only runner.

Command:

```powershell
uv run python scripts\candidate_profile_from_cv.py --cv "D:\资料\CV\WENQING JI.docx" --out artifacts\seek\candidate_profile_wenqingji_draft.json
```

`cv_text_extraction_v1`:

| Field | Type | Meaning |
| --- | --- | --- |
| `contract_version` | string | Fixed value `cv_text_extraction_v1`. |
| `source_path` | string | Local CV path, preserved as UTF-8. |
| `source_format` | string | `docx`, `txt`, or `md`. |
| `text_hash` | string | SHA-256 of extracted UTF-8 text. |
| `paragraph_count` | integer | Number of extracted paragraphs or lines. |
| `text` | string | Extracted local text. This is not printed by the CLI summary. |

`candidate_profile_v1` draft fields generated by `app.profile.cv.build_candidate_profile_from_cv_text()`:

| Field | Type | Meaning |
| --- | --- | --- |
| `profile_source` | string | `real_user_candidate_profile_v1` when generated from the user's real local CV. |
| `profile_generation` | object | `candidate_profile_generation_v1` metadata: source path/hash, deterministic parser method, and `review_required=true`. |
| `candidate_name`, `email`, `phone`, `city` | string | Extracted local profile basics when visible in the CV. |
| `skills`, `target_roles`, `experience_summary`, `education_summary` | array/string | Deterministic evidence extracted from the CV text. |
| `work_rights_summary` | string | Intentionally left blank; the helper must not infer this from a CV. |
| `profile_review_required` | boolean | Always true for generated drafts until the user reviews/edits them. |

`candidate_profile_from_cv_summary_v1` is the CLI stdout summary. It reports counts, source path, readiness decision, and missing requirements. It must not print raw email or phone values; only lengths/counts are allowed.

### learned_app_profile_v1 / path_graph_seed_v1

These contracts are generated by `scripts\seek_export_learn_artifacts.py` from stable SEEK run evidence. They are Learn Mode artifacts, not direct-click authorization.

Command:

```powershell
uv run python scripts\seek_export_learn_artifacts.py --report logs\smoke\seek_mvp_traversal_report.json --out artifacts\seek\learned_seek_mvp_latest.json
```

`learned_app_profile_v1`:

| Field | Type | Meaning |
| --- | --- | --- |
| `contract_version` | string | Fixed value `learned_app_profile_v1`. |
| `profile_id` | string | Stable id for the learned SEEK profile, currently `seek_search_results_detail_mvp_v1`. |
| `page_type` | string | Current learned page type, `seek_search_results_with_detail`. |
| `scroll_containers` | array | Learned container roles such as `seek:results_list` and `seek:job_detail`. |
| `entity_patterns` | array | Learned extraction patterns for `job_card` and `job_detail`. |
| `action_templates` | array | Templates for `open_job_card`, `read_detail`, `load_more_results`, and `apply_entry`. |
| `verification_rules` | array | Rules that must remain true when executing with this profile. |
| `safety_policy` | object | No-final-submit policy and requirements for gated clicks, Apply Entry, and safe-fill. |

`path_graph_seed_v1`:

| Field | Type | Meaning |
| --- | --- | --- |
| `contract_version` | string | Fixed value `path_graph_seed_v1`. |
| `page_type` | string | The page shape represented by this seed. |
| `sections` | array | Structural sections: `top_search_area`, `results_list`, `job_detail`, `job_card`, `detail_header`, `detail_body`. |
| `edges` | array | Structural relations, for example `job_card -> job_detail` as `open_job_card_updates_detail`. |
| `action_bindings` | object | Binds actions to sections and scroll containers. |
| `safety_policy_ref` | string | Reference to the learned safety policy. |

When passed to `scripts\seek_mvp_traversal_runner.py --learned-artifact`, this artifact may supply scroll targets, candidate constraints, verification policy, and safety policy metadata. It does not bypass `recognition_plan_v1`, `pre_click_decision_v1`, post-click verification, or `final_submit_guard_v1`.

### candidate_profile_readiness_v1

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `candidate_profile_readiness_v1`。 |
| `profile_present` | boolean | 是否加载了 profile JSON。 |
| `is_smoke_or_test_profile` | boolean | 是否检测到 smoke/test/synthetic/Do not use for real 等标记。 |
| `smoke_or_test_markers` | array | 命中的测试 profile 标记。 |
| `matching_ready` | boolean | 是否具备用于 SEEK 岗位匹配的最低资料：真实 profile、skills 或 target_roles、location_constraints。 |
| `cover_letter_ready` | boolean | 是否具备真实求职信生成的最低 profile 条件；仍需岗位为 `strong_apply`。 |
| `safe_fill_ready` | boolean | 是否至少有一个明确的低风险文本字段值可用于单字段 live safe-fill。 |
| `live_smoke_ready` | boolean | 是否同时满足 matching、cover letter、safe-fill 和 work_rights_summary 的 live smoke 前置条件。 |
| `safe_fill_values` | array | 可用于 safe-fill 的 profile 字段摘要，只记录字段名和长度，不记录完整明文。 |
| `missing_requirements` | array | 阻止真实 cover letter 或 safe-fill 的缺失项。 |
| `optional_profile_gaps` | array | 不阻断 live smoke、但建议补齐的资料项，例如 education、availability、avoid roles、salary preference。 |
| `decision` | string | `ready_for_single_safe_field_live_smoke` 或 `blocked_need_real_candidate_profile`。 |
| `notes` | array | 安全说明。 |

smoke/test profile 即使包含邮箱等值，也不能用于真实 safe-fill。真实 live safe-fill 必须由用户提供真实 `candidate_profile_v1`，不能由 runner 或模型伪造。当前 `ready_for_single_safe_field_live_smoke` 还要求 `location_constraints` 和 `work_rights_summary`，避免只有姓名/邮箱却缺少岗位匹配上下文。

### seek_mvp_accuracy_summary_v1

`seek_mvp_run_report_v1.accuracy_summary` 用于把遍历和安全证据收敛成一眼可读的质量摘要；它不授权任何点击，只总结本次 run 已经发生的证据。

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `seek_mvp_accuracy_summary_v1`。 |
| `jobs_seen`, `jobs_opened`, `jobs_fully_read` | integer | 与 report 顶层计数一致。 |
| `opened_rate` | number/null | `jobs_opened / jobs_seen`。无分母时为 null。 |
| `detail_read_completion_rate` | number/null | `jobs_fully_read / jobs_opened`。 |
| `match_decision_coverage_rate` | number/null | 顶层 `match_decisions` 数量 / `jobs_opened`。 |
| `card_click_attempts`, `card_click_opened`, `card_click_open_rate` | integer/number/null | 从 `traversal_steps[].card_click` 汇总的卡片点击验证率。 |
| `post_click_layout_drift_count` | integer | 点击后右侧详情和卡片标题不一致的次数。 |
| `results_list_scroll_count`, `detail_scroll_count` | integer | 左侧列表滚动和右侧详情滚动次数。 |
| `wrong_scope_scroll_count` | integer | 滚错容器或 effect validation 报告 wrong scope 的次数。 |
| `wrong_scope_scrolls` | array | 最多前 10 个 wrong-scope scroll 摘要，含 kind、target pane、target container 和 trace。 |
| `apply_entry_count`, `application_flow_started_count` | integer | Apply Entry 尝试数和实际进入申请流程数。 |
| `final_submit_visible_blocker_count` | integer | 状态层 final-submit blocker 触发次数。 |
| `safety_invariants` | object | `final_submissions_zero`、`submit_clicks_zero`、`continue_clicks_zero`、`wrong_scope_scrolls_zero`。 |
| `status` | string | `pass` 或 `needs_review`。当前如果出现 submit/final submission 或 wrong-scope scroll，会变成 `needs_review`。 |

该摘要用于审计，不替代 trace。定位失败时仍应回到 card-click trace、scroll trace、detail completeness、`pre_click_decision_v1` 和 `post_click_verification` 查根因。

### seek_apply_entry_attempt_v1

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `seek_apply_entry_attempt_v1`。 |
| `job_id`, `title`, `company` | string/null | 进入 Apply Entry 的岗位摘要。 |
| `decision` | string | 来自 `seek_job_match_decision_v1`。默认只有 `strong_apply` 可进入。 |
| `eligible` | boolean | 是否满足进入 Apply Entry 的决策条件。 |
| `goal` | string/null | 发给 Execute Mode 的 Apply / Quick Apply 点击目标，带最终提交负约束。 |
| `dry_run_response` | object/null | Apply 点击 dry-run 摘要，包含 overlay / trace / approved_plan_id 等证据。 |
| `execute_response` | object/null | Apply 点击真实执行摘要。 |
| `apply_click` | object | Apply / Quick Apply 点击意图证据；`container_id` 必须是 `seek:job_detail`。 |
| `final_submit_guard` | object/null | 来自 action gate 的 `final_submit_guard_v1` 摘要。 |
| `application_flow_state` | object/null | 点击后 observe 得到的 `seek_application_flow_state_v1`。 |
| `application_flow_started` | boolean | 是否识别到申请流程已打开。 |
| `final_submit_visible_blocker` | object/null | 状态层 `final_submit_visible_blocker_v1`，看到最终提交类按钮时必须停止。 |
| `cover_letter_draft` | object/null | `cover_letter_draft_v1`；当前只生成或阻断 draft artifact，不粘贴 UI。 |
| `cover_letter_generated` | boolean | 是否生成了 `status=draft_only_not_pasted` 的草稿。 |
| `application_answer_plan` | object/null | `application_answer_plan_v1`；当前只分类字段和答案来源，不填写 UI。 |
| `application_answer_plan_generated` | boolean | 是否生成了只读答题计划。 |
| `safe_form_fill_attempt` | object/null | `safe_form_fill_attempt_v1`；默认 disabled，显式 `--fill-safe-fields` 才可能真实填写。 |
| `continue_clicks` | integer | Apply Entry 阶段 Continue / Next / Review 类推进点击次数，必须为 `0`。 |
| `submit_clicks` | integer | Apply Entry 阶段最终提交点击次数，必须为 `0`。 |
| `form_fields_filled` | integer | Apply Entry 阶段填表字段数，必须为 `0`。 |
| `stop_reason` | string/null | 停止原因。 |
| `final_submission_performed` | boolean | 必须为 `false`。 |

### final_submit_guard_v1

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `final_submit_guard_v1`。 |
| `enabled` | boolean | 请求 metadata 是否启用 `forbid_final_submit`。 |
| `allowed` | boolean | 是否允许当前候选继续执行。为 `false` 时必须在点击前阻断。 |
| `selected_candidate_id` | string/null | pre-click 选中的候选 id。 |
| `selected_texts` | array | 用于判断的候选文本、标签、OCR/grounding 匹配文本。 |
| `matched_terms` | array | 命中的最终提交风险词，如 `submit application`、`send application`、`complete application`、`submit`。 |
| `reason` | string | `no_final_submit_candidate_detected`、`final_submit_candidate_blocked` 或 `guard_disabled`。 |

### seek_application_flow_state_v1

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `seek_application_flow_state_v1`。 |
| `status` | string | 当前固定为 `blocked_need_user_or_gpt_decision`，表示进入状态识别后立即停下。 |
| `state_type` | string | `application_flow_opened`、`application_form_detected`、`cover_letter_field_detected`、`screening_questions_detected`、`review_step_detected`、`resume_upload_required`、`final_submit_visible`、`login_required`、`captcha_or_verification`、`third_party_ats`、`risky_application_questions` 或 `unknown_after_apply`。 |
| `detected_states` | array | 本次只读识别命中的状态标签，例如 `final_submit_detected`、`cover_letter_field_detected`、`screening_questions_detected`。 |
| `stop_reason` | string | 为什么停下。 |
| `application_flow_started` | boolean | 是否确认进入了申请流程。 |
| `final_submit_visible` | boolean | 是否看到了最终提交类按钮。看到也不能点击。 |
| `final_submit_visible_blocker` | object | 状态层最终提交可见拦截证据，合同为 `final_submit_visible_blocker_v1`。 |
| `final_submission_performed` | boolean | 必须为 `false`。 |
| `risk_flags` | array | 登录、验证码、第三方 ATS、最终提交、薪资/签证等风险标记。 |
| `application_form_inventory` | object | 只读表单清单，合同为 `application_form_inventory_v1`，用于判断 cover letter、screening questions 和可见 actions。 |
| `trace_path` | string/null | Apply 后 observe trace。 |
| `source_job` | object | 来源岗位摘要。 |
| `evidence.texts` | array | 用于状态判断的可见文本证据。 |

### final_submit_visible_blocker_v1

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `final_submit_visible_blocker_v1`。 |
| `enabled` | boolean | 当前固定为 `true`。 |
| `blocked` | boolean | 是否看到了最终提交类按钮/文本；为 `true` 时 runner 必须停止。 |
| `matched_terms` | array | 命中的最终提交词，例如 `submit application`、`send application`、`complete application`、`review and submit`。 |
| `matched_items` | array | 命中的可见控件/文本证据，包含 collection、id、text、role、bbox 和 matched_terms。 |
| `reason` | string | `final_submit_visible_stop_before_submission` 或 `no_final_submit_visible`。 |

这是页面状态层 blocker，不替代 action 层 `final_submit_guard_v1`；每次真实点击仍必须走 action gate。负约束或说明文本（例如 `Do not click Submit` / `不要点击 Submit`）不会被当作真实提交按钮证据；触发 STOP 的证据应来自 action-like 控件或短按钮标签。

### application_form_inventory_v1

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `application_form_inventory_v1`。 |
| `application_form_detected` | boolean | 是否看到了申请表单或表单字段证据。 |
| `cover_letter_field_detected` | boolean | 是否看到了 cover letter / supporting statement 字段证据。 |
| `screening_questions_detected` | boolean | 是否看到了 screening questions / employer questions。 |
| `field_count` | integer | 只读识别到的字段证据数量。 |
| `action_count` | integer | 只读识别到的 action 数量。 |
| `fields` | array | 字段证据摘要；当前只用于判断和 trace，不直接授权填写。 |
| `actions` | array | 可见 action 证据摘要；当前只用于判断和 trace，不直接授权点击。 |

### cover_letter_draft_v1

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `cover_letter_draft_v1`。 |
| `job_hash` | string | 由岗位 id/title/company/要求/职责生成的稳定摘要。 |
| `job_id` | string/null | 来源岗位 id。 |
| `title`, `company` | string | 岗位标题和公司。 |
| `status` | string | `draft_only_not_pasted`、`blocked_need_real_resume_profile`、`blocked_decision_not_strong_apply` 或 `blocked_no_profile_skill_evidence`。 |
| `draft` | string | 英文求职信草稿；blocked 时为空。 |
| `evidence_used` | array | 草稿实际使用的 profile/job/match 证据。 |
| `truthfulness_checks` | object | 不声称商业年限、不声称已提交、不夸大毕业状态、不发明技能、draft-only 等检查。 |
| `blocked_reason` | string/null | blocked draft 的原因。 |
| `source_contracts` | object | 输入合同版本摘要。 |

当前该合同只允许生成文本 artifact，不允许粘贴到 SEEK 页面，也不授予表单填写或下一步点击权限。

### application_answer_plan_v1

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `application_answer_plan_v1`。 |
| `status` | string | `planned_only_not_filled`、`blocked_final_submit_visible` 或 `no_fields_detected`。 |
| `filled` | boolean | 当前必须为 `false`。 |
| `field_count` | integer | 从 `application_form_inventory_v1` 看到的字段数。 |
| `action_count` | integer | 从 `application_form_inventory_v1` 看到的 action 数。 |
| `counts` | object | `auto_safe_known`、`needs_user_review`、`blocked_sensitive`、`unsupported`、`danger_final_submit` 计数。 |
| `planned_answers` | array | 每个字段/action 的分类、原因、来源和可选 value preview。 |
| `stop_reason` | string | 为什么当前只规划不填写。 |
| `source_contracts` | object | 输入合同版本摘要。 |

该合同只做只读分类。只有后续 safe-fill slice 才能使用 `auto_safe_known`，并且仍必须禁止 Continue / Next / Review / Submit。

当前 `auto_safe_known` 只允许简单文本/email/url/tel 字段，并且必须从 `candidate_profile_v1` 读到明确值。已支持的低风险字段包括 first name、last name、preferred name、email、phone/mobile、city/suburb、GitHub、LinkedIn、portfolio/website。button、radio、select、dropdown、file 控件不会因为 label 匹配就自动填写。薪资、入职时间、搬家、健康、犯罪、背景调查、复杂签证、上传和最终提交类字段仍然保持 `blocked_sensitive` / `unsupported` / `danger_final_submit` / `needs_user_review`。

### safe_form_fill_attempt_v1

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `safe_form_fill_attempt_v1`。 |
| `enabled` | boolean | 是否启用了真实 safe-fill。默认 `false`。 |
| `max_safe_fields_to_fill` | integer | 单次 Apply Entry 最多填写的 safe-known 字段数。runner 默认 `1`。 |
| `allow_cover_letter_fill` | boolean | 是否允许填写 `cover_letter_draft_v1.draft`。默认 `false`。 |
| `status` | string | `disabled`、`dry_run_ready`、`no_safe_known_fields`、`filled_until_review` 或 `blocked_need_user_or_gpt_decision`。 |
| `filled` | boolean | 本次是否至少填入一个 safe-known 字段。 |
| `fields_attempted` | integer | 尝试填写的字段数。 |
| `fields_filled` | integer | 成功填写的字段数。 |
| `continue_clicks`, `submit_clicks`, `final_submissions` | integer | 必须保持 `0`。 |
| `stop_reason` | string | 停止原因。 |
| `candidate_count` | integer | 通过 safe-fill 过滤的候选数，不包含被跳过的 cover letter 等候选。 |
| `selected_count` | integer | 本次真实填写会选择的候选数，受 `max_safe_fields_to_fill` 限制。 |
| `skipped_candidates` | array | 被策略跳过的候选及原因，例如 `cover_letter_fill_requires_explicit_flag`。 |
| `field_results` | array | 每个 `safe_field_fill_result_v1`。preview 路径会标记 `selected_for_fill`。 |

真实填写时，每个字段必须先通过 `POST /action/execute_recognition_plan` dry-run + approved-plan execution 聚焦字段，再调用 `POST /action/type_text`。`type_text` 必须使用 `click_before_typing=false`、`submit=false`，避免绕过 gated focus 或误提交。每个字段结果会嵌入 `safe_form_fill_trace_v1`。当前 runner 默认最多只填 1 个字段；cover letter 即使有 draft，也必须显式 `--allow-cover-letter-fill` 才能进入候选。

### safe_form_fill_trace_v1

`safe_form_fill_trace_v1` 嵌入在每个 `safe_field_fill_result_v1.safe_form_fill_trace` 中，用于人工审计 safe-fill 预览或真实尝试。默认不开 `--fill-safe-fields` 时也会生成 preview skeleton。

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `safe_form_fill_trace_v1`。 |
| `enabled` | boolean | 本字段是否真的进入填写路径；preview 为 `false`。 |
| `field_id` | string/null | 来源字段 id；通常来自 `application_answer_plan_v1.planned_answers[].source.id`。 |
| `field_label` | string | 字段标签。 |
| `field_category` | string | 应为 `auto_safe_known`；其他类别不得进入真实填写。 |
| `field_bbox` | object/null | 来源字段 bbox，用于人工核对。 |
| `container_or_form_id` | string/null | 字段来源 collection/form/container。 |
| `answer_plan_ref` | object | 答题计划引用，包括 label、reason、answer_source。 |
| `value_source` | string/null | 值来源，例如 `candidate_profile_v1.email` 或 `cover_letter_draft_v1.draft`。 |
| `value_preview` | string | 用于本地人工核对的短预览。 |
| `value_length` | integer | 实际待输入文本长度。 |
| `value_hash` | string/null | UTF-8 文本的 SHA-256，用于核对而不是到处写明文。 |
| `pre_focus_dry_run` | object/null | 聚焦字段前的 `execute_recognition_plan` dry-run 结果摘要。 |
| `approved_focus_reuse` | object/null | 复用 approved plan 真实聚焦结果摘要。 |
| `type_text_request` | object | 只记录请求 flag：`click_before_typing=false`、`clear_existing=true`、`submit=false`、`restore_clipboard=true` 和 text_length。 |
| `post_fill_verification` | object | 当前为占位审计字段；至少记录 `no_submit=true` 和 `type_text_trace_path`。后续 live safe-fill 再补字段内容核验。 |
| `safety` | object | 安全计数，必须保持 `continue_clicks=0`、`submit_clicks=0`、`final_submissions=0`。 |

### post_fill_verification_v1

`post_fill_verification_v1` 在真实 `type_text` 成功后运行。它会重新 observe 当前 SEEK application surface，重新生成 `seek_application_flow_state_v1` / `final_submit_visible_blocker_v1`，并尽量用结构化字段值证据确认输入结果。

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `post_fill_verification_v1`。 |
| `field_id`, `field_label`, `field_category` | string/null | 被验证的字段摘要。 |
| `expected_value_hash` | string/null | 期望值 SHA-256。 |
| `expected_value_preview` | string | 短预览，仅用于本地人工核对。 |
| `verification_methods` | object | DOM value、UIA value pattern、OCR near field 的可用性和匹配情况。当前 DOM/UIA 证据才可作为主成功依据；OCR 只作辅助。 |
| `field_relocation` | object | 重新定位字段的结果、置信度和匹配项。 |
| `field_contains_expected_value` | boolean | 是否用主证据确认字段包含期望值。 |
| `same_application_state` | boolean | 填写后是否仍在安全申请状态。 |
| `no_navigation` | boolean | 是否没有进入外部 ATS、登录、验证码、review/final submit 等危险状态。 |
| `no_continue_or_next` | boolean | 本 slice 固定应为 `true`；如果后续出现推进计数必须失败。 |
| `no_submit` | boolean | 必须为 `true`。 |
| `final_submit_visible_blocker` | object | 填写后重新运行的状态层 blocker 摘要。若 `blocked=true`，`decision=stop_required`。 |
| `application_flow_state` | object | 填写后的申请状态摘要。 |
| `decision` | string | `verified`、`unverified`、`failed` 或 `stop_required`。 |
| `failure_reason` | string/null | 未验证或停止的原因。 |
| `type_text_trace_path`, `observe_trace_path` | string/null | 填写和后置 observe trace。 |
| `safety` | object | `continue_clicks=0`、`submit_clicks=0`、`final_submissions=0`。 |

如果字段无法用 DOM/UIA 风格值证据确认，当前 runner 会返回 `unverified` 并停止后续字段；不会把 OCR-only 命中当作默认成功。

### candidate_profile_readiness_v1

用于在真实 SEEK safe-fill 之前检查 `candidate_profile_v1` 是否可用。纯函数入口为 `app.seek.profile.assess_candidate_profile_readiness()`，独立 CLI 为：

```powershell
uv run python scripts\seek_profile_readiness.py --candidate-profile path\to\candidate_profile.json --out logs\smoke\seek_profile_readiness.json
```

CLI 外层合同为 `seek_profile_readiness_cli_report_v1`，其中 `readiness` 字段是 `candidate_profile_readiness_v1`。

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | `candidate_profile_readiness_v1`。 |
| `profile_present` | boolean | 是否加载了 profile JSON。 |
| `is_smoke_or_test_profile` | boolean | 是否包含 smoke/test/synthetic/do-not-use-for-real 标记。 |
| `smoke_or_test_markers` | array | 命中的测试资料标记。 |
| `matching_ready` | boolean | 是否具备用于 SEEK 岗位匹配的最低资料：真实 profile、skills 或 target_roles、location_constraints。 |
| `cover_letter_ready` | boolean | 是否具备真实求职信草稿的最低资料条件。 |
| `safe_fill_ready` | boolean | 是否具备单字段低风险 safe-fill 的最低资料条件。 |
| `live_smoke_ready` | boolean | 是否同时满足 matching、cover letter、safe-fill 和 work_rights_summary 的 live smoke 前置条件。 |
| `safe_fill_values` | array | 可用于 safe-fill 的字段名、source keys 和 value length；不记录完整明文值。 |
| `missing_requirements` | array | 还缺哪些条件。 |
| `optional_profile_gaps` | array | 不阻断 live smoke、但建议补齐的资料项，例如 education、availability、avoid roles、salary preference。 |
| `decision` | string | `ready_for_single_safe_field_live_smoke` 或 `blocked_need_real_candidate_profile`。 |
| `notes` | array | 不伪造资料、求职信仍需岗位证据等提醒。 |

`--fail-if-blocked` 会在 `decision` 不是 `ready_for_single_safe_field_live_smoke` 时返回退出码 `2`。真实 `--fill-safe-fields` 前必须先通过该检查。

## POST /action/click_text

设计目的：旧式 OCR 找文字并点击接口，主要用于简单调试和历史兼容。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `text` | string | 必填 | 要查找的文字。 |
| `roi` | object/null | null | 限制 OCR 区域。 |
| `partial_match` | boolean | false | 是否允许部分匹配。 |
| `enable_validation` | boolean | true | 点击后是否做通用验证。 |
| `max_retries` | integer | 3 | 最大重试次数，范围 `1..6`。 |

返回 `data` 字段：动作结果、OCR 匹配、点击点、验证结果和 trace。具体字段比 recognition plan 路径更旧，不建议作为新 Agent 主路径。

使用注意：新流程优先使用 `/vision/recognition_plan` 和 `/action/execute_recognition_plan`，因为它们有候选排序和点击前闸门。

## Agent Mode / Write Policy

以下字段可用于视觉与执行主链路请求：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `agent_mode` | string | 架构模式。`learn` 表示学习/建图，`execute` 表示执行当前命令。 |
| `learn_depth` | string/null | 学习深度。`fast` 产出 PathGraph draft；`deep` 会在 Observe 阶段额外产出 `path_graph_deep_review_v1`、`path_graph_delta_v1` 和 `element_memory_init_plan_v1`。执行模式为 null。 |
| `write_policy` | object | 写入策略，形如 `{path_graph, element_memory, trace}`。当前面板会用 `path_graph=false` 阻止响应自动写入导航路径图，执行接口会用 `element_memory=false` 阻止 instruction learning 写回；`trace=false` 会抑制 Observe/Locate/RecognitionPlan/ExecuteRecognitionPlan 的主 trace 写入。 |

默认策略：
- Learn Fast: `{path_graph: true, element_memory: false, trace: true}`
- Learn Deep: `{path_graph: true, element_memory: true, trace: true}`
- Execute: `{path_graph: false, element_memory: true, trace: true}`

## POST /action/click_mouse_tester_left_region

设计目的：MouseTester 专用诊断接口，用于早期固定页面回归。

请求：无。

返回字段：包含点击区域、点击结果、计数器变化、验证结果等 MouseTester 特化信息。

使用注意：这是专用 smoke/test endpoint，不是通用 GUI 自动化入口。

## 字段阅读顺序建议

调试一次失败定位时，建议按这个顺序读字段：

1. `success` / `error.code`：先判断是服务失败、输入失败、闸门拒绝还是验证失败。
2. `trace_path`：打开完整 trace。
3. `execution_path`：看实际经过哪些层，是否 fallback。
4. `ocr_result` / `ocr_anchors`：看文字和坐标证据是否存在。
5. `vision_regions`：看模型是否语义识别到目标。
6. `page_structure` / `screen_reading`：看融合层是否把目标建成可选元素。
7. `candidate_result`：看排序是否把正确候选排到前面。
8. `pre_click_decision`：看为什么允许或拒绝。
9. `selected_click_point`：只有这里有值，才表示自动执行链路有最终点击点。
10. `post_click_verification`：真实点击后看结果是否被验证。
