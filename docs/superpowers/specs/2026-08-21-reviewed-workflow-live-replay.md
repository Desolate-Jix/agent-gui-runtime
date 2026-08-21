# Reviewed Workflow Live Replay v1 设计规范

## 1. 目标与范围

本规范把 `reviewed_workflow_replay.py` 的纯合同接到真实、受控的 GUI 执行链。新增独立的 `ReviewedWorkflowLiveReplayController`，每次调用只尝试推进**一条** reviewed transition，并且只在当前窗口、当前截图、当前定位、当前 Gate 和当前执行授权全部一致时才允许一次点击。

目标：

1. 从已发布的 `reviewed_workflow_asset_v2` 服务器端重新加载资产，capture 后构造可信 current observation，调用纯合同完成 state resolve 与 transition select。
2. 对同一稳定 observation epoch 重新定位目标，运行 `pre_click_decision_v1`；先以 replay-only dry-run 让 Action API 生成 `approved_plan_v2` 和 plan SHA，再把 selection、grounding、Gate、窗口租约、fencing token、capture lineage 与该 plan 强绑定到服务器签发的一次性执行信封。
3. 真实 dispatch 只向 Action API 提供 `envelope_id`；公共 gated dispatcher 原子加载并核验信封及 plan 后执行一次。执行后必须重新 capture 并以 `verify_transition_result` 验证目标状态，才可提交状态推进。
4. 支持每窗口 lease、跨进程幂等、崩溃可恢复的状态机；点击一旦开始，绝不自动重试。
5. 首版只允许资产 v2 已允许的 `open_detail`、`open_apply_flow`、`back`、`close_modal`。`read`、`scroll`、`fill_field`、`continue_next_step`、upload，以及 final action 一律 fail-closed。

非目标：

- 不迁移或激活 v1 memory、旧 PathGraph、历史坐标或历史 approved plan。
- 不提供多 transition 自动循环、批量回放、导航爬取、自动恢复点击或用户资料填写。
- 不把截图、OCR、UIA、浏览器 probe、模型输出、面板提交、provider 输出或 API 成功标志本身当作执行授权。
- 不修改 `reviewed_workflow_replay.py` 的纯函数语义；该模块继续无 GUI、无网络、无持久化副作用。
- 不绕过 `POST /action/execute_recognition_plan` 的 Gate、final-submit 检测、窗口验证和 post-click verification。
- 不把 `no_click` 预览称为真实 transition 成功；真实 `verified` 专用于 post-action target-state verification。

## 2. 权威源与信任边界

```text
Public client
  -> LiveReplay API (untrusted intent only)
  -> Controller / state store / per-window lease
  -> Capture + trusted observation builders
  -> reviewed_workflow_replay.py (pure validation)
  -> fresh grounding + Gate
  -> Action API replay-only dry-run -> approved_plan_v2
  -> server-issued one-shot envelope
  -> common gated Action dispatcher, one real attempt only
  -> post capture + pure verification
  -> committed attempt record
```

| 边界 | 可接受的输入 | 不可信或禁止的输入 | 权威输出 |
|---|---|---|---|
| Public API | asset identity、请求的 reviewed transition、幂等键、执行意图 | observation、resolved state、selection、candidate、bbox、click point、Gate、approved plan、envelope、窗口句柄、provider result | 脱敏的 attempt 状态摘要 |
| 资产仓库 | registry CAS 激活的 immutable asset bytes | 浏览器携带的 asset graph/hash | 重新计算的 asset hash 与 canonical asset |
| 观察层 | bound-window 服务、`ScreenshotService`、OCR/UIA/browser probe 的原始结果 | 历史 capture、客户端 anchor match、provider 自称 confidence | server-built `trusted_live_observation_v1` |
| 定位与 Gate | 当前 capture 及 server selection | 客户端坐标、候选项、Gate verdict | `reviewed_workflow_current_grounding_v1`、`pre_click_decision_v1` |
| 执行层 | 未消费且签名有效的 `reviewed_workflow_execution_envelope_v1` | 任意 public plan/envelope injection、坐标复用、重放 token、过期 fencing token | one-attempt action receipt |
| 验证与存储 | action receipt、全新 capture、服务器 observation | operation result 的自由字段、旧 post observation | 已验证的 transition result 与 append-only audit |

