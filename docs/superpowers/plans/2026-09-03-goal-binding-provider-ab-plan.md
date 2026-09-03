# Goal Binding Provider A/B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement and run a regression-only staged A/B that compares replaceable native GUI grounding models as GoalBindingProvider while reusing one frozen Omni candidate snapshot and the existing VISTA/end-to-end scoring boundary.

**Architecture:** Keep model-facing syntax provider-native, normalize each output through a thin adapter to one canonical screenshot-space point, and deterministically bind only when exactly one active frozen Omni candidate contains that point. Separate snapshot creation, provider execution, binder scoring, existing end-to-end scoring, model storage, and lifecycle evidence so no model, adapter, or runner can read Gold or holdout data.

**Tech Stack:** Python 3.11, `pytest`, PyTorch/Transformers, existing llama.cpp integration, Hugging Face Hub, JSON/JSONL evidence, Windows process/GPU lifecycle controls.

**Spec:** `docs/superpowers/specs/2026-09-03-goal-binding-provider-ab-design.md`

## Global Constraints

- Use exactly `case-001` through `case-005` and 25 targets. Never read or run unique holdout.
- Freeze Omni once and reuse byte-identical candidate files in every arm.
- Do not modify existing scorer, Gold, corpus, estimand, Gate, Fusion, VISTA Contract, or Omni bbox.
- Common contract begins after provider-native parsing; do not force challenger models to generate candidate-index JSON.
- GUI-Actor selection uses only `topk_points[0]`.
- Stage 1 uses full UI-Venus-1.5-2B F16, GUI-Actor-3B BF16, and Phi-Ground-Any BF16. Run Stage 2 only when Stage 1 has no hard-gate passer.
- `E:\模型测试` is the only new model/cache/staging/run root and is capped at exactly `32,212,254,720` logical bytes.
- Never delete or alter incumbent artifacts on D. Deletion must reject paths outside the resolved E root, the root itself, symlinks/reparse points, and unregistered directories.
- One large model may be resident at a time. Cleanup residue blocks the next arm.
- Actual model quality failures remain results; do not tune prompt, preprocessing, mapping, threshold, scorer, or Gold after seeing scores.
- All provider artifacts are regression-only, non-authorizing, and never enable action/click execution.
- After each implementation slice, run the focused tests, inspect `git diff`, run `git diff --check`, and create only the stated single-purpose commit. Do not push.

## File map

- `app/learn/hybrid/goal_binding_provider.py`: canonical result validation and deterministic native-point-to-candidate mapping.
- `app/learn/hybrid/goal_binding_native_adapters.py`: strict provider-native parsers and coordinate normalization; no lifecycle or scoring.
- `app/learn/hybrid/omni_snapshot.py`: create, seal, load, and verify one immutable five-screen Omni snapshot.
- `app/learn/hybrid/goal_binding_ab.py`: consume a snapshot, run one binder arm, feed legal BOUND ROI to existing VISTA path, and finalize arm artifacts.
- `app/learn/hybrid/goal_binding_ab_score.py`: Gold-reading binder scorer, hard gates, passer-only presentation score, and matrix report.
- `app/learn/hybrid/model_test_storage.py`: 30 GiB inventory, projected-size gate, artifact manifest, and safe registered deletion.
- `app/learn/hybrid/goal_binding_model_callers.py`: lazy provider-specific actual callers and cleanup integration.
- `scripts/run_goal_binding_provider_ab.py`: preflight, snapshot, one-arm, staged matrix, score, cleanup, and stop CLI.
- `scripts/fetch_goal_binding_model.py`: resolve immutable revision, size-gate, download, hash, and register one model.
- `scripts/model_servers/goal_binding_transformers_worker.py`: bounded one-model native inference worker for supported full checkpoints.
- `configs/benchmarks/goal_binding_provider_ab_v1.json`: frozen screens, arms, stages, profile IDs, gates, storage root, and no-holdout metadata.
- `configs/model_profiles/goal_binding_*.json`: immutable provider/runtime/native-output metadata for incumbent and challengers.
- `tests/test_goal_binding_provider.py`, `tests/test_goal_binding_native_adapters.py`, `tests/test_omni_snapshot.py`, `tests/test_goal_binding_ab.py`, `tests/test_goal_binding_ab_score.py`, `tests/test_model_test_storage.py`, `tests/test_goal_binding_model_callers.py`, `tests/test_goal_binding_provider_ab_cli.py`: focused contract and orchestration tests.

---

### Task 1: Canonical binding result and deterministic candidate mapper

**Files:**
- Create: `app/learn/hybrid/goal_binding_provider.py`
- Create: `tests/test_goal_binding_provider.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class NativePointProposal:
    goal_index: int
    point: tuple[float, float] | None
    coordinate_space: str
    confidence: float | None
    status: str
    failure_reason: str | None

def map_native_point_to_candidate(
    *,
    proposal: NativePointProposal,
    image_size: tuple[int, int],
    candidates: Sequence[Mapping[str, object]],
    provider_id: str,
    capture_ref: Mapping[str, str],
    native_output_ref: Mapping[str, str],
    omni_snapshot_ref: Mapping[str, str],
) -> dict[str, object]: ...

def validate_goal_binding_provider_result(value: object) -> dict[str, object]: ...
```

