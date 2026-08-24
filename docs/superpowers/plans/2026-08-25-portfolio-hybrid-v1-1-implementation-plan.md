# Portfolio Hybrid v1.1 Learn / Review Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and prove a no-action Learn/Review cascade that seals one capture, runs Omni candidate discovery, Qwen candidate-ID semantic binding, deterministic fusion, bounded VISTA refinement, Human Review, save/fresh-process reload, deterministic compile and single publish without changing Runtime execution authority.

**Architecture:** Add a focused `app.learn.hybrid` package and four managed Learn task kinds inside the existing workflow worker/service boundary. The new path reuses UEI storage, Omni's trusted adapter/runtime, the existing model-server lifecycle, VISTA calibration primitives, Large Review, workflow persistence, compiler and CAS publisher; it does not create a parallel Runtime. The incumbent Learn path remains available until a sealed untouched holdout proves the versioned promotion gate.

**Tech Stack:** Python 3.11, FastAPI/Pydantic-compatible existing request models, pytest, JavaScript panel tests, UEI CAS, Qwen3-VL, OmniParser v2, VISTA local grounding, Windows process/HWND inventory and lifecycle cleanup.

**Spec:** `docs/superpowers/specs/2026-08-25-portfolio-hybrid-v1-1-learn-review-design.md`

## Global Constraints

- Portfolio v1 Runtime, Gate, Receipt, Safe Stop and bounded Quick Apply proof are frozen; no Runtime redesign or new execution authority.
- The only model order is `Capture → Omni → Qwen → deterministic fusion → bounded VISTA → Human Review`.
- Models produce non-authorizing proposals only: `artifact_is_authorization=false`, `execute_binding_enabled=false`.
- All provider outputs bind the same immutable `capture_lineage_ref`, artifact SHA, dimensions and coordinate space; conflicts fail closed.
- Raw provider results and `bbox_original` are immutable; filtering, review deletion and reboxing are append-only decisions/derived geometry.
- Only `BOUND` candidates with exact current lineage may enter VISTA; the returned point must be inside both candidate bbox and ROI without clipping.
- Hybrid cannot become the default Learn path until the sealed holdout passes the versioned benefit/coverage gate with automatic `wrong_target=0`.
- No real click, fill, submit, scroll, keypress/type, navigation click, focus-driven target action or GUI close action is allowed.
- Unknown-UI proof creates only test-owned interfaces. Cleanup uses process/service lifecycle, verifies all owned PID/HWNDs gone, and preserves every pre-existing user interface.
- Every slice follows TDD, focused verification, independent review and an explicit-path commit. Do not stage `tests/test_agent_runtime_actual_adapter_portfolio_v1.py`; it predates this plan.
- Do not push automatically.
- Preserve UTF-8 Chinese content and existing line endings in modified files.

## Dependency Graph

```text
Task 1 contracts/config
  ├─→ Task 2 capture sealing
  ├─→ Task 3A recorded Omni review vertical
  ├─→ Task 3 Omni managed discovery
  └─→ Task 4 Qwen binding
Tasks 1–3A → first working vertical slice
Tasks 2–4 → Task 5 deterministic fusion
Tasks 3A–5 → Task 5A sealed pre-VISTA baseline
Task 5A → Task 5B immutable corpus/Gold seal
Tasks 3–5B → Task 6 managed orchestration
Tasks 5–6 → Task 7 bounded VISTA
Task 7 → Task 7A GPU lifecycle stability
Tasks 5–7A → Task 8 Large Review
Task 8 → Task 9 persistence/restart/compile/publish
Tasks 5A–9 → Task 10 final benchmark
Tasks 6–10 → Task 11 unknown-UI no-action acceptance
Tasks 1–11 → Task 12 regression/docs/freeze
```

## File Structure

New production files have one responsibility each:

- `app/learn/hybrid/contracts.py` — closed validators, stable IDs and non-authorizing invariants.
- `app/learn/hybrid/capture.py` — server-owned capture/lineage sealing and exact-context validation.
- `app/learn/hybrid/omni_candidates.py` — immutable provider-result/source-item candidate ledger.
- `app/learn/hybrid/omni_discovery.py` — Omni invocation and canonical candidate inventory.
- `app/learn/hybrid/qwen_binding.py` — candidate-ID-closed Qwen prompt/output handling.
- `app/learn/hybrid/fusion.py` — deterministic fusion and versioned decision table.
- `app/learn/hybrid/vista_refinement.py` — eligible ROI requests and point validation.
- `app/learn/hybrid/review_projection.py` — proposal/review separation and Large Review projection.
- `app/learn/hybrid/benchmark.py` — scorer-only metrics and sealed gate evaluation.
- `app/learn/hybrid/acceptance.py` — test-owned interface inventory, zero-action audit and cleanup proof.
- `configs/learn_hybrid_v1_1.json` — fusion rules, model order, rollout mode and provider IDs.
- `configs/benchmarks/portfolio_hybrid_v1_1_gate.json` — predeclared release thresholds.

---

### Task 1: Freeze Hybrid contracts, stable identities and versioned rules

**Files:**
- Create: `app/learn/hybrid/__init__.py`
- Create: `app/learn/hybrid/contracts.py`
- Create: `configs/learn_hybrid_v1_1.json`
- Create: `tests/test_learn_hybrid_contracts.py`

**Interfaces:**
- Produces: `load_hybrid_config(project_root: Path) -> dict[str, Any]`.
- Produces: `stable_candidate_id(*, provider_result_ref: Mapping[str, str], source_item_id: str) -> str`.
- Produces: `validate_capture_identity(value: Mapping[str, Any]) -> dict[str, Any]`.
- Produces: `validate_omni_inventory(value)`, `validate_qwen_bindings(value)`, `validate_fusion_result(value)` and `validate_vista_proposals(value)`.
- Contract versions: `hybrid_capture_identity_v1`, `hybrid_omni_inventory_v1`, `hybrid_qwen_bindings_v1`, `hybrid_fusion_result_v1`, `hybrid_vista_proposals_v1`.

- [ ] **Step 1: Write RED contract tests.** Cover deterministic candidate IDs, duplicate/reused IDs, unknown Qwen IDs, geometry fields in Qwen output, non-BOUND VISTA eligibility, conflicting lineage refs, and all authorization flags.

```python
def test_qwen_binding_is_candidate_id_closed_and_cannot_replace_geometry():
    with pytest.raises(ValueError, match="unknown candidate_id"):
        validate_qwen_bindings(binding_fixture(candidate_id="foreign"), inventory_fixture())
    with pytest.raises(ValueError, match="geometry is forbidden"):
        validate_qwen_bindings(binding_fixture(extra={"bbox": [1, 2, 3, 4]}), inventory_fixture())
```

- [ ] **Step 2: Run RED.**

```powershell
uv run pytest -q tests/test_learn_hybrid_contracts.py
```

Expected: import failure for `app.learn.hybrid.contracts`.

- [ ] **Step 3: Implement closed validators and config.** Use explicit field sets, `deepcopy`, SHA-256 over canonical JSON, finite-number checks and canonical `capture_pixel_xyxy`. Require `artifact_sha256 == screenshot_sha256`. Independently verify that `capture_lineage_ref.content_sha256` hashes the immutable lineage object, then verify that the lineage object's artifact ref/SHA/dimensions resolve to the same screenshot bytes. The lineage-object hash is not an image hash and must not be forced equal to it.

```python
def stable_candidate_id(*, provider_result_ref: Mapping[str, str], source_item_id: str) -> str:
    payload = {"provider_result_ref": dict(provider_result_ref), "source_item_id": source_item_id}
    return "candidate/" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
```

Add a negative/positive pair proving a valid lineage-object hash may differ from the image SHA, while a lineage object that names a different artifact SHA is rejected.

- [ ] **Step 4: Run GREEN and syntax validation.**

```powershell
uv run pytest -q tests/test_learn_hybrid_contracts.py
uv run python -m py_compile app/learn/hybrid/contracts.py
```

- [ ] **Step 5: Review, sensitive scan and commit.**