所有时间使用 UTC RFC 3339；所有 JSON 使用 UTF-8、`ensure_ascii=false`、`sort_keys=true`、紧凑 separators，并以 SHA-256 标识规范化 payload。`asset_content_sha256`、`selection_sha256`、capture lineage 和 envelope binding 均为精确相等比较，不能只比较 ID 或 viewport。

## 3. 模块与接口

### 3.1 新增模块

| 模块 | 职责 | 禁止职责 |
|---|---|---|
| `app/agent/reviewed_workflow_live_replay.py` | `ReviewedWorkflowLiveReplayController.advance_one()`；协调一条 transition、状态机、恢复和结果投影 | 不实现纯语义规则、不直接点击 |
| `app/agent/reviewed_workflow_live_replay_store.py` | SQLite 持久化 attempt、lease、idempotency reservation、fencing token、immutable envelope claims 与 mutable consumption；原子 compare-and-set | 不读取客户端状态作为权威 |
| `app/agent/reviewed_workflow_live_observation.py` | capture artifact、hash、OCR/UIA/browser probe 的同 epoch 汇总、稳定性复 capture；生成 strict observation 与 evidence refs | 不选择 transition 或发放点击授权 |
| `app/agent/reviewed_workflow_live_grounding.py` | 依据服务器 selection 生成 current candidate 与 Gate input | 不接受 caller 的 bbox、candidate 或 point |
| `app/agent/reviewed_workflow_execution_envelope.py` | 创建、签名、消费和审计 `reviewed_workflow_execution_envelope_v1` | 不允许直接 public load/execute |
| `app/operation/reviewed_workflow_action_adapter.py` | 仅以 controller identity 先发 replay-only dry-run、再只传 `envelope_id` 作真实调用，并回填可信 receipt | 不自行重试、不传 raw approved plan、不伪造 action result |
| `app/api/reviewed_workflow_live_replay.py` | public request parsing、response projection、HTTP status mapping | 不泄露内部 candidate/坐标/envelope |

### 3.2 复用接口与新增强绑定

- 复用 `app.agent.reviewed_workflow_replay.resolve_current_state`、`select_verified_transition`、`validate_current_grounding`、`verify_transition_result`、`build_recovery_decision`，但仅接受 controller 重新计算的输入。
- 复用 `ScreenshotService.capture_window` 获取 bound window 的全窗口 capture；`CaptureArtifactResolver` 立即以 image bytes 计算 SHA-256、生成 `capture_id`，并把不可变 artifact ref 与 viewport 组成 `CaptureArtifact`。截图文件名不是身份。
- 复用 `screen_reading.build_screen_reading`、`WindowsUIAProvider` 和现有 OCR；网页 transition 还必须通过 `probe_bound_browser` 与 `verify_navigation_policy` 采集同 HWND 的 origin/tab evidence。任一必需 provider 不可用、epoch 不稳定或无 stable tab identity 时，不得 real click。
- Action adapter 分两阶段工作：(a) replay-only dry-run 调用既有 Action API，强制 `dry_run=true`、`max_execution_attempts=1`、`capture_live=true`、`allow_saved_image_execution=false`、`enable_post_click_verification=true`、`metadata.require_current_grounding=true`，取得仅 replay 使用的 `approved_plan_v2` 与 canonical `approved_plan_sha256`；这不是 action attempt；(b) real dispatch 仅传 `envelope_id` 给公共 gated Action dispatcher，强制同一组安全参数和 `dry_run=false`。普通 `approved_plan_id` reuse 分支必须拒绝 replay-only plan，防止绕过信封。
- execution fence 位于公共 gated Action dispatcher，而不是 live controller 的局部检查。所有输入动作（点击、文本、滚动、confirmed point 和未来经该 dispatcher 的动作）都必须在执行前原子验证当前 `window_binding_id` 的 `fencing_token`；过期或较低 token 一律拒绝。Action adapter 的 source lineage 必须等于 envelope source lineage。

## 4. Public API 合同

新增 `POST /reviewed-workflows/live-replay/advance`。它是唯一 public live-replay 写入口；调用者只能请求 reviewed semantic transition，不可注入任何执行事实。当前 runtime 尚未提供认证、`PrincipalResolver`、CSRF 或 one-time approval 的实现，因此 v1 部署配置必须只允许 `no_click`；任何 `real_click` 请求都以 `real_click_authorization_unavailable` 阻断，不能把本设计中的未来授权边界当作现有功能。