`map_native_point_to_candidate` projects a validated provider point to screenshot pixels exactly once, tests strict interior against active candidates, and emits only `BOUND`, `UNBOUND`, or `PROVIDER_FAILURE` with `binding_basis=native_point`. The incumbent control bridge may emit `binding_basis=direct_candidate_index` with a null canonical point after the existing closed index parser succeeds. Neither path reads role/label, Gold, OCR, or action policy.

- [ ] **Step 1: Write RED contract tests**

Add these exact tests:

```python
def test_one_strict_active_hit_binds_existing_candidate(): ...
def test_zero_hit_and_overlapping_hits_are_unbound(): ...
def test_boundary_and_inactive_hits_are_unbound(): ...
def test_provider_failure_never_carries_candidate_or_point(): ...
def test_mapper_rejects_nan_infinity_bad_space_and_out_of_bounds(): ...
def test_mapper_never_mutates_or_expands_omni_geometry(): ...
def test_canonical_result_is_closed_non_authorizing_and_lineage_bound(): ...
def test_missing_provider_confidence_remains_null_not_fabricated(): ...
def test_incumbent_direct_index_basis_is_closed_and_has_no_invented_point(): ...
```

- [ ] **Step 2: Run RED**

```powershell
uv run pytest -q tests/test_goal_binding_provider.py
```

Expected: collection fails because `app.learn.hybrid.goal_binding_provider` does not exist.

- [ ] **Step 3: Implement the minimal pure mapper**

Implement finite/range checks for `normalized_0_1`, `normalized_0_1000`, and `capture_pixels`; use strict `x1 < x < x2` / `y1 < y < y2`; preserve candidate ordering and IDs; use `None` for unavailable confidence; set `artifact_is_authorization=False`. Unknown coordinate spaces or malformed lineage raise `ValueError`; a validated provider failure becomes `PROVIDER_FAILURE` evidence.

- [ ] **Step 4: Run GREEN and adjacent geometry regressions**

```powershell
uv run pytest -q tests/test_goal_binding_provider.py tests/test_simple_native_provider_contracts.py tests/test_learn_hybrid_vista_refinement.py
git diff --check
```

Expected: all selected tests pass and no whitespace errors are reported.

- [ ] **Step 5: Commit**

```powershell
git add app/learn/hybrid/goal_binding_provider.py tests/test_goal_binding_provider.py
git commit -m "feat(binding): add native point candidate mapper"
```

---

### Task 2: Strict provider-native adapters

**Files:**
- Create: `app/learn/hybrid/goal_binding_native_adapters.py`
- Create: `tests/test_goal_binding_native_adapters.py`

**Interfaces:**

```python
def parse_ui_venus_point(raw: object, *, goal_index: int, profile: Mapping[str, object]) -> NativePointProposal: ...
def parse_gui_actor_top1(raw: object, *, goal_index: int, profile: Mapping[str, object]) -> NativePointProposal: ...
def parse_phi_ground_any(raw: object, *, goal_index: int, profile: Mapping[str, object]) -> NativePointProposal: ...
def parse_gguf_grounding(raw: object, *, goal_index: int, profile: Mapping[str, object]) -> NativePointProposal: ...
```

Each function accepts only the exact shape and coordinate space declared in a sealed profile. Phi bbox output uses its geometric center; GUI-Actor uses only `topk_points[0]`; no parser sees candidates or Gold.

- [ ] **Step 1: Write RED native-shape tests**

```python
def test_ui_venus_parses_one_official_point_and_rejects_extra_points(): ...
def test_gui_actor_uses_topk_points_zero_only(): ...
def test_gui_actor_does_not_fallback_when_top1_is_invalid(): ...
def test_phi_point_and_bbox_normalize_by_sealed_profile_mode(): ...
def test_phi_bbox_center_rejects_degenerate_or_out_of_range_box(): ...
def test_gguf_parser_accepts_only_the_profile_native_short_form(): ...
def test_all_native_parsers_preserve_raw_utf8_without_reasoning_fields(): ...
def test_native_parsers_cannot_emit_candidate_id_action_or_authority(): ...
```

- [ ] **Step 2: Run RED**

```powershell
uv run pytest -q tests/test_goal_binding_native_adapters.py
```

Expected: collection fails because the adapter module is absent.

- [ ] **Step 3: Implement closed native parsers**

Use `json.JSONDecoder.raw_decode` for textual outputs and reject trailing prose. Validate all numbers with `math.isfinite`; reject boolean-as-number. Preserve raw bytes outside `NativePointProposal` in caller trace, not as fields invented by the model. Do not accept alternative provider shapes until a sealed official profile and RED fixture explicitly requires them.

- [ ] **Step 4: Run GREEN**

```powershell
uv run pytest -q tests/test_goal_binding_native_adapters.py tests/test_goal_binding_provider.py tests/test_simple_native_provider_callers.py
git diff --check
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add app/learn/hybrid/goal_binding_native_adapters.py tests/test_goal_binding_native_adapters.py
git commit -m "feat(binding): add provider native grounding adapters"
```

---

### Task 3: Frozen Omni snapshot

**Files:**
- Create: `app/learn/hybrid/omni_snapshot.py`
- Create: `tests/test_omni_snapshot.py`
- Modify: `app/learn/hybrid/simple_native_smoke.py`

**Interfaces:**

```python
def create_omni_snapshot(
    *, cases: Sequence[ProviderCase], omni: OmniNativeCaller, output_dir: Path,
    provider_identity: Mapping[str, object]
) -> Path: ...

def load_verified_omni_snapshot(
    path: Path, *, expected_cases: Sequence[ProviderCase]
) -> dict[str, object]: ...
```