```powershell
git add -- app/learn/hybrid/__init__.py app/learn/hybrid/contracts.py configs/learn_hybrid_v1_1.json tests/test_learn_hybrid_contracts.py
git diff --cached --check
git commit -m "feat(learn): add hybrid evidence contracts"
```

---

### Task 2: Seal one server-owned capture and same-envelope OCR/UIA context

**Files:**
- Create: `app/learn/hybrid/capture.py`
- Modify: `app/learn/recognition/uei/builtin_learning_projection.py`
- Modify: `app/learn/workflow_continuation.py`
- Create: `tests/test_learn_hybrid_capture.py`
- Test: `tests/test_learning_workflow_stage_execution.py`
- Test: `tests/test_uei_v1_provider_runtime.py`

**Interfaces:**
- Consumes: the server-adopted capture path returned by the existing capture service, current workflow revision and the pinned UIA/OCR snapshot from the same capture envelope.
- Produces: `seal_hybrid_capture_bundle(*, project_root, image_path, workflow_revision, window_binding, ocr_uia_context) -> HybridCaptureBundle` containing immutable UEI refs and no client-supplied provider payload.
- Produces: `load_and_verify_hybrid_capture_bundle(*, project_root, bundle_ref) -> dict`.

- [ ] **Step 1: Write RED lineage tests.** Prove one read of screenshot bytes, persisted `capture_lineage_ref`, exact SHA/dimensions, sealed OCR/UIA provenance, rejection of a client-forged path/ref, stale workflow revision, cross-capture provider result, conflicting valid refs and transform SHA mismatch.

```python
def test_conflicting_valid_lineage_refs_fail_closed(tmp_path):
    bundle = seal_fixture_capture(tmp_path)
    forged = deepcopy(bundle)
    forged["capture_lineage_ref"] = other_valid_lineage_ref(tmp_path)
    with pytest.raises(ValueError, match="capture lineage conflict"):
        load_and_verify_hybrid_capture_bundle(project_root=tmp_path, bundle_ref=store(forged))
```

- [ ] **Step 2: Run RED.**

```powershell
uv run pytest -q tests/test_learn_hybrid_capture.py tests/test_uei_v1_provider_runtime.py
```

- [ ] **Step 3: Implement by extracting/reusing server-owned sealing.** Do not accept raw Omni/Qwen data or arbitrary hash/path from the panel. Bind `affine_coordinate_transform_v1` source and target artifact SHA for every derived view.

- [ ] **Step 4: Run focused GREEN.**

```powershell
uv run pytest -q tests/test_learn_hybrid_capture.py tests/test_uei_v1_provider_runtime.py tests/test_learning_workflow_stage_execution.py -k "capture or lineage or screen_observe"
uv run python -m py_compile app/learn/hybrid/capture.py app/learn/workflow_continuation.py
```

- [ ] **Step 5: Commit one lineage slice.**

```powershell
git add -- app/learn/hybrid/capture.py app/learn/recognition/uei/builtin_learning_projection.py app/learn/workflow_continuation.py tests/test_learn_hybrid_capture.py tests/test_learning_workflow_stage_execution.py tests/test_uei_v1_provider_runtime.py
git commit -m "feat(learn): seal hybrid capture lineage"
```

---

### Task 3A: First vertical slice — recorded Omni ledger into existing Large Review

**Files:**
- Create: `app/learn/hybrid/omni_candidates.py`
- Create: `app/learn/hybrid/review_projection.py`
- Modify: `app/learn/recognition/uei/learning_shadow.py`
- Modify: `app/learn/draft_review.py`
- Create: `tests/test_learning_hybrid_vertical_slice.py`
- Modify: `tests/test_uei_provider_neutral_review.py`

**Interfaces:**
- Produces `build_omni_candidate_ledger(*, safe_result, capture_bundle) -> dict` with stable IDs and immutable `bbox_original`.
- Produces the first read-only `project_hybrid_review(...) -> dict` that the existing Large Review loader can display.
- This slice uses a recorded valid provider-safe UEI result, performs no model/GPU/GUI action, and proves `sealed capture → Omni candidate ledger → Large Review` end to end.

- [ ] **Step 1: Write RED vertical tests.** Assert stable IDs, exact lineage, raw provenance, original bbox, all candidate visibility and complete refusal of a cross-capture or displayed-image mismatch.

```python
def test_recorded_omni_candidates_project_into_large_review_without_authority(tmp_path):
    review = project_recorded_vertical_slice(tmp_path)
    assert review["candidates"][0]["candidate_id"].startswith("candidate/")
    assert review["candidates"][0]["bbox_original"] == [40, 20, 120, 52]
    assert review["artifact_is_authorization"] is False
    assert review["execute_binding_enabled"] is False
```

- [ ] **Step 2: Run RED.**

```powershell
uv run pytest -q tests/test_learning_hybrid_vertical_slice.py tests/test_uei_provider_neutral_review.py
```

- [ ] **Step 3: Implement only immutable ledger plus read-only projection.** Reuse UEI projection validation; do not invoke Omni and do not add edit semantics yet.

- [ ] **Step 4: Run GREEN and compile.**

```powershell
uv run pytest -q tests/test_learning_hybrid_vertical_slice.py tests/test_uei_provider_neutral_review.py
uv run python -m py_compile app/learn/hybrid/omni_candidates.py app/learn/hybrid/review_projection.py
```

- [ ] **Step 5: Commit the first working vertical slice.**

```powershell
git add -- app/learn/hybrid/omni_candidates.py app/learn/hybrid/review_projection.py app/learn/recognition/uei/learning_shadow.py app/learn/draft_review.py tests/test_learning_hybrid_vertical_slice.py tests/test_uei_provider_neutral_review.py
git commit -m "feat(learn): project immutable omni candidates into review"
```

---

### Task 3: Add cancellation-safe managed Omni discovery

**Files:**
- Create: `app/learn/hybrid/omni_discovery.py`
- Modify: `app/learn/hybrid/omni_candidates.py`
- Create: `app/learn/workflow_tasks/hybrid_omni.py`
- Modify: `app/learn/recognition/uei/provider_runtime.py`
- Modify: `app/learn/recognition/uei/provider_adapters.py`
- Modify: `app/learn/recognition/uei/omniparser_shadow_adapter.py`
- Modify: `app/learn/workflow_worker.py`
- Modify: `app/api/panel.py`
- Create: `tests/test_learn_hybrid_omni_discovery.py`
- Test: `tests/test_uei_v1_provider_runtime.py`
- Test: `tests/test_uei_v1_omniparser_shadow_adapter.py`
- Test: `tests/test_model_request_cancellation.py`
- Test: `tests/test_learning_workflow_stage_worker.py`
- Test: `tests/test_web_panel_route.py`

**Interfaces:**
- Adds managed task kind `panel_learning_hybrid_omni_discovery`.
- Extends internal adapter invocation with `cancellation_event: Event | None` without changing public UEI result contracts.
- Produces `run_hybrid_omni_discovery(payload, *, cancellation_event=None) -> dict` with sealed `hybrid_omni_inventory_v1`, provider result/receipt refs, duration and cleanup status, reusing the Task 3A immutable candidate ledger.

- [ ] **Step 1: Write RED tests.** Cover successful conversion, source order stability, raw bbox preservation, inactive reason rather than deletion, timeout, cancellation before spawn, cancellation during worker, child-tree termination, lease release, orphan absence, exact-capture mismatch and idempotent completed-claim recovery.

```python
def test_cancelled_omni_worker_releases_lease_and_leaves_no_child_process(tmp_path):
    event = threading.Event()
    adapter = blocking_adapter(tmp_path)
    invocation = start_invoke(adapter, event)
    event.set()
    result = invocation.join()
    assert result["cleanup_status"] == "clean"
    assert adapter.live_child_pids() == []
    assert not adapter.lease_path.exists()
```

- [ ] **Step 2: Run RED.**

```powershell
uv run pytest -q tests/test_learn_hybrid_omni_discovery.py tests/test_uei_v1_provider_runtime.py tests/test_uei_v1_omniparser_shadow_adapter.py tests/test_model_request_cancellation.py
```