### 4.1 请求：`reviewed_workflow_live_replay_advance_request_v1`

```json
{
  "contract_version": "reviewed_workflow_live_replay_advance_request_v1",
  "asset_id": "seek-reviewed-workflow-v2",
  "expected_asset_content_sha256": "64-lowercase-hex",
  "requested_transition_id": "results.open_detail",
  "execution_intent": "no_click",
  "idempotency_key": "client-generated-uuid-or-opaque-key"
}
```

字段规则：

- 六个字段均必填、Pydantic model 设为 `extra="forbid"`；`expected_asset_content_sha256` 必须为 64 位小写十六进制；`idempotency_key` 长度 16–128，且只含 ASCII 字母、数字、`.`、`_`、`-`。
- `requested_transition_id` 只表达用户请求的 reviewed edge；controller 仍必须先 resolve current state，再验证该 edge 唯一、属于当前 state、允许且不需 human confirmation。
- `execution_intent` 仅可为 `no_click` 或 `real_click`。`no_click` 永远不发 envelope。`real_click` 的未来开关依赖独立实现的 `PrincipalResolver`、CSRF validation、server-side one-time approval、rollout policy 与 keyring；approval 必须绑定 `asset_id`、asset hash、requested transition、principal、CSRF-bound session 和 10 分钟有效期，且不通过本请求传递。该依赖任一未配置时返回 `real_click_authorization_unavailable`。
- 请求体不得出现或嵌套包含 `observation`、`selection`、`state_resolution`、`grounding`、`bbox`、`click_point`、`candidate`、`gate`、`pre_click_decision`、`approved_plan_id`、`envelope`、`window_handle`、`capture_id`、`screenshot_sha256` 或 `provider_result`。未知字段、这些保留名和递归对象/数组键均返回 `public_authority_injection`。

### 4.2 响应：`reviewed_workflow_live_replay_advance_response_v1`

```json
{
  "contract_version": "reviewed_workflow_live_replay_advance_response_v1",
  "attempt_id": "rwrla_01...",
  "idempotency_key": "...",
  "status": "preview_verified",
  "execution_intent": "no_click",
  "asset_id": "seek-reviewed-workflow-v2",
  "asset_content_sha256": "64-lowercase-hex",
  "transition_id": "results.open_detail",
  "source_state_id": "results",
  "target_state_id": "detail",
  "action_attempted": false,
  "state_advanced": false,
  "recovery": {"decision": "none", "repeat_action": false},
  "evidence_refs": ["evidence://..."],
  "error": null
}
```

`status` 仅为 `created`、`prepared`、`dispatch_started`、`dispatched`、`preview_verified`、`verified`、`failed`、`blocked`。`preview_verified` 只表示 no-click 的 observe/resolve/ground/Gate 链已经验证，且固定 `action_attempted=false`、`state_advanced=false`；`verified` 只表示真实 action 后的新 target state 已验证，且固定两个字段均为 `true`。响应不返回 screenshot 文件路径、OCR 文本、UIA tree、provider raw data、candidate、bbox、click point、Gate internals、approved plan、envelope、lease token、fencing token 或 HWND。

HTTP body 始终使用既有 `APIResponse`：`success`、`message`、`data={"result": reviewed_workflow_live_replay_advance_response_v1}`、`error`。失败的 `error` 使用 `ErrorModel(code, details)`；`details` 仅含 `attempt_id`、`stage`、`action_attempted`、稳定 failure code 和 evidence refs，不能泄露内部信封、坐标、文件路径、原始 provider data 或密钥信息。相同 local idempotency scope、相同 `idempotency_key`、相同 canonical request 必须返回同一 `attempt_id` 和当前投影；同 key 不同请求 hash 返回 HTTP 409 `idempotency_conflict`。在 `PrincipalResolver` 未实施前，scope 是固定 local-runtime scope，不声称存在 authenticated principal。

HTTP 映射：200 为 `preview_verified`、`verified`、`failed` 或 `blocked` 的已完成投影；202 为同一 attempt 尚在 `created`、`prepared`、`dispatch_started` 或 `dispatched`；409 为 idempotency、fencing 或持久状态冲突；422 为 request contract/injection；423 为窗口 lease；503 **只**用于尚未进入 `dispatch_started` 的 capture/provider/Action replay-only dry-run 临时不可用。进入 `dispatch_started` 后即使 transport 丢失也返回 200 的 `failed`/`blocked` 投影并标记 `action_attempted=true`，绝不把未知点击结果作为可安全重试的 503。

