# General UI Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a hierarchy-based, conflict-resolved, cross-interface Learning Mode recognition system that is suitable for a truthful visual demonstration.

**Architecture:** Add focused hierarchy and ownership modules beside the existing two-stage recognizer. Keep Stage1/Stage2 geometry generation intact, convert accepted results into a validated hierarchy, expose audit evidence to page details and the panel, then expand the fixed benchmark to diverse surfaces.

**Tech Stack:** Python 3.11, FastAPI/Pydantic, Pillow/OpenCV review artifacts, vanilla JavaScript/CSS panel, pytest.

## Global Constraints

- All outputs are display/review only and do not authorize Execute.
- Do not add application names, application text, or fixed production coordinates to shared recognition rules.
- Use UTF-8 for Chinese text and JSON with `ensure_ascii=False`.
- Every behavior change follows red-green TDD and same-source replay verification.
- Models remain off unless the user explicitly approves a model run.

---

### Task 1: UIHierarchyGraph Contract

**Files:**
- Create: `app/learn/ui_hierarchy.py`
- Modify: `app/learn/recognition/two_stage.py`
- Test: `tests/test_ui_hierarchy.py`

**Interfaces:**
- Consumes: `build_ui_hierarchy_graph(structure_regions, numbered_regions, screen_size)`.
- Produces: `ui_hierarchy_graph_v1` with nodes, edges, validation, metrics, and safety flags.

- [ ] Write failing tests for unique parent, containment, empty structural lanes, deterministic IDs, and display-only safety.
- [ ] Run `uv run pytest tests/test_ui_hierarchy.py -q` and confirm failures describe the missing contract.
- [ ] Implement typed normalization helpers and hierarchy construction.
- [ ] Attach `ui_hierarchy` to `build_two_stage_screen_understanding` output.
- [ ] Run hierarchy tests and `tests/test_learn_recognition_pipeline.py`.

### Task 2: Recognition Ownership Resolver

**Files:**
- Create: `app/learn/recognition/ownership.py`
- Modify: `app/learn/recognition/two_stage.py`
- Test: `tests/test_recognition_ownership.py`

**Interfaces:**
- Consumes: semantic group claims with role, source, member item IDs, bbox, and evidence.
- Produces: accepted claims, rejected claims, conflict audit, and source-item owner map.

- [ ] Write failing tests for list-vs-text-tile, visual-card-vs-inferred-card, unrelated nested groups, and deterministic tie rejection.
- [ ] Implement evidence/semantic precedence without application-specific rules.
- [ ] Replace `_suppress_inferred_text_tiles_claimed_by_lists` with the shared resolver.
- [ ] Add ownership audit to each Stage2 region and hierarchy validation.
- [ ] Replay Python, Apple Music, and Windows Settings and compare protected metrics.

### Task 3: Page Details and Learning Draft Integration

**Files:**
- Modify: `scripts/build_learn_page_detail_candidate.py`
- Modify: `app/learn/draft_review.py`
- Modify: `app/api/panel.py`
- Test: `tests/test_learn_page_detail_candidate.py`
- Test: `tests/test_learning_draft_review.py`

**Interfaces:**
- Consumes: `ui_hierarchy_graph_v1` and ownership audit.
- Produces: hierarchy-aware page-detail sections and learning-draft review payload.

- [ ] Write failing tests proving page details follow hierarchy order instead of independent bbox guesses.
- [ ] Add hierarchy summary, ownership audit, unresolved review queue, and artifact paths.
- [ ] Preserve compatibility for old drafts without hierarchy data.
- [ ] Verify reviewed drafts remain non-executable.

### Task 4: Read-only Panel Hierarchy Viewer

**Files:**
- Modify: `app/web_panel/index.html`
- Modify: `app/web_panel/panel.js`
- Modify: `app/web_panel/panel.css`
- Test: `tests/test_web_panel_route.py`

**Interfaces:**
- Consumes: hierarchy-aware learning-draft review payload.
- Produces: selectable hierarchy tree, bbox highlight, evidence inspector, and conflict summary.

- [ ] Add route/markup tests for hierarchy and conflict containers.
- [ ] Render six hierarchy levels with compact indentation and status icons.
- [ ] Link node selection to the existing image inspector without enabling clicks on the target app.
- [ ] Add Chinese and English labels.
- [ ] Verify desktop and constrained-width screenshots with the local panel.

### Task 5: Diverse Hierarchy Benchmark

**Files:**
- Create: `scripts/run_learning_hierarchy_benchmark.py`
- Create: `artifacts/benchmarks/learning_hierarchy_manifest_v1.json`
- Test: `tests/test_learning_hierarchy_benchmark.py`

**Interfaces:**
- Consumes: fixed replay reports, screenshots, overlays, hierarchy artifacts, and golden annotations.
- Produces: per-layer metrics, invalid fixtures, failure taxonomy, and contact sheets.

- [ ] Implement manifest checksum and required-evidence validation.
- [ ] Add separate metrics for structure, components, relationships, containment, and duplicate ownership.
- [ ] Add 8–12 diverse valid/failing cases from existing matched traces or deterministic fixtures.
- [ ] Ensure invalid/stale cases do not enter denominators.
- [ ] Generate one original/Stage1/final/hierarchy review sheet per case.

### Task 6: Showcase Readiness Audit

**Files:**
- Create: `scripts/check_learning_hierarchy_showcase_readiness.py`
- Modify: `README.md`
- Modify: `PROJECT_SUMMARY.md`
- Modify: `CURRENT_STATE.md`
- Modify: `ARCHITECTURE.md`
- Test: `tests/test_learning_hierarchy_showcase_readiness.py`

**Interfaces:**
- Consumes: hierarchy benchmark report and panel smoke evidence.
- Produces: `ready`, `needs_review`, or `blocked` with exact evidence paths and limitations.

- [ ] Require at least 8 valid diverse fixtures and explicit failure samples.
- [ ] Require zero unsafe actions and zero Runtime PathGraph promotion.
- [ ] Require panel hierarchy render evidence and known-limitations text.
- [ ] Run targeted tests, full tests, benchmark, and panel smoke.
- [ ] Perform final requirement-by-requirement audit before marking the project goal complete.
