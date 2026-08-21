# UEI Provider Shadow Runtime M2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-agnostic, local-only UEI Shadow runtime, execute the existing pinned OmniParser provider offline, and expose only a revalidated non-authorizing summary in Learning Draft review.

**Architecture:** An internal runtime resolves immutable UEI request/capture/profile context, selects a trusted adapter, executes it under a bounded worker/resource lease, persists a safe result plus a runtime receipt, and passes only an immutable result ref to learning. Learning and panel code revalidate that ref from a fixed store and render a compact display-only summary.

**Tech Stack:** Python 3.11, stdlib subprocess/JSON/hash/path primitives, existing UEI v1 schemas/JCS/store, FastAPI panel routes, vanilla panel JavaScript, pytest and Node test runner.

**Spec:** `docs/superpowers/specs/2026-08-21-uei-provider-shadow-runtime.md`

## Global Constraints

- M2 allows only registered, enabled, `local_only`, `Shadow` providers.
- No public request accepts image paths, commands, raw payloads, coordinates, provider identities, or runtime options.
- No provider/model import occurs from `import app.learn.recognition.uei`.
- All outputs remain display-only, review-only, non-authorizing, and excluded from action/grounding candidates.
- No network, live GUI capture, action API, replay, historical migration, commit, or push.
- Use one retained-context implementation worker and one final independent review gate.

---

### Task 1: Generic runtime contracts and deterministic fake-adapter path

**Files:**
- Create: `schemas/uei/v1/provider_runtime_receipt_v1.schema.json`
- Create: `app/learn/recognition/uei/provider_runtime.py`
- Create: `app/learn/recognition/uei/provider_adapters.py`
- Modify: `app/learn/recognition/uei/contracts.py`
- Test: `tests/test_uei_v1_provider_runtime.py`

**Interfaces:**
- Consumes: `resolve_projection_context`, `resolve_requested_profile`, `UEIObjectStore`, immutable request/capture/artifact refs.
- Produces: `ProviderRunBudget`, `RestrictedCaptureLease`, `NormalizedProviderItem`, `NormalizedScreenParseOutput`, `ScreenParseProviderAdapter`, `TrustedProviderAdapterRegistry`, `ShadowProviderRuntime.invoke(...)`, and sealed `provider_runtime_receipt_v1` refs.

- [ ] Write failing tests for a closed receipt schema, trusted registry lookup, exact stored-context resolution, Shadow/local-only enforcement, capture hash/size validation, deterministic idempotence, and non-authorizing successful/failed results.
- [ ] Run `uv run pytest tests/test_uei_v1_provider_runtime.py -q` and confirm failures are caused by missing runtime interfaces/schema.
- [ ] Implement the minimal pure runtime with an injected deterministic fake adapter. Do not import provider modules from the UEI package initializer.
- [ ] Run the focused test until green, then run `tests/test_uei_v1_schemas.py`, `tests/test_uei_v1_store.py`, `tests/test_uei_v1_registry.py`, and `tests/test_uei_v1_fail_closed.py` once.
- [ ] Do not commit; record RED/GREEN evidence in the local SDD ledger.

### Task 2: Bounded local worker and OmniParser Shadow adapter

**Files:**
- Create: `app/learn/recognition/uei/omniparser_shadow_adapter.py`
- Create: `scripts/run_uei_omniparser_shadow_worker.py`
- Create: `scripts/run_uei_omniparser_shadow_smoke.py`
- Create: `tests/test_uei_v1_omniparser_shadow_adapter.py`
- Modify only if required: `configs/model_profiles/learn_mode_omniparser_v2.json`

**Interfaces:**
- Consumes: Task 1 adapter protocol and trusted capture lease; existing pinned loader/normalizer behavior from `scripts/run_omniparser_learn_smoke.py` and `app/learn/recognition/omniparser_provider.py`.
- Produces: `OmniParserShadowAdapter` and a privacy-safe smoke report with cold/warm latency, bounded resource metrics, item counts, receipt/result refs, and cleanup proof.

- [ ] Write failing tests for fixed trusted configuration, no caller-controlled command/path/options, offline environment, timeout/process-tree termination, output byte/item limits, malformed/secret/lineage-mismatched worker output, resource rejection before spawn, and cleanup.
- [ ] Run the focused tests and confirm the adapter/worker interfaces are missing.
- [ ] Implement a subprocess adapter using a fresh process group, restricted temporary exchange, fixed trusted paths, bounded output, and explicit cleanup. Keep the existing contact-sheet benchmark unchanged.
- [ ] Run the fake-worker tests until green.
- [ ] Run one pinned real offline smoke on a synthetic privacy-safe screenshot: one cold run and at least three warm runs. Verify process exit, resource release, no temp residue, and sealed result/receipt refs.
- [ ] Do not commit; preserve exact commands, metrics, hashes, and limitations in the smoke report.

### Task 3: Learning Draft immutable-ref projection and panel review

**Files:**
- Create: `app/learn/recognition/uei/learning_shadow.py`
- Modify: `app/learn/workflow_tasks/recognition.py`
- Modify: `app/learn/draft_review.py`
- Modify: `app/api/panel.py`
- Modify: `app/web_panel/index.html`
- Modify: `app/web_panel/panel.js`
- Test: `tests/test_learning_draft_review.py`
- Test: `tests/test_web_panel_route.py`
- Create: `tests/js/uei_shadow_provider_summary.test.cjs`

**Interfaces:**
- Consumes: exact immutable `uei_shadow_result_ref` and the fixed server-owned shadow store.
- Produces: `uei_shadow_provider_summary_v1` in Learning Draft `page_details` and a read-only panel rendering.

- [ ] Write failing Python tests for success/failed summaries, fixed-store ref verification, corrupted/missing ref, cached-summary rejection on reload, capture mismatch, and absence from regions/action templates/grounding candidates.
- [ ] Write failing JS tests for compact rendering, no item/coordinate/action exposure, source-change clear, load-failure clear, and stale-response protection.
- [ ] Implement the smallest server adapter and renderer. Do not add a provider-run button or a public path/raw-payload endpoint.
- [ ] Run the focused Python and JS tests until green; run the existing Learning Draft provider-summary and panel route suites once.
- [ ] Do not commit; record the verified lifecycle and remaining non-goals.

### Task 4: Integration, documentation, privacy, and final gate

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`
- Modify: `tests/test_uei_v1_static_conformance.py`
- Create: `.superpowers/sdd/2026-08-21-uei-provider-shadow-runtime/progress.md`

**Interfaces:**
- Consumes: Tasks 1-3 verified runtime, real smoke report, and panel summary.
- Produces: one auditable M2 closeout with explicit Shadow/non-authorization limitations.

- [ ] Update docs from “no provider/panel integration” to the exact verified boundary: controlled local Shadow provider execution and read-only panel summary, with no capture/network/GUI/grounding/replay/action/Execute integration.
- [ ] Run the combined UEI M1+M2, OmniParser provider, Learning Draft, panel route, and JS summary suites once.
- [ ] Run `py_compile`, UTF-8/U+FFFD, schema parsing, `git diff --check`, worker-process/temp cleanup, and change-scope sensitive-data scans.
- [ ] Ask one independent reviewer to inspect runtime identity, subprocess/resource cleanup, privacy, lifecycle invalidation, and authorization isolation. Fix only concrete Critical/Important defects, then rerun the affected focused tests and one final combined gate.
- [ ] Leave all work uncommitted and unpushed unless the user explicitly requests Git publication.