## 5. 可信 observation、信封与持久状态

### 5.1 `trusted_live_observation_v1`

该对象只存在 controller/store；它转换为 pure-contract 所需的 `reviewed_workflow_current_observation_v1`，并保留 provider provenance。

```json
{
  "contract_version": "trusted_live_observation_v1",
  "observation_id": "obs_...",
  "attempt_id": "rwrla_...",
  "asset_id": "...",
  "asset_content_sha256": "64-lowercase-hex",
  "window_binding": {
    "window_binding_id": "window:12345",
    "process_id": 12345,
    "process_name": "msedge.exe",
    "process_creation_time_utc": "2026-08-21T00:00:00Z",
    "canonical_executable_identity": "sha256:64-lowercase-hex",
    "identity_sha256": "64-lowercase-hex"
  },
  "capture_lineage": {
    "capture_id": "capture_...",
    "screenshot_sha256": "64-lowercase-hex",
    "viewport_size": {"width": 1200, "height": 800}
  },
  "origin": "https://www.seek.co.nz",
  "observed_anchor_evidence": [
    {"anchor_id": "results.title", "matched": true, "confidence": 0.98, "evidence_ref": "evidence://..."}
  ],
  "epoch": {
    "epoch_id": "epoch_...",
    "uia_capture_id": "capture_...",
    "browser_probe_capture_id": "capture_...",
    "stability_capture_id": "capture_...",
    "stable": true
  },
  "provider_evidence": [
    {"provider_id": "screenshot_service", "provider_version": "capture_v1", "evidence_ref": "evidence://..."},
    {"provider_id": "windows_uia", "provider_version": "windows_uia_provider_v1", "evidence_ref": "evidence://..."}
  ],
  "created_at": "2026-08-21T00:00:00Z"
}
```

`window_binding.identity_sha256` 覆盖 handle、PID、process creation time、process name 和 canonical executable/file identity；它防止 HWND/PID 复用。rect 不进入 stable identity，只作为每次 capture 的独立 geometry evidence，移动/缩放会使 capture lineage 失效而非伪造进程身份变化。web application 还必须有 browser probe 的 `status=ok`、origin 和 stable tab identity；native application 必须以审核资产声明的 executable/product identity 精确匹配。

一个 observation epoch 固定为：`ScreenshotService` 取得 source `CaptureArtifact` → OCR/UIA/browser probe 都显式标记该 artifact → 再取得 stability `CaptureArtifact` 并比较 window identity、viewport、origin、tab identity、截图 SHA。只有 stability capture 与 source capture 全部相同，epoch 才是 `stable=true`；任何差异、probe 捕获时间越过允许窗口或 browser 没有 stable tab identity 都使 epoch 失败。no-click 可记录不稳定的拒绝证据，但 real click 必须有 stable epoch。所需 anchor evidence 需来自同一 source `capture_id`，且每个 `evidence_ref` 可追溯到不可变 raw capture/provider artifact。

### 5.2 `reviewed_workflow_execution_envelope_v1`

信封由**不可变、已签名 claims**和 SQLite 内的**可变消费状态**组成，二者不得混写。信封绝不经过 public API，也不含可由调用者替换的坐标。

```json
{
  "contract_version": "reviewed_workflow_execution_envelope_v1",
  "envelope_id": "env_...",
  "signed_claims": {
    "attempt_id": "rwrla_...",
    "asset_content_sha256": "64-lowercase-hex",
    "transition_id": "results.open_detail",
    "selection_sha256": "64-lowercase-hex",
    "window_binding_id": "window:12345",
    "window_identity_sha256": "64-lowercase-hex",
    "fencing_token": 42,
    "capture_lineage": {
      "capture_id": "capture_...",
      "screenshot_sha256": "64-lowercase-hex",
      "viewport_size": {"width": 1200, "height": 800}
    },
    "grounding_sha256": "64-lowercase-hex",
    "gate_sha256": "64-lowercase-hex",
    "approved_plan_id": "server-owned-plan-id",
    "approved_plan_sha256": "64-lowercase-hex",
    "action_type": "open_detail",
    "issued_at": "2026-08-21T00:00:00Z",
    "expires_at": "2026-08-21T00:05:00Z",
    "key_id": "live-replay-current",
    "alg": "HS256"
  },
  "signature": "base64url-hmac-sha256"
}
```

