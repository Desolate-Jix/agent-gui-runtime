# Simple Native Provider Smoke Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a regression-only, five-screen diagnostic that uses independent model-native schemas for OmniParser, Qwen, and VISTA while preserving all existing runtime and Learning safety contracts.

**Architecture:** Keep the three model-facing protocols independent. Parse them with pure functions, attach runtime-owned fields in thin adapters, and inject three replaceable caller slots into one offline-first runner. Preserve Qwen's full runtime request and project only the model-facing payload; keep Omni runtime enrichment outside the native schema; call VISTA with a bare normalized pair protocol and no generic JSON system prompt. Do not create a unified provider base class or envelope in Phase A.

**Tech Stack:** Python 3.11, `pytest`, `pydantic`/existing repository validators, `urllib`/existing local model transport, JSON/JSONL artifacts.

**Spec:** `docs/superpowers/specs/2026-09-03-simple-native-provider-smoke-design.md`

## Global Constraints

- Phase A follows A1 → A2 → A3 → A4 → A5 in order.
- Only `tests/fixtures/portfolio_hybrid_v1_1/corpus/regression/case-001.png` through `case-005.png` are in scope; no holdout access.
- Do not modify Benchmark v2, existing Gold files, holdout fixtures, or Learning schemas.
- Gold remains scorer-private. Provider code may read only `provider-corpus.v2.json` and generated provider artifacts.
- Importing modules and default CLI execution must not load weights, start services, reserve GPU, or call a real model.
- Actual model execution requires a current, explicit user approval plus the CLI actual-mode guard.
- No click or action execution is part of this diagnostic.
- Every source/comment/fixture containing Chinese remains UTF-8; JSON writes use `ensure_ascii=False`.
- After each slice, inspect `git diff`, run the stated narrow GREEN checks, run `git diff --check`, and commit only that slice.

---

### Task A1: Add pure model-native contracts and adapters

**Files:**
- Create: `app/learn/hybrid/simple_native_contracts.py`
- Create: `tests/test_simple_native_provider_contracts.py`
- Modify: `app/core/model_server.py`

**Interfaces:**

```python
def parse_omni_native_output(raw: object) -> tuple[OmniNativeItem, ...]: ...

def build_qwen_model_projection(
    runtime_request: Mapping[str, object],
) -> dict[str, object]: ...

def expand_qwen_model_response(
    raw: object,
    *,
    projection: Mapping[str, object],
    runtime_request: Mapping[str, object],
) -> dict[str, object]: ...

def parse_vista_normalized_point(raw_text: str) -> tuple[float, float]: ...

def restore_vista_point_to_capture(
    point: tuple[float, float],
    *,
    roi_xyxy: tuple[int, int, int, int],
) -> tuple[int, int]: ...
```

`OmniNativeItem` is a frozen dataclass with only `bbox`, `type`, `content`, and `interactivity`. `build_qwen_model_projection` must first rely on the existing full runtime request validation, emit only `image_size` and ordinal candidates `{i, box, active}`, and retain no mutable reference to the runtime request. `expand_qwen_model_response` requires exact ordinal coverage in original order, maps ordinals back to the existing candidate IDs, renames `status` to `binding_status`, and returns the existing `hybrid_qwen_bindings_v1` shape. `parse_vista_normalized_point` accepts only a bare two-number array in `[0,1000]`; it rejects dict, bbox, prose, NaN, infinity, extra values, and trailing non-whitespace.

In `app/core/model_server.py`, add `_qwen_model_projection_response_schema` beside `_qwen_binding_response_schema`. Do not replace the existing full runtime schema or `run_qwen_binding_model` in this slice.

- [ ] **Step 1: Write failing contract tests**

Add tests with these exact names:

- `test_omni_native_contract_accepts_only_official_minimal_fields`
- `test_omni_native_contract_rejects_invalid_normalized_boxes_and_extra_fields`
- `test_qwen_projection_keeps_full_runtime_request_unchanged`
- `test_qwen_projection_uses_short_ordinals_and_exact_geometry`
- `test_qwen_expansion_restores_stable_ids_and_existing_contract`
- `test_qwen_expansion_rejects_missing_duplicate_unknown_and_reordered_ordinals`
- `test_vista_contract_accepts_only_bare_normalized_pair`
- `test_vista_restore_rejects_outside_roi_without_clipping`
- `test_native_contracts_preserve_utf8_text`

