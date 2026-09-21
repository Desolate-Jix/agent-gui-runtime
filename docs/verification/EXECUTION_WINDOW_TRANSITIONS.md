> **test.4 发布状态 / Release status (2026-09-21):** 本文契约实现已随冻结候选 10 交付。下文较早的“仅源码/待测试/test.3 未更新”描述保留为当时记录，不代表当前 test.4 状态。最新限定实测和未覆盖范围以 [FIXES.md](../../CHANGELOG.md) 为准。 / Implementation ships in test.4; earlier source-only/pending notes below are historical. Consult FIXES.md for current coverage and limits.

# 弹窗转换与输入收尾 / Window transitions and input cleanup

2026-09-20，源码修复，尚未进入公开 test.3 或冻结候选 07。 / Source-only repair; public test.3 and frozen candidate 07 are unchanged.

## 失败及通用修复 / Failure and common repair

1. **关闭等待不可诊断**：保存弹窗禁用父窗口，客户端却在 `window_close_pending` 后结束宿主。公共关闭接口现在只读枚举同 PID、确切 owner 链内的可见窗口，返回 `close_observation`、原窗口身份、`window_cleanup_verified=false` 和下一步提示；不自动保存、不保存或强杀。 / An owned save modal disables its parent. The common close API now returns a read-only same-process ownership observation and actionable pending state, without choosing save/discard or killing processes.
2. **点击已生效却报告失败**：Notepad05 点击保存已打开“另存为”，但即时事后观察默认尝试聚焦消失的旧弹窗，抛出授权错误，点击回执未进入结果。`Verifier.verify_action(judged_by_agent=True)` 现在只被动采集；采集异常作为 `capture_status=unavailable` 和原错误返回，保留点击回执，判定依然为 `null`，不自动重放。 / A real Save click replaced its bound dialog; active post-capture focus raised an authority error. Agent-reviewed observation is now passive and reports capture failure without erasing the returned click receipt or authorizing replay.
3. **回车后释放键失败**：Enter 按下已保存并关闭窗口，抬键却再次要求旧目标仍存在。公共键盘组合现在在同线程、同控制器、同次同步调用内，仅允许释放此次已授权尝试按下的键；每个释放单次消费，结束即撤销。下一次按下仍完整校验。 / Enter-down saved and closed the window, but key-up incorrectly required the old target. A narrowly scoped cleanup token now releases only keys attempted by this synchronous chord, on the same thread/controller; new key-downs retain their checks.

修复位置：`app/core/window_close.py`、`app/desktop_review/window_preparation.py`、`app/core/verifier.py`、`app/core/input_controller.py`。没有 Notepad 文案、窗口句柄或网站特判；适用于动作关闭或替换目标弹窗的其他应用。 / These common-layer changes contain no Notepad-specific labels, handles or site matching.

## 已验证 / Verified

- 先失败后修复的定向回归，最终 **217 项通过**：窗口关闭、编辑键、观察证据、MCP、即时观察/耗时及输入约束；集合不能换算成真实任务数。 / 217 scoped regressions pass; assertions are not real task counts.
- Notepad05 保留两条原始真实失败；Notepad06 在**同一 MCP/模型宿主会话、每轮新建窗口**连续执行两轮不同内容的输入、关闭请求、识别保存、填写唯一文件名、Enter 保存、文件逐字核验和关窗确认。两轮均保留成功的点击/按键派发回执，并完成文件及窗口效果复核；未重放失败输入。 / Original failures retained; two repeated real journeys in one host session pass dispatch/effect/cleanup checks, with a fresh window/document per round and no replay.
- 保存识别命令 **3.784 / 3.128 s**；Enter **1.042 / 1.043 s**（含 1 s 事后等待）；模型准备一次 **8.398 s**。两轮命令耗时之和 **18.651 / 7.537 s**，不含 Agent 看图与决策时间，不能当整体完成时间。 / Command timings exclude agent deliberation; model preparation occurred once.
- 15 份 `instant_image` 原图摘要与磁盘内容一致；新增 Notepad05/06 证据约 **4.77 MiB**。本轮三个测试文档只保存到各自证据目录，无已有文件覆盖；全部本轮窗口及宿主已清理。 / 15 image bindings verified; approximately 4.77 MiB of evidence. Generated documents saved only to unique test paths; owned windows and hosts cleaned.
- 复核产物：`reports/execution-cross-site-20260920/notepad56-reviewed.json`；只读复核脚本 `review_notepad56.py` 位于同目录。 / Read-only audit artifact and script record receipts, hashes, timings and source hashes.

## 调用方必须区分 / Caller contract and remaining limits

旧目标消失时原 `after` 仍然不可用，这是事实，不伪造新窗口截图。内层 `response.success=true` / `clicked=true` / `pressed=true` 仅证明输入派发；外层 `operation_succeeded=false` 仍可表示完整观察链未完成。不要据此重放。根据 `close_observation` 或重新 `discover` 读取新窗口身份，再明确 `select`、`capture`、`instant_image` 复核结果。 / A destroyed target has no after-frame. Successful dispatch can coexist with outer `operation_succeeded=false` for incomplete observation. Do not replay; discover/select the new target and inspect fresh evidence.

目前并未自动绑定新弹窗，也没有解决所有窗口转换后的证据接续。两轮同会话新窗口测试**不等于同一编辑窗口内撤销历史稳定**，也不能估算通用按钮准确率。重复粘贴/撤销、前台丢失、小目标双击及历史滚动缺帧继续开放。 / Automatic successor binding and full observation continuation remain open, as do undo history, focus loss, small-target double clicks and historical missing scroll frames.

这是输入释放和事实记录修复，不是新增自动安全策略；没有授权新按键、盲点或自动确认。 / This repairs cleanup/evidence, not new automatic safety policy, new-key authority or blind confirmation.