SQLite mutable row 是 `envelope_id`、`state=unconsumed|consuming|consumed|expired|revoked`、`consumed_at`、`action_receipt_ref` 和 row version；它不在签名消息中。签名消息为 `contract_version`、`envelope_id`、`signed_claims` 的 canonical JSON。HMAC key 只能由 `REVIEWED_WORKFLOW_LIVE_REPLAY_HMAC_KEY` 环境变量或受操作系统访问控制的 keyring 按 `key_id` 读取，不能写入 SQLite、trace、response 或日志；`key_id` 未解析、key 长度不足或 keyring/env 未配置时，`real_click` 必须以 `execution_signing_key_unavailable` fail closed。`no_click` 不读取也不需要该 key。

仅 state store 能把 `unconsumed` 原子改为 `consuming`。real dispatcher 接收的唯一 replay 参数是 `envelope_id`；它加载 claims 和 plan，重新验证签名、expiry、attempt state、lease owner、当前 fencing token、window identity、foreground、capture SHA/viewport 和 `approved_plan_sha256`，然后在同一事务中保留消费权。任何验证失败都不得点击。`consumed`、`expired` 或 `revoked` 信封不能再次执行；普通 `approved_plan_id` 分支不能加载标记为 replay-only 的 plan。

### 5.3 `reviewed_workflow_live_replay_attempt_v1`

```json
{
  "contract_version": "reviewed_workflow_live_replay_attempt_v1",
  "attempt_id": "rwrla_...",
  "request_sha256": "64-lowercase-hex",
  "idempotency_scope": "principal-id:idempotency-key",
  "asset_id": "...",
  "asset_content_sha256": "64-lowercase-hex",
  "requested_transition_id": "...",
  "window_binding_id": "window:12345",
  "lease_id": "lease_...",
  "fencing_token": 42,
  "state": "created",
  "action_attempted": false,
  "state_advanced": false,
  "source_observation_id": "obs_...",
  "selection_sha256": "64-lowercase-hex",
  "grounding_sha256": "64-lowercase-hex",
  "gate_sha256": "64-lowercase-hex",
  "envelope_id": null,
  "action_receipt_ref": null,
  "post_observation_id": null,
  "verification_ref": null,
  "failure": null,
  "recovery": {"attempts_used": 0, "decision": "none", "repeat_action": false},
  "created_at": "2026-08-21T00:00:00Z",
  "updated_at": "2026-08-21T00:00:00Z"
}
```

持久状态只允许 `created`、`prepared`、`dispatch_started`、`dispatched`、`verified`、`failed`：

- `created`：以 idempotency scope、key 和 canonical request hash 原子保留 attempt；尚未取得窗口 lease，也没有任何执行事实。
- `prepared`：lease、资产、source observation、resolution、selection、fresh grounding、Gate 已验证；`action_attempted=false`。
- `dispatch_started`：信封已原子保留给 Action API，是否已产生物理点击未知；这是 crash-safe 的不重试边界。
- `dispatched`：Action API 返回可信 receipt；`action_attempted=true`，无论 receipt 成功或失败。
- `verified`：post capture 与 `verify_transition_result` 已验证且 `state_advanced=true`。
- `failed`：安全终态；记录分类失败和不重复的 recovery outcome。`blocked` 仅是 response 投影，持久化为 `failed` 或尚未进入 `prepared` 的拒绝事件。

状态转移以 SQLite `BEGIN IMMEDIATE` 实现；attempt row 版本号 CAS，所有 audit event append-only。每次成功取得/续租同一 window binding 都分配严格递增的 `fencing_token`；lease、envelope 和 dispatcher 必须使用该精确 token。数据库打开时设置 `PRAGMA journal_mode=WAL`、`PRAGMA synchronous=FULL`、`PRAGMA foreign_keys=ON`、`PRAGMA busy_timeout=5000`；commit 成功后才能确认 durable state。raw screenshot/provider blobs 先写入同卷临时文件，flush、`fsync`、SHA-256 验证后以内容 hash 原子 rename，再写入引用它的 SQLite transaction；目录项亦必须 fsync。运行目录固定为 `runtime_state/reviewed-workflow-live-replay-v1/`，内含 `live_replay.sqlite3`、`evidence/`、`envelopes/`；raw artifacts 用 content hash 命名并以相对 evidence ref 引用。

