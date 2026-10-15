---
name: gui-execution
description: Execute an explicitly authorized Windows GUI task through the connected AgentGUI Runtime MCP, preserve original request and evidence identities, handle review without replaying input, and close owned windows and the Runtime session.
---

Read `references/runtime.md` before using the connected Runtime. Discover its actual tools and current schemas; Pi tool names may be namespaced or hashed, so never invent a tool name. This Skill supplies no tools, authority, executor, learning mode or shell route.

Keep one Runtime MCP connection throughout the complete authorized Work task. Confirm the operator's task scope and local-input setting; one input owner at a time. Start once, wait for ready, launch/select the intended window, use current bound observations, submit the actual task, and settle original receipts. A successful launch or asynchronous acknowledgement is not task success.

For pending, unknown, timeout, interrupted input or unavailable after images, keep the original request/run/command IDs and inspect their state. Never use a new ID to replay possibly executed input. The adapter accepts only execution 0.1.4 and 0.1.5 markers; the latter is an unreleased candidate, with formal installed acceptance still pending. The Runtime 0.1.5 candidate supports live `field_review_packet.v1`: request `agent_command_status` with `command_id=packet.execution_request_id` under a new outer request ID, then retrieve that status request's original image with `instant_image`; the original execution is still pending. Inspect its exact bound evidence, copy `caller_controls.review.request` and add only the actual verdict/reason, then use the separately returned continue recipe. Review confirms already-entered text; any submit suffix still uses normal Runtime gates and verification. Released 0.1.4 can instead produce a `field_review` with no resumable ticket; stop and report it. A handoff or version number is not a ticket. Do not manufacture hashes, wait IDs, success or a restart/replay.

Close only windows launched by this task using the returned launch handle/process identity. Resolve owned save dialogs only when that specific choice is authorized. Verify `window_closed` before `instant_stop`, then poll `instant_status` until the host is down, pending IDs are empty and cleanup is verified. Report task outcome separately from cleanup. A saved Pi conversation does not keep the MCP process alive across Work runs.

中文要点：仅执行当前明确授权的任务；保持同一连接和原始 ID；未知输入绝不重放；审核必须读原证据并使用实际返回的原票据，无票据就停报；只关闭本轮自有窗口并先验证，再停止与确认宿主清理。不要使用学习、shell 绕行或删除浏览器资料。
