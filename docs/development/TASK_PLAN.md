# Temporary execution plans / 临时执行计划

**2026-10-09: preview.3 bounded execution plans.** Execution `0.1.2-preview.3` and optional learning `0.1.0-preview.3` use separate installers under `learning-v0.1.0-preview.3`. Scoped source acceptance passed Main and independent Sol; Main also passed the new installed execution and learning journeys. See the [release record](../verification/CONTINUOUS_EXECUTION_RELEASE_20261009.md) for final installed-independent/publication status and [source evidence/limits](../verification/CONTINUOUS_EXECUTION_ACCEPTANCE.md) for measured scope. / **preview.3 有界执行计划。** 源码限定验收与 Main 新安装版实机通过，最终独立及发布核对按本轮记录，旧 preview.2 结果不转计。

## Purpose / 用途

The caller submits a bounded plan once. The existing WorkflowRunner schedules original gated commands and advances after a declared outcome is verified. `source_kind=caller_plan` does not create a reviewed learning asset or require the learning workbench. Saved learned programs retain their original backend. / 主 Agent 一次提交短计划，由现有运行器、队列和动作门禁连续调度。临时计划不是已审核学习资产，不要求安装学习工作台。

Explicit structured targets can use a unique current native UIA match before model inference. Otherwise grounding uses the selected local model, external vision API or client Agent, preserving the target semantics. Decision supplies outcome judgments, not coordinates, extracted values or permission. With `agent_delegate`, the client must still resolve genuine grounding waits using the same visual worker; the host cannot invoke a Codex subagent. / 显式目标可优先用当前唯一原生定位；视觉仍沿已选来源并保留目标语义。Decision 不代替定位或授权，委派识图仍由客户端复用同一子会话。

Local grounding is this run's selected profile, not a requirement for all users. Existing external API/current/delegated Agent routes remain optional and need no local weights. Decision is separately optional outcome verification. / 本轮选用本地识图不强制所有用户加载本地权重；已有视觉 API/Agent 路线仍可选，Decision 为独立可选核验。

## Request / 请求

Submit through `instant_submit` or `instant_run` with a fresh outer request ID:

```json
{
  "kind": "task_plan",
  "request": {
    "action": "start",
    "plan": {
      "schema_version": "task_plan.v1",
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

This example describes a schema, not permission to click an arbitrary application. Select the intended window first. Start freezes handle, PID and process creation time; each dispatch rechecks them. Agent vision routes additionally require `request.vision_capabilities` using the existing ClientVisionCapabilities fields. / 示例只说明结构；先选择目标窗口，开始时固定完整进程身份，逐次派发前核对。Agent 视觉来源另须声明既有视觉能力。

Plans contain 1–8 linear steps with unique `step_id`, explicit action and verification. / 初期限定 1–8 个线性步骤。

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
- `agent_judgment` without `decision_condition`: explicit Agent review. / 未声明判断条件时等待 Agent 复核。
- `agent_judgment` with `decision_condition`: reuse the original after image and shared Decision service. Absent/off stays inactive; shadow retains review. Auto adoption requires exact allowlisting and authenticated results. Unsupported for `read_text`. / 使用原后图与共用服务；未配置或关闭不调用，影子模式保留审核，自动采用须满足白名单及认证，不用于动态读取。

The declared condition must prove the intended step outcome. A player being visible does not prove playback/audio. An intermediate success is not complete task success. / 条件须足以证明步骤目标；播放器出现不等于播放成功，中间步骤也不等于整个任务成功。

## Controls / 控制

All controls use `kind=task_plan`:

| `request.action` | Required fields / 必填字段 |
| --- | --- |
| `status` | `run_id` |
| `continue` | `run_id`, original `wait_id` |
| `cancel` | `run_id` |
| `review` | `run_id`, `execution_request_id`, `step_id`, `verdict=success|failure`, `reason`, original after-image `evidence_sha256` |

`instant_status` exposes `task_plan_run` and `task_plan_runtime_error`. The original start receipt is immutable. `LearningBenchmarkClient.run_plan` submits once and polls this read-only projection; it does not enqueue repeated `task_plan/status` controls while an action is pending. It returns `status_source=instant_status` and retains the original `request_id`/`start_receipt`. At `grounding_required`, use `active_command_id` and the existing original Agent command protocol; do not resubmit start. / 客户端一次提交后轮询只读投影，不在原动作 pending 时反复排队查询；原 start 回执和 request_id 保持不变，定位等待沿原命令协议续接。

Control receipts report `operation_success_scope=task_plan_control` and contain no action image. Read original images using the actual execution request ID; control acceptance is not task completion. / 控制回执不携带动作图像，须使用实际执行 ID 读取原图；控制请求返回不等于任务完成。

Review requires `verification_required` and a proven terminal input receipt. It settles the original ticket only; then use `continue` with the retained wait ID. Unknown/partial input cannot be reviewed into success. Cancellation stops future steps while retaining actual effects and unresolved evidence; it never silently replays. / 复核只结算原票据，之后显式继续；未知或部分输入不得补记成功，取消保留副作用和待决证据。

`cancel_requested` is transitional even when it retains the old verification wait. `run_plan` keeps polling `instant_status` until the runner settles or the caller's timeout expires; timeout returns `client_state=pending` with the actual cancellation state and original IDs. A validated review may advance the trial history while the runner still holds the original wait. The client returns `client_state=continue_required`, retaining that wait ID without another review callback or automatic input. Only an explicit `continue` settles the runner and permits subsequent steps. / `cancel_requested` 即使保留旧审核等待也只是过渡状态；客户端只读轮询至真实结算或超时，超时保留实际取消状态与原 ID，不冒称已取消。合法复核后历史可先推进，而运行器仍持原等待；客户端返回 `continue_required`，保留原 wait ID，不重复审核回调、不自动输入，须显式继续后才结算运行器并允许后续步骤。

## Persistence and remaining work / 持久化与剩余工作

Sources/tickets use `session/task-plans`, runner state uses `session/task-plan-runners`, and learned runs retain `session/workflow-runners`. Both sources share one input queue with mutual admission. Settlement binds the original command, terminal receipt, image, plan hash and target identity. Uncertainty keeps pending; repeated queries do not create paid requests. / 两种来源分别存账、互斥输入，核验绑定原始证据，不确定保留票据，查询不触发计费。

A different host owner cannot review, continue, cancel or execute an old plan. Cross-host recovery and recovery after source persistence but before successful runner creation are outside this first slice; preserve evidence and do not blindly restart. / 跨宿主不得继续旧计划；本批尚未提供跨宿主或启动中途失败的恢复入口，须保留证据。

`app/execution/timeline.py` aggregates explicit monotonic spans without adding nested timings or treating handoff as pure inference. Production timing collection remains incomplete. Native targets have matched live evidence; pinned recipe references remain future work. Browser repairs cover the 17-level native-root ancestry, bounded initial point readiness and a proven one-pixel change in the same focused field. The real fill/read-back now passes; keyboard input still requires the current snapshot exactly, and coarse/readonly fields remain rejected. / 计时生产采集未齐，原生目标已有成对实测，学习引用仍待开发。浏览器修复了深层窗口归属、初次粗命中及同字段聚焦后 1 像素变化，实机填写读回通过；键盘仍精确复验当前快照，粗容器与只读字段不放行。

Complete contracts, isolated integration, real single and continuous use, cancellation/recovery and cleanup before independent acceptance and equivalent-baseline performance comparison. See the [current acceptance ledger](../verification/CONTINUOUS_EXECUTION_ACCEPTANCE.md). / 按合同、隔离联调、单项、连续使用及清理完成本方验证，再独立验收和同口径性能对照。
