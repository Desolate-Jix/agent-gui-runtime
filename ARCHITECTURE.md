# Architecture

Last updated: 2026-08-27.

## 2026-08-27 Task 6 closed service spine

Task 6 P1/P2 plus Amendment C is closed as an internal, closed-reference incumbent service spine. The P1/P2 authority projections are read-only; production and test composition are factory-minted and reject substituted components. B1 now proves same-reservation gated-launch recovery without a second spawn and verifies the exact cleanup receipt before C can terminalize.

The real Registry/spawn/Task 5 E2Es use a harmless recorded Qwen response only. They perform no actual provider inference, GUI action, click, fill, submit, workflow publish, or other action execution. Final main verification was `252 passed, 333 deselected`; compile and diff checks passed; relevant process, listener, and UI residue was zero. This is **not** an Omni/Qwen/VISTA accuracy result and it does **not** authorize live clicks.


## Portfolio Release v1 — Frozen Position

### Target product definition

> **A model- and agent-agnostic Windows GUI workflow runtime that turns replaceable perception into human-reviewed operational knowledge and exposes gated, verifiable semantic actions to interchangeable computer-use agents.**

> **Reviewed workflows constrain and inform the Agentic Loop; they never replace current observation or authorize execution.**

这个 Runtime 不把 perception model 或 Computer-Use foundation model 本身作为核心。稳定中层由四个合同构成：

```text
Perception Provider Contract
        ↓
Canonical UEI Evidence
        ↓
Reviewed Workflow Asset Contract
        ↓
Reliability Runtime
        ↕
Agent Runtime Contract (Observation / Semantic Intent)
        ↕
Runtime Result & Verification Receipt Contract
```

### Authority boundary

- **Providers propose evidence.** Provider confidence 不能成为 execution authority。
- **Agents propose intent.** Computer-Use Agent 选择 semantic action，不能提交可绕过 Runtime 的历史 bbox/click point。
- **The runtime grants bounded execution authority.** Runtime 必须使用 current capture，重新 grounding，执行 Gate，限制单步 action，验证效果并产生 receipt。
- Historical coordinates may be retained as evidence or relocation hints, but never as executable authority.

Encountering form-fill / Continue / terminal-action classes is a negative-control SAFE STOP; no form mutation belongs to Portfolio v1.

### Four contract surfaces

1. **Perception Provider Contract:** native provider output 通过 trusted adapter 投影到 UEI；required core + optional evidence extensions；保留 provenance/revision。
2. **Reviewed Workflow Asset Contract:** semantic states/transitions、anchors、preconditions、expected effects、verification、risk/safe-stop、provenance 和 revision/hash。
3. **Agent Runtime Contract:** `agent_observation_v1` 向 Agent 暴露 matched state 与 available semantic actions；`agent_intent_v1` 只接受 observation-bound semantic intent。
4. **Runtime Result & Verification Receipt Contract:** `runtime_result_receipt_v1` 绑定 intent、current observation/candidate、Gate、operation、verification、next state、safe stop 和 trace refs。

### Portfolio proof boundary

- **Proof A:** Built-in 与 OmniParser recorded/Shadow output → same UEI / provider-neutral Review contract。Omni local live inference optional。
- **Proof B:** controlled SEEK Job Detail → `open_apply_flow` → Apply Entry → Safe Stop，强制 current re-ground、Gate、semantic verification 和 lineage。current semantic `open_detail` live proof 属于 post-v1，不是 frozen Portfolio v1 acceptance。
- **Proof C:** current internal Agent adapter → Agent Intent → Runtime Receipt conformance。第二个外部 Computer-Use adapter 是 stretch。

当前 frozen Portfolio v1 只能写成 bounded Quick Apply-only release，不能写成通用 live reliability proof。UEI 的 provider 质量仍是 Contract/Recorded Proof；四个 northbound contracts 保持冻结，perception 仍可替换。W3b/W5 已实现一条**内部 deterministic composition**：exact reviewed asset -> passive bound-window capture -> observed UIA origin -> pinned current recognition -> strict Agent Observation/Intent -> current re-ground -> Gate -> exact pre-dispatch pixel freshness -> one-shot backend -> durable verification checkpoint -> fresh projected C2 -> closed target-state verification -> exactly paired terminal receipt。该路径绑定 exact session/capture/SHA/viewport/HWND/PID，重算 ranking/margin，zero/low/ambiguous anchors fail closed，duplicate/restart lookup prevents re-dispatch。W4 Stop Condition 已通过独立严格审计：只有 `LiveController` mint one-time authority，`ExistingWindowsBackendAdapter` 先消费并且是唯一 authority-scope caller；`InputController` 与 `WindowManager` 的 public/private raw sinks 都有 leading guard，scripts 无 raw dispatcher，SEEK `WM_CLOSE` 已禁用，W3b observation/freshness capture 保持 passive。Desktop I/O 仍是四个 public contracts 下方的 internal SPI，不得扩张 authority。

在 deterministic composition 之外，现在另有一个**受限 controlled-live proof**：当前 active asset `8284e172...391b7` 通过 current capture、fresh re-ground、Gate 和一次真实 Windows `open_apply_flow` dispatch 到达 fresh Apply Entry C2，匹配 `Choose documents`，并以 `SAFE_STOP/stop_boundary` 结束。公开投影绑定 exact receipt、effect/destination verification 与 zero form mutation；它只证明这一条 Job Detail → Apply Entry 路径。W6 已在这个 bounded Quick Apply-only boundary 内冻结；current semantic `open_detail` live proof 已移入 post-v1。这不声称 Provider accuracy、general SEEK navigation、external Agent compatibility、unattended reliability 或 production readiness。

`ExistingWindowsCurrentEvidenceAdapter` now removes duplicate recognition work without weakening anchor independence. Within one current capture, serialized raw recognition bytes may be reused only for the exact same goal. Every anchor still independently parses those bytes, matches its own target, applies its own threshold checks, and projects its own evidence. A different goal or a new capture invokes recognition separately. The related deterministic suite reports `50 passed`; this is a performance/duplicate-work improvement with code/test evidence only, not live model or SEEK proof, human review, or execution authorization.

The tracked deterministic synthetic production-composition proof now connects production `ExistingWindowsCurrentEvidenceAdapter`, the visibility adapter, `ReviewedWorkflowGateAdapter`, `LiveController`, and durable claim/receipt stores, with deterministic external-boundary doubles and `DeterministicFakeBackend`. It proves synthetic `Job Detail -> confirmation -> exactly one open_apply_flow fake dispatch -> fresh C2 Apply Entry -> SAFE_STOP/stop_boundary`, then proves a durable restart duplicate performs zero capture, recognition, or dispatch. The related suite reports `51 passed`, and an independent Sol review reports PASS. Its approvals live under `tmp_path` and all external I/O is fake: this is not real human Portfolio review, actual Windows/SEEK I/O, physical dispatch, or controlled live proof, and it does not close W2c.

The public W6 negative-control package now maps all six canonical failure classes plus two supplemental idempotency/confirmation controls. Exact-current controls load the checked-in `8284e172...391b7` asset; the remaining controls are explicitly graded as deterministic behavior-equivalent **synthetic** fixtures. Each entry declares whether its typed result is a `runtime_result_receipt_v1` or a pre-dispatch `live_controller_decision`; invalid intent is not misrepresented as a terminal Receipt. This matrix is deterministic evidence, not live failure injection.

Compiled lineage 现在显式保存经过 registry/path/SHA 校验的原始 `source_workflow_id`；`WorkflowRef.workflow_id` 与 `asset_id` 不再混用。Callsite、adapter、LiveController 与 publish boundary 都 fail closed 拒绝替换或缺失身份，旧 v2 CAS 对象需要从精确 reviewed source 重新编译，不做推断迁移。

需要人工确认的 transition 现在进入 server-owned one-shot confirmation ledger，而不是写入 `AgentIntent` 或先生成不准确的 terminal receipt。Immutable request/decision/resume/closed markers 绑定 exact claim、workflow/asset revision 与 hashes、transition/action、request C1 capture/state-resolution evidence、HWND/PID 和 fixed server TTL。相同 approve/deny 幂等，opposite decision 冲突；只允许一个 cross-process resume marker winner。Approval 仅是 evidence：exact Intent 重交后必须重新获取 window lease、fresh C1/PID、重新 resolve state、使用 private server-confirmed selection、current re-ground、Gate、pre-dispatch visibility，再 mint one-time authority 并只尝试一次 backend，之后执行 C2 verification。Crash after resume marker 返回 indeterminate recovery decision，不盲重试；denied/expired/stale/tampered/mismatched 均 zero dispatch。Loopback-only `/runtime/agent` callsite 现已公开严格的 session start、四-ID Intent submission 和 confirmation decision；它由服务器固定唯一 active asset 的完整 WorkflowRef、当前 HWND/PID 与 persisted exact Intent，不接受客户端 geometry/authority/backend/provider/path。Deterministic Portfolio test 已让 compiled `Job Detail` → `open_apply_flow` → `Apply Entry` 到达 terminal `SAFE_STOP`，但这仍不是 panel approval UI、actual Windows adapter、physical GUI 或 live SEEK proof。

Canonical release plan：`docs/superpowers/plans/2026-08-22-portfolio-release-v1-plan.md`。

The panel has one public Learning workspace. It composes capture, the nine-stage read-only recognition progress, reviewed evidence, human correction, and the application-scoped radial workflow graph without exposing Template replay, Trace audit, or PathGraph validation as separate daily pages. Those capabilities remain internal diagnostics and compatibility contracts. Execute presents single-step available-action, locate, Gate, and input surfaces; its legacy multi-step task harness remains internal. This is a presentation boundary only: learning assets remain non-authorizing, and every real operation still requires current observation, Agent choice, Gate, Operation dispatch, Trace, and post-action observation.

