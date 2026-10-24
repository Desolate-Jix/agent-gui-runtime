# Use the current Agent (0.1.7)

[简体中文](CURRENT_AGENT_MODE.zh-CN.md) · [Execution guide](../EXECUTION_GUIDE.md)

Status: execution **0.1.7**, 2026-10-24. The CLI, setup alias and `CurrentAgentClient` are included in the delivered artifact. Source acceptance passed 20 7-Zip steps on one connection; separate installed acceptance passed five Calculator clicks, cancellation controls and cleanup. See the [release record](../releases/EXECUTION_017_20261024.md) and [source live evidence](../verification/CURRENT_AGENT_LIVE_20261024.md). The old 0.1.6 installer does not contain this adapter.

## What this mode does

The connected main agent reads original Runtime screenshots, locates each target and judges the result. Runtime binds the screenshot and request, checks window identity, freshness, cancellation and input authorization, dispatches the original action once and returns its receipt. Keep one persistent MCP connection and one desktop input owner.

The supported click loop needs no independent Runtime vision or Decision API, no local model weights and no visual subagent. It still depends on the hosting agent's image support and model service and consumes that service's quota. This is not an offline or zero-cost claim. Runtime does not infer vision from a model name, silently select another source or send screenshots to another model when this route is unavailable.

The two main choices are **Use the current Agent** and **Use an external model API**. Existing `local` and `agent_delegate` routes remain advanced choices. Selecting a mode applies to a new session; it does not replace a frozen pending request's source.

## Connect and declare capabilities

Use a prepared Windows API/Agent Python environment; Python 3.12 is recommended. Initial dependency setup can download packages:

```powershell
.\scripts\setup_instant.ps1 -RecognitionSource agent_current -DataDirectory "D:\AgentReviewInstantData"
```

From the 0.1.7 installation or matching source directory, start the persistent UTF-8 JSONL entry:

```powershell
.\.venv-agent\Scripts\python.exe .\scripts\execution_client.py --current-agent --data-dir "D:\AgentReviewInstantData" --client-name "my-agent-client" --client-image-transport supported --client-current-vision supported --allow-actions
```

`--allow-actions` is an explicit input opt-in and must reflect actual operator authorization. Omit it for a connection without action permission. Client capability declarations do not authorize input. A label such as `my-agent-client` identifies the client; it is not evidence of image support.

`image_transport` and `current_vision` must both be `supported` before an action can be prepared. Omitted values are `unknown`; `unknown` or `unsupported` allows status inspection but blocks the dependent action. Declare `supported` only when the connected agent can actually receive and read the original images.

The new selection rejects `--luna-api`, a different `--recognition-source`, `--api-profile`, `--decision-profile`, `--delegate-profile`, `--model-directory`, `--prepare-models` and `--administrator`. The new adapter supports ordinary-permission sessions only: the existing UAC bridge rebuilds its child environment and does not provide this mode's Decision-isolation guarantee. The legacy administrator route remains available. `--recognition-source agent_current` can accompany the alias. The older explicit `--recognition-source agent_current` route remains available, including its optional Decision configuration, and does not select this adapter automatically. The omitted-mode local default and existing API route retain their original behavior.

## Generate an MCP entry

This 0.1.7 convenience alias writes `mcp-config.local.json` and `mcp-config.local.toml` in the current Runtime directory:

```powershell
.\.venv-agent\Scripts\python.exe .\scripts\configure_instant_mcp.py --current-agent --python "$PWD\.venv-agent\Scripts\python.exe" --data-dir "D:\AgentReviewInstantData"
```

It generates the standard `agent-review-instant` server with `--recognition-source agent_current`; it does not connect, call a service, change global Codex/MCP settings or reload an existing client. Both generated formats set `AGENT_GUI_DECISION_PROFILE=""` in this server's environment, overriding an inherited Decision profile. The maintained `InstantSession` and `DecisionService` loaders treat that empty value as disabled. The persistent adapter separately removes the variable from its child environment copy. Neither changes the parent/global environment. Preserve other servers when merging the entry and reconnect explicitly. The generator does not fabricate `ClientVisionCapabilities` or enable input. Existing `--enable-local-input` remains an explicit host opt-in; each caller must still satisfy its capability and input gates.

The alias rejects API, Decision, delegate and local-model options, `--administrator`, and a different explicit recognition source, before writing either output. Omitting the alias preserves the legacy source choices, administrator route, inherited Decision behavior and default `local` validation. No fallback route is chosen automatically.

## Caller workflow

`CurrentAgentClient` subclasses `ExecutionClient` and retains its MCP transport and receipt checks. The JSONL entry exposes explicit `agent_prepare`, `agent_resolve`, `agent_continue`, `agent_status`, `agent_cancel`, `agent_verify` and `agent_complete` actions. It manages the original command identity, grounding request and capture separately from new outer control-request IDs.

