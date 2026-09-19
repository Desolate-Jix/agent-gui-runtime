# Agent 接入与操作 / Agent usage — v0.1.0-test.3

本包只提供即时操作，不是学习桥。按用户指定的低风险任务使用本包接口，不使用另一套鼠标工具冒充本包测试。快捷入口使用管理员宿主且自动风险拦截关闭；一次只允许一个 Agent 控制桌面。付款、发送、删除、最终提交等不可逆操作不在本次测试范围。

Instant-mode operations only, not learning. Use this framework for the user's supervised low-risk task; do not substitute another input backend and claim package coverage. Quick setup uses an administrator host with automatic risk interception disabled. Only one Agent may operate the desktop. Payments, sending, deletion and final submissions are outside trial scope.

## 连接顺序 / Connection sequence

**解释器一致 / One interpreter:** MCP服务及OCR取证脚本都使用本包安装后的 `.venv\Scripts\python.exe`（Python3.11，`rapidocr-onnxruntime==1.4.4`）。不要使用PATH里的其他 `python`；旧OCR1.2.3不提供词级元数据。出现缺字符元数据错误时报告解释器路径和OCR版本，不跳过错误或改用整行框充当单词定位。 / Use the locked package venv for services and helpers; old OCR1.2.3 lacks word metadata. Report interpreter/version on this error instead of weakening geometry validation.

**客户端常见错误 / Client pitfalls:** `instant_submit` 返回 `pending` 不是操作失败或最终回执；只轮询原 request_id 的 `instant_result`，不要重复提交动作。已停止会话不会被默认 `instant_start()` 自动重开，需要显式 `new_session=true`。正常结束时，在断开 MCP 前用 `close_launched_window` 关闭本会话启动的测试窗口，再 stop 并轮询清理状态。 / Pending requires polling, not replay. Explicitly request a new session after stop; close session-owned test windows before stopping/disconnecting.

1. `instant_start(new_session=true)`，随后查询 `instant_status`，等 `phase=ready`。同一任务保持同一 MCP 连接；断连会触发宿主收尾。 / Start a fresh session, poll until ready, and keep one continuous MCP connection for the task. Disconnect initiates host cleanup.
2. `instant_submit` 提交 `discover`，使用同一个 request_id 轮询 `instant_result`，从回执读取真实窗口与应用目录。 / Discover real windows and app catalog; poll the submitted ID.
3. 按实际返回值 `launch` 或 `select`，再 `capture` 并取原图。`select` 会切前台，不猜 HWND/PID。 / Launch or select an observed target, capture, and inspect the original image. Selection changes foreground; never invent HWND/PID.

```json
{"request_id":"discover-001","command":{"kind":"discover"}}
```

`launch` 使用发现结果里的 app_id，可附 url；`select` 使用真实 handle、process_id；`maximize`、`capture` 针对已选窗口。`prepare_models` 可在连续任务前预热一次，`release_models` 释放模型。不要把每次冷启动耗时当成热启动点击耗时。

Launch uses an observed app_id with optional url; select requires real handle/process_id. Maximize/capture use the selected window. Prepare models once for a continuous task and release them when appropriate; cold-start timings are not warm-click timings.

## 单步输入 / Single-step input

每次只提交一个动作，回执返回并看图后再决定下一步。以下坐标仅为示例，必须替换为当前原始窗口截图上的像素坐标，不是桌面坐标或缩略图坐标。

Submit one action at a time, await the receipt and inspect images before proceeding. Example coordinates must be replaced using the current original window image, not desktop or thumbnail pixels.

```json
{"request_id":"click-001","command":{"kind":"step","operation":"execute_recognition_plan","request":{"goal":"Click the button labelled Search","task":"click_target"},"observation_wait_ms":2000}}
```

```json
{"request_id":"type-001","command":{"kind":"step","operation":"type_text","request":{"text":"Google Maps","x":500,"y":300,"click_before_typing":true,"clear_existing":true}}}
```

```json
{"request_id":"enter-001","command":{"kind":"step","operation":"press_key","request":{"key":"Enter","x":500,"y":300},"observation_wait_ms":2000}}
```