Expose or reuse the existing Omni-native-to-canonical-candidate function from `simple_native_smoke.py`; do not duplicate bbox conversion. Snapshot creation is the only path allowed to call Omni in this experiment.

- [ ] **Step 1: Write RED snapshot tests**

```python
def test_snapshot_runs_omni_exactly_once_per_five_screens(): ...
def test_snapshot_seals_native_and_canonical_bytes_and_candidate_order(): ...
def test_all_arms_receive_byte_identical_candidate_files(): ...
def test_snapshot_rejects_changed_capture_sha_geometry_order_or_profile(): ...
def test_snapshot_contains_no_gold_holdout_or_action_authority(): ...
def test_snapshot_loader_never_constructs_an_omni_caller(): ...
```

- [ ] **Step 2: Run RED**

```powershell
uv run pytest -q tests/test_omni_snapshot.py
```

Expected: collection fails because snapshot APIs do not exist.

- [ ] **Step 3: Implement create/seal/load verification**

Write canonical UTF-8 JSON with `ensure_ascii=False`, close each case file before hashing, then write and self-hash `manifest.json`. Require exactly five configured case IDs and 25 goals. Loader recalculates every screenshot, candidate file, and aggregate hash before returning immutable copies.

- [ ] **Step 4: Run GREEN and Omni regressions**

```powershell
uv run pytest -q tests/test_omni_snapshot.py tests/test_simple_native_provider_smoke.py tests/test_simple_native_provider_evidence.py tests/test_uei_v1_omniparser_shadow_worker.py
git diff --check
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add app/learn/hybrid/omni_snapshot.py app/learn/hybrid/simple_native_smoke.py tests/test_omni_snapshot.py
git commit -m "feat(benchmark): freeze reusable omni candidate snapshot"
```

---

### Task 4: One-arm runner with existing VISTA downstream

**Files:**
- Create: `app/learn/hybrid/goal_binding_ab.py`
- Create: `tests/test_goal_binding_ab.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class GoalBindingArm:
    arm_id: str
    provider_id: str
    call: Callable[[Path, Mapping[str, object]], object]
    adapt: Callable[[object, int, Mapping[str, object]], Mapping[str, object]]
    cleanup: Callable[[], Mapping[str, object]]

def run_goal_binding_arm(
    *, cases: Sequence[ProviderCase], snapshot_path: Path, arm: GoalBindingArm,
    vista: VistaNativeCaller, artifact_dir: Path
) -> ProviderDiagnosticArtifact: ...
```

The runner performs 25 per-goal provider calls, adapts each raw native result to the closed canonical result, and invokes existing VISTA only for legal `BOUND` results. Challenger adapters call `map_native_point_to_candidate`; the incumbent control adapter keeps its already-frozen candidate-index parser, validates the index against the same snapshot, and emits the canonical result without inventing a point. It writes raw/parsed/error hashes and exact snapshot parent ref before finalizing the existing provider artifact shape expected by `score_simple_native_regression`.

- [ ] **Step 1: Write RED runner tests**

```python
def test_arm_runner_never_calls_omni_and_verifies_snapshot_first(): ...
def test_arm_runner_calls_binder_once_for_each_of_25_goals(): ...
def test_malformed_native_output_is_provider_failure_not_fallback(): ...
def test_zero_or_multiple_candidate_hit_is_safe_abstain_before_vista(): ...
def test_vista_receives_only_legal_bound_candidate_roi(): ...
def test_runner_records_native_raw_parsed_error_and_parent_hashes(): ...
def test_runner_preserves_role_label_by_deterministic_goal_inheritance(): ...
def test_incumbent_control_uses_existing_index_parser_without_fake_point(): ...
def test_runner_is_regression_only_non_authorizing_and_has_zero_actions(): ...
def test_cleanup_failure_blocks_arm_finalization_and_next_model(): ...
```

- [ ] **Step 2: Run RED**

```powershell
uv run pytest -q tests/test_goal_binding_ab.py
```

Expected: collection fails because `goal_binding_ab` is absent.

- [ ] **Step 3: Implement one-arm orchestration**

Reuse `_prepare_capture`, ROI persistence/validation, provider-phase cleanup, and `score_simple_native_regression` input shape from the current simple-native diagnostic. Add adapters at the binder seam only. Do not modify VISTA Contract or existing scorer arithmetic.

- [ ] **Step 4: Run GREEN and downstream regressions**

```powershell
uv run pytest -q tests/test_goal_binding_ab.py tests/test_goal_binding_provider.py tests/test_goal_binding_native_adapters.py tests/test_simple_native_provider_smoke.py tests/test_simple_native_provider_evidence.py
git diff --check
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add app/learn/hybrid/goal_binding_ab.py tests/test_goal_binding_ab.py
git commit -m "feat(benchmark): add frozen-snapshot binder arm runner"
```

---

### Task 5: Separate binder scorer, hard gate, and matrix report

**Files:**
- Create: `app/learn/hybrid/goal_binding_ab_score.py`
- Create: `tests/test_goal_binding_ab_score.py`

**Interfaces:**

```python
def score_goal_binding_arm(*, provider_artifact: Path, gold_path: Path) -> dict[str, object]: ...
def evaluate_binding_hard_gate(*, binder_report: Mapping[str, object], cleanup_receipt: Mapping[str, object]) -> dict[str, object]: ...
def build_goal_binding_matrix(*, arm_reports: Sequence[Mapping[str, object]]) -> dict[str, object]: ...
```

