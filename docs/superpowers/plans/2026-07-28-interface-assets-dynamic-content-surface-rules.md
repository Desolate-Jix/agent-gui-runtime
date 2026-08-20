# Interface Assets, Dynamic Content, And Surface Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn corrected single-screen learning results into application-scoped interface assets that can be freely linked, compiled for Agent decisions, safely test-run, and improved by validated browser-video and media class rules.

**Architecture:** Keep reviewed single-interface evidence canonical, store transitions separately, and derive the software-level graph and Agent context from references. Extend the existing host/content surface adapter chain rather than introducing app-specific recognizers; class rules remain evidence-scoped, regression-gated, and non-authorizing.

**Tech Stack:** Python 3.11, FastAPI, vanilla JavaScript, HTML/CSS/Canvas, pytest, Node test runner.

## Global Constraints

- Workflow/PathGraph is reusable memory, not execution authorization.
- Dynamic values must come from the latest capture and must not be frozen into interface assets.
- Historical click points are forbidden.
- Agent suggestions remain editable and do not bypass human review.
- Every real action still follows observe → Agent → Gate → Operation → Trace → observe.
- Surface adapters may change candidate policy but may not generate final click geometry or loosen Gate.
- Final submit, send, confirm, delete, and payment remain hard-blocked.

---

### Task 1: Canonical Single-Interface Asset Contract

**Files:**
- Create: `app/learn/interface_assets.py`
- Test: `tests/test_interface_assets.py`
- Modify: `app/learn/interface_workflow_review.py`

**Interfaces:**
- Produces `build_single_interface_asset(review: dict, *, application_identity: dict) -> dict`.
- Produces `save_single_interface_asset(asset: dict, *, project_root: Path) -> dict`.
- Produces `load_application_interface_library(application_identity_key: str, *, project_root: Path) -> dict`.

- [ ] Write failing tests for independent evidence ownership, application grouping, stable IDs, missing overlay status, and runtime coordinate removal.
- [ ] Run `uv run pytest tests/test_interface_assets.py -q` and confirm failures describe the missing contract.
- [ ] Implement the minimal asset store under `artifacts/interface-assets/<application-key>/interfaces/`.
- [ ] Add a compatibility projector from existing workflow nodes without changing old API shapes.
- [ ] Rerun the focused tests until green.

### Task 2: Fixed And Dynamic Content Semantics

**Files:**
- Modify: `app/learn/interface_assets.py`
- Modify: `app/agent/reviewed_interface_memory.py`
- Test: `tests/test_interface_assets.py`
- Modify: `tests/test_reviewed_interface_memory.py`

**Interfaces:**
- Adds `content_behavior`, `agent_usage`, `read_policy`, and `agent_description`.
- Produces `compile_agent_interface_graph_context(...) -> dict`.

- [ ] Write failing tests proving historical dynamic text is excluded from current decision values.
- [ ] Write failing tests for fixed anchors, on-demand dynamic slots, sensitive dynamic slots, and invalid enum rejection.
- [ ] Implement normalization and compilation.
- [ ] Verify Agent context contains schema/meaning but only caller-supplied latest observations contain current values.
- [ ] Rerun focused memory and asset tests.

### Task 3: Editable Interface Transitions

**Files:**
- Modify: `app/learn/interface_assets.py`
- Modify: `app/learn/interface_workflow_review.py`
- Modify: `app/web_panel/learning_workflow_review.js`
- Test: `tests/test_interface_assets.py`
- Modify: `tests/js/learning_workflow_review.test.cjs`

**Interfaces:**
- Produces `save_interface_transition(...)`.
- Produces application graph from interface and transition references.

- [ ] Write failing tests for one-to-many transitions, loops, target-control ownership, Agent-suggested edges, human confirmation, and unknown references.
- [ ] Implement transition storage and graph projection.
- [ ] Add panel controls for selecting source control, operation, and target interface.
- [ ] Ensure save refreshes the exact interface and graph revision without stale UI.
- [ ] Rerun Python and JavaScript tests.