## Universal Evidence Interface v1 (M1 base and M2 Shadow boundary)

Universal Evidence Interface v1 retains an offline static-fixture M1 evidence boundary: closed schemas define JCS immutable refs, a test-root-only content-addressed store, a trusted registration intersection with the request and provider manifest, and pure non-authorizing OCR, UIA, and screen-parser projections. Its checked-in sidecar contains synthetic fixture bindings only and its rollout remains Disabled.

M2 adds a generic controlled local Shadow runtime behind the trusted registration intersection. It resolves immutable request/capture/profile context from the fixed store, accepts only registered enabled `local_only` Shadow adapters whose implementation version exactly matches the sealed manifest, centrally redacts common private-path and credential shapes, executes a bounded fresh worker process with fixed trusted configuration, and seals safe result plus runtime receipt refs. File-lease release fails closed on tamper/unlink/residue, and Windows termination records the descendant tree before termination and verifies every recorded PID has exited; a real parent/child regression covers that path. Production OmniParser calls remain one fresh-worker inference. The worker receives the exact restricted capture and its immutable dimensions; its normalized pixel boxes are therefore emitted as `capture_pixel_xyxy`, revalidated against that same capture by the adapter, and can enter the large-image Review projection without becoming authorization. The smoke-only benchmark is a distinct provider-version binding and runs exactly one cold plus three warm inferences inside one worker/model lifetime; the version is part of durable invocation identity, preventing benchmark/production claim recovery collisions. Successful smoke evidence copies the sealed temporary UEI store and a path-neutral report into ignored local artifacts before temporary cleanup. Review candidate post-processing is deterministic and non-authorizing: it removes only sub-threshold boxes using a 10 px cap that scales down for unusually small captures, and only merges semantics-equivalent near-identical boxes while retaining removal fingerprints and reasons. The bounded OmniParser adapter/fake-worker path is offline-tested; it is not a general provider or model-loading surface.

Learning receives only `uei_shadow_result_ref`. Each draft load revalidates that exact ref from the fixed server-owned Shadow store and derives the unchanged `uei_shadow_provider_summary_v1`; cached summaries never authorize or provide fallback. Before projecting any item, Review resolves and decodes the actual panel source image, then requires its computed SHA-256 and dimensions to match the immutable capture artifact and `image_size` exactly. A successful `review_only` result may project canonical safe items into the existing large-image editor only when that display binding and the current capture lineage both match. Items without a legal `capture_bbox` remain non-grounded evidence and are counted/skipped; malformed or out-of-range geometry, ambiguous semantic duplicates, duplicate IDs, lineage/display mismatch, or region-ID collision rejects the whole projection. The internal projection emits deterministic capture-bound review-only regions with safe text/bbox, keeps provider role/state belief only in compact provenance, merges without overwriting existing regions, and carries the standard candidate/human-review/Gate markers. A uniquely overlapping current-draft UIA item may add `canonical_role` provenance to the review region; zero or multiple acceptable supports do not promote a role, and this hybrid evidence remains explicitly separate from standalone provider accuracy. It never exposes full refs, hashes, local paths, source-coordinate payloads, transforms, opaque attributes, action templates, intent, clicks, grounding candidates, or authorization. The panel clears the derived model on programmatic source changes, manually typed source input, load/review invalidation, and stale responses.

UEI neither authorizes actions nor serves as an authorization artifact. There is no live capture, network, GUI, grounding, replay, action, Execute, migration, or remote-egress integration. Installed pinned assets are verified, but a real cold plus three-warm smoke is still unverified because fixed device-0 `nvidia-smi` free-memory preflight is below 8 GiB; no download was attempted.

`runtime_storage_cleanup_plan_v1` is the bounded retention contract for disposable generated output. Planning is read-only and considers only `logs/tmp` and `artifacts/review-overlays` older than the requested cutoff. `logs/traces` and `artifacts/learning-runs` are protected roots and cannot be cleanup targets; both are scanned as reference sources so their linked overlays remain protected. References from project documentation, tests, benchmark/golden manifests, interface-workflow reviews, Trace, learning runs, and the newest files in each managed root protect matching candidates. Apply accepts only a generated plan, rejects any plan that overlaps a protected root, verifies every resolved path remains inside an allowed root, and deletes a file only when its size and modification time still match the plan. Models, environments, fixed benchmark assets, operational memory, Trace evidence, learning drafts, and runtime state are outside this contract.

`single_application_workflow_review_v1` is the generic human-review projection between Learning Draft evidence and operational memory. The panel exposes one deduplicated interface-asset library plus the application-scoped workflow library; only the workflow library owns graph membership and transitions. `加入流程` is an explicit interface-plus-destination selection and creates no edge by itself. The graph keeps every node's fused, numbered, and source image, page details, regions, candidate actions, blockers, and verification rules together while rendering interfaces as circular points and transition operations as labelled links. Reviewed, unreviewed, invalid/stale, and disconnected states remain visually distinct, and mixed review coverage is reported separately from Agent usability. Selection places one interface at the centre and shows its directly connected neighbours; zoom, pan, cycles, converging branches, and disconnected outer rings are presentation concerns only and do not modify the persisted workflow. A latest-load guard prevents a delayed raw-draft request from replacing a workflow the reviewer explicitly opened. `修正与确认` opens the checksum-bound full-image workbench only when evidence provenance declares `clean_capture` or an explicitly editable `sanitized_clean_capture`; annotated derivatives and unclassified sources fail closed. Explicit workflow-review opens supersede a stale pending auto-load before entering the modal. Editable boxes are an independent overlay layer. The modal keeps four responsibilities separate: canvas selection, current-interface fields, selected-box semantics, and a dedicated Link Dialog for operation/transition editing. Provider operation suggestions are non-authoritative and read-only in workflow review. The Link Dialog stages operation edits against its opening revision; only its explicit save writes the edge, while Cancel, close, Escape, and backdrop discard only the dialog UI draft and never roll back the business workflow snapshot. Save requires the exact opening state identity and business-revision key, so same-ID state replacement or same-state external drift fails closed. Canonical edge editing includes success and failure conditions. Selecting one must resolve exactly one current-node control, action candidate, and outgoing edge through explicit IDs or a unique semantic binding; ambiguity clears stale focus, keeps confirmation disabled, and surfaces a local error instead of guessing by text or proximity. Standalone sources may save corrected evidence but cannot approve a workflow. Workflow-level compile, publish, dry-run, and execution-verification controls remain outside this current-interface workbench. Recomposition merges bounded edits only when stable node or edge identities still match. Saving validates graph indexes, entry-node identity, unique IDs, and transition endpoints before producing a display-only candidate. It strips runtime click points, keeps `artifact_is_authorization=false` and `execute_binding_enabled=false`, and does not create a published memory version.

The review surface and execution surface remain separate. `Publish and execution verification` only transfers the selected interface identity and goal into the existing Agent Memory panel. Publication requires explicit human approval, and Execute must still recapture the current target, perform fresh localization, pass the action Gate, and verify the result. Evidence-layer changes rerender only the screenshot so pending edits are not discarded. Concurrent requests for the same draft source are coalesced before clearing the panel, preventing a duplicate boot/history load from leaving the review workspace in a false loading state.

An executable outgoing operation retains four independent revision-bound human-review facts but exposes one final user gesture: (1) the target control or region, (2) the exact action candidate, (3) the transition edge, and (4) the source node. `确认并入库` first binds workflow, node, normalized evidence source, editor identity/generation, exact selected-box key, and state identity into one review session. Every asynchronous boundary revalidates that full session before refreshing, merging, or persisting. The only permitted source/editor change is an explicit token-checked draft-to-reviewed phase transition, which advances the expected source, editor identity, generation, and exact selection together; forced reselection cannot hide external drift. The transaction commits the current selected-box Agent-readable content descriptor into that same state revision, then validates every outgoing operation without writing approval state; only when all subjects match does it build the granular operation receipts and source-node confirmation in an isolated draft state, persist that exact draft, and replace the live state only after persistence succeeds under the opening revision guard. Each fact remains `display_only=true`, `artifact_is_authorization=false`, and `execute_binding_enabled=false`; none grants Runtime authorization. Failure may leave a safely saved, unapproved evidence revision, but it cannot leave a partially approved operation set. Any semantic or safety-fact edit invalidates the affected approval and returns the relevant scope to `needs_human_review`. `needs_learning` is an immutable safe-stop and cannot be promoted by normal Panel save. The compiler independently fail-closes each granular fact: source-node approval cannot substitute for control, action, or edge approval, and action/edge approval cannot substitute for source-node approval. Human review completion remains a user event, not an automated claim.

The contract intends to represent one application, but legacy learning artifacts do not consistently carry a capture-bound application identity. Historical source composition is therefore a review/development scaffold until consecutive captures persist that identity. The runtime must not infer identity from filenames or UI labels. Before operational-memory promotion, every node must carry compatible application/window identity and every transition must be backed by an observed sequence or explicit human review.

`application_identity_v1` is the grouping boundary for reviewed workflow memory. Browser identity is canonical domain/origin, never the browser executable alone; `accounts.google.com` and `mail.google.com` remain distinct unless a future reviewed alias explicitly joins them. A browser capture without URL/domain evidence is `needs_domain_review` and is not indexed. Native identity combines executable and stable product identity. `interface_workflow_library_registry_v1` indexes saved review candidates under that identity, while `/memory/interface_workflows/agent_context` exposes only human-reviewed planning context. The graph is a derived review view, not authority. Historical bboxes and declared destinations cannot authorize action; execution must recapture, ground, pass Gate, and verify.

The human-correction execution bridge is now explicit and separate from both Learning Mode display artifacts and CorrectionMemory rules. A candidate must first be saved as `reviewed_template_candidate_v1` with `reviewed_by_human=true`, `review_status=approved_as_assisted_template`, checksum-valid screenshot evidence, stable states, regions, actions, blockers, and verification rules. `ReviewedInterfaceMemoryStore` compiles that candidate into immutable, content-addressed `reviewed_interface_memory_v1` and atomically advances a revision-checked registry. The memory stores normalized geometry only as reference evidence; it never stores an executable historical click point.

