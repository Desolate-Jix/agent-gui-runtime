# agent-gui-runtime

Windows GUI Agent Runtime for observing, understanding, locating, safely operating, tracing, and learning reusable interface structures across websites and desktop software.

## Deployment

### Requirements

- Windows 10 or Windows 11
- Python `>=3.11,<3.12`
- [`uv`](https://docs.astral.sh/uv/)
- Local vision models are optional for API and panel inspection, but required for real model understanding and precise grounding

### Quick Start

```powershell
cd D:\agent-gui-runtime
uv sync
.\start_test_panel.bat
```

The launcher validates that an existing health response belongs to `agent-gui-runtime`, reuses a running instance on port `8000` or `8765`, or starts the runtime on the first free port. It then opens the panel and writes runtime logs to `logs/test-panel-runtime.log`. A different application occupying one candidate port is skipped instead of being mistaken for this runtime.

The launcher prints the selected URL. Typical endpoints are:

- Panel: `http://127.0.0.1:8000/panel` or `http://127.0.0.1:8765/panel`
- API documentation: `/docs` on the selected port
- Health check: `/health` on the selected port

### Manual Runtime Start

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run one API worker for the current durable Workflow Store. Starting overlapping API processes against the same `AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH` fails closed with an ownership error; shared multi-worker coordination is not implemented.

### Local Vision Models

The recommended route is the panel model manager. Learning observation uses Qwen3-VL 8B by default; precise grounding uses VISTA-4B. Profiles live in `configs/model_profiles/` and server scripts live in `scripts/model_servers/`.

Install the optional VISTA dependencies before its first run:

```powershell
uv sync --group vista
```

### Runtime Storage Cleanup

Runtime traces and Learning Mode run assets are retained as evidence. Only old temporary files and review overlays that are not referenced by learning runs, documentation, tests, benchmarks, golden traces, or workflow reviews can be proposed by the protected dry-run:

```powershell
uv run python scripts\cleanup_runtime_storage.py --older-than-days 14 --json
```

Review the generated plan under `logs/cleanup/`, then apply the same policy explicitly:

```powershell
uv run python scripts\cleanup_runtime_storage.py --older-than-days 14 --apply --json
```

The cleaner is limited to `logs/tmp` and `artifacts/review-overlays`. `logs/traces` and `artifacts/learning-runs` are protected roots: they cannot be supplied as cleanup targets and are scanned to protect their referenced overlays. The cleaner also protects benchmark/golden/current-workflow references and the newest files in each managed root. It never targets models, the virtual environment, fixed benchmark assets, operational memory, Trace evidence, or learning drafts. Apply rechecks file size and modification time, skips anything changed after planning, and removes empty descendant directories only inside the managed roots.

Manual VISTA start:

```powershell
.\scripts\model_servers\start_transformers_vision_server.ps1 `
  -ModelPath .\models\vista-4b-safetensors `
  -ModelName inclusionAI/VISTA-4B `
  -Port 1244
```

Stop local services after testing:

```powershell
.\scripts\model_servers\stop_local_vision_server.ps1 -Port 1244
```

Stop the manually started API with `Ctrl+C`. The runtime does not authorize real clicks merely because a model or panel is running.

### Generated Data Policy

`artifacts/`, `logs/`, and `runtime_state/` are local runtime output and are ignored by Git. They can contain screenshots, traces, learned drafts, candidate data, browser-session state, and the durable Learning Workflow run store. Do not force-add these directories. Reusable, privacy-reviewed test fixtures must live under `tests/fixtures/` or another explicitly reviewed source directory.

## Results Preview

### Simplified Learning Workspace

Learn Mode now exposes one public `学习工作台 / Learning workspace` instead of separate Template, Trace, and PathGraph-validation pages. The first screen keeps the nine-stage single-interface recognition progress strip, then leads into the application-scoped force-directed workflow graph, reviewed overlay evidence, and optional human correction. The review order is always graph first and evidence second. `修正当前界面` opens the existing full-image box editor with its fixed bottom toolbar; it does not expand a duplicate correction form below the evidence. Matching loaded evidence is reused immediately. When another workflow node's evidence must be loaded, the full-image surface opens at once with `正在加载框编辑器...`, while the entry shows `正在打开框编辑器...`; both remain in loading state until the editable overlay is ready. The entry now follows a visible outcome contract: it either opens the editor or reports loading, missing-evidence, missing-image, or request-failure status beside the button. Errors are still copied to internal diagnostics, but the hidden diagnostic response is no longer the only feedback. This exact-node editor path skips unrelated sidecar discovery, supersedes stale background draft loads, and avoids rendering the hidden full diagnostic review before opening the editor. The editor background always uses the clean source screenshot, never a fused or numbered overlay containing baked-in annotations. A checksum-valid source outside the project is copied into the content-addressed `artifacts/learning-draft-review/source-images/` cache before display, so `/panel/file` remains restricted while every visible editor box stays a real selectable overlay. Closing the editor returns to the graph and evidence view.

The box editor defaults to a conservative compact view. Credible parent controls or regions remain visible while fully contained OCR, text, and icon fragments are folded into a `+N` member selector. Selecting a folded member reveals and selects that original box, and `显示全部框 / 精简框` switches between the complete evidence set and the display projection. Selected, manually edited, actionable, dangerous, and ambiguous boxes are never hidden. This is presentation-only: save/export still uses the complete editor state, and no evidence, action, Gate decision, or safety rule is removed.

Template replay, Trace inspection, PathGraph validation, and the legacy task harness remain internal compatibility and advanced-diagnostic capabilities. They were hidden from the daily navigation rather than deleted. Execute Mode likewise presents the current single-step flow: available actions, precise locate, click Gate, and input. None of these presentation changes turn a learning artifact into execution authorization or alter final-submit blocking.

Learning Interface progress follows the backend-owned `learning_workflow_state_v2` contract. The server rejects stale, skipped, backward, post-terminal, and tampered transitions; every completed stage must provide checksum-bound local evidence under `artifacts/` or `logs/`. The panel renders `bind/capture -> understand -> number -> calibrate -> review/repair -> fuse -> page details -> read-only PathGraph -> complete`, but it is not the workflow authority. It starts only bind/capture plus the initial `screen_understanding` operation and Observe worker. Backend continuation owns every later operation, payload, first worker, result interpretation, evidence verification, and terminal transition. The panel validates the returned operation/worker identity, moves heartbeat and cancellation tracking to that operation, follows the worker chain, and renders adopted responses. It does not reconstruct or start downstream stages.

Observe now has a transport-neutral service boundary. `/vision/observe_screen` and the Learn Worker both call `app.learn.workflow_tasks.observe.run_observe_task`, which composes the Operation read-only observation with Learn-only screen-map, read-only PathGraph, deep-review, and visual-asset enrichment. The Worker no longer loads `app.api.*` for Observe. Public request/response fields and no-action safety behavior remain unchanged; Locate is still API-coupled and is intentionally deferred to a separate extraction.

### Generic Single-Application Workflow Review

The Learning workspace can project an ordered set of reviewed learning artifacts into `single_application_workflow_review_v1`. Each interface node owns its fused, numbered, and source screenshots, page details, candidate actions, blockers, verification rules, and incoming/outgoing transitions. Its review workbench places a compact, viewport-responsive force-directed interface graph directly above the checksum-bound evidence viewer, so the graph and the beginning of the selected interface screenshot remain visible together. Correction tools live inside the current-interface section and stay hidden until requested. Like a compact Connected Papers view, the graph renders interfaces as circular points with evidence- and connectivity-weighted sizes, while each operation is written as small plain text parallel to its arrow without a label container. Link text measures the actual clear curve span between the two circular boundaries, then truncates and scales to fit; links that are too short to keep readable text clear of both nodes show only the arrow. Controls stay attached to an interface instead of becoming graph nodes. A deterministic initial layout and bounded force simulation keep the selected interface near the centre, separate neighbouring interfaces, and produce the same settled positions for the same topology after a brief entry animation. Hovering a node highlights that interface, its one-hop neighbours, and their transition links while dimming unrelated paths; a tooltip shows interface type, control count, path count, and review state. Clicking an interface centres it and opens its evidence without removing any other interface or link from the software-wide graph. Reviewers can zoom, pan, or use `适合画布` to restore the application-wide fit.

Saved single-interface preview evidence and current workflow-node evidence are separate modes. Opening a preview cannot silently leave the evidence title or image bound to a different graph node, and the reviewer can switch explicitly between the two sources. `加入流程` now inserts the selected reviewed interface as an unconnected node only. Transitions are created from the graph by right-clicking a source interface, choosing a target interface, and then selecting the source control and operation; individual outgoing links can be removed from the same context menu without deleting either interface. Source controls are presented by readable interface label and role; the reviewer may also choose a control directly on the boxed evidence image, after which its internal ID is filled automatically. One interface can fan out through several operations, several branches can converge on one interface, and reviewed flows can contain return edges or cycles. Missing or unverifiable target geometry is reported as unavailable rather than drawn from guessed coordinates. The Agent operation editor supports adding, updating, or deleting routine operations and target interfaces. A transition can point to an observed interface or create a clearly marked `needs_learning` placeholder. The toolbar covers read, open-detail, open-flow, fill, select, scroll, back, close-modal, wait, and continue operations; final submit, submit, send, confirm, payment, and delete are rejected. The existing full-image bbox editor remains available, and the reviewed workflow can be saved without editing JSON or Markdown. Rebuilding the graph preserves bounded human edits and custom links whose source and target interfaces still exist. The graph remains a display/review surface and does not authorize Execute.

Saving is deliberately non-authorizing: the artifact remains `display_only=true`, `artifact_is_authorization=false`, `execute_binding_enabled=false`, has no published memory version, and contains no reusable runtime click point. The saver rejects duplicate node/edge IDs, missing entry nodes, mismatched graph indexes, dangling transition targets, unsupported actions, and forbidden high-impact actions. The operation toolbar unlocks `Safe validation` only after save; that path forces `capture_live=true` and `dry_run=true`, performs fresh localization plus Gate review, and never dispatches the action. `Publish and execution verification` only prepares the existing Agent Memory panel. Publication still requires separate human approval, while any later execution must recapture the current interface, localize again, pass Gate, and verify the result.

Reviewed workflows are indexed into an application-scoped library. Browser captures use a canonical site domain/origin such as `web:seek.co.nz`; Edge or Chrome without URL/domain evidence remains `needs_domain_review` and is never treated as the website identity. Native applications use executable plus product identity. The Agent may load this library as read-only planning context, but historical coordinates are forbidden and every action still requires a current capture, fresh grounding, Gate, and post-action verification.

Learning evidence now has an explicit Agent-facing semantic projection. `agent_evidence_context_v1` describes the interface responsibility, fixed identity anchors, dynamic or on-demand content, semantic controls, candidate operations, expected transitions, verification rules, blockers, and evidence-file references without exposing historical bbox or click points. The contract is available through `GET /memory/interface_assets/agent_context` and inside `interface_workflow_agent_context_v1.agent_evidence_workflows`. Old hierarchy-only boxes remain visible as non-actionable `legacy_recognition_candidates`; they are not promoted into Agent actions until a human supplies the missing content semantics and control linkage. `scripts/migrate_agent_evidence_assets.py` writes adjacent `agent_evidence.json` sidecars without modifying source assets. The projection is a read-only derivative of versioned assets and human review, not a second writable source of truth. Unknown actions fail closed, dangerous aliases remain forbidden, and evidence references are not expanded into historical coordinates. This projection is planning evidence, not Execute authorization.

Saving a reviewed workflow now refreshes its adjacent Agent evidence projection in the same backend operation. Application identity keys are normalized only for safe filesystem segments, while the semantic identity remains unchanged. The previous `web:msn.com` learning history and Agent-evidence projection were removed after human review found that the page had been misclassified as a news site. A fresh model observation classifies the surface as `aggregate_portal`: a personalized portal/dashboard containing independent news, advertising, video, weather, sports, market, and game modules. The `independent_content_modules` policy now reaches deterministic Stage1 root partitioning instead of stopping at classification. On real-model Protopage and MSN aggregate-portal traces, Stage1 now produces a coarse top region plus one main-content region and continues to Stage2. Google News, Yahoo NZ, and YouTube control traces retain their feed/search policies. The common root-partition invariant now requires current semantic navigation evidence before a class-rule edge split can become a sidebar; this removes Yahoo NZ's false left-navigation root without adding an application-specific rule. Final fusion remains review evidence rather than Agent authorization.

The fixed offline demo is defined by `configs/demos/interface_class_rule_aggregate_portal_demo_v1.json` and rerun with `uv run python scripts/run_interface_class_rule_demo.py --manifest configs/demos/interface_class_rule_aggregate_portal_demo_v1.json --out logs/benchmarks/interface_class_rule_aggregate_portal_demo_v1`. It contains two aggregate-portal positives and three feed/search controls, verifies screenshot and trace checksums, applies the same Stage1 gate, and writes a linked original/fused/Agent-evidence index to `logs/benchmarks/interface_class_rule_aggregate_portal_demo_v1/DEMO.md`. Each Agent evidence file describes semantic responsibilities and required runtime safeguards without historical bbox or click points. The five replay checks are fixture/replay contract checks, not model accuracy or live GUI reliability. The same MSN screenshot has earlier traces with conflicting content-class labels, so model classification repeatability is explicitly not established.

### Continuous Navigation And Reading

The reviewed-asset runtime can now execute a controlled multi-interface
navigation and reading loop without form filling:

```text
observe -> Agent semantic decision -> fresh Operation localization
        -> Gate -> low-risk action -> Trace -> observe
```

The linear live baseline is under
`configs/demos/navigation_reading_live_v1/`. Its latest verified run visited
four interfaces (`Feed -> Atlas -> Notes -> Summary`), performed three
verified transitions, three region reads, five effect-verified scrolls, and
ended with an Agent-requested safe stop. All 12 decisions came from the local
8B model. The report is
`logs/smoke/navigation_reading_live_v8/navigation_reading_live_smoke_report.json`.

The branching live suite is under
`configs/demos/navigation_reading_live_v2/`. Its verified path was
`Workspace -> Incident -> Workspace -> Policy dialog -> Workspace -> Live
Updates -> Summary`. It used 14 serialized local-8B decisions, completed
return navigation and modal open/close, performed two explicit
effect-verified scrolls over the bounded updates collection, emitted an
explicit `stop_reading`, read the terminal summary exactly once, and ended in
`safe_stop` with no failed step. Task progress is semantic: visited
interfaces, completed choices, completed reads, bounded reads, and the latest
outcome are supplied to the Agent. The Agent is instructed not to repeat a
completed branch by default or claim a scroll budget is exhausted while
budget remains. The report is
`logs/smoke/navigation_reading_branching_live_v7_initial_preflight/navigation_reading_live_smoke_report.json`.

Every live suite now declares an `initial_interface_id`. Before constructing
the Agent provider or Operation adapter, the runner captures the current
interface once and compares its observed identity with that declaration. A
mismatch returns `needs_human_review / initial_interface_mismatch` with zero
model calls and zero actions. A match reuses that same capture for the first
Agent decision, so preflight does not create a second screenshot with different
coordinates. The real mismatch report is
`logs/smoke/navigation_reading_initial_state_mismatch_v1/navigation_reading_live_smoke_report.json`.

Reviewed assets provide semantic choices and completion rules only. Current
screenshots provide geometry, every real transition and scroll passes the
existing Operation/Gate path, and Trace records before/after evidence. OCR
bottom-marker comparison tolerates whitespace loss while preserving the
original OCR text in Trace. Form filling and final submit remain outside this
capability.

These are two controlled local live paths, not a general reliability or
success-rate claim. The second path covers branching, back navigation, a
dialog, and bounded reading of an infinite-style collection, but unfamiliar
applications, wrong-scope live failures, additional scroll containers, and
longer workflows still require broader live coverage.

A fresh positive full-chain rerun used the framework's own `/apps/open` path to
open and bind the controlled fixture at `branch_hub`. The preflight matched,
the same initial capture reached the first Agent decision, and the full
branching path completed with 14 serialized model decisions, six verified
transitions, three reads, three effect-verified scrolls, one explicit
`stop_reading`, zero failed step, and final `safe_stop`. This remains controlled
fixture evidence rather than unfamiliar-application reliability.

Learn Mode Stage2 now applies conservative repeated-layout review enhancement before calibration and fusion. It combines existing semantic card candidates with current-image repeated rectangles, regularizes only stable peer rows/columns, preserves each raw bbox as `source_bbox`, and refuses to shrink multi-column candidates into one slot. The class rule may declare an expected peer-item family, but actual geometry changes still require current visual repetition. The fixed MSN/Protopage/Yahoo experiment remains available at `configs/demos/layout_regularization_msn_protopage_yahoo_v1.json`; it is review assistance, not recognition accuracy, Agent memory, or Execute authorization.

The same Stage2 enhancement includes a conservative one-hop same-class neighbourhood prior. It can propose only a directly adjacent, visually supported, previously unoccupied slot from confirmed seed pairs; inferred proposals never seed more proposals. Every proposal remains `needs_human_review`, display-only, and disconnected from Agent memory, Gate, and Execute. The class-rule demo emits an Agent-readable strategy summary containing the declared peer family, whether current visual evidence actually triggered, and review-only adjustment counts. On the checksum-pinned MSN fixture, the isolated experiment changed reviewed structural card coverage from `2 / 4` to `3 / 4`; this remains one fixture result, not model accuracy or general card reliability.

Stage2 also emits `agent_peer_card_inventory_v1`, a geometry-free semantic projection of current peer-card evidence. Row/column containers are excluded from the item list. Visual card parents may expose their current member text as readable candidates, while text-only groupings and inferred neighbours remain `review_only_candidate` and cannot become readable or open-detail actions. Open-detail capability requires explicit current interactable/action evidence; the class prior alone cannot create it. The fixed replay report separates readable items from review candidates and explicitly treats those counts as current-screen inventory, not recognition accuracy or execution reliability.

Real Qwen3-VL calls separately identified aggregate-portal, news-feed, video-search, and ordinary-search signals on MSN, Google News, YouTube, Vimeo, Bing, and Google screenshots. This is not yet browser-class runtime completion. The full two-stage Vimeo and Google holdouts still selected the conservative `generic` adapter because structured inventory did not contain enough repeated-item semantic evidence to corroborate the model signals. The next recognition fix belongs in structured inventory semantic projection and aggregate-module child grouping; the Surface Adapter evidence gate must not be weakened. Human review must compare the original screenshot, Stage1/root-partition overlay, and final fusion overlay from the same capture. A machine validator or model repair result cannot replace that three-image review.

The panel exposes that library through `学习工作台 -> 已学习的软件流程`. On a normal panel start it restores the newest saved reviewed workflow before scanning the larger raw-result history, so the branching graph and per-interface evidence are available without waiting for unrelated artifact discovery. Loading a recent single-interface result no longer replaces an already opened software workflow. Saving an audited workflow refreshes the library and reopens the exact persisted version immediately. The selector and `打开已学习流程` remain available for switching to another software/workflow. `新建软件 / 网站流程` creates an empty display-only workflow for the supplied application identity, and `打开源文件夹` opens the fixed local workflow-review directory so users can inspect or manually remove unwanted assets without exposing an arbitrary filesystem path API. Reviewed multi-interface workflows are stored under `artifacts/interface-workflow-reviews/<workflow_id>/reviewed_workflow.json` and indexed by `artifacts/interface-workflow-reviews/registry.json`. Raw single-interface model outputs remain under `artifacts/learning-runs/<run_id>/trial_result.json`; the user UI presents them as saved single-interface learning results, while legacy `draft_*` field and route names remain for API compatibility. Published reviewed Agent memory, when explicitly approved, is stored separately under `artifacts/agent-memory/`.

Historical artifacts that do not carry a capture-bound application identity can be composed only as development/review scaffolding. They do not prove that the nodes belong to one application or form a real observed transition. Production-ready continuous learning must record application identity on every capture and reject mismatched sources before operational-memory promotion.

This checkpoint covers application-scoped multi-interface review, branching graph inspection, and Agent-readable planning-memory lookup. It does not yet establish automatic operational-memory publication, verified destination transitions, recognition reliability, or unattended execution.

The authoritative workflow store is durable for one API owner. It commits replay-validated UTF-8 JSON to `runtime_state/learning-workflow-runs.json` by default, while managed workers persist identity-only journals and identity-bound result envelopes under `logs/workflow-workers/`. Result adoption and continuation are separate, digest-bound contracts. Backend continuation automatically constructs and dispatches the first worker for each newly issued stage in the active process. If payload construction or worker start fails, the new operation is closed as terminal `failed` with `worker_start_failure` evidence instead of remaining orphaned. Automatic continuation after API reload and shared multi-worker deployment remain unsupported. These contracts prove workflow ownership and evidence integrity, not recognition accuracy, Execute authorization, or unattended reliability.

Bind/capture is model-free and stores the immutable source screenshot through `/state/capture_window`. The actual 8B Observe request starts only after the backend issues the `screen_understanding` operation; `vision_observe_screen` reads that exact image with `capture_live=false`, and learning-draft generation follows under the same operation ID, heartbeat, worker ownership, and cancellation boundary. This closes the previous mismatch where the panel showed bind/capture while Observe inference was already running. Managed model requests now carry a worker-owned request ID. The local VISTA server supports matching request cancellation and exposes the active request through `/health`; cancellation is reported as model-service `terminated` only after health proves that request is no longer active. Qwen/llama-server request-level cancellation is still `not_supported`.

Long-running managed stages renew the same server-issued operation lease through `/panel/heartbeat_learning_workflow_stage_operation`. Before following a backend-issued successor, the panel waits for any in-flight heartbeat and replaces its active operation identity, so later heartbeat and cancellation requests target the real current stage. VISTA cancellation is cooperative and request-scoped; unsupported providers remain explicit. Automatic first-worker dispatch is covered for the active process, while automatic full-flow continuation after API reload and multi-process coordination remain future work.

### Continuous SEEK Quick Apply Demo Scaffold

The Learning Draft view now includes a compact continuous-task handoff. Before Quick Apply entry, it displays the current verified job-detail screenshot and enables one explicit `Confirm Quick Apply entry` action. On an unknown SEEK-hosted Quick Apply interface it instead pauses for learning, exposes the checksum-verified screenshot and interface ID, and loads that exact evidence into Learning Studio without operating the target window. After human review and reviewed-memory publication, the panel rechecks the same task and enables `Continue original task` only when the matching active memory, screenshot freshness, checkpoint phase, and no-submit constraints all pass. A runtime-written latest-task pointer avoids recursively scanning the large artifact tree during panel startup.

The offline acceptance covers `pause -> publish reviewed memory -> resume the same run directory`; the resumed command does not reopen results or rescan cards. A bounded live run at `logs/smoke/seek_continuous_live_confirmation_20260727` opened the SEEK recommendations page, read one full job detail, produced an Agent `maybe_apply` decision, and stopped at `quick_apply_entry_confirmation_required` in about 30 seconds. Safety counters remained `submit_clicks=0` and `final_submissions=0`. The panel loaded this checkpoint in about 44 ms and displayed the confirmation button; it was not clicked. External ATS/login and final-submit-visible surfaces remain safe-stop boundaries. This is not live safe-fill or SEEK E2E reliability evidence.

A supervised single-job run at `logs/smoke/seek_one_job_final_learning_20260728` learned four consecutive SEEK Quick Apply interfaces: document selection, employer questions, profile update, and final review. The saved review graph is `artifacts/interface-workflow-reviews/seek_quick_apply_one_job_final_review/reviewed_workflow.json`; it contains four evidence-ready nodes and three human-supervised `continue_next_step` transitions. It is indexed as read-only Agent context for `web:seek.co.nz`, but remains `published=false`, `artifact_is_authorization=false`, and `execute_binding_enabled=false`.

The same run exposed and fixed a common final-submit safety gap: a VISTA direct candidate could point inside a real UIA submit button while hiding its text behind a synthetic candidate ID. The Action guard now associates the final point only with overlapping action-control evidence, so the live visible `Submit application` dry-run returns `final_submit_guard_rejected` with `action_executed=false`. No live free-text fill or final submit occurred. This is one supervised workflow example, not SEEK E2E or unattended-reliability evidence.

The layered Surface Adapter benchmark now has separate protocol dev and holdout manifests. Every explicit host adapter, host status, content adapter, content status, and combined decision expectation must pass for a case to pass; the old single `adapter_id` can no longer hide a layer mismatch. The committed dev/holdout cases are `fixture_only`, and both reports keep `model_ability_denominator.attempted=0`.

```powershell
uv run python scripts\run_surface_adapter_benchmark.py `
  --manifest tests\fixtures\learning_surface_adapter_protocol_dev_manifest_v1.json `
  --out logs\benchmarks\surface_adapter_protocol_dev `
  --json

uv run python scripts\run_surface_adapter_benchmark.py `
  --manifest tests\fixtures\learning_surface_adapter_protocol_holdout_manifest_v1.json `
  --out logs\benchmarks\surface_adapter_protocol_holdout `
  --json
```

### Two-Week Practical-Use Track (2026-07-22)

Learning Mode now emits a read-only `learning_surface_adapter_decision_v1` alongside its existing interface classification. The contract supports `browser`, `chat`, `mail_workspace`, `media_player`, `employment_workflow`, and `generic` adapters. `employment_workflow` is a cross-site task adapter, not a SEEK adapter: correlated model and current-inventory evidence may classify `job_search_results`, `job_detail`, `application_form`, `application_review`, `mixed`, or `ambiguous` states. Ordinary surveys, registration forms, ecommerce lists, and checkout review pages are negative boundaries. BrowserAdapter remains an independent host adapter and excludes only explicit browser-chrome inventory evidence. Root geometry remains `deterministic_root_partition_v1`; no adapter may emit final bbox geometry, click points, Execute binding, final-submit authorization, or safety overrides. The rule audit is in `docs/learning/SURFACE_RULE_INVENTORY.md`; the two-week implementation checklist is in `docs/superpowers/plans/2026-07-22-learning-mode-practical-use.md`.

Browser is now treated as a host adapter while Chat, Mail Workspace, and Media Player are content adapters. A browser-hosted content surface therefore keeps both pieces of evidence instead of letting browser chrome routing erase the page-content strategy. The decision reports `host_adapter_status` and `content_adapter_status` separately. Content adapters require correlation between the model classification and independent inventory topology; application names or one coarse model signal cannot activate them. Framework-generated structural IDs are normalized only through a small generic allowlist, and legacy mail rows require repeated rows plus visible mailbox anchors before the Mail policy is selected. Validated content adapters compile Stage2 policy; the legacy classification profile remains in reports only for compatibility. The real panel loads only checksum-valid `active` CorrectionMemory rules and exposes matching rules as non-geometric advisories. It never reuses an old screenshot bbox, and candidate or merely reviewed rules cannot enter this path.

Completed panel `trial_result` artifacts and raw observe traces now share one replay input contract. The loader reads the nested observe bundle and checksum-bound learning-draft regions without inventing missing evidence. Offline replay of older QQ, Gmail, and Bilibili outputs intentionally exposes outdated model protocols and model/inventory conflicts instead of treating them as successful class selection. These are routing and dataflow checks, not model accuracy or general interface-recognition reliability.

The Learning Draft panel also has a full-image manual bbox editor with add, move, eight-direction resize, delete, undo/redo, role, and parent editing. Add mode temporarily makes existing boxes pointer-transparent so a new box can be drawn over dense evidence instead of accidentally selecting an old box. Saving creates a checksum-bound, versioned `human_review_patch_v1`, rebuilds the numbered overlay, page details, and read-only PathGraph, and records the correction as a non-active CorrectionMemory candidate. The compact manual-edit fields now bind to explicit region/action IDs; after save, the panel requires the reviewed candidate path, reloads that candidate before closing the editor, increments the image revision, and refreshes the form, region list, screenshot, page detail, workflow evidence, and read-only PathGraph from the same source. The same exact-source refresh is available from `刷新当前证据` beside the workflow evidence controls. Both automatic and manual refresh skip unrelated sidecar discovery, replace only the saved interface source, and preserve every other interface and transition in the current software workflow. The save button shows an in-progress state and remains available with an explicit failure state when either parent or workflow refresh fails. CorrectionMemory refresh is auxiliary and can no longer block the saved candidate from appearing in the panel. The human-review overlay takes display precedence over the stale pre-review fusion overlay. The review panel spans the full replay workspace width while history and screenshot remain a compact two-column row, so long draft inventories expand into available space instead of leaving an unused second column. Rule promotion is strictly `candidate -> regression_verified -> human_approved -> active -> rolled_back`; model output cannot approve or activate a rule, and tampered active evidence is rejected by checksum. See `docs/learning/CORRECTION_MEMORY.md`. No correction rule is active by default, and this remains read-only Learning Mode behavior.

Human-approved `reviewed_template_candidate_v1` artifacts can now be published into a checksum-addressed Agent operational-memory registry. The Learning Draft panel exposes publish, load, Execute preview, low-risk Execute, and return-to-edit controls. The action selector is an optional operator override: by default, the Agent resolves the natural-language goal to one unique low-risk memory action and rejects no-match, ambiguous, or high-risk results. Publication is not click authorization: every preview or real execution captures the current window, validates page-level text evidence, re-runs VISTA grounding and rerank, then verifies that the selected point is locally associated with a current OCR anchor inside the memory seed neighborhood before Gate and dispatch. Wrapped card titles may use adjacent OCR-line composition, while loose token matches and the same text elsewhere on the page cannot authorize the click. Successful planning responses expose the complete `local_target_validation` evidence; local mismatch responses preserve the same evidence and return the memory action to human review. Historical click coordinates remain forbidden, and post-action verification remains mandatory. Execution failures are persisted as `operational_memory_execution_feedback_v1` and point back to the reviewed candidate for human correction; the feedback artifact is not action authorization.

A bounded current-code run resolved `Open Documentation` without an action ID, selected `(1152, 276)`, opened Python.org Documentation, and passed post-action verification (`logs/traces/actions/20260727-012748-965096__execute-mode-click__msedge-exe.json`). A SEEK negative run rejected stale `Senior Test Engineer` memory because the exact OCR anchor was 356 pixels from the selected point, beyond the 180-pixel local threshold; no click occurred and feedback was written (`logs/traces/actions/20260727-012554-257633__execute-mode-plan-preview__msedge-exe.json`). A current wrapped-title SEEK memory then selected `(878, 817)`, opened `General Practitioner - Hauora Heretaunga`, and verified the detail panel (`logs/traces/actions/20260727-013543-423238__execute-mode-click__msedge-exe.json`). No run clicked Apply, filled a field, or submitted anything. These are bounded workflow and safety proofs, not a general success rate or unattended-reliability claim.

The final Demo target is a continuous SEEK-hosted Quick Apply session rather than one isolated screen. The Agent must read each complete job detail before deciding suitability; local keyword pruning is disabled. Reviewed memories may accelerate current-screen recognition, but every transition still requires a fresh capture, current localization, Gate, and post-action verification. `scripts/seek_speed_demo_runner.py --continuous-session` persists `continuous_task_session.json` and `seek_continuous_checkpoint.json`, waits for explicit Quick Apply entry approval, pauses before filling an unknown Quick Apply state, and resumes the same `run_dir` after matching memory is published. The live recommendations-to-confirmation slice and panel handoff are now verified. The remaining live acceptance is the post-confirmation unknown-state learning pause and final-review safe-stop; no current evidence proves live safe-fill reliability.

The same panel now shows a read-only Human Correction Memory list after startup and refreshes it immediately after a manual draft save. The list exposes only safe summaries such as rule ID, lifecycle status, surface adapter, edit types, correction count, and evidence validity; it does not expose raw human notes, before/after payloads, or screenshot content. Candidate rows remain non-production, and the panel intentionally has no approve or activate control until a separate human approval step is designed and verified. The live API field audit found no raw correction, screenshot, or source-patch fields. The current registry view reports three candidates and zero active rules. A real panel visual audit also confirmed that the manual editor, correction memory, page details, and read-only PathGraph headings each render once with no page-level horizontal overflow. Chat/Media regression coverage additionally proves that application names such as QQ, WeChat, WhatsApp, Apple Music, and Spotify cannot activate a content adapter by themselves, and that a validated Media policy reaches the real Stage2 output.

The delivery target is two weeks, not one day. Week 1 makes the real panel usable and recoverable; Week 2 runs the protected and holdout interfaces, fixes shared failures, and closes with an end-user correction trial. Real Apple Music, QQ, and Windows Settings correction replays have passed bbox edit, save, reload, rebuilt-overlay, page-detail, read-only PathGraph, and candidate-only CorrectionMemory checks. The latest third-surface evidence is `logs/benchmarks/learning_human_correction_acceptance_windows_settings_20260722/learning_human_correction_acceptance_report.json`; the panel registry now reports three candidates and zero active rules. Screenshot evidence must be present, checksum-bound, and fully decodable before a human geometry patch is accepted.

The latest fifteen-interface model-backed rerun is complete. The strict aggregate at `logs/benchmarks/learning_practical_acceptance_final_aggregate_20260722/learning_practical_acceptance_aggregate_report.json` reports `collection_status=collection_complete` and `quality_status=review_evidence_complete`: all 15 cases have original/Stage1/final evidence and complete the read-only display chain, while the nine cases with frozen class expectations pass those manifest checks. The two Steam failures in the first aggregate were traced by three-image review to stale expectations: both source images contain a real docked group-chat bottom area, so the manifest now expects `bottom_bar`. The six holdouts still have no class-expectation denominator and remain `not_covered` for that metric. These are review-chain and manifest-conformance results, not recognition accuracy, Execute readiness, or unattended reliability evidence. No live click, fill, submit, Execute binding, or Runtime PathGraph promotion occurred.

The first common fix for that GitHub Desktop contamination is now in Stage1.5. A geometric multi-pane finding may select chat-specific `conversation_list`, `message_thread`, and `bottom_composer` roles only when the validated surface profile allows chat semantics or structural container evidence independently identifies a chat surface. Plain OCR/page text, including source code containing words such as `conversation` or `composer`, cannot switch the semantic family. Non-chat multi-pane layouts use contiguous neutral `list_pane` and `detail_pane` suggestions from current-image separators or element gaps. Focused recognition regression reports `241 passed`; a saved GitHub trace replay emits no chat roles. The required fresh model-backed GitHub/QQ/WhatsApp replay is still pending because the user is using the GPU, so no VISTA or Qwen model was launched.

The File Explorer failure had both downstream and upstream causes. Generic sibling-overlap normalization first removed eight adjacent rows because OCR-inflated row heights overlapped by 18%–38%; distinct same-column repeated rows are now preserved while true duplicate containers remain suppressed. Upstream row synthesis also tied minimum row span to the full primary-region width and required three globally dominant columns. That dropped indented folder names and rows with one OCR-missing or merged cell. The table detector now establishes strict repeated columns first, derives span from the table's own row evidence, and only then recovers rows with at least two column anchors plus the established row rhythm. A checksum-stable File Explorer replay now produces all 35 visible `table_row` groups, above the protected minimum of 25. This is fixed-screenshot offline regression evidence, not a fresh model run or a general recognition-rate claim.

The WhatsApp protected failure also contained two common dataflow defects. Stage1.5 conversation-list children were generated but were dropped when the hierarchy builder required their IDs to equal the Stage1 root ID; explicit `parent_region_id` linkage now attaches those children to the authoritative root and preserves 10 `conversation_row` groups. Separately, the root partition detected the real near-full-width title-bar separator at `y=40`, but its `0.9453` support narrowly missed a hard `0.95` T-partition threshold, so the title bar was merged into main content. The threshold now accepts near-full-width `0.94+` separators only in the presence of an independently supported full-height edge rail. A fixed-trace nine-interface replay keeps eight root geometries byte-for-byte unchanged and changes only WhatsApp to adjacent `left_nav`, `top_bar`, and `main_content` roots; all nine root expectations, validators, Stage1 gates, Stage2 runs, and three-image sets pass. The report is `logs/benchmarks/learning_practical_root_regression_20260722_final/deterministic_first_recognition_report.json`. Manual three-image review accepts the root geometry but keeps the dense final overlay review-only. This is CPU offline fixed-trace evidence, not a fresh model run, recognition accuracy, or unattended reliability.

The Apple Music protected hierarchy miss also had a common evidence-order cause. A valid year-led section title was rejected merely because it contained digits, and Stage2 required two OCR fragments before it would inspect visible bottom-edge card pixels. Section-title validation now requires semantic letters or CJK text while continuing to reject timestamps, counts, dates, and pure years. Visual card evidence is collected before the sparse-OCR decision, so one OCR fragment plus multiple visible card boxes can recover review-only partial cards. The fixed Apple Music trace now synthesizes five partial cards and raises the learning-draft region count from 44 to 50; the other eight fixed-trace root results remain valid. Evidence is in `logs/benchmarks/learning_practical_sparse_partial_cards_20260722/deterministic_first_recognition_report.json`. This is CPU fixed-trace evidence only; the historical model-backed acceptance report remains unchanged until a fresh model rerun is allowed.

The next fresh model check is frozen as the checksum-pinned three-case manifest `tests/fixtures/learning_practical_targeted_rerun_manifest_v1.json`. It contains WhatsApp for the repaired structure hierarchy, QQ for chat hierarchy recall, and GitHub Desktop for the non-chat semantic-contamination guard. Expectations were frozen from the original screenshots, `used_for_rule_tuning=false`, and `holdout_used_for_tuning=false`; the manifest itself contains no result. While the user is using the GPU, only CPU validation is allowed and the rerun remains pending.

The class-expectation audit now enforces declared bar semantics instead of merely echoing them. Missing `expected_bar_types`, present `expected_absent_bar_types`, and missing `expected_sub_bar_roles` each produce an explicit `needs_review` issue; reports include the observed `bar_types` and `sub_bar_roles`. This makes the targeted WhatsApp top-bar/sub-bar check executable rather than documentary. It is a conformance gate, not an accuracy metric.

The checksum-pinned WhatsApp / QQ / GitHub Desktop targeted rerun has now completed with the real VISTA grounding service. The final report is `logs/benchmarks/learning_practical_targeted_final_regression_20260722/learning_interface_chain_smoke_report.json`: all three cases completed the read-only chain, produced complete original/Stage1/final evidence, and passed their frozen class/structure expectations. A validated conversation profile now triggers Stage1.5 pane decomposition even when parser roles are generic, so WhatsApp preserves 10 conversation rows and QQ preserves 21 conversation rows plus 4 message items. GitHub Desktop remains generic rather than form/chat, and dense code/document surfaces downgrade weak model `news_card` / `recommendation_item` interpretations to review-only `document_section` nodes while retaining explicit visual `content_card` / `media_card` evidence. This is three-case conformance evidence only, not recognition accuracy, general holdout reliability, Execute readiness, or Runtime PathGraph authorization. Full repository verification reports `1881 passed`; VISTA was stopped after the run.

### Stage1 Color-Block Partition (2026-07-20)

Stage1 now detects long, high-contrast RGB color-block boundaries before weaker grayscale separators and element-derived cuts. The rule requires broad cross-screen support, so a local card or decorative patch cannot create a root partition. In the protected nine-interface replay, eight root geometries stayed identical; File Explorer's left navigation boundary moved from `174px` to the visually matching `155px` color boundary. Original, root-partition, and final-fusion images were compared for the changed case. This remains fixed-trace structural regression evidence, not a general recognition-rate claim.

### Learning Review And Finalization (2026-07-19)

Stage2 now records atomic evidence and semantic interpretation as separate streams. `learn_stage2_dual_streams_v1` keeps `visual_objects`, `semantic_groups`, and post-hoc `associations`; a semantic container cannot claim a small visual candidate before atomic control synthesis. Bar candidates may compile into complete control parents, while non-bar raw candidates remain review-only evidence until a parent control is established. Existing `numbered_items` and `subregion_groups` remain as compatibility outputs for page details and the read-only PathGraph.

The QQ offline replay that exposed this ordering bug now keeps 13 left-rail control parents and reduces the rendered Stage2 inventory from 155 noisy items to 82 by retaining 74 conversation-list visual fragments in the evidence stream instead of numbering them. This is one fixed replay and a data-integrity improvement, not recognition accuracy. After checksum-validating the current 30-annotation ownership golden, the fixed general hierarchy benchmark reports `9 / 10` supported cases and `23 / 27` ownership annotations. Steam remains the supported failure; NVIDIA remains a separately declared known limitation. A stale ownership fixture now invalidates the benchmark instead of narrowing the denominator or producing a capability-pass claim.

The panel Learning Interface flow now runs precise calibration before display-only model review and repair. Stage2 produces the numbered candidate map, VISTA/OCR/rerank/Gate dry-run adds current positioning evidence, and Qwen3-VL 8B then receives the calibrated composite overlay plus Stage2 JSON. Strict validators keep final geometry, allowed roles, content preservation, and completion authority in code. Valid `conversation_row`, `list_row`, and `table_row` leaves may bypass model review only after parent-containment and size invariants pass. Removed wrappers must preserve their atomic children, and the reviewed revision must pass the integrity gate before fusion, page-detail output, or read-only PathGraph output.

Focused model review also handles one bounded schema-copy error: when `observed_role` exactly repeats the reviewed source region ID, the parser may recover the role only from that same authoritative Stage2 record. Arbitrary unknown roles remain invalid and still safe-stop the integrity gate.

The review contract now treats a rejected missing-region proposal as a rejection regardless of any provisional role emitted with it, normalizes the common `message_bubble` alias, and scopes generated review-group IDs to their parent region. Chat-like Stage1.5 layouts may use a second evidence-backed vertical separator to preserve an auxiliary pane instead of letting the message thread consume it. Missing-region repair remains conservative: it cannot recreate a semantic region from one OCR text atom, nest navigation inside an existing navigation parent, or place message items inside a conversation list or bottom composer. A fixed QQ model-review replay now reaches deterministic repair closure without protocol failure. This is one review-path regression result; bottom-composer/tool-row recall and overlay readability still require improvement, and it is not a recognition-accuracy claim.

A real QQ API run completed the 8B review in about 386 seconds and produced a new final numbering revision with 49 calibration candidates and 57 child-evidence records. The subsequent VISTA dry-run loaded all 49 candidates, but only 13 of 44 eligible targets were attempted before one per-target request timed out; 6 targets passed the precise-locator review gate. Trace review found the stall contract: timeout/model-busy attempts were incorrectly added to `completed_candidate_ids`, and the next batch could collide with the still-held model generation lock. Retryable attempts now remain in `remaining_candidate_ids`, the panel waits until `/runtime/models` reports the locator idle, and recovery has a bounded retry limit. The historical result remains incomplete dry-run evidence, not point-grounding reliability, and performed no click.

Precise calibration now uses revision-bound resumable batches. Every local-model inference runs `model_resource_preflight_v1`. The initial Observe request uses the panel's `ensureStageModelReady` entry because it carries the user-selected Observe profile. Backend-managed workers perform resource preflight and model-service readiness for subsequent learning-draft, Stage2, model-review, and calibration tasks; the panel only follows their operation and worker identities. Critical load or `model_launch_allowed=false` is surfaced as an explicit blocker. Resource preflight recommends batch size `8` for an idle machine, `2` for constrained GPU/system memory, or `1` for critical load; an unavailable probe uses conservative batch size `2`. Each VISTA batch uses the latest recommendation directly, so an initial constrained result no longer permanently caps later batches at `2`; the batch may rise or fall as GPU load changes. Resume payloads retain candidate identity, point, selected candidate, Gate result, and evidence status while excluding repeated model I/O and preprocessing blobs. Known local model processes include descendants of the profile launcher. When Windows/WDDM reports zero per-process VRAM for a running model, the preflight attributes the profile's declared reservation to that known model, bounded by aggregate usage. High aggregate utilization is likewise attributed to the known model only when no external GPU process is measured and unattributed memory remains low; real external game/process load still constrains or blocks launch. The launch check also compares free VRAM with 90% of the profile's declared GPU-memory requirement; insufficient headroom is `critical`. Both Qwen3-VL 8B profiles declare a 7 GiB budget, while VISTA declares 10 GiB. This is resource-gating and batch-contract evidence only, not point-grounding reliability.

The same resource contract now guards the multi-interface acceptance runner. It supports resumable cases and writes `resource_blocked` before a model request when GPU headroom is insufficient:

```powershell
uv run python scripts\run_learning_interface_chain_smoke.py `
  --manifest artifacts\benchmarks\interface_class_recursive_manifest_v1.json `
  --manifest tests\fixtures\learning_surface_adapter_holdout_manifest_v1.json `
  --batch-index 0 `
  --out logs\benchmarks\learning_practical_acceptance `
  --json
```

Repeat `--manifest` to form one acceptance denominator and repeat `--resume-report` to skip case IDs already completed by prior batch or aggregate reports. Resume reports must use the exact same manifest set; unknown or duplicate completed cases are rejected. Because the resource-selected batch size may change between runs, completion-ID resume keeps `--batch-index 0`; a non-zero index with completed IDs is rejected instead of risking a skipped case. Repeated `--case-id` options may still select a targeted batch. A blocked batch has `model_calls_attempted=0`; pending cases are not scored. The protected manifest has nine cases and the independent holdout manifest has six. Completing these fixtures is three-image review-chain evidence, not recognition accuracy or unattended GUI reliability.

Merge every completed or resource-blocked batch into one strict checkpoint by repeating `--batch-report`:

```powershell
uv run python scripts\aggregate_learning_practical_acceptance.py `
  --manifest artifacts\benchmarks\interface_class_recursive_manifest_v1.json `
  --manifest tests\fixtures\learning_surface_adapter_holdout_manifest_v1.json `
  --batch-report logs\benchmarks\learning_practical_acceptance_batch_0\learning_interface_chain_smoke_report.json `
  --out logs\benchmarks\learning_practical_acceptance_aggregate `
  --json
```

The aggregate rejects duplicate completed cases and manifest-set drift. It reports collection status, three-image completeness, chain completion, class expectations, failure cases, and safety separately; it does not emit a total recognition rate. Resource-blocked reports preserve pending cases without putting them in any quality denominator. A pending or quality-review aggregate is still written to disk but returns a non-zero process status so automation cannot mistake evidence collection for acceptance. Current failure records preserve the source, Stage1, final overlay, trace, and report paths from the current three-image contract. The latest collection completed 15/15 cases, while quality remains `needs_review`; holdout class expectations remain `not_covered`.

For the next batch, rerun the chain command with `--resume-report logs\benchmarks\learning_practical_acceptance_aggregate\learning_practical_acceptance_aggregate_report.json` and keep `--batch-index 0`. Then refresh the aggregate without relisting every old batch:

```powershell
uv run python scripts\aggregate_learning_practical_acceptance.py `
  --manifest artifacts\benchmarks\interface_class_recursive_manifest_v1.json `
  --manifest tests\fixtures\learning_surface_adapter_holdout_manifest_v1.json `
  --resume-aggregate logs\benchmarks\learning_practical_acceptance_aggregate\learning_practical_acceptance_aggregate_report.json `
  --batch-report logs\benchmarks\learning_practical_acceptance_next_batch\learning_interface_chain_smoke_report.json `
  --out logs\benchmarks\learning_practical_acceptance_aggregate_next `
  --json
```

The refreshed aggregate inherits the prior batch-source list, appends the new batch, and becomes the next `--resume-report`. Identical report paths are deduplicated; different reports that claim the same completed case still fail strict aggregation.

The reviewed page-detail and read-only PathGraph adapters now carry `learning_repaired_source_identity_v1`. The source resolver reads the identity from the nested integrity-gated final Stage2 when a fused trial wraps it, rather than silently emitting an empty identity. A real Windows Settings panel flow verified that the final calibrated overlay, page-detail candidate, demo scaffold, and nested read-only PathGraph share capture hash `895d926e...72d` and final numbering revision `a2599d84...990`; `same_repaired_source_verified=true`. The run completed all nine display-only learning steps, including bounded VISTA batches, with no click, fill, submit, Execute binding, or Runtime PathGraph promotion. This is an auditable display-lineage and control-flow check, not recognition accuracy or point-grounding reliability.

The final review-overlay renderer now compiles complete atomic control parents into the main display layer and suppresses their OCR/icon member fragments from duplicate rendering. The fragments remain available in the Stage2 dual-stream JSON for audit and review. Re-rendering the current QQ final Stage2 produced 23 control-parent boxes, suppressed 67 member fragments from the main overlay, and left 15 unmatched atomic items visible as review-only evidence. This is a presentation/dataflow correction, not recognition accuracy or Execute authorization.

Current-capture evidence now also governs blank and misplaced review boxes. UIA-only text whose current screenshot crop is uniform is retained in audit data but suppressed from the main overlay. Stage1.5 chat decomposition anchors the message/composer boundary to a supported horizontal separator when factual composer evidence exists below it; model-only input-area or toolbar guesses cannot move that boundary. Semantic groups with no current renderable members are likewise hidden by both the fusion and model-review renderers. The fixed QQ trace removes two stale blank UIA boxes and a model-only composer cluster while keeping the current screenshot, Stage1 roots, and review-only safety boundary unchanged. This is one deterministic replay, not a general recognition-quality claim.

Chat image-message synthesis now inherits an already confirmed Stage1.5 `message_thread` classification instead of requiring a second atomic chat anchor. Large images keep the existing visual threshold; smaller stickers are recovered only when multiple current-capture candidates have similar dimensions and a shared alignment edge. The fixed replay restores three repeated `52x42` stickers and two larger image messages without globally admitting isolated small contours. This is current-screenshot candidate recall evidence, not a model or cross-interface recognition-rate claim.

The latest fixed nine-interface development run completed `9 / 9` review-and-repair integrity cases with `0` failed, `0` invalid, and `0` safe-stop cases. This means the recorded model responses, deterministic repair closure, final Stage2 binding, and report contract completed on those fixtures. Human-adjudicated keep precision, false-group cleanup, relabel quality, missing-region detection/recovery, and atomic-evidence quality remain `not_covered`; therefore `9 / 9` is not recognition accuracy or cross-interface reliability.

A real panel API smoke produced a current final reviewed overlay, final Stage2 report, numbering revision, and trace. The resulting display-complete Apple Music learning draft loads as the panel's current recommendation and renders the same-source reviewed overlay, page details, and read-only PathGraph preview. The panel now loads the history source list during boot and visibly labels the selected artifact as `[Recommended current]`; old benchmark scaffolds are labeled `[Pinned reference]` and cannot displace a newer display-complete draft. The latest real browser replay loaded the 1154x1005 reviewed overlay, reported 32 review-only regions and zero executable action templates, rendered non-empty page details, and retained `needs_human_review · no_click_authorization=true`. No real click, fill, submit, Execute binding, live safe fill, or Runtime PathGraph promotion occurred.

The panel history source path now has a bounded sidecar-discovery contract. `/panel/learning_draft_sources` may read explicit and adjacent PathGraph review sidecars, but it must not recursively search all `logs` and `artifacts` for every listed candidate. On the current repository with more than 1,500 learning-run directories, direct source enumeration fell from about `23.2s` to `0.34s`; a fresh Uvicorn HTTP smoke returned `/panel` in `0.006s` and `/panel/learning_draft_sources` in `0.354s`. The normal panel service on port `8765` was then restarted on the current code and returned the source endpoint in `0.389s`. Full single-artifact review keeps the existing related-sidecar discovery behavior. These timings are a local performance check, not a recognition-quality claim.

Fresh 2026-07-20 verification is `150 passed` across the focused root-partition, GPU-resource, runtime-route, and panel suites and `1791 passed` repository-wide, plus successful JavaScript/Python syntax checks and `git diff --check`.

The final ChatGPT reviewer verdict for this declared scope is `PASS`: the current implementation is acceptable as a phase-close, display-only learning-review scaffold, with no code, panel, or safety blocker required before shutdown. Human-adjudicated recognition quality, action-template capability, Runtime PathGraph promotion, and Execute authorization remain explicitly outside this pass.

- [Current nine-interface review report](logs/benchmarks/learning_model_review_nine_interface_current_v9/learning_model_review_validation_report.json)
- [Current panel final overlay](artifacts/learning-runs/panel_review_20260719-112040-331_01_original/repair_closure/final_repaired_overlay/reviewed_overlay.png)
- [Current panel final Stage2](artifacts/learning-runs/panel_review_20260719-112040-331_01_original/final_stage2_for_calibration.json)
- [Current display-complete learning draft](artifacts/learning-runs/panel_20260719-114819-440_apple_music_reviewed/trial_result.json)

### Deterministic Hierarchy Checkpoint (2026-07-18)

Learning Mode now uses `deterministic_root_partition_v1` as the authoritative Stage1 source. The production chain no longer asks a model to invent top-level bars or runs the former bar-localization postprocessor:

```text
observe trace / screenshot evidence
  -> deterministic full-coverage root partition
  -> Stage1 structure gate
  -> Stage2 numbering inside each accepted root
  -> fused learning draft
  -> page details + read-only PathGraph
  -> learned-artifact candidate + Gate dry-run
```

Current fixed-trace evidence:

| Evidence | Result |
| --- | --- |
| Fixed interfaces | 9 attempted, 9 checksum-valid, 9 Stage1 gates passed |
| Stage1 source | `deterministic_root_partition_v1` |
| Model calls used for root partition | 0 |
| Three-image sets | 9 original / root partition / final fusion sets |
| Added holdouts | QQ, Steam Friends, Task Manager |
| QQ regression | internal whitespace no longer creates a false root split |
| Task Manager | 27 complete visible table rows plus one bottom partial row retained |
| Exact panel-request replay | 7 valid cases; 7 API/gate/Stage2/review loads completed |
| New Steam state | OCR label evidence restores the expected top/main/bottom root partition |
| Frozen nine-case drift | 0 root, Stage1, Stage2, numbering, or fusion-count changes |
| Downstream active-group normalization | suppressed sibling groups cannot re-enter final overlay, page details, or read-only PathGraph |
| Learned-artifact operation | Gate-approved `dry_run=true`; `action_executed=false` |
| Repository tests | 1588 passed |

Reports and traces:

- [Nine-interface deterministic benchmark](logs/benchmarks/deterministic_first_post_generalization_fix_v1/deterministic_first_recognition_report.json)
- [QQ holdout](logs/benchmarks/generalization_holdout_v2/qq/learn_screenshot_exploration_report_20260718-031920.json)
- [Task Manager holdout](logs/benchmarks/generalization_holdout_v2/task_manager/learn_screenshot_exploration_report_20260718-032003.json)
- [Seven-interface exact panel replay](logs/benchmarks/panel_more_interfaces_exact_request_regression_20260718/panel_more_interfaces_exact_request_regression_report.json)
- [Seven-interface three-image sheet](logs/benchmarks/panel_more_interfaces_exact_request_regression_20260718/three_image_contact_sheet.png)
- [Frozen nine-interface baseline diff](logs/benchmarks/deterministic_first_new_interface_semantic_bottom_regression_20260718/baseline_diff_report.json)
- [Active-group seven-interface replay](logs/benchmarks/panel_more_interfaces_active_group_regression_20260718/panel_active_group_regression_report.json)
- [Active-group seven-interface three-image sheet](logs/benchmarks/panel_more_interfaces_active_group_regression_20260718/three_image_contact_sheet.png)
- [Active-group frozen-nine baseline diff](logs/benchmarks/deterministic_first_active_group_regression_20260718/baseline_diff_report.json)
- [Active-group frozen-nine three-image sheet](logs/benchmarks/deterministic_first_active_group_regression_20260718/three_image_contact_sheet.png)
- [Learned-artifact Gate dry-run trace](logs/traces/actions/20260718-031304-338751__execute-mode-plan-preview__python-org.json)

These are structural and pipeline checks, not a general recognition-accuracy claim. The seven-case replay preserves the original 6/7 pre-adjudication root expectation and separately records the previously documented Windows Settings crop adjudication. Task Manager, Python.org, and Windows Settings retain raw sibling-overlap review evidence, but groups already suppressed by that review can no longer re-enter the final overlay, page details, or read-only PathGraph. Python.org still exposes unresolved item-owner ambiguity and remains stress-only. The NVIDIA overlay screenshot is excluded because it contains a mixed/wrong surface. No live click, fill, submit, or Runtime PathGraph promotion occurred.

### Current Stage

The read-only Learning Mode phase is accepted with declared limitations.

| Evidence | Current result |
| --- | --- |
| Phase status | `phase_acceptance_passed_with_declared_limitations` |
| Protected regression | 9 checksum-pinned cases |
| Three-image audits | 9 complete source / Stage1 / final sets |
| Read-only learning chains | 9 completed |
| Review-ready cases | 8 |
| Stress-only cases | 1, Python.org |
| Repository tests | 1585 passed |
| Strict final readiness | `final_goal_complete=false` |

Authoritative reports:

- [Phase acceptance report](logs/benchmarks/learning_mode_stage_acceptance_20260715/stage_acceptance_report.json)
- [Nine-case recursive report](logs/benchmarks/learning_interface_chain_stage_acceptance_20260715_rerun/learning_interface_chain_smoke_report.json)
- [Strict readiness report](logs/benchmarks/learning_mode_stage_acceptance_20260715/learning_mode_demo_goal_readiness_report.json)
- [Panel presentation evidence](logs/benchmarks/learning_mode_stage_acceptance_20260715/learning_interface_presentation_evidence_v1.json)

### Nine-Case Fusion Review

![Nine-case contact sheet](logs/benchmarks/learning_interface_chain_stage_acceptance_20260715_rerun/learning_interface_chain_contact_sheet.png)

| Case | Interface family | Final fusion image | Review status |
| --- | --- | --- | --- |
| Apple Music 2026-07-10 | Media catalog | [Open](artifacts/review-overlays/state-6bacc9cc36d224e3-learn-targets__learn-target-coordinates__20260715-194943-911989.png) | Review-ready |
| Apple Music 2026-07-11 | Media catalog | [Open](artifacts/review-overlays/state-d105e84d6c3a7091-learn-targets__learn-target-coordinates__20260715-195015-547117.png) | Review-ready |
| Python.org | Documentation portal | [Open](artifacts/review-overlays/state-521513ecc2a306e2-learn-targets__learn-target-coordinates__20260715-195025-921057.png) | Stress-only |
| Windows Settings | Settings dashboard | [Open](artifacts/review-overlays/state-2cd40c4415ab239a-learn-targets__learn-target-coordinates__20260715-195053-166912.png) | Review-ready |
| File Explorer | File browser | [Open](artifacts/review-overlays/state-656d16c3985759b7-learn-targets__learn-target-coordinates__20260715-195141-005171.png) | Review-ready |
| Steam 2026-07-13 | Conversation workspace | [Open](artifacts/review-overlays/state-3ee160a08ac3185c-learn-targets__learn-target-coordinates__20260715-195204-990549.png) | Review-ready |
| Steam 2026-07-14 | Conversation workspace | [Open](artifacts/review-overlays/state-038abc0eee06ec39-learn-targets__learn-target-coordinates__20260715-195225-208234.png) | Review-ready |
| WhatsApp | Conversation workspace | [Open](artifacts/review-overlays/state-d74a5379f44f615b-learn-targets__learn-target-coordinates__20260715-195258-709611.png) | Review-ready |
| Notepad | Generic editor | [Open](artifacts/review-overlays/state-b33c83e0d43877fa-learn-targets__learn-target-coordinates__20260715-195312-896997.png) | Review-ready |

### Panel Presentation

Desktop and narrow layouts render the current fused image, page details, and a resizable read-only PathGraph preview without horizontal overflow. Page-detail views with the same explicit report/source identity render once; a genuinely distinct model preview remains visible.

![Desktop learning panel](logs/benchmarks/learning_mode_stage_acceptance_20260715/panel_desktop.png)

![Narrow learning panel](logs/benchmarks/learning_mode_stage_acceptance_20260715/panel_narrow.png)

### Runtime Flow

```text
User conversation
  -> Agent decision
  -> Observe / OCR / vision inventory
  -> Operation candidate
  -> Gate safety decision
  -> Controlled action or safe stop
  -> Trace evidence
```

Reviewed multi-interface assets can now drive a generic navigation and reading
decision loop:

```text
current observe
  -> load reviewed interface evidence
  -> Agent chooses transition / region read / scroll / safe stop
  -> Operation resolves the choice against the current capture
  -> Gate checks the current target
  -> Operation dispatches
  -> Trace records dispatch and effect
  -> observe verifies the next interface or new content
```

Finite detail regions require explicit `reached_bottom` evidence before they are
reported complete. Infinite feeds use a bounded read budget and may stop after
no new content, but that stop is not reported as proof that the feed was fully
read. The current checkpoint is covered by fixture and trace-oriented tests; it
does not yet establish a live multi-interface success rate.

The first fixed replay can be rerun with:

```powershell
uv run python scripts\run_navigation_reading_replay.py `
  --manifest artifacts\benchmarks\navigation_reading_replay_v1\manifest.json `
  --out logs\benchmarks\navigation_reading_replay_latest `
  --json
```

The report separates Agent context/decision validation, Gate safety, Operation
dispatch, effect verification, destination observation, finite-read completion,
and wrong-scope safe stop. A dispatched action without a verified effect fails
the case. The current manifest contains a two-interface recorded news example;
it is a reusable scaffold for adding more reviewed interfaces, not evidence of
actual-model quality or live GUI reliability.

Learning Mode uses a read-only chain:

```text
Bind and capture
  -> evidence inventory
  -> deterministic full-coverage Stage1 structure regions
  -> Stage2 numbered regions
  -> page details
  -> OCR + VISTA + rerank + Gate dry-run
  -> fused learning draft
  -> read-only PathGraph preview
```

### Safety and Evidence Boundary

- Learning drafts and preview PathGraphs do not authorize execution.
- Every real click must pass the gated recognition-plan API with current screenshot and coordinate evidence.
- Final submit, send, confirm, and payment actions remain hard-blocked.
- The current evidence does not establish general recognition accuracy, pure-model template reliability, SEEK E2E stability, or live safe-fill reliability.
- No live click, fill, submit, Execute binding, live safe fill, or Runtime PathGraph promotion occurred during the current phase acceptance.

## Project Iteration History

### June 2026: Runtime Foundation

- Established the Agent, Operation, Gate, Trace, and reusable PathGraph architecture.
- Added Windows application discovery, exact window binding, screenshots, OCR/UIA evidence, controlled input, and action verification.
- Built the first SEEK profile and no-submit application safety contracts.

### Early July 2026: Learning Mode

- Separated execution models from learning models.
- Added full-screen understanding, Stage1 structure localization, Stage2 numbering, page-detail drafts, precise grounding, and read-only PathGraph previews.
- Separated model-generated drafts, human-assisted review assets, templates, and executable runtime assets.

### Mid July 2026: Generalization and Review

- Added hierarchy ownership, parent containment, browser-chrome filtering, same-source screenshot checks, stale-fixture detection, and cross-interface anti-pollution regression.
- Repaired dense two-column ROI behavior, non-actionable grounding leakage, stale overlay display, and precise-calibration progress reporting.
- Introduced mandatory source screenshot, Stage1 image, and final fusion image review for every protected interface.

### Late July 2026: Class-Aware Review

- Added generic surface adapters and kept visual objects separate from semantic groups so container interpretation cannot erase atomic evidence.
- Repaired media-card ownership by preferring original visual containment before adjacency. A real YouTube fixed-trace replay now keeps playlist, video, and Shorts cards separate and loads the current fused overlay in the panel.
- Current adapter benchmarks validate routing contracts on fixtures only; they are not recognition accuracy. Generic surfaces can now activate chat processing from strong local evidence while explicit non-chat profiles remain blocking. Native media classification still has explicit regression work remaining.
- Workflow graph links are now edited in a centered modal. Right-click a source interface, choose a target interface, then select the source control and operation without leaving or scrolling the graph. The inline link editor stays hidden until this explicit action.
- Selecting a transition control now opens a dedicated evidence picker. The unfinished link form remains intact while the reviewer selects a real evidence box, then the link dialog resumes with the selected control populated. This is a read-only review handoff and does not authorize target-window actions.

### 15 July 2026: Phase Acceptance

- Completed four current real-interface evidence sets and a nine-case protected recursive regression.
- Verified the desktop and narrow panel presentation with current same-source artifacts.
- Passed the complete repository test suite with 1538 tests.
- Kept strict final readiness blocked until model-only generation and independent holdout evidence are sufficient.

Detailed history and current planning:

- [Full iteration archive](PROJECT_ITERATION_HISTORY.md)
- [Project summary](PROJECT_SUMMARY.md)
- [Current state](CURRENT_STATE.md)
- [Architecture](ARCHITECTURE.md)
- [Next steps](NEXT_STEPS.md)
- [Agent API workflow](AGENT_API_WORKFLOW.md)
- [API field reference](API_FIELD_REFERENCE.zh-CN.md)