The provider runner never receives `gold_path`. The scorer joins finalized outcomes to regression Gold by screen and goal semantics, and uses the frozen acceptable-candidate-or-point-in-acceptable-region rule. Presentation score is computed only for hard-gate passers.

- [ ] **Step 1: Write RED scoring tests**

```python
def test_binder_scorer_reads_gold_only_after_artifact_is_finalized(): ...
def test_binder_score_counts_correct_wrong_unbound_and_provider_failure_over_25(): ...
def test_correctness_matches_frozen_acceptable_candidate_or_region_rule(): ...
def test_hard_gate_requires_zero_wrong_25_parse_10_correct_and_zero_residue(): ...
def test_numeric_score_never_promotes_failed_safety_gate(): ...
def test_presentation_weights_total_100_for_passers_only(): ...
def test_matrix_rejects_mixed_snapshot_or_capture_lineage(): ...
def test_matrix_is_regression_only_non_authorizing_and_no_holdout(): ...
```

- [ ] **Step 2: Run RED**

```powershell
uv run pytest -q tests/test_goal_binding_ab_score.py
```

Expected: collection fails because `goal_binding_ab_score` is absent.

- [ ] **Step 3: Implement scorer and gates**

Copy no mutable state from the existing scorer. Validate finalized artifact SHA first; read only regression Gold records; report numerator and denominator for every metric. Use weights `40/25/10/10/5/5/5` exactly. Emit `winner_arm_id=None` if no arm passes.

- [ ] **Step 4: Run GREEN and prove existing scorer unchanged**

```powershell
uv run pytest -q tests/test_goal_binding_ab_score.py tests/test_portfolio_hybrid_v1_1_benchmark.py tests/test_simple_native_provider_evidence.py
git diff --exit-code -- app/learn/hybrid/benchmark_scorer_v1.py app/learn/hybrid/benchmark_scorer_v2.py tests/fixtures/portfolio_hybrid_v1_1/gold.v1.json tests/fixtures/portfolio_hybrid_v1_1/provider-corpus.v2.json
git diff --check
```

Expected: all tests pass; protected files have no diff.

- [ ] **Step 5: Commit**

```powershell
git add app/learn/hybrid/goal_binding_ab_score.py tests/test_goal_binding_ab_score.py
git commit -m "feat(benchmark): score binder arms with safety gates"
```

---

### Task 6: 30 GiB model-test storage and safe deletion

**Files:**
- Create: `app/learn/hybrid/model_test_storage.py`
- Create: `scripts/fetch_goal_binding_model.py`
- Create: `tests/test_model_test_storage.py`

**Interfaces:**

```python
MODEL_TEST_ROOT = Path(r"E:\模型测试")
MODEL_TEST_MAX_BYTES = 32_212_254_720

def inventory_storage(root: Path = MODEL_TEST_ROOT) -> dict[str, object]: ...
def assert_download_fits(*, root: Path, remote_bytes: int) -> None: ...
def register_downloaded_artifact(*, root: Path, provider_id: str, repo_id: str, revision: str, files: Sequence[Path]) -> Path: ...
def delete_registered_artifact(*, root: Path, manifest_path: Path) -> dict[str, object]: ...
```

`fetch_goal_binding_model.py` resolves a Hugging Face branch/tag to an immutable commit, obtains sibling/LFS sizes before download, applies a 5% staging margin, downloads only profile-declared files, hashes every file, and writes a local manifest. The manifest and report remain after weight deletion.

- [ ] **Step 1: Write RED storage tests**

```python
def test_inventory_counts_all_logical_bytes_under_root(): ...
def test_projected_download_over_30_gib_is_rejected_before_write(): ...
def test_download_manifest_requires_immutable_revision_size_and_sha(): ...
def test_safe_delete_rejects_root_outside_symlink_reparse_and_unregistered_path(): ...
def test_safe_delete_removes_only_registered_weights_and_keeps_report_manifest(): ...
def test_failed_staging_cleanup_obeys_the_same_root_guard(): ...
def test_no_storage_operation_touches_incumbent_d_drive_paths(): ...
def test_chinese_storage_root_round_trips_as_utf8(): ...
```

- [ ] **Step 2: Run RED**

```powershell
uv run pytest -q tests/test_model_test_storage.py
```

Expected: collection fails because the storage module is absent.

- [ ] **Step 3: Implement storage inventory, gate, fetch, and deletion**

Use `Path.resolve(strict=True)` for deletion, `os.path.commonpath` for containment, Windows file attributes to reject reparse points, and logical `stat().st_size` sums. Never construct a delete shell string. Download into provider/revision-specific staging and atomically rename only after hashes and expected bytes pass.

- [ ] **Step 4: Run GREEN and CLI no-write preflight**

```powershell
uv run pytest -q tests/test_model_test_storage.py
uv run python scripts/fetch_goal_binding_model.py --help
uv run python scripts/fetch_goal_binding_model.py --inventory-only --root "E:\模型测试"
git diff --check
```

Expected: tests pass; inventory command creates no model files and reports bytes under the exact cap.

- [ ] **Step 5: Commit**

```powershell
git add app/learn/hybrid/model_test_storage.py scripts/fetch_goal_binding_model.py tests/test_model_test_storage.py
git commit -m "feat(models): enforce bounded test artifact storage"
```