```json
{"request_id":"scroll-001","command":{"kind":"step","operation":"scroll","request":{"direction":"down","wheel_clicks":3,"x":500,"y":400}}}
```

`type_text.clear_existing=true` 显式替换已有内容，默认 false；不会自动回车或提交。`press_key.key` 精确支持：

`Enter`, `Tab`, `Shift+Tab`, `Escape`, `Backspace`, `Delete`, `Left`, `Right`, `Up`, `Down`, `Home`, `End`, `Ctrl+A`, `Ctrl+Z`, `Ctrl+Y`。

按键发给当前焦点；其 x/y 只用于窗口点校验，**不会点击或重新聚焦**。先通过截图确认焦点；切字段用 Tab/Shift+Tab。应用可能不支持撤销/重做，不把按键派发当作生效。不支持任意组合键、shell 或隐式 submit。

Explicit clear_existing replaces text; default false, without implicit Enter/submit. Keys above go to current focus. Their x/y do not click or refocus. Confirm focus, use Tab/Shift+Tab to change fields, and inspect results. Undo/redo support depends on the app. Arbitrary chords and shell commands are unsupported.

## 右击、双击和读取 / Right-click, double-click and reading

`request.click_kind` 为 `single`（默认）、`right`、`double`。右键只是打开菜单；查看原图后另发单击菜单项。双击只选目标词的效果必须看图确认，不能只看点击次数。 / Use single (default), right or double. Inspect the menu before a separate item click; verify actual word selection from images.

```json
{"request_id":"right-001","command":{"kind":"step","operation":"execute_recognition_plan","request":{"goal":"Right click inside the search input box","click_kind":"right"}}}
```

```json
{"request_id":"double-001","command":{"kind":"step","operation":"execute_recognition_plan","request":{"goal":"Double click the word Rotorua inside the search input box","click_kind":"double"}}}
```

```json
{"request_id":"read-001","command":{"kind":"read_text","max_chars":10000}}
```

`read_text` 的文字在 `receipt.result.text`，行框在 `receipt.result.lines`，原图信息在 `receipt.result.capture`；不是输入动作的 `response.data.result`。用同一request_id调用 `instant_image`。只读当前可见像素，`read_complete=false`不表示调用失败。 / Read results use the direct result/text/lines/capture contract, not the input-action envelope; retrieve the same ID's image. Visible pixels only; read_complete=false is not a command failure.

## 可恢复错误 / Actionable errors

- 非法字段返回 validation_rejected，包含字段位置/允许字段；原填写值不回显。修正参数后再提交，不退出连接或重复加载模型。
- 宿主未就绪、已有命令处理中或正在关闭时返回 state_rejected 和 next 查询指引，不把被拒请求写入执行队列。
- 多候选或无有效坐标会返回候选诊断；使用当前证据明确目标，不凭候选列表盲点。
- 已输入但后图采集失败时，回执保留 error_code 和 capture_current_state_without_replaying_input 指引；先单独 capture，不能假定尚未输入。

Malformed fields return structured validation errors without echoing input values. State rejections include the next status/result query and do not enqueue input. Ambiguous targeting returns candidate diagnostics. A post-input capture error calls for a separate capture, not another input attempt.

## Agent 判断结果 / Judge the outcome

### 回执取值 / Parsing receipts

先解析 MCP 文本块中的 JSON，不把调用方日志包装的 `parsed`/`value` 当成服务端字段。等待 `status=returned` 后，操作细节位于 `receipt.result.response.data.result`；错误或未完成回执可能没有这一层，先检查状态和错误。识别点击的 `selected_click_point` 为 `{"x":333,"y":132}`；`resolved_click_point.bbox` 为 `{"x":310,"y":123,"w":47,"h":18}`，**不是数组**。按键名读取，不能用 `[int(v) for v in bbox]`；那会把 `x` 等键名当数字。示例数字仅说明结构，不可作为操作坐标。

Parse the MCP JSON text, not client-log wrappers such as `parsed`/`value`. After completion, action details live at `receipt.result.response.data.result`; failed/pending receipts may omit it. Points and rectangles are named-key objects, not arrays. Never reuse these illustrative coordinates. For screenshots, prefer the top-level `receipt.agent_review.before/after` tool arguments; do not recursively pick the first matching diagnostic field.