## 6. 一条 transition 的时序

1. 验证 public 请求、principal 和 idempotency；服务器重新读取 registry 与 asset，重新计算 hash，拒绝 hash 不匹配、未发布或非 v2 资产。
2. 获取 bound window，构造稳定 `window_binding_id` 与 identity hash；对该 ID 取得互斥 lease。lease TTL 为 90 秒，每个有副作用阶段前续租；释放仅由 owner 或过期清理完成。
3. 通过 `ScreenshotService` capture；对同 capture 执行 OCR/UIA/screen-reading，web 同时执行 HWND-scoped browser probe；保存 evidence，生成 `trusted_live_observation_v1` 与严格 pure observation。
4. 调用 `resolve_current_state`；从 asset 重新验证 `requested_transition_id`，调用 `select_verified_transition`。source state、transition、origin、human confirmation、stop boundary 任何一项不合格即失败，无点击。
5. 以 selection 的 `element_ref` 进行**新的**同 capture grounding；生成 strict `reviewed_workflow_current_grounding_v1`，调用 Gate 获得带 selection/candidate/capture binding 的 `pre_click_decision_v1`，再调用 `validate_current_grounding`。
6. `no_click` 模式在此结束：写入 verification-compatible preview evidence，`action_attempted=false`，返回 `verified` 仅表示 no-click chain verified，`state_advanced=false`。它不创建 envelope、不调用 Action API。
7. `real_click` 模式先验证 rollout 与 server-side operator approval；创建信封和 approved plan，原子写入 `prepared`。在同一 lease 下把 attempt 改为 `dispatch_started`，随后才调用 Action adapter。
8. Action adapter 消费信封并用一次 `execute_recognition_plan` 调用执行。调用前 Action API 再 capture/核验 source binding；调用后存储不可伪造 receipt。只要进入 `dispatch_started`，`action_attempted` 在恢复逻辑中按 true 对待。
9. receipt 返回后原子写为 `dispatched`。即使 action 返回失败、超时或连接中断，也不得再调用点击；只允许观察。
10. 重新 capture、重新构造 post observation，并调用 `verify_transition_result(asset, selection, trusted_operation_result, post_observation)`。只在目标 state 唯一、post capture ID 新、origin 与 operation lineage 合法时写 `verified`；否则写 `failed`。
11. 在任何终态撤销未消费信封、写 audit event、释放 lease。`verified` 和 `failed` 的重复 idempotency 调用只读回放结果，绝不重新 capture 或点击。

## 7. 并发、幂等与崩溃规则

- lease key 是 `window_binding_id`，不是 asset、principal 或标题。任何 active lease 均拒绝另一个 attempt，即使请求的是不同 asset。
- idempotency key 的 scope 是 authenticated principal 加 key；同一 canonical request hash 复用 attempt，哈希不同必冲突。服务端生成的 recovery observation 不改变原 request hash。
- 同一 attempt 的 in-flight 重入返回 202，不创建第二个 envelope，不触发第二次 action adapter。
- 进程启动恢复按状态扫描：`prepared` 可撤销 envelope 后从 source capture 重新观察并至多一次 reground；`dispatch_started` 必须标记 `action_attempted=true`，禁止执行，做 post observation；`dispatched` 只做 post observation/verification；`verified` 和 `failed` 只返回已有结果。
- Action API 调用超时、worker 崩溃、OS 输入回执丢失、数据库在点击后写入失败都归类为“点击可能已发生”。它们进入 `dispatch_started` recovery，永远不重试 action。
- lease 过期不能让新 owner 重放 `dispatch_started` attempt；新 owner 只能创建新 observation 的新 attempt，且需新的 idempotency key。旧 attempt 保留审计和 safe-stop 结果。

## 8. 错误分类与恢复矩阵

错误采用稳定 `code`、`stage`、`retryable`、`action_attempted`、`evidence_refs`。错误消息不得包含 secrets、原始 UIA tree 或截图路径。

