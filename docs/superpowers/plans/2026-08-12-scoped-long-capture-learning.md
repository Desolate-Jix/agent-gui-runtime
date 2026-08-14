# Scoped Long Capture Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Learn Mode 面板中加入普通截图与人工确认的区域长截图，使长内容形成 Agent 可读、可审核、可复现的学习证据，并在执行时继续使用当前截图重新定位。

**Architecture:** 面板负责编排已有 `/state/capture_window` 与带 Gate/Trace 的 `/action/scroll`，不会建立第二条真实滚动通道。新 Learn 模块只负责分段截图去重、重叠估计、拼接和 manifest；拼接图用于理解与人工审核，原始 segment 与每次滚动证据用于审计。执行模式不得直接使用长截图坐标，而是每次滚动后重新 observe 和 grounding。

**Tech Stack:** Python 3.11、FastAPI、Pillow、HTML/CSS/JavaScript、pytest、Node test runner、Windows GUI Operation/Gate/Trace。

## Global Constraints

- 长截图仅是学习与审核证据，不是执行坐标授权。
- 所有真实滚动必须复用 `/action/scroll` 的 Gate、scroll scope、effect validation 和 Trace。
- 每个 segment 必须保留截图路径、SHA-256、viewport、ROI、顺序和来源滚动 Trace。
- `scroll_dispatch_success` 与 `scroll_effect_success` 必须分开；没有内容变化不得继续伪造新 segment。
- wrong scope、blocked surface、重复帧、达到底部、达到上限必须形成不同停止原因。
- 原始 segment 永不被 composite 替代；拼接失败时仍保存可审核的 segment 序列。
- 模型可以推荐 `normal` 或 `scoped_long`，但首版由人工确认或覆盖模式、ROI 和上限。
- 未审核长截图产物不得标记为 `agent_usable`。
- 执行模式继续遵守 `observe -> Agent -> Gate -> Operation -> Trace -> observe`。
- final submit、send、complete、confirm、payment 保持硬阻断。
- 不增加 SEEK 名称、固定坐标或网站专用长截图规则。

---

### Task 1: Segment manifest and deterministic stitcher

**Files:**
- Create: `app/learn/scoped_capture.py`
- Create: `tests/test_scoped_capture.py`

**Interfaces:**
- Consumes: ordered segment image paths plus ROI, viewport, scroll Trace references and stop reason.
- Produces: `build_scoped_capture_artifact(...) -> dict[str, Any]` with `contract_version=scoped_learning_capture_v1`, segment checksums, duplicate classification, overlap evidence, composite path and completeness state.

- [ ] Add failing tests for identical-frame dedupe, deterministic overlap stitching, missing/unreadable segment rejection, segment preservation, and `reached_bottom` versus `max_captures` completeness.
- [ ] Run `uv run pytest tests/test_scoped_capture.py -q` and confirm the new tests fail before implementation.
- [ ] Implement immutable input validation, SHA-256 generation, grayscale overlap matching, deterministic composite generation and UTF-8 JSON manifest writing.
- [ ] Run `uv run pytest tests/test_scoped_capture.py -q` until all tests pass.

### Task 2: Panel composition API

**Files:**
- Modify: `app/api/panel.py`
- Test: `tests/test_web_panel_route.py`

**Interfaces:**
- Consumes: only screenshot paths under managed artifact roots plus capture metadata.
- Produces: `POST /panel/compose_scoped_learning_capture` returning the manifest and composite path; no scrolling or clicking occurs in this route.

- [ ] Add failing route tests for valid composition, path traversal rejection, missing segment rejection and structured error responses.
- [ ] Implement the request model and route using `build_scoped_capture_artifact`.
- [ ] Run the focused route tests and `uv run python -m py_compile app\learn\scoped_capture.py app\api\panel.py`.

### Task 3: Learn Mode panel capture selector and controlled sequence

**Files:**
- Modify: `app/web_panel/index.html`
- Modify: `app/web_panel/panel.js`
- Modify: `app/web_panel/panel.css`
- Test: `tests/test_web_panel_route.py`
- Test: `tests/js/learning_workflow_review.test.cjs`

**Interfaces:**
- Consumes: bound window, capture mode, human-confirmed ROI, segment limit, `/state/capture_window`, `/action/scroll`, and composition API.
- Produces: visible progress, cancellable sequence, segment list, stop reason, composite preview and selected learning image path.

