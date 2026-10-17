## Current availability / 当前可用状态

## 2026-10-17 Execution 0.1.5 refresh / 执行版 0.1.5 更新

The dated 0.1.5 refresh keeps the version number and existing model, prompts and action gates. For default v3 visual clicks, and authenticated completed visual Enter submissions within `input_sequence`, observation may finish before the original two-second deadline after a substantial change and three stable samples spanning at least 200 ms, with at least 400 ms elapsed overall. Focus/type waits remain zero. Stability only selects an observation; the same semantic verification must still pass. A semantic nonpass retains one read-only final observation at the original absolute deadline. An unchanged image reuses its assessment; changed evidence follows the existing Decision → ordinary vision review → Main path. No repeated input, new wait budget or HTTP/protocol retry is introduced.

本次日期构建更新沿用 0.1.5，模型、提示词和动作门禁不变。默认 v3 视觉点击，以及 `input_sequence` 中有完整真实 Enter 回执的视觉提交，在充分变化、三次稳定采样、稳定跨度至少 200ms 且总观察至少 400ms 后可以提前采图。聚焦／键入的默认等待仍为零。稳定只决定采图时机，结果仍需语义核验通过。语义非通过保留原绝对两秒截止后的单次只读末帧；同图复用原判断，变化图按原 Decision → 普通视觉复核 → Main 路线处理，不重放输入、不追加等待预算、不重试 HTTP／协议错误。

The Enter path binds the whole command, completed input proof, sequence ID, parent execution ID, final submit child ID/hash and after-frame geometry. A bare input-sequence kind or reanchor click cannot opt in. Explicit waits, native conditions, temporal content, learning/memory and nonvisual submit paths retain their contracts. Receipts expose `adaptive_wait` and, for Enter, `adaptive_submit` as evidence rather than action authorization.

Enter 路线绑定原完整命令、已完成输入证明、序列 ID、父执行 ID、最后提交子步 ID／摘要及后图几何。仅声明输入序列或回锚点击不能启用。显式等待、原生条件、动态内容、学习／记忆及非视觉提交保留原合同。`adaptive_wait` 和 Enter 的 `adaptive_submit` 是证据，不授予动作权限。

For eligible `external_api` v3 linear plans, the current result assessment may overlap exactly one next-step read-only grounding request using the same frozen after-frame. `TaskGroundingPrefetch` prepares and resolves grounding only: it cannot claim input, advance the plan or change windows. Only persisted predecessor success releases the result. The next job consumes it once through the existing claim, target freshness and action checks. Input sequences consume it only for their initial field target; subsequent reanchor/Enter phases cannot reuse it.

符合条件的 `external_api` v3 线性计划，在当前结果核验期间可用同一冻结后图并行定位下一步，最多预取一步。`TaskGroundingPrefetch` 只准备／解析定位，不申请输入、不推进计划、不切窗。前一步成功落账后才允许后一步消费；仍经过原有单次 claim、新鲜度和动作核验。输入序列仅首个输入框目标可消费，后续回锚／Enter 不复用。

Prefetch binds the process/owner, plan hash, predecessor, exact next command/attempt, source capture/hash and provider configuration. Cancellation, manual handoff, changed evidence, wrong identity, restart or shutdown invalidates it. Failed calls are retained and do not trigger a hidden retry. Discarded requests still count toward API usage. The host stores their request, provider usage, disposition and timing under `task-grounding-prefetch`; adopted requests also appear in the job's recognition calls and must be deduplicated in aggregate reports.

预取绑定进程／所有者、计划摘要、前步、后步完整命令／尝试、源图 ID／摘要及服务配置。取消、Main 接管、换图、身份变化、重启或关闭会使预取失效；错误保留，不隐式重试。被弃用的请求仍计入 API 消耗。宿主在 `task-grounding-prefetch` 保存请求、供应商用量、去向和计时；被消费的请求也出现在后续 job 定位记录中，汇总时按请求身份去重。

Source checks and multi-application continuous runs passed. Dated installer acceptance is recorded in the release notes; historical click-only measurements are not new Enter/prefetch performance evidence. [Measured scope and limits](../verification/EXECUTION_015_REFRESH_20261017.md) · [Implementation plan](../superpowers/plans/2026-10-17-execution-015-refresh.md) · [Earlier baseline](../verification/WAIT_AND_DECISION_LATENCY_20261017.md).

源码检查和多应用连续运行已通过，日期安装包验收由发布说明记录；旧普通点击测量不当作新 Enter／预取的性能证明，见上方实测范围、计划及历史基线。

