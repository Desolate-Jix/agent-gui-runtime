> **test.4 发布状态 / Release status (2026-09-21):** 本文契约实现已随冻结候选 10 交付。下文较早的“仅源码/待测试/test.3 未更新”描述保留为当时记录，不代表当前 test.4 状态。最新限定实测和未覆盖范围以 [FIXES.md](../../CHANGELOG.md) 为准。 / Implementation ships in test.4; earlier source-only/pending notes below are historical. Consult FIXES.md for current coverage and limits.

# 前台诊断与取消关闭恢复 / Focus diagnostics and close-cancel recovery

2026-09-20：源码修复与实机对照，候选 07、公开 test.3 未改。 / Source-only changes and live contrast; frozen/public packages unchanged.

## 失败 / Failures

- 历史 `np4-key-24` 在按键前前台不匹配，错误只有一句文字，没有保留当时的实际前台 HWND；后续检查前台已恢复，无法反推是谁切走。事前图可见约 32% 遮挡，不足以识别焦点转移来源。 / Historical focus refusal lacked the contemporaneous foreground handle. Later recovery and partial occlusion do not identify the focus thief.
- 本轮 `notepad-focus01` 取消保存提示后，第二次明确关闭请求只等待，没有重新发出关闭。前后截图相同，状态 `window_still_present`。 / Cancelling a save prompt left close bookkeeping permanently pending; a new close invocation did not post another close.

## 违反的通用契约 / Broken invariants

1. 派发前已拒绝与派发后未知必须区分；诊断必须绑定拒绝当刻，而非事后重读。 / Distinguish proven pre-dispatch refusal from unknown effects and bind diagnostics to the rejection instant.
2. 同一关闭等待的去重不能永久阻止“弹窗退出后再次关闭”；查询旧回执不等于新动作。 / Deduplication within a pending close must not permanently disable a new close after modal dismissal; querying an old receipt is not a new action.

## 修复位置 / Common-layer changes

- `app/core/input_controller.py` 保存 `KeyboardForegroundMismatchError.evidence`：目标 HWND、观测前台 HWND、`before_keyboard_dispatch`；不取标题、不新增聚焦或重试。
- `app/desktop_review/local_keyboard_action.py` 仅在原生 `press_key` 派发前这个明确错误中返回 `keyboard_target_not_foreground`、`pressed=false`、`dispatch_status=not_dispatched` 和 `select_target_and_inspect_before_new_request`。部分派发或其他异常仍为 `key_dispatch_failed`，不能声称零输入。
- `app/desktop_review/local_direct_step.py` 保留 `phase=not_dispatched`，即使后图缺失也不把已知零按键改成未知；`automatic_retry_allowed=false` 不变。
- `app/desktop_review/window_preparation.py` 记录曾观测到归属模态窗口。后续新调用重新核验完整进程身份，且只有模态窗口消失、主窗口恢复可用、无归属窗口时才重新请求正常关闭。模态窗口仍在、隐藏等待、仅查询同一 MCP 请求均不重复关闭。

The shared input and coordinator layers now retain typed foreground evidence and distinguish a known no-key refusal. Close bookkeeping permits a new explicit invocation after an observed modal has gone and the original window is enabled again. No site-specific behavior, extra input backend or automatic key replay was added.

## 验证 / Verification

- 新测试先红后绿：原前台错误码与 `result_unknown` 不符合新契约；原取消关闭对照第三次调用仍 pending。修复后 193 项定向检查通过（不是全仓库测试数量或成功任务数）。 / New regressions first failed on the observed defects; 193 scoped checks pass, not a full-repository or task-success count.
- `notepad-focus01`：真实记事本保存提示把前台从 `7471262` 转到 `6096532`，新回执准确报告，拒绝前后原图字节一致。取消提示、重新选择主窗口后 Home 将光标恢复第一列；同轮发现取消关闭状态缺陷。该轮**正常关闭失败**；窗口只在 MCP 客户端退出后观察为不存在，不能算正常关窗通过。 / The first run verifies diagnostics/recovery but fails graceful closure; absence after client exit is reported separately.
- `notepad-focus02`：修复后的新连接完成输入、关闭、取消、重新选择、再次关闭（出现新保存提示）、保存新文件、确认原窗口消失。保存文件内容逐字节核验正确，随后宿主清理通过。 / Fresh corrected run completes cancel/reclose/save with file-byte verification and graceful window closure before host cleanup.
- 两轮 16 份原图摘要已复核，原始证据约 **1.445 MiB**。第二轮第一帧仍是启动过渡图，重新截图稳定后才输入，不算已解决启动渲染问题。 / Sixteen image hashes checked; startup-frame limitation retained, input began only after a settled capture.
- 命令 / Command: `.superpowers/sdd/2026-09-13-formal-release/.venv-clean-desktop/Scripts/python.exe -X utf8 -m pytest tests/test_keyboard_focus_diagnostics.py tests/test_launched_window_close.py tests/test_window_close_observation.py tests/test_local_editing_keys.py tests/test_text_input_guard.py tests/test_local_step_observation.py tests/test_post_action_window_transition.py tests/test_instant_mcp.py -q`
- 审计 / Audit: `reports/execution-cross-site-20260920/focus-close-reviewed.json`，由同目录 `review_focus_close.py` 读取原件核验。

## 影响与边界 / Impact and limits

这是公共 Windows 编辑/关闭契约修复，其他应用也使用同一实现，不依赖记事本文字或按钮位置。没有放宽前台、身份或点击检查，没有自动确认保存/丢弃；允许重新请求正常关闭不等于允许处理提示。仍由 Agent 看图决定效果。 / Shared behavior applies beyond Notepad; no focus/identity checks were loosened and no dialog choices are auto-confirmed. Effects remain agent-reviewed.

历史偶发前台丢失的来源、记事本同文重复撤销、启动过渡帧、小目标双击及历史滚动缺帧仍开放。关闭弹窗的 Escape/Enter 实际派发成功，但旧目标消失后观察不可用，外层 `operation_succeeded=false` 仍是已知边界，应重新识别窗口而不是重放。未完成广泛连续稳定性或新候选独立验收。 / Historical focus attribution, undo state, startup frames, small targets and missing scroll frames remain open. Post-transition observation can still be unavailable despite successful input; do not replay based on the outer failure flag.