These are message shapes. Replace `123`/`456` with the actual handle/process ID from this session's discovery. Send each dependent line only after inspecting the previous response:

```jsonl
{"request_id":"discover-1","command":{"kind":"discover"}}
{"request_id":"select-1","command":{"kind":"select","handle":123,"process_id":456}}
{"action":"agent_prepare","request_id":"click-1","command":{"kind":"step","operation":"execute_recognition_plan","request":{"goal":"Open Settings","click_kind":"single"}}}
```

The remaining messages depend on the fresh response and the image you actually read; do not prepare coordinates in advance:

1. Discover and select the actual target window through the same session. Inspect the ready/status result, client capabilities and input permission.
2. Use `agent_prepare` with a basic click command. This submits one original command and waits for its fresh grounding request. If the result is `running`, `pending`, `result_unknown` or still needs an image, use `agent_status`; do not submit the click again.
3. Only resolve when the phase is `awaiting_grounding` and `current_agent.original_image` is present. Read its saved `image_path` as the original PNG, then return a strict `grounding.v1` result using `current_agent.pending_grounding_request_id`, `capture_id` and `image_size`; coordinates are capture-image pixels. Use `absent`, `ambiguous`, `unsupported` or `error` honestly when appropriate.
4. Use `agent_resolve` to validate the result, then `agent_continue` to continue that same command. Resolve itself does not click. Do not substitute a separate `grounding_execute` or resubmit the original click.
5. At `verification_required`, inspect the action receipt and `current_agent.verification_image`, then record the main agent's judgment through `agent_verify` (`success`, `failure` or `uncertain`). After input was dispatched, `success`/`failure` must bind `evidence.request_id` to `current_agent.verification_request_id`, `evidence.sha256` to the original result image hash, and `evidence.capture_id` to that image's capture ID when present. The adapter rechecks the saved file/hash. This checks evidence binding; it does not prove the caller actually understood the image or grant fresh input authorization.
6. Only after that judgment, prepare the next fresh action or mark the task done with `agent_complete`. `agent_cancel` and `agent_status` refer to the tracked original command. `agent_complete` is a local completion marker; `{"action":"finish"}` or EOF closes the JSONL session and performs cleanup. Inspect the final `finished` event and `cleanup_verified` result.

Results include a top-level `status` and a `current_agent` session snapshot with `phase`, `connection_active`, `capability_status` (`eligible` or `unavailable`), the original command/current/pending request IDs, capture metadata, `verification_image`/`verification_request_id`, client capabilities, input permission, verification and completion state. `eligible` reflects declared capabilities, not proven perception. A returned `receipt` retains the original compact Runtime receipt. Use the structured IDs; do not infer completion from a transport success flag.

`{"action":"agent_status"}` reads the tracked action. After supplying the current `grounding.v1` object as `result` to `agent_resolve`, wait for `grounding_ready`, then use `{"action":"agent_continue"}`. Missing result images keep `verification_required`: read status again without replaying input. `{"action":"agent_verify","verdict":"uncertain"}` needs no image and keeps further input blocked. A proven `action_executed=false` failure/cancellation may be judged from the receipt; `success` cannot turn failed/rejected execution into success. When the actual task is done and its terminal judgment is accepted, send `{"action":"agent_complete"}`, then `{"action":"finish"}` and inspect cleanup. Prepare/resolve/continue/status/cancel accept an optional outer `request_id`; omit it to let the adapter allocate one or read its tracked pending receipt. While a receipt is pending, an explicit status ID must match that original pending ID. Verify/complete do not accept an outer request ID. Never replace the IDs inside the frozen grounding result.

Pending transport results are read using their original request ID. A wait expiry is not cancellation or proof that input did not occur. Never resend input to extend a wait. Unknown input cannot be replayed. Following navigation, scrolling or a layout change, use a new screenshot rather than reusing coordinates.

The new adapter's input entry is the managed basic-click workflow. Compatible low-level messages are limited to `discover`, `select`, `capture`, `read_text` and `instant_status`/`instant_result`/`instant_image`; `select` requires action permission and an idle or already-verified action. Local `read_text` retains its own OCR dependency; it is not a replacement for the main agent reading the image. Other low-level input, raw grounding/control or plan messages are rejected rather than forwarded around the managed workflow. Existing commands remain available through their original explicit route; that does not add them to this adapter's supported set.

## Capability matrix

This table separates code contracts, adapter scope and acceptance. “Offline” means schema, state/receipt checks or simulated transport, not a hosting agent running without a service. Source live acceptance covers 20 7-Zip click steps; separate installed acceptance covers five Calculator clicks and cancellation. Neither establishes other actions or Amadeus acceptance.