Execute requests identify the memory plus a natural-language goal. `resolve_action_for_goal` selects one unique low-risk memory action; an explicit action ID is only an operator override. No-match, ambiguous, or high-risk resolution safe-stops before localization. A selected action captures the current target window and first applies a page-level text-anchor check. Current UIA inventory is built and ranked before memory-seeded VISTA localization. When an exact current UIA action matches the goal, that current bbox becomes the compact VISTA ROI; the historical memory bbox remains prior evidence only. A model point may ground only the ROI candidates supplied to that model call, so candidates appended later cannot inherit VISTA validation. After current VISTA grounding and rerank, `operational_memory_local_target_validation_v1` requires the selected point to agree with strict current OCR evidence near the seed's reference neighborhood. It may compose vertically adjacent OCR lines for wrapped labels, but it does not reuse the page-level loose token matcher for target identity. Only then may Gate authorize one low-risk dispatch with post-action verification. Wrong-surface, local-anchor mismatch, stale-capture, ambiguous-grounding, Gate rejection, dispatch failure, or verification failure is persisted as `operational_memory_execution_feedback_v1`. That record links the trace, reviewed candidate, source action, source region, and stable element back to human review and explicitly cannot authorize execution. Final submit, send, confirm, delete, purchase, and payment remain blocked.

`continuous_task_session_v1` is the orchestration contract for connecting several reviewed interface memories without turning any memory into authorization. A known current interface may proceed to Agent decision; an unknown interface pauses the same task for Learning Mode and human-reviewed memory publication. Each verified low-risk action returns the session to current observation, so the next interface is captured and matched again instead of inheriting historical coordinates. SEEK Quick Apply entry has an explicit confirmation boundary. External ATS and final-submit-visible surfaces terminate the current path with `safe_stop`.

`seek_continuous_demo_checkpoint_v1` binds that contract to `scripts/seek_speed_demo_runner.py`. The run directory stores the append-only session timeline and a resumable phase checkpoint. Results and job-detail surfaces may use the existing SEEK Runtime profile, while each SEEK-hosted Quick Apply step requires an active reviewed interface memory before any fill or Continue action. A missing memory stops before form mutation. After publication, `--resume-continuous-session` loads the same run directory and continues from the current application surface without reopening results. Action events retain screenshot checksum, Trace path, Agent decision, Gate summary, and post-action verification summary.

`continuous_task_learning_handoff_v1` is the panel bridge for confirmation and learning pauses. A runtime-written `logs/continuous_task_latest.json` pointer selects the latest task without recursively scanning artifacts. For `awaiting_apply_entry_confirmation / awaiting_apply_confirmation`, the current screenshot checksum and pending job identity unlock one explicit `confirm_apply_entry` action. For `paused_for_learning / quick_apply`, resume additionally requires matching active reviewed memory. The launcher reuses the same run directory and current local Runtime URL, forces `max_safe_fields_to_fill=0` and a single application step, and carries no submit authorization. The live recommendations-to-confirmation slice and offline pause-to-publication-to-resume chain are covered; post-confirmation live learning remains pending.

Learning Mode has a read-only Surface Adapter boundary between interface classification and surface-specific policy. Host-shell classification and content-topology classification are separate decisions: Browser may be the host while Chat, Mail Workspace, Media Player, Employment Workflow, or Generic describes the content. `employment_workflow` is one task adapter with page-state policies for job results, job detail, application form, and application review; it is not split into site-specific SEEK rules. `learning_surface_adapter_decision_v1` records `host_adapter_status` and `content_adapter_status` independently, then composes an `adapter_chain`. Content selection requires both the model category contract and independently observed inventory topology. Application names, domains, one coarse model signal, and fixed-height guesses cannot activate a content adapter. Framework-generated structural IDs may contribute only whitelisted generic tokens. `learning_surface_adapter_application_v1` records policy application without changing geometry. Adapters cannot emit click points, authorize Execute, override the safety gate, authorize final submit, or replace `deterministic_root_partition_v1`.

Stage2 additionally compiles the selected content adapter or legacy content-class strategy into `repeated_peer_layout_review`. This is an advisory class prior, not a detector result. Existing candidate geometry can be regularized only when current-image repeated rectangles satisfy the common layout checks. A missing adjacent peer may become one review candidate only when a confirmed seed pair and direct current-image support agree; inferred candidates cannot recursively seed more candidates. Source bboxes remain preserved, and every derived bbox stays display-only with no Agent-memory, Gate, or Execute authority. Agent-readable class-rule evidence reports the declared peer family and whether current visual evidence triggered, so planning can distinguish expectation from observation.

`agent_peer_card_inventory_v1` is the Stage2 semantic projection for repeated content items. It intentionally excludes geometry, click points, selectors, and row/column containers. Visual card parents may aggregate current member text into a readable candidate. Text-only groupings, inferred neighbours, and unsupported candidates remain review-only. An `open_detail_candidate` is exposed only when the current candidate already carries explicit interactable and safe action semantics; class membership or repeated layout cannot synthesize action authority.

`learning_surface_adapter_protocol_manifest_v1` separates rule-development and holdout evidence. A holdout manifest is invalid when `used_for_rule_tuning=true`. Its case outcome is the conjunction of every explicit host/content adapter and status expectation, rather than the legacy `adapter_id` alone. Source types remain visible in the report. The current committed protocol cases are deterministic `fixture_only` routing checks, so their model-ability denominator is `not_covered`; actual or recorded-per-config model outputs are required before drawing a model-capability conclusion.

The authoritative learning dataflow is:

`capture -> immutable evidence -> host adapter -> interface classifier -> content topology evidence -> content adapter or abstain -> deterministic roots -> Stage2 dual streams -> precise calibration -> model review/repair -> artifact integrity gate -> fusion -> learning draft -> page details + read-only PathGraph`.

The panel workflow has one backend-owned transition contract, `learning_workflow_state_v2`. Its fixed order is `bind_capture -> screen_understanding -> numbered_map -> precise_calibration -> review_repair -> fusion -> page_details -> pathgraph_draft -> complete`. The client submits only `run_id`, `expected_revision`, and the requested transition; a thread-safe server run store supplies and validates the authoritative previous state. The backend replays the append-only event history before accepting the next revision. Skipped, backward, stale-revision, post-terminal, or tampered transitions are rejected. A stage also cannot become `completed` without its minimum evidence: capture image, learning trial, Stage2 report and overlay, structured calibration result and overlay, integrity-gated final report and overlay, fused trial, page-detail source, or read-only PathGraph scaffold as applicable. Before the state revision is accepted, `learning_workflow_evidence_integrity_v1` resolves each required path under the repository-local `artifacts/` or `logs/` roots, rejects missing files and path escapes, computes SHA-256 and size, and rejects a caller-declared checksum mismatch. `learning_workflow_lineage_v1` establishes the bound image SHA-256 as the run capture anchor. Every later completed JSON artifact is scanned for non-empty declared capture hashes, source screenshot paths, source numbering-report hashes, `source_graph_revision`, `reviewed_graph_revision`, and `final_numbering_revision`. Declared screenshot paths are independently resolved and hashed; conflicts inside one artifact or against accepted prior stages are rejected before the `expected_revision` transition, so a stale numbered result cannot be combined with a current capture without leaving the running-stage revision unchanged. Precise calibration is represented by `learning_calibration_result_v1`. It is persisted from the successful final locator trace and binds the source image, accepted Stage2 report, trace, and overlay by path and SHA-256. Missing or malformed `remaining_count`, a nonzero remaining count, or a resumable batch prevents completion. The calibration numbering-report hash must equal the integrity digest accepted for `numbered_map`. Evidence that carries only a binary overlay, or legacy JSON with no declared identity, is recorded as lineage `not_covered` rather than `verified`. The verified file and lineage summaries are stored in the accepted event. Failed and safe-stopped transitions require an explicit reason. The panel stores only the active run ID in `sessionStorage`, recovers accepted state through `GET /panel/learning_workflow_state/{run_id}`, and never infers `running`, `failed`, `safe_stopped`, or `completed` from message text. A fusion failure is terminal and cannot continue by substituting the initial draft for the missing fused result. `learning_workflow_stage_operation_v1` owns every model-driven lifecycle from `screen_understanding` through `fusion`. The backend issues the operation ID, start time, and lease expiry; only that ID may finish the current revision, late completion is rejected, and reload recovery fails only an expired managed lease. Direct transitions for these managed stages through the generic endpoint are rejected after state-order validation.

