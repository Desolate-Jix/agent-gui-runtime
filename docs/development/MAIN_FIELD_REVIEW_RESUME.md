# 原主 Agent 审核输入后继续 / Main review of typed input

执行版 0.1.5 的输入审核续行合同。安装器、校验值及最终独立验收状态见[发布说明](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5)。此前未发布候选的受控注入证据单独保留。/ Execution 0.1.5 typed-input review and continuation contract. See the [release notes](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5) for the installer, checksums and final independent acceptance status. Earlier unreleased-candidate fault-injection evidence remains separately labeled.

## 问题 / Problem

Amadeus Pi 联调中，记事本文字已经正确输入，但 Decision 与普通 Luna 都未认可输入后的截图。旧代码把这个语义判断结算成整步失败，只能交回证据，不能审核后继续原计划。原失败保留，不改记成功。

During Amadeus Pi integration, Notepad contained the requested text, but both Decision and ordinary Luna rejected the after-image. The old path finalized the whole step as failed, leaving evidence but no continuation ticket. That failed run remains a failure.

## 修复合同 / Recovery contract

1. 只有可信模型非通过、原点击与文字输入均已结算、原截图与窗口绑定完整时，才在原命令工作线程等待 Main。未知派发、协议或鉴权失败不进入此通道。
   Only an authenticated model nonpass with settled click/type receipts and bound image/window evidence can park the original command for Main. Unknown dispatch, protocol and authentication failures do not qualify.
2. 返回原任务、步骤、执行 ID、原图、模型原结论、审核包与证据摘要。Main 使用现有 `task_plan.review`，提供结论及理由。审核本身不产生输入。
   Return the original task, step, execution ID, image, model decisions, review packet and evidence hashes. Main supplies a verdict and reason through the existing `task_plan.review` control. Review itself produces no input.
3. Main 通过后，调用原 `wait_id` 的 `task_plan.continue`。只输入的命令完成输入核验；含回车的命令接着执行未完成的提交后缀，保留既有重新锚定与动作门禁，不重复全选或输入文字。
   After approval, `task_plan.continue` uses the original `wait_id`. A type-only command finishes its input check; a command with Enter proceeds to its pending submit suffix through the existing re-anchoring and action gates. It does not repeat selection or text entry.
4. 原模型拒绝保持不变，主 Agent 审核有独立来源与记录。后续任务结果仍按原步骤合同核验。取消、关闭、证据变化、重复请求与重启均不能变成重复输入授权。
   Original model rejections remain unchanged, and Main review has separate provenance. Subsequent effects still use the original step verification contract. Cancellation, closure, changed evidence, duplicate requests and restart cannot authorize replay.

不新增全图像素一致要求，不修改模型阈值，不重写已经执行的原始回执。此改动复用原 Job、运行器、审核及继续命令，不新增桌面执行器。

This change adds no whole-screen pixel equality requirement, changes no model threshold and rewrites no completed action receipt. It reuses the original job, runner, review and continue controls rather than adding a desktop executor.

## 客户端取证 / Client evidence access

公共客户端将 `awaiting_field_review` 映射为 `review_required`，验证 `field_review_packet.v1` 的任务、步骤、执行、计划及证据摘要，不自动审核或继续。原执行仍未结束，不能用原执行 ID 调用只接受终态的 `instant_image`。应读取审核包绑定的 `after.image_path`，或先请求 `agent_command_status`，再用该次状态查询的外层请求 ID 获取附件。继续后若进入原整步结果审核，只接受同一任务、步骤、执行及计划且原输入已完成的审核包。

The public client maps `awaiting_field_review` to `review_required`, validates the task, step, execution, plan and evidence bindings in `field_review_packet.v1`, and never reviews or continues automatically. The original execution is unfinished, so its ID cannot be used with terminal-only `instant_image`. Read the bound `after.image_path`, or request `agent_command_status` and retrieve its attachment using that new outer request ID. After continuation, a whole-step review packet is accepted only for the same task, step, execution and plan with completed original input.

## 验证 / Verification

验证包括：双模型非通过、Main 审核后显式继续、仅回车后缀、无输入重放、取消、重复审核及继续、证据篡改与跨窗口拒绝。源码离线检查与真实 Pi/MCP 验收分开记录；最终结果见本轮验收报告，不能用合成检查代替实机成功。