- [ ] **Step 3: Implement cancellation propagation and managed task.** Use the existing trusted registry/profile and `ShadowProviderRuntime`; never import a benchmark script into production. Persist only revalidated provider-safe output.

- [ ] **Step 4: Run focused GREEN.**

```powershell
uv run pytest -q tests/test_learn_hybrid_omni_discovery.py tests/test_uei_v1_provider_runtime.py tests/test_uei_v1_omniparser_shadow_adapter.py tests/test_model_request_cancellation.py tests/test_learning_workflow_stage_worker.py tests/test_web_panel_route.py -k "omni or cancellation or task_kind"
uv run python -m py_compile app/learn/hybrid/omni_discovery.py app/learn/workflow_tasks/hybrid_omni.py app/learn/recognition/uei/provider_runtime.py app/learn/recognition/uei/omniparser_shadow_adapter.py app/learn/workflow_worker.py app/api/panel.py
```

- [ ] **Step 5: Commit.**

```powershell
git add -- app/learn/hybrid/omni_discovery.py app/learn/hybrid/omni_candidates.py app/learn/workflow_tasks/hybrid_omni.py app/learn/recognition/uei/provider_runtime.py app/learn/recognition/uei/provider_adapters.py app/learn/recognition/uei/omniparser_shadow_adapter.py app/learn/workflow_worker.py app/api/panel.py tests/test_learn_hybrid_omni_discovery.py tests/test_uei_v1_provider_runtime.py tests/test_uei_v1_omniparser_shadow_adapter.py tests/test_model_request_cancellation.py tests/test_learning_workflow_stage_worker.py tests/test_web_panel_route.py
git commit -m "feat(learn): run managed omni discovery"
```

---

### Task 4: Add candidate-ID-closed Qwen semantic binding

**Files:**
- Create: `app/learn/hybrid/qwen_binding.py`
- Create: `app/learn/workflow_tasks/hybrid_qwen.py`
- Modify: `app/core/model_server.py`
- Modify: `app/learn/workflow_worker.py`
- Modify: `app/api/panel.py`
- Create: `tests/test_learn_hybrid_qwen_binding.py`
- Test: `tests/test_learning_workflow_stage_worker.py`
- Test: `tests/test_model_request_cancellation.py`
- Test: `tests/test_web_panel_route.py`

**Interfaces:**
- Adds managed task kind `panel_learning_hybrid_qwen_binding`.
- Produces `build_qwen_binding_request(capture_bundle, omni_inventory) -> dict` with the canonical screenshot, closed candidate IDs/geometry and sealed same-capture OCR/UIA context.
- Produces `run_qwen_candidate_binding(payload, *, model_runner, cancellation_event=None) -> dict` returning `hybrid_qwen_bindings_v1`.
- The parser rejects unknown/duplicate IDs, geometry output, free-created candidates and unbound prose. A missing important element becomes `ORPHAN_SEMANTIC` with no fabricated Omni candidate.

- [ ] **Step 1: Write RED request/parser tests.** Include exact UTF-8 labels, same-capture UIA provenance, unknown ID, duplicate binding, two IDs for one semantic target, geometry injection, candidate omission, orphan semantic and model timeout/cancel.

```python
def test_qwen_output_cannot_inject_geometry_or_execution_authority():
    raw = {"bindings": [{"candidate_id": "candidate/abc", "bbox": [0, 0, 1, 1], "approved_to_click": True}]}
    with pytest.raises(ValueError, match="forbidden Qwen field"):
        parse_qwen_candidate_bindings(raw, inventory_fixture("candidate/abc"))
```

- [ ] **Step 2: Run RED.**

```powershell
uv run pytest -q tests/test_learn_hybrid_qwen_binding.py tests/test_learning_workflow_stage_worker.py -k "qwen or hybrid"
```

- [ ] **Step 3: Implement the smallest model-runner adapter.** Reuse existing Qwen server acquisition/cancellation; do not add another model server. Release Qwen after the binding artifact is sealed.

- [ ] **Step 4: Run GREEN.**

```powershell
uv run pytest -q tests/test_learn_hybrid_qwen_binding.py tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py tests/test_web_panel_route.py -k "qwen or hybrid or cancellation"
uv run python -m py_compile app/learn/hybrid/qwen_binding.py app/learn/workflow_tasks/hybrid_qwen.py
```

- [ ] **Step 5: Commit.**

```powershell
git add -- app/learn/hybrid/qwen_binding.py app/learn/workflow_tasks/hybrid_qwen.py app/core/model_server.py app/learn/workflow_worker.py app/api/panel.py tests/test_learn_hybrid_qwen_binding.py tests/test_learning_workflow_stage_worker.py tests/test_model_request_cancellation.py tests/test_web_panel_route.py
git commit -m "feat(learn): bind qwen semantics to omni candidates"
```

---

### Task 5: Implement deterministic fusion and review-required policy

**Files:**
- Create: `app/learn/hybrid/fusion.py`
- Create: `app/learn/workflow_tasks/hybrid_fusion.py`
- Modify: `app/learn/workflow_worker.py`
- Modify: `app/api/panel.py`
- Create: `tests/test_learn_hybrid_fusion.py`
- Test: `tests/test_learning_workflow_stage_worker.py`

**Interfaces:**
- Adds managed task kind `panel_learning_hybrid_fusion`.
- Produces `fuse_hybrid_candidates(*, config, capture_bundle, omni_inventory, qwen_bindings) -> dict`.
- The decision table maps only exact-lineage unique `BOUND` to `vista_eligible=true`; `AMBIGUOUS`, `CONFLICT`, `ORPHAN`, `LOW_CONFIDENCE`, `UNBOUND`, `CAPTURE_MISMATCH` all produce `REVIEW_REQUIRED`.
- UIA/OCR may corroborate or create conflict but cannot independently upgrade to `BOUND`.

- [ ] **Step 1: Write table-driven RED tests for every state and tie rule.** Assert candidate count is preserved, filtering records `active=false` plus reason, original geometry is byte-identical, result order is deterministic, and config SHA is included.

```python
@pytest.mark.parametrize("state", ["AMBIGUOUS", "CONFLICT", "ORPHAN", "LOW_CONFIDENCE", "UNBOUND", "CAPTURE_MISMATCH"])
def test_non_bound_states_are_never_vista_eligible(state):
    record = fuse_fixture(state=state)
    assert record["review_status"] == "REVIEW_REQUIRED"
    assert record["vista_eligible"] is False
```

- [ ] **Step 2: Run RED.**

```powershell
uv run pytest -q tests/test_learn_hybrid_fusion.py
```

- [ ] **Step 3: Implement pure deterministic fusion.** No model call, voting, confidence averaging or hidden threshold is permitted.

- [ ] **Step 4: Run GREEN and repeatability check.**

```powershell
uv run pytest -q tests/test_learn_hybrid_fusion.py tests/test_learning_workflow_stage_worker.py -k "hybrid or fusion"
uv run pytest -q tests/test_learn_hybrid_fusion.py --count=3
uv run python -m py_compile app/learn/hybrid/fusion.py app/learn/workflow_tasks/hybrid_fusion.py
```

If `pytest-repeat` is unavailable, run the first command three times without adding a dependency.

- [ ] **Step 5: Commit.**

```powershell
git add -- app/learn/hybrid/fusion.py app/learn/workflow_tasks/hybrid_fusion.py app/learn/workflow_worker.py app/api/panel.py tests/test_learn_hybrid_fusion.py tests/test_learning_workflow_stage_worker.py
git commit -m "feat(learn): add deterministic hybrid fusion"
```

---

### Task 5A: Seal the pre-VISTA baseline benchmark before refinement work

**Files:**
- Create: `app/learn/hybrid/benchmark.py`
- Create: `app/learn/hybrid/benchmark_scorer_v1.py`
- Create: `configs/benchmarks/portfolio_hybrid_v1_1_gate.json`
- Create: `scripts/run_portfolio_hybrid_v1_1_benchmark.py`
- Create: `tests/test_portfolio_hybrid_v1_1_benchmark.py`
- Create: `tests/fixtures/portfolio_hybrid_v1_1/manifest.template.json`
- Create: `tests/fixtures/portfolio_hybrid_v1_1/regression/README.md`
- Create: `tests/fixtures/portfolio_hybrid_v1_1/holdout/README.md`