---

### Task 7: Profiles and lazy provider-specific actual callers

**Files:**
- Create: `app/learn/hybrid/goal_binding_model_callers.py`
- Create: `scripts/model_servers/goal_binding_transformers_worker.py`
- Create: `tests/test_goal_binding_model_callers.py`
- Create: `configs/model_profiles/goal_binding_qwen_incumbent.json`
- Create: `configs/model_profiles/goal_binding_ui_venus_1_5_2b_f16.json`
- Modify: `configs/model_profiles/learn_mode_gui_actor_3b.json`
- Create: `configs/model_profiles/goal_binding_phi_ground_any_bf16.json`
- Create: `configs/model_profiles/goal_binding_ui_venus_2_9b_q6_k.json`
- Create: `configs/model_profiles/goal_binding_groundnext_7b_q6_k.json`
- Create: `configs/model_profiles/goal_binding_ui_venus_1_5_8b_q6_k.json`

**Interfaces:**

```python
def load_goal_binding_profile(path: Path) -> dict[str, object]: ...
def make_goal_binding_arm(*, profile: Mapping[str, object], artifact_dir: Path) -> GoalBindingArm: ...
def probe_goal_binding_profile(*, profile: Mapping[str, object], image_path: Path) -> dict[str, object]: ...
```

Profiles declare repo ID, immutable revision after acquisition, artifact paths, hashes, runtime kind, dtype/quantization, native output kind, coordinate space, preprocessing identity, max output, timeout, license, and `artifact_is_authorization=false`. Correct GUI-Actor model ID to `microsoft/GUI-Actor-3B-Qwen2.5-VL`.

- [ ] **Step 1: Write RED profile/caller tests**

```python
def test_import_and_profile_load_never_start_or_download_a_model(): ...
def test_profiles_are_closed_non_authorizing_and_use_exact_model_ids(): ...
def test_ui_venus_and_phi_workers_return_only_native_output_trace(): ...
def test_gui_actor_caller_preserves_topk_raw_but_selects_top1_only(): ...
def test_gguf_profile_requires_model_mmproj_and_runtime_hashes(): ...
def test_each_caller_binds_exact_pid_create_time_and_cleanup_receipt(): ...
def test_unknown_residue_or_gpu_owner_blocks_next_provider(): ...
def test_probe_uses_no_gold_holdout_or_candidate_mapping(): ...
```

- [ ] **Step 2: Run RED**

```powershell
uv run pytest -q tests/test_goal_binding_model_callers.py
```

Expected: collection fails because actual caller APIs are absent or profiles are incomplete.

- [ ] **Step 3: Implement lazy callers and bounded worker**

Reuse current model lease/process cleanup primitives instead of adding a supervisor. Load exactly one profile/model; one screenshot and short goal per request; bounded output; no generic JSON response requirement. The worker exposes raw provider-native result and resource metrics only. Keep official preprocessing isolated per profile and seal its source/hash before scoring.

- [ ] **Step 4: Run GREEN without starting models**

```powershell
uv run pytest -q tests/test_goal_binding_model_callers.py tests/test_simple_native_provider_callers.py tests/test_model_server_registry.py
uv run python scripts/model_servers/goal_binding_transformers_worker.py --help
git diff --check
```

Expected: tests and help pass; no model process/listener/GPU lease is created.

- [ ] **Step 5: Commit**

```powershell
git add app/learn/hybrid/goal_binding_model_callers.py scripts/model_servers/goal_binding_transformers_worker.py tests/test_goal_binding_model_callers.py configs/model_profiles/goal_binding_qwen_incumbent.json configs/model_profiles/goal_binding_ui_venus_1_5_2b_f16.json configs/model_profiles/learn_mode_gui_actor_3b.json configs/model_profiles/goal_binding_phi_ground_any_bf16.json configs/model_profiles/goal_binding_ui_venus_2_9b_q6_k.json configs/model_profiles/goal_binding_groundnext_7b_q6_k.json configs/model_profiles/goal_binding_ui_venus_1_5_8b_q6_k.json
git commit -m "feat(models): add replaceable goal binding profiles"
```

---

### Task 8: Staged matrix CLI and frozen config

**Files:**
- Create: `scripts/run_goal_binding_provider_ab.py`
- Create: `configs/benchmarks/goal_binding_provider_ab_v1.json`
- Create: `tests/test_goal_binding_provider_ab_cli.py`

**CLI:**

```text
--mode {preflight,snapshot,arm,matrix,score,cleanup}
--config PATH
--artifact-root PATH
--storage-root PATH                    default E:\模型测试
--arm-id ID                            required for arm
--operator-approved-model-start        required for snapshot/arm/matrix
```

`matrix` runs incumbent then Stage 1 sequentially and enters Stage 2 only when no Stage 1 hard-gate passer exists. Default mode is `preflight`; imports and preflight never start/download a model.

- [ ] **Step 1: Write RED CLI/config tests**

```python
def test_cli_defaults_to_preflight_and_constructs_no_model_callers(): ...
def test_config_contains_exact_five_screens_25_targets_and_no_holdout(): ...
def test_config_freezes_incumbent_stage1_and_conditional_stage2_order(): ...
def test_snapshot_arm_and_matrix_require_explicit_model_start_flag(): ...
def test_all_arms_are_forced_to_one_snapshot_sha(): ...
def test_stage2_is_skipped_when_any_stage1_arm_passes(): ...
def test_stage2_order_uses_venus_1_5_8b_only_after_venus_2_incompatibility(): ...
def test_cleanup_failure_and_storage_overage_block_next_arm(): ...
def test_score_mode_never_constructs_model_or_omni_callers(): ...
def test_cli_cannot_address_holdout_or_action_execution(): ...
```