The execution plane for those managed stages is `learning_stage_worker_v1`. The panel initiates only the first `screen_understanding` stage operation and Observe worker. After each successful terminal model stage, backend continuation selects the unique next stage, creates its server-owned operation lease, deterministically builds the stage payload, and starts the first white-listed worker. It returns `learning_workflow_next_stage_operation_v1` plus the matching worker identity. The panel validates owner, status, run, stage, operation, task kind, and backend-compute ownership before following that worker; it neither reconstructs the payload nor starts a duplicate stage. Its heartbeat/cancellation context moves to the returned operation before polling continues. If payload construction or worker start fails, the backend immediately finishes that new operation as `failed` with `learning_stage_worker_start_failure_v1` evidence, so no orphan `running` stage remains. One operation may contain several sequential worker invocations. For `screen_understanding`, the panel starts only `vision_observe_screen`; after result adoption, backend continuation validates the immutable image identity, builds the recognition-trial payload from that adopted evidence, starts `panel_learning_recognition_trial`, and returns its worker identity. The panel follows that identity but does not choose the next task or determine the stage outcome. Only the adopted trial result may complete or safe-stop `screen_understanding`. Invocation idempotency is keyed by `run + stage + operation + task_kind + payload_sha256`; backend continuation may reuse the identical active invocation, while a different active task or payload remains rejected. Precise calibration is submitted once as `panel_learning_calibration_sequence`; its backend worker owns every locator batch, resource preflight, dynamic batch-size decision, retry, resume, idle wait, and no-progress decision. Automatic downstream model tasks perform local-model resource preflight and service readiness inside the backend worker before dispatch. Bind/capture is model-free and saves one immutable screenshot through `/state/capture_window`. Two-stage numbering, model review/repair, fusion draft generation, and the precise-calibration sequence use the worker boundary; manual/debug calls without a managed operation retain the direct endpoint path. Starting a worker revalidates the operation after process creation so a concurrent cancel cannot leave an unowned process. Each managed worker creates a model request ID before spawn, and the local provider forwards it in both the request body and `X-Agent-GUI-Request-ID`. Cancellation validates the current operation, asks the selected provider to cancel that exact request, terminates or kills the worker, then records terminal `safe_stopped` with separate `backend_compute_termination` and `model_service_compute_termination` evidence. Calibration-sequence cancellation resolves the nested locator request so the active VISTA request ID remains cancellable. The VISTA `ThreadingHTTPServer` exposes `/v1/cancel`; its generation stopping criteria observes a per-request event, and the broker reports `terminated` only after `/health` no longer exposes the matching active request. Qwen/llama-server does not currently provide this verified contract and remains `not_supported`.

Learn task execution is separated from HTTP transport through task-specific application services. Model review/repair uses `ModelReviewTaskInput -> run_model_review_task() -> LearningTaskResult`, recognition uses `RecognitionTaskInput -> run_recognition_task() -> LearningTaskResult`, and two-stage understanding uses `TwoStageUnderstandingTaskInput -> run_two_stage_understanding_task() -> LearningTaskResult`, in both the Panel and Worker adapters. These services own their read-only task orchestration, Trace creation, failure mapping, and non-authorization safety fields without importing `app.api.*`; compatibility adapters alone restore the legacy `APIResponse` shape. The recognition service owns authoritative two-stage report attachment, review-only numbered evidence, fusion-overlay projection, model-source audit, and learning-trial persistence. The two-stage service owns observe-result normalization, explicit screenshot override, Stage1 inventory and Gate input, layout graph construction, Stage2 report assembly, review-only overlay evidence, artifact persistence, and Trace emission. Panel routes are thin transport adapters, and the three corresponding Worker branches no longer import `app.api.panel`. Static source checks cover the contracts, adapter, and all three services. A clean subprocess regression executes all three Learn Worker branches with isolated task doubles and verifies that no `app.api` module exists in `sys.modules`; this proves the Learn transport boundary without starting a model. Recognition-specific Panel helper copies and their two remaining unused imports were removed after repository-wide references, AST import-use analysis, and the subprocess path proved they were no longer callers.

Observe uses the same boundary. `ObserveScreenTaskInput` and `ObserveScreenTaskResult` are transport-neutral contracts. `app.operation.observe` owns image-source resolution, provider-backed screen reading, OCR/UIA degraded evidence, operation context, and read-only Trace linkage. `app.learn.observe_enrichment` owns screen-map construction, read-only PathGraph projection, deep review, and visual-asset enrichment. `run_observe_task()` composes those layers and is called by both `/vision/observe_screen` and the `vision_observe_screen` Learn Worker branch. The HTTP route only adapts public models and legacy response shape. A clean subprocess regression executes the Worker failure path and verifies that no `app.api` module is loaded. `app.operation` package exports are lazy so importing an Operation submodule does not eagerly load the real-action stack. Locate and calibration still retain their existing API coupling and require a separate safety review before extraction.

`learning_workflow_readonly_tail_v1` owns the next execution slice: one API call sequentially builds and evidence-validates `page_details`, `pathgraph_draft`, and `complete`. A builder or evidence failure makes that exact stage terminal and prevents every later stage. Only the model-free bind/capture transaction remains a direct short panel transaction.

`LearningWorkflowRunStore` is the durable single-writer control-plane store. Its default file is `runtime_state/learning-workflow-runs.json`, configurable through `AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH`. A transition first builds and replay-validates a candidate snapshot, then serializes UTF-8 JSON to a same-directory temporary file, flushes and fsyncs it, atomically replaces the committed file, and only afterward publishes the candidate in memory. Startup replays every run's append-only events and rejects malformed, duplicate, over-capacity, or snapshot-inconsistent persistence. A process-held exclusive lock rejects a second store owner for the same path, so multi-worker Uvicorn deployment fails closed instead of silently becoming last-writer-wins. `:memory:` remains an explicit test/ephemeral mode.

Durable workflow state is not the same as resumable worker execution. `LearningStageWorkerRegistry` writes one atomic `learning_stage_worker_journal_v1` identity record and one identity-bound `learning_stage_worker_result_v2` envelope under `logs/workflow-workers/`. The journal stores `run_id + stage + operation_id + task_kind + model_request_id + payload_sha256` but never the raw payload. Startup discovers journals, validates filenames and result paths, and accepts a result only when every identity field matches. A forged, stale, malformed, or cross-operation result becomes an explicit worker failure instead of being attached to the workflow. Status observation, result adoption, and result continuation are separate contracts: worker status exposes availability but not the response; `/panel/adopt_learning_stage_worker_result` validates the active operation and persists an idempotent `learning_stage_worker_result_adoption_v1` receipt bound to the result SHA-256 before returning the response. A changed result can no longer satisfy that receipt. `/panel/continue_learning_stage_worker_result` reads only an adopted digest-matching result and applies `learning_stage_worker_continuation_v1`. The interpreter classifies a result as terminal or as a typed request for the next backend worker. It owns evidence extraction plus `completed`, `safe_stopped`, or `failed` transitions for `screen_understanding`, `numbered_map`, `precise_calibration`, `review_repair`, and `fusion`. An adopted Observe result starts the recognition-trial worker under the same operation and remains non-terminal; the adopted trial result supplies the terminal draft evidence. For precise calibration, the adopted sequence result carries source-bound artifact inputs. The service writes `learning_calibration_result_v1`, verifies required files and cross-stage lineage, then commits the terminal stage event; missing or inconsistent artifact evidence produces terminal `failed`. For Fusion, the stage-sensitive recognition-trial continuation extracts `trial_path`; a present, verified artifact completes the stage, while missing fused evidence safe-stops it. After a successful terminal stage, the service idempotently creates or reuses the next managed-stage operation, constructs its payload, starts its first worker, and returns both identities. The panel no longer derives Fusion success, submits its completion evidence, selects later stages, or starts downstream workers. The accepted workflow event stores worker, operation, task, and result-digest evidence, so an exact terminal replay is idempotent while another result cannot reuse the transition. `GET /panel/learning_workflow_state/{run_id}` returns the authoritative state plus the non-authoritative `learning_workflow_runtime_attachment_v1` projection. A managed stage is `running_attached` only while the current process holds its live worker handle. A recovered running journal is `running_detached / recovery_required`; a recovered completed envelope is `worker_finished / result_available / resume_required`, or `result_adopted / continuation_required` after explicit adoption. Full workflow continuation after reload and shared multi-worker coordination remain separate work.

Runtime action safety remains outside this artifact pipeline. The learning integrity gate proves source and revision completeness; the Execute Gate independently decides whether a current action may run. A learning draft or read-only PathGraph never becomes action authorization.

Learning Mode Stage1 now has one authoritative production source: `deterministic_root_partition_v1`. OCR, UIA, parser evidence, image separators, long-support RGB color-block boundaries, whitespace boundaries, repeated-grid guards, and remainder coverage are compiled into a complete non-overlapping root partition. A model does not invent Stage1 geometry, and the former model/bar-localization report is not part of `build_two_stage_screen_understanding()` or the panel workflow. A color boundary is promoted ahead of weaker grayscale or element cuts only when it spans at least 72% of the orthogonal screen axis and has sufficient RGB distance; local cards and decorative patches therefore remain child evidence rather than root partitions. Internal whitespace alone cannot create a root split; a horizontal root boundary needs edge-band, separator, strong color-block, or semantic structural evidence. Semantic edge-band evidence may read normalized OCR `label`, `text`, or `name` fields in addition to structural roles, but it cannot create geometry without the existing edge-band constraints.

Accepted roots flow through Stage1 gate, Stage2 numbering, precise calibration, model review/repair, integrity validation, fusion, learning draft, page-detail candidate, and read-only PathGraph adapters. The panel progress indicator follows this dependency order and does not mark page details complete before calibration, review, and fusion. A reviewed learning region may seed the normal recognition plan, but execution still requires current capture identity, viewport, bbox, click point, candidate freshness, and Gate approval. The verified learned-artifact exercise used `dry_run=true` and produced `action_executed=false`; it does not establish live-operation reliability.

Stage2 output first passes through revision-bound OCR/VISTA/rerank/Gate dry-run calibration. The calibrated composite overlay and Stage2 JSON then pass through `learning_overlay_model_review_prompt_v2`, deterministic repair closure, and `learning_review_final_integrity_gate_v1` before fusion. The model may keep, remove, relabel within the allowed role taxonomy, or request review; it cannot create final geometry or authorize execution. Strictly contained small `conversation_row`, `list_row`, and `table_row` leaves may be preserved by `learning_model_review_scope_v1` without consuming model context. Every remaining source group needs one explicit disposition and every removed wrapper must retain complete atomic evidence. Unknown IDs, unsupported roles, missing evidence, stale captures, and incomplete coverage safe-stop the chain.

Focused-review protocol recovery is source-bound. If the model copies the exact source region ID into `observed_role`, the parser can substitute only the role already stored on that same Stage2 record and only when that role belongs to the existing allowlist. It does not infer a new role, accept arbitrary strings, or bypass semantic-transition and final-integrity gates.