- [ ] **Step 2: Run RED**

Run:

```powershell
uv run pytest -q tests/test_simple_native_provider_contracts.py
```

Expected: collection fails because `app.learn.hybrid.simple_native_contracts` does not exist.

- [ ] **Step 3: Implement the minimal pure contracts**

Implement exact-key validation, finite/range checks, deterministic ordinal mapping, immutable return values, UTF-8-safe values, and explicit `ValueError` messages. Reuse `parse_qwen_candidate_bindings` after expansion rather than copying its runtime validation. Restore a VISTA point with the existing ROI coordinate convention and reject any restored point that does not pass containment; do not clip or search for a nearby point.

- [ ] **Step 4: Run GREEN and existing boundary regressions**

Run:

```powershell
uv run pytest -q tests/test_simple_native_provider_contracts.py tests/test_learn_hybrid_qwen_binding.py tests/test_learn_hybrid_vista_refinement.py tests/test_uei_v1_omniparser_shadow_worker.py
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the slice**

```powershell
git add app/learn/hybrid/simple_native_contracts.py app/core/model_server.py tests/test_simple_native_provider_contracts.py
git commit -m "feat(learn): add simple native provider contracts"
```

---

### Task A2: Add an injectable offline runner and scorer boundary

**Files:**
- Create: `app/learn/hybrid/simple_native_smoke.py`
- Create: `tests/test_simple_native_provider_smoke.py`
- Create: `tests/fixtures/simple_native_provider_smoke/replay/omni.jsonl`
- Create: `tests/fixtures/simple_native_provider_smoke/replay/qwen.jsonl`
- Create: `tests/fixtures/simple_native_provider_smoke/replay/vista.jsonl`

**Interfaces:**

```python
@dataclass(frozen=True)
class SimpleNativeSlots:
    omni: OmniNativeCaller
    qwen: QwenNativeCaller
    vista: VistaNativeCaller

def run_simple_native_regression_diagnostic(
    *,
    cases: Sequence[ProviderCase],
    slots: SimpleNativeSlots,
    artifact_dir: Path,
) -> ProviderDiagnosticArtifact: ...