- [ ] Add `普通截图` / `区域长截图` selector, model recommendation display, human confirmation, ROI selection, max segments and cancel controls.
- [ ] For long capture, capture segment zero, call `/action/scroll` with the selected scope, require effect evidence, capture the next segment, and stop on duplicate/no effect/wrong scope/reached bottom/limit/cancel.
- [ ] Compose accepted segments, select the composite as Learn input, retain raw segment/Trace links, and show which stage is running.
- [ ] Verify failed or cancelled capture never starts model learning automatically.
- [ ] Run focused Python and Node panel tests.

### Task 4: Agent-readable evidence projection and review UI

**Files:**
- Modify: `app/learn/agent_evidence.py`
- Modify: `app/learn/draft_review.py`
- Modify: `app/web_panel/learning_workflow_review.js`
- Test: `tests/test_agent_evidence.py`
- Test: `tests/test_learning_draft_review.py`
- Test: `tests/js/learning_workflow_review.test.cjs`

**Interfaces:**
- Consumes: scoped capture manifest and human-reviewed regions.
- Produces: `capture_policy`, `content_completeness`, segment provenance, semantic region purpose, read strategy and explicit `historical_coordinates_are_priors=true`.

- [ ] Add tests proving composite coordinates cannot become runtime authorization and missing/low-confidence capture evidence forces review.
- [ ] Project capture policy and completeness into Agent evidence without storing stale dynamic values as current facts.
- [ ] Render composite plus segment strip, stop reason and completeness state in the existing review surface.
- [ ] Run focused learning evidence and panel tests.

### Task 5: Real panel smoke and screenshot supervision

**Files:**
- Generate: `artifacts/learning-runs/<run_id>/scoped-capture/`
- Generate: `logs/smoke/scoped_learning_capture_<timestamp>/`
- Test: `tests/test_runtime_contracts.py`

**Interfaces:**
- Consumes: a real bound window with a scrollable region.
- Produces: original screenshot, numbered/boxed screenshot, segment sequence, composite, manifest, Gate/Trace evidence and a reviewed learning asset.

- [ ] Start the minimum runtime services and verify `/health`.
- [ ] Use the actual panel to bind, select a scrollable region, run scoped long capture and inspect every segment before accepting the composite.
- [ ] Compare original, scoped segment sequence and final composite; reject empty/loading/stale screenshots.
- [ ] Use the panel editor to make one human correction and confirm save-refresh updates the visible evidence.
- [ ] Confirm no click, fill or submit happened during Learn capture.

### Task 6: SEEK workflow integration and no-submit verification

**Files:**
- Update: `docs/superpowers/plans/2026-08-11-seek-learn-review-execute.md`
- Generate: reviewed SEEK list/detail/application interface assets and one reviewed workflow.
- Modify: `README.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`

**Interfaces:**
- Consumes: normal screenshots for finite surfaces and scoped long screenshots for list/detail/form content requiring completeness.
- Produces: one multi-interface reviewed workflow that the Agent can read and traverse through the gated execution chain to a safe stop before final submit.

- [ ] Relearn and human-review list, detail and application surfaces through the panel, choosing capture mode per surface.
- [ ] Connect reviewed interfaces with source control, semantic action, target interface and verification rule.
- [ ] Dry-run every edge, then execute only low-risk navigation with fresh observation after every action/scroll.
- [ ] Verify long-reading state, target-state transitions, blocker handling and final-submit safe stop.
- [ ] Run targeted Gate, Trace, panel, reviewed-memory, workflow and final-submit regression tests.
- [ ] Document automatic output, human corrections, executed actions, remaining limitations and the exact artifact/Trace paths.

### 2026-08-12 Task 5 compose-blocker checkpoint

- [x] Reproduce the real-size overlap estimator stall and classify it in the common `app/learn/scoped_capture.py` layer.
- [x] Add a 2048x1046 synthetic TDD regression with a loose `<20 s` composition budget; observe RED at `75.297 s`.
- [x] Add deterministic row-digest candidate filtering while retaining full-resolution RGB and informative-content verification before any accepted overlap.
- [x] Run `tests/test_scoped_capture.py`, scoped panel-route tests, and the Learning workflow JavaScript suite.
- [x] Compose the four captured Navigation Branching Lab ROI files into `artifacts/learning-captures/task5-overlap-smoke-optimized/` in `0.338 s` with `artifact_is_authorization=false`.
- [ ] Repeat the same compose path through the real panel request and visually accept or reject the resulting composite; this remains Task 5 supervision work for the main Agent.