Stage2 candidate ownership follows `learn_stage2_dual_streams_v1`. Atomic `visual_objects` are factual OCR/UIA/parser/visual evidence; `semantic_groups` are structural interpretation; `associations` are created only after both streams exist. Semantic-only containers cannot consume small visual candidates, and deleting or rejecting a semantic group cannot delete its atomic objects. Bar candidates may compile into `atomic_control_parent` items after icon/OCR/background synthesis. Non-bar raw candidates remain display-only evidence until a complete parent is available, so edge fragments do not become executable or final numbered controls. The compatibility compiler still emits `numbered_items` and `subregion_groups` for current page-detail and read-only PathGraph consumers.

When a complete `atomic_control_parent` exists, final review presentation renders that parent once and suppresses its member fragments from the main overlay. Member objects are not deleted: they remain in the dual-stream evidence and parent membership records. Unmatched atomic items remain visible and review-only. This keeps visual evidence independent from semantic grouping while preventing the final fused screenshot from drawing both a complete control and each OCR/icon fragment on top of it.

Precise calibration consumes the current Stage2 report and its exact source revision before model review. Each synthesized control parent becomes one revision-bound calibration target with its member fragments retained as evidence rather than separate click targets. Large target sets are processed by `learning_calibration_sequence_v1` as resumable bounded batches: partial results separately record attempted, completed, retryable-failure, and remaining candidate IDs, while stale revisions invalidate continuation. Every batch re-runs resource preflight and uses that batch's recommendation rather than a frozen initial cap. Resume transport keeps the point/Gate evidence required for continuation but strips repeated model-I/O and image-preprocess blobs. `request_timeout` and `model_busy` never count as completed; the backend sequence worker waits for the locator health state to return from busy before retrying the same candidate, with bounded recovery, iteration, and no-progress limits. Model-unreachable and model-unavailable conditions remain hard blockers. No timeout, retry state, calibration result, or pre-review artifact authorizes a click or replaces the final integrity-gated review report used by downstream fusion.

Every local-model inference starts with `model_resource_preflight_v1`, not only locator startup. The initial Observe request still uses the panel's `ensureStageModelReady` boundary because the user-selected Observe profile is panel input. After that first worker, backend-managed learning workers own resource preflight and model-service readiness for learning-draft generation, Stage2 organization, model review, and precise calibration; the panel follows their returned identities and does not launch those models. Each VISTA grounding batch also re-checks resources immediately before its real model call. Critical load therefore becomes an explicit blocker instead of a silent loading state. Known-model accounting follows the launcher process recursively to its server descendants. If WDDM returns zero per-process VRAM for those descendants, the runtime may attribute the active profile's declared reservation, capped by aggregate use; aggregate utilization is attributed to the known model only when no external GPU process is measured and unattributed memory remains low. This prevents Qwen or VISTA's own load from blocking the next bounded batch while preserving conservative handling for an actual game or other external GPU process. The preflight recommends batch `8` for normal load, `2` for constrained load, or `1` for critical load. A stopped profile also needs at least 90% of its declared GPU-memory requirement available before launch; insufficient VRAM sets `model_launch_allowed=false`. Model profiles used here must declare a GPU memory budget. If GPU evidence is unavailable the runtime selects conservative batch `2`. Resource mode never changes candidate ownership, review decisions, final numbering revision, Gate policy, or authorization.

The panel source resolver treats display readiness as a separate contract. Only reviewable learning artifacts are listed, every entry records screenshot availability and missing display fields, and one newest non-pinned display-complete artifact may be marked as the current recommendation. Source discovery starts during panel boot; the history UI labels that artifact `[Recommended current]` and labels pinned benchmark scaffolds `[Pinned reference]`. Intermediate calibration JSON cannot become a panel learning draft merely because it is recent. When a fused trial wraps the integrity-gated final Stage2, page-detail generation resolves lineage from that nested final Stage2 while retaining the outer trial as the source path. The selected draft's final calibrated overlay, page details, demo scaffold, and nested read-only PathGraph therefore carry the same `learning_repaired_source_identity_v1`, including capture hash, source/review/final revisions, compiled overlay, and dual-stream counts. Missing lineage does not authorize inference or execution; none of these display assets authorize execution.

Learning Mode capture now enforces three common runtime invariants before recognition: exact HWND binding, visually ready capture evidence for panel learning runs, and stage-specific model routing (`local_understanding` for observe, `local_grounding` for precise calibration). UI hierarchy data is preserved through two-stage output, page-detail candidates, demo scaffolds, and panel draft normalization. Benchmark-referenced screenshots are protected from rolling capture cleanup.

Root-region existence follows evidence precedence. A model-generated `screen_map.sections` item is structural interpretation and cannot by itself prove that a top, bottom, or side bar exists, even when a nearby visual separator is present. Root promotion requires direct atomic semantics, edge/status controls, or the bounded visual geometry rules. This prevents a content-row separator from becoming a false root bar while retaining real status bars and nested chat headers.

Authoritative calibration also separates target content from browser chrome. Browser tabs, address bars, automation/debug banners, and window chrome may remain visible in review evidence, but they are filtered from actionable calibration candidates and reported through `filtered_calibration_browser_chrome_count`. Presentation acceptance is a separate same-source contract: the panel must render the current final fused overlay, current page details, and current read-only PathGraph on desktop and narrow layouts. Passing that presentation contract does not satisfy the stricter model-only template-readiness gate.

Runtime evidence has a repository boundary: `artifacts/` and `logs/` are local-only outputs and must never be source-controlled. Privacy-reviewed deterministic fixtures belong in an explicit fixture/config source directory; browser profiles, screenshots, traces, learned runs, and candidate records must not be promoted from runtime output into Git.

Application launch and binding also distinguish dedicated processes from shared Windows hosts. A shared-host catalog entry must provide localized title hints and require a title match; if that match fails, the runtime must surface a bind error instead of binding another `ApplicationFrameHost.exe` window. Learning capture readiness is a separate gate: a correctly titled but low-information startup surface is rejected before OCR/model work.

## Direction

`agent-gui-runtime` is organized as a general GUI Agent Runtime. The default execution model is Agentic Loop-first, not Workflow-first:

```text
observe -> Agent decision -> Gate -> Operation -> Trace -> observe
```

This matters because unfamiliar websites and Windows applications cannot reliably expose their next screen in advance. A prewritten Workflow or PathGraph can guide known flows, but it is not required for execution and never authorizes actions by itself.

## Core Layers

- `Agent`: understands the user's conversation, decomposes the task, manages prompts, makes content decisions, emits `ask_user_required`, and selects a PathGraph when one matches.
- `Operation`: observes the screen and executes concrete skills such as locate, click, input, scroll, read, form inventory, and app/window adapter actions.
- `Gate`: checks every real action for target freshness, coordinate validity, action taxonomy, danger scope, policy, and final-submit safety.
- `Trace`: records prompt/output evidence, screenshots, OCR/UIA/DOM evidence, operation candidates, gate decisions, audit data, replay inputs, and learning material.
- `Workflow / PathGraph Asset`: stores reusable learned workflows with states, transitions, skill bindings, gate requirements, success conditions, failure conditions, and trace evidence.

Form inspection follows the same ownership boundary. The common Operation layer emits `form_question_inventory_v1` from current-capture evidence inside the active form or modal scope. It owns field normalization, question/option ownership, required/disabled state, unsupported file-upload classification, and separation of navigation from final actions. Website adapters such as SEEK only translate site evidence into this contract. The inventory is read-only evidence: `fill_attempted=false`, `submit_attempted=false`, and `artifact_is_authorization=false`.

The Agent converts that inventory into `form_answer_decision_v1` policies: `auto_fill`, `derived_with_evidence`, `needs_user_review`, `blocked_sensitive`, `unsupported`, or `final_submit`. Reviewed values remain outside the Agent report; decisions carry only an evidence reference, hash, length, and redacted preview. `form_action_gate_decision_v1` checks policy evidence but never authorizes execution by itself. Even an allowed policy records `execution_authorized=false` and still requires current-capture grounding plus the real action Gate.

Form mutation remains a sequence of atomic Operation contracts rather than a batch fill. Text input uses `form_fill_action_result_v1`; page-contained dropdown opening and option selection use `form_dropdown_action_result_v1`; radio and checkbox changes use `form_choice_action_result_v1`. Each mutation requires current ownership, enabled state, unique semantic identity, candidate freshness, approved value hash/length, and Gate approval. A fresh observation must produce the corresponding effect-verification contract before the runtime can report success. Already-satisfied choices do not dispatch, and final submit/send/confirm/payment semantics remain blocked. Current coverage is controlled-fixture evidence only; it does not establish live ATS safe-fill reliability.

### Agent-readable evidence invariant

All persistent learning evidence must be designed so the Agent can understand what an interface is, which content is fixed or dynamic, when current content must be read, which semantic operation is being considered, which interface or state should follow, and how success is verified. Raw OCR, UIA, model boxes, and hierarchy nodes are evidence facts, not Agent action semantics.

`agent_evidence_context_v1` is the semantic projection boundary. Agent receives descriptions, read policies, reviewed control identities, transitions, blockers, and evidence references. Every control referenced by an available action must carry a semantic name, purpose, allowed action set, verification rule, and risk class. The projection builder demotes an action whose source control lacks these semantics, and the Agent consumer validates the same invariant again instead of trusting an `agent_usable` marker alone. Operation receives the current-capture localization problem. Gate receives freshness, ambiguity, risk, and action-taxonomy inputs. Trace receives the complete audit chain. Historical bbox and click points are excluded from Agent context, and a learning asset remains `artifact_is_authorization=false`.

The projection is read-only and derived from versioned interface assets plus human review; it is never a second writable source of truth. Evidence-file references may be retained for audit, but Agent-facing loaders must not expand them into historical geometry. Unknown action types fail closed as `actions_needing_review`, and canonical dangerous aliases remain forbidden even when a reviewed control exists.