**Original 0.1.5 frozen release code:** `6fa3c487da5710f1e86d7a93f484226c94b96c70`. Main can review authenticated nonpass evidence after settled typing and explicitly continue the original command without retyping; original IDs, images and submit-suffix gates remain required. The final installed independent check passed on its first attempt: **3 steps / 27.70161 s / 10 HTTP (7 Decision + 3 grounding)**, no Main override and full cleanup. Total tokens remain unknown because one usage record is opaque. [Final acceptance and limits](../verification/AMADEUS_PI_MAIN_REVIEW_20261015.md#final-independent-installed-acceptance--最终独立安装态验收); publication/checksums are handled in the [release notes](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5).

**原始 0.1.5 冻结发布源码：** `6fa3c487da5710f1e86d7a93f484226c94b96c70`。已结算输入后的认证非通过证据可由 Main 审核并明确续行原命令，不重复输入；原 ID、原图与提交后缀门禁继续有效。最终安装态独立检查首次通过：**3 步／27.70161 秒／10 次 HTTP（7 Decision＋3 grounding）**，无 Main override，完整收尾通过；一项用量不可读，因此总 tokens 仍未知。[最终验收及限制](../verification/AMADEUS_PI_MAIN_REVIEW_20261015.md#final-independent-installed-acceptance--最终独立安装态验收)，发布及校验值由[发布说明](https://github.com/Desolate-Jix/agent-gui-runtime/releases/tag/instant-v0.1.5)承接。

### Historical candidate checkpoint / 历史候选检查点

The following candidate/pending paragraph records the earlier checkpoint, superseded by the final acceptance above. / 下方“候选／待验收”段落保留较早检查点，不是当前状态，最终验收以上方为准。

**Execution 0.1.5 candidate (unreleased):** authenticated dual-model nonpass after settled typed input can wait for Main's bound-image review and explicit continuation of the same live command, without retyping. Use the returned review/continue controls; unknown input or missing tickets cannot be replayed. Formal 0.1.5 installed/independent acceptance is pending. [Contract](MAIN_FIELD_REVIEW_RESUME.md). / **执行版 0.1.5 候选（未发布）：** 已结算文字输入后的认证非通过判断，可等待 Main 读取绑定原图审核，再明确续原活跃命令，不重复输入。只用实际返回的 review／continue controls；未知输入或无票据均不能重放。0.1.5 正式安装态／独立验收待完成，见合同。

Execution **0.1.4 source supports nonempty linear caller plans without a fixed count**, retaining per-step validation, content budgets, original evidence/window bindings, cancellation and API/time budgets. Candidate01 exposed a separate eight-step receipt limit in the public client; it is repaired and offline verified. Frozen source02/candidate02 then completed a fresh-data 12+4-step run and cleanup. Notepad's two rounds belong to pre-repair source01; original 7-Zip failures remain recorded. Installed and independent acceptance are separate release-note results. See [current evidence](../verification/MULTI_APP_EXECUTION_20261015.md). / 执行版 **0.1.4 源码支持非空线性调用方计划，不设固定数量上限**，保留逐步校验、内容预算、原始证据／窗口绑定、取消及 API／时间预算。candidate01 暴露的公共客户端独立八步回执限制已修复并通过离线验证；冻结 source02／candidate02 随后完成新数据 12+4 步及收尾。记事本两轮属于修复前 source01，7-Zip 原始失败继续保留；安装态与独立验收由发布说明分别记录，见本轮证据。

**Installed 0.1.4 acceptance:** Main completed Notepad 3+3 steps and 7-Zip 6 steps; independent Sol completed fresh 3+3-step tasks. All five plans completed automatically. The same package passed isolated contracts, 0.1.3 upgrade/repeat-install checks and final temporary-install cleanup. See the linked multi-application report for the retained first failures and the empty test-directory cleanup required before the second uninstall. / **0.1.4 安装态验收：** Main 完成记事本 3+3 步及 7-Zip 6 步，独立 Sol 完成全新 3+3 步任务，五个计划均自动完成。同包通过隔离契约、0.1.3 升级／重复安装检查及最终临时安装清理；原始失败和第二次卸载前所需的空测试目录清理见上述多应用报告。

## Current target wording / 当前目标表达

`action.goal` 与 `field_goal` 只描述当前可见对象，保留所有必要限定条件；筛选条件和排序范围须明确。例如“主结果区中可见域名为 `curl.se` 的第一个匹配普通结果，排除广告与摘要卡片”，不同于“整个结果列表的第一条”。流程总目标放在 `plan.goal`，结果要求放在 `verification`，重试、接管与恢复规则由计划控制，不塞入目标语句。视觉定位和候选 Decision 使用同一目标；运行时不自动改写目标，也不使用模型候选名称代替目标。

Keep `action.goal` / `field_goal` to the current visible target while preserving every required qualifier. State filtering and ordering explicitly: the first matching ordinary result with visible domain `curl.se` differs from the first result overall. Put task objectives in `plan.goal`, expected outcomes in `verification`, and retry/recovery in plan controls. Grounding and candidate Decision receive the same target. The runtime does not rewrite it or substitute the candidate model label.

This is a caller-facing usage contract, not a semantic parser or additional model call. Frozen requests and prior failures remain unchanged. See [retained-image diagnosis](../verification/DECISION_TARGET_USAGE_20261013.md). / 这是调用契约，不增加语义解析器或模型请求，不改写冻结请求与历史失败。

Dated development-status checkpoints below retain their original limitations and pending statements; they do not replace the final 0.1.5 acceptance above. / 下方带日期的开发检查点保留当时的限制与待办表述，不替代上方 0.1.5 最终验收。

## 2026-10-12 默认纯视觉输入 / Default visual input

源码已实现，本轮整合回归与实测尚待完成。新普通执行提交默认使用截图与 Decision 核验字段，UIA 仅用于学习或显式原生路线；默认视觉输入不读取 UIA 字段、控件树或 OCR。阈值、窗口/坐标绑定、原始回执、取消和截止时间保持有效，旧冻结计划及回执不重新解释。路线切换不构成 `text_field_geometry_changed` 根因修复证明。见[视觉输入闭环](VISUAL_EXECUTION_INPUT.md)。 / Implemented in source; integrated regression and live checks for this batch remain pending. New ordinary submissions use screenshots and Decision for field verification. UIA remains for learning or explicit native routes; default visual input reads neither UIA fields/trees nor OCR. Existing thresholds, bindings, receipts, cancellation and deadlines remain, and frozen evidence is not reinterpreted. This routing change does not prove the native geometry defect fixed.

## 2026-10-11 未发布 task_plan.v3 / Unreleased task_plan.v3

V3 保留现有线性执行器，增加必填 `goal` 和 `completion`；completion 的 step_id 必须为最后一步，verification 复用 v2 可观察条件并冻结摘要。不能把“最后一次点击发出了”当作完成用户任务。最后一步和 completion 的完整 verification 一致时复用已有证明；不同则交原 Main 做只读最终审核，不再执行动作或默认追加 API。 / V3 adds a required goal and final-step completion contract to the existing linear runner. It reuses v2 verification shapes and freezes the snapshot. Identical complete verification reuses existing proof; otherwise the original Main reviews completion without another action or automatic API request.

下面仅示范已在搜索结果页的单步结构。启动前还需按普通入口选择窗口/会话、配置视觉服务和获准 Decision 条件，示例不代表任务已实测通过。 / This single-step example starts on an existing search-results page. Normal window/session setup and approved visual/Decision configuration are still required; it is not live acceptance evidence.

```json
{
  "schema_version": "task_plan.v3",
  "title": "Open the first Java search result",
  "goal": "Open the first ordinary result from the current Java search results page",
  "inputs": {},
  "steps": [
    {
      "step_id": "open_result",
      "action": {
        "kind": "click",
        "goal": "Open the first ordinary Java search result"
      },
      "verification": {
        "kind": "agent_judgment",
        "decision_condition": "The page from the first ordinary Java search result is loaded and its main content is visible."
      }
    }
  ],
  "completion": {
    "step_id": "open_result",
    "verification": {
      "kind": "agent_judgment",
      "decision_condition": "The page from the first ordinary Java search result is loaded and its main content is visible."
    }
  }
}
```

新 v3 的 click/input_sequence 自动绑定 `action_review_context.v1`，包含完整计划、run/step/attempt 和默认60000ms本次执行总预算。新普通执行提交中，无显式控件或学习目标的组合输入默认纯视觉替换，不读取 UIA 字段或 OCR；追加在启动校验时拒绝。UIA 仅用于学习或显式原生路线。完整计划仍用于本地认证和动作前审核，动作后仅审核当前声明条件与必要证据。旧冻结计划和回执不重新解释；新固定审核条件见[专用示例](../../configs/decision-profile.visual-execution.example.json)，业务结果条件还须获得明确许可。 / V3 binds each click/input sequence to full-plan review context and an attempt-level 60000ms budget. New ordinary untargeted sequences default to visual replacement without UIA/OCR field reads; append is rejected at start. UIA remains for learning or explicit native routes. Full plans remain locally authenticated and available for pre-action review; after-action review receives only the current condition and necessary evidence. Frozen plans and receipts are not reinterpreted. Fixed predicates are listed in the example profile; task-specific outcome conditions still need explicit permission.

V3 默认 `recovery_policy=intervention_v1`，旧格式省略时为 legacy。只有维护回执证明零输入才形成 `blocked_before_dispatch` 审核包；`after=None`，不伪造后图。原 Main 可以经公开 `recover` 发出精确绑定的恢复 click，或在证据充分且无需恢复动作时 `resume_pre_dispatch`；均绑定原 wait、step、execution_request_id、review_packet_sha256、evidence_set_sha256 和 assessment_round。恢复 click 另有 recovery_request_id、独立派发/结算回执；未结算或结果未知不得继续。 / V3 defaults to intervention recovery, while older plans default to legacy. Proven no-input waits preserve the before frame and have no fabricated after frame. Public recover/resume commands bind the original authenticated wait and review packet. Recovery clicks have separate receipts and must settle before continuation.

恢复后同一步使用新 attempt/执行ID，已完成前缀、原请求和失败回执均保留。重复请求幂等；一次恢复后仍受阻就暂停，不能自动循环。focus已点或Ctrl+A已发但正文未发属于部分输入，不能使用零输入恢复；未知动作先对账。取消会阻止新输入，尚在途的原输入仍需结清。 / Recovery creates a new attempt without replaying completed steps or overwriting failed receipts. Requests are idempotent; repeated obstruction pauses. Focus-only/selection-only effects are partial input, not zero input. Cancellation stops new dispatch but does not erase in-flight effects.

[完整图和恢复图](../superpowers/specs/2026-10-11-visual-execution-decision-flow-design.md) · [源码验证与限制](../verification/VISUAL_EXECUTION_DECISION_FLOW_20261011.md)。下方历史示例与已发布版本兼容说明继续保留；不能把此前的测试数量或耗时当成本轮验收。 / Historical examples remain below; their counts and timings do not validate this source change.

## 2026-10-11 通用动态内容 / Generic dynamic content

在 `task_plan.v2` 的click或提交式input_sequence步骤中声明：

```json
{"kind":"dynamic_content","target_description":"The main clock seconds digits","decision_condition":"The main clock digits visibly change during the observed interval.","render_grace_ms":500}
```

`target_description` 必须是非空字符串，最多1000字符，原值参与认证。`decision_condition` 必须得到profile的精确批准。复用下方视频三图时序、一次Decision及8秒预算，使用独立 `temporal_visual_change.v1` / `dynamic_content_binding.v1`。无API或always_main仍采三图交原Main；不接wait_policy。只证明指定内容变化，不证明任意业务目标完成。 / The target is a required authenticated string (up to1000 characters). Reuse the video sampling/budget with a separate generic schema and an exactly approved condition; no API still returns the evidence to Main. Target change alone is not general task success.

真实时钟45→46→47自动通过；静态文档三图相同正确未通过。视频单项5.234秒，其中HTTP1.758秒；完整流程、暂停/恢复与会话修复边界见[本轮证据](../verification/THREE_FRAME_DYNAMIC_CONTENT_20261011.md)。 / Scoped live positive/negative results do not establish a general accuracy rate or complete workflow acceptance.

# Temporary execution plans / 临时执行计划

## Unreleased three-frame video verification / 未发布的三图视频核验

仅在需要按目标视频画面变化核验播放时显式使用；原点击继续经过普通动作门禁。 / Use this explicit kind to verify target-video picture change; the original click retains ordinary action gates.

```json
{
  "schema_version": "task_plan.v2",
  "title": "Open and verify the intended video",
  "inputs": {},
  "steps": [{
    "step_id": "open_video",
    "action": {"kind": "click", "goal": "Open the intended first video result"},
    "verification": {
      "kind": "video_playback",
      "decision_condition": "The intended target video's picture changes across the three observations.",
      "render_grace_ms": 500
    }
  }]
}
```

原输入须已完成；`render_grace_ms` 结束后等至少1000ms采首张新图，再按至少500ms实际间隔采满三张，三图跨度至少1000ms，完成时刻均须小于8000ms。原 after 独立保留，不充当三张样本之一。采样与一次 Decision、采用共用原8秒预算，不重置预算；底层同步截图无法硬中断，晚返拒绝并保留实际耗时。 / Once input and render grace complete, wait at least1000ms for the first new capture, take exactly three samples at actual intervals of at least500ms, span at least1000ms and finish every sample before8000ms. The original after is separate. Sampling, one assessment and adoption share the existing8s budget; late synchronous results are rejected.

新路径不再额外定位播放器，不调用控件/OCR/播放时间观察，也不依赖本地进度分析成功。一次 Decision 只问目标视频内容画面在三张图间是否变化；有变化按播放处理，页面其他区域或按钮显隐不计入。该画面变化判据不证明音频、静止镜头持续播放或未来不中断。 / No extra player localization, controls, OCR, playback-time observation or local progress proof is required. One Decision checks target-video picture change, excluding unrelated page/control changes. This visual criterion does not establish audio, playback of a static scene or future continuity.

自动采用须由v2 profile批准同一确切条件，并保留可见错误与审核门禁。新 profile 显式配置 `after_action_pass_threshold:0.80`、`after_action_review_threshold:0.70` 后，条件满足达到0.80且needs_agent_review低于0.70才可在其他门禁通过时自动采用；省略这两个字段仍按旧规则，不能将全局 `pass_threshold` 改为0.8替代。 / Exact condition approval remains mandatory. Explicit new-profile after-action fields select the0.80 outcome and0.70 Main-routing thresholds; omission preserves legacy behavior and other gates.

可显式使用 `review_policy:"always_main"`，省略沿用adaptive。无 API 或always_main仍采三图交原 Main，不隐式启用服务。拒绝、不确定、预算耗尽或迟到均沿原审核路径处理，不重新输入或反复判断。此类型不接 `wait_policy` 或 `condition_binding`。 / No-API or always-main cases still collect three frames for the original Main without enabling an API. Refusal, uncertainty or exhausted budget retains original review and never replays input. This kind does not use static loading policies or condition bindings.

Runtime构造闭合的 `temporal_playback.v2`：`{schema,original_after,samples,selected_capture_ids,timeout_seconds}`；`samples` 恰为三项 `{frame,elapsed_ms}`，全部三图按序上传为 `sample_start/sample_middle/sample_end`。路径、SHA、PNG、窗口、尺寸、时间与原 after 在采用端认证；原 after 不上传。当前 `review_packet.v4` 保存原 after 及三张时序图，`instant_result(images="after")` 交付原图而不重采，审核和续行使用原请求/原 wait。 / Runtime builds the closed v2 context and uploads all three ordered authenticated samples. The original after is authenticated but not uploaded. V4 image delivery reads the original evidence; review/continuation retain the original request and wait.

视频v1仅历史兼容；旧7.797s/6.990s属于旧实现，当前限定正负例与剩余验收范围见上方最新记录。 / Historical timings do not validate the new path; current scoped results and limitations are linked above.

**2026-10-09: preview.3 bounded execution plans.** Execution `0.1.2-preview.3` and optional learning `0.1.0-preview.3` use separate installers under `learning-v0.1.0-preview.3`. Scoped source acceptance passed Main and independent Sol; Main also passed the new installed execution and learning journeys. See the [release record](../verification/CONTINUOUS_EXECUTION_RELEASE_20261009.md) for final installed-independent/publication status and [source evidence/limits](../verification/CONTINUOUS_EXECUTION_ACCEPTANCE.md) for measured scope. / **preview.3 有界执行计划。** 源码限定验收与 Main 新安装版实机通过，最终独立及发布核对按本轮记录，旧 preview.2 结果不转计。

## Purpose / 用途

The caller submits a bounded plan once. The existing WorkflowRunner schedules original gated commands and advances after a declared outcome is verified. `source_kind=caller_plan` does not create a reviewed learning asset or require the learning workbench. Saved learned programs retain their original backend. / 主 Agent 一次提交短计划，由现有运行器、队列和动作门禁连续调度。临时计划不是已审核学习资产，不要求安装学习工作台。

New ordinary execution uses the selected local model, external vision API or client Agent for visual grounding and screenshot-based field checks. UIA remains for learning or explicit native routes; explicit structured targets can use a unique current native match. Decision supplies judgments, not coordinates, extracted values or permission. With `agent_delegate`, the client must still resolve genuine grounding waits using the same visual worker; the host cannot invoke a Codex subagent. / 新普通执行使用已选本地模型、外部视觉 API 或客户端 Agent 定位，并由截图核验字段。UIA 仅用于学习或显式原生路线；显式结构化目标可使用当前唯一原生匹配。Decision 不代替定位、读值或授权，委派识图仍由客户端复用同一子会话。

Local grounding is optional; external API/current/delegated Agent routes need no local weights. Decision configuration remains explicit: no profile means no API connection even if a key exists. Default visual input without an adoptable Decision stops for the existing Main; it does not switch implicitly to UIA or type blindly. Explicit native routes retain their local-proof contracts. / 本地识图可选，视觉 API/当前或委派 Agent 路线无需本地权重。Decision 仍须显式配置；无 profile 时不因环境中有 key 自动连接。默认视觉输入缺少可采用的 Decision 时停止并交回原 Main，不隐式改走 UIA 或盲输；显式原生路线保留原本地证明合同。

## Request / 请求

Submit through `instant_submit` or `instant_run` with a fresh outer request ID:

```json
{
  "kind": "task_plan",
  "request": {
    "action": "start",
    "plan": {
      "schema_version": "task_plan.v2",
      "title": "Open the details panel",
      "inputs": {},
      "steps": [{
        "step_id": "open_details",
        "action": {"kind": "click", "goal": "Open detail"},
        "verification": {
          "kind": "native_condition",
          "condition": {"text": "Detail panel", "control_type": "Text"}
        }
      }]
    }
  }
}
```

This is the preserved v2 compatibility example; the new v3 route is documented above. Published preview.3 uses the same basic example with schema_version changed to task_plan.v1 and, when Decision is configured, the [legacy v1 profile](../../configs/decision-profile.legacy.example.json); v2-only fields are unsupported there. Existing explicit v1 plans and frozen sessions are not upgraded. These default changes are not packaged, released or hot-loaded. / 此为保留的v2兼容示例；新v3路线见上方。已发布 preview.3 应将此基础示例的 schema_version 改为 task_plan.v1，并在配置 Decision 时使用 legacy v1 配置，不接受 v2 专属字段。显式旧 v1 计划及冻结会话不自动升级；当前默认调整未打包、未发布、不热更新。

This example describes a schema, not permission to click an arbitrary application. Select the intended window first. Start freezes handle, PID and process creation time; each dispatch rechecks them. Agent vision routes additionally require `request.vision_capabilities` using the existing ClientVisionCapabilities fields. / 示例只说明结构；先选择目标窗口，开始时固定完整进程身份，逐次派发前核对。Agent 视觉来源另须声明既有视觉能力。

The 0.1.4 runtime accepts a nonempty list of linear steps with unique `step_id`, explicit action and verification; there is no fixed step-count cap. Context-size limits, per-step checks, evidence binding, cancellation and API/time budgets still apply. Existing 0.1.3 installations retain their build-time contract until explicitly upgraded; source live evidence and installed acceptance remain distinct. / 0.1.4 运行时接收非空线性步骤列表，每步具有唯一 `step_id`、明确动作和核验条件，不设固定步数上限。内容大小限制、逐步校验、证据绑定、取消和 API／时间预算仍有效；已有 0.1.3 安装在明确升级前保留构建时协议，源码实机证据与安装态验收分别报告。

| Action / 动作 | Fields / 字段 |
| --- | --- |
| `click` | `goal`, optional `click_kind=single` or `double`, optional `target` |
| `input_sequence` | `field_goal`, `text`, explicit boolean `clear_existing` and `submit_search`, optional `target` |
| `read_text` | `goal`; observation requires explicit Agent review / 读取观察需 Agent 复核 |

Text accepts a string, `{source:"constant",value:"..."}`, or `{source:"input",name:"..."}` referencing an explicit string input. Other input values may be finite numbers or booleans. Missing parameters are rejected before dispatch. Raw coordinates, arbitrary commands, branches, loops, `target_memory`, output references and extraction specifications are unsupported in this slice. / 文本只来自常量或显式字符串输入，不猜参数；初期不支持裸坐标、任意命令、分支循环、学习定位引用和动态输出数据流。

An optional semantic target has `name`, `control_type` and an optional `container` containing its own `name` and `control_type`, for example `{"name":"Find records","control_type":"Button"}`. It accepts no coordinates, runtime IDs or caller capture bindings. Click types are `Button/Hyperlink/Edit/ComboBox/MenuItem/TabItem`; input targets are `Edit/ComboBox`; containers are `Window/Pane/Group/Custom/ToolBar/Menu/Tab`. / 可选 target 只声明名称、类型和祖先容器，不接受裸坐标、RID 或调用方截图绑定。

This route requires the current complete bound-window UIA tree and the live full-window screenshot from the original action gate. A unique semantic match skips visual inference with source `windows_uia`; missing or ambiguous targets retain their semantics in the selected visual route and must still bind to a matching current control. Provider errors, stale images, incomplete trees, wrong windows and unproven target semantics refuse input. Field writability and all original gates remain required. Model service startup is unchanged; skipping inference does not promise skipping startup. / 当前完整树与本次全窗图绑定后，唯一命中免视觉推理；缺失或歧义仍保留语义，无法证明目标时拒绝。模型服务启动逻辑不变。

## Verification / 核验

- `native_condition`: click or search-submit transitions only. Original receipts must prove a newly observed unique stable UIA marker and a rechecked after image. Timeout enters review. / 仅点击或搜索跳转；核对原唯一稳定标记与后图，超时进入复核。
- `agent_judgment` without a semantic condition (neither `decision_condition` nor an unreleased v2 `condition_binding`): explicit Agent review. / 未声明判断条件时等待 Agent 复核。
- `agent_judgment` with `decision_condition`: reuse the original after image and shared Decision service. Absent/off stays inactive; shadow retains review. Auto adoption requires exact allowlisting and authenticated results. Unsupported for `read_text`. / 使用原后图与共用服务；未配置或关闭不调用，影子模式保留审核，自动采用须满足白名单及认证，不用于动态读取。

The declared condition must prove the intended step outcome. A player being visible does not prove playback/audio. An intermediate success is not complete task success. / 条件须足以证明步骤目标；播放器出现不等于播放成功，中间步骤也不等于整个任务成功。

## Controls / 控制

All controls use `kind=task_plan`:

| `request.action` | Required fields / 必填字段 |
| --- | --- |
| `status` | `run_id` |
| `continue` | `run_id`, original `wait_id` |
| `cancel` | `run_id` |
| `review` | `run_id`, `execution_request_id`, `step_id`, `verdict=success\|failure`, `reason`, original after-image `evidence_sha256`; v2 also requires current `review_packet_sha256`, `evidence_set_sha256`, `assessment_round` / v2 另绑定当前审核包及实际轮次 |

`instant_status` exposes `task_plan_run` and `task_plan_runtime_error`. The original start receipt is immutable. `LearningBenchmarkClient.run_plan` submits once and polls this read-only projection; it does not enqueue repeated `task_plan/status` controls while an action is pending. It returns `status_source=instant_status` and retains the original `request_id`/`start_receipt`. At `grounding_required`, use `active_command_id` and the existing original Agent command protocol; do not resubmit start. / 客户端一次提交后轮询只读投影，不在原动作 pending 时反复排队查询；原 start 回执和 request_id 保持不变，定位等待沿原命令协议续接。

Control receipts report `operation_success_scope=task_plan_control` and contain no action image. Read original images using the actual execution request ID; control acceptance is not task completion. / 控制回执不携带动作图像，须使用实际执行 ID 读取原图；控制请求返回不等于任务完成。

Review requires `verification_required` and a proven terminal input receipt. It settles the original ticket only; then use `continue` with the retained wait ID. Unknown/partial input cannot be reviewed into success. Cancellation stops future steps while retaining actual effects and unresolved evidence; it never silently replays. / 复核只结算原票据，之后显式继续；未知或部分输入不得补记成功，取消保留副作用和待决证据。

In unreleased source, recognition-plan failure and a read-only text-focus rejection before the first click dispatch carry explicit, internally consistent no-dispatch proof. The common local receipt, sequence, learned workflow and terminal inspector preserve `phase=not_dispatched` and `action_executed=false`; the original plan runner can settle failure/cancellation and release its competing-input gate. Entering `click_point` does not itself prove an input occurred or did not occur: unconfirmed outcomes remain unknown, and a confirmed click stays true even if later verification fails. Empty attempt lists and nested false values cannot replace dispatch evidence. Incomplete/conflicting proof and legacy unknown receipts are not reclassified. This does not add cross-host/epoch recovery or turn an unknown effect into success. / 未发布源码为识别阶段失败及首次点击前的只读字段拒绝提供严格未派发证明，公共回执、组合序列、学习工作流与终态检查共用判定，原运行器可结束已知失败/取消并释放互斥门禁。进入点击入口后未确认的结果保留未知，确认输入后即使核验失败也保留true；不再凭空attempts或嵌套false推断零输入。不改旧未知票据，不新增跨宿主恢复。

普通start在runner活动锁内通过门禁后才创建trial；已有审核等待未continue时拒绝，不残留ready计划。复核结算与runner继续仍是两个显式步骤。 / A rejected ordinary start now leaves no active trial: creation follows admission under the runner lock. Review and original-wait continuation remain separate explicit operations.

`cancel_requested` is transitional even when it retains the old verification wait. `run_plan` keeps polling `instant_status` until the runner settles or the caller's timeout expires; timeout returns `client_state=pending` with the actual cancellation state and original IDs. A validated review may advance the trial history while the runner still holds the original wait. The client returns `client_state=continue_required`, retaining that wait ID without another review callback or automatic input. Only an explicit `continue` settles the runner and permits subsequent steps. / `cancel_requested` 即使保留旧审核等待也只是过渡状态；客户端只读轮询至真实结算或超时，超时保留实际取消状态与原 ID，不冒称已取消。合法复核后历史可先推进，而运行器仍持原等待；客户端返回 `continue_required`，保留原 wait ID，不重复审核回调、不自动输入，须显式继续后才结算运行器并允许后续步骤。

## Adaptive v2 source (offline verified) / 主动审核 v2 源码（离线通过）

The following is development source, not the published preview.3 contract. Earlier frozen-source results and later repairs have separate evidence in the [current acceptance record](../verification/ADAPTIVE_REVIEW_LIVE_20261009.md); none substitutes for a complete final candidate. The current testing batch is approved, with its paid request cap exhausted. Final continuous, loading and installed/independent gates remain incomplete. V1 remains supported. / 以下为开发源码，非已发布preview.3合同；各冻结源码及后续修复分别留证，不能代替完整最终候选。本批测试已批准，付费额度已用尽；最终连续、加载及安装/独立门槛仍未闭合，v1继续支持。

New source callers explicitly use `schema_version="task_plan.v2"` as the default plan protocol. The same linear action structure, input ownership and window binding apply; the original step-count restriction has been removed in current source. An `agent_judgment` verification may additionally declare `allowed_states` (up to 32 nonempty strings, each up to 1000 characters). Omit step `review_policy` to inherit the adaptive host default; the only explicit step override is `"always_main"`, which cannot weaken the frozen host policy. Semantic adoption requires an enabled `decision_profile.v2` and exact condition/template approval; auto mode does not approve conditions or pending learning drafts. An enabled v1 provider with a v2 plan returns a review wait without a paid request. / 当前源码新调用默认显式采用 v2 计划协议，维持原动作范围；可声明有限允许状态。单步省略 review_policy 沿用宿主 adaptive 默认，只可显式设 always_main 收紧，不能传 adaptive 或弱化冻结策略。语义采用仍须已启用的 v2 配置及精确条件/模板批准，auto 不批准条件或 pending 学习草稿。v2 计划与启用的 v1 判断策略组合零调用等待，不静默付费后再拒绝。

V2 caller plans keep the string-shaped `step_goal` and `remaining_plan` contract, but each string is a deterministic compact JSON step summary containing the step ID, action kind/goal, input parameter reference (or explicit literal/constant redaction), input flags/click kind and declared verification condition. No resolved input values or arbitrary target metadata are copied. Empty `allowed_states` means no extra state list was declared, not that every visible state is forbidden or that any new action is authorized. / v2临时计划保留字符串字段，内容为确定性紧凑JSON步骤摘要；包含步骤ID、动作、参数引用或隐藏标记、flags和声明验证条件，不复制解析后输入值及任意目标元数据。空allowed_states表示未声明额外状态，不能解释为全部禁止或新增动作授权。

After all step structures validate, v2 admission preflights each context with the same normalizer used by the provider: current summary≤4000 characters, each remaining summary≤2000, total≤64KiB including the real74-character source ID. Oversize is rejected before any command is queued; no silent truncation. Long goal/condition combinations accepted by older development source may need shortening. V1 remains unchanged. V2 summaries enter authenticated bindings/hashes: finish or cancel active runs on their original frozen runtime and start a new run after upgrading; do not recompute old evidence with this projection. / 全部步骤结构验证后，v2入队前以请求同一normalizer检查当前4000字、后续单项2000字及整体64KiB（包含74字符source_id）；超长明确拒绝、不静默截断。部分旧开发源码接受的长组合需缩短；v1不变。v2摘要参与认证与哈希，升级前用原冻结运行时终结或取消活动运行，升级后新开运行，不用新投影重算旧证据。

One request can judge both the visible outcome and whether Main should intervene. `verdict=success` with `disposition=review_required` does not settle the step or dispatch the suffix. An enabled v2 global `always_main` policy applies in auto/shadow and pauses complete native proof without a Decision request; global off preserves the local path. Explicit step `always_main` still tightens policy independently. / 结果成功与可继续独立；启用v2全局逐步审核在auto/shadow均覆盖本地成功且零API，global off保留原路径；单步明确always_main独立收紧策略。

At a v2 verification wait, `instant_status.task_plan_run.review_packet` binds original run/step/execution/wait IDs, frozen plan/context, original input facts, source and evidence references/hashes, assessment summary and policy/profile. The original path uses `review_packet.v1` and round 0; the observation extension below uses `review_packet.v2` and the actual current round. The client returns `client_state=review_required` to the existing caller instead of creating a Main session. / v2 审核包固定原上下文及证据，通过已有客户端交回主会话；原路径保持 v1 包，第 0 轮；追加观察使用 v2 包和实际轮次，不自动新建会话。

The v2 `review` control requires the original fields in the control table plus:

```json
{
  "review_packet_sha256": "<current packet.packet_sha256>",
  "evidence_set_sha256": "<current packet.evidence_set_sha256>",
  "assessment_round": 0
}
```

Read and review the original evidence first. Successful review only settles the original ticket; `continue` still needs its original `wait_id`. A stale packet, changed source/evidence, cancellation or unresolved input cannot be converted into a successful effect by review. / 审核后仍须明确 continue；过期包、被改证据、取消及未决输入不能补记成功。

### Caller control parameters / 调用方控制参数

**2026-10-14 unreleased source repair / 未发布源码修复。** At a supported packet-based review wait, read `instant_status.task_plan_run.caller_controls.review`, or `result.caller_controls.review` in the current `instant_run`/`instant_result` control receipt. Copy its `request` exactly, inspect the original evidence and current packet, then add the caller's explicit `verdict` (`success` or `failure`) and nonempty `reason`. The projection never supplies either decision. The existing benchmark client's compact plan output retains the same projection. / 支持的审核等待直接提供当前绑定参数；复制 `request`，核对原证据和当前包，再由调用方明确补上结论与理由，精简客户端结果也保留该字段。运行时不代填结论。

```python
review = snapshot["caller_controls"]["review"]
request = {**review["request"], "verdict": caller_verdict, "reason": caller_reason}
command = {"kind": "task_plan", "request": request}
```

`review.request` includes `action`, `run_id`, `step_id`, `execution_request_id`, original after-image `evidence_sha256`, current `review_packet_sha256`, `evidence_set_sha256` and actual `assessment_round`; `caller_supplied_fields` lists `verdict` and `reason`. `wait_id` belongs to `continue`, not `review`. Even after a manual observation, `evidence_sha256` remains `review_packet.after.sha256`; the latest observation changes the packet/evidence-set bindings, not that original-image binding. / 审核参数绑定原后图与当前包及实际轮次；不要加入 `wait_id`，也不要以最新观察图摘要替换原后图摘要。

Only after a successful bound caller review does `caller_controls.continue.request` appear. Submit that request separately to retain the original wait ID. There is no review/continue recipe during execution, automatic observation, unresolved manual capture, unknown/partial input, pre-dispatch obstruction, cancellation, failed review or terminal runner state. Failed review still records failure; cancel/closure remains explicit. / 成功审核后才提供原 wait 的独立续行参数；执行中、自动观察、未决采集、未知或部分输入、派发前阻塞、取消、失败审核及运行器终态不生成此配方。失败审核仍记录失败，取消和收尾仍须显式处理。

`caller_controls` is an unsigned status projection outside `review_packet`, so existing packet bytes and hashes are unchanged. It neither approves evidence nor grants input permission; the original evidence, stale-packet, ownership and action gates still run on submission. Invalid control fields return actionable `missing_fields`, `unknown_fields` and `allowed_fields` without logging submitted values or queueing input. / 参数投影不写入签名包、不授予权限；提交仍走原认证与门禁。字段校验明确列出缺失、未知和允许项，不记录提交值，也不入队动作。These source/offline checks are separate from installed/live acceptance. / 源码离线验证与安装及实机验收分别报告。

### Declared-loading observations (unreleased source) / 已声明加载状态的观察（未发布源码）

**2026-10-10 source addition, offline verified / 新增源码，离线已验证:** v2 `agent_judgment` verification may explicitly set `render_grace_ms` to an integer in `[0, 2000]` only for a click or `input_sequence` with `submit_search=true`, alongside a valid `wait_policy` with `completion_excludes_loading=true` and a declared semantic condition. `0` captures the first post-action frame without the fixed two-second pre-observation sleep; it does not certify navigation. Decision still evaluates the original result and declared loading state, then uses bounded read-only observations or returns the original Main wait. Without Decision, the original Main reviews that earlier image. Earlier capture can add an observation/API call on slow pages; speed and accuracy require comparison. Omission preserves existing command hashes and wait behavior; native conditions retain their original bounded early-completion probe and do not accept this override. / 仅点击或提交搜索的输入序列可设置；必须声明加载状态与互斥的完成条件。显式设0只提前采图，不宣称跳转成功；仍按Decision/原Main审核及加载观察合同结算。慢页面可能多一次观察或请求，收益待测。省略字段保持旧计划语义；原生条件沿用已有提前完成探测。见[本轮离线记录 / Offline evidence](../verification/LUNA_EXECUTION_OFFLINE_20261010.md)。

The exclusion declaration must agree with the actual completion text: visible partial results during active search are not completion. Describe an observable finished state and the corresponding loading state, rather than asking a still image to prove future layout stability. Write the exclusion into the caller completion condition itself where necessary; the flag constrains assessment aggregation and does not supply missing observable facts. Independent loading/error/review predicates and the original input freshness gate remain in force. / 互斥声明须与完成文字一致：搜索中已出现部分结果不能算完成。应声明当前可见的完成事实及对应加载状态，不要求静态图片证明未来布局稳定。必要时把排除状态直接写进调用方完成条件；该标志约束评估聚合，不能补出未声明的可见事实。独立加载/错误/审核谓词及原输入新鲜度门禁仍保留。

The observation extension was included in the earlier offline combination. Source-level Bilibili playback trials on 2026-10-11 now verify declared loading, two bounded read-only captures and one additional Decision, without replay or Main review at that playback step. This does not validate every site, the render_grace_ms override or a packaged release. See [live evidence](../verification/LUNA_EXECUTION_LIVE_20261011.md). A v2 agent_judgment step with a decision_condition can explicitly add: / 早期组合为离线证据；本轮源码实机已验证声明加载后的播放自动核验，未推广为所有网站、提前采图收益或安装版验收。v2语义步骤可显式增加：

```json
{
  "kind": "agent_judgment",
  "decision_condition": "The requested document title is visible in the detail page.",
  "wait_policy": {
    "loading_condition": "A loading indicator is visible in the document detail area.",
    "completion_excludes_loading": true
  }
}
```

This requests a fourth predicate in the same initial Decision request. Only an authenticated, eligible auto-mode `uncertain + observe` result starts read-only observation; shadow only records advice. Error, conflict or Main-review signals stop automatic continuation. The condition still needs exact allowlisting. / 第四个问题和初次判断一起发送；只有合规自动模式的观察结果进入等待，影子模式只建议，错误、冲突或需接管时停止自动继续。

The same runner retains the original input ticket across ticks. It permits at most two additional captures at the 0.5/1.5-second slots after entering observation, skips expired slots instead of catching up, and makes at most one further paid assessment with changed new evidence. The whole observation step permits at most two requests, subject to the host cap and a 12-second scheduling/adoption budget including initial judgment time. The current owned HTTP transport applies the remaining network deadline; native capture/local I/O are not hard-interruptible, and late results cannot authorize automatic continuation. / 同运行器跨 tick 保留原票据，最多两次追加截图、一次追加付费判断；观察总预算包含初次判断。当前自有 HTTP 传输施加剩余网络截止，截图和本地 I/O 不冒称可硬中断，迟到结果不自动采用。

While `observation_pending=true`, the client only polls; it does not ask Main to review an unfinished evidence revision. Original after-image evidence is preserved; new captures and operation claims are separate immutable records under `session/task-plan-observations`. New assessments authenticate `assessment_context`, original receipt SHA and the input evidence-set SHA. Input hashes exclude the assessment being created, while the final review packet includes the complete artifact references. / 观察期间只轮询；原后图不变，新图和操作声明独立持久化，输入摘要不包含正在生成的结果，最终审核包覆盖完整证据。

Copy `assessment_round` and both hashes from the current packet when reviewing; the example `0` above only applies to the original round. Repeated polls cannot trigger another capture or paid retry, unsettled manual claims block review while cancel remains available, and unchanged pixels do not justify a second paid assessment. Manual Main-requested observe is implemented below. Typed-template shared profile/service, caller-plan binding and the editor are now implemented in source; learning-core integration is also implemented and included in Main's frozen offline regression. The earlier96 pure cases do not certify later wiring. / 审核须复制当前轮次与摘要；重复查询不重拍或重付费，未决手动采集阻止审核且可取消，同图不追加付费。人工observe见下方源码合同；类型模板共享profile/service、执行绑定及编辑器已源码实现，学习core也已接通并纳入Main冻结离线回归。此前纯模板96例不证明随后接线。

If the original after image becomes missing or invalid, automatic observation stops with a diagnostic wait; it does not produce an approvable success packet from bad evidence. Newly captured receipts include their own verified window rectangle and pixel size. Older receipts without trusted geometry require review instead of borrowing pre-action coordinates. / 原后图丢失或失效会结束自动观察并诊断，不生成可审核成功的坏证据包；新截图保存当次已核对几何，旧回执缺几何则停止，不借用点击前坐标。

To change the remaining plan, explicitly close/cancel the parent and wait for terminal, quiescent input state. Submit a new v2 `start` containing only the intended remaining work and this `request.successor` object:

```json
{
  "successor_request_id": "unique-logical-successor-id",
  "successor_of": "<parent run_id>",
  "parent_plan_sha256": "<parent plan_sha256>",
  "prefix_sha256": "<parent status.prefix_sha256>",
  "lineage_generation": 0,
  "reason": "Explain the change to the remaining plan."
}
```

Use the parent's reported `lineage_generation`, not a fixed `0` after the first generation. The durable logical ID is distinct from the outer transport ID. Matching retries return the original successor; different content or a second successor for an already consumed parent generation is rejected. Old successor lookups must remain read-only while another run is active. Admission stays in the same host and target; cross-host/window continuation is unsupported. / 使用父运行实际代数；逻辑 ID 不随传输请求变化，重复请求只读返回原运行，不抢占当前活动运行。每父代只准入一个后续计划，不支持跨宿主/跨窗自动接续。

**Current conservative limit:** partial/unknown parent input blocks successor admission. A successor command identical to any completed parent input is also rejected, including intentional repeated navigation; this is not a general replanner. Handle that limitation explicitly instead of changing the logical request ID to bypass it. / **本批保守限制：** 部分或未知输入阻止后续计划；与父运行已执行命令完全相同的动作也拒绝，包括有意重复导航。不得换逻辑 ID 绕过，不宣称通用自主改计划。

## Typed condition templates (unreleased source) / 类型条件模板（未发布源码）

共享 profile/service、执行计划接线和编辑器已源码实现，学习 core 也已接通并纳入 Main 冻结离线回归；均未发布，未完成新候选实机验收，不宣称准确率、速度或 Main 审核次数收益。此前1008/1仅属于人工观察＋纯模板冻结点。执行接线限定离线回归为325 passed，包含实际 DecisionService＋离线 FakeProvider 的输入 A/B、后端认证及重开零重发；不是全候选或实机证明。 / Shared profile/service, caller-plan wiring and the editor are implemented in source; learning-core integration is also implemented and included in Main's frozen offline regression. This is unreleased, without new-candidate live acceptance or measured benefits. The earlier1008/1 checkpoint covers manual observe and pure templates only. The execution slice's325 offline checks include real DecisionService with a fake provider, input A/B authentication and reopen without redispatch; this is not whole-candidate or live evidence.

以下是完整静态合同示例，假设选定应用的搜索会打开记录详情；不授予输入权限。profile 必须使用 [Decision API 配置示例](DECISION_API.md)中的相同 id/revision/SHA。Agent 视觉路线仍另需其既有 vision_capabilities。 / This complete schema example assumes the selected application's search opens a record detail and does not authorize input. Use the matching profile identity in the linked configuration; Agent grounding still needs its existing vision-capability declaration.

```json
{
  "kind": "task_plan",
  "request": {
    "action": "start",
    "plan": {
      "schema_version": "task_plan.v2",
      "title": "Search and verify the requested record detail",
      "inputs": {
        "record_id": "R-101"
      },
      "steps": [
        {
          "step_id": "search_record",
          "action": {
            "kind": "input_sequence",
            "field_goal": "Record search input",
            "text": {
              "source": "input",
              "name": "record_id"
            },
            "clear_existing": true,
            "submit_search": true
          },
          "verification": {
            "kind": "agent_judgment",
            "condition_binding": {
              "schema": "condition_binding.v1",
              "template": {
                "allowed_states": [
                  "Matching detail without a modal"
                ],
                "condition_template_id": "detail_record_id_equals_input",
                "kind": "record_id_equals_input",
                "parameters": {
                  "record_id": {
                    "max_length": 160,
                    "min_length": 1,
                    "type": "string"
                  }
                },
                "review_policy": "adaptive",
                "revision": 1,
                "schema": "condition_template.v1",
                "template_sha256": "a84a522757c78460d230643f347ca0251fe4ed155810073dd43668b5e1ce5130",
                "text_template": "The detail page record ID equals {record_id}."
              },
              "typed_parameters": {
                "record_id": {
                  "source": "input",
                  "name": "record_id"
                }
              }
            }
          }
        }
      ]
    }
  }
}
```

`plan.inputs.record_id` 是本次实际字符串值；`typed_parameters.record_id` 保留对该名字的引用。字面参数可改为 `{"source":"literal","value":"R-101"}`。缺输入、非字符串、输出引用、未知字段、长度或渲染后文本超限在 start 派发前拒绝；read_text 不支持此语义判断。v2 verification 的 condition_binding 与 decision_condition 互斥；agent_judgment 不接受 native condition 字段。v1 与不含模板的 v2 保持旧合同，不增加空快照字段。 / The plan contains actual input values while the binding preserves a typed reference. A literal parameter is also supported. Missing/nonstring inputs, output references, unknown fields and length/rendered-text overflow fail before start dispatch; read_text is unsupported. Semantic fields are mutually exclusive; the native object belongs only to native_condition. V1 and template-free v2 keep their existing contract without empty snapshot fields.

启动把完整快照保存于 source.condition_snapshots，并用 state.condition_snapshots_sha256 绑定映射。每次 source/load、发送前及后端最终采用都从原 plan.inputs 独立重建；恢复读取原账本时也须带原完整快照认证，不能用模型返回的快照代替可信输入。快照含完整 binding、具体值、条件文字、状态/策略和摘要；审核包及自动观察/手动 v3 继承该冻结语义。 / Start persists the full snapshot map and state digest. Source/load, dispatch and final backend adoption independently rebuild from pinned inputs; ledger readback authenticates the original full snapshot, never a model-supplied substitute. Review packets and automatic/manual observations inherit these semantics.

模板自带 allowed_states 与 review_policy；另声明 allowed_states 时须完全相等。模板或步骤的 always_main 只能收紧审核。参数从 R-101 改为 R-202 不改变 template id/revision/template_sha256，但会改变本次 source/snapshot 摘要，须新开计划。修改规则文字、参数约束、状态或策略须新 revision、重算 template_sha256 并重新获 profile 批准；不能修改活动运行的冻结源。 / Template states are authoritative; any sibling state list must match exactly, and always_main only tightens review. Changing parameter values preserves template identity but changes the concrete snapshot and requires a new plan. Rule changes need a new revision/hash and profile approval; active frozen sources cannot be edited.

native_condition 可保留必填 `condition` UIA 对象，并把其字符串 decision_condition 换成上例完整 condition_binding；二者语义字段不能同时出现。完整 native 证明仍直接本地核验，模板 always_main 则交 Main；仅完整可信 timed_out 才接续共同语义路径，原回执与 after_capture_rechecked=false 不改写。原自动/手动采集上限、预算、取消和原 wait continue 门禁保持有效。直接单步 decision_check 仍只支持 literal condition，不接受模板。 / Native checks retain their UIA object and may replace only the semantic string with the full binding. Complete native proof stays local unless always_main applies; only trusted timeout proof enters the shared semantic path. Original evidence and observation/cancellation/continuation gates remain intact. Direct decision_check is still literal-only.

## Manual read-only observation (unreleased source) / 人工只读观察（未发布源码）

Use `instant_run` with `kind=task_plan` and the following request. Copy every binding, including the actual assessment round, from the current review packet; the placeholders are illustrative. / 经原instant_run/task_plan入口调用，全部绑定及实际轮次复制当前审核包，以下占位符仅示意。

```json
{"action":"observe","run_id":"<original-run>","step_id":"<current-step>","execution_request_id":"<original-execution>","wait_id":"<original-wait>","observation_request_id":"main-observe-1","review_packet_sha256":"<current-packet-sha256>","evidence_set_sha256":"<current-evidence-set-sha256>","assessment_round":0}
```

手动观察仅支持原输入completed且action_executed=True的v2核验等待，暂不支持read_text的False；复用原run/step/execution/wait，逻辑请求先持久占位，相同请求不重截图，未知采集不重派。自动与手动共享最多2次，失败/未知也计数；手动12秒采用期限不重置自动期限，同步capture不能硬中断，晚回复拒绝采用。v3保留原after与assessment_round，追加新图/证据摘要/祖先链；仅最新包可审核，旧包只可读取已认证图像，仍须原wait显式continue。 / Manual observe requires completed original input and action_executed=True at a v2 verification wait; read_text=False is unsupported. It retains the original IDs, persists a logical claim before capture and never repeats identical or unknown captures. Automatic and manual captures share two attempts, counting failed/unknown attempts. The separate12-second manual adoption deadline does not reset the automatic deadline or hard-interrupt synchronous capture. V3 preserves original after and assessment_round, appends evidence/ancestry, permits review only of the latest packet and read-only image retrieval from authenticated older packets, then requires explicit original-wait continuation.

Observe adds no input, Decision call, verdict, automatic continue or new wait. Capture claims are durable before owner capture; exact logical replays read saved results even under a new transport ID, conflicts fail and unknown operations never repeat. Unsettled capture blocks review while cancel remains available. Final capture/backend gates recheck window, owner, pending state, evidence and queued cancellation. / observe不增加输入、判断调用、结算、自动继续或新wait；采集前持久占位，新transport也只读原逻辑结果，冲突拒绝、未知不重派。未决时阻止审核但可取消，最终采集/结算再次核对身份、状态、证据及取消。

`review_packet.v3` appends `latest_observation`, `packet_revision`, `previous_packet_sha256` and `packet_ancestors`; `assessment_basis` keeps the last model assessment tied to its old evidence. Original `evidence_sha256` still refers to the action after. Review must use the current packet/evidence digest; old versions cannot settle. Client callbacks occur once per packet version. MCP `images=after` on an observe receipt returns labeled observation PNG bytes; after A→B→replay A it returns authenticated A pixels while B remains current. / v3新证据与旧评估依据明确分开，原evidence_sha256仍绑定动作after；审核使用最新摘要，旧包不得结算。客户端同版回调去重；A→B→重放A只读A原图，当前审核仍为B。

人工只读 observe 已源码完成；此前人工观察＋纯模板 Main 冻结联调1008 passed、1 skipped（共1009，0 failure/error，XML91.700秒；stdout91.74秒，wall92.968秒），1048个app/scripts/tests Python文件前后SHA一致。唯一跳过为符号链接目录拒绝用例，因环境无创建权限。此冻结点包含纯模板模块96例，不覆盖随后模板接线；本次零付费、零桌面、未打包。 / Manual read-only observe is implemented in source. The earlier manual+pure-template Main freeze records1008 passed/1 permission skip out of1009, zero failures/errors, XML91.700s, stdout91.74s and wall92.968s, with unchanged1048-file hashes. It includes96 pure-template cases but not subsequent template wiring; zero paid calls, desktop actions or packages. See the [source checkpoint](../verification/ADAPTIVE_P2_SOURCE_20261010.md). This is not new-candidate live or release acceptance. / 参见源码检查点，不代表新候选实机或发布验收。

## Native mismatch continuation (unreleased source) / 原生不匹配续接（未发布源码）

An explicit `task_plan.v2` native check can declare a semantic alternative for the same intended outcome:

```json
{
  "kind": "native_condition",
  "condition": {"text": "Detail panel", "control_type": "Text"},
  "decision_condition": "The requested detail page is visible.",
  "allowed_states": ["Requested detail page without an extra modal choice"]
}
```

Complete native proof still uses zero API calls. Only a maintained `timed_out` observation with completed original input, matching window/image/condition, valid timing and exclusively valid absent/matched UIA samples may enter the common Decision path. Unavailable, ambiguous, missing or malformed records go to Main without a paid bypass. The original receipt, image and `after_capture_rechecked=false` remain unchanged; semantic assessment does not turn the UIA result into a native match. / 完整原生证明零调用；仅维护路径生成、原输入已完成、身份/图像/条件相符且所有样本有效的超时可以进入共用判断。坏证据、歧义、未知输入不付费绕过；原回执、原图和false复查标志保持不变。

Semantic continuation requires an enabled v2 profile; auto adoption still requires exact string `auto_conditions` or typed-template identity approval, according to the selected semantic field, authenticated success and no review signal. V1 does not accept the new fields. `allowed_states`, `review_policy` and `wait_policy` require an explicit `decision_condition` or full `condition_binding` and reuse the strict semantic options; the two semantic fields are mutually exclusive, while the native `condition` object remains required. Enabled global or per-step `always_main` pauses without a paid check; disabling the global service preserves local behavior. / 语义续接须配置并启用v2服务，自动采用仍受精确允许条件、认证和审核信号约束；v1不接受新增字段，其他选项不能脱离语义条件单独生效，关闭全局服务不改本地行为。

The semantic condition is an alternative, not an additional check after native success. Use `agent_judgment` when success must always be judged semantically. Native waiting still uses the original 2-second polling budget; a subsequent Decision can add latency. No speed or accuracy gain is claimed by this interface alone. See [P2 source evidence](../verification/ADAPTIVE_P2_SOURCE_20261010.md). / 语义条件是替代核验，不会在本地成功后额外调用；始终需要语义判断时使用agent_judgment。原生2秒轮询保留，后续API可能增加耗时，不因接口接通便宣称收益。

## Persistence and remaining work / 持久化与剩余工作

Sources/tickets use `session/task-plans`, runner state uses `session/task-plan-runners`, and learned runs retain `session/workflow-runners`. Both sources share one input queue with mutual admission. Settlement binds the original command, terminal receipt, image, plan hash and target identity. Uncertainty keeps pending; repeated queries do not create paid requests. / 两种来源分别存账、互斥输入，核验绑定原始证据，不确定保留票据，查询不触发计费。

A different host owner cannot review, continue, cancel or execute an old plan. Cross-host recovery and recovery after source persistence but before successful runner creation are outside this first slice; preserve evidence and do not blindly restart. / 跨宿主不得继续旧计划；本批尚未提供跨宿主或启动中途失败的恢复入口，须保留证据。

**历史显式原生路线证据 / Historical explicit-native evidence.** `app/execution/timeline.py` aggregates explicit monotonic spans without adding nested timings or treating handoff as pure inference. Production timing collection remains incomplete. Native targets have matched live evidence; pinned recipe references remain future work. Browser repairs cover the 17-level native-root ancestry, bounded initial point readiness and a proven one-pixel change in the same focused field. The real fill/read-back now passes; keyboard input still requires the current snapshot exactly, and coarse/readonly fields remain rejected. / 计时生产采集未齐，原生目标已有成对实测，学习引用仍待开发。浏览器修复了深层窗口归属、初次粗命中及同字段聚焦后 1 像素变化，实机填写读回通过；键盘仍精确复验当前快照，粗容器与只读字段不放行。 该历史记录不证明本次 geometry 首败根因已修复。 / This historical record does not establish repair of the latest geometry failure.

Complete contracts, isolated integration, real single and continuous use, cancellation/recovery and cleanup before independent acceptance and equivalent-baseline performance comparison. See the [current adaptive acceptance ledger](../verification/ADAPTIVE_REVIEW_LIVE_20261009.md); the [preview.3 source record](../verification/CONTINUOUS_EXECUTION_ACCEPTANCE.md) remains historical. / 按合同、隔离联调、单项、连续使用及清理完成本方验证，再独立验收和同口径性能对照；当前进度以主动审核实机记录为准，preview.3 源码记录保留为历史。
