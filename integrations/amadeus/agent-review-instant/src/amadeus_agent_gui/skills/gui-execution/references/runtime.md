# Runtime session and receipt contract / 会话与回执合同

This resource extension connects to an operator-started, authenticated loopback HTTP MCP Runtime; it never launches external code. The connection token is distinct from provider API keys. Use the tools actually discovered on this connection. The logical tool names below are Runtime names, not predictions of Pi's namespaced model tool names. Use the active schema if the candidate reports a newer contract. Do not change profiles, thresholds or prompts to bypass a refusal.

## Start and select / 启动与选择

Call the discovered `instant_start` once, then `instant_status` until ready. Vision and Decision profiles are preconfigured; do not call `prepare_models` or any `learning_*` command. A selected target is session state.

For an explicitly approved new application or shortcut, one `instant_run` argument example is:

```json
{"request_id":"launch-001","command":{"kind":"launch","path":"C:\\approved-test\\application.lnk","prefer_existing":false},"wait_ms":10000,"images":"none"}
```

Read the actual returned launch/window ownership and exact handle/process_id. Never substitute a guessed handle. If selecting an already observed window, use the discovered identities in a command shaped `{"kind":"select","handle":123,"process_id":456}`; a pre-existing user window does not become owned by this task.

Capture the selected target with **only** `kind` in the command:

```json
{"request_id":"capture-001","command":{"kind":"capture"},"wait_ms":10000,"images":"after"}
```

Do not put handle/process_id inside `capture`. Use the original images returned by `instant_run`/`instant_result`; the discovered `instant_image` can retrieve an available image by the original request_id. A new capture is a new observation, not replacement evidence for an older action. Never mix coordinates from old images with current window geometry.

## Submit, wait and inspect / 提交、等待与核对

Prefer the provided complete `task_plan` when the task calls for one; do not manually split it to evade checks. Use its actual active schema, explicit actions/verification and original run identity. There is no adapter step cap; Runtime budgets, evidence binding and admission still apply. `instant_run` accepts `request_id`, `command`, `wait_ms`, `detail` and `images`; choose a wait below the MCP client timeout. `instant_submit` is also asynchronous. A start receipt with status running is not plan completion.

When pending, follow the returned `next` and call the discovered `instant_result` with the **same** outer request_id:

```json
{"request_id":"launch-001","detail":"full","images":"both"}
```

For an asynchronous `agent_command.v1`, preserve its command_id. Query it with a new outer request ID (a read-only status command, not a replay):

```json
{"request_id":"status-001","command":{"kind":"agent_command_status","request":{"command_id":"original-command-id"}},"wait_ms":10000,"images":"after"}
```

For task plans, inspect `instant_status.task_plan_run` and the original start/result receipts until a terminal outcome or explicit wait. Report actual completed steps, pending/review/failure and evidence, not merely whether a tool call returned. `result_unknown`, timeout, `action_executed=true`, interrupted typing, or missing after images never prove input did not happen. Do not resubmit with a new ID, start a competing plan, or use another input route to hide uncertainty.

## Review / 原 Agent 审核

Use the packet actually returned by the active service. A pre-action candidate
and an already-entered field value are different review scopes. Neither a tool
handoff nor a version marker authorizes guessing a ticket or bypassing a check.

### Candidate before input / 输入前的候选

When the Runtime returns a real `pre_action_review_packet.v1`, its original job
is parked after authenticated Decision and ordinary-model nonpasses, with no
native input claimed. Read `packet.execution_request_id` through
`agent_command_status` using a new outer request ID and `images=none`, as in the
status example below. Retrieve that status request's bound original **before**
PNG with the discovered `instant_image`, for example:

```json
{"request_id":"candidate-status-001","view":"before"}
```

`candidate-status-001` must be the actual successful status request ID, not the
unfinished execution ID. Inspect the original task target, candidate point/box
and bound original image. Do not replace it with a new capture or assume the
locator's description proves the target correct. Only if the candidate satisfies
the actual task, copy the returned `caller_controls.review.request` and add the
actual `verdict=success` and a specific visual reason. Otherwise record failure
with the genuine reason or cancel; do not repeatedly ask models to obtain a pass.