Evidence lifecycle is `recognition_candidate -> saved_unreviewed -> reviewed -> agent_usable -> runtime_verified`. Missing semantics or control linkage keeps old evidence at `needs_human_review`; compatibility conversion must never promote hierarchy-only boxes into executable actions.

Saving a human-reviewed interface or workflow must refresh its derived Agent projection in the same application-layer operation. A successful save is not complete if `interface.json` changes while an adjacent `agent_evidence.json` remains stale. This refresh still does not publish memory or authorize Execute.

Browser content-class routing requires two independent evidence layers: model-produced category/structure signals and structured-inventory corroboration from current screenshot evidence. A model label alone cannot activate a content adapter. Missing repeated-item semantics must produce `content_adapter_evidence_insufficient` and retain the generic adapter; repair belongs in the shared inventory projection, not in a weaker routing gate or a site-name exception.

## Current Contracts

Learning recognition now has a common hierarchy/ownership boundary:

- `recognition_group_ownership_resolution_v1` receives all semantic group candidates, preserves valid ancestor aggregation, selects one primary leaf owner, records rejected claims, and never authorizes execution.
- `ui_hierarchy_graph_v1` converts accepted Stage1/Stage2 evidence into explicit screen, structure-region, section, component-group, component, and content nodes. Children must remain inside parents; orphan nodes and duplicate primary owners are validation failures.
- `learn_downstream_active_group_normalization_v1` makes sibling-overlap review authoritative across presentation and hierarchy dataflow. A suppressed group remains in raw Stage2 audit evidence but cannot participate in later conflict selection or re-enter the final overlay, UI hierarchy, page details, or read-only PathGraph.
- `learning_generic_repair_requests_v1` is the default-off review-repair contract. It links each accepted missing-region decision to the removed wrapper IDs, preserved atomic child IDs, owning Stage1 parent, rough search ROI, and explicit completion checks. `deterministic_atomic_evidence_union_v1` may produce replacement geometry only from complete atomic child boxes clipped to that parent. Missing evidence, unresolved semantics, or untrusted geometry blocks completion; no application name, fixed coordinate, or title-specific branch is permitted.
- `learning_template_draft_v1` and `learning_draft_page_details_v1` are derived from the hierarchy for panel review. They remain draft-only and contain no executable action templates until later human review and gated promotion.
- The panel resolves the review image from `page_details.screen.compiled_overlay_path` before the raw screenshot, then renders the same draft's hierarchy tree and page details. Page-detail candidates are deduplicated by their explicit normalized report/source path: the same source renders once, while a distinct model-generated source remains separately reviewable. This is a display dataflow contract only; the overlay and hierarchy do not authorize Execute.
- Generic card rows are classified by evidence: at least two trusted `visual_card_segmenter` media cards create `media_card_group`; ordinary application tiles create `tile_card_group`. This prevents media-specific semantics from contaminating settings grids.
- Human ownership goldens are a fixed holdout, not rule-tuning input. Missing or stale golden evidence is invalid; human owner-role annotations are scored separately from fixture assertions and cannot support a reliability conclusion below the declared sample/family thresholds.
- Showcase readiness is a separate evidence gate. It requires checksum-valid original/Stage1/final review sheets, hierarchy validation, real local-panel desktop/mobile rendering, and zero Execute/live-action side effects. Coverage shortfalls produce `needs_review`; stale evidence or a safety-boundary violation produces `blocked`.
- Grounding eligibility separates geometry evidence from direct interaction evidence. `calibrated_target_validated` and `cross_evidence_overlap` may support coordinate review, but they cannot make `text`, `section`, or `group` roles actionable. Those roles require UIA/DOM/OmniParser/ranked-Execute interaction evidence before ROI grounding; all real action still requires the normal Gate and freshness contracts.
- Interface classification is model-produced before class-rule application. The accepted category selects a bounded class profile such as `conversation_workspace -> conversation_rows`; category/profile conformance and cross-application contamination are checked separately from recognition quality. A class profile can change grouping strategy but cannot override safety, authorization, ownership, or parent-boundary invariants.

Learning-mode Stage2 follows two additional geometry invariants. A confirmed top/header structure region may contain multiple horizontal control rows; direct-control search must retain the full Stage1 bbox, then cluster and normalize controls per y-band instead of imposing one fixed-height strip. A bottom-edge partial-card row may use a visible peer card as a geometry template; fragments sharing the same visual slot are merged, while inferred sibling slots remain display-only and never authorize execution.

Stage2 semantic groups also follow an ownership precedence rule: explicit repeated list structure (`list_group` / `list_row`) owns its member evidence before inferred text-only tile cards. An inferred text tile that reuses list-owned item IDs is suppressed; explicit visual cards and unrelated tiles are preserved.

The first architecture contract slice lives in `app\runtime_architecture\contracts.py`:

- `gui_agent_runtime_architecture_v1`
- `operation_request_v1`
- `gate_decision_v1`
- `trace_event_v1`
- `app_profile_v1`

Profile discovery and loading are exposed through runtime APIs:

```text
GET /runtime/architecture
GET /runtime/app_profiles
GET /runtime/app_profiles/{app_id}
GET /runtime/operation_skills
GET /runtime/operation_skills?app_id=seek
GET /runtime/gate_contracts
GET /runtime/gate_contracts?app_id=seek
```

The corresponding code layer entry points are:

- `app.operation`: framework Operation skill catalog and profile-specific skill mapping.
- `app.operation.page_structure`, `app.operation.screen_reading`, `app.operation.screen_inventory`, and `app.operation.recognition`: screen-understanding and recognition pipeline behind `/vision/*`.
- `app.operation.vision_protocol`: vision-action execution adapter on top of Operation primitives.
- `app.operation.region_click`: reusable region-click execution for fixed-region baselines and vision-protocol actions.
- `app.operation.mousetester`: MouseTester-specific post-click semantic verification shared by live execution and trace evaluation.
- `app.agent.profile`: deterministic CV-to-candidate-profile extraction for job-search profile assets.
- `app.gate`: shared action-candidate freshness, action taxonomy, danger, scroll precondition/effect validation, scroll scope, dataflow, OCR, and target validation contracts.
- `app.trace`: trace event recording facade and execution-action trace write policy on top of the bounded trace writer.

Operation skills are now contract-bound atomic capabilities, exposed as `operation_skill_catalog_v2` with `operation_skill_v2` entries. A skill must declare its semantic actions, input/output contracts, preconditions, evidence requirements, failure modes, authorization requirements, decision boundary, and trace contract. The required split is:

- Agent decides intent, task decomposition, business suitability, prompt output, and when user review is required.
- Gate decides whether a proposed action is fresh, scoped, non-dangerous, and policy-allowed.
- Operation executes only the bounded skill it was authorized to perform.
- PathGraph provides hints such as ROI, historical label, or expected transition; it never provides click authorization.

The runtime request/result layer now exposes the same split through `operation_runtime_context_v1` and `operation_trace_link_v1`. The concrete Operation entry points add context for app/window binding, observe, locate, recognition planning, OCR/read-region, form inventory, verify diff, click/open-apply execution, confirmed point, type text, and scroll. Read-only skills require an authorized intent and capture evidence but do not require a Gate decision. Navigation/write skills carry a gate-linked id derived from the primary runtime check that already authorizes the action, such as `pre_click_decision_v1`, confirmed-point validation, type-field validation, or `scroll_precondition_decision_v1`.

The legacy execute compatibility package and old top-level screen-understanding packages have been removed. Runtime callers now import migrated contracts directly from `app.gate`, `app.operation`, `app.trace`, or `app.agent.profile`.

Agent prompt discovery, loading, and version saving are also runtime APIs:

```text
GET /runtime/agent_prompts
GET /runtime/agent_prompts/{prompt_id}
GET /runtime/agent_prompts/{prompt_id}/versions
GET /runtime/agent_prompts/{prompt_id}/versions/{version}
GET /runtime/agent_prompts/{prompt_id}/diff?from_version=...&to_version=...
POST /runtime/agent_prompts/{prompt_id}/versions
POST /runtime/agent_prompts/{prompt_id}/rollback
```

Prompt versions are stored as `agent_prompt_template_v1` artifacts under `artifacts/agent_prompts`. Saving or rolling back writes a new version artifact and a trace; it does not overwrite the base template.

The default architecture spec can be loaded with:

```python
from app.runtime_architecture import build_default_architecture_spec

spec = build_default_architecture_spec()
```

App/software profiles can be loaded with:

```python
from app.runtime_architecture import load_app_profile

profile = load_app_profile("artifacts/app_profiles/seek_app_profile_v1.json")
```

## App Profiles

Specific software belongs in app profiles, not in the root architecture.

The first profile is:

```text
artifacts\app_profiles\seek_app_profile_v1.json
```

It records SEEK-specific Agent prompt requirements, Operation skills, Gate contracts, Trace requirements, learned PathGraph references, learning assets, and policy. It does not authorize final submit and does not make SEEK the center of the runtime.

For SEEK, both station-internal `Quick apply` and ordinary external `Apply` are modeled as `open_apply_flow`. External ATS account creation, privacy consent, login, captcha, upload, and final-submit surfaces are safety stop points, not autonomous fill/submit authorization.

The generic execution boundary does not classify ambiguous labels from text
alone. Transition requests carry `semantic_action`, `source_interface_id`,
`surface_context`, and `active_flow_started` from the current reviewed
observation. The action API combines those fields with current selected-target
evidence and the scoped final-submit Gate. `Apply now` may therefore open a
flow only in an entry context; the same text on a final-review surface is a
blocked terminal action. Historical workflow assets do not provide this
authorization.

Use this template for future apps:

```text
artifacts\templates\app_profile_template_v1.json
```