def score_simple_native_regression(
    *,
    provider_artifact: ProviderDiagnosticArtifact,
    gold_path: Path,
) -> RegressionDiagnosticReport: ...
```

The three caller protocols remain independent: Omni accepts one screenshot, Qwen accepts a screenshot plus Qwen projection, and VISTA accepts an ROI image plus target text. `SimpleNativeSlots` is only dependency injection; it is not a generic provider protocol. The runner must close and hash the provider artifact before the scorer receives `gold_path`.

- [ ] **Step 1: Write failing runner tests**

Add tests with these exact names:

- `test_offline_runner_processes_exactly_five_regression_screens_and_25_targets`
- `test_each_native_slot_can_be_replaced_independently`
- `test_provider_runner_never_receives_gold_or_scorer_private_fields`
- `test_qwen_runner_preserves_full_runtime_request_but_sends_projection`
- `test_vista_runs_only_for_uniquely_bound_grounding_eligible_targets`
- `test_runner_counts_schema_failures_and_abstentions_without_fallback`
- `test_report_contains_numerators_denominators_latency_and_raw_bytes`
- `test_report_is_regression_only_and_never_promotion_eligible`
- `test_runner_writes_raw_parsed_error_lineage_and_cleanup_receipt`

- [ ] **Step 2: Run RED**

Run:

```powershell
uv run pytest -q tests/test_simple_native_provider_smoke.py
```

Expected: collection fails because `app.learn.hybrid.simple_native_smoke` does not exist.

- [ ] **Step 3: Implement the offline-first runner**

Load only provider-visible case data before model calls. Use the existing Qwen runtime request builder and parser, existing Omni normalization boundary, and existing VISTA containment rules. Persist per-call prompt/input, raw response, parsed response or parse error, hashes, parent IDs, latency, output bytes, and abstention reason. Calculate the spec metrics with fixed denominators. Open the existing Gold only inside `score_simple_native_regression` after the provider artifact is finalized.

Replay callers must return the three native shapes without model lifecycle behavior. Do not add retry fallback; one malformed response is a recorded schema failure, and two consecutive malformed responses mark that slot stopped.

- [ ] **Step 4: Run GREEN and scorer-isolation regressions**

Run:

```powershell
uv run pytest -q tests/test_simple_native_provider_smoke.py tests/test_portfolio_hybrid_v1_1_benchmark.py -k "simple_native or scorer_private or promotion_eligible or existing_five_screen"
```

Expected: all selected tests pass; no holdout path is opened.

- [ ] **Step 5: Commit the slice**

```powershell
git add app/learn/hybrid/simple_native_smoke.py tests/test_simple_native_provider_smoke.py tests/fixtures/simple_native_provider_smoke/replay
git commit -m "feat(learn): add injectable native smoke runner"
```

---

### Task A3: Add the fixed five-screen CLI and config

**Files:**
- Create: `scripts/run_simple_native_provider_smoke.py`
- Create: `configs/benchmarks/simple_native_provider_smoke_v1.json`
- Create: `tests/test_simple_native_provider_smoke_cli.py`

**CLI:**

```text
--mode {preflight,replay,actual}   default: preflight
--config PATH                     default: configs/benchmarks/simple_native_provider_smoke_v1.json
--artifact-dir PATH               required for replay/actual
--replay-dir PATH                 required for replay
--operator-approved-model-start   required in addition to --mode actual
```

The config lists exactly five regression case IDs and paths, 25 target IDs, native contract versions, timeout/output limits, prompt hashes, provider profile IDs, and report metadata. It references the existing provider corpus and Gold paths but does not copy or modify their contents. The provider loader receives only the provider corpus path; the scorer receives Gold separately.

- [ ] **Step 1: Write failing CLI tests**

Add tests with these exact names:

- `test_cli_defaults_to_preflight_and_never_builds_actual_callers`
- `test_cli_replay_runs_only_the_five_regression_cases`
- `test_cli_actual_requires_explicit_model_start_flag`
- `test_cli_actual_flag_does_not_bypass_current_user_approval_policy`
- `test_config_contains_no_holdout_and_no_scorer_fields_in_provider_projection`
- `test_cli_rejects_changed_screenshot_and_prompt_hashes`

- [ ] **Step 2: Run RED**

Run:

```powershell
uv run pytest -q tests/test_simple_native_provider_smoke_cli.py
```

Expected: tests fail because the CLI and config do not exist.

- [ ] **Step 3: Implement preflight and replay modes**

Preflight validates exact case set, paths, SHA/size, prompt hashes, output directory policy, unknown model process policy, GPU exclusivity preconditions, and absence of holdout. Replay injects fixture callers and produces the diagnostic report. Keep actual caller construction behind a lazy import inside the guarded actual branch. `--operator-approved-model-start` is a technical double-check, not a substitute for obtaining user approval in the active task.

- [ ] **Step 4: Run GREEN and CLI help**

Run:

```powershell
uv run pytest -q tests/test_simple_native_provider_smoke_cli.py tests/test_simple_native_provider_smoke.py
uv run python scripts/run_simple_native_provider_smoke.py --help
uv run python scripts/run_simple_native_provider_smoke.py --mode preflight
```

Expected: tests pass; help exits 0; preflight exits 0 without importing model runtimes, starting processes, or reserving GPU.

- [ ] **Step 5: Commit the slice**

```powershell
git add scripts/run_simple_native_provider_smoke.py configs/benchmarks/simple_native_provider_smoke_v1.json tests/test_simple_native_provider_smoke_cli.py
git commit -m "feat(learn): add five-screen native smoke cli"
```

---

### Task A4: Wire actual callers behind the explicit guard

**Files:**
- Create: `app/learn/hybrid/simple_native_callers.py`
- Modify: `app/core/model_server.py`
- Modify: `scripts/run_uei_omniparser_shadow_worker.py`
- Modify: `scripts/run_simple_native_provider_smoke.py`
- Modify: `app/learn/hybrid/simple_native_smoke.py`
- Create: `tests/test_simple_native_provider_callers.py`
- Modify: `tests/test_simple_native_provider_smoke_cli.py`

**Interfaces:**

```python
def make_actual_simple_native_slots(
    *,
    config: SimpleNativeSmokeConfig,
    lifecycle: ModelLifecycle,
    transport: HTTPTransport,
) -> SimpleNativeSlots: ...