**Interfaces:**
- Produces `seal_benchmark_manifest(...)`, provider-safe prediction projections, and the final generic prediction-producer interfaces for every arm (including future VISTA payload fields) in `benchmark.py` and `run_portfolio_hybrid_v1_1_benchmark.py`.
- Produces the final immutable scorer schema for every arm, VISTA fields, post-review split and `evaluate_release_gate(...)` in `benchmark_scorer_v1.py`. This file and the gate config are frozen after the Corpus Seal checkpoint; Task 10 must not modify them.
- Pre-VISTA diagnostics are `Qwen-only`, `Omni-only discovery`, and `Omni → Qwen`; the existing five-screen data is regression-only.
- The gate config SHA, scorer SHA, corpus/image/Gold hashes, model revisions, budget and shared UIA/OCR context policy are sealed before any holdout prediction.
- Grow the combined public/synthetic corpus to 20–30 screenshots and 100–200 independently reviewable important targets; record annotator/reviewer identity hashes and acceptable-region disagreements without leaking personal data.
- Promotion cleanup gates are hard failures: `max_simultaneous_gpu_owners <= 1`, every provider `cleanup_status == "verified"`, `orphan_provider_pids == 0`, `orphan_helper_pids == 0`, `lease_files_remaining == 0`, VRAM release within the predeclared tolerance, and verified compute termination after cancellation/timeout. Missing or indeterminate lifecycle evidence keeps Hybrid experimental.

- [ ] **Step 1: Write RED isolation tests.** Reject Gold fields in provider input, post-seal manifest mutation, unequal non-Omni context, unequal budgets, duplicate statistical arms, and zero-selection false success.

```python
def test_provider_projection_never_contains_gold_or_expected_target():
    projection = provider_manifest_projection(sealed_manifest_fixture())
    encoded = json.dumps(projection, sort_keys=True)
    assert "gold" not in encoded.casefold()
    assert "expected_candidate" not in encoded.casefold()
    assert "acceptable_bbox" not in encoded.casefold()
```

- [ ] **Step 2: Run RED.**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark.py
```

- [ ] **Step 3: Implement sealing/scoring and the regression-only pre-VISTA runner.** Do not run untouched holdout predictions in this task.

- [ ] **Step 4: Run GREEN and deterministic regression dry-run.**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark.py tests/test_omniparser_goal_selection_benchmark.py tests/test_omniparser_role_value_benchmark.py
uv run python scripts/run_portfolio_hybrid_v1_1_benchmark.py --partition regression --phase pre-vista --dry-run --output runtime_state/portfolio-hybrid-v1-1/benchmark-pre-vista-dry-run.json
```

- [ ] **Step 5: Independent Gold-leakage review and commit before VISTA integration.**

```powershell
git add -- app/learn/hybrid/benchmark.py app/learn/hybrid/benchmark_scorer_v1.py configs/benchmarks/portfolio_hybrid_v1_1_gate.json scripts/run_portfolio_hybrid_v1_1_benchmark.py tests/test_portfolio_hybrid_v1_1_benchmark.py tests/fixtures/portfolio_hybrid_v1_1/manifest.template.json tests/fixtures/portfolio_hybrid_v1_1/regression/README.md tests/fixtures/portfolio_hybrid_v1_1/holdout/README.md
git commit -m "test(learn): seal hybrid baseline benchmark"
```

---

### Task 5B: Create, review and commit the immutable corpus/Gold seal before VISTA

**Files:**
- Create: `scripts/seal_portfolio_hybrid_v1_1_corpus.py`
- Create: `tests/test_portfolio_hybrid_v1_1_corpus_seal.py`
- Create: `tests/fixtures/portfolio_hybrid_v1_1/corpus/regression/case-001.png` through `case-012.png`
- Create: `tests/fixtures/portfolio_hybrid_v1_1/corpus/holdout/case-013.png` through `case-024.png`
- Create: `tests/fixtures/portfolio_hybrid_v1_1/gold.v1.json`
- Create: `tests/fixtures/portfolio_hybrid_v1_1/corpus-manifest.v1.json`

**Interfaces:**
- Produces an immutable `portfolio_hybrid_v1_1_corpus_manifest_v1` containing screenshot, Gold, gate-config, benchmark producer/runner, scorer, model revision, budget and context-policy SHA values.
- The holdout partition remains prediction-free. The committed manifest is the only acceptable input to Task 10; runtime seal creation or mutation is forbidden.

- [ ] **Step 1: Write RED seal tests.** Assert exact file enumeration, content hashes, no prior prediction artifacts, scorer/gate SHA binding, disjoint regression/holdout IDs, no Gold in provider projections and rejection of any byte/config/model-budget mutation.

```python
def test_sealed_holdout_has_no_predictions_and_provider_projection_has_no_gold(tmp_path):
    manifest = load_and_verify_corpus_seal(tmp_path / "corpus-manifest.v1.json")
    assert manifest["holdout_prediction_count"] == 0
    assert not contains_gold_fields(provider_manifest_projection(manifest))
```

- [ ] **Step 2: Run RED, then create privacy-reviewed public/synthetic screenshots and independently reviewed Gold.** Holdout screenshots must not be used for prompt/rule/threshold development.

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_corpus_seal.py tests/test_portfolio_hybrid_v1_1_benchmark.py
```

- [ ] **Step 3: Seal once in a separate command; do not predict.**

```powershell
uv run python scripts/seal_portfolio_hybrid_v1_1_corpus.py --corpus-root tests/fixtures/portfolio_hybrid_v1_1/corpus --gold tests/fixtures/portfolio_hybrid_v1_1/gold.v1.json --gate configs/benchmarks/portfolio_hybrid_v1_1_gate.json --producer app/learn/hybrid/benchmark.py --runner scripts/run_portfolio_hybrid_v1_1_benchmark.py --scorer app/learn/hybrid/benchmark_scorer_v1.py --output tests/fixtures/portfolio_hybrid_v1_1/corpus-manifest.v1.json --require-no-predictions
```

- [ ] **Step 4: Run GREEN and obtain independent Gold-leakage PASS against the final actual provider projection.**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_corpus_seal.py tests/test_portfolio_hybrid_v1_1_benchmark.py
```

- [ ] **Step 5: Commit the immutable seal checkpoint before Task 6/7.**

```powershell
git add -- scripts/seal_portfolio_hybrid_v1_1_corpus.py tests/test_portfolio_hybrid_v1_1_corpus_seal.py tests/fixtures/portfolio_hybrid_v1_1/corpus tests/fixtures/portfolio_hybrid_v1_1/gold.v1.json tests/fixtures/portfolio_hybrid_v1_1/corpus-manifest.v1.json
git commit -m "test(eval): seal hybrid corpus and holdout gold"
```

After this commit, do not modify the corpus, Gold, manifest, `benchmark.py`, `benchmark_scorer_v1.py`, benchmark runner, or gate config. Any required change creates a new version and invalidates all predictions under the old seal.

---

### Task 6: Wire the managed Learn cascade without changing incumbent Runtime

**Files:**
- Modify: `app/learn/workflow_continuation.py`
- Modify: `app/learn/workflow_service.py`
- Modify: `app/learn/workflow_worker.py`
- Modify: `app/learn/workflow_contracts.py`
- Modify: `app/api/panel.py`
- Modify: `app/web_panel/panel.js`
- Test: `tests/test_learning_workflow_stage_execution.py`
- Test: `tests/test_learning_workflow_stage_worker.py`
- Test: `tests/test_learning_workflow_task_boundaries.py`
- Test: `tests/test_web_panel_route.py`
- Test: `tests/js/panel_learning_observation_evidence.test.cjs`