## Learning Patterns

Learning patterns sit between abstract architecture and concrete PathGraphs. A PathGraph is a specific learned route for one app state space; a learning pattern is the reusable shape extracted from that route.

The first extracted pattern set comes from SEEK and lives under:

```text
artifacts\learning_patterns\
```

Each `learning_pattern_template_v1` declares where it applies, which states and regions matter, which Operation skills it may call, which semantic actions it covers, which Gate contracts must be active, what Trace evidence is required, and where execution must stop. The SEEK profile references these patterns through `learned_patterns`:

- `list_detail_page`: split result list plus detail pane.
- `long_detail_reading`: region-scoped long-detail reading with latest snapshot dataflow. The batch exposes `still_reading`, `reached_bottom`, `max_captures`, `no_new_content`, `wrong_surface`, and `blocked_surface`; only `reached_bottom` is complete, and downstream suitability decisions must read that state from the latest snapshot.
- `agent_full_content_review`: complete content must go to Agent before business suitability decisions.
- `entry_boundary`: Apply and Quick Apply open an application flow but are not final submit.
- `multi_step_form`: safe form progression until review boundary.
- `danger_zone_final_submit`: final submit/send/confirm/payment remains blocked by default.

Patterns are not scripts and not authorization. Agent may select them as guidance, Operation may use their region/skill hints, Gate still authorizes each action from current evidence, and Trace records the review chain.

The first closed-loop implementation is deliberately small and no-mouse:

```text
GET /runtime/learning/seek/draft
```

It reads existing SEEK profile / PathGraph / interface-map artifacts and produces `learning_episode_v1`, `normalized_learning_observation_v1`, `pattern_candidate_v1[]`, `learned_interface_map_draft_v1`, and `learning_eval_report_v1`. Learning only reads Trace-derived assets and stable references. It does not mutate Trace, Profile, PathGraph, or visual assets, and it does not execute Apply, Quick Apply, final submit, send, confirm, payment, or any real click.

The same draft/eval path now runs against local no-mouse fixtures:

```text
GET /runtime/learning/fixtures/generic_list_detail_fixture/draft
GET /runtime/learning/fixtures/generic_multi_step_form_fixture/draft
GET /runtime/learning/generalization
```

`learning_generalization_report_v1` summarizes SEEK plus the fixtures, including pattern coverage, total false-safe actions, average danger-zone recall, and the non-promotion policy.

## Panel View

The local panel mirrors the architecture. The shared Navigation Path / PathGraph card shows the Agentic Loop strip, and Runtime PathGraph node details show:

- execution model: Agentic Loop-first
- PathGraph role: navigation asset, not action authorization
- Gate requirement: real actions must re-observe and pass Gate
- app profile path, such as `artifacts/app_profiles/seek_app_profile_v1.json`

The Artifact Replay page also has an App Profile viewer. Loading a SEEK PathGraph fills `app_id=seek`, calls `/runtime/app_profiles/seek`, `/runtime/operation_skills?app_id=seek`, and `/runtime/gate_contracts?app_id=seek`, then renders the profile's execution model, operation skills, Operation-layer mappings, Gate-layer contracts, workflow assets, learning assets, and policy.

The same page now has an Agent Prompt viewer/editor. It can load `job_suitability_full_jd_v1`, show its variables/output contract/safety notes, edit the template, list existing versions, load a selected version, diff two versions, and save or rollback through the runtime prompt API.

## Detailed Design

The detailed Chinese design note is:

```text
docs\GUI_AGENT_RUNTIME_ARCHITECTURE.zh-CN.md
```

It covers the Agentic Loop, layer boundaries, PathGraph positioning, learning mode, profile placement, migration order, and safety invariants.
# Learning structure regression workflow

Learning structure changes follow a protected, same-source three-image workflow:

1. replay one fixed observe trace against its checksum-matched original screenshot;
2. render and review the Stage1 structure-bar overlay;
3. render and review the final fused overlay;
4. score human-annotated structure regions and element parents;
5. reject stale, incomplete, or cross-source evidence before metric denominators;
6. rerun every protected surface after changing a shared recognition rule.

The benchmark report keeps the automated gate and manual review separate. `automated_gate_status=passed` only means the checksum, structure, and golden-element fixture gates passed; `manual_visual_review_required=true` remains until a reviewer compares all three rendered images.

Learning-interface class expectations are executable report contracts. The audit compares declared present/absent structure bars and required sub-bar roles against the final hierarchy, emits separate missing/unexpected issues, and records observed `bar_types` and `sub_bar_roles`. These fields describe structural conformance only; they are not combined into recognition accuracy or unattended-reliability claims.

The current element-parent reconciliation uses only reusable geometry and hierarchy evidence. Repeated aligned heading/body columns can form complete text-module parents, and parallel repeated list groups can inherit a complete sibling column width. These are display-only learning artifacts and do not grant click, Execute, or Runtime PathGraph authorization.

For a shallow full-screen inventory that has been expanded to the whole viewport, Stage1 may replace the rough header/main split only when OCR supplies a reliable repeated horizontal control row: at least three short items in one horizontal band with sufficient page-width coverage. The last reliable row before the rough boundary defines the split. Boundary error is measured relative to the expected region itself so a large local error cannot be hidden by a large screenshot.

## Review Repair Integrity

Model review is advisory. A `reject_candidate` result never needs a valid proposed role because no replacement geometry will be created. Removing an overmerged semantic wrapper preserves and reparents its atomic children; the model is not allowed to request a second broad repartition merely to delete that wrapper. Generated review-group identities are parent-scoped so batches cannot alias groups from different panes.

Stage1.5 chat decomposition may use two independently detected vertical separators. The first separates the list pane from the detail pane; a stable second separator may expose an auxiliary pane. The second split is accepted only with multi-item vertical evidence. Missing-region repair then applies common containment policy before deterministic geometry reconstruction: existing navigation and conversation-list parents cannot be duplicated by nested semantic proposals, bottom composers only admit composer-relevant roles, and a lone OCR text atom cannot establish a new semantic region.

Stage1.5 horizontal chat boundaries follow the same evidence ordering. A current-image separator plus factual composer evidence may establish the message-thread/composer boundary; model-only `element_*`, `action_screen_*`, or visual-region proposals cannot establish or move it. UIA-only text must have non-uniform current pixels before it appears in the main overlay. After ownership, each semantic group's display bbox is reconciled against its current renderable members; a group with no such member remains audit evidence and is suppressed from fusion, model-review rendering, calibration, page details, and read-only PathGraph presentation. These rules preserve semantic interpretation without allowing stale or model-only evidence to overwrite current visual facts.

Confirmed structural context must flow into visual candidate synthesis. In particular, a Stage1.5 `message_thread` is sufficient chat-surface evidence for image-message synthesis; downstream code must not require the same fact to be rediscovered from an atomic candidate. Small visual contours remain conservative: an isolated contour below the normal image threshold is noise, while multiple similarly sized candidates aligned to the same message edge may be promoted as repeated stickers. Geometry still comes from current screenshot pixels, and the synthesized items remain review-only.

## Reviewed Continuous Navigation And Reading

`app.agent.navigation_reading` is the generic Agent decision boundary for
human-reviewed single-interface evidence. It consumes
`agent_evidence_context_v1` plus the current observation identity and emits only
semantic choices: `follow_transition`, `read_region`, `scroll_for_more`,
`stop_reading`, or `safe_stop`. Its output contains no reusable bbox, click
point, or historical coordinate. A transition choice includes the linked
geometry-free semantic control so Agent can explain what the control means,
which action is allowed, and how the outcome will be verified. A validated choice is still a plan, not an
authorization: Operation must resolve it against the current capture, Gate must
approve the resolved action, Trace must record dispatch and effect, and a new
observation must verify the result.

`ContinuousTaskSession` binds each Agent choice to the current interface and
capture before Operation dispatch. A verified transition returns control to the
Agent on the newly observed interface. A scroll dispatch without a content
effect becomes `needs_human_review`; wrong-scope movement becomes `safe_stop`.
This keeps dispatch evidence separate from task effect.

Each live suite must declare `initial_interface_id`. The live runner performs an
initial observation before constructing the model provider or Operation
adapter. If the observed interface differs from the declared start, the run
fails closed as `needs_human_review / initial_interface_mismatch`; no Agent
model call and no action dispatch are allowed. When it matches, the observer
prefetches that exact observation for the controller's first decision. This
preserves capture freshness and avoids validating one screenshot while acting
from another.

The controller also projects semantic task progress back into each Agent
decision: the ordered interface visit history, completed choice ids, completed
and bounded read ids, and the latest verified outcome. This state contains no
geometry. It prevents a sequential goal from being reconstructed from the
current screenshot alone and lets the Agent avoid repeating a completed branch.
The decision prompt treats completed choices and remaining scroll budget as
constraints; a completed branch may be repeated only when the user goal
explicitly requires a loop.

Read completion is explicit and surface-aware:

- `finite_detail` requires `reached_bottom=true` before completion.
- `infinite_collection` uses a bounded read budget and may stop on
  `no_new_content`, but that condition is not evidence that all content was
  exhausted.
- A completed finite read is removed from the next Agent choice set. A bounded
  collection at its configured budget exposes only explicit `stop_reading` or
  `safe_stop` until reading has been stopped; the workflow may continue after
  `stop_reading`.
- `wrong_scope_detected` is blocked and cannot be converted into read progress.

Reviewed evidence can describe controls, transitions, and deferred read regions,
but `artifact_is_authorization=false` remains mandatory. Final submit, send,
confirm, payment, and other final actions remain outside this decision contract.

## Dynamic Form Question Boundary

Dynamic application questions are normalized in the Agent layer before answer
policy lookup. `normalized_question_intent_v1` separates canonical intent from
surface wording and records explicit answer polarity. For example, work-rights
and sponsorship-requirement questions map to the same intent but invert what an
affirmative answer means. Negated requirements and mixed current/future clauses
are evaluated as evidence spans so one clause cannot silently erase another.

