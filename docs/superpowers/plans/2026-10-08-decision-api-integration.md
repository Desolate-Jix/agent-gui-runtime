# Decision API integration / 判断 API 接入计划

> For agentic workers: use the code-implementation loop and bounded Sol ultra delegation. Preserve unrelated edits; no commits, publishing, packaging or live desktop input from workers.

**Goal / 目标:** 接入可选 OpenAI Decisions 服务，在明确的结果核验上减少 Agent 往返，保留本地图像核验快速路径，并提供独立的动作前判断位置。

**Approved design / 已批准设计:** 2026-10-08 本对话：本地匹配优先，Decision 判断变化，主 Agent 处理疑难；共享输入合并独立问题；不确定、拒答、超时和冲突交回 Agent；实测验证准确率、总耗时和成本，再扩大自动采用。用户已明确批准开发。

**Workspace / 工作区:** `codex/dev-decision-api`, based on published `origin/main` db443ef99eee67cd4dbaf7f57ce997d1542b2fd1. Existing dirty maintenance and stable release worktrees stay preserved.

**Architecture / 架构:** `app/judgment` owns profile, evidence binding, one persistent HTTP client, batching and durable replay protection. Execution and learning consume the same service; provider output never directly dispatches input. Default absent profile has zero network/credential/evidence work. Shadow is the configured default; automatic result adoption is explicit and scoped to exact approved conditions.

## Global constraints / 全局约束

- Only `POST https://api.openai.com/v1/decisions`, model `gpt-6-luna`; no SDK or new dependency needed (existing httpx 0.28.1).
- Credentials from a named environment variable, default `OPENAI_API_KEY`; never persist, echo or pass key in argv. No worker reads the user's key or calls the paid API.
- No retries, redirects, arbitrary image URLs or file paths outside owned session roots. Verify original image SHA and window identity before upload. UTF-8 throughout.
- Pending/unknown input cannot be replayed; repeated verification must read its prior durable result, including failures. Model replies cannot authorize input or erase original receipts.
- Keep existing local match success and definitive local failure paths. Corrupt/stale/cross-window evidence is not a semantic mismatch to route around.
- Before-action gates never bypass existing coordinates, window freshness, authorization or final-submit rules. Shadow does not change action admission.
- Worker model `gpt-6.1-sol`, effort `ultra`, bounded context. Main performs final integration and acceptance.

## Shared service contract / 共用服务合同

`DecisionService.from_environment(session_dir)` reads optional `AGENT_GUI_DECISION_PROFILE`, returning a disabled service when absent. Profile JSON has version `decision_profile.v1`, mode `off|shadow|auto` (default shadow), `api_key_env`, `timeout_seconds` (default 8), probability thresholds `pass_threshold` (default 0.9) and `fail_threshold` (default 0.1), per-scope request cap (default 20), and `auto_conditions` (exact approved condition strings, default empty). Thresholds are provisional configuration, not a claim of calibrated accuracy.

`service.evaluate(*, request_id, execution_request_id, condition, frames, mode='execution', phase='after_action', run_id=None, step_id=None, action=None) -> dict`

- Frames: list of 1–2 dicts, each `capture_id`, `sha256`, `image_path`, `window_identity` containing handle/process_id/process_create_time, and role `before|after`. Before-action uses one current `before` frame; after-action exactly one `after` and optional `before`.
- `condition` is explicit, observable expected state. No automatic conversion of 'screen changed' into success. `action` is optional trusted proposed-action context for before-action classification, never an executable model reply.
- Result: status, verdict `success|failure|uncertain`, phase, request binding, predicate probabilities, usage, timings, `adopted` bool, `authorizes_action=False`, `automatic_retry_allowed=False`, evidence hashes. `adopted` only when mode auto, condition explicitly listed, and evidence and probabilities valid; before-action never grants action authorization.
- Two predicates share one request: condition met + visible error (after) or unsafe effect (before). False/refusal/unknown answers preserve distinctions. No unbounded history or redundant full-frame uploads.
- `close()` releases owned HTTP client. Service persistence lives below session `judgments/`; exclusive dispatch marker prevents a crash/reopen from spending or replaying twice. Persistence must never grant trust to a forged API result.

## Task 1: Shared adapter and evidence service

- [x] Implement profile validation, provider transport and service contract in `app/judgment/*`; extend existing optional contract only where necessary without breaking its strict behavior.
- [x] Tests first: disabled has zero side effects; correctly batched request; hash/window/path rejection before HTTP; malformed/refusal/timeout/no retry; thresholds; durable duplicate/conflict; usage and server/HTTP timing; credential redaction; concurrent calls serialize or reject duplicate dispatch.
- [x] Run narrow tests and report failures and reruns.

## Task 2: Learning verification integration

- [x] Add optional reviewed `decision_condition` to agent_judgment verification rules (and image_check combination); retain pinned immutable program versions and no dynamic output extraction by predicates.
- [x] Route only eligible unresolved semantic checks to the service; local image success stays zero API, invalid evidence stays rejected. Build fresh same-window evidence through maintained observation interfaces.
- [x] Shadow returns advice with the existing Agent wait; auto-adopt requires allowlisted condition and valid original receipt/envelope. Persist once; preserve request/run/step bindings, cancellation and recovery.
- [x] Cover new branch, local fast path, failure/uncertain, reopen/idempotency, tampered images, cancellation and cross-window cases with focused integration tests.

## Task 3: Execution pre/post integration

- [x] Expose opt-in `decision_check` metadata (explicit condition and phase) through maintained execution command validation. Automatic after-action check shares original frame/receipt without another Agent tool call.
- [x] Place before-action check at the actual fresh candidate boundary where candidate geometry is known. Unsupported routes report not applied, never imply universal coverage. API cannot dispatch actions or substitute coordinates.
- [x] Persist original input status separately from task effect; shadow/uncertain leaves Agent review, eligible auto result can resolve it. Polling returns saved results without another API request.
- [x] Cover allowed, rejected, uncertain, stale-after-wait, no duplicate input and disabled behavior in the common action path.

## Task 4: Integration, configuration, evidence and documentation

- [x] Wire service lifecycle into the maintained host and command bridge; configuration must survive ordinary/UAC launch without exposing secrets. Add a sample profile and user instructions; no version bump or packaging in this source development task.
- [x] Main runs affected contract/integration tests and a small bounded real API smoke through production adapter using synthetic-only evidence. Record actual calls/tokens/cost and server/client timings; do not call this a GUI end-to-end benchmark.
- [x] Compare local-fast-path call count and injected-provider behavior against old paths; define later fresh desktop A/B acceptance for real accuracy and task p50/p95. Do not claim an improvement from one API timing.
- [x] Update README, optional-judgment doc and local state notes with implemented vs pending scope. Independent final source review; fix relevant findings and rerun affected checks.

## Review focus / 审阅重点

- Screenshot or window changes while API waits: invalidate pre-action result before dispatch.
- Host exits after request was sent: return unknown and retain dispatch marker, no automatic second charge.
- Local template fails because evidence is corrupt: do not turn it into a successful semantic check.
- Learning pending step/cancellation changes during judgment: revalidate before settling.
- Shadow or uncalibrated conditions: preserve Agent review and never imply auto authorization.