**Interfaces:**
- Adds explicit `learning_pipeline_mode: "incumbent" | "hybrid_v1_1"`; default remains `incumbent`, and `hybrid_v1_1` remains `rollout=disabled` in this checkpoint.
- Hybrid continuation order is exactly `hybrid_omni_discovery → hybrid_qwen_binding → hybrid_fusion → calibration`.
- Duplicate `continue`/adopt calls recover the same completed artifact and never repeat model inference.
- This slice stops after proving the calibration task handoff. Task 7 adds the post-calibration deterministic review projection and proves it never enters `panel_learning_model_review_repair`.
- API/panel requests for Hybrid must fail closed with `hybrid_rollout_disabled` until Task 7A has registered every handler and lifecycle guard.

- [ ] **Step 1: Write RED orchestration tests.** Assert exact task order, payload hash/idempotency, shared bundle ref, no old Qwen Observe before Omni, no post-VISTA Qwen repair, explicit SAFE_STOP on any stage failure and incumbent path byte-for-byte behavior preservation.

```python
def test_hybrid_managed_worker_order_reaches_calibration_without_pre_omni_qwen():
    run = drive_fake_hybrid_workers()
    assert run.task_kinds == [
        "panel_learning_hybrid_omni_discovery",
        "panel_learning_hybrid_qwen_binding",
        "panel_learning_hybrid_fusion",
        "panel_learning_calibration_sequence",
    ]
    assert run.task_kinds[0] != "vision_observe_screen"
```

- [ ] **Step 2: Run RED Python/JS tests.**

```powershell
uv run pytest -q tests/test_learning_workflow_stage_execution.py tests/test_learning_workflow_stage_worker.py tests/test_learning_workflow_task_boundaries.py tests/test_web_panel_route.py -k "hybrid or incumbent or continuation"
node --test tests/js/panel_learning_observation_evidence.test.cjs
```

- [ ] **Step 3: Implement the disabled orchestration branch.** Keep UI changes limited to a mode/status surface; do not add a new review page or Runtime endpoint. Unit tests may drive internal fake handlers, but the production API/panel must reject Hybrid startup at this checkpoint.

- [ ] **Step 4: Run GREEN and incumbent regression.**

```powershell
uv run pytest -q tests/test_learning_workflow_stage_execution.py tests/test_learning_workflow_stage_worker.py tests/test_learning_workflow_task_boundaries.py tests/test_web_panel_route.py
node --test tests/js/panel_learning_observation_evidence.test.cjs
node --check app/web_panel/panel.js
```

- [ ] **Step 5: Commit.**

```powershell
git add -- app/learn/workflow_continuation.py app/learn/workflow_service.py app/learn/workflow_worker.py app/learn/workflow_contracts.py app/api/panel.py app/web_panel/panel.js tests/test_learning_workflow_stage_execution.py tests/test_learning_workflow_stage_worker.py tests/test_learning_workflow_task_boundaries.py tests/test_web_panel_route.py tests/js/panel_learning_observation_evidence.test.cjs
git commit -m "feat(learn): orchestrate hybrid model cascade"
```

---

### Task 7: Reuse VISTA calibration with exact candidate/ROI lineage

**Files:**
- Create: `app/learn/hybrid/vista_refinement.py`
- Create: `app/learn/workflow_tasks/hybrid_review.py`
- Modify: `app/learn/calibration_sequence.py`
- Modify: `app/learn/recognition/roi.py`
- Modify: `app/api/vision.py`
- Modify: `app/learn/workflow_worker.py`
- Modify: `app/learn/workflow_service.py`
- Create: `tests/test_learn_hybrid_vista_refinement.py`
- Test: `tests/test_learning_calibration_sequence.py`
- Test: `tests/test_learn_recognition_roi.py`
- Test: `tests/test_learning_workflow_stage_execution.py`

**Interfaces:**
- Adds final managed task `panel_learning_hybrid_review_projection` after calibration.
- Produces `build_vista_requests(fusion_result, capture_bundle) -> list[dict]` for `BOUND` candidates only.
- Produces `validate_vista_proposal(*, request, raw_result) -> dict` with candidate ID, `candidate_bbox_ref`, `roi_ref`, affine transform ref and canonical point.
- `VISTA_FAILED`, `VISTA_OUT_OF_BOUNDS` and `TRANSFORM_INVALID` always become `REVIEW_REQUIRED`; they never preserve automatic acceptance.
- Calibration completion continues only to `panel_learning_hybrid_review_projection`; a test must prove `panel_learning_model_review_repair` is absent from the Hybrid path.

- [ ] **Step 1: Write RED geometry and lineage tests.** Cover ROI round trip, point inside ROI but outside candidate bbox, point inside candidate but outside ROI, stale source revision, wrong candidate ID, wrong capture SHA, unsubmitted candidate receiving VISTA status, clipping attempt, batch resume and cancellation.

```python
def test_vista_point_inside_roi_but_outside_candidate_is_rejected():
    request = vista_request(candidate_bbox=[100, 100, 140, 130], roi=[80, 80, 180, 160])
    result = validate_vista_proposal(request=request, raw_result={"point": [90, 90]})
    assert result["status"] == "VISTA_OUT_OF_BOUNDS"
    assert result["review_status"] == "REVIEW_REQUIRED"
    assert result.get("canonical_point") is None
```

- [ ] **Step 2: Run RED.**

```powershell
uv run pytest -q tests/test_learn_hybrid_vista_refinement.py tests/test_learning_calibration_sequence.py tests/test_learn_recognition_roi.py
```

- [ ] **Step 3: Implement a thin bridge over existing calibration/ROI primitives.** Do not copy the calibration service. Pass stable candidate IDs and source revision through batching/resume. Explicitly unload Qwen before VISTA acquisition.

- [ ] **Step 4: Run GREEN.**

```powershell
uv run pytest -q tests/test_learn_hybrid_vista_refinement.py tests/test_learning_calibration_sequence.py tests/test_learn_recognition_roi.py tests/test_learning_workflow_stage_execution.py -k "hybrid or vista or calibration or roi"
uv run python -m py_compile app/learn/hybrid/vista_refinement.py app/learn/workflow_tasks/hybrid_review.py app/learn/calibration_sequence.py app/learn/recognition/roi.py
```

- [ ] **Step 5: Commit.**

```powershell
git add -- app/learn/hybrid/vista_refinement.py app/learn/workflow_tasks/hybrid_review.py app/learn/calibration_sequence.py app/learn/recognition/roi.py app/api/vision.py app/learn/workflow_worker.py app/learn/workflow_service.py tests/test_learn_hybrid_vista_refinement.py tests/test_learning_calibration_sequence.py tests/test_learn_recognition_roi.py tests/test_learning_workflow_stage_execution.py
git commit -m "feat(learn): refine bound hybrid candidates with vista"
```

---

### Task 7A: Enforce sequential GPU release, recovery and repeated-run stability

**Files:**
- Create: `app/learn/hybrid/gpu_lifecycle.py`
- Modify: `app/core/model_server.py`
- Modify: `app/learn/workflow_worker.py`
- Modify: `app/learn/workflow_service.py`
- Modify: `app/api/panel.py`
- Modify: `app/web_panel/panel.js`
- Modify: `configs/learn_hybrid_v1_1.json`
- Modify: `configs/model_profiles/learn_mode_omniparser_v2.json`
- Create: `tests/test_learn_hybrid_gpu_lifecycle.py`
- Modify: `tests/test_model_request_cancellation.py`
- Modify: `tests/test_learning_workflow_stage_worker.py`

**Interfaces:**
- Produces `release_hybrid_provider(provider, *, process_inventory) -> cleanup_receipt`.
- Produces `assert_next_provider_safe_to_start(previous_cleanup_receipt, next_provider) -> None`.
- Required sequence is `Omni cleanup verified → Qwen start → Qwen cleanup verified → VISTA start → VISTA cleanup verified → Review`.
- After every real handler and lifecycle guard is registered, this task changes rollout from `disabled` to `experimental`; incumbent remains the default. The full GREEN test must resolve actual registry handlers, not only compare fake task-kind strings.