Coverage includes two-model nonpass, explicit continuation after Main review, pending Enter suffix, no input replay, cancellation, repeated controls, evidence tampering and cross-window rejection. Offline checks and real Pi/MCP acceptance are reported separately; synthetic checks are not evidence of live success.

### 2026-10-15 最新实机结果 / Latest live result

用户恢复测试后，已安装的 Amadeus Pi 扩展在全新笔记中完成受控双拒绝 → 原 Pi 读取绑定 PNG → 原审核与明确继续 → 同一计划剩余菜单及保存 → 窗口和宿主收尾。8 项验收检查通过，独立只读核对确认输入只派发一次、原模型非通过未改写。详见[验收与限制](../verification/AMADEUS_PI_MAIN_REVIEW_20261015.md)。这是测试服务注入，不是模型自然误判或准确率、速度评测。

After the user resumed testing, the installed Amadeus Pi extension completed an injected two-model rejection, original-Pi PNG review and explicit continuation, the same plan's remaining menu/save steps, and window/host cleanup on a fresh note. Eight acceptance checks passed; independent read-only verification confirmed one input dispatch and unchanged original nonpasses. See [acceptance and limits](../verification/AMADEUS_PI_MAIN_REVIEW_20261015.md). These are injected test replies, not natural model errors or an accuracy/latency evaluation.

### 较早暂停时的记录 / Earlier paused snapshot

- 修复取消结算后，Main 运行的 6 个相关测试文件共 70 项通过。此前扩大检查为 26 个文件、560 项通过；两组有重叠，不能相加作为独立用例数。取消回归另有 83 项通过。
  After the cancellation-settlement fix, Main's six affected test files passed 70 checks. The earlier broader check passed 560 checks across 26 files. The groups overlap and must not be added as distinct cases. A separate cancellation regression passed 83 checks.
- 冻结的未发布执行载荷通过隔离入口及 649 个载荷文件的哈希核对。Amadeus 正式扩展 owner 已安装并应用 MCP＋Skill，Pi 实际读取了 Skill 并通过扩展调用 Runtime。
  The frozen, unreleased execution payload passed isolated entrypoint validation and hash checks for 649 payload files. Amadeus's real extension owner installed and applied MCP + Skill; Pi read the installed Skill and called Runtime through the extension.
- 本轮记事本前三步通过；第二次编辑在模型调用前因点击坐标采样不一致而停下，随后清理遇到窗口遮挡。用户确认正在使用电脑，因此本轮受到人工桌面活动影响，不能归因为已确认的 Runtime 自身缺陷。原失败不改记成功。
  The first three Notepad steps passed. The second edit stopped before model evaluation because cursor samples disagreed, and cleanup later encountered window occlusion. The user confirmed active desktop use, so this run was affected by human activity and does not establish an intrinsic Runtime defect. The original failure remains recorded.
- 已暂停桌面测试，保留原会话及待处理保存弹窗。新功能的原 Pi 审核、继续及完整收尾仍待实机验证；不得宣称双模型误拒后的原计划续行已经实测通过。
  Desktop testing is paused, retaining the original session and pending save dialog. Original-Pi review, continuation and full cleanup still require live validation; successful live continuation after two-model rejection has not been demonstrated.
- 已离线准备只对指定测试文字注入一次双拒绝的测试服务，8 项协议与边界检查通过，尚未启动。它用于确定性验证 Main 接管，不作为模型准确率或真实 API 延迟证据。
  A test-only service is prepared offline to inject one paired rejection for an exact test string. Eight protocol and boundary checks passed; the service has not been started. It validates Main handoff deterministically and is not model-accuracy or real-API-latency evidence.

本机证据 / Local evidence: `D:/AgentGUI-Projects/evidence/amadeus-pi-runtime-20261015-01/`，包括 / including `main-field-review-final.xml`, `field-review-cancel-green.xml`, `field-review-fault-proxy-green.xml`, `pi-field-review-live04-final.json`。此前受干扰的桌面样本已按用户要求排除出验收结论，原日志及连通证据保留。/ Earlier interfered desktop samples were excluded from acceptance conclusions at the user's instruction; raw logs and connectivity evidence remain.