def call_qwen_projected_binding(
    *, image_path: Path, projection: Mapping[str, object], transport: HTTPTransport
) -> object: ...

def call_vista_bare_point(
    *, roi_path: Path, target_text: str, transport: HTTPTransport
) -> str: ...

def project_omni_official_items(items: Sequence[Mapping[str, object]]) -> dict[str, object]: ...
```

`call_qwen_projected_binding` sends the short projection while the runner retains and hashes the full runtime request. `call_vista_bare_point` sends no generic system message and no `response_format`; it returns raw text to the strict parser. `project_omni_official_items` emits only `{bbox,type,content,interactivity}` and lets the existing adapter attach runtime fields.

- [ ] **Step 1: Write failing transport/lifecycle tests**

Add tests with these exact names:

- `test_qwen_actual_caller_sends_projection_not_full_runtime_request`
- `test_qwen_actual_response_is_expanded_before_existing_parser`
- `test_vista_actual_caller_sends_no_generic_json_system_prompt_or_response_format`
- `test_vista_actual_caller_reads_bare_normalized_pair`
- `test_omni_worker_projects_only_native_fields_before_runtime_adapter`
- `test_actual_slots_are_lazy_and_default_cli_starts_no_models`
- `test_actual_lifecycle_is_exclusive_bounded_and_records_verified_cleanup`
- `test_cancellation_stops_owned_processes_and_never_kills_unknown_processes`

- [ ] **Step 2: Run RED**

Run:

```powershell
uv run pytest -q tests/test_simple_native_provider_callers.py tests/test_simple_native_provider_smoke_cli.py
```

Expected: collection fails because `simple_native_callers` and actual-slot factory are absent.

- [ ] **Step 3: Implement the guarded actual wiring**

Use injected fake transport and lifecycle in all tests. Add the Qwen projected response schema beside the existing schema without changing the full runtime contract. Extract Omni official-field projection before the existing normalization path. Implement a dedicated VISTA request builder rather than calling `LocalVisionProvider._call_openai_compatible_endpoint`. Lazy construction must occur only after preflight and both actual guards succeed.

Preserve bounded timeout, cancellation, PID ownership, GPU exclusivity, raw UTF-8 trace, output-size limit, and verified cleanup receipt. Do not implement a fallback to the legacy prompt when native parsing fails.

- [ ] **Step 4: Run GREEN without starting a model**

Run:

```powershell
uv run pytest -q tests/test_simple_native_provider_callers.py tests/test_simple_native_provider_smoke_cli.py tests/test_simple_native_provider_contracts.py
uv run python scripts/run_simple_native_provider_smoke.py --mode preflight
```

Expected: all tests pass with fake transport/lifecycle; preflight exits 0; process/GPU before-and-after snapshots are unchanged.

- [ ] **Step 5: Run safety regressions**

Run:

```powershell
uv run pytest -q tests/test_learn_hybrid_qwen_binding.py tests/test_learn_hybrid_vista_refinement.py tests/test_uei_v1_omniparser_shadow_worker.py tests/test_learn_recognition_actual_grounding_smoke.py
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the slice**

```powershell
git add app/learn/hybrid/simple_native_callers.py app/core/model_server.py scripts/run_uei_omniparser_shadow_worker.py scripts/run_simple_native_provider_smoke.py app/learn/hybrid/simple_native_smoke.py tests/test_simple_native_provider_callers.py tests/test_simple_native_provider_smoke_cli.py
git commit -m "feat(learn): wire opt-in native model callers"
```

Do not run `--mode actual` in this task. A later actual run starts only after current user approval and must stop under the design's stop criteria.

---