- [ ] **Step 2: Run RED**

```powershell
uv run pytest -q tests/test_goal_binding_provider_ab_cli.py
```

Expected: collection/help fails because CLI and config are absent.

- [ ] **Step 3: Implement CLI and frozen experiment config**

Reuse `_cases` and `preflight` from `run_simple_native_provider_smoke.py` where practical. Persist a stage journal before and after every provider transition. Require finalized arm report and verified cleanup before scoring/advancing. Always write `holdout_accessed=false`, and error if any resolved input path contains a holdout component.

- [ ] **Step 4: Run GREEN and protected-file diff checks**

```powershell
uv run pytest -q tests/test_goal_binding_provider_ab_cli.py tests/test_goal_binding_ab.py tests/test_goal_binding_ab_score.py tests/test_model_test_storage.py tests/test_goal_binding_model_callers.py
uv run python scripts/run_goal_binding_provider_ab.py --help
uv run python scripts/run_goal_binding_provider_ab.py --mode preflight --config configs/benchmarks/goal_binding_provider_ab_v1.json --artifact-root .artifacts/goal-binding-ab
git diff --exit-code -- app/learn/hybrid/benchmark_scorer_v1.py app/learn/hybrid/benchmark_scorer_v2.py tests/fixtures/portfolio_hybrid_v1_1/gold.v1.json tests/fixtures/portfolio_hybrid_v1_1/provider-corpus.v2.json
git diff --check
```

Expected: tests/preflight pass, no model starts, protected files are unchanged.

- [ ] **Step 5: Commit**

```powershell
git add scripts/run_goal_binding_provider_ab.py configs/benchmarks/goal_binding_provider_ab_v1.json tests/test_goal_binding_provider_ab_cli.py
git commit -m "feat(benchmark): orchestrate staged binder model matrix"
```

---