| Capability | Existing lower-level protocol | New current-agent adapter | Offline check scope | New adapter live check |
| --- | --- | --- | --- | --- |
| Click | `step/execute_recognition_plan`, agent grounding and explicit original-command continuation | Supported basic click loop; original image → resolve → continue → caller judgment | Capability admission, request/capture/image binding, state and no-replay checks | Source: 20 live 7-Zip steps on one connection; installed: five Calculator clicks passed |
| Key press | `step/press_key`, with maintained key/request and target gates | Not exposed as managed input | Existing contract inspected; not adapter acceptance | Not run |
| Scroll | `step/scroll`, with current target/input gates | Not exposed as managed input | Existing contract inspected; not adapter acceptance | Not run |
| Replace text | Explicit `step/type_text` or compatible native/legacy `input_sequence` with clearing and result checks | Not exposed as managed input | Existing request/default-route contracts inspected | Not run |
| Combined field filling | `input_sequence`; bounded `form_fill` supports up to 32 declared fields under its own checks | Not exposed as managed input | Existing contracts inspected; no end-to-end no-API claim | Not run |
| v1 linear plan | Existing click/input/read-text plan and original Main review semantics | Not accepted by `agent_prepare` | Existing plan contract inspected | Not run |
| v2 linear plan | Compatible no-Decision/native proofs and explicit Main review; semantic auto adoption has separate provider requirements | Not accepted by `agent_prepare` | Existing plan/default-route contracts inspected | Not run |
| v3 linear plan | Existing visual/Decision action-review route; click/input preflight requires eligible Decision auto configuration | No API-free v3 extension | Existing preflight inspected; rejection boundary preserved | Not run |
| Cross-window work | Window discovery/selection exists; plans and continuations remain bound to their original host/target | No automatic cross-window workflow | Binding contracts inspected; not cross-window acceptance | Not run |
| Disconnect/restart recovery | Original receipt read-back and experimental proof-gated new-epoch recovery exist; neither replays old commands or takes over a workflow automatically | No reconnect or host-restart continuation guarantee | Receipt/no-replay boundary only; no restart acceptance | Not run |
| Administrator/UAC | Existing explicit administrator bridge remains available through legacy routes | Unsupported; rejected before connection/config output | Rejection and ordinary-session Decision-isolation loading checked | Not run |

An omitted `field_evidence_mode` can adopt the public visual-input default. That route and v3 visual click/input review still require an enabled `decision_profile.v2`, auto mode and eligible conditions/budgets. This mode does not loosen those checks, convert the request to `legacy`, or promise all v3/default visual input without an API. See [visual input](VISUAL_EXECUTION_INPUT.md) and [task plans](TASK_PLAN.md).

## Evidence and limits

The [2026-10-24 source live run](../verification/CURRENT_AGENT_LIVE_20261024.md) completed 20 7-Zip steps through original image → resolve → continue → after image → verify on one persistent MCP connection. Separate controls rejected wrong-hash review, blocked uncertain judgment and input after complete, and cancelled awaiting_grounding to real cancelled/action_executed=false. Cleanup passed. No independent vision/Decision service profile or provider key was configured. The hosting agent still used its own model service. Separate installed acceptance used the actual installed-root CLI with -I/-B: Calculator C → 1 → + → 2 → = displayed 3, with Agent review of each original frame. Post-action cancellation preserved completed/action_executed=true while blocking further input; a separate awaiting-grounding cancellation reached cancelled/action_executed=false and rejected late continuation. Both hosts verified cleanup. All 684 installed payload hashes matched before/after the run, and native uninstall passed. The [release record](../releases/EXECUTION_017_20261024.md) preserves the tested installer identity and final documentation-only repack boundary; the source 20 steps are not 20 installed steps.

Earlier setup/API/Decision/startup qualification passed 43 offline checks, with a separate 40-check simulated adapter group. These are earlier snapshots and must not be added to the current regression count. The [release record](../releases/EXECUTION_017_20261024.md) owns the current qualification and artifact scope.

Implementation references: [client adapter](../../scripts/current_agent_client.py), [CLI](../../scripts/execution_client.py), [setup generator](../../scripts/configure_instant_mcp.py), [capability negotiation](../../app/vision/recognition_source.py), [grounding validation](../../app/vision/grounding_contract.py), [public input defaults](../../app/execution/public_input_defaults.py) and [Decision preflight](../../app/execution/action_review.py).

Further acceptance must retain original failures and per-step screenshot/request/receipt bindings. Target absence, ambiguity, unknown input and disconnect recovery have not gained comprehensive acceptance. Report executor time, caller gaps and measured user waits separately; unobservable hosting-agent usage stays unknown. No speedup, cost-saving percentage or general success rate is established. Learning stays paused; thresholds and input gates are unchanged.

## Amadeus and update boundary

The Amadeus 0.0.4 wheel retains its fixed `instant-v0.1.6` URL and existing API-route Skill. This round does not establish current-agent mode in Amadeus. A compatible HTTP protocol lets Runtime patches retain an unchanged extension. Automatic checks, downloads and switching are not implemented: see the [Amadeus](AMADEUS_UPDATE_STRATEGY.md) and [Runtime](RUNTIME_UPDATE_STRATEGY.md) strategies.