### Task A5: Synchronize behavior and architecture documentation

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/LEARN_RECOGNITION_PARSER_AND_GROUNDING.zh-CN.md`

- [ ] **Step 1: Write the documentation assertions**

Document: the three independent native shapes, Qwen full-runtime/projection split, runtime-attached fields, CLI default preflight behavior, explicit actual-model approval, 5-screen regression-only metrics, stop criteria, no Learning/Benchmark v2 schema change, and Phase B entry conditions.

- [ ] **Step 2: Verify documentation markers and UTF-8**

Run:

```powershell
uv run python -c "from pathlib import Path; files=[Path(x) for x in ['README.md','README.zh-CN.md','docs/LEARN_RECOGNITION_PARSER_AND_GROUNDING.zh-CN.md']]; [p.read_text(encoding='utf-8') for p in files]; required=['simple-native','preflight','regression']; assert all(any(token in p.read_text(encoding='utf-8').lower() for p in files) for token in required)"
git diff --check
```

Expected: UTF-8 reads and marker assertions succeed; `git diff --check` prints nothing.

- [ ] **Step 3: Run the complete Phase A offline verification**

Run:

```powershell
uv run pytest -q tests/test_simple_native_provider_contracts.py tests/test_simple_native_provider_smoke.py tests/test_simple_native_provider_smoke_cli.py tests/test_simple_native_provider_callers.py
uv run python scripts/run_simple_native_provider_smoke.py --mode preflight
uv run python scripts/run_simple_native_provider_smoke.py --mode replay --replay-dir tests/fixtures/simple_native_provider_smoke/replay --artifact-dir .artifacts/simple-native-provider-smoke-replay
```

Expected: tests pass; preflight starts no model; replay processes exactly 5 screens/25 targets, reads no holdout, performs zero actions, writes a non-promotable report and verified cleanup receipt.

- [ ] **Step 4: Inspect repository scope and secrets**

Run:

```powershell
git diff --check
git status --short
rg -n "sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|Bearer [A-Za-z0-9._-]{16,}|api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9]" app/learn/hybrid/simple_native_contracts.py app/learn/hybrid/simple_native_smoke.py app/learn/hybrid/simple_native_callers.py scripts/run_simple_native_provider_smoke.py configs/benchmarks/simple_native_provider_smoke_v1.json tests/test_simple_native_provider_contracts.py tests/test_simple_native_provider_smoke.py tests/test_simple_native_provider_smoke_cli.py tests/test_simple_native_provider_callers.py README.md README.zh-CN.md docs/LEARN_RECOGNITION_PARSER_AND_GROUNDING.zh-CN.md
```

Expected: only the planned Phase A files are modified; whitespace check is clean; secret scan returns no matches.

- [ ] **Step 5: Commit the slice**

```powershell
git add README.md README.zh-CN.md docs/LEARN_RECOGNITION_PARSER_AND_GROUNDING.zh-CN.md
git commit -m "docs(learn): document simple native provider smoke"
```

---

## Actual Five-screen Run Procedure and Stop Criteria

This section is an operator procedure, not an instruction to run actual models during implementation.

1. Obtain explicit user approval in the current task to start the three real models and run the five regression screens.
2. Record clean process/GPU ownership, frozen config hash, prompt hashes, screenshot hashes, and intended artifact directory.
3. Run exactly:

```powershell
uv run python scripts/run_simple_native_provider_smoke.py --mode actual --operator-approved-model-start --artifact-dir .artifacts/simple-native-provider-smoke-actual
```

4. Stop immediately on capture mismatch, Gold leakage, ambiguous process ownership, non-exclusive GPU state, lost UTF-8/raw lineage, invalid coordinate transform, attempted clipping/nearest correction, any action execution, or unverifiable cleanup.
5. Stop an individual slot after 2 consecutive schema-invalid responses. Record remaining dependent targets as abstentions; do not switch to the legacy prompt or heuristic fallback.
6. A completed report must cover exactly `case-001` through `case-005`, use the 25-target denominator, include all metrics from the spec, perform zero clicks, and set `regression_diagnostic_only=true` and `promotion_eligible=false`.

## Phase B Gate — No Implementation in This Plan

Do not create Simple Provider Protocol v1 code in Phase A. Open a separate spec only when all design entry conditions hold: one approved frozen actual run, stable real native traces for all slots, verified safety/lineage/cleanup, accuracy improvement or non-regression evidence, a factual second implementation or repeated seam that justifies extraction, and zero holdout use. The later abstraction may share lifecycle, trace, and registration primitives, but must retain separate Omni item, Qwen binding, and VISTA point payloads.