### Task 4: Execute-Style Learning Graph And Workbench

**Files:**
- Modify: `app/web_panel/interface_workflow_graph.js`
- Modify: `app/web_panel/learning_workflow_review.js`
- Modify: `app/web_panel/panel.css`
- Modify: `app/web_panel/index.html`
- Modify: `tests/js/interface_workflow_graph.test.cjs`
- Modify: `tests/js/learning_workflow_review.test.cjs`

**Interfaces:**
- Interface nodes render screenshot thumbnails and review status.
- Control ports render outgoing operations.
- Selected nodes atomically switch evidence and editor state.

- [ ] Write failing layout tests for branching, cycles, screenshot cards, focused subgraphs, and stable node dimensions.
- [ ] Implement a quiet three-column workbench with 4/8px spacing, neutral surfaces, visible focus, and no nested decorative cards.
- [ ] Reuse Execute Mode pan/zoom/selection behavior without importing execution authorization state.
- [ ] Add loading, empty, missing-evidence, save-error, and reduced-motion states.
- [ ] Run Node tests and a browser screenshot smoke at desktop and narrow widths.

### Task 5: Agent Safe Transition Test

**Files:**
- Modify: `app/agent/reviewed_interface_memory.py`
- Modify: `app/api/action.py`
- Modify: `app/api/memory.py`
- Test: `tests/test_reviewed_interface_memory_execution.py`

**Interfaces:**
- Uses reviewed interface graph context to propose one low-risk action.
- Reuses the gated recognition-plan API for execution.

- [ ] Write failing tests for fresh capture, fresh grounding, target control resolution, Gate rejection, post-action interface verification, and feedback recording.
- [ ] Implement one-step dry-run first.
- [ ] Add human-confirmed low-risk real-click verification through the existing gated API only.
- [ ] Confirm dangerous action vocabulary remains blocked.
- [ ] Rerun execution-memory and pre-click safety tests.

### Task 6: Employment Workflow Surface Adapter

**Files:**
- Modify: `app/learn/recognition/interface_classification.py`
- Modify: `app/learn/recognition/surface_adapters.py`
- Modify: `app/learn/recognition/two_stage.py`
- Modify: `scripts/run_surface_adapter_benchmark.py`
- Modify: `tests/test_learning_surface_adapters.py`
- Modify: `tests/test_surface_adapter_benchmark.py`
- Add fixtures under: `tests/fixtures/surface_adapter_protocol/`

**Interfaces:**
- Adds one content adapter `employment_workflow`.
- Classifies `job_search_results`, `job_detail`, `application_form`, `application_review`, `mixed`, and `ambiguous`.
- Keeps `browser` as an independent host adapter.

- [x] Write failing classifier/adapter tests for job results, job detail plus application drawer, application form, application review, ordinary-form negatives, and ecommerce negatives.
- [x] Add correlated model and current-inventory evidence requirements without using SEEK domains or application names.
- [x] Compile the adapter policy into Stage2 read-only policy without writing final geometry or authorizing final submit.
- [ ] Benchmark generic versus selected adapter on dev and untouched holdout fixtures.
- [ ] Reject activation when the selected adapter improves one sample but degrades unrelated old samples.

### Task 7: Regression, UI Smoke, And Documentation

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Produces an evidence-backed checkpoint report, not a single advertised accuracy.

- [ ] Run focused Python and Node test suites for Tasks 1–6.
- [ ] Run the nine-interface regression plus multiple employment-site and non-employment counterexamples; report each layer separately.
- [ ] Exercise panel history load, interface switching, box edits, dynamic classification, edge creation, save refresh, and graph selection.
- [ ] Verify no live submit, no unsafe click, no historical coordinate reuse, and no candidate rule auto-activation.
- [ ] Synchronize behavior, architecture, limitations, and next work in project documentation.