- [ ] **Step 1: Write RED lifecycle tests.** Cover simultaneous residency rejection, timeout, cancellation, outer-worker termination, orphan descendant, failed cleanup receipt, failure recovery, asset non-mutation and 3–5 repeated runs with zero leaked PID/lease.

```python
def test_next_model_cannot_start_until_previous_cleanup_is_verified():
    with pytest.raises(RuntimeError, match="previous provider cleanup is not verified"):
        assert_next_provider_safe_to_start(
            {"provider": "qwen", "cleanup_status": "indeterminate"},
            "vista",
        )
```

- [ ] **Step 2: Run RED.**

```powershell
uv run pytest -q tests/test_learn_hybrid_gpu_lifecycle.py tests/test_model_request_cancellation.py tests/test_learning_workflow_stage_worker.py -k "gpu or cleanup or cancellation or hybrid"
```

- [ ] **Step 3: Implement a thin lifecycle coordinator over existing model-server status/stop and Omni process lease.** Do not create a general scheduler.

- [ ] **Step 4: Run GREEN plus repeated deterministic runs and the complete registered-handler chain.**

```powershell
uv run pytest -q tests/test_learn_hybrid_gpu_lifecycle.py tests/test_model_request_cancellation.py tests/test_learning_workflow_stage_worker.py tests/test_learning_workflow_stage_execution.py tests/test_web_panel_route.py -k "hybrid or gpu or cleanup or cancellation"
uv run pytest -q tests/test_learn_hybrid_gpu_lifecycle.py -k repeated
uv run python -m py_compile app/learn/hybrid/gpu_lifecycle.py app/core/model_server.py app/learn/workflow_worker.py
```

- [ ] **Step 5: Commit.**

```powershell
git add -- app/learn/hybrid/gpu_lifecycle.py app/core/model_server.py app/learn/workflow_worker.py app/learn/workflow_service.py app/api/panel.py app/web_panel/panel.js configs/learn_hybrid_v1_1.json configs/model_profiles/learn_mode_omniparser_v2.json tests/test_learn_hybrid_gpu_lifecycle.py tests/test_model_request_cancellation.py tests/test_learning_workflow_stage_worker.py tests/test_learning_workflow_stage_execution.py tests/test_web_panel_route.py
git commit -m "fix(learn): verify sequential hybrid gpu cleanup"
```

---

### Task 8: Upgrade Large Review projection with append-only Hybrid edits

**Files:**
- Modify: `app/learn/hybrid/review_projection.py`
- Modify: `app/learn/draft_review.py`
- Modify: `app/learn/workflow_tasks/recognition.py`
- Modify: `app/learn/interface_workflow_review.py`
- Modify: `app/web_panel/panel.js`
- Modify: `app/web_panel/learning_workflow_review.js`
- Modify: `app/web_panel/index.html`
- Create: `tests/test_learn_hybrid_review.py`
- Modify: `tests/test_learning_draft_review.py`
- Modify: `tests/test_interface_workflow_review.py`
- Create: `tests/js/panel_learning_hybrid_review.test.cjs`

**Interfaces:**
- Produces `project_hybrid_review(*, capture_bundle, omni_inventory, qwen_bindings, fusion_result, vista_proposals) -> dict`.
- Raw proposal fields remain under immutable `model_proposal`; reviewer output is an append-only `review_decisions` collection.
- Delete/mark-unavailable creates a tombstone, rebox creates reviewed-derived geometry linked to the original candidate, point edit creates a human point proposal without overwriting VISTA, semantic edit appends a semantic revision, and Add creates a `human/...` origin ID.
- Any geometry, semantics, provenance or source revision edit revokes current-revision approval.

- [ ] **Step 1: Write RED backend and panel-state tests.** Verify all candidates can be selected in the large image, original/current geometry are both visible, provider provenance is compact, conflict warnings are visible, tombstones survive, added human IDs are unique, and confirm/review uses existing granular approval facts.

```javascript
test("rebox preserves model bbox and revokes current approval", () => {
  const state = createHybridReviewState(fixture());
  state.rebox("candidate/abc", [10, 20, 80, 50]);
  const candidate = state.currentCandidate();
  assert.deepEqual(candidate.model_proposal.bbox_original, [8, 18, 82, 52]);
  assert.deepEqual(candidate.reviewed_geometry.bbox, [10, 20, 80, 50]);
  assert.equal(candidate.reviewed_by_human, false);
});
```

- [ ] **Step 2: Run RED.**

```powershell
uv run pytest -q tests/test_learn_hybrid_review.py tests/test_learning_draft_review.py tests/test_interface_workflow_review.py -k "hybrid or review or approval"
node --test tests/js/panel_learning_hybrid_review.test.cjs
```

- [ ] **Step 3: Implement inside the existing large-image modal.** Do not restore a second page-level audit tool. Keep screen-level properties separate from selected-candidate properties.

- [ ] **Step 4: Run GREEN and static panel checks.**

```powershell
uv run pytest -q tests/test_learn_hybrid_review.py tests/test_learning_draft_review.py tests/test_interface_workflow_review.py
node --test tests/js/panel_learning_hybrid_review.test.cjs tests/js/panel_learning_observation_evidence.test.cjs
node --check app/web_panel/panel.js
node --check app/web_panel/learning_workflow_review.js
```

- [ ] **Step 5: Commit.**

```powershell
git add -- app/learn/hybrid/review_projection.py app/learn/draft_review.py app/learn/workflow_tasks/recognition.py app/learn/interface_workflow_review.py app/web_panel/panel.js app/web_panel/learning_workflow_review.js app/web_panel/index.html tests/test_learn_hybrid_review.py tests/test_learning_draft_review.py tests/test_interface_workflow_review.py tests/js/panel_learning_hybrid_review.test.cjs
git commit -m "feat(review): audit hybrid proposals in large review"
```

---

### Task 9: Prove save, fresh-process reload, deterministic compile and single publish

**Files:**
- Create: `scripts/prove_portfolio_hybrid_v1_1_persistence.py`
- Create: `tests/test_portfolio_hybrid_v1_1_persistence.py`
- Create: `tests/fixtures/portfolio_hybrid_v1_1/reviewed_hybrid_source.json`
- Modify: `tests/test_learning_workflow_stage_execution.py`
- Modify only if a failing test proves a gap: `app/agent/reviewed_workflow_compiler.py`
- Modify only if a failing test proves a gap: `app/agent/reviewed_workflow_asset.py`
- Modify only if a failing test proves a gap: `app/learn/workflow_store.py`

**Interfaces:**
- Produces a machine-readable `portfolio_hybrid_v1_1_persistence_proof_v1`.
- Required sequence: `Save → compile_without_publish A → terminate server → fresh server → reload exact saved bytes → compile_without_publish B → compare source/compiled SHA → publish B once → verify registry/CAS`.
- Review source may retain the non-authorizing VISTA proposal; compiled/published asset must contain no runtime point field and must still require fresh grounding.
- The authoritative deterministic E2E test drives the production managed cascade through public service/API boundaries with fake Omni/Qwen/VISTA runners, saves through the Task 8 Large Review path, and feeds those exact source bytes into the two-process proof. The hand-written fixture is only a narrow compiler negative-control input, never the sole persistence evidence.

- [ ] **Step 1: Write RED managed-E2E plus subprocess tests.** Drive `capture → fake Omni → fake Qwen → fusion → fake bounded VISTA → Large Review save`, then cross a real process boundary. Do not simulate restart by clearing a module cache. Assert PID A differs from PID B, exact managed-source bytes load, source SHA A/B and compiled SHA A/B match, publish revision increments once, duplicate publish is idempotent, and runtime-point fields are absent.

```python
def test_fresh_process_compile_is_deterministic_and_strips_runtime_points(tmp_path):
    proof = run_managed_two_process_persistence_proof(
        tmp_path,
        omni_runner=fake_omni_runner,
        qwen_runner=fake_qwen_runner,
        vista_runner=fake_bounded_vista_runner,
    )
    assert proof["server_pid_a"] != proof["server_pid_b"]
    assert proof["source_sha_a"] == proof["source_sha_b"]
    assert proof["compiled_asset_sha_a"] == proof["compiled_asset_sha_b"]
    assert proof["publish_count"] == 1
    assert proof["published_runtime_point_fields"] == []
```