Submit review through `task_plan`; it records Main's judgment and performs no
click. Then submit the **separately returned**
`caller_controls.continue.request`, retaining the original run/wait. This resumes
the original job/candidate with a fresh target-region check and all ordinary
input/identity/geometry/visibility/cancellation gates. A changed or expired
candidate stops; do not restart, replan or synthesize a new approval to repeat
it. The two original model refusals remain refusals, separate from Main's
one-use approval. No new threshold or model prompt is selected by this Skill.

### Entered field value / 已输入文字

The Runtime's Main review contract can park the original live input thread at `field_review_packet.v1` after an authenticated dual-model rejection. This contract shipped in Runtime 0.1.5; the HTTP entry point is a separate new capability. Use the running service's actual returned recipe and existing public MCP actions. At this wait, the original execution is not terminal: read `packet.execution_request_id`, issue `agent_command_status` with that command_id using a new outer request ID, and wait for that read-only status receipt:

```json
{"request_id":"field-status-001","command":{"kind":"agent_command_status","request":{"command_id":"original-execution-request-id"}},"wait_ms":10000,"images":"none"}
```

Then call the discovered `instant_image` with `{"request_id":"field-status-001","view":"after"}`. Use the actual returned status request ID. Do not request image directly on the unfinished original execution, replace the bound after image with a new capture, or replay the input. The example command_id is a placeholder for the real packet identity.

Inspect the exact original evidence bound to `caller_controls.review.request`. Copy that returned request and add only the actual `verdict` and `reason`; do not invent a review packet/hash or add wait_id to review. Submit through the existing task_plan command. A successful review only records the original Agent's judgment. Use the separately returned `caller_controls.continue.request` for explicit continue on the **original** run/wait; only then can that live thread resume without retyping. These projections are parameter recipes, not action authorization.

This review only confirms already-entered text. If the original request has a submit suffix, its fresh target/candidate, input gates and result verification still apply; the review does not prove submit/search success or bypass a final-submit restriction. Released 0.1.4 is a separate baseline: some `field_review` failures have no resumable ticket. If the active host supplies no actual review/continue recipe, keep the first failure and stop/report; do not fabricate a ticket, restart/replay, relabel success or construct a successor to repeat input. The version marker alone does not prove the new capability. This package does not implement the Runtime repair or claim its real installed acceptance.

中文：文字结果 Main 审核已在 0.1.5 发布；HTTP 和前置候选审核是另外的能力。先通过新外层 agent_command_status 查 packet.execution_request_id，再对该 status request 取绑定原图：前置候选看 before，已输入文字看 after。只按实际 caller_controls.review→单独 continue 续原 run；前置审核不跳过新鲜度及输入门禁，文字审核不重输，也不代表 submit 成功。无真实票据、候选变化或过期就停报，不伪造 Main 通过。

## Owned-window and host cleanup / 自有窗口与宿主收尾

Once input has settled, close only a task-launched window. Substitute the exact handle/process_id read from its launch receipt into this shape:

```json
{"request_id":"close-001","command":{"kind":"close_launched_window","handle":123,"process_id":456},"wait_ms":10000,"images":"after"}
```

No `request.ownership` field is required. Keep and check the original launch identity; example integers are placeholders, not real targets. If `window_close_pending` exposes an owned modal, inspect the returned current dialog using select/capture. A close receipt does not authorize Save/Discard/Confirm; act only if the exact choice is separately in scope. Missing after evidence can mean the window has closed: inspect the original action receipt and verify disappearance instead of repeating the click. Confirm `window_closed` for each owned window.

Then call `instant_stop`, poll `instant_status`, and require `host_alive=false`, `pending_ids=[]`, `cleanup_verified=true` and no unresolved cleanup error before disconnecting. Stop acknowledgement/cleanup_pending is not terminal cleanup. Host cleanup does not substitute for checking application-window closure. Do not close unrelated windows, uninstall the external Runtime, delete the extension's retained data, or reset/delete browser profiles, cookies, history or sessions.

Report task success/failure/unknown, original request/run IDs and bound evidence, any assistance/recovery, owned-window closure, and host cleanup separately. HTTP disconnection is a transport boundary; it is not evidence of a successful task, cancellation or a fully settled Runtime. Release the HTTP MCP owner only after the explicit cleanup conditions above; a new Work can then initialize its own connection. Keep this lifecycle within one Work run. Reopening a Pi conversation is not resuming a live MCP connection. The independently started daemon has a separate lifetime and data directory; extension removal does not stop it or delete its data.
