# Learning Draft Overlap Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce overlapping boxes in the learning interface editor without deleting evidence or changing saved review semantics.

**Architecture:** Add a pure display projection to the existing learning-draft editor module. The panel renders that projection in compact mode, while all edit operations and saves continue to use the complete editor state.

**Tech Stack:** Browser JavaScript, HTML, CSS, Node.js built-in test runner, pytest.

## Global Constraints

- Compact display must not mutate source items or exported review operations.
- Actions, dangerous controls, manually edited boxes, selected boxes, and ambiguous overlaps remain visible.
- Execute, Gate, Trace, PathGraph, and final-submit safety behavior remain unchanged.
- Chinese UI text remains UTF-8.

---

### Task 1: Pure Display Projection

**Files:**
- Modify: `app/web_panel/learning_draft_editor.js`
- Test: `tests/js/learning_draft_editor.test.cjs`

**Interfaces:**
- Produces: `buildLearningDraftDisplayProjection(items, options)`
- Produces: `createLearningDraftEditorState().editedKeys()`

- [x] Add failing tests for safe containment grouping, ambiguous overlap, action safety, manual/selected visibility, and full mode.
- [x] Run `node --test tests/js/learning_draft_editor.test.cjs` and confirm failures are caused by the missing projection.
- [x] Implement the minimal pure projection and edited-key exposure.
- [x] Rerun the Node test file until it passes.

### Task 2: Compact Editor Interaction

**Files:**
- Modify: `app/web_panel/panel.js`
- Modify: `app/web_panel/index.html`
- Modify: `app/web_panel/panel.css`
- Test: `tests/js/learning_draft_editor.test.cjs`
- Test: `tests/test_web_panel_route.py`

**Interfaces:**
- Consumes: `buildLearningDraftDisplayProjection(items, options)`
- Produces: compact/all toggle and an overlap-member selector.

- [x] Add failing static integration assertions for the toggle, projection call, and overlap selector.
- [x] Run the narrow Node and panel route tests and confirm the new assertions fail.
- [x] Render projected visible boxes, `+N`, and member selection without changing drag/add behavior.
- [x] Add compact/all styling and update asset versions.
- [x] Rerun the narrow tests until they pass.

### Task 3: Runtime Verification And Documentation

**Files:**
- Modify: `README.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Verifies: dense editor presentation only; no execution authorization.

- [x] Run `uv run pytest tests/test_learning_draft_editor_js.py tests/test_web_panel_route.py -q`.
- [x] Run the relevant broader panel tests.
- [x] Open the local panel, load a dense reviewed interface, toggle both modes, and select a hidden member. Save/export equivalence is covered by the pure-state regression test without modifying a user artifact.
- [x] Confirm no Execute, Gate, Trace, PathGraph, or final-submit behavior changed.
- [x] Synchronize the public behavior and remaining limitation in documentation.