- [ ] **Step 2: Run RED.**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_persistence.py
```

- [ ] **Step 3: Implement the production-boundary E2E fixture driver and proof runner.** Change compiler/store production code only if the proof exposes a real gap; preserve current granular node/control/action/edge approval requirements.

- [ ] **Step 4: Run GREEN plus existing compiler/store suites.**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_persistence.py tests/test_learning_workflow_stage_execution.py -k "hybrid or persistence or restart"
uv run pytest -q tests/test_reviewed_workflow_compiler_v2.py tests/test_reviewed_workflow_asset_v2.py
uv run python scripts/prove_portfolio_hybrid_v1_1_persistence.py --managed-e2e --fake-provider-boundaries --output runtime_state/portfolio-hybrid-v1-1/persistence-proof-managed-e2e.json
```

Expected: subprocess exit 0 and a proof with equal source/compiled SHA, one publish, all non-authorizing flags false for execution, and no runtime point fields in the published object.

The optional command below is negative-control evidence only and must never replace the managed proof:

```powershell
uv run python scripts/prove_portfolio_hybrid_v1_1_persistence.py --fixture tests/fixtures/portfolio_hybrid_v1_1/reviewed_hybrid_source.json --no-publish --output runtime_state/portfolio-hybrid-v1-1/persistence-proof-fixture-negative-control.json
```

- [ ] **Step 5: Commit production/test changes but not generated runtime evidence.**

```powershell
git add -- scripts/prove_portfolio_hybrid_v1_1_persistence.py tests/test_portfolio_hybrid_v1_1_persistence.py tests/test_learning_workflow_stage_execution.py tests/fixtures/portfolio_hybrid_v1_1/reviewed_hybrid_source.json app/agent/reviewed_workflow_compiler.py app/agent/reviewed_workflow_asset.py app/learn/workflow_store.py
git commit -m "test(learn): prove hybrid persistence across restart"
```

Omit unchanged optional production paths from `git add`.

---

### Task 10: Extend the sealed benchmark with VISTA and run final holdout once

**Files:**
- Create: `scripts/assemble_portfolio_hybrid_v1_1_report.py`
- Create: `tests/test_portfolio_hybrid_v1_1_release_gate.py`

**Interfaces:**
- Reuses the Task 5A immutable manifest/producer/scorer/gate to run incumbent Qwen(+same UIA)→VISTA, automatic Omni→Qwen(+same UIA)→bounded VISTA and post-review reporting.
- `pre-review Hybrid artifact` is the persisted representation of the automatic Hybrid prediction, not a duplicate statistical arm.
- The predeclared gate remains: `wrong_target_count == 0`, automatic coverage at least `0.20`, critical-target correct coverage improvement at least `0.05` over incumbent, semantic precision not below incumbent, and positive point-accuracy gain for the declared VISTA-eligible subset.
- The immutable scorer also requires every Task 5A cleanup/lifecycle gate. Task 10 may add report assembly only; it must not modify `benchmark.py`, `benchmark_scorer_v1.py`, the benchmark runner, gate config, Gold, corpus or sealed manifest.

- [ ] **Step 1: Write RED final-arm/gate tests.** Cover wrong target forcing safety credit to zero, duplicate pre-review arm, human edits masking automatic errors, VISTA benefit only on submitted candidates, gate-config SHA mismatch and post-seal threshold mutation.

```python
def test_zero_selection_cannot_pass_wrong_target_gate():
    report = score_predictions(sealed_case(), predictions=[])
    assert report["wrong_target_count"] == 0
    assert report["automatic_coverage"] == 0
    assert evaluate_release_gate(report)["passed"] is False
```

- [ ] **Step 2: Run RED.**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark.py tests/test_portfolio_hybrid_v1_1_release_gate.py
```

- [ ] **Step 3: Implement report assembly around the already-sealed producer/scorer outputs.** Do not change Gold/model projections or scoring behavior.

- [ ] **Step 4: Run deterministic benchmark unit tests and regression-only dry run.**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_benchmark.py tests/test_portfolio_hybrid_v1_1_release_gate.py tests/test_omniparser_goal_selection_benchmark.py tests/test_omniparser_role_value_benchmark.py
uv run python scripts/run_portfolio_hybrid_v1_1_benchmark.py --partition regression --phase final --dry-run --output runtime_state/portfolio-hybrid-v1-1/benchmark-final-dry-run.json
```

- [ ] **Step 5: Independent leakage review before any holdout call.** Reviewer must inspect the exact manifest projection passed to each model and return PASS.

- [ ] **Step 6: Commit report assembly and release-gate tests before prediction.**

```powershell
git add -- scripts/assemble_portfolio_hybrid_v1_1_report.py tests/test_portfolio_hybrid_v1_1_release_gate.py
git commit -m "test(eval): verify hybrid vista release gate"
```

- [ ] **Step 7: Run actual model regression and untouched holdout once.** Run sequentially, collect latency/VRAM/cleanup, and do not tune on holdout failures.

```powershell
uv run python scripts/run_portfolio_hybrid_v1_1_benchmark.py --manifest tests/fixtures/portfolio_hybrid_v1_1/corpus-manifest.v1.json --partition regression --actual-models --require-existing-seal --output runtime_state/portfolio-hybrid-v1-1/benchmark-regression.json
uv run python scripts/run_portfolio_hybrid_v1_1_benchmark.py --manifest tests/fixtures/portfolio_hybrid_v1_1/corpus-manifest.v1.json --partition holdout --actual-models --require-existing-seal --output runtime_state/portfolio-hybrid-v1-1/benchmark-holdout.json
```

Decision: promote Hybrid default only if the sealed gate passes. If VISTA has no stable point gain, keep it optional for the declared subset. If automatic `wrong_target > 0`, do not promote and continue fixing the bounded Hybrid layer without weakening thresholds.

---

### Task 11: Run native and web unknown-UI no-action acceptance with verified cleanup

**Files:**
- Create: `app/learn/hybrid/acceptance.py`
- Create: `scripts/run_portfolio_hybrid_v1_1_no_action_acceptance.py`
- Create: `tests/test_portfolio_hybrid_v1_1_no_action_acceptance.py`
- Create: `tests/fixtures/portfolio_hybrid_v1_1/unknown_native/static_fixture.py`
- Create: `tests/fixtures/portfolio_hybrid_v1_1/unknown_web/index.html`

**Interfaces:**
- Produces `portfolio_hybrid_v1_1_no_action_acceptance_v1` with pre/post PID/HWND inventory, exact test-owned process tree, zero-action counters, per-interface recognition/review metrics and cleanup status.
- Native fixture and dedicated browser are child processes owned by the harness. Browser uses a temporary dedicated profile and never attaches to an existing user session.
- Cleanup calls process/job/service lifecycle only. If exact cleanup is unavailable, the harness exits blocked and does not issue GUI close actions.
- At least one actual native/web reviewed artifact must be saved/reloaded and passed through compiler schema/current-approval readiness checks equivalent to Task 9. It need not publish a second asset, but a screenshot-only or in-memory artifact cannot satisfy acceptance.

- [ ] **Step 1: Write RED lifecycle/zero-action tests using fake process and HWND inventory providers.** Cover pre-existing windows preserved, child browser tree cleanup, partial termination failure, PID reuse, missing HWND, cleanup retry bounds, accidental input dispatch, scroll/type/navigation/GUI-close counters and model helper orphan detection.

```python
def test_cleanup_removes_only_exact_test_owned_identities():
    proof = run_fake_acceptance(preexisting={101, 102}, created={201, 202, 203})
    assert proof["test_owned_interfaces_remaining"] == 0
    assert proof["test_owned_model_processes_remaining"] == 0
    assert proof["user_preexisting_interfaces_closed"] == 0
    assert proof["post_existing_pids"] == [101, 102]
```