The normalizer never produces an answer or execution authorization. Low
confidence, conflicting polarity, salary, relocation, visa, and unknown text
remain `needs_user_review`; criminal-history, health, demographic, and
disability questions remain `blocked_sensitive`. A later reviewed-answer memory
may reference this intent and polarity, but Operation still requires current
form ownership, current capture grounding, Gate approval, and post-action
verification. Final submit/send/confirm/payment remain hard-blocked.

`app.agent.navigation_reading_replay` is the offline contract harness for this
loop. It checksum-validates reviewed interface assets, rebuilds Agent context
for every current observation, validates recorded semantic decisions, and
replays Gate/Operation/effect evidence without dispatching a live GUI action.
Its metrics intentionally keep dispatch and effect separate. A failed effect or
`needs_human_review` state fails a normal case; an expected wrong-scope or Gate
intercept is reported separately as a safe stop. Recorded replay evidence does
not evaluate model decision quality or live localization.
# Dense document semantic guard

Stage2 keeps factual atomic evidence separate from semantic grouping. When a main-content region contains dense readable text, repeated code/document syntax, and an independently observed structured workspace container, weak model card roles (`news_card`, `recommendation_item`, inferred `tile_card`) are normalized to review-only `document_section` nodes. Inferred card rows and card parents are suppressed on that surface. Explicit visual `content_card` and `media_card` roles remain eligible, so the guard does not remove supported media/catalog cards. This policy is evidence-driven and cannot use the application name, authorize Execute, or change final-submit safety.

## Reviewed Answer Policy Memory Boundary

Human-reviewed form answers are represented as strategy references, not stored answer values. `FormAnswerPolicyMemoryStore` persists canonical intent, polarity, scope, review decision, opaque evidence reference, evidence hash, and expiry in a separate memory namespace. This keeps form-answer policy independent from reviewed interface geometry and action memory.

Agent lookup may return `reviewed_strategy_available`, but this is only a decision input. It never sets execution authorization and never supplies historical coordinates. Unknown intent, changed polarity, rejected review, stale evidence, or scope mismatch pauses for human review. A later fill still requires a current form inventory, current-capture target resolution, policy Gate, Action Gate, Operation dispatch, Trace, and post-observe verification.

## Multi-Step Form Workflow Boundary

The form workflow controller is an Agent-layer state selector, not an input dispatcher. For one current capture it consumes the current form inventory and answer-policy projection, then emits at most one semantic turn: fill one field, select one option, continue one step, request human review, or safe-stop.

```text
observe current form step
  -> bind capture + inventory + grounding fingerprints
  -> Agent chooses exactly one semantic form action
  -> Gate validates current target and action
  -> Operation dispatches at most one action
  -> Trace records dispatch and post-action evidence
  -> invalidate page-local form evidence
  -> observe and rebuild before the next turn
```

A verified `Continue` invalidates the capture, inventory, and grounding from the prior page. No historical bbox or point can cross that boundary. Unknown question order, login blockers, wrong surfaces, failed effect verification, stale evidence, and visible final actions stop the state machine. Final submit/send/confirm/payment remain hard-blocked independently of prompt or workflow assets.

## Immediate Pre-Dispatch Visibility Contract

Current-capture grounding is necessary but not sufficient for a real click. Immediately before `mouse_down`, `InputController` asks `WindowManager` to resolve the top-level window under the approved click point. The point is executable only when that window is the bound target or a window owned by the same target process. A foreign top-level window, notification, tooltip, or overlay causes `target_point_occluded`; the action terminates before `mouse_down` and emits structured Trace evidence.

This visibility check is intentionally later than recognition and Gate because the desktop can change between planning and dispatch. It does not replace candidate freshness, coordinate validation, semantic Gate, final-action blocking, or post-action verification, and it has no fallback that clicks through an obstruction.

## Controlled Demo Evidence Boundary

The final Demo scaffold combines two evidence scopes without merging their claims:

- a real controlled Edge traversal proves reviewed multi-interface evidence can drive Agent decisions, current-screen localization, Gate, Operation, effect verification, bounded reading, and safe stop;
- a controlled form fixture proves atomic text/choice/upload/Continue handling and final-action blocking with bounded step durations.

The form fixture is not live ATS evidence. The reviewed workflow is non-authorizing and every real action still requires a fresh observation. A derived workflow produced from a traversal remains `needs_human_review` until its interfaces and transitions receive explicit human approval.

## Scoped Capture Composition Boundary

`app.learn.scoped_capture` composes already captured Learn evidence and has no Operation or Gate dispatch capability. Vertical overlap discovery is a two-stage deterministic proof: full-width RGB row digests remove impossible candidates, then every surviving candidate must pass full-resolution RGB equality and full-resolution informative-tile checks. Row digests are only a filter; they can never prove or authorize a stitch.

For non-matching frames, a bounded-width grayscale scan ranks a small diagnostic candidate set, whose MAE is then measured at full resolution. This diagnostic path may explain why no overlap was accepted, but it cannot turn an inexact candidate into a stitch. Ambiguous exact candidates, low-information strips, size mismatch, or any full-resolution mismatch still append the complete segment. The resulting composite and manifest remain read-only learning evidence with `artifact_is_authorization=false`.

## OmniParser Learning Shadow Boundary

A canonical `screen_parser_result_v1` may enter Learn observation evidence only as a read-only OmniParser source. Recognition produces a compact provider/lineage summary for review, but neither provider success nor `interactivity=true` grants an action. The UI separately shows provider success, generated candidates, ROI-grounding eligibility, and `execution_authorized=false`; failures and incomplete lineage remain visible. Any future action still requires a fresh current capture, independent corroboration, Gate, gated action API, Trace, and post-action verification.

## Reviewed Workflow Asset v2 API Boundary

`reviewed_workflow_asset_v2` is the server-owned bridge from Human Review to replay. `POST /panel/compile_reviewed_workflow_asset` resolves the source workflow from the application-scoped v1 registry and verifies its current bytes against the caller's expected SHA-256; the client does not provide an arbitrary source path or compiled asset. `POST /panel/publish_reviewed_workflow_asset` repeats compilation immediately before publication, serializes the in-process workflow lock, checks the final content hash, and advances the content-addressed store only when the expected CAS registry revision still matches. A blocked compile or revision conflict produces no asset write. Cross-process atomicity for the legacy v1 save/publish path is not part of this boundary.

`POST /panel/preview_reviewed_workflow_replay` loads the active v2 asset by server-side identity and expected content hash, then performs a read-only semantic preview from an explicitly supplied current observation. It returns state/transition preview data with `would_call_action_api=false` and `execution_authorized=false`; it does not capture a window, ground a click, call the action API, or dispatch an operation. Missing current observation, hash mismatch, stale lineage, and invalid replay data remain structured failures. The existing workflow panel now exposes Compile, CAS Publish, and explicit-observation read-only Preview with exact workflow/SHA binding, stale-response guards, and edit invalidation. A synthetic SEEK homepage → detail → apply-entry-stop E2E covers the real compiler, CAS, API, replay coordinator, and navigation adapter envelope with fake external dependencies; it makes no GUI, network, or physical-action claim.

`LiveController` now carries current observation, state resolution, transition selection, fresh grounding, Gate, one-shot action dispatch, post-state verification, durable receipt recovery, and the internal confirmation-resume chain. A loopback-only local API callsite exposes this chain using strict, geometry-free requests and existing Observation/Receipt contracts; tests replace the physical backend. No panel approval UI or controlled physical Windows/SEEK proof exists. Replay-mode adapter requests remain restricted to one action attempt; `read`, `scroll`, `fill_field`, `continue_next_step`, upload, and final-submit classes remain fail closed. The milestone does not publish a recovery-feedback authority; only non-authorizing recovery and replay evidence are retained.

`run_reviewed_workflow_v2_benchmark.py` is a pure offline contract benchmark. A separate closed manifest pins the canonical asset, valid-case set, and every case before replay. Ordered recorded Bare events and Runtime results are classified independently; category semantics, unsafe dispatch, bounded recovery, latency, and derived result digests are reported without coordinates. This is fixture-conformance evidence, not a Bare-model, perception, live-GUI, or reliability benchmark.

## UEI Provider Evidence to Learning Review Boundary

The Learning Review loader may internally project grounded safe items from a
revalidated `provider_safe_result_v1` into the existing large-image editor. It
first resolves and decodes the image that the panel will display, then requires
its actual SHA-256 and dimensions to match the immutable current-capture
lineage. A payload capture reference or declared source checksum alone is not
sufficient. Before exposing provider-projected regions, the server always
materializes that verified image as a content-addressed, immutable panel source;
an already repository-local input is not reused as a mutable display binding.

Projected boxes are deterministic, capture-bound review candidates. They use
the editor-compatible `review_only` role while retaining provider belief and
confidence only as non-authorizing evidence. Ungrounded items with a legal null
`capture_bbox` are counted and skipped. Capture or display-image mismatch,
invalid geometry, duplicate source identity, ambiguous duplicate semantic
boxes, or region-ID collision rejects the whole projection.

This is an internal safe projection, not a fifth public UEI contract. It never
exposes full immutable references, full hashes, local paths, transforms, or raw
provider payloads to Review, never overwrites an existing region, and never
creates an intent, action template, click candidate, grounding authority, or
execution authorization.

Learning Draft loads use a latest-generation lifecycle rather than allowing a
boot-time auto-load to own the UI indefinitely. A manual Load supersedes any
pending generation, marks it stale before abort, waits until the shared request
key is released, and only then starts the latest request. A same-source ordinary
load still coalesces. Promise identity guards, request tokens, and an owned
`AbortController` prevent an abort-racing success response from rendering stale
evidence or clearing a newer load.
