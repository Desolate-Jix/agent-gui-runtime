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

## POST /runtime/prepare

设计目的：给上层 Agent 一个“执行前准备”入口。调用它可以确认 runtime 本身可用，并按阶段检查/启动本地视觉模型服务。它不绑定窗口、不截图、不点击。

请求字段：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `start_models` | boolean | true | 是否自动启动不可达的模型服务。为 false 时只做状态检查。 |
| `stages` | array | `["observe","locate"]` | 要检查的阶段。`observe` 默认对应整屏理解小模型，`locate` 默认对应精准定位大模型。 |
| `wait_until_ready` | boolean | false | 启动模型后是否等待 `/v1/models` 变为可用。 |
| `wait_seconds` | number | 0 | 最大等待秒数，范围 `0..120`。 |

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
| `wait_seconds` | number | 0 | 最大等待秒数。 |

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
| `metadata` | object | `{}` | prompt override、OCR anchor 等扩展。 |
| `capture_live` | boolean | true | 是否从绑定窗口实时截图。 |
| `image_path` | string/null | null | `capture_live=false` 时使用的截图路径。 |

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `screen_observation_v1`。 |
| `screen_reading` | object | 读取层结果，结构同 `/vision/screen_reading`。 |
| `live_capture` | object/null | 实时截图信息。 |
| `suggested_state_hint` | string | 从模型 `state_guess` 压缩出的下一步定位提示。面板会自动填入精准定位 State hint。 |
| `agent_next_steps` | array | 建议下一步：选择具体目标、调用 `/vision/locate_target`、不要直接点击。 |
| `execution_path` | object | 是否使用视觉模型、page structure、screen reading。 |
| `trace_path` | string | observe trace。 |

使用注意：

- `suggested_state_hint` 不是最终目标，只是下一步 `locate_target.state_hint` 的默认建议。
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
| `execution_path` | object | provider、OCR、candidate rank、pre-click 等路径信息。 |
| `trace_path` | string | locate trace。 |

使用注意：

- `located_bbox` / `located_point` 不代表可自动点击；只有 `selected_click_point` 非空才是闸门批准的执行点。
- 对 `include_referenced_text` 的文本目标，如果视觉语义框里包含未引用 OCR 文本，融合层会写入 `unreferenced_text_contamination` 并将候选保持为 `precise_text_target` review 状态。
- `locate_target` 会把最佳 review 候选也带回给测试面板填候选框，方便人工生成 overlay 和确认坐标。

使用注意：

- `located_point` 不是自动点击点。
- 自动执行只能信任 `selected_click_point`，且一般应通过 `/action/execute_recognition_plan` 完成。

## POST /vision/recognition_plan

设计目的：生成完整 no-click 识别计划。它比 `/vision/locate_target` 更底层，暴露 OCR、视觉、page structure、screen reading、candidate rank、narrow search 和 pre-click decision。

请求字段：继承 `/vision/analyze` 字段，额外有：

| 字段 | 类型 | 默认值 | 作用 |
| --- | --- | --- | --- |
| `top_k` | integer | 5 | 候选数量上限。 |

返回 `data.result` 字段：

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `contract_version` | string | 固定为 `recognition_plan_v1`。 |
| `goal` | string/null | 目标。 |
| `vision_regions` | object | 视觉模型原始/标准化区域。 |
| `ocr_result` | object | OCR 结果。 |
| `ocr_anchors` | object/null | OCR anchors 证据。 |
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
| `trace_path` | string | action trace。 |

安全语义：

- `dry_run=true` 且闸门通过：`success=true`，但 `execution_path.action_executed=false`。
- 闸门拒绝：`success=false`，`error.code=pre_click_rejected`，不会点击。
- 真实点击后验证失败：`success=false`，但 `execution_path.action_executed=true`，需要读验证字段。

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