- [ ] **Step 2: Run RED.**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_no_action_acceptance.py
```

- [ ] **Step 3: Implement inventory, job/process ownership and action audit.** Do not use browser-control, computer-use, SendInput, click, key, scroll or window-close APIs. Launch static interfaces by process command, capture/read them through the Learn capture path, and terminate the exact owned process tree in `finally`.

- [ ] **Step 4: Run deterministic GREEN and syntax checks.**

```powershell
uv run pytest -q tests/test_portfolio_hybrid_v1_1_no_action_acceptance.py
uv run python -m py_compile app/learn/hybrid/acceptance.py scripts/run_portfolio_hybrid_v1_1_no_action_acceptance.py tests/fixtures/portfolio_hybrid_v1_1/unknown_native/static_fixture.py
```

- [ ] **Step 5: Commit the harness before live-static acceptance.**

```powershell
git add -- app/learn/hybrid/acceptance.py scripts/run_portfolio_hybrid_v1_1_no_action_acceptance.py tests/test_portfolio_hybrid_v1_1_no_action_acceptance.py tests/fixtures/portfolio_hybrid_v1_1/unknown_native/static_fixture.py tests/fixtures/portfolio_hybrid_v1_1/unknown_web/index.html
git commit -m "test(learn): add no-action unknown-ui acceptance"
```

- [ ] **Step 6: Record pre-test inventory and run one native plus one web acceptance.** Save/reload both; select at least one reviewed artifact for `compile_without_publish --verify-approval-readiness` using the same compiler contract as Task 9.

```powershell
uv run python scripts/run_portfolio_hybrid_v1_1_no_action_acceptance.py --actual-models --native --web --output runtime_state/portfolio-hybrid-v1-1/no-action-acceptance.json
```

Required final counters:

```text
real_clicks = 0
live_fills = 0
live_submits = 0
live_scrolls = 0
live_keypresses_or_types = 0
focus_driven_target_actions = 0
navigation_clicks = 0
gui_window_close_actions = 0
test_owned_interfaces_remaining = 0
test_owned_model_processes_remaining = 0
user_preexisting_interfaces_closed = 0
```

- [ ] **Step 7: Independently inspect the acceptance JSON, exact PIDs/HWNDs and post-cleanup process state before making any success claim.**

---

### Task 12: Run Portfolio v1 regression, synchronize docs and freeze or retain experimental status

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_SUMMARY.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`
- Create: `release/portfolio-hybrid-v1-1/README.md`
- Create only from privacy-reviewed projections: `release/portfolio-hybrid-v1-1/benchmark-summary.json`
- Create only from privacy-reviewed projections: `release/portfolio-hybrid-v1-1/no-action-acceptance-summary.json`
- Create only from the privacy-reviewed `persistence-proof-managed-e2e.json` projection: `release/portfolio-hybrid-v1-1/persistence-proof-summary.json`

**Interfaces:**
- Public docs distinguish actual-model, deterministic replay, controlled static UI and prior Portfolio v1 live execution evidence.
- README states that perception is replaceable, reviewed knowledge is durable, and Hybrid v1.1 affects Learn/Review only.
- Final status is `Frozen Portfolio Hybrid v1.1` only if every spec stop condition has direct evidence; otherwise it remains `Partial/Experimental` with exact failed gates.

- [ ] **Step 1: Run the focused integrated Hybrid matrix.**

```powershell
uv run pytest -q tests/test_learn_hybrid_contracts.py tests/test_learn_hybrid_capture.py tests/test_learning_hybrid_vertical_slice.py tests/test_learn_hybrid_omni_discovery.py tests/test_learn_hybrid_qwen_binding.py tests/test_learn_hybrid_fusion.py tests/test_portfolio_hybrid_v1_1_corpus_seal.py tests/test_learn_hybrid_vista_refinement.py tests/test_learn_hybrid_gpu_lifecycle.py tests/test_learn_hybrid_review.py tests/test_portfolio_hybrid_v1_1_persistence.py tests/test_portfolio_hybrid_v1_1_benchmark.py tests/test_portfolio_hybrid_v1_1_release_gate.py tests/test_portfolio_hybrid_v1_1_no_action_acceptance.py
```

- [ ] **Step 2: Run affected Learn/UEI/Review/worker regression.**

```powershell
uv run pytest -q tests/test_learning_workflow_stage_execution.py tests/test_learning_workflow_stage_worker.py tests/test_learning_workflow_task_boundaries.py tests/test_learning_calibration_sequence.py tests/test_learning_draft_review.py tests/test_interface_workflow_review.py tests/test_uei_v1_provider_runtime.py tests/test_uei_v1_omniparser_shadow_adapter.py tests/test_uei_provider_neutral_review.py tests/test_web_panel_route.py
Get-ChildItem tests/js -Filter *.test.cjs | ForEach-Object { node --test $_.FullName; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
```

- [ ] **Step 3: Run the frozen Portfolio v1 authority/receipt/compiler/public-evidence regression.** This command is canonical for this Hybrid close-out and must not be replaced by a narrower suite.

```powershell
uv run pytest -q tests/test_portfolio_v1_provider_contract.py tests/test_portfolio_v1_reviewed_asset.py tests/test_portfolio_v1_release_callsite.py tests/test_portfolio_v1_release_workspace.py tests/test_portfolio_v1_public_evidence_package.py tests/test_build_portfolio_v1_controlled_live_gif.py tests/test_live_controller_portfolio_confirmation_v1.py tests/test_reviewed_workflow_compiler_v2.py tests/test_reviewed_workflow_asset_v2.py
```

Record `tests/test_agent_runtime_actual_adapter_portfolio_v1.py` as a pre-existing untracked file. Do not stage it or use its result as proof of the committed snapshot; if run separately, label the result inherited/untracked.

- [ ] **Step 4: Run the full offline repository baseline if time and dependencies permit.**

```powershell
uv run pytest -q
```

Record skipped/external-dependency tests separately. A previous `2762 passed, 1 skipped` baseline is historical and cannot replace a current run.

- [ ] **Step 5: Privacy-project generated evidence.** Strip absolute paths, usernames, credentials, full raw OCR/model text and private window titles. Verify public JSON hashes still bind the private authoritative evidence through non-sensitive refs.

- [ ] **Step 6: Update the five canonical docs and release evidence.** Record exact benchmark arms/results, review edits, latency/VRAM, cleanup proof, failed/optional providers and whether Hybrid becomes default.

- [ ] **Step 7: Independent final architecture, accuracy, safety and documentation review.** Reviewer must return PASS against every Final Stop Condition in the spec.

- [ ] **Step 8: Stage only the close-out slice, scan and commit.**

```powershell
git add -- README.md PROJECT_SUMMARY.md ARCHITECTURE.md CURRENT_STATE.md NEXT_STEPS.md release/portfolio-hybrid-v1-1
git diff --cached --check
git commit -m "docs(learn): freeze portfolio hybrid v1.1"
```

Do not commit ignored/private runtime evidence or the unrelated pre-existing untracked test.

## Final Verification Checklist

- [ ] All managed tasks use one immutable capture lineage and deterministic artifact refs.
- [ ] Omni candidate IDs are stable and raw geometry remains inspectable after reload.
- [ ] Qwen binds only existing candidate IDs and cannot emit geometry or authority.
- [ ] Fusion states and thresholds come from the sealed versioned config.
- [ ] VISTA runs only for exact-lineage `BOUND` candidates and its point is inside both bbox and ROI.
- [ ] Large Review preserves proposal/review separation and existing granular approval facts.
- [ ] Fresh-process double compile is deterministic; publish occurs once; published asset has no reusable runtime point.
- [ ] Sealed holdout has no Gold leakage, non-trivial coverage and automatic `wrong_target=0`.
- [ ] Promotion lifecycle gates prove one GPU owner, verified provider cleanup, zero orphan PID/lease and bounded VRAM release after normal/cancel/timeout paths.
- [ ] Native and web unknown-UI acceptance has every action counter at zero.
- [ ] Every test-owned interface/model/helper process is closed by lifecycle cleanup; no user pre-existing window is closed.
- [ ] Portfolio v1 regression remains green and Runtime authority is unchanged.
- [ ] Public claims match evidence grade and actual status.