| 代码 | 阶段 | 是否点击 | 处理 |
|---|---|---:|---|
| `public_authority_injection`、`request_contract_invalid` | request | 否 | 422，拒绝请求 |
| `asset_not_published`、`asset_lineage_mismatch`、`stop_boundary`、`human_review_required` | asset/select | 否 | safe stop，人工审核 |
| `bound_window_missing`、`window_identity_mismatch`、`foreground_changed` | window | 否 | safe stop；重新绑定后以新 key 重新发起 |
| `lease_conflict`、`idempotency_conflict`、`attempt_state_conflict` | store | 否 | 423/409；只读取 owner attempt |
| `capture_unavailable`、`provider_unavailable` | observe | 否 | 503；同一 `prepared` attempt 可重新 observe，最多一次 |
| `current_state_unresolved`、`current_state_ambiguous`、`transition_not_available`、`transition_ambiguous` | resolve/select | 否 | safe stop，人工审核 |
| `target_unresolved`、`grounding_ambiguous`、`stale_candidate`、`capture_lineage_mismatch`、`stale_approved_plan` | grounding/Gate | 否 | 重新 capture、resolve、reground 一次；第二次失败 safe stop |
| `pre_click_rejected`、`final_submit_visible`、`dangerous_action_blocked` | Gate | 否 | safe stop；绝不降级或换目标 |
| `envelope_invalid`、`envelope_expired`、`envelope_consumed` | dispatch precondition | 否 | safe stop；需新 attempt |
| `action_timeout_unknown`、`action_transport_lost`、`action_receipt_invalid` | dispatch | 可能 | 不重试；post observe 后 safe stop 或验证 |
| `post_capture_missing`、`post_capture_not_new`、`post_action_failure` | verify | 已尝试 | 仅 observe，不重试；失败后人工审核 |
| `destination_mismatch`、`unexpected_origin`、`unexpected_new_tab` | verify | 已尝试 | 立即 safe stop，锁定 attempt，人工审核 |

恢复严格使用 `build_recovery_decision` 的语义：仅在未进入 `dispatch_started` 且 `attempts_used=0` 时允许一次 `reobserve_and_reground_once`；点击后只允许 `observe_without_repeat`；所有其他情况 `safe_stop_human_review`。任何 recovery 的 `repeat_action` 必为 `false`。

## 9. 安全不变量

1. 资产、状态、transition、window、capture、candidate、Gate、approved plan、envelope、receipt 和 post observation 必须有完整可验证 lineage；任一缺失即无点击。
2. reference ROI、旧 bbox、旧 click point、旧 capture、UIA runtime ID、窗口标题和文件路径都只能作定位先验，不能单独授权执行。
3. Gate 必须在同一 capture 上绑定精确 `selection_sha256`、candidate ID、element ref、click point、截图 SHA 和 viewport；任何不等即拒绝。
4. envelope 是 one-shot、短时、服务端签名、服务端消费；其 source capture、window identity、Gate 与 plan 的任一变化都会使其失效。
5. 所有点击经 gated Action API；controller、provider 和 public endpoint 都没有直接 `input_controller.click_point` 权限。
6. `max_execution_attempts=1` 是 Action adapter、Action API envelope branch 与 store state 三层共同强制，而非调用者约定。
7. `final_submit`、submit、send、confirm、payment、purchase、delete、open_external_apply 及其别名始终拒绝；即使资产、approval 或 provider 标记允许也不得执行。
8. web 动作需同 HWND、same-origin 与 no-new-tab 约束；native 动作需 executable/product identity 一致。foreground/window identity 变化立即使 envelope 失效。
9. 只有全新 post capture 解析为准确 target state 才能推进；“API 200”“click executed”“pixel changed”均不足以推进。
10. 证据和审计 append-only；用户面板文本、报告文件名或 operator note 不是验证证据。敏感截图与 provider raw output 只保留在受控 evidence store，public response 仅给 ref。

## 10. Provider 接口边界

`LiveObservationProvider` 和 `LiveGroundingProvider` 均为可替换 adapter，但返回值仅为候选事实，controller 必须统一规范化、绑定 capture、存证并再验证。

```python
class LiveObservationProvider(Protocol):
    provider_id: str
    provider_version: str
    def observe(self, *, capture: CaptureLineage, window: BoundWindow, asset: Mapping[str, Any]) -> ProviderObservation: ...

class LiveGroundingProvider(Protocol):
    provider_id: str
    provider_version: str
    def ground(self, *, capture: CaptureLineage, selection: Mapping[str, Any], observation: TrustedLiveObservation) -> ProviderGrounding: ...
```