### 自行裁剪和OCR取证 / Client-side crops and OCR

识别点击的上述矩形使用 `x,y,w,h`；`captured_text_v1.lines[].bbox` 则使用 `x,y,width,height`，按具体契约读取，不混用键名。例如 Pillow `Image.crop` 要求 `left,top,right,bottom`，将宽高转换为 `(x,y,x+w,y+h)`，并检查区域在当前原图内、宽高大于零。不能直接传 `(x,y,w,h)`，也不能把上一轮截图坐标用于新截图。 / Recognition rectangles above use `x,y,w,h`; captured-text line boxes use `x,y,width,height`. Follow the specific contract, then convert dimensions to Pillow `(x,y,x+w,y+h)`. Check positive dimensions and current-image bounds; do not reuse an older capture's coordinates.

外部OCR进程非零退出、缺输出或JSON解析失败是**取证工具错误**，必须保留退出码和stderr，不能转换为“未识别到文字”或产品操作失败。 / Nonzero exit, missing output or invalid JSON is an **evidence-tool error**, not empty OCR or a proven product failure.

判断文本选区时只看目标输入行；不要合并浏览器标题、正文中的同词框。右键菜单可能遮住原文字，菜单展开图不适合作为唯一选区基线：优先使用本次打开菜单前的原图和全选后的原图，菜单关闭仅作辅助证据。未确认选区就停止后续替换，但把原因准确区分为操作失败或证据不足。 / Scope selection checks to the input row. Use the current pre-menu image as the unobscured baseline, not solely the menu-open frame; separate action failure from insufficient evidence.

- `returned` / `operation_succeeded` 只说明命令与输入链状态，不证明任务成功。识别点击的 `verified=null` 与 `retry_reason=awaiting_agent_review` 表示等待你的判断，不自动重放。
- 读取 `instant_result.agent_review`，分别执行 before/after 中的 `instant_image` 参数。默认 `view=after` 兼容旧调用；原 PNG 不缩放且验证 SHA-256。
- 主证据对是 `before_input` / `after_settled`；内部诊断的 `before_immediate` / `after_immediate` 和 diff 是另一组帧，**不可混用**。主证据没有额外服务器 diff；等待后图不保证渲染结束。
- 根据目标和图像报告 success / failure / uncertain，并说明可见依据。没有变化可能是目标原本已选中；画面变化也不证明点中了目标。文字部分匹配不等于完整目标身份验证。
- `evidence_incomplete`、结果未知或图不可读时，不猜成功、不盲目重试；可单独提交新的 capture。Agent 结论保留在其会话，本版没有服务端判定写回工具。

Returned/operation_succeeded describes command/input handling, not task success. Retrieve both original frames via agent_review. Compare the primary before_input/after_settled pair against the goal and report success/failure/uncertain with evidence. Immediate diagnostic diffs belong to a different pair. No change can be valid; change alone is not success. Missing evidence requires inspection or a separate capture, not replay. Agent judgements remain in its conversation.

## 重连与结束 / Reconnect and stop

请求 ID 在会话内唯一。同 ID、同命令读取原回执；不同命令不得复用 ID。`pending` 继续查询原 ID，`result_unknown` 先检查现场，不能当作没执行。

先提交 `command={"kind":"close_launched_window","handle":本次launch返回的handle,"process_id":本次launch返回的process_id}` 正常关闭自己的测试窗口；不要填写用户原有窗口。随后调用 `instant_stop`，轮询 `instant_status`，直到 `cleanup_verified=true`，最后断连。第一次返回 false 可能只是仍在清理，不是终态失败。重连先用 `instant_start()` 附着历史；确实需要新任务且旧会话清理完成后才用 new_session=true。

IDs are unique per session. Reusing an ID retrieves its original receipt and never authorizes replay with different content. Poll pending IDs; unknown results may already have affected the target. Stop and poll until cleanup_verified=true. A transient false is not a final cleanup failure. Reattach before requesting a fresh session.