### Task 9: Documentation sync and implementation review gate

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`
- Modify: `docs/LEARN_RECOGNITION_PARSER_AND_GROUNDING.zh-CN.md`
- Test: `tests/test_project_documentation.py`

- [ ] **Step 1: Add/adjust documentation assertions**

Assert docs describe `provider-native output → thin adapter → GoalBindingProvider`, frozen Omni snapshot, VISTA unchanged, regression-only evidence, 30 GiB external storage, and no holdout. They must not claim a winner before actual results exist.

- [ ] **Step 2: Update only affected documentation**

Mark implementation as available but actual comparative results pending. State that perception models are replaceable and non-authorizing; reviewed workflow/runtime remains the product core.

- [ ] **Step 3: Run focused and full implementation verification**

```powershell
uv run pytest -q tests/test_goal_binding_provider.py tests/test_goal_binding_native_adapters.py tests/test_omni_snapshot.py tests/test_goal_binding_ab.py tests/test_goal_binding_ab_score.py tests/test_model_test_storage.py tests/test_goal_binding_model_callers.py tests/test_goal_binding_provider_ab_cli.py tests/test_simple_native_provider_contracts.py tests/test_simple_native_provider_smoke.py tests/test_simple_native_provider_callers.py tests/test_simple_native_provider_evidence.py tests/test_project_documentation.py
uv run python scripts/run_goal_binding_provider_ab.py --mode preflight --config configs/benchmarks/goal_binding_provider_ab_v1.json --artifact-root .artifacts/goal-binding-ab
git diff --check
```

Expected: all selected tests and preflight pass; no model process starts.

- [ ] **Step 4: Independent code review**

Ask a high-reasoning reviewer to inspect spec compliance, model-start guards, Gold/holdout isolation, point mapping, top-1-only rule, storage deletion containment, lifecycle cleanup, and protected-file diffs. Fix only evidence-backed in-scope findings, rerun affected focused tests, then rerun Step 3.

- [ ] **Step 5: Commit**

```powershell
git add README.md README.zh-CN.md ARCHITECTURE.md CURRENT_STATE.md NEXT_STEPS.md docs/LEARN_RECOGNITION_PARSER_AND_GROUNDING.zh-CN.md tests/test_project_documentation.py
git commit -m "docs(benchmark): document replaceable binder experiment"
```

---

### Task 10: Acquire and verify Stage 1 model artifacts

**Files:**
- Generated outside Git: `E:\模型测试\models\<provider_id>\<revision>\...`
- Generated outside Git: `E:\模型测试\reports\artifact-manifests\<provider_id>.json`
- Modify after verified acquisition: corresponding `configs/model_profiles/goal_binding_*.json`

- [ ] **Step 1: Record initial storage/lifecycle baseline**

```powershell
uv run python scripts/fetch_goal_binding_model.py --inventory-only --root "E:\模型测试"
uv run python scripts/run_goal_binding_provider_ab.py --mode preflight --config configs/benchmarks/goal_binding_provider_ab_v1.json --artifact-root "E:\模型测试\runs\goal-binding-ab"
```

Expected: total logical bytes ≤ `32,212,254,720`; model/provider/window/listener/lease residue is zero; no holdout path appears.

- [ ] **Step 2: Acquire one Stage 1 model at a time**

Run the fetcher for these exact provider IDs/repositories in order:

```powershell
uv run python scripts/fetch_goal_binding_model.py --root "E:\模型测试" --provider-id ui_venus_1_5_2b_f16 --repo-id inclusionAI/UI-Venus-1.5-2B --full-checkpoint
uv run python scripts/fetch_goal_binding_model.py --root "E:\模型测试" --provider-id gui_actor_3b_bf16 --repo-id microsoft/GUI-Actor-3B-Qwen2.5-VL --full-checkpoint
uv run python scripts/fetch_goal_binding_model.py --root "E:\模型测试" --provider-id phi_ground_any_bf16 --repo-id microsoft/Phi-Ground-Any --full-checkpoint
```

Before each command the fetcher must resolve remote bytes and refuse if current bytes + download + margin exceed the cap. If keeping all three simultaneously would exceed the cap, finish, score, and safely delete a rejected earlier model before acquiring the next; never bypass the gate.

- [ ] **Step 3: Update profiles from verified local manifests**

Copy only immutable revision, relative artifact path, file size/SHA list, license reference, and verified runtime/preprocessing identity from the generated manifests into the matching profiles. Do not commit weights, caches, raw secrets, or machine-specific absolute paths other than the explicit configurable storage root contract.

- [ ] **Step 4: Run no-Gold native probes and profile tests**

```powershell
uv run pytest -q tests/test_model_test_storage.py tests/test_goal_binding_model_callers.py tests/test_goal_binding_provider_ab_cli.py
uv run python scripts/run_goal_binding_provider_ab.py --mode preflight --config configs/benchmarks/goal_binding_provider_ab_v1.json --artifact-root "E:\模型测试\runs\goal-binding-ab"
git diff --check
```

Expected: every acquired artifact hash/profile passes; failures are recorded as runtime-incompatible/OOM/dependency failure without prompt or contract changes.

- [ ] **Step 5: Commit only verified profile identities**

```powershell
git add configs/model_profiles/goal_binding_ui_venus_1_5_2b_f16.json configs/model_profiles/learn_mode_gui_actor_3b.json configs/model_profiles/goal_binding_phi_ground_any_bf16.json configs/benchmarks/goal_binding_provider_ab_v1.json
git commit -m "chore(models): pin stage one binder artifacts"
```

---

### Task 11: Freeze Omni and run incumbent plus Stage 1 actual regression

**Files:**
- Generated outside Git: `E:\模型测试\runs\goal-binding-ab\omni-snapshot-v1\...`
- Generated outside Git: `E:\模型测试\runs\goal-binding-ab\arms\...`
- Generated outside Git: `E:\模型测试\reports\goal-binding-stage1-matrix.json`

- [ ] **Step 1: Run actual preflight immediately before model start**

```powershell
uv run python scripts/run_goal_binding_provider_ab.py --mode preflight --config configs/benchmarks/goal_binding_provider_ab_v1.json --artifact-root "E:\模型测试\runs\goal-binding-ab"
```

Expected: screenshots/config/profiles/storage pass; model/provider/listener/lease/GPU-owner residue is zero.

- [ ] **Step 2: Create and independently verify one Omni snapshot**

```powershell
uv run python scripts/run_goal_binding_provider_ab.py --mode snapshot --operator-approved-model-start --config configs/benchmarks/goal_binding_provider_ab_v1.json --artifact-root "E:\模型测试\runs\goal-binding-ab"
uv run python scripts/run_goal_binding_provider_ab.py --mode preflight --config configs/benchmarks/goal_binding_provider_ab_v1.json --artifact-root "E:\模型测试\runs\goal-binding-ab"
```

Expected: five candidate files and one sealed manifest exist; Omni is absent; snapshot verification passes; no arm has run.

- [ ] **Step 3: Run incumbent and Stage 1 in frozen order**

```powershell
uv run python scripts/run_goal_binding_provider_ab.py --mode matrix --operator-approved-model-start --config configs/benchmarks/goal_binding_provider_ab_v1.json --artifact-root "E:\模型测试\runs\goal-binding-ab"
```

Expected: incumbent, UI-Venus-1.5-2B, GUI-Actor-3B, and Phi-Ground-Any each consume the exact snapshot SHA; every provider cleans before the next starts; exactly 25 outcomes per completed arm; no holdout access.

- [ ] **Step 4: Score and independently review Stage 1 evidence**

```powershell
uv run python scripts/run_goal_binding_provider_ab.py --mode score --config configs/benchmarks/goal_binding_provider_ab_v1.json --artifact-root "E:\模型测试\runs\goal-binding-ab"
uv run pytest -q tests/test_goal_binding_ab_score.py tests/test_goal_binding_provider_ab_cli.py
```

Expected: report includes native parse, correct/wrong/abstain, Omni recall if available, VISTA dispatch/validated/out-of-bounds, end-to-end correct/wrong/abstain, latency, peak VRAM, cleanup, and hard-gate result.

- [ ] **Step 5: Stop or enter Stage 2 by frozen condition**

If any Stage 1 challenger passes all hard gates, do not download/run Stage 2. Choose the highest passer-only presentation score, safely delete rejected challenger weights after verified cleanup, inventory E again, and proceed to Task 13. If none passes, proceed to Task 12 without changing prompt, adapters, thresholds, scorer, Gold, or candidate mapping.

---

### Task 12: Conditional Stage 2 quantized fallbacks

**Files:**
- Generated outside Git: Stage 2 models/manifests/runs under `E:\模型测试`
- Modify after verified acquisition: Stage 2 profile/config identity fields only

- [ ] **Step 1: Acquire UI-Venus-2-9B Q6_K + mmproj under the same gate**

Use the profile-pinned community repository and exact file allow-list through `fetch_goal_binding_model.py`; the fetcher must first record the immutable revision, Q6_K model SHA, mmproj SHA, remote bytes, and compatible llama.cpp build requirement. Do not reuse unverified b8892 if the profile requires newer Qwen3.5 support.

- [ ] **Step 2: Probe and run UI-Venus-2 once**

Run no-Gold load/native-output probe, verify cleanup, then run the 25-target arm against the same snapshot SHA. OOM, incompatible runtime, or invalid native output is recorded as the arm result; do not change its quantization or prompt mid-arm.

- [ ] **Step 3: Acquire/probe/run GroundNext-7B-V0 Q6_K + Q8 mmproj**

Apply the identical storage, revision, hash, native probe, 25-target, and cleanup requirements. Delete the prior rejected Stage 2 weight first if required by the 30 GiB gate.

- [ ] **Step 4: Use UI-Venus-1.5-8B fallback only for UI-Venus-2 runtime incompatibility**

Acquire Q6_K + Q8 mmproj and run it only when the finalized UI-Venus-2 arm status is specifically `runtime_incompatible`. Do not use it merely because UI-Venus-2 accuracy is low.

- [ ] **Step 5: Score, choose, and clean**

Generate the full matrix; select only among hard-gate passers; retain only final winner weights; delete all rejected test weights with receipts; rerun storage inventory and lifecycle residue checks. Commit only newly pinned profile/config identities:

```powershell
git add configs/model_profiles/goal_binding_ui_venus_2_9b_q6_k.json configs/model_profiles/goal_binding_groundnext_7b_q6_k.json configs/model_profiles/goal_binding_ui_venus_1_5_8b_q6_k.json configs/benchmarks/goal_binding_provider_ab_v1.json
git commit -m "chore(models): pin conditional binder fallbacks"
```

---

### Task 13: Final evidence, documentation truth, and STOP

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `CURRENT_STATE.md`
- Modify: `NEXT_STEPS.md`
- Generated outside Git: `E:\模型测试\reports\goal-binding-provider-ab-final.json`

- [ ] **Step 1: Verify final evidence and cleanup**

```powershell
uv run python scripts/run_goal_binding_provider_ab.py --mode score --config configs/benchmarks/goal_binding_provider_ab_v1.json --artifact-root "E:\模型测试\runs\goal-binding-ab"
uv run python scripts/run_goal_binding_provider_ab.py --mode cleanup --config configs/benchmarks/goal_binding_provider_ab_v1.json --artifact-root "E:\模型测试\runs\goal-binding-ab"
uv run python scripts/fetch_goal_binding_model.py --inventory-only --root "E:\模型测试"
```

Expected: final report hashes validate; one winner or explicit no-winner decision; E ≤ 30 GiB; rejected weights absent; process/listener/lease/GPU-owner residue zero; `holdout_accessed=false`.

- [ ] **Step 2: Update documentation from measured truth only**

Record exact numerators/denominators and identify results as 5-screen regression evidence, not general model quality or promotion proof. Do not claim production readiness. If there is no passer, retain incumbent and state that the common adapter worked but no replacement met safety/quality gates.

- [ ] **Step 3: Run final verification**

```powershell
uv run pytest -q tests/test_goal_binding_provider.py tests/test_goal_binding_native_adapters.py tests/test_omni_snapshot.py tests/test_goal_binding_ab.py tests/test_goal_binding_ab_score.py tests/test_model_test_storage.py tests/test_goal_binding_model_callers.py tests/test_goal_binding_provider_ab_cli.py tests/test_simple_native_provider_contracts.py tests/test_simple_native_provider_smoke.py tests/test_simple_native_provider_callers.py tests/test_simple_native_provider_evidence.py tests/test_project_documentation.py
uv run python scripts/run_goal_binding_provider_ab.py --mode preflight --config configs/benchmarks/goal_binding_provider_ab_v1.json --artifact-root "E:\模型测试\runs\goal-binding-ab"
git diff --exit-code -- app/learn/hybrid/benchmark_scorer_v1.py app/learn/hybrid/benchmark_scorer_v2.py tests/fixtures/portfolio_hybrid_v1_1/gold.v1.json tests/fixtures/portfolio_hybrid_v1_1/provider-corpus.v2.json
git diff --check
```

Expected: all tests/preflight pass; protected files remain byte-unchanged.

- [ ] **Step 4: Independent final review**

High-reasoning reviewer checks every design predicate, snapshot equality, native parser behavior, top-1-only evidence, 25-outcome arithmetic, Gold/holdout isolation, storage/deletion receipts, process cleanup, docs claims, commits, and no-push status. Fix only in-scope verified findings and rerun Step 3.

- [ ] **Step 5: Commit final truth**

```powershell
git add README.md README.zh-CN.md CURRENT_STATE.md NEXT_STEPS.md
git commit -m "docs(benchmark): publish binder regression findings"
```

Then STOP. Do not run unique holdout, do not push, and report all commit hashes/messages, tests, model artifact identities, storage before/after bytes, deleted weights, per-arm binder/end-to-end metrics, winner/none decision, limitations, and cleanup proof.