provider 不能：签发 `selection_sha256`、设置 `eligible=true` 的最终结论、降低 policy 阈值、生成 Gate allow、创建 envelope、调用 Action API、写 attempt state，或从其他 capture 移植 bbox/click point。provider 返回必须包含 provider ID/version、source capture ID、raw artifact hash 和 evidence ref；controller 拒绝缺 provenance、capture 不同、schema 非法、confidence 非有限或几何越界的返回。模型屏读只作为一个 provider，OCR/UIA/browser probe 的交叉证据不一致时取拒绝，不采取多数投票放行。

## 11. 测试与发布阶段

### Phase 1：纯合同与状态存储

- 为每个 attempt 状态转移、CAS、lease TTL、同 key 幂等、不同 hash 冲突、recovery、envelope HMAC/expiry/consume 编写离线 pytest。
- 复用 `tests/test_reviewed_workflow_replay_v2.py` fixtures；新增测试证明 public payload 中任意 `bbox`、`candidate`、`gate`、nested injection 都被拒绝。
- 注入崩溃点：`prepared`、`dispatch_started`、Action API 返回前、`dispatched`、post capture 前、verification 前；断言无点击 retry。

### Phase 2：模拟 live providers 与 Action API adapter

- fake `ScreenshotService`、OCR/UIA/browser probe 与 Action API；验证相同 capture lineage 成功，SHA、viewport、origin、window identity、candidate、Gate 任一不一致都在点击前阻断。
- 验证 adapter 传入 `max_execution_attempts=1`、`capture_live=true`、strict lineage，且只调用 Action API 一次。
- 验证 final-submit、external origin/new tab、foreground drift、ambiguous state、destination mismatch 和 unknown action outcome 的 safe-stop/audit。

### Phase 3：no-click 集成试运行

- rollout 默认仅接受 `execution_intent=no_click`；在合成 fixture 和已审核的低风险真实窗口上运行 capture→resolve→ground→Gate→preview evidence，但断言没有 envelope、没有 Action API real call、`action_attempted=false`。
- 记录失败分类和 evidence lineage，先修复共同 runtime invariant，再扩大覆盖；不得以 fallback 隐藏 provider、capture 或 binding 根因。

### Phase 4：显式 real-click 批准后的窄验证

- 只有 Phase 1–3 全部通过、服务器 rollout 开关开启、操作者在受控 UI 中创建一次性 `real_click` approval 后，才允许每个已审核 low-risk transition 进行一次真实点击。
- 每次只验证一个 transition，并要求 post capture target state；失败立即回到 no-click，禁用该 asset/transition 的 real-click rollout，保留审计，不重复点击。
- 永不在此阶段启用 form fill、continue、upload、final submit 或多步自动执行。

## 12. 文档影响与验收

实现时需同步审查并按实际公开行为更新：`README.md`（live replay capability 与 no-click 默认）、`PROJECT_SUMMARY.md`、`ARCHITECTURE.md`（controller/store/envelope 边界）、`CURRENT_STATE.md`、`NEXT_STEPS.md`、`RUNTIME_STATE_GRAPH.md` 与 `RUNTIME_STATE_GRAPH.zh-CN.md`（五个 durable states）、`API_FIELD_REFERENCE.zh-CN.md`、`AGENT_API_WORKFLOW.md`、`ACTION_PATH_GRAPH_SPEC.zh-CN.md`。现阶段本设计文件不宣称这些实现或文档更新已经发生。

完成验收条件：

1. public request 无法传入任何 observation、selection、bbox、click/candidate、Gate、approved plan 或 envelope；递归注入同样失败。
2. 一次合法 no-click 请求可完整产生可审计的 source observation、selection、grounding、Gate 和安全预览，且没有 action attempt。
3. real-click 仅在显式 rollout/approval 下可用，并由 one-shot envelope、per-window lease、fresh capture 和 Gate 强绑定。
4. 点击开始后，所有重入、超时、进程崩溃和恢复路径都绝不重复点击。
5. 只有新的 post capture 证明 target state 时记录 `verified`/`state_advanced=true`；所有负控与危险动作保持 safe stop。
