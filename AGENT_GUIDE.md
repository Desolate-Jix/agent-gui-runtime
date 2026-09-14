# Agent 接入与操作 / Agent usage — v0.1.0-test.1

本包只提供即时操作，不是学习桥。按用户指定的低风险任务使用本包接口，不使用另一套鼠标工具冒充本包测试。快捷入口使用管理员宿主且自动风险拦截关闭；一次只允许一个 Agent 控制桌面。付款、发送、删除、最终提交等不可逆操作不在本次测试范围。

Instant-mode operations only, not learning. Use this framework for the user's supervised low-risk task; do not substitute another input backend and claim package coverage. Quick setup uses an administrator host with automatic risk interception disabled. Only one Agent may operate the desktop. Payments, sending, deletion and final submissions are outside trial scope.

## 连接顺序 / Connection sequence

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
{"request_id":"type-001","command":{"kind":"step","operation":"type_text","request":{"text":"Google Maps","x":500,"y":300,"click_before_typing":true}}}
```

```json
{"request_id":"enter-001","command":{"kind":"step","operation":"press_key","request":{"key":"Enter","x":500,"y":300},"observation_wait_ms":2000}}
```

```json
{"request_id":"scroll-001","command":{"kind":"step","operation":"scroll","request":{"direction":"down","wheel_clicks":3,"x":500,"y":400}}}
```

不支持 clear_existing、任意快捷键或 shell 命令。不得在失败时悄悄换成其他工具重复输入。 / No clear_existing, arbitrary hotkeys or shell commands. Do not silently repeat failed input through another backend.

## Agent 判断结果 / Judge the outcome

- `returned` / `operation_succeeded` 只说明命令与输入链状态，不证明任务成功。识别点击的 `verified=null` 与 `retry_reason=awaiting_agent_review` 表示等待你的判断，不自动重放。
- 读取 `instant_result.agent_review`，分别执行 before/after 中的 `instant_image` 参数。默认 `view=after` 兼容旧调用；原 PNG 不缩放且验证 SHA-256。
- 主证据对是 `before_input` / `after_settled`；内部诊断的 `before_immediate` / `after_immediate` 和 diff 是另一组帧，**不可混用**。主证据没有额外服务器 diff；等待后图不保证渲染结束。
- 根据目标和图像报告 success / failure / uncertain，并说明可见依据。没有变化可能是目标原本已选中；画面变化也不证明点中了目标。文字部分匹配不等于完整目标身份验证。
- `evidence_incomplete`、结果未知或图不可读时，不猜成功、不盲目重试；可单独提交新的 capture。Agent 结论保留在其会话，本版没有服务端判定写回工具。

Returned/operation_succeeded describes command/input handling, not task success. Retrieve both original frames via agent_review. Compare the primary before_input/after_settled pair against the goal and report success/failure/uncertain with evidence. Immediate diagnostic diffs belong to a different pair. No change can be valid; change alone is not success. Missing evidence requires inspection or a separate capture, not replay. Agent judgements remain in its conversation.

## 重连与结束 / Reconnect and stop

请求 ID 在会话内唯一。同 ID、同命令读取原回执；不同命令不得复用 ID。`pending` 继续查询原 ID，`result_unknown` 先检查现场，不能当作没执行。

结束调用 `instant_stop`，轮询 `instant_status`，直到 `cleanup_verified=true`。第一次返回 false 可能只是仍在清理，不是终态失败。重连先用 `instant_start()` 附着历史；确实需要新任务且旧会话清理完成后才用 new_session=true。

IDs are unique per session. Reusing an ID retrieves its original receipt and never authorizes replay with different content. Poll pending IDs; unknown results may already have affected the target. Stop and poll until cleanup_verified=true. A transient false is not a final cleanup failure. Reattach before requesting a fresh session.
